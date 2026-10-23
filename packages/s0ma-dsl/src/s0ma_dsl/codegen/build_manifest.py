"""Build manifest emission and reading — M6b (feedback 5–6, ADR-007).

The build manifest (``build.s0ma.json``) is the canonical "what's in
this build" answer. Every successful ``s0ma build`` writes one alongside
the transpiled artifacts; the runtime bridge reads it to discover what
to import. Filesystem walking is deliberately not a fallback — the
manifest IS the contract.

Schema versioning
-----------------

The schema string ``s0ma-build-manifest@1`` is intentional. M10 will
extend the schema with ``topological_import_order``; M12 may extend it
with ``external_content_files``. Both are *additive* under the same
schema string — readers branch on the presence of optional fields, not
on the version number. A new major version (`@2`) is reserved for a
breaking schema change (renamed/removed fields). Until that happens,
``MANIFEST_SCHEMA`` stays at ``s0ma-build-manifest@1``.

Public surface
--------------

- :data:`MANIFEST_SCHEMA` — the canonical schema string.
- :data:`MANIFEST_FILENAME` — ``build.s0ma.json``.
- :class:`ModuleManifestEntry` — one row per emitted module.
- :class:`BuildManifest` — top-level dataclass.
- :func:`compute_file_hash` — sha256 helper used by the build pipeline.
- :func:`emit_manifest` — write a ``BuildManifest`` to a directory.
- :func:`load_manifest` — read a manifest, validating the schema.
- :class:`ManifestSchemaError` — raised on schema mismatch / corruption.

Shared with the runtime reader (M10, 0.16.x)
--------------------------------------------

``MANIFEST_SCHEMA``, ``MANIFEST_FILENAME``, ``VALID_ROLES`` and
``ManifestSchemaError`` are **defined in** :mod:`s0ma.bootstrap` and
re-exported here under their historical names (the same objects, so
``except ManifestSchemaError`` written against either import path catches
either reader's failures). The runtime read path —
:func:`s0ma.bootstrap.bootstrap_imports`, which a *deployed* application
calls at boot — must not import the authoring packages (INV-9), so the
schema identity it needs lives in Apache-licensed ``s0ma-core``. This
module remains the authoring-side view of the same file: the dataclasses,
hashes, source maps, external content files and self-context references
that only the build pipeline and its tooling read.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma.bootstrap import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA,
    VALID_ROLES,
    ManifestSchemaError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# MANIFEST_SCHEMA (``s0ma-build-manifest@1``), MANIFEST_FILENAME
# (``build.s0ma.json``) and VALID_ROLES are imported above from
# ``s0ma.bootstrap``; see the module docstring for why the runtime reader
# owns them. The schema string is intentionally stable: additive fields
# land under ``@1`` and readers branch on a field's presence, not on the
# version number. A new major version (``@2``) is reserved for a breaking
# schema change (renamed/removed fields).

MANIFEST_STUB_FILENAME = "build.s0ma.pyi"
"""On-disk filename for the companion Python type stub (M-8 / POST-14,
0.15.x). Lives in the build directory next to ``build.s0ma.json`` and
``__init__.py``; written by
:func:`s0ma_dsl.codegen.manifest_stub_emitter.emit_manifest_stub`
alongside the manifest on every successful build. Exposed here as a
sibling constant so other tooling (``s0ma migrate-layout``,
``s0ma verify``, future commands) can name the file without importing
the stub-emitter module's full surface."""

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
# ``ManifestSchemaError`` is imported above from ``s0ma.bootstrap`` and
# stays importable from here under its historical name. Raising it from
# either reader produces the same class, so every existing ``except
# s0ma_dsl.codegen.build_manifest.ManifestSchemaError`` keeps catching.


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModuleManifestEntry:
    """One row in the manifest's ``modules`` list.

    All paths in the on-disk JSON are stored as strings. ``source`` is
    the ``.s0ma`` source identity — SH-M1 (INV-5): when the build runs
    against a resolved ``[tool.s0ma]`` project, the pipeline records it
    as a **project-root-relative POSIX path** (forward slashes on every
    OS) so the manifest is byte-identical across machines, working
    directories, and platforms; synthetic-fallback builds keep the
    legacy as-passed form (there is no root to be relative to). Readers
    resolve relative values against the project root (see
    ``s0ma_dsl.cli.doctor``). The other paths are recorded as basenames
    relative to the build directory so the manifest is portable across
    absolute paths.

    ``role`` (added 0.14.0, additive under ``s0ma-build-manifest@1``):
    distinguishes production source modules from test modules so a
    single manifest can hold both. Older manifests load with
    ``role="source"`` for every entry; the runtime helper
    :func:`s0ma.bootstrap.bootstrap_imports` filters by role so
    consumers default to importing source modules only.

    ``source_root`` / ``logical_path`` (STD-M5, usability plan; additive
    under ``s0ma-build-manifest@1``) record the module's **logical**
    position in the source tree so tooling (the app map, the future
    explorer, ``s0ma inspect``) can present the source layout while the
    build directory stays flat (Decision 3 / Option B — no
    hierarchical module-name DSL change, no build-dir nesting):

    - ``source_root`` is the configured ``[tool.s0ma].source_roots`` /
      ``test_roots`` entry the module was discovered under, recorded as
      the project-root-relative POSIX string the author wrote (e.g.
      ``"src"``, ``"domain"``). NOT a resolved absolute path.
    - ``logical_path`` is the module's source path **relative to that
      source root**, POSIX (e.g. ``"orders/orders_domain.s0ma"``, or
      just ``"order_model.s0ma"`` for a module at the root's top level).

    Both follow the SH-M1 / INV-5 contract for path-typed manifest
    fields: relative, forward-slash POSIX on every OS, never absolute,
    never CWD-dependent — so the committed-build equality gate
    (FR-MCP-11, plan D-3/D-4) byte-compares rebuilds across machines and
    operating systems. They are empty strings for synthetic-fallback
    builds and any module that resolves outside every configured root
    (no portable anchor to express them against); ``to_dict`` omits an
    empty value so pre-STD-M5 manifests — and project builds whose
    modules have no recordable root — stay byte-identical. Older
    manifests omit both keys and load with the empty-string default.
    """

    name: str
    source: str
    output: str
    ir: str
    source_map: str
    source_hash: str
    output_hash: str
    role: str = "source"
    source_root: str = ""
    logical_path: str = ""

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise ValueError(
                f"ModuleManifestEntry.role must be one of "
                f"{sorted(VALID_ROLES)}, got {self.role!r}."
            )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # STD-M5 (INV-5): ``source_root`` / ``logical_path`` are additive
        # and optional. Omit them when empty (synthetic builds, or a
        # module outside every configured root) so the manifest bytes
        # stay identical to pre-STD-M5 builds and to any build that has
        # no portable anchor to record. A populated value is always a
        # project-root-relative POSIX string (see the class docstring).
        if not self.source_root:
            payload.pop("source_root", None)
        if not self.logical_path:
            payload.pop("logical_path", None)
        return payload


