"""The whole journey, once, with the real s0ma - milestone Q2 of ``beta-prep-2-claude``.

Every other test in this directory proves one thing about the launcher against
stand-ins: tiny wheels with no dependencies, a stub server, a fake spawner. This
file proves the thing those stand-ins stand in for. It builds the four **real**
s0ma wheels from this tree, publishes them on the fake control plane, and then
does exactly what a subscriber's machine does:

* **T1** ``install`` fetches, verifies and installs them; ``serve`` starts the
  real ``s0ma-mcp``; a real MCP handshake and ``tools/list`` go through the
  launcher's pipes; the tool names are the ones the surface snapshot pins.
* **T2** a newer version is published; ``serve`` leaves a detached update
  behind; the newer version arrives on its own; the next ``serve`` runs it and
  the older one is still there to go back to.
* **T3** a project pinned with ``.s0ma-version`` keeps running the version it
  asked for, and s0ma does not start an update behind its back.

**What this costs, and why it is not in the ordinary run.** Eight wheel builds,
five real ``uv`` environments and four real server starts. On a machine whose uv
cache already holds s0ma's dependencies that is about ten seconds; on a cold one
it is minutes, because every dependency is fetched. Either way it is not
something to pay on every run of the launcher's suite, so it happens only when
``S0MA_E2E=1`` is set - and ``scripts/smoke_claude_integration.sh`` is the way
the owner runs it by hand.

**What it does not touch.** The real ``~/.s0ma`` (every run gets a temporary
``S0MA_HOME``), the real control plane (the fake one, on a loopback port, is the
only host any of this contacts), the user's Claude configuration, and the
worktree itself - ``uv build`` is given an ``--out-dir`` outside it and the
version-bumped copy for T2 is assembled in a temporary directory.

**What it may contact.** ``uv`` resolving the real wheels' third-party
dependencies - lark, the MCP SDK and what that pulls in - from the public
package index. That is the one exception, and it is avoided when it can be: the
:func:`offline_uv` fixture proves first, with a dry run, whether every
dependency is already in uv's cache, and only then switches the network off for
the whole smoke with ``UV_OFFLINE``. Which of the two happened is printed, so
the person reading the output never has to guess.
(``S0MA_LAUNCH_OFFLINE_INSTALL`` - the launcher's own test-only seam - is
deliberately **not** used: it would make the launcher pass ``--offline`` to
``uv`` itself, and the point here is to exercise the install exactly as a
subscriber's machine runs it.)

**Windows.** Nothing here is skipped there, because nothing here needs a shell,
a symbolic link or a POSIX-only call: the paths are :mod:`pathlib`, the
subprocesses are ``sys.executable`` running the launcher, every text stream is
opened ``utf-8``, and where a version's programs live is asked of the launcher
(``bin_dir_of``, ``find_program``) rather than spelled ``bin/``. The two things
that behave differently there - ``serve`` spawning and waiting instead of
replacing the process, and the quiet update detaching with Windows creation
flags - are exactly what this file drives, so a Windows run is worth having;
the orchestrator's CI run is the proof. The POSIX-only half of Q2 is the smoke
*script*, which says so itself.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import zipfile
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from fake_control_plane import FakeControlPlane

# ---------------------------------------------------------------------------
# Where things are, and what "slow" means here.
# ---------------------------------------------------------------------------

#: This file -> tests -> launcher -> integrations -> the monorepo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER_FILE = REPO_ROOT / "integrations" / "launcher" / "s0ma_launch.py"
PACKAGES_DIR = REPO_ROOT / "packages"
SURFACE_SNAPSHOT = REPO_ROOT / "packages" / "s0ma-mcp" / "tests" / "snapshots" / "mcp_surface.json"

#: The four distributions a copy of s0ma is made of. The build asks for each by
#: name, so a fifth package would have to be named here on purpose.
DISTRIBUTIONS = ("s0ma-core", "s0ma-dsl", "s0ma-mcp", "s0ma-studi0")

#: The eight places the version is written (``scripts/check_version_refs.py``
#: calls them LOCKSTEP_SITES): one per package manifest and one per package
#: ``__init__``. They are found by shape rather than listed, so the count below
#: is what catches a layout that has moved.
LOCKSTEP_PYPROJECTS = 4
LOCKSTEP_MODULES = 4

#: An obviously fake key: the value ``conftest.FAKE_LICENSE_KEY`` holds, written
#: out here as ``test_activate.py`` writes it out, because a key in a test should
#: be readable as fake at the place it is used rather than one import away.
FAKE_KEY = "s0ma_test_not_a_real_key_wxyz"

#: Anything key-shaped, in anything a run leaves behind. Nothing may match.
KEY_SHAPED = re.compile(r"s0ma_(?:live|test)_[A-Za-z0-9_-]{4,}")

#: How long one launcher command may take. Generous: a cold install builds a
#: virtual environment and unpacks four real wheels into it.
COMMAND_TIMEOUT_SECONDS = 600.0

#: How long the MCP server has to answer one message. The real server imports
#: the SDK, the DSL and the transpiler on the way up.
MESSAGE_TIMEOUT_SECONDS = 120.0

#: How long T2 waits for the detached update to finish, polling ``state.json``.
#: Four minutes, as the milestone asks - it is a whole second install.
UPDATE_WAIT_SECONDS = 240.0
UPDATE_POLL_SECONDS = 0.5

#: A ``last_check`` far enough in the past that ``serve`` starts an update.
TWO_DAYS_SECONDS = 2 * 24 * 60 * 60

E2E_FLAG = "S0MA_E2E"

pytestmark = pytest.mark.skipif(
    os.environ.get(E2E_FLAG, "").strip() != "1",
    reason=(
        "the end-to-end smoke builds the real s0ma wheels and installs them for "
        "real - ten seconds with a warm uv cache, minutes without one: set "
        "S0MA_E2E=1 to run it, or run scripts/smoke_claude_integration.sh"
    ),
)


# ---------------------------------------------------------------------------
# Saying what happened. The smoke script runs this file with -s, so these lines
# are the record of how long each phase took and what was contacted.
# ---------------------------------------------------------------------------


def note(message: str) -> None:
    """One line of plain narration, flushed so an interrupted run still shows it."""
    print(f"[e2e] {message}", flush=True)


class Phase:
    """Time one phase and say how long it took."""

    def __init__(self, what: str) -> None:
        self.what = what
        self.seconds = 0.0

    def __enter__(self) -> Phase:
        note(f"{self.what}...")
        self._started = time.monotonic()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.seconds = time.monotonic() - self._started
        note(f"{self.what}: {self.seconds:.1f}s")


# ---------------------------------------------------------------------------
# Building the real wheels.
# ---------------------------------------------------------------------------


def tree_version(root: Path = REPO_ROOT) -> str:
    """The version this tree is at, read where the release reads it."""
    manifest = root / "packages" / "s0ma-core" / "pyproject.toml"
    return str(tomllib.loads(manifest.read_text(encoding="utf-8"))["project"]["version"])


def next_patch(version: str) -> str:
    """The next patch version after *version* - what T2 publishes as newer."""
    parts = version.split(".")
    if len(parts) < 3 or not parts[2].isdigit():  # pragma: no cover - a shape we do not ship
        raise AssertionError(f"{version!r} is not a plain X.Y.Z version")
    return ".".join([parts[0], parts[1], str(int(parts[2]) + 1)])


def build_wheels(source_root: Path, into: Path) -> list[Path]:
    """Build the four real wheels from *source_root* into *into*.

    The same call ``scripts/wheel_smoke.py`` makes: ``uv build --package <name>
    --wheel --out-dir <dir>``. The out-directory is always outside the worktree,
    so a build leaves nothing behind in it - which is the point of naming one.

    A wheel build resolves one thing only, the build backend (hatchling), which
    is in every cache that has ever built this tree. The dependencies that might
    genuinely need fetching - lark, the MCP SDK - are resolved by the *install*,
    and that is what :func:`offline_uv` governs.
    """
    into.mkdir(parents=True, exist_ok=True)
    for distribution in DISTRIBUTIONS:
        finished = subprocess.run(
            ["uv", "build", "--package", distribution, "--wheel", "--out-dir", str(into)],
            cwd=str(source_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
        assert finished.returncode == 0, (
            f"uv build refused to build {distribution}:\n{finished.stderr}"
        )
    built = sorted(into.glob("*.whl"))
    assert len(built) == len(DISTRIBUTIONS), f"expected four wheels, got {[p.name for p in built]}"
    return built


def copy_buildable_tree(into: Path) -> Path:
    """Copy just enough of this tree to build the four wheels from, and return it.

    Not the whole tree: the tests, the fixtures and the documentation together
    are ten times the size of what a wheel build reads, and copying them would
    make T2 slow for nothing. What hatchling actually needs is each package's
    manifest, its ``README.md`` and ``LICENSE`` (both are named in the manifest)
    and its ``src/`` tree; what ``uv build --package`` additionally needs is the
    workspace root's ``pyproject.toml``, so that the names resolve.

    Every wheel this produces is built by the same backend from the same bytes
    as one built in place - which is what T2 needs, because the thing under test
    is the version, not the contents.
    """
    into.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "pyproject.toml", into / "pyproject.toml")
    skip = shutil.ignore_patterns("__pycache__", "*.pyc", ".s0ma.cache")
    for package in sorted(PACKAGES_DIR.iterdir()):
        if not (package / "pyproject.toml").is_file():
            continue
        destination = into / "packages" / package.name
        destination.mkdir(parents=True, exist_ok=True)
        for name in ("pyproject.toml", "README.md", "LICENSE"):
            source = package / name
            if source.is_file():
                shutil.copy2(source, destination / name)
        shutil.copytree(package / "src", destination / "src", ignore=skip)
    return into


def bump_lockstep_sites(root: Path, old: str, new: str) -> list[Path]:
    """Rewrite every version site in *root* from *old* to *new*; return them.

    The eight sites are found by shape - the ``version = "..."`` line in each
    ``packages/*/pyproject.toml`` and the ``__version__ = "..."`` line in each
    package's ``__init__.py`` - rather than listed, so this cannot quietly miss
    a package. The counts below are the check: if the layout moves, this fails
    where a reader can see why, instead of building a wheel that is still V.
    """
    changed: list[Path] = []
    for manifest in sorted(root.glob("packages/*/pyproject.toml")):
        text = manifest.read_text(encoding="utf-8")
        bumped = text.replace(f'version = "{old}"', f'version = "{new}"', 1)
        assert bumped != text, f"{manifest} does not carry version {old}"
        manifest.write_text(bumped, encoding="utf-8", newline="\n")
        changed.append(manifest)
    assert len(changed) == LOCKSTEP_PYPROJECTS, [str(p) for p in changed]

    modules: list[Path] = []
    for init in sorted(root.glob("packages/*/src/*/__init__.py")):
        text = init.read_text(encoding="utf-8")
        bumped = text.replace(f'__version__ = "{old}"', f'__version__ = "{new}"', 1)
        if bumped == text:
            continue
        init.write_text(bumped, encoding="utf-8", newline="\n")
        modules.append(init)
    assert len(modules) == LOCKSTEP_MODULES, [str(p) for p in modules]
    return changed + modules


