"""The first-run driver's own parts, on any machine, with no Claude and no uv needed.

``scripts/first_run_check.py`` is what the first-run workflow runs on GitHub's
runners. Its full checks need a machine with no uv and the real Claude Code, so
they run there. What is tested here is what lets those checks fail: the driver
refuses to start without being told whether to run Claude, it reads ``claude
mcp list`` lines in both sets of marks and calls a failed server failed, its
MCP client fails on a server that says nothing or writes something that is not
JSON, it takes Git's shell off a Windows ``PATH`` while keeping ``Git\\cmd``,
and it reads the hook's line once s0ma is installed: the standing note for
Claude and nothing for the person, or the one off line and nothing else. It
reads the edit hooks' answers too: silence, the refusal with the build folder
named, and a finding between the lead-in and the closing line.

Nothing here runs Claude: no test passes ``--claude``.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DRIVER = REPO_ROOT / "scripts" / "first_run_check.py"


@pytest.fixture(scope="module")
def driver() -> ModuleType:
    spec = importlib.util.spec_from_file_location("first_run_check_for_tests", DRIVER)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise RuntimeError(f"could not load {DRIVER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("leg", ["uv-absent", "uv-present"])
def test_the_driver_will_not_start_without_being_told_about_claude(leg: str) -> None:
    done = subprocess.run(  # noqa: S603 - this repository's own script
        [sys.executable, str(DRIVER), leg],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 2
    assert "--claude <command> or --no-claude" in done.stderr


def test_claude_needs_a_version_to_hold_it_to() -> None:
    done = subprocess.run(  # noqa: S603 - this repository's own script
        [sys.executable, str(DRIVER), "uv-absent", "--claude", "claude"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 2
    assert "--claude needs --claude-version" in done.stderr


@pytest.mark.parametrize(
    ("line", "connected"),
    [
        ("plugin:s0ma:s0ma: /x/plugin/scripts/s0ma-serve  - ✔ Connected", True),
        ("plugin:s0ma:s0ma: C:/x/plugin/scripts/s0ma-serve  - √ Connected", True),
        (
            "plugin:s0ma:s0ma: /x/plugin/scripts/s0ma-serve  - ✘ Failed to connect",
            False,
        ),
        (
            "plugin:s0ma:s0ma: C:/x/plugin/scripts/s0ma-serve  - × Failed to connect",
            False,
        ),
        ("plugin:s0ma:s0ma: /x/Connected/s0ma-serve  - ✘ Failed to connect", False),
    ],
)
def test_a_server_line_is_read_in_either_set_of_marks(
    driver: ModuleType, line: str, connected: bool
) -> None:
    output = f"Checking MCP server health...\n\n{line}\n"
    assert driver.server_line(output) == line
    assert driver.is_connected(line) is connected


def test_no_server_line_is_a_failure(driver: ModuleType) -> None:
    with pytest.raises(driver.CheckFailed):
        driver.server_line("No MCP servers configured.\n")


def test_git_shell_comes_off_a_windows_path_and_git_cmd_stays(
    driver: ModuleType,
) -> None:
    path = ";".join(
        [
            r"C:\Program Files\Git\bin",
            r"C:\Program Files\Git\usr\bin",
            r"C:\Program Files\Git\mingw64\bin",
            r"C:\Program Files\Git\cmd",
            r"C:\Windows\System32",
        ]
    )
    kept, dropped = driver.without_git_shell(path, ";")
    assert kept.split(";") == [r"C:\Program Files\Git\cmd", r"C:\Windows\System32"]
    assert len(dropped) == 3


def fake_server(body: str) -> list[str]:
    return [sys.executable, "-c", body]


def test_a_server_that_says_nothing_fails(driver: ModuleType, tmp_path: Path) -> None:
    session = driver.McpSession(
        fake_server("import sys; sys.stdin.readline()"), None, tmp_path
    )
    try:
        with pytest.raises(driver.CheckFailed, match="closed its output"):
            session.initialize()
    finally:
        session.kill()


def test_a_server_that_writes_something_else_fails(
    driver: ModuleType, tmp_path: Path
) -> None:
    body = "import sys; sys.stdin.readline(); print('hello'); sys.stdout.flush()"
    session = driver.McpSession(fake_server(body), None, tmp_path)
    try:
        with pytest.raises(driver.CheckFailed, match="not JSON"):
            session.initialize()
    finally:
        session.kill()


def test_a_server_that_answers_with_the_wrong_id_fails(
    driver: ModuleType, tmp_path: Path
) -> None:
    body = (
        "import sys; sys.stdin.readline(); "
        'print(\'{"jsonrpc":"2.0","id":7,"result":{}}\'); sys.stdout.flush()'
    )
    session = driver.McpSession(fake_server(body), None, tmp_path)
    try:
        with pytest.raises(driver.CheckFailed, match="id 0"):
            session.initialize()
    finally:
        session.kill()


@pytest.fixture(scope="module")
def launcher(driver: ModuleType) -> ModuleType:
    return driver.load_launcher()


def hook_ran(driver: ModuleType, printed: object, *, code: int = 0, stderr: str = "") -> object:
    out = printed if isinstance(printed, str) else json.dumps(printed, sort_keys=True) + "\n"
    return driver.Ran(code, out, stderr)


def note_of(launcher: ModuleType) -> str:
    prefs = launcher.read_preferences({}, Path("/nonexistent-for-the-test"))
    return str(launcher.standing_note(prefs))


def test_the_installed_hook_is_the_note_for_claude_only(
    driver: ModuleType, launcher: ModuleType
) -> None:
    printed = {
        "hookSpecificOutput": {
            "additionalContext": note_of(launcher),
            "hookEventName": "SessionStart",
        }
    }
    verdict = driver.check_hook_installed(hook_ran(driver, printed), launcher)
    assert "no systemMessage" in verdict


@pytest.mark.parametrize(
    "printed",
    [
        "",
        "not json\n",
        {"systemMessage": "hello"},
        {"hookSpecificOutput": {"additionalContext": "something else", "hookEventName": "SessionStart"}},
        "two\nlines\n",
    ],
    ids=["silent", "not json", "a line for the person", "not the note", "two lines"],
)
def test_the_installed_hook_check_fails_on_anything_else(
    driver: ModuleType, launcher: ModuleType, printed: object
) -> None:
    with pytest.raises(driver.CheckFailed):
        driver.check_hook_installed(hook_ran(driver, printed), launcher)


def test_the_installed_hook_check_fails_when_the_person_sees_a_line_too(
    driver: ModuleType, launcher: ModuleType
) -> None:
    printed = {
        "systemMessage": "hello",
        "hookSpecificOutput": {
            "additionalContext": note_of(launcher),
            "hookEventName": "SessionStart",
        },
    }
    with pytest.raises(driver.CheckFailed, match="showed the person"):
        driver.check_hook_installed(hook_ran(driver, printed), launcher)


def test_the_installed_hook_check_fails_on_stderr_or_an_exit_code(
    driver: ModuleType, launcher: ModuleType
) -> None:
    printed = {
        "hookSpecificOutput": {
            "additionalContext": note_of(launcher),
            "hookEventName": "SessionStart",
        }
    }
    with pytest.raises(driver.CheckFailed):
        driver.check_hook_installed(hook_ran(driver, printed, code=1), launcher)
    with pytest.raises(driver.CheckFailed):
        driver.check_hook_installed(hook_ran(driver, printed, stderr="x"), launcher)


def test_the_off_hook_is_the_one_line(driver: ModuleType, launcher: ModuleType) -> None:
    printed = {
        "hookSpecificOutput": {
            "additionalContext": launcher.HINT_OFF_HERE,
            "hookEventName": "SessionStart",
        }
    }
    assert "off line" in driver.check_hook_off(hook_ran(driver, printed), launcher)


@pytest.mark.parametrize("extra", ["note", "message"])
def test_the_off_hook_check_fails_on_anything_more(
    driver: ModuleType, launcher: ModuleType, extra: str
) -> None:
    printed: dict[str, object] = {
        "hookSpecificOutput": {
            "additionalContext": launcher.HINT_OFF_HERE
            + ("\n\n" + note_of(launcher) if extra == "note" else ""),
            "hookEventName": "SessionStart",
        }
    }
    if extra == "message":
        printed["systemMessage"] = "s0ma's tools are not available in this session."
    with pytest.raises(driver.CheckFailed):
        driver.check_hook_off(hook_ran(driver, printed), launcher)


# ---------------------------------------------------------------------------
# The edit hooks.
# ---------------------------------------------------------------------------


def refusal(launcher: ModuleType, build_dir: str = "build") -> dict[str, object]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": launcher.BUILD_DIR_REFUSAL.format(build_dir=build_dir),
        }
    }


def finding(launcher: ModuleType, body: str = "x:1: ERROR [PARSE_ERROR]") -> dict[str, object]:
    lead = launcher.EDIT_CHECK_LEAD.format(path="src/a.s0ma")
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"{lead}\n{body}\n{launcher.EDIT_CHECK_CLOSE}",
        }
    }


def test_the_driver_reads_both_edit_commands_from_hooks_json(driver: ModuleType) -> None:
    plugin = REPO_ROOT / "integrations" / "claude" / "plugin"
    for hook in ("before-edit", "after-edit"):
        command = driver.edit_hook_command(plugin, hook)
        assert command.endswith(f'/hooks/edit-guard.sh" {hook} # | out-null')
        assert "${" not in command


def test_a_silent_edit_hook_passes_and_anything_else_fails(driver: ModuleType) -> None:
    assert "stdout empty" in driver.check_edit_hook_silent(hook_ran(driver, ""), "before-edit")
    for ran in (hook_ran(driver, "x\n"), hook_ran(driver, "", code=1), hook_ran(driver, "", stderr="x")):
        with pytest.raises(driver.CheckFailed):
            driver.check_edit_hook_silent(ran, "before-edit")


def test_the_refusal_is_read(driver: ModuleType, launcher: ModuleType) -> None:
    verdict = driver.check_edit_refused(hook_ran(driver, refusal(launcher)), launcher, "build")
    assert "deny naming build/" in verdict


@pytest.mark.parametrize(
    "printed",
    ["", "not json\n", "refusal for another folder", "allow"],
)
def test_the_refusal_check_fails_on_anything_else(
    driver: ModuleType, launcher: ModuleType, printed: str
) -> None:
    shown: object = printed
    if printed == "refusal for another folder":
        shown = refusal(launcher, "out")
    elif printed == "allow":
        answer = refusal(launcher)
        answer["hookSpecificOutput"]["permissionDecision"] = "allow"  # type: ignore[index]
        shown = answer
    with pytest.raises(driver.CheckFailed):
        driver.check_edit_refused(hook_ran(driver, shown), launcher, "build")


def test_the_finding_is_read(driver: ModuleType, launcher: ModuleType) -> None:
    verdict = driver.check_edit_finding(
        hook_ran(driver, finding(launcher)), launcher, "src/a.s0ma", "PARSE_ERROR"
    )
    assert "names PARSE_ERROR" in verdict


@pytest.mark.parametrize("case", ["silent", "another code", "wrong event", "too long"])
def test_the_finding_check_fails_on_anything_else(
    driver: ModuleType, launcher: ModuleType, case: str
) -> None:
    shown: object = ""
    if case == "another code":
        shown = finding(launcher, "x:1: ERROR [OTHER]")
    elif case == "wrong event":
        answer = finding(launcher)
        answer["hookSpecificOutput"]["hookEventName"] = "PreToolUse"  # type: ignore[index]
        shown = answer
    elif case == "too long":
        shown = finding(launcher, "[PARSE_ERROR] " + "x" * 4000)
    with pytest.raises(driver.CheckFailed):
        driver.check_edit_finding(hook_ran(driver, shown), launcher, "src/a.s0ma", "PARSE_ERROR")


# ---------------------------------------------------------------------------
# Reading `claude plugin validate`, strict and with the directory profile.
# ---------------------------------------------------------------------------


def ran(driver: ModuleType, code: int, stdout: str = "", stderr: str = "") -> object:
    return driver.Ran(code, stdout, stderr)


def test_a_passed_verdict_is_read(driver: ModuleType) -> None:
    report = "Validating plugin manifest...\nWarnings:\n  ICON_MISSING\nValidation passed\n"
    assert driver.passed_verdict(ran(driver, 0, report), "validate") == "Validation passed"


def test_a_report_with_no_passed_verdict_fails(driver: ModuleType) -> None:
    with pytest.raises(driver.CheckFailed):
        driver.passed_verdict(ran(driver, 0, "Validation failed\n"), "validate")


@pytest.mark.parametrize(
    "stderr",
    [
        "error: unknown option '--profile'\n",
        "error: option '--profile <name>' argument 'directory' is invalid.\n",
    ],
)
def test_a_cli_that_refuses_the_profile_flag_is_told_apart(
    driver: ModuleType, stderr: str
) -> None:
    assert driver.profile_rejected(ran(driver, 1, "", stderr)) is True


def test_a_failed_directory_report_is_not_a_refused_flag(driver: ModuleType) -> None:
    report = (
        "Plugin directory: README_MISSING\n"
        "To fail on problems the directory refuses, run this command with --profile directory.\n"
        "Validation failed\n"
    )
    assert driver.profile_rejected(ran(driver, 1, report)) is False


FAKE_CLI = """\
#!/bin/sh
# Answers like `claude plugin validate` would, as FAKE_VALIDATE says.
printf '%s\\n' "$*" >> "$FAKE_LOG"
case "$*" in
    *--profile*)
        case $FAKE_VALIDATE in
            no-profile) echo "error: unknown option '--profile'" >&2; exit 1 ;;
            directory-fails) echo "Plugin directory: README_MISSING"; echo "Validation failed"; exit 1 ;;
        esac
        echo "Plugin directory warning: ICON_MISSING"
        echo "Validation passed"
        ;;
    *--strict*)
        case $FAKE_VALIDATE in
            strict-fails) echo "Validation failed (--strict treats warnings as errors)"; exit 1 ;;
        esac
        echo "Validation passed"
        ;;
    *) echo "neither flag was given" >&2; exit 2 ;;
