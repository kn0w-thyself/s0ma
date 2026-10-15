"""Self-description verifier — the framework examining itself.

Implements the verification logic that checks whether the registry
accurately represents the s0ma codebase. This is the core of the
bootstrap test: if this verifier reports anomalies, the system cannot
accurately describe itself.

Phase 2 note: This module is now a thin wrapper around the structural
verifier in s0ma.verifiers.structural. It preserves the Phase 1
public API (verify_self_model) for backward compatibility while
delegating to the new verifier framework internally.

The AST scanning utilities (_scan_module_for_public_entities, etc.)
remain here as they are used by both the bootstrap verification and
the structural verifier's blind spot detection.

Verification checks:
1. No phantom limbs: every registered component has corresponding source code.
2. No blind spots: every public entity is registered, exempt, or accounted for.
3. Metadata accuracy: module paths, qualified names, and source files are correct.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma.models import Anomaly
from s0ma.types import AnomalyKind, AnomalySeverity

if TYPE_CHECKING:
    from collections.abc import Mapping

    from s0ma.models import ComponentSpec
    from s0ma.registry import ComponentRegistry

__all__ = ["verify_self_model"]

# s0ma modules to scan for public entities.
# Private modules (starting with _) are not scanned — they are framework
# internals not subject to the registration requirement.
_S0MA_PUBLIC_MODULES = [
    "s0ma",             # __init__.py — public API surface
    "s0ma.models",
    "s0ma.registry",
    "s0ma.decorators",
    "s0ma.import_hook",
    "s0ma.exceptions",
    "s0ma.types",
    "s0ma.verifiers",              # Phase 2 verifier package
    "s0ma.verifiers.base",         # Verifier protocol
    "s0ma.verifiers.structural",   # Structural verifier
    "s0ma.verifiers.contracts",    # Contract verifier
    "s0ma.verifiers.interoception",  # Interoception monitor
    "s0ma.verifiers.coverage",       # Coverage auditor
    "s0ma.lifecycle",                # Phase 2.5 lifecycle package
    "s0ma.lifecycle.manager",        # LifecycleManager
    "s0ma.lifecycle.transaction",    # TransactionContext
    "s0ma.self_model",              # Phase 3A self-model query API
    "s0ma.self_model.interface",     # SelfModelInterface
    "s0ma.self_model.analyzers",     # Impact analysis, extension points
    "s0ma.self_model.formatters",    # Text formatters for LLM consumption
    "s0ma.api",                     # Phase 3B external API (lazy imports only)
    "s0ma.api.query_engine",         # Phase 3B natural language query engine
    "s0ma.utils",                    # Bootstrap and import-ordering utilities
    "s0ma.examples",                # Plan M6 example execution subsystem
    "s0ma.examples.runner",          # ExampleRunner / ExampleResult
    "s0ma.examples.dispatcher",      # ExampleDispatcher / DispatchOutcome
    "s0ma.examples.timeout",         # TimeoutResult + subprocess helpers
    "s0ma.examples.plugin",          # Opt-in pytest integration
    "s0ma.hashing",                 # Plan M7 content-hash subsystem
    "s0ma.hashing.canonical",        # Deterministic canonicalizer
    "s0ma.hashing.content_hash",     # Transitive content-hash utility
    "s0ma.anomaly_stream",          # hw-foundation runtime anomaly stream
]

# Base class names that make a class exempt from registration.
# Enums are structural (type vocabulary), exceptions are data.
_EXEMPT_BASE_NAMES = frozenset({
    # Enum family
    "Enum", "IntEnum", "StrEnum", "Flag", "IntFlag",
    # Exception family
    "Exception", "BaseException",
})

# Suffixes on base class names that indicate an exception subclass.
_EXCEPTION_SUFFIXES = ("Error", "Exception", "Warning")

# Public utility functions that are intentionally unregistered.
# These cannot use @internal due to circular import constraints
# (e.g., decorators.py imports registry.py — adding @internal to
# registry.py functions would create a circular import cycle).
# Each entry is a fully qualified name.
_KNOWN_UNREGISTERED_UTILITIES: frozenset[str] = frozenset({
    # s0ma/__init__.py — framework entry point
    "s0ma.initialize",
    "s0ma.verify",
    # s0ma/__init__.py — documentation subsystem wrappers (M2).
    # Thin forwarders over ComponentRegistry methods; analogous to
    # initialize/verify. Real registration lives on the registry.
    "s0ma.register_doc_ref",
    "s0ma.register_doc_guide",
    "s0ma.register_example",
    # registry.py — global singleton management
    "s0ma.registry.get_registry",
    "s0ma.registry.set_registry",
    "s0ma.registry.reset_registry",
    # decorators.py — introspection utilities
    "s0ma.decorators.is_component",
    "s0ma.decorators.is_internal",
    "s0ma.decorators.get_component_spec",
    "s0ma.decorators.get_all_components_in_module",
    # import_hook.py — hook lifecycle management
    "s0ma.import_hook.install_import_hook",
    "s0ma.import_hook.uninstall_import_hook",
    "s0ma.import_hook.is_hook_installed",
    # verifiers/__init__.py — verification orchestration functions
    "s0ma.verifiers.verify_all",
    "s0ma.verifiers.verify_structural",
    "s0ma.verifiers.verify_contracts",
    "s0ma.verifiers.verify_interoception",
    "s0ma.verifiers.verify_coverage",
    "s0ma.verifiers.verify_incremental",
    # verifiers/contracts.py — contract verification utilities
    "s0ma.verifiers.contracts.get_contract_registry",
    "s0ma.verifiers.contracts.reset_contract_registry",
    "s0ma.verifiers.contracts.is_contract_verification_enabled",
    "s0ma.verifiers.contracts.set_contract_verification",
    "s0ma.verifiers.contracts.precondition",
    "s0ma.verifiers.contracts.postcondition",
    "s0ma.verifiers.contracts.invariant",
    # verifiers/interoception.py — interoception monitor utilities
    "s0ma.verifiers.interoception.get_metrics_collector",
    "s0ma.verifiers.interoception.reset_metrics_collector",
    "s0ma.verifiers.interoception.instrument",
    "s0ma.verifiers.interoception.monitor_call",
    "s0ma.verifiers.interoception.compute_danger_signals",
    # anomaly_stream.py — runtime anomaly stream (hw-foundation M1).
    # Module-level subscription channel; follows the singleton-management
    # pattern of the contracts/interoception utilities above.
    "s0ma.anomaly_stream.subscribe_runtime_anomalies",
    "s0ma.anomaly_stream.emit_runtime_anomaly",
    "s0ma.anomaly_stream.reset_runtime_anomaly_subscribers",
    # self_model/analyzers.py — analysis utility functions
    "s0ma.self_model.analyzers.compute_impact_analysis",
    "s0ma.self_model.analyzers.find_extension_points",
    "s0ma.self_model.analyzers.validate_proposed_component",
    # self_model/formatters.py — text formatting utility functions
    "s0ma.self_model.formatters.format_component_summary",
    "s0ma.self_model.formatters.format_component_detail",
    "s0ma.self_model.formatters.format_dependency_graph_text",
    "s0ma.self_model.formatters.format_layer_breakdown",
    "s0ma.self_model.formatters.format_health_summary",
    "s0ma.self_model.formatters.format_contracts_text",
    "s0ma.self_model.formatters.format_impact_report",
    "s0ma.self_model.formatters.format_extension_points",
    "s0ma.self_model.formatters.format_lifecycle_events",
    "s0ma.self_model.formatters.format_dependency_graph_dot",
    "s0ma.self_model.formatters.format_code_generation_context",
    # self_model/formatters.py — M5 documentation-surface formatters
    "s0ma.self_model.formatters.format_doc_refs_overview",
    "s0ma.self_model.formatters.format_doc_ref_detail",
    "s0ma.self_model.formatters.format_doc_guide_detail",
    "s0ma.self_model.formatters.format_example_detail",
    "s0ma.self_model.formatters.format_docs_for_component",
    "s0ma.self_model.formatters.format_examples_for_component",
    "s0ma.self_model.formatters.format_drift_status",
    # api/__init__.py — external API entry points (optional dependencies)
    "s0ma.api.create_app",
    "s0ma.api.create_mcp_server",
    # api/query_engine.py — query classification and matching utilities
    "s0ma.api.query_engine.classify_query",
    # self_model/analyzers.py — explain_dependency_chain utility
    "s0ma.self_model.analyzers.explain_dependency_chain",
    # examples/runner.py — module-level convenience wrapper for ExampleRunner
    "s0ma.examples.runner.run_all_examples",
    # examples/timeout.py — cross-platform subprocess timeout helper
    "s0ma.examples.timeout.run_subprocess_with_timeout",
    # examples/plugin.py — pytest hook-protocol functions (opt-in plugin).
    # Naming is mandated by pytest; not registrable as components.
    "s0ma.examples.plugin.pytest_addoption",
    "s0ma.examples.plugin.pytest_collection_modifyitems",
    # hashing subpackage (M7) — module-level primitives. Both are pure
    # functions over immutable inputs; registering them as components
    # would add cycles through models.py without adding verification
    # value. They follow the same pattern as formatters + run_all_examples.
    "s0ma.hashing.canonicalize",
    "s0ma.hashing.content_hash",
    "s0ma.hashing.canonical.canonicalize",
    "s0ma.hashing.content_hash.content_hash",
})


def verify_self_model(registry: ComponentRegistry) -> list[Anomaly]:
    """Verify that the registry accurately represents the s0ma codebase.

    This is the core verification function for the bootstrap test. It
    performs three categories of checks:

    1. **No phantom limbs:** Every registered framework component has
       corresponding source code that can be resolved via its
       qualified_name.
    2. **No blind spots:** Every public class/function in s0ma source
       is either registered, exempt (enum/exception), or explicitly
       accounted for as a known utility.
    3. **Metadata accuracy:** Module paths, qualified names, and source
       file paths are correct for every registered component.

    Args:
        registry: The ComponentRegistry to verify.

    Returns:
        List of Anomaly objects describing any discrepancies found.
        An empty list means the system accurately describes itself.
    """
    anomalies: list[Anomaly] = []

    # Build lookup sets from the registry
    framework_specs = {
        name: spec
        for name, spec in registry.get_all().items()
        if spec.is_framework
    }
    registered_qualified_names = {
        spec.qualified_name for spec in framework_specs.values()
    }

    # Phase 1: No phantom limbs
    anomalies.extend(_check_no_phantom_limbs(framework_specs))

    # Phase 2: No blind spots
    anomalies.extend(
        _check_no_blind_spots(registered_qualified_names)
    )

    # Phase 3: Metadata accuracy
    anomalies.extend(_check_metadata_accuracy(framework_specs))

    return anomalies


def _check_no_phantom_limbs(
    framework_specs: Mapping[str, ComponentSpec],
) -> list[Anomaly]:
    """Verify every registered component has corresponding source code.

    A phantom limb is a registry entry with no matching code entity.
    This checks that each component's qualified_name resolves to a real
    attribute in a real module.
    """
    anomalies: list[Anomaly] = []

    for name, spec in framework_specs.items():

        # Split qualified_name into module and attribute
        parts = spec.qualified_name.rsplit(".", 1)
        if len(parts) != 2:
            anomalies.append(Anomaly(
                kind=AnomalyKind.PHANTOM_LIMB,
                severity=AnomalySeverity.ERROR,
                component_name=name,
                message=(
                    f"Component '{name}' has invalid qualified_name "
                    f"'{spec.qualified_name}' (cannot split into module.attr)"
                ),
            ))
            continue

        module_path, attr_name = parts

        # Verify the module can be imported
        try:
            mod = importlib.import_module(module_path)
        except ImportError:
            anomalies.append(Anomaly(
                kind=AnomalyKind.PHANTOM_LIMB,
                severity=AnomalySeverity.ERROR,
                component_name=name,
                message=(
                    f"Component '{name}' references module "
                    f"'{module_path}' which cannot be imported"
                ),
            ))
            continue

        # Verify the attribute exists in the module
        if not hasattr(mod, attr_name):
            anomalies.append(Anomaly(
                kind=AnomalyKind.PHANTOM_LIMB,
                severity=AnomalySeverity.ERROR,
                component_name=name,
                message=(
                    f"Component '{name}' references '{attr_name}' "
                    f"in module '{module_path}' but no such attribute exists"
                ),
            ))
            continue

        # Verify the source file exists on disk
        if spec.source_file is not None:
            source_path = Path(spec.source_file)
            if not source_path.exists():
                anomalies.append(Anomaly(
                    kind=AnomalyKind.PHANTOM_LIMB,
                    severity=AnomalySeverity.WARNING,
                    component_name=name,
                    message=(
                        f"Component '{name}' source file does not exist: "
                        f"{spec.source_file}"
                    ),
                ))

    return anomalies


def _check_no_blind_spots(
    registered_qualified_names: set[str],
) -> list[Anomaly]:
    """Verify every public entity in s0ma is accounted for.

    A blind spot is a public class or function that exists in source
    but is not registered, not exempt (enum/exception), and not in
    the known utilities list.
    """
    anomalies: list[Anomaly] = []

    for module_name in _S0MA_PUBLIC_MODULES:
        source_entities = _scan_module_for_public_entities(module_name)

        seen: set[str] = set()
        for entity_name, entity_kind, is_exempt in source_entities:
            qualified = f"{module_name}.{entity_name}"

            # Deduplicate (e.g., @overload produces multiple defs)
            if qualified in seen:
                continue
            seen.add(qualified)

            # Check if registered
            if qualified in registered_qualified_names:
                continue

            # Check if exempt (enum, exception)
            if is_exempt:
                continue

            # Check if known utility function
            if qualified in _KNOWN_UNREGISTERED_UTILITIES:
                continue

            # This is a blind spot
            anomalies.append(Anomaly(
                kind=AnomalyKind.IMMUNE_RESPONSE,
                severity=AnomalySeverity.ERROR,
                component_name=None,
                message=(
                    f"Blind spot: public {entity_kind} '{entity_name}' "
                    f"in module '{module_name}' is not registered as a "
                    f"component, not exempt, and not in the known "
                    f"utilities list"
                ),
                details={
                    "module": module_name,
                    "entity": entity_name,
                    "entity_kind": entity_kind,
                    "qualified_name": qualified,
                },
            ))

    return anomalies


def _check_metadata_accuracy(
    framework_specs: Mapping[str, ComponentSpec],
) -> list[Anomaly]:
    """Verify module paths and source files match reality.

    Checks that each component's module_path can be imported and that
    the registered source_file matches the actual file for that module.
    """
    anomalies: list[Anomaly] = []

    for name, spec in framework_specs.items():

        # Verify module_path is importable
        try:
            mod = importlib.import_module(spec.module_path)
        except ImportError:
            anomalies.append(Anomaly(
                kind=AnomalyKind.PHANTOM_LIMB,
                severity=AnomalySeverity.ERROR,
                component_name=name,
                message=(
                    f"Component '{name}' module_path '{spec.module_path}' "
                    f"cannot be imported"
                ),
            ))
            continue

        # Verify source file matches the module's actual file
        if spec.source_file is not None:
            actual_file = inspect.getfile(mod)
            spec_resolved = str(Path(spec.source_file).resolve())
            actual_resolved = str(Path(actual_file).resolve())
            if spec_resolved != actual_resolved:
                anomalies.append(Anomaly(
                    kind=AnomalyKind.PHANTOM_LIMB,
                    severity=AnomalySeverity.WARNING,
                    component_name=name,
                    message=(
                        f"Component '{name}' source_file mismatch: "
                        f"registered='{spec.source_file}', "
                        f"actual='{actual_file}'"
                    ),
                ))

    return anomalies


def _scan_module_for_public_entities(
    module_name: str,
) -> list[tuple[str, str, bool]]:
    """Scan a module's source for public class and function definitions.

    Uses the ``ast`` module to parse the source file and extract
    top-level class and function definitions. Each entity is classified
    as exempt or not based on its inheritance (enums and exceptions are
    exempt from registration).

    Args:
        module_name: Fully qualified module name.

    Returns:
        List of ``(entity_name, entity_kind, is_exempt)`` tuples.
        ``entity_kind`` is ``"class"`` or ``"function"``.
        ``is_exempt`` is True for enums, exceptions, etc.
    """
    mod = importlib.import_module(module_name)
    source_file = inspect.getfile(mod)

    with open(source_file, encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source, filename=source_file)
    entities: list[tuple[str, str, bool]] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            is_exempt = _is_exempt_class(node)
            entities.append((node.name, "class", is_exempt))

        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name.startswith("_"):
                continue
            entities.append((node.name, "function", False))

    return entities


def _is_exempt_class(node: ast.ClassDef) -> bool:
    """Check if a class definition is exempt from registration.

    Classes inheriting from Enum or Exception families are exempt.
    They are structural vocabulary or data types, not behavioral
    components.
    """
    for base in node.bases:
        base_name = _get_base_name(base)
        if base_name is None:
            continue

        # Direct match against known exempt bases
        if base_name in _EXEMPT_BASE_NAMES:
            return True

        # Check for exception subclasses (e.g., S0maError)
        if any(base_name.endswith(suffix) for suffix in _EXCEPTION_SUFFIXES):
            return True

    return False


def _get_base_name(node: ast.expr) -> str | None:
    """Extract the simple name from a base class AST node.

    Handles both simple names (``Name``) and dotted names
    (``Attribute``).
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None
