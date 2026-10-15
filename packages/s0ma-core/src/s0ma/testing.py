"""s0ma.testing — Canonical testing utilities for s0ma-based projects.

Provides test isolation primitives that handle the interaction between
Python's module caching (sys.modules) and s0ma's one-shot registration model.

The ``@component`` decorator fires once at import time. Python caches imported
modules. When ``reset_registry()`` is called for test isolation, already-imported
modules retain their cached state — ``importlib.import_module()`` is a no-op.

These utilities solve that by evicting specified modules from ``sys.modules``
before re-importing, ensuring ``@component`` decorators fire into a fresh registry.

Public API::

    from s0ma.testing import fresh_registry, reinitialize_for_test, isolate_registry

    # Context manager with automatic restore
    with fresh_registry(".", ["myapp.components"]) as registry:
        assert registry.contains("MyComponent")

    # Imperative variant
    registry = reinitialize_for_test(".", ["myapp.components"])

    # Isolated scope for synthetic components
    with isolate_registry() as registry:
        registry.register(synthetic_spec)
"""

from __future__ import annotations

import importlib
import logging
import sys
from contextlib import contextmanager
from pathlib import Path  # noqa: TC003 — used in function signatures
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

    from s0ma.registry import ComponentRegistry

__all__ = [
    "fresh_registry",
    "reinitialize_for_test",
    "isolate_registry",
]

logger = logging.getLogger("s0ma.testing")


@contextmanager
def fresh_registry(
    project_root: str | Path,
    module_prefixes: list[str],
    *,
    persist: bool = False,
    strict_dependencies: bool = False,
) -> Generator[ComponentRegistry, None, None]:
    """Context manager providing a clean registry with freshly-imported modules.

    Handles the full cycle needed for true test isolation in s0ma-based projects:

    1. Saves the current global registry reference (may be ``None``).
    2. Creates a fresh in-memory registry and sets it as the global singleton.
    3. Evicts all modules whose names match ``module_prefixes`` from
       ``sys.modules``.
    4. Re-imports the evicted modules, triggering their ``@component`` decorators
       to fire into the fresh registry.
    5. Yields the fresh, populated registry.
    6. On exit, restores the original global registry unconditionally.

    Args:
        project_root: Root directory of the project. Accepted for context and
            future import-discovery support; does not affect current behavior.
        module_prefixes: Module name prefixes to evict and re-import.
            A prefix of ``"myapp"`` evicts ``myapp`` itself plus every
            ``myapp.*`` submodule currently in ``sys.modules``.
        persist: If ``True``, the fresh registry uses SQLite persistence.
            Defaults to ``False`` (in-memory only) for test isolation.
        strict_dependencies: If ``True``, the fresh registry raises
            ``RegistrationError`` when a component declares an unresolved
            dependency. Defaults to ``False``.

    Yields:
        A fresh :class:`~s0ma.registry.ComponentRegistry` with the specified
        modules re-registered.

    Example::

        from s0ma.testing import fresh_registry

        def test_my_component():
            with fresh_registry(".", ["myapp.components"]) as registry:
                spec = registry.get("MyComponent")
                assert spec is not None
    """
    import s0ma.registry as _registry_module
    from s0ma.registry import ComponentRegistry, set_registry

    # Save the original global registry (may be None if not yet initialized).
    original_registry = _registry_module._global_registry

    # Create and install the fresh registry as the new global.
    fresh = ComponentRegistry(persist=persist, strict_dependencies=strict_dependencies)
    set_registry(fresh)

    # Evict cached modules and re-import them so @component decorators fire.
    evicted = _evict_modules(module_prefixes)
    _reimport_modules(evicted)

    try:
        yield fresh
    finally:
        # Restore the original global registry unconditionally.
        _registry_module._global_registry = original_registry


