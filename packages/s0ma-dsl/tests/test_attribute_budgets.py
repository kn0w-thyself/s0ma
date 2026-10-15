"""Tests for ``ATTRIBUTE_BUDGET_VIOLATION`` and ``declares_attributes:`` budgets (M18).

The M18 milestone introduces a generalised mechanism for structural
attribute claims on nerves. A nerve may declare a list of
``<namespace>:<attribute>`` strings (HTML landmarks, HTTP routes, CSS
classes, RPC method names, anything the project author wants to model)
and the project configures budgets for those namespaces under
``[tool.s0ma.attribute_budgets]``. Three budget shapes are supported:
``exactly_one_per_page``, ``unique_in_project``, and
``warn_on_duplicate``.

The validator runs at ``s0ma check`` / ``s0ma build`` time so duplicate
landmarks (the original feedback-5.5 ask) and duplicate routes /
classes / RPC methods all surface at build time rather than runtime.
Without an ``attribute_budgets`` table, ``declares_attributes:`` is
purely descriptive — ``s0ma inspect`` shows it; nothing else fires.

These tests exercise the five scenarios from the M18 plan:

  - ``test_exactly_one_per_page_clean``
  - ``test_exactly_one_per_page_violation``
  - ``test_unique_in_project``
  - ``test_no_budget_no_check``
  - ``test_attribute_in_inspect_output``

See:
  - plans/feedback_5-6/feedback_5-6_plan.md, Milestone 18
  - plans/feedback_5-6/s0ma-dsl-feedback-5.5.md lines 1023–1061
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.ir.builder import IRBuilder
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.project import S0maProject
from s0ma_dsl.resolver.dependency import DependencyResolver, resolve_dependencies

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.nodes import S0maModule
    from s0ma_dsl.errors import S0maError

_FIXTURES = Path(__file__).parent / "fixtures" / "landmark_budget"


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
    """Run resolution against a fixture, threading attribute_budgets from the project."""
    project = S0maProject.discover(fixture_dir)
    modules, filenames = _load_project(fixture_dir)
    resolver = DependencyResolver(
        mode=mode,
        attribute_budgets=dict(project.attribute_budgets),
    )
    return resolver.resolve(modules, filenames=filenames, check_imports=False)


class TestExactlyOnePerPageClean:
    """A clean fixture with one nerve per landmark must pass strict checks."""

    def test_exactly_one_per_page_clean(self) -> None:
        """Three landmark renderers + a composer reaching all three: no violations.

        Fixture: ``exactly_one_clean/`` declares header, main, and
        footer renderers (each with ``declares_attributes:
        [landmark:<x>]``) plus a top-level ``page_composer`` that
        ``uses:`` all three. Under
        ``landmark = "exactly_one_per_page"``, every landmark string
        appears exactly once on the composer's reachable set, so no
        ``ATTRIBUTE_BUDGET_VIOLATION`` should fire.
        """
        diagnostics = _resolve_with_project(
            _FIXTURES / "exactly_one_clean", mode=StrictnessMode.STRICT,
        )
        budget = [
            d for d in diagnostics
            if d.code == "ATTRIBUTE_BUDGET_VIOLATION"
        ]
        assert budget == [], (
            f"clean fixture must produce zero attribute budget "
            f"violations; got: {[(d.code, d.message) for d in budget]}"
        )


class TestExactlyOnePerPageViolation:
    """Two nerves with the same landmark on one page must fail strict checks."""

    def test_exactly_one_per_page_violation(self) -> None:
        """Two ``landmark:nav`` declarations reachable from one composer trips the check.

        Fixture: ``exactly_one_violation/`` declares ``primary_nav``
        and ``secondary_nav`` (both ``declares_attributes:
        [landmark:nav]``) and a ``page_composer`` whose ``compose_page``
        nerve carries ``is_page_composer: true`` and ``uses:`` both.
        Under ``landmark = "exactly_one_per_page"`` this is exactly the
        fr3d M13 two-``<nav>`` regression M18 was designed to catch.

        F3 (feedback 5–6 follow-up): the diagnostic's ``page`` context
        key now identifies the composer as ``<module>.<nerve>``
        (``page_composer.compose_page``) — F3 promotes the page to
        first-class metadata on the composer nerve, so the composer
        is the page identity, not just the module.
        """
        diagnostics = _resolve_with_project(
            _FIXTURES / "exactly_one_violation",
            mode=StrictnessMode.STRICT,
        )
        budget = [
            d for d in diagnostics
            if d.code == "ATTRIBUTE_BUDGET_VIOLATION"
        ]
        assert len(budget) == 1, (
            f"expected exactly one ATTRIBUTE_BUDGET_VIOLATION; got: "
            f"{[(d.code, d.message) for d in budget]}"
        )
        err = budget[0]
        assert err.severity == "error"
        ctx = err.context
        assert ctx["namespace"] == "landmark"
        assert ctx["attribute"] == "landmark:nav"
        assert ctx["budget_shape"] == "exactly_one_per_page"
        # F3: page is identified by composer (<module>.<nerve>).
        assert ctx["page"] == "page_composer.compose_page"
        assert ctx["page_composer"] == "page_composer.compose_page"
        assert "primary_nav.render_primary_nav" in ctx["nerves"]
        assert "secondary_nav.render_secondary_nav" in ctx["nerves"]
        assert "landmark:nav" in err.message
        # Remediation must mention the budget keys an author can flip
        # if the duplication was intentional.
        assert "warn_on_duplicate" in err.remediation


class TestUniqueInProject:
    """Two nerves declaring the same route across the project must fail."""

    def test_unique_in_project(self) -> None:
        """Two nerves with ``route:GET /self`` produces an error.

        Fixture: ``unique_in_project_violation/`` declares two route
        handlers with ``declares_attributes: ["route:GET /self"]``.
        Under ``route = "unique_in_project"`` the resolver flags the
        duplicate even though there is no inter-module ``uses:`` edge
        — duplicates anywhere in the project are illegal.
        """
        diagnostics = _resolve_with_project(
            _FIXTURES / "unique_in_project_violation",
            mode=StrictnessMode.STRICT,
        )
        budget = [
            d for d in diagnostics
            if d.code == "ATTRIBUTE_BUDGET_VIOLATION"
        ]
        assert len(budget) == 1, (
            f"expected exactly one ATTRIBUTE_BUDGET_VIOLATION; got: "
            f"{[(d.code, d.message) for d in budget]}"
        )
        err = budget[0]
        assert err.severity == "error"
        ctx = err.context
        assert ctx["namespace"] == "route"
        assert ctx["attribute"] == "route:GET /self"
        assert ctx["budget_shape"] == "unique_in_project"
        assert "self_route_a.handle_self_a" in ctx["nerves"]
        assert "self_route_b.handle_self_b" in ctx["nerves"]


class TestNoBudgetNoCheck:
    """Without an attribute_budgets table, the field is purely descriptive."""

    def test_no_budget_no_check(self) -> None:
        """Same duplicate landmarks; no budget configured; zero violations.

        Fixture: ``no_budget/`` is structurally identical to the
        violation fixture (two ``landmark:nav`` declarations) but the
        ``pyproject.toml`` omits ``[tool.s0ma.attribute_budgets]``.
        The resolver must not synthesise any budget pass — the field
        is informational and projects that don't opt in are
        unaffected.
        """
        diagnostics = _resolve_with_project(
            _FIXTURES / "no_budget", mode=StrictnessMode.STRICT,
        )
        budget = [
            d for d in diagnostics
            if d.code == "ATTRIBUTE_BUDGET_VIOLATION"
        ]
        assert budget == [], (
            f"no-budget fixture must produce zero violations; got: "
            f"{[(d.code, d.message) for d in budget]}"
        )


class TestAttributeInInspectOutput:
    """``s0ma inspect`` (i.e. the IR) carries declares_attributes per nerve."""

    def test_attribute_in_inspect_output(self) -> None:
        """The IR builder serialises declares_attributes under the nerve fields.

        We exercise the IRBuilder directly (the same path
        ``s0ma inspect`` reads from) and assert the field lands in the
        emitted IR alongside the existing nerve fields. This is the
        load-bearing "machines sense their own components" property
        from the plan's guiding principles.
        """
        modules, _filenames = _load_project(_FIXTURES / "exactly_one_clean")
        builder = IRBuilder()
        page_header = modules["page_header"]
        ir = builder.build(page_header)
        # Find the render_header nerve in the IR's components.
        nerve_components = [
            c for c in ir.components if c.declaration_type == "nerve"
        ]
        assert len(nerve_components) == 1
        render_header = nerve_components[0]
        assert "declares_attributes" in render_header.fields, (
            f"declares_attributes missing from IR fields: "
            f"{render_header.fields.keys()}"
        )
        assert render_header.fields["declares_attributes"] == ["landmark:header"]


class TestAttributeBudgetSeverityModes:
    """Severity ladders with strictness mode for the error-shaped budgets.

    Pin the severity matrix entry for ``ATTRIBUTE_BUDGET_VIOLATION``:
    migration → warning, dev → error, strict → error, release → error.
    The migration warning lets authors wire things up; from dev onward
    the violation blocks the build (same precedent as
    ``CROSS_LAYER_DEPENDENCY``, mode-graduated).
    """

    @pytest.mark.parametrize(
        ("mode", "expected_severity"),
        [
            (StrictnessMode.MIGRATION, "warning"),
            (StrictnessMode.DEV, "error"),
            (StrictnessMode.STRICT, "error"),
            (StrictnessMode.RELEASE, "error"),
        ],
    )
    def test_violation_fires_with_expected_severity(
        self, mode: StrictnessMode, expected_severity: str,
    ) -> None:
        diagnostics = _resolve_with_project(
            _FIXTURES / "exactly_one_violation", mode=mode,
        )
        budget = [
            d for d in diagnostics
            if d.code == "ATTRIBUTE_BUDGET_VIOLATION"
        ]
        assert len(budget) == 1
        assert budget[0].severity == expected_severity


class TestWarnOnDuplicateShape:
    """The ``warn_on_duplicate`` shape never escalates past warning severity."""

    def test_warn_on_duplicate_emits_warning(self, tmp_path: Path) -> None:
        """A project with ``warn_on_duplicate`` emits a warning even in release.

        We synthesise the fixture inline because the fixture set above
        covers the two error-shaped budgets and the no-budget case; this
        test pins the third shape's contract to keep the matrix honest.
        """
        a = tmp_path / "self_route_a.s0ma"
        a.write_text(
            """\
