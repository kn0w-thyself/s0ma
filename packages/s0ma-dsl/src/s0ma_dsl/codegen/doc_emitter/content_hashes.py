"""Project-wide content-hash computation for doc declarations (plan M6).

This module is the bridge between the DSL-side AST and the s0ma-core
:func:`s0ma.hashing.content_hash` utility. It:

1. Synthesises a :class:`s0ma.RegistrySnapshot` covering every nerve,
   cell, ganglion, example, and module in the parsed project.
2. Builds provisional :class:`DocRefRegistration` /
   :class:`DocGuideRegistration` records (with ``content_hash=""``) for
   every doc declaration in every module.
3. Calls ``content_hash()`` for each doc registration with the
   synthesised snapshot to obtain the transitive digest.
4. Returns a :class:`DocHashIndex` keyed by ``(decl_kind, decl_name)``
   that the Python emitter and renderer pipeline read from when baking
   hashes into emitted output.

Examples are not hashed directly — per the s0ma-core M7 design, examples
participate only as dependencies of guides that reference them.

The transpiler version stamped into every hash comes from
:data:`s0ma_dsl.ir.schema.TRANSPILER_VERSION`. Bumping that constant
invalidates every previously-stored doc hash, exactly the right
behaviour when the emitter's canonicalisation rules change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from s0ma.decorators import component
from s0ma.hashing import content_hash as _content_hash
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.codegen.doc_emitter.registrations import (
    build_doc_guide_registration,
    build_doc_ref_registration,
)
from s0ma_dsl.codegen.doc_emitter.snapshot import build_content_hash_snapshot
from s0ma_dsl.ir.schema import TRANSPILER_VERSION

if TYPE_CHECKING:
    from s0ma.models import (
        DocGuideRegistration,
        DocRefRegistration,
        RegistrySnapshot,
    )

    from s0ma_dsl.ast_nodes.nodes import (
        DocGuideDecl,
        DocRefDecl,
        S0maModule,
    )

__all__ = [
    "DocHashIndex",
    "compute_doc_hashes",
]


@component(
    name="S0maDSL_DocHashIndex",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Project-wide map from (declaration kind, declaration name) to the "
        "transitive content hash computed by s0ma.hashing.content_hash."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class DocHashIndex:
    """Stable handle for the content hashes the emitter must bake in.

    Keys are ``(kind, name)`` pairs where ``kind`` is one of
    ``"doc-ref"`` or ``"doc-guide"`` (examples are not hashed
    directly). Lookup misses default to the empty string so the
    emitter can fall back gracefully if a doc is added between hash
    computation and emission — though under normal operation that
    should not happen because both phases share the same parsed
    module dict.

    The :attr:`registrations` map carries the provisional records the
    hashes were computed against; renderers re-use them to avoid
    rebuilding the same shape twice.

    The :attr:`snapshot` is the synthesised :class:`RegistrySnapshot`
    used during hashing; renderers can also walk it to resolve
    ``covers:`` filters without rebuilding their own view.
    """

    hashes: dict[tuple[str, str], str] = field(default_factory=dict)
    registrations: dict[
        tuple[str, str],
        DocRefRegistration | DocGuideRegistration,
    ] = field(default_factory=dict)
    snapshot: RegistrySnapshot | None = None

    def get(self, kind: str, name: str) -> str:
        """Return the hash for ``(kind, name)`` or ``""`` if missing."""
        return self.hashes.get((kind, name), "")

    def get_for_doc_ref(self, decl: DocRefDecl) -> str:
        return self.get("doc-ref", decl.name)

    def get_for_doc_guide(self, decl: DocGuideDecl) -> str:
        return self.get("doc-guide", decl.name)

    def is_empty(self) -> bool:
        return not self.hashes


@component(
    name="S0maDSL_compute_doc_hashes",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Compute transitive content hashes for every doc-ref and doc-guide "
        "in a parsed project, returning a DocHashIndex keyed by "
        "(declaration kind, name)."
    ),
    idempotent=True,
    is_framework=True,
)
def compute_doc_hashes(
    modules: dict[str, S0maModule],
    *,
    transpiler_version: str = TRANSPILER_VERSION,
    filenames: dict[str, str] | None = None,
) -> DocHashIndex:
    """Compute the project's full doc-hash map.

    Parameters
    ----------
    modules:
        Project-wide map of module name → parsed :class:`S0maModule`.
        The same dict shape the cross-module dependency resolver and
        :class:`DocValidator` consume.
    transpiler_version:
        Stamped into every hash. Defaults to
        :data:`s0ma_dsl.ir.schema.TRANSPILER_VERSION`. Tests can pin
        a fixed version string to keep golden snapshots stable.
    filenames:
        Optional map of module name → source file path used for the
        registration's ``source_span.file``. Falls back to the module
        name when omitted.

    Returns
    -------
    DocHashIndex
        Map keyed by ``(kind, name)`` with the registrations and the
        synthesised snapshot for downstream consumption.
    """
    snapshot = build_content_hash_snapshot(modules)
    filenames = filenames or {}

    hashes: dict[tuple[str, str], str] = {}
    registrations: dict[tuple[str, str], object] = {}

    for module_name in sorted(modules.keys()):
        module = modules[module_name]
        # Normalise to basename for hash determinism. Absolute paths
        # leak filesystem layout into the hash and make goldens / CI
        # snapshots non-portable. The Python emitter applies the same
        # basename normalisation to its emitted ``source_span`` dicts so
        # that the runtime registration's hash matches what the
        # transpiler baked into the doc registration.
        raw_filename = filenames.get(module_name, module_name)
        filename = os.path.basename(raw_filename) if raw_filename else module_name

        for ref_decl in module.doc_refs:
            reg = build_doc_ref_registration(ref_decl, filename=filename)
            digest = _content_hash(
                reg, snapshot, transpiler_version=transpiler_version,
            )
            key = ("doc-ref", ref_decl.name)
            hashes[key] = digest
            registrations[key] = reg

        for guide_decl in module.doc_guides:
            guide_reg = build_doc_guide_registration(guide_decl, filename=filename)
            digest = _content_hash(
                guide_reg, snapshot, transpiler_version=transpiler_version,
            )
            key = ("doc-guide", guide_decl.name)
            hashes[key] = digest
            registrations[key] = guide_reg

    return DocHashIndex(
        hashes=hashes,
        registrations=registrations,  # type: ignore[arg-type]
        snapshot=snapshot,
    )
