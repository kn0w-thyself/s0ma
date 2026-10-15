"""Bootstrap and import-ordering utilities for s0ma-based projects.

Provides topological sorting of module dependencies and a convenience
function for importing modules in dependency-safe order. These tools
replace the error-prone pattern of manually maintaining ordered module
lists — the self-model already knows the dependency graph, so the
framework should compute the correct ordering automatically.

Key capabilities:
    - Topological sort with cycle detection and reporting
    - Module-level dependency graph construction from registered components
    - Convenience function for dependency-safe module import and registration
"""

from __future__ import annotations

import importlib
import logging
from collections import defaultdict, deque
from typing import TYPE_CHECKING

from s0ma.exceptions import RegistrationError

if TYPE_CHECKING:
    from pathlib import Path

    from s0ma.models import ComponentSpec

__all__ = [
    "topological_sort_modules",
    "bootstrap_modules",
]

logger = logging.getLogger("s0ma")


def topological_sort_modules(
    module_specs: list[tuple[str, list[str]]],
) -> list[str]:
    """Return topologically sorted import order for modules.

    Uses Kahn's algorithm (BFS-based) for clarity and reliable cycle
    detection. The algorithm maintains an in-degree count for each node
    and processes nodes with zero in-degree first, guaranteeing that
    every module appears after all its dependencies.

    Args:
        module_specs: List of ``(module_path, dependency_module_paths)``
            tuples. Each dependency must be a module path that appears
            as the first element of another tuple in the list (or is
            absent, in which case it is treated as an external dependency
            and ignored for ordering purposes).

    Returns:
        Module paths in dependency-safe import order (dependencies
        appear before the modules that depend on them).

    Raises:
        RegistrationError: On circular dependencies, with a message
            listing the cycle.

    Example::

        sorted_order = topological_sort_modules([
            ("myapp.models", []),
            ("myapp.services", ["myapp.models"]),
            ("myapp.api", ["myapp.services", "myapp.models"]),
        ])
        # Returns: ["myapp.models", "myapp.services", "myapp.api"]
    """
    # Build the set of known modules (only modules in our input list)
    known_modules = {mod_path for mod_path, _ in module_specs}

    # Build adjacency list and in-degree map
    # adj[A] = [B, C] means B and C depend on A (A must come before B, C)
    adj: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = dict.fromkeys(known_modules, 0)

    for mod_path, deps in module_specs:
        for dep in deps:
            if dep in known_modules:
                adj[dep].append(mod_path)
                in_degree[mod_path] += 1

    # Kahn's algorithm: start with nodes that have zero in-degree
    queue: deque[str] = deque(
        mod for mod, degree in sorted(in_degree.items()) if degree == 0
    )
    sorted_result: list[str] = []

    while queue:
        current = queue.popleft()
        sorted_result.append(current)

        for neighbor in sorted(adj[current]):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(sorted_result) != len(known_modules):
        # Cycle detected — find and report the cycle
        remaining = {m for m in known_modules if m not in set(sorted_result)}
        cycle_description = _find_cycle(remaining, module_specs)
        raise RegistrationError(
            f"Circular dependency detected among modules. "
            f"Cannot determine safe import order. "
            f"Cycle: {cycle_description}"
        )

    return sorted_result


def _find_cycle(
    remaining: set[str],
    module_specs: list[tuple[str, list[str]]],
) -> str:
    """Extract a human-readable cycle description from the remaining nodes.

    Performs DFS from an arbitrary remaining node to find and report
    one cycle path.
    """
    known_modules = {mod_path for mod_path, _ in module_specs}
    deps_map: dict[str, list[str]] = {}
    for mod_path, deps in module_specs:
        deps_map[mod_path] = [d for d in deps if d in known_modules]

    # DFS to find a cycle
    visited: set[str] = set()
    path: list[str] = []
    path_set: set[str] = set()

    def dfs(node: str) -> str | None:
        if node in path_set:
            cycle_start = path.index(node)
            cycle = path[cycle_start:] + [node]
            return " -> ".join(cycle)

        if node in visited:
            return None

        visited.add(node)
        path.append(node)
        path_set.add(node)

        for dep in deps_map.get(node, []):
            if dep in remaining:
                result = dfs(dep)
                if result is not None:
                    return result

        path.pop()
        path_set.discard(node)
        return None

    for start_node in sorted(remaining):
        result = dfs(start_node)
        if result is not None:
            return result

    return " -> ".join(sorted(remaining))


