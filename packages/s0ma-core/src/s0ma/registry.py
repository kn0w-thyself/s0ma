"""Component registry — the central store of the self-model.

The registry is the brain of s0ma: an in-memory store with SQLite
persistence that holds all registered components and supports hierarchical
queries. It provides the queryable self-knowledge that makes the system
introspectable.

Key capabilities:
    - Register, retrieve, and query components by name, layer, kind
    - Dependency graph construction and traversal (forward and reverse)
    - Snapshot generation for serialization and self-description
    - Thread-safe write operations
    - SQLite persistence that survives process restarts
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma.exceptions import LifecycleError, RegistrationError, RegistryIntegrityError
from s0ma.models import (
    AdoptedFile,
    AssertExpr,
    ComponentSpec,
    Contract,
    DocGuideRegistration,
    DocRefRegistration,
    EntityRef,
    ExampleRegistration,
    FilterExpr,
    ImportHookAnomaly,
    ModuleMetadata,
    PluginRegistration,
    RegistrySnapshot,
    RelationshipEdge,
    ResourceProfile,
    Section,
    SourceSpan,
    TestRegistration,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from types import ModuleType
    from typing import Literal

    from s0ma.types import ComponentKind, Layer

# Allowed values for validation at the registration boundary
# (design §6 / documentation subsystem plan M2).
_VALID_DOC_FORMATS: frozenset[str] = frozenset({"markdown", "html", "json"})
_VALID_RUNS_IN: frozenset[str] = frozenset({"standalone", "pytest", "integration"})


def _validate_doc_format(fmt: str) -> None:
    """Reject unknown doc formats at the registration boundary."""
    if fmt not in _VALID_DOC_FORMATS:
        raise ValueError(
            f"Unsupported doc format '{fmt}'. "
            f"Expected one of {sorted(_VALID_DOC_FORMATS)}."
        )


def _validate_relative_output(output: str) -> None:
    """Reject absolute paths and parent-dir escapes in a doc output path."""
    if not output:
        raise ValueError("output path must be non-empty.")
    if output.startswith("/"):
        raise ValueError(
            f"output must be a relative path, got absolute '{output}'."
        )
    if ".." in Path(output).parts:
        raise ValueError(
            f"output must not contain '..' components, got '{output}'."
        )

__all__ = [
    "ComponentRegistry",
    "get_registry",
    "set_registry",
    "reset_registry",
]

logger = logging.getLogger("s0ma")


class ComponentRegistry:
    """Central registry for all registered components.

    The registry provides:
    - Thread-safe registration and retrieval of ComponentSpecs
    - Hierarchical queries by layer, kind, and dependency relationships
    - Snapshot generation for self-description
    - Optional SQLite persistence that survives process restarts

    Usage::

        registry = ComponentRegistry(persist=False)
        registry.register(spec)
        snapshot = registry.snapshot()
        print(snapshot.describe())
    """

    def __init__(
        self,
        persist: bool = True,
        db_path: str | Path | None = None,
        strict_dependencies: bool = False,
    ) -> None:
        """Initialize the component registry.

        Args:
            persist: If True, persist registrations to SQLite.
            db_path: Path to the SQLite database file. Defaults to
                `.s0ma/registry.db` in the current working directory.
            strict_dependencies: If True, raise RegistrationError when a
                component declares a dependency that isn't yet registered.
                If False (default), log a warning instead.
        """
        self._components: dict[str, ComponentSpec] = {}
        self._modules: dict[str, ModuleMetadata] = {}
        self._edges: list[RelationshipEdge] = []
        self._test_registrations: dict[str, TestRegistration] = {}
        self._ir_store: dict[str, dict[str, object]] = {}
        self._plugins: dict[str, PluginRegistration] = {}
        # Documentation subsystem stores — see design §§6, 10.1.
        # Populated by register_doc_ref / register_doc_guide / register_example
        # (landed in Milestone 2). Read paths land in later milestones.
        self._doc_refs: dict[str, DocRefRegistration] = {}
        self._doc_guides: dict[str, DocGuideRegistration] = {}
        self._examples: dict[str, ExampleRegistration] = {}
        # Adopted-file store (0.11.0, batch-01a D2): real (non-generated)
        # files registered into the self-model by path + content hash via
        # ``register_adopted_file`` — the per-file primitive under the
        # ``s0ma adopt`` command family. Keyed by the adopted path string.
        self._adopted_files: dict[str, AdoptedFile] = {}
        # Import-hook anomaly buffer (POST-1 / 0.4.0). Populated by the
        # import hook every time it would otherwise raise / warn about
        # an unregistered entity or stale doc declaration. Consumers
        # read via the ``import_hook_anomalies`` property or subscribe
        # via ``subscribe_import_hook_anomalies``.
        self._import_hook_anomalies: list[ImportHookAnomaly] = []
        self._import_hook_anomaly_subscribers: list[
            Callable[[ImportHookAnomaly], None]
        ] = []
        self._lock = threading.Lock()
        self._persist = persist
        self._strict_dependencies = strict_dependencies

        # SQLite persistence setup
        self._db_path: Path | None = None
        self._connection: sqlite3.Connection | None = None
        if persist:
            if db_path is None:
                db_path = Path(".s0ma") / "registry.db"
            self._db_path = Path(db_path)
            self._init_db()
            self._load_all()

    # ------------------------------------------------------------------
    # Identity helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _registry_key(spec: ComponentSpec) -> str:
        """Return the in-memory registry key for a spec.

        Module-scoped specs are keyed under ``"<module_path>::<name>"`` so two
        specs with identical bare names but distinct module paths can coexist.
        Specs without ``module_scoped=True`` keep the bare-name keying that
        every legacy registration relies on.
        """
        if spec.module_scoped and spec.module_path:
            return f"{spec.module_path}::{spec.name}"
        return spec.name

    def _resolve_key(self, name: str) -> str | None:
        """Resolve a caller-supplied identifier to a stored registry key.

        Direct hits (qualified or bare) win. Two fallbacks follow:

        - Bare ``name``: when exactly one stored module-scoped spec ends
          with ``"::<name>"`` and carries that bare name on its spec, that
          key is returned.
        - Qualified ``"<module>::<name>"`` (the DSL-M2 canonical-ID form,
          which the emitter writes into generated ``dependencies=[...]``
          claims): when exactly one stored spec carries the bare ``<name>``
          and its ``module_path`` is consistent with the claimed module per
          :meth:`_module_claim_matches`, that spec's key is returned. The
          emitter registers generated components under bare keys
          (``module_scoped`` stays False), so a qualified claim must be
          able to land on a bare-keyed spec — without this fallback every
          generated cross-module dependency edge warned "not yet
          registered" at import (0.15.1, observed in the s0ma-cpx pilot).

        Ambiguity — multiple stored specs matching the identifier — returns
        ``None`` so callers fail explicitly rather than guessing.
        """
        if name in self._components:
            return name
        if "::" in name:
            claimed_module, _, bare = name.partition("::")
            if not claimed_module or not bare:
                return None
            matches = [
                key
                for key, spec in self._components.items()
                if spec.name == bare
                and self._module_claim_matches(spec.module_path, claimed_module)
            ]
            if len(matches) == 1:
                return matches[0]
            return None
        suffix = f"::{name}"
        matches = [
            key
            for key, spec in self._components.items()
            if key.endswith(suffix) and spec.name == name
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    @staticmethod
    def _module_claim_matches(module_path: str, claimed_module: str) -> bool:
        """Whether a spec's ``module_path`` is consistent with a claimed module.

        ``claimed_module`` is the ``<module>::`` prefix of a canonical ID and
        names the DSL module. ``module_path`` records the Python import path
        at registration time (``entity.__module__``) — the DSL module name
        plus an optional package prefix: ``"reading_models"`` when the
        generated module is imported top-level, ``"build.reading_models"``
        when imported as a package. Consistent therefore means equal, or
        ``module_path`` ending with ``".<claimed_module>"`` — segment-aware,
        so ``"not_reading_models"`` never matches ``"reading_models"``. An
        empty ``module_path`` recorded nothing to check the claim against
        and does not refute it.
        """
        if not module_path:
            return True
        return (
            module_path == claimed_module
            or module_path.endswith(f".{claimed_module}")
        )

    def _declares_dependency_on(
        self, declarer: ComponentSpec, key: str, bare_name: str
    ) -> bool:
        """Return True when ``declarer`` claims the component stored at ``key``.

        A dependency claim matches by bare name — the comparison every
        pre-0.15 call site used — or, for qualified ``module::name`` claims,
        by resolving to the same storage key.
        """
        for dep in declarer.dependencies:
            if dep == bare_name:
                return True
            if "::" in dep and self._resolve_key(dep) == key:
                return True
        return False

    # ------------------------------------------------------------------
    # Core registration and retrieval
    # ------------------------------------------------------------------

    def register(self, spec: ComponentSpec, *, idempotent: bool = False) -> None:
        """Register a component in the registry.

        Args:
            spec: The ComponentSpec to register.
            idempotent: If True, silently succeed when re-registering the same
                component from the same source file (redundant declaration).
                If the name exists but the source file differs, raises
                RegistrationError regardless of this flag — that is a genuine
                name collision, not a redundant declaration.
                Default is False (existing behavior: raise on any duplicate).

        Raises:
            RegistrationError: If the component name is already registered,
                or if strict_dependencies is True and a declared dependency
                is not yet registered.
        """
        with self._lock:
            key = self._registry_key(spec)
            if key in self._components:
                existing = self._components[key]
                if idempotent and existing.source_file == spec.source_file:
                    # Same component from the same source — redundant declaration,
                    # not a collision. Silently succeed — after refreshing the
                    # one derived field a stored spec can lack: a registry
                    # persisted before ``register_constant`` / ``register_type``
                    # derived ``qualified_name`` holds ``""`` for those cells,
                    # and the phantom-limb check rejects an empty name.
                    if not existing.qualified_name and spec.qualified_name:
                        existing.qualified_name = spec.qualified_name
                        if self._persist:
                            self._persist_spec(existing)
                    return
                raise RegistrationError(
                    f"Component '{spec.name}' is already registered "
                    f"(first registered from '{existing.module_path}'). "
                    f"Attempted re-registration from '{spec.module_path}'."
                )

            # Validate declared dependencies. Dependencies are resolved through
            # ``_resolve_key`` so a module-scoped consumer can name a sibling
            # module's bare-name dependency the usual way.
            for dep_name in spec.dependencies:
                if self._resolve_key(dep_name) is None:
                    msg = (
                        f"Component '{spec.name}' declares dependency "
                        f"'{dep_name}' which is not yet registered."
                    )
                    if self._strict_dependencies:
                        raise RegistrationError(msg)
                    logger.warning(msg)

            self._components[key] = spec
            logger.debug(
                "Registered component '%s' (%s, %s)",
                spec.name,
                spec.kind.name,
                spec.layer.name,
            )

            if self._persist:
                self._persist_spec(spec)

    def unregister(self, name: str, *, force: bool = False) -> ComponentSpec:
        """Remove a component from the registry.

        Removes the component from both the in-memory store and SQLite
        persistence. If other components declare this component as a
        dependency, the operation is rejected unless force=True.

        Args:
            name: The name of the component to remove.
            force: If True, remove even if other components depend on it.
                If False (default), raise LifecycleError if dependents exist.

        Returns:
            The removed ComponentSpec (for rollback support).

        Raises:
            RegistryIntegrityError: If the component is not registered.
            LifecycleError: If the component has dependents and force=False.
        """
        with self._lock:
            # 1. Check existence — accept either qualified or bare name.
            key = self._resolve_key(name)
            if key is None:
                raise RegistryIntegrityError(
                    f"Cannot unregister '{name}': component is not registered. "
                    f"Registered components: {sorted(self._components.keys())}"
                )
            spec = self._components[key]

            # 2. Dependency validation (unless forced)
            if not force:
                dependents = [
                    s.name for s in self._components.values()
                    if self._declares_dependency_on(s, key, spec.name)
                ]
                if dependents:
                    raise LifecycleError(
                        f"Cannot unregister '{name}': {len(dependents)} component(s) "
                        f"depend on it: {sorted(dependents)}. "
                        f"Use force=True to remove anyway, or update the "
                        f"dependent components first."
                    )

            # 3. Remove from in-memory store
            del self._components[key]

            # 4. Remove from SQLite (under the same key)
            self._delete_from_db(key)

            # 5. Log the removal
            logger.info(
                "Unregistered component '%s' (kind=%s, layer=%s)%s",
                spec.name, spec.kind.name, spec.layer.name,
                " [forced]" if force else "",
            )

            return spec

    def register_from_module(self, module: ModuleType) -> list[ComponentSpec]:
        """Scan a module for @component-decorated entities and register new ones.

        Iterates over the module's namespace looking for entities bearing
        ``__component__`` attributes (placed by the @component decorator) and
        registers any that are not already present in this registry.

        This is a production API for dynamic code loading scenarios — any project
        that imports generated modules at runtime can call this to register the
        module's components without relying on the @component decorator firing
        at import time in the correct registry context. It is also useful after
        ``reset()`` to re-register components from already-imported modules.

        Args:
            module: A Python module to scan for components.

        Returns:
            List of ComponentSpec objects that were newly registered during
            this call. Components already in the registry are skipped.
        """
        # Import here to avoid circular import: decorators.py imports registry.py
        from s0ma.decorators import get_all_components_in_module

        specs = get_all_components_in_module(module)
        newly_registered: list[ComponentSpec] = []

        for spec in specs:
            if not self.contains(spec.name):
                self.register(spec)
                newly_registered.append(spec)

        logger.debug(
            "register_from_module('%s'): %d new, %d already registered",
            getattr(module, "__name__", repr(module)),
            len(newly_registered),
            len(specs) - len(newly_registered),
        )

        return newly_registered

    def register_or_update(self, spec: ComponentSpec) -> ComponentSpec:
        """Register a component or update it if already registered from the same source.

        Upsert semantics:
        - If the name is new → register and return the new spec.
        - If the name exists and ``source_file`` matches → replace the existing
          spec with the new one and return the new spec.
        - If the name exists but ``source_file`` differs → raise
          ``RegistrationError`` (genuine name collision from different source).

        This is the recommended API for dynamic code loading scenarios where
        modules may be reloaded and components need to be re-registered with
        updated metadata.

        Args:
            spec: The ComponentSpec to register or update.

        Returns:
            The registered (or updated) ComponentSpec.

        Raises:
            RegistrationError: If a component with the same name exists but
                was registered from a different source file.
        """
        with self._lock:
            key = self._registry_key(spec)
            existing = self._components.get(key)
            if existing is None:
                # New component — register normally (acquire inner lock via register)
                # We're already holding the lock, so insert directly.
                for dep_name in spec.dependencies:
                    if self._resolve_key(dep_name) is None:
                        msg = (
                            f"Component '{spec.name}' declares dependency "
                            f"'{dep_name}' which is not yet registered."
                        )
                        if self._strict_dependencies:
                            raise RegistrationError(msg)
                        logger.warning(msg)

                self._components[key] = spec
                logger.debug(
                    "register_or_update: registered new component '%s' (%s, %s)",
                    spec.name, spec.kind.name, spec.layer.name,
                )
                if self._persist:
                    self._persist_spec(spec)
                return spec

            if existing.source_file != spec.source_file:
                raise RegistrationError(
                    f"Component '{spec.name}' is already registered "
                    f"(from '{existing.module_path}'). "
                    f"Cannot update from a different source "
                    f"('{spec.module_path}') — this is a name collision."
                )

            # Same source — update in place.
            self._components[key] = spec
            logger.debug(
                "register_or_update: updated component '%s' (%s, %s)",
                spec.name, spec.kind.name, spec.layer.name,
            )
            if self._persist:
                self._persist_spec(spec)
            return spec

    def _replace_internal(
        self,
        name: str,
        new_spec: ComponentSpec,
    ) -> ComponentSpec:
        """Atomically replace a component's spec under the write lock.

        This is the internal primitive for component updates. It removes
        the old spec and registers the new one in a single lock acquisition,
        preventing other threads from seeing an intermediate state where
        the component doesn't exist.

        Args:
            name: The name of the component to replace.
            new_spec: The new ComponentSpec to register.

        Returns:
            The previous ComponentSpec (for rollback support).

        Raises:
            RegistryIntegrityError: If the component is not registered.
            RegistrationError: If new_spec.name differs from 'name' and
                conflicts with an existing registration.
        """
        with self._lock:
            # 1. Verify the old component exists (accept qualified or bare).
            old_key = self._resolve_key(name)
            if old_key is None:
                raise RegistryIntegrityError(
                    f"Cannot replace '{name}': component is not registered."
                )
            old_spec = self._components[old_key]

            new_key = self._registry_key(new_spec)

            # 2. Handle name (or scoping) changes — anything that shifts the key.
            if new_key != old_key:
                if new_key in self._components:
                    raise RegistrationError(
                        f"Cannot rename '{name}' to '{new_spec.name}': "
                        f"'{new_spec.name}' is already registered."
                    )
                # Remove old key entry
                del self._components[old_key]
                self._delete_from_db(old_key)

            # 3. Store new spec under the new key
            self._components[new_key] = new_spec

            # 4. Persist to SQLite
            if self._persist:
                self._persist_spec(new_spec)

            logger.info(
                "Replaced component '%s'%s (kind=%s, layer=%s)",
                name,
                f" -> '{new_spec.name}'" if new_spec.name != old_spec.name else "",
                new_spec.kind.name,
                new_spec.layer.name,
            )

            return old_spec

    def get(self, name: str) -> ComponentSpec | None:
        """Retrieve a component by name.

        Accepts either the bare component name or the module-qualified
        ``"<module>::<name>"`` form. The qualified form finds module-scoped
        specs stored under that exact key and also bare-keyed specs whose
        ``module_path`` matches the module part (exactly, or as a dotted
        suffix) — the canonical claim form the DSL emitter writes. When
        ``name`` is bare and multiple module-scoped specs share that bare
        name, returns ``None`` rather than guessing — callers must
        disambiguate with the qualified form.

        Args:
            name: Bare or qualified component identifier.

        Returns:
            The ComponentSpec if found, None otherwise.
        """
        key = self._resolve_key(name)
        if key is None:
            return None
        return self._components.get(key)

    def get_all(self) -> dict[str, ComponentSpec]:
        """Return a copy of all registered components.

        Returns:
            A dictionary mapping component names to their specs.
        """
        return dict(self._components)

    # ------------------------------------------------------------------
    # Hierarchical queries
    # ------------------------------------------------------------------

    def query_by_layer(self, layer: Layer) -> list[ComponentSpec]:
        """Return all components in a given architectural layer.

        Args:
            layer: The Layer enum value to filter by.

        Returns:
            List of ComponentSpecs in the specified layer.
        """
        return [spec for spec in self._components.values() if spec.layer == layer]

    def query_by_kind(self, kind: ComponentKind) -> list[ComponentSpec]:
        """Return all components of a given kind.

        Args:
            kind: The ComponentKind enum value to filter by.

        Returns:
            List of ComponentSpecs of the specified kind.
        """
        return [spec for spec in self._components.values() if spec.kind == kind]

    def get_dependencies(self, name: str) -> list[ComponentSpec]:
        """Get the resolved dependencies of a component.

        Returns the ComponentSpec objects for each declared dependency
        that is currently registered. Unresolved dependencies are skipped.

        Args:
            name: The component name to look up dependencies for.

        Returns:
            List of ComponentSpecs this component depends on.

        Raises:
            RegistryIntegrityError: If the component is not registered.
        """
        key = self._resolve_key(name)
        if key is None:
            raise RegistryIntegrityError(
                f"Cannot get dependencies: component '{name}' is not registered. "
                f"Register it with @component before querying its dependencies."
            )
        spec = self._components[key]
        result = []
        for dep_name in spec.dependencies:
            dep_key = self._resolve_key(dep_name)
            if dep_key is not None:
                result.append(self._components[dep_key])
        return result

    def get_dependents(self, name: str) -> list[ComponentSpec]:
        """Get components that depend on the named component (reverse lookup).

        Args:
            name: The component name to find dependents of.

        Returns:
            List of ComponentSpecs that declare this component as a dependency.

        Raises:
            RegistryIntegrityError: If the component is not registered.
        """
        key = self._resolve_key(name)
        if key is None:
            raise RegistryIntegrityError(
                f"Cannot get dependents: component '{name}' is not registered. "
                f"Register it with @component before querying its dependents."
            )
        spec = self._components[key]
        return [
            other
            for other in self._components.values()
            if self._declares_dependency_on(other, key, spec.name)
        ]

    def get_dependency_graph(self) -> dict[str, list[str]]:
        """Return the full dependency graph as an adjacency list.

        Returns:
            Dictionary mapping each component name to its list of
            declared dependency names.
        """
        return {
            name: list(spec.dependencies)
            for name, spec in self._components.items()
        }

    # ------------------------------------------------------------------
    # Import ordering
    # ------------------------------------------------------------------

    def import_order(self) -> list[str]:
        """Return topologically sorted module paths based on the dependency graph.

        Uses the registered components' declared dependencies to determine
        a safe import order. Each unique module_path in the registry is
        treated as a node, with edges derived from cross-module component
        dependencies.

        Returns:
            Topologically sorted list of module paths. Modules with no
            dependencies appear first. Modules whose components depend
            on components in other modules appear after those modules.

        Raises:
            RegistrationError: If circular module-level dependencies
                are detected.
        """
        from s0ma.utils import topological_sort_modules

        # Build component-name → module-path lookup
        component_to_module: dict[str, str] = {}
        for spec in self._components.values():
            component_to_module[spec.name] = spec.module_path

        # Build module-level dependency graph. Claims are resolved through
        # ``_resolve_key`` so qualified ``module::name`` dependencies
        # contribute their cross-module edges — exactly the edges this
        # ordering exists to honour.
        module_deps: dict[str, set[str]] = {}
        for spec in self._components.values():
            if spec.module_path not in module_deps:
                module_deps[spec.module_path] = set()
            for dep_name in spec.dependencies:
                dep_key = self._resolve_key(dep_name)
                dep_module: str | None
                if dep_key is not None:
                    dep_module = self._components[dep_key].module_path
                else:
                    dep_module = component_to_module.get(dep_name)
                if dep_module is not None and dep_module != spec.module_path:
                    module_deps[spec.module_path].add(dep_module)

        # Convert to the format expected by topological_sort_modules
        module_specs = [
            (mod_path, sorted(deps))
            for mod_path, deps in module_deps.items()
        ]

        return topological_sort_modules(module_specs)

    # ------------------------------------------------------------------
    # Snapshot and self-description
    # ------------------------------------------------------------------

    def snapshot(self) -> RegistrySnapshot:
        """Generate a frozen snapshot of the current registry state.

        Returns:
            A RegistrySnapshot capturing all components, their layers,
            dependency graph, and summary statistics.
        """
        components = dict(self._components)
        component_count = len(components)
        framework_count = sum(
            1 for spec in components.values() if spec.is_framework
        )

        # Build layers dictionary
        layers: dict[str, list[str]] = {}
        for name, spec in components.items():
            layer_name = spec.layer.name
            if layer_name not in layers:
                layers[layer_name] = []
            layers[layer_name].append(name)

        # Build dependency graph
        dependency_graph = {
            name: list(spec.dependencies)
            for name, spec in components.items()
        }

        return RegistrySnapshot(
            components=components,
            component_count=component_count,
            framework_component_count=framework_count,
            layers=layers,
            dependency_graph=dependency_graph,
            modules=dict(self._modules),
            edges=list(self._edges),
            test_registrations=dict(self._test_registrations),
            ir=dict(self._ir_store),
            plugins=dict(self._plugins),
            doc_refs=dict(self._doc_refs),
            doc_guides=dict(self._doc_guides),
            examples=dict(self._examples),
            adopted_files=dict(self._adopted_files),
        )

    def to_dict(self) -> dict[str, object]:
        """Return the complete registry state as a JSON-serializable dict.

        Includes components, modules, edges, and test registrations —
        everything needed for runtime self-introspection.
        """
        return {
            "components": {
                name: spec.to_dict()
                for name, spec in self._components.items()
            },
            "modules": {
                name: meta.to_dict()
                for name, meta in self._modules.items()
            },
            "edges": [edge.to_dict() for edge in self._edges],
            "test_registrations": {
                name: reg.to_dict()
                for name, reg in self._test_registrations.items()
            },
            "ir": dict(self._ir_store),
            "plugins": {
                name: plugin.to_dict()
                for name, plugin in self._plugins.items()
            },
            "adopted_files": {
                path: rec.to_dict()
                for path, rec in self._adopted_files.items()
            },
            "summary": {
                "component_count": len(self._components),
                "module_count": len(self._modules),
                "edge_count": len(self._edges),
                "test_count": len(self._test_registrations),
                "ir_count": len(self._ir_store),
                "plugin_count": len(self._plugins),
                "adopted_file_count": len(self._adopted_files),
            },
        }

    # ------------------------------------------------------------------
    # Containment and iteration
    # ------------------------------------------------------------------

    def contains(self, name: str) -> bool:
        """Check if a component is registered by name.

        Accepts either bare or qualified identifiers; ambiguous bare lookups
        return False (mirroring ``get``).
        """
        return self._resolve_key(name) is not None

    def count(self) -> int:
        """Return the number of registered components."""
        return len(self._components)

    def __contains__(self, name: object) -> bool:
        """Support `name in registry` syntax."""
        if not isinstance(name, str):
            return False
        return self._resolve_key(name) is not None

    def __len__(self) -> int:
        """Support `len(registry)` syntax."""
        return len(self._components)

    def __iter__(self) -> Iterator[str]:
        """Support `for name in registry` iteration over component names."""
        return iter(self._components)

    # ------------------------------------------------------------------
    # Import-hook anomaly surface (POST-1 / 0.4.0)
    # ------------------------------------------------------------------
    #
    # The s0ma import hook scans every project module that loads under
    # the configured project root. When it detects an unregistered
    # public entity, a stale documentation marker, or any other foreign-
    # code violation, it appends an :class:`ImportHookAnomaly` to this
    # registry's buffer (under ``self._lock``) and dispatches the same
    # record to every subscriber registered through
    # :meth:`subscribe_import_hook_anomalies`. This is the load-bearing
    # surface fr3d's Phase 2 B1 ``IMMUNE_RESPONSE`` detection consumes
    # — it lets downstream code react to surveillance findings without
    # scraping log output.

    @property
    def import_hook_anomalies(self) -> list[ImportHookAnomaly]:
        """Return a snapshot of the import-hook anomaly buffer.

        Returns a new list of :class:`ImportHookAnomaly` records in the
        order they were detected. The returned list is a defensive
        copy — mutating it does not affect future polls and does not
        clear the buffer. Use :meth:`clear_import_hook_anomalies` to
        empty the buffer once you have consumed it.

        Polling is cheap (one lock acquisition + list copy); the
        buffer is bounded only by the number of import-hook detections
        that have occurred, so long-running processes that never poll
        should subscribe instead.
        """
        with self._lock:
            return list(self._import_hook_anomalies)

    def clear_import_hook_anomalies(self) -> None:
        """Empty the import-hook anomaly buffer.

        Subscribers registered via :meth:`subscribe_import_hook_anomalies`
        are not affected — they continue to receive future detections.
        Call this once you have drained
        :attr:`import_hook_anomalies` and acted on the records, so the
        buffer does not grow without bound across a long-running
        process's lifetime.
        """
        with self._lock:
            self._import_hook_anomalies.clear()

    def subscribe_import_hook_anomalies(
        self,
        callback: Callable[[ImportHookAnomaly], None],
    ) -> Callable[[], None]:
        """Register a callback invoked on every new import-hook anomaly.

        ``callback`` is invoked synchronously under the registry lock
        every time the import hook records a new anomaly, before the
        appending poll-side buffer write returns. Subscribers run in
        registration order; exceptions raised by a subscriber are
        logged and swallowed so one bad callback does not break the
        others.

        Args:
            callback: A callable receiving the freshly-detected
                :class:`ImportHookAnomaly`. Keep the body short — it
                runs under the registry lock. For heavier work, hand
                the record off to a queue or executor.

        Returns:
            A zero-argument unsubscribe function. Call it to remove
            the callback from future dispatches.
        """
        with self._lock:
            self._import_hook_anomaly_subscribers.append(callback)

        def _unsubscribe() -> None:
            # Suppressed ValueError means already unsubscribed — make
            # repeated calls a no-op rather than an error so callers can
            # hold onto the handle freely.
            with self._lock, contextlib.suppress(ValueError):
                self._import_hook_anomaly_subscribers.remove(callback)

        return _unsubscribe

    def record_import_hook_anomaly(self, anomaly: ImportHookAnomaly) -> None:
        """Record an :class:`ImportHookAnomaly` in the registry buffer.

        The s0ma import hook calls this from inside its loader after a
        foreign-code violation is detected; downstream code should not
        usually invoke it directly. Append and subscriber dispatch
        happen under the registry lock so concurrent registrations and
        anomaly recording cannot interleave.
        """
        with self._lock:
            self._import_hook_anomalies.append(anomaly)
            # Snapshot subscribers under the lock and dispatch under
            # the same lock — keeps subscriber-visible state consistent
            # with the buffer they read via the property. Subscribers
            # are expected to be fast; bad ones get logged and swallowed
            # so a single failure can't blackhole future detections.
            for callback in list(self._import_hook_anomaly_subscribers):
                try:
                    callback(anomaly)
                except Exception:  # noqa: BLE001 — subscriber isolation
                    logger.exception(
                        "Import-hook anomaly subscriber %r raised; "
                        "remaining subscribers will still be notified.",
                        callback,
                    )

    # ------------------------------------------------------------------
    # DSL expansion: module, constant, type, relationship, test
    # ------------------------------------------------------------------

    def register_module(
        self,
        *,
        name: str,
        layer: str,
        version: str,
        intent: str,
        exports: list[str] | None = None,
        content_hash: str = "",
        tags: list[str] | None = None,
        source_file: str | None = None,
    ) -> ModuleMetadata:
        """Register module-level metadata for a .s0ma module.

        Stores the architectural identity of a module: its layer, version,
        intent, exported symbols, and optional tags. Idempotent — re-registering
        the same module name replaces the previous entry.

        Args:
            name: The module's canonical name (e.g., ``signal_processor``).
            layer: Architectural layer (``DOMAIN``, ``APPLICATION``, etc.).
            version: Semantic version string.
            intent: Human-readable purpose statement.
            exports: List of exported component names.
            content_hash: Optional content hash for change detection.
            tags: Optional classification tags.
            source_file: Path to the source ``.s0ma`` file.

        Returns:
            The stored ModuleMetadata.
        """
        meta = ModuleMetadata(
            name=name,
            layer=layer,
            version=version,
            intent=intent,
            exports=exports or [],
            content_hash=content_hash,
            tags=tags or [],
            source_file=source_file,
        )
        with self._lock:
            self._modules[name] = meta
            logger.debug("Registered module '%s' (layer=%s)", name, layer)
            if self._persist:
                self._persist_module(meta)
        return meta

    def register_adopted_file(
        self,
        *,
        path: str,
        description: str,
        content_hash: str = "",
        re_adopt_count: int = 0,
        metadata: dict[str, object] | None = None,
    ) -> AdoptedFile:
        """Register a real (non-generated) file into the self-model by adoption.

        Adoption (0.11.0, batch-01a D2) is the per-file primitive for
        making plain files first-class: registered by path, verified by
        content hash, counted in registration ratios. Idempotent —
        re-registering the same path replaces the previous entry (that
        is the "re-adopt" remediation after an intentional edit).

        Args:
            path: The adopted file's path. DSL tooling stores this
                project-root-relative in POSIX form; the registry treats
                it as an opaque key.
            content_hash: Content hash captured at adoption time
                (``sha256:<hex>`` by convention, mirroring
                :class:`ModuleMetadata`).
            description: Required human-readable purpose statement.
            re_adopt_count: Advisory number of re-adoptions after the
                initial intake. It is never gate evidence.
            metadata: Optional additional facts (provenance, tags, …).

        Returns:
            The stored AdoptedFile.
        """
        record = AdoptedFile(
            path=path,
            description=description,
            content_hash=content_hash,
            re_adopt_count=re_adopt_count,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._adopted_files[path] = record
            logger.debug("Registered adopted file '%s'", path)
            if self._persist:
                self._persist_adopted_file(record)
        return record

    def register_constant(
        self,
        *,
        name: str,
        layer: str,
        intent: str,
        metadata: dict[str, object] | None = None,
        source_file: str | None = None,
        module_path: str = "",
    ) -> ComponentSpec:
        """Register a CONSTANT cell as a component.

        Constants can't use the ``@component`` decorator (they're bare
        assignments), so this function creates a ComponentSpec with
        ``kind=MODEL`` and ``kind_detail=CONSTANT`` in metadata.

        Args:
            name: The constant's name.
            layer: Architectural layer string (e.g., ``"DOMAIN"``).
            intent: Human-readable purpose statement (≥10 chars).
            metadata: Additional DSL metadata (visibility, schema, etc.).
            source_file: Source file path.
            module_path: Owning module's canonical name (e.g.
                ``"presentation.web.shell_view"``). Empty string when
                unknown — the DSL emitter populates this so the registry
                can attribute the constant to its module the same way
                ``register_module`` and ``@component`` registrations do.
                The spec's ``qualified_name`` is derived from it as
                ``"<module_path>.<name>"``, the same shape ``@component``
                derives, so the verifiers can resolve the constant to its
                module attribute; it stays empty when ``module_path`` is
                empty.

        Returns:
            The registered ComponentSpec.
        """
        from s0ma.types import ComponentKind
        from s0ma.types import Layer as FrameworkLayer

        merged_metadata = dict(metadata or {})
        merged_metadata.setdefault("kind_detail", "CONSTANT")

        spec = ComponentSpec(
            name=name,
            kind=ComponentKind.MODEL,
            layer=FrameworkLayer[layer],
            intent=intent,
            metadata=merged_metadata,
            source_file=source_file,
            module_path=module_path,
            qualified_name=f"{module_path}.{name}" if module_path else "",
        )
        self.register(spec, idempotent=True)
        return spec

    def register_type(
        self,
        *,
        name: str,
        layer: str,
        intent: str,
        metadata: dict[str, object] | None = None,
        source_file: str | None = None,
        module_path: str = "",
    ) -> ComponentSpec:
        """Register a TYPE cell as a component.

        Type aliases can't use the ``@component`` decorator, so this
        function creates a ComponentSpec with ``kind=MODEL`` and
        ``kind_detail=TYPE`` in metadata.

        Args:
            name: The type alias name.
            layer: Architectural layer string (e.g., ``"DOMAIN"``).
            intent: Human-readable purpose statement (≥10 chars).
            metadata: Additional DSL metadata (visibility, schema, etc.).
            source_file: Source file path.
            module_path: Owning module's canonical name. Empty string when
                unknown — the DSL emitter populates this so the registry
                can attribute the type alias to its module. The spec's
                ``qualified_name`` is derived from it as
                ``"<module_path>.<name>"``, the same shape ``@component``
                derives, so the verifiers can resolve the alias to its
                module attribute; it stays empty when ``module_path`` is
                empty.

        Returns:
            The registered ComponentSpec.
        """
        from s0ma.types import ComponentKind
        from s0ma.types import Layer as FrameworkLayer

        merged_metadata = dict(metadata or {})
        merged_metadata.setdefault("kind_detail", "TYPE")

        spec = ComponentSpec(
            name=name,
            kind=ComponentKind.MODEL,
            layer=FrameworkLayer[layer],
            intent=intent,
            metadata=merged_metadata,
            source_file=source_file,
            module_path=module_path,
            qualified_name=f"{module_path}.{name}" if module_path else "",
        )
        self.register(spec, idempotent=True)
        return spec

    def register_relationship(
        self,
        *,
        source: str,
        target: str,
        relation: str,
        intent: str = "",
        carries: str = "",
        coupling: str = "",
        origin: str = "authored",
    ) -> RelationshipEdge:
        """Register a dependency relationship between two components.

        Stores an edge in the relationship graph. Both authored edges
        (from standalone ``axon`` declarations) and derived edges (inferred
        from ``raises``/type annotations) use this method.

        Duplicate edges (same source, target, relation) are silently
        replaced — idempotent semantics.

        Args:
            source: Canonical ID of the source component (``module::name``).
            target: Canonical ID of the target component.
            relation: Relationship type (``CALLS``, ``READS``, ``RAISES``,
                ``PRODUCES``, ``CONSUMES``, etc.).  See
                :data:`s0ma.types.KNOWN_RELATION_TYPES` for the full set.
            intent: Human-readable description of the relationship.
            carries: Data type carried across the edge.
            coupling: Coupling strength (``TIGHT`` or ``LOOSE``).
            origin: Edge origin — ``"authored"`` or ``"derived"``.

        Returns:
            The stored RelationshipEdge.
        """
        edge = RelationshipEdge(
            source=source,
            target=target,
            relation=relation,
            intent=intent,
            carries=carries,
            coupling=coupling,
            origin=origin,
        )
        with self._lock:
            # Replace existing edge with same (source, target, relation)
            self._edges = [
                e for e in self._edges
                if not (e.source == source and e.target == target and e.relation == relation)
            ]
            self._edges.append(edge)
            logger.debug(
                "Registered relationship %s -[%s]-> %s", source, relation, target
            )
            if self._persist:
                self._persist_edge(edge)
        return edge

    def register_test(
        self,
        *,
        name: str,
        intent: str,
        validates: list[str] | None = None,
        source_file: str | None = None,
    ) -> TestRegistration:
        """Register a test declaration with its validated component links.

        Stores the test's identity and the list of component canonical IDs
        it validates, enabling coverage queries and release-mode checks.

        Idempotent — re-registering the same test name replaces the entry.

        Args:
            name: Canonical test ID (``module::test_name``).
            intent: Human-readable purpose statement.
            validates: List of canonical component IDs this test validates.
            source_file: Source file path.

        Returns:
            The stored TestRegistration.
        """
        reg = TestRegistration(
            name=name,
            intent=intent,
            validates=validates or [],
            source_file=source_file,
        )
        with self._lock:
            self._test_registrations[name] = reg
            logger.debug("Registered test '%s' (validates %d components)", name, len(reg.validates))
            if self._persist:
                self._persist_test(reg)
        return reg

    # ------------------------------------------------------------------
    # DSL expansion: queries
    # ------------------------------------------------------------------

    def get_module(self, name: str) -> ModuleMetadata | None:
        """Retrieve module metadata by name."""
        return self._modules.get(name)

    def get_all_modules(self) -> dict[str, ModuleMetadata]:
        """Return a copy of all registered module metadata."""
        return dict(self._modules)

    def get_adopted_file(self, path: str) -> AdoptedFile | None:
        """Retrieve an adopted-file record by path."""
        return self._adopted_files.get(path)

    def get_all_adopted_files(self) -> dict[str, AdoptedFile]:
        """Return a copy of all adopted-file records."""
        return dict(self._adopted_files)

    def get_edges(
        self,
        *,
        source: str | None = None,
        target: str | None = None,
        relation: str | None = None,
        origin: str | None = None,
    ) -> list[RelationshipEdge]:
        """Query relationship edges with optional filters.

        All filter parameters are optional. When omitted, that dimension
        is not filtered. When multiple filters are provided, all must match.

        Args:
            source: Filter by source canonical ID.
            target: Filter by target canonical ID.
            relation: Filter by relation type.
            origin: Filter by origin (``"authored"`` or ``"derived"``).

        Returns:
            List of matching RelationshipEdge objects.
        """
        result = list(self._edges)
        if source is not None:
            result = [e for e in result if e.source == source]
        if target is not None:
            result = [e for e in result if e.target == target]
        if relation is not None:
            result = [e for e in result if e.relation == relation]
        if origin is not None:
            result = [e for e in result if e.origin == origin]
        return result

    def get_test(self, name: str) -> TestRegistration | None:
        """Retrieve a test registration by name."""
        return self._test_registrations.get(name)

    def get_all_tests(self) -> dict[str, TestRegistration]:
        """Return a copy of all registered test metadata."""
        return dict(self._test_registrations)

    def get_tests_for_component(self, component_id: str) -> list[TestRegistration]:
        """Find all tests that validate a given component.

        Args:
            component_id: Canonical component ID to search for.

        Returns:
            List of TestRegistration objects that validate this component.
        """
        return [
            reg for reg in self._test_registrations.values()
            if component_id in reg.validates
        ]

    # ------------------------------------------------------------------
    # DSL expansion: advanced queries (M15)
    # ------------------------------------------------------------------

    def get_component_by_canonical_id(self, canonical_id: str) -> ComponentSpec | None:
        """Retrieve a component by its canonical ID (``module::component``).

        Canonical IDs follow the format ``module_name::component_name`` —
        the claim alphabet the DSL emitter writes (``register_relationship``
        targets and emitted ``dependencies=[...]`` entries). Resolution is
        exactly ``get``'s, via ``_resolve_key``: direct key hits win, a
        qualified ID matches the unique spec with that bare name whose
        ``module_path`` equals the module part or ends with
        ``".<module part>"``, and ambiguous IDs return ``None`` rather than
        guessing. If no ``::`` separator is present, this is a plain name
        lookup.

        Args:
            canonical_id: The canonical ID to look up (e.g.,
                ``"signal_processor::process_signal"``).

        Returns:
            The matching ComponentSpec, or None if not found.
        """
        return self.get(canonical_id)

    def get_incoming_edges(self, canonical_id: str) -> list[RelationshipEdge]:
        """Get all edges where the given component is the target.

        Args:
            canonical_id: Canonical component ID (``module::component``).

        Returns:
            List of RelationshipEdge objects targeting this component.
        """
        return self.get_edges(target=canonical_id)

    def get_outgoing_edges(self, canonical_id: str) -> list[RelationshipEdge]:
        """Get all edges where the given component is the source.

        Args:
            canonical_id: Canonical component ID (``module::component``).

        Returns:
            List of RelationshipEdge objects originating from this component.
        """
        return self.get_edges(source=canonical_id)

    def get_observers(self, canonical_id: str) -> list[RelationshipEdge]:
        """Find all observation edges targeting a given component.

        Returns edges where the target is the given component and the
        relation indicates observation (typically registered by ganglia
        via ``register_relationship`` with relation ``"OBSERVES"``).

        Args:
            canonical_id: Canonical component ID being observed.

        Returns:
            List of observation RelationshipEdge objects.
        """
        return self.get_edges(target=canonical_id, relation="OBSERVES")

    def get_verifiers(self, canonical_id: str) -> list[TestRegistration]:
        """Find all tests that verify a given component.

        Alias for ``get_tests_for_component`` using the canonical ID.

        Args:
            canonical_id: Canonical component ID to find tests for.

        Returns:
            List of TestRegistration objects that validate this component.
        """
        return self.get_tests_for_component(canonical_id)

    def get_public_nerve_coverage(self) -> dict[str, list[str]]:
        """Compute test coverage for PUBLIC nerves.

        Scans all registered modules for exported component names,
        then checks which of those have test registrations covering
        them. This supports the release-mode check that all PUBLIC
        nerves must be tested.

        Returns:
            Dictionary mapping canonical component IDs of PUBLIC
            (exported) components to lists of test names that
            validate them. Components with no tests will have an
            empty list.
        """
        coverage: dict[str, list[str]] = {}

        for mod_name, mod_meta in self._modules.items():
            for export_name in mod_meta.exports:
                canonical_id = f"{mod_name}::{export_name}"
                tests = self.get_tests_for_component(canonical_id)
                coverage[canonical_id] = [t.name for t in tests]

        return coverage

    def get_untested_public_nerves(self) -> list[str]:
        """Find PUBLIC nerves that have no test coverage.

        Returns:
            List of canonical IDs for exported components that
            have no test registrations validating them.
        """
        coverage = self.get_public_nerve_coverage()
        return [cid for cid, tests in coverage.items() if not tests]

    # ------------------------------------------------------------------
    # IR storage
    # ------------------------------------------------------------------

    def store_ir(
        self, module_name: str, ir_data: dict[str, object]
    ) -> None:
        """Store IR data for a module, making it available at runtime.

        Args:
            module_name: The module whose IR data is being stored.
            ir_data: The parsed IR (e.g. from a ``.s0ma.json`` file).
        """
        with self._lock:
            self._ir_store[module_name] = ir_data
            logger.debug("Stored IR for module '%s'.", module_name)

    def get_ir(self, module_name: str) -> dict[str, object] | None:
        """Retrieve stored IR data for a module.

        Args:
            module_name: The module to look up.

        Returns:
            The IR dict, or None if no IR is stored for this module.
        """
        return self._ir_store.get(module_name)

    def get_all_ir(self) -> dict[str, dict[str, object]]:
        """Return all stored IR data.

        Returns:
            A copy of the full IR store keyed by module name.
        """
        return dict(self._ir_store)

    # ------------------------------------------------------------------
    # Plugin registration
    # ------------------------------------------------------------------

    def register_plugin(
        self,
        *,
        name: str,
        version: str,
        intent: str,
        registers: list[str] | None = None,
        requires_core: list[str] | None = None,
        source_file: str | None = None,
    ) -> PluginRegistration:
        """Register a plugin and validate its core dependencies exist.

        Args:
            name: Unique plugin name.
            version: Semantic version string.
            intent: Human-readable purpose statement.
            registers: Component names this plugin provides.
            requires_core: Component names this plugin depends on
                (must already be registered).
            source_file: Path to the plugin source file.

        Returns:
            The stored PluginRegistration.

        Raises:
            RegistryIntegrityError: If a required core component is
                not registered.
        """
        for dep in (requires_core or []):
            if self._resolve_key(dep) is None:
                raise RegistryIntegrityError(
                    f"Plugin '{name}' requires core component '{dep}' "
                    f"which is not registered."
                )
        plugin = PluginRegistration(
            name=name,
            version=version,
            intent=intent,
            registers=list(registers or []),
            requires_core=list(requires_core or []),
            source_file=source_file,
        )
        with self._lock:
            self._plugins[name] = plugin
            logger.info("Registered plugin '%s' v%s.", name, version)
            if self._persist:
                self._persist_plugin(plugin)
        return plugin

    def get_plugin(self, name: str) -> PluginRegistration | None:
        """Retrieve a registered plugin by name."""
        return self._plugins.get(name)

    def get_all_plugins(self) -> dict[str, PluginRegistration]:
        """Return all registered plugins."""
        return dict(self._plugins)

    # ------------------------------------------------------------------
    # Documentation subsystem — doc-ref / doc-guide / example
    # ------------------------------------------------------------------
    #
    # See the documentation-subsystem implementation plan (Milestone 2)
    # and design overview §§6, 10.2. These functions are the public write
    # path invoked by DSL-generated modules containing ``doc-ref``,
    # ``doc-guide``, and ``example`` declarations.

    def register_doc_ref(
        self,
        *,
        name: str,
        module: str,
        intent: str,
        format: str,  # noqa: A002 — field name mandated by design §6 / plan M2
        output: str,
        covers: list[FilterExpr] | None = None,
        sections: list[Section] | None = None,
        content_hash: str = "",
        source_span: SourceSpan | None = None,
        idempotent: bool = False,
    ) -> DocRefRegistration:
        """Register a ``doc-ref`` declaration.

        Args:
            name: Unique doc-ref name (key in the registry store).
            module: Canonical module ID the doc-ref lives in.
            intent: Human-readable purpose statement.
            format: Output format — one of ``markdown``, ``html``, ``json``.
            output: Relative output path (no leading ``/``, no ``..``).
            covers: Filter expressions selecting entities the doc covers.
            sections: Rendering sections emitted by the doc.
            content_hash: Deterministic digest over referenced state.
            source_span: Declaration location in source.
            idempotent: If True, silently replace an existing registration
                with the same name (upsert). If False (default), raise
                RegistrationError on duplicate.

        Returns:
            The stored DocRefRegistration.

        Raises:
            RegistrationError: Name already registered and ``idempotent`` is
                False.
            ValueError: ``format`` unknown or ``output`` not a safe relative
                path.
        """
        _validate_doc_format(format)
        _validate_relative_output(output)

        reg = DocRefRegistration(
            name=name,
            module=module,
            intent=intent,
            format=format,
            output=output,
            covers=list(covers or []),
            sections=list(sections or []),
            content_hash=content_hash,
            source_span=source_span,
        )
        with self._lock:
            if name in self._doc_refs and not idempotent:
                raise RegistrationError(
                    f"doc-ref '{name}' is already registered "
                    f"(module='{self._doc_refs[name].module}'). "
                    f"Pass idempotent=True to replace."
                )
            self._doc_refs[name] = reg
            logger.debug(
                "Registered doc-ref '%s' (module=%s, format=%s)",
                name, module, format,
            )
            if self._persist:
                self._persist_doc_ref(reg)
        return reg

    def register_doc_guide(
        self,
        *,
        name: str,
        module: str,
        intent: str,
        format: str,  # noqa: A002 — field name mandated by design §6 / plan M2
        output: str,
        covers: list[EntityRef] | None = None,
        asserts: list[AssertExpr] | None = None,
        examples: list[EntityRef] | None = None,
        body: str = "",
        content_hash: str = "",
        source_span: SourceSpan | None = None,
        idempotent: bool = False,
    ) -> DocGuideRegistration:
        """Register a ``doc-guide`` declaration.

        Args:
            name: Unique doc-guide name.
            module: Canonical module ID the doc-guide lives in.
            intent: Human-readable purpose statement.
            format: Output format — one of ``markdown``, ``html``, ``json``.
            output: Relative output path.
            covers: Entities the guide covers.
            asserts: Verifiable assertions attached to the guide.
            examples: Canonical examples referenced by the guide.
            body: Authored prose body.
            content_hash: Deterministic digest over referenced state.
            source_span: Declaration location in source.
            idempotent: If True, silently replace an existing registration.

        Returns:
            The stored DocGuideRegistration.

        Raises:
            RegistrationError: Name already registered and ``idempotent`` is
                False.
            ValueError: ``format`` unknown or ``output`` not a safe relative
                path.
        """
        _validate_doc_format(format)
        _validate_relative_output(output)

        reg = DocGuideRegistration(
            name=name,
            module=module,
            intent=intent,
            format=format,
            output=output,
            covers=list(covers or []),
            asserts=list(asserts or []),
            examples=list(examples or []),
            body=body,
            content_hash=content_hash,
            source_span=source_span,
        )
        with self._lock:
            if name in self._doc_guides and not idempotent:
                raise RegistrationError(
                    f"doc-guide '{name}' is already registered "
                    f"(module='{self._doc_guides[name].module}'). "
                    f"Pass idempotent=True to replace."
                )
            self._doc_guides[name] = reg
            logger.debug(
                "Registered doc-guide '%s' (module=%s, format=%s)",
                name, module, format,
            )
            if self._persist:
                self._persist_doc_guide(reg)
        return reg

    def register_example(
        self,
        *,
        name: str,
        module: str,
        intent: str,
        demonstrates: list[EntityRef],
        runs_in: Literal["standalone", "pytest", "integration"] = "standalone",
        body: str = "",
        source_span: SourceSpan | None = None,
        idempotent: bool = False,
    ) -> ExampleRegistration:
        """Register an ``example`` declaration.

        ``demonstrates`` is mandatory (design R-30 / §6.3): an example that
        does not demonstrate any registered component would have no
        verifiable relationship to the self-model.

        Args:
            name: Unique example name.
            module: Canonical module ID the example lives in.
            intent: Human-readable purpose statement.
            demonstrates: One or more entities the example demonstrates
                (must be non-empty).
            runs_in: Dispatcher selector — ``standalone``, ``pytest``, or
                ``integration``.
            body: Executable source, stored verbatim.
            source_span: Declaration location in source.
            idempotent: If True, silently replace an existing registration.

        Returns:
            The stored ExampleRegistration.

        Raises:
            RegistrationError: Name already registered and ``idempotent`` is
                False.
            ValueError: ``demonstrates`` is empty or ``runs_in`` is unknown.
        """
        if not demonstrates:
            raise ValueError(
                f"example '{name}' must declare at least one 'demonstrates' "
                f"target (design R-30 / §6.3)."
            )
        if runs_in not in _VALID_RUNS_IN:
            raise ValueError(
                f"Unknown runs_in '{runs_in}'. "
                f"Expected one of {sorted(_VALID_RUNS_IN)}."
            )

        reg = ExampleRegistration(
            name=name,
            module=module,
            intent=intent,
            demonstrates=list(demonstrates),
            runs_in=runs_in,
            body=body,
            source_span=source_span,
        )
        with self._lock:
            if name in self._examples and not idempotent:
                raise RegistrationError(
                    f"example '{name}' is already registered "
                    f"(module='{self._examples[name].module}'). "
                    f"Pass idempotent=True to replace."
                )
            self._examples[name] = reg
            logger.debug(
                "Registered example '%s' (module=%s, runs_in=%s)",
                name, module, runs_in,
            )
            if self._persist:
                self._persist_example(reg)
        return reg

    def get_doc_ref(self, name: str) -> DocRefRegistration | None:
        """Retrieve a doc-ref registration by name."""
        return self._doc_refs.get(name)

    def get_doc_guide(self, name: str) -> DocGuideRegistration | None:
        """Retrieve a doc-guide registration by name."""
        return self._doc_guides.get(name)

    def get_example(self, name: str) -> ExampleRegistration | None:
        """Retrieve an example registration by name."""
        return self._examples.get(name)

    # ------------------------------------------------------------------
    # Reset and teardown
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all registered components from memory and persistence.

        Used for test isolation and framework re-initialization.
        """
        with self._lock:
            self._components.clear()
            self._modules.clear()
            self._edges.clear()
            self._test_registrations.clear()
            self._ir_store.clear()
            self._plugins.clear()
            self._doc_refs.clear()
            self._doc_guides.clear()
            self._examples.clear()
            self._adopted_files.clear()
            # Clear import-hook anomalies but keep subscriber bindings —
            # tests and re-initialisation should not strand subscribers
            # that re-attach across resets.
            self._import_hook_anomalies.clear()
            if self._persist:
                self._clear_persistence()
            logger.info("Registry reset: all components cleared.")

    def close(self) -> None:
        """Close the SQLite connection if open."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    # ------------------------------------------------------------------
    # SQLite persistence internals
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Initialize the SQLite database and create tables if needed."""
        if self._db_path is None:
            return

        # Ensure parent directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS components (
                name TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                layer TEXT NOT NULL,
                intent TEXT NOT NULL,
                contracts_json TEXT,
                dependencies_json TEXT,
                resource_profile_json TEXT,
                version TEXT,
                metadata_json TEXT,
                module_path TEXT,
                qualified_name TEXT,
                source_file TEXT,
                registered_at TEXT,
                is_framework INTEGER DEFAULT 0,
                module_scoped INTEGER DEFAULT 0
            )
            """
        )
        # Additive column migration for legacy databases (pre-0.3.0). The
        # CREATE-IF-NOT-EXISTS above does not add columns to an existing
        # table, so an explicit ALTER is needed when the column is missing.
        # Suppressed error means the column already exists — typical case.
        with contextlib.suppress(sqlite3.OperationalError):
            self._connection.execute(
                "ALTER TABLE components ADD COLUMN module_scoped INTEGER DEFAULT 0"
            )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS modules (
                name TEXT PRIMARY KEY,
                layer TEXT NOT NULL,
                version TEXT NOT NULL,
                intent TEXT NOT NULL,
                exports_json TEXT,
                content_hash TEXT,
                tags_json TEXT,
                source_file TEXT
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS edges (
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                relation TEXT NOT NULL,
                intent TEXT,
                carries TEXT,
                coupling TEXT,
                origin TEXT,
                PRIMARY KEY (source, target, relation)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS test_registrations (
                name TEXT PRIMARY KEY,
                intent TEXT NOT NULL,
                validates_json TEXT,
                source_file TEXT
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS plugins (
                name TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                intent TEXT NOT NULL,
                registers_json TEXT NOT NULL DEFAULT '[]',
                requires_core_json TEXT NOT NULL DEFAULT '[]',
                source_file TEXT
            )
            """
        )
        # Documentation subsystem tables — design §§6, 10.1.
        # Persisted as whole-payload JSON rather than per-field columns
        # because the registration shapes are richer (nested FilterExpr /
        # Section / EntityRef / AssertExpr / SourceSpan) and the registry
        # only reads them back through from_dict in _load_all.
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS doc_refs (
                name TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS doc_guides (
                name TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS examples (
                name TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            )
            """
        )
        # Adopted files (0.11.0, batch-01a D2) — whole-payload JSON like
        # the documentation stores: the record shape is read back only
        # through AdoptedFile.from_dict in _load_all.
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS adopted_files (
                path TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def _persist_spec(self, spec: ComponentSpec) -> None:
        """Persist a ComponentSpec to SQLite."""
        if self._connection is None:
            return

        resource_profile_json: str | None = None
        if spec.resource_profile is not None:
            resource_profile_json = json.dumps(spec.resource_profile.to_dict())

        # Module-scoped specs are persisted under their qualified key so two
        # specs sharing a bare name across different modules do not collide
        # on the SQLite primary key. Bare-keyed specs (the default) keep the
        # legacy bare-name PK shape.
        registry_key = self._registry_key(spec)
        self._connection.execute(
            """
            INSERT OR REPLACE INTO components (
                name, kind, layer, intent, contracts_json,
                dependencies_json, resource_profile_json, version,
                metadata_json, module_path, qualified_name,
                source_file, registered_at, is_framework, module_scoped
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                registry_key,
                spec.kind.name,
                spec.layer.name,
                spec.intent,
                json.dumps(spec.contracts.to_dict()),
                json.dumps(spec.dependencies),
                resource_profile_json,
                spec.version,
                json.dumps(spec.metadata),
                spec.module_path,
                spec.qualified_name,
                spec.source_file,
                spec.registered_at.isoformat(),
                1 if spec.is_framework else 0,
                1 if spec.module_scoped else 0,
            ),
        )
        self._connection.commit()

    def _delete_from_db(self, name: str) -> None:
        """Remove a single component from the SQLite persistence layer.

        Called under the write lock by unregister(). The caller is
        responsible for holding self._lock.

        Args:
            name: The component name to delete from the database.
        """
        if self._connection is not None:
            self._connection.execute(
                "DELETE FROM components WHERE name = ?", (name,)
            )
            self._connection.commit()

    def _persist_module(self, meta: ModuleMetadata) -> None:
        """Persist a ModuleMetadata to SQLite."""
        if self._connection is None:
            return
        self._connection.execute(
            """
            INSERT OR REPLACE INTO modules
                (name, layer, version, intent, exports_json, content_hash, tags_json, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meta.name,
                meta.layer,
                meta.version,
                meta.intent,
                json.dumps(meta.exports),
                meta.content_hash,
                json.dumps(meta.tags),
                meta.source_file,
            ),
        )
        self._connection.commit()

    def _persist_edge(self, edge: RelationshipEdge) -> None:
        """Persist a RelationshipEdge to SQLite."""
        if self._connection is None:
            return
        self._connection.execute(
            """
            INSERT OR REPLACE INTO edges
                (source, target, relation, intent, carries, coupling, origin)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge.source,
                edge.target,
                edge.relation,
                edge.intent,
                edge.carries,
                edge.coupling,
                edge.origin,
            ),
        )
        self._connection.commit()

    def _persist_test(self, reg: TestRegistration) -> None:
        """Persist a TestRegistration to SQLite."""
        if self._connection is None:
            return
        self._connection.execute(
            """
            INSERT OR REPLACE INTO test_registrations
                (name, intent, validates_json, source_file)
            VALUES (?, ?, ?, ?)
            """,
            (
                reg.name,
                reg.intent,
                json.dumps(reg.validates),
                reg.source_file,
            ),
        )
        self._connection.commit()

    def _persist_plugin(self, plugin: PluginRegistration) -> None:
        """Persist a PluginRegistration to SQLite."""
        if self._connection is None:
            return
        self._connection.execute(
            """
            INSERT OR REPLACE INTO plugins
                (name, version, intent, registers_json,
                 requires_core_json, source_file)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                plugin.name,
                plugin.version,
                plugin.intent,
                json.dumps(plugin.registers),
                json.dumps(plugin.requires_core),
                plugin.source_file,
            ),
        )
        self._connection.commit()

    def _persist_doc_ref(self, reg: DocRefRegistration) -> None:
        """Persist a DocRefRegistration to SQLite as whole-payload JSON."""
        if self._connection is None:
            return
        self._connection.execute(
            "INSERT OR REPLACE INTO doc_refs (name, payload_json) VALUES (?, ?)",
            (reg.name, json.dumps(reg.to_dict())),
        )
        self._connection.commit()

    def _persist_adopted_file(self, record: AdoptedFile) -> None:
        """Persist an AdoptedFile to SQLite as whole-payload JSON."""
        if self._connection is None:
            return
        self._connection.execute(
            "INSERT OR REPLACE INTO adopted_files (path, payload_json)"
            " VALUES (?, ?)",
            (record.path, json.dumps(record.to_dict())),
        )
        self._connection.commit()

    def _persist_doc_guide(self, reg: DocGuideRegistration) -> None:
        """Persist a DocGuideRegistration to SQLite as whole-payload JSON."""
        if self._connection is None:
            return
        self._connection.execute(
            "INSERT OR REPLACE INTO doc_guides (name, payload_json) VALUES (?, ?)",
            (reg.name, json.dumps(reg.to_dict())),
        )
        self._connection.commit()

    def _persist_example(self, reg: ExampleRegistration) -> None:
        """Persist an ExampleRegistration to SQLite as whole-payload JSON."""
        if self._connection is None:
            return
        self._connection.execute(
            "INSERT OR REPLACE INTO examples (name, payload_json) VALUES (?, ?)",
            (reg.name, json.dumps(reg.to_dict())),
        )
        self._connection.commit()

    def _load_all(self) -> None:
        """Load all components, modules, edges, and tests from SQLite."""
        if self._connection is None:
            return

        # Load components
        cursor = self._connection.execute("SELECT * FROM components")
        rows = cursor.fetchall()
        column_names = [description[0] for description in cursor.description]

        for row in rows:
            row_dict = dict(zip(column_names, row, strict=True))
            spec = self._row_to_spec(row_dict)
            self._components[self._registry_key(spec)] = spec

        # Load modules
        try:
            cursor = self._connection.execute("SELECT * FROM modules")
            rows = cursor.fetchall()
            col_names = [d[0] for d in cursor.description]
            for row in rows:
                row_dict = dict(zip(col_names, row, strict=True))
                meta = ModuleMetadata(
                    name=str(row_dict["name"]),
                    layer=str(row_dict["layer"]),
                    version=str(row_dict["version"]),
                    intent=str(row_dict["intent"]),
                    exports=(
                        json.loads(str(row_dict["exports_json"]))
                        if row_dict["exports_json"]
                        else []
                    ),
                    content_hash=str(row_dict["content_hash"]) if row_dict["content_hash"] else "",
                    tags=json.loads(str(row_dict["tags_json"])) if row_dict["tags_json"] else [],
                    source_file=str(row_dict["source_file"]) if row_dict["source_file"] else None,
                )
                self._modules[meta.name] = meta
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet (pre-M14 DB)

        # Load edges
        try:
            cursor = self._connection.execute("SELECT * FROM edges")
            rows = cursor.fetchall()
            col_names = [d[0] for d in cursor.description]
            for row in rows:
                row_dict = dict(zip(col_names, row, strict=True))
                edge = RelationshipEdge(
                    source=str(row_dict["source"]),
                    target=str(row_dict["target"]),
                    relation=str(row_dict["relation"]),
                    intent=str(row_dict["intent"]) if row_dict["intent"] else "",
                    carries=str(row_dict["carries"]) if row_dict["carries"] else "",
                    coupling=str(row_dict["coupling"]) if row_dict["coupling"] else "",
                    origin=str(row_dict["origin"]) if row_dict["origin"] else "",
                )
                self._edges.append(edge)
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet (pre-M14 DB)

        # Load test registrations
        try:
            cursor = self._connection.execute("SELECT * FROM test_registrations")
            rows = cursor.fetchall()
            col_names = [d[0] for d in cursor.description]
            for row in rows:
                row_dict = dict(zip(col_names, row, strict=True))
                reg = TestRegistration(
                    name=str(row_dict["name"]),
                    intent=str(row_dict["intent"]),
                    validates=(
                        json.loads(str(row_dict["validates_json"]))
                        if row_dict["validates_json"]
                        else []
                    ),
                    source_file=str(row_dict["source_file"]) if row_dict["source_file"] else None,
                )
                self._test_registrations[reg.name] = reg
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet (pre-M14 DB)

        # Load plugins
        try:
            cursor = self._connection.execute("SELECT * FROM plugins")
            rows = cursor.fetchall()
            col_names = [d[0] for d in cursor.description]
            for row in rows:
                row_dict = dict(zip(col_names, row, strict=True))
                plugin = PluginRegistration(
                    name=str(row_dict["name"]),
                    version=str(row_dict["version"]),
                    intent=str(row_dict["intent"]),
                    registers=json.loads(
                        str(row_dict["registers_json"])
                    ) if row_dict["registers_json"] else [],
                    requires_core=json.loads(
                        str(row_dict["requires_core_json"])
                    ) if row_dict["requires_core_json"] else [],
                    source_file=str(
                        row_dict["source_file"]
                    ) if row_dict["source_file"] else None,
                )
                self._plugins[plugin.name] = plugin
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet (pre-plugin DB)

        # Load doc-refs (documentation subsystem, design §§6, 10.1)
        try:
            cursor = self._connection.execute("SELECT * FROM doc_refs")
            for name, payload_json in cursor.fetchall():
                doc_ref = DocRefRegistration.from_dict(json.loads(payload_json))
                self._doc_refs[str(name)] = doc_ref
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet (pre-docs DB)

        # Load doc-guides
        try:
            cursor = self._connection.execute("SELECT * FROM doc_guides")
            for name, payload_json in cursor.fetchall():
                guide = DocGuideRegistration.from_dict(json.loads(payload_json))
                self._doc_guides[str(name)] = guide
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet (pre-docs DB)

        # Load examples
        try:
            cursor = self._connection.execute("SELECT * FROM examples")
            for name, payload_json in cursor.fetchall():
                example = ExampleRegistration.from_dict(json.loads(payload_json))
                self._examples[str(name)] = example
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet (pre-docs DB)

        # Load adopted files (0.11.0, batch-01a D2)
        try:
            cursor = self._connection.execute("SELECT * FROM adopted_files")
            for path, payload_json in cursor.fetchall():
                record = AdoptedFile.from_dict(json.loads(payload_json))
                self._adopted_files[str(path)] = record
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet (pre-adoption DB)

    @staticmethod
    def _row_to_spec(row: dict[str, object]) -> ComponentSpec:
        """Convert a SQLite row dictionary to a ComponentSpec.

        Module-scoped specs are persisted with their qualified key in the
        ``name`` column. Re-derive the bare ``spec.name`` from the row's
        ``module_path`` so the returned spec is honest about its identity
        regardless of how it is keyed in the registry dict.
        """
        from datetime import datetime

        from s0ma.types import ComponentKind, Layer

        # Parse contracts JSON
        contracts_data = json.loads(str(row["contracts_json"])) if row["contracts_json"] else {}
        contracts = Contract(
            preconditions=contracts_data.get("preconditions", []),
            postconditions=contracts_data.get("postconditions", []),
            invariants=contracts_data.get("invariants", []),
            max_latency_ms=contracts_data.get("max_latency_ms"),
            error_rate_threshold=contracts_data.get("error_rate_threshold"),
            input_type=contracts_data.get("input_type"),
            output_type=contracts_data.get("output_type"),
            forbids=contracts_data.get("forbids", []),
        )

        # Parse dependencies JSON
        dependencies: list[str] = (
            json.loads(str(row["dependencies_json"]))
            if row["dependencies_json"]
            else []
        )

        # Parse resource profile JSON
        resource_profile: ResourceProfile | None = None
        if row["resource_profile_json"]:
            rp_data = json.loads(str(row["resource_profile_json"]))
            resource_profile = ResourceProfile(**rp_data)

        # Parse metadata JSON
        metadata: dict[str, object] = (
            json.loads(str(row["metadata_json"]))
            if row["metadata_json"]
            else {}
        )

        # Parse registered_at timestamp
        registered_at = datetime.fromisoformat(str(row["registered_at"]))

        # ``module_scoped`` column may be absent on legacy rows (pre-0.3.0
        # database). Default to False so legacy specs round-trip unchanged.
        module_scoped_val = row.get("module_scoped", 0)
        module_scoped = bool(module_scoped_val) if module_scoped_val is not None else False

        # When module-scoped, the row's ``name`` column holds the qualified
        # key — reconstitute the bare spec name from the suffix.
        raw_name = str(row["name"])
        spec_module_path = str(row["module_path"]) if row["module_path"] else ""
        if module_scoped and spec_module_path and raw_name.startswith(spec_module_path + "::"):
            spec_name = raw_name[len(spec_module_path) + 2:]
        else:
            spec_name = raw_name

        return ComponentSpec(
            name=spec_name,
            kind=ComponentKind[str(row["kind"])],
            layer=Layer[str(row["layer"])],
            intent=str(row["intent"]),
            contracts=contracts,
            dependencies=dependencies,
            resource_profile=resource_profile,
            version=str(row["version"]) if row["version"] else "0.1.0",
            metadata=metadata,
            module_path=spec_module_path,
            qualified_name=str(row["qualified_name"]) if row["qualified_name"] else "",
            source_file=str(row["source_file"]) if row["source_file"] else None,
            registered_at=registered_at,
            is_framework=bool(row["is_framework"]),
            module_scoped=module_scoped,
        )

    def _clear_persistence(self) -> None:
        """Drop and recreate all tables."""
        if self._connection is None:
            return
        self._connection.execute("DROP TABLE IF EXISTS components")
        self._connection.execute("DROP TABLE IF EXISTS modules")
        self._connection.execute("DROP TABLE IF EXISTS edges")
        self._connection.execute("DROP TABLE IF EXISTS test_registrations")
        self._connection.execute("DROP TABLE IF EXISTS plugins")
        self._connection.execute("DROP TABLE IF EXISTS doc_refs")
        self._connection.execute("DROP TABLE IF EXISTS doc_guides")
        self._connection.execute("DROP TABLE IF EXISTS examples")
        self._connection.execute("DROP TABLE IF EXISTS adopted_files")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS components (
                name TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                layer TEXT NOT NULL,
                intent TEXT NOT NULL,
                contracts_json TEXT,
                dependencies_json TEXT,
                resource_profile_json TEXT,
                version TEXT,
                metadata_json TEXT,
                module_path TEXT,
                qualified_name TEXT,
                source_file TEXT,
                registered_at TEXT,
                is_framework INTEGER DEFAULT 0,
                module_scoped INTEGER DEFAULT 0
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS modules (
                name TEXT PRIMARY KEY,
                layer TEXT NOT NULL,
                version TEXT NOT NULL,
                intent TEXT NOT NULL,
                exports_json TEXT,
                content_hash TEXT,
                tags_json TEXT,
                source_file TEXT
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS edges (
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                relation TEXT NOT NULL,
                intent TEXT,
                carries TEXT,
                coupling TEXT,
                origin TEXT,
                PRIMARY KEY (source, target, relation)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS test_registrations (
                name TEXT PRIMARY KEY,
                intent TEXT NOT NULL,
                validates_json TEXT,
                source_file TEXT
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS plugins (
                name TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                intent TEXT NOT NULL,
                registers_json TEXT NOT NULL DEFAULT '[]',
                requires_core_json TEXT NOT NULL DEFAULT '[]',
                source_file TEXT
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS doc_refs (
                name TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS doc_guides (
                name TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS examples (
                name TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS adopted_files (
                path TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._connection.commit()


# ======================================================================
# Global registry singleton
# ======================================================================

_global_registry: ComponentRegistry | None = None
_global_lock = threading.Lock()


def get_registry(
    persist: bool = True,
    db_path: str | Path | None = None,
    strict_dependencies: bool = False,
) -> ComponentRegistry:
    """Get or create the global ComponentRegistry singleton.

    On first call, creates a new registry with the specified options and
    registers s0ma's own framework components in it, so the singleton
    knows the framework from the moment it exists: a ``@component`` that
    runs before ``s0ma.initialize()`` — at import time, in a toolchain
    process, or in a library that never calls ``initialize`` — resolves a
    declared dependency on a framework component the same as one that
    runs after it. Subsequent calls return the existing singleton (options
    are ignored after the first call).

    The registry is published before the framework registers, so a
    ``get_registry()`` call made while the framework is registering — a
    module the bootstrap imports that decorates at import time — receives
    the same instance instead of deadlocking or creating a second one.

    Args:
        persist: If True, enable SQLite persistence.
        db_path: Path to the SQLite database file.
        strict_dependencies: If True, raise on unresolved dependencies.

    Returns:
        The global ComponentRegistry instance.
    """
    global _global_registry
    if _global_registry is None:
        with _global_lock:
            # Double-check locking pattern
            if _global_registry is None:
                _global_registry = ComponentRegistry(
                    persist=persist,
                    db_path=db_path,
                    strict_dependencies=strict_dependencies,
                )
                # Imported here, not at module level: _bootstrap imports
                # the framework packages this module must not depend on
                # at import time.
                from s0ma._bootstrap import bootstrap_register

                bootstrap_register(_global_registry)
    return _global_registry


def set_registry(registry: ComponentRegistry) -> None:
    """Replace the global registry with a custom instance.

    Useful for testing or custom configurations.

    Args:
        registry: The registry instance to use as the global singleton.
    """
    global _global_registry
    with _global_lock:
        _global_registry = registry


def reset_registry() -> None:
    """Clear and remove the global registry singleton.

    Resets the global registry to None so the next get_registry() call
    creates a fresh instance. Also calls reset() on the existing registry
    to clear its contents.
    """
    global _global_registry
    with _global_lock:
        if _global_registry is not None:
            _global_registry.reset()
            _global_registry.close()
            _global_registry = None