# ---------------------------------------------------------------------------
# Session fixtures: the expensive things, built once.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def version_v() -> str:
    """V: the version this tree is at."""
    return tree_version()


@pytest.fixture(scope="session")
def version_w(version_v: str) -> str:
    """W: one patch newer than V. Published on the fake plane, nowhere else."""
    return next_patch(version_v)


@pytest.fixture(scope="session")
def wheels_v(tmp_path_factory: pytest.TempPathFactory, version_v: str) -> Path:
    """The four real wheels of version V, built from this tree."""
    into = tmp_path_factory.mktemp("wheels-v")
    with Phase(f"building the four real wheels of s0ma {version_v} from this tree"):
        build_wheels(REPO_ROOT, into)
    return into


def wheel_members(wheel: Path, version: str) -> set[str]:
    """What is inside a wheel, with its version spelled out of the names.

    A ``.dist-info`` directory carries the version in its own name, so two
    wheels that differ only by version differ in every path under it. Replacing
    the version with a placeholder is what makes them comparable - which is the
    one thing :func:`copy_buildable_tree` has to get right.
    """
    with zipfile.ZipFile(wheel) as archive:
        return {name.replace(version, "<version>") for name in archive.namelist()}


@pytest.fixture(scope="session")
def wheels_w(
    tmp_path_factory: pytest.TempPathFactory, version_v: str, version_w: str, wheels_v: Path
) -> Path:
    """The four real wheels of version W, built from a version-bumped copy.

    The copy is partial (see :func:`copy_buildable_tree`), so the last thing
    this does is prove the copy was not *too* partial: every W wheel holds the
    same files as the V wheel of the same distribution. A payload left behind -
    the embedded documentation, the committed build output, the teaching slice -
    would show up here as a difference, rather than later as a server that will
    not start for a reason nobody can see.
    """
    work = tmp_path_factory.mktemp("wheels-w")
    with Phase(f"building the four real wheels of s0ma {version_w} from a bumped copy"):
        source = copy_buildable_tree(work / "tree")
        bump_lockstep_sites(source, version_v, version_w)
        into = work / "dist"
        built = build_wheels(source, into)

    for wheel in built:
        assert version_w in wheel.name, f"{wheel.name} is not a {version_w} wheel"
        original = wheels_v / wheel.name.replace(version_w, version_v)
        assert original.is_file(), f"there is no {version_v} wheel matching {wheel.name}"
        missing = wheel_members(original, version_v) - wheel_members(wheel, version_w)
        assert not missing, f"{wheel.name} is missing {sorted(missing)[:10]}"
    return into


