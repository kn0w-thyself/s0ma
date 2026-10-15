"""Prose body tokenisation for ``doc-guide`` declarations.

Tokenises the prose body of a ``doc-guide`` into an ordered sequence of
:class:`TextChunk`, :class:`ReferenceToken`, and :class:`ExampleEmbedToken`
nodes satisfying the byte-level round-trip invariant
``"".join(t.raw for t in tokens) == body``.

The parser is deliberately minimal: it does not parse Markdown structure.
The only structural thing it does is detect triple-backtick / triple-tilde
fenced code blocks — which a well-formed doc-guide must never contain, since
the only way to embed source code in a guide is ``{{example::X}}`` —
and emit ``PROSE_RAW_CODE_BLOCK`` diagnostics for them.

Inside a ``{{...}}`` token the content is handed to the M2 entity-ref
parser (:func:`s0ma_dsl.parser.s0ma_parser._parse_entity_ref`). The
``{{example::X}}`` form is distinguished from other references by
``EntityRefAst.kind == "example"``.

A best-effort heuristic additionally flags identifier-shaped content
inside single-backtick inline spans that is NOT wrapped in ``{{...}}``
as ``POSSIBLE_UNRESOLVED_REFERENCE``. This is a warning in every mode
except ``release`` (see :mod:`s0ma_dsl.config`).

PRD references: FR-07 (exact body preservation). Design references:
§6.2 (prose body rules), R-28 (no raw code blocks).
"""

from __future__ import annotations

import re

from s0ma.decorators import component, internal
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.ast_nodes.nodes import (
    EntityRefAst,
    ExampleEmbedToken,
    ProseToken,
    ReferenceToken,
    TextChunk,
)
from s0ma_dsl.config import StrictnessMode, get_severity
from s0ma_dsl.errors import S0maParseError, S0maSemanticError

__all__ = ["parse_prose"]


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Matches the opening run of fence characters at the start of a line
# (optionally after leading whitespace). A valid Markdown fence is at
# least three consecutive backticks or tildes; we accept any count >= 3.
_FENCE_OPEN_RE = re.compile(r"^(\s*)(`{3,}|~{3,})")

# Matches a single-backtick inline code span: `identifier_like_text`.
# Conservative — we only fire the heuristic when the span contains
# exactly one identifier-shaped token (no spaces, no punctuation).
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")

