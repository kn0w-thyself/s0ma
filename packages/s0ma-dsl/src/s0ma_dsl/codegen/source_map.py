"""Source map generation for the s0ma DSL transpiler.

Generates ``.s0ma.map`` files that link ``.s0ma`` source line numbers to
generated ``.py`` output line numbers.  Supports tracing runtime exceptions
back to source declarations and compiler/emitter debugging.

The source map format is a custom JSON format defined in ADR-003.
All line numbers are **1-indexed** and **inclusive**.

PRD references: FR-24, §2.6 (source map requirements)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

from s0ma_dsl.ast_nodes.enums import Kind
from s0ma_dsl.ast_nodes.nodes import (
    CellDecl,
    DocGuideDecl,
    DocRefDecl,
    ExampleDecl,
    GanglionDecl,
    HelperDecl,
    IntegrationDecl,
    NerveDecl,
    S0maModule,
    StandaloneAxonDecl,
    TestDecl,
)

# Type alias for any declaration the source map can address.
_AnyDecl = (
    NerveDecl
    | CellDecl
    | GanglionDecl
    | TestDecl
    | StandaloneAxonDecl
    | HelperDecl
    | IntegrationDecl
    | DocRefDecl
    | DocGuideDecl
    | ExampleDecl
)

__all__ = [
    "DeclarationMapping",
    "LineRange",
    "ModuleHeaderMapping",
    "ResolvedLocation",
    "SourceMap",
    "SourceMapGenerator",
    "annotate_source_pointers",
    "generate_source_map",
    "load_source_map",
    "resolve_output_line",
]

SOURCE_MAP_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Passive source-pointer comments (DSL 0.13.0 M3)
# ---------------------------------------------------------------------------
#
# Generated ``.py`` files carry one ``# s0ma:`` boundary comment at each
# authored declaration's body boundary, plus a module-header comment naming
# the source file. They greet an agent reading a traceback line in
# ``build/*.py`` with its ``.s0ma`` origin — no ``.map`` load, no MCP tool.
# The per-declaration form is::
#
#     # s0ma: src/rooms.s0ma:43 (nerve RoomsvcApi)
#
# The comments are inserted by :func:`annotate_source_pointers` BEFORE the
# drift hash is injected, so a regenerated file still classifies as clean
# (the 0.11.0 write-guard hashes the final emitted text). The source-map
# body finders (below) skip a leading boundary comment so ``body_output``
# still points at the first *authored* body line — the pointer sits one
# line above it, and the ``body_output.start -> body_source.start`` line
# arithmetic the resolver relies on stays exact.

#: The shared prefix of every source-pointer comment (per-declaration and
#: module-header forms alike).
SOURCE_POINTER_PREFIX = "# s0ma: "

#: Matches ONLY the per-declaration boundary form (``# s0ma: <file>:<n>
#: (<...>``) — never the module-header form — so the body finders skip the
#: pointer that sits at a body boundary without touching the header comment
#: (which lives in the imports region, not a body).
_BOUNDARY_COMMENT_RE = re.compile(r"^# s0ma: .+:\d+ \(")


def _is_boundary_comment(line: str) -> bool:
    """True iff *line* is a per-declaration ``# s0ma:`` body-boundary pointer."""
    return bool(_BOUNDARY_COMMENT_RE.match(line))


def _skip_boundary_comment(lines: list[str], idx: int) -> int:
    """Advance a 0-indexed body-start past a leading boundary comment.

    Returns ``idx + 1`` when ``lines[idx]`` is a per-declaration source
    pointer (so ``body_output`` starts at the first authored line), else
    ``idx`` unchanged. A no-op on un-annotated output (no pointers present),
    which keeps the direct ``emit_python`` + ``generate_source_map`` path —
    and every test that drives it — byte-for-byte as before.
    """
    if 0 <= idx < len(lines) and _is_boundary_comment(lines[idx]):
        return idx + 1
    return idx


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_LineRange",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Represents a contiguous range of lines (1-indexed, inclusive) "
        "in a source or output file for source map mappings."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class LineRange:
    """A contiguous, inclusive range of 1-indexed lines."""

    start_line: int
    end_line: int

    def to_dict(self) -> dict[str, int]:
        return {"start_line": self.start_line, "end_line": self.end_line}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> LineRange:
        """Inverse of :meth:`to_dict` (M3 follow-up: load shipped maps)."""
        return cls(
            start_line=payload["start_line"], end_line=payload["end_line"]
        )