@pytest.fixture(scope="session")
def offline_uv(tmp_path_factory: pytest.TempPathFactory, wheels_v: Path) -> bool:
    """Whether uv can install the real wheels without the network. Proved, not assumed.

    The real wheels have real dependencies - lark, the MCP SDK, and what that
    pulls in. If every one of them is already in uv's cache on this machine, the
    whole smoke runs with the network switched off, which is both quicker and a
    far stronger statement about what was contacted. If any is missing, uv is
    left free to fetch it from the public package index - the one thing here
    that ever leaves the machine - and the run says so out loud.

    The proof is a dry run: the same resolution the install will do, against the
    same wheels, with nothing written and the network off.
    """
    probe = tmp_path_factory.mktemp("uv-cache-probe")
    made = subprocess.run(
        ["uv", "venv", str(probe / "venv")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=False,
    )
    assert made.returncode == 0, f"uv could not make an environment to probe with:\n{made.stderr}"
    interpreter = probe / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    dry = subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(interpreter),
            "--dry-run",
            *[str(wheel) for wheel in sorted(wheels_v.glob("*.whl"))],
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ) | {"UV_OFFLINE": "1"},
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=False,
    )
    if dry.returncode == 0:
        note("every dependency is already in uv's cache: this smoke contacts no index at all")
        return True
    note(
        "some dependencies are not in uv's cache, so uv will fetch them from the "
        "public package index; nothing else leaves this machine"
    )
    return False