# An identifier that looks plausibly like a component name: starts with
# a letter, contains only word characters, and is at least two chars.
_COMPONENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,}$")


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_parse_prose",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Tokenise a doc-guide prose body into text chunks and {{...}} reference tokens, flagging "
        "raw code blocks and suspicious inline identifiers."
    ),
    idempotent=True,
    is_framework=True,
)
def parse_prose(
    body: str,
    filename: str,
    body_start_line: int,
    mode: StrictnessMode = StrictnessMode.DEV,
) -> tuple[tuple[ProseToken, ...], list[S0maParseError | S0maSemanticError]]:
    """Tokenise a ``doc-guide`` prose body.

    Args:
        body: The raw prose body text captured after the ``---`` separator.
        filename: Source ``.s0ma`` file path (for diagnostics).
        body_start_line: 1-indexed line number of the first line of ``body``
            within the source file.
        mode: Active strictness mode — modulates the severity of the
            ``POSSIBLE_UNRESOLVED_REFERENCE`` heuristic warning.

    Returns:
        A tuple ``(tokens, diagnostics)`` where:

        * ``tokens`` is a tuple of :class:`TextChunk`,
          :class:`ReferenceToken`, and :class:`ExampleEmbedToken` nodes.
          Concatenating ``t.raw for t in tokens`` reproduces ``body``
          byte-for-byte.
        * ``diagnostics`` is a list of :class:`S0maParseError` /
          :class:`S0maSemanticError` objects, containing both
          hard errors (``PROSE_RAW_CODE_BLOCK``) and heuristic warnings
          (``POSSIBLE_UNRESOLVED_REFERENCE``). The caller decides how to
          handle them based on each diagnostic's ``severity``.

    The function never raises on prose-structure errors — it always
    returns a complete token stream plus a list of diagnostics. Invalid
    ``{{...}}`` content raised by the entity-ref parser (e.g. malformed
    kind, empty name) DOES raise :class:`S0maParseError` with the
    ``TEMPLATE_SYNTAX_ERROR`` code, since those are structural faults in
    a location that should contain a valid entity reference.
    """
    diagnostics: list[S0maParseError | S0maSemanticError] = []
    tokens: list[ProseToken] = []

    # Fence-awareness requires a line-level scan for opens/closes, but the
    # {{...}} extraction is character-level. We do a single pass by
    # iterating lines and, for each non-fence line, feeding its text into
    # a `{{...}}` scanner.

    lines = body.split("\n")
    text_buffer: list[str] = []
    in_fence = False
    fence_marker: str | None = None

    def _flush_text_buffer() -> None:
        """Emit any accumulated plain text as a TextChunk."""
        if text_buffer:
            tokens.append(TextChunk(raw="".join(text_buffer)))
            text_buffer.clear()

    for line_idx, line in enumerate(lines):
        # ``line_no`` is the 1-indexed absolute line number in the source.
        line_no = body_start_line + line_idx
        # The trailing newline is re-inserted for every line except the
        # last to preserve the original body exactly.
        trailing_newline = "\n" if line_idx < len(lines) - 1 else ""

        if in_fence:
            text_buffer.append(line + trailing_newline)
            # Check for fence close. Per Markdown, a closing fence must
            # use the same marker character; we match the leading run.
            stripped = line.lstrip()
            if fence_marker is not None and stripped.startswith(fence_marker[0] * 3):
                in_fence = False
                fence_marker = None
            continue

        fence_match = _FENCE_OPEN_RE.match(line)
        if fence_match is not None:
            # Raw code block detected — emit a structural error and enter
            # fence-consumption mode. The content is still preserved in
            # the token stream so the round-trip invariant holds.
            marker = fence_match.group(2)
            column = len(fence_match.group(1)) + 1
            diagnostics.append(S0maSemanticError(
                code="PROSE_RAW_CODE_BLOCK",
                message=(
                    "Raw fenced code block in doc-guide prose body. "
                    "Embed executable code via an example declaration and "
                    "reference it with {{example::NAME}}."
                ),
                file=filename,
                line=line_no,
                column=column,
                severity=get_severity("PROSE_RAW_CODE_BLOCK", mode) or "error",
                remediation=(
                    "Replace the fenced code block with an {{example::NAME}} "
                    "token pointing at a registered example declaration. "
                    "Source code in a doc-guide must always flow through an "
                    "example so the self-model can verify it."
                ),
                context={
                    "fence_marker": marker,
                    "line_number": line_no,
                },
            ))
            in_fence = True
            fence_marker = marker
            text_buffer.append(line + trailing_newline)
            continue

        # Not in a fence — scan the line for {{...}} tokens and inline code.
        _scan_line(
            line=line,
            trailing_newline=trailing_newline,
            line_no=line_no,
            filename=filename,
            mode=mode,
            tokens=tokens,
            text_buffer=text_buffer,
            diagnostics=diagnostics,
            flush=_flush_text_buffer,
        )

    _flush_text_buffer()

    # Round-trip sanity check — fail loudly if a contributor breaks the
    # invariant during refactoring. This is a development-time check,
    # not a user-facing diagnostic.
    assert "".join(t.raw for t in tokens) == body, (
        "parse_prose round-trip invariant violated"
    )

    return tuple(tokens), diagnostics


# ---------------------------------------------------------------------------
# Line-level scan
# ---------------------------------------------------------------------------


@internal
def _scan_line(
    line: str,
    trailing_newline: str,
    line_no: int,
    filename: str,
    mode: StrictnessMode,
    tokens: list[ProseToken],
    text_buffer: list[str],
    diagnostics: list[S0maParseError | S0maSemanticError],
    flush: object,  # Callable[[], None]
) -> None:
    """Scan a single non-fence line for ``{{...}}`` tokens and inline code.

    Appends tokens to ``tokens`` (via ``flush()`` for pending text),
    accumulates plain text into ``text_buffer``, and extends
    ``diagnostics`` with any heuristic warnings. Raises
    :class:`S0maParseError` with ``TEMPLATE_SYNTAX_ERROR`` if a
    ``{{...}}`` body contains content that is not a valid entity ref.
    """
    i = 0
    n = len(line)
    while i < n:
        # Match {{...}}
        if line[i] == "{" and i + 1 < n and line[i + 1] == "{":
            end = _find_close(line, i + 2, line_no, filename)
            raw_token = line[i:end + 2]
            inner = line[i + 2:end]
            # Column of the opening '{' in the original source line.
            column = i + 1

            # The M2 entity-ref parser may raise S0maParseError (wrapped
            # as TEMPLATE_SYNTAX_ERROR). We let that propagate — a
            # malformed reference inside {{...}} is a hard structural
            # fault in a location that MUST contain a valid reference.
            entity_ref = _parse_inner(inner.strip(), filename, line_no, column)

            # Preserve the raw text verbatim on the AST node so round-trip
            # is exact even across diagnostic repair cycles.
            token_entity = EntityRefAst(
                kind=entity_ref.kind,
                name=entity_ref.name,
                field_path=entity_ref.field_path,
                raw=raw_token,
            )

            # Before emitting the reference, flush any pending text.
            flush()  # type: ignore[operator]
            if entity_ref.kind == "example":
                tokens.append(ExampleEmbedToken(entity_ref=token_entity, raw=raw_token))
            else:
                tokens.append(ReferenceToken(entity_ref=token_entity, raw=raw_token))

            i = end + 2
            continue

        # Match single-backtick inline code (heuristic): `ident`
        if line[i] == "`":
            m = _INLINE_CODE_RE.match(line, i)
            if m is not None:
                content = m.group(1)
                # Emit heuristic warning if the content looks like a
                # component name.
                if _COMPONENT_NAME_RE.match(content):
                    severity = get_severity("POSSIBLE_UNRESOLVED_REFERENCE", mode)
                    if severity is not None:
                        diagnostics.append(S0maSemanticError(
                            code="POSSIBLE_UNRESOLVED_REFERENCE",
                            message=(
                                f"Inline code span `{content}` looks like a "
                                "component name but is not wrapped in "
                                "{{...}} — the reference cannot be "
                                "verified against the registry."
                            ),
                            file=filename,
                            line=line_no,
                            column=i + 1,
                            severity=severity,
                            remediation=(
                                f"If `{content}` refers to a registered "
                                "component, replace it with "
                                f"{{{{<kind>::{content}}}}} so the "
                                "transpiler can resolve it. If it is "
                                "incidental prose, use a descriptive "
                                "phrase instead of inline code."
                            ),
                            context={
                                "identifier": content,
                                "line_number": line_no,
                            },
                        ))
                # Buffer the inline-code span as plain text regardless
                # of the warning so the round-trip is preserved.
                text_buffer.append(line[i:m.end()])
                i = m.end()
                continue

        # Plain character.
        text_buffer.append(line[i])
        i += 1

    # Preserve the line's trailing newline (if any) in the text buffer.
    if trailing_newline:
        text_buffer.append(trailing_newline)


