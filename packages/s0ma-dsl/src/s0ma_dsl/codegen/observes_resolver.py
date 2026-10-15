"""Observes pattern resolution and privileged import determination.

Resolves ganglion ``observes`` patterns against a project-level registry
of all nerves. Determines which resolved targets require privileged
imports (cross-module INTERNAL components).

Three pattern forms per PRD §2.2.4 / FR-20:
  - Exact name: ``"process_signal"`` — matches a nerve with that name
  - Module glob: ``"signal_processor.*"`` — matches all nerves in that module
  - Layer glob: ``"DOMAIN::*"`` — matches all nerves at that layer

PRD references: FR-20 (ganglion observes), FR-22 (privileged imports),
                §2.3.3 (registry namespace)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from s0ma.decorators import component
from s0ma.types import ComponentKind
from s0ma.types import Layer as S0maLayer

from s0ma_dsl.config import StrictnessMode, get_severity
from s0ma_dsl.errors import S0maResolutionError

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.enums import Visibility
    from s0ma_dsl.ast_nodes.nodes import (
        GanglionDecl,
        NerveDecl,
        S0maModule,
    )

__all__ = [
    "ProjectContext",
    "ResolvedObserves",
    "PrivilegedImportInfo",
    "ObservesResolver",
    "resolve_observes",
    "determine_privileged_imports",
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_ProjectContext",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Project-level context holding all parsed modules for cross-module "
        "resolution of observes patterns and privileged imports."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class ProjectContext:
    """Project-level context for cross-module resolution.

    Holds all parsed modules in the project, enabling observes pattern
    resolution against the full registry namespace (PRD §2.3.3).
    """

    modules: list[S0maModule] = field(default_factory=list)

    def all_nerves(self) -> list[tuple[str, str, NerveDecl]]:
        """Return all nerves in the project as (module_name, canonical_id, decl) triples.

        Sorted by canonical_id for deterministic output.
        """
        result: list[tuple[str, str, NerveDecl]] = []
        for mod in self.modules:
            mod_name = mod.module.name
            for nerve in mod.nerves:
                canonical = f"{mod_name}::{nerve.name}"
                result.append((mod_name, canonical, nerve))
        result.sort(key=lambda t: t[1])
        return result

    def all_component_names(self) -> dict[str, tuple[str, str, Visibility | None]]:
        """Return all components as name -> (module_name, canonical_id, visibility).

        For resolving test ``tests`` field references.
        """
        result: dict[str, tuple[str, str, Visibility | None]] = {}
        for mod in self.modules:
            mod_name = mod.module.name
            for nerve in mod.nerves:
                canonical = f"{mod_name}::{nerve.name}"
                result[nerve.name] = (mod_name, canonical, nerve.visibility)
            for cell in mod.cells:
                canonical = f"{mod_name}::{cell.name}"
                result[cell.name] = (mod_name, canonical, cell.visibility)
            for ganglion in mod.ganglia:
                canonical = f"{mod_name}::{ganglion.name}"
                result[ganglion.name] = (mod_name, canonical, ganglion.visibility)
        return result


@component(
    name="S0maDSL_ResolvedObserves",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Result of resolving a single observes pattern to concrete nerve "
        "canonical IDs, with the pattern type identified."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class ResolvedObserves:
    """Result of resolving one observes pattern."""

    pattern: str
    """The original pattern string."""

    pattern_type: str
    """One of 'exact', 'module_glob', 'layer_glob'."""

    resolved_targets: tuple[str, ...]
    """Canonical IDs of resolved nerves, sorted deterministically."""


@component(
    name="S0maDSL_PrivilegedImportInfo",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Describes a privileged import needed by a ganglion or test to access "
        "a cross-module INTERNAL component, with the import kind and source field."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class PrivilegedImportInfo:
    """A privileged import needed by a ganglion or test.

    Privileged imports bypass normal export checks to allow observation
    and verification of INTERNAL components per PRD FR-22.
    """

    canonical_id: str
    """Canonical ID of the target component (module::component)."""

    module_name: str
    """The module containing the target component."""

    component_name: str
    """The local name of the target component."""

    import_kind: str
    """One of 'privileged_observation' (ganglia) or 'privileged_verification' (tests)."""

    referenced_in: str
    """The field that references this component: 'observes' or 'tests'."""


# ---------------------------------------------------------------------------
# Observes Resolver
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_ObservesResolver",
    kind=ComponentKind.SERVICE,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Resolves ganglion observes patterns (exact, module glob, layer glob) "
        "against the project-level registry namespace and determines which "
        "resolved targets require privileged imports."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class ObservesResolver:
    """Resolves observes patterns against the project registry namespace.

    Implements the three pattern forms defined in PRD §2.2.4:
      - Exact name: matches a specific nerve
      - Module glob (``module.*``): matches all nerves in a module
      - Layer glob (``LAYER::*``): matches all nerves in a layer
    """

    mode: StrictnessMode = StrictnessMode.DEV
    filename: str = ""

    def resolve_patterns(
        self,
        patterns: tuple[str, ...],
        context: ProjectContext,
        source_line: int = 0,
    ) -> tuple[list[ResolvedObserves], list[S0maResolutionError]]:
        """Resolve all observes patterns to concrete nerve targets.

        Parameters
        ----------
        patterns:
            The observes patterns from a ganglion declaration.
        context:
            Project-level context with all modules.
        source_line:
            Line number for error reporting.

        Returns
        -------
        tuple:
            (resolved list, errors list)
        """
        all_nerves = context.all_nerves()
        resolved_list: list[ResolvedObserves] = []
        errors: list[S0maResolutionError] = []

        for pattern in patterns:
            pattern_type = _classify_pattern(pattern)
            targets = self._match_pattern(pattern, pattern_type, all_nerves)

            resolved_list.append(ResolvedObserves(
                pattern=pattern,
                pattern_type=pattern_type,
                resolved_targets=tuple(sorted(targets)),
            ))

            if not targets:
                severity = get_severity("EMPTY_OBSERVES", self.mode)
                if severity is not None:
                    errors.append(S0maResolutionError(
                        code="EMPTY_OBSERVES",
                        message=(
                            f"Observes pattern '{pattern}' resolved to no nerves."
                        ),
                        file=self.filename,
                        line=source_line,
                        column=0,
                        severity=severity,
                        remediation=(
                            f"Check that pattern '{pattern}' matches at least one "
                            f"nerve in the project. Exact names must match a nerve name; "
                            f"module globs ('module.*') must reference a module with nerves; "
                            f"layer globs ('LAYER::*') must reference a layer with nerves."
                        ),
                        context={"pattern": pattern, "pattern_type": pattern_type},
                    ))

        return resolved_list, errors

    def _match_pattern(
        self,
        pattern: str,
        pattern_type: str,
        all_nerves: list[tuple[str, str, NerveDecl]],
    ) -> list[str]:
        """Match a single pattern against all nerves.

        Returns canonical IDs of matching nerves.
        """
        if pattern_type == "layer_glob":
            return self._match_layer_glob(pattern, all_nerves)
        elif pattern_type == "module_glob":
            return self._match_module_glob(pattern, all_nerves)
        else:
            return self._match_exact(pattern, all_nerves)

    @staticmethod
    def _match_exact(
        name: str,
        all_nerves: list[tuple[str, str, NerveDecl]],
    ) -> list[str]:
        """Match an exact nerve name against all nerves."""
        return [
            canonical
            for _mod, canonical, nerve in all_nerves
            if nerve.name == name
        ]

    @staticmethod
    def _match_module_glob(
        pattern: str,
        all_nerves: list[tuple[str, str, NerveDecl]],
    ) -> list[str]:
        """Match a module glob (``module.*``) against all nerves."""
        # Pattern is "module_name.*"
        module_prefix = pattern[:-2]  # Remove ".*"
        return [
            canonical
            for mod_name, canonical, _nerve in all_nerves
            if mod_name == module_prefix
        ]

    @staticmethod
    def _match_layer_glob(
        pattern: str,
        all_nerves: list[tuple[str, str, NerveDecl]],
    ) -> list[str]:
        """Match a layer glob (``LAYER::*``) against all nerves."""
        # Pattern is "LAYER::*"
        layer_str = pattern.split("::")[0]
        return [
            canonical
            for _mod, canonical, nerve in all_nerves
            if nerve.layer.value == layer_str
        ]


# ---------------------------------------------------------------------------
# Privileged import determination
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_determine_privileged_imports",
    kind=ComponentKind.FUNCTION,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Determines which cross-module components referenced by ganglia or tests "
        "require privileged imports because they are INTERNAL and not exported."
    ),
    idempotent=True,
    is_framework=True,
)
def determine_privileged_imports(
    current_module_name: str,
    resolved_canonical_ids: list[str],
    context: ProjectContext,
    import_kind: str,
    referenced_in: str,
) -> list[PrivilegedImportInfo]:
    """Determine which resolved targets need privileged imports.

    A privileged import is needed when a ganglion or test references
    a component that is:
      1. In a different module (cross-module), AND
      2. INTERNAL (not in the source module's exports)

    Per PRD FR-22, privileged imports are only emitted in ganglion
    and test files, never in normal module code.

    Parameters
    ----------
    current_module_name:
        The module containing the ganglion or test.
    resolved_canonical_ids:
        Canonical IDs of components being referenced.
    context:
        Project-level context with all modules.
    import_kind:
        'privileged_observation' for ganglia, 'privileged_verification' for tests.
    referenced_in:
        The field that references the component: 'observes' or 'tests'.

    Returns
    -------
    list[PrivilegedImportInfo]:
        Sorted by canonical_id for deterministic output.
    """
    # Build export lookup: module_name -> set of exported names
    exports_by_module: dict[str, set[str]] = {}
    for mod in context.modules:
        exports_by_module[mod.module.name] = set(mod.module.exports)

    privileged: list[PrivilegedImportInfo] = []

    for canonical_id in resolved_canonical_ids:
        if "::" not in canonical_id:
            continue

        target_module, target_component = canonical_id.split("::", 1)

        # Skip local references — no privileged import needed
        if target_module == current_module_name:
            continue

        # Check if the component is exported (PUBLIC)
        target_exports = exports_by_module.get(target_module, set())
        if target_component in target_exports:
            # Exported component — normal import via uses, no privilege needed
            continue

        # Cross-module, not exported → privileged import required
        privileged.append(PrivilegedImportInfo(
            canonical_id=canonical_id,
            module_name=target_module,
            component_name=target_component,
            import_kind=import_kind,
            referenced_in=referenced_in,
        ))

    # Deterministic ordering
    privileged.sort(key=lambda p: p.canonical_id)
    return privileged


# ---------------------------------------------------------------------------
# Pattern classification helper
# ---------------------------------------------------------------------------


def _classify_pattern(pattern: str) -> str:
    """Classify an observes pattern into its type.

    Returns one of: 'exact', 'module_glob', 'layer_glob'.
    """
    if "::" in pattern and pattern.endswith("*"):
        return "layer_glob"
    if pattern.endswith(".*"):
        return "module_glob"
    return "exact"


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_resolve_observes",
    kind=ComponentKind.FUNCTION,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Convenience function to resolve ganglion observes patterns and determine "
        "privileged imports in one call."
    ),
    idempotent=True,
    is_framework=True,
)
def resolve_observes(
    ganglion: GanglionDecl,
    current_module_name: str,
    context: ProjectContext,
    *,
    mode: StrictnessMode = StrictnessMode.DEV,
    filename: str = "",
) -> tuple[list[ResolvedObserves], list[PrivilegedImportInfo], list[S0maResolutionError]]:
    """Resolve observes patterns and determine privileged imports.

    Parameters
    ----------
    ganglion:
        The ganglion declaration with observes patterns.
    current_module_name:
        The module containing this ganglion.
    context:
        Project-level context with all modules.
    mode:
        Strictness mode for error severity.
    filename:
        Source file for error reporting.

    Returns
    -------
    tuple:
        (resolved patterns, privileged imports, errors)
    """
    resolver = ObservesResolver(mode=mode, filename=filename)
    source_line = ganglion.location.start_line if ganglion.location else 0

    resolved, errors = resolver.resolve_patterns(
        ganglion.observes, context, source_line
    )

    # Collect all resolved canonical IDs
    all_targets: list[str] = []
    for r in resolved:
        all_targets.extend(r.resolved_targets)

    # Determine privileged imports
    privileged = determine_privileged_imports(
        current_module_name=current_module_name,
        resolved_canonical_ids=all_targets,
        context=context,
        import_kind="privileged_observation",
        referenced_in="observes",
    )

    return resolved, privileged, errors
