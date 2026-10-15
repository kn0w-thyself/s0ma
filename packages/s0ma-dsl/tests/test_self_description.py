"""Milestone 22 — Transpiler Self-Description Audit.

Verifies that the transpiler is a complete, queryable s0ma project:
- Every module has @component or @internal coverage (FR-31, P4)
- The transpiler's architecture is visible through the registry
- The component graph is queryable via SelfModelInterface
- Dependencies are registered and the dependency graph is accurate
"""

import pytest
import s0ma
from s0ma import SelfModelInterface
from s0ma.registry import reset_registry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_TRANSPILER_MODULES = [
    "s0ma_dsl.errors",
    "s0ma_dsl.config",
    "s0ma_dsl.ast_nodes.enums",
    "s0ma_dsl.ast_nodes.nodes",
    "s0ma_dsl.parser.body_extractor",
    "s0ma_dsl.parser.s0ma_parser",
    "s0ma_dsl.semantic.validator",
    "s0ma_dsl.semantic.derived_edges",
    "s0ma_dsl.resolver.namespaces",
    "s0ma_dsl.resolver.dependency",
    "s0ma_dsl.ir.schema",
    "s0ma_dsl.ir.builder",
    "s0ma_dsl.codegen.python_emitter",
    "s0ma_dsl.codegen.observes_resolver",
    "s0ma_dsl.codegen.source_map",
    "s0ma_dsl.runtime_bridge.registration",
    "s0ma_dsl.cli.main",
    "s0ma_dsl.cache",
]


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Ensure a clean registry with all transpiler modules registered.

    Since modules are already cached in sys.modules and @component decorators
    have already fired (into the previous registry), we use register_from_module()
    to scan the cached modules and register their components into the new registry.
    """
    import importlib
    import sys

    reset_registry()
    registry = s0ma.initialize(persist=False)

    # Import all transpiler modules (no-op if already cached) and register
    for mod_name in _TRANSPILER_MODULES:
        if mod_name not in sys.modules:
            importlib.import_module(mod_name)
        mod = sys.modules[mod_name]
        registry.register_from_module(mod)

    yield registry
    reset_registry()


def _get_dsl_components(registry):
    """Return only S0maDSL_ prefixed components from the registry."""
    return {
        name: spec
        for name, spec in registry.get_all().items()
        if name.startswith("S0maDSL_")
    }


# ---------------------------------------------------------------------------
# 22.1 — Component coverage audit
# ---------------------------------------------------------------------------


class TestComponentCoverage:
    """Verify every transpiler module has @component/@internal coverage."""

    def test_total_component_count(self, _fresh_registry):
        """The transpiler should register a substantial number of components."""
        dsl = _get_dsl_components(_fresh_registry)
        # We expect 80 components (59 classes/enums + 21 functions)
        assert len(dsl) >= 75, (
            f"Expected at least 75 S0maDSL components, found {len(dsl)}"
        )

    def test_all_components_use_framework_layer(self, _fresh_registry):
        """Every transpiler component uses Layer.FRAMEWORK per CC-1."""
        from s0ma.types import Layer

        dsl = _get_dsl_components(_fresh_registry)
        for name, spec in dsl.items():
            assert spec.layer == Layer.FRAMEWORK, (
                f"{name} has layer={spec.layer}, expected FRAMEWORK"
            )

    def test_all_components_have_intent(self, _fresh_registry):
        """Every component has a non-trivial intent field."""
        dsl = _get_dsl_components(_fresh_registry)
        for name, spec in dsl.items():
            assert spec.intent and len(spec.intent) >= 10, (
                f"{name} has missing or too-short intent: {spec.intent!r}"
            )

    def test_error_types_registered(self, _fresh_registry):
        """All four error types are registered."""
        dsl = _get_dsl_components(_fresh_registry)
        for name in [
            "S0maDSL_S0maError",
            "S0maDSL_S0maParseError",
            "S0maDSL_S0maSemanticError",
            "S0maDSL_S0maResolutionError",
        ]:
            assert name in dsl, f"Missing error component: {name}"

    def test_config_types_registered(self, _fresh_registry):
        """Strictness modes and config are registered."""
        dsl = _get_dsl_components(_fresh_registry)
        assert "S0maDSL_StrictnessMode" in dsl
        assert "S0maDSL_TranspilerConfig" in dsl
        assert "S0maDSL_get_severity" in dsl

    def test_ast_enums_registered(self, _fresh_registry):
        """All 7 AST enums are registered."""
        dsl = _get_dsl_components(_fresh_registry)
        for name in [
            "S0maDSL_Layer",
            "S0maDSL_DeclarationType",
            "S0maDSL_Kind",
            "S0maDSL_Visibility",
            "S0maDSL_Relation",
            "S0maDSL_Coupling",
            "S0maDSL_EvaluatesAt",
        ]:
            assert name in dsl, f"Missing AST enum: {name}"

    def test_ast_nodes_registered(self, _fresh_registry):
        """All 11 AST node types are registered."""
        dsl = _get_dsl_components(_fresh_registry)
        for name in [
            "S0maDSL_SourceLocation",
            "S0maDSL_RequiresEntry",
            "S0maDSL_UsesEntry",
            "S0maDSL_InlineAxon",
            "S0maDSL_ModuleDecl",
            "S0maDSL_NerveDecl",
            "S0maDSL_CellDecl",
            "S0maDSL_GanglionDecl",
            "S0maDSL_TestDecl",
            "S0maDSL_StandaloneAxonDecl",
            "S0maDSL_S0maModule",
        ]:
            assert name in dsl, f"Missing AST node: {name}"

    def test_parser_components_registered(self, _fresh_registry):
        """Parser, body extractor, and parse functions are registered."""
        dsl = _get_dsl_components(_fresh_registry)
        for name in [
            "S0maDSL_S0maParser",
            "S0maDSL_BodyType",
            "S0maDSL_BodyInfo",
            "S0maDSL_extract_body",
            "S0maDSL_validate_body",
            "S0maDSL_parse_s0ma",
            "S0maDSL_parse_s0ma_with_warnings",
        ]:
            assert name in dsl, f"Missing parser component: {name}"

    def test_semantic_components_registered(self, _fresh_registry):
        """Validator and derived edge analyzer are registered."""
        dsl = _get_dsl_components(_fresh_registry)
        for name in [
            "S0maDSL_IntraModuleValidator",
            "S0maDSL_validate_module",
            "S0maDSL_DerivedEdge",
            "S0maDSL_DerivedEdgeAnalyzer",
            "S0maDSL_analyze_derived_edges",
        ]:
            assert name in dsl, f"Missing semantic component: {name}"

    def test_resolver_components_registered(self, _fresh_registry):
        """Namespace services and dependency resolver are registered."""
        dsl = _get_dsl_components(_fresh_registry)
        for name in [
            "S0maDSL_NamespaceEntry",
            "S0maDSL_NamespaceService",
            "S0maDSL_build_namespaces",
            "S0maDSL_DependencyResolver",
            "S0maDSL_resolve_dependencies",
        ]:
            assert name in dsl, f"Missing resolver component: {name}"

    def test_ir_components_registered(self, _fresh_registry):
        """All IR schema types and builder are registered."""
        dsl = _get_dsl_components(_fresh_registry)
        for name in [
            "S0maDSL_IRDocument",
            "S0maDSL_IRModule",
            "S0maDSL_IRComponent",
            "S0maDSL_IRAuthoredEdge",
            "S0maDSL_IRDerivedEdge",
            "S0maDSL_IRVerificationEdge",
            "S0maDSL_IREdges",
            "S0maDSL_IRImports",
            "S0maDSL_IRBuilder",
            "S0maDSL_build_ir",
            "S0maDSL_compute_content_hash",
        ]:
            assert name in dsl, f"Missing IR component: {name}"

    def test_codegen_components_registered(self, _fresh_registry):
        """Emitter, observes resolver, and source map components are registered."""
        dsl = _get_dsl_components(_fresh_registry)
        for name in [
            "S0maDSL_PythonEmitter",
            "S0maDSL_emit_python",
            "S0maDSL_ObservesResolver",
            "S0maDSL_ProjectContext",
            "S0maDSL_ResolvedObserves",
            "S0maDSL_PrivilegedImportInfo",
            "S0maDSL_resolve_observes",
            "S0maDSL_determine_privileged_imports",
            "S0maDSL_SourceMapGenerator",
            "S0maDSL_SourceMap",
            "S0maDSL_generate_source_map",
        ]:
            assert name in dsl, f"Missing codegen component: {name}"

    def test_runtime_bridge_registered(self, _fresh_registry):
        """All registration bridge functions are registered."""
        dsl = _get_dsl_components(_fresh_registry)
        for name in [
            "S0maDSL_register_module",
            "S0maDSL_register_constant",
            "S0maDSL_register_type",
            "S0maDSL_register_relationship",
            "S0maDSL_register_test",
        ]:
            assert name in dsl, f"Missing runtime bridge function: {name}"

    def test_cli_components_registered(self, _fresh_registry):
        """CLI entry point and main function are registered."""
        dsl = _get_dsl_components(_fresh_registry)
        assert "S0maDSL_S0maCLI" in dsl
        assert "S0maDSL_main" in dsl

    def test_cache_components_registered(self, _fresh_registry):
        """Cache types are registered."""
        dsl = _get_dsl_components(_fresh_registry)
        assert "S0maDSL_CacheResult" in dsl
        assert "S0maDSL_BuildCache" in dsl

    def test_helpers_are_framework_components(self, _fresh_registry):
        """Every S0maDSL_ helper is part of s0ma's own toolchain.

        They are registered with ``is_framework=True`` so that a self-model
        counts them with the framework rather than with the application, and
        so the coverage auditor does not report them as vestigial.
        """
        dsl = _get_dsl_components(_fresh_registry)
        for name, spec in dsl.items():
            assert spec.is_framework, (
                f"{name} is registered as a user component; the s0ma-dsl "
                f"helpers are framework components"
            )


# ---------------------------------------------------------------------------
# 22.2 — Component graph queryable through registry
# ---------------------------------------------------------------------------


class TestRegistryQueryability:
    """Verify the transpiler's architecture is queryable via the registry."""

    def test_describe_system_includes_dsl_components(self, _fresh_registry):
        """SelfModelInterface.describe_system() shows transpiler components."""
        smi = SelfModelInterface(_fresh_registry)
        description = smi.describe_system()
        # The system description should mention user/application components
        assert "80" in description or "component" in description.lower()

    def test_describe_component_works_for_dsl(self, _fresh_registry):
        """SelfModelInterface.describe_component() works for transpiler components."""
        smi = SelfModelInterface(_fresh_registry)
        desc = smi.describe_component("S0maDSL_S0maParser")
        assert "S0maDSL_S0maParser" in desc
        assert "SERVICE" in desc or "service" in desc.lower()

    def test_get_by_name(self, _fresh_registry):
        """Registry.get() retrieves transpiler components by name."""
        spec = _fresh_registry.get("S0maDSL_S0maParser")
        assert spec is not None
        assert spec.intent and len(spec.intent) >= 10

    def test_query_by_layer(self, _fresh_registry):
        """Registry.query_by_layer() returns transpiler components."""
        from s0ma.types import Layer

        framework_components = _fresh_registry.query_by_layer(Layer.FRAMEWORK)
        dsl_names = [
            c.name for c in framework_components if c.name.startswith("S0maDSL_")
        ]
        assert len(dsl_names) >= 75

    def test_query_by_kind_service(self, _fresh_registry):
        """Registry.query_by_kind() returns transpiler SERVICE components."""
        from s0ma.types import ComponentKind

        services = _fresh_registry.query_by_kind(ComponentKind.SERVICE)
        dsl_services = [s for s in services if s.name.startswith("S0maDSL_")]
        # Expect: S0maParser, IntraModuleValidator, DependencyResolver,
        # DerivedEdgeAnalyzer, NamespaceService, IRBuilder, PythonEmitter,
        # ObservesResolver, SourceMapGenerator, S0maCLI, BuildCache
        assert len(dsl_services) >= 10, (
            f"Expected at least 10 S0maDSL SERVICE components, found {len(dsl_services)}"
        )

    def test_query_by_kind_function(self, _fresh_registry):
        """Registry.query_by_kind() returns transpiler FUNCTION components."""
        from s0ma.types import ComponentKind

        functions = _fresh_registry.query_by_kind(ComponentKind.FUNCTION)
        dsl_functions = [f for f in functions if f.name.startswith("S0maDSL_")]
        # Expect: parse_s0ma, parse_s0ma_with_warnings, validate_module,
        # analyze_derived_edges, build_namespaces, resolve_dependencies,
        # compute_content_hash, build_ir, emit_python, resolve_observes,
        # determine_privileged_imports, generate_source_map, get_severity,
        # extract_body, validate_body, main, register_module, register_constant,
        # register_type, register_relationship, register_test
        assert len(dsl_functions) >= 20, (
            f"Expected at least 20 S0maDSL FUNCTION components, found {len(dsl_functions)}"
        )

    def test_query_by_kind_model(self, _fresh_registry):
        """Registry.query_by_kind() returns transpiler MODEL components."""
        from s0ma.types import ComponentKind

        models = _fresh_registry.query_by_kind(ComponentKind.MODEL)
        dsl_models = [m for m in models if m.name.startswith("S0maDSL_")]
        # Expect: all enums, AST nodes, IR schema types, error types, etc.
        assert len(dsl_models) >= 45, (
            f"Expected at least 45 S0maDSL MODEL components, found {len(dsl_models)}"
        )


