# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""s0ma-launch - the one small program that decides which s0ma runs, and starts it.

Claude Code (through the plugin) and Claude Desktop (through the extension)
both start s0ma by running this file:

    uv run --script s0ma_launch.py serve

Nothing else about s0ma is baked into either host. This file finds a copy of
s0ma to run, hands control to it, and - in later pieces of the work - installs
and updates copies of its own.

Design rules this file keeps (plan ``beta-prep-2-claude``, section 3.1):

* **Standard library only.** No third-party import, ever. The PEP 723 header
  above declares an empty dependency list so ``uv run --script`` never resolves
  anything.
* **Windows is a first-class target.** No ``os.execv`` on Windows, no
  ``/bin/sh``, both ``bin/`` and ``Scripts/`` virtual-environment layouts, and
  every path that reaches a human is printed with forward slashes.
* **Text is for people, not for programmers.** Say what happened and what to do
  next.
* **A license key is never printed, logged, put on a command line or in a URL.**
  The only thing this file ever says about a key is whether there is one and
  what its last four characters are.
* **ASCII only in anything printed.** A Windows console that is not running in
  UTF-8 mode can refuse anything else, and a launcher that cannot print is a
  launcher that cannot explain itself.

The file is organised in sections, and each one says at its head what it is for.
Reading order, roughly: the state directory, then which copy of s0ma runs here,
then ``status`` and ``serve``, then the built-in stub server - the one this file
speaks itself when there is no s0ma to start - then everything that talks to the
control plane and looks after installed copies: install, update, pin and
activate.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import importlib
import ipaddress
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Names, codes and constants.
# ---------------------------------------------------------------------------

PROG = "s0ma-launch"

#: Exit codes, frozen by the plan (section 4.3).
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NOT_INSTALLED = 3
EXIT_NO_KEY = 4
EXIT_NETWORK = 5
EXIT_VERIFY_FAILED = 6
EXIT_NO_UV = 7

#: Environment variables this launcher reads. Nothing else is consulted.
ENV_HOME = "S0MA_HOME"
ENV_LICENSE_KEY = "S0MA_LICENSE_KEY"
ENV_UPDATE = "S0MA_UPDATE"
ENV_TOOLCHAIN = "S0MA_TOOLCHAIN"
ENV_CP_HOST = "S0MA_CP_HOST"
ENV_PROJECT_DIR = "CLAUDE_PROJECT_DIR"
ENV_PLUGIN_DATA = "CLAUDE_PLUGIN_DATA"

#: Default state directory, relative to the user's home.
DEFAULT_HOME_DIRNAME = ".s0ma"

#: Files and directories under the state directory (plan section 4.2).
LICENSE_FILENAME = "license"
LAUNCHER_DIRNAME = "launcher"
CONFIG_FILENAME = "config.json"
STATE_FILENAME = "state.json"
TOOLCHAINS_DIRNAME = "toolchains"
DOWNLOADS_DIRNAME = "downloads"
UPDATE_LOCK_FILENAME = "update.lock"
UPDATE_LOG_FILENAME = "update.log"

#: Written last inside a toolchain directory. A directory without it is
#: half-built: it is never used, and a later run sweeps it away.
COMPLETE_MARKER = ".complete"

#: The file a project uses to pin itself to one version of s0ma.
PIN_FILENAME = ".s0ma-version"

#: The programs a toolchain is expected to provide.
MCP_PROGRAM = "s0ma-mcp"
CLI_PROGRAM = "s0ma"

#: The distribution whose version is the toolchain's version. The s0ma
#: distributions version in lockstep, so any one of them would answer; this is
#: the one that provides the MCP server.
VERSION_DISTRIBUTION = "s0ma_mcp"

#: Owner-only permissions, applied on POSIX and a documented no-op elsewhere
#: (Windows ACLs are not expressible as a POSIX mode).
DIR_MODE = 0o700
FILE_MODE = 0o600

#: How the update setting may be spelled.
UPDATE_MODES = ("auto", "notify", "off")
DEFAULT_UPDATE_MODE = "auto"

#: The control plane: the one host this launcher ever talks to, and only for
#: the manifest, the wheels it names, and a key check.
DEFAULT_CP_HOST = "account.kn0wthyself.ai"

#: The four distributions a copy of s0ma is made of, in the order they are
#: fetched. The same four the keyed installer downloads
#: (``scripts/install.sh``); the manifest may carry more, and anything else in
#: it is left alone.
WHEEL_STEMS = ("s0ma_core", "s0ma_dsl", "s0ma_mcp", "s0ma_studi0")

#: How long one request may take before the launcher gives up and says so.
#: Read through :func:`_timeout` so a test can shorten them.
CP_TIMEOUT_SECONDS = 20.0
DOWNLOAD_TIMEOUT_SECONDS = 120.0

#: How much of an answer is read before it is treated as nonsense (a JSON body)
#: or as something that cannot be a wheel.
MAX_JSON_BYTES = 1024 * 1024
MAX_WHEEL_BYTES = 256 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 64 * 1024

#: How long an automatic check waits before asking the control plane again.
UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60

#: The background update's log is rotated at this size, and one older file is
#: kept beside it.
UPDATE_LOG_LIMIT_BYTES = 256 * 1024
UPDATE_LOG_OLD_SUFFIX = ".1"

#: Test-only seam. When ``S0MA_LAUNCH_OFFLINE_INSTALL=1`` is set, ``uv`` is told
#: to resolve nothing from the network, so the launcher's own tests can perform
#: a real install of stand-in wheels without ever leaving the machine. A real
#: install leaves the package index on, because the real s0ma wheels depend on
#: packages from PyPI (lark, the MCP SDK and friends) and those have to resolve.
ENV_OFFLINE_INSTALL = "S0MA_LAUNCH_OFFLINE_INSTALL"

#: How an entitlement answer is worded for a person.
ENTITLEMENT_WORDS = {
    "ok": "active when it was last checked",
    "not_entitled": "this account's access to new versions has ended",
    "invalid_key": "the key was not accepted the last time it was used",
    "unknown": "not checked yet",
}

#: Kinds of answer :func:`resolve_toolchain` can give.
KIND_OVERRIDE = "override"
KIND_PROJECT = "project"
KIND_PINNED = "pinned"
KIND_MANAGED = "managed"
KIND_NONE = "none"

#: The schema tag on ``status --json`` output, so a later reader can tell
#: which shape it is looking at.
STATUS_SCHEMA = "s0ma-launch-status@1"

UV_MISSING_MESSAGE = (
    "s0ma needs the `uv` tool to look after its own Python environments, and "
    "there is no copy of it on this machine.\n"
    "Install uv (see https://docs.astral.sh/uv/getting-started/installation/) "
    "and run this again."
)

#: Where a key goes. Said the same way everywhere, because a person who has
#: just been told their key is missing should not have to guess which of the two
#: places the other message meant.
KEY_HOMES_SENTENCE = (
    "Put it in the s0ma plugin's settings in Claude, or run `s0ma-launch "
    "activate` in a terminal to save it on this machine. Never type a license "
    "key into a chat."
)

KEY_MISSING_MESSAGE = (
    "s0ma needs your license key to fetch anything from its control plane, and "
    "there is no key on this machine.\n" + KEY_HOMES_SENTENCE
)

KEY_REFUSED_MESSAGE = (
    "The s0ma control plane did not accept this license key, so nothing was "
    "fetched. Anything already installed keeps working.\n"
    "Check that the whole key was pasted, then try again. " + KEY_HOMES_SENTENCE
)

_VERSION_RE = re.compile(r"\A[0-9]+(?:\.[0-9]+)*[A-Za-z0-9.+_-]*\Z")
_PROGRAM_NAME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_MAX_VERSION_LENGTH = 64


class LauncherError(Exception):
    """A failure with a plain sentence for the user and an exit code.

    Raised from anywhere below; :func:`main` prints *message* on stderr and
    returns *code*. Nothing else in this file calls :func:`sys.exit`.
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ControlPlaneError(LauncherError):
    """What the control plane said, turned into a sentence and an exit code.

    *entitlement* is what the answer means for the record in ``state.json`` -
    ``invalid_key`` or ``not_entitled`` - or ``None`` when the answer says
    nothing about the subscription at all (a busy server, a network that is
    down). *notice* is the control plane's own wording, shown once after ours
    and never instead of it; it is already part of :attr:`message`.
    """

    def __init__(
        self,
        code: int,
        message: str,
        *,
        entitlement: str | None = None,
        notice: str | None = None,
    ) -> None:
        super().__init__(code, message if notice is None else message + "\n" + notice)
        self.entitlement = entitlement
        self.notice = notice


# ---------------------------------------------------------------------------
# Small helpers: environment, printing, paths.
# ---------------------------------------------------------------------------


def environ(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    """Return *env*, defaulting to the real process environment."""
    return os.environ if env is None else env


def is_windows() -> bool:
    """True when this interpreter is running on Windows."""
    return os.name == "nt"


def fwd(path: Path | str) -> str:
    """Render *path* for a human, always with forward slashes (NFR-7).

    ``C:\\Users\\x`` prints as ``C:/Users/x``. Every path that reaches a
    message, a log line or a JSON field goes through this function.
    """
    return Path(path).as_posix()


def say(message: str, *, stream: Any = None) -> None:
    """Write one message for the user on stderr.

    Never stdout: ``serve`` hands stdout to the MCP protocol, and a stray line
    there breaks the session. Everything the launcher says about itself is
    stderr, except the deliberate report ``status`` prints. *stream* is the seam
    a background run uses to send the same lines to its log file instead.
    """
    handle = sys.stderr if stream is None else stream
    print(message, file=handle)


def _chmod_best_effort(path: Path, mode: int) -> bool:
    """Apply *mode* to *path*; a no-op off POSIX and never an exception."""
    if os.name != "posix":
        return False
    try:
        os.chmod(path, mode)
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# The state directory (plan section 4.2).
# ---------------------------------------------------------------------------


def s0ma_home(env: Mapping[str, str] | None = None) -> Path:
    """Return the state directory: ``S0MA_HOME`` when set, else ``~/.s0ma``.

    Nothing is created. The directory is shared with the feedback function,
    which owns ``feedback-token`` and ``feedback-receipts.jsonl`` there; the
    launcher never reads or writes either.
    """
    values = environ(env)
    override = values.get(ENV_HOME, "").strip()
    if override:
        return Path(override).expanduser()
    home = values.get("USERPROFILE") if is_windows() else values.get("HOME")
    base = Path(home).expanduser() if home else Path.home()
    return base / DEFAULT_HOME_DIRNAME


def launcher_dir(home: Path) -> Path:
    """The launcher's own corner of the state directory."""
    return home / LAUNCHER_DIRNAME


def config_path(home: Path) -> Path:
    """Where the launcher's settings live."""
    return launcher_dir(home) / CONFIG_FILENAME


def state_path(home: Path) -> Path:
    """Where the launcher's runtime record lives."""
    return launcher_dir(home) / STATE_FILENAME


def license_path(home: Path) -> Path:
    """Where ``activate`` stores a key, owner-readable only."""
    return home / LICENSE_FILENAME


def toolchains_dir(home: Path) -> Path:
    """The parent of every version the launcher has installed."""
    return home / TOOLCHAINS_DIRNAME


def downloads_dir(home: Path) -> Path:
    """Where verified downloads are kept for re-use."""
    return home / DOWNLOADS_DIRNAME


def update_lock_path(home: Path) -> Path:
    """The advisory lock that stops two sessions installing at once."""
    return launcher_dir(home) / UPDATE_LOCK_FILENAME


def update_log_path(home: Path) -> Path:
    """Where a background update writes what it did."""
    return launcher_dir(home) / UPDATE_LOG_FILENAME


def managed_toolchain_dir(home: Path, version: str) -> Path:
    """The directory one installed version lives in."""
    return toolchains_dir(home) / version


# ---------------------------------------------------------------------------
# Reading and writing JSON, safely.
# ---------------------------------------------------------------------------


