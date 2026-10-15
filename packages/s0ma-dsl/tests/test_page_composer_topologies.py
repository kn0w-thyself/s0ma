"""F3 stress tests: explicit ``is_page_composer:`` field across topologies.

F3 (feedback 5–6 follow-up) replaces M18's heuristic page-composer
detection ("top-level module in the ``uses:`` graph") with an explicit
``is_page_composer: true`` field on nerves. The validator only walks
``exactly_one_per_page`` budget rules from explicitly-marked nerves;
if no nerve is marked but the budget is configured, the resolver
emits ``NO_PAGE_COMPOSER_DECLARED`` (error in every mode).

These tests exercise the topologies the M18 heuristic mishandled:

  - ``test_two_pages_share_subcomponent`` — two composers each
    consuming a shared header; budget satisfied per page.
  - ``test_test_module_not_a_page`` — a test harness with ``uses:`` to
    production modules; no marker → no false-positive page.
  - ``test_no_uses_edges_only_marked_nerves_count`` — every nerve
    independent; no marker → ``NO_PAGE_COMPOSER_DECLARED``.
  - ``test_circular_graph_with_explicit_page`` — A → B → C → A; the
    walker terminates correctly via the seen-set guard.
  - ``test_no_page_composer_declared_errors`` — pure
    ``NO_PAGE_COMPOSER_DECLARED`` shape.
  - ``test_explicit_page_composer_drives_budget`` — pinning the
    explicit-only contract: marking a nerve scopes the budget,
    nothing else does.
  - ``test_inspect_shows_page_composer_flag`` — pinning the
    ``s0ma inspect`` rendering of the marker.

See:
  - plans/5-6_follow-up_plan.md, Milestone F3
  - plans/5-6_deviations.md (M18 deviations)
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.ir.builder import IRBuilder
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.project import S0maProject
from s0ma_dsl.resolver.dependency import DependencyResolver
from s0ma_dsl.semantic.attribute_budgets import check_attribute_budgets

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.nodes import S0maModule
    from s0ma_dsl.errors import S0maError

_FIXTURES = Path(__file__).parent / "fixtures" / "page_composer_topologies"


def _load_project(fixture_dir: Path) -> tuple[
    dict[str, S0maModule], dict[str, str]
]:
    """Parse every ``.s0ma`` file under ``fixture_dir/src/``."""
    modules: dict[str, S0maModule] = {}
    filenames: dict[str, str] = {}
    for s0ma_path in sorted((fixture_dir / "src").rglob("*.s0ma")):
        source = s0ma_path.read_text(encoding="utf-8")
        module, _warnings = parse_s0ma_with_warnings(
            source, str(s0ma_path), mode=StrictnessMode.STRICT,
        )
        modules[module.module.name] = module
        filenames[module.module.name] = str(s0ma_path)
    return modules, filenames


def _resolve_with_project(
    fixture_dir: Path, mode: StrictnessMode = StrictnessMode.STRICT,
) -> list[S0maError]:
    """Run resolution against a fixture, threading attribute_budgets."""
    project = S0maProject.discover(fixture_dir)
    modules, filenames = _load_project(fixture_dir)
    resolver = DependencyResolver(
        mode=mode,
        attribute_budgets=dict(project.attribute_budgets),
    )
    return resolver.resolve(modules, filenames=filenames, check_imports=False)


class TestExplicitPageComposerDrivesBudget:
    """The explicit ``is_page_composer:`` field is the only signal the budget consults."""

    def test_explicit_page_composer_drives_budget(self) -> None:
        """A nerve marked ``is_page_composer: true`` scopes the budget.

        We pick the ``two_pages_shared_subcomponent`` fixture because it
        has two explicitly-marked composers and the per-page budget
        must hold for each independently. The clean-fixture assertion
        (zero violations) is the load-bearing contract: marking a nerve
        works as a scope root; nothing else does.
        """
        diagnostics = _resolve_with_project(
            _FIXTURES / "two_pages_shared_subcomponent",
            mode=StrictnessMode.STRICT,
        )
        budget = [
            d for d in diagnostics
            if d.code == "ATTRIBUTE_BUDGET_VIOLATION"
        ]
        no_composer = [
            d for d in diagnostics
            if d.code == "NO_PAGE_COMPOSER_DECLARED"
        ]
        assert budget == [], (
            f"two-pages-shared-subcomponent must have zero "
            f"ATTRIBUTE_BUDGET_VIOLATION; got: "
            f"{[(d.code, d.message) for d in budget]}"
        )
        assert no_composer == [], (
            "two-pages-shared-subcomponent has two marked composers; "
            "NO_PAGE_COMPOSER_DECLARED must not fire."
        )


class TestNoPageComposerDeclaredErrors:
    """Budget configured but no nerve marked → loud project-level error."""

    def test_no_page_composer_declared_errors(self) -> None:
        """``no_marked_nerve/`` is the canonical NO_PAGE_COMPOSER_DECLARED case.

        One module, one nerve, one budget, no marker. Resolver emits
        exactly one ``NO_PAGE_COMPOSER_DECLARED`` and zero
        ``ATTRIBUTE_BUDGET_VIOLATION`` (because no per-page walk
        happens when the project has no composers).
        """
        diagnostics = _resolve_with_project(
            _FIXTURES / "no_marked_nerve",
            mode=StrictnessMode.STRICT,
        )
        no_composer = [
            d for d in diagnostics
            if d.code == "NO_PAGE_COMPOSER_DECLARED"
        ]
        budget = [
            d for d in diagnostics
            if d.code == "ATTRIBUTE_BUDGET_VIOLATION"
        ]
        assert len(no_composer) == 1
        err = no_composer[0]
        assert err.severity == "error"
        assert "is_page_composer" in err.message or \
               "is_page_composer" in err.remediation
        assert "landmark" in err.message
        assert err.context["budgeted_namespaces"] == ["landmark"]
        # The per-page walker must not run when no composer exists —
        # otherwise NO_PAGE_COMPOSER_DECLARED would be redundant.
        assert budget == []

    def test_no_page_composer_declared_errors_in_every_mode(self) -> None:
        """The diagnostic is ``error`` in every mode (matrix entry pin)."""
        for mode in StrictnessMode:
            diagnostics = _resolve_with_project(
                _FIXTURES / "no_marked_nerve", mode=mode,
            )
            no_composer = [
                d for d in diagnostics
                if d.code == "NO_PAGE_COMPOSER_DECLARED"
            ]
            assert len(no_composer) == 1, (
                f"NO_PAGE_COMPOSER_DECLARED must fire in mode {mode!r}; "
                f"got: {diagnostics}"
            )
            assert no_composer[0].severity == "error", (
                f"NO_PAGE_COMPOSER_DECLARED must be error in mode "
                f"{mode!r}; got severity {no_composer[0].severity!r}"
            )


class TestTwoPagesShareSubcomponent:
    """Two composers reaching the same shared subcomponent — both pages valid."""

    def test_two_pages_share_subcomponent(self) -> None:
        """Each composer's reachable set has exactly one ``landmark:header``.

        Both composers ``uses:`` the same ``shared_header`` module. From
        ``home_page``'s perspective the reachable set is
        ``{home_page, shared_header}`` → one ``landmark:header``.
        Same for ``about_page``. Budget satisfied for both. The
        ``unique_in_project`` shape would have flagged the shared
        header (one project-wide occurrence is OK; the test verifies
        the per-page interpretation, not the project-wide one).
        """
        diagnostics = _resolve_with_project(
            _FIXTURES / "two_pages_shared_subcomponent",
            mode=StrictnessMode.STRICT,
        )
        violations = [
            d for d in diagnostics
            if d.code in (
                "ATTRIBUTE_BUDGET_VIOLATION",
                "NO_PAGE_COMPOSER_DECLARED",
            )
        ]
        assert violations == [], (
            f"two-page-shared-subcomponent must produce zero "
            f"attribute-budget diagnostics; got: "
            f"{[(d.code, d.message) for d in violations]}"
        )


class TestTestModuleNotAPage:
    """A test harness with ``uses:`` to production isn't flagged as a page."""

    def test_test_module_not_a_page(self) -> None:
        """No nerve marked → no per-page walk; project-level error fires.

        The ``test_harness`` module has ``uses:`` to ``page_a`` and
        ``page_b`` (each declaring ``landmark:header``). Pre-F3, the
        heuristic would have flagged ``test_harness`` as a top-level
        page (no other module references it) and emitted a per-page
        violation for the two ``landmark:header`` declarations.
        Post-F3, no nerve is marked so ``NO_PAGE_COMPOSER_DECLARED``
        fires instead — the loud project-level error replaces the
        previous false-positive.
        """
        diagnostics = _resolve_with_project(
            _FIXTURES / "test_module_not_a_page",
            mode=StrictnessMode.STRICT,
        )
        # The expected post-F3 diagnostic: NO_PAGE_COMPOSER_DECLARED.
        no_composer = [
            d for d in diagnostics
            if d.code == "NO_PAGE_COMPOSER_DECLARED"
        ]
        assert len(no_composer) == 1
        # The pre-F3 false-positive must NOT fire, because we never
        # walk anything as a page.
        budget = [
            d for d in diagnostics
            if d.code == "ATTRIBUTE_BUDGET_VIOLATION"
        ]
        assert budget == [], (
            "F3 must not flag the test harness as a page; got "
            f"unexpected ATTRIBUTE_BUDGET_VIOLATION(s): "
            f"{[(d.code, d.message) for d in budget]}"
        )


