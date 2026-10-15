"""Tests for ``s0ma score`` (STD-M8, usability plan).

Covers (per the M8 plan, Step 5): score on (a) the monorepo's own
``packages/s0ma-mcp`` flagship self-host (should score HIGH), (b) a fresh
``s0ma new project`` temp project, and (c) ``--gate`` tripping below a
mode floor and passing above it. The structured JSON shape is pinned, and
the honesty rules are asserted directly: interoception is ``n/a`` (never a
fabricated 0/100) and excluded from the overall roll-up, and the exempt
set is LISTED (members enumerated), not merely counted.

The flagship's committed ``_built/`` is always on disk (the selfhost build
is byte-gated), so (a) needs no build step. The temp-project cases drive
``s0ma new project`` / ``s0ma build`` through the CLI exactly as a user
would, then score with ``--project-root`` so the wall-clock-free run stays
hermetic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.cli.score import MODE_FLOORS, _public_nerve_coverage
from s0ma_dsl.parser.s0ma_parser import parse_s0ma

#: The monorepo root (tests run with cwd = packages/s0ma-dsl under
#: check.py — every score invocation passes --project-root explicitly).
REPO_ROOT = Path(__file__).resolve().parents[3]
FLAGSHIP = REPO_ROOT / "packages" / "s0ma-mcp"

EXIT_GATE_FAILURE = 1

#: Top-level keys every score report carries (the pinned JSON shape).
REPORT_KEYS = {
    "schema",
    "project",
    "root",
    "mode",
    "gate_mode",
    "overall",
    "faculties",
    "exempt_set",
    "module_count",
    "public_nerve_count",
    "gate",
}
FACULTY_KEYS = {"proprioception", "interoception", "metacognition"}
EXEMPT_KEYS = {
    "total",
    "bootstrap_module",
    "bootstrap_files",
    "package_markers",
    "internal",
}


@pytest.fixture
def cli() -> S0maCLI:
    return S0maCLI()


def _score_json(
    cli: S0maCLI,
    capsys: pytest.CaptureFixture[str],
    root: Path,
    *extra: str,
) -> tuple[int, dict[str, Any]]:
    rc = cli.run(
        ["--project-root", str(root), "score", "--format", "json", *extra]
    )
    return rc, json.loads(capsys.readouterr().out)


@pytest.fixture
def fresh_project(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> Path:
    """A freshly initialized + built project (via ``s0ma new project``)."""
    target = tmp_path / "scoreproj"
    assert cli.run(["new", "project", str(target), "--quiet"]) == EXIT_SUCCESS
    capsys.readouterr()  # drain the scaffold summary
    return target


# ---------------------------------------------------------------------------
# Shared shape assertions
# ---------------------------------------------------------------------------


def _assert_report_shape(report: dict[str, Any]) -> None:
    assert set(report) == REPORT_KEYS, set(report) ^ REPORT_KEYS
    assert report["schema"] == "s0ma-score@2"
    assert set(report["faculties"]) == FACULTY_KEYS
    assert set(report["exempt_set"]) == EXEMPT_KEYS

    # Every faculty body carries a ``score`` (float or None).
    for body in report["faculties"].values():
        assert "score" in body
        assert body["score"] is None or isinstance(body["score"], (int, float))

    # Proprioception + metacognition expose their named sub-metrics.
    pm = report["faculties"]["proprioception"]["metrics"]
    assert set(pm) == {
        "registration",
        "layer_compliance",
        "structural_clean",
    }
    mm = report["faculties"]["metacognition"]["metrics"]
    assert set(mm) == {
        "doc_ref_coverage", "declared_test_evidence", "drift_free",
    }

    gate = report["gate"]
    assert set(gate) == {
        "mode", "floor", "passes", "blocked", "reasons", "na_faculties",
    }
    assert gate["passes"] is None
    assert gate["reasons"] == ["mode not pinned by caller"]


# ---------------------------------------------------------------------------
# (a) The flagship self-host — should score HIGH
# ---------------------------------------------------------------------------


class TestScoreOnTheFlagship:
    def test_flagship_scores_high_with_full_shape(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc, report = _score_json(cli, capsys, FLAGSHIP)

        assert rc == EXIT_SUCCESS
        _assert_report_shape(report)
        assert report["project"] == "s0ma-mcp"

        # The flagship is the worked example of the boundary doctrine at the
        # release gate: a high overall, with the two measurable faculties at
        # or near 100 and interoception honestly n/a.
        assert report["overall"] is not None
        assert report["overall"] >= 90.0
        assert report["faculties"]["proprioception"]["score"] == 100.0
        assert report["faculties"]["metacognition"]["score"] == 100.0

    def test_interoception_is_honest_na_not_fabricated(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Interoception is n/a (not 0, not 100) and excluded from roll-up."""
        _, report = _score_json(cli, capsys, FLAGSHIP)

        inter = report["faculties"]["interoception"]
        assert inter["score"] is None
        assert inter["status"].startswith("n/a")
        assert "resource profile" in inter["status"]
        # The n/a faculty must be named in the gate's exclusion list — never
        # silently counted toward the overall as 0 or 100.
        assert "interoception" in report["gate"]["na_faculties"]

    def test_exempt_set_is_listed_not_just_counted(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The exempt set enumerates its members (HONESTY rule + M3 §28.2)."""
        _, report = _score_json(cli, capsys, FLAGSHIP)

        exempt = report["exempt_set"]
        # The single handwritten bootstrap module is the self-host's
        # ``__init__.py`` (declared first under bootstrap_files).
        assert exempt["bootstrap_module"] == ["src/s0ma_mcp/__init__.py"]
        # The generated build-dir package marker is auto-classified the same
        # way ``s0ma verify`` classifies it.
        assert "src/s0ma_mcp/_built/__init__.py" in exempt["package_markers"]
        # @internal components are enumerated as module::name ids, not summed.
        assert exempt["internal"], "expected @internal members enumerated"
        assert all("::" in item for item in exempt["internal"])
        # ``total`` is the sum of the four listed categories.
        assert exempt["total"] == (
            len(exempt["bootstrap_module"])
            + len(exempt["bootstrap_files"])
            + len(exempt["package_markers"])
            + len(exempt["internal"])
        )

    def test_text_and_json_render_the_same_overall(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """D-5: text is derived from the same data as JSON."""
        _, report = _score_json(cli, capsys, FLAGSHIP)
        overall = report["overall"]

        rc = cli.run(["--project-root", str(FLAGSHIP), "score"])
        text = capsys.readouterr().out
        assert rc == EXIT_SUCCESS
        assert f"{overall:.1f}%" in text
        assert "self-knowledge" in text
        assert "proprioception" in text
        assert "interoception" in text
        assert "metacognition" in text
        # The n/a faculty surfaces honestly in the text too.
        assert "n/a" in text


# ---------------------------------------------------------------------------
# (b) A fresh new project
# ---------------------------------------------------------------------------


class TestScoreOnAFreshProject:
    def test_fresh_project_scores_well(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        fresh_project: Path,
    ) -> None:
        """A fresh project is release-clean by construction (M6/M7).

        ``s0ma new project`` ships a built, app-map-covered, mirrored-test
        starter, so its single PUBLIC nerve is fully doc- and test-covered
        and the layers/structure are clean — a genuinely high score (the
        honest measurement, even though the plan was authored expecting a
        "mid" number before M6 raised the scaffold floor).
        """
        rc, report = _score_json(cli, capsys, fresh_project)

        assert rc == EXIT_SUCCESS
        _assert_report_shape(report)
        assert report["overall"] is not None
        # Comfortably above the dev floor; the scaffold is well-formed.
        assert report["overall"] >= MODE_FLOORS["dev"]
        # The starter has at least its one PUBLIC nerve.
        assert report["public_nerve_count"] >= 1
        # Interoception stays honestly n/a on a .s0ma project.
        assert report["faculties"]["interoception"]["score"] is None

    def test_fresh_project_report_only_exits_zero(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        fresh_project: Path,
    ) -> None:
        """Without --gate the command is report-only (exit 0)."""
        rc = cli.run(["--project-root", str(fresh_project), "score"])
        capsys.readouterr()
        assert rc == EXIT_SUCCESS

    def test_registration_carries_roster_count(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        fresh_project: Path,
    ) -> None:
        """Roster adoption remains visible but earns no gate credit."""
        rc, report = _score_json(cli, capsys, fresh_project)
        assert rc == EXIT_SUCCESS
        reg = report["faculties"]["proprioception"]["metrics"]["registration"]
        assert reg["roster_adopted"] == 0
        assert reg["componentized"] >= 1


def test_covered_by_requires_a_real_nonempty_test_declaration() -> None:
    """A name alone is not evidence; a declared test body is."""
    production_source = """\
module evidence_subject
    layer: DOMAIN
    version: 1.0.0
    intent: "Subject for declared-test-evidence scoring."
    exports: [Compute]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve Compute :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Returns a stable value."
    expects: "no inputs"
    guarantees: "Returns one."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    covered_by: [test_compute_evidence]
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
    ---
    def Compute() -> int:
        return 1
"""
    test_source = """\
module evidence_tests
    layer: DOMAIN
    version: 1.0.0
    intent: "Declared test-evidence fixture."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
test test_compute_evidence :: DOMAIN
    intent: "Provides real, non-empty evidence for Compute."
    tests: [missing_target]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_compute_evidence():
        assert True
"""
    subject = parse_s0ma(production_source, filename="evidence_subject.s0ma")
    assert _public_nerve_coverage(
        {"evidence_subject": subject}, {"evidence_subject"},
    ) == (1, 0, 0)

    evidence = parse_s0ma(test_source, filename="evidence_tests.s0ma")
    assert _public_nerve_coverage(
        {"evidence_subject": subject, "evidence_tests": evidence},
        {"evidence_subject"},
    ) == (1, 0, 1)


# ---------------------------------------------------------------------------
# (c) --gate trips below a floor and passes above it
# ---------------------------------------------------------------------------


def _strip_test_coverage(project: Path) -> None:
    """Degrade a fresh project so its PUBLIC nerve loses test coverage.

    Removing the mirrored ``tests/`` tree drops test coverage to 0%, which
    pulls metacognition (and therefore the overall) below the release floor
    while staying above the dev floor — the lever the gate tests need.
    """
    import shutil

    tests_dir = project / "tests"
    if tests_dir.exists():
        shutil.rmtree(tests_dir)


class TestGate:
    def test_release_gate_blocks_pending_debt_from_migration_authoring(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        fresh_project: Path,
    ) -> None:
        source = next(
            path
            for path in (fresh_project / "src").rglob("*.s0ma")
            if "    requires: []" in path.read_text(encoding="utf-8")
        )
        source.write_text(
            source.read_text(encoding="utf-8").replace(
                "    requires: []",
                '    requires: pending("dependency owner review")',
                1,
            ),
            encoding="utf-8",
        )

        rc, report = _score_json(
            cli,
            capsys,
            fresh_project,
            "--mode",
            "migration",
            "--gate-mode",
            "release",
            "--gate",
        )
        assert rc == EXIT_GATE_FAILURE, report
        assert report["mode"] == "migration"
        assert report["gate_mode"] == "release"
        assert report["gate"]["passes"] is False
        assert {
            "faculty": "proprioception",
            "metric": "semantic_completeness",
            "reason": "pending_semantic_state",
        } in report["gate"]["blocked"]

        _, report_only = _score_json(
            cli, capsys, fresh_project, "--mode", "migration",
        )
        assert report_only["gate"]["passes"] is None
        assert all(
            item["reason"] != "pending_semantic_state"
            for item in report_only["gate"]["blocked"]
        )

    def test_gate_trips_below_release_floor(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        target = tmp_path / "degraded"
        assert cli.run(["new", "project", str(target), "--quiet"]) == EXIT_SUCCESS
        capsys.readouterr()
        _strip_test_coverage(target)
        # Rebuild source only (tests removed) so the manifest is consistent.
        assert (
            cli.run(["--project-root", str(target), "build", str(target / "src"), "--quiet"])
            == EXIT_SUCCESS
        )
        capsys.readouterr()

        # Confirm the degradation actually pushed overall below 90.
        rc_json, report = _score_json(
            cli, capsys, target, "--gate-mode", "release",
        )
        assert rc_json == EXIT_SUCCESS  # report-only, no --gate
        assert report["overall"] is not None
        assert report["overall"] < MODE_FLOORS["release"]
        assert report["gate"]["passes"] is False
        assert report["faculties"]["metacognition"]["metrics"][
            "declared_test_evidence"
        ]["score"] == 0.0

        # --gate at release: exit non-zero.
        rc_gate = cli.run(
            [
                "--project-root", str(target), "score",
                "--gate-mode", "release", "--gate",
            ]
        )
        capsys.readouterr()
        assert rc_gate == EXIT_GATE_FAILURE

    def test_gate_passes_above_floor(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        target = tmp_path / "degraded2"
        assert cli.run(["new", "project", str(target), "--quiet"]) == EXIT_SUCCESS
        capsys.readouterr()
        _strip_test_coverage(target)
        assert (
            cli.run(["--project-root", str(target), "build", str(target / "src"), "--quiet"])
            == EXIT_SUCCESS
        )
        capsys.readouterr()

        # The same degraded project still clears the dev floor (50%): the
        # gate is mode-relative, so --gate --mode dev passes (exit 0).
        rc_json, report = _score_json(
            cli, capsys, target, "--gate-mode", "dev",
        )
        assert report["overall"] is not None
        assert report["overall"] >= MODE_FLOORS["dev"]

        rc_gate = cli.run(
            [
                "--project-root", str(target), "score",
                "--gate-mode", "dev", "--gate",
            ]
        )
        capsys.readouterr()
        assert rc_gate == EXIT_SUCCESS

    def test_mode_precedence_flag_overrides_table(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        fresh_project: Path,
    ) -> None:
        """Authoring mode and caller gate policy stay independent."""
        _, report = _score_json(
            cli, capsys, fresh_project,
            "--mode", "release", "--gate-mode", "dev",
        )
        assert report["mode"] == "release"
        assert report["gate_mode"] == "dev"
        assert report["gate"]["floor"] == MODE_FLOORS["dev"]

    def test_floors_are_frozen_for_014(self) -> None:
        """Migration cannot weaken the 0.14 dev floor."""
        assert (
            MODE_FLOORS["migration"] == MODE_FLOORS["dev"]
            < MODE_FLOORS["strict"]
            < MODE_FLOORS["release"]
        )

    def test_gate_requires_caller_pinned_mode(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        fresh_project: Path,
    ) -> None:
        rc = cli.run([
            "--project-root", str(fresh_project), "score", "--gate",
        ])
        captured = capsys.readouterr()
        assert rc == 2
        assert "--gate requires --gate-mode" in captured.err

    def test_contract_kill_switch_refused_only_for_pinned_gate(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        fresh_project: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("S0MA_VERIFY_CONTRACTS", "0")
        rc_report, report = _score_json(cli, capsys, fresh_project)
        assert rc_report == EXIT_SUCCESS
        assert report["gate"]["passes"] is None

        rc_gate = cli.run([
            "--project-root", str(fresh_project), "score",
            "--gate-mode", "strict",
        ])
        captured = capsys.readouterr()
        assert rc_gate == 2
        assert "S0MA_VERIFY_CONTRACTS=0" in captured.err
