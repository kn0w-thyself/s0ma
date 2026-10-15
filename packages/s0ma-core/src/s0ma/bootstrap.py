"""Manifest-driven bootstrap for s0ma-built applications.

This is the module a *deployed* s0ma application imports to boot: it
reads the build manifest (``build.s0ma.json``) written by ``s0ma build``
and imports every module the build emitted, in the dependency-first
order the build recorded. The whole boot ceremony collapses to::

    from s0ma.bootstrap import bootstrap_imports
    modules = bootstrap_imports(build_dir)

Why it lives in s0ma-core (M10, 0.16.x)
---------------------------------------

:func:`bootstrap_imports` shipped from ``s0ma_dsl.runtime`` through
0.16.1. That made every deployed application import the *authoring*
transpiler at process start: a runtime environment with no authoring
packages installed died with ``ModuleNotFoundError: No module named
's0ma_dsl'`` on the blessed one-line bootstrap. PRD INV-9 says nothing a
deployed system needs at import/runtime may be license-gated, so the
loader moved into ``s0ma-core`` (Apache-2.0) where deployment can reach
it. ``s0ma_dsl.runtime.bootstrap_imports`` remains as a deprecated
re-export of this function (INV-2: no silent rename) and delegates here.

The loader is deliberately **stdlib-only**. It parses the manifest's
JSON itself rather than importing the transpiler's manifest dataclasses,
so importing this module pulls in nothing beyond ``importlib``, ``json``,
``sys`` and ``pathlib``. The transpiler's richer reader
(``s0ma_dsl.codegen.build_manifest.load_manifest``) stays the authoring
side's view of the same file — it reads hashes, source maps, external
content files and self-context references that a booting process has no
use for. The two readers share this module's schema constants, role
vocabulary and error type by import, so there is exactly one definition
of each in the tree.

Scope note: the modules this helper imports are still emitted with an
authoring-side registration import (``from
s0ma_dsl.runtime_bridge.registration import ...``). Making *emitted
code* runtime-free is a separate design round; M10 fixes the bootstrap
surface only.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

__all__ = [
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA",
    "VALID_ROLES",
    "ManifestSchemaError",
    "bootstrap_imports",
]

MANIFEST_SCHEMA = "s0ma-build-manifest@1"
"""Canonical schema string for the build manifest.

Additive fields are added under this string; a new major version (``@2``)
is reserved for a breaking schema change (renamed/removed fields).
"""

MANIFEST_FILENAME = "build.s0ma.json"
"""On-disk filename for the build manifest, inside the build directory."""

VALID_ROLES: frozenset[str] = frozenset({"source", "test"})
"""Allowed values for a manifest module entry's ``role`` (0.14.0).

