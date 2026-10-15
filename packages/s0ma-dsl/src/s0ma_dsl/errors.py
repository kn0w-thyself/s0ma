"""Structured error types for the s0ma DSL transpiler.

Every error produced by the transpiler is an instance of S0maError with all
fields populated. Errors include unique codes, source locations, severity,
and actionable remediation instructions per PRD §2.4.1.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "S0maError",
    "S0maParseError",
    "S0maSemanticError",
    "S0maResolutionError",
    "S0maProjectNotFound",
    "TranspilerInternalError",
]


# ---------------------------------------------------------------------------
# Exception-safe frozen dataclass base
#
# Python's exception machinery (contextlib.__exit__, traceback, etc.) needs
# to set __traceback__, __cause__, __context__, and __suppress_context__ on
# raised exceptions.  A @dataclass(frozen=True) blocks ALL __setattr__
# calls, and Python 3.11 forbids overriding __setattr__ in frozen classes.
#
# Solution: use a non-frozen dataclass and implement freezing manually,
# whitelisting the attributes that Python's exception protocol requires.
# ---------------------------------------------------------------------------

# Attributes that Python's exception protocol needs to set freely.
_EXCEPTION_MUTABLE_ATTRS = frozenset({
    "__traceback__", "__cause__", "__context__",
    "__suppress_context__", "args",
})


@component(
    name="S0maDSL_S0maError",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Base structured error type for all transpiler diagnostics, carrying code, location, "
        "severity, and remediation."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(eq=True, unsafe_hash=True)
class S0maError(Exception):
    """A single structured diagnostic produced by the transpiler.

    Extends Exception so errors can be raised directly. Also serves as
    a structured data container with all diagnostic fields populated.

    Immutable after construction: field assignments raise
    ``FrozenInstanceError``, while exception-protocol attributes
    (``__traceback__``, ``__cause__``, etc.) remain settable so that
    Python's traceback machinery works normally.

    Every field is mandatory. The ``remediation`` field must contain
    a specific, actionable instruction — generic messages like
    "fix the error" are unacceptable.
    """

    code: str
    """Unique, searchable error code (e.g. ``NOT_EXPORTED``)."""

    message: str
    """Human/AI-readable description of the problem."""

    file: str
    """Source ``.s0ma`` file path."""

    line: int
    """Line number in the ``.s0ma`` source."""

    column: int
    """Column number in the ``.s0ma`` source."""

    severity: str
    """One of ``"error"`` or ``"warning"`` (modulated by strictness mode)."""

    remediation: str
    """Specific, actionable fix instruction."""

    context: dict[str, Any] = field(default_factory=dict)
    """Structured data providing additional context (e.g. expected vs. actual values)."""

    suggested_declaration: str | None = None
    """A ready-to-paste corrected declaration block (0.13.0 M1, batch-01c).

    Set only by the self-healing contract diagnostics
    (``PROVIDES_KEY_MISMATCH`` / ``MISSING_PACKAGE``) when the checker can
    render a *certain* corrected block from the same resolved-actual sets
    it used to detect the mismatch — e.g. ``"provides: [store.open,
    store.migrate]"``. Pasting the block over the named declaration and
    re-checking clears that diagnostic class (correct by construction). It
    stays ``None`` when no suggestion applies or when the resolution is
    ambiguous (a structured ``provides:`` triple, a ``requires:`` entry that
    names a s0ma module) — the ambiguity is then explained in
    ``remediation`` instead. Renders after the ``Remediation:`` line so the
    lead-with-cause ordering is untouched, and rides
    :meth:`to_dict` into the ``--format json`` payload and the MCP ``check``
    result unchanged. Absent from the serialised dict when ``None`` so
    pre-M1 consumers are byte-unaffected."""

    def __post_init__(self) -> None:
        # Seal the instance: all further field assignments will be blocked.
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        # Always allow exception-protocol attributes
        if name in _EXCEPTION_MUTABLE_ATTRS:
            object.__setattr__(self, name, value)
            return
        # Allow assignments during __init__ (before _sealed is set)
        try:
            sealed = object.__getattribute__(self, "_sealed")
        except AttributeError:
            sealed = False
        if sealed:
            raise dataclasses.FrozenInstanceError(
                f"cannot assign to field {name!r}"
            )
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if name in _EXCEPTION_MUTABLE_ATTRS:
            object.__delattr__(self, name)
            return
        raise dataclasses.FrozenInstanceError(
            f"cannot delete field {name!r}"
        )

    def __str__(self) -> str:
        return self.format_text()

    def format_text(self) -> str:
        """Format this error as a human-readable text diagnostic.

        Batch-01c 0.13.0 M1: when :attr:`suggested_declaration` is set,
        the corrected declaration block is rendered *after* the
        ``Remediation:`` line (the lead-with-cause ordering stays intact)
        under a label naming the declaration to replace.
        """
        sev = self.severity.upper()
        # Diagnostics point at files with a forward slash on every OS: the
        # location is a stable, portable string a reader and a committed
        # transcript can both rely on, not the host's path separator. On
        # POSIX this is a no-op; on Windows it turns ``a\b`` into ``a/b``.
        location = str(self.file).replace("\\", "/")
        header = f"{location}:{self.line}: {sev} [{self.code}]"
        body = f"  {self.message}"
        fix = f"  Remediation: {self.remediation}"
        text = f"{header}\n{body}\n{fix}"
        if self.suggested_declaration is not None:
            field_label = self.suggested_declaration.split(":", 1)[0].strip()
            text += (
                f"\n  Suggested fix — replace your `{field_label}:` "
                f"block with:\n    {self.suggested_declaration}"
            )
        return text

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary.

        Batch-01c 0.13.0 M1: ``suggested_declaration`` is included only
        when set, so a pre-M1 consumer sees a byte-identical dict for every
        diagnostic that carries no suggestion.
        """
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "severity": self.severity,
            "remediation": self.remediation,
            "context": self.context,
        }
        if self.suggested_declaration is not None:
            payload["suggested_declaration"] = self.suggested_declaration
        return payload