class TestNoUsesEdgesOnlyMarkedNervesCount:
    """No inter-module ``uses:`` and no markers → only NO_PAGE_COMPOSER_DECLARED."""

    def test_no_uses_edges_only_marked_nerves_count(self) -> None:
        """Pre-F3 the heuristic flagged every isolated module; F3 doesn't.

        Three independent modules, each declaring a different landmark
        (``landmark:header``, ``landmark:main``, ``landmark:footer``).
        Pre-F3 the heuristic flagged every one of them as a top-level
        page (none referenced anywhere) and would have emitted three
        per-page violations (each page reaches its own landmark only,
        so actually no violations would have fired in this exact
        configuration — but the M18 heuristic's behavior on isolated
        modules was opaque). Post-F3, the explicit-only logic emits
        ``NO_PAGE_COMPOSER_DECLARED`` because no nerve carries the
        marker. The author then has to mark the real composer or
        change the budget shape — the failure mode is loud and
        actionable.
        """
        diagnostics = _resolve_with_project(
            _FIXTURES / "no_uses_edges_isolated_nerves",
            mode=StrictnessMode.STRICT,
        )
        no_composer = [
            d for d in diagnostics
            if d.code == "NO_PAGE_COMPOSER_DECLARED"
        ]
        assert len(no_composer) == 1, (
            "no-uses-edges-isolated-nerves must produce exactly one "
            "NO_PAGE_COMPOSER_DECLARED; got: "
            f"{[(d.code, d.message) for d in no_composer]}"
        )


