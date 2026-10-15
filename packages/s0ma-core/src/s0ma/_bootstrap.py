"""Bootstrap self-registration — the escape hatch for the bootstrap paradox.

The @component decorator cannot decorate itself at import time because
the decorator module hasn't loaded yet when it's being defined. This
module solves the chicken-and-egg problem with direct registration:

Phase A: Manually construct ComponentSpec objects and register them
         without using @component.
Phase B: After all modules load, verify the manual specs are equivalent
         to what @component would produce (validated in test_bootstrap.py).

This is the only module that bypasses the normal registration path.
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING

from s0ma.models import ComponentSpec, Contract
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from types import ModuleType

    from s0ma.registry import ComponentRegistry

__all__ = [
    "bootstrap_register",
    "EXPECTED_FRAMEWORK_COMPONENT_COUNT",
]

logger = logging.getLogger("s0ma")

# The exact number of framework components registered by bootstrap.
# Update this constant whenever a framework component is added or removed.
# The bootstrap test uses this to catch accidental omissions.
# 60 → 61 (0.11.0): + AdoptedFile (batch-01a D2, adopted-file records).
EXPECTED_FRAMEWORK_COMPONENT_COUNT = 61


def bootstrap_register(registry: ComponentRegistry) -> None:
    """Register s0ma's own components in the registry.

    This function is called during framework initialization to register
    the framework's own infrastructure. It uses direct ComponentSpec
    construction (not the @component decorator) to avoid the bootstrap
    paradox — the decorator can't decorate itself.

    The bootstrap test (test_bootstrap.py) verifies that these manual
    registrations are accurate: every registered component has
    corresponding source code, and every public entity in s0ma
    is either registered here or intentionally excluded.

    Args:
        registry: The ComponentRegistry to register framework components in.
    """
    # Import all framework modules to derive source file paths
    from s0ma import decorators, import_hook, models
    from s0ma import registry as registry_module
    from s0ma import testing as testing_module
    from s0ma import utils as utils_module
    from s0ma.api import query_engine as query_engine_module
    from s0ma.api import teaching as teaching_module
    from s0ma.examples import dispatcher as examples_dispatcher_module
    # `s0ma.examples.plugin` does `import pytest` at module load time
    # because it implements pytest11 hook functions. pytest is declared
    # only as a dev/test extra, so in runtime-only environments
    # (production wheel install, OCI containers without pytest) the
    # plugin module is unimportable. We do no bootstrap registration
    # for the plugin module anyway — see `_ = examples_plugin_module`
    # ~line 1585 with the inline rationale: "No bootstrap registration
    # is required for the plugin module." A `None` placeholder is
    # functionally equivalent and lets s0ma.initialize() succeed in
    # pytest-less environments.
    examples_plugin_module: ModuleType | None
    try:
        from s0ma.examples import plugin as examples_plugin_module
    except ImportError:
        examples_plugin_module = None
    from s0ma.examples import runner as examples_runner_module
    from s0ma.examples import timeout as examples_timeout_module
    from s0ma.lifecycle import manager as lifecycle_manager_module
    from s0ma.lifecycle import transaction as lifecycle_transaction_module
    from s0ma.self_model import analyzers as self_model_analyzers_module
    from s0ma.self_model import interface as self_model_interface_module
    from s0ma.verifiers import base as verifiers_base
    from s0ma.verifiers import contracts as verifiers_contracts
    from s0ma.verifiers import coverage as verifiers_coverage
    from s0ma.verifiers import interoception as verifiers_interoception
    from s0ma.verifiers import structural as verifiers_structural

    specs = _build_framework_specs(
        models_module=models,
        registry_module=registry_module,
        decorators_module=decorators,
        import_hook_module=import_hook,
        verifiers_base_module=verifiers_base,
        verifiers_structural_module=verifiers_structural,
        verifiers_contracts_module=verifiers_contracts,
        verifiers_interoception_module=verifiers_interoception,
        verifiers_coverage_module=verifiers_coverage,
        lifecycle_manager_module=lifecycle_manager_module,
        lifecycle_transaction_module=lifecycle_transaction_module,
        self_model_interface_module=self_model_interface_module,
        self_model_analyzers_module=self_model_analyzers_module,
        query_engine_module=query_engine_module,
        teaching_module=teaching_module,
        testing_module=testing_module,
        utils_module=utils_module,
        examples_runner_module=examples_runner_module,
        examples_dispatcher_module=examples_dispatcher_module,
        examples_timeout_module=examples_timeout_module,
        examples_plugin_module=examples_plugin_module,
    )

    for spec in specs:
        if not registry.contains(spec.name):
            registry.register(spec)
            logger.debug("Bootstrap-registered framework component: %s", spec.name)

    logger.info(
        "Bootstrap self-registration complete: %d framework components registered.",
        len(specs),
    )


def _build_framework_specs(
    *,
    models_module: object,
    registry_module: object,
    decorators_module: object,
    import_hook_module: object,
    verifiers_base_module: object | None = None,
    verifiers_structural_module: object | None = None,
    verifiers_contracts_module: object | None = None,
    verifiers_interoception_module: object | None = None,
    verifiers_coverage_module: object | None = None,
    lifecycle_manager_module: object | None = None,
    lifecycle_transaction_module: object | None = None,
    self_model_interface_module: object | None = None,
    self_model_analyzers_module: object | None = None,
    query_engine_module: object | None = None,
    teaching_module: object | None = None,
    testing_module: object | None = None,
    utils_module: object | None = None,
    examples_runner_module: object | None = None,
    examples_dispatcher_module: object | None = None,
    examples_timeout_module: object | None = None,
    examples_plugin_module: object | None = None,
) -> list[ComponentSpec]:
    """Construct ComponentSpec objects for all s0ma framework entities.

    Each spec mirrors what @component would produce if it could decorate
    itself. The fields are:
    - name: matches the class/function name used in the codebase
    - kind: FRAMEWORK for all (they are framework infrastructure)
    - layer: FRAMEWORK for all (they live in the framework layer)
    - intent: accurate, >10 char description of purpose
    - module_path: fully qualified module path
    - qualified_name: fully qualified dotted name
    - source_file: absolute path derived from inspect.getfile()
    - is_framework: True for all

    Returns:
        List of ComponentSpec objects for framework registration.
    """
    models_file = inspect.getfile(models_module)  # type: ignore[arg-type]
    registry_file = inspect.getfile(registry_module)  # type: ignore[arg-type]
    decorators_file = inspect.getfile(decorators_module)  # type: ignore[arg-type]
    import_hook_file = inspect.getfile(import_hook_module)  # type: ignore[arg-type]

    verifiers_base_file: str | None = None
    if verifiers_base_module is not None:
        verifiers_base_file = inspect.getfile(verifiers_base_module)  # type: ignore[arg-type]

    verifiers_structural_file: str | None = None
    if verifiers_structural_module is not None:
        verifiers_structural_file = inspect.getfile(
            verifiers_structural_module  # type: ignore[arg-type]
        )

    verifiers_contracts_file: str | None = None
    if verifiers_contracts_module is not None:
        verifiers_contracts_file = inspect.getfile(
            verifiers_contracts_module  # type: ignore[arg-type]
        )

    verifiers_interoception_file: str | None = None
    if verifiers_interoception_module is not None:
        verifiers_interoception_file = inspect.getfile(
            verifiers_interoception_module  # type: ignore[arg-type]
        )

    verifiers_coverage_file: str | None = None
    if verifiers_coverage_module is not None:
        verifiers_coverage_file = inspect.getfile(
            verifiers_coverage_module  # type: ignore[arg-type]
        )

    specs: list[ComponentSpec] = [
        # --- models.py entities ---
        ComponentSpec(
            name="ComponentSpec",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent="Core data structure storing registration metadata for a single component",
            contracts=Contract(
                invariants=[
                    "name is non-empty and contains no whitespace",
                    "intent is at least 10 characters",
                    "no self-dependency in dependencies list",
                ],
                postconditions=[
                    "to_dict() produces JSON-serializable dictionary",
                    "from_dict() reconstructs ComponentSpec from dictionary",
                    "from_dict(to_dict()) round-trip preserves all fields",
                ],
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.ComponentSpec",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="Contract",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Behavioral contract declaring pre/postconditions, "
                "invariants, performance expectations, and cross-boundary "
                "protocol contracts with descriptive error messages "
                "on invalid keyword arguments"
            ),
            contracts=Contract(
                invariants=[
                    "max_latency_ms is positive when set",
                    "error_rate_threshold is between 0.0 and 1.0 when set",
                ],
                postconditions=[
                    "invalid keyword arguments raise RegistrationError with valid field list",
                    "to_dict() produces JSON-serializable dictionary",
                    "from_dict() reconstructs Contract from dictionary with validation",
                    "from_dict(to_dict()) round-trip preserves all fields "
                    "including configurable_properties and protocol",
                ],
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.Contract",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="ConfigurableProperty",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Descriptor for runtime-configurable component properties "
                "like theme colors, layout options, and display settings"
            ),
            contracts=Contract(
                invariants=[
                    "type must be one of: str, int, float, bool, enum",
                    "default value must match declared type",
                    "enum type requires non-empty allowed_values list containing default",
                    "numeric constraints must have min < max when both specified",
                ],
                postconditions=[
                    "to_dict() omits None values",
                    "from_dict() reconstructs ConfigurableProperty with validation",
                ],
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.ConfigurableProperty",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="ProtocolContract",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Declarative specification of a cross-boundary interface contract "
                "for WebSocket, REST, gRPC, or IPC protocols"
            ),
            contracts=Contract(
                invariants=[
                    "protocol_type is a non-empty string",
                    "message_types maps message names to schema dicts",
                ],
                postconditions=[
                    "to_dict() omits None description",
                    "from_dict() reconstructs ProtocolContract with required field validation",
                    "from_dict(to_dict()) round-trip preserves all fields",
                ],
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.ProtocolContract",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="ResourceProfile",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent="Expected resource usage profile for interoception monitoring of components",
            contracts=Contract(
                invariants=[
                    "all numeric fields are non-negative when set",
                    "expected_error_rate is between 0.0 and 1.0 when set",
                ],
                postconditions=[
                    "to_dict() omits None values",
                    "from_dict() reconstructs ResourceProfile with validation",
                ],
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.ResourceProfile",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="Anomaly",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Represents a detected code-model discrepancy "
                "classified by biological pathology"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.Anomaly",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="ImportHookAnomaly",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Frozen record describing one foreign-code violation "
                "detected by the s0ma import hook; appended to the "
                "registry's anomaly buffer and dispatched to "
                "subscribers for downstream immune-response detection"
            ),
            contracts=Contract(
                postconditions=[
                    "to_dict() serialises severity / layer enum names "
                    "as strings; layer is None when registry module "
                    "metadata is unavailable",
                    "instance is frozen and hashable — safe in sets "
                    "and as dict keys",
                ],
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.ImportHookAnomaly",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="RegistrySnapshot",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Frozen serializable view of registry state "
                "with human-readable self-description"
            ),
            contracts=Contract(
                postconditions=[
                    "to_dict() includes components, modules, edges, "
                    "test_registrations, ir, and plugins; "
                    "doc_refs / doc_guides / examples keys are emitted "
                    "only when the corresponding stores are non-empty",
                    "describe() produces human-readable self-description",
                    "examples_for(entity_ref) returns ExampleRegistrations "
                    "whose demonstrates list matches the given EntityRef "
                    "or 'module::name' string shortcut",
                    "docs_for(entity_ref) returns a DocsForResult with "
                    "matching doc-refs and doc-guides",
                ],
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.RegistrySnapshot",
            source_file=models_file,
            is_framework=True,
        ),
        # --- models.py DSL expansion entities ---
        ComponentSpec(
            name="ModuleMetadata",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Metadata for module-level registration capturing layer, "
                "version, intent, exports, content hash, and tags"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.ModuleMetadata",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="AdoptedFile",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Record of a real (non-generated) file registered into "
                "the self-model by adoption: path, content hash at "
                "adoption time, optional description and metadata"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.AdoptedFile",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="RelationshipEdge",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Dependency relationship between two components with "
                "relation type (CALLS, READS, CONSTRUCTS, CONFIGURES, "
                "RAISES, TYPE_USES, OBSERVES, PRODUCES, CONSUMES), "
                "coupling, and authored/derived origin"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.RelationshipEdge",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="TestRegistration",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Registration metadata for a test declaration linking "
                "tests to the components they validate"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.TestRegistration",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="PluginRegistration",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Registration metadata for a plugin with dependency "
                "validation against core components"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.PluginRegistration",
            source_file=models_file,
            is_framework=True,
        ),
        # --- models.py documentation subsystem entities (design §§6, 10.1) ---
        ComponentSpec(
            name="SourceSpan",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Source file location (path + line range) for a "
                "documentation subsystem declaration"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.SourceSpan",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="EntityRef",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Typed reference to a registered entity by kind, name, "
                "and optional module, used for doc-guide covers and "
                "example demonstrates lists"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.EntityRef",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="FilterExpr",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Parsed filter expression used by doc-refs to select the "
                "entities they cover, carrying target kind, predicate, "
                "and raw source text"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.FilterExpr",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="Section",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Rendering section inside a doc-ref declaration with "
                "optional iterate, group_by, and structured render "
                "directive"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.Section",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="AssertExpr",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Verifiable assertion attached to a doc-guide, pairing "
                "an assertion expression with its source span for "
                "precise diagnostic reporting"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.AssertExpr",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="DocRefRegistration",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Registration record for a doc-ref declaration: a "
                "generated-documentation artifact selecting entities "
                "via covers filter expressions and emitting structured "
                "sections, with a content hash for drift detection"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.DocRefRegistration",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="DocGuideRegistration",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Registration record for a doc-guide declaration: an "
                "authored prose body with embedded example references, "
                "explicit covers, declarative asserts, and a content "
                "hash for drift detection"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.DocGuideRegistration",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="ExampleRegistration",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Registration record for an example declaration: a "
                "runnable body demonstrating named entities, dispatched "
                "by runs_in mode (standalone, pytest, or integration)"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.ExampleRegistration",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="DocsForResult",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Structured result of RegistrySnapshot.docs_for, "
                "splitting matches into refs and guides lists so "
                "callers iterate either without runtime type dispatch"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.DocsForResult",
            source_file=models_file,
            is_framework=True,
        ),
        # --- registry.py entities ---
        ComponentSpec(
            name="ComponentRegistry",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Central registry storing all registered components "
                "with hierarchical queries and SQLite persistence"
            ),
            contracts=Contract(
                invariants=[
                    "component names are unique within the registry",
                    "thread-safe write operations via threading.Lock",
                ],
                postconditions=[
                    "register_from_module() scans a module and registers all "
                    "@component-decorated entities not already present, "
                    "returning a list of newly registered ComponentSpecs; "
                    "register(spec, idempotent=True) silently succeeds when "
                    "re-registering the same component from the same source file; "
                    "register_or_update(spec) upserts a component (registers if "
                    "new, updates if same source file, raises on name collision "
                    "from a different source); "
                    "import_order() returns topologically sorted module paths "
                    "based on the current dependency graph; "
                    "to_dict() returns complete registry state as a "
                    "JSON-serializable dict including components, modules, "
                    "edges, test_registrations, ir, plugins, and summary "
                    "counts; "
                    "store_ir(module_name, ir_data) stores IR data for a "
                    "module; get_ir(module_name) retrieves it; "
                    "get_all_ir() returns all stored IR data; "
                    "register_plugin() registers a plugin with dependency "
                    "validation; get_plugin(name) retrieves it; "
                    "get_all_plugins() returns all registered plugins",
                ],
            ),
            dependencies=[
                "ComponentSpec",
                "RegistrySnapshot",
                "AdoptedFile",
                "AssertExpr",
                "Contract",
                "DocGuideRegistration",
                "DocRefRegistration",
                "EntityRef",
                "ExampleRegistration",
                "FilterExpr",
                "ImportHookAnomaly",
                "ModuleMetadata",
                "PluginRegistration",
                "RelationshipEdge",
                "ResourceProfile",
                "Section",
                "SourceSpan",
                "TestRegistration",
            ],
            module_path="s0ma.registry",
            qualified_name="s0ma.registry.ComponentRegistry",
            source_file=registry_file,
            is_framework=True,
        ),
        # --- decorators.py entities ---
        ComponentSpec(
            name="ComponentDecorator",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Decorator factory that registers classes and functions "
                "as components in the self-model"
            ),
            contracts=Contract(
                preconditions=[
                    "target is a class or callable function",
                    "name, kind, layer, and intent are provided",
                ],
                postconditions=[
                    "entity is registered in the global registry",
                    "entity.__component__ contains the ComponentSpec",
                    "entity is returned unmodified (no wrapping or proxying); "
                    "idempotent=True allows re-registration from the same "
                    "source file without error, enabling hot-reload patterns",
                ],
            ),
            dependencies=[
                "ComponentRegistry",
                "ComponentSpec",
                "Contract",
                "ResourceProfile",
            ],
            module_path="s0ma.decorators",
            qualified_name="s0ma.decorators.component",
            source_file=decorators_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="InternalDecorator",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Lightweight marker decorator for private helpers "
                "intentionally excluded from registration"
            ),
            contracts=Contract(
                postconditions=[
                    "entity.__s0ma_internal__ is set to True",
                    "entity is NOT registered in the registry",
                ],
            ),
            module_path="s0ma.decorators",
            qualified_name="s0ma.decorators.internal",
            source_file=decorators_file,
            is_framework=True,
        ),
        # --- import_hook.py entities ---
        ComponentSpec(
            name="S0maLoader",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Module loader wrapper that scans for unregistered "
                "public entities after module execution"
            ),
            contracts=Contract(
                preconditions=["module has been fully loaded by the original loader"],
                postconditions=[
                    "all public classes and functions are verified as registered or @internal",
                ],
            ),
            module_path="s0ma.import_hook",
            qualified_name="s0ma.import_hook.S0maLoader",
            source_file=import_hook_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="S0maFinder",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Meta-path finder that determines whether a module "
                "is in scope for registration enforcement"
            ),
            contracts=Contract(
                invariants=[
                    "only modules under project_root are enforced",
                    "allowlisted module prefixes are always exempted",
                ],
            ),
            dependencies=["S0maLoader"],
            module_path="s0ma.import_hook",
            qualified_name="s0ma.import_hook.S0maFinder",
            source_file=import_hook_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="S0maDSLLoader",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Module loader for .s0ma source files that transpiles "
                "on-the-fly via the s0ma-dsl package and caches the "
                "emitted Python alongside the source"
            ),
            contracts=Contract(
                preconditions=[
                    "s0ma_path points to an existing .s0ma file under project_root",
                    "s0ma-dsl package is importable when transpilation is required",
                ],
                postconditions=[
                    "module namespace is populated from the cached transpiled .py",
                    "all public classes, functions, and documentation markers "
                    "are verified against the registry",
                ],
                invariants=[
                    "cache is keyed by SHA-256 of the .s0ma source text",
                ],
            ),
            module_path="s0ma.import_hook",
            qualified_name="s0ma.import_hook.S0maDSLLoader",
            source_file=import_hook_file,
            is_framework=True,
        ),
        # --- Phase 2: Verification models (models.py) ---
        ComponentSpec(
            name="ReflexionAnalysis",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Murphy's Reflexion Model output classifying "
                "convergences, divergences, and absences"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.ReflexionAnalysis",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="VerificationResult",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Result from a single verifier run with anomalies, "
                "timing, and summary statistics"
            ),
            contracts=Contract(
                postconditions=[
                    "passed is True when no ERROR-severity anomalies exist",
                    "error_count, warning_count, info_count are accurate",
                ],
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.VerificationResult",
            source_file=models_file,
            is_framework=True,
        ),
        ComponentSpec(
            name="VerificationReport",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Aggregated results from running multiple verifiers "
                "with summary statistics and overall pass/fail"
            ),
            contracts=Contract(
                postconditions=[
                    "passed is True when all verifiers passed",
                ],
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.VerificationReport",
            source_file=models_file,
            is_framework=True,
        ),
        # --- Phase 2 M2: Erosion coverage model ---
        ComponentSpec(
            name="ErosionCoverageReport",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "de Silva et al. erosion-control strategy coverage "
                "tracking minimise, prevent, and repair activation"
            ),
            contracts=Contract(
                postconditions=[
                    "all_strategies_active is True when all three "
                    "strategies are active",
                ],
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.ErosionCoverageReport",
            source_file=models_file,
            is_framework=True,
        ),
    ]

    # --- Phase 2: Verifier package entities ---
    if verifiers_base_file is not None:
        specs.append(
            ComponentSpec(
                name="Verifier",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Protocol defining the interface for all "
                    "s0ma verification engines"
                ),
                contracts=Contract(
                    postconditions=[
                        "verify() returns a VerificationResult",
                        "verify_incremental() scopes checks "
                        "to a single component",
                    ],
                ),
                dependencies=[
                    "ComponentRegistry",
                    "VerificationResult",
                ],
                module_path="s0ma.verifiers.base",
                qualified_name="s0ma.verifiers.base.Verifier",
                source_file=verifiers_base_file,
                is_framework=True,
            )
        )

    if verifiers_structural_file is not None:
        specs.append(
            ComponentSpec(
                name="StructuralVerifier",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "AST-based structural drift detection comparing "
                    "registry declarations against actual source code"
                ),
                contracts=Contract(
                    preconditions=["registry is not None"],
                    postconditions=[
                        "returns VerificationResult with structural anomalies",
                        "includes Murphy's Reflexion Model analysis",
                    ],
                ),
                dependencies=[
                    "ComponentRegistry",
                    "VerificationResult",
                    "Anomaly",
                    "ReflexionAnalysis",
                ],
                module_path="s0ma.verifiers.structural",
                qualified_name=(
                    "s0ma.verifiers.structural.StructuralVerifier"
                ),
                source_file=verifiers_structural_file,
                is_framework=True,
            )
        )

    # --- Phase 2 M3: Contract verifier entities ---
    if verifiers_contracts_file is not None:
        specs.extend([
            ComponentSpec(
                name="ContractValidatorEntry",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Data structure linking a callable validator "
                    "to a contract description string"
                ),
                module_path="s0ma.verifiers.contracts",
                qualified_name=(
                    "s0ma.verifiers.contracts"
                    ".ContractValidatorEntry"
                ),
                source_file=verifiers_contracts_file,
                is_framework=True,
            ),
            ComponentSpec(
                name="ContractValidators",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Collection of all callable validators "
                    "for a single registered component"
                ),
                module_path="s0ma.verifiers.contracts",
                qualified_name=(
                    "s0ma.verifiers.contracts"
                    ".ContractValidators"
                ),
                source_file=verifiers_contracts_file,
                is_framework=True,
            ),
            ComponentSpec(
                name="ContractRegistry",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Stores executable contract validators "
                    "linked to component names for verification"
                ),
                contracts=Contract(
                    invariants=[
                        "thread-safe write operations via "
                        "threading.Lock",
                    ],
                ),
                module_path="s0ma.verifiers.contracts",
                qualified_name=(
                    "s0ma.verifiers.contracts"
                    ".ContractRegistry"
                ),
                source_file=verifiers_contracts_file,
                is_framework=True,
            ),
            ComponentSpec(
                name="ContractVerifier",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Verifies component contracts: coverage "
                    "reporting and performance/error validation"
                ),
                contracts=Contract(
                    preconditions=["registry is not None"],
                    postconditions=[
                        "returns VerificationResult with "
                        "contract coverage details",
                    ],
                ),
                dependencies=[
                    "ComponentRegistry",
                    "VerificationResult",
                    "Anomaly",
                ],
                module_path="s0ma.verifiers.contracts",
                qualified_name=(
                    "s0ma.verifiers.contracts"
                    ".ContractVerifier"
                ),
                source_file=verifiers_contracts_file,
                is_framework=True,
            ),
        ])

    # --- Phase 2 M4: Interoception monitor entities ---
    if verifiers_interoception_file is not None:
        specs.extend([
            ComponentSpec(
                name="ComponentMetrics",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Collected runtime metrics for a single component "
                    "including latency percentiles and error rates"
                ),
                module_path="s0ma.verifiers.interoception",
                qualified_name=(
                    "s0ma.verifiers.interoception"
                    ".ComponentMetrics"
                ),
                source_file=verifiers_interoception_file,
                is_framework=True,
            ),
            ComponentSpec(
                name="MetricsCollector",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Thread-safe collector of per-component "
                    "runtime performance metrics"
                ),
                contracts=Contract(
                    invariants=[
                        "thread-safe write operations via "
                        "threading.Lock",
                    ],
                ),
                dependencies=[
                    "Anomaly",
                    "ResourceProfile",
                ],
                module_path="s0ma.verifiers.interoception",
                qualified_name=(
                    "s0ma.verifiers.interoception"
                    ".MetricsCollector"
                ),
                source_file=verifiers_interoception_file,
                is_framework=True,
            ),
            ComponentSpec(
                name="InteroceptionVerifier",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Runtime monitoring verifier comparing "
                    "metrics against declared ResourceProfile"
                ),
                contracts=Contract(
                    preconditions=["registry is not None"],
                    postconditions=[
                        "returns VerificationResult with "
                        "interoception anomalies",
                    ],
                ),
                dependencies=[
                    "ComponentRegistry",
                    "VerificationResult",
                    "Anomaly",
                ],
                module_path="s0ma.verifiers.interoception",
                qualified_name=(
                    "s0ma.verifiers.interoception"
                    ".InteroceptionVerifier"
                ),
                source_file=verifiers_interoception_file,
                is_framework=True,
            ),
            ComponentSpec(
                name="DangerSignal",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Aickelin's danger signal for adaptive "
                    "monitoring based on component criticality"
                ),
                module_path="s0ma.verifiers.interoception",
                qualified_name=(
                    "s0ma.verifiers.interoception"
                    ".DangerSignal"
                ),
                source_file=verifiers_interoception_file,
                is_framework=True,
            ),
        ])

    # --- Phase 2 M5: Coverage auditor entity ---
    if verifiers_coverage_file is not None:
        specs.append(
            ComponentSpec(
                name="CoverageAuditor",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Coverage auditor detecting dead code and "
                    "pathologies using the biological taxonomy"
                ),
                contracts=Contract(
                    preconditions=["registry is not None"],
                    postconditions=[
                        "returns VerificationResult with "
                        "coverage anomalies and automation metric",
                    ],
                ),
                dependencies=[
                    "ComponentRegistry",
                    "VerificationResult",
                    "Anomaly",
                    "MetricsCollector",
                ],
                module_path="s0ma.verifiers.coverage",
                qualified_name=(
                    "s0ma.verifiers.coverage"
                    ".CoverageAuditor"
                ),
                source_file=verifiers_coverage_file,
                is_framework=True,
            )
        )

    # --- Phase 2.5: Lifecycle package entities ---

    # LifecycleEvent model in models.py
    specs.append(
        ComponentSpec(
            name="LifecycleEvent",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent=(
                "Records a lifecycle operation (register, unregister, update, "
                "create) for audit logging and rollback reference"
            ),
            module_path="s0ma.models",
            qualified_name="s0ma.models.LifecycleEvent",
            source_file=models_file,
            is_framework=True,
        ),
    )

    lifecycle_manager_file: str | None = None
    if lifecycle_manager_module is not None:
        lifecycle_manager_file = inspect.getfile(
            lifecycle_manager_module  # type: ignore[arg-type]
        )

    lifecycle_transaction_file: str | None = None
    if lifecycle_transaction_module is not None:
        lifecycle_transaction_file = inspect.getfile(
            lifecycle_transaction_module  # type: ignore[arg-type]
        )

    if lifecycle_manager_file is not None:
        specs.append(
            ComponentSpec(
                name="LifecycleManager",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Orchestrates component lifecycle operations (create, update, "
                    "remove) with verification integration and automatic rollback"
                ),
                contracts=Contract(
                    preconditions=["registry is initialized"],
                    postconditions=[
                        "lifecycle events are recorded and registry "
                        "state is consistent after operation",
                    ],
                    invariants=[
                        "failed operations leave registry in pre-operation state",
                    ],
                ),
                dependencies=[
                    "ComponentRegistry",
                    "ComponentSpec",
                    "Contract",
                    "LifecycleEvent",
                    "ResourceProfile",
                ],
                module_path="s0ma.lifecycle.manager",
                qualified_name="s0ma.lifecycle.manager.LifecycleManager",
                source_file=lifecycle_manager_file,
                is_framework=True,
            )
        )

    if lifecycle_transaction_file is not None:
        specs.append(
            ComponentSpec(
                name="TransactionContext",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Transactional wrapper for multi-step lifecycle operations "
                    "with automatic rollback on failure"
                ),
                contracts=Contract(
                    invariants=[
                        "all operations roll back on exception, restoring pre-transaction state",
                    ],
                ),
                dependencies=[
                    "LifecycleManager",
                    "LifecycleEvent",
                    "ComponentSpec",
                    "Contract",
                    "ResourceProfile",
                ],
                module_path="s0ma.lifecycle.transaction",
                qualified_name=(
                    "s0ma.lifecycle.transaction.TransactionContext"
                ),
                source_file=lifecycle_transaction_file,
                is_framework=True,
            )
        )

    # --- Phase 3A: Self-Model API entities ---

    self_model_interface_file: str | None = None
    if self_model_interface_module is not None:
        self_model_interface_file = inspect.getfile(
            self_model_interface_module  # type: ignore[arg-type]
        )

    self_model_analyzers_file: str | None = None
    if self_model_analyzers_module is not None:
        self_model_analyzers_file = inspect.getfile(
            self_model_analyzers_module  # type: ignore[arg-type]
        )

    if self_model_interface_file is not None:
        specs.append(
            ComponentSpec(
                name="SelfModelInterface",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Python-native self-model query interface producing "
                    "natural language text optimized for LLM consumption, "
                    "including audience-aware output for code generation "
                    "and agent contexts"
                ),
                contracts=Contract(
                    postconditions=[
                        "all methods return str (text, not data structures)",
                        "describe_system() includes component counts and layer breakdown",
                        "describe_component() raises RegistryIntegrityError for unknown names",
                        "describe_for_code_generation() annotates framework components "
                        "as non-importable and includes @component decorator template",
                        "describe_for_agent() dispatches to the appropriate method "
                        "based on context argument",
                        "describe_docs() summarises all registered doc-refs, "
                        "doc-guides, and examples",
                        "describe_doc(name) returns detail for a doc-ref or "
                        "doc-guide and an informative not-found message for "
                        "unknown names (does not raise)",
                        "get_docs_for_component(name) and "
                        "get_examples_for_component(name) surface M4 "
                        "reverse-index matches as natural-language text",
                        "get_drift_status() reports per-doc content-hash "
                        "presence; transitive recomputation lands with M7",
                    ],
                ),
                dependencies=[
                    "ComponentRegistry",
                    "LifecycleManager",
                    "Anomaly",
                    "ComponentSpec",
                    "MetricsCollector",
                    "VerificationReport",
                ],
                module_path="s0ma.self_model.interface",
                qualified_name=(
                    "s0ma.self_model.interface.SelfModelInterface"
                ),
                source_file=self_model_interface_file,
                is_framework=True,
            )
        )

    if self_model_analyzers_file is not None:
        specs.extend([
            ComponentSpec(
                name="ImpactReport",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Structured impact analysis result describing what would "
                    "be affected if a component changes, including direct "
                    "and transitive dependents, affected layers, and "
                    "affected documentation and example artifacts"
                ),
                module_path="s0ma.self_model.analyzers",
                qualified_name=(
                    "s0ma.self_model.analyzers.ImpactReport"
                ),
                source_file=self_model_analyzers_file,
                is_framework=True,
            ),
            ComponentSpec(
                name="ExtensionPoint",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Describes a location in the architecture where a new "
                    "component can be added without violating constraints"
                ),
                module_path="s0ma.self_model.analyzers",
                qualified_name=(
                    "s0ma.self_model.analyzers.ExtensionPoint"
                ),
                source_file=self_model_analyzers_file,
                is_framework=True,
            ),
        ])

    # --- Phase 3B: Teaching capability entity ---

    teaching_file: str | None = None
    if teaching_module is not None:
        teaching_file = inspect.getfile(
            teaching_module  # type: ignore[arg-type]
        )

    if teaching_file is not None:
        specs.append(
            ComponentSpec(
                name="TeachingProvider",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Serves documentation and live registry examples for "
                    "teaching agents how to use the s0ma framework without "
                    "duplicating content"
                ),
                contracts=Contract(
                    postconditions=[
                        "all content is read from source files at query time",
                        "returns helpful message when docs files are unavailable",
                    ],
                ),
                dependencies=["ComponentRegistry"],
                module_path="s0ma.api.teaching",
                qualified_name=(
                    "s0ma.api.teaching.TeachingProvider"
                ),
                source_file=teaching_file,
                is_framework=True,
            )
        )

    # --- Phase 3B: Query Engine entity ---

    query_engine_file: str | None = None
    if query_engine_module is not None:
        query_engine_file = inspect.getfile(
            query_engine_module  # type: ignore[arg-type]
        )

    if query_engine_file is not None:
        specs.append(
            ComponentSpec(
                name="QueryEngine",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Rule-based natural language query engine that answers "
                    "questions about the system using keyword matching and "
                    "component name resolution"
                ),
                contracts=Contract(
                    postconditions=[
                        "query() always returns a non-empty str",
                        "handles all 9 question categories plus fallback",
                    ],
                ),
                dependencies=[
                    "ComponentRegistry",
                    "SelfModelInterface",
                    "MetricsCollector",
                    "TeachingProvider",
                ],
                module_path="s0ma.api.query_engine",
                qualified_name=(
                    "s0ma.api.query_engine.QueryEngine"
                ),
                source_file=query_engine_file,
                is_framework=True,
            )
        )

    # --- s0ma.testing entities ---

    testing_file: str | None = None
    if testing_module is not None:
        testing_file = inspect.getfile(
            testing_module  # type: ignore[arg-type]
        )

    if testing_file is not None:
        specs.extend([
            ComponentSpec(
                name="fresh_registry",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Context manager providing a clean registry with freshly-imported "
                    "modules, handling sys.modules eviction and restore for test isolation"
                ),
                contracts=Contract(
                    preconditions=[
                        "module_prefixes contains valid Python module name prefixes",
                    ],
                    postconditions=[
                        "yields a fresh ComponentRegistry with evicted modules re-registered",
                        "original global registry is restored on context manager exit",
                        "evicted modules are re-imported in sorted order (parents before children)",
                    ],
                ),
                dependencies=["ComponentRegistry"],
                module_path="s0ma.testing",
                qualified_name="s0ma.testing.fresh_registry",
                source_file=testing_file,
                is_framework=True,
            ),
            ComponentSpec(
                name="reinitialize_for_test",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Imperatively reset the global registry and re-import modules "
                    "for non-context-manager test isolation scenarios"
                ),
                contracts=Contract(
                    postconditions=[
                        "returns a fresh ComponentRegistry with evicted modules re-registered",
                        "caller is responsible for cleanup after use",
                    ],
                ),
                dependencies=["ComponentRegistry"],
                module_path="s0ma.testing",
                qualified_name="s0ma.testing.reinitialize_for_test",
                source_file=testing_file,
                is_framework=True,
            ),
            ComponentSpec(
                name="isolate_registry",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Context manager creating a temporary isolated registry scope "
                    "for tests that register synthetic components"
                ),
                contracts=Contract(
                    postconditions=[
                        "yields a fresh empty ComponentRegistry as the global singleton",
                        "original global registry is restored on context manager exit",
                        "no module eviction or re-import is performed",
                    ],
                ),
                dependencies=["ComponentRegistry"],
                module_path="s0ma.testing",
                qualified_name="s0ma.testing.isolate_registry",
                source_file=testing_file,
                is_framework=True,
            ),
        ])

    # --- s0ma.utils entities ---

    utils_file: str | None = None
    if utils_module is not None:
        utils_file = inspect.getfile(
            utils_module  # type: ignore[arg-type]
        )

    if utils_file is not None:
        specs.extend([
            ComponentSpec(
                name="topological_sort_modules",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Topologically sorts module paths by their declared dependencies "
                    "using Kahn's algorithm with cycle detection and reporting"
                ),
                contracts=Contract(
                    preconditions=[
                        "module_specs is a list of (module_path, dependency_paths) tuples",
                    ],
                    postconditions=[
                        "returns module paths in dependency-safe import order",
                        "raises RegistrationError on circular dependencies with cycle info",
                    ],
                ),
                module_path="s0ma.utils",
                qualified_name="s0ma.utils.topological_sort_modules",
                source_file=utils_file,
                is_framework=True,
            ),
            ComponentSpec(
                name="bootstrap_modules",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Imports modules in dependency-safe order and registers their "
                    "components, replacing manually-ordered module lists"
                ),
                contracts=Contract(
                    preconditions=[
                        "module_paths contains valid importable Python module paths",
                    ],
                    postconditions=[
                        "all modules are imported and their components registered "
                        "in dependency-safe order",
                        "returns list of all newly registered ComponentSpec objects",
                        "raises RegistrationError on circular module dependencies",
                    ],
                ),
                dependencies=[
                    "ComponentRegistry",
                    "ComponentSpec",
                ],
                module_path="s0ma.utils",
                qualified_name="s0ma.utils.bootstrap_modules",
                source_file=utils_file,
                is_framework=True,
            ),
        ])

    # --- Plan M6: Example execution subsystem entities ---

    examples_runner_file: str | None = None
    if examples_runner_module is not None:
        examples_runner_file = inspect.getfile(
            examples_runner_module  # type: ignore[arg-type]
        )

    examples_dispatcher_file: str | None = None
    if examples_dispatcher_module is not None:
        examples_dispatcher_file = inspect.getfile(
            examples_dispatcher_module  # type: ignore[arg-type]
        )

    examples_timeout_file: str | None = None
    if examples_timeout_module is not None:
        examples_timeout_file = inspect.getfile(
            examples_timeout_module  # type: ignore[arg-type]
        )

    if examples_timeout_file is not None:
        specs.append(
            ComponentSpec(
                name="TimeoutResult",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Uniform subprocess outcome representation including "
                    "returncode, captured stdout/stderr, duration, and "
                    "whether the process was killed for exceeding its "
                    "timeout budget"
                ),
                contracts=Contract(
                    invariants=[
                        "returncode is -1 whenever timed_out is True",
                    ],
                ),
                module_path="s0ma.examples.timeout",
                qualified_name="s0ma.examples.timeout.TimeoutResult",
                source_file=examples_timeout_file,
                is_framework=True,
            )
        )

    if examples_dispatcher_file is not None:
        specs.extend([
            ComponentSpec(
                name="DispatchOutcome",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Raw per-dispatch result pairing a TimeoutResult with the "
                    "effective runs_in mode that produced it"
                ),
                dependencies=["TimeoutResult"],
                module_path="s0ma.examples.dispatcher",
                qualified_name="s0ma.examples.dispatcher.DispatchOutcome",
                source_file=examples_dispatcher_file,
                is_framework=True,
            ),
            ComponentSpec(
                name="ExampleDispatcher",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Routes an ExampleRegistration to the correct subprocess "
                    "runner based on its runs_in field (standalone, pytest, "
                    "or integration)"
                ),
                contracts=Contract(
                    postconditions=[
                        "dispatch() always returns a DispatchOutcome capturing "
                        "stdout, stderr, returncode, and timed_out",
                    ],
                    invariants=[
                        "each dispatch writes the example body to a temporary "
                        "directory that is cleaned up on return",
                    ],
                ),
                dependencies=["ExampleRegistration", "TimeoutResult"],
                module_path="s0ma.examples.dispatcher",
                qualified_name="s0ma.examples.dispatcher.ExampleDispatcher",
                source_file=examples_dispatcher_file,
                is_framework=True,
            ),
        ])

    if examples_runner_file is not None:
        specs.extend([
            ComponentSpec(
                name="ExampleResult",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Structured outcome of a single example execution, "
                    "carrying pass/fail summary, captured stdout/stderr, "
                    "duration, return code, and timeout state"
                ),
                contracts=Contract(
                    invariants=[
                        "passed is True iff returncode == 0 and not timed_out",
                    ],
                ),
                module_path="s0ma.examples.runner",
                qualified_name="s0ma.examples.runner.ExampleResult",
                source_file=examples_runner_file,
                is_framework=True,
            ),
            ComponentSpec(
                name="ExampleRunner",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent=(
                    "Discovers registered examples from a registry snapshot "
                    "and executes each body in an isolated subprocess with "
                    "per-example timeout enforcement"
                ),
                contracts=Contract(
                    preconditions=["registry is initialized"],
                    postconditions=[
                        "discover() returns the ExampleRegistration list from "
                        "the current snapshot",
                        "run_all() returns one ExampleResult per discovered "
                        "example and never raises on example failure or timeout",
                    ],
                    invariants=[
                        "example bodies execute in a child process, never in "
                        "the runner's interpreter",
                    ],
                ),
                dependencies=[
                    "ComponentRegistry",
                    "ExampleRegistration",
                    "ExampleDispatcher",
                    "ExampleResult",
                    "TimeoutResult",
                ],
                module_path="s0ma.examples.runner",
                qualified_name="s0ma.examples.runner.ExampleRunner",
                source_file=examples_runner_file,
                is_framework=True,
            ),
        ])

    # s0ma.examples.plugin is an opt-in pytest11 plugin. Its
    # hook-protocol functions are allowlisted in _verifier.py; the only
    # other public entity it defines is _S0maExampleItem, which is
    # underscore-prefixed and therefore skipped by the blind-spot scan.
    # No bootstrap registration is required for the plugin module.
    _ = examples_plugin_module

    return specs
