"""Tests for the check-failure baseline — NEW vs PRE-EXISTING attribution.

Batch-01c M2 (P0). The baseline gives ``s0ma check`` a memory of the last
run so a fresh failure can be labelled NEW and the "these errors are
pre-existing" excuse (the verbatim batch-01c CM6 dismissal) is only
claimable when the output actually says PRE-EXISTING.

Coverage maps to the M2 done-when clauses:

* green -> record (empty baseline, schema-tagged)
* fail-after-green -> NEW labels (the CM6 shape, driven end to end)
* fail-with-prior-fails -> PRE-EXISTING vs NEW split
* resolved summary
* no-baseline path (first-ever run is failing)
* atomicity / determinism (two green checks byte-identical; no temp left)
* stable key ignores line numbers

0.13.0 M2 (the anchor semantics upgrade — deliberate pin updates):
classification now keys on the record's monotone-shrinking inherited-debt
``anchor`` (additive field under the same schema), not the last run's
set, so an agent's own red ``check`` can no longer launder NEW into
PRE-EXISTING (the exact CM6 sequence: check red, dismiss, build green).
``TestAnchorSemantics`` pins: second-red-check stays NEW; a subset-scope
check neither records nor strips other modules' anchor keys; a parse
error shadowing a module does not resurrect its inherited failures as
NEW; a legacy no-anchor record migrates gracefully; a once-fixed key
never re-enters the anchor.
"""

from __future__ import annotations

import json
from pathlib import PurePath
from typing import TYPE_CHECKING

from s0ma_dsl.check_baseline import (
    BASELINE_SCHEMA,
    DiagnosticKey,
    baseline_path,
    classify,
    diagnostic_key,
    load_baseline_keys,
    load_baseline_record,
    save_baseline_keys,
)
from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.errors import S0maError

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_PYPROJECT = """\
[project]
name = "baseline_app"
version = "0.1.0"

[tool.s0ma]
source_roots = ["src"]
build_dir = "build"
"""


def _valid(module: str, nerve: str) -> str:
    """A minimal strict-green module exporting one PUBLIC nerve."""
    return f"""\
module {module}
    layer: DOMAIN
    version: 1.0.0
    intent: "A minimal module exercising the check-baseline attribution."
    exports: [{nerve}]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve {nerve} :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Return a constant used by the check-baseline attribution tests."
    expects: "no arguments"
    guarantees: "returns a constant integer"
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
    def {nerve}():
        return 1
"""


def _broken(module: str, nerve: str) -> str:
    """The valid module with a bare body import — a reliable BARE_IMPORT error."""
    return f"""\
module {module}
    layer: DOMAIN
    version: 1.0.0
    intent: "A minimal module exercising the check-baseline attribution."
    exports: [{nerve}]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve {nerve} :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Return a constant used by the check-baseline attribution tests."
    expects: "no arguments"
    guarantees: "returns a constant integer"
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
    def {nerve}():
        import os
        return len(str(os.getpid())) and 1
"""