class TestCircularGraphWithExplicitPage:
    """A → B → C → A; one nerve marked. Walker terminates and walks correctly."""

    def test_circular_graph_with_explicit_page(self) -> None:
        """The budget walker handles cycles via the ``seen`` set.

        The s0ma-dsl resolver's cycle-detection phase (Phase 1) bails
        out on circular graphs before reaching attribute-budget
        enforcement; that path is exercised by the cycle-detection
        tests elsewhere. F3's contribution to the cyclic case is
        guaranteeing the budget walker terminates if it ever sees a
        cyclic input — call ``check_attribute_budgets`` directly here
        to bypass Phase 1 and verify the walker (a) terminates and
        (b) walks every reachable nerve exactly once via the ``seen``
        set in ``_reachable_modules``.
        """
        modules, filenames = _load_project(_FIXTURES / "circular_uses_graph")
        diagnostics = check_attribute_budgets(
            modules,
            attribute_budgets={"landmark": "exactly_one_per_page"},
            mode=StrictnessMode.STRICT,
            filenames=filenames,
        )
        # ``cycle_a`` is the only marker. From its module, the walker
        # reaches B and C exactly once (cycle terminated by the seen
        # set). The reachable nerves declare three distinct landmark
        # attributes (header, main, footer) — each appears exactly
        # once in the per-page set. Budget satisfied.
        violations = [
            d for d in diagnostics
            if d.code in (
                "ATTRIBUTE_BUDGET_VIOLATION",
                "NO_PAGE_COMPOSER_DECLARED",
            )
        ]
        assert violations == [], (
            "Circular graph with one explicit page composer must "
            "produce zero budget diagnostics — each landmark appears "
            "exactly once in the reachable set. Got: "
            f"{[(d.code, d.message) for d in violations]}"
        )