esac
"""


@pytest.mark.skipif(sys.platform.startswith("win"), reason="the stand-in CLI is a sh script")
@pytest.mark.parametrize(
    ("mode", "outcome"),
    [
        ("pass", "--strict: Validation passed; --profile directory: Validation passed"),
        (
            "no-profile",
            "--strict: Validation passed; "
            "--profile directory: NOT RUN: this claude does not take --profile",
        ),
        ("strict-fails", None),
        ("directory-fails", None),
    ],
)
def test_validate_runs_strict_then_the_directory_profile(
    driver: ModuleType, tmp_path: Path, mode: str, outcome: str | None
) -> None:
    """Both runs happen, in that order, each must pass, and a CLI without the
    flag is said out loud rather than failed. No real Claude is run."""
    fake = tmp_path / "fake-cli"
    fake.write_text(FAKE_CLI, encoding="utf-8")
    fake.chmod(0o755)
    log = tmp_path / "argv.log"
    base = {
        "PATH": "/usr/bin:/bin",
        "FAKE_VALIDATE": mode,
        "FAKE_LOG": str(log),
    }
    cli = driver.Claude(str(fake), "0.0.0", tmp_path / "work")
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    if outcome is None:
        with pytest.raises(driver.CheckFailed):
            cli.validate(plugin, base, tmp_path)
    else:
        assert cli.validate(plugin, base, tmp_path) == outcome
    calls = log.read_text(encoding="utf-8").splitlines()
    assert calls[0] == f"plugin validate --strict {plugin}"
    if mode != "strict-fails":
        assert calls[1] == f"plugin validate --profile directory {plugin}"
        assert len(calls) == 2


# ---------------------------------------------------------------------------
# After a release: the install from the public package index.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("version", ["0.22.0", "1.0", "1.0.0rc1", "1.0.0a2", "1.0.0.post1", "2.0.0b1.dev3"])
def test_a_released_version_is_taken(driver: ModuleType, version: str) -> None:
    assert driver.release_version(version) == version


@pytest.mark.parametrize(
    "version",
    [
        "",
        "v0.22.0",
        "0.22.0+keyless",
        "0.22.0 ",
        " 0.22.0",
        "0.22.0;echo",
        "0.22.0$(id)",
        "0.22.0\n",
        "0..22",
        "0.22.",
        "0.22.0rc1.",
        ".0.22",
        "0.22.0-rc1",
        "../0.22.0",
        "latest",
        "1" * 65,
    ],
)
def test_anything_else_is_refused_before_anything_runs(version: str) -> None:
    done = subprocess.run(  # noqa: S603 - this repository's own script
        [sys.executable, str(DRIVER), "real-index", "--version", version],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 2
    assert "is not a released version" in done.stderr
    assert "working in" not in done.stdout


def test_the_real_index_leg_needs_a_version_and_runs_no_claude() -> None:
    for argv, said in (
        (["real-index"], "real-index needs --version"),
        (["real-index", "--version", "0.22.0", "--claude", "claude"], "runs no Claude Code step"),
    ):
        done = subprocess.run(  # noqa: S603 - this repository's own script
            [sys.executable, str(DRIVER), *argv],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert done.returncode == 2
        assert said in done.stderr


@pytest.mark.parametrize("leg", ["uv-absent", "uv-present", "e2e"])
def test_the_ordinary_legs_take_no_version(leg: str) -> None:
    done = subprocess.run(  # noqa: S603 - this repository's own script
        [sys.executable, str(DRIVER), leg, "--no-claude", "--version", "0.22.0"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 2
    assert "--version belongs to the real-index leg only" in done.stderr


def test_the_ordinary_legs_still_hold_their_tools_count(driver: ModuleType) -> None:
    """The uv-present leg's real-server check still pins 15 tools by default."""
    assert inspect.signature(driver.check_real_server).parameters["count"].default == 15


