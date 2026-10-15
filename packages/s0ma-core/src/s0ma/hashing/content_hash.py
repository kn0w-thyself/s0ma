"""Deterministic transitive content hash for documentation registrations.

Plan §10.9 / design §8.5. A doc-ref or doc-guide registration carries a
``content_hash`` string that must change when — and only when — the
registry state that the doc *depends on* changes. This module computes
that hash.

Hash input (in order)
---------------------
1. A literal prefix: ``HASH_ALGORITHM_VERSION`` + ``:`` + the
   ``transpiler_version`` supplied by the caller. Bumping the version
   constant invalidates every previously-stored hash, which is the
   right thing to do when the algorithm changes.
2. The canonicalized form of the doc registration itself *with its own
   ``content_hash`` field zeroed out* — otherwise the hash would be a
   fixed point of its own input.
3. The transitive closure of registry state the doc references:

   * For a :class:`DocRefRegistration`: each ``FilterExpr`` in
     ``covers`` is resolved against the snapshot. Matching
     :class:`ComponentSpec` entries are included in sorted-name order;
     their own canonicalized form feeds the hash. Components whose
     target kind is ``doc-ref``, ``doc-guide``, or ``example`` resolve
     against the corresponding snapshot store.
   * For a :class:`DocGuideRegistration`: each :class:`EntityRef` in
     ``covers`` and ``examples`` is resolved. The asserts list is
     already canonicalized as part of step 2, but we also include each
     referenced example's body verbatim so that editing an example
     body invalidates every guide that references it.

The resulting bytes are hashed with SHA-256 and returned as a lowercase
hex digest prefixed with ``HASH_ALGORITHM_VERSION`` (e.g.
``"1:4f1ac...`"``). The prefix makes old hashes self-identifying when
the algorithm version is bumped.

Invariance guarantee
--------------------
Changing a component that no ``covers`` / ``examples`` entry resolves
to does **not** change the hash. This is what makes drift detection
actionable: a doc's hash is a statement about the state of its
referenced world, not the whole registry.
"""

from __future__ import annotations

import dataclasses
import hashlib
from typing import TYPE_CHECKING, Any

from s0ma.hashing.canonical import canonicalize

if TYPE_CHECKING:
    from s0ma.models import (
        ComponentSpec,
        DocGuideRegistration,
        DocRefRegistration,
        EntityRef,
        ExampleRegistration,
        FilterExpr,
        RegistrySnapshot,
    )

__all__ = [
    "HASH_ALGORITHM_VERSION",
    "content_hash",
]

# Version tag for the hashing algorithm. Bump whenever the
# canonicalization scheme or transitive-walk rules change; stored
# hashes will then compare unequal and drift-check will flag every
# doc as stale until it is re-hashed. The prefix is carried on the
# emitted digest so old hashes are self-identifying.
HASH_ALGORITHM_VERSION = "1"

# Kinds routed to the doc/example snapshot stores rather than the
# generic component store. Keeps doc-ref filters able to cover
# documentation artifacts themselves (e.g., a doc-ref that indexes
# every registered example).
_DOC_STORE_KINDS = frozenset({"doc-ref", "doc-guide", "example"})


def content_hash(
    doc_registration: DocRefRegistration | DocGuideRegistration,
    snapshot: RegistrySnapshot,
    *,
    transpiler_version: str,
) -> str:
    """Compute the transitive content hash for a doc registration.

    Args:
        doc_registration: A :class:`DocRefRegistration` or
            :class:`DocGuideRegistration`. Examples are not hashed
            directly — they participate only as dependencies of guides
            that reference them.
        snapshot: Current :class:`RegistrySnapshot` used to resolve
            ``covers`` / ``examples`` references. The snapshot must be
            self-consistent (taken in one call) or the walk can see a
            torn registry.
        transpiler_version: Version of the s0ma-dsl transpiler that
            produced the registration. Included in the hash so that
            two DSL versions emitting identical registrations do not
            collide if their emission rules are drifting.

    Returns:
        Lowercase hex digest prefixed with ``HASH_ALGORITHM_VERSION``
        and a ``:``. Always 65 characters (``"1:" + 64 hex``) for the
        current algorithm version.
    """
    # Import here to avoid a circular import at module load: models
    # imports nothing from hashing, but hashing only needs model types
    # at call time.
    from s0ma.models import DocGuideRegistration, DocRefRegistration

    hasher = hashlib.sha256()
    _feed(hasher, f"{HASH_ALGORITHM_VERSION}:{transpiler_version}".encode())

    # Step 2: the registration itself with content_hash zeroed.
    stripped = dataclasses.replace(doc_registration, content_hash="")
    _feed(hasher, canonicalize(stripped))

    # Step 3: the transitive closure.
    if isinstance(doc_registration, DocRefRegistration):
        _feed_doc_ref_dependencies(hasher, doc_registration, snapshot)
    elif isinstance(doc_registration, DocGuideRegistration):
        _feed_doc_guide_dependencies(hasher, doc_registration, snapshot)
    else:
        raise TypeError(
            "content_hash: expected DocRefRegistration or "
            f"DocGuideRegistration, got {type(doc_registration).__name__}"
        )

    return f"{HASH_ALGORITHM_VERSION}:{hasher.hexdigest()}"


def _feed_doc_ref_dependencies(
    hasher: "hashlib._Hash",  # noqa: UP037 — hashlib._Hash is runtime-only
    doc: DocRefRegistration,
    snapshot: RegistrySnapshot,
) -> None:
    resolved: list[bytes] = []
    for filter_expr in doc.covers:
        for entity_canon in _resolve_filter(filter_expr, snapshot):
            resolved.append(entity_canon)
    resolved.sort()
    _feed(hasher, canonicalize(len(resolved)))
    for chunk in resolved:
        _feed(hasher, chunk)


