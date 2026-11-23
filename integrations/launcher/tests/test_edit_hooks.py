"""``before-edit`` and ``after-edit``: the launcher's answers to the plugin's edit hooks.

The path logic is tested here on both platforms' path rules, whatever machine
runs it: which file an edit is for, whether it lies under a project's build
folder, and what that build folder is. Then the two answers, with a stand-in
for the one process ``after-edit`` may start, so nothing here runs s0ma itself.
``integrations/claude/tests/test_plugin_edit_hooks.py`` runs the hook commands for
real.

Two things are proven by making them impossible: neither command opens a
socket, and ``after-edit`` never installs, updates or starts an update.
"""

from __future__ import annotations

import io
import json
import socket
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import ModuleType
from typing import Any

import pytest

S0MA_TABLE = '[tool.s0ma]\nsource_roots = ["src"]\n'


def make_project(
    root: Path, *, name: str | None = "demo", table: str = 'build_dir = "build"\n'
) -> Path:
    """A folder with a ``pyproject.toml`` that makes it a s0ma project."""
    root.mkdir(parents=True, exist_ok=True)
    project = f'[project]\nname = "{name}"\n' if name is not None else ""
    (root / "pyproject.toml").write_text(project + S0MA_TABLE + table, encoding="utf-8")
    return root


def edit(path: Path | str, cwd: Path | str | None = None) -> dict[str, Any]:
    """What Claude Code hands an edit hook, less the fields nothing here reads."""
    payload: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": str(path), "content": "x = 1\n"},
    }
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return payload


def turn_off(folder: Path) -> None:
    (folder / ".s0ma").mkdir(parents=True, exist_ok=True)
    (folder / ".s0ma" / "preferences.json").write_text('{"s0ma": "off"}', encoding="utf-8")


class FakeRun:
    """Stands in for :func:`subprocess.run` and records what it was asked."""

    def __init__(self, code: int = 0, stdout: str = "", *, raises: BaseException | None = None) -> None:
        self.code = code
        self.stdout = stdout
        self.raises = raises
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> Any:
        self.calls.append((list(argv), kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.code, self.stdout.encode("utf-8"), b"")


FINDING = (
    "src/a.s0ma:3: ERROR [PARSE_ERROR]\n"
    "  Invalid kind: 'FUNKTION'\n"
    "  Remediation: Valid kinds are: FUNCTION\n"
    "\n"
    "Results: 1 error(s), 0 warning(s) [mode: dev]\n"
)


# ---------------------------------------------------------------------------
# Which file, and is it inside a folder.
# ---------------------------------------------------------------------------


def test_an_absolute_path_is_taken_as_it_is(launcher: ModuleType) -> None:
    assert launcher.edit_target(edit("/p/build/a.py"), windows=False) == PurePosixPath(
        "/p/build/a.py"
    )


def test_a_relative_path_is_read_against_the_hooks_cwd(launcher: ModuleType) -> None:
    found = launcher.edit_target(edit("build/a.py", cwd="/p"), Path("/elsewhere"), windows=False)
    assert found == PurePosixPath("/p/build/a.py")


def test_with_no_cwd_the_project_folder_is_the_base(launcher: ModuleType) -> None:
    found = launcher.edit_target(edit("build/a.py"), PurePosixPath("/proj"), windows=False)
    assert found == PurePosixPath("/proj/build/a.py")


@pytest.mark.parametrize(
    ("raw", "cwd", "expected"),
    [
        (r"C:\Users\me\proj\build\a.py", None, r"C:\Users\me\proj\build\a.py"),
        ("C:/Users/me/proj/build/a.py", None, r"C:\Users\me\proj\build\a.py"),
        (r"build\a.py", r"C:\Users\me\proj", r"C:\Users\me\proj\build\a.py"),
        (r"\\server\share\proj\build\a.py", None, r"\\server\share\proj\build\a.py"),
    ],
    ids=["backslashes", "forward slashes", "relative", "network share"],
)
def test_windows_form_paths_are_read_as_windows_reads_them(
    launcher: ModuleType, raw: str, cwd: str | None, expected: str
) -> None:
    found = launcher.edit_target(edit(raw, cwd=cwd), windows=True)
    assert found == PureWindowsPath(expected)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"tool_input": "not an object"},
        {"tool_input": {}},
        {"tool_input": {"file_path": ""}},
        {"tool_input": {"file_path": 7}},
        {"tool_input": {"file_path": "a\x00b"}},
        {"tool_input": {"file_path": "relative.py"}, "cwd": "also/relative"},
    ],
    ids=["empty", "input not an object", "no path", "blank path", "not text", "nul", "no base"],
)
def test_no_usable_path_is_no_target(launcher: ModuleType, payload: dict[str, Any]) -> None:
    assert launcher.edit_target(payload, None, windows=False) is None


