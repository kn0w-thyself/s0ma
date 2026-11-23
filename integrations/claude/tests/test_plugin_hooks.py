"""What the plugin's three hooks must look like.

``SessionStart`` says the one line a session may begin with. ``PreToolUse`` on
Write and Edit refuses an edit under a s0ma project's build folder, and
``PostToolUse`` on Write and Edit to a ``.s0ma`` file hands Claude what
``s0ma check`` found. Every one of the rules below comes from something that
would otherwise break quietly:

* **Shell form, running one script.** There is no ``args``, so Claude Code
  hands ``command`` to a shell: ``sh`` on macOS and Linux, Git Bash on Windows
  (<https://code.claude.com/docs/en/hooks#exec-form-and-shell-form>). Each
  command is ``sh`` and one quoted path under ``${CLAUDE_PLUGIN_ROOT}``, and
  for the edit hooks one plain word saying which, so a machine with no uv
  still has something that starts: the script, which finds uv itself. Exec
  form would need uv to exist before anything could run, and a hook that
  cannot start is a hook error in front of the person.
* **A timeout on every command.** The documented default is 600 seconds, and
  Claude waits for each of these.
* **No ``if`` on ``SessionStart``.** ``if`` is read on tool events only; on any
  other event a hook that has one never runs. The check after an edit has one
  per tool, ``Write(**/*.s0ma)`` and ``Edit(**/*.s0ma)``, so it runs only for
  a ``.s0ma`` file where Claude Code honors it; its script gives the same
  answer where it does not.
* **No ``${user_config.*}``.** Since Claude Code v2.1.207 those are rejected in
  shell-form hook commands, and these hooks need no configured value at all.
* **The same launcher the server runs.** The hook script and the server script
  must run one file. Two launchers, one of them stale, is the kind of
  difference nobody finds for a week.
* **Three events, and no more.** A plugin that hooks more than it says it does
  is a plugin nobody can review from its install screen.

Nothing here installs a plugin, changes any Claude configuration, or runs a
model: the only subprocess is the CLI's own offline ``plugin validate``.
"""

from __future__ import annotations

import argparse
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
CLAUDE_DIR = REPO_ROOT / "integrations" / "claude"
PLUGIN_DIR = CLAUDE_DIR / "plugin"

HOOKS_CONFIG = PLUGIN_DIR / "hooks" / "hooks.json"
MCP_CONFIG = PLUGIN_DIR / ".mcp.json"
LAUNCHER_PATH = REPO_ROOT / "integrations" / "launcher" / "s0ma_launch.py"

#: The sub-command this hook exists to run.
HOOK_COMMAND = "session-hint"

#: The events this plugin hooks, and nothing else.
EVENTS = ["PostToolUse", "PreToolUse", "SessionStart"]

#: The edit hooks' command lines, and the script and launcher commands they name.
EDIT_SCRIPT = PLUGIN_DIR / "hooks" / "edit-guard.sh"
BEFORE_EDIT_LINE = 'sh "${CLAUDE_PLUGIN_ROOT}/hooks/edit-guard.sh" before-edit'
AFTER_EDIT_LINE = 'sh "${CLAUDE_PLUGIN_ROOT}/hooks/edit-guard.sh" after-edit'
EDIT_COMMANDS = ("before-edit", "after-edit")

#: The before-edit hook runs before every Write and Edit, so it gets less time
#: than the one that runs a check after an edit.
MAX_BEFORE_EDIT_SECONDS = 10
MAX_AFTER_EDIT_SECONDS = 30

#: The hook's whole command line, and the script it names.
HOOK_SHELL_LINE = 'sh "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"'
HOOK_SCRIPT = PLUGIN_DIR / "hooks" / "session-start.sh"
SERVER_SCRIPT = PLUGIN_DIR / "scripts" / "s0ma-serve"

#: A SessionStart hook runs before Claude's first answer, so it is given a
#: short leash rather than the documented 600-second default.
MAX_TIMEOUT_SECONDS = 30

#: Passed to every `claude` subprocess so a test run never reaches the network.
OFFLINE_ENV = {
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
}


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def read_json(path: Path) -> dict[str, Any]:
    """Load one of the manifests, failing with a readable message if it is not JSON."""
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:  # pragma: no cover
        raise AssertionError(f"{path.name} is not valid UTF-8 JSON: {exc}") from exc
    assert isinstance(data, dict), f"{path.name} must hold a JSON object"
    return data


def handlers(event: str = "SessionStart") -> list[dict[str, Any]]:
    """Every hook handler declared for *event*."""
    found: list[dict[str, Any]] = []
    for entry in read_json(HOOKS_CONFIG)["hooks"].get(event, []):
        found.extend(entry["hooks"])
    return found


def the_handler() -> dict[str, Any]:
    """The one handler this plugin declares."""
    only = handlers()
    assert len(only) == 1, (
        f"expected exactly one SessionStart handler, found {len(only)}"
    )
    return only[0]


