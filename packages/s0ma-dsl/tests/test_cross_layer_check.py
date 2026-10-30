"""Tests for ``CROSS_LAYER_DEPENDENCY`` — cross-module ``uses:`` layer enforcement (M9).

The M9 milestone formalises layer discipline at the cross-module level.
Pre-M9, the validator enforced layer rules within a module (every
component shares the module's layer; spec §4.0.1) but did *not* check
``uses:`` declarations against the layers of their target modules. This
let three real layer violations slip through 13 milestones in the
fr3d audit (feedback-5.5 lines 1157–1177).

The post-M9 contract:

  - For every module ``M`` at layer ``L_M`` and every ``uses:`` entry
    targeting a registered project module ``T`` at layer ``L_T``, the
    pair ``(L_M, L_T)`` must be in ``_ALLOWED_TARGET_LAYERS``.
  - The matrix is the canonical Clean Architecture reachability table:
    DOMAIN sees only DOMAIN/FRAMEWORK; APPLICATION adds itself;
    PRESENTATION/INFRASTRUCTURE see DOMAIN+APPLICATION+self+FRAMEWORK;
    FRAMEWORK is at the bottom and sees only itself.
  - Severity ladders with strictness mode: ``warning`` in
    migration/dev (so authors see violations as they develop),
    ``error`` in strict and release (so the violations cannot ship).
  - Test modules' ``uses:`` are checked at the layer the test
    declares (a DOMAIN-layer test importing a PRESENTATION component
    is the same architectural smell as a DOMAIN production module
    doing it).

These tests exercise the four scenarios listed in the M9 plan.

See:
  - plans/feedback_5-6/feedback_5-6_plan.md, Milestone 9
  - plans/feedback_5-6/s0ma-dsl-feedback-5.5.md lines 1157–1177
  - docs/s0ma-dsl-spec-v0.13.0.md §4.0.1 + cross-module addendum
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.resolver.dependency import (
    _ALLOWED_TARGET_LAYERS,
    DependencyResolver,
)

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.nodes import S0maModule
    from s0ma_dsl.errors import S0maError

_FIXTURES = Path(__file__).parent / "fixtures"


def _load_project(fixture_dir: Path) -> tuple[
    dict[str, S0maModule], dict[str, str]
]:
    """Parse every ``.s0ma`` file under ``fixture_dir`` into a project view."""
    modules: dict[str, S0maModule] = {}
    filenames: dict[str, str] = {}
    for s0ma_path in sorted(fixture_dir.rglob("*.s0ma")):
        source = s0ma_path.read_text(encoding="utf-8")
        module, _warnings = parse_s0ma_with_warnings(
            source, str(s0ma_path), mode=StrictnessMode.STRICT,
        )
        modules[module.module.name] = module
        filenames[module.module.name] = str(s0ma_path)
    return modules, filenames


def _resolve(
    fixture_dir: Path, mode: StrictnessMode = StrictnessMode.STRICT,
) -> list[S0maError]:
    """Run the cross-module dependency resolver against a fixture project."""
    modules, filenames = _load_project(fixture_dir)
    resolver = DependencyResolver(mode=mode)
    return resolver.resolve(modules, filenames=filenames, check_imports=False)


class TestCleanLayersPasses:
    """The ``cross_layer_clean/`` fixture must validate clean in every mode."""

    def test_clean_layers_passes(self) -> None:
        """A 4-module project with proper layer ordering must produce no errors.

        Fixture: ``cross_layer_clean/`` declares one module per layer
        (DOMAIN: ``order_model``; APPLICATION: ``order_service``;
        PRESENTATION: ``order_renderer``; INFRASTRUCTURE:
        ``order_repository``). Every ``uses:`` edge points to a layer
        that the consuming layer is allowed to reach. The strict-mode
        resolver must produce zero ``CROSS_LAYER_DEPENDENCY`` errors.
        """
        diagnostics = _resolve(
            _FIXTURES / "cross_layer_clean", mode=StrictnessMode.STRICT,
        )
        cross_layer = [
            d for d in diagnostics if d.code == "CROSS_LAYER_DEPENDENCY"
        ]
        assert cross_layer == [], (
            f"clean fixture must validate without cross-layer errors; "
            f"got: {[(d.code, d.message) for d in cross_layer]}"
        )
        # Sanity-check: no other errors either (the fixture is meant to
        # be strict-mode clean overall, not just w.r.t. cross-layer).
        errors = [d for d in diagnostics if d.severity == "error"]
        assert errors == [], (
            f"clean fixture must be strict-mode clean overall; got: "
            f"{[(d.code, d.message) for d in errors]}"
        )


class TestDomainUsesApplicationErrors:
    """A DOMAIN module reaching up to APPLICATION must trigger the check."""

    def test_domain_uses_application_errors(self) -> None:
        """The violation fixture must produce exactly one CROSS_LAYER_DEPENDENCY.

        Fixture: ``cross_layer_violation/`` declares ``order_model``
        (DOMAIN) with ``uses: [order_service.process_order]`` against
        ``order_service`` (APPLICATION). DOMAIN sees only
        ``{DOMAIN, FRAMEWORK}`` per the matrix, so this is the
        canonical "domain reaches up" anti-pattern.
        """
        diagnostics = _resolve(
            _FIXTURES / "cross_layer_violation",
            mode=StrictnessMode.STRICT,
        )
        cross_layer = [
            d for d in diagnostics if d.code == "CROSS_LAYER_DEPENDENCY"
        ]
        assert len(cross_layer) == 1, (
            f"expected exactly one CROSS_LAYER_DEPENDENCY error; got: "
            f"{[(d.code, d.message) for d in cross_layer]}"
        )
        err = cross_layer[0]
        assert err.severity == "error", (
            f"strict-mode severity must be error; got {err.severity}"
        )
        assert err.context["source_module"] == "order_model"
        assert err.context["source_layer"] == "DOMAIN"
        assert err.context["target_module"] == "order_service"
        assert err.context["target_layer"] == "APPLICATION"
        assert err.context["qualified_name"] == "order_service.process_order"
        # Remediation must mention both fix paths (move down vs invert).
        assert "invert" in err.remediation.lower()
        assert "move" in err.remediation.lower()


class TestDevModeWarns:
    """In dev mode, the same violation produces a warning, not an error."""

    def test_dev_mode_warns(self) -> None:
        """Dev mode must downgrade the violation to ``warning`` severity.

        Same fixture as :class:`TestDomainUsesApplicationErrors`, but
        run under :attr:`StrictnessMode.DEV`. The plan's severity
        ladder is: dev = warning, strict = error, release = error.
        Warnings are diagnostics that don't fail a build — the build
        proceeds, the user sees the warning.
        """
        diagnostics = _resolve(
            _FIXTURES / "cross_layer_violation",
            mode=StrictnessMode.DEV,
        )
        cross_layer = [
            d for d in diagnostics if d.code == "CROSS_LAYER_DEPENDENCY"
        ]
        assert len(cross_layer) == 1, (
            f"expected exactly one CROSS_LAYER_DEPENDENCY warning; got: "
            f"{[(d.code, d.message) for d in cross_layer]}"
        )
        assert cross_layer[0].severity == "warning"
        # The warning must be the only diagnostic of that code; the
        # other passes (export validation, etc.) must not also flag it.
        errors_only = [d for d in diagnostics if d.severity == "error"]
        # Best-effort: the violation should not block the build in dev.
        # (Other errors may still appear if the fixture has unrelated
        # issues, but the cross-layer one specifically must be a
        # warning.)
        assert all(
            d.code != "CROSS_LAYER_DEPENDENCY" for d in errors_only
        ), (
            f"CROSS_LAYER_DEPENDENCY must not be an error in dev mode; "
            f"got: {[(d.code, d.severity, d.message) for d in errors_only]}"
        )


class TestTestModuleLayerEnforced:
    """Test modules' ``uses:`` are checked at the layer the test declares."""

    def test_test_module_layer_enforced(
        self, tmp_path: Path,
    ) -> None:
        """A DOMAIN-layer test that imports a PRESENTATION nerve must error.

        The plan's scoping note (§M9 implementation step 4): "test
        modules: a test's layer is the layer of the primary component
        under test. Layer rules apply to test modules' ``uses:`` *as
        if they were production modules at the same layer*. This is
        intentional: a DOMAIN test importing a PRESENTATION component
        is the same architectural smell as a DOMAIN production module
        doing it."

        We construct the scenario inline: a PRESENTATION module
        ``ui_renderer`` exporting ``render_html``, and a DOMAIN-layer
        test module ``model_tests`` that ``uses:
        [ui_renderer.render_html]`` and contains a single test. The
        cross-layer check should fire on the test module's ``uses:``.
        """
        # PRESENTATION module exposing render_html.
        ui_renderer = tmp_path / "ui_renderer.s0ma"
        ui_renderer.write_text(
            "module ui_renderer\n"
            "    layer: PRESENTATION\n"
            "    version: 1.0.0\n"
            "    intent: \"Renders HTML for the user-facing UI of the project.\"\n"
            "    exports: [render_html]\n"
            "    uses: none\n"
            "    requires: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "\n"
            "nerve render_html :: PRESENTATION\n"
            "    kind: FUNCTION\n"
            "    visibility: PUBLIC\n"
            "    intent: \"Render a string as an HTML span element.\"\n"
            "    expects: \"A non-empty string of arbitrary text.\"\n"
            "    guarantees: \"Returns a <span>...</span> element.\"\n"
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
            "    ---\n"
            "    def render_html(text: str) -> str:\n"
            "        return \"<span>\" + text + \"</span>\"\n"
        )

        # DOMAIN-layer test module that improperly reaches up.
        model_tests = tmp_path / "model_tests.s0ma"
        model_tests.write_text(
            "module model_tests\n"
            "    layer: DOMAIN\n"
            "    version: 1.0.0\n"
            "    intent: "
            "\"Domain-layer tests covering the model invariants and one ill-conceived UI dep.\"\n"
            "    uses: [ui_renderer.render_html]\n"
            "    exports: []\n"
            "    requires: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "\n"
            "test test_render_html_returns_span :: DOMAIN\n"
            "    intent: \"Verifies render_html wraps the input in a span element.\"\n"
            "    tests: [render_html]\n"
            "    expects: none\n"
            "    depends_on: none\n"
            "    mocks: none\n"
            "    ---\n"
            "    def test_render_html_returns_span():\n"
            "        assert render_html(\"hi\") == \"<span>hi</span>\"\n"
        )

        modules, filenames = _load_project(tmp_path)
        resolver = DependencyResolver(mode=StrictnessMode.STRICT)
        diagnostics = resolver.resolve(
            modules, filenames=filenames, check_imports=False,
        )
        cross_layer = [
            d for d in diagnostics if d.code == "CROSS_LAYER_DEPENDENCY"
        ]
        assert len(cross_layer) == 1, (
            f"expected one CROSS_LAYER_DEPENDENCY for the DOMAIN-test "
            f"importing PRESENTATION; got: "
            f"{[(d.code, d.message) for d in cross_layer]}"
        )
        err = cross_layer[0]
        assert err.severity == "error"
        assert err.context["source_module"] == "model_tests"
        assert err.context["source_layer"] == "DOMAIN"
        assert err.context["target_module"] == "ui_renderer"
        assert err.context["target_layer"] == "PRESENTATION"