@contextmanager
def isolate_registry(
    *,
    persist: bool = False,
) -> Generator[ComponentRegistry, None, None]:
    """Create a temporary isolated registry scope.

    Replaces the global registry with a fresh in-memory registry for the
    duration of the context. On exit, the original global registry is restored.
    No module eviction or re-import is performed — this is for tests that need
    to register synthetic (manually constructed) components without touching
    the real module graph.

    Args:
        persist: If ``True``, the isolated registry uses SQLite persistence.
            Defaults to ``False``.

    Yields:
        A fresh empty :class:`~s0ma.registry.ComponentRegistry`.

    Example::

        from s0ma.testing import isolate_registry
        from s0ma.models import ComponentSpec
        from s0ma.types import ComponentKind, Layer

        def test_custom_components():
            with isolate_registry() as registry:
                spec = ComponentSpec(
                    name="SyntheticService",
                    kind=ComponentKind.SERVICE,
                    layer=Layer.DOMAIN,
                    intent="A synthetic test component",
                    module_path="tests.synthetic",
                    qualified_name="tests.synthetic.SyntheticService",
                )
                registry.register(spec)
                assert registry.contains("SyntheticService")
            # Original global registry is restored here.
    """
    import s0ma.registry as _registry_module
    from s0ma.registry import ComponentRegistry

    # Save the original global registry (may be None).
    original_registry = _registry_module._global_registry

    # Create and install the isolated registry.
    isolated = ComponentRegistry(persist=persist)
    _registry_module._global_registry = isolated

    try:
        yield isolated
    finally:
        # Restore the original global registry unconditionally.
        _registry_module._global_registry = original_registry


def reinitialize_for_test(
    project_root: str | Path,
    module_prefixes: list[str],
    *,
    persist: bool = False,
) -> ComponentRegistry:
    """Imperatively reset the global registry and re-import modules.

    The non-context-manager equivalent of :func:`fresh_registry`. Resets the
    global registry, evicts cached modules matching the given prefixes, and
    re-imports them so their ``@component`` decorators fire into a clean
    registry. The caller is responsible for subsequent cleanup.

    This is useful in non-pytest contexts (e.g., ``setUp()`` in ``unittest``)
    or when lifecycle management must be imperative rather than context-based.

    Args:
        project_root: Root directory of the project. Accepted for context.
        module_prefixes: Module name prefixes to evict and re-import.
        persist: If ``True``, the fresh registry uses SQLite persistence.
            Defaults to ``False``.

    Returns:
        A fresh :class:`~s0ma.registry.ComponentRegistry` with the specified
        modules re-registered.

    Example::

        from s0ma.testing import reinitialize_for_test

        class MyTests(unittest.TestCase):
            def setUp(self):
                self.registry = reinitialize_for_test(".", ["myapp.components"])

            def test_something(self):
                spec = self.registry.get("MyComponent")
                self.assertIsNotNone(spec)
    """
    from s0ma.registry import ComponentRegistry, set_registry

    fresh = ComponentRegistry(persist=persist)
    set_registry(fresh)

    evicted = _evict_modules(module_prefixes)
    _reimport_modules(evicted)

    return fresh


# ------------------------------------------------------------------------------
# Internal helpers — not registered as components (underscore prefix = private)
# ------------------------------------------------------------------------------


def _evict_modules(module_prefixes: list[str]) -> list[str]:
    """Remove modules matching the given prefixes from ``sys.modules``.

    Args:
        module_prefixes: List of module name prefixes whose matching entries
            should be removed from ``sys.modules``.

    Returns:
        Sorted list of module names that were evicted (sorted order ensures
        parent modules sort before their children, which is the safe re-import
        order).
    """
    to_evict = sorted([
        name for name in list(sys.modules.keys())
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in module_prefixes
        )
    ])
    for name in to_evict:
        sys.modules.pop(name, None)
    if to_evict:
        logger.debug("Evicted %d modules from sys.modules: %s", len(to_evict), to_evict)
    return to_evict


def _reimport_modules(module_names: list[str]) -> None:
    """Re-import a list of module names, triggering ``@component`` registration.

    Imports in the provided order. Since :func:`_evict_modules` returns a sorted
    list, parent modules naturally precede their children.

    Args:
        module_names: Sorted list of module names to re-import.
    """
    for name in module_names:
        try:
            importlib.import_module(name)
            logger.debug("Re-imported module: %s", name)
        except ImportError:
            logger.warning(
                "Could not re-import '%s' after eviction — "
                "its @component registrations will be missing from the registry.",
                name,
            )