@dataclass(frozen=True)
class ExternalContentFileEntry:
    """One row in the manifest's ``external_content_files`` map.

    M12 (feedback 5–6): records each file embedded by a CONSTANT cell's
    ``content: @file("path")`` directive. The map is keyed by
    ``"<module_name>::<cell_name>"`` (the spec-§4.10 canonical reference
    for the consuming cell); the entry stores both the path-as-written
    (relative to the .s0ma source's directory unless absolute) and the
    SHA-256 hash of the file's content at build time.

    The hash exists for cache-invalidation: editing the embedded file
    changes its hash, which propagates through the consuming module's
    cache key (see ``cache.BuildCache.lookup`` and the M12 hash-folding
    in the IR builder). The path-as-written is what authors recognise
    when reading the manifest.
    """

    path: str
    """The path the .s0ma file wrote in ``@file("...")``. Preserved
    verbatim: relative paths stay relative, absolute paths stay
    absolute."""

    hash: str
    """``sha256:<hex>`` of the embedded file's UTF-8 bytes."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArtifactReference:
    """One build-root-relative, content-addressed companion artifact."""

    path: str
    sha256: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True)
class SelfContextReferences:
    """Optional additive references to M6 self-context companions."""

    json: ArtifactReference
    prompt_card: ArtifactReference

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {
            "json": self.json.to_dict(),
            "prompt_card": self.prompt_card.to_dict(),
        }


@dataclass(frozen=True)
class BuildManifest:
    """Top-level ``build.s0ma.json`` payload.

    ``topological_import_order`` (M10) is the dependency-first import
    order computed from every module's ``uses:`` edges. Older manifests
    pre-dating M10 omit the field; readers must tolerate its absence
    (the dataclass default is an empty tuple) — see
    :func:`load_manifest` for the back-compat path.

    ``external_content_files`` (M12) maps ``"<module>::<cell>"`` to the
    external file embedded via ``content: @file("path")`` on a CONSTANT
    cell. Additive under ``s0ma-build-manifest@1`` — older manifests
    omit the field, and the loader tolerates its absence. The map is
    empty when no cell in the project uses ``@file()``.
    """

    schema: str
    project: str
    build_dir: str
    transpiler_version: str
    # SH-M1 (selfhost plan, INV-5): the manifest no longer records a
    # build timestamp — wall-clock time in an emitted artifact violates
    # INV-5 ("no emitted artifact may embed wall-clock time") and made
    # every rebuild differ by one byte region, which the committed-build
    # equality gate (FR-MCP-11 / plan D-4) cannot tolerate. The field
    # stays on the dataclass (default ``""``) so pre-SH-M1 manifests —
    # which carry the timestamp — still load and round-trip; the writer
    # simply never populates it, and ``to_dict`` omits the key when
    # empty. Schema stays ``s0ma-build-manifest@1`` with the field
    # documented optional (pre-1.0 relaxation, see the CHANGELOG).
    built_at: str = ""
    modules: tuple[ModuleManifestEntry, ...] = field(default_factory=tuple)
    # M10 (feedback 5–6): dependency-first module import order. Empty
    # when the manifest pre-dates M10 or the project is empty. Both the
    # runtime helper and ``s0ma topo`` rely on this field; when empty,
    # callers fall back to the manifest's ``modules`` order (alphabetical
    # by name) which is correct only when the project has no edges.
    topological_import_order: tuple[str, ...] = field(default_factory=tuple)
    # M12 (feedback 5–6): external files embedded into CONSTANT cells
    # via ``content: @file("path")``. Additive under
    # ``s0ma-build-manifest@1``. Map is keyed by
    # ``"<module>::<cell>"``; an empty mapping means no cells in the
    # project use the directive.
    external_content_files: dict[str, ExternalContentFileEntry] = field(
        default_factory=dict
    )
    # M2 (0.13.0, batch-01c): the compact keys of the NEW check errors an
    # ``s0ma build --allow-new-errors`` override waved through, recorded so
    # the bench can count overrides after the fact (spec (b)). Additive
    # under ``s0ma-build-manifest@1`` — a normal build (the overwhelming
    # majority, incl. the entire self-host tree and every golden) never
    # sets it, so ``to_dict`` omits the key and those manifests stay
    # byte-identical to their pre-M2 shape. Each key is
    # ``CODE@module.s0ma[:symbol]`` (the line-number-free baseline identity).
    overridden_new_errors: tuple[str, ...] = field(default_factory=tuple)
    # The import names that a build made with ``s0ma build
    # --without-runtime-packages`` looked up for its ``requires:`` entries
    # and could not find in its environment (the top-level package of a
    # plain import, the module of a from-import). The caller stated that
    # the environment does not hold the project's runtime packages, so
    # these were recorded rather than counted as NEW check errors;
    # nothing was overridden, which is why they are not in
    # ``overridden_new_errors``. Additive under
    # ``s0ma-build-manifest@1``: a build made where the packages are
    # installed never sets it, and ``to_dict`` omits the key when empty.
    # Sorted and distinct, so two builds of one tree record the same list.
    unverified_packages: tuple[str, ...] = field(default_factory=tuple)
    # M6 (0.14.0): content-addressed canonical self-context companions.
    # Optional so every older s0ma-build-manifest@1 remains loadable.
    self_context: SelfContextReferences | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": self.schema,
            "project": self.project,
            "build_dir": self.build_dir,
            "transpiler_version": self.transpiler_version,
            "modules": [m.to_dict() for m in self.modules],
        }
        # SH-M1 (INV-5): ``built_at`` is emitted only when explicitly
        # set (e.g. reproducible test fixtures that pin a value). The
        # build pipeline never sets it — see the field comment above.
        if self.built_at:
            payload["built_at"] = self.built_at
        # Emit ``topological_import_order`` whenever it has been set
        # (even to an empty list when the project genuinely has zero
        # modules), but do not synthesise it for older code paths that
        # never assigned a value. The dataclass default is the empty
        # tuple, so the field is always present in M10+ builds.
        payload["topological_import_order"] = list(
            self.topological_import_order
        )
        # M12: emit ``external_content_files`` only when populated. The
        # field is additive — readers branch on ``raw.get(..., {})`` —
        # so projects without any ``@file()`` cells produce manifests
        # byte-identical to pre-M12 builds, keeping the diff surface
        # small and the field opt-in.
        if self.external_content_files:
            payload["external_content_files"] = {
                key: entry.to_dict()
                for key, entry in sorted(
                    self.external_content_files.items()
                )
            }
        # M2: emit ``overridden_new_errors`` only when an override waved
        # NEW check errors through — sorted for deterministic bytes.
        if self.overridden_new_errors:
            payload["overridden_new_errors"] = sorted(
                self.overridden_new_errors
            )
        # Emit ``unverified_packages`` only for a build made without the
        # runtime packages that met at least one it could not find.
        if self.unverified_packages:
            payload["unverified_packages"] = sorted(
                set(self.unverified_packages)
            )
        if self.self_context is not None:
            payload["self_context"] = self.self_context.to_dict()
        return payload

    @staticmethod
    def resolve_source(
        entry: ModuleManifestEntry | Mapping[str, Any] | str,
        project_root: Path | str,
    ) -> Path:
        """Resolve a manifest module entry's ``source`` to an absolute path.

        DSL-M3 (F-M1-1): this is the single home for the manifest-source
        resolution recipe that previously lived in three hand-copied
        places (``s0ma_dsl.cli.doctor._module_statuses``, and the
        ``s0ma_mcp`` ``tools`` bodies ``_collect_artifacts`` /
        ``project_status_tool``). The recipe encodes the SH-M1 / INV-5
        contract:

        - A build run against a resolved ``[tool.s0ma]`` project records
          each module's ``source`` as a **project-root-relative POSIX
          path** (forward slashes on every OS) so the manifest is
          byte-identical across machines, working directories, and
          platforms. Such relative entries MUST be resolved against the
          project root — NOT the caller's CWD (the latter was a latent
          freshness bug: ``project_status`` reported spurious
          unbuilt/orphaned modules unless it happened to run from the
          build's CWD).
        - Synthetic-fallback builds (no project root to be relative to)
          and pre-SH-M1 manifests record an absolute ``source``; those
          resolve as-is.

        *entry* may be a :class:`ModuleManifestEntry`, a raw mapping with
        a ``"source"`` key (the shape a JSON-loaded manifest dict carries),
        or the source string itself — so all three historical call sites
        collapse to one call regardless of whether they hold a parsed
        manifest or a raw dict. *project_root* is the resolved
        ``S0maProject.root``.

        Returns the ``.resolve()``-normalised absolute path. Callers that
        must tolerate ``OSError`` from ``resolve()`` (e.g. comparing
        against a set of wanted paths) should wrap the call.
        """
        if isinstance(entry, ModuleManifestEntry):
            raw_source = entry.source
        elif isinstance(entry, str):
            raw_source = entry
        else:
            raw_source = str(entry.get("source", ""))
        recorded = Path(raw_source).expanduser()
        if not recorded.is_absolute():
            recorded = Path(project_root) / recorded
        return recorded.resolve()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def compute_file_hash(content: str | bytes) -> str:
    """Return ``sha256:<hex>`` for *content*.

    Accepts ``str`` (encoded as UTF-8) or ``bytes``. The ``sha256:``
    prefix mirrors the convention in IR ``content_hash`` fields so the
    manifest's hashes read identically.
    """
    data = content.encode("utf-8") if isinstance(content, str) else content
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


# ---------------------------------------------------------------------------
# Build / write
# ---------------------------------------------------------------------------


def build_manifest(
    *,
    project_name: str,
    build_dir: Path | str,
    modules: list[ModuleManifestEntry],
    transpiler_version: str,
    built_at: str | None = None,
    topological_import_order: tuple[str, ...] | list[str] = (),
    external_content_files: dict[str, ExternalContentFileEntry] | None = None,
    overridden_new_errors: tuple[str, ...] | list[str] = (),
    unverified_packages: tuple[str, ...] | list[str] = (),
    self_context: SelfContextReferences | None = None,
) -> BuildManifest:
    """Construct a :class:`BuildManifest` for the given build.

    Parameters mirror the manifest fields exactly. The caller is
    responsible for computing each ``ModuleManifestEntry`` (in the
    transpile pipeline; see ``cli/main.py``) and the topological order
    (see :func:`s0ma_dsl.resolver.compute_topological_order`).
    ``built_at`` defaults to **empty** (the key is omitted from the
    JSON) — SH-M1 / INV-5: the build pipeline no longer stamps
    wall-clock time into the manifest, so two builds of the same input
    are byte-identical. Tests that need the legacy field pass an
    explicit value. ``build_dir`` accepts a ``str`` so callers can
    record a project-root-relative POSIX path (INV-5: no absolute
    machine paths in artifacts) rather than the on-disk absolute path.

    ``topological_import_order`` (M10) is dependency-first — leaf
    modules first, consumers later. Empty by default so callers from
    older code paths (or transpile of a single isolated file) can omit
    it without ceremony.

    ``external_content_files`` (M12) maps ``"<module>::<cell>"`` to the
    file embedded via ``content: @file("path")`` on a CONSTANT cell.
    ``None`` (the default) is treated as an empty dict so the manifest
    stays back-compatible with pre-M12 callers.

    ``unverified_packages`` is the record of a build made with
    ``--without-runtime-packages``: the import names of the ``requires:``
    entries it could not find. Empty for every other build.
    """
    return BuildManifest(
        schema=MANIFEST_SCHEMA,
        project=project_name,
        build_dir=str(build_dir),
        transpiler_version=transpiler_version,
        built_at=built_at or "",
        # ``modules`` stays deterministically alphabetical so the list
        # diffs cleanly across builds. The M10 topological field is
        # recorded separately under ``topological_import_order``; the
        # two fields serve different purposes (manifest is the inventory;
        # topological_import_order is the import-time directive).
        modules=tuple(sorted(modules, key=lambda m: m.name)),
        topological_import_order=tuple(topological_import_order),
        external_content_files=dict(external_content_files or {}),
        overridden_new_errors=tuple(overridden_new_errors),
        unverified_packages=tuple(sorted(set(unverified_packages))),
        self_context=self_context,
    )


def emit_manifest(manifest: BuildManifest, build_dir: Path) -> Path:
    """Write *manifest* to ``build_dir/build.s0ma.json``.

    Uses ``json.dumps(..., indent=2, sort_keys=True)`` so the output is
    deterministic across runs and diff-friendly. Writes the file with
    a trailing newline (POSIX convention).

    Returns the path the manifest was written to. The caller surfaces
    that path in the build's stdout summary and includes it in the
    ``all_outputs`` listing.
    """
    build_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = build_dir / MANIFEST_FILENAME
    payload = json.dumps(manifest.to_dict(), indent=2, sort_keys=True)
    manifest_path.write_text(payload + "\n", encoding="utf-8", newline="\n")
    return manifest_path


# ---------------------------------------------------------------------------
# Load / validate
# ---------------------------------------------------------------------------


def load_manifest(build_dir: Path) -> BuildManifest:
    """Read ``build_dir/build.s0ma.json`` and return a :class:`BuildManifest`.

    Raises
    ------
    ManifestSchemaError
        If the manifest is missing, malformed JSON, or carries a schema
        string this transpiler version does not recognise. The
        exception message names the remediation explicitly: run
        ``s0ma build`` to (re)generate the manifest, or
        ``s0ma migrate-layout`` to bring a legacy project forward.
    """
    manifest_path = build_dir / MANIFEST_FILENAME
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

    try:
        modules = tuple(
            ModuleManifestEntry(
                name=str(m["name"]),
                source=str(m["source"]),
                output=str(m["output"]),
                ir=str(m["ir"]),
                source_map=str(m["source_map"]),
                source_hash=str(m["source_hash"]),
                output_hash=str(m["output_hash"]),
                # ``role`` (0.14.0+, additive): pre-PRE-2 manifests omit it
                # and load with the back-compat default ``"source"``.
                role=str(m.get("role", "source")),
                # ``source_root`` / ``logical_path`` (STD-M5, additive):
                # pre-STD-M5 manifests omit both and load with the
                # back-compat default ``""`` (derive nothing). Both are
                # project-root-relative POSIX strings when present.
                source_root=str(m.get("source_root", "")),
                logical_path=str(m.get("logical_path", "")),
            )
            for m in raw.get("modules", [])
        )
        # M10 (feedback 5–6): ``topological_import_order`` is additive
        # under ``s0ma-build-manifest@1`` — older manifests omit the
        # field, and the loader stays tolerant of that. When absent we
        # default to the empty tuple so callers can branch on
        # truthiness rather than ``hasattr``-guessing.
        raw_topo = raw.get("topological_import_order", [])
        if not isinstance(raw_topo, list):
            raise ManifestSchemaError(
                f"Build manifest at {manifest_path} has a "
                f"'topological_import_order' that is not a JSON array. "
                f"Re-run `s0ma build` to regenerate it."
            )
        topological_import_order = tuple(str(name) for name in raw_topo)
        # M12 (feedback 5–6): ``external_content_files`` is additive
        # under ``s0ma-build-manifest@1`` — older manifests omit the
        # field, and the loader stays tolerant of that. The map is
        # keyed by ``"<module>::<cell>"``; each value is a JSON object
        # with ``path`` and ``hash`` strings.
        raw_ext = raw.get("external_content_files", {})
        if not isinstance(raw_ext, dict):
            raise ManifestSchemaError(
                f"Build manifest at {manifest_path} has an "
                f"'external_content_files' that is not a JSON object. "
                f"Re-run `s0ma build` to regenerate it."
            )
        external_content_files: dict[str, ExternalContentFileEntry] = {}
        for key, entry in raw_ext.items():
            if not isinstance(entry, dict):
                raise ManifestSchemaError(
                    f"Build manifest at {manifest_path}: "
                    f"'external_content_files[{key!r}]' is not a JSON "
                    f"object. Re-run `s0ma build` to regenerate it."
                )
            try:
                external_content_files[str(key)] = ExternalContentFileEntry(
                    path=str(entry["path"]),
                    hash=str(entry["hash"]),
                )
            except KeyError as exc:
                raise ManifestSchemaError(
                    f"Build manifest at {manifest_path}: "
                    f"'external_content_files[{key!r}]' is missing "
                    f"required field {exc}. Re-run `s0ma build` to "
                    f"regenerate it."
                ) from exc
        # M2 (0.13.0, batch-01c): ``overridden_new_errors`` is additive
        # under ``s0ma-build-manifest@1`` — manifests from a normal build
        # (and every pre-M2 build) omit it, and the loader defaults to the
        # empty tuple. Present only on a build that passed
        # ``--allow-new-errors``.
        raw_override = raw.get("overridden_new_errors", [])
        if not isinstance(raw_override, list):
            raise ManifestSchemaError(
                f"Build manifest at {manifest_path} has an "
                f"'overridden_new_errors' that is not a JSON array. "
                f"Re-run `s0ma build` to regenerate it."
            )
        overridden_new_errors = tuple(str(key) for key in raw_override)
        # ``unverified_packages`` is additive in the same way: present only
        # on a build made with ``--without-runtime-packages`` that could
        # not find at least one ``requires:`` entry.
        raw_unverified = raw.get("unverified_packages", [])
        if not isinstance(raw_unverified, list):
            raise ManifestSchemaError(
                f"Build manifest at {manifest_path} has an "
                f"'unverified_packages' that is not a JSON array. "
                f"Re-run `s0ma build` to regenerate it."
            )
        unverified_packages = tuple(str(name) for name in raw_unverified)
        raw_self_context = raw.get("self_context")
        self_context: SelfContextReferences | None = None
        if raw_self_context is not None:
            if not isinstance(raw_self_context, dict):
                raise ManifestSchemaError(
                    f"Build manifest at {manifest_path} has a 'self_context' "
                    "that is not a JSON object. Re-run `s0ma build` to regenerate it."
                )
            try:
                raw_json_ref = raw_self_context["json"]
                raw_card_ref = raw_self_context["prompt_card"]
                if not isinstance(raw_json_ref, dict) or not isinstance(raw_card_ref, dict):
                    raise TypeError("artifact reference is not an object")
                self_context = SelfContextReferences(
                    json=ArtifactReference(
                        path=str(raw_json_ref["path"]),
                        sha256=str(raw_json_ref["sha256"]),
                    ),
                    prompt_card=ArtifactReference(
                        path=str(raw_card_ref["path"]),
                        sha256=str(raw_card_ref["sha256"]),
                    ),
                )
            except (KeyError, TypeError) as exc:
                raise ManifestSchemaError(
                    f"Build manifest at {manifest_path} has incomplete self-context "
                    "references. Both json and prompt_card require path and sha256; "
                    "re-run `s0ma build` to regenerate it."
                ) from exc
        return BuildManifest(
            schema=schema,
            project=str(raw["project"]),
            build_dir=str(raw["build_dir"]),
            transpiler_version=str(raw["transpiler_version"]),
            # SH-M1 (INV-5): optional since the writer stopped stamping
            # wall-clock time. Pre-SH-M1 manifests still carry it.
            built_at=str(raw.get("built_at", "")),
            modules=modules,
            topological_import_order=topological_import_order,
            external_content_files=external_content_files,
            overridden_new_errors=overridden_new_errors,
            unverified_packages=unverified_packages,
            self_context=self_context,
        )
    except (KeyError, TypeError) as exc:
        raise ManifestSchemaError(
            f"Build manifest at {manifest_path} is missing required "
            f"fields ({exc}). Re-run `s0ma build` to regenerate it."
        ) from exc


__all__ = [
    "ArtifactReference",
    "BuildManifest",
    "ExternalContentFileEntry",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA",
    "MANIFEST_STUB_FILENAME",
    "ManifestSchemaError",
    "ModuleManifestEntry",
    "SelfContextReferences",
    "build_manifest",
    "compute_file_hash",
    "emit_manifest",
    "load_manifest",
]
