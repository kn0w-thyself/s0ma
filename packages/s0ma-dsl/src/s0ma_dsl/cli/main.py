"""CLI entry point for the s0ma DSL transpiler.

Provides the ``s0ma`` command with subcommands for transpiling, checking,
building, inspecting, and graphing ``.s0ma`` projects.

PRD references: FR-30, §2.8.1 (commands), §2.8.2 (exit codes), §2.8.3 (agent goals)

Exit codes per §2.8.2:
  0 — Success (no errors, warnings may exist)
  1 — Validation errors (compilation blocked)
  2 — CLI usage error (invalid arguments)
  3 — Internal error (transpiler bug)
  4 — Nothing modeled (`s0ma verify` found zero hash-bearing transpiled
      modules; roster adoption verifies bytes but cannot make a semantic
      model non-hollow)
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.config import StrictnessMode, get_severity
from s0ma_dsl.discovery import (
    is_in_hidden_subtree,
    iter_visible_dirs,
    iter_visible_files,
)
from s0ma_dsl.errors import S0maError, S0maProjectNotFound
from s0ma_dsl.graph_export import (
    DETAIL_LEVELS,
    DETAIL_SUMMARY,
    IRReadError,
    NoIRArtifactsError,
    collect_graph,
    discover_ir_files,
)
from s0ma_dsl.ir.schema import IRSchemaVersionError, validate_ir_schema_version
from s0ma_dsl.project import S0maProject, is_empty_package_marker

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from s0ma_dsl.ast_nodes.nodes import S0maModule
    from s0ma_dsl.cache import BuildCache, CacheResult
    from s0ma_dsl.check_baseline import DeltaReport, DiagnosticKey
    from s0ma_dsl.codegen.build_manifest import (
        ExternalContentFileEntry,
        ModuleManifestEntry,
    )
    from s0ma_dsl.codegen.doc_emitter import DocHashIndex, RenderedOutput
    from s0ma_dsl.codegen.observes_resolver import ProjectContext
    from s0ma_dsl.resolver.doc_resolver import ProjectIndex
    from s0ma_dsl.semantic.derived_edges import DerivedEdge

__all__ = [
    "main",
    "S0maCLI",
]

# Exit codes per PRD §2.8.2
EXIT_SUCCESS = 0
EXIT_VALIDATION_ERROR = 1
EXIT_USAGE_ERROR = 2
EXIT_INTERNAL_ERROR = 3
# ``s0ma verify`` only: the target tree contains zero transpiled s0ma
# modules (no files carry s0ma hash headers), so there was nothing to
# verify. Distinct from EXIT_SUCCESS (which now means "verified >=1
# module, clean") so a vacuous pass cannot masquerade as a green check.
EXIT_NOTHING_VERIFIED = 4


# ---------------------------------------------------------------------------
# ``s0ma verify`` text rendering
# ---------------------------------------------------------------------------

#: Width the verify notes are wrapped to, matching the hand-wrapped prose
#: the rest of the command line prints. Wrapping here rather than leaving
#: it to the terminal is the point: an unwrapped note soft-wraps mid-word
#: on a narrow screen, which is what made the old per-row rendering hard
#: to read.
_VERIFY_NOTE_WIDTH = 78

#: Statuses whose rows never carried an explanation in the first place —
#: ``CLEAN`` has none, and ``ADOPTED``'s names a hash the reader did not
#: ask for. They are listed here so the note machinery below can say
#: "every other status" without enumerating the failures.
_VERIFY_BARE_STATUSES = frozenset({"CLEAN", "ADOPTED"})

#: Informational statuses: rows and note alike appear only under
#: ``--verbose`` / ``--all`` (M11 for ``BOOTSTRAP``, G1 for
#: ``PACKAGE_MARKER``). The default summary footer stays
#: ``OK / BOOTSTRAP / UNKNOWN``.
_VERIFY_VERBOSE_ONLY_STATUSES = frozenset({"BOOTSTRAP", "PACKAGE_MARKER"})

#: Statuses explained under the list however many rows they have, so the
#: shape does not change between a project with one of them and a project
#: with fifty. ``UNKNOWN`` is here because it is the one status a
#: freshly-adopted codebase sees on nearly every file, and because its
#: explanation is the only one written as prose for the reader rather
#: than lifted from the row (see ``_VERIFY_UNKNOWN_NOTE``).
_VERIFY_ALWAYS_NOTED_STATUSES = frozenset({"UNKNOWN"})

#: What ``UNKNOWN`` means, for a person reading a terminal.
#:
#: Deliberately *not* the row's ``detail`` string. That one is the
#: machine-readable surface — ``--format json`` carries it unchanged, and
#: consumers parse it — so it is written tersely and names the setting
#: twice. Said once under the list there is room to say the same thing
#: the way plan 1 §3.1 rule 12 asks for: what the reader is looking at,
#: that it is not a fault, and the two ways out.
_VERIFY_UNKNOWN_NOTE = (
    "s0ma has no model of these files yet. That is the backlog, not a fault. "
    "Convert one by writing a .s0ma source for it and running `s0ma build`; "
    "or, if a file is meant to stay plain Python, name it under "
    "[tool.s0ma].bootstrap_files in pyproject.toml."
)


def _verify_note(status: str, count: int, explanation: str) -> str:
    """One status's explanation, said once, wrapped and hanging-indented.

    ``count`` is the number of rows the note covers, so the reader can
    tie the paragraph back to the list above it without counting rows.

    Nothing the reader might retype is allowed to straddle a line break:
    a command in backticks is held together, hyphenated words are not
    split, and a long setting name overflows the margin rather than
    being chopped in half. Breaking those is the same unreadable wrap
    this rendering exists to remove.
    """
    noun = "file" if count == 1 else "files"
    text = f"{status} ({count} {noun}): {explanation}"
    held = re.sub(
        r"`[^`]*`", lambda m: m.group(0).replace(" ", "\x00"), text
    )
    return textwrap.fill(
        held,
        width=_VERIFY_NOTE_WIDTH,
        subsequent_indent="  ",
        break_long_words=False,
        break_on_hyphens=False,
    ).replace("\x00", " ")


def _verify_hoisted_details(
    results: list[dict[str, object]], shown_statuses: set[str]
) -> dict[str, str]:
    """Explanations to say once under the list instead of on every row.

    A status qualifies only when every shown row of it carries the
    *same* explanation — that is what makes the repetition repetition.
    A status whose rows say genuinely different things never qualifies:
    ``ADOPTED_DRIFT`` names the file in its remediation, and
    ``PACKAGE_MARKER`` has two distinct classification reasons
    (declared, and auto-detected) that a reader cannot tell apart from
    the file name alone.

    Given that, it is hoisted when it would otherwise be printed more
    than once, or when it is a status listed in
    ``_VERIFY_ALWAYS_NOTED_STATUSES``. The count test is the point of
    the exercise; the exception exists so that the statuses a reader
    meets constantly do not change shape between a one-file project and
    a fifty-file one. Everything else stays on its row, because hoisting
    a lone short explanation costs a label and a blank line to save
    nothing.
    """
    hoisted: dict[str, str] = {}
    for status in shown_statuses:
        rows = [row for row in results if row.get("status") == status]
        details = {str(row.get("detail", "")) for row in rows}
        if len(details) != 1:
            continue
        if len(rows) > 1 or status in _VERIFY_ALWAYS_NOTED_STATUSES:
            hoisted[status] = details.pop()
    return hoisted


# ---------------------------------------------------------------------------
# Diagnostic formatting
# ---------------------------------------------------------------------------


def _group_diagnostics_by_file(
    diagnostics: list[S0maError],
) -> dict[str, list[S0maError]]:
    """Group diagnostics by source file, preserving order of first occurrence."""
    groups: dict[str, list[S0maError]] = {}
    for diag in diagnostics:
        groups.setdefault(diag.file, []).append(diag)
    return groups


def _format_diagnostics_text(
    errors: list[S0maError],
    warnings: list[S0maError],
    mode: str | None = None,
    delta: DeltaReport | None = None,
) -> str:
    """Format diagnostics as human-readable text per PRD §2.4.4.

    Groups diagnostics per-file first, then shows a summary with counts.
    Within each file group, errors are shown before warnings, sorted by line.

    Batch-01c M2: when *delta* is supplied and the run reports failures,
    every error line is prefixed with its ``[NEW]`` / ``[PRE-EXISTING]``
    attribution and the summary leads with the NEW count (or, when no
    baseline exists yet, a one-line note). Warnings are never labelled.
    """
    if not errors and not warnings:
        return ""

    all_diagnostics = errors + warnings
    file_groups = _group_diagnostics_by_file(all_diagnostics)

    lines: list[str] = []
    file_count = len(file_groups)

    for file_path, file_diags in file_groups.items():
        # Show file header when there are multiple files
        if file_count > 1:
            file_errors = [d for d in file_diags if d.severity == "error"]
            file_warnings = [d for d in file_diags if d.severity == "warning"]
            lines.append(
                f"── {_display_path(file_path)} ({len(file_errors)} error(s), "
                f"{len(file_warnings)} warning(s)) ──"
            )
            lines.append("")

        # Sort: errors first, then warnings; within each group, by line number
        sorted_diags = sorted(
            file_diags,
            key=lambda d: (0 if d.severity == "error" else 1, d.line),
        )

        for diag in sorted_diags:
            text = diag.format_text()
            if delta is not None and diag.severity == "error":
                label = delta.label_for_diag(diag)
                if label:
                    text = f"[{label}] {text}"
            lines.append(text)
            lines.append("")

    # Summary
    lines.append("─" * 40)
    # M2: lead the failure summary with the NEW/PRE-EXISTING attribution
    # (or the no-baseline note), before the raw error/warning counts.
    if delta is not None and errors:
        if delta.baseline_exists:
            lines.append(delta.summary_line())
        else:
            lines.append(delta.no_baseline_note())
    mode_str = f" [mode: {mode}]" if mode else ""
    lines.append(
        f"Results: {len(errors)} error(s), {len(warnings)} warning(s){mode_str}"
    )
    return "\n".join(lines)


def _error_to_dict(
    diag: S0maError, delta: DeltaReport | None,
) -> dict[str, Any]:
    """``S0maError.to_dict`` plus a ``delta_label`` when a baseline exists.

    Batch-01c M2: the label (``"NEW"`` / ``"PRE-EXISTING"``) rides on each
    error object so a structured consumer (the MCP ``check`` result) sees
    the attribution per-diagnostic. Omitted entirely when no baseline
    exists — nothing is attributable — so pre-M2 consumers are unaffected.
    """
    payload = diag.to_dict()
    if delta is not None and delta.baseline_exists:
        label = delta.label_for_diag(diag)
        if label:
            payload["delta_label"] = label
    return payload


def _format_diagnostics_json(
    errors: list[S0maError],
    warnings: list[S0maError],
    files_processed: int = 0,
    mode: str | None = None,
    delta: DeltaReport | None = None,
    build_override: dict[str, Any] | None = None,
    build_environment: dict[str, Any] | None = None,
) -> str:
    """Format diagnostics as JSON per PRD §2.4.4.

    Includes per-file grouping in the ``by_file`` field for structured
    consumption by AI tools and coding agents.

    Batch-01c M2: on a failing run with a *delta*, each error object gains
    a ``delta_label`` and the document gains a ``delta`` block (NEW /
    PRE-EXISTING / RESOLVED sets + a lead summary, or a no-baseline note).
    The MCP ``check`` tool passes this document through verbatim, so the
    labels reach the agent with no MCP-side change (spec (e)).

    Batch-01c M2 (build gate): *build_override* — set only when
    ``build --allow-new-errors`` waved NEW check errors through — rides
    into the document as a top-level ``build_override`` block so the MCP
    ``build_project`` result carries the override marker the bench's
    ``build_override_new_errors`` counter keys on.

    *build_environment* is set only by ``build --without-runtime-packages``:
    the record of the ``requires:`` entries that build could not find in an
    environment the caller said lacks the project's runtime packages. It
    rides into the document as a top-level ``build_environment`` block.
    """
    # Build per-file groups for structured output
    all_diags = errors + warnings
    file_groups = _group_diagnostics_by_file(all_diags)
    by_file: list[dict[str, object]] = []
    for file_path, file_diags in file_groups.items():
        file_errors = [
            _error_to_dict(d, delta) for d in file_diags if d.severity == "error"
        ]
        file_warnings = [d.to_dict() for d in file_diags if d.severity == "warning"]
        by_file.append({
            "file": file_path,
            "errors": file_errors,
            "warnings": file_warnings,
            "error_count": len(file_errors),
            "warning_count": len(file_warnings),
        })

    result: dict[str, Any] = {
        "errors": [_error_to_dict(e, delta) for e in errors],
        "warnings": [w.to_dict() for w in warnings],
        "by_file": by_file,
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "files_processed": files_processed,
        },
    }
    if mode is not None:
        result["summary"]["mode"] = mode
    if delta is not None and errors:
        result["delta"] = delta.to_dict()
    if build_override is not None:
        result["build_override"] = build_override
    if build_environment is not None:
        result["build_environment"] = build_environment
    return json.dumps(result, indent=2, sort_keys=True)


def _split_diagnostics(
    all_errors: list[S0maError],
) -> tuple[list[S0maError], list[S0maError]]:
    """Split a flat error list into errors and warnings by severity."""
    errors = [e for e in all_errors if e.severity == "error"]
    warnings = [e for e in all_errors if e.severity == "warning"]
    return errors, warnings


def _format_diagnostic_key(key: DiagnosticKey) -> str:
    """A compact, deterministic string for a :class:`DiagnosticKey`.

    Batch-01c M2: the build manifest records which NEW errors an
    ``--allow-new-errors`` override waved through, so the bench can count
    overrides after the fact. Rendered ``CODE@module.s0ma:symbol`` (the
    ``:symbol`` suffix omitted when the diagnostic carries none) — the same
    line-number-free identity the baseline keys on.
    """
    if key.symbol:
        return f"{key.code}@{key.module}:{key.symbol}"
    return f"{key.code}@{key.module}"


def _has_doc_declarations(modules: dict[str, S0maModule]) -> bool:
    """Return True if any parsed module carries a doc-subsystem declaration."""
    for s0ma_module in modules.values():
        if s0ma_module.doc_refs or s0ma_module.doc_guides or s0ma_module.examples:
            return True
    return False


def _needs_module_local_resolution(modules: dict[str, S0maModule]) -> bool:
    """Return True if any module authors a field whose contracts live in the resolver.

    DSL-M2 (0.8.0, ADR-011 §(c)/(d)): ``deferred_requires:`` contracts
    (``DUPLICATE_REQUIRES_ENTRY``, ``DEFERRED_IMPORT_MODULE_SCOPE``, the
    vestigial-evidence arm) and qualified ``depends_on:`` target
    resolution are resolver passes. Historically the resolver only ran
    for multi-module sets, release mode, or attribute budgets — this
    predicate extends the trigger so single-module invocations that
    author the new fields still get their diagnostics (error in every
    mode means every mode must be able to fire them). Module sets that
    author neither field keep the historical trigger exactly.
    """
    for s0ma_module in modules.values():
        if s0ma_module.module.deferred_requires:
            return True
        for decl in s0ma_module.all_declarations:
            for axon in getattr(decl, "depends_on", ()):
                if "." in axon.target:
                    return True
    return False


# ---------------------------------------------------------------------------
# M14 (feedback 5–6): pretty-printers for multi-line metadata fields
# ---------------------------------------------------------------------------


def _print_inline_or_block(label: str, value: str, *, block_indent: str) -> None:
    """Render a metadata field that may be single- or multi-line.

    ``label`` is the prefix (e.g. ``"  Intent: "``) printed verbatim
    before the value. If ``value`` is single-line, the result is
    ``label + value`` on one line — preserving the pre-M14 visual layout
    for inline-quoted metadata. If ``value`` contains a newline, the
    label is printed on its own line and the value's lines follow,
    each indented by ``block_indent``.
    """
    if value is None:
        value = ""
    if "\n" not in value:
        print(f"{label}{value}")
        return
    print(label.rstrip())
    for line in value.split("\n"):
        print(f"{block_indent}{line}" if line else "")


def _print_block_only(value: str, *, block_indent: str) -> None:
    """Render a metadata field as an indented block.

    Used when the previous line carries the field's label (e.g. the
    component canonical-id row), so the value sits on its own line(s)
    indented by ``block_indent``. Single-line values render as one
    indented line; multi-line values render across multiple indented
    lines, preserving interior structure.
    """
    if value is None:
        value = ""
    if not value:
        print(f"{block_indent}")
        return
    for line in value.split("\n"):
        print(f"{block_indent}{line}" if line else "")


def _ir_semantic_value(value: Any) -> Any:
    """Project an s0ma-ir@3 state wrapper for human rendering.

    Machine-readable inspect output remains canonical IR3. Text output keeps
    its established layout while making unresolved debt explicit.
    """
    if not isinstance(value, dict):
        return value
    state = value.get("state")
    if state == "value":
        return value.get("value")
    if state == "none":
        return None
    if state == "pending":
        return f"pending({value.get('reason', '')!r})"
    return value


def _print_diagnostics(
    all_errors: list[S0maError],
    output_format: str = "text",
    files_processed: int = 0,
    mode: str | None = None,
    quiet: bool = False,
    delta: DeltaReport | None = None,
    build_override: dict[str, Any] | None = None,
    build_environment: dict[str, Any] | None = None,
    manifest_written: bool = True,
) -> None:
    """Print diagnostics in the requested format.

    When *quiet* is ``True``, only errors (not warnings) are printed in
    text mode, and the per-file grouping is suppressed. JSON mode is
    unaffected (callers can filter on the consumer side).

    Batch-01c M2: *delta* (supplied only by ``check``) carries the NEW /
    PRE-EXISTING attribution; it is threaded to the text and JSON
    formatters and applied inline in quiet mode. Callers that pass no
    *delta* (every command but ``check``) render byte-identically to
    before.

    Batch-01c M2 (build gate): *build_override* — supplied only by
    ``build`` when ``--allow-new-errors`` waved NEW check errors through —
    rides into the JSON document as a top-level ``build_override`` block
    and prints one trailing text line naming the override.

    *build_environment* (supplied only by ``build --without-runtime-packages``)
    rides into the JSON document as a top-level ``build_environment`` block
    and prints one text line naming the packages the build could not verify.
    That line names the manifest only when *manifest_written* says the
    build wrote one (a build with no build directory, such as one of a
    project without ``[tool.s0ma]``, writes none).
    """
    errors, warnings = _split_diagnostics(all_errors)
    if output_format == "json":
        print(_format_diagnostics_json(
            errors, warnings, files_processed, mode=mode, delta=delta,
            build_override=build_override,
            build_environment=build_environment,
        ))
        return
    # M2: the override note leads the text output (before any warnings) so
    # a build that waved NEW check errors through says so up front.
    if build_override is not None:
        count = build_override.get("new_error_count", 0)
        print(
            f"Note: built with --allow-new-errors — {count} NEW check "
            f"error(s) waved through and recorded in the build manifest."
        )
    if build_environment is not None:
        names = list(build_environment.get("unverified_packages", []))
        if names:
            noun = "entry" if len(names) == 1 else "entries"
            recorded = (
                ", recorded in the build manifest as unverified"
                if manifest_written else ""
            )
            print(
                f"Note: built without the project's runtime packages: "
                f"{len(names)} requires: {noun} not verified here "
                f"({', '.join(names)}){recorded}."
            )
    if quiet:
        # Quiet mode: only print errors (no warnings, no file grouping)
        for err in errors:
            text = err.format_text()
            if delta is not None:
                label = delta.label_for_diag(err)
                if label:
                    text = f"[{label}] {text}"
            print(text)
    else:
        text = _format_diagnostics_text(errors, warnings, mode=mode, delta=delta)
        if text.strip():
            print(text)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def _discover_s0ma_files(path: str) -> list[Path]:
    """Discover .s0ma files in a file or directory."""
    p = Path(path)
    if p.is_file():
        if p.suffix == ".s0ma":
            return [p]
        return []
    if p.is_dir():
        # ``iter_visible_files`` returns real files only — a *directory*
        # named ``.s0ma`` (the gitignored working-state dir holding the
        # check baseline and ``registry.db``) also matches ``*.s0ma``, and
        # handing it to the parser died with `Is a directory` — and prunes
        # hidden subtrees, so a checkout nested inside the tree being built
        # (``.claude/worktrees/<name>/src/`` — a full copy of the same
        # project) cannot collide every module with itself.
        return iter_visible_files(p, "*.s0ma")
    return []


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------


# M6a (feedback 5–6, ADR-007): the auto-emitted build ``__init__.py``
# carries a single docstring marking the directory as generated.  Kept as
# a module-level constant so the build code-path and any tooling that
# needs to recognise the marker share a canonical string.
_BUILD_INIT_DOCSTRING = (
    '"""Auto-generated by `s0ma build` — do not edit.\n\n'
    "This package contains transpiled .s0ma modules. The directory is\n"
    "marked as a real Python package so cross-module imports work; the\n"
    "build manifest (`build.s0ma.json`, M6b) is the source of truth for\n"
    'what was emitted.\n"""\n'
)


def _emit_build_init(output_dir: Path) -> Path | None:
    """Write ``output_dir / __init__.py`` so the flat build is importable.

    M6a (feedback 5–6, ADR-007): every successful build emits a single
    ``__init__.py`` at the build root. The file's body is the constant
    :data:`_BUILD_INIT_DOCSTRING` — a one-line module docstring
    explaining that the file is generated. Existing matching content is
    left untouched so repeated builds do not churn mtimes; mismatched
    content is overwritten so a stale or hand-edited file cannot
    silently shadow the canonical docstring.

    Returns the path on a successful write/no-op, or ``None`` when
    *output_dir* is missing (caller should not have invoked this).
    """
    if output_dir is None:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    init_path = output_dir / "__init__.py"
    try:
        existing = init_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        existing = None
    if existing != _BUILD_INIT_DOCSTRING:
        init_path.write_text(_BUILD_INIT_DOCSTRING, encoding="utf-8", newline="\n")
    return init_path


# ---------------------------------------------------------------------------
# M6b (feedback 5–6, ADR-007): Build manifest emission
# ---------------------------------------------------------------------------
#
# Every successful build emits a single ``build.s0ma.json`` at the build
# root. The manifest is the canonical "what's in this build" answer —
# the runtime bridge reads it instead of walking the filesystem (see
# ``s0ma_dsl.runtime_bridge.registration.import_modules_from_manifest``).
# Hashes are computed by reading the freshly-written ``.py`` and the
# ``.s0ma`` source from disk; this keeps the pipeline decoupled from
# manifest construction and means no restructuring of the per-file
# transpile signature.


def _display_path(path: object) -> str:
    r"""A path shown to a person or quoted in a committed transcript,
    forward-slashed on every OS.

    Cross-platform byte-identity (NFR-7): ``s0ma build`` / ``s0ma check`` print
    the same line on Windows and POSIX, so an evidence transcript and a reader's
    copy-paste match whatever the host is. POSIX is a no-op; on Windows it turns
    ``a\b`` into ``a/b``. Unlike :func:`_recorded_project_path` it leaves the
    path otherwise as-is (absolute or relative) — this is a console line, not a
    byte recorded into an artifact — and it takes ``str``/``Path`` alike, since
    the emitted-output list is already stringified.
    """
    return str(path).replace("\\", "/")


def _recorded_project_path(
    path: Path, s0ma_project: S0maProject | None,
) -> str:
    """The portable form of *path* for embedding in emitted artifacts.

    SH-M1 (selfhost plan, INV-5 "no absolute machine paths" /
    NFR-7 cross-platform byte-identity — the continuation of WIN-M3's
    basename fix for ``transpiled_file``/``output_file``): artifacts
    that record where their source lives must do so in a form that is
    byte-identical across machines, working directories, and operating
    systems, because consumer projects commit build outputs (FR-MCP-11)
    and byte-compare rebuilds against them. When a real ``[tool.s0ma]``
    project is resolved, the recorded form is the path **relative to
    the project root, in POSIX form** (forward slashes on Windows too).
    Synthetic-fallback invocations (no project) and paths outside the
    project root keep the legacy as-passed string — there is no
    portable anchor to express them against. Diagnostics deliberately
    do NOT use this helper: error messages keep the invocation-relative
    paths the user typed (they are ephemeral output, not artifacts).
    """
    if s0ma_project is None or s0ma_project.synthetic:
        return str(path)
    try:
        root = Path(s0ma_project.root).resolve()
        return Path(path).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return str(path)


def _recorded_logical_structure(
    source_path: Path, s0ma_project: S0maProject | None,
) -> tuple[str, str]:
    """The portable ``(source_root, logical_path)`` for *source_path*.

    STD-M5 (usability plan, Decision 3 / Option B): the build manifest
    records each module's **logical** position in the source tree —
    which configured ``source_roots`` / ``test_roots`` entry it came
    from, and its path relative to that root — so tooling (the app map,
    the future explorer, ``s0ma inspect``) can present the source layout
    while the build directory stays flat. No DSL/source-syntax change,
    no build-dir nesting.

    Both returned values obey the SH-M1 / INV-5 contract for path-typed
    manifest fields, exactly like :func:`_recorded_project_path`:

    - ``source_root`` is the *configured* root entry — the project-root-
      relative POSIX string the author wrote in ``[tool.s0ma]`` (e.g.
      ``"src"``, ``"domain"``) — recovered from the resolved absolute
      root via ``root.relative_to(project_root)``. NOT a resolved
      absolute path.
    - ``logical_path`` is *source_path* relative to that configured
      root, POSIX (forward slashes on Windows too) — e.g.
      ``"orders/orders_domain.s0ma"`` or, for a top-level module,
      ``"order_model.s0ma"``.

    Returns ``("", "")`` when there is no portable anchor: a synthetic-
    fallback project (no ``[tool.s0ma]`` table to be relative to), or a
    *source_path* that resolves outside every configured root (no root
    encloses it). The manifest writer omits empty values so such builds
    stay byte-identical to pre-STD-M5 ones (see
    ``ModuleManifestEntry.to_dict``). The first enclosing root wins when
    roots are nested — though :func:`s0ma_dsl.project._detect_overlapping_roots`
    already rejects overlapping roots at project-load time, so in a
    well-formed project at most one root encloses any source path.
    """
    if s0ma_project is None or s0ma_project.synthetic:
        return ("", "")
    try:
        project_root = Path(s0ma_project.root).resolve()
        resolved_source = Path(source_path).resolve()
    except OSError:
        return ("", "")
    for root in (*s0ma_project.source_roots, *s0ma_project.test_roots):
        try:
            resolved_root = Path(root).resolve()
            logical = resolved_source.relative_to(resolved_root).as_posix()
            source_root = resolved_root.relative_to(project_root).as_posix()
        except (ValueError, OSError):
            continue
        return (source_root, logical)
    return ("", "")


def _root_role(
    source_path: Path, s0ma_project: S0maProject | None,
) -> str | None:
    """The manifest role the project's configured roots give *source_path*.

    ``"test"`` when the file lives under one of ``[tool.s0ma].test_roots``,
    ``"source"`` when it lives under one of ``source_roots``, and ``None``
    when no configured root encloses it or there is no real project to
    ask: a synthetic fallback has no roots of its own, so it has nothing
    to attribute against. The roots are disjoint by construction, since
    :func:`s0ma_dsl.project._detect_overlapping_roots` refuses a project
    whose roots overlap at load time (``OVERLAPPING_DISCOVERY_ROOTS``), so
    at most one root encloses any file and the answer is never ambiguous.

    This is the one place a build derives a role from the file system.
    Readers take the role from the manifest entry it is recorded in.
    ``s0ma test``'s build helper states its role explicitly instead (the
    hidden ``_role`` attribute), and that statement wins over this answer.
    """
    if s0ma_project is None or s0ma_project.synthetic:
        return None
    try:
        resolved_source = Path(source_path).resolve()
    except OSError:
        return None
    for role, roots in (
        ("test", s0ma_project.test_roots),
        ("source", s0ma_project.source_roots),
    ):
        for root in roots:
            try:
                resolved_source.relative_to(Path(root).resolve())
            except (ValueError, OSError):
                continue
            return role
    return None


def _module_outside_project_roots(
    module_name: str, source_path: Path, s0ma_project: S0maProject,
) -> S0maError:
    """The warning for a module the build recorded as source by default.

    Raised by ``_cmd_build`` when a real project is built from a path
    whose module lives under none of the configured roots (``s0ma build
    examples/`` in a project whose roots are ``src`` and ``tests``). The
    entry is still written, with role ``source``, because nothing declares
    the module a test; the warning says so and names the roots, as
    project-root-relative paths, so the reader can declare the directory
    or move the file. It is a warning in every strictness mode
    (``SEVERITY_MATRIX``), so
    :func:`s0ma_dsl.check_baseline.is_check_severity_error` never counts
    it and neither the build gate nor the check baseline is affected.
    """
    source_roots = [
        _recorded_project_path(root, s0ma_project)
        for root in s0ma_project.source_roots
    ]
    test_roots = [
        _recorded_project_path(root, s0ma_project)
        for root in s0ma_project.test_roots
    ]
    return S0maError(
        code="MODULE_OUTSIDE_PROJECT_ROOTS",
        message=(
            f"Module '{module_name}' lives under none of the project's "
            f"source_roots ({', '.join(source_roots) or 'none declared'}) "
            f"or test_roots ({', '.join(test_roots) or 'none declared'}), "
            f"so the build recorded it with role source."
        ),
        file=str(source_path),
        line=1,
        column=0,
        severity="warning",
        remediation=(
            "Add its directory to [tool.s0ma].source_roots or test_roots so "
            "the build can record which it is, or move the file under a "
            "configured root. Until then it is recorded as source, which is "
            "what bootstrap_imports loads by default."
        ),
        context={
            "module": module_name,
            "source_roots": source_roots,
            "test_roots": test_roots,
        },
    )


def _collect_manifest_entry(
    *,
    module_name: str,
    source_path: Path,
    build_dir: Path,
    role: str = "source",
    recorded_source: str | None = None,
    recorded_logical: tuple[str, str] = ("", ""),
) -> ModuleManifestEntry | None:
    """Build one ``ModuleManifestEntry`` from on-disk artifacts.

    Returns ``None`` if the expected ``.py`` is missing — that
    indicates the transpile step did not actually emit (e.g.,
    blocking errors caused an early return). The caller filters
    these out before constructing the manifest.

    Path layout (M6a flat layout):

    - ``.py``  →  ``<build_dir>/<module_name>.py``
    - IR       →  ``<build_dir>/<module_name>.s0ma.json``
    - map      →  ``<build_dir>/<module_name>.s0ma.map``

    Manifest paths are recorded as basenames (the build directory's
    location is recorded in the top-level ``build_dir`` field, so
    individual entries do not need to repeat it). The ``source``
    field stays as a path string — the source lives outside the
    build directory and is what answers "what produced this".
    ``recorded_source`` (SH-M1, INV-5) supplies the portable form to
    embed — project-root-relative POSIX when a project is resolved
    (see :func:`_recorded_project_path`); ``None`` falls back to the
    legacy as-passed string.

    The ``role`` argument (added 0.14.0 / PRE-2) is forwarded to the
    manifest entry so source vs test modules can coexist in the same
    manifest. Defaults to ``"source"`` so legacy build paths stay
    backward-compatible.

    ``recorded_logical`` (STD-M5, INV-5) is the portable
    ``(source_root, logical_path)`` pair to embed — the configured root
    entry the module came from and its path relative to that root, both
    project-root-relative POSIX (see :func:`_recorded_logical_structure`).
    Defaults to ``("", "")`` (no portable anchor); the manifest writer
    omits empty values so the bytes stay identical to pre-STD-M5 builds.
    """
    from s0ma_dsl.codegen.build_manifest import (
        ModuleManifestEntry,
        compute_file_hash,
    )

    py_path = build_dir / f"{module_name}.py"
    if not py_path.is_file():
        return None
    ir_path = build_dir / f"{module_name}.s0ma.json"
    map_path = build_dir / f"{module_name}.s0ma.map"

    source_text = source_path.read_text(encoding="utf-8")
    output_text = py_path.read_text(encoding="utf-8")

    return ModuleManifestEntry(
        name=module_name,
        source=recorded_source if recorded_source is not None else str(source_path),
        output=py_path.name,
        ir=ir_path.name,
        source_map=map_path.name,
        source_hash=compute_file_hash(source_text),
        output_hash=compute_file_hash(output_text),
        role=role,
        source_root=recorded_logical[0],
        logical_path=recorded_logical[1],
    )


def _emit_build_manifest(
    *,
    project_name: str,
    build_dir: Path,
    entries: list[ModuleManifestEntry],
    topological_import_order: tuple[str, ...] = (),
    external_content_files: dict[str, ExternalContentFileEntry] | None = None,
    recorded_build_dir: str | None = None,
    overridden_new_errors: tuple[str, ...] = (),
    unverified_packages: tuple[str, ...] = (),
    emit_self_context: bool = True,
) -> Path | None:
    """Write the build manifest to ``build_dir/build.s0ma.json``.

    Returns the manifest path on success or ``None`` when there is
    nothing to write (e.g., zero modules emitted). The transpiler
    version comes from :data:`s0ma_dsl.__version__`.

    ``recorded_build_dir`` (SH-M1, INV-5) is the portable string to
    embed in the manifest's ``build_dir`` field — project-root-relative
    POSIX when a project is resolved (see
    :func:`_recorded_project_path`). ``None`` falls back to the legacy
    ``str(build_dir)`` (the absolute on-disk path), which synthetic
    invocations keep. The file is always *written* to the real
    ``build_dir`` path regardless.

    ``topological_import_order`` (M10) is the dependency-first import
    order computed from every module's ``uses:`` edges. Empty when the
    caller is the legacy single-file transpile path; the build path
    passes the real value computed by
    :func:`s0ma_dsl.resolver.compute_topological_order`.

    ``external_content_files`` (M12) is the map of CONSTANT-cell embed
    targets keyed by ``"<module>::<cell>"``. The build path collects
    these from each parsed module's ``CellDecl.embedded_*`` fields;
    legacy callers leave the argument ``None`` and the manifest stays
    byte-identical to its pre-M12 shape.

    ``unverified_packages`` is the record of a build made with
    ``--without-runtime-packages``: the import names of the ``requires:``
    entries it could not find. Empty, and the key omitted, otherwise.
    """
    if build_dir is None:
        return None
    from s0ma_dsl import __version__ as transpiler_version
    from s0ma_dsl.codegen.build_manifest import build_manifest, emit_manifest
    from s0ma_dsl.codegen.self_context import emit_self_context_artifacts

    self_context_refs = (
        emit_self_context_artifacts(build_dir, entries)
        if emit_self_context
        else None
    )

    manifest = build_manifest(
        project_name=project_name,
        build_dir=(
            recorded_build_dir if recorded_build_dir is not None else build_dir
        ),
        modules=entries,
        transpiler_version=transpiler_version,
        topological_import_order=topological_import_order,
        external_content_files=external_content_files,
        overridden_new_errors=overridden_new_errors,
        unverified_packages=unverified_packages,
        self_context=self_context_refs,
    )
    return emit_manifest(manifest, build_dir)


def _prune_orphan_artefacts(
    build_dir: Path, known_module_names: set[str],
) -> list[Path]:
    """Delete ``.py`` / ``.s0ma.json`` / ``.s0ma.map`` triples whose
    module is no longer in the manifest.

    PRE-6 (0.14.0): after a build that renames or removes a ``.s0ma``
    source, the prior build's emitted artefacts linger and confuse
    ``s0ma verify`` / ``s0ma inspect``. This helper computes the set of
    orphan triples and removes them.

    Safety predicate (triple-check guard): a ``.py`` file is only
    eligible for prune when ALL THREE of ``<name>.py``,
    ``<name>.s0ma.json``, and ``<name>.s0ma.map`` exist in
    *build_dir*. The triple is the canonical s0ma-emitted shape — a
    hand-written ``.py`` without sibling IR/map is never pruned.
    ``__init__.py`` is always skipped, and the manifest file
    (``build.s0ma.json``) is never matched by the ``*.py`` glob.

    Returns the list of removed ``.py`` paths (the IR and map siblings
    are removed alongside but not separately reported, so the caller
    can log a single concise line).
    """
    pruned: list[Path] = []
    if not build_dir.is_dir():
        return pruned
    for py_path in sorted(build_dir.glob("*.py")):
        if py_path.name == "__init__.py":
            continue
        stem = py_path.stem
        if stem in known_module_names:
            continue
        ir_path = build_dir / f"{stem}.s0ma.json"
        map_path = build_dir / f"{stem}.s0ma.map"
        if not (ir_path.is_file() and map_path.is_file()):
            # Hand-written .py without sibling artefacts — leave alone.
            continue
        py_path.unlink()
        ir_path.unlink()
        map_path.unlink()
        pruned.append(py_path)
    return pruned


def _discover_raw_python_tests(test_roots: list[Path]) -> list[Path]:
    """Return ``.py`` test files under *test_roots* that have no ``.s0ma`` sibling.

    PRE-9 (0.14.0): Phase 2's local-smoke tests and lint linters are raw
    Python (they shell out to docker or operate on file trees in ways
    that don't fit a ``.s0ma`` body), but today ``s0ma test`` only
    discovers ``.s0ma`` test modules, forcing operators to invoke
    ``pytest`` twice. This helper closes the gap.

    Filtering rules:
    - The file's basename matches pytest's collection prefix/suffix
      (``test_*.py`` / ``*_test.py`` / ``*_tests.py``). Files outside
      that shape (helpers, conftest, ``__init__.py``) are skipped.
    - The file has no same-stem ``.s0ma`` sibling in the same
      directory — the ``.s0ma`` is the source of truth and the build
      already emits a canonical ``.py`` into ``build_dir/``.
    - The file is not inside a ``.s0ma.cache`` / ``__s0ma_cache__``
      subtree (those caches hold transpiled artefacts that the
      double-collection guard already excludes via ``--ignore``).
    """
    discovered: list[Path] = []
    for root in test_roots:
        if not root.is_dir():
            continue
        for py in iter_visible_files(root, "*.py"):
            # ``.s0ma.cache`` is pruned as a hidden dir; the legacy
            # ``__s0ma_cache__`` name is not dot-prefixed and still needs
            # naming here.
            if any(part == "__s0ma_cache__" for part in py.parts):
                continue
            name = py.name
            if name in {"__init__.py", "conftest.py"}:
                continue
            if not (
                name.startswith("test_")
                or name.endswith("_test.py")
                or name.endswith("_tests.py")
            ):
                continue
            s0ma_sibling = py.with_suffix(".s0ma")
            if s0ma_sibling.is_file():
                continue
            discovered.append(py.resolve())
    return discovered


def _validate_fixtures_format(
    test_roots: tuple[Path, ...],
    fixtures_format: dict[str, str],
    mode: StrictnessMode,
) -> list[S0maError]:
    """Validate non-``.s0ma`` fixture files under *test_roots*.

    M-18 (POST-12g, 0.16.0): scan every configured ``test_root``
    looking for files whose basenames match a glob declared in
    ``[tool.s0ma].fixtures_format``. For each match, run the
    format-specific validator (``ndjson`` / ``json`` / ``yaml``)
    and emit a :data:`FIXTURE_FORMAT_INVALID` diagnostic if the
    file fails to parse.

    Files outside the configured globs are ignored — fixtures stay
    opt-in. An empty ``test_roots`` tuple or an empty
    ``fixtures_format`` dict produces zero diagnostics.

    Parameters
    ----------
    test_roots:
        Configured ``test_roots`` from :class:`S0maProject`.
    fixtures_format:
        Glob → format-name mapping from
        ``[tool.s0ma].fixtures_format``.
    mode:
        Active strictness mode — used to resolve the severity of
        :data:`FIXTURE_FORMAT_INVALID` (warning in dev/migration,
        error in strict/release).
    """
    errors: list[S0maError] = []
    if not fixtures_format:
        return errors
    severity = get_severity("FIXTURE_FORMAT_INVALID", mode)
    if severity is None:
        return errors

    for root in test_roots:
        if not root.is_dir():
            continue
        for glob, fmt in fixtures_format.items():
            # A declared fixtures glob may be path-shaped, so ``rglob``
            # keeps its exact semantics and the hidden-subtree rule is
            # applied to the results instead of by pruning the walk.
            for path in sorted(root.rglob(glob)):
                if not path.is_file() or is_in_hidden_subtree(path, root):
                    continue
                line_no, message = _check_fixture_format(path, fmt)
                if message is None:
                    continue
                errors.append(S0maError(
                    code="FIXTURE_FORMAT_INVALID",
                    message=(
                        f"Fixture {path} does not parse as "
                        f"'{fmt}': {message}"
                    ),
                    file=str(path),
                    line=line_no,
                    column=0,
                    severity=severity,
                    remediation=(
                        f"Fix the format of {path} so it parses as "
                        f"a '{fmt}' document, or remove the "
                        f"'{glob}' entry from [tool.s0ma].fixtures_format "
                        f"if this file is not actually a fixture."
                    ),
                    context={
                        "fixture_path": str(path),
                        "format": fmt,
                        "glob": glob,
                    },
                ))
    return errors


def _check_fixture_format(
    path: Path, fmt: str,
) -> tuple[int, str | None]:
    """Validate a single fixture file against its declared format.

    Returns ``(line_no, error_message)`` — ``error_message`` is
    ``None`` when the file is valid, and ``line_no`` is the offending
    line number (1-based) for line-based formats (``ndjson``) or ``1``
    for whole-document formats (``json`` / ``yaml``).

    Behaviour by format:

    * ``"ndjson"`` — each non-empty line must parse as a single JSON
      document via ``json.loads``. Blank lines (whitespace-only) are
      tolerated; the first non-empty line that fails to parse is the
      reported failure.
    * ``"json"`` — the file's full text must parse as a single JSON
      document. Failure surfaces the parser's error (and the line
      number from ``json.JSONDecodeError.lineno`` when available).
    * ``"yaml"`` — the file's full text must parse via
      ``yaml.safe_load``. Failure surfaces the PyYAML exception
      message; line numbers come from ``mark.line + 1`` when
      ``yaml.YAMLError.problem_mark`` is set, else ``1``.
    """
    import json as _json

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return 1, f"could not read as UTF-8: {exc}"

    if fmt == "ndjson":
        for idx, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                _json.loads(stripped)
            except _json.JSONDecodeError as exc:
                return idx, f"line {idx} is invalid JSON: {exc.msg}"
        return 0, None

    if fmt == "json":
        try:
            _json.loads(text)
        except _json.JSONDecodeError as exc:
            return exc.lineno or 1, f"invalid JSON: {exc.msg}"
        return 0, None

    if fmt == "yaml":
        try:
            import yaml as _yaml  # type: ignore[import-untyped]  # optional dep, no stubs; cannot add types-PyYAML (no new deps)
        except ImportError:
            return 1, (
                "PyYAML is not installed in the project environment; "
                "install pyyaml to enable yaml fixture validation"
            )
        try:
            _yaml.safe_load(text)
        except _yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            line_no = (mark.line + 1) if mark is not None else 1
            return line_no, f"invalid YAML: {exc}"
        return 0, None

    # Unknown formats are rejected at project-load time; defensive
    # fall-through here keeps the helper total.
    return 1, f"unknown fixture format: {fmt!r}"


def _resolve_output_dir(
    source_path: Path,
    input_root: Path,
    output_dir: Path | None,
) -> Path | None:
    """Compute a per-file output directory.

    M6a (feedback 5–6, ADR-007): output is a single flat layout. When
    *output_dir* is supplied, *every* transpiled module is written
    directly to ``output_dir / f"{module.name}.py"`` regardless of the
    source's position under *input_root*. Subdirectory preservation has
    been intentionally dropped — the build output is a flat Python
    package whose layout reflects module identity, not source-tree
    arrangement. When *output_dir* is ``None``, output goes alongside
    the source file (single-file transpile convenience).
    """
    if output_dir is None:
        return None
    return output_dir


def _module_collision_suggestion(
    module_name: str,
    existing_path: str,
    new_path: str,
    s0ma_project: S0maProject | None = None,
) -> str:
    """Build the M-14 (POST-10d) descriptive-suffix remediation hint.

    Returns a remediation string that names ``module_name`` and the two
    colliding files, then steers the author toward a descriptive
    suffix on one of them. When *s0ma_project* is supplied and at
    least one of the files lives under ``test_roots``, the hint also
    mentions the ``[tool.s0ma].test_module_name_prefix_by_dir`` flag
    as an opt-in alternative to a hand-rename.
    """
    suggestions: list[str] = []
    # Pick a descriptive suffix from the existing path's parent dir.
    # ``tests/unit/foo.s0ma`` → suggest ``foo_unit`` / ``unit_foo``.
    # ``src/foo.s0ma`` → fall back to ``foo_lib`` so we always have a
    # concrete suggestion to print.
    try:
        new_parent = Path(new_path).resolve().parent.name
        if new_parent and new_parent not in {"src", "tests", "."}:
            sanitized = re.sub(r"\W", "_", new_parent)
            if sanitized.isidentifier():
                suggestions.append(f"{module_name}_{sanitized}")
                suggestions.append(f"{sanitized}_{module_name}")
    except (OSError, ValueError):
        pass
    if not suggestions:
        # Conservative fallback so the hint is never empty.
        suggestions.append(f"{module_name}_lib")
        suggestions.append(f"{module_name}_test")
    suggested = " or ".join(repr(s) for s in suggestions[:2])

    base = (
        f"Rename one of the colliding modules to a descriptive variant "
        f"(e.g. {suggested}) so the project's module names stay unique."
    )

    # When the project opted out of dir-aware prefixing but a colliding
    # file lives under a test root, surface the opt-in flag as an
    # alternative to a hand-rename.
    if (
        s0ma_project is not None
        and not s0ma_project.synthetic
        and not s0ma_project.test_module_name_prefix_by_dir
    ):
        try:
            existing = Path(existing_path)
            new = Path(new_path)
            if (
                s0ma_project.is_under_test_roots(existing)
                or s0ma_project.is_under_test_roots(new)
            ):
                base += (
                    " Alternatively, set "
                    "`[tool.s0ma].test_module_name_prefix_by_dir = true` "
                    "to auto-prefix test modules by parent directory."
                )
        except (OSError, ValueError):
            pass
    return base


def _parse_single_file(
    source_path: Path,
    mode: StrictnessMode,
) -> tuple[S0maModule | None, list[S0maError]]:
    """Parse a single .s0ma file, returning (module, diagnostics).

    Uses ``parse_s0ma_with_warnings`` so that body-validation warnings
    (e.g. PROHIBITED_CONSTRUCT, BARE_IMPORT in MIGRATION/DEV mode)
    are surfaced to the caller instead of being silently discarded.
    """
    from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings

    source_text = source_path.read_text(encoding="utf-8")
    try:
        module, warnings = parse_s0ma_with_warnings(source_text, str(source_path), mode)
        return module, list(warnings)
    except S0maError as e:
        return None, [e]
    except Exception as e:
        from s0ma_dsl.errors import S0maParseError
        return None, [S0maParseError(
            code="PARSE_ERROR",
            message=f"Unexpected error while parsing: {e}",
            file=str(source_path),
            line=1,
            column=0,
            severity="error",
            remediation=(
                f"An unexpected error occurred while parsing '{source_path.name}'. "
                "Verify the file is valid UTF-8 text with correct .s0ma syntax. "
                "If the file looks correct, this may be a transpiler bug (exit code 3)."
            ),
            context={"exception_type": type(e).__name__, "exception_message": str(e)},
        )]


def _validate_single_module(
    module: S0maModule,
    source_path: Path,
    mode: StrictnessMode,
    requires_python: tuple[str, ...] | None = None,
) -> list[S0maError]:
    """Run intra-module semantic validation on a parsed module.

    M-12 (POST-8, 0.16.0): ``requires_python`` is forwarded from the
    resolved ``S0maProject`` so the
    ``PARSE_GRAMMAR_FORWARD_INCOMPAT`` pass can flag 3.12-only
    grammar against the project's declared Python floor. ``None``
    (synthetic projects or projects with no ``[project].requires-python``
    declared) suppresses the check.
    """
    from s0ma_dsl.semantic.validator import validate_module

    return list(validate_module(
        module,
        mode=mode,
        filename=str(source_path),
        requires_python=requires_python,
    ))


def _project_constant_targets(
    project_modules: dict[str, S0maModule] | None,
) -> frozenset[str] | None:
    """The canonical ids of every CONSTANT cell across the parsed project.

    ``None`` when the caller has no project view (a single-file
    transpile), in which case only a module's own constants derive READS
    edges.
    """
    if not project_modules:
        return None
    from s0ma_dsl.ast_nodes.enums import Kind

    return frozenset(
        f"{parsed.module.name}::{cell.name}"
        for parsed in project_modules.values()
        for cell in parsed.cells
        if cell.kind == Kind.CONSTANT
    )


def _analyze_derived_edges(
    module: S0maModule,
    source_path: Path,
    mode: StrictnessMode,
) -> tuple[list[DerivedEdge], list[S0maError]]:
    """Analyze derived edges (RAISES, TYPE_USES, READS, CALLS) for a module."""
    from s0ma_dsl.semantic.derived_edges import analyze_derived_edges

    derived, errors = analyze_derived_edges(
        module, mode=mode, filename=str(source_path)
    )
    return list(derived), list(errors)


def _generated_file_drift_message(py_path: Path) -> str:
    """The sentence ``build`` and ``check`` both say about a hand edit.

    One wording for both commands, true on every path: a build refuses
    to overwrite the file — cache hit or miss, source changed or not —
    until the regenerated file would carry the same body (the edit was
    moved into the source), or until ``--force`` discards the edit.
    """
    return (
        f"{py_path.as_posix()} was edited by hand; a build will not "
        f"overwrite it until the .s0ma source says the same thing. Move "
        f"changes into src/*.s0ma, or pass --force to discard them."
    )


def _check_generated_file_drift(
    s0ma_project: S0maProject | None,
) -> list[S0maError]:
    """Flag generated ``.py`` files in the build dir that were hand-edited.

    B2 (0.11.0, batch-01a): reuses the emitter's ``is_hand_edited`` — the
    same output-hash comparison the build write-guard and ``s0ma verify``
    use — so a hand edit is visible at ``s0ma check`` time, before the
    next build refuses on it. Warning severity (``check`` validates
    sources; the hard refusal to overwrite lives in ``build``). No-op for
    a synthetic project (no ``[tool.s0ma]``) or when the build dir does
    not exist yet.
    """
    if s0ma_project is None or s0ma_project.synthetic:
        return []
    build_dir = s0ma_project.build_dir
    if not build_dir.is_dir():
        return []
    from s0ma_dsl.codegen.python_emitter import is_hand_edited
    findings: list[S0maError] = []
    for py_path in iter_visible_files(build_dir, "*.py"):
        try:
            content = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if is_hand_edited(content):
            findings.append(S0maError(
                code="GENERATED_FILE_DRIFT",
                message=_generated_file_drift_message(py_path),
                file=str(py_path),
                line=1,
                column=0,
                severity="warning",
                remediation=(
                    "Move the hand edits back into the .s0ma source and "
                    "rebuild, or discard them with `s0ma build --force`. "
                    "`s0ma verify` classifies it as EDITED."
                ),
            ))
    return findings


def _published_outputs(result: CacheResult, publish_dir: Path) -> list[str]:
    """Where a cache hit's artifacts are published: the files a person imports.

    The cache keeps its own copy of every artifact under
    ``.s0ma.cache/``; what a person imports is the file of the same name
    in the directory the build writes to. The lookup has already checked
    that each of those files holds exactly the cached bytes — a hit whose
    published files were deleted, edited or replaced is a miss — so this
    only maps one path to the other.
    """
    return [
        str(publish_dir / path.name)
        for path in (result.cached_py, result.cached_ir, result.cached_map)
        if path is not None
    ]


def _transpile_single_file(
    source_path: Path,
    mode: StrictnessMode,
    output_dir: Path | None = None,
    emit_ir: bool = True,
    emit_source_map: bool = True,
    project_context: ProjectContext | None = None,
    cache: BuildCache | None = None,
    doc_hashes: DocHashIndex | None = None,
    project_modules: dict[str, S0maModule] | None = None,
    project_index: ProjectIndex | None = None,
    docs_base_dir: Path | None = None,
    requires_python: tuple[str, ...] | None = None,
    recorded_source: str | None = None,
    s0ma_project: S0maProject | None = None,
    force: bool = False,
) -> tuple[list[S0maError], list[str]]:
    """Full single-file transpile pipeline.

    Returns (all_diagnostics, output_files_written).

    If *cache* is provided, checks for a cache hit before running the
    pipeline. A hit needs an unchanged source AND published artifacts
    still byte-identical to the cache's copies; it writes nothing (bar
    replaying rendered docs) and reports the published files. On a miss
    the pipeline runs and results are stored in the cache.

    ``recorded_source`` (SH-M1, INV-5) is the portable path string to
    embed as ``source_file`` in the emitted IR and source map —
    project-root-relative POSIX when the caller resolved a project
    (see :func:`_recorded_project_path`); ``None`` keeps the legacy
    as-passed form. Diagnostics keep the as-passed invocation path
    either way.

    ``s0ma_project`` (SH-M2, INV-5) extends the same portable-path
    policy to the ``body_source_file`` an embedded ``@file()`` cell
    records in the source map: project-resolved invocations record the
    embed path project-root-relative POSIX instead of the resolved
    absolute path (which a committed build must never carry). ``None``
    keeps the legacy resolved-absolute form.
    """
    from s0ma_dsl.cache import (
        RenderedDocEntry,
        compute_embed_hashes,
        scan_embed_paths,
    )
    from s0ma_dsl.codegen.python_emitter import PythonEmitter
    from s0ma_dsl.codegen.source_map import SourceMapGenerator
    from s0ma_dsl.ir.builder import IRBuilder
    from s0ma_dsl.semantic.derived_edges import analyze_derived_edges

    all_errors: list[S0maError] = []
    output_files: list[str] = []

    # --- Cache check ---
    # M7: the cache now covers rendered .md / .html / .json outputs
    # alongside .py / .s0ma.json / .s0ma.map. The doc-key combines the
    # source hash, the doc declaration's transitive content hash, and
    # the snapshot slice the resolver consumed — see _compute_doc_cache_key.
    doc_cache_key: str | None = None
    if doc_hashes is not None:
        doc_cache_key = _compute_doc_cache_key(
            source_path, doc_hashes, project_index,
        )
    # M12 (feedback 5–6): fold any ``content: @file("path")`` embed
    # hashes into the cache key so editing an embedded file invalidates
    # the consuming module's cache. We do a lightweight pre-parse scan
    # of the source for ``@file("...")`` directives — the authoritative
    # parse runs after a cache miss and produces precise diagnostics
    # for any malformed directive.
    embed_paths = scan_embed_paths(source_path)
    embed_hashes = compute_embed_hashes(source_path, embed_paths)
    # B2 (0.11.0): --force bypasses the cache so a hand-edited generated
    # .py is actually re-emitted (a cache hit returns the on-disk file
    # untouched, which on --force would leave the discarded-then-kept
    # edit in place). Without --force the cache is consulted, and a hit
    # also requires the published artifacts to be byte-identical to the
    # cache's copies. An unchanged source used to be enough, so a hand
    # edit survived a rebuild the write-guard below refuses on every
    # other path, and the build called the module "kept". Now a published
    # file that is not what the build wrote is a miss, and the pipeline —
    # with its guard — decides, so the answer never depends on the cache.
    publish_dir = output_dir if output_dir is not None else source_path.parent
    if cache is not None and not force:
        result = cache.lookup(
            source_path,
            doc_key=doc_cache_key,
            extra_dependency_hashes=embed_hashes,
            published_dir=publish_dir,
        )
        if result.hit:
            # G3b (G1's H-9): a hit reports the file the reader can
            # import, not the copy inside `.s0ma.cache/`. The cache is
            # internal bookkeeping and is never on `sys.path`, so listing
            # its paths as this build's output read — at exactly the
            # moment somebody had just aliased a package to the build
            # directory — as though the alias pointed at a stale file.
            output_files.extend(_published_outputs(result, publish_dir))
            # Replay rendered doc outputs from the cache.
            for entry in result.cached_docs:
                entry.output_path.parent.mkdir(parents=True, exist_ok=True)
                entry.output_path.write_text(
                    entry.content, encoding="utf-8", newline="\n"
                )
                output_files.append(str(entry.output_path))
            return all_errors, output_files

    # Stage 1-2: Parse
    module, parse_errors = _parse_single_file(source_path, mode)
    all_errors.extend(parse_errors)
    if module is None:
        return all_errors, output_files

    # Stage 3: Semantic validation
    sem_errors = _validate_single_module(
        module, source_path, mode, requires_python=requires_python,
    )
    all_errors.extend(sem_errors)

    # Stage 4: Derived edge analysis. The build has every module parsed,
    # so the constants of the whole project are known and a body that
    # reads an imported constant derives a READS edge to it. A body's
    # calls to the nerves and ganglia of its own module derive CALLS
    # edges from the module alone.
    derived_edges, derived_errors = analyze_derived_edges(
        module,
        mode=mode,
        filename=str(source_path),
        constant_targets=_project_constant_targets(project_modules),
    )
    all_errors.extend(derived_errors)

    # Check for blocking errors before emission
    blocking = [e for e in all_errors if e.severity == "error"]
    if blocking:
        return all_errors, output_files

    # Determine output paths.
    #
    # M4 (feedback 5–6): output filenames are derived from the declared
    # module name, not the source file's stem. The intra-module
    # validator's MODULE_NAME_STEM_MISMATCH check guarantees the two
    # agree on any file that reaches emission, so the names are
    # equivalent in practice — but the canonical identity is the module
    # name, and the filesystem must mirror that identity (see
    # docs/adr/ADR-006-canonical-module-identity.md).
    if output_dir is not None:
        out_base = output_dir / module.module.name
    else:
        out_base = source_path.parent / module.module.name

    py_path = out_base.with_suffix(".py")
    json_path = Path(str(out_base) + ".s0ma.json")
    map_path = Path(str(out_base) + ".s0ma.map")

    # Stage 5a: Python emission
    hashes_dict: dict[tuple[str, str], str] | None = None
    if doc_hashes is not None:
        hashes_dict = doc_hashes.hashes
    emitter = PythonEmitter(
        project_context=project_context,
        mode=mode,
        filename=str(source_path),
        doc_hashes=hashes_dict,
    )
    python_output = emitter.emit(module)
    all_errors.extend(emitter.errors)
    privileged_imports = emitter.privileged_imports

    # M3 (0.13.0): annotate the emitted Python with passive ``# s0ma:``
    # source-pointer comments (one at each authored declaration's body
    # boundary, plus a module-header pointer) so an agent reading a
    # traceback line in a generated ``.py`` sees the ``.s0ma`` origin
    # without loading the ``.map``. Runs BEFORE ``inject_hashes`` so the
    # comments live inside the drift hash (a regenerated file classifies as
    # clean) and BEFORE the source map below (which is generated from this
    # annotated text — its body finders skip the pointer, so ``body_output``
    # stays anchored to the first authored body line). Uses the recorded
    # (project-root-relative POSIX) source path, matching the map's
    # ``source_file`` and never leaking an absolute path (INV-5).
    from s0ma_dsl.codegen.source_map import annotate_source_pointers

    python_output = annotate_source_pointers(
        module,
        python_output,
        source_file=(
            recorded_source
            if recorded_source is not None
            else str(source_path)
        ),
    )

    # Inject source and output hashes for drift detection (MS 5b)
    from s0ma_dsl.codegen import validate_emitted_python
    from s0ma_dsl.codegen.python_emitter import inject_hashes

    source_text = source_path.read_text(encoding="utf-8")
    python_output = inject_hashes(python_output, source_text)

    # Build invariant (M2, feedback 5–6 plan): emitted Python must parse.
    # Validate before writing so a transpiler bug raises loudly at build
    # time, not at runtime/handoff.
    validate_emitted_python(py_path, python_output)

    # B2 (0.11.0, batch-01a): refuse to silently overwrite a hand-edited
    # generated .py. If the target exists and its embedded output-hash
    # disagrees with its content, someone edited the generated file by
    # hand; overwriting it discards their change (the silent revert that
    # detonated bench run P1_P_r02). Refuse with a teaching message
    # unless --force. Files with no embedded hash (bootstrap, hand-
    # written) are never generated and never accused. And a hand edit
    # this output already carries — moved into the .s0ma source, so the
    # regenerated body is the edited body and only the hash lines differ
    # — loses nothing when overwritten, so it is written, not refused:
    # "move the change into the source, then build" is a whole recovery.
    if not force and py_path.exists():
        from s0ma_dsl.codegen.python_emitter import overwrite_loses_hand_edit
        existing_py = py_path.read_text(encoding="utf-8")
        if overwrite_loses_hand_edit(existing_py, python_output):
            all_errors.append(S0maError(
                code="GENERATED_FILE_DRIFT",
                message=_generated_file_drift_message(py_path),
                file=str(py_path),
                line=1,
                column=0,
                severity="error",
                remediation=(
                    "Move the hand edits back into the .s0ma source and "
                    "rebuild, or re-run with --force to discard the edits "
                    "and regenerate. `s0ma verify` classifies this file "
                    "as EDITED and `s0ma check` reports it as a "
                    "GENERATED_FILE_DRIFT warning."
                ),
            ))
            # Refuse: leave the hand-edited file untouched and skip this
            # module's IR/map/doc emission entirely.
            return all_errors, output_files

    # Write .py
    py_path.parent.mkdir(parents=True, exist_ok=True)
    py_path.write_text(python_output, encoding="utf-8", newline="\n")
    output_files.append(str(py_path))

    ir_json: str | None = None
    map_json: str | None = None

    # Stage 5b: IR generation
    #
    # WIN-M3: ``transpiled_file`` (and the map's ``output_file`` below)
    # reference the generated .py by basename, not by full path. The IR
    # and map are always emitted next to the .py (shared ``out_base``
    # above), so the basename is a complete, directory-independent
    # reference — and embedding the invocation path made artifact bytes
    # vary per output dir/machine (INV-5 "no absolute machine paths";
    # on Windows the escaped backslashes inside JSON also defeated every
    # replace-based path normalisation downstream).
    if emit_ir:
        ir_builder = IRBuilder(
            # SH-M1 (INV-5): project-root-relative POSIX when the
            # caller resolved a project — committed IR must be
            # byte-identical across machines/CWDs/OSes.
            source_file=(
                recorded_source
                if recorded_source is not None
                else str(source_path)
            ),
            source_text=source_text,
            transpiled_file=py_path.name,
        )
        ir_json = ir_builder.to_json(
            module,
            derived_edges=list(derived_edges),
            privileged_imports=privileged_imports,
        )
        json_path.write_text(ir_json + "\n", encoding="utf-8", newline="\n")
        output_files.append(str(json_path))

    # Stage 5c: Source map generation
    if emit_source_map:
        gen = SourceMapGenerator()
        smap = gen.generate(
            module, python_output,
            # SH-M1 (INV-5): same recorded form as the IR above.
            source_file=(
                recorded_source
                if recorded_source is not None
                else str(source_path)
            ),
            output_file=py_path.name,  # WIN-M3: basename, see IR note above
            # SH-M2 (INV-5): embedded @file() cell paths recorded
            # project-root-relative POSIX when a project resolved —
            # committed maps must be byte-identical across machines.
            embed_path_recorder=(
                lambda p: _recorded_project_path(Path(p), s0ma_project)
            ),
        )
        map_json = smap.to_json()
        map_path.write_text(map_json + "\n", encoding="utf-8", newline="\n")
        output_files.append(str(map_path))

    # Stage 5d: Doc rendering (M6) — emit Markdown/HTML/JSON output
    # files for every doc-ref / doc-guide declaration in the module.
    # Only fires when the build pipeline supplies the project-wide
    # ``doc_hashes`` index AND a project index resolved against all
    # parsed modules. Single-file transpiles without that context skip
    # rendering — the emitted ``register_doc_*`` calls still carry
    # placeholder hashes and the runtime registry can render later.
    rendered_outputs: list[str] = []
    rendered: list[RenderedOutput] = []
    if (
        doc_hashes is not None
        and project_index is not None
        and (module.doc_refs or module.doc_guides)
    ):
        from s0ma_dsl.codegen.doc_emitter import (
            DocRenderError,
            render_module_docs,
        )

        base_dir = docs_base_dir or (output_dir or source_path.parent)
        try:
            rendered = list(render_module_docs(
                module,
                index=project_index,
                hashes=doc_hashes,
                base_dir=Path(base_dir),
            ))
        except DocRenderError as exc:
            # The code and remediation ride on the exception (ADR-013 §4):
            # they default to DOC_RENDER_ERROR plus the generic hint, so
            # every historic raise site reports exactly what it did before,
            # while DOC_SOURCE_FORMAT_UNSUPPORTED reports under its own name.
            all_errors.append(S0maError(
                code=exc.code,
                message=str(exc),
                file=str(source_path),
                line=1,
                column=0,
                severity="error",
                remediation=exc.remediation or (
                    "Fix the doc declaration's format: or output: field, "
                    "or adjust the project's output directory."
                ),
            ))
            rendered = []

        for out in rendered:
            out.output_path.parent.mkdir(parents=True, exist_ok=True)
            out.output_path.write_text(out.content, encoding="utf-8", newline="\n")
            output_files.append(str(out.output_path))
            rendered_outputs.append(str(out.output_path))

    # --- Cache store ---
    if cache is not None:
        # Build doc-cache entries from whatever the renderer produced
        # this run. Storing them lets the next build replay rendered
        # outputs without invoking the renderer.
        doc_entries: tuple[RenderedDocEntry, ...] = ()
        if doc_hashes is not None and rendered:
            doc_entries = tuple(
                RenderedDocEntry(
                    decl_kind=out.decl_kind,
                    name=out.name,
                    output_path=out.output_path,
                    content=out.content,
                )
                for out in rendered
            )
        cache.store(
            source_path,
            py_content=python_output,
            ir_content=(ir_json + "\n") if ir_json is not None else None,
            map_content=(map_json + "\n") if map_json is not None else None,
            doc_key=doc_cache_key,
            docs=doc_entries,
            # M4 (feedback 5–6): cache key is the canonical module name,
            # not the source-file stem. The validator's
            # MODULE_NAME_STEM_MISMATCH check already guarantees the two
            # agree on any file that reaches this point, but we pass the
            # name explicitly so the cache derives its key from the IR's
            # canonical identity rather than re-deriving from the path.
            module_name=module.module.name,
            # M12 (feedback 5–6): pass exactly the same extra-dep hashes
            # we used at lookup time so the next build's lookup compares
            # against an identical key.
            extra_dependency_hashes=embed_hashes,
        )

    return all_errors, output_files


# ---------------------------------------------------------------------------
# Doc-cache key helper (M7 subtask 7)
# ---------------------------------------------------------------------------


def _compute_doc_cache_key(
    source_path: Path,
    doc_hashes: DocHashIndex | None,
    project_index: ProjectIndex | None,
) -> str | None:
    """Build the doc-cache invalidation key for a single .s0ma source.

    The key combines:
      a) the source .s0ma content hash (already covered by the regular
         BuildCache key, but folded in for completeness),
      b) every doc declaration in this module's transitive content hash
         from :func:`compute_doc_hashes` — drift in any reachable entity
         changes this digest, so the cache misses,
      c) a digest of the project-wide doc-index entity set so additions
         or removals to the project's nerve/cell/example surface
         invalidate every doc-bearing module's cache.

    Returns ``None`` when there is nothing to key on (no doc-hash index
    supplied) so the caller can fall back to the regular cache contract.
    """
    if doc_hashes is None:
        return None

    parts: list[str] = []
    parts.append("source")
    try:
        parts.append(hashlib.sha256(
            source_path.read_bytes()
        ).hexdigest())
    except OSError:
        # Source unreadable — caller will have surfaced this already.
        parts.append("missing")

    parts.append("hashes")
    for key in sorted(doc_hashes.hashes.keys()):
        digest = doc_hashes.hashes[key]
        parts.append(f"{key[0]}::{key[1]}={digest}")

    if project_index is not None:
        parts.append("index")
        for (kind, name) in sorted(project_index.by_kind_and_name.keys()):
            ent = project_index.by_kind_and_name[(kind, name)]
            parts.append(f"{kind}::{name}@{ent.module_name}")

    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest


# ---------------------------------------------------------------------------
# Drift detection helpers
# ---------------------------------------------------------------------------

# Regex to match the transpiler version comment in the header docstring.
# We ignore this line when comparing so that a transpiler upgrade alone
# doesn't count as drift.
_VERSION_LINE_RE = re.compile(
    r"^Auto-generated by s0ma DSL transpiler v.*$", re.MULTILINE
)

# Regex to match embedded hash comment lines (MS 5b).
# These change every transpile and should not count as drift in --check mode.
_HASH_LINE_RE = re.compile(
    r"^# s0ma-(source|output)-hash:.*$", re.MULTILINE
)


def _normalize_for_comparison(content: str) -> str:
    """Normalize file content for drift comparison.

    * Strips ``\\r`` so CRLF and LF compare equal.
    * Removes the transpiler version comment line.
    * Removes s0ma hash comment lines (MS 5b).
    """
    content = content.replace("\r", "")
    content = _VERSION_LINE_RE.sub("", content)
    content = _HASH_LINE_RE.sub("", content)
    return content


def _compare_outputs(
    temp_dir: Path,
    original_dir: Path,
    temp_outputs: list[str],
) -> list[dict[str, object]]:
    """Compare transpiled outputs in *temp_dir* against *original_dir*.

    Returns a list of per-file result dicts with keys:
    ``file``, ``status`` (``"OK"`` or ``"DRIFT"``), and optionally
    ``lines_differ`` and ``first_divergence``.

    Output-path references embedded in ``.s0ma.json`` and ``.s0ma.map``
    are normalised so that the temp-directory path is replaced with the
    original-directory path before comparison.
    """
    # Resolve to real paths so symlink-based temp dirs (e.g. macOS /var →
    # /private/var) are handled consistently.
    temp_real = str(temp_dir.resolve())
    orig_real = str(original_dir.resolve())

    results: list[dict[str, object]] = []
    for temp_path_str in temp_outputs:
        temp_path = Path(temp_path_str)
        # Compute the relative path from temp_dir
        try:
            rel = temp_path.relative_to(temp_dir)
        except ValueError:
            # temp_path might be using the resolved form
            try:
                rel = temp_path.resolve().relative_to(temp_dir.resolve())
            except ValueError:
                continue
        original_path = original_dir / rel

        entry: dict[str, object] = {"file": str(original_path)}

        if not original_path.exists():
            entry["status"] = "DRIFT"
            entry["detail"] = "(file does not exist at expected location)"
            results.append(entry)
            continue

        new_content = _normalize_for_comparison(
            temp_path.read_text(encoding="utf-8")
        )
        old_content = _normalize_for_comparison(
            original_path.read_text(encoding="utf-8")
        )

        # Normalise embedded output-path references so that path
        # differences between the temp dir and the original dir do not
        # count as drift. Each form is replaced both raw and in its
        # JSON-escaped rendering: json.dumps escapes backslashes, so on
        # Windows a path inside a JSON artifact reads ``C:\\Users\\...``
        # while the raw form never matches (WIN-M3 — the escape-blind
        # replace silently no-opped and every embedded path counted as
        # drift). On POSIX the two renderings coincide and the second
        # replace is a harmless repeat.
        for needle, repl in (
            # Resolved forms (symlink-based temp dirs, e.g. macOS
            # /var → /private/var).
            (temp_real, orig_real),
            # Non-resolved forms as passed in.
            (str(temp_dir), str(original_dir)),
        ):
            new_content = new_content.replace(needle, repl)
            new_content = new_content.replace(
                needle.replace("\\", "\\\\"),
                repl.replace("\\", "\\\\"),
            )

        if new_content == old_content:
            entry["status"] = "OK"
        else:
            new_lines = new_content.splitlines()
            old_lines = old_content.splitlines()
            differ_count = 0
            first_divergence: int | None = None
            for i, (a, b) in enumerate(
                zip(new_lines, old_lines, strict=False), start=1
            ):
                if a != b:
                    differ_count += 1
                    if first_divergence is None:
                        first_divergence = i
            # Lines present in one but not the other
            differ_count += abs(len(new_lines) - len(old_lines))
            if first_divergence is None and len(new_lines) != len(old_lines):
                first_divergence = min(len(new_lines), len(old_lines)) + 1

            entry["status"] = "DRIFT"
            entry["lines_differ"] = differ_count
            entry["first_divergence"] = first_divergence
        results.append(entry)
    return results


def _print_drift_results(
    results: list[dict[str, object]],
    file_count: int,
    quiet: bool = False,
) -> int:
    """Print drift results and return the appropriate exit code."""
    drifted = [r for r in results if r["status"] == "DRIFT"]

    if not quiet:
        print(f"Checking {file_count} module(s) for drift...")
        for r in results:
            if r["status"] == "OK":
                print(f"  OK    {r['file']}")
            else:
                detail = r.get("detail")
                if detail:
                    print(f"  DRIFT {r['file']}")
                    print(f"        {detail}")
                else:
                    ld = r.get("lines_differ", "?")
                    fd = r.get("first_divergence", "?")
                    print(f"  DRIFT {r['file']}")
                    print(f"        ({ld} lines differ; first divergence at line {fd})")
        print()

    if drifted:
        print(
            f"{len(drifted)} file(s) have drifted from their .s0ma sources."
        )
        print(
            "Run `s0ma build` without --check to overwrite, or update the .s0ma sources."
        )
        return EXIT_VALIDATION_ERROR

    if quiet:
        print(f"All {file_count} module(s) match their .s0ma sources.")
    else:
        print("All files match their .s0ma sources.")
    return EXIT_SUCCESS


# ---------------------------------------------------------------------------
# Scaffolding templates (MS 12)
# ---------------------------------------------------------------------------


def _snake_case(name: str) -> str:
    """Convert a PascalCase/camelCase *name* to snake_case.

    Handles runs of consecutive capitals (pilot01): ``CLI`` -> ``cli``,
    ``IOHandler`` -> ``io_handler``, ``HTTPServer2`` -> ``http_server2``,
    ``MyModule`` -> ``my_module``. The naive single-regex form
    (``(?<!^)(?=[A-Z])``) degraded ``CLI`` to ``c_l_i``.

    Used by every site that derives the scaffold's snake name
    (:func:`_scaffold_template` for the module header and
    ``S0maCLI._cmd_new`` for the filename) so the two stay consistent.
    """
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    return s.lower()


# Comment lines inserted at the top of scaffolded nerve bodies. Python
# comments are legal in bodies (invisible to the AST classifier); these
# teach the two body rules that kill first-time users before they ever
# hit a PARSE_ERROR: exactly one def, and imports live in the module
# header's `requires:` list, never in the body.
_BODY_RULE_COMMENT = (
    "    # Body rule: exactly ONE def below — nothing else at this level.\n"
    "    # Imports do NOT go here: declare them in the module header, e.g.\n"
    "    #   requires: [json, pathlib.Path]   (transpiler emits the imports)\n"
)


def _service_provides_nerve(name: str, layer: str) -> str:
    """The SERVICE-nerve skeleton: a factory with a structured ``provides:``.

    D3 (batch-01a): a ``kind: SERVICE`` nerve is the sanctioned
    multi-function shape — ONE ``def`` (the factory) that RETURNS a dict
    of named operations, declared up front under ``provides:``.
    Scaffolding it here teaches the fix for the factory-dict trap the
    batch reproduced (run ``P1_P_r02``): callers subscript the RETURNED
    dict, never a bare ``uses:`` module object (``mod["op"]`` is
    ``MODULE_SUBSCRIPT``). The two placeholder operations are check-clean
    in strict mode (the structured ``provides:`` names match the returned
    dict keys, so the typo check passes); rename or delete one and fill
    in the contracts.
    """
    return (
        f"nerve {name} :: {layer}\n"
        f"    kind: SERVICE\n"
        f"    visibility: PUBLIC\n"
        f'    intent: "TODO: Describe this service\'s purpose."\n'
        f'    expects: "TODO: Describe preconditions"\n'
        f'    guarantees: "TODO: Describe postconditions"\n'
        f'    forbids: "TODO: Describe what this must never do, or replace this with none"\n'
        f"    evaluates_at: FUNCTION_BOUNDARY\n"
        f"    provides:\n"
        f"      - operation_one:\n"
        f'          returns: "TODO: describe what operation_one returns"\n'
        f"      - operation_two:\n"
        f'          returns: "TODO: describe what operation_two returns"\n'
        f"    ---\n"
        f"{_BODY_RULE_COMMENT}"
        f"    def {name}():\n"
        f"        # Multi-function pattern: this SERVICE factory RETURNS a\n"
        f"        # dict of named operations. Callers subscript the RETURN\n"
        f'        # value: svc = {name}(); svc["operation_one"](). Never put\n'
        f"        # many functions in a module and subscript a bare `uses:`\n"
        f'        # module object -- `mod["op"]` raises MODULE_SUBSCRIPT.\n'
        f"        # See s0ma://guide/patterns (Real logic in modules).\n"
        f"        def operation_one():\n"
        f"            pass\n"
        f"\n"
        f"        def operation_two():\n"
        f"            pass\n"
        f"\n"
        f"        return {{\n"
        f'            "operation_one": operation_one,\n'
        f'            "operation_two": operation_two,\n'
        f"        }}\n"
    )


def _legacy_scaffold_template(
    decl_type: str,
    name: str,
    layer: str,
    kind: str | None,
) -> str:
    """Generate a .s0ma template string for the given declaration type."""
    # Convert PascalCase name to snake_case for module names
    snake_name = _snake_case(name)

    if decl_type == "module":
        header = (
            f"module {snake_name}\n"
            f"    layer: {layer}\n"
            f"    version: 0.1.0\n"
            f'    intent: "TODO: Describe this module\'s purpose."\n'
            f"    exports: [{name}]\n"
            f"    requires: []\n"
            f"    uses: []\n"
            f"\n"
        )
        # D3 (batch-01a): a SERVICE scaffolds the multi-function factory
        # skeleton (provides: + a factory returning a dict) — the
        # sanctioned answer to "I need several functions", taught at the
        # exact moment an agent reaches for the factory-dict workaround.
        if kind == "SERVICE":
            return header + _service_provides_nerve(name, layer)
        return (
            header
            + f"nerve {name} :: {layer}\n"
            f"    kind: {kind}\n"
            f"    visibility: PUBLIC\n"
            f'    intent: "TODO: Describe this nerve\'s purpose."\n'
            f'    expects: "TODO: Describe preconditions"\n'
            f'    guarantees: "TODO: Describe postconditions"\n'
            f'    forbids: "TODO: Describe what this must never do, or replace this with none"\n'
            f"    evaluates_at: FUNCTION_BOUNDARY\n"
            f"    ---\n"
            f"{_BODY_RULE_COMMENT}"
            f"    def {name}():\n"
            f"        pass\n"
        )

    if decl_type == "nerve":
        return (
            f"module {snake_name}\n"
            f"    layer: {layer}\n"
            f"    version: 0.1.0\n"
            f'    intent: "Module for {name}."\n'
            f"    exports: [{name}]\n"
            f"\n"
            f"nerve {name} :: {layer}\n"
            f"    kind: {kind}\n"
            f"    visibility: PUBLIC\n"
            f'    intent: "TODO: Describe this nerve\'s purpose."\n'
            f'    expects: "TODO: Describe preconditions"\n'
            f'    guarantees: "TODO: Describe postconditions"\n'
            f'    forbids: "TODO: Describe what this must never do, or replace this with none"\n'
            f"    evaluates_at: FUNCTION_BOUNDARY\n"
            f"    ---\n"
            f"{_BODY_RULE_COMMENT}"
            f"    def {name}():\n"
            f"        pass\n"
        )

    if decl_type == "cell":
        if kind in ("MODEL", "ENUM", "EXCEPTION", "TYPE", "CONFIG"):
            body = (
                f"    ---\n"
                f"    class {name}:\n"
                f"        pass\n"
            )
        else:
            # CONSTANT
            body = (
                f"    ---\n"
                f"    {name} = None\n"
            )

        return (
            f"module {snake_name}\n"
            f"    layer: {layer}\n"
            f"    version: 0.1.0\n"
            f'    intent: "Module for {name}."\n'
            f"    exports: [{name}]\n"
            f"\n"
            f"cell {name} :: {layer}\n"
            f"    kind: {kind}\n"
            f"    visibility: PUBLIC\n"
            f'    intent: "TODO: Describe this cell\'s purpose."\n'
            f'    schema: "TODO: Describe the structure"\n'
            + body
        )

    if decl_type == "test":
        return (
            f"module {snake_name}\n"
            f"    layer: {layer}\n"
            f"    version: 0.1.0\n"
            f'    intent: "Tests for TODO."\n'
            f"    exports: []\n"
            f"\n"
            f"test {name} :: {layer}\n"
            f'    intent: "TODO: Describe what this test verifies."\n'
            f"    tests: []\n"
            f"    ---\n"
            f"    def {name}():\n"
            f"        assert True\n"
        )

    return ""


def _scaffold_template(
    decl_type: str,
    name: str,
    layer: str,
    kind: str | None,
) -> str:
    """Generate a scaffold using only the current explicit-state grammar."""

    from s0ma_dsl.cli.migrate_grammar import current_grammar_source

    return current_grammar_source(
        _legacy_scaffold_template(decl_type, name, layer, kind),
        f"{_snake_case(name)}.s0ma",
    )


# ---------------------------------------------------------------------------
# Conftest generation (MS 12 / G5 — banner + checksum + staleness detection)
# ---------------------------------------------------------------------------
#
# G5 (feedback 5–6 cleanup) versions every generated conftest with a banner
# carrying the s0ma-dsl version and a content checksum of the body below the
# banner. ``s0ma test`` reads the banner before invoking pytest (see
# :meth:`S0maCLI._cmd_test`); any mismatch with the running s0ma-dsl version
# triggers the four-state classifier in :func:`_classify_conftest`.
#
# The version-checksum registry below records, for each released s0ma-dsl
# version, the canonical body checksum that ``s0ma test-conftest`` would have
# produced. It powers the ``untouched_stale`` branch of the classifier:
# a conftest whose banner version is older than the current version *and*
# whose body checksum matches the registered checksum for that older version
# is provably untouched and can be auto-regenerated non-destructively.
#
# **Initial state (G5 ship): the registry is empty.** No prior s0ma-dsl
# release embedded the banner (this is the first release that does), so no
# pre-G5 conftest can be classified ``untouched_stale``. Every pre-G5
# generated conftest is therefore ``unrecognized`` (no banner) →
# ``customized_stale`` (fail-safe; treated identically by the classifier),
# which surfaces ``STALE_GENERATED_CONFTEST`` and refuses to proceed. The
# fail-safe choice is deliberate: silent rewrites of files that may carry
# hidden user customizations are more harmful than a loud one-time error
# that asks the user to inspect, preserve, and run ``s0ma test-conftest
# --force``.
#
# **Future maintenance.** When a future s0ma-dsl release changes the
# generated body shape and the maintainer wants the prior version's bodies
# to auto-regenerate non-destructively, they add an entry mapping the
# *prior* version string to the SHA256 hex digest of the body that prior
# version would have produced. The mapping shape is
# ``{version_string: body_sha256_hex}``; see ``_classify_conftest`` for
# how it is consulted. We do not retroactively populate the registry for
# pre-G5 releases because the bodies those releases produced cannot be
# reconstructed deterministically (kind / layer comment lines depended on
# the consumer's project content).
# ---------------------------------------------------------------------------

STALE_GENERATED_CONFTEST_VERSION_CHECKSUMS: dict[str, str] = {
    # Empty on initial G5 release. Future versions may register entries
    # mapping a prior version string to its canonical body SHA256 here.
}


# Banner format. The banner is four comment lines at the top of the
# generated conftest; the first three are deterministic, the fourth
# carries the version and checksum used by the staleness detector.
# Order is fixed and pinned by tests so format-drift is loud.
_CONFTEST_BANNER_VERSION_PREFIX = "# Generated by s0ma-dsl "
_CONFTEST_BANNER_CHECKSUM_PREFIX = "# Content checksum: "
_CONFTEST_BANNER_NOTICE_LINE = (
    "# Do not hand-edit unless you know what you're doing."
)
_CONFTEST_BANNER_REGEN_LINE = (
    "# Run `s0ma test-conftest --force` to regenerate after upgrading s0ma-dsl."
)


def _render_conftest_body(
    kinds_used: set[str],
    layers_used: set[str],
) -> str:
    """Render the *body* of the generated conftest (no banner).

    The body is everything that follows the four banner comment lines.
    It is the input to the content checksum: the banner itself is
    excluded so re-running ``s0ma test-conftest`` against the same
    s0ma-dsl version produces a banner whose checksum line matches the
    body's actual hash, byte-for-byte. See :func:`_generate_conftest`
    for the assembly.
    """
    lines = [
        '"""Auto-generated conftest.py for s0ma project testing.',
        "",
        "Mocks the s0ma runtime so transpiled modules can be imported",
        "without a running s0ma registry.",
        "",
        "Generated by: s0ma test-conftest",
        '"""',
        "",
        "from unittest.mock import MagicMock, patch",
        "",
        "import pytest",
        "",
        "",
    ]

    # Generate kind/layer comments for reference
    if kinds_used:
        lines.append(f"# Component kinds used in project: {', '.join(sorted(kinds_used))}")
    if layers_used:
        lines.append(f"# Layers used in project: {', '.join(sorted(layers_used))}")
    if kinds_used or layers_used:
        lines.append("")
        lines.append("")

    # Generate the mock fixture
    lines.extend([
        "@pytest.fixture(autouse=True)",
        "def mock_s0ma_runtime():",
        '    """Mock the s0ma runtime to allow importing transpiled modules without a registry."""',
        "",
        "    # Create mock registration functions that pass through the decorated class/function",
        "    def mock_component(**kwargs):",
        "        def decorator(cls):",
        "            return cls",
        "        return decorator",
        "",
        "    def mock_register_module(**kwargs):",
        "        pass",
        "",
        '    with patch("s0ma.decorators.component", side_effect=mock_component):',
        '        with patch("s0ma_dsl.runtime_bridge.registration.register_module", side_effect=mock_register_module):',  # noqa: E501 — generated source-code string; splitting would alter the produced text
        "            yield",
        "",
    ])

    return "\n".join(lines) + "\n"


def _compute_conftest_body_checksum(body: str) -> str:
    """SHA256 hex digest of the conftest body (banner excluded).

    The body is the bytes :func:`_render_conftest_body` produces;
    excluding the banner makes the checksum stable across re-runs of
    ``s0ma test-conftest`` against the same s0ma-dsl version.
    """
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _render_conftest_banner(version: str, body_checksum: str) -> str:
    """Render the four-line banner that precedes the generated body.

    The banner carries the version and content checksum used by
    :func:`_classify_conftest` to distinguish current / untouched-stale /
    customized-stale states. Format is fixed; format-drift is pinned by
    ``tests/test_conftest_staleness.py``.
    """
    return (
        f"{_CONFTEST_BANNER_VERSION_PREFIX}{version}\n"
        f"{_CONFTEST_BANNER_CHECKSUM_PREFIX}{body_checksum}\n"
        f"{_CONFTEST_BANNER_NOTICE_LINE}\n"
        f"{_CONFTEST_BANNER_REGEN_LINE}\n"
    )


def _generate_conftest(
    kinds_used: set[str],
    layers_used: set[str],
) -> str:
    """Generate a conftest.py that mocks the s0ma runtime for testing.

    The returned content carries a four-line banner identifying the
    s0ma-dsl version and a SHA256 content checksum of the body below
    the banner. ``s0ma test`` reads the banner via
    :func:`_classify_conftest` before invoking pytest; banner mismatches
    surface ``STALE_GENERATED_CONFTEST`` rather than letting pytest
    discover a stale runtime contract at import time.
    """
    # Local import to avoid cycle at top of file.
    from s0ma_dsl import __version__ as _dsl_version

    body = _render_conftest_body(kinds_used, layers_used)
    checksum = _compute_conftest_body_checksum(body)
    banner = _render_conftest_banner(_dsl_version, checksum)
    return banner + body


def _collect_kinds_and_layers(
    project_dir: Path,
) -> tuple[set[str], set[str]]:
    """Walk *project_dir* and collect (kinds_used, layers_used).

    Shared by ``_cmd_test_conftest`` (write side) and ``_cmd_test``'s
    ``untouched_stale`` auto-regeneration branch (read-then-write
    side). Both surfaces need the same body content for byte-exact
    regeneration; a single helper guarantees they stay in sync.
    """
    s0ma_files = _discover_s0ma_files(str(project_dir))

    kinds_used: set[str] = set()
    layers_used: set[str] = set()

    for source_path in s0ma_files:
        module, _ = _parse_single_file(source_path, StrictnessMode.DEV)
        if module is None:
            continue
        layer_val = module.module.layer
        layers_used.add(
            layer_val.name if hasattr(layer_val, "name") else str(layer_val)
        )
        for nerve in module.nerves:
            k = nerve.kind
            kinds_used.add(k.name if hasattr(k, "name") else str(k))
        for cell in module.cells:
            k = cell.kind
            kinds_used.add(k.name if hasattr(k, "name") else str(k))

    return kinds_used, layers_used


def _parse_conftest_banner(content: str) -> tuple[str | None, str | None]:
    """Extract (version, body_checksum) from a generated-conftest banner.

    Returns ``(None, None)`` when the file does not begin with the
    G5 banner — i.e., the conftest is hand-written, predates G5, or
    has had its banner stripped. The two prefixes ``# Generated by
    s0ma-dsl `` and ``# Content checksum: `` must appear as the first
    two non-empty lines and in that order; absence of either returns
    ``(None, None)`` so the caller treats the file as ``unrecognized``
    and hands it to the fail-safe ``customized_stale`` branch.

    Pure: only string parsing. No I/O.
    """
    if not content:
        return None, None

    # Walk the leading lines until we run out of comment lines or find
    # both prefixes. A genuinely generated conftest has the version
    # line first and the checksum line second; we accept both orders
    # defensively but require both to be in the leading comment block
    # (no blank line allowed before the second).
    lines = content.splitlines()
    version: str | None = None
    checksum: str | None = None
    for line in lines:
        if line.startswith(_CONFTEST_BANNER_VERSION_PREFIX):
            version = line[len(_CONFTEST_BANNER_VERSION_PREFIX):].strip() or None
            continue
        if line.startswith(_CONFTEST_BANNER_CHECKSUM_PREFIX):
            checksum = line[len(_CONFTEST_BANNER_CHECKSUM_PREFIX):].strip() or None
            continue
        if line.startswith("#") or line == "":
            # Other banner / blank lines are fine; keep scanning.
            continue
        # First non-comment, non-blank line: end of leading comment
        # block. Stop scanning so we never falsely match comment-shaped
        # content from inside a docstring or function body.
        break

    if version is None or checksum is None:
        return None, None
    return version, checksum


def _classify_conftest(
    path: Path,
) -> str:
    """Classify a conftest at *path* into one of five staleness states.

    Returns one of:

    * ``"absent"`` — the file does not exist. No conftest in play; the
      caller (``_cmd_test``) skips the staleness check entirely and lets
      pytest run without one.
    * ``"current"`` — the banner is present and its version matches the
      running ``s0ma_dsl.__version__``. Safe to proceed; the body
      checksum is not consulted (a current-version conftest the user
      hand-edited is still valid against the current contract — the
      checksum is only load-bearing for *older*-version files where it
      distinguishes "untouched, safe to regenerate" from "customized,
      preserve").
    * ``"untouched_stale"`` — banner version mismatches but the body
      checksum matches the registered canonical checksum for that older
      version (consulted via
      :data:`STALE_GENERATED_CONFTEST_VERSION_CHECKSUMS`). The user did
      not customize, so the caller is free to auto-regenerate
      non-destructively.
    * ``"customized_stale"`` — banner version mismatches and the body
      checksum does NOT match the registered checksum for that version,
      OR the version is not in the registry at all (fail-safe path —
      see the registry comment above for why we choose fail-safe over
      fail-permissive).
    * ``"unrecognized"`` — the file exists but has no parseable banner.
      Pre-G5 generated conftests and hand-rolled files both fall here.
      The caller treats this identically to ``customized_stale``: refuse
      to proceed, instruct the user to either delete or run
      ``s0ma test-conftest --force``.

    Pure modulo a single ``Path.is_file()`` + ``Path.read_text`` against
    the conftest path; no other I/O. Easy to unit-test (the
    ``tests/test_conftest_staleness.py`` suite covers each branch).
    """
    # Local import to avoid module-level cycle.
    from s0ma_dsl import __version__ as _dsl_version

    if not path.is_file():
        return "absent"

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # An unreadable / non-UTF-8 file at the canonical conftest
        # path is structurally indistinguishable from a hand-written
        # one we can't parse. Treat as ``unrecognized`` so the
        # ``customized_stale`` branch surfaces a loud error.
        return "unrecognized"

    banner_version, banner_checksum = _parse_conftest_banner(content)
    if banner_version is None or banner_checksum is None:
        return "unrecognized"

    if banner_version == _dsl_version:
        return "current"

    # Compute the actual body's SHA256 (the body is everything below
    # the four-line banner). The classifier compares this *computed*
    # checksum — not the banner-advertised checksum — against the
    # registered older-version checksum: if a user hand-edited the
    # body, the actual checksum diverges from both the banner's claim
    # and the registered value, so the file lands in
    # ``customized_stale``. If the body matches the registered value
    # for the banner's version, the file is provably untouched (the
    # banner can't lie about a body whose hash is reproducible from
    # its bytes), so we may auto-regenerate non-destructively.
    body_actual_checksum = _compute_conftest_body_checksum(
        _strip_banner(content)
    )
    expected = STALE_GENERATED_CONFTEST_VERSION_CHECKSUMS.get(banner_version)
    if expected is not None and expected == body_actual_checksum:
        return "untouched_stale"
    return "customized_stale"


def _strip_banner(content: str) -> str:
    """Return *content* minus the leading four-line banner.

    The banner is exactly four consecutive comment lines starting at
    the top of the file: a version line, a checksum line, a notice,
    and a regeneration pointer. We drop the first four physical lines
    when those four lines all start with ``#`` and the version + checksum
    prefixes appear on lines 1 and 2 in either order; otherwise we
    return the content unchanged (the caller is responsible for
    handling the no-banner case via ``_parse_conftest_banner``).
    """
    lines = content.splitlines(keepends=True)
    if len(lines) < 4:
        return content
    head = lines[:4]
    if not all(line.startswith("#") for line in head):
        return content
    head_joined = "".join(head)
    if (
        _CONFTEST_BANNER_VERSION_PREFIX not in head_joined
        or _CONFTEST_BANNER_CHECKSUM_PREFIX not in head_joined
    ):
        return content
    return "".join(lines[4:])


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------


def _resolve_project(args: argparse.Namespace) -> S0maProject:
    """Resolve a :class:`S0maProject` for this CLI invocation.

    Discovery walks upward from ``--project-root`` (default: ``Path.cwd()``)
    until it finds a ``pyproject.toml`` containing a ``[tool.s0ma]`` table.

    If discovery fails, falls back to a synthetic project (legacy mode)
    and emits a one-line warning to stderr. Subcommands that depend on
    project metadata (e.g. ``s0ma test`` looking up ``source_roots``)
    can still operate against the synthetic defaults; commands that only
    take explicit path arguments (e.g. ``s0ma check <file>``) are
    unaffected.

    The warning is silenced when the user passed ``--format json`` so
    that machine-readable output remains clean — synthetic-mode
    consumers should inspect ``args.s0ma_project.synthetic`` directly.
    """
    start = Path(args.project_root) if args.project_root else Path.cwd()
    try:
        project = S0maProject.discover(start)
    except S0maProjectNotFound:
        project = S0maProject.synthetic_fallback(start)
        output_format = getattr(args, "output_format", "text")
        if output_format != "json":
            # DSL-M4 (F-M0-1): if the positional argument itself carries a
            # [tool.s0ma] table that CWD-anchored discovery did not resolve,
            # name it and point at --project-root — the usual cause of a
            # build that "succeeds" into the wrong layout. Only attempt this
            # when --project-root was not given (when it was, discovery
            # already started from it).
            unused_table: Path | None = None
            # Subcommands name their positional path differently: ``build``
            # uses ``project_dir`` (a single str); ``transpile``/``docs``/
            # ``examples`` use ``source`` (str); ``check`` uses ``source``
            # with ``nargs="*"`` (a list). Normalise to one path string.
            positional_raw = getattr(args, "project_dir", None) or getattr(
                args, "source", None
            )
            if isinstance(positional_raw, list):
                positional_raw = positional_raw[0] if positional_raw else None
            if not args.project_root and positional_raw:
                unused_table = S0maProject.find_unused_tool_s0ma_table(
                    positional_raw
                )
            if unused_table is not None:
                print(
                    f"warning: Operating without project discovery. A "
                    f"[tool.s0ma] table exists at {unused_table} but was not "
                    f"used — discovery anchors on the current directory, not "
                    f"the positional path. Pass `--project-root "
                    f"{unused_table.parent}` to use it.",
                    file=sys.stderr,
                )
            else:
                print(
                    "warning: Operating without project discovery. "
                    "Add `[tool.s0ma]` to pyproject.toml for full functionality.",
                    file=sys.stderr,
                )
        return project

    # Surface advisory warnings produced during discovery (e.g.
    # bootstrap files declared but not yet on disk).
    output_format = getattr(args, "output_format", "text")
    if project.warnings and output_format != "json":
        for w in project.warnings:
            print(f"warning: {w}", file=sys.stderr)
    return project


# DSL-M3 (F-M1-2): the built-in default strictness mode for each
# project-resolving subcommand, used when neither an explicit ``--mode``
# flag nor a ``[tool.s0ma].mode`` table value applies. These mirror the
# pre-0.8.0 argparse defaults EXACTLY so synthetic invocations and
# table-less projects keep their historical behaviour: ``check`` defaults
# to ``strict`` (a safety-first validation gate); ``build`` / ``transpile``
# / ``migrate-layout`` / ``topo`` / ``test`` default to ``dev``. The
# differing ``check`` vs ``build`` defaults are deliberate and are NOT
# unified by this plan. ``new`` is intentionally absent: ``s0ma new
# project`` WRITES ``[tool.s0ma].mode`` for a directory that is not a
# project yet (it self-manages resolution, so there is no project to read
# from), and keeps its own argparse ``--mode`` default.
_BUILTIN_MODE_DEFAULTS: dict[str, str] = {
    "transpile": "dev",
    "check": "strict",
    "build": "dev",
    "migrate-layout": "dev",
    "topo": "dev",
    "test": "dev",
    # STD-M8 (usability plan): ``score`` reads the gate-floor mode with the
    # same precedence (``--mode`` flag > ``[tool.s0ma].mode`` > built-in
    # default). Its built-in default is ``dev`` — the mode a project that
    # has not declared one is presumed to be developing under.
    "score": "dev",
}


def _resolve_mode(
    args: argparse.Namespace, project: S0maProject | None
) -> None:
    """Resolve ``args.mode`` for a project-resolving subcommand in place.

    DSL-M3 (F-M1-2). Precedence (highest wins):

    1. An explicit ``--mode`` flag on the command line. The relevant
       subcommand parsers default ``--mode`` to ``None`` so argparse can
       distinguish "flag omitted" (``None``) from "flag supplied" (a mode
       string) — argparse cannot otherwise tell a default-valued flag from
       an omitted one.
    2. ``[tool.s0ma].mode`` from the resolved project, when the project is
       real (not the synthetic fallback) and declares the key.
    3. The command's built-in default (:data:`_BUILTIN_MODE_DEFAULTS`).

    For subcommands not in :data:`_BUILTIN_MODE_DEFAULTS` (e.g. ``new``,
    or commands that take no ``--mode``) this is a no-op, so their
    behaviour is unchanged. After this call ``args.mode`` is always a
    concrete mode string for the project-resolving commands, which keeps
    each handler's ``StrictnessMode(args.mode)`` unchanged.
    """
    builtin = _BUILTIN_MODE_DEFAULTS.get(getattr(args, "command", None) or "")
    if builtin is None:
        return
    # An explicit flag wins over everything (precedence rule 1). With the
    # parser default of ``None``, a non-``None`` value can only have come
    # from the command line.
    if getattr(args, "mode", None) is not None:
        return
    # Otherwise: the project table (rule 2) if it declared one and is a
    # real project, else the command's built-in default (rule 3).
    table_mode = (
        project.mode
        if project is not None and not project.synthetic
        else None
    )
    args.mode = table_mode if table_mode is not None else builtin


# ---------------------------------------------------------------------------
# CLI class
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_S0maCLI",
    kind=ComponentKind.SERVICE,
    layer=Layer.FRAMEWORK,
    intent=(
        "Command-line interface for the s0ma DSL transpiler. Provides the "
        "s0ma command, whose subcommands include transpile, check, build, "
        "inspect and graph."
    ),
    idempotent=True,
    is_framework=True,
)
class S0maCLI:
    """Main CLI controller for the s0ma transpiler."""

    def build_parser(self) -> argparse.ArgumentParser:
        """Build the argparse parser with all subcommands."""
        parser = argparse.ArgumentParser(
            prog="s0ma",
            description=(
                "s0ma DSL transpiler — compiles .s0ma source files "
                "into self-describing Python."
            ),
        )
        # Global flag — applies to every subcommand. Discovery walks
        # upward from this path to find pyproject.toml + [tool.s0ma].
        # Default: cwd. See ADR-005 for the rationale.
        parser.add_argument(
            "--project-root",
            default=None,
            help=(
                "Project root to use for [tool.s0ma] discovery "
                "(default: current working directory)"
            ),
        )
        subparsers = parser.add_subparsers(dest="command", help="Available commands")

        # --- transpile ---
        tp = subparsers.add_parser(
            "transpile",
            help="Transpile .s0ma file(s) to .py + .s0ma.json + .s0ma.map",
        )
        tp.add_argument("source", help=".s0ma file or directory containing .s0ma files")
        tp.add_argument(
            "--output-dir",
            "-o",
            default=None,
            help="Output directory (default: same as source)",
        )
        tp.add_argument(
            "--mode",
            default=None,
            choices=["migration", "dev", "strict", "release"],
            help=(
                "Strictness mode. Overrides [tool.s0ma].mode when given; "
                "otherwise the project table is used, falling back to "
                "'dev' (default: [tool.s0ma].mode, else dev)"
            ),
        )
        tp.add_argument("--no-ir", action="store_true", help="Skip .s0ma.json generation")
        tp.add_argument("--no-source-map", action="store_true", help="Skip .s0ma.map generation")
        tp.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format for diagnostics (default: text)",
        )
        tp.add_argument(
            "--quiet",
            "-q",
            action="store_true",
            help="Show only errors and a one-line summary",
        )
        tp.add_argument(
            "--check",
            action="store_true",
            help="Compare transpiled output against existing files; exit 1 if drifted",
        )
        # B2 (0.11.0): mirror `build --force` — without it, transpile
        # refuses to overwrite a hand-edited generated .py.
        tp.add_argument(
            "--force",
            action="store_true",
            help=(
                "Overwrite generated .py files even when they were "
                "edited by hand (discards the edits). Without this "
                "flag transpile refuses to clobber a hand-edited "
                "generated file."
            ),
        )

        # --- check ---
        ck = subparsers.add_parser(
            "check",
            help="Validate .s0ma file(s) without generating output",
        )
        # M-11 (POST-7, 0.16.0): ``source`` accepts zero or more
        # positional paths. With no paths the command walks every
        # configured ``source_roots`` + ``test_roots`` from the
        # resolved :class:`S0maProject`. With one or more paths each
        # is processed in sequence and diagnostics are aggregated;
        # subdir inputs resolve the project context by walking
        # upward for a ``pyproject.toml`` rather than treating the
        # input itself as the project root.
        ck.add_argument(
            "source",
            nargs="*",
            help=(
                ".s0ma file(s) or director(ies) to check. With no "
                "positional argument every configured source_roots "
                "+ test_roots entry from the resolved project is "
                "checked."
            ),
        )
        ck.add_argument(
            "--mode",
            default=None,
            choices=["migration", "dev", "strict", "release"],
            help=(
                "Strictness mode. Overrides [tool.s0ma].mode when given; "
                "otherwise the project table is used, falling back to "
                "'strict' (default: [tool.s0ma].mode, else strict)"
            ),
        )
        ck.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )
        ck.add_argument(
            "--quiet",
            "-q",
            action="store_true",
            help="Show only errors and a one-line summary",
        )
        ck.add_argument(
            "--include",
            "-I",
            action="append",
            default=[],
            help="Additional directory to include for cross-module resolution. Repeatable.",
        )
        # M-17 (POST-12f, 0.16.0): ``--report-deferred`` enumerates
        # every nerve / cell / ganglion in the checked surface that
        # carries a ``deferred:`` annotation. Informational only —
        # the flag never changes the exit code (deferred bodies are
        # explicitly *not* a build blocker). Renders after the
        # standard diagnostic block so the deferred surface is visible
        # alongside any warnings/errors. The companion subcommand
        # ``s0ma deferred-surface`` provides the same report as a
        # standalone command for tooling that does not want to run
        # the full ``s0ma check`` pipeline.
        ck.add_argument(
            "--report-deferred",
            action="store_true",
            help=(
                "Enumerate every deferred:-marked nerve/cell/ganglion "
                "after the standard check report. Informational; never "
                "changes the exit code."
            ),
        )

        # --- deferred-surface ---
        # M-17 (POST-12f, 0.16.0): standalone reporter that enumerates
        # every ``deferred:`` annotation in the project. Same payload
        # as ``s0ma check --report-deferred`` but without the
        # diagnostics pass — useful in CI / pre-merge gates that want
        # the stub inventory without the wall of warnings.
        ds = subparsers.add_parser(
            "deferred-surface",
            help=(
                "List every deferred:-marked declaration in the "
                "project (POST-12f)."
            ),
        )
        ds.add_argument(
            "source",
            nargs="*",
            help=(
                ".s0ma file(s) or director(ies) to scan. With no "
                "positional argument every configured source_roots + "
                "test_roots entry from the resolved project is scanned."
            ),
        )
        ds.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )

        # --- build ---
        bd = subparsers.add_parser(
            "build",
            help="Full project build with cross-module resolution",
        )
        bd.add_argument(
            "project_dir",
            nargs="?",
            default=None,
            help=(
                "Directory holding the .s0ma sources to build. Optional: "
                "with none, this builds the project you are in — every "
                "source root and test root it declares, the same set "
                "`s0ma check` reads when it is given no paths. Each module "
                "is recorded with the role of the root its file lives "
                "under, so a test module is a test whether the build was "
                "given a path or not."
            ),
        )
        bd.add_argument(
            "--output-dir",
            "-o",
            default=None,
            help="Output directory (default: project_dir)",
        )
        bd.add_argument(
            "--mode",
            default=None,
            choices=["migration", "dev", "strict", "release"],
            help=(
                "Strictness mode. Overrides [tool.s0ma].mode when given; "
                "otherwise the project table is used, falling back to "
                "'dev' (default: [tool.s0ma].mode, else dev)"
            ),
        )
        bd.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )
        bd.add_argument(
            "--clean",
            action="store_true",
            help="Remove cached transpiler output before building",
        )
        # B2 (0.11.0): without --force the build refuses to overwrite a
        # generated .py that was edited by hand (its embedded
        # output-hash no longer matches its content) — the silent
        # revert that detonated bench run P1_P_r02. --force discards
        # such edits and regenerates.
        bd.add_argument(
            "--force",
            action="store_true",
            help=(
                "Overwrite generated .py files even when they were "
                "edited by hand (discards the edits). Without this "
                "flag the build refuses to clobber a hand-edited "
                "generated file."
            ),
        )
        # M2 (0.13.0, batch-01c): the build refuses to emit artifacts when
        # the current tree introduces NEW check-severity errors since the
        # recorded baseline (the check-red / build-green gap the CM6 crater
        # shipped through). --allow-new-errors is the deliberate escape
        # hatch — build anyway, stamp the override into the manifest. It is
        # kept SEPARATE from --force (force = discard hand-edits to a
        # generated .py; allow-new-errors = accept new contract errors).
        bd.add_argument(
            "--allow-new-errors",
            action="store_true",
            help=(
                "Build even when the current tree introduces NEW "
                "check-severity errors since the last baseline. Without "
                "this flag the build refuses and lists the new errors. "
                "Distinct from --force (which discards hand-edits to "
                "generated files)."
            ),
        )
        # A build hook runs inside a PEP 517 build environment, which holds
        # [build-system].requires and nothing else, so every third-party
        # requires: entry is MISSING_PACKAGE there and the gate above would
        # count each one as NEW against a baseline recorded where the
        # packages are installed. The caller is the one who knows that the
        # environment is the cause, so the caller says so with this flag;
        # the build then records what it could not verify instead of
        # refusing, and still refuses a new contract error. It is not an
        # override: nothing is waved through, and the manifest records the
        # packages under unverified_packages, not overridden_new_errors.
        bd.add_argument(
            "--without-runtime-packages",
            action="store_true",
            help=(
                "Say that the environment this build runs in does not hold "
                "the project's runtime packages, as a PEP 517 build "
                "environment does not. A requires: entry the build cannot "
                "find is then recorded in the build manifest as unverified "
                "instead of counted as a NEW check error; a new contract "
                "error still refuses the build. Combines with --mode dev or "
                "migration only."
            ),
        )
        bd.add_argument(
            "--no-cache",
            action="store_true",
            help="Skip cache entirely — do not read or write .s0ma.cache/",
        )
        bd.add_argument(
            "--quiet",
            "-q",
            action="store_true",
            help="Show only errors and a one-line summary",
        )
        bd.add_argument(
            "--check",
            action="store_true",
            help="Compare transpiled output against existing files; exit 1 if drifted",
        )
        bd.add_argument(
            "--include",
            "-I",
            action="append",
            default=[],
            help=(
                "Additional directory to include for cross-module "
                "resolution (not transpiled). Repeatable."
            ),
        )
        # M-16 (POST-11a, 0.16.0): when a user passes ``--output-dir``
        # that disagrees with the resolved ``[tool.s0ma].build_dir``,
        # the default behaviour refuses the override with a remediation
        # naming both paths. ``--force-output-dir`` suppresses the
        # refusal (still emits a one-line stderr notice for telemetry
        # so the override remains visible in logs).
        bd.add_argument(
            "--force-output-dir",
            action="store_true",
            help=(
                "Suppress the BUILD_DIR_OVERRIDE_CONFLICT refusal when "
                "--output-dir contradicts [tool.s0ma].build_dir. "
                "Without this flag, a conflicting --output-dir exits "
                "with EXIT_USAGE_ERROR; with it, the override proceeds "
                "and a one-line notice is emitted on stderr."
            ),
        )

        # --- migrate-layout (M6b — feedback 5–6, ADR-007) ---
        ml = subparsers.add_parser(
            "migrate-layout",
            help=(
                "One-shot migration: clean legacy __s0ma_cache__/ and "
                "per-layer subdirs from the project's build directory, "
                "then run a fresh `s0ma build`. Idempotent."
            ),
        )
        ml.add_argument(
            "project_dir",
            nargs="?",
            default=None,
            help="Optional project directory (default: resolved S0maProject root).",
        )
        ml.add_argument(
            "--mode",
            default=None,
            choices=["migration", "dev", "strict", "release"],
            help=(
                "Strictness mode for the post-migration build. Overrides "
                "[tool.s0ma].mode when given; otherwise the project table "
                "is used, falling back to 'dev' (default: [tool.s0ma].mode, "
                "else dev)"
            ),
        )
        ml.add_argument(
            "--quiet", "-q",
            action="store_true",
            help="Suppress per-step output; print only the one-line summary.",
        )

        # --- migrate-ext (s0ma consolidation M3) ---
        me = subparsers.add_parser(
            "migrate-ext",
            help=(
                "One-shot migration from the pre-2.0.0 letter-o extension "
                "family to .s0ma / .s0ma.json / .s0ma.map (build manifest "
                "build.s0ma.json): renames files, rewrites the legacy "
                "[tool.*] config table to [tool.s0ma], and removes legacy "
                "cache directories. Idempotent; refuses to overwrite "
                "existing targets."
            ),
        )
        me.add_argument(
            "project_dir",
            nargs="?",
            default=None,
            help=(
                "Optional project directory (default: resolved S0maProject "
                "root, else the current directory)."
            ),
        )
        me.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the full migration plan without changing anything.",
        )
        me.add_argument(
            "--quiet", "-q",
            action="store_true",
            help="Suppress per-item output; print only the one-line summary.",
        )

        # --- migrate grammar (0.14.0 M3A) ---
        migrate = subparsers.add_parser(
            "migrate",
            help="Plan or apply a versioned source-grammar migration.",
        )
        migrate_subs = migrate.add_subparsers(
            dest="migrate_command", help="Migration family"
        )
        grammar = migrate_subs.add_parser(
            "grammar",
            help=(
                "Materialise explicit semantic state. Dry-run by default; "
                "use --apply for an atomic whole-project rewrite."
            ),
        )
        grammar.add_argument(
            "project_dir", nargs="?", default=None,
            help="Project directory (default: resolved project root, else cwd).",
        )
        grammar.add_argument(
            "--apply", action="store_true",
            help="Apply the deterministic plan atomically (default: print only).",
        )

        # --- inspect ---
        # M16 (feedback 5–6): ``s0ma inspect`` resolves ``<target>`` in
        # this order: existing filesystem path → module name resolved
        # against ``project.build_dir`` → ``.s0ma`` source path. The
        # legacy path-based form continues to work; module-name
        # resolution is the new default for authors who think in module
        # names rather than build-output paths. ``--all`` prints a one-
        # line-per-module project survey.
        ip = subparsers.add_parser(
            "inspect",
            help="Query the self-model of a compiled module or project",
        )
        ip.add_argument(
            "target",
            nargs="?",
            default=None,
            help=(
                "Module name (resolved via project.build_dir), .s0ma.json "
                "path, .s0ma source path, or directory. Optional when "
                "--all is passed."
            ),
        )
        ip.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )
        ip.add_argument(
            "--all",
            dest="inspect_all",
            action="store_true",
            help=(
                "Print a one-line summary for every module in the "
                "project (name, layer, kind counts, total components)."
            ),
        )

        # --- score (STD-M8, usability plan) ---
        # The self-knowledge score: one visible number + a per-faculty
        # breakdown, composed from existing dsl/core surfaces (no new
        # engine; never imports s0ma-mcp — plan D-7). Report-only by
        # default; ``--gate`` exits non-zero below the caller-pinned mode's
        # floor. The score formula is recorded here (and in the
        # patterns guide "Measuring self-knowledge" section).
        sc = subparsers.add_parser(
            "score",
            help=(
                "Self-knowledge score: a single number + a three-faculty "
                "breakdown for a s0ma project (text or --format json)."
            ),
            description=(
                "Report a project's SELF-KNOWLEDGE SCORE — a single visible "
                "number plus a per-faculty breakdown, in text and "
                "--format json from the same data.\n\n"
                "FORMULA (overall = mean of the AVAILABLE faculty "
                "sub-scores; an n/a faculty is excluded from the "
                "denominator, never counted as 0 or 100):\n"
                "  proprioception (structure) = mean of: surface "
                "registration (% of built .py that is registered .s0ma vs. "
                "UNKNOWN drift, exempt files excluded), layer compliance "
                "(no CROSS_LAYER_DEPENDENCY), structural-verifier clean "
                "(no cycles/unresolved-uses/parse errors + no build drift).\n"
                "  interoception (runtime state) = n/a — no resource-profile "
                "declaration surface exists in .s0ma, so it is reported "
                "honestly as n/a rather than fabricated.\n"
                "  metacognition (reasoning) = mean of: doc-ref coverage (% "
                "PUBLIC nerves a doc-ref covers:), test coverage (% PUBLIC "
                "nerves with tests:/covered_by:), drift-free (no "
                "DRIFT_DETECTED).\n\n"
                "The exempt set is LISTED (bootstrap module, "
                "[tool.s0ma].bootstrap_files, [tool.s0ma].package_markers, "
                "@internal) so a reviewer sees exactly what sits outside "
                "s0ma. Evaluation floors: migration/dev 50%, strict 75%, "
                "release 90%. Default report-only (exit 0); --gate-mode "
                "pins caller policy, and --gate exits non-zero below that "
                "floor. No network I/O."
            ),
        )
        sc.add_argument(
            "project",
            nargs="?",
            default=".",
            help=(
                "Project directory (or any path inside it) to score "
                "(default: current directory). Discovery walks up to the "
                "[tool.s0ma] table the same way the other commands do."
            ),
        )
        sc.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )
        sc.add_argument(
            "--mode",
            default=None,
            choices=["migration", "dev", "strict", "release"],
            help=(
                "Authoring strictness for diagnostics and reporting. "
                "Overrides [tool.s0ma].mode; never selects a gate floor."
            ),
        )
        sc.add_argument(
            "--gate-mode",
            default=None,
            choices=["migration", "dev", "strict", "release"],
            help=(
                "Caller-selected evaluation policy. Without this flag the "
                "report is non-gating and gate.passes is null."
            ),
        )
        sc.add_argument(
            "--gate",
            action="store_true",
            help=(
                "Exit non-zero when the report is blocked or below the "
                "caller-pinned --gate-mode floor. Requires --gate-mode."
            ),
        )
        sc.add_argument(
            "--adoption-policy",
            default=None,
            help=(
                "Caller-supplied s0ma-adoption-policy@1 JSON path. Only "
                "this explicit input may waive matched adoption debt; "
                "[tool.s0ma].adoption_exempt is classification-only."
            ),
        )
        sc.add_argument(
            "--expected-adoption-policy-hash",
            default=None,
            help=(
                "Expected normalized sha256:<hex> for --adoption-policy; "
                "refuse before evaluation when it differs."
            ),
        )

        # --- graph ---
        # M1 (studi0 v1): `graph --format json` is THE graph export
        # contract — CLI users and the studi0 viewer read the same
        # ``s0ma-graph@2`` document (studi0 plan §3.2/§3.3). The target
        # may also be a project root (a directory whose pyproject.toml
        # carries [tool.s0ma]); its configured build_dir is scanned.
        gp = subparsers.add_parser(
            "graph",
            help="Emit dependency graph data for a module or project",
        )
        gp.add_argument(
            "target",
            help=(
                ".s0ma.json file, directory containing them, or a "
                "project root with a [tool.s0ma] table (its build_dir "
                "is scanned)"
            ),
        )
        gp.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json", "dot"],
            help="Output format (default: text)",
        )
        gp.add_argument(
            "--detail",
            default=DETAIL_SUMMARY,
            choices=list(DETAIL_LEVELS),
            help=(
                "Level of detail for --format json (default: summary). "
                "'full' adds per-component records, module records, and "
                "build freshness. Ignored by the text and dot formats, "
                "which render nodes and edges only."
            ),
        )

        # --- studi0 ---
        # M1 (studi0 v1, FR-STUDI0): a thin launcher for the optional
        # `s0ma-studi0` package. The transpiler never imports it at
        # module scope — the import happens inside the handler, so a
        # missing viewer costs nothing on every other command and
        # surfaces one actionable hint when it is actually asked for.
        sp = subparsers.add_parser(
            "studi0",
            help="Serve the studi0 viewer for a built s0ma project on loopback",
            description=(
                "Serve studi0 — the local, read-only viewer for this "
                "project's component graph — on 127.0.0.1 and open it "
                "in a browser. studi0 renders the same graph "
                "`s0ma graph --format json --detail full` emits, "
                "repainting as builds land. It reads build artifacts "
                "only: nothing is written to the project, and the "
                "target application is never executed. Requires the "
                "optional `s0ma-studi0` package."
            ),
        )
        sp.add_argument(
            "project_root",
            nargs="?",
            default=None,
            help=(
                "Root directory of the s0ma project to view "
                "(default: current working directory)"
            ),
        )
        sp.add_argument(
            "--port",
            type=int,
            default=0,
            help=(
                "Loopback port to bind (default: 0 — let the OS assign "
                "an ephemeral port; the chosen URL is printed)"
            ),
        )
        sp.add_argument(
            "--no-open",
            dest="no_open",
            action="store_true",
            help="Serve and print the URL without opening a browser",
        )

        # --- topo (M10 — feedback 5–6) ---
        # Print the project's topological module import order, one
        # module per line. Useful for debugging and for one-off scripts
        # that need the order without going through the runtime helper.
        # Walks ``.s0ma`` sources directly so the command works without
        # a prior ``s0ma build``; for already-built projects the
        # manifest's recorded order is the authoritative answer (this
        # command's output matches it byte-for-byte).
        topo_p = subparsers.add_parser(
            "topo",
            help=(
                "Print the project's topological module import order, "
                "one module per line"
            ),
        )
        topo_p.add_argument(
            "project_dir",
            help="Root directory of the s0ma project (containing .s0ma files)",
        )
        topo_p.add_argument(
            "--mode",
            default=None,
            choices=["migration", "dev", "strict", "release"],
            help=(
                "Strictness mode for the parse step. Overrides "
                "[tool.s0ma].mode when given; otherwise the project table "
                "is used, falling back to 'dev' (default: [tool.s0ma].mode, "
                "else dev)"
            ),
        )
        topo_p.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )

        # --- verify ---
        # M11 (feedback 5–6): the resolved [tool.s0ma].bootstrap_files
        # tuple is consulted to recognise declared plain-Python entry
        # points as ``BOOTSTRAP`` (informational) rather than the noisy
        # ``UNKNOWN`` they used to surface as. ``--verbose`` re-enables
        # the per-file BOOTSTRAP rows in the default text output; the
        # JSON output always includes them.
        vp = subparsers.add_parser(
            "verify",
            help="Check transpiled files for drift from .s0ma sources (fast, no transpile needed)",
            description=(
                "Check transpiled .py files for drift from their .s0ma "
                "sources using embedded checksums, and adopted files "
                "(adopted.s0ma.json) for drift from their recorded "
                "content hashes. Exit codes: 0 = verified >=1 module "
                "or adopted file, all clean; 1 = drift found "
                "(EDITED/STALE/CONFLICT/ADOPTED_DRIFT); 2 = usage "
                "error; 4 = nothing verified (the target tree contains "
                "zero transpiled s0ma modules and zero adopted files)."
            ),
        )
        vp.add_argument("target", help=".py file or directory containing transpiled files")
        vp.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )
        vp.add_argument(
            "--verbose", "-v",
            action="store_true",
            help=(
                "Show per-file rows for files declared under "
                "[tool.s0ma].bootstrap_files (status BOOTSTRAP) and "
                "for auto-detected or declared Python package markers "
                "(status PACKAGE_MARKER). Default text output hides "
                "these informational rows; JSON output always includes "
                "them."
            ),
        )
        # G1 (feedback 5–6 cleanup): ``--all`` is a synonym for
        # ``--verbose`` on verify — both opt the consumer into the
        # full informational surface (BOOTSTRAP + PACKAGE_MARKER rows
        # + the extended summary footer). Provided so the spec's
        # "surfaces under --verbose / --all" wording can be honoured
        # without forcing the user to remember which flag turns it on.
        vp.add_argument(
            "--all",
            dest="show_all",
            action="store_true",
            help=(
                "Synonym for --verbose: show every per-file row "
                "regardless of status (BOOTSTRAP + PACKAGE_MARKER "
                "informational rows are otherwise hidden in the "
                "default text output)."
            ),
        )

        # --- verify-host (0.14.0 M2) ---
        # This is intentionally separate from static ``verify``. Importing
        # application modules can perform arbitrary project-authored I/O,
        # process, or network work; callers must opt into that trust boundary.
        vhp = subparsers.add_parser(
            "verify-host",
            help=(
                "Explicitly import built production modules under the host "
                "application's Python (executes trusted project code)"
            ),
            description=(
                "DANGEROUS/EXECUTING: import each built production module "
                "in an isolated subprocess under the host application's "
                "actual Python and compare declared, installed, and emitted "
                "runtime dependencies. Project imports may perform arbitrary "
                "I/O or network calls; s0ma does not sandbox them. Host "
                "resolution is --python > [tool.s0ma].venv_path > .venv > "
                "refusal, with no fallback to s0ma's interpreter."
            ),
        )
        vhp.add_argument(
            "--python",
            default=None,
            help=(
                "Explicit host Python executable (may be external to the "
                "project); otherwise use configured/auto-detected project venv"
            ),
        )
        vhp.add_argument(
            "--gate-mode",
            default=None,
            choices=["migration", "dev", "strict", "release"],
            help=(
                "Caller-selected host gate policy. Omit for a report-only "
                "probe whose gate.passes is null."
            ),
        )
        vhp.add_argument(
            "--module-timeout",
            type=float,
            default=10.0,
            help="Per-module import timeout in seconds (default: 10)",
        )
        vhp.add_argument(
            "--timeout",
            type=float,
            default=60.0,
            help="Whole verification timeout in seconds (default: 60)",
        )
        vhp.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )

        # --- adopt <subcommand> (0.11.0, batch-01a D2; scan: B4, init: C1,
        # draft: D4; baseline and verify-parity: E2; status: E3) ---
        # Two things under one name. `adopt file <path>` is the adoption
        # primitive: it registers a real (non-generated) file into the
        # self-model by content hash. `adopt scan`, `adopt init`, `adopt
        # draft`, `adopt baseline`, `adopt verify-parity` and `adopt
        # status` are the retrofit ladder: read a plain-Python tree and
        # say what is in it and in what order to convert it (writing
        # nothing), write the perimeter that read proposed, turn one
        # module at a time into a .s0ma draft without touching the Python
        # it came from, record what that Python promised before anything
        # is deleted, compare the built module against that record, and —
        # at any moment, for somebody who has lost the thread — say which
        # rung the project is on and the one command to run now. That is
        # the whole family the retrofit plan reserved
        # (plans/s0ma-beta-prep-1-retrofit.md §5.3): a seventh
        # sub-command needs the milestone that carries its docs rulings
        # too.
        adopt_p = subparsers.add_parser(
            "adopt",
            help=(
                "Retrofit an existing codebase: `adopt scan` reads a tree "
                "and plans the conversion, `adopt init` makes it a s0ma "
                "project, `adopt draft` converts one module, `adopt "
                "baseline` and `adopt verify-parity` prove the conversion "
                "kept its promises, `adopt status` says where you are and "
                "what to run next; `adopt file <path>` registers one real "
                "(non-generated) file into the self-model"
            ),
        )
        adopt_subs = adopt_p.add_subparsers(dest="adopt_command")
        asc = adopt_subs.add_parser(
            "scan",
            help=(
                "Read an existing codebase and say what is in it and what "
                "to convert first. Writes nothing"
            ),
            description=(
                "Rung 0 of retrofitting an existing codebase. Reads a tree "
                "of plain Python and reports what is in it: how many "
                "modules and public things, the [tool.s0ma] perimeter it "
                "would declare, a leaf-first conversion order with a size "
                "band and a proposed layer for each module, anything worth "
                "knowing before you start, and the one command to run "
                "next. It never imports or runs the code it is reading, "
                "and it writes nothing anywhere — no report file, no "
                "cache — so it is safe on a codebase nobody has decided "
                "anything about yet. A file that will not parse is "
                "reported and the scan carries on."
            ),
        )
        asc.add_argument(
            "path",
            nargs="?",
            default=None,
            help=(
                "Directory to scan (default: the project root, which "
                "--project-root sets)"
            ),
        )
        asc.add_argument(
            "--source-root",
            action="append",
            default=None,
            metavar="DIR",
            help=(
                "Directory holding the application code, relative to the "
                "scanned tree. Repeatable. Default: [tool.s0ma].source_roots "
                "if the tree declares them, else src/ if it looks like a src "
                "layout, else the tree itself"
            ),
        )
        asc.add_argument(
            "--detail",
            default=None,
            metavar="MODULE",
            help=(
                "Print one module in full — what it defines, what it "
                "imports, what imports it, and why its layer was proposed"
            ),
        )
        asc.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )
        ain = adopt_subs.add_parser(
            "init",
            help=(
                "Make an existing codebase a s0ma project. Touches no "
                "application file"
            ),
            description=(
                "Rung 1 of retrofitting an existing codebase. Writes the "
                "perimeter `s0ma adopt scan` proposed — where the code "
                "lives, which files are meant to stay plain Python, which "
                "ones only mark a package, and the most forgiving "
                "strictness mode there is — as a [tool.s0ma] table "
                "appended to pyproject.toml, so the bytes already in that "
                "file stay exactly as they are; a tree with no "
                "pyproject.toml gets a minimal one. It also adds one "
                "marked block to AGENTS.md saying a retrofit is under way "
                "and where the guide is. Those two files are the only "
                "ones it may write: no starter module, no tests, no "
                "build, and not one line of application code. Afterwards "
                "`s0ma verify` calls every unconverted file UNKNOWN, "
                "which is the honest list of what is left to do."
            ),
        )
        ain.add_argument(
            "path",
            nargs="?",
            default=None,
            help=(
                "Directory to make a s0ma project (default: the project "
                "root, which --project-root sets)"
            ),
        )
        ain.add_argument(
            "--source-root",
            action="append",
            default=None,
            metavar="DIR",
            help=(
                "Directory holding the application code, relative to the "
                "tree. Repeatable. Default: the source roots `s0ma adopt "
                "scan` proposes for this tree"
            ),
        )
        ain.add_argument(
            "--dry-run",
            action="store_true",
            help="Print exactly what would be written, and write nothing",
        )
        adr = adopt_subs.add_parser(
            "draft",
            help=(
                "Turn one Python module into a .s0ma draft. The Python file "
                "is read and never changed"
            ),
            description=(
                "Rung 3 of retrofitting an existing codebase, one module at "
                "a time. Reads one Python file and writes the .s0ma draft of "
                "it: every top-level function becomes a nerve, or a helper "
                "when its name starts with an underscore; every class and "
                "every upper-case constant becomes a cell; bodies are "
                "carried across exactly as they are; imports are sorted into "
                "the header's lists. What it will not do is invent meaning. "
                "Every field that says what something is for arrives as a "
                "FIXME(adopt): line saying what belongs there, and `s0ma "
                "check` refuses the draft until a person has written them — "
                "in every mode, so a half-finished conversion cannot build "
                "green. The Python file is parsed, never imported and never "
                "run, and it is not modified, moved or deleted: it stays the "
                "code that runs until you delete it yourself, after the "
                "draft checks, builds and compares clean."
            ),
        )
        adr.add_argument(
            "module",
            metavar="MODULE_OR_FILE",
            help=(
                "The module to draft: the dotted name `s0ma adopt scan` "
                "prints (bookshelf.errors) or the path to the file "
                "(src/bookshelf/errors.py)"
            ),
        )
        adr.add_argument(
            "--layer",
            default=None,
            metavar="LAYER",
            help=(
                "The one layer this module sits at: DOMAIN, APPLICATION, "
                "INFRASTRUCTURE, PRESENTATION or FRAMEWORK. Default: the "
                "layer `s0ma adopt scan` proposes when it is confident, "
                "otherwise the draft asks you to choose"
            ),
        )
        adr.add_argument(
            "--out",
            default=None,
            metavar="DIR",
            help=(
                "Directory to write the draft into. Default: beside where "
                "the converted module will live, in the project's first "
                "source root"
            ),
        )
        adr.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the draft to the screen, and write nothing",
        )
        adr.add_argument(
            "--force",
            action="store_true",
            help="Write the draft even though a file is already in its way",
        )
        abl = adopt_subs.add_parser(
            "baseline",
            help=(
                "Record what a module's Python offers today, before you "
                "convert it — and long before you delete it"
            ),
            description=(
                "The promise that makes a conversion safe. Reads a module's "
                "Python file and writes down its public surface — every "
                "public name, how each one is called, the type each one "
                "declares, what each one says about itself — into one "
                "committed file at the project root, "
                "adopt-baseline.s0ma.json. `s0ma adopt verify-parity` then "
                "compares the module s0ma builds against that record and "
                "names every difference. Take the baseline BEFORE you "
                "delete the Python file: it is the only surviving statement "
                "of what that file promised, and once the file is gone it "
                "cannot be taken again. Commit it with your code. The "
                "Python file is parsed, never imported and never run, and "
                "it is not changed; recording a module whose file has not "
                "changed rewrites the same bytes, so a re-run diffs empty."
            ),
        )
        abl.add_argument(
            "modules",
            nargs="*",
            metavar="MODULE_OR_FILE",
            help=(
                "The modules to record: the dotted names `s0ma adopt scan` "
                "prints (bookshelf.errors) or paths to the files "
                "(src/bookshelf/errors.py)"
            ),
        )
        abl.add_argument(
            "--all",
            dest="all_modules",
            action="store_true",
            help=(
                "Record every module this project reads as application "
                "code, instead of naming them — never a test, a package "
                "marker or a file s0ma generated"
            ),
        )
        avp = adopt_subs.add_parser(
            "verify-parity",
            help=(
                "Compare a built module with the baseline taken from the "
                "Python it replaced, and name every difference"
            ),
            description=(
                "Did the conversion change anything? This reads the .py "
                "`s0ma build` wrote, compares its public surface with the "
                "baseline captured from the original Python, and reports "
                "every difference one line at a time: a name that is gone "
                "or new, a signature, a declared type, a docstring, a base "
                "class, a decorator, or a constant's value. It knows what "
                "the build adds around your code — the registration "
                "decorator, the generated header and import block, the "
                "order of __all__ — and ignores that, and only that. Exit "
                "0 when every module compared has the surface it had, 1 "
                "when anything differs, 2 when the comparison could not be "
                "made. It writes nothing anywhere, and the built module is "
                "parsed rather than imported. A clean verdict is not the "
                "end of it: run the project's own tests, which are what "
                "parity stands in for."
            ),
        )
        avp.add_argument(
            "modules",
            nargs="*",
            metavar="MODULE",
            help=(
                "The modules to compare, by the dotted name their baseline "
                "was recorded under (bookshelf.errors)"
            ),
        )
        avp.add_argument(
            "--all",
            dest="all_modules",
            action="store_true",
            help=(
                "Compare every module that has a baseline and has been "
                "built; any that are not built yet are named rather than "
                "passed over"
            ),
        )
        avp.add_argument(
            "--format",
            dest="output_format",
            choices=["text", "json"],
            default="text",
            help=(
                "Output format (default: text). json prints the verdict as "
                "an s0ma-adopt-parity@1 document: every finding with its "
                "kind, the symbol it is about, and the text before and "
                "after"
            ),
        )
        ast_ = adopt_subs.add_parser(
            "status",
            help=(
                "Where this retrofit stands, and the one command to run "
                "next. Writes nothing"
            ),
            description=(
                "The command for coming back. A retrofit is walked over "
                "days or weeks, so this answers the four questions "
                "somebody has on returning to one: which rung of the "
                "ladder the project is on, what is done, what is left, "
                "and what the single next command is. It counts the "
                "modules converted, drafted, adopted in place and still "
                "plain Python, the baselines captured and — where "
                "something has been built — what the comparison with "
                "those baselines says. Where several modules are half "
                "converted it names the one furthest along, because "
                "finishing what is started beats starting another. It "
                "writes nothing anywhere and never imports or runs the "
                "code it is reading, so it is safe at any moment. It also "
                "answers for a tree that is not a s0ma project yet: that "
                "is rung 0, and the next command is `s0ma adopt scan`."
            ),
        )
        ast_.add_argument(
            "path",
            nargs="?",
            default=None,
            help=(
                "Directory to report on (default: the project root, which "
                "--project-root sets)"
            ),
        )
        ast_.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help=(
                "Output format (default: text). json prints an "
                "s0ma-adopt-status@1 document: the rung, every count, the "
                "state of each module, and the next step as a sentence and "
                "a command"
            ),
        )
        af = adopt_subs.add_parser(
            "file",
            help=(
                "Record one pre-existing file as interim migration intake; "
                "newly-written code starts from intent with author_module"
            ),
            description=(
                "Migration intake for a pre-existing, non-generated file. "
                "This is not for code you just wrote: new code starts from "
                "intent and is authored as a .s0ma component. Records the "
                "project-root-relative path, required intent, and "
                "current content hash in adopted.s0ma.json at the "
                "project root (committed, diffable). `s0ma verify` then "
                "classifies the file ADOPTED while its content hash "
                "matches. Adoption remains roster debt and cannot answer "
                "semantic queries; componentize with author_module. "
                "Re-adoption refreshes the hash only as advisory migration "
                "telemetry, and repeated use emits ADOPTED_CHURN."
            ),
        )
        af.add_argument("path", help="File to adopt (inside the project root)")
        af.add_argument(
            "--description",
            required=True,
            help="Required non-empty one-line intent recorded with the file",
        )
        af.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )

        # --- new ---
        # UX-M3 (FR-DSL-5 v1.1): `new` scaffolds single declarations
        # (module/nerve/cell/test) AND initializes whole projects
        # (`s0ma new project <dir>`). The project path lives in
        # `cli/new_project.py` per the migrate-ext separate-module
        # precedent; the project-only options below are ignored by the
        # declaration scaffolds.
        np = subparsers.add_parser(
            "new",
            help=(
                "Scaffold a new .s0ma file from a template, or "
                "initialize a whole project (`s0ma new project <dir>`)"
            ),
        )
        np.add_argument(
            "type",
            choices=["module", "nerve", "cell", "test", "project"],
            help=(
                "Declaration type to scaffold, or 'project' to "
                "initialize a new s0ma project"
            ),
        )
        np.add_argument(
            "name",
            help=(
                "Name for the new declaration (PascalCase or "
                "snake_case); for 'project': the target directory"
            ),
        )
        np.add_argument(
            "--layer",
            default="DOMAIN",
            choices=["DOMAIN", "APPLICATION", "INFRASTRUCTURE", "PRESENTATION"],
            help="Architectural layer (default: DOMAIN)",
        )
        np.add_argument(
            "--kind",
            default=None,
            help="Component kind (default: SERVICE for nerve, MODEL for cell)",
        )
        np.add_argument(
            "--output-dir",
            "-o",
            default=".",
            help="Directory to write the generated file (default: current directory)",
        )
        np.add_argument(
            "--name",
            dest="project_name",
            default=None,
            help=(
                "('project' only) Project name for [project].name and "
                "the starter module (default: target directory basename)"
            ),
        )
        np.add_argument(
            "--mode",
            default="dev",
            choices=["migration", "dev", "strict", "release"],
            help=(
                "('project' only) [tool.s0ma].mode to declare and use "
                "for the first build (default: dev)"
            ),
        )
        np.add_argument(
            "--template",
            default=None,
            choices=["service", "library", "cli"],
            help=(
                "('project' only) Scaffold a complete archetype mini-app "
                "instead of the minimal starter: 'service' (multi-feature, "
                "cross-feature depends_on edges), 'library' (export-focused, "
                "exports + covered_by), or 'cli' (argparse.REMAINDER "
                "bootstrap shim). Default: the minimal single-feature starter."
            ),
        )
        np.add_argument(
            "--default-off",
            dest="default_off",
            action="store_true",
            help=(
                "('project' only) Write [tool.s0ma].authoring = \"off\" "
                "(default: \"on\"). The authoring posture controls the "
                "s0ma-authoring MCP server's confirmation handshake; "
                "\"off\" opts the project out of it."
            ),
        )
        np.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="('project' only) Output format (default: text)",
        )
        np.add_argument(
            "--quiet",
            "-q",
            action="store_true",
            help="('project' only) Show only the one-line summary",
        )

        # --- doctor (UX-M3, FR-DSL-5 v1.1) ---
        dct = subparsers.add_parser(
            "doctor",
            help=(
                "Environment and project health report: package "
                "versions, project detection, build freshness, MCP "
                "registration hint. Diagnoses, does not gate — exit 0 "
                "with findings; non-zero only when the environment "
                "itself is broken. License/update sections are offline "
                "placeholders in this version."
            ),
        )
        dct.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )

        # --- test (M7 — feedback 5–6, CRIT-3) ---
        # Project-aware pytest runner. ``s0ma test`` discovers the
        # project via [tool.s0ma], builds every source_root + test_root
        # to project.build_dir using the M6a single-flat layout, and
        # invokes pytest as a subprocess with:
        #
        #   * PYTHONPATH = <build_dir> (so cross-module imports resolve)
        #   * -o python_files=test_*.py *_tests.py (matches both naming
        #     conventions; addresses feedback-5.5 M01 silent miss)
        #   * pytest target = <build_dir>
        #   * args after ``--`` passed through to pytest verbatim
        #
        # The legacy positional ``test_dir`` argument is now optional
        # and accepted for backwards compatibility — when supplied, it
        # narrows the build pass to that directory but the runner still
        # discovers the project, builds source_roots first for
        # cross-module resolution, and invokes pytest the same way.
        # Args after ``--`` reach pytest unmodified — argparse's greedy
        # ``nargs="*"`` consumption of ``-o`` is gone.
        test_p = subparsers.add_parser(
            "test",
            help=(
                "Discover the project, build source + tests, run pytest "
                "(args after `--` pass through to pytest)"
            ),
        )
        test_p.add_argument(
            "test_dir",
            nargs="?",
            default=None,
            help=(
                "Optional .s0ma test directory (default: every test_root "
                "from [tool.s0ma])"
            ),
        )
        test_p.add_argument(
            "--mode",
            default=None,
            choices=["migration", "dev", "strict", "release"],
            help=(
                "Strictness mode for the build pass. Overrides "
                "[tool.s0ma].mode when given; otherwise the project table "
                "is used, falling back to 'dev' (default: [tool.s0ma].mode, "
                "else dev)"
            ),
        )
        test_p.add_argument(
            "--quiet", "-q",
            action="store_true",
            help="Suppress per-step build output; pytest output is unaffected.",
        )

        # --- test-conftest ---
        tc = subparsers.add_parser(
            "test-conftest",
            help="Generate a conftest.py that mocks the s0ma runtime for testing",
        )
        tc.add_argument(
            "--output",
            "-o",
            default="conftest.py",
            help="Output path for conftest.py (default: conftest.py)",
        )
        tc.add_argument(
            "--project",
            "-p",
            default=".",
            help="Project directory containing .s0ma files to inspect",
        )
        # G5 (feedback 5–6 cleanup): without --force the command refuses
        # to overwrite an existing file. With --force, regenerate
        # unconditionally. The default refusal is the safe behaviour
        # (mirrors `s0ma new`); --force is the documented escape hatch
        # for the "I have customizations and want a clean regeneration
        # after preserving them" flow.
        tc.add_argument(
            "--force",
            action="store_true",
            help=(
                "Overwrite an existing output file. Without this flag, "
                "test-conftest refuses to overwrite (safe default)."
            ),
        )

        # --- docs <subcommand> (M7, read surface F6) ---
        #
        # The help line is the one `s0ma --help` prints beside `docs`, and
        # arch §9.3 row 2 makes it a discovery guarantee: it has to
        # advertise `docs` as learning and reference, not only as
        # authoring-subsystem maintenance. It is also the `intent` of
        # `cli:s0ma/docs` in the composed model (the D1 provider quotes the
        # help line an author wrote), so it is written for a reader rather
        # than as a list of subcommand names.
        docs_p = subparsers.add_parser(
            "docs",
            help=(
                "Learn how s0ma works: run `s0ma docs` for the learning map, "
                "or list/show/search one topic. Also renders and gates this "
                "project's own documentation (render, verify, check-drift, "
                "compose, check)"
            ),
        )
        # Bare `s0ma docs` prints the learning map, and a program reading
        # it needs the same option every other output of this family has.
        # Declared on the group parser because the bare form *is* the
        # group parser: `s0ma docs --format json` has no subcommand to
        # carry it.
        docs_p.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format for the learning map (default: text)",
        )
        docs_subs = docs_p.add_subparsers(dest="docs_command")

        # The read surface (F6). Three subcommands, and the bare form
        # handled by _cmd_docs. None of them takes a source, a mode or a
        # project: they read a composed snapshot and compose nothing.
        dl = docs_subs.add_parser(
            "list",
            help="List every topic in one part of the documentation, or in all five",
        )
        dl.add_argument(
            "category",
            nargs="?",
            default=None,
            help="One of: understand, build, toolchain, reference, operate",
        )
        dl.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )

        ds = docs_subs.add_parser(
            "show",
            help="Show one topic in full, by its id or by a name it goes by",
        )
        ds.add_argument("topic", help="A topic id such as concept:nerve, or a name")
        ds.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )

        dsr = docs_subs.add_parser(
            "search",
            help="Find every topic a word or phrase could mean, strongest match first",
        )
        dsr.add_argument("query", nargs="+", help="What to look for")
        dsr.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )

        dr = docs_subs.add_parser(
            "render",
            help="Render every doc-ref/doc-guide to its declared output: path",
        )
        dr.add_argument("source", help=".s0ma file or directory containing .s0ma files")
        dr.add_argument(
            "--output-dir",
            "-o",
            default=None,
            help="Base directory for declared output: paths",
        )
        dr.add_argument(
            "--mode",
            default="dev",
            choices=["migration", "dev", "strict", "release"],
            help="Strictness mode (default: dev)",
        )
        dr.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Diagnostic output format (default: text)",
        )

        dv = docs_subs.add_parser(
            "verify",
            help="Run doc-subsystem validation layers without rendering",
        )
        dv.add_argument("source", help=".s0ma file or directory")
        # A8 (T1): `verify` renders in memory through the same M6 pipeline
        # as `render` / `check-drift`, so it must accept — and resolve —
        # the same output base. Without this flag verify could only see
        # the source-relative base and disagreed with its two siblings
        # about where declared `output:` paths land.
        dv.add_argument(
            "--output-dir",
            "-o",
            default=None,
            help="Base directory for declared output: paths",
        )
        dv.add_argument(
            "--mode",
            default="strict",
            choices=["migration", "dev", "strict", "release"],
            help="Strictness mode (default: strict)",
        )
        dv.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Diagnostic output format (default: text)",
        )

        dd = docs_subs.add_parser(
            "check-drift",
            help="Re-render every doc and byte-compare against committed output files",
        )
        dd.add_argument("source", help=".s0ma file or directory")
        dd.add_argument(
            "--output-dir",
            "-o",
            default=None,
            help="Base directory for declared output: paths",
        )
        dd.add_argument(
            "--mode",
            default="strict",
            choices=["migration", "dev", "strict", "release"],
            help="Strictness mode (default: strict)",
        )
        dd.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Diagnostic output format (default: text)",
        )

        # --- docs compose / docs check (C8, ADR-012) ---
        #
        # The documentation *application*, not the doc-declaration surface
        # above. These two compose the `s0ma-docs-model@1` snapshot from
        # its five providers and write / compare the declared outputs.
        # They take no positional source: nothing they read is a `.s0ma`
        # file, and a source argument they ignored would be a lie about
        # what the command does. They take no `--mode` for the same
        # reason — the model's gates report findings, and no strictness
        # mode changes whether a reference resolves.
        for name, verb in (
            ("compose", "Compose the documentation snapshot and write its declared outputs"),
            (
                "check",
                "Compose the documentation snapshot and byte-compare it against the "
                "committed outputs, writing nothing",
            ),
        ):
            dp = docs_subs.add_parser(name, help=verb)
            dp.add_argument(
                "--output-dir",
                "-o",
                default=None,
                help=(
                    "The documentation root that declared outputs resolve "
                    "against (ADR-012 §2.2). Defaults to the resolved "
                    "--project-root."
                ),
            )
            # H2b. The one input the documentation build takes about the
            # world outside its sources, and it is *stated* rather than
            # looked up: nothing in the build runs `git`, so a compose
            # cannot promote itself to a release by standing somewhere.
            # Absent — every ordinary run — composes `preview`, exactly as
            # before this flag existed.
            dp.add_argument(
                "--head-tag",
                default="",
                metavar="TAG",
                help=(
                    "The tag this commit is exactly at, as a value (the "
                    "release cut passes v<version>). Given the tag of the "
                    "version being built, the documentation composes on "
                    "the release channel; absent, or naming another "
                    "version, it composes preview. Nothing here ever "
                    "looks a tag up."
                ),
            )
            dp.add_argument(
                "--format",
                dest="output_format",
                default="text",
                choices=["text", "json"],
                help="Finding output format (default: text)",
            )

        # --- examples <subcommand> (M7) ---
        ex_p = subparsers.add_parser(
            "examples",
            help="Run registered .s0ma example declarations",
        )
        ex_subs = ex_p.add_subparsers(dest="examples_command")
        er = ex_subs.add_parser(
            "run",
            help="Run every example, or one named example",
        )
        er.add_argument("source", help=".s0ma file or directory containing example declarations")
        er.add_argument(
            "name",
            nargs="?",
            default=None,
            help="Optional example name to run (default: run all)",
        )
        er.add_argument(
            "--mode",
            default="dev",
            choices=["migration", "dev", "strict", "release"],
            help="Strictness mode (default: dev)",
        )
        er.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="Per-example timeout in seconds (default: 30)",
        )
        er.add_argument(
            "--format",
            dest="output_format",
            default="text",
            choices=["text", "json"],
            help="Output format (default: text)",
        )

        # --- feedback <subcommand> (FB-M7) ---
        # User-facing copy lives in cli/feedback_commands.py, next to the
        # commands it describes. That module imports the feedback engine
        # lazily, inside its handlers, so reading these two strings on every
        # `s0ma` invocation costs nothing but the module itself.
        from s0ma_dsl.cli.feedback_commands import (
            DEFAULT_CATEGORY,
            DEFAULT_IMPACT,
            HELP_DESCRIPTION,
            HELP_EPILOG,
        )

        fb = subparsers.add_parser(
            "feedback",
            help="Send feedback about s0ma, and manage the reports you have sent",
            description=HELP_DESCRIPTION,
            epilog=HELP_EPILOG,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        # F-1: -m is the fast path — with it, the only questions left are
        # the contact question and the one that sends. -c/-i are checked
        # against the frozen vocabulary inside the command (with a plain
        # refusal that lists the choices), not by argparse `choices=`,
        # which would answer in argparse's voice and its exit code.
        fb.add_argument(
            "-m",
            "--message",
            default=None,
            help="Your feedback in one line; with this, nothing else is asked",
        )
        fb.add_argument(
            "-c",
            "--category",
            default=None,
            metavar="CATEGORY",
            help=f"Which kind of feedback this is (default: {DEFAULT_CATEGORY})",
        )
        fb.add_argument(
            "-i",
            "--impact",
            default=None,
            metavar="IMPACT",
            help=f"How much this is affecting your work (default: {DEFAULT_IMPACT})",
        )
        fb_subs = fb.add_subparsers(dest="feedback_command")
        fb_subs.add_parser(
            "drafts",
            help="List the reports written here but not yet sent",
        )
        fb_submit = fb_subs.add_parser(
            "submit",
            help="Show a saved draft again and send it if you approve",
        )
        fb_submit.add_argument("draft_id", help="The draft id from `s0ma feedback drafts`")
        fb_subs.add_parser(
            "list",
            help="List the feedback reports you have sent",
        )
        fb_delete = fb_subs.add_parser(
            "delete",
            help="Delete one of your feedback reports, or all of them",
        )
        fb_delete.add_argument(
            "report_id",
            nargs="?",
            default=None,
            help="The report id to delete; with no id, nothing is deleted",
        )
        fb_delete.add_argument(
            "--all",
            action="store_true",
            help="Delete every one of your reports (asks for confirmation first)",
        )
        fb_enroll = fb_subs.add_parser(
            "enroll",
            help="Connect this machine to your s0ma account so it can send feedback",
        )
        fb_enroll.add_argument(
            "--key",
            default=None,
            help="Your s0ma license key (default: the S0MA_LICENSE_KEY variable)",
        )

        return parser

    # -------------------------------------------------------------------
    # Command dispatch
    # -------------------------------------------------------------------

    def run(self, argv: list[str] | None = None) -> int:
        """Parse arguments and dispatch to the appropriate command.

        Returns the exit code.

        M7 (feedback 5–6, CRIT-3): a literal ``--`` argument splits
        the input into a parsed prefix and a verbatim suffix. The
        suffix is stored on ``args.passthrough_args`` so the ``test``
        subcommand can hand it to pytest without argparse rewriting
        any flags. (Pre-M7, ``s0ma test ... -- -o python_files=...``
        had ``-o`` greedy-consumed by the test parser's own
        ``--output-dir`` short flag, producing a directory literally
        named ``python_files=...``. The split happens before
        ``parse_args`` so argparse never sees the suffix.)
        """
        if argv is None:
            argv = sys.argv[1:]
        parsed_argv: list[str]
        passthrough: list[str]
        if "--" in argv:
            sep = argv.index("--")
            parsed_argv = argv[:sep]
            passthrough = argv[sep + 1:]
        else:
            parsed_argv = list(argv)
            passthrough = []

        parser = self.build_parser()
        args = parser.parse_args(parsed_argv)
        args.passthrough_args = passthrough

        if args.command is None:
            parser.print_help()
            return EXIT_USAGE_ERROR

        # Resolve a S0maProject before dispatching. Every subcommand
        # operates against the resolved project, which provides
        # source_roots / test_roots / build_dir / bootstrap_files. See
        # ADR-005 for the rationale.
        #
        # UX-M3 (FR-DSL-5 v1.1): `doctor` and `new project` self-manage
        # resolution. `doctor` must render a malformed [tool.s0ma]
        # table as a finding (discover's ValueError would crash here,
        # pre-dispatch) and reports project absence itself; `new
        # project` targets a directory that is not a project yet, so
        # the "Operating without project discovery" warning would be
        # noise on the success path.
        #
        # FB-M7: `feedback` joins them for the same reason. It is
        # user-scoped, not project-scoped — it reads and writes ~/.s0ma
        # and never touches a build — so a project-discovery warning in
        # front of "here is the exact feedback data" would be noise the
        # reader cannot act on.
        #
        # beta-prep-1-retrofit C1: `adopt scan` and `adopt init` join them
        # for the strongest version of `new project`'s reason. Both are
        # pointed at a tree that is NOT a s0ma project — that is the whole
        # premise of rung 0 and rung 1 — so "Add `[tool.s0ma]` to
        # pyproject.toml for full functionality" is not a warning, it is
        # the thing the person is in the middle of doing, printed as the
        # first line of the answer. `adopt draft` (D4), `adopt baseline`
        # and `adopt verify-parity` (E2) deliberately do NOT join them:
        # all three run at rung 3, inside a project `adopt init` has
        # already given a [tool.s0ma] table, and each needs that table —
        # to know where a draft belongs, where the baselines file lives,
        # and where the build wrote its modules. So they take the
        # ordinary resolution, and refuse with "run `s0ma adopt init`
        # here first" when there is no project — which is the rung they
        # are really missing. `adopt status` (E3) does join them, for
        # `adopt scan`'s reason exactly: "there is no [tool.s0ma] table
        # here" is rung 0, one of the four answers the command exists to
        # give, and a warning in front of it would be that answer printed
        # twice. The rest of the family (`adopt file`, and bare `s0ma
        # adopt`) still resolves: `adopt file` writes project state and
        # refuses without a project.
        self_managed_resolution = args.command in {"doctor", "feedback"} or (
            args.command == "new" and getattr(args, "type", None) == "project"
        ) or (
            args.command == "adopt"
            and getattr(args, "adopt_command", None)
            in {"scan", "init", "status"}
        )
        args.s0ma_project = (
            None if self_managed_resolution else _resolve_project(args)
        )

        # DSL-M3 (F-M1-2): resolve the effective strictness mode now that
        # the project is known. ``--mode`` flag > ``[tool.s0ma].mode`` >
        # the command's built-in default. No-op for subcommands without a
        # table-aware mode (e.g. ``new``, which writes the key itself).
        _resolve_mode(args, args.s0ma_project)

        try:
            handler = {
                "transpile": self._cmd_transpile,
                "check": self._cmd_check,
                "build": self._cmd_build,
                "migrate-layout": self._cmd_migrate_layout,
                "migrate-ext": self._cmd_migrate_ext,
                "migrate": self._cmd_migrate,
                "doctor": self._cmd_doctor,
                "inspect": self._cmd_inspect,
                "score": self._cmd_score,
                "graph": self._cmd_graph,
                "studi0": self._cmd_studi0,
                "topo": self._cmd_topo,
                "verify": self._cmd_verify,
                "verify-host": self._cmd_verify_host,
                "adopt": self._cmd_adopt,
                "new": self._cmd_new,
                "test": self._cmd_test,
                "test-conftest": self._cmd_test_conftest,
                "docs": self._cmd_docs,
                "examples": self._cmd_examples,
                "feedback": self._cmd_feedback,
                "deferred-surface": self._cmd_deferred_surface,
            }.get(args.command)

            if handler is None:
                parser.print_help()
                return EXIT_USAGE_ERROR

            return handler(args)

        except Exception as e:
            print(f"Internal error: {e}", file=sys.stderr)
            return EXIT_INTERNAL_ERROR

    # -------------------------------------------------------------------
    # transpile
    # -------------------------------------------------------------------

    def _cmd_transpile(self, args: argparse.Namespace) -> int:
        """Transpile .s0ma file(s) to .py + .s0ma.json + .s0ma.map."""
        from s0ma_dsl.cache import BuildCache
        from s0ma_dsl.codegen.build_manifest import MANIFEST_FILENAME  # noqa: F401

        mode = StrictnessMode(args.mode)
        # M6a: --output-dir wins; otherwise fall back to the resolved
        # S0maProject.build_dir when one is configured. (Single-file
        # transpiles without --output-dir continue to emit alongside
        # the source — see _transpile_single_file.)
        explicit_output = Path(args.output_dir) if args.output_dir else None
        s0ma_project = getattr(args, "s0ma_project", None)
        if explicit_output is not None:
            output_dir = explicit_output
        elif s0ma_project is not None and not s0ma_project.synthetic:
            output_dir = s0ma_project.build_dir
        else:
            output_dir = None
        check_mode = args.check
        quiet = args.quiet
        s0ma_files = _discover_s0ma_files(args.source)

        if not s0ma_files:
            print(f"No .s0ma files found at: {args.source}", file=sys.stderr)
            return EXIT_USAGE_ERROR

        # M-12 (POST-8, 0.16.0): forward ``[project].requires-python``
        # so the validator can fire PARSE_GRAMMAR_FORWARD_INCOMPAT on
        # 3.12-only grammar inside emitted bodies before the codegen
        # step ever runs. Synthetic projects (no [tool.s0ma] table)
        # and projects without a requires-python declaration both map
        # to ``None`` — the forward-compat pass stays silent.
        transpile_requires_python = (
            s0ma_project.requires_python
            if s0ma_project is not None and not s0ma_project.synthetic
            else None
        )

        # In --check mode, transpile to a temp directory then compare
        input_root = Path(args.source)
        if check_mode:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_out = Path(tmpdir)
                all_diagnostics: list[S0maError] = []
                all_outputs: list[str] = []

                for source_path in s0ma_files:
                    file_output_dir = _resolve_output_dir(
                        source_path, input_root, tmp_out,
                    )
                    diagnostics, outputs = _transpile_single_file(
                        source_path,
                        mode=mode,
                        output_dir=file_output_dir,
                        emit_ir=not args.no_ir,
                        emit_source_map=not args.no_source_map,
                        requires_python=transpile_requires_python,
                        recorded_source=_recorded_project_path(
                            source_path, s0ma_project,
                        ),
                        s0ma_project=s0ma_project,
                    )
                    all_diagnostics.extend(diagnostics)
                    all_outputs.extend(outputs)

                if s0ma_project is not None:
                    from s0ma_dsl.host_verification import (
                        static_runtime_dependency_warning,
                    )
                    runtime_warning = static_runtime_dependency_warning(
                        s0ma_project
                    )
                    if runtime_warning is not None:
                        all_diagnostics.append(runtime_warning)

                errors = [e for e in all_diagnostics if e.severity == "error"]
                if errors:
                    _print_diagnostics(
                        all_diagnostics,
                        output_format=args.output_format,
                        files_processed=len(s0ma_files),
                        mode=args.mode,
                        quiet=quiet,
                    )
                    return EXIT_VALIDATION_ERROR

                # Determine original output location for comparison
                if output_dir:
                    original_dir = output_dir
                elif input_root.is_dir():
                    original_dir = input_root
                else:
                    original_dir = s0ma_files[0].parent
                results = _compare_outputs(tmp_out, original_dir, all_outputs)
                return _print_drift_results(
                    results, len(s0ma_files), quiet=quiet
                )

        all_diagnostics = []
        all_outputs = []

        for source_path in s0ma_files:
            file_output_dir = _resolve_output_dir(
                source_path, input_root, output_dir,
            )
            diagnostics, outputs = _transpile_single_file(
                source_path,
                mode=mode,
                output_dir=file_output_dir,
                emit_ir=not args.no_ir,
                emit_source_map=not args.no_source_map,
                requires_python=transpile_requires_python,
                recorded_source=_recorded_project_path(
                    source_path, s0ma_project,
                ),
                s0ma_project=s0ma_project,
                force=getattr(args, "force", False),
            )
            all_diagnostics.extend(diagnostics)
            all_outputs.extend(outputs)

        if s0ma_project is not None:
            from s0ma_dsl.host_verification import (
                static_runtime_dependency_warning,
            )
            runtime_warning = static_runtime_dependency_warning(s0ma_project)
            if runtime_warning is not None:
                all_diagnostics.append(runtime_warning)

        # M6a: invalidate stale incremental-cache entries for transpiled
        # files. The cache lives under ``.s0ma.cache/`` next to the
        # source; transpile-only invocations may also encounter legacy
        # ``__s0ma_cache__/`` directories from pre-M6a builds and
        # invalidate those too so the import surface stays consistent.
        cache_roots: set[Path] = set()
        for source_path in s0ma_files:
            cache_roots.add(source_path.parent / ".s0ma.cache")
            cache_roots.add(source_path.parent / "__s0ma_cache__")
        for cache_dir in cache_roots:
            if cache_dir.is_dir():
                for source_path in s0ma_files:
                    BuildCache(cache_dir=cache_dir).invalidate(source_path)

        # M6a (feedback 5–6, ADR-007): emit a single ``__init__.py`` at
        # the explicit output directory so cross-module imports work.
        # Only fires for explicit --output-dir / project.build_dir
        # invocations; single-file transpiles that emit alongside the
        # source skip this so we don't pollute the source tree.
        errors_so_far = [e for e in all_diagnostics if e.severity == "error"]
        if not errors_so_far and output_dir is not None:
            init_path = _emit_build_init(output_dir)
            if init_path is not None:
                all_outputs.append(str(init_path))

        # M6b (feedback 5–6, ADR-007): emit ``build.s0ma.json`` when
        # transpile is targeting a build directory (explicit
        # --output-dir or a resolved S0maProject.build_dir). This keeps
        # the manifest invariant in sync with the build invariant: any
        # write into a build directory carries a manifest. Single-file
        # transpiles that emit alongside the source skip this — there
        # is no build directory there.
        if not errors_so_far and output_dir is not None:
            from s0ma_dsl.cache import extract_module_name as _extract_name
            manifest_entries: list[ModuleManifestEntry] = []
            for source_path in s0ma_files:
                module_name = _extract_name(source_path)
                entry = _collect_manifest_entry(
                    module_name=module_name,
                    source_path=source_path,
                    build_dir=output_dir,
                    recorded_source=_recorded_project_path(
                        source_path, s0ma_project,
                    ),
                    recorded_logical=_recorded_logical_structure(
                        source_path, s0ma_project,
                    ),
                )
                if entry is not None:
                    manifest_entries.append(entry)

            project_name = (
                s0ma_project.project_name
                if s0ma_project is not None
                else output_dir.name
            )
            manifest_path = _emit_build_manifest(
                project_name=project_name,
                build_dir=output_dir,
                entries=manifest_entries,
                recorded_build_dir=_recorded_project_path(
                    output_dir, s0ma_project,
                ),
                emit_self_context=not args.no_ir,
            )
            if manifest_path is not None:
                all_outputs.append(str(manifest_path))

                # M-8 (POST-14, 0.15.x): companion ``build.s0ma.pyi``
                # stub. ``s0ma transpile`` produces the same flat-build
                # layout as ``s0ma build`` when ``--output-dir`` is set,
                # so the stub rides alongside the manifest here too —
                # consumer projects that bootstrap from a transpile
                # output get the same typed surface they would from a
                # full project build.
                from s0ma_dsl import __version__ as transpiler_version
                from s0ma_dsl.codegen.build_manifest import load_manifest
                from s0ma_dsl.codegen.manifest_stub_emitter import (
                    emit_manifest_stub,
                )
                stub_path = emit_manifest_stub(
                    load_manifest(output_dir),
                    output_dir,
                    transpiler_version=transpiler_version,
                )
                all_outputs.append(str(stub_path))

        # Report diagnostics
        _print_diagnostics(
            all_diagnostics,
            output_format=args.output_format,
            files_processed=len(s0ma_files),
            mode=args.mode,
            quiet=quiet,
        )

        # Report outputs
        errors, warnings = _split_diagnostics(all_diagnostics)
        if not errors and args.output_format == "text" and all_outputs:
            if quiet:
                print(
                    f"Transpiled {len(s0ma_files)} file(s). "
                    f"0 errors, {len(warnings)} warning(s)."
                )
            else:
                print(f"\nTranspiled {len(s0ma_files)} file(s). Outputs:")
                for out in all_outputs:
                    print(f"  {_display_path(out)}")

        # Info message when --output-dir differs from source directory
        if (
            not errors
            and not quiet
            and output_dir is not None
            and args.output_format == "text"
        ):
            source_dir = s0ma_files[0].parent.resolve() if s0ma_files else None
            if source_dir is not None and output_dir.resolve() != source_dir:
                print(
                    f"Info: Output written to {output_dir}. "
                    f"Ensure this path is on sys.path for imports."
                )

        return EXIT_VALIDATION_ERROR if errors else EXIT_SUCCESS

    # -------------------------------------------------------------------
    # check
    # -------------------------------------------------------------------

    def _maybe_reresolve_project_for_check(
        self,
        args: argparse.Namespace,
        source_args: list[str],
    ) -> None:
        """Re-resolve ``args.s0ma_project`` from a check-command input.

        M-11 (POST-7, 0.16.0): the global :func:`_resolve_project`
        pass keys discovery off ``args.project_root`` (default:
        ``Path.cwd()``). When ``s0ma check`` is invoked with a
        subdir path that lives inside a project — and
        ``--project-root`` was not supplied — the cwd-rooted
        resolution may yield a synthetic project even though a
        real ``pyproject.toml`` is reachable by walking upward
        from the input path. This helper re-runs
        :meth:`S0maProject.discover` from the first existing input
        path so the right project's ``[tool.s0ma]`` table governs
        the invocation. If that walk also fails, or already
        resolved to the same project root, the original
        ``args.s0ma_project`` stays.
        """
        from s0ma_dsl.errors import S0maProjectNotFound

        existing_project: S0maProject | None = getattr(
            args, "s0ma_project", None,
        )

        start: Path | None = None
        for raw in source_args:
            candidate = Path(raw)
            if candidate.exists():
                start = candidate
                break
        if start is None:
            return

        try:
            new_project = S0maProject.discover(start)
        except S0maProjectNotFound:
            return

        # Only swap when we actually found a different (or non-
        # synthetic upgrade of the prior) project. Re-resolution to
        # the exact same root is a no-op.
        if (
            existing_project is not None
            and not existing_project.synthetic
            and existing_project.root == new_project.root
        ):
            return

        args.s0ma_project = new_project
        # Surface advisory warnings the same way ``_resolve_project``
        # does so the user sees the same notice shape regardless of
        # which path triggered discovery.
        output_format = getattr(args, "output_format", "text")
        if new_project.warnings and output_format != "json":
            for w in new_project.warnings:
                print(f"warning: {w}", file=sys.stderr)

    def _record_check_baseline(
        self,
        s0ma_project: S0maProject | None,
        all_diagnostics: list[S0maError],
    ) -> DeltaReport | None:
        """Update the per-project check baseline; return this run's delta.

        Batch-01c M2 (P0). The baseline records the last run's failure
        fingerprint plus the monotone-shrinking inherited-debt **anchor**
        (0.13.0 M2 — see :mod:`s0ma_dsl.check_baseline`) under gitignored
        ``<root>/.s0ma/check-baseline.json`` so every run can label each
        failure NEW / PRE-EXISTING — closing the batch-01c CM6 gap where
        an agent falsely dismissed its own breakage as "pre-existing"
        because nothing in the check output made the claim checkable
        (and, since 0.13.0 M2, closing the second half of the same gap:
        the agent's own red ``check`` can no longer launder a NEW failure
        into PRE-EXISTING, because attribution keys on the anchor, which
        an agent's runs can only ever shrink).

        Callers own the scope guard: ONLY full-project runs may record
        (full-scope ``check`` — no positional paths — and full-root
        builds). A subset run must use
        :meth:`_classify_check_baseline` instead — recording a partial
        analysis would corrupt the last-run set and shrink the anchor on
        modules that were never re-analysed.

        Only real (non-synthetic) projects have a stable root to anchor
        the baseline; a synthetic fallback (no ``[tool.s0ma]``) records
        nothing and returns ``None``. Any I/O failure is swallowed —
        working-state bookkeeping must never break ``check`` / ``build``.
        The returned :class:`DeltaReport` is meaningful only on a failing
        run; ``check`` threads it into the formatters, ``build`` records
        and ignores it.
        """
        if s0ma_project is None or s0ma_project.synthetic:
            return None
        from s0ma_dsl.check_baseline import record_check_baseline

        try:
            return record_check_baseline(
                Path(s0ma_project.root),
                all_diagnostics,
                python_paths=self._python_file_inventory(s0ma_project),
            )
        except OSError:
            return None

    @staticmethod
    def _python_file_inventory(s0ma_project: S0maProject) -> tuple[str, ...]:
        """Current managed Python paths for the immutable first-contact anchor."""
        paths: set[str] = set()
        roots = (
            *s0ma_project.source_roots,
            *s0ma_project.test_roots,
            s0ma_project.build_dir,
        )
        for root in roots:
            if not root.is_dir():
                continue
            for path in iter_visible_files(root, "*.py"):
                try:
                    relative = path.resolve().relative_to(
                        s0ma_project.root.resolve()
                    ).as_posix()
                except (OSError, ValueError):
                    continue
                paths.add(relative)
        return tuple(sorted(paths))

    @staticmethod
    def _new_roster_diagnostics(
        s0ma_project: S0maProject | None,
    ) -> list[S0maError]:
        """Warn when code born after first contact is only roster-adopted."""
        if s0ma_project is None or s0ma_project.synthetic:
            return []
        from s0ma_dsl.adoption import AdoptedRecordError, load_adopted_files
        from s0ma_dsl.check_baseline import load_baseline_record

        record = load_baseline_record(s0ma_project.root)
        if record is None or record.python_file_anchor is None:
            return []
        try:
            adopted = load_adopted_files(s0ma_project.root)
        except AdoptedRecordError:
            return []
        diagnostics: list[S0maError] = []
        for relative, adopted_file in sorted(adopted.items()):
            if relative in record.python_file_anchor:
                continue
            path = s0ma_project.root / relative
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if (
                "# s0ma-source-hash:" in content
                and "# s0ma-output-hash:" in content
            ):
                continue
            diagnostics.append(S0maError(
                code="NEW_FILE_ROSTER_ONLY",
                message=(
                    f"{relative} first appeared after s0ma's project "
                    "baseline and is only roster-adopted; new code must "
                    "start from intent as a component."
                ),
                file=str(path),
                line=1,
                column=0,
                severity="warning",
                remediation=(
                    "Use author_module to create the canonical .s0ma "
                    "component from the recorded intent; adopt_file is "
                    "migration intake for pre-existing code, not completion."
                ),
                context={
                    "path": relative,
                    "description": adopted_file.description,
                    "gate_relevant": True,
                    "next_action": {
                        "tool": "author_module",
                        "arguments": {
                            "project_root": str(s0ma_project.root),
                            "module_name": Path(relative).stem,
                        },
                        "reason": "Componentize newly-written roster debt.",
                    },
                },
            ))
        return diagnostics

    def _classify_check_baseline(
        self,
        s0ma_project: S0maProject | None,
        all_diagnostics: list[S0maError],
    ) -> DeltaReport | None:
        """Classify against the stored anchor WITHOUT recording (M2).

        The read-only sibling of :meth:`_record_check_baseline` for
        scope-limited runs (``check <path>``): labels still render
        against the inherited-debt anchor, but nothing is written — a
        subset run analyses part of the project, and recording it would
        both corrupt the last-run set and shrink the anchor on modules
        it never re-analysed (attribution safety, spec (c): a key may
        only leave the anchor when its module was actually re-analysed
        and the failure observed absent).
        """
        if s0ma_project is None or s0ma_project.synthetic:
            return None
        from s0ma_dsl.check_baseline import classify, load_baseline_record

        try:
            record = load_baseline_record(Path(s0ma_project.root))
        except OSError:
            return None
        return classify(
            record.anchor if record is not None else None,
            all_diagnostics,
            Path(s0ma_project.root),
        )

    def _cmd_check(self, args: argparse.Namespace) -> int:
        """Validate .s0ma file(s) without generating output.

        M-11 (POST-7, 0.16.0): the positional ``source`` argument is
        ``nargs="*"`` so the command accepts zero or more paths.

        * **No paths** — discovery walks every configured
          ``source_roots`` + ``test_roots`` from the resolved
          :class:`S0maProject`. An empty configured set yields a
          friendly no-op message and exit code 0 rather than the
          legacy ``EXIT_USAGE_ERROR``.
        * **One or more paths** — each path is processed in
          sequence; diagnostics from every path are aggregated into
          one list so the user sees the union without interleaving.
          When the first input path is inside a project (i.e.
          ``pyproject.toml`` is reachable by walking upward from it)
          and ``--project-root`` was not given, the project context
          is re-resolved from the input path so the right
          ``S0maProject`` (with its ``[tool.s0ma]`` table) governs
          this invocation rather than the synthetic fallback that
          ``Path.cwd()`` would have produced.
        """
        mode = StrictnessMode(args.mode)

        # Normalize ``args.source`` to a list. With ``nargs="*"``
        # argparse already produces a list; keep the legacy single-
        # string code path forgiving for any downstream test that
        # constructs ``Namespace`` directly.
        raw_source = args.source
        if isinstance(raw_source, str):
            source_args: list[str] = [raw_source] if raw_source else []
        elif raw_source is None:
            source_args = []
        else:
            source_args = list(raw_source)

        # POST-7 sub-feature: subdir inputs resolve the project
        # context by walking up to find ``pyproject.toml`` rather
        # than treating the input as the project root. Only re-resolve
        # when ``--project-root`` was not supplied (an explicit
        # ``--project-root`` wins) and the user gave at least one
        # input path; ``s0ma check`` with no args keeps the cwd-rooted
        # resolution already performed by :func:`_resolve_project`.
        if source_args and not getattr(args, "project_root", None):
            self._maybe_reresolve_project_for_check(args, source_args)

        s0ma_project = getattr(args, "s0ma_project", None)

        # Build the list of s0ma files to check. When no positional
        # paths are supplied, walk every configured root from the
        # resolved project. When paths are supplied, walk each one in
        # sequence (preserving order). Duplicates that result from
        # overlapping inputs or roots are removed while preserving
        # first-seen order so cross-module resolution sees each
        # module exactly once.
        s0ma_files: list[Path] = []
        seen: set[Path] = set()

        def _extend_with(found: list[Path]) -> None:
            for path in found:
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                s0ma_files.append(path)

        if not source_args:
            # No positional args — check every configured root from
            # the resolved project. Synthetic projects fall back to
            # the defaults ``("src",) + ("tests",)``; both are
            # rooted at the synthetic project root.
            configured_roots: tuple[Path, ...] = ()
            if s0ma_project is not None:
                configured_roots = (
                    tuple(s0ma_project.source_roots)
                    + tuple(s0ma_project.test_roots)
                )
            if not configured_roots:
                print(
                    "No source_roots or test_roots configured; "
                    "nothing to check.",
                    file=sys.stderr,
                )
                return EXIT_SUCCESS

            any_root_existed = False
            for root in configured_roots:
                if not root.exists():
                    continue
                any_root_existed = True
                _extend_with(_discover_s0ma_files(str(root)))

            if not s0ma_files:
                if not any_root_existed:
                    print(
                        "No source_roots or test_roots exist on "
                        "disk; nothing to check.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "No .s0ma files found under configured "
                        "source_roots or test_roots.",
                        file=sys.stderr,
                    )
                return EXIT_SUCCESS
        else:
            for path_str in source_args:
                _extend_with(_discover_s0ma_files(path_str))

            if not s0ma_files:
                joined = ", ".join(repr(p) for p in source_args)
                print(
                    f"No .s0ma files found at: {joined}",
                    file=sys.stderr,
                )
                return EXIT_USAGE_ERROR

        # Discover context modules from --include paths
        context_files: list[Path] = []
        for include_path in args.include or []:
            context_files.extend(_discover_s0ma_files(str(include_path)))
        target_names: set[str] = set()

        all_diagnostics: list[S0maError] = []
        modules: dict[str, S0maModule] = {}
        module_filenames: dict[str, str] = {}

        # M-12 (POST-8, 0.16.0): resolve the project's
        # ``[project].requires-python`` once up-front so every
        # per-file ``_validate_single_module`` call forwards the
        # same range. Synthetic projects (no ``[tool.s0ma]``) and
        # projects without ``[project].requires-python`` both
        # resolve to ``None`` — the forward-compat pass stays silent.
        check_requires_python = (
            s0ma_project.requires_python
            if s0ma_project is not None and not s0ma_project.synthetic
            else None
        )

        # M-14 (POST-10d): track effective module names (with the
        # optional directory-aware prefix) for collision detection
        # only. The ``modules`` dict stays keyed by the AST-declared
        # name so cross-module resolution (``uses: [foo.bar]``) keeps
        # its contract — only the collision-check discriminator
        # changes. ``effective_to_file`` lets the diagnostic name the
        # already-seen colliding path.
        effective_to_file: dict[str, str] = {}

        # Parse and validate target files
        for source_path in s0ma_files:
            module, parse_errors = _parse_single_file(source_path, mode)
            all_diagnostics.extend(parse_errors)
            if module is None:
                continue

            declared_name = module.module.name
            effective_name = (
                s0ma_project.effective_module_name(
                    declared_name, source_path,
                )
                if s0ma_project is not None
                else declared_name
            )

            # Check for module name collision with already-seen targets
            # under the effective-name discriminator.
            if effective_name in effective_to_file:
                existing_file = effective_to_file[effective_name]
                all_diagnostics.append(S0maError(
                    code="MODULE_NAME_COLLISION",
                    message=(
                        f"Module '{declared_name}' found in both "
                        f"'{existing_file}' and "
                        f"'{source_path}'."
                    ),
                    file=str(source_path),
                    line=1,
                    column=0,
                    severity="error",
                    remediation=_module_collision_suggestion(
                        declared_name,
                        existing_file,
                        str(source_path),
                        s0ma_project,
                    ),
                ))
                continue

            sem_errors = _validate_single_module(
                module, source_path, mode,
                requires_python=check_requires_python,
            )
            all_diagnostics.extend(sem_errors)

            derived_edges, derived_errors = _analyze_derived_edges(
                module, source_path, mode
            )
            all_diagnostics.extend(derived_errors)

            modules[declared_name] = module
            module_filenames[declared_name] = str(source_path)
            effective_to_file[effective_name] = str(source_path)
            target_names.add(declared_name)

        # Parse and validate context modules (from --include)
        for source_path in context_files:
            module, parse_errors = _parse_single_file(source_path, mode)
            all_diagnostics.extend(parse_errors)
            if module is None:
                continue

            declared_name = module.module.name
            effective_name = (
                s0ma_project.effective_module_name(
                    declared_name, source_path,
                )
                if s0ma_project is not None
                else declared_name
            )

            # Check for module name collision with targets or other context
            if effective_name in effective_to_file:
                existing_file = effective_to_file[effective_name]
                all_diagnostics.append(S0maError(
                    code="MODULE_NAME_COLLISION",
                    message=(
                        f"Module '{declared_name}' found in both "
                        f"'{existing_file}' and '{source_path}'."
                    ),
                    file=str(source_path),
                    line=1,
                    column=0,
                    severity="error",
                    remediation=_module_collision_suggestion(
                        declared_name,
                        existing_file,
                        str(source_path),
                        s0ma_project,
                    ),
                ))
                continue

            sem_errors = _validate_single_module(
                module, source_path, mode,
                requires_python=check_requires_python,
            )
            all_diagnostics.extend(sem_errors)

            derived_edges, derived_errors = _analyze_derived_edges(
                module, source_path, mode
            )
            all_diagnostics.extend(derived_errors)

            modules[declared_name] = module
            module_filenames[module.module.name] = str(source_path)

        # Cross-module resolution (multiple files, or release mode)
        # M18 (feedback 5–6): always run resolution when attribute
        # budgets are configured, even for single-file invocations,
        # so the budget pass has a chance to fire.
        s0ma_project = getattr(args, "s0ma_project", None)
        attribute_budgets = (
            s0ma_project.attribute_budgets
            if s0ma_project is not None and not s0ma_project.synthetic
            else {}
        )
        # M-10 (POST-6, 0.16.0): forward project-level
        # ``test_layering`` stance so the resolver can carve out
        # test-context modules from ``CROSS_LAYER_DEPENDENCY`` when
        # the project opts in. Synthetic projects (no
        # ``[tool.s0ma]``) stay at the strict default.
        test_layering = (
            s0ma_project.test_layering
            if s0ma_project is not None and not s0ma_project.synthetic
            else "strict"
        )
        if (
            len(modules) > 1
            or mode == StrictnessMode.RELEASE
            or attribute_budgets
            or _needs_module_local_resolution(modules)
        ):
            from s0ma_dsl.resolver.dependency import resolve_dependencies
            resolution_errors = resolve_dependencies(
                modules,
                mode=mode,
                filenames=module_filenames,
                attribute_budgets=attribute_budgets,
                test_layering=test_layering,
            )
            all_diagnostics.extend(resolution_errors)

        # Doc-subsystem validation (plan M5 — wire DocValidator into pipeline)
        if modules and _has_doc_declarations(modules):
            from s0ma_dsl.semantic.doc_validator import validate_docs
            doc_errors = validate_docs(modules, filenames=module_filenames, mode=mode)
            all_diagnostics.extend(doc_errors)
        # Release-mode coverage checks (plan M7 subtask 4) run
        # unconditionally so a project that ships zero doc-refs still
        # surfaces uncovered PUBLIC nerves in release mode.
        if modules:
            from s0ma_dsl.semantic.doc_validator import check_release_doc_coverage
            all_diagnostics.extend(check_release_doc_coverage(
                modules, mode=mode, filenames=module_filenames,
            ))

        # M-18 (POST-12g, 0.16.0): validate non-``.s0ma`` fixtures
        # under ``test_roots`` against the project's declared
        # ``[tool.s0ma].fixtures_format`` map. Synthetic projects (no
        # ``[tool.s0ma]``) and projects without ``fixtures_format``
        # configured both no-op silently.
        if (
            s0ma_project is not None
            and not s0ma_project.synthetic
            and s0ma_project.fixtures_format
        ):
            all_diagnostics.extend(_validate_fixtures_format(
                s0ma_project.test_roots,
                s0ma_project.fixtures_format,
                mode,
            ))

        # B2 (0.11.0, batch-01a): surface generated .py files in the
        # build dir that were hand-edited since transpilation, before the
        # next build silently overwrites them (the revert that detonated
        # bench run P1_P_r02). Warning-only here — `check` validates
        # sources; the hard refusal to overwrite lives in `build`.
        all_diagnostics.extend(_check_generated_file_drift(s0ma_project))

        # 0.14 M4: first-contact inventory distinguishes brownfield migration
        # from code created after s0ma already knew the checkout. Advisory in
        # authoring output; pinned score policy supplies the reproducible gate.
        all_diagnostics.extend(self._new_roster_diagnostics(s0ma_project))

        # M2 (batch-01c): attribute this run's failures against the
        # project's inherited-debt anchor, so failures render with NEW /
        # PRE-EXISTING labels (the CM6 gap). Computed BEFORE printing.
        # Scope guard (0.13.0 M2): only a FULL-project check (no
        # positional paths) records the baseline — a subset run
        # (`check src/foo.s0ma`) classifies read-only, because recording
        # a partial analysis would corrupt the last-run set and shrink
        # the anchor on modules it never re-analysed.
        if source_args:
            delta = self._classify_check_baseline(
                s0ma_project, all_diagnostics,
            )
        else:
            delta = self._record_check_baseline(s0ma_project, all_diagnostics)

        # Report
        quiet = args.quiet
        _print_diagnostics(
            all_diagnostics,
            output_format=args.output_format,
            files_processed=len(s0ma_files),
            mode=args.mode,
            quiet=quiet,
            delta=delta,
        )

        errors, warnings = _split_diagnostics(all_diagnostics)
        if not errors and args.output_format == "text":
            if quiet:
                print(f"Checked {len(s0ma_files)} file(s). 0 errors, {len(warnings)} warning(s).")
            else:
                print(f"\n{len(s0ma_files)} file(s) checked. No errors.")

        # M-17 (POST-12f, 0.16.0): when ``--report-deferred`` is set,
        # enumerate every deferred-marked declaration across the
        # checked modules. This is informational only — the report
        # never raises the exit code (the goal is visibility on the
        # project's stub surface, not a build gate). Renders after
        # the standard diagnostic block so the deferred surface is
        # visible alongside any warnings/errors.
        if getattr(args, "report_deferred", False):
            self._render_deferred_surface(
                modules, module_filenames,
                output_format=args.output_format,
            )

        return EXIT_VALIDATION_ERROR if errors else EXIT_SUCCESS

    # -------------------------------------------------------------------
    # deferred-surface (POST-12f, 0.16.0)
    # -------------------------------------------------------------------

    def _cmd_deferred_surface(self, args: argparse.Namespace) -> int:
        """Enumerate every deferred:-marked declaration in the project.

        Standalone reporter for the POST-12f deferred-surface feature.
        Same payload as ``s0ma check --report-deferred`` but without
        the diagnostics pass. Always exits 0 — the report is
        informational; deferred bodies are explicitly *not* a build
        blocker.
        """
        raw_source = args.source
        if isinstance(raw_source, str):
            source_args: list[str] = [raw_source] if raw_source else []
        elif raw_source is None:
            source_args = []
        else:
            source_args = list(raw_source)

        if source_args and not getattr(args, "project_root", None):
            self._maybe_reresolve_project_for_check(args, source_args)

        s0ma_project = getattr(args, "s0ma_project", None)

        s0ma_files: list[Path] = []
        seen: set[Path] = set()

        def _extend_with(found: list[Path]) -> None:
            for path in found:
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                s0ma_files.append(path)

        if not source_args:
            configured_roots: tuple[Path, ...] = ()
            if s0ma_project is not None:
                configured_roots = (
                    tuple(s0ma_project.source_roots)
                    + tuple(s0ma_project.test_roots)
                )
            for root in configured_roots:
                if root.exists():
                    _extend_with(_discover_s0ma_files(str(root)))
        else:
            for path_str in source_args:
                _extend_with(_discover_s0ma_files(path_str))

        # Parse every discovered file in non-strict mode (we only
        # care about deferred annotations; strict-mode diagnostics
        # are out of scope for this reporter).
        modules: dict[str, S0maModule] = {}
        module_filenames: dict[str, str] = {}
        for source_path in s0ma_files:
            module, _parse_errors = _parse_single_file(
                source_path, StrictnessMode.DEV,
            )
            if module is None:
                continue
            declared_name = module.module.name
            modules[declared_name] = module
            module_filenames[declared_name] = str(source_path)

        self._render_deferred_surface(
            modules, module_filenames,
            output_format=args.output_format,
        )
        return EXIT_SUCCESS

    def _render_deferred_surface(
        self,
        modules: dict[str, S0maModule],
        module_filenames: dict[str, str],
        *,
        output_format: str,
    ) -> None:
        """Render the deferred-surface report.

        Used by both ``s0ma check --report-deferred`` and the
        standalone ``s0ma deferred-surface`` subcommand. Aggregates
        every ``deferred:``-marked nerve / cell / ganglion across the
        supplied modules and renders the surface either as a
        human-readable text block or as a JSON envelope keyed by
        ``"deferred"`` (with one entry per declaration).
        """
        entries: list[dict[str, object]] = []
        for module_name in sorted(modules.keys()):
            module = modules[module_name]
            source_file = module_filenames.get(module_name, "<unknown>")
            # Nerves
            for nerve in module.nerves:
                if nerve.deferred is not None:
                    entries.append({
                        "module": module_name,
                        "declaration_type": "nerve",
                        "name": nerve.name,
                        "reason": nerve.deferred,
                        "file": source_file,
                        "line": (
                            nerve.location.start_line
                            if nerve.location is not None
                            else 0
                        ),
                    })
            # Cells
            for cell in module.cells:
                if cell.deferred is not None:
                    entries.append({
                        "module": module_name,
                        "declaration_type": "cell",
                        "name": cell.name,
                        "reason": cell.deferred,
                        "file": source_file,
                        "line": (
                            cell.location.start_line
                            if cell.location is not None
                            else 0
                        ),
                    })
            # Ganglia
            for ganglion in module.ganglia:
                if ganglion.deferred is not None:
                    entries.append({
                        "module": module_name,
                        "declaration_type": "ganglion",
                        "name": ganglion.name,
                        "reason": ganglion.deferred,
                        "file": source_file,
                        "line": (
                            ganglion.location.start_line
                            if ganglion.location is not None
                            else 0
                        ),
                    })

        if output_format == "json":
            import json as _json
            print(_json.dumps({"deferred": entries}, indent=2))
            return

        # Text output
        print()
        if not entries:
            print("Deferred surface: no deferred:-marked declarations found.")
            return
        print(f"Deferred surface ({len(entries)} declaration(s)):")
        for entry in entries:
            print(
                f"  {entry['module']}::{entry['name']} "
                f"[{entry['declaration_type']}]"
            )
            print(f"    reason: {entry['reason']}")
            print(f"    at: {entry['file']}:{entry['line']}")

    # -------------------------------------------------------------------
    # build
    # -------------------------------------------------------------------

    _BUILD_GATE_RULE = (
        "new check errors block builds; fix them or pass "
        "allow_new_errors=true with a reason."
    )
    """The one-line rule the build refusal leads with (spec (a)).

    Kept SEPARATE from the ``GENERATED_FILE_DRIFT`` / ``--force`` refusal
    (0.11.0 M1): ``--force`` discards hand-edits to a generated ``.py``;
    ``--allow-new-errors`` accepts *new contract errors*. The two flags
    are never conflated (spec (d))."""

    def _emit_build_refusal(
        self,
        *,
        new_errors: list[S0maError],
        delta: DeltaReport,
        output_format: str,
        files_processed: int,
        mode: str | None,
        quiet: bool,
        name_environment_flag: bool = False,
        project_modules: Collection[str] = (),
        build_environment: dict[str, Any] | None = None,
    ) -> int:
        """Render the first-class build refusal for NEW check errors.

        Batch-01c M2 (P0). The build gate refuses when the current tree
        introduces NEW check-severity errors since the recorded baseline —
        the ``GENERATED_FILE_DRIFT`` refuse-at-write precedent (0.11.0 M1),
        applied to *new contract errors* instead of hand-edited output. The
        refusal is a **result, not an exception**: no artifacts are
        written, the baseline is left untouched (a re-run refuses again),
        and the payload LEADS with the labelled NEW-error list — each
        carrying M1's ``suggested_declaration`` block when the checker
        could render one — then the rule and the escape hatch.

        Returns :data:`EXIT_VALIDATION_ERROR` (the ``GENERATED_FILE_DRIFT``
        exit convention) so the MCP ``build_project`` tool sees a failing
        exit and surfaces the refusal under ``result["diagnostics"]``.

        *name_environment_flag*: when every NEW error is an environment
        diagnostic (see :data:`s0ma_dsl.check_baseline.ENVIRONMENT_CODES`)
        and the caller did not pass ``--without-runtime-packages``, the
        refusal says that the flag exists and what it does, so a build
        hook meeting the gate for the first time reads the answer in the
        refusal rather than sniffing the error list for it.
        *project_modules* names the project's s0ma modules, so an entry
        that names one of them is not taken for an environment finding.
        *build_environment* is the record a build made with
        ``--without-runtime-packages`` keeps of what it could not verify;
        a refusal under the flag carries it too, as the ``build_environment``
        block of the JSON document and one text line, so the reader sees
        what was left out of the count and why.
        """
        from s0ma_dsl.check_baseline import is_environment_diagnostic

        environment_hint: str | None = None
        if name_environment_flag and all(
            is_environment_diagnostic(diag, project_modules)
            for diag in new_errors
        ):
            environment_hint = (
                "Every NEW error is MISSING_PACKAGE, a requires: entry this "
                "environment cannot find. If this build runs where the "
                "project's runtime packages are not installed, such as a "
                "PEP 517 build environment, pass --without-runtime-packages: "
                "the build then records those packages in its manifest as "
                "unverified and refuses only new contract errors."
            )
        # Present the NEW check errors as errors (they ARE errors to
        # `check` — strict — even though this build's mode ranked them
        # warnings), each labelled [NEW] and carrying its suggested block.
        display_errors = [
            dataclasses.replace(diag, severity="error") for diag in new_errors
        ]
        count = len(display_errors)
        escape_hatch = (
            "Pass --allow-new-errors (CLI) / allow_new_errors=true (MCP) "
            "with a reason to build anyway; the override is recorded in "
            "the build manifest."
        )
        if output_format == "json":
            doc = json.loads(
                _format_diagnostics_json(
                    display_errors,
                    [],
                    files_processed,
                    mode=mode,
                    delta=delta,
                    build_environment=build_environment,
                )
            )
            doc["build_refused"] = {
                "reason": "NEW_CHECK_ERRORS",
                "new_error_count": count,
                "rule": self._BUILD_GATE_RULE,
                "escape_hatch": escape_hatch,
            }
            if environment_hint is not None:
                doc["build_refused"]["environment_hint"] = environment_hint
            print(json.dumps(doc, indent=2, sort_keys=True))
            return EXIT_VALIDATION_ERROR

        # Text output: lead with the rule, then the labelled NEW list
        # (with suggested declarations), then the escape hatch.
        print(
            f"BUILD REFUSED: {count} NEW check error(s) since your last "
            f"baseline. {self._BUILD_GATE_RULE}"
        )
        print()
        for diag in display_errors:
            label = delta.label_for_diag(diag) or "NEW"
            print(f"[{label}] {diag.format_text()}")
            print()
        print(escape_hatch)
        if environment_hint is not None:
            print(environment_hint)
        if build_environment is not None:
            names = list(build_environment.get("unverified_packages", []))
            if names:
                noun = "entry" if len(names) == 1 else "entries"
                print(
                    f"Not counted above, because --without-runtime-packages "
                    f"was passed: {len(names)} requires: {noun} this "
                    f"environment cannot find ({', '.join(names)})."
                )
        return EXIT_VALIDATION_ERROR

    def _cmd_build(self, args: argparse.Namespace) -> int:
        """Full project build with cross-module resolution.

        ``PROJECT_DIR`` is optional (G3b, pilot G2-16 / G1's H-6): a bare
        ``s0ma build`` builds the project it is standing in, resolved
        exactly the way ``s0ma check`` resolves its own — the same
        ``S0maProject``, honouring ``--project-root`` — and walks that
        project's configured source and test roots rather than the whole
        tree above them. Naming a directory still means exactly what it
        always did: build what is under it. Every refusal in the family
        can now print ``s0ma build`` as a sentence somebody can run
        (friction F-E2-2).

        Whichever path the caller names, each module's manifest ``role``
        is the role of the configured root its file lives under
        (``test`` under ``test_roots``, ``source`` under
        ``source_roots``), so a bare build records the test modules it
        sweeps in as tests rather than as source, and
        ``bootstrap_imports`` with its default roles loads the
        application alone. ``s0ma test``'s helper states its role
        explicitly through the hidden ``_role`` attribute, which wins. A
        module under no configured root is recorded as source and
        reported with ``MODULE_OUTSIDE_PROJECT_ROOTS``.
        """
        from s0ma_dsl.cache import BuildCache
        from s0ma_dsl.codegen.build_manifest import MANIFEST_FILENAME
        from s0ma_dsl.codegen.observes_resolver import ProjectContext
        from s0ma_dsl.resolver.dependency import resolve_dependencies

        mode = StrictnessMode(args.mode)
        # A build made where the project's runtime packages are not
        # installed (--without-runtime-packages) can only record the
        # requires: entries it could not find. Strict and release mode
        # exist to verify them, so the two do not combine: the flag is
        # refused there rather than left to fail on the errors it cannot
        # explain. The mode may come from [tool.s0ma].mode rather than a
        # --mode flag, so the refusal names the mode, not the flag, and
        # says which flag overrides it.
        without_runtime_packages = bool(
            getattr(args, "without_runtime_packages", False)
        )
        if without_runtime_packages and mode in (
            StrictnessMode.STRICT, StrictnessMode.RELEASE,
        ):
            print(
                f"s0ma build: --without-runtime-packages does not combine "
                f"with {mode.value} mode: strict and release mode verify "
                f"every requires: entry, which an environment without the "
                f"project's runtime packages cannot do. Pass --mode dev or "
                f"--mode migration here (either overrides "
                f"[tool.s0ma].mode), and run `s0ma check --mode "
                f"{mode.value}` where the packages are installed.",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR
        # M6a (feedback 5–6, ADR-007): output_dir resolution prefers an
        # explicit --output-dir; otherwise falls back to the resolved
        # S0maProject.build_dir (M1) when one is available; otherwise
        # legacy fallback to project_dir.
        explicit_output = Path(args.output_dir) if args.output_dir else None
        s0ma_project = getattr(args, "s0ma_project", None)

        # With no positional, the project's own roots are the input. A
        # tree with no [tool.s0ma] table has no roots to read, so that is
        # the one case the bare command cannot serve, and it says so.
        configured_roots: tuple[Path, ...] | None = None
        if args.project_dir is None:
            if s0ma_project is None or s0ma_project.synthetic:
                print(
                    "s0ma build: there is no s0ma project here, so there is "
                    "nothing to build. Run this from a directory whose "
                    "pyproject.toml carries a [tool.s0ma] table (or pass "
                    "--project-root), or name the directory holding your "
                    ".s0ma files.",
                    file=sys.stderr,
                )
                return EXIT_USAGE_ERROR
            project_dir = Path(s0ma_project.root)
            configured_roots = tuple(s0ma_project.source_roots) + tuple(
                s0ma_project.test_roots
            )
        else:
            project_dir = Path(args.project_dir)

        # M-16 (POST-11a, 0.16.0): when an explicit ``--output-dir``
        # disagrees with the resolved ``[tool.s0ma].build_dir`` the
        # default behaviour is to refuse with ``BUILD_DIR_OVERRIDE_CONFLICT``
        # — the project config is the canonical source of truth and a
        # silent override would scatter build artefacts across two
        # locations (a steady-state ``build/`` plus the throwaway
        # ``--output-dir`` target the user typed once). ``--force-output-dir``
        # is the escape hatch for the ad-hoc-override case (e.g. a CI
        # script that wants to inspect a build in a tmpdir without
        # touching the steady-state path). The hidden ``_role`` namespace
        # attribute is set by ``_run_build_for_test`` (``s0ma test``'s
        # build helper) which already passes ``output_dir == build_dir``
        # — that path is exempt so the test runner's internal call does
        # not need the user-facing flag.
        force_output_dir = bool(getattr(args, "force_output_dir", False))
        invoked_by_test_runner = getattr(args, "_role", None) is not None
        if (
            explicit_output is not None
            and s0ma_project is not None
            and not s0ma_project.synthetic
            and not invoked_by_test_runner
        ):
            try:
                same_path = (
                    explicit_output.resolve() == s0ma_project.build_dir.resolve()
                )
            except (OSError, RuntimeError):
                # Resolution failure (broken symlink, permission, etc.)
                # — fall back to a string comparison rather than crash.
                same_path = str(explicit_output) == str(s0ma_project.build_dir)
            if not same_path:
                if not force_output_dir:
                    pyproject_path = s0ma_project.root / "pyproject.toml"
                    print(
                        f"s0ma build: BUILD_DIR_OVERRIDE_CONFLICT: "
                        f"--output-dir={explicit_output} disagrees with "
                        f"[tool.s0ma].build_dir={s0ma_project.build_dir} "
                        f"in {pyproject_path}.\n"
                        f"The project model is the canonical source of "
                        f"truth for build_dir; silent overrides scatter "
                        f"build artefacts.\n"
                        f"Remediation:\n"
                        f"  - Drop --output-dir and let the project model "
                        f"resolve the build dir (recommended).\n"
                        f"  - Pass --force-output-dir to proceed with the "
                        f"override (the build still lands at the supplied "
                        f"path; a one-line stderr notice is emitted).",
                        file=sys.stderr,
                    )
                    return EXIT_USAGE_ERROR
                print(
                    f"s0ma build: --output-dir={explicit_output} "
                    f"overrides [tool.s0ma].build_dir="
                    f"{s0ma_project.build_dir} (--force-output-dir).",
                    file=sys.stderr,
                )

        if explicit_output is not None:
            output_dir = explicit_output
        elif s0ma_project is not None and not s0ma_project.synthetic:
            output_dir = s0ma_project.build_dir
        else:
            output_dir = None

        if not project_dir.is_dir():
            print(f"Not a directory: {project_dir}", file=sys.stderr)
            return EXIT_USAGE_ERROR

        # M6a: incremental-rebuild cache lives under a hidden
        # ``.s0ma.cache/`` directory rooted at the build's input dir
        # (or, when ``--output-dir`` is supplied, under that). It is
        # *not* the build output (which is the flat layout at
        # ``output_dir``) and it is *not* a Python package — leading
        # dot keeps Python's importer from ever picking it up. The
        # legacy ``__s0ma_cache__/`` directory is no longer emitted
        # (ADR-007).
        use_cache = not args.no_cache
        cache: BuildCache | None = None
        cache_anchor = output_dir or project_dir
        if use_cache:
            cache_root = cache_anchor / ".s0ma.cache"
            cache = BuildCache(cache_dir=cache_root)

            # Clean if requested — clear the cache and any stray legacy
            # ``__s0ma_cache__/`` directories that pre-date M6a (which
            # may sit under either the input project dir or the output
            # dir, since pre-M6a wrote to ``(output_dir or project_dir)``).
            if args.clean:
                cache.clear()
                import shutil
                legacy_roots = {
                    cache_anchor / "__s0ma_cache__",
                    project_dir / "__s0ma_cache__",
                }
                if s0ma_project is not None:
                    legacy_roots.add(s0ma_project.root / "__s0ma_cache__")
                for legacy_root in legacy_roots:
                    if legacy_root.exists():
                        shutil.rmtree(legacy_root)

        if configured_roots is None:
            target_files = _discover_s0ma_files(str(project_dir))
            searched = str(project_dir)
        else:
            # The project's own roots, in the order it declares them,
            # each file once — `s0ma check`'s rule when it is given no
            # paths, so the two commands read one project the same way.
            seen_sources: set[Path] = set()
            target_files = []
            for source_root in configured_roots:
                if not source_root.is_dir():
                    continue
                for found in _discover_s0ma_files(str(source_root)):
                    resolved_source = found.resolve()
                    if resolved_source in seen_sources:
                        continue
                    seen_sources.add(resolved_source)
                    target_files.append(found)
            searched = ", ".join(
                self._shown_root(source_root, project_dir)
                for source_root in configured_roots
            ) or str(project_dir)
        if not target_files:
            print(f"No .s0ma files found in: {searched}", file=sys.stderr)
            return EXIT_USAGE_ERROR

        # Discover context modules from --include paths
        context_files: list[Path] = []
        for include_path in args.include or []:
            context_files.extend(_discover_s0ma_files(str(include_path)))

        all_diagnostics: list[S0maError] = []
        all_outputs: list[str] = []
        modules: list[tuple[Path, S0maModule]] = []
        module_dict: dict[str, S0maModule] = {}
        module_filenames: dict[str, str] = {}
        target_names: set[str] = set()
        # M-14 (POST-10d): effective-name discriminator for the
        # collision check. See ``_cmd_check`` for the rationale.
        build_effective_to_file: dict[str, str] = {}
        # The manifest role each built module is recorded with. The
        # hidden ``_role`` attribute is the explicit statement
        # ``_run_build_for_test`` (``s0ma test``'s build helper) makes
        # for a whole pass, and it wins when set. Every other caller
        # gets the role of the configured root each file lives under
        # (``_root_role``), so a bare build, ``s0ma build .`` and
        # ``s0ma build tests`` record a test module as a test. A module
        # under no configured root is recorded as source and reported
        # (``MODULE_OUTSIDE_PROJECT_ROOTS``); a synthetic project has no
        # roots to be outside of and records source silently, as before.
        explicit_role: str | None = getattr(args, "_role", None)
        roles_by_source: dict[Path, str] = {}

        # M-12 (POST-8, 0.16.0): resolve ``[project].requires-python``
        # for the build pass so per-file validation can fire
        # PARSE_GRAMMAR_FORWARD_INCOMPAT on 3.12-only grammar before
        # the codegen step ever runs.
        build_requires_python = (
            s0ma_project.requires_python
            if s0ma_project is not None and not s0ma_project.synthetic
            else None
        )

        # Stage 1-3: Parse and validate target files
        for source_path in target_files:
            module, parse_errors = _parse_single_file(source_path, mode)
            all_diagnostics.extend(parse_errors)
            if module is not None:
                declared_name = module.module.name
                effective_name = (
                    s0ma_project.effective_module_name(
                        declared_name, source_path,
                    )
                    if s0ma_project is not None
                    else declared_name
                )

                # Check for module name collision
                if effective_name in build_effective_to_file:
                    existing_file = build_effective_to_file[effective_name]
                    all_diagnostics.append(S0maError(
                        code="MODULE_NAME_COLLISION",
                        message=(
                            f"Module '{declared_name}' found in both "
                            f"'{existing_file}' and "
                            f"'{source_path}'."
                        ),
                        file=str(source_path),
                        line=1,
                        column=0,
                        severity="error",
                        remediation=_module_collision_suggestion(
                            declared_name,
                            existing_file,
                            str(source_path),
                            s0ma_project,
                        ),
                    ))
                    continue

                sem_errors = _validate_single_module(
                    module, source_path, mode,
                    requires_python=build_requires_python,
                )
                all_diagnostics.extend(sem_errors)
                modules.append((source_path, module))
                module_dict[declared_name] = module
                module_filenames[declared_name] = str(source_path)
                build_effective_to_file[effective_name] = str(source_path)
                target_names.add(declared_name)
                if explicit_role is not None:
                    module_role = explicit_role
                else:
                    attributed = _root_role(source_path, s0ma_project)
                    if (
                        attributed is None
                        and s0ma_project is not None
                        and not s0ma_project.synthetic
                    ):
                        all_diagnostics.append(_module_outside_project_roots(
                            declared_name, source_path, s0ma_project,
                        ))
                    module_role = attributed or "source"
                roles_by_source[source_path] = module_role

        # Parse and validate context modules (from --include — not transpiled)
        for source_path in context_files:
            module, parse_errors = _parse_single_file(source_path, mode)
            all_diagnostics.extend(parse_errors)
            if module is not None:
                declared_name = module.module.name
                effective_name = (
                    s0ma_project.effective_module_name(
                        declared_name, source_path,
                    )
                    if s0ma_project is not None
                    else declared_name
                )

                # Check for module name collision
                if effective_name in build_effective_to_file:
                    existing_file = build_effective_to_file[effective_name]
                    all_diagnostics.append(S0maError(
                        code="MODULE_NAME_COLLISION",
                        message=(
                            f"Module '{declared_name}' found in both "
                            f"'{existing_file}' and '{source_path}'."
                        ),
                        file=str(source_path),
                        line=1,
                        column=0,
                        severity="error",
                        remediation=_module_collision_suggestion(
                            declared_name,
                            existing_file,
                            str(source_path),
                            s0ma_project,
                        ),
                    ))
                    continue

                sem_errors = _validate_single_module(
                    module, source_path, mode,
                    requires_python=build_requires_python,
                )
                all_diagnostics.extend(sem_errors)
                module_dict[declared_name] = module
                module_filenames[declared_name] = str(source_path)
                build_effective_to_file[effective_name] = str(source_path)

        # Cross-module dependency resolution
        # M18 (feedback 5–6): forward configured attribute budgets so
        # the resolver runs the budget pass on every project that opts
        # in via ``[tool.s0ma.attribute_budgets]``.
        attribute_budgets = (
            s0ma_project.attribute_budgets
            if s0ma_project is not None and not s0ma_project.synthetic
            else {}
        )
        # M-10 (POST-6, 0.16.0): forward project-level
        # ``test_layering`` stance so the resolver can carve out
        # test-context modules from ``CROSS_LAYER_DEPENDENCY`` when
        # the project opts in. Synthetic projects (no
        # ``[tool.s0ma]``) stay at the strict default.
        test_layering = (
            s0ma_project.test_layering
            if s0ma_project is not None and not s0ma_project.synthetic
            else "strict"
        )
        if (
            len(module_dict) > 1
            or mode == StrictnessMode.RELEASE
            or attribute_budgets
            or _needs_module_local_resolution(module_dict)
        ):
            resolution_errors = resolve_dependencies(
                module_dict,
                mode=mode,
                filenames=module_filenames,
                attribute_budgets=attribute_budgets,
                test_layering=test_layering,
            )
            all_diagnostics.extend(resolution_errors)

        # Doc-subsystem validation (plan M5 — wire DocValidator into pipeline)
        if module_dict and _has_doc_declarations(module_dict):
            from s0ma_dsl.semantic.doc_validator import validate_docs
            doc_errors = validate_docs(
                module_dict, filenames=module_filenames, mode=mode,
            )
            all_diagnostics.extend(doc_errors)
        # Release-mode coverage checks (plan M7 subtask 4) run
        # unconditionally so a project that ships zero doc-refs still
        # surfaces uncovered PUBLIC nerves in release mode.
        if module_dict:
            from s0ma_dsl.semantic.doc_validator import check_release_doc_coverage
            all_diagnostics.extend(check_release_doc_coverage(
                module_dict, mode=mode, filenames=module_filenames,
            ))

        # 0.14 M2: emission always imports the s0ma core + DSL runtime.
        # Warn at the two emitting surfaces; static check/score/verify never
        # execute project code and do not pretend this proves installation.
        if s0ma_project is not None:
            from s0ma_dsl.host_verification import (
                static_runtime_dependency_warning,
            )
            runtime_warning = static_runtime_dependency_warning(s0ma_project)
            if runtime_warning is not None:
                all_diagnostics.append(runtime_warning)

        # Check for blocking errors before emission
        quiet = args.quiet
        blocking = [e for e in all_diagnostics if e.severity == "error"]
        if blocking:
            _print_diagnostics(
                all_diagnostics,
                output_format=args.output_format,
                files_processed=len(target_files),
                mode=args.mode,
                quiet=quiet,
            )
            return EXIT_VALIDATION_ERROR

        # --- M2 (0.13.0, batch-01c): the NEW check-error build gate ------
        # `build_project` failed 0/84 times in batch-01c cold sessions
        # while 18/36 ended check-red; the CM6 crater shipped through
        # exactly this gap — the agent read its own check failures, called
        # them "pre-existing and not related to my changes" (it was
        # wrong), built green (dev), and never ran the service. 0.12.0 made
        # NEW-vs-PRE-EXISTING computable; this makes it BINDING on the
        # build. Past the dev-error block above, any diagnostic that
        # `check` (strict) would rank an error but this (dev) build ranks a
        # warning is a *check error*. Classify those against the baseline's
        # inherited-debt ANCHOR (0.13.0 M2 semantics — the anchor is seeded
        # at first contact and only ever shrinks, so an intervening red
        # `check` structurally CANNOT launder a NEW failure into
        # PRE-EXISTING; the CM6 sequence ran check before building): a NEW
        # one REFUSES the build unless --allow-new-errors is passed.
        # Warnings never block; PRE-EXISTING (anchored) errors alone never
        # block (brownfield stays viable); a missing baseline degrades to
        # today's warn-and-build (the gate only tightens on evidence it can
        # attribute to the current edits). Refusal writes no artifacts and
        # — unlike the success tail below — never touches the baseline, so
        # a re-run refuses again until the errors are fixed or the flag is
        # passed.
        allow_new_errors = bool(getattr(args, "allow_new_errors", False))
        from s0ma_dsl.check_baseline import is_environment_diagnostic

        # The record of a build made without the runtime packages: every
        # requires: entry it could not find, whether or not a baseline
        # exists to attribute it, and whether or not the gate below goes
        # on to refuse the build for something else. Rides into the JSON
        # report as ``build_environment`` and into the manifest as
        # ``unverified_packages`` (nothing was overridden, so never into
        # ``overridden_new_errors``). An entry naming one of this
        # project's s0ma modules is not an environment finding.
        build_environment: dict[str, Any] | None = None
        unverified_packages: tuple[str, ...] = ()
        if without_runtime_packages:
            environment_findings = [
                d for d in all_diagnostics
                if is_environment_diagnostic(d, module_dict)
            ]
            unverified_packages = tuple(sorted({
                str(
                    d.context.get("import_path")
                    or d.context.get("requires")
                    or d.code
                )
                for d in environment_findings
            }))
            build_environment = {
                "without_runtime_packages": True,
                "unverified_package_count": len(unverified_packages),
                "unverified_packages": list(unverified_packages),
                "diagnostics": [d.to_dict() for d in environment_findings],
            }

        # Two paths are exempt: `build --check` (a drift dry-run that
        # writes NO artifacts to the real build dir — the gate's
        # refuse-before-emit rationale does not apply) and the internal
        # `s0ma test` build helper (signalled by the hidden `_role`
        # namespace attribute), whose job is to build-for-test, not to
        # gate the tree.
        gate_exempt = bool(getattr(args, "check", False)) or (
            getattr(args, "_role", None) is not None
        )
        gate_root = (
            Path(s0ma_project.root)
            if s0ma_project is not None and not s0ma_project.synthetic
            else None
        )
        build_override: dict[str, Any] | None = None
        overridden_new_error_keys: tuple[str, ...] = ()
        if gate_root is not None and not gate_exempt:
            from s0ma_dsl.check_baseline import (
                classify,
                diagnostic_key,
                is_check_severity_error,
                load_baseline_record,
            )
            check_errors = [
                d for d in all_diagnostics if is_check_severity_error(d)
            ]
            if without_runtime_packages:
                # The caller stated that this environment does not hold
                # the runtime packages, so a requires: entry the build
                # cannot find is an environment finding, not a contract
                # error the edit introduced. It is left out of the set the
                # gate classifies, so a refusal's delta counts only what
                # can refuse; the record above keeps it. An entry naming
                # one of this project's s0ma modules is not an environment
                # finding and stays in.
                check_errors = [
                    d for d in check_errors
                    if not is_environment_diagnostic(d, module_dict)
                ]
            if check_errors:
                record = load_baseline_record(gate_root)
                delta = classify(
                    record.anchor if record is not None else None,
                    check_errors,
                    gate_root,
                )
                new_errors = [
                    d for d in check_errors
                    if delta.label_for_diag(d) == "NEW"
                ]
                if new_errors and not allow_new_errors:
                    return self._emit_build_refusal(
                        new_errors=new_errors,
                        delta=delta,
                        output_format=args.output_format,
                        files_processed=len(target_files),
                        mode=args.mode,
                        quiet=quiet,
                        name_environment_flag=not without_runtime_packages,
                        project_modules=module_dict,
                        build_environment=build_environment,
                    )
                if new_errors:  # allow_new_errors — override, record it
                    overridden_new_error_keys = tuple(
                        sorted(
                            _format_diagnostic_key(
                                diagnostic_key(d, gate_root)
                            )
                            for d in new_errors
                        )
                    )
                    build_override = {
                        "allow_new_errors": True,
                        "new_error_count": len(new_errors),
                        "new_errors": [
                            _error_to_dict(d, delta) for d in new_errors
                        ],
                    }

        # Build project context for cross-module features (include all modules)
        all_modules_list = [m for _, m in modules]
        # Also include context-only modules in the project context
        for name, mod in module_dict.items():
            if name not in target_names:
                all_modules_list.append(mod)
        project_context = ProjectContext(
            modules=all_modules_list
        )

        # Compute project-wide doc hashes + project index once. Both
        # are passed into every per-file transpile so the rendered
        # output and the emitted register_doc_* calls agree on the
        # hash for every doc declaration.
        doc_hashes_index = None
        project_index_inst = None
        if _has_doc_declarations(module_dict):
            from s0ma_dsl.codegen.doc_emitter import compute_doc_hashes
            from s0ma_dsl.resolver.doc_resolver import build_project_index
            doc_hashes_index = compute_doc_hashes(
                module_dict, filenames=module_filenames,
            )
            project_index_inst = build_project_index(module_dict)

        check_mode = args.check

        # --check mode: transpile to temp dir, compare against existing output
        if check_mode:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_out = Path(tmpdir)
                for source_path, _module in modules:
                    file_output_dir = _resolve_output_dir(
                        source_path, project_dir, tmp_out,
                    )
                    diagnostics, outputs = _transpile_single_file(
                        source_path,
                        mode=mode,
                        output_dir=file_output_dir,
                        project_context=project_context,
                        doc_hashes=doc_hashes_index,
                        project_modules=module_dict,
                        project_index=project_index_inst,
                        docs_base_dir=tmp_out,
                        requires_python=build_requires_python,
                        recorded_source=_recorded_project_path(
                            source_path, s0ma_project,
                        ),
                        s0ma_project=s0ma_project,
                    )
                    all_diagnostics.extend(diagnostics)
                    all_outputs.extend(outputs)

                errors = [e for e in all_diagnostics if e.severity == "error"]
                if errors:
                    _print_diagnostics(
                        all_diagnostics,
                        output_format=args.output_format,
                        files_processed=len(target_files),
                        mode=args.mode,
                        quiet=quiet,
                    )
                    return EXIT_VALIDATION_ERROR

                original_dir = output_dir or project_dir
                results = _compare_outputs(tmp_out, original_dir, all_outputs)
                return _print_drift_results(
                    results, len(modules), quiet=quiet
                )

        # Stage 5-6: Transpile only target files (not context modules)
        docs_base = output_dir or project_dir
        for source_path, _module in modules:
            file_output_dir = _resolve_output_dir(
                source_path, project_dir, output_dir,
            )
            diagnostics, outputs = _transpile_single_file(
                source_path,
                mode=mode,
                output_dir=file_output_dir,
                project_context=project_context,
                cache=cache,
                doc_hashes=doc_hashes_index,
                project_modules=module_dict,
                project_index=project_index_inst,
                docs_base_dir=docs_base,
                requires_python=build_requires_python,
                recorded_source=_recorded_project_path(
                    source_path, s0ma_project,
                ),
                s0ma_project=s0ma_project,
                force=getattr(args, "force", False),
            )
            all_diagnostics.extend(diagnostics)
            all_outputs.extend(outputs)

        # M6a (feedback 5–6, ADR-007): emit a single ``__init__.py`` at
        # the build root so the flat layout is a real Python package and
        # cross-module imports work without runtime gymnastics.
        errors_so_far = [e for e in all_diagnostics if e.severity == "error"]
        if not errors_so_far and output_dir is not None:
            init_path = _emit_build_init(output_dir)
            if init_path is not None:
                all_outputs.append(str(init_path))

        # M6b (feedback 5–6, ADR-007): emit the canonical
        # ``build.s0ma.json`` manifest. The manifest is the runtime
        # bridge's source of truth — it lists every emitted module,
        # source/output paths, and source/output hashes. The plan's
        # schema string ``s0ma-build-manifest@1`` is intentional: M10
        # extends the schema additively (topological_import_order),
        # and M12 may extend it further (external_content_files);
        # readers branch on optional fields rather than the version.
        manifest_path: Path | None = None
        if not errors_so_far and output_dir is not None and modules:
            # PRE-2/PRE-3 (0.14.0): tag manifest entries with a role so
            # a single ``build.s0ma.json`` can hold both source and test
            # modules. Each entry carries the role decided in the target
            # loop above (``roles_by_source``): the configured root the
            # file lives under, or the explicit role ``s0ma test``'s
            # helper passed for the whole pass, so the tag is right
            # whichever command wrote the manifest.
            manifest_entries: list[ModuleManifestEntry] = []
            for source_path, module in modules:
                entry = _collect_manifest_entry(
                    module_name=module.module.name,
                    source_path=source_path,
                    build_dir=output_dir,
                    role=roles_by_source.get(source_path, "source"),
                    recorded_source=_recorded_project_path(
                        source_path, s0ma_project,
                    ),
                    recorded_logical=_recorded_logical_structure(
                        source_path, s0ma_project,
                    ),
                )
                if entry is not None:
                    manifest_entries.append(entry)

            # M10 (feedback 5–6): compute the dependency-first
            # topological order over target modules. The four-phase
            # resolver above already detected cycles via
            # ``CIRCULAR_DEPENDENCY`` and returned before we got here,
            # so a cycle at this point is unexpected. We still surface
            # ``MODULE_DEPENDENCY_CYCLE`` defensively in case the
            # resolver path was bypassed (e.g., a single-target build
            # with cross-module ``uses:`` to context-only modules — not
            # currently a possibility, but the defensive surface is
            # cheap insurance).
            from s0ma_dsl.resolver.topological import (
                ModuleDependencyCycleError,
                compute_topological_order,
            )
            target_modules_dict = {m.module.name: m for _, m in modules}
            try:
                topo_order = compute_topological_order(target_modules_dict)
            except ModuleDependencyCycleError as cycle_err:
                # Surface as a regular diagnostic so the user sees the
                # same output shape they get for every other build error.
                first_target_path = (
                    str(modules[0][0]) if modules else str(project_dir)
                )
                all_diagnostics.append(S0maError(
                    code="MODULE_DEPENDENCY_CYCLE",
                    message=str(cycle_err),
                    file=first_target_path,
                    line=1,
                    column=0,
                    severity="error",
                    remediation=(
                        f"Break the cycle by removing one of the "
                        f"uses: entries in the chain among modules: "
                        f"{', '.join(cycle_err.cycle_modules)}. "
                        f"Consider whether a dependency can be "
                        f"inverted or mediated through a shared "
                        f"lower-layer module."
                    ),
                    context={"cycle_modules": list(cycle_err.cycle_modules)},
                ))
                _print_diagnostics(
                    all_diagnostics,
                    output_format=args.output_format,
                    files_processed=len(target_files),
                    mode=args.mode,
                    quiet=quiet,
                )
                return EXIT_VALIDATION_ERROR

            project_name = (
                s0ma_project.project_name
                if s0ma_project is not None
                else output_dir.name
            )
            # M12 (feedback 5–6): collect every CONSTANT-cell embed
            # directive (``content: @file("path")``) into the build
            # manifest's ``external_content_files`` map. The map is
            # additive under ``s0ma-build-manifest@1`` — projects with
            # zero embeds produce manifests byte-identical to pre-M12
            # builds. Each entry preserves the path the author wrote
            # (relative paths stay relative; absolute paths stay
            # absolute) plus the SHA-256 hash of the embedded bytes
            # captured by the parser at parse time.
            from s0ma_dsl.codegen.build_manifest import (
                ExternalContentFileEntry,
            )
            external_content_files: dict[str, ExternalContentFileEntry] = {}
            for _, module in modules:
                for cell in module.cells:
                    if cell.embedded_file_path is None:
                        continue
                    key = f"{module.module.name}::{cell.name}"
                    external_content_files[key] = ExternalContentFileEntry(
                        path=cell.embedded_file_path,
                        hash=cell.embedded_file_hash or "",
                    )

            # PRE-3 (0.14.0): when ``s0ma test`` runs the test-roots
            # build pass after the source-roots pass, merge with the
            # source-roots manifest already on disk so the unified
            # manifest carries both source and test entries. Each pass
            # overwrites only its own modules (matched by name); other
            # entries survive. ``--clean`` skips the merge so a clean
            # build always starts from an empty manifest.
            from s0ma_dsl.codegen.build_manifest import (
                MANIFEST_FILENAME,
                ManifestSchemaError,
                load_manifest,
            )
            merged_entries: list[ModuleManifestEntry] = manifest_entries
            merged_topo: tuple[str, ...] = tuple(topo_order)
            merged_external: dict[str, ExternalContentFileEntry] = (
                external_content_files
            )
            existing_manifest_path = output_dir / MANIFEST_FILENAME
            if (
                not getattr(args, "clean", False)
                and existing_manifest_path.is_file()
            ):
                try:
                    prior = load_manifest(output_dir)
                except ManifestSchemaError:
                    # Corrupt prior — overwrite cleanly (matches the
                    # pre-PRE-3 behaviour of unconditional rewrite).
                    pass
                else:
                    new_names = {e.name for e in manifest_entries}
                    surviving_prior = [
                        e for e in prior.modules if e.name not in new_names
                    ]
                    merged_entries = surviving_prior + list(manifest_entries)
                    # Preserve prior topological order, then append new
                    # names that the prior topology did not know about.
                    # ``dict.fromkeys`` deduplicates while keeping order.
                    merged_topo = tuple(
                        dict.fromkeys(
                            (*prior.topological_import_order, *topo_order)
                        )
                    )
                    merged_external = {
                        **prior.external_content_files,
                        **external_content_files,
                    }

            manifest_path = _emit_build_manifest(
                project_name=project_name,
                build_dir=output_dir,
                entries=merged_entries,
                topological_import_order=merged_topo,
                external_content_files=merged_external,
                recorded_build_dir=_recorded_project_path(
                    output_dir, s0ma_project,
                ),
                # M2 (batch-01c): record which NEW check errors an
                # --allow-new-errors override waved through, so the bench
                # can count overrides. Empty (key omitted) on every normal
                # build.
                overridden_new_errors=overridden_new_error_keys,
                unverified_packages=unverified_packages,
            )
            if manifest_path is not None:
                all_outputs.append(str(manifest_path))

            # M-8 (POST-14, 0.15.x): emit the companion Python type
            # stub at ``<build_dir>/build.s0ma.pyi``. The stub declares
            # each module's importable identity as ``ModuleType`` plus a
            # ``BootstrapModules`` TypedDict so consumers of
            # ``s0ma.bootstrap.bootstrap_imports`` get mypy / pyright
            # coverage on ``modules["<name>"]`` lookups when they point
            # their type-checker at the build directory. Gated on the
            # same ``errors_so_far == 0`` condition as the manifest;
            # builds without a manifest never produce a stub either, so
            # the two files are always consistent.
            if manifest_path is not None:
                from s0ma_dsl import __version__ as transpiler_version
                from s0ma_dsl.codegen.build_manifest import load_manifest
                from s0ma_dsl.codegen.manifest_stub_emitter import (
                    emit_manifest_stub,
                )
                stub_path = emit_manifest_stub(
                    load_manifest(output_dir),
                    output_dir,
                    transpiler_version=transpiler_version,
                )
                all_outputs.append(str(stub_path))

            # PRE-6 (0.14.0): prune orphan artefacts whose source is no
            # longer in the manifest. Only runs on a clean build (no
            # earlier errors) — a partial build's stale artefacts may
            # still be recoverable from the user's standpoint, so we
            # avoid deleting them.
            known_module_names = {entry.name for entry in merged_entries}
            pruned_paths = _prune_orphan_artefacts(
                output_dir, known_module_names,
            )
            if pruned_paths and not quiet:
                names = ", ".join(sorted(p.name for p in pruned_paths))
                print(
                    f"Pruned {len(pruned_paths)} orphan artefact(s): {names}"
                )

        # M2 (batch-01c): a fully-green build refreshes the same check
        # baseline as ``check`` (spec (a) — "check/build_project"), so the
        # clean fingerprint tracks whichever ran last. Build records but
        # does not render the attribution (delta rendering is ``check``'s
        # surface, spec (b)); the returned report is ignored here.
        # Scope guard (0.13.0 M2): only a full-project-root, user-facing
        # build records — the internal `s0ma test` helper (`_role`) and a
        # subdir-scoped invocation analyse a subset of the project, and a
        # partial run must never rewrite the whole-project record (the
        # anchor may only shrink on full re-analysis evidence).
        try:
            is_full_root_build = (
                s0ma_project is not None
                and not s0ma_project.synthetic
                and project_dir.resolve() == Path(s0ma_project.root).resolve()
            )
        except OSError:
            is_full_root_build = False
        # A build made without the runtime packages observed a foreign
        # environment: what it could not find says nothing about this
        # checkout's debt, so it leaves the baseline alone.
        if (
            is_full_root_build
            and getattr(args, "_role", None) is None
            and not without_runtime_packages
        ):
            self._record_check_baseline(s0ma_project, all_diagnostics)

        # Report
        _print_diagnostics(
            all_diagnostics,
            output_format=args.output_format,
            files_processed=len(target_files),
            mode=args.mode,
            quiet=quiet,
            build_override=build_override,
            build_environment=build_environment,
            manifest_written=manifest_path is not None,
        )

        errors, warnings = _split_diagnostics(all_diagnostics)
        if not errors and args.output_format == "text" and all_outputs:
            # M-16 (POST-11b, 0.16.0): when ``_cmd_build`` is invoked
            # via ``_run_build_for_test`` (``s0ma test``'s build helper,
            # signalled by the hidden ``_role`` namespace attribute) AND
            # the user passed ``--quiet``, suppress the per-build summary
            # entirely so the only thing on stdout is pytest's own
            # stream. Without ``--quiet`` the summary still prints (the
            # user explicitly opted into visible per-step output).
            # Without ``_role`` (the user-facing ``s0ma build --quiet``
            # invocation), the legacy "Built N module(s). …" one-liner
            # is preserved for back-compat.
            suppress_build_summary = (
                quiet and getattr(args, "_role", None) is not None
            )
            if suppress_build_summary:
                pass  # nothing to print
            elif quiet:
                print(f"Built {len(modules)} module(s). 0 errors, {len(warnings)} warning(s).")
            else:
                canonical_dir = output_dir or project_dir
                # M6b: build summary names the manifest. The pre-M6b
                # line was "Built N module(s). Output directory: …";
                # the new line satisfies the plan's
                # "Build complete: M modules → <build_dir> (manifest: …)"
                # shape while keeping the M6a "Import via:" idiom on
                # its own line so consumers' grep-based workflows stay
                # stable.
                if manifest_path is not None:
                    print(
                        f"\nBuild complete: {len(modules)} module(s) → "
                        # Forward-slashed on every OS (POSIX no-op; Windows
                        # keeps this line byte-identical to the transcripts).
                        f"{canonical_dir.as_posix()} (manifest: {MANIFEST_FILENAME})"
                    )
                else:
                    print(
                        f"\nBuilt {len(modules)} module(s). "
                        f"Output directory: {canonical_dir.as_posix()}"
                    )
                # M6a: replace the misleading two-headed-layout note with
                # a single accurate import idiom derived from the build
                # directory's basename.
                import_pkg = canonical_dir.name
                print(
                    f"Build complete. Import via: from {import_pkg} import <module>"
                )
                for out in all_outputs:
                    print(f"  {_display_path(out)}")
                # G3b (G1's H-9): say when a file was kept rather than
                # written. The paths above are the published ones either
                # way, and the reader who has just aliased a package to
                # this directory wants to know that nothing moved.
                if cache is not None and cache.hits:
                    kept = cache.hits
                    print(
                        f"  ({kept} module{'' if kept == 1 else 's'} unchanged "
                        f"— kept from the last build, not rewritten)"
                    )
                # M4 (0.13.0, batch-01c): ship-without-running was the
                # common thread of the batch's worst outcomes, so a green
                # build points at the way to verify it — the declared
                # verify command, or the nudge to declare one. The MCP
                # build_project result is the primary surface (spec (a));
                # this keeps the CLI coherent, rendering the single
                # canonical wording from ``S0maProject.health_echo``.
                # Skipped for the ``s0ma test`` build helper (``_role``;
                # a build-to-test is not a build-to-ship) and for
                # synthetic projects (no [tool.s0ma] — the MCP surface
                # likewise attaches no echo in legacy mode, where the
                # right nudge is init_project, not health_command).
                if (
                    s0ma_project is not None
                    and not s0ma_project.synthetic
                    and getattr(args, "_role", None) is None
                ):
                    print(s0ma_project.health_echo())

        return EXIT_VALIDATION_ERROR if errors else EXIT_SUCCESS

    # -------------------------------------------------------------------
    # migrate-layout (M6b — feedback 5–6, ADR-007)
    # -------------------------------------------------------------------

    def _cmd_migrate_layout(self, args: argparse.Namespace) -> int:
        """Bring a legacy build directory forward to the M6a flat layout.

        Walks ``<build_dir>`` for any pre-M6a artifacts —
        ``__s0ma_cache__/`` directories, per-layer subdirectories
        (``presentation/``, ``application/``, ``domain/``,
        ``infrastructure/``) — and deletes them. Then runs a fresh
        ``s0ma build`` so the flat layout, ``__init__.py``, and
        ``build.s0ma.json`` manifest are emitted from scratch.

        The command is idempotent: running it twice in a row produces
        the same result. The second pass finds nothing to clean and
        simply re-runs the build. (The build step itself is idempotent
        per M6a — ``__init__.py`` is not rewritten if its content
        matches.)

        Defensive: never deletes a directory that does not look like a
        s0ma build target. The recogniser checks for at least one
        s0ma-shaped artifact (a ``__s0ma_cache__/`` directory with
        files inside, a ``.s0ma.json`` IR file anywhere under the
        target, or the M6a-emitted ``__init__.py`` whose docstring
        marks it as auto-generated). If the build directory exists
        but carries no recognisable artifact, we refuse to delete and
        surface a remediation.
        """
        import shutil

        s0ma_project: S0maProject | None = getattr(args, "s0ma_project", None)

        # Resolve project_dir (where source lives) and build_dir (the
        # output directory whose legacy layout we're migrating). Order
        # of preference: explicit positional arg → s0ma_project root.
        if args.project_dir is not None:
            project_dir = Path(args.project_dir).resolve()
            # If we have an explicit project_dir but no S0maProject
            # discovered, fall back to a synthetic project anchored
            # there. The synthetic project's build_dir matches what
            # `s0ma build <project_dir>` would write to without an
            # explicit --output-dir.
            if (
                s0ma_project is None
                or s0ma_project.synthetic
                or s0ma_project.root != project_dir
            ):
                s0ma_project = S0maProject.synthetic_fallback(project_dir)
        elif s0ma_project is not None and not s0ma_project.synthetic:
            project_dir = s0ma_project.root
        else:
            print(
                "s0ma migrate-layout: no project resolved. Pass a "
                "project directory or run from a tree containing "
                "[tool.s0ma] in pyproject.toml.",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR

        build_dir: Path = s0ma_project.build_dir
        quiet = args.quiet

        # ----- Step 1: Identify legacy paths to clean up. -----
        legacy_paths = self._discover_legacy_layout_paths(
            project_dir=project_dir, build_dir=build_dir,
        )

        # Defensive: if the build directory exists but does not look
        # like a s0ma build (no __init__.py with our marker, no IR,
        # no __s0ma_cache__/), refuse to touch it. This is a guard
        # against accidentally pointing migrate-layout at the wrong
        # directory. Empty / non-existent build dirs are fine — the
        # post-clean build creates them.
        if (
            build_dir.exists()
            and not legacy_paths
            and not self._looks_like_s0ma_build(build_dir)
        ):
            print(
                f"s0ma migrate-layout: refusing to operate on "
                f"{build_dir}: no recognisable s0ma build artifacts. "
                f"Verify the project's build_dir setting in "
                f"pyproject.toml's [tool.s0ma] table.",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR

        cleaned = 0
        for legacy_path in legacy_paths:
            if not quiet:
                print(f"  removing legacy path: {legacy_path}")
            if legacy_path.is_dir():
                shutil.rmtree(legacy_path)
            else:
                legacy_path.unlink()
            cleaned += 1

        # ----- Step 2: Run a fresh build. -----
        # Reuse the existing build entry point in-process so the
        # migration honours the same project model and strictness
        # settings. We pass ``build_dir`` as an explicit ``output_dir``
        # because the build's resolver only honours
        # ``s0ma_project.build_dir`` for *non-synthetic* projects;
        # ``s0ma migrate-layout`` is also valid against synthetic
        # projects (consumers that have not yet adopted ``[tool.s0ma]``)
        # and still needs to write to the canonical build directory.
        build_args = argparse.Namespace(
            command="build",
            project_dir=str(project_dir),
            output_dir=str(build_dir),
            mode=args.mode,
            output_format="text",
            clean=False,
            no_cache=False,
            quiet=True,  # silence the build's own stdout in favour of our summary
            check=False,
            include=[],
            s0ma_project=s0ma_project,
        )
        rc = self._cmd_build(build_args)
        if rc != EXIT_SUCCESS:
            print(
                f"s0ma migrate-layout: post-clean build failed "
                f"(exit {rc}). The legacy paths were removed but the "
                f"flat layout was not regenerated. Inspect the build "
                f"errors and re-run.",
                file=sys.stderr,
            )
            return rc

        # ----- Step 3: Count emitted modules from the manifest. -----
        # The manifest is the canonical source of truth for what was
        # built — we read it rather than counting files on disk.
        from s0ma_dsl.codegen.build_manifest import (
            ManifestSchemaError,
            load_manifest,
        )
        try:
            manifest = load_manifest(build_dir)
            emitted = len(manifest.modules)
        except ManifestSchemaError:
            # The build succeeded but no manifest landed (e.g., zero
            # modules emitted). Fall back to a count derived from the
            # build dir's contents.
            emitted = sum(
                1 for p in build_dir.glob("*.py") if p.name != "__init__.py"
            ) if build_dir.is_dir() else 0

        # ----- Step 4: Print the one-line summary. -----
        project_label = s0ma_project.project_name
        if cleaned == 0:
            print(
                f"Migrated {project_label}: nothing to clean, "
                f"emitted {emitted} module(s) to {build_dir}."
            )
        else:
            print(
                f"Migrated {project_label}: removed {cleaned} legacy "
                f"path(s), emitted {emitted} module(s) to {build_dir}."
            )
        return EXIT_SUCCESS

    @staticmethod
    def _discover_legacy_layout_paths(
        *, project_dir: Path, build_dir: Path,
    ) -> list[Path]:
        """Return every legacy-layout path that should be deleted.

        Targets:
        - ``__s0ma_cache__/`` anywhere under *build_dir* or *project_dir*
          (pre-M6a wrote to either, depending on flags).
        - Per-layer subdirectories under *build_dir* whose name matches
          one of the four legacy architectural layers.

        We do **not** delete arbitrary subdirectories — only the four
        well-known layer names. Any other subdir is left alone (the
        defensive check on the calling side will refuse to operate on
        a build dir that has no recognisable s0ma artifacts).
        """
        legacy: list[Path] = []
        # __s0ma_cache__ wherever it appears under the build dir
        legacy.extend(iter_visible_dirs(build_dir, "__s0ma_cache__"))
        # __s0ma_cache__ anywhere under the project dir (pre-M6a's
        # default anchor was the source dir). Hidden subtrees are pruned:
        # this list is deleted, and a nested checkout of the same project
        # (``.claude/worktrees/<name>/``) owns its own build artifacts.
        if project_dir != build_dir:
            for cache_root in iter_visible_dirs(project_dir, "__s0ma_cache__"):
                if cache_root not in legacy:
                    legacy.append(cache_root)
        # Per-layer subdirs at the build dir's top level
        legacy_layers = {
            "presentation", "application", "domain", "infrastructure",
        }
        if build_dir.exists():
            for child in build_dir.iterdir():
                if child.is_dir() and child.name in legacy_layers:
                    legacy.append(child)
        # De-duplicate while preserving order; nested children disappear
        # if a parent we already plan to delete contains them.
        seen: set[Path] = set()
        unique: list[Path] = []
        for path in legacy:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            unique.append(path)
        return unique

    @staticmethod
    def _looks_like_s0ma_build(build_dir: Path) -> bool:
        """Defensive recogniser — does *build_dir* look like a s0ma build?

        The recogniser is intentionally permissive of pre-M6b layouts so
        ``s0ma migrate-layout`` can clean them. It returns True when any
        of the following are present:

        - the M6a auto-emitted ``__init__.py`` whose docstring marks
          the directory as generated by ``s0ma build``;
        - any ``.s0ma.json`` IR file (anywhere under the target);
        - any ``__s0ma_cache__/`` directory with files inside (the
          pre-M6a marker);
        - any of the legacy per-layer subdirs (these only appear under
          a s0ma build, never accidentally).
        """
        init_path = build_dir / "__init__.py"
        if init_path.is_file():
            try:
                head = init_path.read_text(encoding="utf-8")[:200]
            except OSError:
                head = ""
            if "Auto-generated by `s0ma build`" in head:
                return True
        for _ir in iter_visible_files(build_dir, "*.s0ma.json"):
            return True  # noqa: B007
        for cache in iter_visible_dirs(build_dir, "__s0ma_cache__"):
            try:
                next(iter(cache.iterdir()))
            except (StopIteration, OSError):
                continue
            return True
        legacy_layers = {
            "presentation", "application", "domain", "infrastructure",
        }
        for child in build_dir.iterdir() if build_dir.is_dir() else []:
            if child.is_dir() and child.name in legacy_layers:
                return True
        return False

    # -------------------------------------------------------------------
    # migrate-ext (s0ma consolidation M3)
    # -------------------------------------------------------------------

    def _cmd_migrate_ext(self, args: argparse.Namespace) -> int:
        """Migrate a project from the pre-2.0.0 extension family.

        Renames legacy-extension files to the ``.s0ma`` family, rewrites
        the legacy ``[tool.*]`` table in ``pyproject.toml``, and removes
        legacy cache directories. All migration logic — and every
        legacy-spelling literal — lives in ``s0ma_dsl.cli.migrate_ext``
        (see that module's docstring for the full semantics).
        """
        from s0ma_dsl.cli.migrate_ext import run_migrate_ext

        return run_migrate_ext(args)

    def _cmd_migrate(self, args: argparse.Namespace) -> int:
        """Dispatch versioned source-grammar migrations."""

        if getattr(args, "migrate_command", None) == "grammar":
            from s0ma_dsl.cli.migrate_grammar import run_migrate_grammar

            return run_migrate_grammar(args)
        print("Usage: s0ma migrate grammar [PROJECT_DIR] [--apply]", file=sys.stderr)
        return EXIT_USAGE_ERROR

    # -------------------------------------------------------------------
    # doctor (UX-M3, FR-DSL-5 v1.1)
    # -------------------------------------------------------------------

    def _cmd_doctor(self, args: argparse.Namespace) -> int:
        """Environment and project health report.

        Implementation lives in ``s0ma_dsl.cli.doctor`` per the
        migrate-ext separate-module precedent. Doctor diagnoses, it
        does not gate: exit 0 with findings; non-zero only when the
        environment itself is broken (e.g. s0ma-core unimportable).
        """
        from s0ma_dsl.cli.doctor import run_doctor

        return run_doctor(args)

    # -------------------------------------------------------------------
    # score (STD-M8, usability plan)
    # -------------------------------------------------------------------

    def _cmd_score(self, args: argparse.Namespace) -> int:
        """Report the project's self-knowledge score.

        Implementation lives in ``s0ma_dsl.cli.score`` per the
        doctor/migrate-ext separate-module precedent. Composes the three
        faculty sub-scores from existing dsl/core surfaces (no new engine;
        never imports s0ma-mcp — plan D-7). Report-only by default; with
        ``--gate`` exits non-zero below the resolved mode's floor.
        """
        from s0ma_dsl.cli.score import run_score

        return run_score(args)

    # -------------------------------------------------------------------
    # inspect
    # -------------------------------------------------------------------

    def _cmd_inspect(self, args: argparse.Namespace) -> int:
        """Query the self-model from .s0ma.json or .s0ma artifacts.

        M16 (feedback 5–6): ``<target>`` resolution order:

        1. Existing filesystem path (file or directory) — legacy form,
           unchanged. Supports ``.s0ma.json``, ``.s0ma``, and directories.
        2. Module name → ``project.build_dir/<target>.s0ma.json``. The
           project is resolved via :class:`S0maProject.discover`; the
           build manifest (M6b) is the canonical "what's in this build"
           answer when present.
        3. ``.s0ma`` source basename → looked up under each
           ``source_root``/``test_root`` and resolved through the existing
           transpile-to-temp path.

        Falls through to a friendly error listing the available modules
        from the manifest (or the source roots if the project has not
        been built yet).

        ``--all`` short-circuits the resolution chain and prints a
        project survey: one line per module with its layer, kind counts,
        and total component count.
        """
        s0ma_project: S0maProject | None = getattr(args, "s0ma_project", None)
        inspect_all = bool(getattr(args, "inspect_all", False))

        # ----- --all: project survey -----
        if inspect_all:
            return self._cmd_inspect_all(args, s0ma_project)

        # Without --all, ``target`` is required.
        if args.target is None:
            print(
                "s0ma inspect: a target (module name, path, or directory) "
                "is required unless --all is passed.",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR

        target_str = args.target
        target = Path(target_str)

        # ----- Step 1: existing filesystem path (legacy) -----
        if target.exists():
            if target.is_file() and target.suffix == ".s0ma":
                ir_files = self._resolve_s0ma_to_ir(target)
            else:
                ir_files = self._discover_ir_files(target)
            if not ir_files:
                print(f"No .s0ma.json files found at: {target_str}", file=sys.stderr)
                return EXIT_USAGE_ERROR
            return self._render_inspect(ir_files, args)

        # ----- Step 2: module name → project.build_dir/<name>.s0ma.json -----
        # Only attempt project-aware resolution when the target looks
        # like a module-name token (no path separators, no recognised
        # file suffix). This keeps "you typed a path that doesn't exist"
        # errors from being confusingly upgraded to "module not found".
        looks_like_module_name = (
            "/" not in target_str
            and "\\" not in target_str
            and not target_str.endswith(".s0ma.json")
            and not target_str.endswith(".s0ma")
        )
        if (
            looks_like_module_name
            and s0ma_project is not None
            and not s0ma_project.synthetic
        ):
            ir_path = s0ma_project.build_dir / f"{target_str}.s0ma.json"
            if ir_path.is_file():
                return self._render_inspect([ir_path], args)
            # Module name didn't resolve via build_dir — emit the
            # friendly error with the available-modules listing.
            return self._inspect_module_not_found(target_str, s0ma_project)

        # ----- Step 3: .s0ma source basename via project source/test roots -----
        if (
            looks_like_module_name
            and s0ma_project is not None
            and not s0ma_project.synthetic
        ):
            for root in (*s0ma_project.source_roots, *s0ma_project.test_roots):
                if not root.is_dir():
                    continue
                for candidate in iter_visible_files(root, f"{target_str}.s0ma"):
                    ir_files = self._resolve_s0ma_to_ir(candidate)
                    if ir_files:
                        return self._render_inspect(ir_files, args)

        # ----- Final fallback: legacy "no IR found" error -----
        # When no project context is available we keep the historical
        # error wording so existing tests (and ad-hoc invocations against
        # arbitrary paths) continue to behave as before.
        print(f"No .s0ma.json files found at: {target_str}", file=sys.stderr)
        return EXIT_USAGE_ERROR

    def _logical_structure_for_module(
        self,
        module_name: str,
        s0ma_project: S0maProject | None,
    ) -> dict[str, str] | None:
        """Return the manifest's ``{source_root, logical_path}`` for a module.

        STD-M5 (usability plan): the logical structure lives in the build
        manifest (``build.s0ma.json``), not in the per-module IR — so
        ``s0ma inspect`` reads it back from there to surface where the
        module sits in the source tree. Returns ``None`` when there is no
        resolved project, no manifest on disk yet, no matching module
        entry, or the entry recorded no structure (a synthetic build, or
        a module outside every configured root — see
        :func:`_recorded_logical_structure`). Both values are
        project-root-relative POSIX strings (INV-5).
        """
        if s0ma_project is None or s0ma_project.synthetic:
            return None
        from s0ma_dsl.codegen.build_manifest import (
            ManifestSchemaError,
            load_manifest,
        )

        try:
            manifest = load_manifest(s0ma_project.build_dir)
        except ManifestSchemaError:
            return None
        for entry in manifest.modules:
            if entry.name != module_name:
                continue
            if not entry.source_root and not entry.logical_path:
                return None
            return {
                "source_root": entry.source_root,
                "logical_path": entry.logical_path,
            }
        return None

    def _render_inspect(
        self, ir_files: list[Path], args: argparse.Namespace,
    ) -> int:
        """Load IR docs from *ir_files* and emit them per ``args.output_format``."""
        s0ma_project: S0maProject | None = getattr(args, "s0ma_project", None)
        ir_docs = []
        for ir_path in ir_files:
            try:
                data = json.loads(ir_path.read_text(encoding="utf-8"))
                validate_ir_schema_version(data)
                ir_docs.append(data)
            except IRSchemaVersionError as e:
                print(str(e), file=sys.stderr)
                return EXIT_VALIDATION_ERROR
            except (json.JSONDecodeError, OSError) as e:
                print(f"Error reading {ir_path}: {e}", file=sys.stderr)
                return EXIT_INTERNAL_ERROR

        # STD-M5: annotate each doc with its manifest-recorded logical
        # structure (source_root + logical_path) so both the text and the
        # JSON output surface where the module lives in the source tree.
        # The IR itself does not carry this — it is a manifest property —
        # so we look it up by module name and attach it under a dedicated
        # ``logical_structure`` key (absent when the project has none).
        for doc in ir_docs:
            module_name = doc.get("module", {}).get("name")
            if not isinstance(module_name, str):
                continue
            structure = self._logical_structure_for_module(
                module_name, s0ma_project,
            )
            if structure is not None:
                doc["logical_structure"] = structure

        if args.output_format == "json":
            if len(ir_docs) == 1:
                print(json.dumps(ir_docs[0], indent=2, sort_keys=True))
            else:
                print(json.dumps(ir_docs, indent=2, sort_keys=True))
        else:
            for doc in ir_docs:
                self._print_inspect_text(doc)
                if len(ir_docs) > 1:
                    print()

        return EXIT_SUCCESS

    def _list_available_modules(
        self, s0ma_project: S0maProject,
    ) -> list[str]:
        """Return the available module names for *s0ma_project*.

        The build manifest (M6b) is the source of truth when present —
        every successful ``s0ma build`` writes one. When the project has
        not been built yet, falls back to scanning ``source_roots`` and
        ``test_roots`` for ``.s0ma`` files (filename stem).
        """
        from s0ma_dsl.codegen.build_manifest import (
            ManifestSchemaError,
            load_manifest,
        )

        try:
            manifest = load_manifest(s0ma_project.build_dir)
        except ManifestSchemaError:
            manifest = None

        if manifest is not None:
            return sorted(m.name for m in manifest.modules)

        # No manifest yet — fall back to filesystem walk of declared
        # roots. This is purely the "you haven't built yet" path; the
        # manifest is the canonical answer otherwise.
        names: set[str] = set()
        for root in (*s0ma_project.source_roots, *s0ma_project.test_roots):
            if not root.is_dir():
                continue
            for s0ma_file in iter_visible_files(root, "*.s0ma"):
                names.add(s0ma_file.stem)
        return sorted(names)

    def _inspect_module_not_found(
        self, target: str, s0ma_project: S0maProject,
    ) -> int:
        """Print a friendly "module not found" message and return EXIT_USAGE_ERROR.

        Lists the available module names from the manifest (or the
        filesystem fallback) and offers a "Did you mean ...?" hint when
        a single near-match dominates by edit distance.
        """
        available = self._list_available_modules(s0ma_project)
        if not available:
            print(
                f"Module '{target}' not found. The project at "
                f"{s0ma_project.root} has no built modules — run "
                f"`s0ma build` first.",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR

        suggestion = self._suggest_module_name(target, available)
        msg = f"Module '{target}' not found. Available modules: " + ", ".join(available) + "."
        if suggestion is not None:
            msg += f" Did you mean '{suggestion}'?"
        print(msg, file=sys.stderr)
        return EXIT_USAGE_ERROR

    @staticmethod
    def _suggest_module_name(
        target: str, available: list[str],
    ) -> str | None:
        """Return the closest module name to *target* if one stands out.

        Uses :func:`difflib.get_close_matches` (Ratcliff/Obershelp). A
        suggestion is offered only when the top match has a similarity
        ratio above ``0.6``; below that threshold the noise outweighs
        the signal, and the bare available-list message is more useful
        than a guess.
        """
        matches = difflib.get_close_matches(target, available, n=1, cutoff=0.6)
        return matches[0] if matches else None

    def _cmd_inspect_all(
        self, args: argparse.Namespace, s0ma_project: S0maProject | None,
    ) -> int:
        """Implementation of ``s0ma inspect --all``.

        Reads the build manifest (M6b) for the list of modules, loads
        each ``.s0ma.json`` IR, and prints one line per module with the
        module name, layer, per-kind component counts, and total
        component count. JSON output (``--format json``) emits a list of
        objects with the same fields for machine consumption.
        """
        if s0ma_project is None or s0ma_project.synthetic:
            print(
                "s0ma inspect --all: no project resolved. Add `[tool.s0ma]` "
                "to pyproject.toml or pass --project-root.",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR

        from s0ma_dsl.codegen.build_manifest import (
            ManifestSchemaError,
            load_manifest,
        )

        try:
            manifest = load_manifest(s0ma_project.build_dir)
        except ManifestSchemaError as exc:
            print(f"s0ma inspect --all: {exc}", file=sys.stderr)
            return EXIT_USAGE_ERROR

        if not manifest.modules:
            if args.output_format == "json":
                print(json.dumps([], indent=2))
            else:
                print(
                    f"Project '{s0ma_project.project_name}' has no built "
                    f"modules in {s0ma_project.build_dir}."
                )
                self._print_adopted_files_section(s0ma_project)
            return EXIT_SUCCESS

        survey: list[dict[str, Any]] = []
        for entry in manifest.modules:
            ir_path = s0ma_project.build_dir / entry.ir
            try:
                doc = json.loads(ir_path.read_text(encoding="utf-8"))
                validate_ir_schema_version(doc)
            except IRSchemaVersionError as e:
                print(str(e), file=sys.stderr)
                return EXIT_VALIDATION_ERROR
            except (json.JSONDecodeError, OSError) as e:
                print(
                    f"Error reading {ir_path} for module '{entry.name}': {e}",
                    file=sys.stderr,
                )
                return EXIT_INTERNAL_ERROR
            mod = doc.get("module", {})
            components = doc.get("components", [])
            kind_counts: dict[str, int] = {}
            for comp in components:
                kind = str(comp.get("kind", "?"))
                kind_counts[kind] = kind_counts.get(kind, 0) + 1
            survey.append({
                "name": entry.name,
                "layer": mod.get("layer", "?"),
                "kind_counts": kind_counts,
                "components": len(components),
            })

        if args.output_format == "json":
            print(json.dumps(survey, indent=2, sort_keys=True))
            return EXIT_SUCCESS

        # Text output: aligned table. Column widths are computed from
        # the longest concrete value per column so the layout stays
        # tidy across projects of different sizes.
        name_w = max(len("Module"), *(len(row["name"]) for row in survey))
        layer_w = max(len("Layer"), *(len(str(row["layer"])) for row in survey))
        comp_w = max(
            len("Components"),
            *(len(str(row["components"])) for row in survey),
        )

        print(
            f"{'Module':<{name_w}}  {'Layer':<{layer_w}}  "
            f"{'Components':>{comp_w}}  Kind counts"
        )
        print(
            f"{'-' * name_w}  {'-' * layer_w}  "
            f"{'-' * comp_w}  {'-' * 11}"
        )
        for row in survey:
            kinds = ", ".join(
                f"{k}={v}" for k, v in sorted(row["kind_counts"].items())
            ) or "—"
            print(
                f"{row['name']:<{name_w}}  {str(row['layer']):<{layer_w}}  "
                f"{row['components']:>{comp_w}}  {kinds}"
            )
        self._print_adopted_files_section(s0ma_project)
        return EXIT_SUCCESS

    @staticmethod
    def _print_adopted_files_section(s0ma_project: S0maProject) -> None:
        """Append the adopted-files listing to ``s0ma inspect --all`` text.

        D2 (0.11.0): adopted files are part of the project's registered
        surface, so the survey lists each with its recorded content hash
        (and honestly marks records whose file has since disappeared).
        Empty when nothing is adopted — zero noise for non-adopters. The
        JSON output of ``inspect --all`` deliberately stays a flat list
        of module rows (its documented shape); the machine-readable
        adopted listing lives in ``s0ma verify --format json`` rows and
        the MCP ``project_status`` result.

        A corrupt ``adopted.s0ma.json`` surfaces as a one-line stderr
        note here (inspect is an informational surface); ``s0ma verify``
        is the surface that fails loudly on it.
        """
        from s0ma_dsl.adoption import AdoptedRecordError, load_adopted_files

        try:
            adopted_records = load_adopted_files(s0ma_project.root)
        except AdoptedRecordError as exc:
            print(f"s0ma inspect: {exc}", file=sys.stderr)
            return
        if not adopted_records:
            return
        print()
        print(f"Adopted files ({len(adopted_records)}):")
        for rel_key in sorted(adopted_records):
            record = adopted_records[rel_key]
            line = f"  {rel_key}  {record.content_hash or '(no hash recorded)'}"
            if record.description:
                line += f"  — {record.description}"
            if not (s0ma_project.root / rel_key).is_file():
                line += "  (missing on disk)"
            print(line)

    def _print_inspect_text(self, doc: dict[str, Any]) -> None:
        """Print a human-readable summary of an IR document.

        M14 (feedback 5–6): metadata fields may now contain ``\\n`` when
        the source uses YAML literal-block-scalar (``|``) form. This
        renderer detects multi-line values and prints them across
        multiple indented lines so the structure stays readable; single-
        line values render unchanged.
        """
        mod = doc.get("module", {})
        components = doc.get("components", [])
        edges = doc.get("edges", {})
        exports = _ir_semantic_value(doc.get("exports", [])) or []
        helpers = doc.get("helpers", [])
        # POST-5 (0.16.0): first-class integration declarations live in
        # their own IR section parallel to ``helpers``.
        integrations = doc.get("integrations", [])

        print(f"Module: {mod.get('name', '?')}")
        print(f"  Layer: {mod.get('layer', '?')}")
        print(f"  Version: {mod.get('version', '?')}")
        _print_inline_or_block(
            "  Intent: ", _ir_semantic_value(mod.get("intent", "?")),
            block_indent="    ",
        )
        print(f"  Source: {mod.get('source_file', '?')}")
        # STD-M5 (usability plan): surface the manifest-recorded logical
        # position in the source tree — the configured source root the
        # module came from and its path relative to that root (both
        # project-root-relative POSIX). Attached by ``_render_inspect``
        # under ``logical_structure``; absent for builds with no portable
        # anchor (synthetic projects / modules outside every root).
        logical_structure = doc.get("logical_structure")
        if isinstance(logical_structure, dict):
            logical_path = logical_structure.get("logical_path", "")
            source_root = logical_structure.get("source_root", "")
            if logical_path:
                print(f"  Logical path: {logical_path}")
            if source_root:
                print(f"  Source root: {source_root}")
        print(f"  Content hash: {mod.get('content_hash', '?')}")
        print()

        print(f"Components ({len(components)}):")
        for comp in components:
            vis = comp.get("visibility", "")
            kind = comp.get("kind", "")
            decl_type = comp.get("declaration_type", "")
            comp_fields = {
                key: _ir_semantic_value(value)
                for key, value in (comp.get("fields", {}) or {}).items()
            }
            # F3 (feedback 5–6 follow-up): nerves marked
            # ``is_page_composer: true`` carry a ``page_composer`` flag
            # in the ``[...]`` label so the role is visible at a glance.
            # The flag is appended after the standard
            # "<vis> <kind> <decl_type>" tuple, separated by a comma to
            # match the existing label-extension convention (M8's
            # ``[TEST FUNCTION nerve]``-style triplet).
            label_parts = [" ".join(filter(None, [vis, kind, decl_type]))]
            if comp_fields.get("is_page_composer"):
                label_parts.append("page_composer")
            # POST-2 (0.15.0): cells with ``category: capability |
            # behaviour`` surface the value in the bracket label so
            # readers see the high-level role at a glance, parallel to
            # the page_composer flag above.
            category = comp_fields.get("category")
            if category:
                label_parts.append(f"category={category}")
            # M-17 (POST-12f, 0.16.0): declarations carrying a
            # ``deferred:`` annotation surface a ``deferred`` flag in
            # the bracket label so the stub status is visible at a
            # glance. The reason string renders in a dedicated
            # sub-section below the row (mirrors the ``Internal
            # helpers`` rendering convention).
            deferred_reason = comp_fields.get("deferred")
            if deferred_reason is not None:
                label_parts.append("deferred")
            label = ", ".join(p for p in label_parts if p)
            print(f"  {comp.get('canonical_id', '?')} [{label}]")
            _print_block_only(
                _ir_semantic_value(comp.get("intent", "")),
                block_indent="    ",
            )
            # M18 (feedback 5–6): surface ``declares_attributes:``
            # entries so the user-facing inspect view includes the
            # structural attribute claims a nerve makes.
            declares = comp_fields.get("declares_attributes")
            if declares:
                print(
                    f"    declares_attributes: "
                    f"[{', '.join(declares)}]"
                )
            # POST-3d (0.15.0): nerves with ``internal:`` entries
            # surface their inner-helper introspection list under a
            # dedicated "Internal helpers" sub-section so a reader
            # can see the private surface at a glance without
            # scrolling the body. Helpers stay separate from the
            # component graph — they are not registered as
            # components and emit no ``register_*`` call.
            internal_helpers = comp_fields.get("internal_helpers")
            if internal_helpers:
                print(
                    f"    Internal helpers ({len(internal_helpers)}):"
                )
                for h in internal_helpers:
                    h_name = h.get("name", "?")
                    h_intent = h.get("intent")
                    if h_intent:
                        print(f"      - {h_name}: {h_intent}")
                    else:
                        print(f"      - {h_name}")
            # M-17 (POST-12a, 0.16.0): nerves declaring Python-side
            # exceptions they catch by design surface them under a
            # dedicated "Expected exceptions" sub-section so a reader
            # can see the exception envelope at a glance. The field
            # carries no validation today — it is metadata for
            # downstream tooling — but inspecting the declared
            # envelope is the primary author-facing affordance.
            expected_exceptions = comp_fields.get("expected_exceptions")
            if expected_exceptions:
                print(
                    f"    Expected exceptions: "
                    f"{', '.join(expected_exceptions)}"
                )
            # M-19 (POST-12d, 0.16.0): nerves declaring duck-typed
            # couplings (``consumes_via_dict: [{contract, param}, ...]``)
            # surface them under a dedicated "Consumes via dict" sub-
            # section. Each entry shows ``<contract> via <param>`` so
            # the registry's introspection view exposes the contract
            # relationship that would otherwise be invisible behind a
            # dict-key access shape.
            consumes_via_dict = comp_fields.get("consumes_via_dict")
            if consumes_via_dict:
                print(
                    f"    Consumes via dict ({len(consumes_via_dict)}):"
                )
                for entry in consumes_via_dict:
                    contract = entry.get("contract", "?")
                    param = entry.get("param", "?")
                    print(f"      - {contract} via param '{param}'")
            # M-19 (POST-12c, 0.16.0): MODEL cells declaring
            # ``dataclass_invariants:`` surface them under a dedicated
            # "Dataclass invariants" sub-section so a reader can see
            # the declared boolean expressions at a glance. The
            # invariants are pure metadata; s0ma does not runtime-
            # evaluate them.
            dataclass_invariants = comp_fields.get("dataclass_invariants")
            if dataclass_invariants:
                print(
                    f"    Dataclass invariants "
                    f"({len(dataclass_invariants)}):"
                )
                for inv in dataclass_invariants:
                    print(f"      - {inv}")
            # M-17 (POST-12f, 0.16.0): declarations carrying a
            # ``deferred:`` annotation surface the reason string in
            # a dedicated sub-section under the row so a reader sees
            # the stub status alongside the ``deferred`` label tag.
            deferred_reason = comp_fields.get("deferred")
            if deferred_reason is not None:
                print(f"    Deferred: {deferred_reason}")
        print()

        # M13 (feedback 5–6): helpers appear in their own ``[helpers]``
        # section. They are intentionally separate from the component
        # graph above — helpers are not registered components, but they
        # ARE introspectable, which is the whole point of the helper
        # declaration kind. The ``[helper]`` tag distinguishes their
        # rows from component rows so a reader can tell at a glance
        # which functions are part of the public surface and which are
        # module-private.
        if helpers:
            print(f"Helpers ({len(helpers)}):")
            for h in helpers:
                print(f"  {h.get('canonical_id', '?')} [helper]")
                _print_block_only(
                    _ir_semantic_value(h.get("intent", "")),
                    block_indent="    ",
                )
            print()

        # POST-5 (0.16.0): integration declarations appear in their own
        # section parallel to Helpers. Each integration entry shows the
        # canonical id, intent, declared factory + smoke-test target,
        # manifest keys, and the four auto-emitted helper names so the
        # reader sees the full public surface at a glance.
        if integrations:
            print(f"Integrations ({len(integrations)}):")
            for integ in integrations:
                print(
                    f"  {integ.get('canonical_id', '?')} "
                    f"[integration]"
                )
                _print_block_only(
                    _ir_semantic_value(integ.get("intent", "")),
                    block_indent="    ",
                )
                print(
                    f"    factory: "
                    f"{_ir_semantic_value(integ.get('factory', '?'))}"
                )
                print(
                    f"    smoke_test_primary: "
                    f"{_ir_semantic_value(integ.get('smoke_test_primary', '?'))}"
                )
                manifest = _ir_semantic_value(integ.get("manifest", {})) or {}
                if manifest:
                    print(
                        f"    manifest keys: "
                        f"{', '.join(sorted(manifest.keys()))}"
                    )
                print(
                    "    Auto-emitted helpers: get_factory, "
                    "get_manifest, smoke_test_primary, get_smoke_test"
                )
            print()

        authored = edges.get("authored", [])
        derived = edges.get("derived", [])
        verification = edges.get("verification", [])

        if authored:
            print(f"Authored edges ({len(authored)}):")
            for e in authored:
                print(
                    f"  {e.get('source', '?')} "
                    f"--[{e.get('relation', '?')}]--> "
                    f"{e.get('target', '?')}"
                )
        if derived:
            print(f"Derived edges ({len(derived)}):")
            for e in derived:
                print(
                    f"  {e.get('source', '?')} "
                    f"--[{e.get('relation', '?')}]--> "
                    f"{e.get('target', '?')}"
                )
        if verification:
            print(f"Verification edges ({len(verification)}):")
            for e in verification:
                print(f"  {e.get('test', '?')} validates {e.get('validates', '?')}")

        if exports:
            print(f"\nExports: {', '.join(exports)}")

    # -------------------------------------------------------------------
    # verify (MS 5b)
    # -------------------------------------------------------------------

    def _cmd_verify(self, args: argparse.Namespace) -> int:
        """Check transpiled .py files for drift using embedded checksums.

        Fast drift detection without running the transpiler — reads hash
        comments embedded in transpiled ``.py`` files and compares them
        against current file contents and ``.s0ma`` source files.

        M11 (feedback 5–6): a ``.py`` file with no hash comments is now
        either ``BOOTSTRAP`` (its absolute path is listed under
        ``[tool.s0ma].bootstrap_files``) or ``UNKNOWN`` (the residual
        bucket the verify check has always surfaced as a warning).
        ``BOOTSTRAP`` is informational; ``UNKNOWN`` retains the
        actionable remediation that points the author at either
        declaring the file or transpiling a ``.s0ma`` source for it.

        0.11.0 (batch-01a D2): a hash-header-less file recorded in the
        project's ``adopted.s0ma.json`` classifies as ``ADOPTED`` when
        its current content hash matches the adoption record — a
        *verified* state, checked the same way transpiled modules are —
        and ``ADOPTED_DRIFT`` (an actionable failure, exit 1, like
        EDITED) when the file changed since adoption. The remediation
        names both options in doctrine order: convert the file to a
        ``.s0ma`` source first, or re-adopt (`s0ma adopt file <path>` /
        MCP adopt_file) as an interim hash refresh. A file
        that carries transpiler hash headers is classified by them —
        a stale adoption record for a since-converted file is inert.

        Exit codes (pilot01): 0 means "verified >=1 module, clean";
        1 means drift was found (EDITED/STALE/CONFLICT/ADOPTED_DRIFT);
        4 (``EXIT_NOTHING_VERIFIED``) means the target tree contains
        zero hash-bearing modeled modules, and emits ``HOLLOW_MODEL``.
        Roster-adopted files are byte-verified but carry no canonical
        component knowledge, so adopted-only trees also exit 4. The text
        output always prints the modeled / roster-adopted / unknown triple.

        B4 (beta-prep-5): the text output is one line per file. An
        explanation that would otherwise be identical on every row of a
        status is printed once, as a note under the list, instead of
        after each row — see ``_verify_hoisted_details``. ``--format
        json`` is unchanged: every row still carries its own ``detail``.
        """
        import hashlib

        target = Path(args.target)

        # Discover .py files with hash comments
        if target.is_file():
            py_files = [target] if target.suffix == ".py" else []
        elif target.is_dir():
            py_files = iter_visible_files(target, "*.py")
        else:
            print(f"Target not found: {args.target}", file=sys.stderr)
            return EXIT_USAGE_ERROR

        if not py_files:
            print(f"No .py files found at: {args.target}", file=sys.stderr)
            return EXIT_USAGE_ERROR

        # M11: build the absolute-path set of declared bootstrap files
        # from the resolved S0maProject. ``S0maProject.discover`` already
        # resolves each entry to an absolute :class:`Path` (calling
        # ``.resolve()`` on ``root / entry``); we mirror the same on the
        # ``.py`` paths we scan so symlinks and relative-vs-absolute
        # forms cannot make the comparison miss.
        project = getattr(args, "s0ma_project", None)
        bootstrap_set: set[Path] = set()
        # G1 (feedback 5–6 cleanup): same path-set construction for the
        # explicit ``[tool.s0ma].package_markers`` declarative escape
        # hatch. Auto-detection (``is_empty_package_marker``) handles
        # the common case of empty / docstring-only ``__init__.py``
        # files; this set covers ``__init__.py`` files the author
        # explicitly classifies as markers (e.g. ones carrying
        # ``__all__`` re-exports).
        package_marker_set: set[Path] = set()
        if project is not None:
            for bf in project.bootstrap_files:
                try:
                    bootstrap_set.add(Path(bf).resolve())
                except OSError:
                    # A declared bootstrap file may not exist yet (M1
                    # surfaces a warning; we still record the path so a
                    # path comparison against a future-existing file
                    # is consistent). ``Path.resolve(strict=False)`` is
                    # the default; the bare except is defensive against
                    # a permissions race.
                    bootstrap_set.add(Path(bf))
            for pm in project.package_markers:
                try:
                    package_marker_set.add(Path(pm).resolve())
                except OSError:
                    package_marker_set.add(Path(pm))

        # D2 (0.11.0): adopted-file records — real files registered by
        # content hash via `s0ma adopt file` (adopted.s0ma.json at the
        # project root). Resolved-absolute keying mirrors the bootstrap
        # and package-marker sets above. A corrupt record file is a
        # loud validation failure, not a silent downgrade to UNKNOWN:
        # the author explicitly adopted files and deserves to know the
        # record is unreadable.
        adopted_by_path: dict[Path, tuple[str, Any]] = {}
        if project is not None:
            from s0ma_dsl.adoption import AdoptedRecordError, load_adopted_files

            try:
                adopted_records = load_adopted_files(project.root)
            except AdoptedRecordError as exc:
                print(f"s0ma verify: {exc}", file=sys.stderr)
                return EXIT_VALIDATION_ERROR
            for rel_key, adopted_record in adopted_records.items():
                candidate = project.root / rel_key
                try:
                    adopted_by_path[candidate.resolve()] = (
                        rel_key, adopted_record,
                    )
                except OSError:
                    adopted_by_path[candidate] = (rel_key, adopted_record)

        source_hash_re = re.compile(r"^# s0ma-source-hash:\s*sha256:(\w+)$", re.MULTILINE)
        output_hash_re = re.compile(r"^# s0ma-output-hash:\s*sha256:(\w+)$", re.MULTILINE)

        # B2 (0.11.0): the output-hash recompute is factored into the
        # emitter so `s0ma verify`, the build write-guard, and `s0ma
        # check`'s drift pass all detect a hand edit the same way.
        from s0ma_dsl.codegen.python_emitter import recompute_output_hash

        results: list[dict[str, object]] = []
        for py_path in py_files:
            content = py_path.read_text(encoding="utf-8")
            source_match = source_hash_re.search(content)
            output_match = output_hash_re.search(content)

            if not source_match or not output_match:
                # M11: distinguish declared bootstrap files (intentional
                # plain-Python exceptions) from genuinely-unknown files.
                # Path matching uses absolute-resolved paths on both
                # sides so symlinks and relative invocations cannot
                # smuggle an ``UNKNOWN`` past a valid bootstrap entry.
                try:
                    py_resolved = py_path.resolve()
                except OSError:
                    py_resolved = py_path
                # D2 (0.11.0): adoption wins over the exemption buckets —
                # it is the stronger claim (a hash-verified registration,
                # not a declared exception). Content-hash match → ADOPTED
                # (verified); mismatch → ADOPTED_DRIFT, an actionable
                # failure whose remediation names both ways out.
                adopted_entry = adopted_by_path.get(py_resolved)
                if adopted_entry is not None:
                    rel_key, adopted_record = adopted_entry
                    from s0ma_dsl.codegen.build_manifest import (
                        compute_file_hash,
                    )

                    current_adopted_hash = compute_file_hash(content)
                    if current_adopted_hash == adopted_record.content_hash:
                        results.append({
                            "file": _display_path(py_path),
                            "status": "ADOPTED",
                            "detail": (
                                f"registered by adoption "
                                f"({adopted_record.content_hash} verified)"
                            ),
                        })
                    else:
                        results.append({
                            "file": _display_path(py_path),
                            "status": "ADOPTED_DRIFT",
                            "detail": (
                                f"changed since adoption: content hash no "
                                f"longer matches the adopted.s0ma.json "
                                f"record; convert it to a .s0ma source so "
                                f"the logic is modeled; if it must remain "
                                f"interim migration debt, re-adopt the "
                                f"current content (`s0ma adopt file "
                                f"{rel_key} --description <intent>` / MCP "
                                f"tool adopt_file)."
                            ),
                        })
                    continue
                if py_resolved in bootstrap_set:
                    results.append({
                        "file": _display_path(py_path),
                        "status": "BOOTSTRAP",
                        "detail": (
                            "declared under [tool.s0ma].bootstrap_files "
                            "(intentional plain-Python entry point)"
                        ),
                    })
                    continue
                # G1 (feedback 5–6 cleanup): explicit declaration wins
                # over auto-detection. If the author lists the file
                # under ``[tool.s0ma].package_markers``, classify as
                # PACKAGE_MARKER even when the body is non-empty
                # (e.g. an ``__init__.py`` carrying ``__all__``
                # re-exports the author wants acknowledged as a marker
                # surface rather than reported as ``UNKNOWN``).
                if py_resolved in package_marker_set:
                    results.append({
                        "file": _display_path(py_path),
                        "status": "PACKAGE_MARKER",
                        "detail": (
                            "declared under [tool.s0ma].package_markers "
                            "(Python package marker)"
                        ),
                    })
                    continue
                # G1: auto-classify empty / docstring-only
                # ``__init__.py`` files. Reading the source via the AST
                # is more robust than a size threshold: a long docstring
                # is still a marker; any executable content (imports,
                # ``__all__``, calls) disqualifies the file. This is
                # the structural "noise floor" defense — consumers no
                # longer need to enumerate every package layer's
                # ``__init__.py`` under ``bootstrap_files``.
                if is_empty_package_marker(py_path):
                    results.append({
                        "file": _display_path(py_path),
                        "status": "PACKAGE_MARKER",
                        "detail": (
                            "auto-classified as a Python package marker "
                            "(empty or single-docstring __init__.py)"
                        ),
                    })
                    continue
                results.append({
                    "file": _display_path(py_path),
                    "status": "UNKNOWN",
                    "detail": (
                        "no checksum and not declared under "
                        "[tool.s0ma].bootstrap_files. Either declare this "
                        "file under [tool.s0ma].bootstrap_files in "
                        "pyproject.toml, or transpile a .s0ma source for it."
                    ),
                })
                continue

            embedded_source_hash = source_match.group(1)
            embedded_output_hash = output_match.group(1)

            # Check output hash — has the .py been hand-edited?
            # B2 (0.11.0): the recompute is the shared helper the build
            # write-guard and `s0ma check`'s drift pass also use, so all
            # three classify a hand edit identically (EDITED / refused /
            # GENERATED_FILE_DRIFT).
            current_output_hash = recompute_output_hash(content)
            output_matches = current_output_hash == embedded_output_hash

            # Check source hash — has the .s0ma been updated?
            # Try to find the corresponding .s0ma file
            s0ma_path = py_path.with_suffix(".s0ma")
            if s0ma_path.exists():
                s0ma_content = s0ma_path.read_text(encoding="utf-8")
                current_source_hash = hashlib.sha256(
                    s0ma_content.encode("utf-8")
                ).hexdigest()[:16]
                source_matches = current_source_hash == embedded_source_hash
            else:
                # No .s0ma file found — can't check source freshness
                source_matches = True  # Assume OK if no source to compare

            if source_matches and output_matches:
                results.append({"file": _display_path(py_path), "status": "CLEAN"})
            elif source_matches and not output_matches:
                results.append({
                    "file": _display_path(py_path),
                    "status": "EDITED",
                    "detail": ".py was modified after transpilation",
                })
            elif not source_matches and output_matches:
                results.append({
                    "file": _display_path(py_path),
                    "status": "STALE",
                    "detail": ".s0ma was updated but .py was not re-transpiled",
                })
            else:
                results.append({
                    "file": _display_path(py_path),
                    "status": "CONFLICT",
                    "detail": "both .s0ma and .py were modified independently",
                })

        # Also check .s0ma.json files for source hash staleness (MS 5b.3)
        if target.is_dir():
            ir_files = self._discover_ir_files(target)
            for ir_path in ir_files:
                try:
                    data = json.loads(ir_path.read_text(encoding="utf-8"))
                    validate_ir_schema_version(data)
                except IRSchemaVersionError as exc:
                    print(str(exc), file=sys.stderr)
                    return EXIT_VALIDATION_ERROR
                except (json.JSONDecodeError, OSError):
                    continue
                ir_source_hash = data.get("source_hash", "")
                if not ir_source_hash or not ir_source_hash.startswith("sha256:"):
                    continue
                embedded_hash = ir_source_hash.split(":", 1)[1]
                # Find corresponding .s0ma file
                ir_s0ma_path = ir_path.with_name(
                    ir_path.name.replace(".s0ma.json", ".s0ma")
                )
                if ir_s0ma_path.exists():
                    ir_s0ma_content = ir_s0ma_path.read_text(encoding="utf-8")
                    current_hash = hashlib.sha256(
                        ir_s0ma_content.encode("utf-8")
                    ).hexdigest()[:16]
                    if current_hash != embedded_hash:
                        results.append({
                            "file": str(ir_path),
                            "status": "STALE",
                            "detail": ".s0ma was updated but .s0ma.json was not re-transpiled",
                        })

        # beta-prep-1 G3b (G1's H-10, pilot G2-9): a source root holding
        # a `.s0ma` source whose build is in the manifest is not hollow.
        # Before this, `s0ma verify --all src` said "0 modeled" and
        # HOLLOW_MODEL the moment after a conversion went clean, while
        # `s0ma score` said one componentized and `s0ma adopt status`
        # said one converted — three commands, three answers, on a
        # product whose whole claim is that it knows itself. The row is
        # added only when the built `.py` is NOT itself under this
        # target, so a `verify --all .` that covers both the source and
        # the build directory still counts the module exactly once.
        results.extend(
            self._verify_converted_rows(target, project, py_files)
        )

        # 0.14 M1: only hash-bearing transpiled modules are modeled. A roster
        # adoption verifies bytes but carries no semantic component model, so
        # an adopted-only tree is hollow and exits EXIT_NOTHING_VERIFIED.
        # CONVERTED rows are modeled too: the module they name is built,
        # in the manifest, and answerable — it simply lives one directory
        # away from the source this reading is about.
        modeled_statuses = {"CLEAN", "EDITED", "STALE", "CONFLICT", "CONVERTED"}
        modeled_rows = [
            row for row in results if row.get("status") in modeled_statuses
        ]
        adopted_rows = [row for row in results if row.get("status") == "ADOPTED"]
        adopted_drift_rows = [
            row for row in results if row.get("status") == "ADOPTED_DRIFT"
        ]
        unknown_rows = [row for row in results if row.get("status") == "UNKNOWN"]
        hollow_model = not modeled_rows
        hollow_message = (
            f"{len(adopted_rows)} adopted, 0 modeled — the self-model cannot "
            "answer questions about this code"
        )
        if hollow_model:
            results.append({
                "code": "HOLLOW_MODEL",
                "status": "HOLLOW_MODEL",
                "message": hollow_message,
                "detail": (
                    "Roster adoption verifies file content only; author at least "
                    "one canonical .s0ma module and rebuild."
                ),
                "modeled": 0,
                "adopted": len(adopted_rows),
                "unknown": len(unknown_rows),
            })

        # Output
        if args.output_format == "json":
            # JSON output is the machine-readable surface: it always
            # carries every row regardless of verbosity, so consumers
            # never have to re-derive the bootstrap-vs-unknown split.
            # The printed list shape is byte-compatible with pre-pilot01
            # output (consumers parse it); only the exit code gained the
            # nothing-verified state. Precedence is trivial: an
            # EDITED/STALE/CONFLICT row is itself a checked row, so
            # issues and nothing-verified can never both hold.
            print(json.dumps(results, indent=2))
            has_issues = any(
                r["status"] in ("EDITED", "STALE", "CONFLICT", "ADOPTED_DRIFT")
                for r in results
            )
            if has_issues:
                return EXIT_VALIDATION_ERROR
            if hollow_model:
                return EXIT_NOTHING_VERIFIED
            return EXIT_SUCCESS

        # Text format — M11: BOOTSTRAP rows are hidden by default so
        # the noise floor goes to zero on every project that declares
        # its plain-Python entry points. ``--verbose`` re-introduces
        # them. UNKNOWN rows remain loud at all verbosity levels: a
        # genuinely-undeclared ``.py`` file is the warning signal the
        # check is meant to surface.
        #
        # G1 (feedback 5–6 cleanup): PACKAGE_MARKER rows follow the
        # same hidden-by-default policy as BOOTSTRAP — package markers
        # are informational, not actionable. They surface under
        # ``--verbose`` with their classification reason and are
        # included in the summary footer's count only at that
        # verbosity. The default summary line stays
        # ``OK / BOOTSTRAP / UNKNOWN`` so the consumer's signal-to-noise
        # ratio matches M11's original promise.
        # G1 (feedback 5–6 cleanup): ``--all`` is a synonym for
        # ``--verbose`` on the verify surface — both opt into the
        # full informational rendering. The OR keeps either flag
        # working independently and either flag firing both effects.
        verbose = bool(
            getattr(args, "verbose", False) or getattr(args, "show_all", False)
        )
        bootstrap_rows = [r for r in results if r["status"] == "BOOTSTRAP"]
        package_marker_rows = [
            r for r in results if r["status"] == "PACKAGE_MARKER"
        ]
        # D2 (0.11.0): adopted rows are verified registrations but not
        # transpiled modules — counted on their own so the summary and
        # coverage lines stay honest about what each number means.
        checked = modeled_rows
        unknown = unknown_rows
        total = (
            len(checked)
            + len(unknown)
            + len(bootstrap_rows)
            + len(package_marker_rows)
            + len(adopted_rows)
            + len(adopted_drift_rows)
        )

        # B4 (beta-prep-5): an explanation that is identical on every row
        # of a status is said once, under the list, rather than after
        # every row. On a freshly-adopted codebase the ``UNKNOWN``
        # remediation was printed verbatim once per file — nine copies of
        # one ~190-character sentence on the standard brownfield fixture,
        # each soft-wrapping mid-word on a normal terminal, which pushed
        # the counts that actually matter off the bottom of the screen.
        #
        # The rule is about repetition, not about ``UNKNOWN``: whichever
        # status repeats itself gets hoisted, and a status whose rows say
        # genuinely different things keeps its explanation on the row.
        # This is also the shape the documentation already promised —
        # "One line per file … and the counts underneath"
        # (``docs/s0ma_src/journeys/retrofit-existing-codebase.json``).
        #
        # ``--format json`` is untouched: every row still carries its own
        # ``detail``, because that is the surface consumers parse.
        shown_statuses = {
            str(r["status"])
            for r in results
            if str(r["status"]) not in _VERIFY_BARE_STATUSES
            and str(r["status"]) != "HOLLOW_MODEL"
        }
        if not verbose:
            shown_statuses -= _VERIFY_VERBOSE_ONLY_STATUSES
        hoisted_details = _verify_hoisted_details(results, shown_statuses)
        # Reading order, so the notes arrive in the order the statuses
        # they explain first appeared in the list (and deterministically
        # — no set iteration reaches the output).
        noted_statuses: list[str] = []

        def _row_detail(row: dict[str, object]) -> None:
            """The row's own explanation, unless it was hoisted into a note."""
            status = str(row["status"])
            if status in hoisted_details:
                if status not in noted_statuses:
                    noted_statuses.append(status)
                return
            print(f"           ({row['detail']})")

        print(f"Verifying {total} transpiled file(s)...")
        for r in results:
            status = r["status"]
            if status == "CLEAN":
                print(f"  CLEAN    {r['file']}")
            elif status == "ADOPTED":
                # Always shown, like CLEAN: a verified state the reader
                # should see, not an informational exemption.
                print(f"  ADOPTED  {r['file']}")
            elif status == "CONVERTED":
                # Always shown, for the same reason, and with its own
                # detail: the reader wants to know where the module they
                # converted actually lives now.
                print(f"  CONVERTED {r['file']}")
                _row_detail(r)
            elif status == "UNKNOWN":
                print(f"  UNKNOWN  {r['file']}")
                _row_detail(r)
            elif status == "BOOTSTRAP":
                if verbose:
                    print(f"  BOOTSTRAP {r['file']}")
                    _row_detail(r)
                # Otherwise hidden — informational only.
            elif status == "PACKAGE_MARKER":
                if verbose:
                    print(f"  PACKAGE_MARKER {r['file']}")
                    _row_detail(r)
                # Otherwise hidden — informational only.
            elif status == "HOLLOW_MODEL":
                # One synthetic row, never repeated, so it keeps its own
                # explanation next to it.
                print(f"  HOLLOW_MODEL {r['message']}")
                print(f"           ({r['detail']})")
            else:
                print(f"  {status:<8s} {r['file']}")
                _row_detail(r)
        print()

        # The hoisted explanations, one paragraph each. ``UNKNOWN`` is
        # the one status whose note is written for the reader rather than
        # reused from the row (see ``_VERIFY_UNKNOWN_NOTE``); every other
        # status's own wording is already short enough to stand as prose.
        for status in noted_statuses:
            count = sum(1 for r in results if r["status"] == status)
            explanation = (
                _VERIFY_UNKNOWN_NOTE
                if status == "UNKNOWN"
                else hoisted_details[status]
            )
            print(_verify_note(status, count, explanation))
            print()

        # M11 summary: bootstrap-recognised count is always reported so
        # the consumer can see the project's declared exception surface
        # at a glance without scanning per-file rows. G1 (feedback 5–6
        # cleanup): the PACKAGE_MARKER count is appended only under
        # ``--verbose`` — package markers are noise floor under the
        # default verbosity, the same way BOOTSTRAP rows are.
        # D2 (0.11.0): the adopted segment appears only when adoption is
        # in use, so projects that never adopt keep the exact pre-0.11.0
        # summary shape.
        adopted_in_use = bool(adopted_rows or adopted_drift_rows)
        adopted_segment = (
            f"{len(adopted_rows)} adopted file(s) verified. "
            if adopted_in_use
            else ""
        )
        if verbose:
            print(
                f"Verified {len(checked)} module(s). "
                f"{adopted_segment}"
                f"{len(bootstrap_rows)} bootstrap file(s) recognized. "
                f"{len(package_marker_rows)} package marker(s). "
                f"{len(unknown)} unknown."
            )
        else:
            print(
                f"Verified {len(checked)} module(s). "
                f"{adopted_segment}"
                f"{len(bootstrap_rows)} bootstrap file(s) recognized. "
                f"{len(unknown)} unknown."
            )

        # The coverage line is always printed as the frozen 0.14 triple:
        # hollow-model case (a .s0ma husk checking green while the
        # logic lives in unregistered plain Python) stays visible in
        # every run, not just the nothing-verified edge. D2 (0.11.0):
        # adoption is visible roster debt, never modeled gate credit.
        print(
            f"Coverage: {len(checked)} modeled s0ma module(s), "
            f"{len(adopted_rows)} roster-adopted file(s), "
            f"{len(unknown)} unknown plain-Python file(s)."
        )

        issues = [
            r for r in results
            if r["status"] in ("EDITED", "STALE", "CONFLICT", "ADOPTED_DRIFT")
        ]
        if issues:
            edited = sum(1 for r in issues if r["status"] == "EDITED")
            stale = sum(1 for r in issues if r["status"] == "STALE")
            conflict = sum(1 for r in issues if r["status"] == "CONFLICT")
            adrift = sum(
                1 for r in issues if r["status"] == "ADOPTED_DRIFT"
            )
            parts = []
            if edited:
                parts.append(f"{edited} file(s) edited directly")
            if stale:
                parts.append(f"{stale} file(s) stale")
            if conflict:
                parts.append(f"{conflict} file(s) in conflict")
            if adrift:
                parts.append(
                    f"{adrift} adopted file(s) changed since adoption"
                )
            print(", ".join(parts) + ".")
            # A build refuses to overwrite a hand edit (GENERATED_FILE_DRIFT)
            # until the source carries it or --force discards it, so "run
            # `s0ma build`" is only the whole answer for a stale file.
            if edited or conflict:
                print(
                    "For edited files: move the hand edits into the .s0ma "
                    "source and run `s0ma build`, or discard them with "
                    "`s0ma build --force`."
                )
            if stale:
                print(
                    "For stale files: run `s0ma build` to re-transpile from "
                    ".s0ma sources."
                )
            if adrift:
                print(
                    "For drifted adopted files: convert the file to a "
                    ".s0ma component first. If it must remain interim "
                    "migration debt, refresh the hash with `s0ma adopt "
                    "file <path> --description <intent>`."
                )
            return EXIT_VALIDATION_ERROR

        # Pilot01: a tree with zero checked rows has no s0ma artifacts
        # at all — "All files are clean." would be a vacuous pass.
        # BOOTSTRAP/PACKAGE_MARKER-only trees land here too
        # (deliberate: informational rows are not verified modules).
        if hollow_model:
            print(
                f"HOLLOW_MODEL: {hollow_message}. "
                "Roster adoption verifies bytes but does not create an "
                "authoritative component model."
            )
            return EXIT_NOTHING_VERIFIED

        print("All files are clean.")
        return EXIT_SUCCESS

    @staticmethod
    def _shown_root(source_root: Path, project_dir: Path) -> str:
        """A configured root as the author wrote it, forward-slashed (NFR-7)."""
        try:
            return source_root.relative_to(project_dir).as_posix()
        except ValueError:  # pragma: no cover - roots resolve inside the root
            return source_root.name

    @staticmethod
    def _verify_converted_rows(
        target: Path,
        project: S0maProject | None,
        py_files: Sequence[Path],
    ) -> list[dict[str, object]]:
        """``CONVERTED`` rows for the ``.s0ma`` sources under *target*.

        A converted module is a ``.s0ma`` source here whose build is in
        the project's manifest. It is modeled — it is the most modeled
        thing a project has — and before this it was invisible to
        ``s0ma verify``, which reads ``.py`` files: a source root whose
        modules had all been converted reported ``HOLLOW_MODEL``, "0
        modeled", while ``s0ma score`` and ``s0ma adopt status`` counted
        them (G1's H-10, pilot G2-9).

        A row is emitted only when the built ``.py`` is **not** itself
        among *py_files*: with a target that covers the build directory
        as well as the source (``s0ma verify --all .`` on a flat tree)
        the built file is already being verified, and counting the source
        beside it would report one module as two.

        Never reads the source, never imports anything, and returns rows
        sorted by path so two runs print the same bytes.
        """
        from s0ma.bootstrap import ManifestSchemaError

        from s0ma_dsl.codegen.build_manifest import load_manifest

        if project is None or project.synthetic or not target.is_dir():
            return []
        try:
            manifest = load_manifest(project.build_dir)
        except (ManifestSchemaError, OSError, ValueError):
            return []

        def resolved(path: Path) -> Path:
            try:
                return path.resolve()
            except OSError:  # pragma: no cover - resolve fails on a broken tree
                return path

        already = {resolved(path) for path in py_files}
        by_source: dict[Path, tuple[str, Path]] = {}
        for entry in manifest.modules:
            logical = str(getattr(entry, "logical_path", "") or "")
            source_root = str(getattr(entry, "source_root", "") or "")
            if logical:
                candidate = project.root / source_root / logical
            else:
                # Pre-STD-M5 manifests and synthetic builds record only
                # the source string; it is project-relative POSIX when a
                # project was resolved and an as-passed path otherwise.
                raw = Path(str(entry.source))
                candidate = raw if raw.is_absolute() else project.root / raw
            by_source[resolved(candidate)] = (entry.name, project.build_dir / entry.output)

        rows: list[dict[str, object]] = []
        for source in sorted(iter_visible_files(target, "*.s0ma")):
            found = by_source.get(resolved(source))
            if found is None:
                continue
            name, built = found
            if resolved(built) in already or not built.is_file():
                continue
            try:
                shown = built.resolve().relative_to(project.root).as_posix()
            except (OSError, ValueError):  # pragma: no cover - build_dir is inside
                shown = built.name
            rows.append({
                "file": str(source),
                "status": "CONVERTED",
                "detail": f"converted — built at {shown}, module {name}",
            })
        return rows

    def _cmd_verify_host(self, args: argparse.Namespace) -> int:
        """Run the explicit, project-code-executing host verification."""
        from s0ma_dsl.host_verification import (
            HostVerificationUsageError,
            verify_host,
        )

        project: S0maProject = args.s0ma_project
        try:
            report = verify_host(
                project,
                explicit_python=args.python,
                gate_mode=args.gate_mode,
                module_timeout_seconds=args.module_timeout,
                run_timeout_seconds=args.timeout,
            )
        except HostVerificationUsageError as exc:
            if args.output_format == "json":
                print(json.dumps({
                    "schema": "s0ma-host-verification@1",
                    "ok": False,
                    "gate_mode": args.gate_mode,
                    "interpreter": None,
                    "modules": [],
                    "dependencies": [],
                    "diagnostics": [],
                    "duration_ms": 0,
                    "gate": {
                        "mode": args.gate_mode,
                        "passes": False if args.gate_mode else None,
                        "reasons": [str(exc)],
                    },
                    "error": str(exc),
                }, indent=2, sort_keys=True))
            else:
                print(f"verify-host refused: {exc}", file=sys.stderr)
            return EXIT_USAGE_ERROR

        if args.output_format == "json":
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            interpreter = report["interpreter"]
            print(
                f"Host Python: {interpreter['resolved_path']} "
                f"({interpreter['implementation']} "
                f"{interpreter['python_version']}; "
                f"{interpreter['platform']})"
            )
            for module in report["modules"]:
                print(
                    f"  {module['outcome'].upper():<7} {module['name']} "
                    f"({module['duration_ms']} ms)"
                )
                if module["stderr_tail"]:
                    print(f"           {module['stderr_tail']}")
            for diagnostic in report["diagnostics"]:
                print(f"  [{diagnostic['code']}] {diagnostic['message']}")
                print(f"    Remediation: {diagnostic['remediation']}")
            gate = report["gate"]
            if gate["passes"] is None:
                print("Host gate: report-only (mode not pinned by caller)")
            else:
                print(
                    f"Host gate ({gate['mode']}): "
                    f"{'PASS' if gate['passes'] else 'FAIL'}"
                )
            print(
                "Release acceptance is the pair: static check with the "
                "same gate mode, then this explicit host verification."
            )
        return EXIT_SUCCESS if report["ok"] else EXIT_VALIDATION_ERROR

    # -------------------------------------------------------------------
    # graph
    # -------------------------------------------------------------------

    def _cmd_graph(self, args: argparse.Namespace) -> int:
        """Emit dependency graph data from .s0ma.json artifacts.

        M1 (studi0 v1): aggregation lives in
        :func:`s0ma_dsl.graph_export.collect_graph` — the single graph
        contract every consumer (this command, the studi0 viewer) reads
        through. This handler only chooses a rendering. The ``text`` and
        ``dot`` formats consume the summary payload and are unchanged;
        ``json`` emits the versioned ``s0ma-graph@2`` document, whose
        ``nodes`` / ``edges.authored`` / ``edges.derived`` keep their
        historical content exactly.
        """
        target = Path(args.target)
        detail = getattr(args, "detail", DETAIL_SUMMARY)

        try:
            graph_data = collect_graph(target, detail=detail)
        except NoIRArtifactsError:
            print(f"No .s0ma.json files found at: {args.target}", file=sys.stderr)
            return EXIT_USAGE_ERROR
        except IRSchemaVersionError as e:
            print(str(e), file=sys.stderr)
            return EXIT_VALIDATION_ERROR
        except IRReadError as e:
            print(str(e), file=sys.stderr)
            return EXIT_INTERNAL_ERROR

        all_nodes: list[str] = graph_data["nodes"]
        all_authored: list[dict[str, Any]] = graph_data["edges"]["authored"]
        all_derived: list[dict[str, Any]] = graph_data["edges"]["derived"]

        if args.output_format == "json":
            print(json.dumps(graph_data, indent=2, sort_keys=True))

        elif args.output_format == "dot":
            print("digraph s0ma {")
            print("  rankdir=LR;")
            print('  node [shape=box, fontname="Helvetica"];')
            for node in all_nodes:
                safe = node.replace("::", "__").replace('"', '\\"')
                label = node.replace('"', '\\"')
                print(f'  "{safe}" [label="{label}"];')
            for edge in all_authored:
                src = edge.get("source", "").replace("::", "__").replace('"', '\\"')
                tgt = edge.get("target", "").replace("::", "__").replace('"', '\\"')
                rel = edge.get("relation", "").replace('"', '\\"')
                print(f'  "{src}" -> "{tgt}" [label="{rel}"];')
            for edge in all_derived:
                src = edge.get("source", "").replace("::", "__").replace('"', '\\"')
                tgt = edge.get("target", "").replace("::", "__").replace('"', '\\"')
                rel = edge.get("relation", "").replace('"', '\\"')
                print(f'  "{src}" -> "{tgt}" [label="{rel}", style=dashed];')
            print("}")

        else:
            # Text format
            print("Dependency Graph")
            print("=" * 40)
            print(f"Nodes: {len(all_nodes)}")
            print(f"Authored edges: {len(all_authored)}")
            print(f"Derived edges: {len(all_derived)}")
            print()
            for edge in all_authored:
                print(
                    f"  {edge.get('source', '?')} "
                    f"--[{edge.get('relation', '?')}]--> "
                    f"{edge.get('target', '?')}"
                )
            for edge in all_derived:
                print(
                    f"  {edge.get('source', '?')} "
                    f"~~[{edge.get('relation', '?')}]~~> "
                    f"{edge.get('target', '?')}  (derived)"
                )

        return EXIT_SUCCESS

    # -------------------------------------------------------------------
    # studi0 (M1, studi0 v1)
    # -------------------------------------------------------------------

    def _cmd_studi0(self, args: argparse.Namespace) -> int:
        """Launch the studi0 viewer for a project (optional package).

        The transpiler does not depend on ``s0ma-studi0``: the import is
        deferred to this handler so the viewer stays an install-time
        opt-in. When it is absent the command prints one structured hint
        block naming what studi0 is and how to install it, and exits
        with the CLI's usage-error code.

        ``importlib`` is used rather than a bare ``import`` statement so
        the dependency stays genuinely optional from the type checker's
        point of view as well as the installer's.
        """
        import importlib

        project_root = (
            Path(args.project_root) if args.project_root else Path.cwd()
        )

        try:
            studi0 = importlib.import_module("s0ma_studi0")
        except ImportError:
            # Deliberately not an error-code diagnostic: nothing about
            # the project is wrong, the optional viewer is simply not
            # installed. One block, in the house hint shape.
            print(
                "s0ma studi0: the optional `s0ma-studi0` package is "
                "not importable in this environment.\n"
                "studi0 is the local viewer for a built s0ma project: "
                "it serves this project's component graph — the same "
                "graph `s0ma graph --format json --detail full` emits "
                "— on 127.0.0.1 and repaints it as builds land. It "
                "reads build artifacts only and never writes to the "
                "project.\n"
                "Remediation:\n"
                "  - Install the `s0ma-studi0` wheel next to the other s0ma "
                "packages: the keyed installer from the hosting "
                "getting-started guide does this for you; from a source "
                "checkout, build and install the studi0 wheel. "
                "(s0ma is not on PyPI - PRD NFR-8.)\n"
                f"  - Then re-run `s0ma studi0 {project_root}`.",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR

        exit_code: int = studi0.launch(
            project_root,
            port=args.port,
            open_browser=not args.no_open,
        )
        return exit_code

    # -------------------------------------------------------------------
    # topo (M10 — feedback 5–6)
    # -------------------------------------------------------------------

    def _cmd_topo(self, args: argparse.Namespace) -> int:
        """Print the project's topological module import order.

        Walks the project's ``.s0ma`` files (no build artifact required),
        parses every module enough to read its ``module:`` block, and
        runs Kahn's algorithm over the ``uses:`` edges. Output is one
        module per line in dependency-first order.

        Cycle detection: if the ``uses:`` graph contains a cycle, the
        command surfaces ``MODULE_DEPENDENCY_CYCLE`` (severity ``error``
        in every mode) and exits non-zero — the same diagnostic
        ``s0ma build`` would emit. The cycle's modules are listed in
        the message.
        """
        from s0ma_dsl.resolver.topological import (
            ModuleDependencyCycleError,
            compute_topological_order,
        )

        mode = StrictnessMode(args.mode)
        project_dir = Path(args.project_dir)
        if not project_dir.is_dir():
            print(f"Not a directory: {args.project_dir}", file=sys.stderr)
            return EXIT_USAGE_ERROR

        target_files = _discover_s0ma_files(str(project_dir))
        if not target_files:
            print(f"No .s0ma files found in: {args.project_dir}", file=sys.stderr)
            return EXIT_USAGE_ERROR

        # Parse just enough of each file to reach ``module:``. Reuses
        # the standard parser so any structural error (PARSE_ERROR,
        # MISSING_FIELD, etc.) surfaces with the same diagnostic shape
        # the user sees from ``s0ma check`` or ``s0ma build``.
        all_diagnostics: list[S0maError] = []
        modules_by_name: dict[str, S0maModule] = {}
        filenames: dict[str, str] = {}
        topo_s0ma_project = getattr(args, "s0ma_project", None)
        topo_effective_to_file: dict[str, str] = {}
        for source_path in target_files:
            module, parse_errors = _parse_single_file(source_path, mode)
            all_diagnostics.extend(parse_errors)
            if module is not None:
                declared_name = module.module.name
                effective_name = (
                    topo_s0ma_project.effective_module_name(
                        declared_name, source_path,
                    )
                    if topo_s0ma_project is not None
                    else declared_name
                )
                if effective_name in topo_effective_to_file:
                    existing_file = topo_effective_to_file[effective_name]
                    all_diagnostics.append(S0maError(
                        code="MODULE_NAME_COLLISION",
                        message=(
                            f"Module '{declared_name}' found in both "
                            f"'{existing_file}' and "
                            f"'{source_path}'."
                        ),
                        file=str(source_path),
                        line=1,
                        column=0,
                        severity="error",
                        remediation=_module_collision_suggestion(
                            declared_name,
                            existing_file,
                            str(source_path),
                            topo_s0ma_project,
                        ),
                    ))
                    continue
                modules_by_name[declared_name] = module
                filenames[declared_name] = str(source_path)
                topo_effective_to_file[effective_name] = str(source_path)

        blocking = [d for d in all_diagnostics if d.severity == "error"]
        if blocking:
            _print_diagnostics(
                all_diagnostics,
                output_format=args.output_format,
                files_processed=len(target_files),
                mode=args.mode,
                quiet=False,
            )
            return EXIT_VALIDATION_ERROR

        try:
            order = compute_topological_order(modules_by_name)
        except ModuleDependencyCycleError as cycle_err:
            anchor_file = (
                filenames.get(cycle_err.cycle_modules[0])
                if cycle_err.cycle_modules
                else str(target_files[0])
            )
            cycle_diag = S0maError(
                code="MODULE_DEPENDENCY_CYCLE",
                message=str(cycle_err),
                file=anchor_file or str(target_files[0]),
                line=1,
                column=0,
                severity="error",
                remediation=(
                    f"Break the cycle by removing one of the uses: "
                    f"entries in the chain among modules: "
                    f"{', '.join(cycle_err.cycle_modules)}."
                ),
                context={"cycle_modules": list(cycle_err.cycle_modules)},
            )
            _print_diagnostics(
                [cycle_diag],
                output_format=args.output_format,
                files_processed=len(target_files),
                mode=args.mode,
                quiet=False,
            )
            return EXIT_VALIDATION_ERROR

        if args.output_format == "json":
            print(json.dumps({"topological_import_order": list(order)}, indent=2))
        else:
            for name in order:
                print(name)
        return EXIT_SUCCESS

    # -------------------------------------------------------------------
    # new (MS 12)
    # -------------------------------------------------------------------

    def _cmd_new(self, args: argparse.Namespace) -> int:
        """Scaffold a new .s0ma file from a template.

        UX-M3 (FR-DSL-5 v1.1): ``s0ma new project <dir>`` initializes a
        whole project (config table, starter module, first build,
        printed bootstrap snippet); that path lives in
        ``s0ma_dsl.cli.new_project`` per the migrate-ext
        separate-module precedent.
        """
        if args.type == "project":
            from s0ma_dsl.cli.new_project import run_new_project

            return run_new_project(args)

        decl_type: str = args.type
        name: str = args.name
        layer: str = args.layer
        kind: str | None = args.kind
        output_dir = Path(args.output_dir)

        # Validate kind for the declaration type
        nerve_kinds = {"SERVICE", "FUNCTION", "ADAPTER", "ORCHESTRATOR"}
        cell_kinds = {"MODEL", "CONSTANT", "CONFIG", "ENUM", "EXCEPTION", "TYPE"}

        if decl_type in ("module", "nerve"):
            if kind is None:
                kind = "SERVICE"
            elif kind not in nerve_kinds:
                print(
                    f"Invalid kind '{kind}' for nerve. "
                    f"Valid: {', '.join(sorted(nerve_kinds))}",
                    file=sys.stderr,
                )
                return EXIT_USAGE_ERROR
        elif decl_type == "cell":
            if kind is None:
                kind = "MODEL"
            elif kind not in cell_kinds:
                print(
                    f"Invalid kind '{kind}' for cell. "
                    f"Valid: {', '.join(sorted(cell_kinds))}",
                    file=sys.stderr,
                )
                return EXIT_USAGE_ERROR
        elif decl_type == "test" and kind is not None:
            print(
                "--kind is not applicable for 'test' declarations.",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR

        content = _scaffold_template(decl_type, name, layer, kind)

        output_dir.mkdir(parents=True, exist_ok=True)
        # Use snake_case filename (same derivation as the module header
        # in _scaffold_template, so filename and module name agree).
        snake_name = _snake_case(name)
        filename = snake_name + ".s0ma"
        out_path = output_dir / filename

        if out_path.exists():
            print(
                f"File already exists: {out_path}",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR

        # B3 (0.11.0, batch-01a): a module named after a Python stdlib
        # module cannot be imported by its bare name (the stdlib module
        # is already loaded), so the built project fails at runtime.
        # Warn at scaffold time — to stdout so the MCP scaffold_module
        # tool (which shells `s0ma new module` and captures stdout)
        # surfaces it too. The check-time MODULE_SHADOWS_STDLIB
        # diagnostic is the enforcing gate; this is the early steer.
        if decl_type == "module" and snake_name in sys.stdlib_module_names:
            print(
                f"Warning: module name '{snake_name}' shadows the Python "
                f"standard-library module '{snake_name}'. A s0ma module "
                f"with a stdlib name cannot be imported by its bare name "
                f"and will fail at runtime — rename it (e.g. "
                f"'{snake_name}_io', 'app_{snake_name}')."
            )

        out_path.write_text(content, encoding="utf-8", newline="\n")
        # Forward slashes on every OS: this line is quoted verbatim in
        # walkthroughs and committed transcripts, so it must not vary with
        # the host separator (POSIX no-op; Windows ``src\x`` -> ``src/x``).
        print(f"Created {out_path.as_posix()}")

        # Validate the generated file
        module, parse_errors = _parse_single_file(out_path, StrictnessMode.DEV)
        if parse_errors:
            blocking = [e for e in parse_errors if e.severity == "error"]
            if blocking:
                print("Warning: generated file has validation errors:")
                for err in blocking:
                    print(f"  {err.format_text()}")
                return EXIT_VALIDATION_ERROR

        print("Validation passed.")
        return EXIT_SUCCESS

    # -------------------------------------------------------------------
    # test (M7 — feedback 5–6, CRIT-3)
    # -------------------------------------------------------------------

    def _cmd_test(self, args: argparse.Namespace) -> int:
        """Project-aware pytest runner.

        Discovers the project (M1), builds every ``source_root`` and
        ``test_root`` to ``project.build_dir`` using the M6a single
        flat layout, and invokes pytest as a subprocess.

        The pytest subprocess inherits ``PYTHONPATH = <build_dir>``
        (so cross-module imports resolve) and is invoked with
        ``-o python_files=test_*.py *_tests.py`` (so both naming
        conventions are picked up — pre-M7, the default
        ``test_*.py`` glob silently missed every ``*_tests.py`` file
        emitted by the s0ma transpiler).

        F2 (feedback 5–6 follow-up): the invocation also passes
        ``--ignore=<abs_path>`` for the hidden ``.s0ma.cache/``
        directory and any legacy ``__s0ma_cache__/`` directories that
        could be sitting at the build dir, project root, source
        roots, or test roots. The cache directory holds transpiled
        ``.py`` artifacts that match the ``python_files`` glob and
        would otherwise be double-collected (causing
        ``RegistrationError: Component 'X' is already registered``).
        Cache exclusion is unconditional — pytest accepts non-existent
        ``--ignore`` paths harmlessly, so no preflight check is needed.

        Args after ``--`` on the command line reach pytest verbatim.
        The ``--`` split happens in :meth:`run` before argparse runs,
        so flags like ``-o``, ``-k``, ``--maxfail`` cannot be
        consumed by ``s0ma test``'s own parser.

        Preflight (no silent failures):
        * pytest must be importable in the active environment
          (otherwise exit code 2 with a remediation pointing at
          ``pip install pytest``).
        * The project must declare at least one ``test_root``
          (otherwise a friendly notice tells the user to add
          ``test_roots = ["tests"]`` to ``[tool.s0ma]``).

        See ``docs/s0ma-dsl-spec-v0.13.0.md`` §4.15
        (Test Execution) and ``docs/coding_agent_handbook.md``
        (`s0ma test` runner internals) for the full contract.
        """
        import importlib.util
        import subprocess

        # Preflight: pytest importable in this environment.
        if importlib.util.find_spec("pytest") is None:
            print(
                "s0ma test: pytest is not importable in the active "
                "environment.\n"
                "Install pytest in the active environment: "
                "`pip install pytest`.",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR

        s0ma_project: S0maProject = args.s0ma_project

        # Preflight: at least one test root must be configured.
        if not s0ma_project.test_roots:
            print(
                "s0ma test: no tests configured.\n"
                "Add `test_roots = [\"tests\"]` under `[tool.s0ma]` "
                "in pyproject.toml.",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR

        # If the user supplied an explicit positional ``test_dir``,
        # narrow the test build to it — otherwise we build every
        # configured test_root. Source roots are always built so
        # cross-module imports resolve. (CRIT-3.)
        explicit_test_dir = (
            Path(args.test_dir).resolve() if args.test_dir else None
        )
        if explicit_test_dir is not None and not explicit_test_dir.is_dir():
            print(
                f"s0ma test: not a directory: {args.test_dir}",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR

        # G5 (feedback 5–6 cleanup): conftest staleness pre-flight.
        # The canonical generated location is ``<project.root>/conftest.py``
        # (matches ``s0ma test-conftest``'s default --output relative
        # to the user's invocation cwd, which for project-aware
        # invocations is the project root). The classifier returns one
        # of five states; we act on three of them and pass through the
        # other two:
        #   - ``absent``: skip — the project doesn't use a generated
        #     conftest (the M11+ runner doesn't require one).
        #   - ``current``: proceed — banner version matches.
        #   - ``untouched_stale``: regenerate non-destructively with a
        #     one-line stderr notice, then proceed. Only fires for
        #     entries explicitly registered in
        #     ``STALE_GENERATED_CONFTEST_VERSION_CHECKSUMS``; the
        #     initial-G5 registry is empty so this branch never fires
        #     today (every pre-G5 conftest is ``unrecognized`` →
        #     handled below as ``customized_stale``).
        #   - ``customized_stale`` / ``unrecognized``: refuse to proceed.
        #     Surface ``STALE_GENERATED_CONFTEST`` with a remediation
        #     pointing at ``s0ma test-conftest --force``. Loud, explicit,
        #     non-destructive of user customizations.
        conftest_path = s0ma_project.root / "conftest.py"
        classification = _classify_conftest(conftest_path)
        if classification == "untouched_stale":
            from s0ma_dsl import __version__ as _dsl_version
            banner_version, _ = _parse_conftest_banner(
                conftest_path.read_text(encoding="utf-8")
            )
            kinds_used, layers_used = _collect_kinds_and_layers(
                s0ma_project.root
            )
            conftest_path.write_text(
                _generate_conftest(kinds_used, layers_used),
                encoding="utf-8",
                newline="\n",
            )
            print(
                f"s0ma-dsl: regenerated stale conftest at {conftest_path} "
                f"from {banner_version} -> {_dsl_version}",
                file=sys.stderr,
            )
        elif classification in ("customized_stale", "unrecognized"):
            from s0ma_dsl import __version__ as _dsl_version
            banner_version, _ = _parse_conftest_banner(
                conftest_path.read_text(encoding="utf-8")
            )
            if banner_version is None:
                version_clause = (
                    "predates G5 (no banner) and may carry references "
                    "to internals that have since moved"
                )
            else:
                version_clause = (
                    f"was generated by s0ma-dsl {banner_version} "
                    f"(current: {_dsl_version}) and has been hand-edited "
                    f"since"
                )
            print(
                f"s0ma test: STALE_GENERATED_CONFTEST: "
                f"{conftest_path} {version_clause}.\n"
                f"Refusing to run pytest against a potentially-broken "
                f"conftest.\n"
                f"Remediation:\n"
                f"  - Inspect the file. If your customizations matter, "
                f"preserve them, then run `s0ma test-conftest --force` "
                f"to regenerate.\n"
                f"  - Otherwise, delete the file and run "
                f"`s0ma test-conftest` to regenerate cleanly.",
                file=sys.stderr,
            )
            return EXIT_VALIDATION_ERROR

        # ---- Build pass ----------------------------------------------
        # Build source_roots first (they're context for tests), then
        # the selected test root(s). All output lands in the single
        # build_dir per M6a.
        build_dir = s0ma_project.build_dir
        build_dir.mkdir(parents=True, exist_ok=True)

        # Source-root build pass — every source root that exists on
        # disk *and* contains at least one ``.s0ma`` file is built.
        # Missing or empty source roots are silently skipped:
        # consumers may declare a source_root before scaffolding any
        # source under it. Empty roots only become an error if there
        # is also no test root with content to run.
        #
        # G4 (feedback 5–6 cleanup): each per-source-root build pass
        # threads the *other* configured source roots through
        # ``--include`` so that cross-source-root ``uses:`` references
        # resolve as context modules. Pre-G4, every source root was
        # built with ``include_dirs=[]`` and a fan-out layout (e.g.
        # ``source_roots = ["application", "domain", "presentation"]``)
        # could not resolve a ``uses: domain.X`` reference from
        # ``application/foo.s0ma`` — kn0wthyself-website-2 hit this on
        # its first migration attempt (M20 finding #6). Per-root
        # iteration is preserved (it is the canonical surface for
        # build-error attribution: a parse / validation failure still
        # names the offending file's actual source-root path); only the
        # resolution context expands. Each build pass is one-shot, so
        # circular sibling-include patterns (A↔B, A→B→C→A) cannot
        # induce a cycle — the build does not recursively descend into
        # ``--include`` paths.
        source_roots_present = [
            r for r in s0ma_project.source_roots
            if r.is_dir() and _discover_s0ma_files(str(r))
        ]
        for src_root in source_roots_present:
            sibling_includes = [
                r for r in source_roots_present if r != src_root
            ]
            rc = self._run_build_for_test(
                project_dir=src_root,
                output_dir=build_dir,
                include_dirs=sibling_includes,
                mode=args.mode,
                s0ma_project=s0ma_project,
                quiet=args.quiet,
                role="source",
            )
            if rc != EXIT_SUCCESS:
                print("s0ma test: build failed; aborting.", file=sys.stderr)
                return rc

        # Test-root build pass — every test root that exists on disk
        # (or the explicit test_dir override) is built. Source roots
        # are passed as ``--include`` so cross-module ``uses:`` in the
        # test files resolve against their source counterparts.
        if explicit_test_dir is not None:
            test_roots_to_build: list[Path] = [explicit_test_dir]
        else:
            test_roots_to_build = [
                r for r in s0ma_project.test_roots if r.is_dir()
            ]
            if not test_roots_to_build:
                # No test_root exists on disk yet. This is not an
                # error — it just means there are no tests to run.
                # Surface a friendly notice rather than failing.
                # M-16 (POST-11b, 0.16.0): suppress the notice under
                # ``--quiet`` so the only stdout in a quiet run is
                # pytest's own stream (here: nothing, since there is no
                # pytest run; the exit code carries the result).
                if not args.quiet:
                    print(
                        "s0ma test: no .s0ma test files found "
                        f"(test_roots: {[str(r) for r in s0ma_project.test_roots]}).",
                    )
                return EXIT_SUCCESS

        for test_root in test_roots_to_build:
            rc = self._run_build_for_test(
                project_dir=test_root,
                output_dir=build_dir,
                include_dirs=source_roots_present,
                mode=args.mode,
                s0ma_project=s0ma_project,
                quiet=args.quiet,
                role="test",
            )
            if rc != EXIT_SUCCESS:
                print("s0ma test: build failed; aborting.", file=sys.stderr)
                return rc

        # ---- pytest invocation ---------------------------------------
        # PYTHONPATH = <build_dir> first, then any pre-existing value
        # appended. Letting <build_dir> precede the existing path
        # ensures a build's transpiled module always wins over a
        # stale install of the same name.
        env = dict(os.environ)
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            str(build_dir) + (os.pathsep + existing_pp if existing_pp else "")
        )

        # F2 (feedback 5–6 follow-up): exclude the hidden incremental
        # cache and any legacy pre-M6a cache dirs from pytest collection.
        # The cache stores transpiled `.py` artifacts that match
        # ``python_files`` and would otherwise be double-collected
        # (causing ``RegistrationError: Component 'X' is already
        # registered`` at import time and duplicate test runs).
        # ``--ignore=<absolute_path>`` is unconditional: pytest accepts
        # paths that don't exist, so the flags are harmless when the
        # cache hasn't been materialised yet (e.g. ``--no-cache`` build
        # passes, which `_cmd_test` always uses). We pass absolute paths
        # — globs would risk over-matching a user test directory whose
        # name happens to contain ``.s0ma.cache`` as a substring.
        # See `docs/s0ma-dsl-spec-v0.13.0.md` §4.15 (Test Execution) and
        # `docs/coding_agent_handbook.md` §9.4 (`s0ma test` runner
        # internals) for the user-facing contract.
        cache_ignore_roots: list[Path] = []
        # Primary anchor: the build dir itself, which is where
        # `_cmd_build` writes the cache when called via
        # `_run_build_for_test` (output_dir is set, so ``cache_anchor =
        # output_dir`` per the M6a logic at line ~1939).
        cache_ignore_roots.append(build_dir / ".s0ma.cache")
        cache_ignore_roots.append(build_dir / "__s0ma_cache__")
        # Defensive: also exclude caches that might sit at the project
        # root from any prior `s0ma build` (no `--output-dir`) or
        # pre-M6a `s0ma transpile` run that wrote into the source tree.
        # Mid-migration projects (haven't yet run `s0ma migrate-layout`)
        # are the main consumers of the legacy entries.
        project_root = s0ma_project.root
        cache_ignore_roots.append(project_root / ".s0ma.cache")
        cache_ignore_roots.append(project_root / "__s0ma_cache__")
        for src_root in s0ma_project.source_roots:
            cache_ignore_roots.append(src_root / "__s0ma_cache__")
        for test_root in s0ma_project.test_roots:
            cache_ignore_roots.append(test_root / "__s0ma_cache__")

        # Deduplicate while preserving order — multiple roots may
        # resolve to the same path (e.g. project_root == build_dir's
        # parent for some layouts), and pytest doesn't need duplicate
        # ``--ignore`` flags.
        seen: set[Path] = set()
        unique_ignores: list[Path] = []
        for p in cache_ignore_roots:
            resolved = p.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique_ignores.append(resolved)

        pytest_args: list[str] = [
            "-o", "python_files=test_*.py *_tests.py",
        ]
        for ignore_path in unique_ignores:
            pytest_args.extend(["--ignore", str(ignore_path)])
        pytest_args.append(str(build_dir))

        # PRE-9 (0.14.0): discover raw ``.py`` tests under ``test_roots``
        # that have no ``.s0ma`` sibling and add them to pytest's
        # collection. The "no .s0ma sibling" rule + the flat-layout
        # invariant (emitted .py lands in ``build_dir``, not the test
        # root) guarantees the two collection sets are disjoint.
        raw_python_tests = _discover_raw_python_tests(
            list(s0ma_project.test_roots),
        )
        for raw_test in sorted(raw_python_tests):
            pytest_args.append(str(raw_test))

        passthrough = list(getattr(args, "passthrough_args", []) or [])
        pytest_args.extend(passthrough)

        cmd = [sys.executable, "-m", "pytest", *pytest_args]
        if not args.quiet:
            print(f"\nRunning: {' '.join(cmd)}")
        result = subprocess.run(cmd, env=env, check=False)
        return result.returncode

    def _run_build_for_test(
        self,
        *,
        project_dir: Path,
        output_dir: Path,
        include_dirs: list[Path],
        mode: str,
        s0ma_project: S0maProject,
        quiet: bool,
        role: str = "source",
    ) -> int:
        """Run :meth:`_cmd_build` against *project_dir* with explicit
        output and include paths.

        Helper for :meth:`_cmd_test` — constructs the same argparse
        Namespace shape ``s0ma build`` consumes and dispatches to the
        existing build pipeline (single source of truth for transpile
        + manifest emission, M6a/M6b).

        ``role`` (added 0.14.0 / PRE-3): tags the manifest entries this
        pass will produce as ``"source"`` or ``"test"``. ``s0ma test``
        runs both passes against the same build dir, and the build
        pipeline merges the test pass into the prior source pass's
        manifest so a single ``build.s0ma.json`` carries both.
        """
        build_args = argparse.Namespace(
            command="build",
            project_dir=str(project_dir),
            output_dir=str(output_dir),
            include=[str(p) for p in include_dirs],
            mode=mode,
            output_format="text",
            no_cache=True,
            clean=False,
            check=False,
            quiet=quiet,
            s0ma_project=s0ma_project,
            _role=role,
        )
        return self._cmd_build(build_args)

    # -------------------------------------------------------------------
    # docs <subcommand> (M7)
    # -------------------------------------------------------------------

    def _cmd_adopt(self, args: argparse.Namespace) -> int:
        """Dispatch to the appropriate ``s0ma adopt <sub>`` handler.

        Seven today: ``scan`` (rung 0 of the retrofit ladder — read a
        tree and plan the conversion, writing nothing), ``init`` (rung 1
        — write the perimeter that read proposed, and nothing else),
        ``draft`` (rung 3 — turn one Python module into a ``.s0ma``
        draft, leaving the Python untouched), ``baseline`` (record what
        that Python promised, before anything is deleted),
        ``verify-parity`` (compare the built module with that record),
        ``status`` (which rung the whole project is on, and the one
        command to run now) and ``file`` (the per-file adoption
        primitive). That is the whole family the retrofit plan reserved.
        """
        from s0ma_dsl.cli.adopt_commands import cmd_adopt_file

        sub = getattr(args, "adopt_command", None)
        if sub == "scan":
            return self._cmd_adopt_scan(args)
        if sub == "init":
            return self._cmd_adopt_init(args)
        if sub == "draft":
            return self._cmd_adopt_draft(args)
        if sub == "baseline":
            return self._cmd_adopt_baseline(args)
        if sub == "verify-parity":
            return self._cmd_adopt_verify_parity(args)
        if sub == "status":
            return self._cmd_adopt_status(args)
        if sub == "file":
            return cmd_adopt_file(args)
        print(
            "Usage: s0ma adopt scan [PATH] | s0ma adopt init [PATH] | "
            "s0ma adopt draft <module or file> | "
            "s0ma adopt baseline <module or file>... | "
            "s0ma adopt verify-parity <module>... | "
            "s0ma adopt status [PATH] | s0ma adopt file <path>",
            file=sys.stderr,
        )
        return EXIT_USAGE_ERROR

    def _cmd_adopt_scan(self, args: argparse.Namespace) -> int:
        """Handler for ``s0ma adopt scan`` — rung 0 of the retrofit ladder.

        Reads an existing tree of plain Python and reports what is in it,
        what perimeter it would declare, in what order to convert it, and
        the one command to run next. Writes nothing anywhere and never
        imports the code it reads.

        A method rather than a bare dispatch to the module-level handler
        so the command is *bound*: the documentation model addresses
        ``S0maCLI``, which is a registered component, and a command whose
        handler is one of its methods binds to it at class granularity
        (``providers_cli.BOUND_TO_OWNING_CLASS``) instead of joining the
        ledger of surfaces that reach nothing the model can name. The work
        itself stays in :func:`~s0ma_dsl.cli.adopt_commands.cmd_adopt_scan`
        with the rest of the family.
        """
        from s0ma_dsl.cli.adopt_commands import cmd_adopt_scan

        return cmd_adopt_scan(args)

    def _cmd_adopt_init(self, args: argparse.Namespace) -> int:
        """Handler for ``s0ma adopt init`` — rung 1 of the retrofit ladder.

        Makes an existing tree of plain Python a s0ma project by writing
        the perimeter ``s0ma adopt scan`` proposed: a ``[tool.s0ma]``
        table appended to ``pyproject.toml`` and one marked block in
        ``AGENTS.md``. Those two files are the only ones it may write —
        no starter module, no tests, no build, and not one line of
        application code.

        A method rather than a bare dispatch to the module-level handler,
        for the reason :meth:`_cmd_adopt_scan` gives in full: the
        documentation model addresses ``S0maCLI``, which is a registered
        component, so a command whose handler is one of its methods binds
        to it at class granularity instead of joining the ledger of
        surfaces that reach nothing the model can name. The work stays in
        :func:`~s0ma_dsl.cli.adopt_commands.cmd_adopt_init`.
        """
        from s0ma_dsl.cli.adopt_commands import cmd_adopt_init

        return cmd_adopt_init(args)

    def _cmd_adopt_draft(self, args: argparse.Namespace) -> int:
        """Handler for ``s0ma adopt draft`` — the first half of rung 3.

        Turns one Python module into a ``.s0ma`` draft: structure derived
        from the file, bodies carried across byte for byte, and every
        field that says what something is *for* left as a
        ``FIXME(adopt):`` line for a person to write. The Python file is
        parsed and never imported, and it is not modified, moved or
        deleted by this command.

        A method rather than a bare dispatch to the module-level handler,
        for the reason :meth:`_cmd_adopt_scan` gives in full: the
        documentation model addresses ``S0maCLI``, which is a registered
        component, so a command whose handler is one of its methods binds
        to it at class granularity instead of joining the ledger of
        surfaces that reach nothing the model can name. The work stays in
        :func:`~s0ma_dsl.cli.adopt_commands.cmd_adopt_draft`.
        """
        from s0ma_dsl.cli.adopt_commands import cmd_adopt_draft

        return cmd_adopt_draft(args)

    def _cmd_adopt_baseline(self, args: argparse.Namespace) -> int:
        """Handler for ``s0ma adopt baseline`` — the record a conversion is judged against.

        Reads a module's Python file and writes down what it offers its
        callers into one committed file at the project root. It is the
        one artifact of the ladder that cannot be recovered: the moment
        the ``.py`` is deleted, nothing else says what it promised. The
        file is parsed and never imported, and never changed.

        A method rather than a bare dispatch to the module-level handler,
        for the reason :meth:`_cmd_adopt_scan` gives in full: the
        documentation model addresses ``S0maCLI``, which is a registered
        component, so a command whose handler is one of its methods binds
        to it at class granularity instead of joining the ledger of
        surfaces that reach nothing the model can name. The work stays in
        :func:`~s0ma_dsl.cli.adopt_commands.cmd_adopt_baseline`.
        """
        from s0ma_dsl.cli.adopt_commands import cmd_adopt_baseline

        return cmd_adopt_baseline(args)

    def _cmd_adopt_verify_parity(self, args: argparse.Namespace) -> int:
        """Handler for ``s0ma adopt verify-parity`` — did the conversion change anything?

        Compares the public surface of the module ``s0ma build`` emitted
        with the baseline captured from the Python it replaced, and names
        every difference. Exit 1 on any finding, 2 when the comparison
        cannot be made at all. It writes nothing anywhere, and the built
        module is parsed rather than imported.

        A method for the same binding reason as its siblings; the work
        stays in
        :func:`~s0ma_dsl.cli.adopt_commands.cmd_adopt_verify_parity`.
        """
        from s0ma_dsl.cli.adopt_commands import cmd_adopt_verify_parity

        return cmd_adopt_verify_parity(args)

    def _cmd_adopt_status(self, args: argparse.Namespace) -> int:
        """Handler for ``s0ma adopt status`` — where am I on the ladder?

        Reads the whole retrofit at once and answers the four questions
        somebody has when they come back to one: which rung the project
        is on, what is done, what is left, and the single next command.
        It writes nothing anywhere and never imports the code it reads,
        and it answers for a tree that is not a s0ma project yet — that
        is rung 0.

        A method for the same binding reason as its siblings, given in
        full by :meth:`_cmd_adopt_scan`; the work stays in
        :func:`~s0ma_dsl.cli.adopt_commands.cmd_adopt_status`.
        """
        from s0ma_dsl.cli.adopt_commands import cmd_adopt_status

        return cmd_adopt_status(args)

    def _cmd_docs(self, args: argparse.Namespace) -> int:
        """Dispatch to the appropriate ``s0ma docs <sub>`` handler.

        Two families under one name. ``render`` / ``verify`` /
        ``check-drift`` are the doc-declaration surface and ``compose`` /
        ``check`` are the documentation application's build and gate; both
        keep exactly the behaviour they had. ``list`` / ``show`` /
        ``search`` and the bare form are F6's read surface.

        **Bare ``s0ma docs`` shows the learning map and exits 0.** It used
        to print a usage line and exit 2. Arch §9.3 makes that one of the
        seven guaranteed ways a person finds out documentation exists at
        all, and a usage error is the one thing it must not be: somebody
        who typed the command with nothing after it was asking what is
        here, and the answer is a map, not a complaint.
        """
        from s0ma_dsl.cli.docs_commands import (
            cmd_docs_check,
            cmd_docs_check_drift,
            cmd_docs_compose,
            cmd_docs_list,
            cmd_docs_navigate,
            cmd_docs_render,
            cmd_docs_search,
            cmd_docs_show,
            cmd_docs_verify,
        )

        sub = getattr(args, "docs_command", None)
        if sub == "render":
            return cmd_docs_render(args)
        if sub == "verify":
            return cmd_docs_verify(args)
        if sub == "check-drift":
            return cmd_docs_check_drift(args)
        if sub == "compose":
            return cmd_docs_compose(args)
        if sub == "check":
            return cmd_docs_check(args)
        if sub == "list":
            return cmd_docs_list(args)
        if sub == "show":
            return cmd_docs_show(args)
        if sub == "search":
            return cmd_docs_search(args)
        return cmd_docs_navigate(args)

    # -------------------------------------------------------------------
    # examples <subcommand> (M7)
    # -------------------------------------------------------------------

    def _cmd_examples(self, args: argparse.Namespace) -> int:
        """Dispatch to the appropriate ``s0ma examples <sub>`` handler."""
        from s0ma_dsl.cli.examples_commands import cmd_examples_run

        sub = getattr(args, "examples_command", None)
        if sub == "run":
            return cmd_examples_run(args)
        print(
            "Usage: s0ma examples run <source> [name]",
            file=sys.stderr,
        )
        return EXIT_USAGE_ERROR

    # -------------------------------------------------------------------
    # feedback <subcommand> (FB-M7)
    # -------------------------------------------------------------------

    def _cmd_feedback(self, args: argparse.Namespace) -> int:
        """Dispatch to the appropriate ``s0ma feedback`` handler.

        Implementation lives in ``s0ma_dsl.cli.feedback_commands`` per the
        doctor/examples separate-module precedent. The family carries its
        own exit-code contract (plan §5.9): 0 sent · 2 declined · 3 the
        service could not be reached or refused · 4 not enrolled · 5 the
        report or the invocation cannot be used as written.
        """
        from s0ma_dsl.cli.feedback_commands import run_feedback

        return run_feedback(args)

    # -------------------------------------------------------------------
    # test-conftest (MS 12)
    # -------------------------------------------------------------------

    def _cmd_test_conftest(self, args: argparse.Namespace) -> int:
        """Generate a conftest.py that mocks the s0ma runtime."""
        project_dir = Path(args.project)
        output_path = Path(args.output)

        if not project_dir.is_dir():
            print(f"Not a directory: {args.project}", file=sys.stderr)
            return EXIT_USAGE_ERROR

        # G5 (feedback 5–6 cleanup): refuse to overwrite an existing
        # file unless --force was passed. The classifier in
        # ``_cmd_test`` is the read-side counterpart; this is the
        # write-side guard that prevents accidental clobbering of a
        # user-customized conftest. Mirrors ``s0ma new``'s default
        # safety behaviour.
        if output_path.exists() and not getattr(args, "force", False):
            print(
                f"s0ma test-conftest: refusing to overwrite existing file: "
                f"{output_path}\n"
                f"Pass --force to regenerate, or delete the file first.",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR

        # Discover and parse .s0ma files to determine what's used.
        # Helper is shared with ``_cmd_test``'s G5 auto-regeneration
        # branch so both surfaces produce byte-identical bodies for the
        # same project shape.
        kinds_used, layers_used = _collect_kinds_and_layers(project_dir)

        conftest_content = _generate_conftest(kinds_used, layers_used)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(conftest_content, encoding="utf-8", newline="\n")
        print(f"Generated {output_path}")
        return EXIT_SUCCESS

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _discover_ir_files(target: Path) -> list[Path]:
        """Discover .s0ma.json files from a path.

        M1 (studi0 v1): the implementation moved to
        :func:`s0ma_dsl.graph_export.discover_ir_files` so `graph`,
        `inspect`, and `score` share one discovery path with the studi0
        viewer. Behaviour is unchanged for all three call sites.
        """
        return discover_ir_files(target)

    @staticmethod
    def _resolve_s0ma_to_ir(s0ma_path: Path) -> list[Path]:
        """Resolve a .s0ma file to its corresponding .s0ma.json IR.

        Lookup order (M6a, feedback 5–6, ADR-007):
        1. Same directory as the .s0ma file (single-file transpile case).
        2. ``.s0ma.cache/`` under the .s0ma file's directory — the
           current internal cache root.
        3. Legacy ``__s0ma_cache__/`` for backwards-compat reads only —
           still readable so ``s0ma inspect`` works against pre-M6a
           build trees during migration. Never written.
        4. Auto-transpile to a temporary directory.
        """
        stem = s0ma_path.stem

        # Check same directory
        ir_path = s0ma_path.parent / f"{stem}.s0ma.json"
        if ir_path.exists():
            return [ir_path]

        # Check current cache, then legacy cache (read-only).
        for cache_name in (".s0ma.cache", "__s0ma_cache__"):
            cache_ir = s0ma_path.parent / cache_name / f"{stem}.s0ma.json"
            if cache_ir.exists():
                return [cache_ir]

        # Auto-transpile to temp location
        print(
            f"No pre-built .s0ma.json found for {s0ma_path.name}. "
            "Auto-transpiling..."
        )
        tmp_dir = Path(tempfile.mkdtemp(prefix="s0ma_inspect_"))
        diagnostics, outputs = _transpile_single_file(
            s0ma_path,
            mode=StrictnessMode.DEV,
            output_dir=tmp_dir,
        )
        blocking = [e for e in diagnostics if e.severity == "error"]
        if blocking:
            _print_diagnostics(diagnostics)
            return []

        generated_ir = tmp_dir / f"{stem}.s0ma.json"
        if generated_ir.exists():
            print(
                "Tip: run `s0ma build` first for faster inspect."
            )
            return [generated_ir]
        return []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_main",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "CLI entry point function for the s0ma command. Creates and runs the S0maCLI controller."
    ),
    idempotent=True,
    is_framework=True,
)
def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``s0ma`` CLI command.

    Parses arguments, dispatches to the appropriate subcommand, and
    exits with the appropriate exit code per PRD §2.8.2.
    """
    # Ensure UTF-8 output on Windows to avoid charmap codec errors
    # when diagnostic formatting uses unicode box-drawing characters.
    # The isinstance narrow is what types the call: typeshed's TextIO has no
    # .reconfigure (it lives on io.TextIOWrapper), so the bare call fails
    # mypy --platform win32. At entry-point time the streams are always
    # TextIOWrapper on a real console or redirect; anything else (e.g. a
    # capture object) would have raised AttributeError here before, so
    # skipping is strictly safer and otherwise byte-for-byte equivalent.
    if sys.platform == "win32":
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    cli = S0maCLI()
    exit_code = cli.run(argv)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