@component(
    name="S0maDSL_DeclarationMapping",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Maps a single declaration's line ranges between .s0ma source and "
        "generated .py output, including optional body and decorator sub-ranges."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class DeclarationMapping:
    """Line mapping for a single declaration between source and output."""

    name: str
    type: str  # "nerve", "cell", "ganglion", "test", "axon", "doc-ref", "doc-guide", "example"
    source: LineRange
    output: LineRange
    body_source: LineRange | None = None
    body_output: LineRange | None = None
    decorator_output: LineRange | None = None
    # M12 (feedback 5–6): when a CONSTANT cell uses
    # ``content: @file("path")``, the cell's *body* originates outside
    # the .s0ma source — in the embedded file. Source-map consumers
    # (debuggers, error reporters) follow this field instead of
    # ``body_source`` so a runtime error in the embedded literal points
    # back to the original HTML/SQL/prompt file rather than the .s0ma
    # line that holds the directive.
    body_source_file: str | None = None
    body_source_lines: LineRange | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "source": self.source.to_dict(),
            "output": self.output.to_dict(),
        }
        if self.body_source is not None:
            d["body_source"] = self.body_source.to_dict()
        if self.body_output is not None:
            d["body_output"] = self.body_output.to_dict()
        if self.decorator_output is not None:
            d["decorator_output"] = self.decorator_output.to_dict()
        if self.body_source_file is not None:
            d["body_source_file"] = self.body_source_file
        if self.body_source_lines is not None:
            d["body_source_lines"] = self.body_source_lines.to_dict()
        return d

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> DeclarationMapping:
        """Inverse of :meth:`to_dict` — optional keys stay ``None`` when absent."""

        def _opt_range(key: str) -> LineRange | None:
            value = payload.get(key)
            return LineRange.from_dict(value) if value is not None else None

        return cls(
            name=payload["name"],
            type=payload["type"],
            source=LineRange.from_dict(payload["source"]),
            output=LineRange.from_dict(payload["output"]),
            body_source=_opt_range("body_source"),
            body_output=_opt_range("body_output"),
            decorator_output=_opt_range("decorator_output"),
            body_source_file=payload.get("body_source_file"),
            body_source_lines=_opt_range("body_source_lines"),
        )


