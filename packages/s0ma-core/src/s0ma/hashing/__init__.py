"""Deterministic content-hash subsystem (plan M7).

The :func:`content_hash` function produces a transitive SHA-256 digest
over a documentation registration and the registry state it references.
Downstream consumers:

* :class:`s0ma.self_model.interface.SelfModelInterface.get_drift_status`
  compares the stored ``content_hash`` on each doc-ref / doc-guide with
  a freshly recomputed one and reports divergence.
* The s0ma-dsl transpiler emits the stored hash into generated
  registration calls; its own ``docs check-drift`` command re-runs
  :func:`content_hash` against the committed registry and fails CI
  when the stored and recomputed values diverge.

:func:`canonicalize` is the shared primitive — a deterministic byte
serializer exposed publicly so other parts of the codebase can
fingerprint structured state without reimplementing the scheme.
"""

from s0ma.hashing.canonical import canonicalize
from s0ma.hashing.content_hash import HASH_ALGORITHM_VERSION, content_hash

__all__ = [
    "HASH_ALGORITHM_VERSION",
    "canonicalize",
    "content_hash",
]
