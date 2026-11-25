"""The plugin directory's blocking rules, and the lists that must not drift.

A plugin directory's validator refuses a plugin outright for a few things, and
each of them is cheap to hold here rather than discover at submission:

* **No ``userConfig``.** A plugin that declares one opens a settings dialog at
  install, and this one asks nothing.
* **No variable but ``${CLAUDE_PLUGIN_ROOT}``** in the command of a hook or of
  a server, its arguments included.
* **Every ``uv run`` carries ``--locked`` or ``--frozen``**, in those commands
  and in the scripts they run.
* **The SessionStart hook is shell form**, with no command substitution and no
  wildcard in its line.

Then the lists that several files carry and that must stay one list:

* where uv is looked for: the launcher's ``uv_candidates``, and the copy in
  every script that finds uv on its own;
* the front door's name, ``/s0ma:start``, in the launcher's "tools missing"
  lines, its stub server, its ``status`` and in the plugin's one message;
* the lock file beside the launcher, which ``--frozen`` reads, still matching
  the launcher's header;
* where uv keeps the Pythons it downloads for s0ma: the launcher's
  ``child_environment``, and the copy of that rule in every script that runs
  uv before the launcher does;
* the Pythons s0ma supports: the launcher's ``SUPPORTED_PYTHON``, the server
  scripts' probe, the Python versions the ``CI`` workflow runs, and the
  packages' classifiers.

Everything here reads files, except three kinds of test: the lock test asks
the local uv, offline, whether the lock file is current, and the python-folder
tests run each script's rule in ``sh`` (not on Windows) and in ``cmd.exe`` (on
Windows only).
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "integrations" / "claude" / "plugin"
LAUNCHER_PATH = REPO_ROOT / "integrations" / "launcher" / "s0ma_launch.py"

PLUGIN_MANIFEST = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
HOOKS_CONFIG = PLUGIN_DIR / "hooks" / "hooks.json"
MCP_CONFIG = PLUGIN_DIR / ".mcp.json"
HOOK_SCRIPT = PLUGIN_DIR / "hooks" / "session-start.sh"
EDIT_SCRIPT = PLUGIN_DIR / "hooks" / "edit-guard.sh"
SERVER_SCRIPT = PLUGIN_DIR / "scripts" / "s0ma-serve"
SERVER_CMD = PLUGIN_DIR / "scripts" / "s0ma-serve.cmd"
STAND_IN_PS1 = PLUGIN_DIR / "scripts" / "s0ma-stand-in.ps1"
MESSAGE_FILE = PLUGIN_DIR / "scripts" / "not-set-up.txt"
PLUGIN_LAUNCHER = PLUGIN_DIR / "launcher" / "s0ma_launch.py"
PLUGIN_LOCK = PLUGIN_DIR / "launcher" / "s0ma_launch.py.lock"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PACKAGE_PYPROJECTS = sorted((REPO_ROOT / "packages").glob("*/pyproject.toml"))

#: Every POSIX script that finds uv on its own.
SH_FINDERS = (
    HOOK_SCRIPT,
    EDIT_SCRIPT,
    SERVER_SCRIPT,
    PLUGIN_DIR / "bin" / "s0ma",
    PLUGIN_DIR / "bin" / "s0ma-launch",
)

#: Every Windows batch file that finds uv on its own.
CMD_FINDERS = (
    SERVER_CMD,
    PLUGIN_DIR / "bin" / "s0ma.cmd",
    PLUGIN_DIR / "bin" / "s0ma-launch.cmd",
)

#: Every script a hook command or a server command runs, directly or by name.
COMMAND_SCRIPTS = (HOOK_SCRIPT, EDIT_SCRIPT, SERVER_SCRIPT, SERVER_CMD)

#: The one variable a hook or server command may contain.
ALLOWED_VARIABLE = "CLAUDE_PLUGIN_ROOT"

#: ``${NAME}``, ``${NAME:-default}`` and a bare ``$NAME``.
VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.]*)[^}]*\}|\$([A-Za-z_][A-Za-z0-9_]*)")


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} must hold a JSON object"
    return data


@pytest.fixture(scope="module")
def launcher() -> ModuleType:
    """``s0ma_launch.py``, imported from its path under a name of this suite's own."""
    spec = importlib.util.spec_from_file_location("s0ma_launch_for_rule_tests", LAUNCHER_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise RuntimeError(f"could not load the launcher from {LAUNCHER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def hook_handlers() -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for entries in read_json(HOOKS_CONFIG)["hooks"].values():
        for entry in entries:
            found.extend(entry["hooks"])
    return found


def command_lines() -> list[tuple[str, list[str]]]:
    """``(where, [command, *args])`` for every hook command and server command."""
    lines: list[tuple[str, list[str]]] = []
    for index, handler in enumerate(hook_handlers()):
        lines.append((f"hook {index}", [handler["command"], *handler.get("args", [])]))
    for name, server in read_json(MCP_CONFIG)["mcpServers"].items():
        lines.append((f"server {name}", [server["command"], *server.get("args", [])]))
    return lines


def uv_run_lines(text: str) -> list[str]:
    """Every line of a script that runs ``uv run``, however uv is spelled."""
    return [
        line.strip()
        for line in text.splitlines()
        if re.search(r'(?:"\$uv"|"%uv%"|\buv)\s+run\b', line)
        and not line.lstrip().startswith(("#", "rem "))
    ]


def marked_block(text: str, comment: str) -> str:
    """The lines between ``BEGIN uv places`` and ``END uv places``."""
    begin = f"{comment} BEGIN uv places"
    end = f"{comment} END uv places"
    assert text.count(begin) == 1 and text.count(end) == 1, "one marked list, exactly"
    return text.split(begin, 1)[1].split(end, 1)[0]


def sh_places(text: str) -> list[str]:
    """The uv places a POSIX script tries, in order, with variables left in."""
    block = marked_block(text, "#")
    listed = block.split("for candidate in", 1)[1].split("\n", 1)[1]
    words = listed.split("do", 1)[0].replace("\\", " ").split()
    return [word.strip('"') for word in words]


def cmd_places(text: str) -> list[str]:
    """The uv places a batch file tries, in order, with variables left in."""
    block = marked_block(text, "rem")
    return re.findall(r'set "uv=([^"]+)"', block)


# ---------------------------------------------------------------------------
# The directory's blocking rules.
# ---------------------------------------------------------------------------


def test_the_plugin_manifest_has_no_user_config() -> None:
    """No ``userConfig`` anywhere, so no settings dialog at install."""
    text = PLUGIN_MANIFEST.read_text(encoding="utf-8")
    assert "userConfig" not in text
    for path in (HOOKS_CONFIG, MCP_CONFIG, *COMMAND_SCRIPTS, STAND_IN_PS1):
        assert "user_config" not in path.read_text(encoding="utf-8"), path.name


def test_commands_name_no_variable_but_the_plugin_root() -> None:
    """In every hook command and server command, its arguments included."""
    lines = command_lines()
    assert len(lines) == 5, f"four hook commands and one server are expected: {lines}"
    for where, words in lines:
        for word in words:
            for braced, bare in VARIABLE.findall(word):
                name = braced or bare
                assert name == ALLOWED_VARIABLE, f"{where} uses ${name}: {word!r}"


def test_the_rule_catches_what_it_is_for() -> None:
    """Anti-vacuity: the pattern finds the forms a stray variable takes."""
    names = {b or s for b, s in VARIABLE.findall("${user_config.x} ${HOME:-/n} $PATH")}
    assert names == {"user_config.x", "HOME", "PATH"}


def test_every_uv_run_is_locked_or_frozen() -> None:
    """In the commands themselves and in every script they run or that finds uv."""
    for where, words in command_lines():
        if words[0] == "uv" and words[1:2] == ["run"]:
            assert {"--locked", "--frozen"} & set(words), f"{where}: {words}"
    scripts = {*COMMAND_SCRIPTS, *SH_FINDERS, *CMD_FINDERS}
    seen = 0
    for path in sorted(scripts):
        for line in uv_run_lines(path.read_text(encoding="utf-8")):
            seen += 1
            assert "--frozen" in line or "--locked" in line, f"{path.name}: {line}"
    assert seen >= len(scripts), "every script that finds uv also runs it"


def test_the_session_start_hook_is_shell_form() -> None:
    """No ``args``; one line with no command substitution and no wildcard."""
    handlers = read_json(HOOKS_CONFIG)["hooks"]["SessionStart"][0]["hooks"]
    assert len(handlers) == 1
    handler = handlers[0]
    assert "args" not in handler
    line = handler["command"]
    assert line == (
        'echo --% >/dev/null; sh "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh" # | out-null'
    )


def test_every_hook_line_is_one_script_and_plain_words() -> None:
    """The same for every hook: ``sh``, one quoted path, at most one plain word,
    between the opening and closing that make PowerShell run nothing.

    Inside that frame, no command substitution, no wildcard, no second
    command and no quoting but the one path's double quotes.
    """
    opening = "echo --% >/dev/null; "
    closing = " # | out-null"
    for handler in hook_handlers():
        assert "args" not in handler
        line = handler["command"]
        assert line.startswith(opening) and line.endswith(closing), line
        line = line[len(opening) : -len(closing)]
        for forbidden in ("$(", "`", "*", "?", "[", ";", "&", "|", "#", ">", "'", "\\"):
            assert forbidden not in line, f"a hook line carries {forbidden!r}: {line}"
        words = line.split(" ")
        assert words[0] == "sh" and len(words) in (2, 3), line
        assert re.fullmatch(r'"\$\{CLAUDE_PLUGIN_ROOT\}/hooks/[a-z-]+\.sh"', words[1]), line
        if len(words) == 3:
            assert re.fullmatch(r"[a-z-]+", words[2]), line


def test_the_server_command_is_a_script_with_its_windows_twin() -> None:
    """An extensionless path, with the ``.cmd`` Claude Code runs on Windows beside it."""
    command = read_json(MCP_CONFIG)["mcpServers"]["s0ma"]["command"]
    assert command == "${CLAUDE_PLUGIN_ROOT}/scripts/s0ma-serve"
    target = PLUGIN_DIR / command.replace("${CLAUDE_PLUGIN_ROOT}/", "")
    assert target == SERVER_SCRIPT and target.is_file()
    assert target.with_name(target.name + ".cmd").is_file()


def test_the_server_scripts_are_not_on_the_bash_tools_path() -> None:
    """``bin/`` is on the Bash tool's ``PATH``; the server scripts are not for it."""
    for path in (SERVER_SCRIPT, SERVER_CMD, STAND_IN_PS1):
        assert path.parent.name == "scripts"


# ---------------------------------------------------------------------------
# One list of uv places.
# ---------------------------------------------------------------------------

POSIX_ENV = {"HOME": "/H"}
WINDOWS_ENV = {"USERPROFILE": "/P", "LOCALAPPDATA": "/L", "ProgramFiles": "/F"}

SH_SUBSTITUTIONS = {
    "${HOME:-/nonexistent}": "/H",
    "${USERPROFILE:-/nonexistent}": "/P",
    "${LOCALAPPDATA:-/nonexistent}": "/L",
    "${ProgramFiles:-/nonexistent}": "/F",
}
CMD_SUBSTITUTIONS = {"%USERPROFILE%": "/P", "%LOCALAPPDATA%": "/L", "%ProgramFiles%": "/F"}


def expected_places(launcher: ModuleType, *, windows: bool) -> list[str]:
    env = WINDOWS_ENV if windows else POSIX_ENV
    return [path.as_posix() for path in launcher.uv_candidates(env, windows=windows)]


def substituted(place: str, table: dict[str, str]) -> str:
    for variable, value in table.items():
        place = place.replace(variable, value)
    return place.replace("\\", "/")


@pytest.mark.parametrize("script", SH_FINDERS, ids=lambda path: path.name)
def test_posix_scripts_look_where_the_launcher_looks(
    script: Path, launcher: ModuleType
) -> None:
    """POSIX places first, then the Windows places Git Bash can see, in order."""
    places = [substituted(p, SH_SUBSTITUTIONS) for p in sh_places(script.read_text(encoding="utf-8"))]
    expected = expected_places(launcher, windows=False) + expected_places(launcher, windows=True)
    assert places == expected, f"{script.name} drifted from uv_candidates"
    assert "command -v uv" in script.read_text(encoding="utf-8"), "PATH comes first"


@pytest.mark.parametrize("script", CMD_FINDERS, ids=lambda path: path.name)
def test_batch_files_look_where_the_launcher_looks_on_windows(
    script: Path, launcher: ModuleType
) -> None:
    places = [substituted(p, CMD_SUBSTITUTIONS) for p in cmd_places(script.read_text(encoding="utf-8"))]
    assert places == expected_places(launcher, windows=True), (
        f"{script.name} drifted from uv_candidates"
    )
    assert "%%~$PATH:I" in script.read_text(encoding="utf-8"), "PATH comes first"


def test_the_drift_check_catches_a_drift(launcher: ModuleType) -> None:
    """Anti-vacuity: a list with one place missing does not pass."""
    text = SERVER_SCRIPT.read_text(encoding="utf-8").replace(
        '        /opt/homebrew/bin/uv \\\n', ""
    )
    places = [substituted(p, SH_SUBSTITUTIONS) for p in sh_places(text)]
    assert places != expected_places(launcher, windows=False) + expected_places(
        launcher, windows=True
    )


# ---------------------------------------------------------------------------
# One message, one skill name.
# ---------------------------------------------------------------------------


def plugin_message() -> str:
    raw = MESSAGE_FILE.read_bytes()
    assert raw.endswith(b"\n") and raw.count(b"\n") == 1, "one line, LF-ended"
    return raw.decode("ascii").rstrip("\n")


def test_the_message_names_the_launchers_front_door(launcher: ModuleType) -> None:
    """The message and the launcher's own "tools missing" words name one skill."""
    message = plugin_message()
    named = set(re.findall(r"/s0ma:[a-z-]+", message))
    assert named == {launcher.START_SKILL}
    assert launcher.START_SKILL == "/s0ma:start"
    assert launcher.START_SKILL in launcher.HINT_START_SKILL
    assert launcher.START_SKILL in launcher.HINT_START_ACTION


def test_everything_that_says_not_set_up_names_the_same_door(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One name across every text a machine with no s0ma produces.

    The plugin's message, the session hint for the person and for the model,
    the stub server's instructions, its status tool and its answer to a tool it
    does not have, and ``status``'s next step all name ``/s0ma:start`` and no
    other skill. ``/s0ma:setup`` is for repairing an install, and none of these
    is about one.
    """
    monkeypatch.setenv("S0MA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("S0MA_TOOLCHAIN", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    project = tmp_path / "project"
    project.mkdir()
    resolution = launcher.resolve_toolchain(project=project)
    assert resolution.kind == launcher.KIND_NONE
    hint = launcher.tools_missing_hint(resolution.reason)
    report = launcher.status_report(project=project)
    context = launcher.StubContext(resolution=resolution, project=project)
    missing_tool = launcher.stub_call_tool(1, {"name": "s0ma_anything"}, context)
    texts = {
        "not-set-up.txt": plugin_message(),
        "hint for the person": hint.message,
        "hint for the model": hint.context,
        "hint when too long": launcher.HINT_TOO_LONG_CONTEXT,
        "stub instructions": launcher.stub_instructions(resolution),
        "stub status": launcher.stub_status_text(report),
        "stub unknown tool": missing_tool["result"]["content"][0]["text"],
        "status next step": launcher.next_step(resolution, project=project),
    }
    for where, text in texts.items():
        assert text is not None, where
        assert set(re.findall(r"/s0ma:[a-z-]+", text)) == {"/s0ma:start"}, (
            f"{where} names {sorted(set(re.findall(r'/s0ma:[a-z-]+', text)))}: {text!r}"
        )


def test_the_message_says_what_it_must(launcher: ModuleType) -> None:
    """Plain, short, ASCII, and calm: s0ma is not set up, which is expected."""
    message = plugin_message()
    assert message.isascii()
    assert len(message) < launcher.HINT_MAX_CHARS
    assert "not set up on this machine yet" in message
    assert "tools are not available" in message
    assert "not a fault" in message
    assert "server is not running" not in message, "the stand-in server is running"
    assert '"' not in message and "\\" not in message


def test_every_script_that_speaks_reads_the_one_message() -> None:
    """No script carries its own copy of the words."""
    assert "not-set-up.txt" in HOOK_SCRIPT.read_text(encoding="utf-8")
    assert "not-set-up.txt" in SERVER_SCRIPT.read_text(encoding="utf-8")
    assert "not-set-up.txt" in STAND_IN_PS1.read_text(encoding="utf-8")
    words = plugin_message()[:40]
    for path in (HOOK_SCRIPT, SERVER_SCRIPT, STAND_IN_PS1):
        assert words not in path.read_text(encoding="utf-8"), path.name


# ---------------------------------------------------------------------------
# The lock file ``--frozen`` reads.
# ---------------------------------------------------------------------------


def test_the_lock_file_is_beside_the_launcher_the_plugin_runs() -> None:
    """Newer uv refuses ``--frozen`` on a script with no lock file beside it."""
    assert PLUGIN_LOCK.is_file(), f"{PLUGIN_LOCK} is missing"
    assert PLUGIN_LOCK.read_bytes() == LAUNCHER_PATH.with_name(
        LAUNCHER_PATH.name + ".lock"
    ).read_bytes()


def test_the_lock_file_matches_the_launchers_header(tmp_path: Path) -> None:
    """Asked of uv itself, offline, on a copy so nothing in the tree is touched."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("no uv on PATH, so uv cannot be asked whether the lock is current")
    script = tmp_path / "s0ma_launch.py"
    shutil.copyfile(LAUNCHER_PATH, script)
    shutil.copyfile(LAUNCHER_PATH.with_name(LAUNCHER_PATH.name + ".lock"), tmp_path / "s0ma_launch.py.lock")
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        [uv, "lock", "--script", str(script), "--check", "--offline"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 0, (
        "the lock file no longer matches the launcher's header; run `uv lock "
        "--script integrations/launcher/s0ma_launch.py`, then "
        f"`uv run python scripts/sync_integrations.py --write`:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# One folder for the Pythons uv downloads for s0ma.
# ---------------------------------------------------------------------------

#: The variable every script and the launcher set, unless the person has.
PYTHON_DIR_VARIABLE = "UV_PYTHON_INSTALL_DIR"


def home_block(text: str, comment: str) -> str:
    """The lines between ``BEGIN s0ma home`` and ``END s0ma home``, both markers in."""
    begin = f"{comment} BEGIN s0ma home"
    end = f"{comment} END s0ma home"
    assert text.count(begin) == 1 and text.count(end) == 1, "one marked block"
    start = text.index(begin)
    return text[start : text.index(end) + len(end)]


def first_uv_call(text: str) -> int:
    """Where a script first runs uv: ``uv run`` or ``uv python find``."""
    found = [
        text.index(line)
        for line in text.splitlines()
        if re.search(r'(?:"\$uv"|"%uv%")\s+(?:run|python)\b', line)
        and not line.lstrip().startswith(("#", "rem "))
    ]
    assert found, "the script runs uv"
    return min(found)


def blocks_differ(blocks: dict[str, str]) -> list[str]:
    """The scripts whose block is not the first one's, by name."""
    first = next(iter(blocks.values()))
    return [name for name, block in blocks.items() if block != first]


def test_every_script_that_runs_uv_names_the_python_folder_first() -> None:
    """All eight entry scripts carry the rule, before uv is run."""
    for path, comment in [*((p, "#") for p in SH_FINDERS), *((p, "rem") for p in CMD_FINDERS)]:
        text = path.read_text(encoding="utf-8")
        block = home_block(text, comment)
        assert PYTHON_DIR_VARIABLE in block, path.name
        assert text.index(block) < first_uv_call(text), f"{path.name} runs uv first"
    assert len(SH_FINDERS) + len(CMD_FINDERS) == 8


def test_the_rule_is_the_same_in_every_script_of_a_kind() -> None:
    """A change to one script that is not made in the others fails here."""
    sh = {p.name: home_block(p.read_text(encoding="utf-8"), "#") for p in SH_FINDERS}
    cmd = {p.name: home_block(p.read_text(encoding="utf-8"), "rem") for p in CMD_FINDERS}
    assert blocks_differ(sh) == [], "the POSIX scripts' rules drifted apart"
    assert blocks_differ(cmd) == [], "the batch files' rules drifted apart"


def test_the_sameness_check_catches_a_drift() -> None:
    """Anti-vacuity: one script with its folder renamed does not pass."""
    sh = {p.name: home_block(p.read_text(encoding="utf-8"), "#") for p in SH_FINDERS}
    sh[SERVER_SCRIPT.name] = sh[SERVER_SCRIPT.name].replace("/python", "/pythons")
    assert blocks_differ(sh) == [SERVER_SCRIPT.name]


#: ``(case, environment)``: what the rule is held to, Windows or not.
POSIX_CASES = (
    ("home only", {"HOME": "/h o/me"}),
    ("S0MA_HOME", {"HOME": "/h", "S0MA_HOME": "/a b/state"}),
    ("S0MA_HOME blank", {"HOME": "/h", "S0MA_HOME": "   "}),
    ("S0MA_HOME padded", {"HOME": "/h", "S0MA_HOME": "  /a b/state  "}),
    ("S0MA_HOME under ~", {"HOME": "/h o", "S0MA_HOME": "~/state"}),
    ("set by the person", {"HOME": "/h", PYTHON_DIR_VARIABLE: "/mine/pythons"}),
)
WINDOWS_CASES = (
    ("profile only", {"USERPROFILE": "C:\\Users\\Rob Smith", "HOME": "/c/Users/Rob Smith"}),
    ("S0MA_HOME", {"USERPROFILE": "C:\\Users\\Rob", "S0MA_HOME": "D:\\s0ma state"}),
    ("S0MA_HOME blank", {"USERPROFILE": "C:\\Users\\Rob", "S0MA_HOME": "   "}),
    ("set by the person", {"USERPROFILE": "C:\\Users\\Rob", PYTHON_DIR_VARIABLE: "E:\\py"}),
)


def launchers_folder(
    launcher: ModuleType, env: dict[str, str], windows: bool, monkeypatch: pytest.MonkeyPatch
) -> str:
    """What the launcher hands uv for *env*, with forward slashes.

    ``Path.expanduser`` reads this process's ``HOME``, so it is set to *env*'s.
    """
    monkeypatch.setattr(launcher, "is_windows", lambda: windows)
    if "HOME" in env:
        monkeypatch.setenv("HOME", env["HOME"])
    return str(launcher.child_environment(env)[PYTHON_DIR_VARIABLE]).replace("\\", "/")


def sh_folder(env: dict[str, str], tmp_path: Path) -> str:
    """What the POSIX scripts' rule sets for *env*, run in ``sh``."""
    script = tmp_path / "rule.sh"
    block = home_block(SERVER_SCRIPT.read_text(encoding="utf-8"), "#")
    script.write_text(
        block + '\nprintf \'%s\\n\' "${UV_PYTHON_INSTALL_DIR-}"\n', encoding="utf-8", newline="\n"
    )
    done = subprocess.run(  # noqa: S603 - a fixed, local command
        ["sh", str(script)], env=env, capture_output=True, text=True, timeout=30, check=False
    )
    assert done.returncode == 0 and done.stderr == "", done.stderr
    return done.stdout.rstrip("\n").replace("\\", "/")


posix_only = pytest.mark.skipif(
    os.name == "nt" or shutil.which("sh") is None,
    reason="the POSIX rule is run in a POSIX sh; Git Bash rewrites HOME as it starts",
)
windows_only = pytest.mark.skipif(os.name != "nt", reason="cmd.exe runs only on Windows")


@posix_only
@pytest.mark.parametrize(("case", "env"), POSIX_CASES, ids=[c for c, _ in POSIX_CASES])
def test_the_posix_rule_is_the_launchers(
    case: str,
    env: dict[str, str],
    launcher: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert sh_folder(env, tmp_path) == launchers_folder(launcher, env, False, monkeypatch), case


@posix_only
@pytest.mark.parametrize(("case", "env"), WINDOWS_CASES, ids=[c for c, _ in WINDOWS_CASES])
def test_the_posix_rule_is_the_launchers_under_git_bash(
    case: str,
    env: dict[str, str],
    launcher: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows marks itself with ``OS=Windows_NT``, which Git Bash passes on."""
    env = {**env, "OS": "Windows_NT"}
    assert sh_folder(env, tmp_path) == launchers_folder(launcher, env, True, monkeypatch), case


@windows_only
@pytest.mark.parametrize(("case", "env"), WINDOWS_CASES, ids=[c for c, _ in WINDOWS_CASES])
def test_the_batch_rule_is_the_launchers(
    case: str,
    env: dict[str, str],
    launcher: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # pragma: no cover - Windows only
    script = tmp_path / "rule.cmd"
    block = home_block(SERVER_CMD.read_text(encoding="utf-8"), "rem")
    script.write_text(
        "@echo off\nsetlocal\n" + block + "\necho [%UV_PYTHON_INSTALL_DIR%]\n",
        encoding="utf-8",
        newline="\n",
    )
    names = ("S0MA_HOME", "USERPROFILE", "HOME", PYTHON_DIR_VARIABLE)
    base = {k: v for k, v in os.environ.items() if k.upper() not in names}
    done = subprocess.run(  # noqa: S603 - a fixed, local command
        ["cmd.exe", "/d", "/c", str(script)],
        env={**base, **env},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode == 0 and done.stderr == "", done.stderr
    shown = done.stdout.strip()
    assert shown.startswith("[") and shown.endswith("]"), shown
    got = shown[1:-1].replace("\\", "/")
    assert got == launchers_folder(launcher, env, True, monkeypatch), case


# ---------------------------------------------------------------------------
# The Pythons s0ma supports.
# ---------------------------------------------------------------------------


def supported_minors(launcher: ModuleType) -> set[int]:
    """``>=3.A,<3.B`` as the set of minor versions A to B-1."""
    found = re.fullmatch(r">=3\.(\d+),<3\.(\d+)", launcher.SUPPORTED_PYTHON)
    assert found is not None, f"not a range of 3.x: {launcher.SUPPORTED_PYTHON}"
    return set(range(int(found.group(1)), int(found.group(2))))


def test_the_supported_pythons_are_the_ones_ci_runs(launcher: ModuleType) -> None:
    """When the CI matrix grows, this is what says to move the cap.

    ``.github/workflows/ci.yml`` runs the gate on each ``python-version`` in its
    matrix; the range the launcher asks uv for is exactly those.
    """
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    listed = re.search(r"(?m)^\s+python-version:\s*\[([^\]]*)\]", text)
    assert listed is not None, "ci.yml has no python-version list"
    versions = {item.strip().strip("\"'") for item in listed.group(1).split(",")}
    assert {int(v.split(".")[1]) for v in versions} == supported_minors(launcher)
    assert all(v.startswith("3.") for v in versions), versions


def test_the_supported_pythons_are_the_packages_classifiers(launcher: ModuleType) -> None:
    """Each package says which Pythons it is for, and its floor is the launcher's."""
    assert PACKAGE_PYPROJECTS, "no package manifests found"
    for path in PACKAGE_PYPROJECTS:
        with path.open("rb") as handle:
            project = tomllib.load(handle)["project"]
        minors = {
            int(c.rsplit(".", 1)[1])
            for c in project.get("classifiers", [])
            if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)
        }
        if not minors:
            continue
        assert minors == supported_minors(launcher), path.parent.name
        floor = min(supported_minors(launcher))
        assert project["requires-python"] == f">=3.{floor}", path.parent.name


def test_the_server_scripts_probe_for_a_supported_python(launcher: ModuleType) -> None:
    """The stand-in or the real server is chosen by the range the launcher accepts."""
    for path in (SERVER_SCRIPT, SERVER_CMD):
        probes = re.findall(r"python find [^\n]*?['\"]([^'\"]+)['\"]", path.read_text(encoding="utf-8"))
        assert probes == [launcher.SUPPORTED_PYTHON], f"{path.name}: {probes}"