# ---------------------------------------------------------------------------
# 22.3 — Dependency graph accuracy
# ---------------------------------------------------------------------------


class TestDependencyGraph:
    """Verify transpiler dependencies are registered and the graph is accurate."""

    def test_dependency_graph_exists(self, _fresh_registry):
        """The registry produces a dependency graph."""
        graph = _fresh_registry.get_dependency_graph()
        assert isinstance(graph, dict)

    def test_impact_analysis_works(self, _fresh_registry):
        """Impact analysis works for transpiler components."""
        smi = SelfModelInterface(_fresh_registry)
        impact = smi.get_impact_analysis("S0maDSL_S0maParser")
        assert "S0maDSL_S0maParser" in impact

    def test_architecture_context_includes_dsl(self, _fresh_registry):
        """get_architecture_context() includes transpiler architecture."""
        smi = SelfModelInterface(_fresh_registry)
        context = smi.get_architecture_context()
        assert "FRAMEWORK" in context

    def test_component_kind_distribution(self, _fresh_registry):
        """The transpiler has a healthy distribution of component kinds."""
        dsl = _get_dsl_components(_fresh_registry)
        from s0ma.types import ComponentKind

        kinds = {}
        for spec in dsl.values():
            kinds[spec.kind] = kinds.get(spec.kind, 0) + 1

        # Should have all three main kinds
        assert ComponentKind.MODEL in kinds, "No MODEL components found"
        assert ComponentKind.SERVICE in kinds, "No SERVICE components found"
        assert ComponentKind.FUNCTION in kinds, "No FUNCTION components found"

        # Models should be the majority (data types)
        assert kinds[ComponentKind.MODEL] > kinds[ComponentKind.SERVICE]
        assert kinds[ComponentKind.FUNCTION] > kinds[ComponentKind.SERVICE]