def test_inside_means_below_and_not_the_folder_itself(launcher: ModuleType) -> None:
    build = PurePosixPath("/p/build")
    assert launcher.is_inside(PurePosixPath("/p/build/a.py"), build, fold=False)
    assert launcher.is_inside(PurePosixPath("/p/build/sub/a.py"), build, fold=False)
    assert not launcher.is_inside(build, build, fold=False)
    assert not launcher.is_inside(PurePosixPath("/p/builder/a.py"), build, fold=False)
    assert not launcher.is_inside(PurePosixPath("/p/src/a.py"), build, fold=False)


def test_case_counts_only_where_the_platform_folds_it(launcher: ModuleType) -> None:
    child = PureWindowsPath(r"C:\Proj\BUILD\a.py")
    build = PureWindowsPath("c:/proj/build")
    assert launcher.is_inside(child, build, fold=True)
    assert not launcher.is_inside(PurePosixPath("/p/BUILD/a.py"), PurePosixPath("/p/build"), fold=False)


@pytest.mark.parametrize(
    ("platform", "folds"),
    [("win32", True), ("cygwin", True), ("darwin", True), ("linux", False)],
)
def test_which_platforms_fold_case(launcher: ModuleType, platform: str, folds: bool) -> None:
    assert launcher.folds_case(platform) is folds


# ---------------------------------------------------------------------------
# The build folder.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [("demo", "demo_build"), ("my-app", "my_app_build"), ("a.b c", "a_b_c_build"), ("2fast", None)],
)
def test_the_default_build_folder(launcher: ModuleType, name: str, expected: str | None) -> None:
    assert launcher.default_build_dir(name) == expected


def test_the_build_folder_is_read_from_the_project(launcher: ModuleType, tmp_path: Path) -> None:
    root = make_project(tmp_path / "p", table='build_dir = "out/gen"\n')
    assert launcher.build_dir_of(root) == (root / "out" / "gen").resolve()


def test_with_no_build_dir_the_default_follows_the_projects_name(
    launcher: ModuleType, tmp_path: Path
) -> None:
    root = make_project(tmp_path / "p", name="my-app", table="")
    assert launcher.build_dir_of(root) == (root / "my_app_build").resolve()


def test_with_no_project_name_the_folder_names_it(launcher: ModuleType, tmp_path: Path) -> None:
    root = make_project(tmp_path / "shop", name=None, table="")
    assert launcher.build_dir_of(root) == (root / "shop_build").resolve()


@pytest.mark.parametrize(
    "table",
    ['build_dir = "."\n', 'build_dir = ".."\n', 'build_dir = "../sibling"\n', "build_dir = 3\n", 'build_dir = ""\n'],
    ids=["the project itself", "its parent", "outside", "not text", "blank"],
)
def test_a_build_folder_that_is_not_inside_the_project_is_none(
    launcher: ModuleType, tmp_path: Path, table: str
) -> None:
    root = make_project(tmp_path / "p", table=table)
    assert launcher.build_dir_of(root) is None


def test_a_name_with_no_default_is_none(launcher: ModuleType, tmp_path: Path) -> None:
    root = make_project(tmp_path / "p", name="2fast", table="")
    assert launcher.build_dir_of(root) is None


# ---------------------------------------------------------------------------
# before-edit.
# ---------------------------------------------------------------------------