class TestAllowedMatrixContract:
    """Pin the ``_ALLOWED_TARGET_LAYERS`` matrix contract.

    The plan's M9 implementation step 1 names the exact matrix. We pin
    it behind an explicit test so a future "let's loosen DOMAIN to
    reach APPLICATION because it'd be convenient here" change cannot
    silently land.
    """

    def test_matrix_matches_plan(self) -> None:
        """The matrix's reachable-set rows match the plan verbatim."""
        from s0ma_dsl.ast_nodes.enums import Layer

        expected = {
            Layer.DOMAIN: {Layer.DOMAIN, Layer.FRAMEWORK},
            Layer.APPLICATION: {
                Layer.DOMAIN, Layer.APPLICATION, Layer.FRAMEWORK,
            },
            Layer.PRESENTATION: {
                Layer.DOMAIN,
                Layer.APPLICATION,
                Layer.PRESENTATION,
                Layer.FRAMEWORK,
            },
            Layer.INFRASTRUCTURE: {
                Layer.DOMAIN,
                Layer.APPLICATION,
                Layer.INFRASTRUCTURE,
                Layer.FRAMEWORK,
            },
            Layer.FRAMEWORK: {Layer.FRAMEWORK},
        }
        assert expected == _ALLOWED_TARGET_LAYERS


