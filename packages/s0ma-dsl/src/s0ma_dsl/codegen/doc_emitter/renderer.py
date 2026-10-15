"""Top-level renderer for the documentation subsystem (plan M6).

Coordinates per-format rendering of every ``doc-ref`` and ``doc-guide``
declaration in a parsed module. Format dispatch is by the declaration's
``format:`` field (``markdown`` / ``html`` / ``json``); examples never
render — they are body sources embedded by guides that reference them.

Output paths are resolved relative to the *project root* (or the
``output-dir`` passed by the CLI). The renderer creates parent
directories as needed and writes UTF-8 with ``\\n`` line endings to
satisfy the determinism contract in plan §5.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.codegen.doc_emitter.html import (
    render_doc_guide_html,
    render_doc_ref_html,
)
from s0ma_dsl.codegen.doc_emitter.json_format import (
    render_doc_guide_json,
    render_doc_ref_json,
)
from s0ma_dsl.codegen.doc_emitter.markdown import (
    render_doc_guide_markdown,
    render_doc_ref_markdown,
)
from s0ma_dsl.ir.schema import SCHEMA_VERSION

if TYPE_CHECKING:
    from pathlib import Path

    from s0ma_dsl.ast_nodes.nodes import (
        DocGuideDecl,
        DocRefDecl,
        S0maModule,
    )
    from s0ma_dsl.codegen.doc_emitter.content_hashes import DocHashIndex
    from s0ma_dsl.resolver.doc_resolver import ProjectIndex

__all__ = [
    "DocRenderError",
    "RenderedOutput",
    "render_module_docs",
]


class DocRenderError(ValueError):
    """Raised when a doc declaration cannot be rendered.

    Examples: an unsupported ``format:`` value, an output path that
    escapes the project root, or an :class:`OSError` during write.
    Caller code should treat this as a deterministic failure — there
    is no partial-output state to clean up because rendering is
    file-by-file.

    The exception carries the diagnostic code the CLI should report.
    It defaults to ``DOC_RENDER_ERROR`` — every historic raise site
    keeps its exact reported code — and ADR-013 §4's
    ``DOC_SOURCE_FORMAT_UNSUPPORTED`` sets it explicitly. The code has
    to travel on the exception because rendering is one call deep
    inside two CLI commands, and a diagnostic registered in
    ``SEVERITY_MATRIX`` that never appears as a reported ``code`` is
    exactly the dead-registry shape ADR-013 exists to end.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "DOC_RENDER_ERROR",
        remediation: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.remediation = remediation