@component(
    name="S0maDSL_S0maParseError",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Parse-stage error for invalid syntax, missing fields, or malformed declarations in "
        ".s0ma source."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(eq=True, unsafe_hash=True)
class S0maParseError(S0maError):
    """Error produced during parsing (Stage 1-2).

    Covers invalid syntax, missing mandatory fields, malformed
    separators, and unrecognized declaration types.
    """


@component(
    name="S0maDSL_S0maSemanticError",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Semantic validation error for intra-module rule violations such as visibility "
        "mismatches or kind incompatibility."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(eq=True, unsafe_hash=True)
class S0maSemanticError(S0maError):
    """Error produced during semantic validation (Stage 3).

    Covers kind mismatches, visibility/export inconsistency, layer
    mismatches, namespace collisions, prohibited constructs, and
    authored-vs-derived relationship violations.
    """


@component(
    name="S0maDSL_S0maResolutionError",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Dependency resolution error for cross-module issues such as circular dependencies, "
        "missing exports, or vestigial imports."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(eq=True, unsafe_hash=True)
class S0maResolutionError(S0maError):
    """Error produced during dependency resolution (Stage 3, cross-module).

    Covers circular dependencies, references to non-exported components,
    missing packages, vestigial imports, and empty observes resolutions.
    """


# ---------------------------------------------------------------------------
# Project discovery error
#
# S0maProjectNotFound is structurally a plain Exception, not a S0maError,
# because it is raised before any .s0ma source is parsed: there is no file,
# line, column, or severity to report. The CLI catches it and either falls
# back to a synthetic project (legacy mode + warning) or surfaces a
# remediation message and exits with EXIT_USAGE_ERROR.
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_S0maProjectNotFound",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Raised when S0maProject.discover() cannot locate a pyproject.toml containing a "
        "[tool.s0ma] table on the path from the start directory to filesystem root."
    ),
    idempotent=True,
    is_framework=True,
)
class S0maProjectNotFound(Exception):  # noqa: N818 — public API name; renaming would break consumers
    """No ``pyproject.toml`` containing a ``[tool.s0ma]`` table was found.

    Carries the *start* path that discovery began from, so callers can
    surface a precise remediation message ("add `[tool.s0ma]` to
    `<root>/pyproject.toml`").
    """

    REMEDIATION = (
        "Add a `[tool.s0ma]` table to your project's pyproject.toml.\n"
        "  Minimum example:\n"
        "      [tool.s0ma]\n"
        "      source_roots = [\"src\"]\n"
        "  See docs/migration_guide.md \"0.11.0 → 0.12.0: Adding "
        "`[tool.s0ma]`\" for the full schema."
    )

    def __init__(self, message: str, *, start: Path | None = None) -> None:
        super().__init__(message)
        self.start = start
        self.remediation = self.REMEDIATION

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base}\nRemediation: {self.remediation}"


# ---------------------------------------------------------------------------
# Transpiler internal error
#
# TranspilerInternalError signals a *transpiler bug* — a violated build
# invariant such as the post-emission ``ast.parse()`` check (M2). It is
# structurally a plain Exception, not a S0maError, because the cause is
# code in the transpiler itself rather than anything in the user's
# ``.s0ma`` source. The user cannot remediate it; only a transpiler patch
# can. The message tells the user to file an issue.
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_TranspilerInternalError",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Raised when a transpiler-internal build invariant is violated (e.g. emitted Python "
        "fails ast.parse). Indicates a transpiler bug, not a user-source error."
    ),
    idempotent=True,
    is_framework=True,
)
class TranspilerInternalError(Exception):
    """A transpiler-internal invariant was violated.

    Raised when the transpiler produces output it knows is wrong — for
    example, an emitted ``.py`` file that fails ``ast.parse()``. The
    user has no actionable fix; the message directs them to file an
    issue against the transpiler.
    """
