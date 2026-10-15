"""Front-matter helpers for rendered doc output.

Per design §11.6 / plan M6: every rendered output file embeds the
content hash that authorises it. The placement varies by format:

* Markdown — YAML front-matter at the top of the file.
* HTML — ``<meta>`` tag in the document head.
* JSON — ``_hash`` top-level key.

All three forms must be deterministic. We hand-roll a tiny YAML emitter
rather than pull in :mod:`pyyaml` so the output bytes never change with
upstream library versions. Only the small subset of YAML the design
needs (string scalars, no flow style, no quoting heuristics) is
supported.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "FrontmatterFields",
    "render_markdown_frontmatter",
    "render_html_meta_tags",
    "json_frontmatter_dict",
]


# Reserve a small fixed set of fields so the front-matter is a stable
# contract: drift-check, IDE plugins, and downstream tools can rely on
# them appearing in the same key order on every render.
#
# DSL-M4 (0.8.0, ADR-011 §(f), F-M5-5): ``transpiler_version`` was DROPPED
# from the front matter. ``schema_version`` (= ``ir.schema.SCHEMA_VERSION``)
# remains the contract identity; the distribution version lives only in the
# build manifest's ``transpiler_version`` and the ``.pyi`` header, so a
# distribution bump no longer churns every rendered doc. The content hash
# still mixes in ``TRANSPILER_VERSION`` (see ``content_hashes.py``) — that
# is unchanged; only the rendered field is gone.
_FIELD_ORDER = (
    "s0ma_kind",
    "name",
    "module",
    "format",
    "intent",
    "schema_version",
    "content_hash",
)


def FrontmatterFields(  # noqa: N802 — callable-casing is intentional; see docstring
    *,
    s0ma_kind: str,
    name: str,
    module: str,
    format: str,  # noqa: A002 — design field name
    intent: str,
    schema_version: str,
    content_hash: str,
) -> dict[str, str]:
    """Construct the canonical front-matter field dict.

    Returned in :data:`_FIELD_ORDER`. Callable casing keeps the public
    surface readable at call-sites (``FrontmatterFields(...)``) without
    introducing a redundant dataclass.
    """
    raw: dict[str, str] = {
        "s0ma_kind": s0ma_kind,
        "name": name,
        "module": module,
        "format": format,
        "intent": intent,
        "schema_version": schema_version,
        "content_hash": content_hash,
    }
    return {k: raw[k] for k in _FIELD_ORDER}


def _yaml_quote(value: str) -> str:
    """Quote a YAML scalar string deterministically.

    We always emit double-quoted strings — they accept the broadest
    range of characters and avoid the YAML 1.1 / 1.2 ambiguity about
    bare ``yes`` / ``no`` / ``on`` / ``off`` keywords. Backslashes and
    embedded double quotes are escaped.
    """
    escaped = value.replace("\\", "\\\\").replace("\"", "\\\"")
    # Newlines inside a YAML double-quoted string are legal but rare in
    # our usage; preserve them as escape sequences for readability.
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r")
    return f"\"{escaped}\""


def render_markdown_frontmatter(fields: dict[str, str]) -> str:
    """Render the front-matter dict as a YAML block delimited by ``---``.

    The block is followed by exactly one blank line so the body that
    follows is not parsed as part of the front-matter.
    """
    lines = ["---"]
    for key in _FIELD_ORDER:
        if key in fields:
            lines.append(f"{key}: {_yaml_quote(fields[key])}")
    lines.append("---")
    lines.append("")  # blank separator
    return "\n".join(lines) + "\n"


def render_html_meta_tags(fields: dict[str, str]) -> str:
    """Render the front-matter dict as a stack of ``<meta>`` tags.

    Each tag uses the ``s0ma:<key>`` namespace prefix to avoid colliding
    with standard HTML meta names. Output is deterministic — keys are
    emitted in :data:`_FIELD_ORDER` order, attribute values are HTML-
    escaped.
    """

    def esc(s: str) -> str:
        return (
            s.replace("&", "&amp;")
            .replace("\"", "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    lines: list[str] = []
    for key in _FIELD_ORDER:
        if key in fields:
            lines.append(
                f'    <meta name="s0ma:{esc(key)}" content="{esc(fields[key])}">'
            )
    return "\n".join(lines)


def json_frontmatter_dict(fields: dict[str, str]) -> dict[str, Any]:
    """Return the front-matter as a structured dict for JSON output.

    Keys are mirrored as a top-level ``_meta`` block so the document's
    own keys remain in the natural place; ``_hash`` is hoisted to the
    top level so consumers can read it without parsing the rest.
    """
    return {
        "_hash": fields.get("content_hash", ""),
        "_meta": {k: fields[k] for k in _FIELD_ORDER if k in fields},
    }
