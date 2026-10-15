"""Tests for ``[tool.s0ma].test_layering`` opt-in (M-10 / POST-6).

Pre-0.16.0, the cross-module layer-reachability check (spec §4.0.2)
fired ``CROSS_LAYER_DEPENDENCY`` for every module's ``uses:`` entries
whose target was outside the reachable-layer matrix — including
test-context modules. This produced persistent warning noise in
projects whose tests routinely instantiated higher-layer services
(e.g. PRESENTATION test fixtures wiring INFRASTRUCTURE adapters,
DOMAIN tests reaching APPLICATION).

The M-10 milestone introduces a project-level opt-in:

  - ``[tool.s0ma].test_layering = "strict"`` (default) preserves the
    pre-0.16.0 behaviour: every module's ``uses:`` entries are checked
    against the cross-layer matrix.
  - ``[tool.s0ma].test_layering = "permissive"`` exempts modules with
    at least one ``test`` declaration from the cross-layer check.
    Production modules (zero ``test`` declarations) still get the
    strict check regardless of the opt-in.

The carve-out trigger ("module has ≥1 test declaration") mirrors the
M13 helper-access rule (``HELPER_PRIVATE_TO_MODULE``); a module that
mixes production code and test declarations counts as test-context
under both rules.

See:
  - plans/post-phase2/post-phase2_implementation_plan.md, M-10
  - docs/s0ma-dsl-spec-v0.16.0.md §4.13 + §4.0.2
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl import S0maProject
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.resolver.dependency import DependencyResolver

if TYPE_CHECKING:
    from pathlib import Path

    from s0ma_dsl.ast_nodes.nodes import S0maModule
    from s0ma_dsl.errors import S0maError


# ---------------------------------------------------------------------------
# Fixture authoring helpers
# ---------------------------------------------------------------------------


_UI_RENDERER_S0MA = dedent("""\
module ui_renderer
    layer: PRESENTATION
    version: 1.0.0
    intent: "Renders HTML for the user-facing UI of the project."
    exports: [render_html]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve render_html :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Render a string as an HTML span element."
    expects: "A non-empty string of arbitrary text."
    guarantees: "Returns a <span>...</span> element."
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
    def render_html(text: str) -> str:
        return "<span>" + text + "</span>"
""").lstrip()


_DOMAIN_TEST_MODULE_S0MA = dedent("""\
module model_tests
    layer: DOMAIN
    version: 1.0.0
    intent: "Domain-layer tests that improperly reach up into PRESENTATION via uses:."
    uses: [ui_renderer.render_html]
    exports: []

    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
test test_render_html_returns_span :: DOMAIN
    intent: "Verifies render_html wraps the input in a span element."
    tests: [render_html]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_render_html_returns_span():
        assert render_html("hi") == "<span>hi</span>"
""").lstrip()


_DOMAIN_PRODUCTION_MODULE_S0MA = dedent("""\
module model_consumer
    layer: DOMAIN
    version: 1.0.0
    intent: "Production DOMAIN module that improperly reaches up into PRESENTATION."
    uses: [ui_renderer.render_html]
    exports: [build_label]

    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve build_label :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Builds a label by delegating to render_html."
    expects: "A non-empty label string."
    guarantees: "Returns the HTML-wrapped label."
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
    def build_label(text: str) -> str:
        return render_html(text)