@pytest.fixture(scope="session")
def launcher() -> ModuleType:
    """``s0ma_launch.py``, imported from its path under a name of this suite's own."""
    spec = importlib.util.spec_from_file_location(
        "s0ma_launch_for_hook_tests", LAUNCHER_PATH
    )
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise RuntimeError(f"could not load the launcher from {LAUNCHER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def claude_cli() -> str | None:
    """The `claude` executable, if this machine has one on its PATH."""
    return shutil.which("claude")


def validate_supports_strict(binary: str) -> bool:
    """Whether this build of `claude plugin validate` understands ``--strict``."""
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        [binary, "plugin", "validate", "--help"],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, **OFFLINE_ENV},
    )
    return "--strict" in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# The file itself.
# ---------------------------------------------------------------------------


def test_hooks_config_is_where_claude_code_looks_for_it() -> None:
    """``hooks/hooks.json`` at the plugin root is the documented location."""
    assert HOOKS_CONFIG.is_file(), f"{HOOKS_CONFIG} is missing"


def test_hooks_config_is_canonical() -> None:
    """Two-space indent, sorted keys, plain ASCII, LF endings, one trailing newline.

    The house rule for anything committed (plan section 3.1 rule 9): the same
    content always produces the same bytes, so a diff only shows a real change.
    """
    raw = HOOKS_CONFIG.read_bytes()
    assert b"\r\n" not in raw, "hooks.json must use LF line endings"
    text = raw.decode("utf-8")
    assert text.isascii(), "hooks.json must be plain ASCII"
    canonical = json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"
    assert text == canonical, (
        "hooks.json is not in canonical form. Rewrite it with "
        "json.dumps(data, indent=2, sort_keys=True) and a trailing newline."
    )


def test_exactly_three_events_are_declared() -> None:
    """SessionStart, PreToolUse and PostToolUse, and no other. A plugin that
    hooks more than it says it does is a plugin nobody can review from its
    install screen."""
    config = read_json(HOOKS_CONFIG)
    assert list(config) == ["hooks"]
    assert sorted(config["hooks"]) == EVENTS
    assert len(config["hooks"]["SessionStart"]) == 1
    assert len(handlers()) == 1


def every_handler() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """``(event, matcher entry, handler)`` for every handler in the file."""
    found = []
    for event, entries in read_json(HOOKS_CONFIG)["hooks"].items():
        for entry in entries:
            for handler in entry["hooks"]:
                found.append((event, entry, handler))
    return found


def test_every_command_is_shell_form_with_a_timeout() -> None:
    """For each handler: a command, no ``args``, only ``${CLAUDE_PLUGIN_ROOT}``,
    and a timeout of its own."""
    seen = every_handler()
    assert len(seen) == 4
    for event, _entry, handler in seen:
        assert handler["type"] == "command", event
        assert "args" not in handler, f"{event}: the hook must be shell form"
        command = handler["command"]
        assert command.startswith('sh "${CLAUDE_PLUGIN_ROOT}/hooks/'), command
        assert command.count("${") == 1, f"{event}: one variable, the plugin root"
        assert "$" not in command.replace("${CLAUDE_PLUGIN_ROOT}", ""), command
        timeout = handler["timeout"]
        assert isinstance(timeout, int) and not isinstance(timeout, bool), event
        assert 0 < timeout <= MAX_TIMEOUT_SECONDS, event


def test_no_if_on_session_start() -> None:
    """``if`` switches a SessionStart hook off; it belongs on tool events only."""
    for event, entry, handler in every_handler():
        if event == "SessionStart":
            assert "if" not in handler and "if" not in entry
            assert "matcher" not in entry


