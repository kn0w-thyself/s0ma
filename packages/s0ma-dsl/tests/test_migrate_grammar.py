"""M3A whole-project grammar migration safety contracts."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.cli import migrate_grammar
from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.cli.migrate_grammar import (
    GrammarMigrationError,
    apply_grammar_migration,
    plan_grammar_migration,
)
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.parser import parse_s0ma


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