@component(
    name="S0maDSL_RenderedOutput",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Result record for a single rendered doc output: format, output path, "
        "byte content, and the content hash baked into its front-matter."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class RenderedOutput:
    """One file's worth of rendered documentation output.

    The ``content`` is the exact bytes that were (or would be) written
    to ``output_path``. Tests can compare ``content`` directly without
    touching the filesystem; CLI integration passes ``content`` to
    :meth:`Path.write_text` with a UTF-8 encoding.
    """

    decl_kind: str
    """Either ``"doc-ref"`` or ``"doc-guide"``."""

    name: str
    """Declaration name."""

    format: str
    """Output format: ``markdown`` / ``html`` / ``json``."""

    output_path: Path
    """Absolute path the renderer chose for this output."""

    content: str
    """The full rendered document, including front-matter."""

    content_hash: str
    """The transitive content hash baked into the front-matter."""


def _resolve_output_path(decl_output: str, base_dir: Path) -> Path:
    """Resolve a declared ``output:`` path against ``base_dir``.

    Reject absolute paths and ``..`` traversals — every rendered file
    must live inside the project tree to keep ``docs check-drift``
    operating on a known, bounded surface in M7.
    """
    if not decl_output:
        raise DocRenderError("doc declaration has empty output: path")
    if os.path.isabs(decl_output):
        raise DocRenderError(
            f"doc declaration output: must be a relative path, got '{decl_output}'"
        )

    candidate = (base_dir / decl_output).resolve()
    base_resolved = base_dir.resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise DocRenderError(
            f"doc declaration output: '{decl_output}' escapes base directory '{base_dir}'"
        ) from exc
    return candidate


def _render_doc_ref(
    decl: DocRefDecl,
    *,
    index: ProjectIndex,
    content_hash: str,
) -> str:
    fmt = decl.format
    if fmt == "markdown":
        return render_doc_ref_markdown(
            decl,
            index=index,
            content_hash=content_hash,
            schema_version=SCHEMA_VERSION,
        )
    if fmt == "html":
        return render_doc_ref_html(
            decl,
            index=index,
            content_hash=content_hash,
            schema_version=SCHEMA_VERSION,
        )
    if fmt == "json":
        return render_doc_ref_json(
            decl,
            index=index,
            content_hash=content_hash,
            schema_version=SCHEMA_VERSION,
        )
    raise DocRenderError(
        f"doc-ref '{decl.name}' has unsupported format '{fmt}' "
        f"(expected one of: markdown, html, json)"
    )


def _render_doc_guide(
    decl: DocGuideDecl,
    *,
    index: ProjectIndex,
    content_hash: str,
) -> str:
    fmt = decl.format
    if fmt == "markdown":
        return render_doc_guide_markdown(
            decl,
            index=index,
            content_hash=content_hash,
            schema_version=SCHEMA_VERSION,
        )
    if fmt == "html":
        return render_doc_guide_html(
            decl,
            index=index,
            content_hash=content_hash,
            schema_version=SCHEMA_VERSION,
        )
    if fmt == "json":
        return render_doc_guide_json(
            decl,
            index=index,
            content_hash=content_hash,
            schema_version=SCHEMA_VERSION,
        )
    raise DocRenderError(
        f"doc-guide '{decl.name}' has unsupported format '{fmt}' "
        f"(expected one of: markdown, html, json)"
    )


@component(
    name="S0maDSL_render_module_docs",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Render every doc-ref and doc-guide declaration in a module to its "
        "declared output path. Returns the rendered outputs without writing "
        "to disk — the caller decides whether to persist them."
    ),
    idempotent=True,
    is_framework=True,
)
def render_module_docs(
    module: S0maModule,
    *,
    index: ProjectIndex,
    hashes: DocHashIndex,
    base_dir: Path,
) -> list[RenderedOutput]:
    """Render every doc-ref and doc-guide in *module*.

    Examples are not rendered — their bodies are embedded in
    referencing guides at render time.

    Parameters
    ----------
    module:
        Parsed :class:`S0maModule` whose doc declarations are to be
        rendered.
    index:
        Project-level :class:`ProjectIndex` used to resolve references
        in ``covers:`` filters and ``{{...}}`` prose tokens.
    hashes:
        :class:`DocHashIndex` produced by
        :func:`compute_doc_hashes`. The renderer looks up each doc's
        transitive content hash and bakes it into the front-matter.
    base_dir:
        Directory paths in ``output:`` are resolved against. Typically
        the project root or the CLI's ``--output-dir``.

    Returns
    -------
    list[RenderedOutput]
        Rendered files in source-declaration order. The CLI integration
        is responsible for calling ``write_text`` on each.
    """
    outputs: list[RenderedOutput] = []

    for decl in module.doc_refs:
        digest = hashes.get_for_doc_ref(decl)
        body = _render_doc_ref(decl, index=index, content_hash=digest)
        outputs.append(RenderedOutput(
            decl_kind="doc-ref",
            name=decl.name,
            format=decl.format,
            output_path=_resolve_output_path(decl.output, base_dir),
            content=body,
            content_hash=digest,
        ))

    for guide_decl in module.doc_guides:
        digest = hashes.get_for_doc_guide(guide_decl)
        body = _render_doc_guide(guide_decl, index=index, content_hash=digest)
        outputs.append(RenderedOutput(
            decl_kind="doc-guide",
            name=guide_decl.name,
            format=guide_decl.format,
            output_path=_resolve_output_path(guide_decl.output, base_dir),
            content=body,
            content_hash=digest,
        ))

    return outputs