@pytest.fixture(scope="session")
def snapshot_tool_names() -> list[str]:
    """The tool names the MCP surface snapshot pins, sorted."""
    document = json.loads(SURFACE_SNAPSHOT.read_text(encoding="utf-8"))
    names = sorted(str(tool["name"]) for tool in document["tools"])
    assert names, "the surface snapshot lists no tools"
    return names


# ---------------------------------------------------------------------------
# Per-test fixtures: a fresh machine, a fresh project, a fresh control plane.
# ---------------------------------------------------------------------------


@pytest.fixture
def plane(tmp_path: Path, wheels_v: Path, version_v: str) -> Iterator[FakeControlPlane]:
    """A fake control plane on loopback, with the real wheels of V published."""
    running = FakeControlPlane(key=FAKE_KEY, work=tmp_path / "control-plane")
    running.publish_directory(version_v, wheels_v)
    running.start()
    try:
        yield running
    finally:
        running.stop()


@pytest.fixture
def smoke_home(tmp_path: Path) -> Path:
    """A throwaway ``S0MA_HOME``. The real one is never touched."""
    home = tmp_path / "s0ma-home"
    home.mkdir(parents=True, exist_ok=True)
    return home


@pytest.fixture
def smoke_project(tmp_path: Path) -> Path:
    """A throwaway project directory, with no toolchain of its own."""
    where = tmp_path / "smoke-project"
    where.mkdir(parents=True, exist_ok=True)
    return where


# ---------------------------------------------------------------------------
# Running the launcher the way a host does: as a whole program, over pipes.
# ---------------------------------------------------------------------------