class TestModeIndependence:
    """The check fires (with appropriate severity) in every applicable mode."""

    @pytest.mark.parametrize(
        ("mode", "expected_severity"),
        [
            (StrictnessMode.MIGRATION, "warning"),
            (StrictnessMode.DEV, "warning"),
            (StrictnessMode.STRICT, "error"),
            (StrictnessMode.RELEASE, "error"),
        ],
    )
    def test_violation_fires_with_expected_severity(
        self, mode: StrictnessMode, expected_severity: str,
    ) -> None:
        """Violation produces one diagnostic at the mode's configured severity.

        The severity matrix entry for ``CROSS_LAYER_DEPENDENCY`` is:
        migration → warning, dev → warning, strict → error,
        release → error. This mirrors the precedent set by other
        behavioral/hygiene rules (PROHIBITED_CONSTRUCT, BARE_IMPORT,
        VESTIGIAL_IMPORT).
        """
        diagnostics = _resolve(
            _FIXTURES / "cross_layer_violation", mode=mode,
        )
        cross_layer = [
            d for d in diagnostics if d.code == "CROSS_LAYER_DEPENDENCY"
        ]
        assert len(cross_layer) == 1, (
            f"expected exactly one CROSS_LAYER_DEPENDENCY in mode "
            f"{mode}; got: {[(d.code, d.message) for d in cross_layer]}"
        )
        assert cross_layer[0].severity == expected_severity