def bootstrap_modules(
    module_paths: list[str],
    *,
    project_root: str | Path | None = None,
) -> list[ComponentSpec]:
    """Import modules in dependency-safe order and register their components.

    Given a list of module paths (in any order), this function:

    1. Imports each module to discover its ``@component``-decorated entities.
    2. Builds a module-level dependency graph from the discovered components'
       declared dependencies.
    3. Topologically sorts the modules.
    4. Registers components into the global registry in dependency-safe order.

    This replaces the error-prone pattern of manually maintaining an ordered
    ``_PLATFORM_MODULES`` list — the component declarations already contain
    the dependency information needed to determine correct import order.

    Args:
        module_paths: List of fully qualified Python module paths to import
            and register. Order does not matter — the function determines
            the correct order automatically.
        project_root: Project root directory (accepted for context; reserved
            for future use with path-based module discovery).

    Returns:
        List of all ComponentSpec objects registered during the import,
        in dependency-safe (topological) order.

    Raises:
        RegistrationError: If circular module-level dependencies are detected.
        ImportError: If any module cannot be imported.

    Example::

        from s0ma.utils import bootstrap_modules

        registered = bootstrap_modules([
            "myapp.api",          # depends on myapp.services
            "myapp.models",       # no dependencies
            "myapp.services",     # depends on myapp.models
        ])
        # Imports in order: myapp.models, myapp.services, myapp.api
    """
    from s0ma.decorators import get_all_components_in_module
    from s0ma.registry import get_registry

    registry = get_registry()

    # Phase 1: Import all modules and discover their components
    module_components: dict[str, list[ComponentSpec]] = {}
    for mod_path in module_paths:
        mod = importlib.import_module(mod_path)
        specs = get_all_components_in_module(mod)
        module_components[mod_path] = specs

    # Phase 2: Build module-level dependency graph
    component_to_module: dict[str, str] = {}
    for mod_path, specs in module_components.items():
        for spec in specs:
            component_to_module[spec.name] = mod_path

    module_deps: list[tuple[str, list[str]]] = []
    for mod_path, specs in module_components.items():
        dep_modules: set[str] = set()
        for spec in specs:
            for dep_name in spec.dependencies:
                dep_module = component_to_module.get(dep_name)
                if dep_module is None and "::" in dep_name:
                    # Canonical qualified claim ("module::name") from the
                    # DSL emitter: match the bare name, then hold the
                    # claimed module against the owning import path
                    # (exact, or as a dotted suffix).
                    claim_module, _, claim_name = dep_name.partition("::")
                    candidate = component_to_module.get(claim_name)
                    if (
                        candidate is not None
                        and claim_module
                        and (
                            candidate == claim_module
                            or candidate.endswith(f".{claim_module}")
                        )
                    ):
                        dep_module = candidate
                if dep_module is not None and dep_module != mod_path:
                    dep_modules.add(dep_module)
        module_deps.append((mod_path, sorted(dep_modules)))

    # Phase 3: Topologically sort
    sorted_modules = topological_sort_modules(module_deps)

    # Phase 4: Register in sorted order
    all_registered: list[ComponentSpec] = []
    for mod_path in sorted_modules:
        for spec in module_components[mod_path]:
            if not registry.contains(spec.name):
                registry.register(spec)
                all_registered.append(spec)

    logger.info(
        "bootstrap_modules: imported %d modules, registered %d components "
        "in dependency-safe order.",
        len(sorted_modules),
        len(all_registered),
    )

    return all_registered