def launcher_env(
    home: Path,
    project: Path,
    plane: FakeControlPlane,
    *,
    update: str,
    offline_uv: bool,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """The environment a launcher subprocess gets. Built up, never inherited.

    Every ``S0MA_*`` variable this machine happens to have is dropped and only
    the ones this test means are put back - including the launcher's own
    test-only offline seam, which must never be on here (see the module
    docstring). ``UV_OFFLINE`` is uv's own switch, not the launcher's: it says
    nothing about how the launcher installs, only where uv may look.
    """
    values = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("S0MA_") and name not in ("CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_DATA")
    }
    values["S0MA_HOME"] = str(home)
    values["CLAUDE_PROJECT_DIR"] = str(project)
    values["S0MA_CP_HOST"] = plane.host
    values["S0MA_LICENSE_KEY"] = plane.key
    values["S0MA_UPDATE"] = update
    if offline_uv:
        values["UV_OFFLINE"] = "1"
    if extra:
        values.update(extra)
    return values


def run_launcher(
    arguments: list[str], environment: dict[str, str], project: Path
) -> subprocess.CompletedProcess[str]:
    """Run one launcher command as a real subprocess and wait for it."""
    return subprocess.run(
        [sys.executable, str(LAUNCHER_FILE), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        cwd=str(project),
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=False,
    )


class ServeSession:
    """One ``serve`` subprocess, driven as an MCP client drives it.

    Newline-delimited JSON-RPC over the process's own pipes, one message at a
    time, with a reader thread so a server that says nothing cannot hang the
    test: every read is bounded. This is what ``test_stub_server.py`` does to
    the built-in stub, done to the real ``s0ma-mcp`` instead - and reaching it
    through ``serve`` is the point, because the thing being proved is that the
    launcher hands over to the real server correctly.
    """

    def __init__(self, environment: dict[str, str], project: Path) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(LAUNCHER_FILE), "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
            cwd=str(project),
            bufsize=1,
        )
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def receive(self, timeout: float = MESSAGE_TIMEOUT_SECONDS) -> dict[str, Any]:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:  # pragma: no cover - only a server that stopped answering
            raise AssertionError(
                f"the server said nothing for {timeout:.0f}s; its error output was:\n"
                f"{self.stop_and_read()[1]}"
            ) from None
        if line is None:
            raise AssertionError(
                "the server closed its output before answering; its error output was:\n"
                f"{self.stop_and_read()[1]}"
            )
        parsed: dict[str, Any] = json.loads(line)
        return parsed

    def handshake(self, protocol: str = "2025-06-18") -> dict[str, Any]:
        """``initialize`` then ``notifications/initialized``; return the result."""
        self.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": protocol,
                    "capabilities": {},
                    "clientInfo": {"name": "the s0ma end-to-end smoke", "version": "1.0.0"},
                },
            }
        )
        answer = self.receive()
        assert "error" not in answer, answer
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        result: dict[str, Any] = answer["result"]
        return result

    def list_tools(self) -> list[str]:
        """``tools/list``, as the names it returned, sorted."""
        self.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        answer = self.receive()
        assert "error" not in answer, answer
        return sorted(str(tool["name"]) for tool in answer["result"]["tools"])

    def close_stdin_and_wait(self) -> tuple[int, str]:
        """Close the conversation the way a host does; return the code and stderr."""
        assert self.process.stdin is not None
        self.process.stdin.close()
        code = self.process.wait(timeout=COMMAND_TIMEOUT_SECONDS)
        self._reader.join(timeout=10)
        return code, self.stderr_text()

    def stderr_text(self) -> str:
        assert self.process.stderr is not None
        try:
            return self.process.stderr.read() or ""
        except ValueError:  # pragma: no cover - already read and closed
            return ""

    def stop_and_read(self) -> tuple[int | None, str]:
        """Kill the run and hand back whatever it managed to say. For failures only."""
        self.process.kill()
        try:
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover
            pass
        return self.process.returncode, self.stderr_text()

    def __enter__(self) -> ServeSession:
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.process.poll() is None:  # pragma: no cover - only on a failed test
            self.stop_and_read()


# ---------------------------------------------------------------------------
# Reading what a run left behind.
# ---------------------------------------------------------------------------


def state_of(home: Path) -> dict[str, Any]:
    """``state.json``, read the way anything else reads it."""
    document: dict[str, Any] = json.loads(
        (home / "launcher" / "state.json").read_text(encoding="utf-8")
    )
    return document