def test_the_refusal_runs_before_every_write_and_edit() -> None:
    """No path filter: a project names its own build folder, so none would fit."""
    entries = read_json(HOOKS_CONFIG)["hooks"]["PreToolUse"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["matcher"] == "Write|Edit"
    [handler] = entry["hooks"]
    assert handler["command"] == BEFORE_EDIT_LINE
    assert "if" not in handler
    assert handler["timeout"] <= MAX_BEFORE_EDIT_SECONDS


def test_the_check_runs_after_a_s0ma_edit_once_per_tool() -> None:
    """One entry per tool, each with the one rule its ``if`` can hold."""
    entries = read_json(HOOKS_CONFIG)["hooks"]["PostToolUse"]
    seen = {}
    for entry in entries:
        [handler] = entry["hooks"]
        assert handler["command"] == AFTER_EDIT_LINE
        assert handler["timeout"] <= MAX_AFTER_EDIT_SECONDS
        seen[entry["matcher"]] = handler["if"]
    assert seen == {"Write": "Write(**/*.s0ma)", "Edit": "Edit(**/*.s0ma)"}


def test_the_edit_script_runs_the_launcher_commands_that_exist(launcher: ModuleType) -> None:
    """The script hands each hook's word to the launcher, which offers both."""
    text = EDIT_SCRIPT.read_text(encoding="utf-8")
    assert "launcher=$hooks_dir/../launcher/s0ma_launch.py" in text
    assert '--script "$launcher" "$event"' in text
    assert "before-edit | after-edit)" in text
    parser = launcher.build_parser()
    names: set[str] = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            names.update(action.choices)
    assert set(EDIT_COMMANDS) <= names


def test_the_hook_runs_a_command_in_shell_form() -> None:
    """No ``args``: the command is one shell line, ``sh`` and the script's path."""
    handler = the_handler()
    assert handler["type"] == "command"
    assert "args" not in handler, "the hook must be shell form: no `args` list"
    assert handler["command"] == HOOK_SHELL_LINE


def test_the_hook_is_given_a_short_leash() -> None:
    """A command hook's documented default is 600 seconds; Claude's first answer
    waits for SessionStart, so this one says a number of its own."""
    timeout = the_handler()["timeout"]
    assert isinstance(timeout, int) and not isinstance(timeout, bool)
    assert 0 < timeout <= MAX_TIMEOUT_SECONDS


def test_the_hook_script_runs_the_launcher_through_uv() -> None:
    """The script runs ``session-hint`` from the launcher inside the plugin."""
    text = HOOK_SCRIPT.read_text(encoding="utf-8")
    assert "launcher=$hooks_dir/../launcher/s0ma_launch.py" in text
    assert '--script "$launcher" session-hint' in text


def test_the_hook_and_the_server_name_one_launcher() -> None:
    """Both scripts run the copy inside the plugin, by the same relative path."""
    hook = HOOK_SCRIPT.read_text(encoding="utf-8")
    server = SERVER_SCRIPT.read_text(encoding="utf-8")
    assert "/../launcher/s0ma_launch.py" in hook
    assert "launcher=$scripts_dir/../launcher/s0ma_launch.py" in server
    assert '--script "$launcher" serve' in server


def test_the_hook_named_script_is_there_and_the_launcher_beside_it() -> None:
    """The placeholder resolves to the script, and the launcher it runs is there."""
    assert HOOK_SCRIPT.is_file(), f"{HOOK_SCRIPT} is missing"
    launcher_copy = PLUGIN_DIR / "launcher" / "s0ma_launch.py"
    head = launcher_copy.read_bytes()[:200].decode("utf-8")
    assert head.startswith("# /// script")
    assert "dependencies = []" in head


def test_the_sub_command_the_hook_runs_exists(launcher: ModuleType) -> None:
    """Read from the launcher's own parser, not from a list kept in step by hand."""
    parser = launcher.build_parser()
    names: set[str] = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            names.update(action.choices)
    assert HOOK_COMMAND in names, (
        f"the hook runs `{HOOK_COMMAND}`, which the launcher does not offer"
    )


# ---------------------------------------------------------------------------
# What it must not contain.
# ---------------------------------------------------------------------------


def test_no_user_config_substitution_anywhere() -> None:
    """Rejected in shell-form hook commands since v2.1.207, and unnecessary here:
    this hook reads local files and needs nothing configured to do it."""
    for path in (HOOKS_CONFIG, HOOK_SCRIPT, EDIT_SCRIPT):
        assert "user_config" not in path.read_text(encoding="utf-8"), path.name


def test_the_hook_sets_no_environment_variables() -> None:
    """A command hook handler has no documented ``env`` field, so the hook cannot
    widen ``PATH`` the way the MCP server's own ``env`` block does. Writing one
    anyway would be an unknown field that a strict validator may refuse."""
    for _event, _entry, handler in every_handler():
        assert "env" not in handler


def test_no_secret_shaped_string_is_in_the_file() -> None:
    """A key never reaches a hook command line, so none may appear here."""
    text = HOOKS_CONFIG.read_text(encoding="utf-8")
    for forbidden in ("license", "key", "token", "secret"):
        assert forbidden not in text.lower(), (
            f"hooks.json mentions {forbidden!r}; a hook never carries a secret"
        )


# ---------------------------------------------------------------------------
# The CLI's own verdict.
# ---------------------------------------------------------------------------


def test_the_plugin_still_validates_with_the_hook_in_it() -> None:
    """`claude plugin validate` accepts the plugin, strictly where it can."""
    binary = claude_cli()
    if binary is None:
        pytest.skip("no `claude` on PATH, so the CLI's own verdict cannot be taken")
    argv = [binary, "plugin", "validate", str(PLUGIN_DIR)]
    if validate_supports_strict(binary):
        argv.append("--strict")
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        argv,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, **OFFLINE_ENV},
    )
    assert result.returncode == 0, (
        f"claude plugin validate rejected the plugin:\n{result.stdout}{result.stderr}"
    )