# ---------------------------------------------------------------------------
# {{...}} helpers
# ---------------------------------------------------------------------------


@internal
def _find_close(line: str, start: int, line_no: int, filename: str) -> int:
    """Find the closing ``}}`` for a ``{{`` opened at ``start - 2``.

    Rejects nested ``{{...}}`` — curly braces are literal otherwise.
    Returns the index of the first ``}`` in the closing ``}}``.
    """
    i = start
    n = len(line)
    while i < n:
        # Nested {{ is a parse error — per design §6.2, curly braces
        # outside {{...}} are literal and nesting is not permitted.
        if line[i] == "{" and i + 1 < n and line[i + 1] == "{":
            raise S0maParseError(
                code="TEMPLATE_SYNTAX_ERROR",
                message=(
                    "Nested '{{' inside a prose-body reference token. "
                    "References must not contain braces."
                ),
                file=filename,
                line=line_no,
                column=i + 1,
                severity="error",
                remediation=(
                    "Close the enclosing '{{...}}' token before starting "
                    "a new one. If you need a literal '{{' in prose, split "
                    "the braces across separate characters."
                ),
                context={"line_number": line_no},
            )
        if line[i] == "}" and i + 1 < n and line[i + 1] == "}":
            return i
        i += 1

    # Unclosed reference.
    raise S0maParseError(
        code="TEMPLATE_SYNTAX_ERROR",
        message=(
            "Unclosed '{{...}}' reference in doc-guide prose body — "
            "missing closing '}}'."
        ),
        file=filename,
        line=line_no,
        column=start - 1,
        severity="error",
        remediation=(
            "Close the reference with '}}'. Reference tokens may not span "
            "multiple lines; wrap the content onto a single line."
        ),
        context={"line_number": line_no},
    )


@internal
def _parse_inner(raw: str, filename: str, line_no: int, column: int) -> EntityRefAst:
    """Parse the content of a ``{{...}}`` token as an entity reference.

    Imports the M2 entity-ref parser lazily to break the circular import
    between ``prose_parser`` and ``s0ma_parser`` (the latter already
    imports the former via the doc-guide builder).

    Raises :class:`S0maParseError` with ``TEMPLATE_SYNTAX_ERROR`` if the
    content is empty or does not parse as an entity reference.
    """
    # Lazy import to avoid circular dependency with s0ma_parser.
    from s0ma_dsl.parser.s0ma_parser import _parse_entity_ref

    if not raw:
        raise S0maParseError(
            code="TEMPLATE_SYNTAX_ERROR",
            message="Empty '{{}}' reference in doc-guide prose body.",
            file=filename,
            line=line_no,
            column=column,
            severity="error",
            remediation=(
                "Fill the reference with an entity form such as "
                "'{{nerve::name}}', '{{cell::Name.field}}', or "
                "'{{example::name}}'."
            ),
            context={"line_number": line_no},
        )
    # The M2 parser raises S0maParseError(code="TEMPLATE_SYNTAX_ERROR") on
    # failure — re-raise without wrapping so the caller sees one error code.
    ref = _parse_entity_ref(raw, filename, line_no)
    return ref