""").lstrip()


def _write_modules(tmp_path: Path, sources: dict[str, str]) -> None:
    """Materialise *sources* under *tmp_path* (name → body)."""
    for name, body in sources.items():
        (tmp_path / f"{name}.s0ma").write_text(body, encoding="utf-8")


def _load_project(fixture_dir: Path) -> tuple[
    dict[str, S0maModule], dict[str, str]
]:
    """Parse every ``.s0ma`` file under *fixture_dir*."""
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
    fixture_dir: Path,
    *,
    mode: StrictnessMode = StrictnessMode.STRICT,
    test_layering: str = "strict",
) -> list[S0maError]:
    """Run the resolver against the fixture project."""
    modules, filenames = _load_project(fixture_dir)
    resolver = DependencyResolver(
        mode=mode, test_layering=test_layering,
    )
    return resolver.resolve(modules, filenames=filenames, check_imports=False)


def _cross_layer_only(diagnostics: list[S0maError]) -> list[S0maError]:
    """Return the subset of diagnostics with code CROSS_LAYER_DEPENDENCY."""
    return [d for d in diagnostics if d.code == "CROSS_LAYER_DEPENDENCY"]


# ---------------------------------------------------------------------------
# Strict mode (default) still fires
# ---------------------------------------------------------------------------


class TestStrictModeStillFires:
    """The default ``"strict"`` value preserves pre-0.16.0 behaviour."""

    def test_default_strict_fires_for_test_module(
        self, tmp_path: Path,
    ) -> None:
        """A DOMAIN-layer test module reaching PRESENTATION still errors.

        Default ``test_layering`` is ``"strict"`` — every module's
        ``uses:`` are checked against the reachability matrix
        regardless of whether the module is a test context.
        """
        _write_modules(tmp_path, {
            "ui_renderer": _UI_RENDERER_S0MA,
            "model_tests": _DOMAIN_TEST_MODULE_S0MA,
        })
        diagnostics = _resolve(tmp_path, test_layering="strict")
        cross_layer = _cross_layer_only(diagnostics)
        assert len(cross_layer) == 1, (
            f"strict mode must still fire CROSS_LAYER_DEPENDENCY for "
            f"a DOMAIN test reaching PRESENTATION; got: "
            f"{[(d.code, d.message) for d in cross_layer]}"
        )
        err = cross_layer[0]
        assert err.context["source_module"] == "model_tests"
        assert err.context["target_module"] == "ui_renderer"

    def test_strict_implicit_when_constructor_default(
        self, tmp_path: Path,
    ) -> None:
        """The resolver's default ``test_layering`` is ``"strict"``.

        Existing callers that do not pass ``test_layering`` get the
        same behaviour as before this milestone.
        """
        _write_modules(tmp_path, {
            "ui_renderer": _UI_RENDERER_S0MA,
            "model_tests": _DOMAIN_TEST_MODULE_S0MA,
        })
        modules, filenames = _load_project(tmp_path)
        # NOTE: no ``test_layering`` kwarg.
        resolver = DependencyResolver(mode=StrictnessMode.STRICT)
        diagnostics = resolver.resolve(
            modules, filenames=filenames, check_imports=False,
        )
        cross_layer = _cross_layer_only(diagnostics)
        assert len(cross_layer) == 1


# ---------------------------------------------------------------------------
# Permissive mode suppresses for test-context modules
# ---------------------------------------------------------------------------


class TestPermissiveSuppressesForTestModules:
    """The opt-in suppresses ``CROSS_LAYER_DEPENDENCY`` for tests only."""

    def test_permissive_suppresses_for_pure_test_module(
        self, tmp_path: Path,
    ) -> None:
        """A module with ≥1 ``test`` declaration is exempt under permissive.

        The fixture has the same shape as the strict-mode test, but
        we flip ``test_layering`` to ``"permissive"``: the
        cross-layer check no longer fires on the test module's
        ``uses:`` entry.
        """
        _write_modules(tmp_path, {
            "ui_renderer": _UI_RENDERER_S0MA,
            "model_tests": _DOMAIN_TEST_MODULE_S0MA,
        })
        diagnostics = _resolve(tmp_path, test_layering="permissive")
        cross_layer = _cross_layer_only(diagnostics)
        assert cross_layer == [], (
            f"permissive mode must suppress CROSS_LAYER_DEPENDENCY for "
            f"a module containing a ``test`` declaration; got: "
            f"{[(d.code, d.message) for d in cross_layer]}"
        )


# ---------------------------------------------------------------------------
# Permissive mode does NOT relax production-module checks
# ---------------------------------------------------------------------------


class TestPermissiveDoesNotRelaxProduction:
    """Production modules (zero ``test`` declarations) still get the check."""

    def test_production_module_still_fires_under_permissive(
        self, tmp_path: Path,
    ) -> None:
        """A DOMAIN production module reaching PRESENTATION still errors.

        The opt-in does not relax the rule for shipped code — only
        test-context modules qualify for the carve-out. ``model_consumer``
        contains a nerve but no ``test`` declarations, so the
        permissive mode does not exempt it.
        """
        _write_modules(tmp_path, {
            "ui_renderer": _UI_RENDERER_S0MA,
            "model_consumer": _DOMAIN_PRODUCTION_MODULE_S0MA,
        })
        diagnostics = _resolve(tmp_path, test_layering="permissive")
        cross_layer = _cross_layer_only(diagnostics)
        assert len(cross_layer) == 1, (
            f"permissive mode must NOT suppress CROSS_LAYER_DEPENDENCY for "
            f"a production module reaching a higher layer; got: "
            f"{[(d.code, d.message) for d in cross_layer]}"
        )
        err = cross_layer[0]
        assert err.context["source_module"] == "model_consumer"
        assert err.context["target_module"] == "ui_renderer"
        # Severity is still error in strict mode.
        assert err.severity == "error"


# ---------------------------------------------------------------------------
# Mixed module (production code + test declarations) is treated as test
# ---------------------------------------------------------------------------


class TestMixedModuleTreatedAsTest:
    """A module mixing production code with ≥1 test declaration qualifies.

    The carve-out trigger is "module has ≥1 test declaration" —
    mirrors the M13 helper-access rule. A nerve sitting next to a
    ``test`` in the same module still counts as test-context.
    """

    def test_mixed_module_qualifies_for_carve_out(
        self, tmp_path: Path,
    ) -> None:
        """A DOMAIN module with a nerve AND a test gets the carve-out.

        The module declares both a ``nerve`` and a ``test``; under
        permissive mode the cross-layer check is skipped for the
        whole module (the trigger checks ``len(module.tests) > 0``).
        """
        mixed_module = dedent("""\
