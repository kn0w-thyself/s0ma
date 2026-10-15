"""Import hook — the enforcement mechanism for the load-bearing self-model.

Implements a sys.meta_path finder/loader that scans modules at import time
and enforces registration. Any module within an s0ma-managed project
that contains unregistered public classes or functions will fail to import
in strict mode.

This is what makes the self-model load-bearing rather than advisory.
Without the import hook, @component is just documentation. With it,
the self-model is a structural requirement.

Key classes:
    - S0maFinder: decides whether a module is in scope for enforcement
    - S0maLoader: wraps standard loader, adds post-load verification

Key functions:
    - install_import_hook(): activate enforcement for a project root
    - uninstall_import_hook(): deactivate enforcement
    - is_hook_installed(): check if the hook is active
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import inspect
import logging
import sys
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma.exceptions import UnregisteredComponentError

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from s0ma.types import Layer

__all__ = [
    "S0maFinder",
    "S0maLoader",
    "S0maDSLLoader",
    "install_import_hook",
    "uninstall_import_hook",
    "is_hook_installed",
]

logger = logging.getLogger("s0ma")

# Module-level marker attribute names for documentation-subsystem
# declarations emitted by the s0ma-dsl transpiler. Each attribute, when
# present on a loaded module, is a tuple (or other iterable) of names
# whose matching registrations must be present in the registry after the
# module finishes executing. See docs/references/documentation_subsystem.md.
DOC_REF_MARKER_ATTR = "__s0ma_doc_ref__"
DOC_GUIDE_MARKER_ATTR = "__s0ma_doc_guide__"
EXAMPLE_MARKER_ATTR = "__s0ma_example__"


def _is_public_entity(name: str, obj: object) -> bool:
    """Determine whether an object is a public class or function.

    Only classes and functions with public names (not starting with ``_``)
    are subject to registration enforcement. Module-level variables,
    constants, type aliases, and imported names are excluded.

    Args:
        name: The attribute name in the module namespace.
        obj: The object bound to that name.

    Returns:
        True if the object should be checked for registration.
    """
    # Skip private/protected names
    if name.startswith("_"):
        return False

    # Only check classes and functions defined in the module
    if isinstance(obj, type):
        return True
    if callable(obj) and isinstance(obj, type(lambda: None)):
        # This is a plain function (not a built-in, not a class instance method)
        return inspect.isfunction(obj)

    return False


def _get_unregistered_entities(
    module: ModuleType,
) -> list[tuple[str, object]]:
    """Scan a module for public entities lacking registration.

    Examines every public class and function in the module's namespace.
    An entity passes if it has either ``__component__`` (registered via
    ``@component``) or ``__s0ma_internal__`` (exempted via
    ``@internal``). Entities that have neither are collected as violations.

    Args:
        module: A fully-loaded Python module to scan.

    Returns:
        List of (name, object) tuples for unregistered entities.
    """
    unregistered: list[tuple[str, object]] = []

    for attr_name in dir(module):
        obj = getattr(module, attr_name, None)
        if obj is None:
            continue

        # Only check public classes and functions
        if not _is_public_entity(attr_name, obj):
            continue

        # Check if the entity was defined in this module (not imported)
        obj_module = getattr(obj, "__module__", None)
        if obj_module is not None and obj_module != module.__name__:
            # This entity was imported from elsewhere — skip it
            continue

        # Check for registration or internal exemption
        has_component = hasattr(obj, "__component__")
        has_internal = getattr(obj, "__s0ma_internal__", False) is True

        if not has_component and not has_internal:
            unregistered.append((attr_name, obj))

    return unregistered


def _get_unregistered_doc_declarations(
    module: ModuleType,
) -> list[tuple[str, str]]:
    """Scan a module for documentation-subsystem markers whose declarations
    are missing from the active registry.

    The s0ma-dsl transpiler emits three module-level marker attributes
    (``__s0ma_doc_ref__``, ``__s0ma_doc_guide__``, ``__s0ma_example__``),
    each holding an iterable of registration names declared in that module.
    After the module finishes executing, every listed name must resolve
    to a registration in the global registry. Mismatches typically mean
    the generated code is stale with respect to the current registry.

    Args:
        module: A fully-loaded Python module to scan.

    Returns:
        List of (kind, name) tuples for declarations that do not resolve
        to a registration in the global registry. Empty list if the
        module declares no documentation markers or all names resolve.
    """
    # Late import to avoid a circular dependency between registry and
    # import_hook at package import time.
    from s0ma.registry import get_registry

    registry = get_registry(persist=False)

    checks: tuple[tuple[str, str, Callable[[str], object]], ...] = (
        (DOC_REF_MARKER_ATTR, "doc-ref", registry.get_doc_ref),
        (DOC_GUIDE_MARKER_ATTR, "doc-guide", registry.get_doc_guide),
        (EXAMPLE_MARKER_ATTR, "example", registry.get_example),
    )

    missing: list[tuple[str, str]] = []
    for attr_name, kind, lookup in checks:
        declared = getattr(module, attr_name, None)
        if declared is None:
            continue
        # Accept a bare string as shorthand for a single declaration.
        if isinstance(declared, str):
            names: tuple[str, ...] = (declared,)
        else:
            try:
                names = tuple(declared)
            except TypeError:
                # Marker is present but not iterable — treat as malformed
                # and report as a violation so the author notices.
                missing.append((kind, repr(declared)))
                continue
        for name in names:
            if lookup(str(name)) is None:
                missing.append((kind, str(name)))

    return missing


def _format_doc_violation_message(
    module_name: str,
    module_file: str | None,
    missing: list[tuple[str, str]],
) -> str:
    """Format an actionable error message for missing doc declarations.

    Args:
        module_name: Fully qualified module name.
        module_file: Filesystem path to the module source (if known).
        missing: List of (kind, name) tuples — one per missing declaration.

    Returns:
        Human-readable error message with remediation suggestions.
    """
    file_info = f" ({module_file})" if module_file else ""
    entity_lines = [f"  - {kind} '{name}'" for kind, name in missing]
    entities_str = "\n".join(entity_lines)

    return (
        f"Module '{module_name}'{file_info} declares documentation "
        f"registrations that were not present in the registry after "
        f"import:\n"
        f"{entities_str}\n\n"
        f"This usually means the generated code is stale. To fix:\n"
        f"  1. Regenerate the module from its '.s0ma' source, OR\n"
        f"  2. Confirm register_doc_ref / register_doc_guide / "
        f"register_example is invoked with the declared name, OR\n"
        f"  3. Remove the stale __s0ma_doc_ref__ / __s0ma_doc_guide__ / "
        f"__s0ma_example__ marker."
    )


def _layer_for_module(module_name: str) -> Layer | None:
    """Best-effort lookup of the architectural layer for ``module_name``.

    The import hook is invoked very early in module loading, often
    before any of the module's components register. When this is the
    case the registry has no record for the module and ``None`` is the
    correct value to attach to an :class:`ImportHookAnomaly`. When a
    sibling module under the same name *has* registered (e.g. the hook
    is firing again on a reload), the registry's ``ModuleMetadata``
    layer name is returned as the matching :class:`Layer` enum value.
    """
    try:
        # Local import — keep the import hook self-contained and avoid
        # circular-import-time cost when this helper is unused.
        from s0ma.registry import get_registry
        from s0ma.types import Layer
    except ImportError:
        return None

    try:
        registry = get_registry(persist=False)
    except Exception:  # noqa: BLE001 — registry init must never break loader
        return None

    meta = registry._modules.get(module_name)  # noqa: SLF001 — internal coupling
    if meta is None:
        return None
    try:
        return Layer[meta.layer]
    except (KeyError, ValueError):
        return None


def _record_import_hook_anomalies(
    module_name: str,
    descriptions: list[str],
    *,
    strict: bool,
) -> None:
    """Append one :class:`ImportHookAnomaly` per detection to the registry.

    The import hook calls this whenever a foreign-code surveillance
    pass detects violations. Each ``descriptions`` entry becomes its
    own anomaly record so consumers can correlate one finding to one
    record. Severity tracks the hook's behaviour: strict-mode
    enforcement is ``ERROR`` (the same import is about to raise);
    lenient-mode enforcement is ``WARNING`` (the import proceeds but
    operators should investigate).

    Registry / import-time failures are swallowed — the anomaly
    surface is a best-effort observability channel and must never
    break the loader.
    """
    if not descriptions:
        return
    try:
        from s0ma.models import ImportHookAnomaly
        from s0ma.registry import get_registry
        from s0ma.types import AnomalySeverity
    except ImportError:
        return

    try:
        registry = get_registry(persist=False)
    except Exception:  # noqa: BLE001 — never break the loader on registry init
        return

    severity = AnomalySeverity.ERROR if strict else AnomalySeverity.WARNING
    layer = _layer_for_module(module_name)
    for description in descriptions:
        anomaly = ImportHookAnomaly(
            name=module_name,
            description=description,
            severity=severity,
            layer=layer,
        )
        try:
            registry.record_import_hook_anomaly(anomaly)
        except Exception:  # noqa: BLE001 — observability path must not raise
            logger.exception(
                "Failed to record import-hook anomaly for '%s'.",
                module_name,
            )


def _format_violation_message(
    module_name: str,
    module_file: str | None,
    unregistered: list[tuple[str, object]],
) -> str:
    """Format a clear, actionable error message for unregistered entities.

    Args:
        module_name: Fully qualified module name.
        module_file: Filesystem path to the module source.
        unregistered: List of (name, object) tuples.

    Returns:
        Human-readable error message with remediation suggestions.
    """
    file_info = f" ({module_file})" if module_file else ""
    entity_lines = []
    for name, obj in unregistered:
        entity_type = "class" if isinstance(obj, type) else "function"
        entity_lines.append(f"  - {entity_type} '{name}'")

    entities_str = "\n".join(entity_lines)

    return (
        f"Unregistered public entities detected in module "
        f"'{module_name}'{file_info}:\n"
        f"{entities_str}\n\n"
        f"All public classes and functions in s0ma-managed projects "
        f"must be registered. To fix:\n"
        f"  1. Add @component(...) decorator to register the entity, OR\n"
        f"  2. Add @internal decorator to mark it as intentionally "
        f"unregistered, OR\n"
        f"  3. Rename it with a leading underscore to make it private."
    )


class S0maLoader(importlib.abc.Loader):
    """Wraps a standard loader to add post-load registration verification.

    After the original loader executes the module, this loader scans the
    module's public namespace for unregistered classes and functions. In
    strict mode, violations raise ``UnregisteredComponentError``. In
    lenient mode, a warning is issued but the module loads normally.
    """

    def __init__(self, original_loader: importlib.abc.Loader, *, strict: bool = True) -> None:
        """Initialize with the original loader to delegate to.

        Args:
            original_loader: The real loader that will actually load the module.
            strict: If True, raise on violations. If False, warn only.
        """
        self._original_loader = original_loader
        self._strict = strict

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:
        """Delegate module creation to the original loader."""
        if hasattr(self._original_loader, "create_module"):
            return self._original_loader.create_module(spec)
        return None

    def exec_module(self, module: ModuleType) -> None:
        """Execute the module, then verify registration of public entities.

        Delegates to the original loader to execute the module code, then
        scans for unregistered entities. This ordering ensures all
        decorators have had a chance to execute before the scan runs.

        Raises:
            UnregisteredComponentError: In strict mode, if any public
                entity lacks ``@component`` or ``@internal`` decoration.
        """
        # Let the real loader execute the module first
        if hasattr(self._original_loader, "exec_module"):
            self._original_loader.exec_module(module)

        # Scan for unregistered public classes/functions
        unregistered = _get_unregistered_entities(module)

        if unregistered:
            module_file = getattr(module, "__file__", None)
            msg = _format_violation_message(
                module.__name__, module_file, unregistered
            )
            # Record one anomaly per unregistered entity (POST-1 /
            # 0.4.0) — fine-grained records let downstream B1 logic
            # correlate one finding to one detection record.
            _record_import_hook_anomalies(
                module.__name__,
                [
                    f"Unregistered public "
                    f"{'class' if isinstance(obj, type) else 'function'} "
                    f"'{name}' in module '{module.__name__}'."
                    for name, obj in unregistered
                ],
                strict=self._strict,
            )
            if self._strict:
                logger.error(
                    "Import hook enforcement: %d unregistered entit%s in '%s'",
                    len(unregistered),
                    "y" if len(unregistered) == 1 else "ies",
                    module.__name__,
                )
                raise UnregisteredComponentError(msg)

            warnings.warn(msg, stacklevel=2)
            logger.warning(
                "Import hook (lenient): %d unregistered entit%s in '%s'",
                len(unregistered),
                "y" if len(unregistered) == 1 else "ies",
                module.__name__,
            )

        # Scan for documentation declarations that were not registered
        missing_docs = _get_unregistered_doc_declarations(module)
        if missing_docs:
            module_file = getattr(module, "__file__", None)
            msg = _format_doc_violation_message(
                module.__name__, module_file, missing_docs,
            )
            _record_import_hook_anomalies(
                module.__name__,
                [
                    f"Missing documentation registration: {kind} '{name}' "
                    f"declared in module '{module.__name__}' did not "
                    f"resolve to a registry entry."
                    for kind, name in missing_docs
                ],
                strict=self._strict,
            )
            if self._strict:
                logger.error(
                    "Import hook enforcement: %d missing doc declaration"
                    "%s in '%s'",
                    len(missing_docs),
                    "" if len(missing_docs) == 1 else "s",
                    module.__name__,
                )
                raise UnregisteredComponentError(msg)

            warnings.warn(msg, stacklevel=2)
            logger.warning(
                "Import hook (lenient): %d missing doc declaration%s in '%s'",
                len(missing_docs),
                "" if len(missing_docs) == 1 else "s",
                module.__name__,
            )


class S0maDSLLoader(importlib.abc.Loader):
    """Loader for ``.s0ma`` files that transpiles on-the-fly with caching.

    When a ``.s0ma`` file is discovered by ``S0maFinder``, this loader:

    1. Checks the ``__s0ma_cache__/`` directory for a cached ``.py`` file.
    2. Compares the content hash of the source against the cached version.
    3. If the cache is stale or missing, transpiles the ``.s0ma`` file
       using the ``s0ma_dsl`` transpiler and writes the output to the
       cache directory.
    4. Executes the cached ``.py`` file as the module.

    The cache directory is ``__s0ma_cache__/`` alongside the ``.s0ma`` file.
    Cache invalidation is based on file content hashes (SHA-256).
    """

    def __init__(
        self,
        s0ma_path: Path,
        project_root: Path,
        *,
        strict: bool = True,
    ) -> None:
        """Initialize the DSL loader.

        Args:
            s0ma_path: Absolute path to the ``.s0ma`` source file.
            project_root: Project root directory for context.
            strict: If True, raise on registration violations after loading.
        """
        self.s0ma_path = s0ma_path
        self.project_root = project_root
        self.strict = strict
        self._cache_dir = s0ma_path.parent / "__s0ma_cache__"

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:
        """Return None to use default module creation semantics."""
        return None

    def exec_module(self, module: ModuleType) -> None:
        """Transpile the ``.s0ma`` file if needed, then execute the cached ``.py``.

        Steps:
        1. Read the ``.s0ma`` source and compute its content hash.
        2. Check the cache for a valid ``.py`` file with a matching hash.
        3. If the cache is stale or missing, transpile and write to cache.
        4. Execute the cached ``.py`` in the module's namespace.

        Raises:
            ImportError: If the ``.s0ma`` file cannot be transpiled.
            UnregisteredComponentError: In strict mode, if the transpiled
                module contains unregistered entities.
        """
        import hashlib

        source_text = self.s0ma_path.read_text(encoding="utf-8")
        content_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()

        # Determine cache paths
        cache_py = self._cache_dir / (self.s0ma_path.stem + ".py")
        cache_hash = self._cache_dir / (self.s0ma_path.stem + ".hash")

        # Check cache validity
        needs_transpile = True
        if cache_py.is_file() and cache_hash.is_file():
            try:
                cached_hash = cache_hash.read_text(encoding="utf-8").strip()
                if cached_hash == content_hash:
                    needs_transpile = False
                    logger.debug(
                        "Cache hit for '%s' (hash: %s...)",
                        self.s0ma_path.name, content_hash[:12],
                    )
            except OSError:
                pass

        if needs_transpile:
            logger.info(
                "Transpiling '%s' (cache %s)",
                self.s0ma_path.name,
                "stale" if cache_py.is_file() else "miss",
            )
            python_source = self._transpile(source_text)

            # Write cache (newline="\n": cached artifacts must be
            # byte-identical across platforms — INV-5)
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            cache_py.write_text(python_source, encoding="utf-8", newline="\n")
            cache_hash.write_text(content_hash, encoding="utf-8")

            # Also write .s0ma.json and .s0ma.map if transpiler supports it
            self._write_ir_and_map(source_text)

        # Execute the cached .py in the module's namespace
        py_source = cache_py.read_text(encoding="utf-8")
        module.__file__ = str(cache_py)
        module.__loader__ = self

        code = compile(py_source, str(cache_py), "exec")
        exec(code, module.__dict__)  # noqa: S102

        # Post-load verification (same as S0maLoader)
        unregistered = _get_unregistered_entities(module)
        if unregistered:
            module_file = getattr(module, "__file__", None)
            msg = _format_violation_message(
                module.__name__, module_file, unregistered
            )
            _record_import_hook_anomalies(
                module.__name__,
                [
                    f"Unregistered public "
                    f"{'class' if isinstance(obj, type) else 'function'} "
                    f"'{name}' in module '{module.__name__}'."
                    for name, obj in unregistered
                ],
                strict=self.strict,
            )
            if self.strict:
                raise UnregisteredComponentError(msg)
            warnings.warn(msg, stacklevel=2)

        # Verify documentation declarations are registered
        missing_docs = _get_unregistered_doc_declarations(module)
        if missing_docs:
            module_file = getattr(module, "__file__", None)
            msg = _format_doc_violation_message(
                module.__name__, module_file, missing_docs,
            )
            _record_import_hook_anomalies(
                module.__name__,
                [
                    f"Missing documentation registration: {kind} '{name}' "
                    f"declared in module '{module.__name__}' did not "
                    f"resolve to a registry entry."
                    for kind, name in missing_docs
                ],
                strict=self.strict,
            )
            if self.strict:
                raise UnregisteredComponentError(msg)
            warnings.warn(msg, stacklevel=2)

    def _transpile(self, source_text: str) -> str:
        """Transpile ``.s0ma`` source to Python.

        Attempts to import and use the ``s0ma_dsl`` transpiler. If the
        transpiler is not installed, raises ``ImportError`` with guidance.

        Args:
            source_text: The raw ``.s0ma`` source text.

        Returns:
            The transpiled Python source code.

        Raises:
            ImportError: If ``s0ma_dsl`` is not installed or transpilation fails.
        """
        try:
            from s0ma_dsl.codegen.python_emitter import emit_python
            from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
        except ImportError as exc:
            raise ImportError(
                f"Cannot transpile '{self.s0ma_path.name}': the s0ma-dsl "
                f"package is not installed. Install it with: "
                f"pip install -e ../s0ma-dsl\n"
                f"Original error: {exc}"
            ) from exc

        try:
            ast_module, body_warnings = parse_s0ma_with_warnings(
                source_text, filename=str(self.s0ma_path),
            )
            for w in body_warnings:
                logger.warning(
                    "%s:%d: [%s] %s", w.file, w.line, w.code, w.message,
                )
            python_source: str = emit_python(ast_module)
            return python_source
        except Exception as exc:
            raise ImportError(
                f"Transpilation failed for '{self.s0ma_path}': {exc}"
            ) from exc

    def _write_ir_and_map(self, source_text: str) -> None:
        """Write .s0ma.json and .s0ma.map alongside the cached .py.

        Best-effort: failures are logged but do not block module loading.
        """
        try:
            from s0ma_dsl.codegen.python_emitter import emit_python
            from s0ma_dsl.codegen.source_map import generate_source_map
            from s0ma_dsl.ir.builder import build_ir
            from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings

            ast_module, _warnings = parse_s0ma_with_warnings(
                source_text, filename=str(self.s0ma_path),
            )
            python_source = emit_python(ast_module)

            # IR
            ir_doc = build_ir(
                ast_module,
                source_file=str(self.s0ma_path),
                source_text=source_text,
                # Basename, not the cache path: the IR sits next to the
                # cached .py it references, and emitted artifacts must
                # not embed absolute machine paths (INV-5; same policy
                # as the s0ma-dsl build artifacts since WIN-M3).
                transpiled_file=self.s0ma_path.stem + ".py",
            )
            ir_path = self._cache_dir / (self.s0ma_path.stem + ".s0ma.json")
            import json
            # newline="\n" on both artifact writes: INV-5 byte-identity
            # across platforms.
            ir_path.write_text(
                json.dumps(ir_doc.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
                newline="\n",
            )

            # Source map
            source_map = generate_source_map(ast_module, python_source)
            map_path = self._cache_dir / (self.s0ma_path.stem + ".s0ma.map")
            map_path.write_text(
                json.dumps(source_map.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
                newline="\n",
            )
        except Exception:
            logger.debug(
                "Could not generate IR/source map for '%s' (non-fatal)",
                self.s0ma_path.name,
                exc_info=True,
            )


class S0maFinder(importlib.abc.MetaPathFinder):
    """Decides whether a module is within scope for registration enforcement.

    Only modules whose source files are under the configured ``project_root``
    are subject to enforcement. Modules in the allowlist (e.g., s0ma's
    own packages) and standard library / third-party modules are never
    intercepted.

    This finder also discovers ``.s0ma`` files alongside ``.py`` files.
    When a ``.s0ma`` file exists for a module, it is preferred over the
    ``.py`` version (the ``.s0ma`` file is authoritative). The loader
    handles on-the-fly transpilation and caching.
    """

    def __init__(
        self,
        project_root: str | Path,
        allowlist: set[str] | None = None,
        *,
        strict: bool = True,
    ) -> None:
        """Initialize the finder with scope configuration.

        Args:
            project_root: The root directory of the managed project.
                Only modules under this directory are enforced.
            allowlist: Set of module name prefixes to skip enforcement
                for (e.g., ``{"s0ma"}`` to skip framework internals).
            strict: If True, raise on violations. If False, warn only.
        """
        self.project_root = Path(project_root).resolve()
        self.allowlist = allowlist or set()
        self.strict = strict
        self._active = True

        logger.info(
            "S0maFinder initialized for project root: %s (strict=%s)",
            self.project_root,
            self.strict,
        )

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        """Find a module spec, wrapping the loader if in scope.

        Returns None if the module is outside scope (allowing the normal
        import machinery to handle it). If in scope, finds the real spec
        via the standard finders and wraps its loader with
        ``S0maLoader``.

        Also checks for ``.s0ma`` source files. If a ``.s0ma`` file is
        found for the module, the spec is updated to use the
        ``S0maDSLLoader`` which handles transpilation and caching.

        Args:
            fullname: The fully qualified module name.
            path: The parent package __path__ (or None for top-level).
            target: The target module object (for reloads).

        Returns:
            A ModuleSpec with wrapped loader if in scope, None otherwise.
        """
        if not self._active:
            return None

        # Check allowlist — skip enforcement for exempted prefixes
        for prefix in self.allowlist:
            if fullname == prefix or fullname.startswith(prefix + "."):
                return None

        # Check for .s0ma file first (authoritative if present)
        s0ma_spec = self._find_s0ma_spec(fullname, path)
        if s0ma_spec is not None:
            return s0ma_spec

        # Find the real spec using other finders (skip ourselves)
        real_spec = self._find_real_spec(fullname, path, target)
        if real_spec is None:
            return None

        # Check if the module's source file is under our project root
        if not self._is_in_scope(real_spec):
            return None

        # Wrap the loader for post-load verification
        if real_spec.loader is not None:
            logger.debug(
                "Import hook intercepting module '%s'", fullname
            )
            real_spec.loader = S0maLoader(
                real_spec.loader, strict=self.strict
            )

        return real_spec

    def _find_s0ma_spec(
        self,
        fullname: str,
        path: object,
    ) -> importlib.machinery.ModuleSpec | None:
        """Check if a ``.s0ma`` source file exists for this module.

        Searches the project root and any parent package paths for a
        ``.s0ma`` file corresponding to the module name. If found,
        returns a ModuleSpec with an ``S0maDSLLoader`` that handles
        on-the-fly transpilation with caching.

        Args:
            fullname: The fully qualified module name.
            path: The parent package ``__path__`` (or None).

        Returns:
            A ModuleSpec for the ``.s0ma`` source, or None if no
            ``.s0ma`` file exists.
        """
        # Convert dotted module name to path parts
        parts = fullname.split(".")
        module_filename = parts[-1] + ".s0ma"

        # Build search paths: parent package path(s) + project root
        search_paths: list[Path] = []
        if path is not None:
            if isinstance(path, (list, tuple)):
                search_paths.extend(Path(p) for p in path)
            elif isinstance(path, str):
                search_paths.append(Path(path))
        search_paths.append(self.project_root)

        # For top-level modules, also check project root directly
        # For nested modules (e.g., a.b.c), the parent path covers it

        for search_dir in search_paths:
            s0ma_path = search_dir / module_filename
            if s0ma_path.is_file():
                # Verify it's under our project root
                try:
                    resolved = s0ma_path.resolve()
                    if not resolved.is_relative_to(self.project_root):
                        continue
                except (ValueError, OSError):
                    continue

                logger.debug(
                    "Found .s0ma source for module '%s': %s",
                    fullname, s0ma_path,
                )

                # Create a spec that will use our DSL loader
                # The origin points to the .s0ma file; the loader
                # handles transpilation to .py
                return importlib.machinery.ModuleSpec(
                    name=fullname,
                    loader=S0maDSLLoader(
                        s0ma_path=resolved,
                        project_root=self.project_root,
                        strict=self.strict,
                    ),
                    origin=str(resolved),
                )

        return None

    def _find_real_spec(
        self,
        fullname: str,
        path: object,
        target: ModuleType | None,
    ) -> importlib.machinery.ModuleSpec | None:
        """Find the real ModuleSpec using standard finders.

        Temporarily deactivates this finder to avoid recursion, then
        searches the remaining meta_path finders.

        Args:
            fullname: The fully qualified module name.
            path: The parent package __path__.
            target: The target module object (for reloads).

        Returns:
            The real ModuleSpec, or None if not found.
        """
        self._active = False
        try:
            # Use importlib.util.find_spec for clean delegation
            # But we need to handle the case where the parent package
            # may not be imported yet
            try:
                spec = importlib.util.find_spec(fullname)
            except (ModuleNotFoundError, ValueError):
                spec = None
            return spec
        finally:
            self._active = True

    def _is_in_scope(self, spec: importlib.machinery.ModuleSpec) -> bool:
        """Check if a module's source file is under the project root.

        Args:
            spec: The module spec to check.

        Returns:
            True if the module's source is under project_root.
        """
        origin = spec.origin
        if origin is None:
            return False

        try:
            module_path = Path(origin).resolve()
            return module_path.is_relative_to(self.project_root)
        except (ValueError, OSError):
            return False


# ======================================================================
# Hook installation / removal API
# ======================================================================

# Module-level reference to the installed finder (if any)
_installed_finder: S0maFinder | None = None


def install_import_hook(
    project_root: str | Path,
    allowlist: set[str] | None = None,
    *,
    strict: bool = True,
) -> S0maFinder:
    """Install the s0ma import hook on ``sys.meta_path``.

    The hook enforces that all public classes and functions in modules
    under ``project_root`` are registered with ``@component`` or marked
    with ``@internal``. This is what makes the self-model load-bearing.

    Calling this function when a hook is already installed is safe —
    it will uninstall the existing hook first (idempotent).

    Args:
        project_root: Root directory of the managed project. Only modules
            under this directory are subject to enforcement.
        allowlist: Set of module name prefixes to exempt from enforcement
            (e.g., ``{"s0ma"}`` to skip framework internals).
        strict: If True (default), raise ``UnregisteredComponentError``
            for violations. If False, issue warnings only.

    Returns:
        The installed ``S0maFinder`` instance.
    """
    global _installed_finder

    # Idempotent: uninstall existing hook if present
    if _installed_finder is not None:
        uninstall_import_hook()

    finder = S0maFinder(
        project_root=project_root,
        allowlist=allowlist,
        strict=strict,
    )
    sys.meta_path.insert(0, finder)
    _installed_finder = finder

    logger.info(
        "s0ma import hook installed for '%s' (strict=%s)",
        Path(project_root).resolve(),
        strict,
    )

    return finder


def uninstall_import_hook() -> None:
    """Remove the s0ma import hook from ``sys.meta_path``.

    Safe to call when no hook is installed (no-op).
    """
    global _installed_finder

    if _installed_finder is not None:
        with contextlib.suppress(ValueError):
            sys.meta_path.remove(_installed_finder)
        logger.info("s0ma import hook uninstalled.")
        _installed_finder = None


def is_hook_installed() -> bool:
    """Check if the s0ma import hook is currently active.

    Returns:
        True if the hook is installed on ``sys.meta_path``.
    """
    return _installed_finder is not None and _installed_finder in sys.meta_path
