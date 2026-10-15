"""Milestone 1 structural checks — per-component verification functions.

Contains the check functions for:
- Phantom limb detection (registry entry with no code)
- Signature verification (declared vs actual types)
- Dependency accuracy (declared vs actual imports)
- Metadata accuracy (module paths, source files)
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma.models import Anomaly
from s0ma.types import AnomalyKind, AnomalySeverity

if TYPE_CHECKING:
    from s0ma.models import ComponentSpec
    from s0ma.registry import ComponentRegistry

__all__: list[str] = []  # All functions are internal


def check_phantom_limb(
    spec: ComponentSpec,
) -> tuple[list[Anomaly], int]:
    """Check if a registered component has corresponding source code.

    Returns:
        Tuple of (anomalies found, number of checks performed).
    """
    anomalies: list[Anomaly] = []
    checks = 0

    # Check qualified_name resolves
    checks += 1
    parts = spec.qualified_name.rsplit(".", 1)
    if len(parts) != 2:
        anomalies.append(Anomaly(
            kind=AnomalyKind.PHANTOM_LIMB,
            severity=AnomalySeverity.ERROR,
            component_name=spec.name,
            message=(
                f"Component '{spec.name}' has invalid qualified_name "
                f"'{spec.qualified_name}' (cannot split into module.attr)"
            ),
        ))
        return anomalies, checks

    module_path, attr_name = parts

    # Verify the module can be imported
    checks += 1
    try:
        mod = importlib.import_module(module_path)
    except ImportError:
        anomalies.append(Anomaly(
            kind=AnomalyKind.PHANTOM_LIMB,
            severity=AnomalySeverity.ERROR,
            component_name=spec.name,
            message=(
                f"Component '{spec.name}' references module "
                f"'{module_path}' which cannot be imported"
            ),
        ))
        return anomalies, checks

    # Verify the attribute exists in the module
    checks += 1
    if not hasattr(mod, attr_name):
        anomalies.append(Anomaly(
            kind=AnomalyKind.PHANTOM_LIMB,
            severity=AnomalySeverity.ERROR,
            component_name=spec.name,
            message=(
                f"Component '{spec.name}' references '{attr_name}' "
                f"in module '{module_path}' but no such attribute exists"
            ),
        ))
        return anomalies, checks

    # Verify the source file exists on disk
    if spec.source_file is not None:
        checks += 1
        source_path = Path(spec.source_file)
        if not source_path.exists():
            anomalies.append(Anomaly(
                kind=AnomalyKind.PHANTOM_LIMB,
                severity=AnomalySeverity.WARNING,
                component_name=spec.name,
                message=(
                    f"Component '{spec.name}' source file does not exist: "
                    f"{spec.source_file}"
                ),
            ))

    return anomalies, checks


def check_signatures(
    spec: ComponentSpec,
) -> tuple[list[Anomaly], int, list[str]]:
    """Check function/method signature against declared contract types.

    Compares the actual callable's signature (via inspect.signature())
    against Contract.input_type and Contract.output_type if declared.

    Returns:
        Tuple of (anomalies, checks_performed, convergences).
    """
    anomalies: list[Anomaly] = []
    checks = 0
    convergences: list[str] = []

    contract = spec.contracts
    if contract.input_type is None and contract.output_type is None:
        return anomalies, checks, convergences

    entity = _resolve_entity(spec)
    if entity is None:
        return anomalies, checks, convergences

    try:
        sig = inspect.signature(entity)
    except (ValueError, TypeError):
        return anomalies, checks, convergences

    # Check input_type
    if contract.input_type is not None:
        checks += 1
        params = [
            p for p in sig.parameters.values()
            if p.name not in ("self", "cls")
        ]
        param_annotations = [
            p.annotation for p in params
            if p.annotation != inspect.Parameter.empty
        ]
        annotation_names = [
            _get_annotation_name(a) for a in param_annotations
        ]

        declared_params = _declared_parameter_names(contract.input_type)
        if declared_params is not None:
            # The documented ``"name: type, name: type"`` form names the
            # parameters; compare those names with the signature's.
            actual_params = [p.name for p in params]
            if declared_params != actual_params:
                anomalies.append(Anomaly(
                    kind=AnomalyKind.PHANTOM_LIMB,
                    severity=AnomalySeverity.WARNING,
                    component_name=spec.name,
                    message=(
                        f"Component '{spec.name}' declares input_type "
                        f"'{contract.input_type}' but actual parameters "
                        f"are: {actual_params}"
                    ),
                    details={
                        "declared_input_type": contract.input_type,
                        "declared_parameters": declared_params,
                        "actual_parameters": actual_params,
                        "actual_annotations": annotation_names,
                    },
                ))
            else:
                convergences.append(
                    f"{spec.name}: input_type "
                    f"'{contract.input_type}' matches"
                )
        elif annotation_names and contract.input_type not in annotation_names:
            anomalies.append(Anomaly(
                kind=AnomalyKind.PHANTOM_LIMB,
                severity=AnomalySeverity.WARNING,
                component_name=spec.name,
                message=(
                    f"Component '{spec.name}' declares input_type "
                    f"'{contract.input_type}' but actual parameter "
                    f"annotations are: {annotation_names}"
                ),
                details={
                    "declared_input_type": contract.input_type,
                    "actual_annotations": annotation_names,
                },
            ))
        elif annotation_names:
            convergences.append(
                f"{spec.name}: input_type "
                f"'{contract.input_type}' matches"
            )

    # Check output_type
    if contract.output_type is not None:
        checks += 1
        return_annotation = sig.return_annotation
        if return_annotation != inspect.Parameter.empty:
            actual_return_name = _get_annotation_name(return_annotation)
            if actual_return_name != contract.output_type:
                anomalies.append(Anomaly(
                    kind=AnomalyKind.PHANTOM_LIMB,
                    severity=AnomalySeverity.WARNING,
                    component_name=spec.name,
                    message=(
                        f"Component '{spec.name}' declares output_type "
                        f"'{contract.output_type}' but actual return "
                        f"annotation is '{actual_return_name}'"
                    ),
                    details={
                        "declared_output_type": contract.output_type,
                        "actual_return_type": actual_return_name,
                    },
                ))
            else:
                convergences.append(
                    f"{spec.name}: output_type "
                    f"'{contract.output_type}' matches"
                )

    return anomalies, checks, convergences


def check_dependency_accuracy(
    spec: ComponentSpec,
    registry: ComponentRegistry,
) -> tuple[list[Anomaly], int, list[str]]:
    """Check dependency declarations against actual imports.

    Detects:
    - Undeclared dependencies: imports a registered component not in deps
    - Phantom dependencies: declares a dep it doesn't actually import
    - Missing dependencies: declares a dep that isn't registered

    An import is charged to the component only when the component's own
    top-level definition (the class, function or assignment named by its
    ``qualified_name``) references the imported name — in its body,
    defaults, base classes, nested decorators or annotations, string
    annotations included — and not merely because the module imports it
    for a sibling. The definition's own decorator list is excluded, since
    that is the registration call. Self-imports (``from <own module>
    import …``) are never charged. When the definition cannot be found,
    every import of the module counts, as before.

    A declared dependency is satisfied when the component imports it, when
    its definition references it directly (a sibling in the same module),
    or when its definition references a name imported from the
    dependency's module (a factory such as ``get_registry``).

    Returns:
        Tuple of (anomalies, checks_performed, convergences).
    """
    anomalies: list[Anomaly] = []
    checks = 0
    convergences: list[str] = []

    if not spec.module_path:
        return anomalies, checks, convergences

    source = _load_module_source(spec.module_path)
    if source is None:
        return anomalies, checks, convergences

    all_registered = set(registry.get_all().keys())
    referenced = source.referenced_names(_definition_name(spec))
    if referenced is None:
        actual_imports = source.names
    else:
        actual_imports = set()
        for local, (module, original) in source.bindings.items():
            if local in referenced:
                actual_imports.update((local, original, module))
    imported_components = _find_imported_components(
        actual_imports, all_registered, registry
    )
    declared_deps = set(spec.dependencies)
    satisfied_deps = set(imported_components)
    if referenced is not None:
        for dep in declared_deps - satisfied_deps:
            if _definition_references_dependency(
                referenced, source, registry.get(dep), dep
            ):
                satisfied_deps.add(dep)

    # Check for undeclared dependencies
    checks += 1
    undeclared = imported_components - declared_deps - {spec.name}
    for dep in sorted(undeclared):
        anomalies.append(Anomaly(
            kind=AnomalyKind.IMMUNE_RESPONSE,
            severity=AnomalySeverity.WARNING,
            component_name=spec.name,
            message=(
                f"Component '{spec.name}' imports '{dep}' but does not "
                f"declare it as a dependency"
            ),
            details={
                "undeclared_dependency": dep,
                "declared_dependencies": sorted(declared_deps),
            },
        ))

    # Check for phantom dependencies
    checks += 1
    phantom_deps = declared_deps - satisfied_deps
    for dep in sorted(phantom_deps):
        if dep in all_registered:
            anomalies.append(Anomaly(
                kind=AnomalyKind.VESTIGIAL_ORGAN,
                severity=AnomalySeverity.WARNING,
                component_name=spec.name,
                message=(
                    f"Component '{spec.name}' declares dependency "
                    f"on '{dep}' but does not import it"
                ),
                details={
                    "phantom_dependency": dep,
                    "actual_imports": sorted(imported_components),
                },
            ))

    # Check for missing dependencies (declared but not registered)
    checks += 1
    for dep in sorted(declared_deps):
        if dep not in all_registered:
            anomalies.append(Anomaly(
                kind=AnomalyKind.PHANTOM_LIMB,
                severity=AnomalySeverity.INFO,
                component_name=spec.name,
                message=(
                    f"Component '{spec.name}' declares dependency "
                    f"on '{dep}' which is not registered"
                ),
                details={"missing_dependency": dep},
            ))

    # Record convergences
    accurate_deps = declared_deps & satisfied_deps
    for dep in sorted(accurate_deps):
        convergences.append(
            f"{spec.name}: dependency '{dep}' correctly declared"
        )

    return anomalies, checks, convergences


def check_metadata_accuracy(
    spec: ComponentSpec,
) -> tuple[list[Anomaly], int, list[str]]:
    """Check module path and source file accuracy.

    Returns:
        Tuple of (anomalies, checks_performed, convergences).
    """
    anomalies: list[Anomaly] = []
    checks = 0
    convergences: list[str] = []

    if not spec.module_path:
        return anomalies, checks, convergences

    checks += 1
    try:
        mod = importlib.import_module(spec.module_path)
    except ImportError:
        anomalies.append(Anomaly(
            kind=AnomalyKind.PHANTOM_LIMB,
            severity=AnomalySeverity.ERROR,
            component_name=spec.name,
            message=(
                f"Component '{spec.name}' module_path "
                f"'{spec.module_path}' cannot be imported"
            ),
        ))
        return anomalies, checks, convergences

    convergences.append(
        f"{spec.name}: module_path '{spec.module_path}' importable"
    )

    if spec.source_file is not None:
        checks += 1
        try:
            actual_file = inspect.getfile(mod)
        except TypeError:
            return anomalies, checks, convergences

        spec_resolved = str(Path(spec.source_file).resolve())
        actual_resolved = str(Path(actual_file).resolve())
        if spec_resolved != actual_resolved:
            anomalies.append(Anomaly(
                kind=AnomalyKind.PHANTOM_LIMB,
                severity=AnomalySeverity.WARNING,
                component_name=spec.name,
                message=(
                    f"Component '{spec.name}' source_file mismatch: "
                    f"registered='{spec.source_file}', "
                    f"actual='{actual_file}'"
                ),
            ))
        else:
            convergences.append(
                f"{spec.name}: source_file matches actual module location"
            )

    return anomalies, checks, convergences


# ======================================================================
# Helper functions (used by the check functions above)
# ======================================================================


def _resolve_entity(spec: ComponentSpec) -> Any:
    """Resolve a ComponentSpec's qualified_name to the actual entity."""
    parts = spec.qualified_name.rsplit(".", 1)
    if len(parts) != 2:
        return None

    module_path, attr_name = parts
    try:
        mod = importlib.import_module(module_path)
    except ImportError:
        return None

    return getattr(mod, attr_name, None)