def read_json_file(
    path: Path, *, recreate: Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    """Return the object in *path*, or ``None`` when there is nothing usable.

    A missing file is not a problem and nothing is written for it - a machine
    that has never installed anything keeps a clean state directory. A file that
    cannot be parsed, or that holds something other than an object, is moved
    aside to ``<name>.corrupt`` and reported in one line on stderr; when
    *recreate* is given, a fresh file with those contents takes its place, so
    the next run starts from something readable.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as error:
        say(f"Could not read {fwd(path)} ({error.strerror or error}); using the defaults.")
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    _quarantine(path)
    if recreate is not None:
        try:
            write_json_file(path, recreate)
        except OSError:
            # Read-only directory, a full disk: the run carries on with the
            # defaults it already has in hand.
            pass
    return None


def _quarantine(path: Path) -> None:
    """Move an unreadable file aside and say so once."""
    spoiled = path.with_name(path.name + ".corrupt")
    try:
        os.replace(path, spoiled)
    except OSError:
        say(
            f"The file {fwd(path)} could not be understood, and it could not be "
            "moved aside either. s0ma is carrying on with its normal settings."
        )
        return
    say(
        f"The file {fwd(path)} could not be understood, so it was moved to "
        f"{fwd(spoiled)} and s0ma started a fresh one."
    )


def write_json_file(path: Path, data: Mapping[str, Any]) -> None:
    """Write *data* to *path* as one object, replacing it in one step.

    The content goes to a temporary file in the same directory and is then
    moved over the target with :func:`os.replace`, which is atomic on POSIX and
    on Windows alike. A reader never sees a half-written file.
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(parent, DIR_MODE)
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    handle_fd, temporary = tempfile.mkstemp(dir=str(parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    _chmod_best_effort(path, FILE_MODE)


# ---------------------------------------------------------------------------
# Settings and runtime record.
# ---------------------------------------------------------------------------


def default_config() -> dict[str, Any]:
    """The settings a machine has before anyone changes anything."""
    return {"update": DEFAULT_UPDATE_MODE, "cp_host": DEFAULT_CP_HOST}


def default_state() -> dict[str, Any]:
    """The runtime record of a machine that has never installed anything."""
    return {
        "installed": [],
        "current": None,
        "latest_seen": None,
        "last_check": None,
        "entitlement": "unknown",
        "pending": None,
        "last_error": None,
    }


def _load_with_defaults(path: Path, defaults: dict[str, Any]) -> dict[str, Any]:
    stored = read_json_file(path, recreate=defaults)
    merged = dict(defaults)
    if stored:
        merged.update(stored)
    return merged


def load_config(home: Path) -> dict[str, Any]:
    """Return the launcher's settings, filling in anything not set."""
    config = _load_with_defaults(config_path(home), default_config())
    if config.get("update") not in UPDATE_MODES:
        config["update"] = DEFAULT_UPDATE_MODE
    if not isinstance(config.get("cp_host"), str) or not config["cp_host"].strip():
        config["cp_host"] = DEFAULT_CP_HOST
    return config


def save_config(home: Path, config: Mapping[str, Any]) -> None:
    """Write the launcher's settings."""
    write_json_file(config_path(home), config)


def load_state(home: Path) -> dict[str, Any]:
    """Return the launcher's runtime record, filling in anything missing."""
    state = _load_with_defaults(state_path(home), default_state())
    if not isinstance(state.get("installed"), list):
        state["installed"] = []
    if state.get("entitlement") not in ENTITLEMENT_WORDS:
        state["entitlement"] = "unknown"
    return state


def save_state(home: Path, state: Mapping[str, Any]) -> None:
    """Write the launcher's runtime record."""
    write_json_file(state_path(home), state)


def update_mode(
    env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> str:
    """Return ``auto``, ``notify`` or ``off``.

    ``S0MA_UPDATE`` wins over the stored setting; anything unrecognised in
    either place falls back to ``auto`` rather than stopping the run.
    """
    chosen = environ(env).get(ENV_UPDATE, "").strip().lower()
    if chosen in UPDATE_MODES:
        return chosen
    if config is not None:
        stored = config.get("update")
        if stored in UPDATE_MODES:
            return str(stored)
    return DEFAULT_UPDATE_MODE


def cp_host(
    env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> str:
    """Return the control-plane host a later install would ask."""
    chosen = environ(env).get(ENV_CP_HOST, "").strip()
    if chosen:
        return chosen
    if config is not None:
        stored = config.get("cp_host")
        if isinstance(stored, str) and stored.strip():
            return stored.strip()
    return DEFAULT_CP_HOST


# ---------------------------------------------------------------------------
# The license key. Read here, shown nowhere.
# ---------------------------------------------------------------------------


def license_key(
    env: Mapping[str, str] | None = None, home: Path | None = None
) -> tuple[str | None, str | None]:
    """Return ``(key, where_it_came_from)``; ``(None, None)`` when there is none.

    Order, per decision CD-2: the ``S0MA_LICENSE_KEY`` variable the plugin sets
    from its configuration screen, then the ``license`` file that
    ``s0ma-launch activate`` writes.
    """
    values = environ(env)
    from_env = values.get(ENV_LICENSE_KEY, "").strip()
    if from_env:
        return from_env, "environment"
    base = s0ma_home(values) if home is None else home
    try:
        stored = license_path(base).read_text(encoding="utf-8").strip()
    except OSError:
        return None, None
    if stored:
        return stored, "file"
    return None, None


def key_last4(key: str) -> str:
    """Return the last four characters of *key*, or fewer if it is shorter."""
    return key[-4:]


def redact_key(key: str) -> str:
    """Render *key* for a message: a fixed mask and its last four characters.

    The real prefix is masked too, so nothing about the key's shape leaks. The
    mask is plain ASCII on purpose - see the note about Windows consoles in
    this file's docstring.
    """
    return "s0ma_..." + key_last4(key)


# ---------------------------------------------------------------------------
# Finding uv.
# ---------------------------------------------------------------------------


def uv_candidates(
    env: Mapping[str, str] | None = None,
    *,
    windows: bool | None = None,
) -> list[Path]:
    """The places uv installs itself, in the order worth trying.

    A GUI-launched Claude does not read the user's shell profile, so ``uv`` may
    be perfectly present and simply not on ``PATH`` (research note 7.4). These
    are the paths worth looking at before giving up.
    """
    values = environ(env)
    on_windows = is_windows() if windows is None else windows
    if on_windows:
        profile = values.get("USERPROFILE", "")
        local_app_data = values.get("LOCALAPPDATA", "")
        program_files = values.get("ProgramFiles", "")
        roots = [
            (profile, (".local", "bin")),
            (local_app_data, ("uv", "bin")),
            (profile, (".cargo", "bin")),
            (program_files, ("uv",)),
        ]
        return [Path(root).joinpath(*parts, "uv.exe") for root, parts in roots if root]
    home = values.get("HOME", "")
    candidates: list[Path] = []
    if home:
        candidates.append(Path(home) / ".local" / "bin" / "uv")
        candidates.append(Path(home) / ".cargo" / "bin" / "uv")
    candidates.append(Path("/opt/homebrew/bin/uv"))
    candidates.append(Path("/usr/local/bin/uv"))
    return candidates


def find_uv(env: Mapping[str, str] | None = None, *, windows: bool | None = None) -> Path | None:
    """Return the path to uv, or ``None`` when this machine has none."""
    values = environ(env)
    on_windows = is_windows() if windows is None else windows
    exe = "uv.exe" if on_windows else "uv"
    found = shutil.which(exe, path=values.get("PATH"))
    if found:
        return Path(found)
    for candidate in uv_candidates(values, windows=on_windows):
        if candidate.is_file():
            return candidate
    return None


def require_uv(env: Mapping[str, str] | None = None, *, windows: bool | None = None) -> Path:
    """Return the path to uv, or raise with the sentence that explains it."""
    found = find_uv(env, windows=windows)
    if found is None:
        raise LauncherError(EXIT_NO_UV, UV_MISSING_MESSAGE)
    return found


# ---------------------------------------------------------------------------
# Toolchain layout: where a copy of s0ma keeps its programs.
# ---------------------------------------------------------------------------


def program_names(name: str) -> tuple[str, ...]:
    """The filenames one program can have. Windows adds ``.exe``."""
    return (name, name + ".exe")


def find_program(directory: Path, name: str) -> Path | None:
    """Return ``directory/<name>`` in whichever spelling exists there."""
    for candidate in program_names(name):
        path = directory / candidate
        if path.is_file():
            return path
    return None


def bin_dir_of(root: Path) -> Path | None:
    """Return the directory of *root* that holds the s0ma programs.

    Both virtual-environment layouts are accepted, on every platform, so a
    Windows-shaped tree is understood on a POSIX machine and the other way
    round: ``bin/`` (POSIX) and ``Scripts/`` (Windows).
    """
    for name in ("bin", "Scripts"):
        candidate = root / name
        if find_program(candidate, MCP_PROGRAM) is not None:
            return candidate
    return None


def site_packages_dirs(root: Path) -> list[Path]:
    """Every site-packages directory a virtual environment at *root* may have.

    POSIX puts it at ``lib/python3.N/site-packages``; Windows at
    ``Lib/site-packages``. Both are looked at, always, for the same reason as
    :func:`bin_dir_of`.
    """
    found: list[Path] = []
    windows_style = root / "Lib" / "site-packages"
    if windows_style.is_dir():
        found.append(windows_style)
    lib = root / "lib"
    if lib.is_dir():
        try:
            children = sorted(lib.iterdir())
        except OSError:
            children = []
        for child in children:
            candidate = child / "site-packages"
            if candidate.is_dir():
                found.append(candidate)
    return found


def installed_version_of(root: Path, distribution: str = VERSION_DISTRIBUTION) -> str | None:
    """Return the version installed in the environment at *root*, if it is cheap.

    The answer comes from the name of the ``*.dist-info`` directory that pip and
    uv both leave behind - no program is executed and nothing is imported. When
    there is no such directory the answer is ``None``, and the caller says
    something honest instead of guessing.
    """
    prefix = distribution.replace("-", "_") + "-"
    for site_packages in site_packages_dirs(root):
        try:
            entries = sorted(site_packages.glob(prefix + "*.dist-info"))
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            version = entry.name.removeprefix(prefix).removesuffix(".dist-info")
            if version:
                return version
    return None


def version_sort_key(version: str) -> tuple[tuple[int, ...], str]:
    """Sort versions as numbers, so 0.10.0 comes after 0.9.0.

    Sorting version strings as text puts ``0.9.0`` after ``0.10.0``, which would
    make the launcher start the wrong copy of s0ma. Each dot-separated part
    contributes its leading digits; the original string breaks ties so the order
    is total and stable.
    """
    numbers: list[int] = []
    for chunk in version.split("."):
        digits = ""
        for character in chunk:
            if not character.isdigit():
                break
            digits += character
        numbers.append(int(digits) if digits else 0)
    return tuple(numbers), version


def installed_versions(home: Path) -> list[str]:
    """Every version the launcher has fully installed, oldest first.

    A directory without its :data:`COMPLETE_MARKER` was interrupted part-way and
    is ignored here (a later run sweeps it away). A directory that carries the
    marker but has lost its programs is ignored too, because starting it would
    fail in front of the user.
    """
    parent = toolchains_dir(home)
    try:
        entries = list(parent.iterdir())
    except OSError:
        return []
    usable: list[str] = []
    for entry in entries:
        if not entry.is_dir():
            continue
        if not (entry / COMPLETE_MARKER).exists():
            continue
        if bin_dir_of(entry) is None:
            continue
        usable.append(entry.name)
    return sorted(usable, key=version_sort_key)


# ---------------------------------------------------------------------------
# The project: which directory we are working in, and what it asks for.
# ---------------------------------------------------------------------------


def project_dir(env: Mapping[str, str] | None = None) -> Path:
    """Return the project directory.

    ``CLAUDE_PROJECT_DIR`` when Claude set it (it is exported to MCP server
    subprocesses), otherwise the working directory. No search upwards: the
    directory the launcher reads a pin from is the same one ``pin`` writes it
    to, and a rule that simple is one a person can hold in their head.
    """
    chosen = environ(env).get(ENV_PROJECT_DIR, "").strip()
    if chosen:
        return Path(chosen).expanduser()
    return Path.cwd()


def project_venv(project: Path) -> Path:
    """The virtual environment a project keeps its own s0ma in."""
    return project / ".venv"


@dataclass(frozen=True)
class Pin:
    """What a project's ``.s0ma-version`` file says.

    *present* is whether the file exists at all; *version* is what it names, and
    is ``None`` when the file exists but says nothing usable; *problem* is the
    half-sentence that explains that case.
    """

    present: bool
    version: str | None
    problem: str | None


def looks_like_version(text: str) -> bool:
    """Whether *text* could be a version number."""
    return bool(text) and len(text) <= _MAX_VERSION_LENGTH and _VERSION_RE.match(text) is not None


def read_pin(project: Path) -> Pin:
    """Read the project's ``.s0ma-version`` file."""
    path = project / PIN_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Pin(present=False, version=None, problem=None)
    except OSError:
        return Pin(present=True, version=None, problem="could not be read")
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    if not first:
        return Pin(present=True, version=None, problem="is empty")
    if not looks_like_version(first):
        return Pin(present=True, version=None, problem="does not name a version")
    return Pin(present=True, version=first, problem=None)


# ---------------------------------------------------------------------------
# Which s0ma runs here (decision CD-4).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Resolution:
    """The answer to "which s0ma runs here, and why".

    * *kind* - one of :data:`KIND_OVERRIDE`, :data:`KIND_PROJECT`,
      :data:`KIND_PINNED`, :data:`KIND_MANAGED`, :data:`KIND_NONE`.
    * *path* - the directory holding the s0ma programs, or ``None``.
    * *version* - the version, or ``None`` when it cannot be read without
      running anything.
    * *reason* - one plain sentence, printed as-is by ``status``.
    """

    kind: str
    path: Path | None
    version: str | None
    reason: str

    @property
    def found(self) -> bool:
        """Whether there is something to run."""
        return self.path is not None


def override_bin_dir(root: Path) -> Path | None:
    """Find the s0ma programs inside a directory the user named.

    ``S0MA_TOOLCHAIN`` is for contributors and for anyone running s0ma from
    source, so three shapes are accepted: a virtual environment, the directory
    of programs itself, and a checkout with a ``.venv`` in it.
    """
    direct = bin_dir_of(root)
    if direct is not None:
        return direct
    if find_program(root, MCP_PROGRAM) is not None:
        return root
    return bin_dir_of(project_venv(root))


def resolve_toolchain(
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    project: Path | None = None,
) -> Resolution:
    """Decide which copy of s0ma runs here. Reads the disk; changes nothing.

    The order is decision CD-4 and first match wins:

    1. ``S0MA_TOOLCHAIN`` - someone said explicitly which copy to use.
    2. The project's own environment, when it has s0ma installed. Every project
       installed by the old installer keeps working, pinned exactly as it is.
    3. The version named in the project's ``.s0ma-version`` file.
    4. The newest version the launcher has installed.

    Two of those are deliberately *not* fall-throughs. An explicit
    ``S0MA_TOOLCHAIN`` that holds no s0ma is an answer of "none", not a reason
    to quietly run something else; and a project pinned to a version that is not
    installed is told so, rather than being moved to a version it did not ask
    for.
    """
    values = environ(env)
    base = s0ma_home(values) if home is None else home
    where = project_dir(values) if project is None else project

    override = values.get(ENV_TOOLCHAIN, "").strip()
    if override:
        root = Path(override).expanduser()
        found = override_bin_dir(root)
        if found is None:
            return Resolution(
                kind=KIND_NONE,
                path=None,
                version=None,
                reason=(
                    f"S0MA_TOOLCHAIN points at {fwd(root)}, but there is no s0ma "
                    "program there."
                ),
            )
        return Resolution(
            kind=KIND_OVERRIDE,
            path=found,
            version=installed_version_of(found.parent),
            reason=(
                f"S0MA_TOOLCHAIN points at {fwd(root)}, so that copy of s0ma runs here."
            ),
        )

    own = bin_dir_of(project_venv(where))
    if own is not None:
        return Resolution(
            kind=KIND_PROJECT,
            path=own,
            version=installed_version_of(project_venv(where)),
            reason=(
                "This project has its own copy of s0ma installed, so that is what "
                "runs here."
            ),
        )

    pin = read_pin(where)
    if pin.present and pin.version is None:
        return Resolution(
            kind=KIND_NONE,
            path=None,
            version=None,
            reason=(
                f"This project has a {PIN_FILENAME} file, but it {pin.problem}, so "
                "s0ma cannot tell which version the project wants."
            ),
        )
    if pin.version is not None:
        root = managed_toolchain_dir(base, pin.version)
        found = bin_dir_of(root) if (root / COMPLETE_MARKER).exists() else None
        if found is None:
            return Resolution(
                kind=KIND_NONE,
                path=None,
                version=pin.version,
                reason=(
                    f"This project asks for s0ma {pin.version} in its {PIN_FILENAME} "
                    "file, and that version is not installed on this machine."
                ),
            )
        return Resolution(
            kind=KIND_PINNED,
            path=found,
            version=pin.version,
            reason=(
                f"This project is pinned to s0ma {pin.version} by its {PIN_FILENAME} "
                "file, so that is what runs here."
            ),
        )

    versions = installed_versions(base)
    if versions:
        newest = versions[-1]
        found = bin_dir_of(managed_toolchain_dir(base, newest))
        if found is not None:
            return Resolution(
                kind=KIND_MANAGED,
                path=found,
                version=newest,
                reason=(
                    f"s0ma {newest} is the newest version installed on this machine, "
                    "and nothing in this project asks for a different one."
                ),
            )

    return Resolution(
        kind=KIND_NONE,
        path=None,
        version=None,
        reason="s0ma is not installed on this machine yet.",
    )


def version_words(resolution: Resolution) -> str:
    """Name the resolved s0ma in a sentence, with or without a version number.

    A version the launcher installed always has one. A copy that belongs to a
    project, or to a contributor's own checkout, often does not - reading it
    would mean running something, and neither ``status`` nor ``serve`` will do
    that just to print a line - so those are named for what they are instead.
    """
    if resolution.version:
        return f"s0ma {resolution.version}"
    if resolution.kind == KIND_PROJECT:
        return "s0ma (the project's own copy)"
    if resolution.kind == KIND_OVERRIDE:
        return "s0ma (your own copy)"
    return "s0ma"


def next_step(
    resolution: Resolution,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    project: Path | None = None,
) -> str:
    """One sentence saying what, if anything, the person should do now."""
    values = environ(env)
    base = s0ma_home(values) if home is None else home
    where = project_dir(values) if project is None else project

    if resolution.found:
        key, _ = license_key(values, base)
        if key is None and resolution.kind == KIND_MANAGED:
            return (
                "Nothing urgent. Add your license key in the s0ma plugin's settings "
                "when you want new versions to keep arriving."
            )
        return "Nothing - s0ma is ready."

    if values.get(ENV_TOOLCHAIN, "").strip():
        return (
            "Point S0MA_TOOLCHAIN at a directory that contains s0ma, or unset it to "
            "let s0ma look after its own copy."
        )
    pin = read_pin(where)
    if pin.present and pin.version is None:
        return f"Fix or delete {fwd(where / PIN_FILENAME)}, then try again."
    if pin.version is not None:
        return (
            f"Run `{PROG} install --version {pin.version}` to get the version this "
            "project asks for."
        )
    return f"Run /s0ma:setup in Claude, or `{PROG} install` in a terminal."


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def status_report(
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    project: Path | None = None,
) -> dict[str, Any]:
    """Gather everything ``status`` knows. Never touches the network."""
    values = environ(env)
    base = s0ma_home(values) if home is None else home
    where = project_dir(values) if project is None else project

    config = load_config(base)
    state = load_state(base)
    resolution = resolve_toolchain(values, base, where)
    pin = read_pin(where)
    key, key_source = license_key(values, base)
    uv = find_uv(values)
    plugin_data = values.get(ENV_PLUGIN_DATA, "").strip()
    override = values.get(ENV_TOOLCHAIN, "").strip()

    return {
        "schema": STATUS_SCHEMA,
        "home": fwd(base),
        "project": fwd(where),
        "pin": {
            "present": pin.present,
            "version": pin.version,
            "problem": pin.problem,
        },
        "resolved": {
            "kind": resolution.kind,
            "path": fwd(resolution.path) if resolution.path else None,
            "version": resolution.version,
            "named": version_words(resolution),
            "reason": resolution.reason,
        },
        "installed": installed_versions(base),
        "license_key": {
            "present": key is not None,
            "last4": key_last4(key) if key else None,
            "source": key_source,
        },
        "entitlement": state.get("entitlement", "unknown"),
        "update": update_mode(values, config),
        "cp_host": cp_host(values, config),
        "uv": fwd(uv) if uv else None,
        "toolchain_override": fwd(Path(override)) if override else None,
        "plugin_data": fwd(Path(plugin_data)) if plugin_data else None,
        "latest_seen": state.get("latest_seen"),
        "pending": state.get("pending"),
        "last_check": state.get("last_check"),
        "last_error": state.get("last_error"),
        "next_step": next_step(resolution, values, base, where),
    }


def status_lines(report: Mapping[str, Any]) -> list[str]:
    """Render *report* as at most twelve lines for a person to read."""
    resolved = report["resolved"]
    if resolved["path"]:
        runs = f"{resolved['named']}, from {resolved['path']}"
    else:
        runs = "nothing yet"

    pin = report["pin"]
    if pin["version"]:
        pinned = f"pinned to {pin['version']}"
    elif pin["present"]:
        pinned = f"has a {PIN_FILENAME} file that {pin['problem']}"
    else:
        pinned = "not pinned"

    installed = ", ".join(report["installed"]) if report["installed"] else "none yet"

    key = report["license_key"]
    if key["present"]:
        shown = "s0ma_..." + (key["last4"] or "")
        if key["source"] == "environment":
            where_from = "from the plugin's settings"
        else:
            where_from = "saved on this machine"
        key_line = f"present ({shown}), {where_from}"
    else:
        key_line = "not set"

    updates = {
        "auto": "automatic - a newer s0ma is fetched quietly and used next time",
        "notify": "you are told when a newer s0ma is available",
        "off": "off - s0ma never updates itself",
    }[report["update"]]

    return [
        f"Runs here:    {runs}",
        f"Why:          {resolved['reason']}",
        f"Project:      {report['project']} ({pinned})",
        f"Installed:    {installed}",
        f"License key:  {key_line}",
        f"Subscription: {ENTITLEMENT_WORDS.get(report['entitlement'], 'not checked yet')}",
        f"Updates:      {updates}",
        f"uv:           {report['uv'] or 'not found on this machine'}",
        f"Next step:    {report['next_step']}",
    ]


def cmd_status(args: argparse.Namespace) -> int:
    """Say what is installed, what would run here, and why. No network."""
    report = status_report()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return EXIT_OK
    for line in status_lines(report):
        print(line)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Handing control to the toolchain.
# ---------------------------------------------------------------------------


def _forwarding_handlers() -> tuple[int, ...]:
    """The signals worth passing on to the child, on whichever platform."""
    names = ("SIGINT", "SIGTERM", "SIGBREAK", "SIGHUP")
    found = []
    for name in names:
        number = getattr(signal, name, None)
        if number is not None:
            found.append(int(number))
    return tuple(found)


def _spawn_and_wait(
    argv: Sequence[str],
    env: Mapping[str, str],
    *,
    spawn: Callable[..., Any],
    set_handler: Callable[[int, Any], Any],
) -> int:
    """Start *argv*, pass signals on to it, and return its exit code.

    This is the Windows path, and the path any POSIX machine falls back to when
    replacing the process is refused. Standard input, output and error are
    inherited, so the MCP conversation runs straight through this process
    without being copied.
    """
    process = spawn(list(argv), env=dict(env))

    def forward(signum: int, _frame: Any = None) -> None:
        try:
            process.send_signal(signum)
        except (ValueError, OSError, AttributeError):
            # Windows only accepts a few signals through send_signal; asking it
            # to stop is better than doing nothing.
            try:
                process.terminate()
            except (OSError, AttributeError):
                pass

    previous: list[tuple[int, Any]] = []
    for signum in _forwarding_handlers():
        try:
            previous.append((signum, set_handler(signum, forward)))
        except (ValueError, OSError, RuntimeError):
            # Not the main thread, or a signal this platform will not let us
            # take. Neither is a reason to refuse to start s0ma.
            continue
    try:
        while True:
            try:
                return int(process.wait())
            except KeyboardInterrupt:
                forward(getattr(signal, "SIGINT", 2))
    finally:
        for signum, handler in previous:
            try:
                set_handler(signum, handler)
            except (ValueError, OSError, RuntimeError):
                pass


def hand_off(
    argv: Sequence[str],
    env: Mapping[str, str] | None = None,
    *,
    replace: bool | None = None,
    execv: Callable[[str, Sequence[str], Mapping[str, str]], None] | None = None,
    spawn: Callable[..., Any] | None = None,
    set_handler: Callable[[int, Any], Any] | None = None,
) -> int:
    """Give the rest of this run to *argv* and return the exit code it ends with.

    On POSIX this process is *replaced*, so there is no extra process sitting
    between Claude and s0ma and no second set of pipes to get wrong. Windows has
    no such call that keeps the process identity, so there the child is started
    and waited on, with signals passed through to it (:func:`_spawn_and_wait`).

    Both branches are here, and both are tested on every platform: the
    behaviour the machine will not perform natively is exercised with a stand-in
    for the call it would make.
    """
    environment = dict(environ(env))
    use_exec = (not is_windows()) if replace is None else replace
    executable = str(argv[0])
    if use_exec:
        do_exec = execv if execv is not None else os.execve
        try:
            do_exec(executable, [str(part) for part in argv], environment)
        except OSError:
            # The kernel refused to replace this process. Starting a child is a
            # worse shape but a working one.
            pass
        else:
            # os.execve does not return. A stand-in used in a test might.
            return EXIT_OK
    return _spawn_and_wait(
        argv,
        environment,
        spawn=spawn if spawn is not None else subprocess.Popen,
        set_handler=set_handler if set_handler is not None else signal.signal,
    )


def toolchain_program(resolution: Resolution, name: str) -> Path | None:
    """Return the path to one program inside the resolved toolchain."""
    if resolution.path is None:
        return None
    return find_program(resolution.path, name)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the s0ma MCP server. This is what the plugin and the extension run.

    Nothing here installs anything: an MCP server has thirty seconds to answer
    its first message, and a cold install of s0ma can take longer than that
    (plan section 4.4). When there is nothing to run, the built-in stub server
    answers in the session instead, so Claude can explain the situation to the
    person rather than showing them a server that would not start.
    """
    del args
    resolution = resolve_toolchain()
    program = toolchain_program(resolution, MCP_PROGRAM)
    if program is None:
        return _serve_without_toolchain(resolution)
    # Decision CD-3: start what is installed now, and - only for a copy the
    # launcher looks after, only when updates are on, only when there is a key,
    # and only once a day - leave a process behind to fetch a newer one for the
    # next session. It is started BEFORE the hand-off because on POSIX the
    # hand-off replaces this process and nothing after it ever runs.
    maybe_start_background_update(resolution)
    return hand_off([str(program)])


def _serve_without_toolchain(resolution: Resolution) -> int:
    """What ``serve`` does when there is no s0ma to start: speak MCP itself.

    The reason and the next step are said once on stderr, so that anyone reading
    the host's server log sees plainly what happened. Then the built-in stub
    server (:func:`serve_stub`) takes the conversation: it completes the
    handshake at once and tells Claude, in the session, that s0ma is not
    installed yet and that ``/s0ma:setup`` fixes it.

    Nothing is installed and nothing is fetched on this path - see
    :func:`cmd_serve` for why - and the run ends with :data:`EXIT_OK` when the
    host closes the conversation.
    """
    say(resolution.reason)
    say(next_step(resolution))
    return serve_stub(sys.stdin, sys.stdout, resolution=resolution)


# ---------------------------------------------------------------------------
# The built-in stub server: what answers when there is no s0ma to start.
#
# This is the whole of section 4.4's second case. An MCP server has about thirty
# seconds to answer its first message and a cold install of s0ma takes longer,
# so installing on this path is out of the question. Instead the launcher
# becomes the server for one session: it answers the handshake at once, says in
# its `instructions` what is missing and how to fix it, and offers one read-only
# tool that repeats those facts when Claude asks for them.
#
# It installs nothing, opens no socket, contacts nobody, and never says more
# about a license key than `status` does: whether there is one, and its last four
# characters.
# ---------------------------------------------------------------------------


#: The protocol revisions this stub speaks, newest first. This is exactly the
#: set the MCP Python SDK (1.27.2) supports, which is what the real ``s0ma-mcp``
#: server speaks, so a host that can talk to one can talk to the other.
STUB_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

#: What an `initialize` that asks for something unknown is answered with.
STUB_LATEST_PROTOCOL_VERSION = STUB_PROTOCOL_VERSIONS[0]

#: How the stub introduces itself. The name matches the real server's, because
#: to the host this *is* the s0ma server; the version says plainly that it is
#: not the real one.
STUB_SERVER_NAME = "s0ma"
STUB_SERVER_TITLE = "s0ma (setup needed)"
STUB_SERVER_VERSION = "0.0.0-setup-stub"

#: The one tool the stub offers.
STUB_TOOL_NAME = "s0ma_setup_status"
STUB_TOOL_TITLE = "s0ma setup status"
STUB_TOOL_DESCRIPTION = (
    "Report whether s0ma is installed on this machine, which copy of s0ma would "
    "run in this project and why, and the one thing to do next. Reads a few "
    "files and changes nothing."
)

#: JSON-RPC 2.0 framing and the error codes that specification reserves.
JSONRPC_VERSION = "2.0"
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602

#: How much of the client's own wording is quoted back in an error message.
_QUOTE_LIMIT = 60


@dataclass
class StubContext:
    """What the stub needs to answer, gathered once when the session starts.

    *resolution* is why there is nothing to run, and is what the ``instructions``
    are built from. The rest are the seams the tests use: the same three
    arguments :func:`status_report` takes, so a test can point the stub at a
    throwaway state directory without touching the machine's real one.
    """

    resolution: Resolution
    env: Mapping[str, str] | None = None
    home: Path | None = None
    project: Path | None = None


def _quote(text: str, limit: int = _QUOTE_LIMIT) -> str:
    """Shorten something the client said before quoting it back at them."""
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def negotiate_protocol_version(requested: object) -> str:
    """Choose the protocol revision to answer an ``initialize`` with.

    The rule is the specification's: if the server supports the version the
    client asked for it must answer with that same version, and otherwise with
    another version it supports - which should be the newest one it has.
    """
    if isinstance(requested, str) and requested in STUB_PROTOCOL_VERSIONS:
        return requested
    return STUB_LATEST_PROTOCOL_VERSION


def stub_instructions(resolution: Resolution) -> str:
    """The two sentences Claude reads before anything else in the session.

    Tool search is on by default in Claude Code, so the tools themselves are not
    in the model's context at the start - this field is (plan section 1.2, fact
    10). It therefore has to carry the whole situation on its own: what is
    missing, in the launcher's own words, and the one thing the person can do
    about it.
    """
    reason = resolution.reason.strip()
    if reason.endswith("."):
        reason = reason[:-1]
    return (
        f"{reason}, so none of s0ma's own tools are available in this session "
        "and this server can only report on that. Tell the person to run "
        "/s0ma:setup, which installs s0ma and shows them where their license key "
        "goes, and then to restart this server - starting a new session is "
        "enough - so the real s0ma takes over."
    )


def stub_server_info() -> dict[str, Any]:
    """How the stub names itself in the handshake."""
    return {
        "name": STUB_SERVER_NAME,
        "title": STUB_SERVER_TITLE,
        "version": STUB_SERVER_VERSION,
    }


def stub_tool() -> dict[str, Any]:
    """The one tool this server offers.

    The hints say what they mean: it reads and reports, it destroys nothing,
    asking twice gives the same answer, and it talks to nothing outside this
    machine. Anthropic's plugin directory requires a title and a read-only or
    destructive hint on every tool, and this is the shape that satisfies it.
    ``annotations.title`` is the older spelling of the same thing and is carried
    too, for hosts that read that one.
    """
    return {
        "name": STUB_TOOL_NAME,
        "title": STUB_TOOL_TITLE,
        "description": STUB_TOOL_DESCRIPTION,
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "annotations": {
            "title": STUB_TOOL_TITLE,
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }


def stub_status_text(report: Mapping[str, Any]) -> str:
    """The tool's answer: the same facts ``status`` prints, plus what to do now.

    The report is taken fresh on every call, so a person who runs ``/s0ma:setup``
    in the middle of a session and then asks again is told that s0ma has arrived
    and that restarting is all that is left.
    """
    if report["resolved"]["path"]:
        lead = (
            "s0ma is installed on this machine now, but this session is still "
            "running the setup helper. Start a new session, and the real s0ma "
            "will answer instead."
        )
    else:
        lead = (
            "s0ma is not running in this session. This is its setup helper "
            "answering in its place, and here is everything it can see."
        )
    return "\n".join([lead, "", *status_lines(report)])


def stub_text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    """Wrap *text* as a tool result: one text block, and whether it went wrong."""
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def jsonrpc_result(message_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    """A JSON-RPC answer carrying *result*."""
    return {"jsonrpc": JSONRPC_VERSION, "id": message_id, "result": dict(result)}


def jsonrpc_error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    """A JSON-RPC answer carrying a failure.

    *message_id* is ``None`` when the line was too broken to find one in, which
    is what the JSON-RPC specification asks for.
    """
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": message_id,
        "error": {"code": code, "message": message},
    }


def stub_initialize_result(
    params: Mapping[str, Any], resolution: Resolution
) -> dict[str, Any]:
    """Answer ``initialize``: the agreed version, what we offer, and who we are."""
    return {
        "protocolVersion": negotiate_protocol_version(params.get("protocolVersion")),
        # Only tools. No prompts, no resources, no logging, no completions - a
        # capability this server does not declare is one Claude will not ask for.
        "capabilities": {"tools": {}},
        "serverInfo": stub_server_info(),
        "instructions": stub_instructions(resolution),
    }


def stub_call_tool(
    message_id: Any, params: Mapping[str, Any], context: StubContext
) -> dict[str, Any]:
    """Answer ``tools/call``.

    A call without a tool name is malformed, and gets the protocol's own answer
    for that. A call naming a tool that is not here gets a *result* that says so
    rather than a protocol error: the MCP Python SDK answers an unknown tool the
    same way, and a result reaches the model with its wording intact, which is
    the only way this server can do its job.
    """
    name = params.get("name")
    if not isinstance(name, str) or not name:
        return jsonrpc_error(
            message_id,
            JSONRPC_INVALID_PARAMS,
            "A tool call has to say which tool to call.",
        )
    if name != STUB_TOOL_NAME:
        return jsonrpc_result(
            message_id,
            stub_text_result(
                f"There is no tool called `{_quote(name)}` in this session. s0ma "
                f"is not installed yet, so the only tool here is {STUB_TOOL_NAME}, "
                "which reports on that. Run /s0ma:setup to install s0ma, then "
                "start a new session to get s0ma's own tools.",
                is_error=True,
            ),
        )
    report = status_report(context.env, context.home, context.project)
    return jsonrpc_result(message_id, stub_text_result(stub_status_text(report)))


def stub_answer(message: object, context: StubContext) -> dict[str, Any] | None:
    """Work out what to send back for one parsed message, or ``None`` for silence.

    Silence is the right answer to three things: a notification (the protocol
    forbids answering one), a response to a request this server never sent, and
    a blank line. Everything else gets either a result or a JSON-RPC error, and
    nothing raises.
    """
    if isinstance(message, list):
        # Batches were part of JSON-RPC and were removed from MCP in revision
        # 2025-06-18. Nothing this stub supports sends them.
        return jsonrpc_error(
            None,
            JSONRPC_INVALID_REQUEST,
            "This server takes one message per line, not a batch.",
        )
    if not isinstance(message, dict):
        return jsonrpc_error(
            None, JSONRPC_INVALID_REQUEST, "A message has to be a JSON object."
        )
    if "result" in message or "error" in message:
        return None
    is_request = "id" in message
    method = message.get("method")
    if not isinstance(method, str) or not method:
        if not is_request:
            return None
        return jsonrpc_error(
            None, JSONRPC_INVALID_REQUEST, "A request has to name a method."
        )
    if not is_request:
        return None

    message_id = message["id"]
    # The protocol forbids a null id on a request, and a boolean is an integer
    # in Python but not a number anyone means.
    if isinstance(message_id, bool) or not isinstance(message_id, (str, int)):
        return jsonrpc_error(
            None,
            JSONRPC_INVALID_REQUEST,
            "A request needs an id that is a string or a number.",
        )

    raw_params = message.get("params")
    if raw_params is None:
        params: dict[str, Any] = {}
    elif isinstance(raw_params, dict):
        params = raw_params
    else:
        return jsonrpc_error(
            message_id, JSONRPC_INVALID_PARAMS, "The params have to be a JSON object."
        )

    if method == "initialize":
        return jsonrpc_result(
            message_id, stub_initialize_result(params, context.resolution)
        )
    if method == "ping":
        return jsonrpc_result(message_id, {})
    if method == "tools/list":
        return jsonrpc_result(message_id, {"tools": [stub_tool()]})
    if method == "tools/call":
        return stub_call_tool(message_id, params, context)
    return jsonrpc_error(
        message_id,
        JSONRPC_METHOD_NOT_FOUND,
        f"This server cannot do `{_quote(method)}`. s0ma is not installed yet, so "
        "the setup helper is answering, and it only knows initialize, ping, "
        "tools/list and tools/call.",
    )


def stub_answer_line(line: str, context: StubContext) -> dict[str, Any] | None:
    """Turn one line of input into the object to send back, or ``None``."""
    text = line.strip()
    if not text:
        return None
    try:
        message = json.loads(text)
    except ValueError:
        return jsonrpc_error(
            None, JSONRPC_PARSE_ERROR, "That line could not be read as JSON."
        )
    return stub_answer(message, context)


def _prepare_stream(stream: Any, *, newline: str | None = None) -> None:
    """Ask a text stream to speak UTF-8, when it is the kind that can be asked.

    Protocol messages must be UTF-8. A Windows console hands Python a stream in
    the machine's code page instead, which would mangle anything outside it, and
    would turn every ``\\n`` this server writes into ``\\r\\n``. Anything that
    cannot be reconfigured - a stream a test supplies, a stream a host has
    already wrapped - is left exactly as it is.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        if newline is None:
            reconfigure(encoding="utf-8", errors="replace")
        else:
            reconfigure(encoding="utf-8", errors="replace", newline=newline)
    except (OSError, ValueError, TypeError):
        # A stream that has already been read from, or one that is not a text
        # wrapper at all. Speaking to it as it is beats refusing to speak.
        pass


def write_stub_message(stream: Any, message: Mapping[str, Any]) -> bool:
    """Write one protocol message and push it out; ``False`` when the pipe is gone.

    One JSON object, one line, terminated with ``\\n`` and flushed at once - a
    message that sits in a buffer is a message the host is still waiting for.
    ``ensure_ascii`` keeps every byte on the wire inside ASCII and, with the
    compact separators, guarantees there is no newline anywhere inside the
    object: the transport forbids one.
    """
    text = json.dumps(message, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    try:
        stream.write(text + "\n")
        stream.flush()
    except (BrokenPipeError, OSError, ValueError):
        return False
    return True


def serve_stub(
    input_stream: Any,
    output_stream: Any,
    *,
    resolution: Resolution | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    project: Path | None = None,
) -> int:
    """Be the s0ma MCP server for one session, and return the exit code.

    Reads newline-delimited JSON-RPC from *input_stream* and writes the same to
    *output_stream*, one object per line, flushed every time. The end of the
    input is the end of the session and is not a failure: the host closes that
    stream to ask the server to stop, so the answer is :data:`EXIT_OK`.

    **Protocol revisions.** This implements the Model Context Protocol
    initialization handshake and the tools methods as specified in revision
    ``2025-11-25`` (lifecycle, transports and server/tools pages, read at
    modelcontextprotocol.io on 2026-09-17), and negotiates down to the earlier
    revisions ``2025-06-18``, ``2025-03-26`` and ``2024-11-05`` - the same set
    the MCP Python SDK the real ``s0ma-mcp`` server is built on supports, so the
    stub and the real server look the same to a host. The published
    specification has since moved on to revision ``2026-07-28``, which drops the
    handshake in favour of per-request metadata and a ``server/discover`` method;
    that revision documents how a client meets a server like this one, which
    answers ``server/discover`` with a plain method-not-found and is then spoken
    to in the older way.

    Methods answered: ``initialize``, ``ping``, ``tools/list`` and
    ``tools/call``. Notifications, ``notifications/initialized`` among them, are
    taken and never answered. Anything else gets a method-not-found error that
    says what this server is, in words a model can pass on to a person.

    The stub deliberately answers whatever arrives, in any order, rather than
    insisting on ``initialize`` first: its whole job is to be useful to a host
    that is already confused about the state of this machine.
    """
    context = StubContext(
        resolution=(
            resolve_toolchain(env, home, project) if resolution is None else resolution
        ),
        env=env,
        home=home,
        project=project,
    )
    _prepare_stream(input_stream)
    _prepare_stream(output_stream, newline="\n")
    while True:
        try:
            line = input_stream.readline()
        except (OSError, ValueError):
            # The input has gone away, or was never readable. There is nothing
            # left to serve, and that is not an error.
            return EXIT_OK
        if not line:
            return EXIT_OK
        answer = stub_answer_line(line, context)
        if answer is None:
            continue
        if not write_stub_message(output_stream, answer):
            return EXIT_OK


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    """Run one of the toolchain's own programs, for example ``s0ma doctor``.

    The first word after ``--`` is the program's name inside the toolchain, and
    everything after it is passed on untouched. Only a plain name is accepted:
    the launcher runs the s0ma that it resolved, and nothing else on the
    machine.
    """
    child: list[str] = list(args.child_argv or [])
    if not child:
        say(f"`{PROG} run` needs a command, for example: {PROG} run -- s0ma doctor")
        return EXIT_USAGE
    name = child[0]
    if not _PROGRAM_NAME_RE.match(name):
        say(
            f"`{name}` is not the name of a s0ma command. Give a plain name, for "
            f"example: {PROG} run -- s0ma doctor"
        )
        return EXIT_USAGE

    resolution = resolve_toolchain()
    if not resolution.found:
        say(resolution.reason)
        say(next_step(resolution))
        return EXIT_NOT_INSTALLED
    program = toolchain_program(resolution, name)
    if program is None:
        where = fwd(resolution.path) if resolution.path is not None else "its own folder"
        say(
            f"This copy of s0ma does not provide a command called `{name}`. "
            f"It lives in {where} if you want to look."
        )
        return EXIT_NOT_INSTALLED
    return hand_off([str(program), *child[1:]])


# ---------------------------------------------------------------------------
# Talking to the control plane.
#
# This is the conversation the keyed installer (`scripts/install.sh`) has today,
# moved into Python: ask for the manifest, read the wheels it names and the
# sha256 hash of each, fetch them, and check that what arrived is what was
# described. Three rules hold everywhere in this section.
#
# * The key travels in exactly one place: the `Authorization` header. Never in a
#   URL - URLs are written down by proxies, by servers and by us - never on a
#   command line, where every process on the machine can read it, never in a
#   message, and never in the update log.
# * https, or a loopback address, or nothing. The launcher's own tests run a
#   control plane on 127.0.0.1 over plain http; any other host is reached over
#   https or refused, because a key in a header on a plain connection is a key
#   given away.
# * Every answer has a sentence a person can act on and an exit code
#   (plan section 4.3), and the ones that say something about the subscription
#   also say what to record in `state.json`.
# ---------------------------------------------------------------------------


def _timeout(given: float | None, fallback: float) -> float:
    """The number of seconds one request may take."""
    return fallback if given is None else given


def is_loopback_host(hostname: str) -> bool:
    """Whether *hostname* is this machine talking to itself."""
    name = hostname.strip().strip("[]").lower()
    if not name:
        return False
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def cp_base_url(host: str) -> str:
    """Turn the configured host into the address the launcher will call.

    A bare host name is always reached over https. A value that carries a
    scheme keeps it, with one exception that exists for the tests and for a
    local control plane: plain http is allowed only when the host is this
    machine itself. Anything else carrying http is refused, loudly, rather than
    quietly sending a license key across a network in the clear.
    """
    text = host.strip().rstrip("/")
    if not text:
        raise LauncherError(
            EXIT_USAGE,
            "There is no control-plane host to ask. Unset S0MA_CP_HOST to use "
            f"the usual one ({DEFAULT_CP_HOST}).",
        )
    if "://" not in text:
        return "https://" + text
    split = urllib.parse.urlsplit(text)
    scheme = split.scheme.lower()
    if scheme == "https":
        return text
    if scheme != "http":
        raise LauncherError(
            EXIT_USAGE,
            f"s0ma can only talk to a control plane over https, and `{text}` "
            "asks for something else.",
        )
    if is_loopback_host(split.hostname or ""):
        return text
    raise LauncherError(
        EXIT_USAGE,
        f"`{text}` asks s0ma to send your license key over a plain, unencrypted "
        "connection to another machine, which it will not do. Use https for "
        "anything that is not this machine itself.",
    )


def manifest_url(base: str, version: str | None = None) -> str:
    """The address of the manifest for *version* (the newest one by default)."""
    wanted = version.strip() if version else "latest"
    return base + "/api/dist/manifest?" + urllib.parse.urlencode({"version": wanted})


def key_check_url(base: str) -> str:
    """The address that answers "is this key any good?"."""
    return base + "/api/key/check"


def wheel_url(base: str, path: str) -> str:
    """The address of one wheel, from the path the manifest gave for it."""
    quoted = "/".join(urllib.parse.quote(part) for part in path.split("/"))
    return base + "/" + quoted


def plain_sentence(text: object, *, limit: int = 300) -> str | None:
    """Make something the control plane said safe to print, or ``None``.

    The control plane's own wording - a ``notice`` on a key check, a
    ``remediation`` on a refusal - is shown to the person as it was written, so
    it is first reduced to printable ASCII on a single line of sensible length.
    Text that arrived over a network is not allowed to move the cursor, clear
    the screen, or run on for a thousand characters.
    """
    if not isinstance(text, str):
        return None
    kept = "".join(character if 32 <= ord(character) < 127 else " " for character in text)
    kept = " ".join(kept.split())
    if not kept:
        return None
    if len(kept) > limit:
        return kept[:limit].rstrip() + "..."
    return kept


def _headers_of(response: Any) -> dict[str, str]:
    """The response's headers, lower-cased, and never an exception."""
    headers = getattr(response, "headers", None)
    if headers is None:
        return {}
    try:
        return {str(name).lower(): str(value) for name, value in headers.items()}
    except (AttributeError, TypeError):  # pragma: no cover - not a real response
        return {}


def _retry_after_words(headers: Mapping[str, str]) -> str:
    """"It suggested about a minute." - or nothing, when it suggested nothing."""
    value = headers.get("retry-after", "").strip()
    if not value.isdigit():
        return ""
    seconds = int(value)
    if seconds <= 0:
        return ""
    if seconds < 90:
        return f" It asked for about {seconds} seconds."
    return f" It asked for about {max(1, round(seconds / 60))} minutes."


def _json_object(raw: bytes) -> dict[str, Any] | None:
    """Read an answer as one JSON object, or ``None`` when it is not one."""
    try:
        parsed = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def cp_failure(
    status: int, body: dict[str, Any] | None, headers: Mapping[str, str], base: str
) -> ControlPlaneError:
    """Turn a refusal into the sentence and the exit code it deserves.

    The control plane answers every failure the same way - a JSON object with
    ``ok: false``, a ``code`` and a ``remediation`` - so the code is what is read
    here, with the HTTP status as the fallback for a body that did not arrive.
    Its ``remediation`` is shown after our own sentence, never instead of it.
    """
    code = ""
    if body is not None and isinstance(body.get("code"), str):
        code = str(body["code"]).strip().upper()
    notice = plain_sentence(body.get("remediation")) if body is not None else None

    if code == "INVALID_KEY" or (not code and status == 401):
        return ControlPlaneError(
            EXIT_NO_KEY, KEY_REFUSED_MESSAGE, entitlement="invalid_key", notice=notice
        )
    if code == "NOT_ENTITLED" or (not code and status == 403):
        return ControlPlaneError(
            EXIT_NO_KEY,
            "This account's access to new versions of s0ma has ended, so there "
            "is nothing new to fetch. The copy of s0ma on this machine keeps "
            "working exactly as it is.\n"
            f"To see what happened, or to start again, go to {base}.",
            entitlement="not_entitled",
            notice=notice,
        )
    if code == "RATE_LIMITED" or (not code and status == 429):
        return ControlPlaneError(
            EXIT_NETWORK,
            "s0ma's control plane is busy and asked this machine to wait, so "
            "nothing was fetched this time. Try again in a little while - the "
            "copy of s0ma on this machine keeps working." + _retry_after_words(headers),
            notice=notice,
        )
    if code == "NOT_FOUND" or (not code and status == 404):
        return ControlPlaneError(
            EXIT_USAGE,
            "The s0ma control plane has no such version. Run `s0ma-launch "
            "install` with no version to get the newest one, or check the "
            "version number you asked for.",
            notice=notice,
        )
    named = code or f"HTTP {status}"
    return ControlPlaneError(
        EXIT_NETWORK,
        f"s0ma's control plane could not answer that request ({named}), so "
        "nothing was fetched. The copy of s0ma on this machine keeps working; "
        "try again in a little while.",
        notice=notice,
    )


def cp_unreachable(base: str, reason: str) -> ControlPlaneError:
    """The answer when there was no answer at all."""
    return ControlPlaneError(
        EXIT_NETWORK,
        f"s0ma could not reach its control plane at {base} ({reason}), so it "
        "could not check for new versions. The copy of s0ma on this machine "
        "keeps working; try again when the network is back.",
    )


def _reason_of(error: BaseException) -> str:
    """One short, printable phrase for why a request did not happen."""
    inner = getattr(error, "reason", None)
    text = str(inner if inner is not None else error)
    if isinstance(error, TimeoutError) or "timed out" in text.lower():
        return "it took too long to answer"
    return plain_sentence(text, limit=80) or "no answer"


def cp_open(
    url: str,
    key: str,
    base: str,
    *,
    timeout: float,
    opener: Callable[..., Any] | None = None,
) -> tuple[int, Any]:
    """Make one request with the key in its header; return the status and the body.

    The body is the live response object: JSON answers are small and are read
    whole, and a wheel is read in pieces straight to disk, so neither is ever
    held in memory in full. A refusal is a readable object too - the control
    plane's failures carry a JSON body worth reading.
    """
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", "Bearer " + key)
    request.add_header("Accept", "*/*")
    request.add_header("User-Agent", PROG)
    perform = _cp_opener().open if opener is None else opener
    try:
        response = perform(request, timeout=timeout)
    except urllib.error.HTTPError as refusal:
        return int(refusal.code), refusal
    except (urllib.error.URLError, TimeoutError, OSError) as failure:
        raise cp_unreachable(base, _reason_of(failure)) from failure
    status = int(getattr(response, "status", 0) or 200)
    return status, response


class _SameOriginRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but never carry the key to a different host.

    ``urllib`` copies a request's headers onto the redirected request, which
    would hand the license key to whatever host a redirect names. A redirect
    that stays on the same host keeps the header; anything else loses it, so
    the worst a hijacked redirect can do is fail.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        followed = super().redirect_request(req, fp, code, msg, headers, newurl)
        if followed is None:
            return None
        if _origin_of(newurl) != _origin_of(req.full_url):
            followed.remove_header("Authorization")
        return followed


def _origin_of(url: str) -> tuple[str, str, int | None]:
    """The scheme, host and port of *url*, for comparing two of them."""
    split = urllib.parse.urlsplit(url)
    port: int | None
    try:
        port = split.port
    except ValueError:
        port = None
    return split.scheme.lower(), (split.hostname or "").lower(), port


def _cp_opener() -> urllib.request.OpenerDirector:
    """The opener every control-plane request goes through.

    Built here rather than taken from ``urllib.request.urlopen`` so that the
    redirect handler above is the one in use, and so that no proxy or
    authentication handler a host has installed globally can join in.
    """
    return urllib.request.build_opener(
        _SameOriginRedirects(), urllib.request.HTTPSHandler()
    )


def cp_get_json(
    url: str,
    key: str,
    base: str,
    *,
    timeout: float | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Ask for one JSON answer, or raise the failure it deserves."""
    status, response = cp_open(
        url, key, base, timeout=_timeout(timeout, CP_TIMEOUT_SECONDS), opener=opener
    )
    headers = _headers_of(response)
    try:
        try:
            raw = response.read(MAX_JSON_BYTES)
        except (OSError, ValueError) as failure:
            raise cp_unreachable(base, _reason_of(failure)) from failure
    finally:
        _close_quietly(response)
    body = _json_object(raw if isinstance(raw, bytes) else bytes(raw))
    if status != 200:
        raise cp_failure(status, body, headers, base)
    if body is None:
        raise ControlPlaneError(
            EXIT_NETWORK,
            "s0ma's control plane answered with something it could not read, so "
            "nothing was fetched. Try again in a little while.",
        )
    return body


def _close_quietly(response: Any) -> None:
    """Close a response, whatever it is, without ever raising."""
    closer = getattr(response, "close", None)
    if closer is None:
        return
    try:
        closer()
    except (OSError, ValueError):  # pragma: no cover - a stand-in in a test
        pass


# ---------------------------------------------------------------------------
# The manifest: what a version of s0ma is made of.
#
# The control plane answers `/api/dist/manifest?version=latest|X.Y.Z` with the
# version that request resolved to and one entry per wheel:
#
#     {"version": "0.18.0",
#      "wheels": [{"name": "s0ma_core-0.18.0-py3-none-any.whl",
#                  "path": "dist/0.18.0/s0ma_core-0.18.0-py3-none-any.whl",
#                  "sha256": "...", "size": 12345}, ...]}
#
# Everything in it arrived over a network, so everything in it is checked: a
# name that is not a plain filename, a path that tries to climb out of the
# downloads directory, or a missing hash all stop the install rather than
# being worked around.
# ---------------------------------------------------------------------------

_WHEEL_NAME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._+-]*\.whl\Z")
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class Wheel:
    """One file the manifest names, and what it must hash to."""

    name: str
    path: str
    sha256: str
    size: int | None


@dataclass(frozen=True)
class Manifest:
    """What one version of s0ma is made of.

    *version* is the version this answer is about - what ``latest`` resolved to,
    when that is what was asked for. *latest* is what the control plane calls
    its newest version, when it says so at all; asking about an older version on
    purpose must not leave this machine thinking that one is the newest there
    is. *notice* is the control plane's own sentence for the person, when it
    sent one: passed on word for word, after whatever the launcher itself had to
    say, and never instead of it.
    """

    version: str
    wheels: tuple[Wheel, ...]
    latest: str | None = None
    notice: str | None = None

    def named(self, stem: str) -> Wheel | None:
        """The wheel for one distribution, or ``None`` when it is not here."""
        for wheel in self.wheels:
            if wheel.name.startswith(stem + "-"):
                return wheel
        return None


def _manifest_problem(detail: str) -> ControlPlaneError:
    return ControlPlaneError(
        EXIT_NETWORK,
        "s0ma's control plane described this version in a way the launcher "
        f"could not use ({detail}), so nothing was fetched. Try again in a "
        "little while, and tell us if it keeps happening.",
    )


def parse_manifest(body: Mapping[str, Any]) -> Manifest:
    """Read a manifest answer, or say exactly what was wrong with it."""
    raw_version = body.get("version")
    if not isinstance(raw_version, str) or not looks_like_version(raw_version.strip()):
        raw_version = body.get("latest")
    if not isinstance(raw_version, str) or not looks_like_version(raw_version.strip()):
        raise _manifest_problem("it names no version")
    version = raw_version.strip()

    entries = body.get("wheels")
    if not isinstance(entries, list) or not entries:
        raise _manifest_problem("it lists no files")

    wheels: list[Wheel] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise _manifest_problem("one of its entries is not an object")
        name = entry.get("name")
        path = entry.get("path")
        digest = entry.get("sha256")
        if not isinstance(name, str) or not _WHEEL_NAME_RE.match(name.strip()):
            raise _manifest_problem("one of its entries has no usable filename")
        if not isinstance(path, str) or not _safe_relative_path(path.strip()):
            raise _manifest_problem(f"the path it gives for {name.strip()} is not usable")
        if not isinstance(digest, str) or not _SHA256_RE.match(digest.strip().lower()):
            raise _manifest_problem(f"it carries no checksum for {name.strip()}")
        size = entry.get("size")
        wheels.append(
            Wheel(
                name=name.strip(),
                path=path.strip(),
                sha256=digest.strip().lower(),
                size=size if isinstance(size, int) and not isinstance(size, bool) else None,
            )
        )
    offered = body.get("latest")
    return Manifest(
        version=version,
        wheels=tuple(wheels),
        latest=(
            offered.strip()
            if isinstance(offered, str) and looks_like_version(offered.strip())
            else None
        ),
        notice=plain_sentence(body.get("notice")),
    )


def _safe_relative_path(path: str) -> bool:
    """Whether a path from the manifest may be joined onto the host's address."""
    if not path or path.startswith("/") or "\\" in path or "://" in path:
        return False
    parts = path.split("/")
    return all(part and part not in (".", "..") for part in parts)


def wheels_to_install(manifest: Manifest) -> list[Wheel]:
    """The four wheels a copy of s0ma is made of, in a fixed order."""
    chosen: list[Wheel] = []
    for stem in WHEEL_STEMS:
        wheel = manifest.named(stem)
        if wheel is None:
            raise _manifest_problem(f"it does not include {stem}")
        chosen.append(wheel)
    return chosen


def fetch_manifest(
    base: str,
    key: str,
    *,
    version: str | None = None,
    timeout: float | None = None,
    opener: Callable[..., Any] | None = None,
) -> Manifest:
    """Ask the control plane what a version of s0ma is made of."""
    body = cp_get_json(
        manifest_url(base, version), key, base, timeout=timeout, opener=opener
    )
    return parse_manifest(body)


# ---------------------------------------------------------------------------
# Downloading and checking one file.
#
# A wheel is written to a temporary name beside its final one and hashed as it
# arrives, so a file that appears under its proper name in `downloads/` has
# already been proven to be the file the control plane described. That is also
# why a file already sitting there can be re-used without asking for it again:
# its presence under that name means it was checked.
# ---------------------------------------------------------------------------


def sha256_of_file(path: Path) -> str:
    """The sha256 of a file, read in pieces so a large one costs nothing."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _no_progress(message: str) -> None:
    """Where progress goes when nobody asked for any."""


def _verification_failed(name: str) -> LauncherError:
    return LauncherError(
        EXIT_VERIFY_FAILED,
        f"The file {name} that arrived is not the file s0ma's control plane "
        "described, so it was deleted and the install stopped. Nothing has been "
        "installed and nothing has changed.\n"
        "This is nearly always a download that was cut short - try again.",
    )


def download_wheel(
    base: str,
    key: str,
    wheel: Wheel,
    into: Path,
    *,
    timeout: float | None = None,
    opener: Callable[..., Any] | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Fetch one wheel into *into* and return the file, or raise.

    A file already there under the right name is checked rather than trusted,
    and re-fetched if it has been damaged since. A file that arrives wrong is
    deleted before anything else happens, so a second attempt starts clean.
    """
    into.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(into, DIR_MODE)
    target = into / wheel.name
    note = _no_progress if progress is None else progress

    if target.is_file():
        try:
            if sha256_of_file(target) == wheel.sha256:
                note(f"  already here: {wheel.name}")
                return target
        except OSError:
            pass

    digest = hashlib.sha256()
    written = 0
    status, response = cp_open(
        wheel_url(base, wheel.path),
        key,
        base,
        timeout=_timeout(timeout, DOWNLOAD_TIMEOUT_SECONDS),
        opener=opener,
    )
    try:
        if status != 200:
            headers = _headers_of(response)
            try:
                raw = response.read(MAX_JSON_BYTES)
            except (OSError, ValueError):  # pragma: no cover - a body that vanished
                raw = b""
            raise cp_failure(status, _json_object(raw), headers, base)
        # Created only once there is something to put in it, so a failed
        # request never leaves a scrap of a file behind.
        handle_fd, temporary = tempfile.mkstemp(
            dir=str(into), prefix=wheel.name + ".", suffix=".part"
        )
        temporary_path = Path(temporary)
        try:
            with os.fdopen(handle_fd, "wb") as out:
                handle_fd = -1
                while True:
                    try:
                        chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                    except (OSError, ValueError) as failure:
                        raise cp_unreachable(base, _reason_of(failure)) from failure
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_WHEEL_BYTES:
                        raise _verification_failed(wheel.name)
                    digest.update(chunk)
                    out.write(chunk)
        except BaseException:
            if handle_fd != -1:  # pragma: no cover - fdopen itself failed
                os.close(handle_fd)
            temporary_path.unlink(missing_ok=True)
            raise
    finally:
        _close_quietly(response)

    if digest.hexdigest() != wheel.sha256:
        temporary_path.unlink(missing_ok=True)
        raise _verification_failed(wheel.name)
    os.replace(temporary_path, target)
    _chmod_best_effort(target, 0o644)
    note(f"  got {wheel.name} and checked it")
    return target


# ---------------------------------------------------------------------------
# Installing a version: from four checked files to a copy of s0ma that runs.
#
# Each version gets its own Python environment under `toolchains/<version>/`,
# built beside the finished name as `<version>.partial` and moved into place in
# one step. Two things make that safe:
#
# * `uv venv --relocatable` - the programs inside a virtual environment normally
#   carry the absolute path of the environment that made them, so moving the
#   directory would break every one of them. A relocatable environment finds
#   itself instead, so the move at the end costs nothing.
# * The `.complete` marker is written last, and everything that reads installed
#   versions ignores a directory without it. A build that is interrupted - the
#   machine sleeps, the session ends - leaves something that is never used and
#   is swept away by the next run.
#
# The wheels are installed by path, with the package index left ON, because the
# real s0ma wheels depend on packages that come from PyPI. The launcher's own
# tests set `S0MA_LAUNCH_OFFLINE_INSTALL=1`, which adds `--offline`, and use
# stand-in wheels with no dependencies at all - so the tests perform a real
# install without ever touching a network.
# ---------------------------------------------------------------------------

PARTIAL_SUFFIX = ".partial"


def now_seconds() -> int:
    """The current time, in whole seconds. The one clock this file reads."""
    return int(time.time())


def venv_python(root: Path) -> Path | None:
    """The Python interpreter inside the environment at *root*."""
    for directory, name in (("bin", "python"), ("Scripts", "python.exe")):
        candidate = root / directory / name
        if candidate.is_file():
            return candidate
    return None


def child_environment(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment a child process gets: this one, without the key.

    ``uv`` has no use for a license key, and a value that is not passed on is a
    value that cannot be written into a log, a crash report or a lock file by
    something that is not this launcher.
    """
    values = dict(environ(env))
    values.pop(ENV_LICENSE_KEY, None)
    return values


def wants_offline_install(env: Mapping[str, str] | None = None) -> bool:
    """Whether ``uv`` should be told to resolve nothing from the network."""
    return environ(env).get(ENV_OFFLINE_INSTALL, "").strip() == "1"


def _ascii_lines(text: str, limit: int = 12) -> list[str]:
    """The last few lines of a program's output, made safe to print."""
    lines = [plain_sentence(line, limit=200) for line in text.splitlines()]
    kept = [line for line in lines if line]
    return kept[-limit:]


def run_uv(
    uv: Path,
    arguments: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    what: str,
    runner: Callable[..., Any] | None = None,
) -> None:
    """Run one uv command, or raise with what it said when it refused."""
    command = [str(uv), *arguments]
    run = subprocess.run if runner is None else runner
    try:
        finished = run(
            command,
            env=child_environment(env),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as failure:
        raise LauncherError(
            EXIT_NO_UV,
            f"s0ma could not run uv to {what} ({_reason_of(failure)}). "
            "Check that uv is installed and working, then try again.",
        ) from failure
    if int(getattr(finished, "returncode", 0) or 0) == 0:
        return
    detail = _ascii_lines(str(getattr(finished, "stderr", "") or "")) or _ascii_lines(
        str(getattr(finished, "stdout", "") or "")
    )
    raise LauncherError(
        EXIT_NOT_INSTALLED,
        "\n".join(
            [
                f"s0ma could not {what}. Nothing has been installed, and anything "
                "already installed keeps working.",
                "This is what uv said:",
                *(f"  {line}" for line in detail),
            ]
        ),
    )


def _remove_tree(path: Path) -> bool:
    """Delete a directory and everything in it; ``False`` when it would not go."""
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def sweep_unusable(home: Path) -> list[str]:
    """Remove every half-built toolchain directory; return what went.

    A directory that is still being built (``<version>.partial``) or that never
    got its ``.complete`` marker is one nothing will ever run, so it is removed
    at the start of an install rather than left to puzzle someone later. The
    update lock is what makes this safe: no other run can be building one.
    """
    parent = toolchains_dir(home)
    try:
        entries = sorted(parent.iterdir())
    except OSError:
        return []
    removed: list[str] = []
    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name.endswith(PARTIAL_SUFFIX) or not (entry / COMPLETE_MARKER).exists():
            if _remove_tree(entry):
                removed.append(entry.name)
    return removed


def sweep_old_versions(home: Path, keep: Iterable[str]) -> list[str]:
    """Remove installed versions that nothing here needs any more."""
    keeping = {version for version in keep if version}
    removed: list[str] = []
    for version in installed_versions(home):
        if version in keeping:
            continue
        if _remove_tree(managed_toolchain_dir(home, version)):
            removed.append(version)
    return removed


def record_failure(home: Path, failure: LauncherError) -> None:
    """Write down what went wrong, so ``status`` can say it later.

    One sentence, never the whole message, and never anything about a key
    beyond the fact that it was refused: this file is read by the session hint
    and printed back to the person.
    """
    try:
        state = load_state(home)
        entitlement = getattr(failure, "entitlement", None)
        if isinstance(entitlement, str) and entitlement in ENTITLEMENT_WORDS:
            state["entitlement"] = entitlement
        state["last_error"] = plain_sentence(failure.message.splitlines()[0])
        save_state(home, state)
    except OSError:  # pragma: no cover - a state directory that cannot be written
        pass


def install_version(
    home: Path,
    *,
    env: Mapping[str, str] | None = None,
    version: str | None = None,
    key: str | None = None,
    manifest: Manifest | None = None,
    uv: Path | None = None,
    opener: Callable[..., Any] | None = None,
    runner: Callable[..., Any] | None = None,
    timeout: float | None = None,
    progress: Callable[[str], None] = say,
) -> str:
    """Install one version of s0ma and return the version that was installed.

    *version* is a version number, or ``None`` for whichever the control plane
    calls the newest. Everything this does is either complete or invisible: the
    new environment is built under a temporary name and moved into place at the
    end, and the record in ``state.json`` is written once, afterwards.

    Taking the update lock is the caller's job - both callers do - because an
    update takes it once for the whole check-and-install, not twice.
    """
    values = environ(env)
    config = load_config(home)
    base = cp_base_url(cp_host(values, config))
    tool = require_uv(values) if uv is None else uv

    if key is None:
        key, _ = license_key(values, home)
    if not key:
        raise LauncherError(EXIT_NO_KEY, KEY_MISSING_MESSAGE)

    swept = sweep_unusable(home)
    if swept:
        progress(
            f"Cleared away {len(swept)} unfinished install"
            + ("s." if len(swept) != 1 else ".")
        )

    if manifest is None:
        progress(f"Asking {base} which files make up s0ma...")
        manifest = fetch_manifest(
            base, key, version=version, timeout=timeout, opener=opener
        )
        if manifest.notice:
            progress(manifest.notice)
    wheels = wheels_to_install(manifest)
    resolved = manifest.version
    progress(f"s0ma {resolved}: {len(wheels)} files to fetch and check.")

    downloads = downloads_dir(home)
    paths: list[Path] = []
    for wheel in wheels:
        paths.append(
            download_wheel(
                base,
                key,
                wheel,
                downloads,
                timeout=timeout,
                opener=opener,
                progress=progress,
            )
        )

    toolchains_dir(home).mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(toolchains_dir(home), DIR_MODE)
    partial = toolchains_dir(home) / (resolved + PARTIAL_SUFFIX)
    _remove_tree(partial)

    offline = ["--offline"] if wants_offline_install(values) else []
    progress(f"Building a private Python environment for s0ma {resolved}...")
    run_uv(
        tool,
        ["venv", "--relocatable", *offline, str(partial)],
        env=values,
        what=f"make a Python environment for s0ma {resolved}",
        runner=runner,
    )
    interpreter = venv_python(partial)
    if interpreter is None:
        raise LauncherError(
            EXIT_NOT_INSTALLED,
            "uv did not leave a Python behind in the new environment at "
            f"{fwd(partial)}, so s0ma could not be installed into it. Nothing "
            "has changed; try again.",
        )
    progress(f"Installing the {len(paths)} s0ma packages into it...")
    run_uv(
        tool,
        [
            "pip",
            "install",
            "--python",
            str(interpreter),
            *offline,
            *[str(path) for path in paths],
        ],
        env=values,
        what=f"install the s0ma packages for {resolved}",
        runner=runner,
    )

    # Written last, on purpose: until this exists, nothing will run what is in
    # this directory, and the next run sweeps it away.
    (partial / COMPLETE_MARKER).write_text(resolved + "\n", encoding="utf-8", newline="\n")

    final = managed_toolchain_dir(home, resolved)
    if final.exists():
        progress(f"Replacing the copy of s0ma {resolved} that was already here.")
        _remove_tree(final)
    try:
        # Atomic on both platforms - but Windows, unlike POSIX, will not let a
        # directory be replaced while anything inside it is open, and the copy
        # that was here may still be in use by a session that is running.
        os.replace(partial, final)
    except OSError as failure:
        raise LauncherError(
            EXIT_NOT_INSTALLED,
            f"s0ma {resolved} was fetched and built, but it could not be moved "
            f"into place at {fwd(final)} ({_reason_of(failure)}). This usually "
            "means a s0ma that is still running is holding it open: close the "
            "sessions that are using s0ma and try again. Nothing that works "
            "today has been changed.",
        ) from failure

    state = load_state(home)
    state["installed"] = installed_versions(home)
    newest = state["installed"][-1] if state["installed"] else resolved
    state["current"] = newest
    # `latest_seen` is the newest version the control plane has offered, so
    # installing an older one on purpose must not lower it.
    offered = manifest.latest or manifest.version
    seen = state.get("latest_seen")
    if is_newer(offered, seen if isinstance(seen, str) else None):
        state["latest_seen"] = offered
    state["last_check"] = now_seconds()
    state["entitlement"] = "ok"
    state["last_error"] = None
    save_state(home, state)
    return resolved


def cmd_install(args: argparse.Namespace) -> int:
    """Install a version of s0ma, with progress, in the foreground."""
    values = environ()
    home = s0ma_home(values)
    project = project_dir(values)
    wanted = getattr(args, "version", None)
    if wanted is not None and not looks_like_version(str(wanted).strip()):
        say(
            f"`{wanted}` does not look like a version of s0ma. A version looks "
            "like 0.18.0."
        )
        return EXIT_USAGE
    try:
        with UpdateLock(home) as taken:
            if not taken:
                say(
                    "s0ma is already installing itself in another window, so this "
                    "one left it to finish."
                )
                return EXIT_OK
            installed = install_version(home, env=values, version=wanted)
    except LauncherError as failure:
        record_failure(home, failure)
        raise
    say(f"s0ma {installed} is installed.")
    pin = read_pin(project)
    if pin.version and pin.version != installed:
        say(
            f"This project asks for s0ma {pin.version} in its {PIN_FILENAME} file, "
            f"so it keeps using that one. Run `{PROG} unpin` to follow the newest."
        )
    else:
        say("Claude will use it the next time it starts s0ma - start a new session.")
    return EXIT_OK


# ---------------------------------------------------------------------------
# The update lock.
#
# Two Claude sessions can start at the same moment, and both can decide it is
# time to look for a newer s0ma. One lock file makes the second one quiet
# instead of destructive. The lock is advisory and non-blocking on purpose:
# nobody waits for anybody, the second run simply says so and stops.
#
# The two platforms lock differently - `fcntl.flock` on POSIX, `msvcrt.locking`
# on Windows - so both live in one function with two branches, and the module
# is imported by name rather than at the top of this file. That keeps this file
# importable on either platform, keeps it clean under a type check aimed at
# either platform, and lets a test drive the branch this machine does not have.
# ---------------------------------------------------------------------------

#: What ``msvcrt.locking`` is asked to lock. One byte is the usual recipe: the
#: region does not have to exist, and the whole file is never read anyway.
_LOCK_REGION_BYTES = 1


def _lock_module(windows: bool, import_module: Callable[[str], Any]) -> Any:
    """The standard-library module that locks files on this platform."""
    return import_module("msvcrt" if windows else "fcntl")


def take_file_lock(
    fileno: int,
    *,
    windows: bool | None = None,
    import_module: Callable[[str], Any] | None = None,
) -> bool:
    """Take an exclusive lock without waiting; ``False`` when someone has it."""
    on_windows = is_windows() if windows is None else windows
    module = _lock_module(on_windows, import_module or importlib.import_module)
    try:
        if on_windows:
            module.locking(fileno, module.LK_NBLCK, _LOCK_REGION_BYTES)
        else:
            module.flock(fileno, module.LOCK_EX | module.LOCK_NB)
    except OSError:
        return False
    return True


def release_file_lock(
    fileno: int,
    *,
    windows: bool | None = None,
    import_module: Callable[[str], Any] | None = None,
) -> None:
    """Give the lock back. Closing the file would do it too; this is explicit."""
    on_windows = is_windows() if windows is None else windows
    module = _lock_module(on_windows, import_module or importlib.import_module)
    try:
        if on_windows:
            module.locking(fileno, module.LK_UNLCK, _LOCK_REGION_BYTES)
        else:
            module.flock(fileno, module.LOCK_UN)
    except OSError:  # pragma: no cover - the file is closed straight after
        pass


class UpdateLock:
    """Hold the update lock for as long as this object is used as a context.

    ``with UpdateLock(home) as taken:`` - *taken* is ``False`` when another run
    holds it, and the body is expected to do nothing in that case. A lock that
    cannot even be created (a read-only home directory) counts as taken, so the
    work still happens on a machine where locking is not available.
    """

    def __init__(
        self,
        home: Path,
        *,
        windows: bool | None = None,
        import_module: Callable[[str], Any] | None = None,
    ) -> None:
        self.path = update_lock_path(home)
        self.windows = is_windows() if windows is None else windows
        self.import_module = import_module
        self.fileno = -1
        self.taken = False

    def __enter__(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _chmod_best_effort(self.path.parent, DIR_MODE)
            self.fileno = os.open(self.path, os.O_RDWR | os.O_CREAT, FILE_MODE)
        except (OSError, ValueError):
            self.fileno = -1
            self.taken = True
            return True
        self.taken = take_file_lock(
            self.fileno, windows=self.windows, import_module=self.import_module
        )
        if not self.taken:
            os.close(self.fileno)
            self.fileno = -1
        return self.taken

    def __exit__(self, *_exc: Any) -> None:
        if self.fileno == -1:
            return
        release_file_lock(
            self.fileno, windows=self.windows, import_module=self.import_module
        )
        os.close(self.fileno)
        self.fileno = -1


# ---------------------------------------------------------------------------
# Updating: the promise that s0ma keeps itself current without interrupting.
#
# `serve` starts what is installed, then - quietly, in a process of its own that
# outlives the session - looks for something newer and installs it beside the
# old one. Nothing is switched mid-session; the next session starts the new one.
# The previous version is always kept, so going back is one `pin` away.
# ---------------------------------------------------------------------------

#: Windows creation flags. Spelled out rather than read from `subprocess`,
#: because those names exist only on Windows and this file is checked, and read,
#: on both platforms. Values from the Win32 process-creation documentation.
_WIN_DETACHED_PROCESS = 0x00000008
_WIN_CREATE_NEW_PROCESS_GROUP = 0x00000200


def detach_kwargs(*, windows: bool | None = None) -> dict[str, Any]:
    """How to start a process that outlives this one, on this platform.

    POSIX: a new session, so the child is not in the terminal's process group
    and does not die with it. Windows: detached, with a process group of its
    own, so closing the console that started it leaves it running.
    """
    if is_windows() if windows is None else windows:
        return {
            "creationflags": _WIN_DETACHED_PROCESS | _WIN_CREATE_NEW_PROCESS_GROUP
        }
    return {"start_new_session": True}


def rotate_update_log(home: Path, *, limit: int = UPDATE_LOG_LIMIT_BYTES) -> Path:
    """Keep the update log from growing forever; return where it belongs.

    One older file is kept beside it. The file is moved, not copied and
    truncated, so a reader that has it open keeps reading a whole file, and
    nothing here holds it open while it moves - Windows would refuse that. If
    another run has it open at that moment, Windows refuses anyway, and the
    answer is simply to carry on writing to the file that is there.
    """
    path = update_log_path(home)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _chmod_best_effort(path.parent, DIR_MODE)
        if path.is_file() and path.stat().st_size >= limit:
            os.replace(path, path.with_name(path.name + UPDATE_LOG_OLD_SUFFIX))
    except OSError:  # pragma: no cover - a home directory that cannot be written
        pass
    return path


def spawn_background_update(
    home: Path,
    *,
    env: Mapping[str, str] | None = None,
    spawn: Callable[..., Any] | None = None,
    windows: bool | None = None,
    python: str | None = None,
    script: Path | None = None,
) -> bool:
    """Start the quiet update in a process of its own; ``False`` if it did not.

    The child is this same file, run by this same Python, with everything it
    prints going to ``launcher/update.log``. Its environment is inherited
    unchanged - the license key included, because the child is the one that has
    to ask the control plane for anything, and an environment variable is how
    the key reached this process too. It is never a command-line argument.
    """
    log = rotate_update_log(home)
    command = [
        sys.executable if python is None else python,
        str(Path(__file__).resolve() if script is None else script),
        "update",
        "--background",
    ]
    starter = subprocess.Popen if spawn is None else spawn
    try:
        handle = open(log, "a", encoding="utf-8", newline="\n")  # noqa: SIM115
    except OSError:
        return False
    try:
        starter(
            command,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            cwd=str(home),
            env=dict(environ(env)),
            **detach_kwargs(windows=windows),
        )
    except (OSError, ValueError):
        return False
    finally:
        handle.close()
    return True


def maybe_start_background_update(
    resolution: Resolution,
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    spawn: Callable[..., Any] | None = None,
    windows: bool | None = None,
) -> str:
    """Decide whether ``serve`` should start a quiet update, and start it.

    Returns one short word for what was decided, which is what the tests read
    and what a reader of the log can match up. Nothing in here may interrupt a
    session, so nothing in here raises: a failure means no update this time.

    All four conditions have to hold:

    * the copy being started is one the launcher looks after - never a
      contributor's own checkout, never a project's own environment, and never a
      project pinned to a version, because none of those are the launcher's to
      move;
    * updates are not switched off;
    * there is a key, so there is something to ask with;
    * the last check was more than a day ago.
    """
    try:
        values = environ(env)
        base_home = s0ma_home(values) if home is None else home
        if resolution.kind != KIND_MANAGED:
            return "not-managed"
        config = load_config(base_home)
        if update_mode(values, config) == "off":
            return "updates-off"
        state = load_state(base_home)
        pending = state.get("pending")
        if pending and resolution.version and pending == resolution.version:
            # The version a quiet update fetched is the one now starting, so
            # there is nothing waiting any more.
            state["pending"] = None
            save_state(base_home, state)
        key, _ = license_key(values, base_home)
        if not key:
            return "no-key"
        last = state.get("last_check")
        if isinstance(last, (int, float)) and not isinstance(last, bool):
            if now_seconds() - int(last) < UPDATE_CHECK_INTERVAL_SECONDS:
                return "checked-recently"
        if not spawn_background_update(
            base_home, env=values, spawn=spawn, windows=windows
        ):
            return "failed"
        return "started"
    except Exception:  # noqa: BLE001 - a session is never interrupted by this
        return "failed"


def newest_installed(home: Path) -> str | None:
    """The version the launcher would start here, or ``None``."""
    versions = installed_versions(home)
    return versions[-1] if versions else None


def is_newer(candidate: str, than: str | None) -> bool:
    """Whether *candidate* is a later version than *than*."""
    if than is None:
        return True
    return version_sort_key(candidate) > version_sort_key(than)


def look_for_newer(
    home: Path,
    *,
    env: Mapping[str, str] | None = None,
    key: str | None = None,
    opener: Callable[..., Any] | None = None,
    timeout: float | None = None,
    progress: Callable[[str], None] = say,
) -> Manifest:
    """Ask what the newest s0ma is, and write down that we asked."""
    values = environ(env)
    config = load_config(home)
    base = cp_base_url(cp_host(values, config))
    if key is None:
        key, _ = license_key(values, home)
    if not key:
        raise LauncherError(EXIT_NO_KEY, KEY_MISSING_MESSAGE)
    manifest = fetch_manifest(base, key, timeout=timeout, opener=opener)
    if manifest.notice:
        progress(manifest.notice)
    state = load_state(home)
    state["latest_seen"] = manifest.version
    state["last_check"] = now_seconds()
    state["entitlement"] = "ok"
    state["last_error"] = None
    save_state(home, state)
    return manifest


def update_check_lines(
    home: Path,
    latest: str,
    *,
    env: Mapping[str, str] | None = None,
    project: Path | None = None,
) -> list[str]:
    """What ``update --check`` says, once it knows what the newest version is."""
    values = environ(env)
    where = project_dir(values) if project is None else project
    current = newest_installed(home)
    lines = [
        f"Installed here:  {current or 'nothing yet'}",
        f"Newest there is: {latest}",
    ]
    pin = read_pin(where)
    if is_newer(latest, current):
        lines.append(f"A newer s0ma is available. Run `{PROG} update` to get it.")
    else:
        lines.append("This machine already has the newest s0ma.")
    if pin.version:
        lines.append(
            f"This project asks for s0ma {pin.version} in its {PIN_FILENAME} file, "
            f"so it stays there until someone runs `{PROG} unpin`."
        )
    elif bin_dir_of(project_venv(where)) is not None:
        lines.append(
            "This project has its own copy of s0ma, so it keeps using that one "
            "whatever is installed here."
        )
    return lines


def perform_update(
    home: Path,
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
    timeout: float | None = None,
    progress: Callable[[str], None] = say,
    project: Path | None = None,
) -> int:
    """Move this machine to the newest s0ma, keeping the one it has.

    The new version is installed beside the old one and becomes what starts
    next; the version before it is kept, so going back is a matter of pinning.
    Anything older than that is swept away - except a version this project is
    pinned to, which is never taken out from under it.
    """
    values = environ(env)
    where = project_dir(values) if project is None else project
    with UpdateLock(home) as taken:
        if not taken:
            progress(
                "s0ma is already updating itself in another window, so this one "
                "left it to finish."
            )
            return EXIT_OK
        previous = newest_installed(home)
        manifest = look_for_newer(
            home, env=values, opener=opener, timeout=timeout, progress=progress
        )
        if not is_newer(manifest.version, previous):
            progress(f"s0ma {previous} is already the newest there is.")
            return EXIT_OK
        installed = install_version(
            home,
            env=values,
            manifest=manifest,
            opener=opener,
            timeout=timeout,
            progress=progress,
        )
        pin = read_pin(where)
        keep = {installed}
        if previous:
            keep.add(previous)
        if pin.version:
            keep.add(pin.version)
        removed = sweep_old_versions(home, keep)
        state = load_state(home)
        state["installed"] = installed_versions(home)
        save_state(home, state)

        progress(
            f"s0ma {installed} is installed and will be used from the next session."
        )
        if previous:
            progress(
                f"s0ma {previous} is still here, so `{PROG} pin {previous}` puts "
                "this project back on it at any time."
            )
        if removed:
            progress("Older versions cleared away: " + ", ".join(sorted(removed)) + ".")
        if pin.version:
            progress(
                f"This project asks for s0ma {pin.version}, so it carries on using "
                "that one."
            )
    return EXIT_OK


def run_background_update(
    home: Path,
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
    timeout: float | None = None,
) -> int:
    """The quiet update `serve` starts. It never fails in front of anybody.

    Everything it prints goes to ``launcher/update.log`` - the process that
    started it pointed its output there - and anything that goes wrong is
    written into ``state.json`` as one sentence, for ``status`` and the session
    hint to pass on. It always ends with :data:`EXIT_OK`: nobody reads the exit
    code of a process nobody is waiting for.

    Under ``notify`` it only writes down what the newest version is. Under
    ``off`` it does nothing at all, which is the same answer ``serve`` already
    reached before starting it - checked twice, because this process may also
    have been started by hand.
    """
    values = environ(env)
    try:
        config = load_config(home)
        mode = update_mode(values, config)
        if mode == "off":
            say("Updates are switched off on this machine, so nothing was checked.")
            return EXIT_OK
        with UpdateLock(home) as taken:
            if not taken:
                say("Another run is already looking after this; nothing to do.")
                return EXIT_OK
            previous = newest_installed(home)
            manifest = look_for_newer(home, env=values, opener=opener, timeout=timeout)
            if not is_newer(manifest.version, previous):
                say(f"s0ma {previous} is the newest there is; nothing to do.")
                return EXIT_OK
            if mode == "notify":
                say(
                    f"s0ma {manifest.version} is available; this machine is set to "
                    "tell you rather than fetch it."
                )
                return EXIT_OK
            installed = install_version(
                home,
                env=values,
                manifest=manifest,
                opener=opener,
                timeout=timeout,
            )
            keep = {installed}
            if previous:
                keep.add(previous)
            pin = read_pin(project_dir(values))
            if pin.version:
                keep.add(pin.version)
            removed = sweep_old_versions(home, keep)
            state = load_state(home)
            state["installed"] = installed_versions(home)
            state["pending"] = installed
            save_state(home, state)
            say(f"s0ma {installed} is installed and waiting for the next session.")
            if removed:
                say("Older versions cleared away: " + ", ".join(sorted(removed)) + ".")
    except LauncherError as failure:
        record_failure(home, failure)
        say(failure.message)
    except Exception as failure:  # noqa: BLE001 - nothing here may escape
        say(f"The quiet update stopped: {plain_sentence(str(failure)) or 'unknown'}")
        record_failure(
            home,
            LauncherError(
                EXIT_NETWORK,
                "s0ma's quiet update did not finish. The copy of s0ma on this "
                "machine keeps working.",
            ),
        )
    return EXIT_OK


def cmd_update(args: argparse.Namespace) -> int:
    """Move to a newer version of s0ma, or just report whether there is one."""
    values = environ()
    home = s0ma_home(values)
    if getattr(args, "background", False):
        return run_background_update(home, env=values)
    if getattr(args, "check", False):
        try:
            manifest = look_for_newer(home, env=values)
        except LauncherError as failure:
            record_failure(home, failure)
            raise
        for line in update_check_lines(home, manifest.version, env=values):
            print(line)
        return EXIT_OK
    try:
        return perform_update(home, env=values)
    except LauncherError as failure:
        record_failure(home, failure)
        raise


# ---------------------------------------------------------------------------
# pin and unpin: holding one project on one version.
#
# The file is `.s0ma-version` in the project directory - the same directory the
# launcher reads it from, with no searching upwards (gate ruling 4), so what is
# written is what will be read. A project that carries its own copy of s0ma is
# already held on one version by its own dependencies, and is told so rather
# than given a second, quieter answer that would not be consulted.
# ---------------------------------------------------------------------------

OWN_TOOLCHAIN_MESSAGE = (
    "This project has its own copy of s0ma in its .venv, so it is already held "
    f"on one version by the project's own dependencies - a {PIN_FILENAME} file "
    "would change nothing here.\n"
    "To move this project to a different s0ma, change the s0ma packages in the "
    "project itself."
)


def write_pin(project: Path, version: str) -> Path:
    """Write the project's ``.s0ma-version`` file: one line, one newline."""
    path = project / PIN_FILENAME
    project.mkdir(parents=True, exist_ok=True)
    handle_fd, temporary = tempfile.mkstemp(dir=str(project), prefix=PIN_FILENAME + ".")
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(version + "\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    _chmod_best_effort(path, 0o644)
    return path


def version_exists(
    home: Path,
    version: str,
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
    timeout: float | None = None,
) -> tuple[bool | None, str | None]:
    """Ask the control plane whether a version exists.

    Returns ``(True, None)``, ``(False, None)`` or ``(None, why_not_known)``.
    Not knowing is not a refusal: a machine with no key, or no network, can
    still pin a version it is sure about, and is told that the check did not
    happen rather than being stopped.
    """
    values = environ(env)
    key, _ = license_key(values, home)
    if not key:
        return None, "there is no license key on this machine"
    config = load_config(home)
    try:
        base = cp_base_url(cp_host(values, config))
        fetch_manifest(base, key, version=version, timeout=timeout, opener=opener)
    except ControlPlaneError as failure:
        if failure.code == EXIT_USAGE:
            return False, None
        return None, plain_sentence(failure.message.splitlines()[0])
    except LauncherError as failure:
        return None, plain_sentence(failure.message.splitlines()[0])
    return True, None


def cmd_pin(args: argparse.Namespace) -> int:
    """Hold this project on one version of s0ma."""
    values = environ()
    home = s0ma_home(values)
    project = project_dir(values)
    version = str(getattr(args, "version", "") or "").strip()
    if not looks_like_version(version):
        say(
            f"`{version}` does not look like a version of s0ma. A version looks "
            f"like 0.18.0, so: {PROG} pin 0.18.0"
        )
        return EXIT_USAGE
    if bin_dir_of(project_venv(project)) is not None:
        say(OWN_TOOLCHAIN_MESSAGE)
        return EXIT_USAGE
    if not getattr(args, "offline", False):
        exists, unknown = version_exists(home, version, env=values)
        if exists is False:
            say(
                f"s0ma's control plane has no version {version}, so this project "
                "was left as it was. Run `" + PROG + " update --check` to see "
                "what the newest version is."
            )
            return EXIT_USAGE
        if exists is None and unknown:
            say(f"s0ma could not check whether {version} exists ({unknown}).")
    path = write_pin(project, version)
    say(f"This project now stays on s0ma {version} until someone unpins it.")
    say(f"  Written to: {fwd(path)}")
    if version not in installed_versions(home):
        say(
            f"s0ma {version} is not installed on this machine yet. Run "
            f"`{PROG} install --version {version}` to get it."
        )
    say(f"Run `{PROG} unpin` here to follow the newest installed version again.")
    return EXIT_OK


def cmd_unpin(args: argparse.Namespace) -> int:
    """Let this project follow the newest installed version again."""
    del args
    values = environ()
    project = project_dir(values)
    if bin_dir_of(project_venv(project)) is not None:
        say(OWN_TOOLCHAIN_MESSAGE)
        return EXIT_USAGE
    path = project / PIN_FILENAME
    try:
        path.unlink()
    except FileNotFoundError:
        say(
            "There was nothing to remove: this project does not ask for a "
            f"particular version of s0ma ({fwd(path)} does not exist)."
        )
        return EXIT_OK
    except OSError as failure:
        raise LauncherError(
            EXIT_USAGE,
            f"s0ma could not remove {fwd(path)} ({_reason_of(failure)}). Delete "
            "the file by hand and this project will follow the newest version.",
        ) from failure
    say(
        "This project no longer asks for a particular version of s0ma, so it "
        "follows the newest one installed on this machine."
    )
    say(f"  Removed: {fwd(path)}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# activate: taking a license key, once, without showing it.
#
# The key is typed at a hidden prompt, checked once against the control plane,
# and written to one owner-readable file. It is never echoed, never a command-
# line argument (arguments are readable by every process on the machine), never
# written anywhere else, and never printed afterwards except as its last four
# characters.
# ---------------------------------------------------------------------------

ACTIVATE_PROMPT = "Paste your s0ma license key (it will not be shown): "

ACTIVATE_NEEDS_TERMINAL = (
    "`s0ma-launch activate` asks for your license key without showing it, which "
    "needs a real terminal, and this is not one.\n"
    "Open a terminal and run `s0ma-launch activate` there - or, in Claude, put "
    "the key in the s0ma plugin's settings instead."
)


def _ask_for_key(prompt: str) -> str:
    """Read a key from a hidden prompt. The seam the tests replace."""
    return getpass.getpass(prompt)


def _stdin_is_a_terminal() -> bool:
    """Whether someone is actually sitting there to type. Never raises."""
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError, OSError):  # pragma: no cover - a closed stdin
        return False


def write_license_key(home: Path, key: str) -> Path:
    """Save the key, readable by its owner and nobody else where that is possible."""
    home.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(home, DIR_MODE)
    path = license_path(home)
    handle_fd, temporary = tempfile.mkstemp(dir=str(home), prefix=LICENSE_FILENAME + ".")
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(key + "\n")
        _chmod_best_effort(Path(temporary), FILE_MODE)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    _chmod_best_effort(path, FILE_MODE)
    return path


def check_key(
    home: Path,
    key: str,
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Ask the control plane whether this key is any good. Once."""
    values = environ(env)
    config = load_config(home)
    base = cp_base_url(cp_host(values, config))
    answer = cp_get_json(
        key_check_url(base), key, base, timeout=timeout, opener=opener
    )
    if answer.get("ok") is not True:
        raise ControlPlaneError(
            EXIT_NO_KEY,
            KEY_REFUSED_MESSAGE,
            entitlement="invalid_key",
            notice=plain_sentence(answer.get("notice")),
        )
    return answer


def cmd_activate(args: argparse.Namespace) -> int:
    """Take a license key at a hidden prompt and save it on this machine."""
    del args
    values = environ()
    home = s0ma_home(values)
    if not _stdin_is_a_terminal():
        say(ACTIVATE_NEEDS_TERMINAL)
        return EXIT_USAGE
    try:
        typed = _ask_for_key(ACTIVATE_PROMPT)
    except (EOFError, KeyboardInterrupt):
        say("Nothing was typed, so nothing was saved.")
        return EXIT_USAGE
    key = typed.strip()
    if not key:
        say("Nothing was typed, so nothing was saved.")
        return EXIT_USAGE

    try:
        answer = check_key(home, key, env=values)
    except LauncherError as failure:
        record_failure(home, failure)
        say("Nothing was saved.")
        raise

    path = write_license_key(home, key)
    state = load_state(home)
    state["entitlement"] = "ok"
    state["last_error"] = None
    save_state(home, state)

    say("That key was accepted and is saved on this machine.")
    say(f"  Key:  {redact_key(key)}")
    say(f"  File: {fwd(path)}")
    if os.name == "posix":
        say("  Only you can read that file.")
    else:
        say(
            "  s0ma could not set the permissions on that file here, so check "
            "that the folder it is in is one only you can read."
        )
    plan = plain_sentence(answer.get("plan"), limit=40)
    if plan:
        say(f"  Plan: {plan}")
    notice = plain_sentence(answer.get("notice"))
    if notice:
        say(notice)
    say(f"Run `{PROG} install` to get s0ma, or /s0ma:setup in Claude.")
    return EXIT_OK


# ---------------------------------------------------------------------------
# session-hint: the one line a new Claude session may begin with.
#
# The plugin runs this from a SessionStart hook
# (integrations/claude/plugin/hooks/hooks.json). Three rules shape everything
# below, and none of them is negotiable:
#
# * **It never stops a session.** Claude's first answer waits for its
#   SessionStart hooks, so this has to be quick, and anything at all that goes
#   wrong here has to end as silence and exit 0.
# * **It reads local files and does nothing else.** No socket, no subprocess, no
#   write - not even the tidying-up the everyday reader does when it meets a
#   spoiled file. A glance that repaired the state directory behind the user's
#   back would be doing real work in a place meant for a glance.
# * **It says nothing when there is nothing to say.** One line, or none. A line
#   that appears every session is a line nobody reads.
#
# What is printed is one line of JSON, in the shape Claude Code documents for a
# SessionStart hook (https://code.claude.com/docs/en/hooks): plain stdout from a
# SessionStart hook is added as context the model reads, while `systemMessage`
# in a JSON object is the notification shown to the person. Almost everything
# this command has to say is for the person alone, so it goes in
# `systemMessage` and nowhere else. The two cases where s0ma's tools are simply
# not there are the exception - the model has to know that too, or it will offer
# to use tools that cannot answer - so those also fill in
# `hookSpecificOutput.additionalContext`, which is the same page's field for
# what the model should be told.
# ---------------------------------------------------------------------------

#: The event this line is written for. It goes in the JSON so Claude Code can
#: check the hint against the event it fired.
HINT_EVENT_NAME = "SessionStart"

#: The whole printed line stays under this many characters. Claude Code's own
#: ceiling is far higher (10,000); this one is about a person's patience, and
#: about never letting one long path turn a glance into a paragraph.
HINT_MAX_CHARS = 600

#: Cases 1 and 2 - there is nothing here to run, so the tools are not there.
HINT_TOOLS_MISSING = "s0ma's tools are not available in this session."
HINT_SETUP_ACTION = "Run /s0ma:setup in Claude to fix that."
HINT_SETUP_SKILL = "The /s0ma:setup skill fixes that."

#: Case 3 - the key was refused the last time s0ma used it. Where a key goes is
#: said in exactly the same words as everywhere else in this file, and the chat
#: is never one of the places.
HINT_KEY_REFUSED = (
    "The last time s0ma used your license key, it was refused. " + KEY_HOMES_SENTENCE
)

#: Case 4 - the subscription's access to new versions has ended. Nothing breaks;
#: this is news, not an error.
HINT_ACCESS_ENDED = (
    "This account's access to new versions of s0ma has ended. The copy you have "
    "installed keeps working. Your subscription is at {host}."
)

#: Case 5 - a newer version exists and this machine asked to be told rather than
#: to be kept current quietly.
HINT_NEWER_AVAILABLE = (
    "s0ma {latest} is available; s0ma {running} is what runs here. "
    "Run /s0ma:update in Claude when you want it."
)

#: Case 6 - a newer version is already on this machine, waiting to be started.
HINT_UPDATE_WAITING = (
    "s0ma {pending} was fetched quietly in the background, and it is what Claude "
    "will use from your next session."
)

#: Said instead of any of the above when the real sentence would not fit in one
#: glance - a very long path or a very long version string is the way that
#: happens. The doctor skill prints the whole story.
HINT_TOO_LONG_MESSAGE = (
    "s0ma has something to say about this machine, and it did not fit in one "
    "line. Run /s0ma:doctor in Claude to see it."
)
HINT_TOO_LONG_CONTEXT = HINT_TOOLS_MISSING + " " + HINT_SETUP_SKILL


@dataclass(frozen=True)
class Hint:
    """The one thing a new session is told, and who it is for.

    *message* is for the person: Claude Code shows it as a system notification.
    *context* is for the model, and is filled in only when s0ma's tools are
    missing - knowing that saves the model from offering work it cannot do.
    """

    message: str
    context: str | None = None


def read_json_quietly(path: Path) -> dict[str, Any]:
    """Return the object in *path*, or an empty one. Reads only; says nothing.

    :func:`read_json_file` is the everyday reader and it tidies up as it goes: a
    spoiled file is moved aside, a fresh one is written in its place, and a line
    goes to stderr. None of that belongs in a session hook, so this is its
    read-only twin. A file that is missing, unreadable or nonsense all answer
    the same way here, because the hint has the same nothing to say about each.
    """
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def hint_version(value: Any) -> str | None:
    """*value* when it could be a version number, and ``None`` otherwise."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed if looks_like_version(trimmed) else None


def hint_output(hint: Hint) -> dict[str, Any]:
    """*hint* in the shape a SessionStart hook's JSON output takes."""
    output: dict[str, Any] = {"systemMessage": hint.message}
    if hint.context is not None:
        output["hookSpecificOutput"] = {
            "additionalContext": hint.context,
            "hookEventName": HINT_EVENT_NAME,
        }
    return output


def hint_fits(hint: Hint) -> bool:
    """Whether *hint* would print inside :data:`HINT_MAX_CHARS`."""
    return len(json.dumps(hint_output(hint), sort_keys=True)) < HINT_MAX_CHARS


def tools_missing_hint(reason: str) -> Hint:
    """Cases 1 and 2: symptom, then cause, then the one thing to do.

    *reason* is :attr:`Resolution.reason`, and it is the only part of anything
    this command says whose length nobody controls - it can carry a directory
    somebody named in ``S0MA_TOOLCHAIN``. When saying why would push the line
    past what a person will read, the why is what goes: the symptom and the fix
    are what matter, and ``/s0ma:setup`` prints the whole story anyway.
    """
    full = Hint(
        message=f"{HINT_TOOLS_MISSING} {reason} {HINT_SETUP_ACTION}",
        context=f"{HINT_TOOLS_MISSING} {reason} {HINT_SETUP_SKILL}",
    )
    if hint_fits(full):
        return full
    return Hint(
        message=f"{HINT_TOOLS_MISSING} {HINT_SETUP_ACTION}",
        context=f"{HINT_TOOLS_MISSING} {HINT_SETUP_SKILL}",
    )


def session_hint(
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    project: Path | None = None,
) -> Hint | None:
    """The one thing this session should hear, or ``None`` when all is well.

    The six things worth saying are in priority order, and the first one that is
    true is the only one said:

    1. There is nothing to run here at all.
    2. The project asks for a version that is not installed.
    3. The key was refused the last time s0ma used it.
    4. This account's access to new versions has ended.
    5. A newer version exists and this machine asked to be told about it.
    6. A newer version has already been fetched and is waiting to be used.

    The last two are about updates, so ``S0MA_UPDATE=off`` silences both by the
    ordinary reading of the setting - ``off`` is neither ``notify`` nor ``auto``.

    Both also ask that the copy running here be one the launcher looks after. A
    project with its own copy of s0ma, a project pinned to a version, and a
    contributor's own checkout are none of the launcher's to move, so a line
    promising them a newer s0ma would simply not be true.
    """
    values = environ(env)
    base = s0ma_home(values) if home is None else home
    where = project_dir(values) if project is None else project

    config = read_json_quietly(config_path(base))
    state = read_json_quietly(state_path(base))
    resolution = resolve_toolchain(values, base, where)

    # 1 and 2. Nothing runs here. The resolution's own sentence is the cause,
    # and it names the version when the project asked for one.
    if not resolution.found:
        return tools_missing_hint(resolution.reason)

    # 3 and 4. What the control plane last said about this key. Both are for the
    # person only: neither changes what the model can do in this session.
    entitlement = state.get("entitlement")
    if entitlement == "invalid_key":
        return Hint(message=HINT_KEY_REFUSED)
    if entitlement == "not_entitled":
        return Hint(message=HINT_ACCESS_ENDED.format(host=cp_host(values, config)))

    running = resolution.version
    if resolution.kind != KIND_MANAGED or running is None:
        return None
    mode = update_mode(values, config)

    # 5. Told, not fetched.
    latest = hint_version(state.get("latest_seen"))
    if mode == "notify" and latest is not None and is_newer(latest, running):
        return Hint(
            message=HINT_NEWER_AVAILABLE.format(latest=latest, running=running)
        )

    # 6. Fetched, not yet started. ``serve`` clears ``pending`` the moment it
    # starts that version, so a ``pending`` still on disk is the launcher's own
    # record that no session has run it yet. A record left behind by an older
    # version than the one that would start here is stale, and stale news is no
    # news.
    pending = hint_version(state.get("pending"))
    if (
        mode in ("auto", "notify")
        and pending is not None
        and not is_newer(running, pending)
    ):
        return Hint(message=HINT_UPDATE_WAITING.format(pending=pending))

    return None


def hint_line(hint: Hint) -> str:
    """*hint* as the one line of JSON the hook prints.

    ``ensure_ascii`` is left at its default, so a path holding a character a
    Windows console cannot show arrives as an escape rather than as broken
    bytes, and the line stays plain ASCII whatever is in it. The length guard is
    the last word: rather than truncate a sentence in the middle, an oversized
    hint is replaced by a short one that points at the skill which can print the
    whole thing.
    """
    line = json.dumps(hint_output(hint), sort_keys=True)
    if len(line) < HINT_MAX_CHARS:
        return line
    short = Hint(
        message=HINT_TOO_LONG_MESSAGE,
        context=None if hint.context is None else HINT_TOO_LONG_CONTEXT,
    )
    return json.dumps(hint_output(short), sort_keys=True)


def cmd_session_hint(args: argparse.Namespace) -> int:
    """Say the one thing a new Claude session needs to hear, or nothing at all.

    This always returns 0 and never raises. A hook that failed would put a hook
    error in front of somebody who has just opened Claude to do something else,
    and nothing this command has to say is worth that.
    """
    del args
    try:
        hint = session_hint()
        if hint is None:
            return EXIT_OK
        line = hint_line(hint)
    except Exception:  # noqa: BLE001 - a session is never interrupted by this
        return EXIT_OK
    try:
        # Stdout, not stderr: stdout is what Claude Code reads a hook's answer
        # from, and stderr on a hook is an error notice.
        print(line)
    except Exception:  # noqa: BLE001 - a closed pipe is not worth a hook error
        pass
    return EXIT_OK


# ---------------------------------------------------------------------------
# The command line.
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the whole command line, every sub-command included."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Find, start and look after the copy of s0ma that belongs to this project."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", metavar="<command>")

    serve = subcommands.add_parser(
        "serve", help="start the s0ma MCP server (what Claude runs)"
    )
    serve.set_defaults(handler=cmd_serve)

    status = subcommands.add_parser(
        "status", help="what is installed, what runs here, and why"
    )
    status.add_argument(
        "--json", action="store_true", help="print the same facts as JSON"
    )
    status.set_defaults(handler=cmd_status)

    install = subcommands.add_parser("install", help="install s0ma on this machine")
    install.add_argument(
        "--version", metavar="V", default=None, help="a version to install (default: the newest)"
    )
    install.set_defaults(handler=cmd_install)

    update = subcommands.add_parser("update", help="move to a newer s0ma")
    update.add_argument(
        "--check", action="store_true", help="only say whether a newer s0ma exists"
    )
    # Not in the help on purpose: this is the form `serve` starts in a process
    # of its own, and it is not something anyone needs to type.
    update.add_argument("--background", action="store_true", help=argparse.SUPPRESS)
    update.set_defaults(handler=cmd_update)

    pin = subcommands.add_parser("pin", help="hold this project on one version")
    pin.add_argument("version", metavar="V", help="the version this project should use")
    pin.add_argument(
        "--offline",
        action="store_true",
        help="do not ask whether that version exists; just write the file",
    )
    pin.set_defaults(handler=cmd_pin)

    unpin = subcommands.add_parser("unpin", help="stop holding this project on one version")
    unpin.set_defaults(handler=cmd_unpin)

    activate = subcommands.add_parser(
        "activate", help="save your license key on this machine (hidden prompt)"
    )
    activate.set_defaults(handler=cmd_activate)

    hint = subcommands.add_parser(
        "session-hint", help="the one line a new Claude session may start with"
    )
    hint.set_defaults(handler=cmd_session_hint)

    run = subcommands.add_parser(
        "run",
        help="run one of s0ma's own commands, for example: run -- s0ma doctor",
        description=(
            "Run one of the commands that belong to the copy of s0ma this project "
            "uses. Put the command after `--`, so its own options reach it "
            "untouched."
        ),
        epilog=f"example: {PROG} run -- s0ma doctor",
    )
    run.set_defaults(handler=cmd_run, child_argv=[])

    return parser


def split_run_argv(argv: Sequence[str]) -> tuple[list[str], list[str] | None]:
    """Separate ``run``'s own arguments from the command it should run.

    ``run -- s0ma doctor --verbose`` has to reach s0ma with ``--verbose``
    intact, so everything after the first ``--`` is taken out before the command
    line is parsed. ``run s0ma doctor`` works too; ``run --help`` still prints
    the help.
    """
    parts = list(argv)
    if not parts or parts[0] != "run":
        return parts, None
    rest = parts[1:]
    if "--" in rest:
        cut = rest.index("--")
        return ["run", *rest[:cut]], rest[cut + 1 :]
    if rest and rest[0] in ("-h", "--help"):
        return parts, None
    return ["run"], rest


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return its exit code. Never raises to the caller."""
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    head, child = split_run_argv(raw)
    try:
        args = parser.parse_args(head)
    except SystemExit as stop:
        return int(stop.code or EXIT_OK)
    if getattr(args, "command", None) is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    if child is not None:
        args.child_argv = child
    try:
        return int(args.handler(args))
    except LauncherError as failure:
        say(failure.message)
        return failure.code
    except KeyboardInterrupt:
        say("Stopped.")
        return EXIT_USAGE
    except BrokenPipeError:
        return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised as a whole program
    sys.exit(main())
