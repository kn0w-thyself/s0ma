"""M3A whole-project grammar migration safety contracts."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.cli import migrate_grammar
from s0ma_dsl.cli.main import EXIT_SUCCESS, EXIT_VALIDATION_ERROR, S0maCLI
from s0ma_dsl.cli.migrate_grammar import (
    GrammarMigrationError,
    apply_grammar_migration,
    plan_grammar_migration,
)
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.parser import parse_s0ma

if TYPE_CHECKING:
    from collections.abc import Iterator


def _legacy(name: str) -> str:
    return f'''\
module {name}
    layer: DOMAIN
    version: 1.0.0
    intent: "Owns {name}."
    exports: []

cell VALUE :: DOMAIN
    kind: CONSTANT
    visibility: INTERNAL
    intent: "Stores a value."
    schema: "int"
    ---
    VALUE = 1
'''


def test_dry_run_is_deterministic_and_does_not_write(tmp_path: Path) -> None:
    source = tmp_path / "src" / "a.s0ma"
    source.parent.mkdir()
    source.write_text(_legacy("a"), encoding="utf-8")
    before = source.read_bytes()
    first = plan_grammar_migration(tmp_path)
    second = plan_grammar_migration(tmp_path)
    assert first.manifest(applied=False) == second.manifest(applied=False)
    assert first.manifest(applied=False)["changes"][0]["path"] == "src/a.s0ma"
    assert source.read_bytes() == before


def test_apply_is_atomic_and_rerun_is_noop(tmp_path: Path) -> None:
    source = tmp_path / "a.s0ma"
    source.write_text(_legacy("a"), encoding="utf-8")
    plan = plan_grammar_migration(tmp_path)
    apply_grammar_migration(plan)
    migrated = source.read_text(encoding="utf-8")
    assert "    requires: none\n" in migrated
    assert "    invariants: none\n" in migrated
    assert plan_grammar_migration(tmp_path).changes == ()


def test_legacy_omission_reader_is_migrator_only(tmp_path: Path) -> None:
    source = tmp_path / "legacy.s0ma"
    source.write_text(_legacy("legacy"), encoding="utf-8")
    with pytest.raises(S0maParseError) as excinfo:
        parse_s0ma(source.read_text(encoding="utf-8"), filename=str(source))
    assert excinfo.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
    plan = plan_grammar_migration(tmp_path)
    assert len(plan.changes) == 1
    apply_grammar_migration(plan)
    parse_s0ma(source.read_text(encoding="utf-8"), filename=str(source))


def test_apply_refuses_a_changed_source_before_any_write(tmp_path: Path) -> None:
    source = tmp_path / "a.s0ma"
    source.write_text(_legacy("a"), encoding="utf-8")
    plan = plan_grammar_migration(tmp_path)
    changed = _legacy("a") + "# concurrent edit\n"
    source.write_text(changed, encoding="utf-8")
    with pytest.raises(GrammarMigrationError, match="GRAMMAR_MIGRATION_CONFLICT"):
        apply_grammar_migration(plan)
    assert source.read_text(encoding="utf-8") == changed


def test_mid_apply_failure_rolls_back_every_replaced_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = [tmp_path / "a.s0ma", tmp_path / "b.s0ma"]
    for path in paths:
        path.write_text(_legacy(path.stem), encoding="utf-8")
    originals = {path: path.read_bytes() for path in paths}
    plan = plan_grammar_migration(tmp_path)
    real_replace = os.replace
    apply_count = 0
    failed = False

    def fail_second_apply(source: str | Path, target: str | Path) -> None:
        nonlocal apply_count, failed
        target_path = Path(target)
        if target_path.suffix == ".s0ma" and not failed:
            apply_count += 1
            if apply_count == 2:
                failed = True
                raise OSError("simulated replace failure")
        real_replace(source, target)

    monkeypatch.setattr(migrate_grammar.os, "replace", fail_second_apply)
    with pytest.raises(GrammarMigrationError, match="every replaced file was restored"):
        apply_grammar_migration(plan)
    assert {path: path.read_bytes() for path in paths} == originals


def test_parse_failure_is_one_named_migration_error(tmp_path: Path) -> None:
    (tmp_path / "broken.s0ma").write_text("not a declaration\n", encoding="utf-8")
    with pytest.raises(GrammarMigrationError, match="GRAMMAR_MIGRATION_PARSE_ERROR"):
        plan_grammar_migration(tmp_path)


def test_nested_invalid_directory_is_discovered_and_fails_preflight(
    tmp_path: Path,
) -> None:
    """A user directory named ``invalid`` is authored source, not a prune hint."""

    source = tmp_path / "src" / "invalid" / "broken.s0ma"
    source.parent.mkdir(parents=True)
    source.write_text("not a declaration\n", encoding="utf-8")

    with pytest.raises(GrammarMigrationError) as excinfo:
        plan_grammar_migration(tmp_path)

    assert excinfo.value.code == "GRAMMAR_MIGRATION_PARSE_ERROR"
    assert "src/invalid/broken.s0ma" in str(excinfo.value)


# ---------------------------------------------------------------------------
# ``forbids:`` on a nerve and a ganglion
# ---------------------------------------------------------------------------

_FORBIDS = "    forbids: none\n"
_PARTS = '''\
module parts
    layer: DOMAIN
    version: 1.0.0
    intent: "Settles accounts and watches the settlements."
    exports: [settle]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve settle :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Settles one account."
    expects: "An account number."
    guarantees: "Returns the settled balance."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def settle(account):
        return 0

ganglion watch_settle :: DOMAIN
    visibility: INTERNAL
    scope: SUBSYSTEM
    intent: "Watches settlements for drift."
    observes: [settle]
    on_anomaly: "Logs the drift and carries on."
    forbids: none
    priors: none
    depends_on: none
    covered_by: none
    ---
    def watch_settle(signal):
        return signal
'''
_WITHOUT_FORBIDS = _PARTS.replace(_FORBIDS, "")


def _drop_forbids(source: str) -> str:
    return "".join(
        line for line in source.splitlines(keepends=True)
        if not line.lstrip().startswith("forbids:")
    )


def _migrate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    assert S0maCLI().run(["migrate", "grammar", "--apply", str(tmp_path)]) == EXIT_SUCCESS
    manifest: dict[str, Any] = json.loads(capsys.readouterr().out)
    return manifest


def test_forbids_is_written_above_the_separator_on_a_nerve_and_a_ganglion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "parts.s0ma"
    source.write_text(_WITHOUT_FORBIDS, encoding="utf-8")
    with pytest.raises(S0maParseError, match="SEMANTIC_REQUIRED_STATE_OMITTED"):
        parse_s0ma(_WITHOUT_FORBIDS, filename="parts.s0ma")
    manifest = _migrate(tmp_path, capsys)
    assert manifest["applied"] is True
    assert [change["inserted_fields"] for change in manifest["changes"]] == [
        ["nerve:settle.forbids", "ganglion:watch_settle.forbids"],
    ]
    migrated = source.read_text(encoding="utf-8")
    assert migrated == _WITHOUT_FORBIDS.replace("    ---\n", _FORBIDS + "    ---\n")
    parse_s0ma(migrated, filename="parts.s0ma")


def test_a_second_forbids_migration_does_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "parts.s0ma"
    source.write_text(_WITHOUT_FORBIDS, encoding="utf-8")
    assert _migrate(tmp_path, capsys)["change_count"] == 1
    migrated = source.read_bytes()
    second = _migrate(tmp_path, capsys)
    assert (second["change_count"], second["changes"]) == (0, [])
    assert source.read_bytes() == migrated


def test_a_skeleton_without_the_line_comes_out_with_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli_main = importlib.import_module("s0ma_dsl.cli.main")
    skeleton_of = cli_main._legacy_scaffold_template

    def without_forbids(*args: Any) -> str:
        return _drop_forbids(skeleton_of(*args))

    monkeypatch.setattr(cli_main, "_legacy_scaffold_template", without_forbids)
    skeleton = cli_main._scaffold_template("nerve", "settle", "DOMAIN", "FUNCTION")
    lines = skeleton.splitlines()
    assert [line for line in lines if "forbids:" in line] == ["    forbids: none"]
    assert lines.index("    forbids: none") < lines.index("    ---")
    parse_s0ma(skeleton, filename="settle.s0ma")


def test_a_template_without_the_line_comes_out_with_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    new_project = importlib.import_module("s0ma_dsl.cli.new_project")
    template_of = new_project._starter_module_source
    authored: list[str] = []

    def without_forbids(*args: Any) -> str:
        authored.append(_drop_forbids(template_of(*args)))
        return authored[-1]

    monkeypatch.setattr(new_project, "_starter_module_source", without_forbids)
    module_path, _test_path = new_project.scaffold_feature_layout(
        tmp_path, "settling", "settle_desk", "DOMAIN", "settle", "FUNCTION",
    )
    written = module_path.read_text(encoding="utf-8")
    lines = written.splitlines()
    assert [line for line in lines if "forbids:" in line] == ["    forbids: none"]
    [template] = authored
    assert "forbids:" not in template
    assert lines.index("    forbids: none") < lines.index("    ---")
    parse_s0ma(written, filename=module_path.name)


# ---------------------------------------------------------------------------
# Which directories are walked, and how paths are reported
# ---------------------------------------------------------------------------

_PROJECT_PYPROJECT = '''\
[project]
name = "walked"
version = "0.0.1"

[tool.s0ma]
source_roots = ["src"]
test_roots = ["tests"]
'''


def _legacy_embed(name: str, embed: str) -> str:
    return f'''\
module {name}
    layer: PRESENTATION
    version: 1.0.0
    intent: "Owns {name}."
    exports: [PAGE]

cell PAGE :: PRESENTATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Holds a page read from a file beside this module."
    schema: "string of HTML"
    content: @file("{embed}")
'''


def _write_project(root: Path) -> Path:
    (root / "pyproject.toml").write_text(_PROJECT_PYPROJECT, encoding="utf-8")
    module = root / "src" / "site" / "page.s0ma"
    module.parent.mkdir(parents=True)
    module.write_text(_legacy_embed("page", "page.html"), encoding="utf-8")
    (module.parent / "page.html").write_text("<p>hi</p>\n", encoding="utf-8")
    return module


def _run_cli(
    argv: list[str], capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    code = S0maCLI().run(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _migration_warnings(err: str) -> list[str]:
    """The lines on stderr that the migration itself wrote."""

    return [
        line for line in err.splitlines()
        if line.startswith("warning: s0ma migrate grammar:")
    ]


def _manifest(out: str) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads(out)
    assert manifest["schema"] == "s0ma-grammar-migration@1"
    return manifest


def test_project_root_run_resolves_embeds_against_root_relative_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    code, out, err = _run_cli(["migrate", "grammar", "."], capsys)
    assert "EMBEDDED_FILE_NOT_FOUND" not in out + err
    assert code == EXIT_SUCCESS
    manifest = _manifest(out)
    assert [change["path"] for change in manifest["changes"]] == [
        "src/site/page.s0ma",
    ]


def _hashes(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (change["before_sha256"], change["after_sha256"])
        for change in manifest["changes"]
    ]


def _plan_from_the_root(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, Any]:
    monkeypatch.chdir(project)
    code, out, err = _run_cli(["migrate", "grammar", "."], capsys)
    assert (code, err) == (EXIT_SUCCESS, "")
    return _manifest(out)


# (working directory, argv after `s0ma`, the manifest path), with the
# working directory relative to the folder that holds the project `proj`.
_EMBED_RUNS = [
    pytest.param("proj", ["migrate", "grammar", "src"], "site/page.s0ma",
                 id="subdirectory-target"),
    pytest.param("proj", ["migrate", "grammar", "src/site"], "page.s0ma",
                 id="nested-target"),
    pytest.param("proj/src", ["migrate", "grammar", ".."], "src/site/page.s0ma",
                 id="parent-from-inside"),
    pytest.param(".", ["migrate", "grammar", "proj"], "src/site/page.s0ma",
                 id="project-from-its-parent"),
    pytest.param(".", ["--project-root", "proj", "migrate", "grammar"],
                 "src/site/page.s0ma", id="project-root-no-target"),
    pytest.param(".", ["--project-root", "proj", "migrate", "grammar", "proj"],
                 "src/site/page.s0ma", id="project-root-and-target"),
    pytest.param("elsewhere", ["migrate", "grammar", "<abs>"], "src/site/page.s0ma",
                 id="absolute-target-from-elsewhere"),
    pytest.param("proj/src/site", ["migrate", "grammar"], "src/site/page.s0ma",
                 id="bare-run-in-a-source-directory"),
]


@pytest.mark.parametrize(("cwd", "argv", "path"), _EMBED_RUNS)
def test_embeds_resolve_whatever_the_working_directory_and_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cwd: str,
    argv: list[str],
    path: str,
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_project(project)
    (tmp_path / "elsewhere").mkdir()
    expected = _hashes(_plan_from_the_root(project, monkeypatch, capsys))
    monkeypatch.chdir(tmp_path / cwd)
    argv = [str(project) if arg == "<abs>" else arg for arg in argv]
    code, out, err = _run_cli(argv, capsys)
    assert "Internal error" not in err
    assert code == EXIT_SUCCESS
    manifest = _manifest(out)
    assert [change["path"] for change in manifest["changes"]] == [path]
    assert _hashes(manifest) == expected


def test_apply_from_inside_a_source_directory_writes_what_the_root_run_plans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    module = _write_project(project)
    [planned] = _plan_from_the_root(project, monkeypatch, capsys)["changes"]
    monkeypatch.chdir(module.parent)
    code, out, err = _run_cli(["migrate", "grammar", "--apply"], capsys)
    assert "Internal error" not in err
    assert code == EXIT_SUCCESS
    manifest = _manifest(out)
    assert manifest["applied"] is True
    assert _hashes(manifest) == [(planned["before_sha256"], planned["after_sha256"])]
    assert migrate_grammar._sha256(module.read_bytes()) == planned["after_sha256"]


def _project_with_both_roots(root: Path) -> None:
    (root / "pyproject.toml").write_text(_PROJECT_PYPROJECT, encoding="utf-8")
    for relative in ("src/a.s0ma", "tests/test_a.s0ma"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_legacy(path.stem), encoding="utf-8")


def test_project_root_run_walks_only_the_configured_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _project_with_both_roots(tmp_path)
    stray = tmp_path / "scratch" / "broken.s0ma"
    stray.parent.mkdir()
    stray.write_text("not a declaration\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code, out, err = _run_cli(["migrate", "grammar", "."], capsys)
    assert (code, _migration_warnings(err)) == (EXIT_SUCCESS, [])
    assert [change["path"] for change in _manifest(out)["changes"]] == [
        "src/a.s0ma", "tests/test_a.s0ma",
    ]


def test_project_root_run_with_no_configured_root_on_disk_walks_the_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text(_PROJECT_PYPROJECT, encoding="utf-8")
    (tmp_path / "top.s0ma").write_text(_legacy("top"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code, out, err = _run_cli(["migrate", "grammar"], capsys)
    assert (code, _migration_warnings(err)) == (EXIT_SUCCESS, [])
    assert [change["path"] for change in _manifest(out)["changes"]] == ["top.s0ma"]


def test_configured_root_outside_the_migration_root_is_named_and_not_walked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _project_with_both_roots(project)
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'source_roots = ["src"]', 'source_roots = ["src", "../shared"]',
        ),
        encoding="utf-8",
    )
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "shared.s0ma").write_text(_legacy("shared"), encoding="utf-8")
    monkeypatch.chdir(project)
    code, out, err = _run_cli(["migrate", "grammar", "."], capsys)
    assert code == EXIT_SUCCESS
    assert [change["path"] for change in _manifest(out)["changes"]] == [
        "src/a.s0ma", "tests/test_a.s0ma",
    ]
    assert _migration_warnings(err) == [
        "warning: s0ma migrate grammar: configured root "
        f"{shared.resolve().as_posix()} is outside "
        f"{project.resolve().as_posix()}; it was not walked.",
    ]


def test_a_target_that_is_not_the_project_root_is_walked_whole(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _project_with_both_roots(tmp_path)
    other = tmp_path / "other" / "deep" / "o.s0ma"
    other.parent.mkdir(parents=True)
    other.write_text(_legacy("o"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code, out, _err = _run_cli(["migrate", "grammar", "other"], capsys)
    assert code == EXIT_SUCCESS
    assert [change["path"] for change in _manifest(out)["changes"]] == [
        "deep/o.s0ma",
    ]


# ---------------------------------------------------------------------------
# A directory the walk cannot read is a warning
# ---------------------------------------------------------------------------


def _unreadable_warning(relative: str, reason: str = "Permission denied") -> str:
    return (
        f"warning: s0ma migrate grammar: cannot read directory {relative} "
        f"({reason}); it was skipped, so no .s0ma file under it is in this plan."
    )


def _mode_change_cannot_lock() -> str | None:
    """Why a mode change cannot make a directory unreadable here, if it cannot."""

    if sys.platform == "win32":
        return "a mode change does not make a directory unreadable on Windows"
    if os.geteuid() == 0:
        return "a run as root reads a directory whatever its mode"
    return None


@contextmanager
def _mode(path: Path, mode: int) -> Iterator[None]:
    original = stat.S_IMODE(path.stat().st_mode)
    path.chmod(mode)
    try:
        yield
    finally:
        path.chmod(original)


def _tree_with_locked_sibling(root: Path) -> tuple[Path, Path]:
    readable = root / "open" / "a.s0ma"
    readable.parent.mkdir()
    readable.write_text(_legacy("a"), encoding="utf-8")
    locked = root / "locked"
    locked.mkdir()
    (locked / "hidden.s0ma").write_text(_legacy("hidden"), encoding="utf-8")
    return readable, locked


def _refuse_listing(monkeypatch: pytest.MonkeyPatch, refused: Path) -> None:
    refused = refused.resolve()
    real_iterdir = Path.iterdir

    def iterdir(self: Path) -> Iterator[Path]:
        if self.resolve() == refused:
            raise PermissionError(13, "Permission denied", str(self))
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)


@pytest.mark.skipif(_mode_change_cannot_lock() is not None,
                    reason=_mode_change_cannot_lock() or "")
def test_an_unreadable_directory_is_skipped_with_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    _readable, locked = _tree_with_locked_sibling(tmp_path)
    with _mode(locked, 0):
        code, out, err = _run_cli(["migrate", "grammar", str(tmp_path)], capsys)
    assert code == EXIT_SUCCESS
    assert [change["path"] for change in _manifest(out)["changes"]] == ["open/a.s0ma"]
    assert _migration_warnings(err) == [_unreadable_warning("locked")]
    assert "Internal error" not in err


@pytest.mark.skipif(_mode_change_cannot_lock() is not None,
                    reason=_mode_change_cannot_lock() or "")
def test_a_listable_directory_that_cannot_be_searched_is_skipped_with_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    _readable, locked = _tree_with_locked_sibling(tmp_path)
    with _mode(locked, stat.S_IRUSR):
        code, out, err = _run_cli(["migrate", "grammar", str(tmp_path)], capsys)
    assert code == EXIT_SUCCESS
    assert [change["path"] for change in _manifest(out)["changes"]] == ["open/a.s0ma"]
    assert _migration_warnings(err) == [_unreadable_warning("locked")]


def test_a_refused_listing_is_skipped_with_a_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _readable, locked = _tree_with_locked_sibling(tmp_path)
    _refuse_listing(monkeypatch, locked)
    code, out, err = _run_cli(["migrate", "grammar", str(tmp_path)], capsys)
    assert code == EXIT_SUCCESS
    assert [change["path"] for change in _manifest(out)["changes"]] == ["open/a.s0ma"]
    assert _migration_warnings(err) == [_unreadable_warning("locked")]
    assert "Internal error" not in err


def test_a_refused_listing_of_the_root_names_the_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "a.s0ma").write_text(_legacy("a"), encoding="utf-8")
    _refuse_listing(monkeypatch, tmp_path.resolve())
    code, out, err = _run_cli(["migrate", "grammar", str(tmp_path)], capsys)
    assert code == EXIT_SUCCESS
    assert _manifest(out)["changes"] == []
    assert _migration_warnings(err) == [_unreadable_warning(".")]


def test_apply_migrates_the_readable_source_beside_a_refused_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    readable, locked = _tree_with_locked_sibling(tmp_path)
    hidden_before = (locked / "hidden.s0ma").read_bytes()
    _refuse_listing(monkeypatch, locked)
    code, out, err = _run_cli(
        ["migrate", "grammar", "--apply", str(tmp_path)], capsys,
    )
    assert code == EXIT_SUCCESS
    manifest = _manifest(out)
    assert manifest["applied"] is True
    assert [change["path"] for change in manifest["changes"]] == ["open/a.s0ma"]
    assert _migration_warnings(err) == [_unreadable_warning("locked")]
    parse_s0ma(readable.read_text(encoding="utf-8"), filename="open/a.s0ma")
    assert (locked / "hidden.s0ma").read_bytes() == hidden_before


def _break_embed(module: Path, kind: str) -> None:
    embed = module.parent / "page.html"
    if kind == "missing":
        embed.unlink()
    elif kind == "unreadable":
        embed.chmod(0)
    else:
        embed.write_bytes(b"\xff\xfe\x00bad")


@pytest.mark.parametrize("kind", [
    "missing",
    pytest.param("unreadable", marks=pytest.mark.skipif(
        _mode_change_cannot_lock() is not None,
        reason=_mode_change_cannot_lock() or "",
    )),
    "not-utf-8",
])
@pytest.mark.parametrize("apply", [False, True], ids=["dry-run", "apply"])
def test_an_embed_that_cannot_be_read_is_a_parse_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kind: str,
    apply: bool,
) -> None:
    module = _write_project(tmp_path)
    before = module.read_bytes()
    _break_embed(module, kind)
    monkeypatch.chdir(tmp_path)
    argv = ["migrate", "grammar", *(["--apply"] if apply else []), "."]
    try:
        code, out, err = _run_cli(argv, capsys)
    finally:
        (module.parent / "page.html").unlink(missing_ok=True)
    assert "Internal error" not in err
    assert code == EXIT_VALIDATION_ERROR
    report = json.loads(out)
    assert (report["code"], report["ok"]) == ("GRAMMAR_MIGRATION_PARSE_ERROR", False)
    assert "EMBEDDED_FILE_NOT_FOUND" in report["message"]
    assert report["message"].startswith(
        "GRAMMAR_MIGRATION_PARSE_ERROR: src/site/page.s0ma: "
        "src/site/page.s0ma:7: ERROR [EMBEDDED_FILE_NOT_FOUND]",
    )
    assert report["message"].endswith(
        "; nothing was changed. Fix this source, then rerun `s0ma migrate grammar`.",
    )
    assert module.read_bytes() == before


# ---------------------------------------------------------------------------
# What git ignores is left out
# ---------------------------------------------------------------------------

_needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")


@pytest.fixture
def isolated_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep git away from this machine's global and system configuration."""

    home = tmp_path / "_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(  # noqa: S603 - fixed argv, no shell, test-local repository
        ["git", "-C", str(root), *arguments],  # noqa: S607
        check=True, capture_output=True,
    )


