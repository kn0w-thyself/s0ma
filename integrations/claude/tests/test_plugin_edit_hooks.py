"""The plugin's two edit hooks, run as ``hooks/hooks.json`` states them.

Each case takes the command line out of ``hooks.json``, fills in
``${CLAUDE_PLUGIN_ROOT}`` the way Claude Code does, runs it through a real
shell (Git Bash on Windows) and hands it the JSON a real Write or Edit would.
uv is a stand-in that records every time it is started and runs the
launcher with this Python; where s0ma is installed, it is the real s0ma of
this workspace, named by ``S0MA_TOOLCHAIN``, and the project is one that
``s0ma new project`` made.

Every case ends the same way: exit 0 and nothing on stderr, whatever was said
on stdout.

Nothing here opens a socket, and nothing here runs Claude.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "integrations" / "claude" / "plugin"
HOOKS_CONFIG = PLUGIN_DIR / "hooks" / "hooks.json"
LAUNCHER_PATH = REPO_ROOT / "integrations" / "launcher" / "s0ma_launch.py"

WINDOWS = sys.platform.startswith("win")

#: The places uv may live that no environment variable can move.
FIXED_UV_PLACES = (Path("/opt/homebrew/bin/uv"), Path("/usr/local/bin/uv"))

TIMEOUT = 120

#: This workspace's own environment, which holds the real s0ma.
WORKSPACE_ENV = Path(sys.prefix)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("s0ma_launch_for_plugin_edit_hooks", LAUNCHER_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise RuntimeError(f"could not load the launcher from {LAUNCHER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def find_sh() -> str | None:
    """The shell Claude Code runs a shell-form hook with: ``sh``, or Git Bash."""
    if WINDOWS:
        git = shutil.which("git")
        roots = [Path(git).resolve().parent.parent] if git else []
        roots.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git")
        for root in roots:
            candidate = root / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
        return None
    return shutil.which("sh")


SH = find_sh()
pytestmark = pytest.mark.skipif(SH is None, reason="no POSIX sh on this machine")


def posix(path: Path | str) -> str:
    return Path(path).as_posix()


def commands() -> dict[str, str]:
    """``before-edit`` and ``after-edit``: each command line, as hooks.json writes it."""
    hooks = json.loads(HOOKS_CONFIG.read_text(encoding="utf-8"))["hooks"]
    found: dict[str, str] = {}
    for event, name in (("PreToolUse", "before-edit"), ("PostToolUse", "after-edit")):
        lines = {h["command"] for entry in hooks[event] for h in entry["hooks"]}
        assert len(lines) == 1, f"{event} runs more than one command: {lines}"
        found[name] = lines.pop()
    return found


def plugin_root_text() -> str:
    """The plugin root as Claude Code fills it in: forward slashes on Windows."""
    return PLUGIN_DIR.resolve().as_posix()


def base_dirs() -> list[Path]:
    if not WINDOWS:
        dirs = [Path("/usr/bin"), Path("/bin")]
    else:
        dirs = [Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"]
        if SH is not None:
            dirs.append(Path(SH).resolve().parent.parent / "usr" / "bin")
    return [d for d in dirs if d.is_dir()]


def skip_if_uv_is_fixed() -> None:
    for directory in base_dirs():
        if shutil.which("uv", path=str(directory)):
            pytest.skip(f"uv is in {directory}, which the scripts need on the PATH")
    for place in FIXED_UV_PLACES:
        if place.exists():
            pytest.skip(f"uv is installed at {place}, which no environment can hide")


class Machine:
    """A home, a PATH and a uv of the test's own making."""

    def __init__(self, tmp_path: Path, *, uv: bool = True, s0ma: bool = True) -> None:
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir(exist_ok=True)
        self.bin = tmp_path / "uv-bin"
        self.uv_log = tmp_path / "uv-started.txt"
        dirs = [tmp_path / "empty"]
        if uv:
            self.bin.mkdir(exist_ok=True)
            stand_in = self.bin / "uv"
            stand_in.write_text(
                "#!/bin/sh\n"
                f'printf \'%s\\n\' "$*" >> "{posix(self.uv_log)}"\n'
                "while [ $# -gt 0 ]; do\n"
                f'    if [ "$1" = --script ]; then shift; exec "{posix(sys.executable)}" "$@"; fi\n'
                "    shift\n"
                "done\n"
                "exit 9\n",
                encoding="utf-8",
                newline="\n",
            )
            stand_in.chmod(0o755)
            dirs = [self.bin]
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith(("UV_", "S0MA_", "CLAUDE_"))
            and key.upper() not in {"VIRTUAL_ENV", "PYTHONPATH"}
        }
        env["PATH"] = os.pathsep.join([*(str(d) for d in dirs), *(str(d) for d in base_dirs())])
        env["HOME"] = str(self.home)
        for name in ("USERPROFILE", "LOCALAPPDATA", "ProgramFiles"):
            env[name] = str(self.home)
        env["S0MA_HOME"] = str(tmp_path / "s0ma-home")
        if s0ma:
            env["S0MA_TOOLCHAIN"] = str(WORKSPACE_ENV)
        self.env = env

    def uv_starts(self) -> list[str]:
        if not self.uv_log.exists():
            return []
        return self.uv_log.read_text(encoding="utf-8").splitlines()

    def run(self, hook: str, payload: Any, project: Path) -> subprocess.CompletedProcess[str]:
        """Run *hook*'s command with *payload* (an object, or text as it is)."""
        assert SH is not None
        command = commands()[hook].replace("${CLAUDE_PLUGIN_ROOT}", plugin_root_text())
        env = dict(self.env)
        env["CLAUDE_PLUGIN_ROOT"] = plugin_root_text()
        env["CLAUDE_PROJECT_DIR"] = str(project)
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        result = subprocess.run(  # noqa: S603 - a fixed, local command
            [SH, "-c", command],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(project),
            timeout=TIMEOUT,
            check=False,
        )
        # Case 8, for every case: exit 0, and nothing on stderr.
        assert result.returncode == 0, result
        assert result.stderr == "", result.stderr
        return result