def write_state(home: Path, state: dict[str, Any]) -> None:
    """Put ``state.json`` back. Used to age ``last_check`` past a day."""
    (home / "launcher" / "state.json").write_text(
        json.dumps(state, indent=2, sort_keys=True), encoding="utf-8", newline="\n"
    )


def update_log_path(home: Path) -> Path:
    return home / "launcher" / "update.log"


def recorded_text(home: Path) -> str:
    """Everything the launcher has written under the state directory, as text.

    The toolchain directories are left out on purpose: they hold installed
    packages, megabytes of them, and nothing the launcher wrote.
    """
    parts: list[str] = []
    for path in sorted(home.rglob("*")):
        if not path.is_file():
            continue
        if "toolchains" in path.relative_to(home).parts:
            continue
        if path.suffix not in ("", ".json", ".log", ".1"):
            continue
        parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def assert_key_never_escaped(home: Path, *outputs: str) -> None:
    """The one hygiene rule, checked everywhere it can be checked.

    The key is *deliberately* inherited by the server and by the quiet updater -
    both of them may need to ask the control plane for something - so what is
    asserted is what the plan asks for: it is in nothing the launcher printed
    and nothing it wrote down. ``state.json``, ``config.json`` and
    ``update.log`` are all under the state directory, so the sweep below covers
    all three at once.
    """
    for output in outputs:
        assert FAKE_KEY not in output, "the license key reached a launcher's output"
        assert not KEY_SHAPED.search(output), "something key-shaped reached a launcher's output"
    written = recorded_text(home)
    assert FAKE_KEY not in written, "the license key was written under S0MA_HOME"
    assert not KEY_SHAPED.search(written), "something key-shaped was written under S0MA_HOME"


def toolchain_of(launcher: ModuleType, home: Path, version: str) -> Path:
    """Where a version lives. Asked of the launcher, so the layout is its answer."""
    directory: Path = launcher.managed_toolchain_dir(home, version)
    return directory


def wait_for_installed(home: Path, version: str, *, seconds: float = UPDATE_WAIT_SECONDS) -> float:
    """Poll ``state.json`` until *version* is installed; return how long it took."""
    started = time.monotonic()
    deadline = started + seconds
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = state_of(home)
        except (OSError, json.JSONDecodeError):  # pragma: no cover - mid-write; try again
            time.sleep(UPDATE_POLL_SECONDS)
            continue
        if version in (last.get("installed") or []):
            return time.monotonic() - started
        time.sleep(UPDATE_POLL_SECONDS)
    log = update_log_path(home)
    said = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else "(no log)"
    raise AssertionError(
        f"s0ma {version} was still not installed after {seconds:.0f}s.\n"
        f"state.json: {json.dumps(last, indent=2, sort_keys=True)}\n"
        f"update.log: {said}"
    )


# ---------------------------------------------------------------------------
# T1 - install the real wheels, start the real server, complete a real handshake.
# ---------------------------------------------------------------------------