def test_a_launcher_at_another_version_stops_the_leg_before_anything_runs(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_command(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"a command ran: {args!r}")

    monkeypatch.setattr(driver, "run", no_command)
    brings = driver.launcher_version_line(driver.LAUNCHER_FILE)
    other = "999.0.0"
    opts = driver.argparse.Namespace(version=other)
    with pytest.raises(driver.CheckFailed) as failure:
        driver.leg_real_index(opts, tmp_path, driver.Results("real-index"))
    message = str(failure.value)
    assert f"the launcher in this tree brings s0ma {brings}" in message
    assert f"the version given is {other}" in message
    assert "a plugin installs the version it brings" in message
    assert driver.check_launcher_is_at(brings) == brings


def test_doctor_versions_are_read(driver: ModuleType) -> None:
    output = (
        "s0ma doctor\n\nversions\n  python           3.13.1\n"
        "  s0ma-lang-core   0.22.0\n  s0ma-lang-dsl    0.22.0\n"
        "  s0ma-lang-mcp    0.22.0\n  s0ma-lang-studi0 0.22.0\n  mcp SDK          1.30.0\n"
    )
    assert "s0ma-lang-studi0 0.22.0" in driver.check_doctor_versions(output, "0.22.0")
    with pytest.raises(driver.CheckFailed, match="not 0.23.0"):
        driver.check_doctor_versions(output, "0.23.0")
    with pytest.raises(driver.CheckFailed, match="not the four"):
        driver.check_doctor_versions(output.replace("  s0ma-lang-mcp    0.22.0\n", ""), "0.22.0")


#: A stand-in uv: it writes down what it was asked and with what environment,
#: runs ``uv run --script`` with this Python, makes a ``venv`` with a ``python``
#: in it, and answers ``pip install`` without installing anything.
FAKE_UV = """\
#!{python}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
watched = {watched}
with open(os.environ["FAKE_UV_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({{"args": args, "env": {{k: os.environ[k] for k in watched if k in os.environ}}}}) + "\\n")
if args[:1] == ["run"]:
    script = args[args.index("--script") + 1]
    rest = args[args.index("--script") + 2:]
    os.execv(sys.executable, [sys.executable, script, *rest])
if args[:1] == ["venv"]:
    target = Path(args[-1]) / "bin"
    target.mkdir(parents=True)
    (target / "python").symlink_to(sys.executable)
sys.exit(0)
"""


@pytest.mark.skipif(sys.platform.startswith("win"), reason="the stand-in uv is a POSIX script")
def test_no_find_links_no_offline_flag_and_no_key_reach_uv(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every way a run could steer uv off the index, or hand it a key, is set,
    and none of it reaches uv: it is asked for ``s0ma-lang==<version>`` alone."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    watched = sorted(
        {*driver.INDEX_STEERING, "S0MA_LICENSE_KEY", "S0MA_LAUNCH_OFFLINE_INSTALL", "UV_NO_CONFIG"}
    )
    fake = bin_dir / "uv"
    fake.write_text(FAKE_UV.format(python=sys.executable, watched=watched), encoding="utf-8")
    fake.chmod(0o755)
    log = tmp_path / "uv.log"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.setenv("FAKE_UV_LOG", str(log))
    for name in driver.INDEX_STEERING:
        monkeypatch.setenv(name, "/somewhere/local" if "LINKS" in name or "URL" in name else "1")
    monkeypatch.setenv("S0MA_LICENSE_KEY", "s0ma_test_key_never_sent")
    monkeypatch.setenv("S0MA_LAUNCH_OFFLINE_INSTALL", "1")

    home = tmp_path / "s0ma-home"
    env = driver.real_index_env(home, "127.0.0.1:9", tmp_path / "uv-cache")
    version = driver.launcher_version_line(driver.LAUNCHER_FILE)
    verdict = driver.install_from_real_index(driver.PLUGIN_DIR, version, env, tmp_path)
    assert f"s0ma {version} is installed" in verdict

    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls[0]["args"][:3] == ["run", "--frozen", "--script"]
    pip = [call for call in calls if call["args"][:2] == ["pip", "install"]]
    assert len(pip) == 1
    asked = pip[0]["args"]
    assert f"s0ma-lang=={version}" in asked
    for flag in ("--offline", "--find-links", "-f", "--no-index", "--index-url", "--extra-index-url"):
        assert flag not in asked
    for call in calls:
        assert "--offline" not in call["args"]
        assert call["env"] == {"UV_NO_CONFIG": "1"}


def test_the_install_refuses_an_environment_that_steers_uv(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_command(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"a command ran: {args!r}")

    monkeypatch.setattr(driver, "run", no_command)
    for name in ("UV_FIND_LINKS", "UV_OFFLINE", "S0MA_LICENSE_KEY"):
        with pytest.raises(driver.CheckFailed, match=name):
            driver.install_from_real_index(driver.PLUGIN_DIR, "0.22.0", {name: "x"}, tmp_path)


# ---------------------------------------------------------------------------
# The real-index leg waits for a version the index does not show yet.
# ---------------------------------------------------------------------------


class Clock:
    """A clock that moves only when the leg sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.pauses: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.pauses.append(seconds)
        self.now += seconds


def answers(driver: ModuleType, *outcomes: tuple[int, str]) -> tuple[list[object], object]:
    """A stand-in for ``run`` that gives *outcomes* in turn, then the last again."""
    calls: list[object] = []

    def fake_run(command: object, env: object, cwd: object, **kwargs: object) -> object:
        calls.append(command)
        code, stderr = outcomes[min(len(calls), len(outcomes)) - 1]
        return driver.Ran(code, "", stderr)

    return calls, fake_run


MISSING = "  Because there is no version of s0ma-lang==0.23.1 and you require s0ma-lang==0.23.1, ..."


def test_a_version_the_index_does_not_show_yet_is_asked_for_again(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = Clock()
    calls, fake_run = answers(
        driver, (3, MISSING), (3, MISSING), (0, "s0ma 0.23.1 is installed.")
    )
    monkeypatch.setattr(driver, "run", fake_run)
    verdict = driver.install_from_real_index(
        driver.PLUGIN_DIR, "0.23.1", {}, tmp_path, sleep=clock.sleep, clock=clock
    )
    assert len(calls) == 3
    assert clock.pauses == [driver.INDEX_RETRY_SECONDS] * 2
    assert "after 2 waits for the index" in verdict
    printed = capsys.readouterr().out
    assert "WAIT 1: the index does not show s0ma-lang==0.23.1 yet" in printed
    assert "WAIT 2:" in printed


def test_the_wait_for_the_index_ends_after_five_minutes(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    calls, fake_run = answers(driver, (3, MISSING))
    monkeypatch.setattr(driver, "run", fake_run)
    with pytest.raises(driver.CheckFailed, match="exited 3"):
        driver.install_from_real_index(
            driver.PLUGIN_DIR, "0.23.1", {}, tmp_path, sleep=clock.sleep, clock=clock
        )
    assert driver.INDEX_WAIT_SECONDS == 300.0
    assert sum(clock.pauses) == driver.INDEX_WAIT_SECONDS
    assert len(calls) == len(clock.pauses) + 1


def test_any_other_failure_of_the_index_install_is_not_retried(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    for said in ("  Failed to download s0ma-lang", MISSING.replace("0.23.1", "0.23.0")):
        calls, fake_run = answers(driver, (3, said))
        monkeypatch.setattr(driver, "run", fake_run)
        with pytest.raises(driver.CheckFailed, match="exited 3"):
            driver.install_from_real_index(
                driver.PLUGIN_DIR, "0.23.1", {}, tmp_path, sleep=clock.sleep, clock=clock
            )
        assert len(calls) == 1
    assert clock.pauses == []


# ---------------------------------------------------------------------------
# The python-download leg: uv chooses, and the plugin says where it keeps it.
# ---------------------------------------------------------------------------


def test_the_python_download_leg_runs_no_claude_and_takes_no_version() -> None:
    for argv, said in (
        (["python-download", "--claude", "claude", "--claude-version", "1"], "runs no Claude Code step"),
        (["python-download", "--version", "0.22.0"], "--version belongs to the real-index leg only"),
    ):
        done = subprocess.run(  # noqa: S603 - this repository's own script
            [sys.executable, str(DRIVER), *argv],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert done.returncode == 2
        assert said in done.stderr


def test_the_supported_range_is_read_as_minor_versions(driver: ModuleType) -> None:
    assert driver.supported_minors(">=3.11,<3.14") == {11, 12, 13}
    with pytest.raises(driver.CheckFailed, match="not >=3.A,<3.B"):
        driver.supported_minors(">=3.11")


def test_nothing_that_names_a_python_reaches_the_plugin(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in driver.PYTHON_STEERING:
        monkeypatch.setenv(name, "3.15")
    env = driver.python_download_env(tmp_path / "s0ma home", "127.0.0.1:9")
    for name in driver.PYTHON_STEERING:
        if name != "UV_PYTHON_PREFERENCE":
            assert name not in env, name
    assert env["UV_PYTHON_PREFERENCE"] == "only-managed"
    assert env["UV_NO_CONFIG"] == "1"
    assert env["S0MA_HOME"] == str(tmp_path / "s0ma home")


#: A stand-in uv that writes down the environment it was given, then runs
#: ``uv run --script`` with this Python and answers ``python dir`` with a path.
FAKE_UV_PYTHON = """\
#!{python}
import json, os, sys
args = sys.argv[1:]
watched = {watched}
with open(os.environ["FAKE_UV_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({{"args": args, "env": {{k: os.environ[k] for k in watched if k in os.environ}}}}) + "\\n")
if args[:2] == ["python", "dir"]:
    print(os.environ.get("UV_PYTHON_INSTALL_DIR", "/default/uv/python"))
    sys.exit(0)
if args[:1] == ["run"]:
    script = args[args.index("--script") + 1]
    rest = args[args.index("--script") + 2:]
    os.execv(sys.executable, [sys.executable, script, *rest])
sys.exit(0)
"""


def fake_uv_python(tmp_path: Path, driver: ModuleType, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    fake = bin_dir / "uv"
    watched = sorted({*driver.PYTHON_STEERING, "UV_NO_CONFIG"})
    fake.write_text(FAKE_UV_PYTHON.format(python=sys.executable, watched=watched), encoding="utf-8")
    fake.chmod(0o755)
    log = tmp_path / "uv.log"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.setenv("FAKE_UV_LOG", str(log))
    return log


@pytest.mark.skipif(sys.platform.startswith("win"), reason="the stand-in uv is a POSIX script")
def test_the_plugins_command_hands_uv_only_its_own_python_folder(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner's Python settings are cleared; the plugin names the folder itself."""
    log = fake_uv_python(tmp_path, driver, monkeypatch)
    monkeypatch.setenv("UV_PYTHON", "3.13")
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", str(tmp_path / "runner-pythons"))
    home = tmp_path / "s0ma home"
    env = driver.python_download_env(home, "127.0.0.1:9")
    ran = driver.run(driver.launch_command(driver.PLUGIN_DIR, "status"), env, tmp_path)
    assert ran.code == 0, ran.stderr
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls[0]["args"][:3] == ["run", "--frozen", "--script"]
    assert calls[0]["env"] == {
        "UV_NO_CONFIG": "1",
        "UV_PYTHON_INSTALL_DIR": str(home / "python"),
        "UV_PYTHON_PREFERENCE": "only-managed",
    }


@pytest.mark.skipif(sys.platform.startswith("win"), reason="the stand-in uv is a POSIX script")
def test_uvs_default_folder_and_the_runners_are_both_watched(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = fake_uv_python(tmp_path, driver, monkeypatch)
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", str(tmp_path / "runner-pythons"))
    folders = driver.default_python_dirs("uv", tmp_path)
    assert folders == [Path("/default/uv/python"), tmp_path / "runner-pythons"]
    asked = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert asked["args"] == ["python", "dir"]
    assert "UV_PYTHON_INSTALL_DIR" not in asked["env"]
    monkeypatch.delenv("UV_PYTHON_INSTALL_DIR")
    assert driver.default_python_dirs("uv", tmp_path) == [Path("/default/uv/python")]


def test_a_folders_entries_are_listed_by_name_only(driver: ModuleType, tmp_path: Path) -> None:
    assert driver.entry_names(tmp_path / "missing") == []
    (tmp_path / "b").mkdir()
    (tmp_path / "a").write_text("x", encoding="utf-8")
    assert driver.entry_names(tmp_path) == ["a", "b"]
    assert driver.is_under(tmp_path / "b", tmp_path)
    assert not driver.is_under(tmp_path, tmp_path / "b")