def write_edit(path: Path | str, project: Path, *, tool: str = "Write", event: str = "PreToolUse") -> dict[str, Any]:
    """The JSON Claude Code hands a hook for one Write or Edit."""
    if tool == "Write":
        tool_input: dict[str, Any] = {"file_path": str(path), "content": 'say = "file_path"\n'}
    else:
        tool_input = {"file_path": str(path), "old_string": "a", "new_string": "b", "replace_all": False}
    payload: dict[str, Any] = {
        "session_id": "plugin-edit-hook-tests",
        "transcript_path": str(project / "transcript.jsonl"),
        "cwd": str(project),
        "permission_mode": "default",
        "hook_event_name": event,
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_use_id": "toolu_edit_hook_tests",
    }
    if event == "PostToolUse":
        payload["tool_response"] = {"filePath": str(path), "success": True}
    return payload


def denial(result: subprocess.CompletedProcess[str]) -> str:
    lines = result.stdout.splitlines()
    assert len(lines) == 1 and lines[0].isascii(), result.stdout
    output = json.loads(lines[0])["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert output["permissionDecision"] == "deny"
    return str(output["permissionDecisionReason"])


def context(result: subprocess.CompletedProcess[str]) -> str:
    lines = result.stdout.splitlines()
    assert len(lines) == 1 and lines[0].isascii(), result.stdout
    output = json.loads(lines[0])["hookSpecificOutput"]
    assert output["hookEventName"] == "PostToolUse"
    return str(output["additionalContext"])


@pytest.fixture(scope="module")
def scaffold(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One project from the real ``s0ma new project``, copied for each test."""
    program = WORKSPACE_ENV / ("Scripts" if WINDOWS else "bin") / ("s0ma.exe" if WINDOWS else "s0ma")
    if not program.is_file():
        pytest.skip(f"no s0ma in {WORKSPACE_ENV}; run the suite through `uv run`")
    where = tmp_path_factory.mktemp("scaffold")
    subprocess.run(  # noqa: S603 - a fixed, local command
        [str(program), "new", "project", "demo", "--name", "demo"],
        cwd=str(where),
        capture_output=True,
        timeout=TIMEOUT,
        check=True,
    )
    project = where / "demo"
    assert (project / "src" / "core" / "core_domain.s0ma").is_file()
    return project


@pytest.fixture
def project(scaffold: Path, tmp_path: Path) -> Path:
    copy = tmp_path / "demo"
    shutil.copytree(scaffold, copy)
    return copy


def source(project: Path) -> Path:
    return project / "src" / "core" / "core_domain.s0ma"


def break_source(project: Path) -> None:
    path = source(project)
    text = path.read_text(encoding="utf-8")
    assert "kind: FUNCTION" in text
    path.write_text(text.replace("kind: FUNCTION", "kind: FUNKTION", 1), encoding="utf-8")


def turn_off(project: Path) -> None:
    (project / ".s0ma").mkdir(exist_ok=True)
    (project / ".s0ma" / "preferences.json").write_text('{"s0ma": "off"}', encoding="utf-8")


# ---------------------------------------------------------------------------
# 1 and 2. After an edit to a .s0ma file.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_a_fault_in_a_s0ma_file_is_handed_to_claude(
    tmp_path: Path, project: Path, tool: str
) -> None:
    break_source(project)
    machine = Machine(tmp_path)
    result = machine.run("after-edit", write_edit(source(project), project, tool=tool, event="PostToolUse"), project)
    said = context(result)
    assert said.startswith("s0ma check ran on src/core/core_domain.s0ma after this edit and reports:\n")
    assert "[PARSE_ERROR]" in said
    assert said.endswith("\nFix these in the .s0ma file before you go on.")
    assert len(said) <= 3000
    assert [line.split()[-1] for line in machine.uv_starts()] == ["after-edit"]


def test_a_clean_s0ma_file_says_nothing(tmp_path: Path, project: Path) -> None:
    machine = Machine(tmp_path)
    result = machine.run("after-edit", write_edit(source(project), project, event="PostToolUse"), project)
    assert result.stdout == ""
    assert len(machine.uv_starts()) == 1


def test_a_file_that_is_not_s0ma_starts_nothing_after_an_edit(tmp_path: Path, project: Path) -> None:
    machine = Machine(tmp_path)
    result = machine.run(
        "after-edit", write_edit(project / "src" / "notes.py", project, event="PostToolUse"), project
    )
    assert result.stdout == ""
    assert machine.uv_starts() == []


def test_with_no_s0ma_installed_the_check_says_nothing(tmp_path: Path, project: Path) -> None:
    break_source(project)
    machine = Machine(tmp_path, s0ma=False)
    result = machine.run("after-edit", write_edit(source(project), project, event="PostToolUse"), project)
    assert result.stdout == ""


# ---------------------------------------------------------------------------
# 3. Before an edit under the build folder.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_an_edit_under_the_build_folder_is_refused(
    tmp_path: Path, project: Path, launcher: ModuleType, tool: str
) -> None:
    machine = Machine(tmp_path)
    target = project / "build" / "core_domain.py"
    assert target.is_file()
    reason = denial(machine.run("before-edit", write_edit(target, project, tool=tool), project))
    assert reason == launcher.BUILD_DIR_REFUSAL.format(build_dir="build")


def test_a_new_file_under_the_build_folder_is_refused(tmp_path: Path, project: Path) -> None:
    machine = Machine(tmp_path)
    target = project / "build" / "not" / "there" / "yet.py"
    assert not target.parent.exists()
    denial(machine.run("before-edit", write_edit(target, project), project))


def test_a_custom_build_folder_is_honored(tmp_path: Path, project: Path) -> None:
    pyproject = project / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert 'build_dir = "build"' in text
    pyproject.write_text(text.replace('build_dir = "build"', 'build_dir = "out/gen"'), encoding="utf-8")
    machine = Machine(tmp_path)
    reason = denial(machine.run("before-edit", write_edit(project / "out" / "gen" / "a.py", project), project))
    assert "under out/gen/ in this project" in reason
    result = machine.run("before-edit", write_edit(project / "build" / "a.py", project), project)
    assert result.stdout == ""


def test_an_edit_to_the_source_is_let_through(tmp_path: Path, project: Path) -> None:
    machine = Machine(tmp_path)
    assert machine.run("before-edit", write_edit(source(project), project), project).stdout == ""


def test_the_refusal_needs_no_s0ma_installed(tmp_path: Path, project: Path) -> None:
    machine = Machine(tmp_path, s0ma=False)
    denial(machine.run("before-edit", write_edit(project / "build" / "a.py", project), project))


# ---------------------------------------------------------------------------
# 4. Not a s0ma project: nothing said, and uv never started.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pyproject", [None, '[project]\nname = "plain"\n'], ids=["no pyproject", "plain pyproject"])
def test_outside_a_s0ma_project_uv_is_never_started(
    tmp_path: Path, pyproject: str | None
) -> None:
    plain = tmp_path / "plain"
    (plain / "build").mkdir(parents=True)
    if pyproject is not None:
        (plain / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    machine = Machine(tmp_path)
    for tool in ("Write", "Edit"):
        result = machine.run("before-edit", write_edit(plain / "build" / "x.py", plain, tool=tool), plain)
        assert result.stdout == ""
    assert machine.uv_starts() == []


def test_a_s0ma_project_further_up_does_not_reach_past_a_nearer_pyproject(
    tmp_path: Path, project: Path
) -> None:
    inner = project / "vendor" / "lib"
    (inner / "build").mkdir(parents=True)
    (inner / "pyproject.toml").write_text('[project]\nname = "lib"\n', encoding="utf-8")
    machine = Machine(tmp_path)
    assert machine.run("before-edit", write_edit(inner / "build" / "x.py", project), project).stdout == ""
    assert machine.uv_starts() == []


# ---------------------------------------------------------------------------
# 5. Off for the project.
# ---------------------------------------------------------------------------


def test_off_in_the_project_neither_hook_says_anything(tmp_path: Path, project: Path) -> None:
    break_source(project)
    turn_off(project)
    machine = Machine(tmp_path)
    before = machine.run("before-edit", write_edit(project / "build" / "core_domain.py", project), project)
    after = machine.run("after-edit", write_edit(source(project), project, event="PostToolUse"), project)
    assert (before.stdout, after.stdout) == ("", "")


# ---------------------------------------------------------------------------
# 6. No uv.
# ---------------------------------------------------------------------------


def test_with_no_uv_neither_hook_says_anything(tmp_path: Path, project: Path) -> None:
    skip_if_uv_is_fixed()
    break_source(project)
    machine = Machine(tmp_path, uv=False)
    before = machine.run("before-edit", write_edit(project / "build" / "core_domain.py", project), project)
    after = machine.run("after-edit", write_edit(source(project), project, event="PostToolUse"), project)
    assert (before.stdout, after.stdout) == ("", "")


# ---------------------------------------------------------------------------
# 7. Input that is broken, empty, or awkward.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hook", ["before-edit", "after-edit"])
@pytest.mark.parametrize(
    "text",
    [
        "",
        "{",
        "not json at all",
        '{"tool_input": {"file_path": 7}}',
        '{"tool_input": {}}',
        "[]",
    ],
    ids=["empty", "cut short", "not json", "path not text", "no path", "a list"],
)
def test_broken_input_is_silence(tmp_path: Path, project: Path, hook: str, text: str) -> None:
    machine = Machine(tmp_path)
    assert machine.run(hook, text, project).stdout == ""


@pytest.mark.parametrize("hook", ["before-edit", "after-edit"])
def test_input_cut_short_after_a_path_is_silence(tmp_path: Path, project: Path, hook: str) -> None:
    """The script reads the path and hands over; the launcher cannot parse the rest."""
    break_source(project)
    target = project / "build" / "a.py" if hook == "before-edit" else source(project)
    text = json.dumps(write_edit(target, project))[:-20]
    machine = Machine(tmp_path)
    assert machine.run(hook, text, project).stdout == ""


@pytest.mark.parametrize(
    "name",
    ['say "hi".py', "caf\u00e9.py", "back\\slash.py", "tab\there.py"],
    ids=["quotes", "unicode", "backslash", "tab"],
)
def test_awkward_names_under_the_build_folder_are_still_refused(
    tmp_path: Path, project: Path, name: str
) -> None:
    if WINDOWS and ('"' in name or "\\" in name or "\t" in name):
        pytest.skip("Windows file names cannot hold that character")
    machine = Machine(tmp_path)
    payload = json.dumps(write_edit(project / "build" / name, project))
    assert "\\u" in payload or name.isascii()
    denial(machine.run("before-edit", payload, project))


def test_a_path_named_twice_is_read_by_the_launcher(tmp_path: Path, project: Path) -> None:
    payload = write_edit(project / "build" / "a.py", project)
    payload["extra"] = {"file_path": str(project / "src" / "elsewhere.py")}
    machine = Machine(tmp_path)
    denial(machine.run("before-edit", payload, project))


def test_a_relative_path_is_read_against_the_cwd(tmp_path: Path, project: Path) -> None:
    payload = write_edit("build/core_domain.py", project)
    machine = Machine(tmp_path)
    denial(machine.run("before-edit", payload, project))


def test_spaced_out_json_is_read_too(tmp_path: Path, project: Path) -> None:
    payload = json.dumps(write_edit(project / "build" / "a.py", project), indent=2)
    machine = Machine(tmp_path)
    denial(machine.run("before-edit", payload, project))


def test_a_windows_form_path_outside_any_project_is_silence(tmp_path: Path, project: Path) -> None:
    payload = write_edit("C:\\Nowhere\\at all\\build\\x.py", project)
    payload["cwd"] = "C:\\Nowhere\\at all"
    machine = Machine(tmp_path)
    assert machine.run("before-edit", payload, project).stdout == ""
    if not WINDOWS:
        assert machine.uv_starts() == []


def test_an_unknown_event_word_is_silence(tmp_path: Path, project: Path) -> None:
    assert SH is not None
    script = posix(PLUGIN_DIR / "hooks" / "edit-guard.sh")
    machine = Machine(tmp_path)
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        [SH, script, "during-edit"],
        input=json.dumps(write_edit(project / "build" / "a.py", project)),
        capture_output=True,
        text=True,
        env=machine.env,
        timeout=TIMEOUT,
        check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert machine.uv_starts() == []
