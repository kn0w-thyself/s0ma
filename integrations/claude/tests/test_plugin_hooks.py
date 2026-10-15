"""What the plugin's ``SessionStart`` hook must look like.

The hook is four lines of JSON and one command, and every one of the rules below
comes from something that would otherwise break quietly:

* **Exec form.** ``args`` is present, so Claude Code resolves ``command`` as an
  executable and spawns it directly, with each argument passed exactly as
  written and no shell to reinterpret the placeholder in it
  (<https://code.claude.com/docs/en/hooks#exec-form-and-shell-form>).
* **No ``${user_config.*}``.** Since Claude Code v2.1.207 those are rejected in
  shell-form hook commands; exec form is the documented way round it, and this
  hook needs no configured value at all, so it asks for none (research note
  section 1.4).
* **The same launcher the server runs.** ``.mcp.json`` and this file must name
  one file. Two launchers, one of them stale, is the kind of difference nobody
  finds for a week.
* **One event.** ``SessionStart`` runs on every session and Claude's first
  answer waits for it, so this plugin declares that one hook and no other.

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


def test_only_session_start_is_declared() -> None:
    """One event, one handler. A plugin that hooks more than it says it does is
    a plugin nobody can review from its install screen."""
    config = read_json(HOOKS_CONFIG)
    assert list(config) == ["hooks"]
    assert list(config["hooks"]) == ["SessionStart"]
    assert len(config["hooks"]["SessionStart"]) == 1
    assert len(handlers()) == 1


def test_the_hook_runs_a_command_in_exec_form() -> None:
    """``args`` present means no shell: each argument is passed exactly as written."""
    handler = the_handler()
    assert handler["type"] == "command"
    assert isinstance(handler.get("args"), list) and handler["args"], (
        "the hook must be exec form: `command` plus a non-empty `args` list"
    )
    assert isinstance(handler["command"], str)
    assert " " not in handler["command"], (
        "in exec form `command` is one executable name, not a shell line"
    )


def test_the_hook_is_given_a_short_leash() -> None:
    """A command hook's documented default is 600 seconds; Claude's first answer
    waits for SessionStart, so this one says a number of its own."""
    timeout = the_handler()["timeout"]
    assert isinstance(timeout, int) and not isinstance(timeout, bool)
    assert 0 < timeout <= MAX_TIMEOUT_SECONDS


def test_the_hook_runs_the_launcher_through_uv() -> None:
    """``uv run --script <launcher> session-hint`` - the same three words the
    MCP server is started with, and the sub-command this hook exists for."""
    handler = the_handler()
    assert handler["command"] == "uv"
    assert handler["args"][:2] == ["run", "--script"]
    assert handler["args"][-1] == HOOK_COMMAND


def test_the_hook_and_the_server_name_one_launcher() -> None:
    """Both point at the copy inside the plugin, by the same placeholder."""
    server = read_json(MCP_CONFIG)["mcpServers"]["s0ma"]
    hook_script = the_handler()["args"][2]
    assert hook_script == "${CLAUDE_PLUGIN_ROOT}/launcher/s0ma_launch.py"
    assert hook_script in server["args"], (
        f"the hook runs {hook_script}, which the MCP server does not: {server['args']}"
    )


def test_the_hook_named_script_is_there_and_is_the_launcher() -> None:
    """The placeholder resolves to a file that exists and has its PEP 723 header."""
    hook_script = the_handler()["args"][2]
    resolved = PLUGIN_DIR / hook_script.replace("${CLAUDE_PLUGIN_ROOT}/", "")
    assert resolved.is_file(), f"{resolved} is missing"
    head = resolved.read_bytes()[:200].decode("utf-8")
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
    text = HOOKS_CONFIG.read_text(encoding="utf-8")
    assert "${user_config." not in text


def test_the_hook_sets_no_environment_variables() -> None:
    """A command hook handler has no documented ``env`` field, so the hook cannot
    widen ``PATH`` the way the MCP server's own ``env`` block does. Writing one
    anyway would be an unknown field that a strict validator may refuse."""
    assert "env" not in the_handler()


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
