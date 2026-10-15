"""Documentation rendering subpackage (plan M6).

Renders ``doc-ref``, ``doc-guide``, and ``example`` declarations into
deterministic Markdown / HTML / JSON output files alongside the
``.py`` / ``.s0ma.json`` / ``.s0ma.map`` artifacts the rest of the
transpiler already emits.

The subpackage also wires the s0ma-core M7 ``content_hash`` utility into
the generated ``register_doc_*`` calls — at transpile time we synthesise
a :class:`s0ma.RegistrySnapshot` from the parsed AST modules, build
provisional ``DocRefRegistration`` / ``DocGuideRegistration`` records,
and ask the framework to compute their transitive content hashes. The
hash strings are then baked into the emitted Python so the runtime
registry receives the same digest the renderers committed to disk.

PRD references: §§8.5, 11.6.
"""

from s0ma_dsl.codegen.doc_emitter.content_hashes import (
    DocHashIndex,
    compute_doc_hashes,
)
from s0ma_dsl.codegen.doc_emitter.registrations import (
    build_doc_guide_registration,
    build_doc_ref_registration,
    build_example_registration,
)
from s0ma_dsl.codegen.doc_emitter.renderer import (
    DocRenderError,
    RenderedOutput,
    render_module_docs,
)
from s0ma_dsl.codegen.doc_emitter.snapshot import build_content_hash_snapshot

__all__ = [
    "DocHashIndex",
    "DocRenderError",
    "RenderedOutput",
    "build_content_hash_snapshot",
    "build_doc_guide_registration",
    "build_doc_ref_registration",
    "build_example_registration",
    "compute_doc_hashes",
    "render_module_docs",
]