def _feed_doc_guide_dependencies(
    hasher: "hashlib._Hash",  # noqa: UP037
    doc: DocGuideRegistration,
    snapshot: RegistrySnapshot,
) -> None:
    # covers: structured entity-level refs.
    covers_canons: list[bytes] = []
    for ref in doc.covers:
        canon = _resolve_entity_ref(ref, snapshot)
        if canon is not None:
            covers_canons.append(canon)
    covers_canons.sort()
    _feed(hasher, canonicalize(len(covers_canons)))
    for chunk in covers_canons:
        _feed(hasher, chunk)

    # examples: resolve to ExampleRegistration; include body verbatim.
    example_canons: list[bytes] = []
    for ref in doc.examples:
        example = _resolve_example_ref(ref, snapshot)
        if example is not None:
            example_canons.append(canonicalize(example))
    example_canons.sort()
    _feed(hasher, canonicalize(len(example_canons)))
    for chunk in example_canons:
        _feed(hasher, chunk)


def _resolve_filter(
    filter_expr: FilterExpr,
    snapshot: RegistrySnapshot,
) -> list[bytes]:
    """Return the canonical form of every entity matched by ``filter_expr``.

    v1 resolver: matches by ``target_kind`` only. Predicates are
    included verbatim in the doc's own canonicalization (step 2) but
    are not interpreted here — an s0ma-dsl upgrade can replace this
    helper without touching the rest of the algorithm.
    """
    kind = filter_expr.target_kind
    if kind in _DOC_STORE_KINDS:
        return _resolve_by_doc_kind(kind, snapshot)
    return _resolve_by_component_kind(kind, snapshot)


def _resolve_by_doc_kind(kind: str, snapshot: RegistrySnapshot) -> list[bytes]:
    store: dict[str, Any]
    if kind == "doc-ref":
        store = dict(snapshot.doc_refs)
    elif kind == "doc-guide":
        store = dict(snapshot.doc_guides)
    else:  # "example"
        store = dict(snapshot.examples)
    return [canonicalize(store[name]) for name in sorted(store)]


def _resolve_by_component_kind(
    kind: str, snapshot: RegistrySnapshot
) -> list[bytes]:
    # ComponentSpec.kind is an enum; comparison is by its string value
    # so ``SERVICE`` matches ``"service"``. Case-insensitive to match
    # the s0ma-dsl filter source language.
    kind_lower = kind.lower()
    matched: list[ComponentSpec] = []
    for spec in snapshot.components.values():
        spec_kind = spec.kind.value if hasattr(spec.kind, "value") else spec.kind
        if str(spec_kind).lower() == kind_lower:
            matched.append(spec)
    matched.sort(key=lambda s: s.name)
    return [_canon_component_spec(spec) for spec in matched]


def _resolve_entity_ref(
    ref: EntityRef, snapshot: RegistrySnapshot
) -> bytes | None:
    """Canonicalize whatever entity the ref points to, or None on miss."""
    if ref.kind == "example":
        example = snapshot.examples.get(ref.name)
        return canonicalize(example) if example is not None else None
    if ref.kind == "doc-ref":
        doc_ref = snapshot.doc_refs.get(ref.name)
        return canonicalize(doc_ref) if doc_ref is not None else None
    if ref.kind == "doc-guide":
        doc_guide = snapshot.doc_guides.get(ref.name)
        return canonicalize(doc_guide) if doc_guide is not None else None
    spec = snapshot.components.get(ref.name)
    return _canon_component_spec(spec) if spec is not None else None


def _canon_component_spec(spec: ComponentSpec) -> bytes:
    """Canonicalize a ComponentSpec using only its semantic fields.

    ``ComponentSpec`` carries operational metadata that must be
    excluded from the hash:

    * ``registered_at`` — a timestamp generated at registration time.
      Including it would make two runs of the same code produce
      different hashes, which defeats the purpose of drift detection.
    * ``source_file`` — an absolute path that depends on where the
      checkout lives. Two developers running the same s0ma-dsl source
      would produce different hashes purely because of their
      filesystem layout.

    Everything else is semantic: a change to ``name``, ``kind``,
    ``layer``, ``intent``, ``contracts``, ``dependencies``, etc. is a
    real drift signal.
    """
    return canonicalize(
        {
            "name": spec.name,
            "kind": spec.kind,
            "layer": spec.layer,
            "intent": spec.intent,
            "contracts": spec.contracts,
            "dependencies": list(spec.dependencies),
            "resource_profile": spec.resource_profile,
            "version": spec.version,
            "metadata": dict(spec.metadata),
            "module_path": spec.module_path,
            "qualified_name": spec.qualified_name,
            "is_framework": spec.is_framework,
        }
    )


def _resolve_example_ref(
    ref: EntityRef, snapshot: RegistrySnapshot
) -> ExampleRegistration | None:
    if ref.kind and ref.kind != "example":
        return None
    return snapshot.examples.get(ref.name)


def _feed(hasher: "hashlib._Hash", chunk: bytes) -> None:  # noqa: UP037
    # A length-prefix on every chunk prevents adjacent chunks from
    # smearing across the SHA-256 input boundary — ``(b"ab", b"cd")``
    # must not collide with ``(b"abc", b"d")``.
    hasher.update(f"{len(chunk)}:".encode("ascii"))
    hasher.update(chunk)