def reason_of(answer: dict[str, Any] | None) -> str:
    assert answer is not None
    output = answer["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert output["permissionDecision"] == "deny"
    reason = output["permissionDecisionReason"]
    assert isinstance(reason, str) and reason.isascii()
    return reason


def test_an_edit_under_the_build_folder_is_refused(launcher: ModuleType, tmp_path: Path) -> None:
    root = make_project(tmp_path / "p")
    (root / "build").mkdir()
    reason = reason_of(launcher.before_edit_answer(edit(root / "build" / "a.py")))
    assert reason == launcher.BUILD_DIR_REFUSAL.format(build_dir="build")
    assert "under build/ in this project" in reason
    assert "Make the change in the .s0ma source instead, then run `s0ma build`." in reason


def test_a_file_that_does_not_exist_yet_is_covered(launcher: ModuleType, tmp_path: Path) -> None:
    root = make_project(tmp_path / "p")
    reason_of(launcher.before_edit_answer(edit(root / "build" / "new" / "deeper" / "a.py")))


def test_a_custom_build_folder_is_the_one_refused(launcher: ModuleType, tmp_path: Path) -> None:
    root = make_project(tmp_path / "p", table='build_dir = "out/gen"\n')
    reason = reason_of(launcher.before_edit_answer(edit(root / "out" / "gen" / "a.py")))
    assert "under out/gen/ in this project" in reason
    assert launcher.before_edit_answer(edit(root / "build" / "a.py")) is None
    assert launcher.before_edit_answer(edit(root / "out" / "a.py")) is None


def test_a_relative_path_is_refused_from_the_hooks_cwd(launcher: ModuleType, tmp_path: Path) -> None:
    root = make_project(tmp_path / "p")
    reason_of(launcher.before_edit_answer(edit("build/a.py", cwd=root)))


def test_a_path_through_dot_dot_is_read_as_where_it_lands(
    launcher: ModuleType, tmp_path: Path
) -> None:
    root = make_project(tmp_path / "p")
    (root / "src").mkdir()
    reason_of(launcher.before_edit_answer(edit(root / "src" / ".." / "build" / "a.py")))
    assert launcher.before_edit_answer(edit(root / "build" / ".." / "src" / "a.py")) is None


def test_a_differently_cased_path_is_refused_where_case_folds(
    launcher: ModuleType, tmp_path: Path
) -> None:
    root = make_project(tmp_path / "p")
    (root / "build").mkdir()
    answer = launcher.before_edit_answer(edit(root / "BUILD" / "a.py"))
    if launcher.folds_case():
        reason_of(answer)
    else:
        assert answer is None


@pytest.mark.parametrize("where", ["src/a.py", "a.py", "build.py", "builder/a.py"])
def test_an_edit_elsewhere_in_the_project_is_let_through(
    launcher: ModuleType, tmp_path: Path, where: str
) -> None:
    root = make_project(tmp_path / "p")
    assert launcher.before_edit_answer(edit(root / where)) is None


def test_outside_a_s0ma_project_nothing_is_said(launcher: ModuleType, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "pyproject.toml").write_text('[project]\nname = "plain"\n', encoding="utf-8")
    assert launcher.before_edit_answer(edit(plain / "build" / "a.py")) is None
    assert launcher.before_edit_answer(edit(tmp_path / "nothing" / "build" / "a.py")) is None


def test_off_in_the_project_nothing_is_said(launcher: ModuleType, tmp_path: Path) -> None:
    root = make_project(tmp_path / "p")
    turn_off(root)
    assert launcher.before_edit_answer(edit(root / "build" / "a.py")) is None


def test_off_where_the_session_started_nothing_is_said(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = tmp_path / "work"
    root = make_project(session / "app")
    turn_off(session)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(session))
    assert launcher.before_edit_answer(edit(root / "build" / "a.py")) is None


# ---------------------------------------------------------------------------
# after-edit.
# ---------------------------------------------------------------------------


@pytest.fixture
def checked_project(tmp_path: Path, make_venv: Any) -> Path:
    """A s0ma project with its own copy of s0ma, and one source file."""
    root = make_project(tmp_path / "p")
    make_venv(root / ".venv")
    (root / "src").mkdir()
    (root / "src" / "a.s0ma").write_text("module a\n", encoding="utf-8")
    return root


def context_of(answer: dict[str, Any] | None) -> str:
    assert answer is not None
    output = answer["hookSpecificOutput"]
    assert output["hookEventName"] == "PostToolUse"
    context = output["additionalContext"]
    assert isinstance(context, str)
    return context


def test_a_finding_is_handed_to_claude(launcher: ModuleType, checked_project: Path) -> None:
    run = FakeRun(1, FINDING)
    answer = launcher.after_edit_answer(edit(checked_project / "src" / "a.s0ma"), runner=run)
    context = context_of(answer)
    lines = context.splitlines()
    assert lines[0] == "s0ma check ran on src/a.s0ma after this edit and reports:"
    assert lines[-1] == "Fix these in the .s0ma file before you go on."
    assert "[PARSE_ERROR]" in context
    argv, kwargs = run.calls[0]
    assert Path(argv[0]).parent == checked_project / ".venv" / "bin"
    assert argv[1:] == ["check", str(Path("src") / "a.s0ma")]
    assert kwargs["cwd"] == str(checked_project)
    assert kwargs["timeout"] == launcher.EDIT_CHECK_TIMEOUT_SECONDS
    assert kwargs["stdin"] == subprocess.DEVNULL


def test_warnings_alone_are_handed_on_too(launcher: ModuleType, checked_project: Path) -> None:
    report = (
        "build/a.py:1: WARNING [GENERATED_FILE_DRIFT]\n  edited by hand\n\n"
        "Results: 0 error(s), 1 warning(s) [mode: dev]\n\n1 file(s) checked. No errors.\n"
    )
    answer = launcher.after_edit_answer(
        edit(checked_project / "src" / "a.s0ma"), runner=FakeRun(0, report)
    )
    assert "[GENERATED_FILE_DRIFT]" in context_of(answer)


@pytest.mark.parametrize(
    ("code", "stdout"),
    [
        (0, "1 file(s) checked. No errors.\n"),
        (0, ""),
        (2, "No .s0ma files found at: 'x'\n"),
        (3, "internal error\n"),
    ],
    ids=["clean", "silent", "usage error", "internal error"],
)
def test_a_clean_or_unfinished_check_says_nothing(
    launcher: ModuleType, checked_project: Path, code: int, stdout: str
) -> None:
    answer = launcher.after_edit_answer(
        edit(checked_project / "src" / "a.s0ma"), runner=FakeRun(code, stdout)
    )
    assert answer is None


@pytest.mark.parametrize(
    "failure",
    [subprocess.TimeoutExpired(["s0ma"], 20), OSError("gone"), ValueError("bad")],
    ids=["timeout", "cannot start", "bad argument"],
)
def test_a_check_that_fails_to_run_says_nothing(
    launcher: ModuleType, checked_project: Path, failure: BaseException
) -> None:
    answer = launcher.after_edit_answer(
        edit(checked_project / "src" / "a.s0ma"), runner=FakeRun(raises=failure)
    )
    assert answer is None


@pytest.mark.parametrize("name", ["a.py", "a.s0ma.bak", ".s0ma", "a.S0MA"])
def test_only_a_s0ma_file_is_checked(launcher: ModuleType, checked_project: Path, name: str) -> None:
    run = FakeRun(1, FINDING)
    assert launcher.after_edit_answer(edit(checked_project / "src" / name), runner=run) is None
    assert run.calls == []


def test_with_no_s0ma_installed_nothing_runs(launcher: ModuleType, tmp_path: Path) -> None:
    root = make_project(tmp_path / "p")
    run = FakeRun(1, FINDING)
    assert launcher.after_edit_answer(edit(root / "src" / "a.s0ma"), runner=run) is None
    assert run.calls == []


def test_a_pinned_version_is_the_one_that_checks(
    launcher: ModuleType, tmp_path: Path, make_toolchain: Any
) -> None:
    root = make_project(tmp_path / "p")
    (root / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")
    make_toolchain("0.18.0")
    make_toolchain("0.19.0")
    run = FakeRun(1, FINDING)
    context_of(launcher.after_edit_answer(edit(root / "src" / "a.s0ma"), runner=run))
    assert "0.18.0" in run.calls[0][0][0]


def test_a_pin_that_is_not_installed_runs_nothing(
    launcher: ModuleType, tmp_path: Path, make_toolchain: Any
) -> None:
    root = make_project(tmp_path / "p")
    (root / ".s0ma-version").write_text("0.17.0\n", encoding="utf-8")
    make_toolchain("0.19.0")
    run = FakeRun(1, FINDING)
    assert launcher.after_edit_answer(edit(root / "src" / "a.s0ma"), runner=run) is None
    assert run.calls == []


def test_off_in_the_project_nothing_runs(launcher: ModuleType, checked_project: Path) -> None:
    turn_off(checked_project)
    run = FakeRun(1, FINDING)
    assert launcher.after_edit_answer(edit(checked_project / "src" / "a.s0ma"), runner=run) is None
    assert run.calls == []


def test_outside_a_s0ma_project_nothing_runs(
    launcher: ModuleType, tmp_path: Path, make_toolchain: Any
) -> None:
    make_toolchain("0.19.0")
    run = FakeRun(1, FINDING)
    assert launcher.after_edit_answer(edit(tmp_path / "loose" / "a.s0ma"), runner=run) is None
    assert run.calls == []


def test_the_key_is_not_handed_to_the_check(
    launcher: ModuleType, checked_project: Path, monkeypatch: pytest.MonkeyPatch, fake_key: str
) -> None:
    monkeypatch.setenv("S0MA_LICENSE_KEY", fake_key)
    run = FakeRun(1, FINDING)
    launcher.after_edit_answer(edit(checked_project / "src" / "a.s0ma"), runner=run)
    env = run.calls[0][1]["env"]
    assert "S0MA_LICENSE_KEY" not in env
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_long_findings_are_cut_at_a_line_and_say_so(launcher: ModuleType) -> None:
    findings = "\n".join(f"src/a.s0ma:{n}: ERROR [PARSE_ERROR] line {n}" for n in range(400))
    context = launcher.edit_check_context("src/a.s0ma", findings)
    assert len(context) <= launcher.EDIT_CHECK_MAX_CHARS
    lines = context.splitlines()
    assert lines[0] == launcher.EDIT_CHECK_LEAD.format(path="src/a.s0ma")
    assert lines[-2] == "There is more than this. Run `s0ma check src/a.s0ma` to see all of it."
    assert lines[-1] == launcher.EDIT_CHECK_CLOSE
    kept = lines[1:-2]
    assert kept and all(line in findings.splitlines() for line in kept)


def test_short_findings_are_handed_on_whole(launcher: ModuleType) -> None:
    context = launcher.edit_check_context("src/a.s0ma", FINDING.strip())
    assert context.splitlines()[1:-1] == FINDING.strip().splitlines()


@pytest.mark.parametrize(
    ("code", "stdout", "found"),
    [
        (1, FINDING, True),
        (1, "something went wrong\n", True),
        (0, "Results: 0 error(s), 2 warning(s)\n", True),
        (0, "Results: 0 error(s), 0 warning(s)\n", False),
        (0, "1 file(s) checked. No errors.\n", False),
        (1, "\n\n", False),
        (4, FINDING, False),
    ],
)
def test_what_counts_as_a_finding(launcher: ModuleType, code: int, stdout: str, found: bool) -> None:
    assert (launcher.check_findings(code, stdout) is not None) is found


# ---------------------------------------------------------------------------
# The commands as a whole.
# ---------------------------------------------------------------------------


class Stdin:
    def __init__(self, data: bytes) -> None:
        self.buffer = io.BytesIO(data)


def run_command(
    launcher: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    data: bytes,
) -> tuple[int, str, str]:
    monkeypatch.setattr(launcher.sys, "stdin", Stdin(data))
    code = launcher.main([command])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_before_edit_prints_one_line_of_json(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_project(tmp_path / "p")
    data = json.dumps(edit(root / "build" / "a.py")).encode()
    code, out, err = run_command(launcher, monkeypatch, capsys, "before-edit", data)
    assert (code, err) == (0, "")
    assert out.endswith("\n") and out.count("\n") == 1 and out.isascii()
    reason_of(json.loads(out))


@pytest.mark.parametrize("command", ["before-edit", "after-edit"])
@pytest.mark.parametrize(
    "data",
    [b"", b"{", b"[]", b"null", b"\xff\xfe", b'{"tool_input": {"file_path": "\\ud800"}}'],
    ids=["empty", "cut short", "a list", "null", "not utf-8", "lone surrogate"],
)
def test_bad_input_is_silence_and_exit_0(
    launcher: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    data: bytes,
) -> None:
    assert run_command(launcher, monkeypatch, capsys, command, data) == (0, "", "")


def test_input_past_the_ceiling_is_not_read(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_project(tmp_path / "p")
    monkeypatch.setattr(launcher, "HOOK_INPUT_MAX_BYTES", 64)
    data = json.dumps(edit(root / "build" / "a.py")).encode()
    assert run_command(launcher, monkeypatch, capsys, "before-edit", data) == (0, "", "")


@pytest.mark.parametrize("command", ["before-edit", "after-edit"])
def test_an_exception_inside_is_silence_and_exit_0(
    launcher: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    def explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("anything at all")

    monkeypatch.setattr(launcher, "s0ma_project_root", explode)
    data = json.dumps(edit(tmp_path / "build" / "a.s0ma")).encode()
    assert run_command(launcher, monkeypatch, capsys, command, data) == (0, "", "")


@pytest.mark.parametrize("command", ["before-edit", "after-edit"])
def test_no_socket_is_opened_and_nothing_is_installed(
    launcher: ModuleType,
    checked_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    """Made impossible, so a command that tried would lose the answer it owes."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"{command} must not do this")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    for name in ("install_version", "install_from_index", "perform_update", "maybe_start_background_update", "spawn_background_update"):
        monkeypatch.setattr(launcher, name, refuse)
    run = FakeRun(1, FINDING)
    monkeypatch.setattr(launcher.subprocess, "run", run)
    target = "build/a.py" if command == "before-edit" else "src/a.s0ma"
    data = json.dumps(edit(checked_project / target)).encode()
    code, out, err = run_command(launcher, monkeypatch, capsys, command, data)
    assert (code, err) == (0, "")
    assert json.loads(out)["hookSpecificOutput"]["hookEventName"] in ("PreToolUse", "PostToolUse")
    assert len(run.calls) == (1 if command == "after-edit" else 0)