def _get_annotation_name(annotation: Any) -> str:
    """Extract a readable name from a type annotation."""
    if isinstance(annotation, str):
        return annotation
    if isinstance(annotation, type):
        return annotation.__name__
    if hasattr(annotation, "__name__"):
        result: str = annotation.__name__
        return result
    return str(annotation)


def _declared_parameter_names(input_type: str) -> list[str] | None:
    """Read the parameter names out of a ``"name: type, name: type"`` string.

    Returns ``None`` when ``input_type`` is a bare type (no ``:`` at the
    top level), which keeps the whole-string comparison for that form.
    """
    parts = _split_top_level(input_type)
    if not any(":" in part for part in parts):
        return None
    names: list[str] = []
    for part in parts:
        head = part.split(":", 1)[0].strip()
        if head:
            names.append(head)
    return names


def _split_top_level(text: str) -> list[str]:
    """Split ``text`` on commas outside brackets."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(depth - 1, 0)
        if ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail or not parts:
        parts.append(tail)
    return parts


@dataclass
class _ModuleSource:
    """A module's source as the dependency check reads it.

    ``bindings`` maps each local import name to ``(module, original)``;
    ``names`` is every imported name the module-wide fallback charges;
    ``definitions`` maps each top-level name to the node that defines it.
    """

    source_file: str
    bindings: dict[str, tuple[str, str]]
    names: set[str]
    definitions: dict[str, ast.AST]
    _references: dict[str, frozenset[str] | None] = field(default_factory=dict)

    def referenced_names(self, definition_name: str) -> frozenset[str] | None:
        """Names the top-level definition references, or ``None`` if absent."""
        if definition_name not in self._references:
            node = self.definitions.get(definition_name)
            self._references[definition_name] = (
                None if node is None else _names_referenced_by(node)
            )
        return self._references[definition_name]


# One parsed module per path, keyed on the file's modification time so an
# edited file is re-read and an unchanged one is parsed once per process.
_MODULE_SOURCE_CACHE: dict[str, tuple[str, float, _ModuleSource]] = {}


def _load_module_source(module_path: str) -> _ModuleSource | None:
    """Parse ``module_path``'s source once and cache the result."""
    try:
        mod = importlib.import_module(module_path)
        source_file = inspect.getfile(mod)
        mtime = os.stat(source_file).st_mtime
    except (ImportError, TypeError, OSError):
        return None

    cached = _MODULE_SOURCE_CACHE.get(module_path)
    if cached is not None and cached[0] == source_file and cached[1] == mtime:
        return cached[2]

    try:
        with open(source_file, encoding="utf-8") as f:
            source = f.read()
    except OSError:
        return None

    try:
        tree = ast.parse(source, filename=source_file)
    except SyntaxError:
        return None

    bindings: dict[str, tuple[str, str]] = {}
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
                local = alias.asname or alias.name.split(".", 1)[0]
                bindings[local] = (alias.name, alias.name)
                if alias.asname:
                    names.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == module_path:
                continue  # a self-import names siblings, not dependencies
            names.add(module)
            for alias in node.names:
                names.add(alias.name)
                bindings[alias.asname or alias.name] = (module, alias.name)
                if alias.asname:
                    names.add(alias.asname)

    definitions: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            definitions.setdefault(node.name, node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    definitions.setdefault(target.id, node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            definitions.setdefault(node.target.id, node)

    parsed = _ModuleSource(
        source_file=source_file,
        bindings=bindings,
        names=names,
        definitions=definitions,
    )
    _MODULE_SOURCE_CACHE[module_path] = (source_file, mtime, parsed)
    return parsed


def _names_referenced_by(definition: ast.AST) -> frozenset[str]:
    """Every name a definition references, its own decorator list excluded.

    Annotations count, including the string form ``"Name"`` that
    ``from __future__ import annotations`` or quoting produces.
    """
    referenced: set[str] = set()

    def collect(node: ast.AST) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                referenced.add(child.id)
            elif isinstance(child, ast.arg):
                _collect_string_annotation(child.annotation, referenced)
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                _collect_string_annotation(child.returns, referenced)
            elif isinstance(child, ast.AnnAssign):
                _collect_string_annotation(child.annotation, referenced)

    for field_name, value in ast.iter_fields(definition):
        if field_name == "decorator_list":
            continue
        if isinstance(value, ast.AST):
            collect(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, ast.AST):
                    collect(item)
    return frozenset(referenced)


def _collect_string_annotation(annotation: ast.AST | None, out: set[str]) -> None:
    """Add the names inside a quoted annotation to ``out``."""
    if not (isinstance(annotation, ast.Constant) and isinstance(annotation.value, str)):
        return
    try:
        parsed = ast.parse(annotation.value, mode="eval")
    except SyntaxError:
        return
    for child in ast.walk(parsed):
        if isinstance(child, ast.Name):
            out.add(child.id)


def _definition_name(spec: ComponentSpec) -> str:
    """The top-level name a spec's ``qualified_name`` points at."""
    if spec.qualified_name:
        return spec.qualified_name.rsplit(".", 1)[-1]
    return spec.name


def _definition_references_dependency(
    referenced: frozenset[str],
    source: _ModuleSource,
    dep_spec: ComponentSpec | None,
    dep_name: str,
) -> bool:
    """True when a definition reaches a declared dependency without importing it.

    Either it names the dependency directly — a sibling defined in the
    same module, or the dependency's own name — or it names something
    imported from the dependency's module, such as a factory function.
    """
    if dep_name in referenced:
        return True
    if dep_spec is None:
        return False
    if _definition_name(dep_spec) in referenced:
        return True
    dep_modules = {dep_spec.module_path}
    if "." in dep_spec.qualified_name:
        dep_modules.add(dep_spec.qualified_name.rsplit(".", 1)[0])
    dep_modules.discard("")
    return any(
        local in referenced and module in dep_modules
        for local, (module, _original) in source.bindings.items()
    )


def _extract_imports_from_module(
    module_path: str,
) -> set[str] | None:
    """Extract all imported names from a module's source using AST."""
    source = _load_module_source(module_path)
    return None if source is None else set(source.names)


def _find_imported_components(
    imports: set[str],
    registered_names: set[str],
    registry: ComponentRegistry,
) -> set[str]:
    """Find which registered components are referenced by imports."""
    imported_components: set[str] = set()

    name_to_component: dict[str, str] = {}
    for comp_name in registered_names:
        spec = registry.get(comp_name)
        if spec is not None:
            name_to_component[comp_name] = comp_name
            parts = spec.qualified_name.rsplit(".", 1)
            if len(parts) == 2:
                name_to_component[parts[1]] = comp_name
            name_to_component[spec.qualified_name] = comp_name

    for imp in imports:
        if imp in name_to_component:
            imported_components.add(name_to_component[imp])

    return imported_components