class TestInspectShowsPageComposerFlag:
    """Marked nerves render with the ``page_composer`` flag in the inspect label."""

    def test_inspect_shows_page_composer_flag(self) -> None:
        """``s0ma inspect`` text output flags marked nerves visibly.

        Build the IR for ``home_page`` (a marked composer) and feed it
        through the CLI's ``_print_inspect_text``. The component's
        bracket label must include ``page_composer`` so the role is
        visible at a glance, alongside the existing
        ``[PUBLIC FUNCTION nerve]`` triplet.
        """
        modules, _filenames = _load_project(
            _FIXTURES / "two_pages_shared_subcomponent"
        )
        builder = IRBuilder()
        ir = builder.build(modules["home_page"])
        # Convert the IR to the dict shape ``_print_inspect_text``
        # expects (the same shape ``s0ma inspect`` reads from JSON).
        ir_dict = json.loads(json.dumps(ir, default=lambda o: o.__dict__))

        cli = S0maCLI()
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._print_inspect_text(ir_dict)
        output = buf.getvalue()

        # The marked composer's label must include "page_composer".
        assert "page_composer" in output, (
            f"Expected 'page_composer' flag in inspect output; got:\n"
            f"{output}"
        )
        # The label is appended to the existing label triplet — the
        # full triplet must still be present.
        assert "PUBLIC FUNCTION nerve" in output

    def test_unmarked_nerve_lacks_page_composer_flag(self) -> None:
        """Sanity check: an unmarked nerve does not get the flag.

        The shared header module's nerve is unmarked. Its inspect
        label must NOT include ``page_composer`` — otherwise the flag
        would be misleading.
        """
        modules, _filenames = _load_project(
            _FIXTURES / "two_pages_shared_subcomponent"
        )
        builder = IRBuilder()
        ir = builder.build(modules["shared_header"])
        ir_dict = json.loads(json.dumps(ir, default=lambda o: o.__dict__))

        cli = S0maCLI()
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._print_inspect_text(ir_dict)
        output = buf.getvalue()

        assert "page_composer" not in output, (
            f"Unmarked nerve should not show 'page_composer' flag; "
            f"got:\n{output}"
        )


class TestParserAcceptsIsPageComposerFalse:
    """``is_page_composer: false`` is accepted and equivalent to omitting it."""

    def test_explicit_false_parses_and_does_not_mark(self, tmp_path: Path) -> None:
        s0ma = tmp_path / "explicit_false.s0ma"
        s0ma.write_text(
            "module explicit_false\n"
            "    layer: PRESENTATION\n"
            "    version: 1.0.0\n"
            "    intent: \"Verifies that is_page_composer: false is accepted.\"\n"
            "    exports: [render]\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "\n"
            "nerve render :: PRESENTATION\n"
            "    kind: FUNCTION\n"
            "    visibility: PUBLIC\n"
            "    intent: \"Render with explicit false marker.\"\n"
            "    expects: \"Nothing.\"\n"
            "    guarantees: \"Returns a string.\"\n"
            "    forbids: none\n"
            "    evaluates_at: FUNCTION_BOUNDARY\n"
            "    provides: none\n"
            "    returns: none\n"
            "    raises: none\n"
            "    interface: none\n"
            "    latency_ms: none\n"
            "    depends_on: none\n"
            "    internal: none\n"
            "    expected_exceptions: none\n"
            "    consumes_via_dict: none\n"
            "    declares_attributes: none\n"
            "    covered_by: none\n"
            "    is_page_composer: false\n"
            "    ---\n"
            "    def render() -> str:\n"
            "        return \"<header/>\"\n"
        )
        module, _warnings = parse_s0ma_with_warnings(
            s0ma.read_text(encoding="utf-8"),
            str(s0ma),
            mode=StrictnessMode.STRICT,
        )
        nerve = module.nerves[0]
        assert nerve.is_page_composer is False