def _make_project(root: Path, sources: dict[str, str]) -> Path:
    """Create a real ``[tool.s0ma]`` project under *root* with *sources*."""
    src = root / "src"
    src.mkdir(parents=True)
    (root / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    for name, content in sources.items():
        (src / name).write_text(content, encoding="utf-8")
    return root


def _write(root: Path, name: str, content: str) -> None:
    (root / "src" / name).write_text(content, encoding="utf-8")


def _check_json(
    root: Path, capsys: pytest.CaptureFixture[str], mode: str = "strict",
) -> tuple[int, dict]:
    """Run ``s0ma check --format json`` on *root*; return (exit_code, doc)."""
    rc = S0maCLI().run(
        ["--project-root", str(root), "check", "--mode", mode, "--format", "json"]
    )
    out = capsys.readouterr().out
    return rc, json.loads(out)


def _labels(doc: dict) -> dict[str, str]:
    """Map each rendered error's source *basename* to its delta label.

    ``errors[].file`` is the diagnostic's absolute, native-separator path
    (the clickable terminal form) — the relative, platform-stable module
    identity is ``delta[].module``, asserted separately. Basenames
    therefore come from ``PurePath``: splitting on "/" returned the whole
    ``C:\\...`` path on Windows and silently compared the wrong keys.
    """
    return {PurePath(e["file"]).name: e["delta_label"] for e in doc["errors"]}


def _check_text(
    root: Path, capsys: pytest.CaptureFixture[str], mode: str = "strict",
) -> tuple[int, str]:
    rc = S0maCLI().run(["--project-root", str(root), "check", "--mode", mode])
    return rc, capsys.readouterr().out


# ---------------------------------------------------------------------------
# green -> record
# ---------------------------------------------------------------------------


class TestGreenRecords:
    def test_green_check_writes_empty_schema_tagged_baseline(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(tmp_path / "p", {"alpha.s0ma": _valid("alpha", "a")})
        rc, doc = _check_json(root, capsys)
        assert rc == 0
        # green render is unchanged: no delta block on a passing run
        assert "delta" not in doc
        # the clean fingerprint is recorded, schema-tagged, empty.
        # 0.13.0 M2 (deliberate pin update): the record gains the additive
        # `anchor` list — the monotone-shrinking inherited-debt set that
        # classification keys on. A green run records both sets empty.
        path = baseline_path(root)
        assert path.is_file()
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record == {
            "schema": BASELINE_SCHEMA, "diagnostics": [], "anchor": [],
            "python_file_anchor": [],
        }

    def test_synthetic_project_records_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # No [tool.s0ma] table -> synthetic fallback -> no baseline anchor.
        loose = tmp_path / "loose.s0ma"
        loose.write_text(_valid("loose", "g"), encoding="utf-8")
        rc = S0maCLI().run(["check", str(loose), "--mode", "dev"])
        assert rc == 0
        assert not (tmp_path / ".s0ma").exists()


# ---------------------------------------------------------------------------
# fail-after-green -> NEW  (the CM6 shape, end to end)
# ---------------------------------------------------------------------------


class TestFailAfterGreenIsNew:
    def test_cm6_shape_edit_introduces_failures_labelled_new(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The exact evidence the r03 agent lacked.

        A clean project checks green (records the baseline); an edit then
        introduces a failure; the very next check labels it NEW — so the
        "these errors are pre-existing" dismissal is directly refuted.
        """
        root = _make_project(tmp_path / "p", {"alpha.s0ma": _valid("alpha", "a")})

        rc, _ = _check_text(root, capsys)
        assert rc == 0  # green baseline established

        _write(root, "alpha.s0ma", _broken("alpha", "a"))
        rc, out = _check_text(root, capsys)
        assert rc == 1
        # every failing line is attributed, NEW-count leads the summary
        assert "[NEW]" in out
        assert "1 failure(s): 1 NEW since your last green build." in out
        assert "[PRE-EXISTING]" not in out

    def test_new_label_in_json_delta(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(tmp_path / "p", {"alpha.s0ma": _valid("alpha", "a")})
        _check_json(root, capsys)  # green baseline
        _write(root, "alpha.s0ma", _broken("alpha", "a"))
        rc, doc = _check_json(root, capsys)
        assert rc == 1
        assert doc["delta"]["baseline_exists"] is True
        assert doc["errors"][0]["delta_label"] == "NEW"
        codes = {k["code"] for k in doc["delta"]["new"]}
        assert "BARE_IMPORT" in codes
        assert doc["delta"]["pre_existing"] == []
        # the freshly-recorded baseline now carries the failure
        keys = load_baseline_keys(root)
        assert keys is not None and len(keys) == 1


# ---------------------------------------------------------------------------
# fail-with-prior-fails -> PRE-EXISTING vs NEW split
# ---------------------------------------------------------------------------


class TestPreExistingVsNewSplit:
    def test_old_failure_pre_existing_new_breakage_new(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(
            tmp_path / "p",
            {
                "alpha.s0ma": _broken("alpha", "a"),  # already failing
                "beta.s0ma": _valid("beta", "b"),
            },
        )
        # Run 1: only alpha fails -> records {alpha}. (No baseline yet.)
        rc, doc = _check_json(root, capsys)
        assert rc == 1
        assert doc["delta"]["baseline_exists"] is False

        # Run 2: alpha still fails AND beta now breaks.
        _write(root, "beta.s0ma", _broken("beta", "b"))
        rc, doc = _check_json(root, capsys)
        assert rc == 1
        assert doc["delta"]["baseline_exists"] is True
        new_modules = {k["module"] for k in doc["delta"]["new"]}
        pre_modules = {k["module"] for k in doc["delta"]["pre_existing"]}
        assert new_modules == {"src/beta.s0ma"}
        assert pre_modules == {"src/alpha.s0ma"}
        assert doc["delta"]["summary"] == (
            "2 failure(s): 1 NEW since your last green build, 1 pre-existing."
        )
        labels = _labels(doc)
        assert labels == {"alpha.s0ma": "PRE-EXISTING", "beta.s0ma": "NEW"}


# ---------------------------------------------------------------------------
# resolved summary
# ---------------------------------------------------------------------------


class TestResolvedSummary:
    def test_resolved_failures_are_summarized(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(
            tmp_path / "p",
            {"alpha.s0ma": _broken("alpha", "a"), "beta.s0ma": _broken("beta", "b")},
        )
        # Run 1: both fail -> baseline {alpha, beta}.
        _check_json(root, capsys)
        # Run 2: fix beta, keep alpha broken.
        _write(root, "beta.s0ma", _valid("beta", "b"))
        rc, doc = _check_json(root, capsys)
        assert rc == 1
        assert {k["module"] for k in doc["delta"]["resolved"]} == {"src/beta.s0ma"}
        assert doc["delta"]["summary"] == (
            "1 failure(s): 1 pre-existing. (1 resolved since baseline.)"
        )


# ---------------------------------------------------------------------------
# no-baseline path
# ---------------------------------------------------------------------------


class TestNoBaselinePath:
    def test_first_ever_run_failing_notes_no_baseline(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(tmp_path / "p", {"alpha.s0ma": _broken("alpha", "a")})
        rc, out = _check_text(root, capsys)
        assert rc == 1
        assert "No check baseline exists yet" in out
        # nothing is attributed without a baseline
        assert "[NEW]" not in out and "[PRE-EXISTING]" not in out

    def test_first_ever_run_failing_json_has_note_not_labels(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(tmp_path / "p", {"alpha.s0ma": _broken("alpha", "a")})
        rc, doc = _check_json(root, capsys)
        assert rc == 1
        assert doc["delta"]["baseline_exists"] is False
        assert "note" in doc["delta"]
        assert "delta_label" not in doc["errors"][0]


# ---------------------------------------------------------------------------
# atomicity / determinism
# ---------------------------------------------------------------------------


class TestDeterminismAndAtomicity:
    def test_two_green_checks_byte_identical(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(tmp_path / "p", {"alpha.s0ma": _valid("alpha", "a")})
        _check_json(root, capsys)
        first = baseline_path(root).read_bytes()
        _check_json(root, capsys)
        second = baseline_path(root).read_bytes()
        assert first == second

    def test_two_identical_failing_checks_byte_identical(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(tmp_path / "p", {"alpha.s0ma": _broken("alpha", "a")})
        _check_json(root, capsys)
        first = baseline_path(root).read_bytes()
        _check_json(root, capsys)
        assert baseline_path(root).read_bytes() == first

    def test_save_leaves_no_temp_file(self, tmp_path: Path) -> None:
        root = tmp_path / "p"
        (root).mkdir()
        keys = [DiagnosticKey("X", "src/a.s0ma", "a")]
        save_baseline_keys(root, keys)
        residue = [p.name for p in (root / ".s0ma").iterdir()]
        assert residue == ["check-baseline.json"]  # tmp-rename left nothing behind

    def test_save_is_order_insensitive_and_deterministic(
        self, tmp_path: Path,
    ) -> None:
        root_a, root_b = tmp_path / "a", tmp_path / "b"
        root_a.mkdir()
        root_b.mkdir()
        k1 = DiagnosticKey("B", "src/z.s0ma", "z")
        k2 = DiagnosticKey("A", "src/a.s0ma", "a")
        save_baseline_keys(root_a, [k1, k2])
        save_baseline_keys(root_b, [k2, k1])
        assert baseline_path(root_a).read_bytes() == baseline_path(root_b).read_bytes()


# ---------------------------------------------------------------------------
# stable key: no line numbers
# ---------------------------------------------------------------------------


class TestStableKey:
    def _err(self, line: int) -> S0maError:
        return S0maError(
            code="NOT_EXPORTED",
            message="msg",
            file="src/alpha.s0ma",
            line=line,
            column=0,
            severity="error",
            remediation="fix it",
            context={"declaration": "widget"},
        )

    def test_key_ignores_line_number(self, tmp_path: Path) -> None:
        k_low = diagnostic_key(self._err(3), root=None)
        k_high = diagnostic_key(self._err(999), root=None)
        assert k_low == k_high
        assert k_low == DiagnosticKey("NOT_EXPORTED", "src/alpha.s0ma", "widget")

    def test_key_uses_context_symbol(self, tmp_path: Path) -> None:
        err = S0maError(
            code="C", message="m", file="f.s0ma", line=1, column=0,
            severity="error", remediation="r", context={"name": "sym"},
        )
        assert diagnostic_key(err, root=None).symbol == "sym"

    def test_classify_no_baseline_attributes_nothing(self) -> None:
        err = self._err(1)
        report = classify(None, [err], root=None)
        assert report.baseline_exists is False
        assert report.new == () and report.pre_existing == ()
        assert report.label_for_diag(err) is None

    def test_dot_s0ma_directory_does_not_break_discovery(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A ``.s0ma`` working-state *directory* must not be parsed as a file.

        ``rglob("*.s0ma")`` matches the ``.s0ma`` directory itself; before
        the ``is_file()`` guard, discovery handed it to the parser and the
        run died with "Is a directory". Two sequential checks (the second
        with ``.s0ma/`` present from the first) exercise the fix; this
        makes it explicit, including a stray ``.s0ma`` dir under ``src/``.
        """
        root = _make_project(tmp_path / "p", {"alpha.s0ma": _valid("alpha", "a")})
        (root / ".s0ma").mkdir()  # as if a prior run / registry.db left it
        (root / "src" / ".s0ma").mkdir()  # even nested under a source root
        rc, _ = _check_json(root, capsys)
        assert rc == 0  # discovery skipped the directories, no internal error

    def test_load_missing_is_none_malformed_is_none(self, tmp_path: Path) -> None:
        root = tmp_path / "p"
        root.mkdir()
        assert load_baseline_keys(root) is None  # missing
        path = baseline_path(root)
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        assert load_baseline_keys(root) is None  # malformed -> absent, never raises


# ---------------------------------------------------------------------------
# 0.13.0 M2: the monotone-shrinking inherited-debt anchor
# ---------------------------------------------------------------------------


def _parse_broken(module: str, nerve: str) -> str:
    """A module whose nerve body cannot parse (import, no def) — PARSE_ERROR.

    Parsing yields no module, so the module's downstream checks (its
    BARE_IMPORT included) never run this pass — the preemption shape.
    """
    return f"""\
module {module}
    layer: DOMAIN
    version: 1.0.0
    intent: "A minimal module exercising the check-baseline attribution."
    exports: [{nerve}]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve {nerve} :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Return a constant used by the check-baseline attribution tests."
    expects: "no arguments"
    guarantees: "returns a constant integer"
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
    import os
"""


def _anchor_codes(root: Path) -> list[str]:
    record = load_baseline_record(root)
    assert record is not None
    return sorted(k.code for k in record.anchor)


class TestAnchorSemantics:
    """Classification anchors on inherited debt, which only ever shrinks.

    The 0.12.0 last-run semantics had the laundering hole the CM6 crater
    walked through: green -> break -> check (NEW, but recorded) -> the
    NEXT look calls it PRE-EXISTING. These tests pin the anchor upgrade.
    """

    def test_second_red_check_stays_new(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The literal CM6 laundering sequence, now closed at `check`."""
        root = _make_project(tmp_path / "p", {"alpha.s0ma": _valid("alpha", "a")})
        rc, _ = _check_text(root, capsys)
        assert rc == 0  # green baseline: empty anchor

        _write(root, "alpha.s0ma", _broken("alpha", "a"))
        rc, out = _check_text(root, capsys)
        assert rc == 1 and "[NEW]" in out

        # The second look — under 0.12.0 this flipped to PRE-EXISTING
        # (the laundering); under the anchor it stays NEW.
        rc, out = _check_text(root, capsys)
        assert rc == 1
        assert "[NEW]" in out
        assert "[PRE-EXISTING]" not in out
        # the anchor never grew
        assert _anchor_codes(root) == []

    def test_subset_check_does_not_record_or_strip(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(
            tmp_path / "p",
            {
                "alpha.s0ma": _broken("alpha", "a"),  # inherited debt
                "beta.s0ma": _valid("beta", "b"),
            },
        )
        # First contact (full scope): alpha's failure IS the anchor.
        rc, _ = _check_json(root, capsys)
        assert rc == 1
        before = baseline_path(root).read_bytes()
        assert _anchor_codes(root) == ["BARE_IMPORT"]

        # A subset check of beta only: labels render (beta NEW — not in
        # the anchor) but NOTHING is recorded — alpha's anchor key must
        # not be stripped by a run that never re-analysed alpha.
        _write(root, "beta.s0ma", _broken("beta", "b"))
        rc = S0maCLI().run([
            "--project-root", str(root),
            "check", str(root / "src" / "beta.s0ma"),
            "--mode", "strict", "--format", "json",
        ])
        doc = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert doc["errors"][0]["delta_label"] == "NEW"
        assert baseline_path(root).read_bytes() == before  # not recorded

        # The next full check still attributes alpha to the anchor.
        rc, doc = _check_json(root, capsys)
        assert rc == 1
        labels = _labels(doc)
        assert labels == {"alpha.s0ma": "PRE-EXISTING", "beta.s0ma": "NEW"}

    def test_parse_error_shadowing_keeps_anchor(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A transient parse error must not resurrect inherited debt as NEW.

        Inherited failure X -> agent introduces a parse error (X's module
        analysis is cut short, X unobservable) -> agent fixes the parse
        error -> X must still classify PRE-EXISTING, not NEW.
        """
        root = _make_project(tmp_path / "p", {"alpha.s0ma": _broken("alpha", "a")})
        rc, _ = _check_json(root, capsys)  # first contact: anchor {BARE_IMPORT}
        assert rc == 1
        assert _anchor_codes(root) == ["BARE_IMPORT"]

        # Parse error preempts alpha's analysis: BARE_IMPORT is absent
        # from the run, but its anchor key survives (module preempted).
        _write(root, "alpha.s0ma", _parse_broken("alpha", "a"))
        rc, doc = _check_json(root, capsys)
        assert rc == 1
        assert {k["code"] for k in doc["delta"]["new"]} == {"PARSE_ERROR"}
        # not reported resolved either — absence under preemption is not
        # evidence of a fix
        assert doc["delta"]["resolved"] == []
        assert _anchor_codes(root) == ["BARE_IMPORT"]

        # Parse error fixed, X resurfaces: still PRE-EXISTING.
        _write(root, "alpha.s0ma", _broken("alpha", "a"))
        rc, doc = _check_json(root, capsys)
        assert rc == 1
        assert doc["errors"][0]["code"] == "BARE_IMPORT"
        assert doc["errors"][0]["delta_label"] == "PRE-EXISTING"

    def test_legacy_record_without_anchor_migrates(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A 0.12.0 record (no anchor field) degrades to last-run semantics
        for exactly one run: anchor := its diagnostics set."""
        root = _make_project(tmp_path / "p", {"alpha.s0ma": _broken("alpha", "a")})
        rc, _ = _check_json(root, capsys)
        assert rc == 1
        # Strip the anchor field — reconstructing a 0.12.0 file.
        path = baseline_path(root)
        raw = json.loads(path.read_text(encoding="utf-8"))
        del raw["anchor"]
        path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
        record = load_baseline_record(root)
        assert record is not None
        assert record.anchor == record.last_run  # graceful migration

        rc, doc = _check_json(root, capsys)
        assert rc == 1
        assert doc["errors"][0]["delta_label"] == "PRE-EXISTING"

    def test_fixed_key_never_reenters_the_anchor(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Once observed fixed, a key leaves the anchor forever: the same
        failure re-introduced later is NEW (yours), not inherited."""
        root = _make_project(tmp_path / "p", {"alpha.s0ma": _broken("alpha", "a")})
        rc, _ = _check_json(root, capsys)  # first contact: inherited
        assert rc == 1
        assert _anchor_codes(root) == ["BARE_IMPORT"]

        _write(root, "alpha.s0ma", _valid("alpha", "a"))
        rc, _ = _check_json(root, capsys)  # observed fixed -> leaves anchor
        assert rc == 0
        assert _anchor_codes(root) == []

        _write(root, "alpha.s0ma", _broken("alpha", "a"))
        rc, doc = _check_json(root, capsys)  # same failure, back again
        assert rc == 1
        assert doc["errors"][0]["delta_label"] == "NEW"