def _repository(root: Path, ignore: str) -> Path:
    root.mkdir()
    _git(root, "init", "-q")
    (root / ".gitignore").write_text(ignore, encoding="utf-8")
    return root


def _broken(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not a declaration\n", encoding="utf-8")


def _legacy_at(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_legacy(path.stem), encoding="utf-8")


@_needs_git
@pytest.mark.usefixtures("isolated_git")
def test_sources_git_ignores_are_not_planned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repository(tmp_path / "repo", "out/\nscratch.s0ma\nvendored/\n")
    _legacy_at(repo / "kept.s0ma")
    _broken(repo / "out" / "broken.s0ma")
    _broken(repo / "scratch.s0ma")
    _legacy_at(repo / "vendored" / "tracked.s0ma")
    _broken(repo / "vendored" / "untracked.s0ma")
    _git(repo, "add", "-f", "vendored/tracked.s0ma")
    code, out, err = _run_cli(["migrate", "grammar", str(repo)], capsys)
    assert (code, _migration_warnings(err)) == (EXIT_SUCCESS, [])
    assert [change["path"] for change in _manifest(out)["changes"]] == [
        "kept.s0ma", "vendored/tracked.s0ma",
    ]


@_needs_git
@pytest.mark.usefixtures("isolated_git")
def test_an_ignored_directory_is_not_read_so_it_cannot_warn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repository(tmp_path / "repo", "locked/\n")
    _legacy_at(repo / "kept.s0ma")
    _legacy_at(repo / "locked" / "hidden.s0ma")
    _refuse_listing(monkeypatch, (repo / "locked").resolve())
    code, out, err = _run_cli(["migrate", "grammar", str(repo)], capsys)
    assert (code, _migration_warnings(err)) == (EXIT_SUCCESS, [])
    assert [change["path"] for change in _manifest(out)["changes"]] == ["kept.s0ma"]


@_needs_git
@pytest.mark.usefixtures("isolated_git")
def test_a_migration_root_its_repository_ignores_still_plans_its_sources(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repository(tmp_path / "repo", "inner/\n")
    _legacy_at(repo / "inner" / "a.s0ma")
    _legacy_at(repo / "inner" / "deep" / "b.s0ma")
    code, out, err = _run_cli(["migrate", "grammar", str(repo / "inner")], capsys)
    assert (code, _migration_warnings(err)) == (EXIT_SUCCESS, [])
    assert [change["path"] for change in _manifest(out)["changes"]] == [
        "a.s0ma", "deep/b.s0ma",
    ]


@_needs_git
@pytest.mark.usefixtures("isolated_git")
def test_git_ignore_applies_inside_the_configured_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repository(tmp_path / "repo", "src/generated/\n")
    _project_with_both_roots(repo)
    _broken(repo / "src" / "generated" / "broken.s0ma")
    monkeypatch.chdir(repo)
    code, out, err = _run_cli(["migrate", "grammar", "."], capsys)
    assert (code, _migration_warnings(err)) == (EXIT_SUCCESS, [])
    assert [change["path"] for change in _manifest(out)["changes"]] == [
        "src/a.s0ma", "tests/test_a.s0ma",
    ]


@_needs_git
@pytest.mark.usefixtures("isolated_git")
@pytest.mark.skipif(_mode_change_cannot_lock() is not None,
                    reason=_mode_change_cannot_lock() or "")
def test_git_says_nothing_on_the_terminal_about_an_unreadable_directory(
    tmp_path: Path, capfd: pytest.CaptureFixture[str],
) -> None:
    repo = _repository(tmp_path / "repo", "")
    _readable, locked = _tree_with_locked_sibling(repo)
    with _mode(locked, 0):
        code, out, err = _run_cli(["migrate", "grammar", str(repo)], capfd)
    assert code == EXIT_SUCCESS
    assert [change["path"] for change in _manifest(out)["changes"]] == ["open/a.s0ma"]
    assert _migration_warnings(err) == [_unreadable_warning("locked")]
    assert "could not open directory" not in err