module self_route_a
    layer: PRESENTATION
    version: 1.0.0
    intent: "Handler A for the warn-on-duplicate route fixture."
    exports: [handle_a]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve handle_a :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Handles GET /self via implementation A."
    expects: "No arguments."
    guarantees: "Returns a JSON-shaped string."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: ["route:GET /self"]
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    covered_by: none
    ---
    def handle_a() -> str:
        return "{}"
"""
        )
        b = tmp_path / "self_route_b.s0ma"
        b.write_text(
            """\
module self_route_b
    layer: PRESENTATION
    version: 1.0.0
    intent: "Handler B for the warn-on-duplicate route fixture."
    exports: [handle_b]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve handle_b :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Handles GET /self via implementation B."
    expects: "No arguments."
    guarantees: "Returns a JSON-shaped string."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: ["route:GET /self"]
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    covered_by: none
    ---
    def handle_b() -> str:
        return "{}"
"""
        )
        modules: dict[str, S0maModule] = {}
        filenames: dict[str, str] = {}
        for s0ma_path in sorted(tmp_path.rglob("*.s0ma")):
            source = s0ma_path.read_text(encoding="utf-8")
            module, _warnings = parse_s0ma_with_warnings(
                source, str(s0ma_path), mode=StrictnessMode.STRICT,
            )
            modules[module.module.name] = module
            filenames[module.module.name] = str(s0ma_path)
        diagnostics = resolve_dependencies(
            modules,
            mode=StrictnessMode.RELEASE,
            filenames=filenames,
            check_imports=False,
            attribute_budgets={"route": "warn_on_duplicate"},
        )
        budget = [
            d for d in diagnostics
            if d.code == "ATTRIBUTE_BUDGET_VIOLATION"
        ]
        assert len(budget) == 1
        assert budget[0].severity == "warning", (
            "warn_on_duplicate must remain a warning even in release mode"
        )


class TestUnsupportedBudgetShapeRejected:
    """``[tool.s0ma.attribute_budgets]`` rejects unknown shapes at discovery."""

    def test_unknown_shape_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            "[project]\n"
            "name = \"unknown_shape\"\n"
            "version = \"0.0.1\"\n"
            "\n"
            "[tool.s0ma]\n"
            "source_roots = [\"src\"]\n"
            "\n"
            "[tool.s0ma.attribute_budgets]\n"
            "landmark = \"made_up_shape\"\n"
        )
        with pytest.raises(ValueError) as excinfo:
            S0maProject.discover(tmp_path)
        msg = str(excinfo.value)
        assert "made_up_shape" in msg
        # The error must enumerate the supported set so the author can fix it.
        assert "exactly_one_per_page" in msg
        assert "unique_in_project" in msg
        assert "warn_on_duplicate" in msg


class TestParserRejectsMalformedAttributes:
    """The parser refuses entries that lack the ``<namespace>:<attribute>`` shape."""

    def test_missing_colon_rejected(self, tmp_path: Path) -> None:
        s0ma = tmp_path / "bad.s0ma"
        s0ma.write_text(
            """\
module bad
    layer: PRESENTATION
    version: 1.0.0
    intent: "Fixture with a malformed declares_attributes entry."
    exports: [render]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve render :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Tries to declare an attribute without a namespace."
    expects: "Nothing."
    guarantees: "Should fail to parse."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: [header]
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    covered_by: none
    ---
    def render() -> str:
        return "<header/>"
"""
        )
        from s0ma_dsl.errors import S0maParseError
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma_with_warnings(
                s0ma.read_text(encoding="utf-8"),
                str(s0ma),
                mode=StrictnessMode.STRICT,
            )
        assert "namespace" in str(excinfo.value).lower() or \
               "<namespace>:<attribute>" in str(excinfo.value)