def test_t1_install_then_serve_the_real_mcp_server(
    launcher: ModuleType,
    plane: FakeControlPlane,
    smoke_home: Path,
    smoke_project: Path,
    version_v: str,
    snapshot_tool_names: list[str],
    offline_uv: bool,
) -> None:
    environment = launcher_env(
        smoke_home, smoke_project, plane, update="off", offline_uv=offline_uv
    )

    with Phase(f"installing the real s0ma {version_v} from the fake control plane"):
        installed = run_launcher(["install"], environment, smoke_project)
    assert installed.returncode == 0, installed.stderr

    # What the install left: one version, complete, with the real programs in it.
    state = state_of(smoke_home)
    assert state["installed"] == [version_v], state
    assert state["current"] == version_v, state
    assert state["entitlement"] == "ok", state
    assert state["last_error"] is None, state
    toolchain = toolchain_of(launcher, smoke_home, version_v)
    assert (toolchain / launcher.COMPLETE_MARKER).is_file()
    programs = launcher.bin_dir_of(toolchain)
    assert programs is not None, "the install left no programs behind"
    assert launcher.find_program(programs, launcher.MCP_PROGRAM) is not None
    assert launcher.find_program(programs, launcher.CLI_PROGRAM) is not None
    note(f"installed s0ma {version_v} into {toolchain.name} with the real wheels")

    # The key travelled in the Authorization header and nowhere else.
    assert plane.authorizations, "the plane was never asked for anything"
    assert set(plane.authorizations) == {"Bearer " + FAKE_KEY}
    for request in plane.requests:
        assert FAKE_KEY not in request, f"the key reached a URL: {request}"

    with Phase("starting the real s0ma-mcp through the launcher and talking to it"):
        with ServeSession(environment, smoke_project) as session:
            result = session.handshake()
            server = result["serverInfo"]
            tools = session.list_tools()
            code, stderr = session.close_stdin_and_wait()

    # It is the real server, not the built-in stub.
    assert server["name"] == "s0ma-authoring", server
    assert server["version"] == version_v, server
    assert server["name"] != launcher.STUB_SERVER_NAME, server
    assert server["version"] != launcher.STUB_SERVER_VERSION, server
    assert "tools" in result["capabilities"], result["capabilities"]
    note(f"handshake: {server['name']} {server['version']}, protocol {result['protocolVersion']}")

    # And its tools are exactly the surface the snapshot pins.
    assert tools == snapshot_tool_names, {
        "served": tools,
        "snapshot": snapshot_tool_names,
    }
    note(f"tools/list returned {len(tools)} tools, exactly the snapshot's")

    # Closing the conversation ends the run cleanly.
    assert code == 0, f"serve exited {code}; its error output was:\n{stderr}"

    assert_key_never_escaped(smoke_home, installed.stdout, installed.stderr, stderr)


# ---------------------------------------------------------------------------
# T2 - a newer version arrives on its own, and the old one is still there.
# ---------------------------------------------------------------------------


def test_t2_a_newer_version_installs_in_the_background_and_runs_next_time(
    launcher: ModuleType,
    plane: FakeControlPlane,
    smoke_home: Path,
    smoke_project: Path,
    version_v: str,
    version_w: str,
    wheels_w: Path,
    offline_uv: bool,
) -> None:
    quiet = launcher_env(smoke_home, smoke_project, plane, update="off", offline_uv=offline_uv)
    with Phase(f"installing s0ma {version_v} to start from"):
        installed = run_launcher(["install"], quiet, smoke_project)
    assert installed.returncode == 0, installed.stderr
    assert state_of(smoke_home)["installed"] == [version_v]

    # A newer version appears on the control plane, and the last check is old
    # enough that `serve` will look.
    plane.publish_directory(version_w, wheels_w)
    assert plane.latest == version_w
    state = state_of(smoke_home)
    state["last_check"] = launcher.now_seconds() - TWO_DAYS_SECONDS
    write_state(smoke_home, state)

    automatic = launcher_env(
        smoke_home, smoke_project, plane, update="auto", offline_uv=offline_uv
    )
    with Phase(f"serving s0ma {version_v} while a quiet update runs behind it"):
        with ServeSession(automatic, smoke_project) as session:
            running = session.handshake()["serverInfo"]
            first_code, first_stderr = session.close_stdin_and_wait()
    assert running["version"] == version_v, running
    assert first_code == 0, first_stderr
    note(f"the session ran s0ma {running['version']} throughout, as decision CD-3 requires")

    with Phase(f"waiting for the quiet update to bring s0ma {version_w} in"):
        waited = wait_for_installed(smoke_home, version_w)
    note(f"s0ma {version_w} arrived on its own after {waited:.1f}s")

    after = state_of(smoke_home)
    assert version_w in after["installed"], after
    assert version_v in after["installed"], "the version that worked was not kept"
    assert after["current"] == version_w, after
    assert after["pending"] == version_w, after
    assert after["latest_seen"] == version_w, after
    assert after["last_error"] is None, after
    assert (toolchain_of(launcher, smoke_home, version_v) / launcher.COMPLETE_MARKER).is_file()
    assert (toolchain_of(launcher, smoke_home, version_w) / launcher.COMPLETE_MARKER).is_file()

    with Phase(f"starting a new session, which should now be s0ma {version_w}"):
        with ServeSession(automatic, smoke_project) as session:
            now_running = session.handshake()["serverInfo"]
            second_code, second_stderr = session.close_stdin_and_wait()
    assert now_running["name"] == "s0ma-authoring", now_running
    assert now_running["version"] == version_w, now_running
    assert second_code == 0, second_stderr
    note(f"the next session ran s0ma {now_running['version']}, with {version_v} still beside it")

    # And the launcher agrees about what it would start, and what is still here.
    reported = run_launcher(["status", "--json"], automatic, smoke_project)
    assert reported.returncode == 0, reported.stderr
    report = json.loads(reported.stdout)
    assert report["resolved"]["version"] == version_w, report["resolved"]
    assert report["resolved"]["kind"] == "managed", report["resolved"]
    assert sorted(report["installed"]) == sorted([version_v, version_w]), report["installed"]

    log = update_log_path(smoke_home)
    assert log.is_file(), "the quiet update wrote no log"
    said = log.read_text(encoding="utf-8")
    assert version_w in said, said
    assert_key_never_escaped(
        smoke_home, installed.stdout, installed.stderr, first_stderr, second_stderr, reported.stdout
    )


