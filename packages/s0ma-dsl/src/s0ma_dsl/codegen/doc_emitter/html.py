"""Deterministic HTML renderer for doc-ref and doc-guide declarations.

We render Markdown first via :mod:`markdown` and then translate a
narrow Markdown subset into HTML by hand. Hand-rolled because every
external Markdown library introduces a version-dependent variability
that breaks plan §5's byte-equal reproducibility contract. The subset
we support matches what the M6 Markdown renderer emits — headings (1–6),
fenced code blocks, paragraphs, and bullet lists — which is enough for
every v1 doc shape.

If the Markdown renderer one day grows tables or images, this module
must grow alongside it. The only thing that should never become
configurable is the rendering algorithm itself: HTML output must be a
pure function of Markdown input.

One shape does not go through that translation: a ``doc-ref`` covering a
derived source (``covers: { source: <name> }``) renders its records to
HTML directly from the ADR-013 registry. Two reasons, both in ADR-013 §4.
The Markdown subset above has no table syntax, so routing a derived doc
through it produced a document with a heading, an intent, and no content
at all — silently, in every strictness mode, from 0.12 onward. And going
via Markdown would make an HTML render require the source to declare
*markdown* too, which turns the per-format declaration into a fiction.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.codegen.doc_emitter.derived_sources import (
    DerivedFieldKind,
    DerivedRecordSet,
    records_for,
)
from s0ma_dsl.codegen.doc_emitter.frontmatter import (
    FrontmatterFields,
    render_html_meta_tags,
)
from s0ma_dsl.codegen.doc_emitter.markdown import (
    render_doc_guide_markdown,
    render_doc_ref_markdown,
)

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.nodes import (
        DocGuideDecl,
        DocRefDecl,
    )
    from s0ma_dsl.resolver.doc_resolver import ProjectIndex

__all__ = [
    "render_doc_ref_html",
    "render_doc_guide_html",
]


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE_OPEN_RE = re.compile(r"^```(\w*)\s*$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _strip_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    """Extract YAML front-matter (key: ``"value"`` lines) and return the body."""
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, markdown

    fields: dict[str, str] = {}
    body_start = 0
    for idx in range(1, len(lines)):
        line = lines[idx]
        if line.strip() == "---":
            body_start = idx + 1
            break
        match = re.match(r"^(\w+):\s*\"(.*)\"\s*$", line)
        if match:
            key = match.group(1)
            value = (
                match.group(2)
                .replace('\\"', '"')
                .replace("\\\\", "\\")
                .replace("\\n", "\n")
                .replace("\\r", "\r")
            )
            fields[key] = value

    # Skip the blank separator line if present.
    if body_start < len(lines) and lines[body_start].strip() == "":
        body_start += 1

    return fields, "\n".join(lines[body_start:])


def _markdown_body_to_html(markdown: str) -> str:
    """Translate the narrow Markdown subset to deterministic HTML."""
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)

    in_paragraph: list[str] = []
    in_list: list[str] = []

    def flush_paragraph() -> None:
        if in_paragraph:
            text = " ".join(in_paragraph).strip()
            if text:
                out.append(f"<p>{_html_escape(text)}</p>")
            in_paragraph.clear()

    def flush_list() -> None:
        if in_list:
            out.append("<ul>")
            for item in in_list:
                out.append(f"  <li>{_html_escape(item)}</li>")
            out.append("</ul>")
            in_list.clear()

    while i < n:
        line = lines[i]

        # Fenced code block
        fence = _FENCE_OPEN_RE.match(line)
        if fence:
            flush_paragraph()
            flush_list()
            language = fence.group(1) or ""
            i += 1
            code_lines: list[str] = []
            while i < n and lines[i].rstrip() != "```":
                code_lines.append(lines[i])
                i += 1
            # i now points at the closing ``` (or off-the-end).
            cls = f' class="language-{_html_escape(language)}"' if language else ""
            escaped = _html_escape("\n".join(code_lines))
            out.append(f"<pre><code{cls}>{escaped}\n</code></pre>")
            i += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            text = heading.group(2).strip()
            out.append(f"<h{level}>{_html_escape(text)}</h{level}>")
            i += 1
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            flush_paragraph()
            in_list.append(bullet.group(1).strip())
            i += 1
            continue

        if not line.strip():
            flush_paragraph()
            flush_list()
            i += 1
            continue

        in_paragraph.append(line.strip())
        i += 1

    flush_paragraph()
    flush_list()
    return "\n".join(out)


def _wrap_html(
    *,
    title: str,
    fields: dict[str, str],
    body: str,
) -> str:
    """Return a complete HTML document with deterministic head + body."""
    meta = render_html_meta_tags(fields)
    head_lines = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '    <meta charset="utf-8">',
        f"    <title>{_html_escape(title)}</title>",
    ]
    if meta:
        head_lines.append(meta)
    head_lines.append("</head>")
    head_lines.append("<body>")
    head_lines.append(body)
    head_lines.append("</body>")
    head_lines.append("</html>")
    return "\n".join(head_lines) + "\n"


def _render_records_table_html(record_set: DerivedRecordSet) -> str:
    """Render one derived source's records as a deterministic HTML table.

    ADR-013 §4: the HTML renderer dispatches through the registry like
    the other two, rather than going through the Markdown translation
    path. Two reasons it renders the table itself. First, the Markdown
    subset this module translates has no table syntax — routing a derived
    doc through it is how ``format: html`` came to emit a heading, an
    intent, and no content at all. Second, going via Markdown would make
    an HTML render require the source to declare *markdown* as well,
    turning the format declaration into a fiction.
    """
    out: list[str] = ["<table>", "  <thead>", "    <tr>"]
    for field in record_set.fields:
        out.append(f"      <th>{_html_escape(field.label)}</th>")
    out.extend(["    </tr>", "  </thead>", "  <tbody>"])
    for row in record_set.records:
        out.append("    <tr>")
        for field, value in zip(record_set.fields, row, strict=True):
            out.append(f"      <td>{_render_record_cell_html(value, field.kind)}</td>")
        out.append("    </tr>")
    out.extend(["  </tbody>", "</table>"])
    return "\n".join(out)


def _render_record_cell_html(value: str | None, kind: DerivedFieldKind) -> str:
    """Render one record value as escaped HTML table-cell content.

    ``None`` means absent — the same em-dash the Markdown renderer uses,
    chosen here rather than by the provider, which never knows what a
    renderer is.
    """
    if value is None:
        return "—"
    if kind is DerivedFieldKind.IDENTIFIER:
        return f"<code>{_html_escape(value)}</code>"
    return _html_escape(value)


def _render_derived_doc_ref_body(decl: DocRefDecl) -> str:
    """Body for a brace-form doc-ref: heading, intent, records table.

    Deliberately the same three blocks, in the same order, that the
    Markdown renderer produces for the identical declaration — the two
    formats are two renderings of one record set, not two documents.
    """
    record_set = records_for(
        decl.covers_source or "", doc_format="html", decl_name=decl.name,
    )
    return "\n".join([
        f"<h1>{_html_escape(decl.name)}</h1>",
        f"<p>{_html_escape(decl.intent)}</p>",
        _render_records_table_html(record_set),
    ])


def _markdown_to_html_document(
    *, fields: dict[str, str], markdown: str, title: str,
) -> str:
    """Convert a complete Markdown render (with front-matter) to HTML."""
    parsed_fields, body_md = _strip_frontmatter(markdown)
    # Prefer the explicit ``fields`` dict (passed from the caller) over
    # the parsed front-matter so the HTML head reflects the canonical
    # values, not the YAML-escaped ones.
    final_fields = parsed_fields | fields
    body = _markdown_body_to_html(body_md)
    return _wrap_html(title=title, fields=final_fields, body=body)


@component(
    name="S0maDSL_render_doc_ref_html",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Render a doc-ref declaration as deterministic HTML with content-hash "
        "<meta> tags by translating the Markdown render of the same document."
    ),
    idempotent=True,
    is_framework=True,
)
def render_doc_ref_html(
    decl: DocRefDecl,
    *,
    index: ProjectIndex,
    content_hash: str,
    schema_version: str,
) -> str:
    """Render a :class:`DocRefDecl` as a complete HTML document."""
    fields = FrontmatterFields(
        s0ma_kind="doc-ref",
        name=decl.name,
        module=decl.module_location,
        format=decl.format,
        intent=decl.intent,
        schema_version=schema_version,
        content_hash=content_hash,
    )
    if decl.covers_source is not None:
        return _wrap_html(
            title=decl.name,
            fields=fields,
            body=_render_derived_doc_ref_body(decl),
        )
    md = render_doc_ref_markdown(
        decl,
        index=index,
        content_hash=content_hash,
        schema_version=schema_version,
    )
    return _markdown_to_html_document(
        fields=fields, markdown=md, title=decl.name,
    )


@component(
    name="S0maDSL_render_doc_guide_html",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Render a doc-guide declaration as deterministic HTML with content-hash "
        "<meta> tags by translating the Markdown render of the same document."
    ),
    idempotent=True,
    is_framework=True,
)
def render_doc_guide_html(
    decl: DocGuideDecl,
    *,
    index: ProjectIndex,
    content_hash: str,
    schema_version: str,
) -> str:
    """Render a :class:`DocGuideDecl` as a complete HTML document."""
    md = render_doc_guide_markdown(
        decl,
        index=index,
        content_hash=content_hash,
        schema_version=schema_version,
    )
    fields = FrontmatterFields(
        s0ma_kind="doc-guide",
        name=decl.name,
        module=decl.module_location,
        format=decl.format,
        intent=decl.intent,
        schema_version=schema_version,
        content_hash=content_hash,
    )
    return _markdown_to_html_document(
        fields=fields, markdown=md, title=decl.name,
    )