@component(
    name="S0maDSL_ModuleHeaderMapping",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Maps the module declaration's line ranges including generated header, "
        "imports, __all__, and registration call sub-ranges."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class ModuleHeaderMapping:
    """Line mapping for the module header region."""

    source: LineRange
    output_header: LineRange
    output_imports: LineRange
    output_all: LineRange
    output_registration: LineRange

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "output_header": self.output_header.to_dict(),
            "output_imports": self.output_imports.to_dict(),
            "output_all": self.output_all.to_dict(),
            "output_registration": self.output_registration.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ModuleHeaderMapping:
        """Inverse of :meth:`to_dict` (M3 follow-up: load shipped maps)."""
        return cls(
            source=LineRange.from_dict(payload["source"]),
            output_header=LineRange.from_dict(payload["output_header"]),
            output_imports=LineRange.from_dict(payload["output_imports"]),
            output_all=LineRange.from_dict(payload["output_all"]),
            output_registration=LineRange.from_dict(
                payload["output_registration"]
            ),
        )


@component(
    name="S0maDSL_SourceMap",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Complete source map document linking .s0ma source ranges to generated "
        ".py output ranges per ADR-003 format."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class SourceMap:
    """Complete source map for a .s0ma -> .py transpilation."""

    version: str
    source_file: str
    output_file: str
    declarations: tuple[DeclarationMapping, ...]
    module_header: ModuleHeaderMapping

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source_file": self.source_file,
            "output_file": self.output_file,
            "mappings": {
                "declarations": [d.to_dict() for d in self.declarations],
                "module_header": self.module_header.to_dict(),
            },
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to deterministic JSON (sorted keys)."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SourceMap:
        """Rebuild a :class:`SourceMap` from :meth:`to_dict`'s shape.

        The read half the write-only ``.s0ma.map`` never had (M3
        follow-up): mirrors ``to_dict`` exactly — ``version`` /
        ``source_file`` / ``output_file`` verbatim, ``mappings.declarations``
        and ``mappings.module_header`` recursively — so
        ``SourceMap.from_dict(map.to_dict()) == map`` and
        :func:`resolve_output_line` answers identically over either.
        Library semantics, not CLI validation: malformed input raises the
        natural ``KeyError``/``TypeError``; no schema-version policy is
        applied here.
        """
        mappings = payload["mappings"]
        return cls(
            version=payload["version"],
            source_file=payload["source_file"],
            output_file=payload["output_file"],
            declarations=tuple(
                DeclarationMapping.from_dict(d)
                for d in mappings["declarations"]
            ),
            module_header=ModuleHeaderMapping.from_dict(
                mappings["module_header"]
            ),
        )


# ---------------------------------------------------------------------------
# Source Map Generator
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_SourceMapGenerator",
    kind=ComponentKind.SERVICE,
    layer=Layer.FRAMEWORK,
    intent=(
        "Generates source maps by analysing AST source locations and the "
        "generated Python output to build declaration-level line mappings."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class SourceMapGenerator:
    """Generates ``.s0ma.map`` source maps.

    Accepts a parsed ``S0maModule`` (with ``SourceLocation`` on every
    declaration) and the generated Python output string.  Locates each
    declaration in the output by pattern-matching, then builds a
    :class:`SourceMap` with line-range mappings.
    """

    def generate(
        self,
        module: S0maModule,
        python_output: str,
        source_file: str = "",
        output_file: str = "",
        embed_path_recorder: Callable[[str], str] | None = None,
    ) -> SourceMap:
        """Generate a source map for a transpiled module.

        Parameters
        ----------
        module:
            The parsed ``S0maModule`` AST (with ``SourceLocation``).
        python_output:
            The generated Python source string from ``PythonEmitter``.
        source_file:
            Path to the ``.s0ma`` source file (for metadata).
        output_file:
            Path to the generated ``.py`` file (for metadata).
        embed_path_recorder:
            SH-M2 (selfhost plan, INV-5 "no absolute machine paths"):
            maps an embedded ``@file()`` cell's resolved absolute path
            to the portable form recorded as ``body_source_file`` —
            project-root-relative POSIX when the caller resolved a
            ``[tool.s0ma]`` project (the same policy the ``source_file``
            field follows since SH-M1). ``None`` keeps the legacy
            resolved-absolute form (synthetic builds, direct API use).
        """
        lines = python_output.split("\n")

        # 1. Map module header regions
        module_header = self._map_module_header(module, lines)

        # 2. Find all declaration start positions (0-indexed)
        decls = list(module.all_declarations)
        starts: list[int | None] = []
        search_from = 0

        for decl in decls:
            start = self._find_decl_start(decl, lines, search_from)
            starts.append(start)
            if start is not None:
                search_from = start + 1

        # 3. Determine end positions and build mappings
        declarations: list[DeclarationMapping] = []
        for i, (decl, start) in enumerate(zip(decls, starts, strict=False)):
            if start is None:
                continue

            # End: last non-blank line before the next declaration's start
            # (or the last non-blank line of the file).
            if i + 1 < len(decls) and starts[i + 1] is not None:
                end = starts[i + 1] - 1  # type: ignore[operator]
                while end > start and not lines[end].strip():
                    end -= 1
            else:
                end = len(lines) - 1
                while end > start and not lines[end].strip():
                    end -= 1

            mapping = self._build_mapping(
                decl, lines, start, end, embed_path_recorder
            )
            declarations.append(mapping)

        return SourceMap(
            version=SOURCE_MAP_VERSION,
            source_file=source_file,
            output_file=output_file,
            declarations=tuple(declarations),
            module_header=module_header,
        )

    # -------------------------------------------------------------------
    # Module header mapping
    # -------------------------------------------------------------------

    def _map_module_header(
        self, module: S0maModule, lines: list[str]
    ) -> ModuleHeaderMapping:
        """Map the module header regions (docstring, imports, __all__, registration)."""

        # Header: docstring from line 0 to the closing """
        header_end = 0
        for i, line in enumerate(lines):
            if i > 0 and line.strip() == '"""':
                header_end = i
                break

        # __all__: find the __all__ line
        all_start = 0
        all_end = 0
        for i, line in enumerate(lines):
            if line.startswith("__all__"):
                all_start = i
                # Handle multi-line __all__
                all_end = i
                if "[" in line and "]" not in line:
                    for j in range(i + 1, len(lines)):
                        if "]" in lines[j]:
                            all_end = j
                            break
                break

        # Imports: non-blank lines between header and __all__
        import_start = header_end + 1
        while import_start < all_start and not lines[import_start].strip():
            import_start += 1
        import_end = all_start - 1
        while import_end > import_start and not lines[import_end].strip():
            import_end -= 1

        # register_module(): find start and end using paren depth
        reg_start = 0
        reg_end = 0
        for i, line in enumerate(lines):
            if line.startswith("register_module("):
                reg_start = i
                depth = 0
                for j in range(i, len(lines)):
                    depth += lines[j].count("(") - lines[j].count(")")
                    if depth == 0:
                        reg_end = j
                        break
                break

        # Source range from AST
        mod_loc = module.module.location
        source_range = LineRange(
            start_line=mod_loc.start_line if mod_loc else 1,
            end_line=mod_loc.end_line if mod_loc else 1,
        )

        return ModuleHeaderMapping(
            source=source_range,
            output_header=LineRange(
                start_line=1, end_line=header_end + 1
            ),
            output_imports=LineRange(
                start_line=import_start + 1, end_line=import_end + 1
            ),
            output_all=LineRange(
                start_line=all_start + 1, end_line=all_end + 1
            ),
            output_registration=LineRange(
                start_line=reg_start + 1, end_line=reg_end + 1
            ),
        )

    # -------------------------------------------------------------------
    # Declaration start finding
    # -------------------------------------------------------------------

    def _find_decl_start(
        self,
        decl: _AnyDecl,
        lines: list[str],
        from_idx: int,
    ) -> int | None:
        """Find the 0-indexed start line of a declaration in the output."""
        if isinstance(decl, (NerveDecl, GanglionDecl)):
            return self._find_component_decorator(decl.name, lines, from_idx)
        elif isinstance(decl, CellDecl):
            if decl.kind in (Kind.CONSTANT, Kind.TYPE):
                return self._find_cell_register_section_start(
                    decl, lines, from_idx
                )
            else:
                return self._find_component_decorator(
                    decl.name, lines, from_idx
                )
        elif isinstance(decl, StandaloneAxonDecl):
            marker = f"# Standalone axon: {decl.source} -> {decl.target}"
            return self._find_line_starting_with(marker, lines, from_idx)
        elif isinstance(decl, TestDecl):
            return self._find_test_start(decl, lines, from_idx)
        elif isinstance(decl, DocRefDecl):
            marker = f"# Doc-ref: {decl.name}"
            return self._find_line_starting_with(marker, lines, from_idx)
        elif isinstance(decl, DocGuideDecl):
            marker = f"# Doc-guide: {decl.name}"
            return self._find_line_starting_with(marker, lines, from_idx)
        elif isinstance(decl, ExampleDecl):
            marker = f"# Example: {decl.name}"
            return self._find_line_starting_with(marker, lines, from_idx)
        elif isinstance(decl, HelperDecl):
            # M13 (feedback 5–6): helpers are emitted with a ``# Helper:
            # <intent>`` comment line above the ``def`` so the source map
            # can locate them by that anchor. The intent is normalised
            # (single-spaced) at emission, so we match by prefix only.
            marker = "# Helper: "
            for i in range(from_idx, len(lines)):
                if lines[i].startswith(marker):
                    return i
            return None
        return None

    def _find_component_decorator(
        self, name: str, lines: list[str], from_idx: int
    ) -> int | None:
        """Find ``@component(`` followed by ``name=<py-literal>`` on the next line.

        The emitter routes names through ``_py_str_literal`` (M2), which
        prefers double-quoted form for identifiers (``name="x"``). When
        the name itself contains a double-quote, the literal falls back
        to ``repr()``'s single-quoted form. Match either to stay robust.
        """
        single = f"name='{name}'"
        double = f'name="{name}"'
        for i in range(from_idx, len(lines)):
            if lines[i].strip() == "@component(":
                for j in range(i + 1, min(i + 5, len(lines))):
                    if single in lines[j] or double in lines[j]:
                        return i
        return None

    def _find_cell_register_section_start(
        self, decl: CellDecl, lines: list[str], from_idx: int
    ) -> int | None:
        """Find the section start for a constant/type cell.

        The emitter outputs the body directly followed by ``register_constant()``
        or ``register_type()``.  We find the register call, then walk backward
        to locate the body start. For M12 ``@file()``-embedded CONSTANT
        cells the body is a single ``<NAME> = r\"\"\"...\"\"\"`` (or
        ``repr()``) literal that may contain blank lines inside the
        embedded content; in that case we look for the literal ``<NAME> =``
        line directly rather than walking backward through non-blank
        lines.
        """
        reg_fn = (
            "register_constant("
            if decl.kind == Kind.CONSTANT
            else "register_type("
        )
        single = f"name='{decl.name}'"
        double = f'name="{decl.name}"'
        for i in range(from_idx, len(lines)):
            stripped = lines[i].strip()
            if stripped.startswith(reg_fn):  # noqa: SIM102 — explanatory comment on inner branch
                # Verify name match on next line (either quote style — the
                # emitter routes names through ``repr()``).
                if (
                    i + 1 < len(lines)
                    and (single in lines[i + 1] or double in lines[i + 1])
                ):
                    # M12: for ``@file()``-embedded CONSTANT cells the
                    # body literal can contain blank lines, so the
                    # walk-backward heuristic would land in the middle
                    # of the literal. Search forward from from_idx for
                    # the assignment line (``<NAME> = ``) instead — the
                    # emitter always places it before the
                    # ``register_constant()`` call for the same cell.
                    if (
                        decl.kind == Kind.CONSTANT
                        and decl.embedded_content is not None
                    ):
                        assign_prefix = f"{decl.name} = "
                        for k in range(from_idx, i):
                            if lines[k].startswith(assign_prefix):
                                return k
                        # Fall through to the original walk-back if we
                        # somehow can't find the assignment (shouldn't
                        # happen for a well-formed emit, but better than
                        # crashing).
                    # Walk backward past blank lines to body
                    j = i - 1
                    while j >= 0 and not lines[j].strip():
                        j -= 1
                    # Walk backward through body content
                    body_start = j
                    while body_start > 0 and lines[body_start - 1].strip():
                        body_start -= 1
                    return body_start
        return None

    def _find_test_start(
        self, decl: TestDecl, lines: list[str], from_idx: int
    ) -> int | None:
        """Find the start of a test declaration (``# Test: validates ...``)."""
        tests_list = ", ".join(decl.tests)
        marker = f"# Test: validates {tests_list}"
        return self._find_line_starting_with(marker, lines, from_idx)

    def _find_line_starting_with(
        self, prefix: str, lines: list[str], from_idx: int
    ) -> int | None:
        """Find the first line starting with *prefix* (from *from_idx*)."""
        for i in range(from_idx, len(lines)):
            if lines[i].startswith(prefix):
                return i
        return None

    # -------------------------------------------------------------------
    # Declaration mapping builder
    # -------------------------------------------------------------------

    def _build_mapping(
        self,
        decl: _AnyDecl,
        lines: list[str],
        section_start: int,
        section_end: int,
        embed_path_recorder: Callable[[str], str] | None = None,
    ) -> DeclarationMapping:
        """Build a :class:`DeclarationMapping` for one declaration."""
        source_range = self._get_source_range(decl)
        output_range = LineRange(
            start_line=section_start + 1, end_line=section_end + 1
        )
        decl_type = self._get_decl_type(decl)
        decl_name = self._get_decl_name(decl)

        body_source = self._get_body_source_range(decl)
        body_output: LineRange | None = None
        decorator_output: LineRange | None = None
        body_source_file: str | None = None
        body_source_lines: LineRange | None = None

        if isinstance(decl, (NerveDecl, GanglionDecl)):
            decorator_output, body_output = self._find_decorator_and_body(
                lines, section_start, section_end
            )
        elif isinstance(decl, CellDecl):
            if decl.kind in (Kind.CONSTANT, Kind.TYPE):
                body_output = self._find_cell_body_output(
                    decl, lines, section_start, section_end
                )
                # M12 (feedback 5–6): an embedded CONSTANT cell's body
                # source lives in the external file. Point the source
                # map at that file so debuggers/error reporters follow
                # the redirect to the HTML/SQL/prompt rather than the
                # .s0ma line that carries the @file() directive.
                # SH-M2 (INV-5): record it in the caller's portable
                # form — committed maps must not embed absolute paths.
                if decl.embedded_file_resolved is not None:
                    body_source_file = (
                        embed_path_recorder(decl.embedded_file_resolved)
                        if embed_path_recorder is not None
                        else decl.embedded_file_resolved
                    )
                    if decl.embedded_content is not None:
                        line_count = len(decl.embedded_content.split("\n"))
                        body_source_lines = LineRange(
                            start_line=1, end_line=max(1, line_count),
                        )
            else:
                decorator_output, body_output = self._find_decorator_and_body(
                    lines, section_start, section_end
                )
        elif isinstance(decl, TestDecl):
            body_output = self._find_test_body_output(
                lines, section_start, section_end
            )
        elif isinstance(decl, HelperDecl):
            # F-M0-2 (DSL-M3): helpers were the one declaration kind
            # without a ``body_output`` range — only the whole-declaration
            # ``output`` was recorded, so tooling that wants "which emitted
            # lines are authored" (the strict-probe categoriser, error
            # reporters, coverage mappers) had to special-case helpers.
            # The emitter renders a helper as a single ``# Helper: <intent>``
            # comment anchor (``_emit_helper``) immediately followed by the
            # authored ``def`` body, so the authored body is everything
            # after that comment line: ``output.start_line + 1 ..
            # output.end_line``.
            body_output = self._find_helper_body_output(
                lines, section_start, section_end
            )
        # StandaloneAxonDecl: no body, no decorator — both stay None

        return DeclarationMapping(
            name=decl_name,
            type=decl_type,
            source=source_range,
            output=output_range,
            body_source=body_source,
            body_output=body_output,
            decorator_output=decorator_output,
            body_source_file=body_source_file,
            body_source_lines=body_source_lines,
        )

    # -------------------------------------------------------------------
    # Sub-range finders
    # -------------------------------------------------------------------

    def _find_decorator_and_body(
        self, lines: list[str], start: int, end: int
    ) -> tuple[LineRange, LineRange]:
        """Find decorator and body ranges for ``@component``-decorated declarations."""
        # Decorator starts at section_start (@component( line).
        # Find closing ) using paren depth.
        depth = 0
        decorator_end = start
        for i in range(start, end + 1):
            depth += lines[i].count("(") - lines[i].count(")")
            if depth == 0:
                decorator_end = i
                break

        decorator = LineRange(
            start_line=start + 1, end_line=decorator_end + 1
        )
        # M3: a ``# s0ma:`` boundary pointer, when the emitter annotated
        # the output, sits immediately after the decorator (at the body
        # boundary). Skip it so ``body_output`` starts at the authored
        # ``def``/``class`` line — the pointer is a marker, not body.
        body_start = _skip_boundary_comment(lines, decorator_end + 1)
        body = LineRange(
            start_line=body_start + 1, end_line=end + 1
        )
        return decorator, body

    def _find_cell_body_output(
        self,
        decl: CellDecl,
        lines: list[str],
        start: int,
        end: int,
    ) -> LineRange:
        """Find body output range for constant/type cells.

        Body lines are the lines before the ``register_constant()`` or
        ``register_type()`` call.
        """
        reg_fn = (
            "register_constant"
            if decl.kind == Kind.CONSTANT
            else "register_type"
        )
        body_end = start
        for i in range(start, end + 1):
            # M12: only the *start* of a line counts when scanning for
            # the register call. An ``r"""..."""`` literal that embeds
            # the substring "register_constant" in its content (e.g.,
            # an HTML page documenting s0ma) would otherwise produce a
            # false match. The emitter always puts ``register_constant(``
            # at column 0 (top-level), so anchoring at line start is
            # both sufficient and stable.
            if lines[i].startswith(reg_fn + "("):
                body_end = i - 1
                # Skip blank lines between body and register call
                while body_end > start and not lines[body_end].strip():
                    body_end -= 1
                break
        return LineRange(start_line=start + 1, end_line=body_end + 1)

    def _find_test_body_output(
        self, lines: list[str], start: int, end: int
    ) -> LineRange:
        """Find body output range for test declarations.

        Body starts on the line after ``# Test: validates ...`` and ends
        before the blank line or ``# Register`` comment.
        """
        # M3: skip a leading ``# s0ma:`` boundary pointer (present only on
        # annotated output) so the body starts at the authored ``def``.
        body_start = _skip_boundary_comment(lines, start + 1)
        body_end = end
        for i in range(body_start, end + 1):
            stripped = lines[i].strip()
            if not stripped or stripped.startswith("# Register"):
                body_end = i - 1
                break
        return LineRange(start_line=body_start + 1, end_line=body_end + 1)

    def _find_helper_body_output(
        self, lines: list[str], start: int, end: int
    ) -> LineRange:
        """Find body output range for helper declarations (F-M0-2, DSL-M3).

        ``_emit_helper`` renders a helper as a single ``# Helper: <intent>``
        comment anchor on the section's first line, immediately followed
        by the authored ``def`` body running to the section end. The
        authored body therefore starts on the line *after* the comment
        anchor (``start + 1`` in 0-based ``lines`` indices) and runs to
        ``end`` — i.e. ``output.start_line + 1 .. output.end_line`` in the
        1-based ``.s0ma.map`` line numbering, computed exactly like the
        nerve/test arms. Defensive: if the first line is not the
        ``# Helper:`` anchor (it always is for a well-formed emit) we still
        skip exactly one line so the range stays the authored body.

        M3: when the emitter annotated the output, a ``# s0ma:`` boundary
        pointer sits between the ``# Helper:`` anchor and the ``def`` — skip
        it too so ``body_output`` still points at the authored ``def``.
        """
        body_start = _skip_boundary_comment(lines, start + 1)
        return LineRange(start_line=body_start + 1, end_line=end + 1)

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _get_source_range(
        decl: _AnyDecl,
    ) -> LineRange:
        loc = decl.location
        if loc:
            return LineRange(start_line=loc.start_line, end_line=loc.end_line)
        return LineRange(start_line=0, end_line=0)

    @staticmethod
    def _get_body_source_range(
        decl: _AnyDecl,
    ) -> LineRange | None:
        """The body's source range, read off the declaration's own.

        The body occupies the last N lines of the declaration's source
        range, where N is the line count of the stored body text. That
        holds because the parser ends a declaration on its last body line,
        not on the blank lines after it (the ``# s0ma:`` pointers name
        ``body_source.start_line``, so an ``end_line`` that ran on would
        move every pointer down by the same amount).
        """
        if isinstance(decl, StandaloneAxonDecl):
            return None
        if isinstance(decl, DocRefDecl):
            # Doc-refs have no body section by design (plan §6.1).
            return None
        # Pull whichever body field this decl carries.
        body: str | None
        if isinstance(decl, DocGuideDecl):
            body = decl.prose_body
        elif isinstance(decl, ExampleDecl):
            body = decl.python_body
        else:
            body = decl.body
        if not body:
            return None
        loc = decl.location
        if not loc:
            return None

        body_text = body.rstrip("\n")
        body_line_count = len(body_text.split("\n"))
        return LineRange(
            start_line=loc.end_line - body_line_count + 1,
            end_line=loc.end_line,
        )

    @staticmethod
    def _get_decl_type(
        decl: _AnyDecl,
    ) -> str:
        if isinstance(decl, NerveDecl):
            return "nerve"
        if isinstance(decl, CellDecl):
            return "cell"
        if isinstance(decl, GanglionDecl):
            return "ganglion"
        if isinstance(decl, TestDecl):
            return "test"
        if isinstance(decl, StandaloneAxonDecl):
            return "axon"
        if isinstance(decl, HelperDecl):
            return "helper"
        if isinstance(decl, DocRefDecl):
            return "doc-ref"
        if isinstance(decl, DocGuideDecl):
            return "doc-guide"
        if isinstance(decl, ExampleDecl):
            return "example"
        return "unknown"

    @staticmethod
    def _get_decl_name(
        decl: _AnyDecl,
    ) -> str:
        if isinstance(decl, StandaloneAxonDecl):
            return f"{decl.source} -> {decl.target}"
        return decl.name


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_generate_source_map",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Convenience function to generate a .s0ma.map source map from a "
        "parsed S0maModule and its generated Python output."
    ),
    idempotent=True,
    is_framework=True,
)
def generate_source_map(
    module: S0maModule,
    python_output: str,
    source_file: str = "",
    output_file: str = "",
    embed_path_recorder: Callable[[str], str] | None = None,
) -> SourceMap:
    """Generate a source map from a parsed module and its Python output.

    Parameters
    ----------
    module:
        The parsed ``S0maModule`` AST (with ``SourceLocation``).
    python_output:
        The generated Python source string from ``PythonEmitter``.
    source_file:
        Path to the ``.s0ma`` source file (for metadata).
    output_file:
        Path to the generated ``.py`` file (for metadata).
    embed_path_recorder:
        Portable-path mapper for embedded ``@file()`` cell paths
        (see :meth:`SourceMapGenerator.generate`).
    """
    generator = SourceMapGenerator()
    return generator.generate(
        module, python_output, source_file, output_file, embed_path_recorder
    )


@component(
    name="S0maDSL_load_source_map",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Load a shipped .s0ma.map file from disk into a SourceMap so the "
        "resolver can consume the committed artifact."
    ),
    idempotent=True,
    is_framework=True,
)
def load_source_map(path: Path | str) -> SourceMap:
    """Load a ``.s0ma.map`` file from disk (M3 follow-up).

    The file helper over :meth:`SourceMap.from_dict`: reads *path* as
    UTF-8 JSON and rebuilds the :class:`SourceMap`, making the artifact
    every build writes next to its ``.py`` finally consumable —
    ``resolve_output_line(load_source_map(map_path), py_line)`` is the
    whole traceback-to-source flow. Library semantics: a missing file or
    malformed document raises the natural ``OSError`` /
    ``json.JSONDecodeError`` / ``KeyError``; callers with a UX (the CLI,
    a 0.14.0 tool post-processor) own their own degradation policy.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return SourceMap.from_dict(payload)


# ---------------------------------------------------------------------------
# Reverse lookup: generated .py line -> .s0ma source location (DSL 0.13.0 M3)
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_ResolvedLocation",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "The .s0ma source location a generated .py output line resolves to: "
        "source file, source line, owning declaration, and region label."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class ResolvedLocation:
    """Where a generated ``.py`` output line came from in the ``.s0ma`` source.

    ``source_line`` is ``None`` when the output line falls in a gap the map
    cannot attribute to a specific source line (between declarations, a
    blank run) — the ``region`` still says where it landed.

    ``region`` is one of: ``"body"`` (inside an authored declaration body —
    the exact-arithmetic case), ``"decorator"``, ``"declaration"`` (in the
    declaration's output but outside its body/decorator), ``"module-header"``,
    ``"imports"``, ``"exports"``, ``"registration"``, or
    ``"between-declarations"``.
    """

    source_file: str
    source_line: int | None
    declaration: str | None
    region: str

    def format_frame(self, output_file: str, output_line: int) -> str:
        """Render the one-line ``resolved:`` frame used by tool post-processing.

        e.g. ``resolved: build/rooms.py:65 -> src/rooms.s0ma:43 (RoomsvcApi)``.
        Kept here so the resolver owns both the lookup and its rendering;
        a 0.14.0 traceback post-processor can reuse it verbatim.
        """
        target = self.source_file
        if self.source_line is not None:
            target = f"{target}:{self.source_line}"
        suffix = f" ({self.declaration})" if self.declaration else f" [{self.region}]"
        return f"resolved: {output_file}:{output_line} -> {target}{suffix}"


def _range_contains(rng: LineRange, line: int) -> bool:
    return rng.start_line <= line <= rng.end_line


@component(
    name="S0maDSL_resolve_output_line",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Reverse-resolve a generated .py output line to its .s0ma source "
        "location via a SourceMap — pure body arithmetic plus region "
        "classification, no schema change."
    ),
    idempotent=True,
    is_framework=True,
)
def resolve_output_line(
    source_map: SourceMap, output_line: int
) -> ResolvedLocation:
    """Resolve a 1-indexed generated ``.py`` line to its ``.s0ma`` origin.

    The one dead-simple consumer the ``.s0ma.map`` never had: given a
    traceback line in ``build/<mod>.py``, return the source file, source
    line, declaration, and region. Inside an authored body the line is
    exact (``body_source.start + (output_line - body_output.start)``); an
    embedded ``@file()`` body resolves into the embedded file (clamped to
    its recorded span); elsewhere the region label carries the answer.
    """
    src = source_map.source_file

    for dm in source_map.declarations:
        if not _range_contains(dm.output, output_line):
            continue

        if dm.body_output is not None and _range_contains(
            dm.body_output, output_line
        ):
            offset = output_line - dm.body_output.start_line
            if dm.body_source is not None:
                return ResolvedLocation(
                    source_file=src,
                    source_line=dm.body_source.start_line + offset,
                    declaration=dm.name,
                    region="body",
                )
            if (
                dm.body_source_file is not None
                and dm.body_source_lines is not None
            ):
                # Embedded ``@file()`` body: the source lives in the
                # external file. Clamp to the recorded span so a line past
                # the literal's end (a trailing register call caught by the
                # body range) never points off the end of the embed.
                raw = dm.body_source_lines.start_line + offset
                clamped = min(
                    max(raw, dm.body_source_lines.start_line),
                    dm.body_source_lines.end_line,
                )
                return ResolvedLocation(
                    source_file=dm.body_source_file,
                    source_line=clamped,
                    declaration=dm.name,
                    region="body",
                )
            return ResolvedLocation(
                source_file=src,
                source_line=dm.source.start_line,
                declaration=dm.name,
                region="body",
            )

        if dm.decorator_output is not None and _range_contains(
            dm.decorator_output, output_line
        ):
            return ResolvedLocation(
                source_file=src,
                source_line=dm.source.start_line,
                declaration=dm.name,
                region="decorator",
            )

        # In the declaration's output but outside its body/decorator — a
        # trailing ``__name__`` reassignment, the boundary pointer itself,
        # or a blank line. Point at the declaration's source start.
        return ResolvedLocation(
            source_file=src,
            source_line=dm.source.start_line,
            declaration=dm.name,
            region="declaration",
        )

    header = source_map.module_header
    for region, rng in (
        ("module-header", header.output_header),
        ("imports", header.output_imports),
        ("exports", header.output_all),
        ("registration", header.output_registration),
    ):
        if _range_contains(rng, output_line):
            return ResolvedLocation(
                source_file=src,
                source_line=header.source.start_line,
                declaration=None,
                region=region,
            )

    return ResolvedLocation(
        source_file=src,
        source_line=None,
        declaration=None,
        region="between-declarations",
    )


# ---------------------------------------------------------------------------
# Passive comment emission: annotate generated .py with source pointers
# ---------------------------------------------------------------------------

# Declaration AST classes whose emitted body is authored ``.s0ma`` code and
# is worth a boundary pointer. CONSTANT/TYPE cells are excluded below — a
# register-emitted data literal is near-zero traceback value and its
# register-anchored body detection is deliberately left untouched.
_ANNOTATE_BODY_CLASSES = (
    NerveDecl,
    GanglionDecl,
    TestDecl,
    HelperDecl,
)


@component(
    name="S0maDSL_annotate_source_pointers",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Insert passive # s0ma: source-pointer comments into generated "
        "Python at each authored declaration's body boundary plus a "
        "module-header pointer, derived from the same spans as the map."
    ),
    idempotent=True,
    is_framework=True,
)
def annotate_source_pointers(
    module: S0maModule,
    python_output: str,
    source_file: str,
) -> str:
    """Return *python_output* with ``# s0ma:`` source-pointer comments added.

    One boundary comment is inserted immediately above each authored
    declaration's body (nerve / ganglion / ``@component`` cell / test /
    helper), plus one module-header comment naming the source file and the
    edit-the-source rule. Positions and source lines are read from a
    source map of the (still clean) output — the exact spans the committed
    ``.s0ma.map`` records — so the pointers are correct by construction and
    deterministic. Constant/type cells are skipped (see
    :data:`_ANNOTATE_BODY_CLASSES`).

    Call this AFTER :meth:`PythonEmitter.emit` and BEFORE ``inject_hashes``
    so the comments live inside the drift hash (a regenerated file still
    classifies as clean) and inside the source map regenerated from the
    annotated text (``body_output`` skips the pointer — see the body
    finders — keeping ``body_output.start -> body_source.start`` exact).
    """
    lines = python_output.split("\n")

    # A source map of the clean output: gives each authored body's first
    # output line (where the pointer goes) and its .s0ma source line (what
    # it names). embed_path_recorder is irrelevant here (constant cells are
    # not annotated), so the default resolved form is fine — this map is
    # discarded, only the committed final map is written to disk.
    prelim = SourceMapGenerator().generate(
        module, python_output, source_file=source_file
    )
    by_name = {dm.name: dm for dm in prelim.declarations}

    # (0-indexed insert position, comment text). Applied high-to-low so an
    # earlier insertion never shifts a later position.
    insertions: list[tuple[int, str]] = []

    for decl in module.all_declarations:
        if isinstance(decl, CellDecl):
            if decl.kind in (Kind.CONSTANT, Kind.TYPE):
                continue
        elif not isinstance(decl, _ANNOTATE_BODY_CLASSES):
            continue
        dm = by_name.get(decl.name)
        if dm is None or dm.body_output is None or dm.body_source is None:
            continue
        comment = (
            f"{SOURCE_POINTER_PREFIX}{source_file}:{dm.body_source.start_line} "
            f"({dm.type} {dm.name})"
        )
        insertions.append((dm.body_output.start_line - 1, comment))

    # Module-header pointer: right after the output-hash placeholder line
    # (still a placeholder at annotate time — inject_hashes runs next), so
    # it lands in the generated file's header where a reader looks first.
    header_comment = (
        f"{SOURCE_POINTER_PREFIX}generated from {source_file} — "
        f"edit the .s0ma source, never this file."
    )
    for i, line in enumerate(lines):
        if line.startswith("# s0ma-output-hash:"):
            insertions.append((i + 1, header_comment))
            break

    for pos, text in sorted(insertions, key=lambda item: item[0], reverse=True):
        lines.insert(pos, text)

    return "\n".join(lines)