module mixed_consumer
    layer: DOMAIN
    version: 1.0.0
    intent: "Mixed-context: a domain nerve and test reach PRESENTATION via uses:."
    uses: [ui_renderer.render_html]
    exports: [build_label]

    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve build_label :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Builds a label by delegating to render_html."
    expects: "A non-empty label string."
    guarantees: "Returns the HTML-wrapped label."
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
    def build_label(text: str) -> str:
        return render_html(text)

test test_build_label_works :: DOMAIN
    intent: "Verifies build_label wraps via render_html."
    tests: [build_label]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_build_label_works():
        assert build_label("hi") == "<span>hi</span>"
""").lstrip()
        _write_modules(tmp_path, {
            "ui_renderer": _UI_RENDERER_S0MA,
            "mixed_consumer": mixed_module,
        })
        diagnostics = _resolve(tmp_path, test_layering="permissive")
        cross_layer = _cross_layer_only(diagnostics)
        assert cross_layer == [], (
            f"permissive mode must suppress CROSS_LAYER_DEPENDENCY for a "
            f"mixed module (production code + ≥1 test declaration); got: "
            f"{[(d.code, d.message) for d in cross_layer]}"
        )


# ---------------------------------------------------------------------------
# Project config parsing
# ---------------------------------------------------------------------------


class TestProjectConfigParsing:
    """``[tool.s0ma].test_layering`` parses through ``S0maProject``."""

    def _write_pyproject(
        self,
        root: Path,
        *,
        body: str,
        project_name: str = "fakeproj",
    ) -> None:
        content = dedent(f"""
            [project]
            name = "{project_name}"
            version = "0.1.0"

            [tool.s0ma]
            {body}
        """).lstrip()
        (root / "pyproject.toml").write_text(content)

    def test_permissive_parses_from_tool_s0ma(self, tmp_path: Path) -> None:
        """``test_layering = "permissive"`` resolves on the project handle."""
        self._write_pyproject(
            tmp_path,
            body='test_layering = "permissive"',
        )
        project = S0maProject.discover(tmp_path)
        assert project.test_layering == "permissive"

    def test_strict_parses_explicitly(self, tmp_path: Path) -> None:
        """``test_layering = "strict"`` (explicit value) is accepted."""
        self._write_pyproject(
            tmp_path,
            body='test_layering = "strict"',
        )
        project = S0maProject.discover(tmp_path)
        assert project.test_layering == "strict"

    def test_default_is_strict_when_omitted(self, tmp_path: Path) -> None:
        """Omitting the key leaves the project at the strict default."""
        self._write_pyproject(
            tmp_path,
            body='source_roots = ["src"]',
        )
        project = S0maProject.discover(tmp_path)
        assert project.test_layering == "strict"

    def test_unknown_value_raises_value_error(self, tmp_path: Path) -> None:
        """``test_layering = "lax"`` raises ``ValueError`` at project-load."""
        self._write_pyproject(
            tmp_path,
            body='test_layering = "lax"',
        )
        with pytest.raises(ValueError) as exc_info:
            S0maProject.discover(tmp_path)
        message = str(exc_info.value)
        assert "test_layering" in message
        assert "'lax'" in message
        # The remediation must name the supported set so a typo is
        # immediately diagnosable.
        assert "'strict'" in message
        assert "'permissive'" in message

    def test_non_string_value_raises_value_error(
        self, tmp_path: Path,
    ) -> None:
        """``test_layering = true`` raises a TOML type error."""
        self._write_pyproject(
            tmp_path,
            body="test_layering = true",
        )
        with pytest.raises(ValueError) as exc_info:
            S0maProject.discover(tmp_path)
        assert "test_layering" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Round-trip — S0maProject carries the field, resolver reads it
# ---------------------------------------------------------------------------


class TestProjectResolverRoundTrip:
    """``S0maProject.test_layering`` propagates into the resolver."""

    def test_resolver_honours_project_test_layering(
        self, tmp_path: Path,
    ) -> None:
        """A ``S0maProject(test_layering="permissive")`` makes the check skip.

        The CLI forwards ``project.test_layering`` into the resolver via
        ``resolve_dependencies(test_layering=...)``; this test exercises
        the same path end-to-end via ``DependencyResolver(test_layering=...)``.
        """
        _write_modules(tmp_path, {
            "ui_renderer": _UI_RENDERER_S0MA,
            "model_tests": _DOMAIN_TEST_MODULE_S0MA,
        })
        # Pretend we resolved a S0maProject with test_layering="permissive";
        # forward that value into the resolver as the CLI would.
        from s0ma_dsl.resolver.dependency import resolve_dependencies
        modules, filenames = _load_project(tmp_path)
        diagnostics = resolve_dependencies(
            modules,
            mode=StrictnessMode.STRICT,
            filenames=filenames,
            check_imports=False,
            test_layering="permissive",
        )
        cross_layer = _cross_layer_only(diagnostics)
        assert cross_layer == [], (
            f"resolve_dependencies(test_layering='permissive') must "
            f"suppress the cross-layer error for the test module; got: "
            f"{[(d.code, d.message) for d in cross_layer]}"
        )

    def test_synthetic_project_defaults_to_strict(
        self, tmp_path: Path,
    ) -> None:
        """A synthetic-fallback project defaults to ``test_layering="strict"``.

        Synthetic projects (no ``[tool.s0ma]`` table) get the
        conservative default — they cannot opt into the relaxation.
        """
        project = S0maProject.synthetic_fallback(tmp_path)
        assert project.synthetic is True
        assert project.test_layering == "strict"