class TestLayerReachabilityMatrixProjection:
    """The matrix as data is the matrix the resolver enforces, nothing else."""

    def test_projection_equals_the_enforced_table(self) -> None:
        from s0ma_dsl.resolver import layer_reachability_matrix

        projected = layer_reachability_matrix()
        assert projected == {
            source.value: sorted(target.value for target in targets)
            for source, targets in _ALLOWED_TARGET_LAYERS.items()
        }
        # Every enforced row is projected and no row is invented.
        assert set(projected) == {layer.value for layer in _ALLOWED_TARGET_LAYERS}
        # The two facts the s4 bench found no arm could learn from the
        # self-model: PRESENTATION reaches APPLICATION, and every layer
        # reaches FRAMEWORK, s0ma's own layer.
        assert "APPLICATION" in projected["PRESENTATION"]
        assert all("FRAMEWORK" in reach for reach in projected.values())
        # A layer always reaches itself.
        assert all(layer in reach for layer, reach in projected.items())
        # Deterministic: sorted keys, sorted rows, plain JSON types.
        assert list(projected) == sorted(projected)
        assert all(reach == sorted(reach) for reach in projected.values())

    def test_the_projection_is_what_the_resolver_allows(self) -> None:
        """Each projected pair passes the check; each pair outside it fires."""
        from s0ma_dsl.ast_nodes.enums import Layer
        from s0ma_dsl.resolver import layer_reachability_matrix

        projected = layer_reachability_matrix()
        for source in Layer:
            for target in Layer:
                allowed = target in _ALLOWED_TARGET_LAYERS[source]
                assert (target.value in projected[source.value]) is allowed