# ---------------------------------------------------------------------------
# T3 - a pinned project stays where it is, and nothing moves it.
# ---------------------------------------------------------------------------


def test_t3_a_pinned_project_keeps_its_version_and_starts_no_update(
    launcher: ModuleType,
    plane: FakeControlPlane,
    smoke_home: Path,
    smoke_project: Path,
    version_v: str,
    version_w: str,
    wheels_w: Path,
    offline_uv: bool,
) -> None:
    quiet = launcher_env(smoke_home, smoke_project, plane, update="off", offline_uv=offline_uv)
    with Phase(f"installing s0ma {version_v} for a project that will pin it"):
        installed = run_launcher(["install"], quiet, smoke_project)
    assert installed.returncode == 0, installed.stderr

    # A newer version is available, and the project says it does not want it.
    plane.publish_directory(version_w, wheels_w)
    pin = smoke_project / launcher.PIN_FILENAME
    pin.write_text(version_v + "\n", encoding="utf-8", newline="\n")

    automatic = launcher_env(
        smoke_home, smoke_project, plane, update="auto", offline_uv=offline_uv
    )
    reported = run_launcher(["status", "--json"], automatic, smoke_project)
    assert reported.returncode == 0, reported.stderr
    report = json.loads(reported.stdout)
    assert report["pin"] == {"present": True, "version": version_v, "problem": None}, report["pin"]
    assert report["resolved"]["kind"] == "pinned", report["resolved"]
    assert report["resolved"]["version"] == version_v, report["resolved"]
    note(f"status says the pin decides: {report['resolved']['reason']}")

    # Age the last check past a day, so that only the pin can be what stops an
    # update from starting.
    state = state_of(smoke_home)
    state["last_check"] = launcher.now_seconds() - TWO_DAYS_SECONDS
    write_state(smoke_home, state)
    before = state_of(smoke_home)
    assert not update_log_path(smoke_home).exists(), "something had already run an update"

    with Phase(f"serving a project pinned to s0ma {version_v} with a newer one published"):
        with ServeSession(automatic, smoke_project) as session:
            running = session.handshake()["serverInfo"]
            code, stderr = session.close_stdin_and_wait()
    assert running["name"] == "s0ma-authoring", running
    assert running["version"] == version_v, running
    assert code == 0, stderr

    # No quiet update was started - and this is structural, not a matter of
    # waiting long enough to be sure. `spawn_background_update` opens
    # `launcher/update.log` in *this* process before it detaches anything, so a
    # log that was never created is a child that was never spawned. `state.json`
    # is untouched for the same reason: nothing ran to write it.
    assert not update_log_path(smoke_home).exists(), (
        "serve started a quiet update for a pinned project"
    )
    after = state_of(smoke_home)
    assert after == before, {"before": before, "after": after}
    assert after["installed"] == [version_v], after
    assert version_w not in after["installed"], after
    assert after["pending"] is None, after
    assert not toolchain_of(launcher, smoke_home, version_w).exists(), (
        f"s0ma {version_w} was installed behind a pinned project's back"
    )
    kept = pin.read_text(encoding="utf-8").strip()
    note(f"nothing was fetched, nothing was installed, and the pin still reads {kept}")

    assert_key_never_escaped(
        smoke_home, installed.stdout, installed.stderr, stderr, reported.stdout
    )