One manifest holds both production source modules and test modules;
:func:`bootstrap_imports` filters by role so production consumers import
source modules only. Future roles (e.g. ``"tool"``) require a
schema-level review of every reader that depends on this vocabulary.
"""

#: Top-level manifest keys every reader requires. Kept in sync with the
#: transpiler's writer by the round-trip tests on both sides.
_REQUIRED_MANIFEST_KEYS = ("project", "build_dir", "transpiler_version")

#: Module-entry keys the transpiler always writes. The runtime read path
#: only *uses* ``name`` and ``role``, but it validates the full set so a
#: truncated manifest fails here exactly as it does on the authoring side
#: rather than half-booting an application.
_REQUIRED_MODULE_KEYS = (
    "name",
    "source",
    "output",
    "ir",
    "source_map",
    "source_hash",
    "output_hash",
)


class ManifestSchemaError(Exception):
    """Raised when a manifest is missing, corrupted, or schema-mismatched.

    Surfaced with a remediation pointing callers at ``s0ma build``
    (regenerate) or ``s0ma migrate-layout`` (legacy projects). It is
    intentionally not a soft failure: the manifest is the contract, and a
    missing or garbled manifest is a loud problem rather than a silent
    fallback to some other import order.

    Re-exported as ``s0ma_dsl.codegen.build_manifest.ManifestSchemaError``
    — the same class object, so ``except`` clauses written against either
    import path catch errors raised by either reader.
    """


def _manifest_payload(build_path: Path) -> dict[str, Any]:
    """Read and schema-check ``build_path/build.s0ma.json``.

    Returns the raw JSON object. Every failure mode raises
    :class:`ManifestSchemaError` with the same remediation text the
    transpiler's reader uses, so a consumer sees one message regardless
    of which reader parsed the file.
    """
    manifest_path = build_path / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ManifestSchemaError(
            f"Build manifest not found at {manifest_path}. "
            f"Run `s0ma build` to (re)generate it, or `s0ma migrate-layout` "
            f"if this is a legacy pre-M6b build directory."
        )

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestSchemaError(
            f"Build manifest at {manifest_path} is not valid JSON: {exc}. "
            f"Re-run `s0ma build` to regenerate it."
        ) from exc

    if not isinstance(raw, dict):
        raise ManifestSchemaError(
            f"Build manifest at {manifest_path} is not a JSON object. "
            f"Re-run `s0ma build` to regenerate it."
        )

    schema = raw.get("schema")
    if schema != MANIFEST_SCHEMA:
        raise ManifestSchemaError(
            f"Build manifest at {manifest_path} has schema {schema!r}, "
            f"expected {MANIFEST_SCHEMA!r}. The transpiler version that "
            f"wrote this manifest is incompatible. Re-run `s0ma build` "
            f"with this transpiler version to regenerate."
        )
    return raw


def _import_order(build_path: Path, role_set: set[str]) -> tuple[str, ...]:
    """Return the module names to import, filtered by role, in order.

    Honours ``topological_import_order`` (the dependency-first list every
    build since M10 records) and falls back to the manifest's ``modules``
    ordering — alphabetical by name — for older manifests that pre-date
    the field.
    """
    manifest_path = build_path / MANIFEST_FILENAME
    raw = _manifest_payload(build_path)

    try:
        for key in _REQUIRED_MANIFEST_KEYS:
            _ = raw[key]

        role_by_name: dict[str, str] = {}
        names_in_manifest_order: list[str] = []
        for entry in raw.get("modules", []):
            if not isinstance(entry, dict):
                raise TypeError("manifest module entry is not a JSON object")
            for key in _REQUIRED_MODULE_KEYS:
                _ = entry[key]
            name = str(entry["name"])
            # ``role`` is additive (0.14.0): pre-PRE-2 manifests omit it
            # and load with the back-compat default ``"source"``.
            role = str(entry.get("role", "source"))
            if role not in VALID_ROLES:
                raise ValueError(
                    f"ModuleManifestEntry.role must be one of "
                    f"{sorted(VALID_ROLES)}, got {role!r}."
                )
            role_by_name[name] = role
            names_in_manifest_order.append(name)
    except (KeyError, TypeError) as exc:
        raise ManifestSchemaError(
            f"Build manifest at {manifest_path} is missing required "
            f"fields ({exc}). Re-run `s0ma build` to regenerate it."
        ) from exc

    raw_topo = raw.get("topological_import_order", [])
    if not isinstance(raw_topo, list):
        raise ManifestSchemaError(
            f"Build manifest at {manifest_path} has a "
            f"'topological_import_order' that is not a JSON array. "
            f"Re-run `s0ma build` to regenerate it."
        )

    if raw_topo:
        return tuple(
            str(name) for name in raw_topo
            if role_by_name.get(str(name), "source") in role_set
        )
    return tuple(
        name for name in names_in_manifest_order
        if role_by_name[name] in role_set
    )


def bootstrap_imports(
    build_dir: Path | str,
    *,
    sys_path_insert: bool = True,
    roles: tuple[str, ...] = ("source",),
) -> dict[str, ModuleType]:
    """Import every module the build manifest lists, in topological order.

    The manifest's ``topological_import_order`` field is the
    dependency-first list of module names: every ``uses:`` edge is
    satisfied before its consumer is imported. Reads the manifest at
    ``build_dir/build.s0ma.json`` and imports each module via
    ``importlib.import_module``.

    Parameters
    ----------
    build_dir:
        Directory holding the flat-layout build — ``__init__.py``,
        per-module ``.py`` / ``.s0ma.json`` / ``.s0ma.map`` triples, and
        the ``build.s0ma.json`` manifest. Accepts a
        :class:`pathlib.Path` or any string convertible to one.
    sys_path_insert:
        When ``True`` (default), inserts the build directory at the head
        of :data:`sys.path` so the bare module names from the manifest
        resolve to the transpiled ``.py`` files. The insertion is
        idempotent — re-invoking ``bootstrap_imports`` against the same
        directory does not produce duplicate ``sys.path`` entries. Pass
        ``False`` if the caller has already arranged ``sys.path`` (e.g.,
        via a framework-side import hook) so the helper does not mutate
        it.
    roles:
        Which manifest entries to import (added 0.14.0). Defaults to
        ``("source",)`` so production consumers see only source modules
        — callers that never knew about test entries get the same dict
        they always got, even after a unified ``s0ma test``-written
        manifest contains both. Pass ``("source", "test")`` to import
        everything (typical inside a test runner harness), or
        ``("test",)`` to import only the test modules. An empty tuple
        imports nothing and returns an empty dict; an unknown role
        raises ``ValueError`` (caller bug).

    Returns
    -------
    dict[str, ModuleType]
        Mapping of canonical module name to imported module object.
        Iteration order matches the topological import order recorded in
        the manifest, restricted to entries whose role is in ``roles``.

    Raises
    ------
    ManifestSchemaError
        When the manifest is missing, malformed, or carries a schema
        string this reader does not recognise. The exception's message
        names the remediation explicitly: ``s0ma build`` to (re)generate
        the manifest, or ``s0ma migrate-layout`` to bring a legacy
        project forward. The same class is re-exported as
        ``s0ma_dsl.codegen.build_manifest.ManifestSchemaError``.

    Notes
    -----
    The function is a *pure* function of the manifest. It does not walk
    the filesystem to discover what's there, does not re-parse ``.s0ma``
    sources, and does not infer the order from anything other than the
    manifest's ``topological_import_order``. If the manifest is missing
    or malformed, the helper raises rather than silently producing a
    different order than the build recorded — silent fallback is the bug
    class this helper set out to retire.

    Bootstrap files are *not* registered as components. The manifest is
    the registration set: every module listed in ``build.s0ma.json`` is
    the result of a ``.s0ma`` source being transpiled, so bootstrap files
    (declared under ``[tool.s0ma].bootstrap_files``) are by construction
    outside the manifest and never imported by this helper.

    Typed view via the companion stub
    ---------------------------------

    The return type stays ``dict[str, ModuleType]`` so legacy callers
    keep working byte-for-byte. Consumers who want a stronger typed view
    can point their type checker (mypy / pyright) at the build
    directory: ``s0ma build`` emits a companion
    ``<build_dir>/build.s0ma.pyi`` stub that declares every module's
    importable identity as ``ModuleType`` plus a ``BootstrapModules``
    ``TypedDict`` listing every module name. Consumers may declare their
    own bootstrap wrapper as::

        from build.s0ma import BootstrapModules  # via MYPYPATH

        def startup() -> BootstrapModules:
            return cast(BootstrapModules, bootstrap_imports(build_dir))

    or simply use ``modules["http_gateway"]`` directly with the build
    directory on ``MYPYPATH``. The stub is *advisory* — its absence never
    changes this function's runtime behaviour; builds that lack the stub
    continue to work unchanged.
    """
    unknown = set(roles) - VALID_ROLES
    if unknown:
        raise ValueError(
            f"bootstrap_imports: roles must be a subset of "
            f"{sorted(VALID_ROLES)}, got unknown values {sorted(unknown)}."
        )

    build_path = Path(build_dir)
    order = _import_order(build_path, set(roles))

    if sys_path_insert:
        # Idempotent insertion: ``str(build_path)`` is what ``importlib``
        # uses to locate modules on this entry, so we check for the exact
        # string rather than any of the path's variants. The build
        # directory must be at index 0 (or, when already present,
        # wherever it landed) so the bare module names in the manifest
        # resolve before any same-named module higher up the search path.
        build_str = str(build_path)
        if build_str not in sys.path:
            sys.path.insert(0, build_str)

    imported: dict[str, ModuleType] = {}
    for name in order:
        # ``import_module`` is the documented entry point for runtime
        # imports; it handles ``__init__.py`` execution, sys.modules
        # caching, and side effects exactly the way ``import`` would.
        imported[name] = importlib.import_module(name)
    return imported
