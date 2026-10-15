"""``s0ma docs`` subcommand handlers (plan M7).

The user-facing CLI surface for the documentation subsystem:

* ``s0ma docs render``     — parse + validate + render every doc-ref /
  doc-guide in the project (or one source file). Writes ``.md`` /
  ``.html`` / ``.json`` files to declared ``output:`` paths.
* ``s0ma docs verify``     — runs validation layers 1–5 without
  rendering. Exit 0 = clean, 1 = validation errors.
* ``s0ma docs check-drift`` — re-renders every doc into memory and
  byte-compares against the committed output files. Exit 0 = clean,
  1 = drift detected.

All three reuse the same M6 renderer (``render_module_docs``) so
behaviour stays consistent with what ``s0ma build`` produced.

Those three are the *doc-declaration* surface: they parse ``.s0ma``
sources and render whatever ``doc-ref`` / ``doc-guide`` declarations they
find. C8 adds two more that are not about declarations at all:

* ``s0ma docs compose`` — the documentation application's write command.
  Composes the five providers into one ``s0ma-docs-model@1`` snapshot,
  runs every gate, and writes the declared outputs under ``docs/``.
* ``s0ma docs check``   — the same pipeline, compared instead of written.
  Byte-compares against what is committed and reports precise diffs. It
  writes nothing, ever (SDA-INV-9). It also prints the two standing
  ledgers' counts against their budgets, because a budgeted exception
  nobody sees is an exception nobody reviews (E8 hand-off 1).

The pair is deliberately not spelled ``render`` / ``check-drift``: those
names are taken by the doc-emitter surface above, which renders different
inputs to different outputs, and one name meaning two pipelines is how a
contributor ends up running the wrong one. What ADR-012 binds the pair to
is its *invocation form* (§2.2) — an explicit ``--output-dir`` resolving
to the documentation root, under a mandatory ``--project-root`` — and both
commands honour that.

F6 adds the four that are neither: the **read** surface, for a person who
wants to learn something rather than to build or gate anything.

* bare ``s0ma docs``      — the learning map: what this build knows, in
  the five parts arch §9.1 organises everything by, the paths that take a
  whole task start to finish, and the exact next commands.
* ``s0ma docs list``      — every topic of one part, each with the one
  short line its author wrote for it.
* ``s0ma docs show``      — one topic in full, through the C7 resolver.
* ``s0ma docs search``    — the resolver's ranked candidates, each with
  the reason it matched.

All four read the composed snapshot through
:mod:`~s0ma_dsl.docs_model.bundle` and compose nothing. They take no
project, touch no network, write nothing, and produce the same bytes on
every machine — which is why none of them lets argparse format anything
(B6 finding 5 measured ``s0ma --help`` at 5,256 bytes on a 40-column
terminal and 3,436 on a 200-column one).
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.errors import S0maError

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from s0ma_dsl.ast_nodes.nodes import S0maModule
    from s0ma_dsl.codegen.doc_emitter import DocHashIndex, RenderedOutput
    from s0ma_dsl.docs_model.application import Build
    from s0ma_dsl.docs_model.bundle import Snapshot
    from s0ma_dsl.docs_model.providers import Finding
    from s0ma_dsl.docs_model.resolve import (
        Candidate,
        PresentationSpec,
        TopicIndex,
        TopicView,
    )
    from s0ma_dsl.resolver.doc_resolver import ProjectIndex

__all__ = [
    "CATEGORY_KEYS",
    "CATEGORY_OF_AUTHORITY_CLASS",
    "CATEGORY_OF_CHANNEL",
    "LISTED_GROUPS",
    "NAV_BYTE_BUDGET",
    "NAV_JOURNEY_LINES",
    "NAV_MAX_COLUMNS",
    "NAV_MAX_LINES",
    "TERMINAL_CHANNEL",
    "TERMINAL_ENVELOPE",
    "TERMINAL_TRANSFORMATIONS",
    "by_category",
    "category_of_topic",
    "cmd_docs_check",
    "cmd_docs_check_drift",
    "cmd_docs_compose",
    "cmd_docs_list",
    "cmd_docs_navigate",
    "cmd_docs_render",
    "cmd_docs_search",
    "cmd_docs_show",
    "cmd_docs_verify",
    "envelope_of",
    "identity_line",
    "navigation",
    "navigation_document",
    "read_more",
    "render_terminal",
    "terminal_spec",
    "topic_index",
    "undeclared_lines",
]

# Exit codes mirror cli/main.py's PRD §2.8.2 contract.
_EXIT_SUCCESS = 0
_EXIT_VALIDATION_ERROR = 1
_EXIT_USAGE_ERROR = 2

#: What ``s0ma docs show`` exits with when the question had several equally
#: good answers. **Read-surface only**, exactly as ``EXIT_NOTHING_VERIFIED``
#: (4) is ``s0ma verify`` only: the PRD §2.8.2 codes 0–3 are the contract
#: every command keeps, and a command that needs to distinguish one more
#: outcome extends past them rather than overloading one of them.
#:
#: It is distinct from 1 on purpose. "Nothing is called that" and "several
#: things are called that" want opposite next moves from the person who
#: asked — one respells the question, the other picks from a list — and a
#: script that cannot tell them apart has to parse the text to find out.
_EXIT_AMBIGUOUS = 5


def _resolve_docs_base_dir(args: argparse.Namespace) -> Path:
    """Resolve the base directory declared ``output:`` paths render against.

    DSL-M4 (F-M5-4): ``s0ma docs render`` / ``check-drift`` must resolve
    the SAME base as ``s0ma build`` for a ``[tool.s0ma]`` project, so the
    drift gate checks the directory the build actually writes to. A8
    (T1) closed the last asymmetry: ``verify`` computed its base from the
    source path directly and had no ``--output-dir``, so it could report
    a clean project that ``render`` / ``check-drift`` saw differently.
    All three subcommands now resolve through this one function.

    The precedence mirrors the build path (``cli/main.py::_cmd_transpile``
    and the project-build ``docs_base = output_dir or project_dir``):

    1. ``--output-dir`` if given (an explicit override always wins);
    2. else the resolved project's ``build_dir`` (the directory a project
       build emits docs under — ``<build_dir>/<output:>``), when a real
       (non-synthetic) ``[tool.s0ma]`` project is resolved;
    3. else the historic synthetic-invocation rule: the source path if it
       is a directory, otherwise its parent.

    Before this fix the project arm was absent, so a project build wrote
    docs under ``<build_dir>/docs/`` while ``check-drift`` looked under the
    project root and reported spurious "missing — never rendered" drift.
    """
    source_path = Path(args.source)
    explicit = getattr(args, "output_dir", None)
    if explicit:
        return Path(explicit)
    project = getattr(args, "s0ma_project", None)
    if project is not None and not project.synthetic:
        return Path(project.build_dir)
    return source_path if source_path.is_dir() else source_path.parent


def _parse_and_validate_project(
    source: str,
    mode: StrictnessMode,
) -> tuple[
    dict[str, S0maModule],
    dict[str, str],
    list[S0maError],
]:
    """Parse + intra-module-validate every .s0ma in *source*.

    Returns ``(modules, filenames, diagnostics)``. Cross-module and
    doc-subsystem validation is layered on by the callers — this
    helper stops at the parse/intra-module boundary so callers can
    decide which downstream layers to run.
    """
    from s0ma_dsl.cli.main import (
        _analyze_derived_edges,
        _discover_s0ma_files,
        _module_collision_suggestion,
        _parse_single_file,
        _validate_single_module,
    )

    s0ma_files = _discover_s0ma_files(source)
    if not s0ma_files:
        return {}, {}, []

    diagnostics: list[S0maError] = []
    modules: dict[str, S0maModule] = {}
    filenames: dict[str, str] = {}

    for source_path in s0ma_files:
        module, parse_errors = _parse_single_file(source_path, mode)
        diagnostics.extend(parse_errors)
        if module is None:
            continue
        if module.module.name in modules:
            from s0ma_dsl.errors import S0maError
            existing_file = filenames[module.module.name]
            diagnostics.append(S0maError(
                code="MODULE_NAME_COLLISION",
                message=(
                    f"Module '{module.module.name}' found in both "
                    f"'{existing_file}' and '{source_path}'."
                ),
                file=str(source_path),
                line=1,
                column=0,
                severity="error",
                remediation=_module_collision_suggestion(
                    module.module.name,
                    existing_file,
                    str(source_path),
                    None,
                ),
            ))
            continue
        diagnostics.extend(_validate_single_module(module, source_path, mode))
        _, derived_errors = _analyze_derived_edges(module, source_path, mode)
        diagnostics.extend(derived_errors)
        modules[module.module.name] = module
        filenames[module.module.name] = str(source_path)

    return modules, filenames, diagnostics


def _run_doc_pipeline(
    source: str,
    mode: StrictnessMode,
    *,
    base_dir: Path,
) -> tuple[
    dict[str, S0maModule],
    dict[str, str],
    DocHashIndex | None,
    ProjectIndex | None,
    dict[str, list[RenderedOutput]],
    list[S0maError],
]:
    """Parse, validate, and render every doc declaration in *source*.

    Returns a tuple ``(modules, filenames, doc_hashes, project_index,
    rendered, diagnostics)`` where ``rendered`` is the per-module list
    of :class:`RenderedOutput` and ``diagnostics`` is the union of
    every validation layer's findings.

    Rendering is best-effort: if validation produces errors but a
    declaration parsed cleanly, we still attempt to render so callers
    that ignore warnings can collect the bytes.
    """
    from s0ma_dsl.codegen.doc_emitter import (
        DocRenderError,
        compute_doc_hashes,
        render_module_docs,
    )
    from s0ma_dsl.resolver.dependency import resolve_dependencies
    from s0ma_dsl.resolver.doc_resolver import build_project_index
    from s0ma_dsl.semantic.doc_validator import (
        check_release_doc_coverage,
        validate_docs,
    )

    modules, filenames, diagnostics = _parse_and_validate_project(source, mode)
    if not modules:
        return modules, filenames, None, None, {}, diagnostics

    diagnostics.extend(resolve_dependencies(
        modules, mode=mode, filenames=filenames,
    ))

    has_docs = any(
        m.doc_refs or m.doc_guides or m.examples for m in modules.values()
    )
    if has_docs:
        diagnostics.extend(
            validate_docs(modules, filenames=filenames, mode=mode)
        )
    # Release-mode coverage runs unconditionally so an empty
    # doc-subsystem (no doc-refs anywhere) still flags every uncovered
    # PUBLIC nerve.
    diagnostics.extend(check_release_doc_coverage(
        modules, mode=mode, filenames=filenames,
    ))

    rendered_by_module: dict[str, list[RenderedOutput]] = {}
    if not has_docs:
        return modules, filenames, None, None, rendered_by_module, diagnostics

    doc_hashes = compute_doc_hashes(modules, filenames=filenames)
    project_index = build_project_index(modules)

    for module_name in sorted(modules.keys()):
        module = modules[module_name]
        if not (module.doc_refs or module.doc_guides):
            continue
        try:
            rendered_by_module[module_name] = list(render_module_docs(
                module,
                index=project_index,
                hashes=doc_hashes,
                base_dir=base_dir,
            ))
        except DocRenderError as exc:
            # The code and remediation ride on the exception (ADR-013 §4):
            # they default to DOC_RENDER_ERROR plus the generic hint, so
            # every historic raise site reports exactly what it did before,
            # while DOC_SOURCE_FORMAT_UNSUPPORTED reports under its own name.
            diagnostics.append(S0maError(
                code=exc.code,
                message=str(exc),
                file=filenames.get(module_name, f"{module_name}.s0ma"),
                line=1,
                column=0,
                severity="error",
                remediation=exc.remediation or (
                    "Fix the doc declaration's format: or output: field, "
                    "or adjust the project's output directory."
                ),
            ))

    return modules, filenames, doc_hashes, project_index, rendered_by_module, diagnostics


@component(
    name="S0maDSL_cmd_docs_render",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Handler for `s0ma docs render`: parse, validate, render every doc declaration to its "
        "declared output: path."
    ),
    idempotent=True,
    is_framework=True,
)
def cmd_docs_render(args: argparse.Namespace) -> int:
    """Implement ``s0ma docs render``."""
    from s0ma_dsl.cli.main import _print_diagnostics, _split_diagnostics

    mode = StrictnessMode(args.mode)
    base_dir = _resolve_docs_base_dir(args)

    pipeline = _run_doc_pipeline(args.source, mode, base_dir=base_dir)
    modules, filenames, _hashes, _index, rendered_by_module, diagnostics = pipeline

    if not modules:
        print(f"No .s0ma files found at: {args.source}", file=sys.stderr)
        return _EXIT_USAGE_ERROR

    errors, _warnings = _split_diagnostics(diagnostics)
    if errors:
        _print_diagnostics(
            diagnostics,
            output_format=args.output_format,
            files_processed=len(modules),
            mode=args.mode,
        )
        return _EXIT_VALIDATION_ERROR

    written: list[Path] = []
    for module_name in sorted(rendered_by_module.keys()):
        for out in rendered_by_module[module_name]:
            out.output_path.parent.mkdir(parents=True, exist_ok=True)
            out.output_path.write_text(out.content, encoding="utf-8", newline="\n")
            written.append(out.output_path)

    _print_diagnostics(
        diagnostics,
        output_format=args.output_format,
        files_processed=len(modules),
        mode=args.mode,
    )

    if args.output_format == "json":
        print(json.dumps(
            {"rendered": [str(p) for p in written]},
            indent=2, sort_keys=True,
        ))
    else:
        if written:
            print(f"Rendered {len(written)} doc output(s):")
            for p in written:
                print(f"  {p}")
        else:
            print("No doc declarations to render.")
    return _EXIT_SUCCESS


@component(
    name="S0maDSL_cmd_docs_verify",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Handler for `s0ma docs verify`: runs documentation validation layers 1-5 without "
        "rendering output files."
    ),
    idempotent=True,
    is_framework=True,
)
def cmd_docs_verify(args: argparse.Namespace) -> int:
    """Implement ``s0ma docs verify``."""
    from s0ma_dsl.cli.main import _print_diagnostics, _split_diagnostics

    mode = StrictnessMode(args.mode)
    base_dir = _resolve_docs_base_dir(args)
    pipeline = _run_doc_pipeline(args.source, mode, base_dir=base_dir)
    modules, _filenames, _hashes, _index, _rendered, diagnostics = pipeline

    if not modules:
        print(f"No .s0ma files found at: {args.source}", file=sys.stderr)
        return _EXIT_USAGE_ERROR

    errors, warnings = _split_diagnostics(diagnostics)
    _print_diagnostics(
        diagnostics,
        output_format=args.output_format,
        files_processed=len(modules),
        mode=args.mode,
    )
    if not errors and args.output_format == "text":
        print(f"\nVerified {len(modules)} module(s). 0 errors, {len(warnings)} warning(s).")
    return _EXIT_VALIDATION_ERROR if errors else _EXIT_SUCCESS


@component(
    name="S0maDSL_cmd_docs_check_drift",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Handler for `s0ma docs check-drift`: re-renders every doc and byte-compares against "
        "committed output files; reports diffs."
    ),
    idempotent=True,
    is_framework=True,
)
def cmd_docs_check_drift(args: argparse.Namespace) -> int:
    """Implement ``s0ma docs check-drift``.

    Re-renders every doc declaration into memory using the M6 renderer
    pipeline and compares the bytes against whatever sits at the
    declared ``output:`` path on disk. Mismatches surface as
    :code:`DRIFT_DETECTED` diagnostics; the exit code follows the
    severity-matrix mapping for the active mode.
    """
    from s0ma_dsl.cli.main import _print_diagnostics, _split_diagnostics
    from s0ma_dsl.config import get_severity

    mode = StrictnessMode(args.mode)
    base_dir = _resolve_docs_base_dir(args)

    pipeline = _run_doc_pipeline(args.source, mode, base_dir=base_dir)
    modules, filenames, _hashes, _index, rendered_by_module, diagnostics = pipeline

    if not modules:
        print(f"No .s0ma files found at: {args.source}", file=sys.stderr)
        return _EXIT_USAGE_ERROR

    pre_render_errors, _ = _split_diagnostics(diagnostics)
    if pre_render_errors:
        _print_diagnostics(
            diagnostics,
            output_format=args.output_format,
            files_processed=len(modules),
            mode=args.mode,
        )
        return _EXIT_VALIDATION_ERROR

    drift_severity = get_severity("DRIFT_DETECTED", mode) or "error"
    drift_records: list[dict[str, Any]] = []

    for module_name in sorted(rendered_by_module.keys()):
        filename = filenames.get(module_name, f"{module_name}.s0ma")
        for out in rendered_by_module[module_name]:
            on_disk: str | None
            if out.output_path.exists():
                on_disk = out.output_path.read_text(encoding="utf-8")
            else:
                on_disk = None

            if on_disk == out.content:
                continue

            if on_disk is None:
                detail = f"{out.output_path} is missing — never rendered."
                diff_lines: list[str] = []
            else:
                diff_lines = list(difflib.unified_diff(
                    on_disk.splitlines(keepends=False),
                    out.content.splitlines(keepends=False),
                    fromfile=f"{out.output_path} (on disk)",
                    tofile=f"{out.output_path} (re-rendered)",
                    lineterm="",
                ))
                detail = (
                    f"{out.output_path} differs from re-rendered output "
                    f"({len(diff_lines)} diff line(s))."
                )

            diagnostics.append(S0maError(
                code="DRIFT_DETECTED",
                message=detail,
                file=filename,
                line=1,
                column=0,
                severity=drift_severity,
                remediation=(
                    "Run `s0ma docs render` to regenerate the file, or "
                    "revert manual edits to the rendered output."
                ),
                context={
                    "decl_kind": out.decl_kind,
                    "name": out.name,
                    "output_path": str(out.output_path),
                },
            ))
            drift_records.append({
                "decl_kind": out.decl_kind,
                "name": out.name,
                "output_path": str(out.output_path),
                "exists": on_disk is not None,
                "diff": diff_lines,
            })

    _print_diagnostics(
        diagnostics,
        output_format=args.output_format,
        files_processed=len(modules),
        mode=args.mode,
    )

    if drift_records and args.output_format == "text":
        print()
        print(f"Drift detected in {len(drift_records)} doc output(s).")
        for rec in drift_records:
            print(f"  {rec['decl_kind']}::{rec['name']} → {rec['output_path']}")
            for line in rec["diff"][:40]:
                print(f"    {line}")

    errors, _ = _split_diagnostics(diagnostics)
    return _EXIT_VALIDATION_ERROR if errors else _EXIT_SUCCESS


# ---------------------------------------------------------------------------
# The documentation application (C8)
# ---------------------------------------------------------------------------


def _resolve_application_roots(args: argparse.Namespace) -> tuple[Path, Path]:
    """The checkout to compose from, and the base to render into.

    Two different questions, and keeping them apart is what makes the
    ``--output-dir`` form mean here what it means for ``render``: an
    override of *where output lands*, never of where sources are read.

    **The checkout** is the tree every provider addresses its sources
    relative to (``docs/s0ma_src/catalog.json``, ``references/…``,
    ``packages/…``). It is the resolved project's parent when a real
    ``[tool.s0ma]`` project was resolved — ADR-012 §2.1 makes
    ``--project-root docs`` mandatory, and ``docs/``'s parent is the
    checkout — and the working directory otherwise, which is where the
    ADR's documented invocations are run from. It is accepted only if the
    catalog is actually there: composing against the wrong tree fails as
    a hundred unrelated findings, so it is refused here as one.

    **The output base** is ``--output-dir`` if given, else the checkout's
    ``docs/``. Note what it is *not*: the resolved project's ``build_dir``,
    which is the fallback the doc-emitter subcommands use. A documentation
    build whose base fell back to ``build_dir`` would put the composed
    snapshot at ``docs/_built/_generated/…``, which is the one place
    ADR-012 §1 says a structured output never goes.
    """
    from s0ma_dsl.docs_model.application import DOCS_ROOT
    from s0ma_dsl.docs_model.providers_catalog import CATALOG_FILE

    project = getattr(args, "s0ma_project", None)
    checkout = (
        Path(project.root).resolve().parent
        if project is not None and not project.synthetic
        else Path.cwd()
    )
    if not (checkout / CATALOG_FILE).is_file():
        raise _ApplicationRootError(
            f"{checkout} does not hold a documentation application: "
            f"{checkout / CATALOG_FILE} is not a file.\n"
            f"Every provider addresses its sources relative to the checkout "
            f"that holds them, so the checkout this resolves to has to be the "
            f"real one.\n"
            f"Remediation: run from the checkout root as\n"
            f"  uv run s0ma --project-root {DOCS_ROOT} docs "
            f"<compose|check> --output-dir {DOCS_ROOT}"
        )

    explicit = getattr(args, "output_dir", None)
    base = Path(explicit) if explicit else checkout / DOCS_ROOT
    return checkout, base


class _ApplicationRootError(Exception):
    """The roots a documentation build needs could not be resolved."""


def _print_findings(
    findings: Sequence[Finding],
    *,
    output_format: str,
    heading: str,
) -> None:
    """Every finding, in reporting order, never only the first.

    ADR-012 §4 charter items 6 and 7: source-located remediation for every
    failure, and independent failures collected rather than stopped at.
    """
    if output_format == "json":
        print(json.dumps(
            {
                "findings": [
                    {
                        "code": item.code,
                        "location": item.location,
                        "message": item.message,
                        "remediation": item.remediation,
                    }
                    for item in findings
                ]
            },
            indent=2,
            sort_keys=True,
        ))
        return
    if not findings:
        return
    print(f"\n{heading}: {len(findings)} finding(s).")
    for item in findings:
        print(f"\n  {item.rendered()}")
        print(f"    → {item.remediation}")


def _ledger_line(result: Build, checkout: Path) -> str:
    """The two standing ledgers, counted, in one line (E8 hand-off 1).

    A ledger nobody reads stops being a ledger. Both of these are
    decisions somebody took — a capability nothing teaches, a capability
    nothing implements — and both are budgeted rather than forbidden, so
    the number is the thing that has to be in front of whoever runs the
    gate. E8 counted them in the suite; this is where the check flow says
    them out loud.

    ``reference_only`` comes from the authored policy and ``unbound``
    from the composed bundle, which is why the line needs both the
    checkout and the build: they are ledgers about different things that
    happen to be reported together. Neither is a finding — a count within
    its budget is a clean build — so this prints alongside the outcome
    rather than as part of it.
    """
    from s0ma_dsl.docs_model.application import (
        REFERENCE_ONLY_CEILING,
        UNBOUND_CEILING,
        coverage_policy,
    )

    policy = coverage_policy(checkout)
    unbound = sum(
        1 for surface in result.bundle.surfaces if not surface.component_refs
    )
    return (
        f"Ledgers: reference_only {len(policy.surface_exceptions)}/"
        f"{REFERENCE_ONLY_CEILING} surface(s) + "
        f"{len(policy.channel_exceptions)} channel ruling(s); "
        f"unbound {unbound}/{UNBOUND_CEILING} surface(s)."
    )


def _head_tag(args: argparse.Namespace) -> str:
    """The tag the operator stated, or the empty string nobody stated.

    ``getattr`` rather than ``args.head_tag`` for the same reason
    ``output_dir`` is read that way: these two handlers are also reached
    from callers that build a namespace by hand, and a missing attribute
    there should mean "no tag" rather than an AttributeError.
    """
    return getattr(args, "head_tag", "") or ""


def _channel_line(head_tag: str, result: Build) -> str:
    """Which channel a stated tag put this build on, and why (H2b).

    Printed only when a tag was stated, so a run without ``--head-tag``
    prints exactly what it printed before the flag existed.

    The preview branch spells out the comparison rather than reporting the
    channel alone, because that is the case an operator can get wrong: a
    release cut that mistypes its tag has asked for a release build, and
    ``channel_of`` hands back a preview one without complaint — correctly,
    since a tag naming another version is not a release of this one. A
    line that said only ``preview`` would leave the typo to be discovered
    later, by a gate, in the wheels.
    """
    from s0ma_dsl.docs_model.manifest import version_tag
    from s0ma_dsl.docs_model.records import RELEASE_CHANNEL

    stamp = result.bundle.stamp
    if stamp.build_channel == RELEASE_CHANNEL:
        return f"Channel: release — {head_tag} is the tag of {stamp.release_version}."
    return (
        f"Channel: preview — {head_tag} is not "
        f"{version_tag(stamp.release_version)}, so this build is not a "
        f"release of {stamp.release_version}."
    )


def _application_build(args: argparse.Namespace) -> tuple[Build, Path, Path] | int:
    """Compose the documentation, or the exit code that says why not.

    Shared by both subcommands so the write path and the check path are
    provably the same pipeline: a check gate that composed differently
    from its writer would report drift that no write could fix. That is
    also why ``--head-tag`` is read here rather than in either handler:
    the tag decides which channel the build composes, and a check told a
    tag its writer was not told would compare two different builds.
    """
    from s0ma_dsl.docs_model.application import build
    from s0ma_dsl.docs_model.records import DocsModelError

    try:
        checkout, docs_root = _resolve_application_roots(args)
    except _ApplicationRootError as exc:
        print(f"s0ma docs: {exc}", file=sys.stderr)
        return _EXIT_USAGE_ERROR

    try:
        return build(checkout, head_tag=_head_tag(args)), docs_root, checkout
    except DocsModelError as exc:
        # A provider refusing its source, or a composition that cannot be
        # built at all. Distinct from a finding: there is no bundle to
        # report findings about.
        print(f"s0ma docs: the documentation could not be composed: {exc}", file=sys.stderr)
        return _EXIT_VALIDATION_ERROR


@component(
    name="S0maDSL_cmd_docs_compose",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Handler for `s0ma docs compose`: composes the documentation snapshot, runs every "
        "gate, and writes the declared outputs under the documentation root."
    ),
    idempotent=True,
    is_framework=True,
)
def cmd_docs_compose(args: argparse.Namespace) -> int:
    """Implement ``s0ma docs compose`` — the application's write command.

    Nothing is written unless every gate passed. SDA-INV-9 in its write
    form: a build either produces documentation that is true or produces
    nothing, so a partially-valid snapshot never reaches the tree where a
    later reader would take it for a good one.
    """
    outcome = _application_build(args)
    if isinstance(outcome, int):
        return outcome
    result, docs_root, _checkout = outcome

    if not result.ok:
        _print_findings(
            result.findings,
            output_format=args.output_format,
            heading="The documentation was not written",
        )
        return _EXIT_VALIDATION_ERROR

    from s0ma_dsl.docs_model.application import write

    written = write(result, docs_root)

    if args.output_format == "json":
        print(json.dumps(
            {
                "written": [str(path) for path in written],
                "snapshot_hash": result.bundle.stamp.snapshot_hash,
                "release_version": result.bundle.stamp.release_version,
            },
            indent=2,
            sort_keys=True,
        ))
    else:
        print(f"Composed {result.bundle.stamp.snapshot_hash}.")
        if head_tag := _head_tag(args):
            print(_channel_line(head_tag, result))
        print(f"Wrote {len(written)} artifact(s):")
        for path in written:
            print(f"  {path}")
    return _EXIT_SUCCESS


@component(
    name="S0maDSL_cmd_docs_check",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Handler for `s0ma docs check`: composes the documentation snapshot in memory and "
        "byte-compares it against the committed outputs without writing anything."
    ),
    idempotent=True,
    is_framework=True,
)
def cmd_docs_check(args: argparse.Namespace) -> int:
    """Implement ``s0ma docs check`` — the application's check command.

    Runs the identical pipeline ``compose`` runs and then compares rather
    than writes. Gate findings and drift findings are reported together,
    because a contributor who has both wants to see both: fixing the
    composition and re-running only to discover the drift is two runs for
    one job.
    """
    outcome = _application_build(args)
    if isinstance(outcome, int):
        return outcome
    result, docs_root, checkout = outcome

    from s0ma_dsl.docs_model.application import check
    from s0ma_dsl.docs_model.providers import sort_findings

    findings = sort_findings([*result.findings, *check(result, docs_root)])

    if args.output_format == "text":
        print(_ledger_line(result, checkout))
        # Before the findings, because with a tag stated the findings are
        # about the channel: a release-channel check against a
        # preview-composed tree drifts on every identity line, and the
        # reader needs to know which build they asked for before they read
        # thirty of them.
        if head_tag := _head_tag(args):
            print(_channel_line(head_tag, result))

    _print_findings(
        findings,
        output_format=args.output_format,
        heading="The documentation does not check out",
    )
    if findings:
        return _EXIT_VALIDATION_ERROR
    if args.output_format == "text":
        print(
            f"Checked {result.bundle.stamp.snapshot_hash}: "
            f"{len(result.artifacts)} artifact(s) match what is committed."
        )
    return _EXIT_SUCCESS


# ---------------------------------------------------------------------------
# The human read surface (F6)
# ---------------------------------------------------------------------------
#
# Everything below answers from a composed snapshot and composes nothing.
# The three questions it had to settle, settled here once so the four
# commands cannot each answer them differently:
#
#   1. which of arch §9.1's five parts a topic belongs to;
#   2. what a topic looks like in a terminal;
#   3. where the committed page for a topic is.


def _sections() -> tuple[Any, ...]:
    """Arch §9.1's five parts, by key and title, in §9.1's order.

    Taken from the map of record rather than restated: the titles a reader
    sees on ``docs/README.md`` and the ones they see here are the same
    authored navigation, and two copies of it would drift the day one was
    edited.
    """
    from s0ma_dsl.docs_model.map_of_record import CATEGORIES

    return CATEGORIES


CATEGORY_KEYS: tuple[str, ...] = (
    "understand",
    "build",
    "toolchain",
    "reference",
    "operate",
)

#: Which part a served capability belongs to, by the channel it is served
#: on. §9.1 files the things a person *drives* under "Use the toolchain"
#: (its sub-list is CLI, MCP, studi0) and the things a person *looks up*
#: under "Reference" (its sub-list is language, configuration, commands and
#: served surfaces, APIs and diagnostics). A configuration key and a
#: diagnostic code are looked up; a command and a tool are driven.
#:
#: Every channel :data:`~s0ma_dsl.docs_model.validate.CHANNEL_EFFECTS`
#: classifies has an entry, and a proof asserts that — a channel that fell
#: through would land its whole group in whatever the default happened to
#: be, and the count beside a category is only worth printing if nothing
#: can be missing from it silently.
CATEGORY_OF_CHANNEL: Mapping[str, str] = {
    "cli": "toolchain",
    "mcp_prompt": "toolchain",
    "mcp_resource": "toolchain",
    "mcp_tool": "toolchain",
    "studi0": "toolchain",
    "config": "reference",
    "diagnostic": "reference",
    "python": "reference",
    "rest": "reference",
}

#: Which part a written authority belongs to, by its class. Imported from
#: the map of record for the reason above and extended by exactly one
#: entry: ``declared``, which the map never meets because no *document* is
#: a declared authority, and which is looked up rather than driven.
#:
#: An unknown class falls to ``reference``, which is
#: :func:`~s0ma_dsl.docs_model.map_of_record.category_of`'s own fallback
#: and for its stated reason: "look it up here" is the promise that stays
#: true for something nobody has classified yet.
CATEGORY_OF_AUTHORITY_CLASS: Mapping[str, str] = {"declared": "reference"}

#: Which bundle groups this surface navigates, and which it does not.
#:
#: **Documents are deliberately absent, and this is the milestone's one
#: structural decision worth reading twice.** A document's part is decided
#: by facts the *catalog* holds — its kind, its standing, who it is for —
#: and :class:`~s0ma_dsl.docs_model.providers_catalog.CatalogRow` says in
#: as many words that "nothing composes a CatalogRow, nothing hashes one,
#: and no snapshot carries one". A read surface answering from a snapshot
#: therefore cannot file a document the way the map files it, and a second
#: filing invented here — from the path, say — would be a different answer
#: to the same question, published beside the first.
#:
#: So documents stay fully addressable (``show`` renders one, ``search``
#: finds one) and are *navigated* through ``docs/README.md``, which is the
#: artifact that has the facts. The navigation map names it in its last
#: line, and that line is not decoration: it is where this surface hands
#: the question over.
LISTED_GROUPS: tuple[str, ...] = (
    "authorities",
    "concepts",
    "journeys",
    "sequences",
    "surfaces",
)


def category_of_topic(view: TopicView) -> str | None:
    """Which of the five parts ``view`` belongs to, or ``None`` for unlisted.

    Total over every group the bundle holds. ``None`` is the honest answer
    for a document — see :data:`LISTED_GROUPS` — and never a fall-through:
    a group this function has not been taught raises rather than picking a
    part, because a topic quietly filed under the wrong heading is worse
    than a build that stops.
    """
    from s0ma_dsl.docs_model.map_of_record import CATEGORY_BY_AUTHORITY
    from s0ma_dsl.docs_model.resolve import DocsResolveError

    if view.group == "concepts":
        return "understand"
    if view.group in {"journeys", "sequences"}:
        return "build"
    if view.group == "surfaces":
        channel = view.text("channel")
        found = CATEGORY_OF_CHANNEL.get(channel)
        if found is None:
            raise DocsResolveError(
                f"{view.id} is served on the {channel!r} channel and this "
                f"surface has no part for that channel. Every channel the "
                f"model classifies has an entry in CATEGORY_OF_CHANNEL; a "
                f"new one is a decision about where a reader looks for it."
            )
        return found
    if view.group == "authorities":
        kind = view.text("authority_class")
        return CATEGORY_OF_AUTHORITY_CLASS.get(
            kind, CATEGORY_BY_AUTHORITY.get(kind, "reference")
        )
    if view.group == "documents":
        return None
    raise DocsResolveError(  # pragma: no cover - group_of refuses first
        f"{view.id} is a {view.group} and this surface has no part for that group"
    )


def by_category(index: TopicIndex) -> Mapping[str, tuple[str, ...]]:
    """Every listed topic id, grouped by part, each group sorted.

    The grouping the navigation counts and ``list`` walks. Built once from
    the index so the count a reader is shown and the list they get when
    they follow it are the same set — a count computed one way and a
    listing computed another is how a "147" turns into 146 rows nobody can
    account for.
    """
    grouped: dict[str, list[str]] = {key: [] for key in CATEGORY_KEYS}
    for identifier, view in index.views.items():
        if view.group not in LISTED_GROUPS:
            continue
        part = category_of_topic(view)
        if part is not None:
            grouped[part].append(identifier)
    return {key: tuple(sorted(values)) for key, values in grouped.items()}


def topic_index(snapshot: Snapshot) -> TopicIndex:
    """The resolver index this snapshot serves, aliases included."""
    from s0ma_dsl.docs_model.resolve import TopicIndex

    return TopicIndex.of(snapshot.bundle, snapshot.aliases)


# ---------------------------------------------------------------------------
# The terminal channel
# ---------------------------------------------------------------------------

#: This channel's name. It is a *channel* rather than a formatting option
#: because B5's residue rules apply to it: what reaches a reader is either
#: a fact carried word for word or declared presentation, and calling the
#: terminal "the human channel with two extra lines" without declaring the
#: two lines is exactly the undeclared carrier clause 1 refuses.
TERMINAL_CHANNEL = "terminal"

#: The blocks this channel adds around the page, which carry no fact.
#: ``{...}`` marks the parts filled in per invocation;
#: :func:`envelope_of` renders them, and :func:`undeclared_lines` accepts
#: exactly what it renders and nothing else.
#: ``{release}`` is the stamp's *written* version — labelled unless the
#: build is a release (H1, architecture §13.2) — so this line is where a
#: person running a read command finds out they are reading preview
#: documentation. The phrase was "documentation snapshot" until H1 and is
#: "docs snapshot" now, for one reason worth recording: the label costs ten
#: columns and this line has to fit :data:`NAV_MAX_COLUMNS`. Shortening a
#: word this channel already says twice (the command is ``s0ma docs``) buys
#: the room, and buys enough of it that a longer version number does not
#: put it back over.
TERMINAL_ENVELOPE: tuple[str, ...] = (
    "s0ma {release} — docs snapshot {snapshot} ({origin})",
    "Read more: {pages}",
    "",
)

#: The named transformations this channel applies on top of the human
#: page's own (B5 clause 1).
#:
#: The width one is the load-bearing one. This channel does **not** wrap:
#: the page's prose is written unwrapped, one paragraph to a line, and the
#: terminal soft-wraps it for display. That is what makes the bytes
#: independent of the terminal — B6 finding 5's requirement — and it is
#: the opposite of what a wrapping renderer would do, which is why it is
#: written down rather than left as an absence.
TERMINAL_TRANSFORMATIONS: tuple[str, ...] = (
    "the page is the human channel's, rendered verbatim",
    "the build identity is written as the first line, before the page",
    "the committed page this topic is written on is named as the last line",
    "prose is not wrapped: the terminal wraps it, so the bytes do not "
    "depend on the terminal's width",
    "line endings: line feed, with exactly one at the end",
)


def identity_line(snapshot: Snapshot) -> str:
    """The one line every output of this surface opens with.

    Arch §9.2's closing requirement, as a line: read commands "must say
    which product version and snapshot they describe". The origin word is
    here too, because the same command in a checkout and from an installed
    wheel can honestly give different answers, and which one answered is
    the first thing a confused reader needs.

    The *path* the snapshot was read from is deliberately not here: it is
    absolute, and plan §3.1 rule 4 keeps absolute machine paths out of
    anything emitted.
    """
    return TERMINAL_ENVELOPE[0].format(
        release=snapshot.version_line(),
        snapshot=snapshot.snapshot_hash(),
        origin=snapshot.origin,
    )


def terminal_spec(group: str) -> PresentationSpec:
    """This channel's declaration for one bundle group.

    The human channel's labels and order, unchanged — the fact set is
    inherited rather than re-opined, so this channel cannot decide a topic
    carries something the page does not — under this channel's own name,
    envelope and transformations.

    ``width`` is ``0``: this channel does not wrap.
    """
    from s0ma_dsl.docs_model import render_human
    from s0ma_dsl.docs_model.resolve import PresentationSpec

    page = render_human.spec_for(group)
    return PresentationSpec(
        channel=TERMINAL_CHANNEL,
        labels=page.labels,
        order=page.order,
        envelope=(*page.envelope, *TERMINAL_ENVELOPE),
        transformations=(*page.transformations, *TERMINAL_TRANSFORMATIONS),
        width=0,
    )


def read_more(snapshot: Snapshot, view: TopicView) -> tuple[str, ...]:
    """The committed pages ``view`` is written on, repository-relative.

    Four derivations, one per kind of thing, and none of them a written-out
    path:

    * a **concept** is written on its learn page, which
      :func:`~s0ma_dsl.docs_model.learn_pages.page_path` computes from the
      id;
    * a **command, setting or report** is written on one of F3's three
      generated references, at the anchor
      :func:`~s0ma_dsl.docs_model.reference_pages.deep_link` computes —
      the exact call that milestone left for this one;
    * any **other served capability** is in the generated index of served
      capabilities, which lists every one of them;
    * everything else — a **journey** above all — is found by asking the
      catalog which documents *cover* it. That is the edge the catalog
      already carries, so a guide renamed or a journey re-covered moves
      this pointer without anybody editing it. Nothing here is hardcoded.

    A document points at itself, and a written authority at nothing: the
    document it is written in is already a fact on its page.
    """
    from s0ma_dsl.docs_model.application import DOCS_ROOT, SURFACES_INDEX_OUTPUT
    from s0ma_dsl.docs_model.learn_pages import page_path
    from s0ma_dsl.docs_model.reference_pages import PAGE_BY_ID_CLASS, deep_link

    if view.group == "concepts":
        return (f"{DOCS_ROOT}/{page_path(view.id)}",)
    if view.group == "documents":
        return (view.text("canonical_source"),)
    if view.group == "authorities":
        return ()
    if view.group == "surfaces":
        if view.id.partition(":")[0] in PAGE_BY_ID_CLASS:
            return (deep_link(view.id, docs_root=DOCS_ROOT),)
        return (f"{DOCS_ROOT}/{SURFACES_INDEX_OUTPUT}",)
    covering = sorted(
        {
            document.canonical_source
            for document in snapshot.bundle.documents
            if view.id in document.covers
        }
    )
    # A journey nothing covers yet points at nothing, rather than at a
    # page guessed from its name: an id in a URL that resolves to a 404 is
    # worse than no line at all, and the catalog is where the answer will
    # appear when a guide claims it.
    return tuple(covering)


def envelope_of(snapshot: Snapshot, view: TopicView) -> tuple[str, ...]:
    """Exactly the envelope lines this invocation writes, in order."""
    pages = read_more(snapshot, view)
    lines = [identity_line(snapshot), ""]
    if pages:
        lines.append(TERMINAL_ENVELOPE[1].format(pages=", ".join(pages)))
    return tuple(lines)


def render_terminal(snapshot: Snapshot, view: TopicView) -> str:
    """One topic, as a person reads it in a terminal.

    The human page verbatim, opened by the build identity and closed by
    the pointer to the committed page. Byte-identical on every terminal.
    """
    from s0ma_dsl.docs_model.render_human import render_human

    page = render_human(view)
    lines = [identity_line(snapshot), "", *page.split("\n")]
    pages = read_more(snapshot, view)
    if pages:
        lines.append(TERMINAL_ENVELOPE[1].format(pages=", ".join(pages)))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def undeclared_lines(
    frame: str, page: str, envelope: Sequence[str]
) -> tuple[str, ...]:
    """Lines of ``frame`` that are neither the page nor declared envelope.

    B5 clause 1's enforcement for this channel, and the reason the terminal
    is declared as a channel at all. The page's lines have to arrive in
    order — a rendering that reordered them would be presenting something
    the human channel did not — and every other line has to be one this
    invocation declared it would write.
    """
    remaining = list(page.split("\n"))
    allowed = set(envelope)
    found: list[str] = []
    for line in frame.split("\n"):
        if remaining and line == remaining[0]:
            remaining.pop(0)
            continue
        if line in allowed:
            continue
        found.append(line)
    return tuple(found)


# ---------------------------------------------------------------------------
# The navigation map (T1)
# ---------------------------------------------------------------------------

#: B6's declared budget for this one artifact: one 80x24 terminal screen,
#: which is the unscrollable unit a person actually sees
#: (``scripts/spikes/docs_model/spike_b6_discovery/fixtures/budgets.json``).
#: The three numbers are held together by a proof, because a stub inside
#: its byte budget and 30 lines long is a stub nobody sees the top of.
NAV_BYTE_BUDGET = 1920
NAV_MAX_LINES = 24
NAV_MAX_COLUMNS = 80

#: How many lines the journeys block occupies, always. With this many
#: journeys or fewer it lists them all; with more, the last line says how
#: many were not listed and which command shows them. A block that grew
#: with the corpus would push the map off the screen the budget exists to
#: keep it on.
#:
#: Raised from six to seven at beta-prep-1-retrofit F2a, when a seventh
#: journey arrived and the sixth-and-last line would otherwise have
#: become "... and 2 more". The line it needed was paid for out of the
#: blank separator that used to sit under :data:`NAV_JOURNEYS`, which
#: carried no fact and which :data:`NAV_ASKING` never had: the screen is
#: the same twenty-four lines, the same three ceilings, and every journey
#: is still listed by name. The next journey to arrive has no such spare
#: line and falls to the overflow line, which is what it is for.
NAV_JOURNEY_LINES = 7

#: The sentence over the five parts, and the two over the blocks below
#: them. Declared presentation: they carry no fact, and they are the only
#: prose on this screen this surface wrote.
NAV_OPENING = "Everything s0ma knows about itself, in five parts:"
NAV_JOURNEYS = "Paths that take you through a whole task, start to finish:"
NAV_ASKING = "Ask for any topic by id, by name, or by a word you remember:"
NAV_MAP = "Every document, and who each one is for: {map}"

#: The two example invocations under :data:`NAV_ASKING`. Written out
#: because they are examples of a *form*, and the form is the teaching.
NAV_EXAMPLES: tuple[str, ...] = (
    "s0ma docs show concept:nerve",
    "s0ma docs search drift",
)


def _journey_order(index: TopicIndex) -> tuple[str, ...]:
    """Every journey, the one that assumes least first.

    Sorted by how many concepts a path expects you to know already, then
    by id. Not a popularity guess and not the order somebody listed them
    in: the path with the fewest prerequisites is the one a person with
    none can actually start, which is the only sense of "start here" this
    build can derive rather than assert.
    """
    def key(identifier: str) -> tuple[int, str]:
        return (len(index.views[identifier].items("concepts_required")), identifier)

    return tuple(sorted(index.group("journeys"), key=key))


def _journey_lines(index: TopicIndex) -> list[str]:
    """The journeys block: :data:`NAV_JOURNEY_LINES` lines, never more."""
    ordered = _journey_order(index)
    if len(ordered) <= NAV_JOURNEY_LINES:
        return [f"  s0ma docs show {identifier}" for identifier in ordered]
    shown = ordered[: NAV_JOURNEY_LINES - 1]
    rest = len(ordered) - len(shown)
    return [
        *(f"  s0ma docs show {identifier}" for identifier in shown),
        f"  ... and {rest} more: s0ma docs list build",
    ]


def navigation(snapshot: Snapshot) -> str:
    """The learning map, as a person meets it in a terminal.

    Authored at a fixed width, on purpose. B6 finding 5: ``s0ma --help``
    renders at the running terminal's width and so has no fixed size at
    all; a navigation screen that has to be byte-deterministic cannot be
    formatted by argparse, and this one is not.
    """
    from s0ma_dsl.docs_model.application import DOCS_ROOT, MAP_OUTPUT

    index = topic_index(snapshot)
    grouped = by_category(index)
    sections = {section.key: section.title for section in _sections()}

    width = max(len(sections[key]) for key in CATEGORY_KEYS)
    parts = [
        f"  {len(grouped[key]):5d}  {sections[key]:<{width}}  s0ma docs list {key}"
        for key in CATEGORY_KEYS
    ]
    lines = [
        identity_line(snapshot),
        "",
        NAV_OPENING,
        "",
        *parts,
        "",
        NAV_JOURNEYS,
        *_journey_lines(index),
        "",
        NAV_ASKING,
        *(f"  {example}" for example in NAV_EXAMPLES),
        "",
        NAV_MAP.format(map=f"{DOCS_ROOT}/{MAP_OUTPUT}"),
    ]
    return "\n".join(lines) + "\n"


def navigation_document(snapshot: Snapshot) -> dict[str, Any]:
    """The same map, as the facts a program would read it for."""
    from s0ma_dsl.docs_model.application import DOCS_ROOT, MAP_OUTPUT

    index = topic_index(snapshot)
    grouped = by_category(index)
    sections = {section.key: section.title for section in _sections()}
    return {
        "categories": [
            {
                "command": f"s0ma docs list {key}",
                "key": key,
                "title": sections[key],
                "topics": len(grouped[key]),
            }
            for key in CATEGORY_KEYS
        ],
        "document_map": f"{DOCS_ROOT}/{MAP_OUTPUT}",
        "journeys": list(_journey_order(index)),
        "origin": snapshot.origin,
        "release_version": snapshot.release_version(),
        "snapshot_hash": snapshot.snapshot_hash(),
    }


# ---------------------------------------------------------------------------
# Listing, showing, searching (T2)
# ---------------------------------------------------------------------------

#: How a topic is written in a list of topics: its id, then the one short
#: line its author wrote for it, indented under it.
#:
#: Two lines rather than a padded column, and the reason is rule (b): a
#: channel carries a fact word for word or leaves it out. Short forms run
#: from 40 to 140 characters across the corpus, so a column would have to
#: truncate one — and a truncated summary is a sentence the author did not
#: write, presented as though they had.
_ENTRY_INDENT = "      "


def _short_fact(view: TopicView) -> str:
    """The one short line this group's author writes, or empty for none.

    :data:`~s0ma_dsl.docs_model.resolve.AGENT_SHORT_FACT` is the table, and
    it is reused rather than reinvented: C7 established that every group
    names its own short form, and a list that picked a different field per
    group would be a second opinion about what "in short" means.
    """
    from s0ma_dsl.docs_model.resolve import AGENT_SHORT_FACT

    name = AGENT_SHORT_FACT[view.group]
    return view.text(name) if name else ""


#: What each listed group is called on a listing, and the order the
#: groups appear in inside a part.
#:
#: A part is sub-headed by group rather than run together, because the
#: parts are uneven in a way a flat list hides: "Understand s0ma" holds
#: thirty-seven concepts and a hundred and ten section anchors of the
#: product requirements, and sorted into one alphabet the concepts land
#: after all of them. The sub-heading is presentation and carries no fact;
#: the count beside it is computed.
GROUP_TITLES: Mapping[str, str] = {
    "concepts": "Ideas and vocabulary",
    "journeys": "Paths through a whole task",
    "sequences": "Teaching orders",
    "surfaces": "What s0ma can be asked to do",
    "authorities": "What decides these things, and where it is written",
}

#: The order those sub-headings appear in: what a person is taught first,
#: what they can do with it, and what settles a disagreement last.
GROUP_ORDER: tuple[str, ...] = (
    "concepts",
    "journeys",
    "sequences",
    "surfaces",
    "authorities",
)


def _entry_lines(index: TopicIndex, identifier: str) -> list[str]:
    """One topic as it appears in a listing."""
    view = index.views[identifier]
    short = _short_fact(view)
    lines = [f"    {identifier}"]
    if short:
        lines.append(f"{_ENTRY_INDENT}{short}")
    return lines


def _part_lines(index: TopicIndex, identifiers: Sequence[str]) -> list[str]:
    """One part's topics, sub-headed by group, each group sorted by id."""
    held: dict[str, list[str]] = {group: [] for group in GROUP_ORDER}
    for identifier in identifiers:
        held[index.views[identifier].group].append(identifier)
    lines: list[str] = []
    for group in GROUP_ORDER:
        members = held[group]
        if not members:
            continue
        lines.extend(["", f"  {GROUP_TITLES[group]} — {len(members)}", ""])
        for identifier in members:
            lines.extend(_entry_lines(index, identifier))
    return lines


def _entry_document(index: TopicIndex, identifier: str) -> dict[str, Any]:
    """One topic as the facts a program would list it by."""
    view = index.views[identifier]
    return {
        "group": view.group,
        "id": identifier,
        "summary": _short_fact(view),
        "title": index.names[identifier],
    }


def _candidate_lines(candidates: Sequence[Candidate]) -> list[str]:
    """Ranked candidates, each with the reason it matched."""
    return [f"  {candidate.id} — {candidate.reason}" for candidate in candidates]


def _candidate_documents(candidates: Sequence[Candidate]) -> list[dict[str, Any]]:
    return [
        {
            "group": candidate.group,
            "id": candidate.id,
            "match": candidate.match_class,
            "rank": candidate.rank,
            "reason": candidate.reason,
        }
        for candidate in candidates
    ]


def _print_json(document: Mapping[str, Any]) -> None:
    """One canonical JSON document, sorted, with a trailing newline.

    :func:`~s0ma_dsl.docs_model.serialize.canonical_json` rather than
    ``json.dumps`` with flags set here: one spelling of canonical, in the
    module that owns it, is what makes two of these comparable at all.
    """
    from s0ma_dsl.docs_model.serialize import canonical_json

    print(canonical_json(dict(document)), end="")


def _snapshot_or_exit(args: argparse.Namespace) -> Snapshot | int:
    """The documentation to answer from, or the exit code that says why not.

    Shared by all four read commands so a person who has no snapshot gets
    the same sentence whichever of them they ran first.
    """
    from s0ma_dsl.docs_model.bundle import DocsBundleUnavailableError, load_snapshot

    try:
        return load_snapshot()
    except (DocsBundleUnavailableError, OSError) as exc:
        if getattr(args, "output_format", "text") == "json":
            _print_json({"error": str(exc), "found": False})
        else:
            print(f"s0ma docs: {exc}", file=sys.stderr)
        return _EXIT_VALIDATION_ERROR


@component(
    name="S0maDSL_cmd_docs_navigate",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Handler for bare `s0ma docs`: prints the learning map of the composed "
        "documentation snapshot, with the next commands."
    ),
    idempotent=True,
    is_framework=True,
)
def cmd_docs_navigate(args: argparse.Namespace) -> int:
    """Implement bare ``s0ma docs`` — the learning map.

    Exit 0. Arch §9.3 row 3: "bare `s0ma docs` shows useful navigation
    rather than a usage error", and an exit code that says the invocation
    was wrong would keep saying so however useful the text above it was.
    """
    outcome = _snapshot_or_exit(args)
    if isinstance(outcome, int):
        return outcome
    if getattr(args, "output_format", "text") == "json":
        _print_json(navigation_document(outcome))
    else:
        print(navigation(outcome), end="")
    return _EXIT_SUCCESS


@component(
    name="S0maDSL_cmd_docs_list",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Handler for `s0ma docs list`: prints every topic of one part of the "
        "documentation, or of all five."
    ),
    idempotent=True,
    is_framework=True,
)
def cmd_docs_list(args: argparse.Namespace) -> int:
    """Implement ``s0ma docs list [category]``."""
    outcome = _snapshot_or_exit(args)
    if isinstance(outcome, int):
        return outcome
    snapshot = outcome
    index = topic_index(snapshot)
    grouped = by_category(index)
    sections = {section.key: section.title for section in _sections()}

    wanted = getattr(args, "category", None)
    if wanted is not None and wanted not in grouped:
        message = (
            f"there is no part of the documentation called {wanted!r}. "
            f"The five are: {', '.join(CATEGORY_KEYS)}. Run `s0ma docs` to "
            f"see what is in each of them."
        )
        if getattr(args, "output_format", "text") == "json":
            _print_json({"categories": list(CATEGORY_KEYS), "error": message})
        else:
            print(f"s0ma docs list: {message}", file=sys.stderr)
        return _EXIT_USAGE_ERROR

    keys = (wanted,) if wanted is not None else CATEGORY_KEYS

    if getattr(args, "output_format", "text") == "json":
        _print_json(
            {
                "categories": [
                    {
                        "key": key,
                        "title": sections[key],
                        "topics": [
                            _entry_document(index, identifier)
                            for identifier in grouped[key]
                        ],
                    }
                    for key in keys
                ],
                "origin": snapshot.origin,
                "release_version": snapshot.release_version(),
                "snapshot_hash": snapshot.snapshot_hash(),
            }
        )
        return _EXIT_SUCCESS

    lines = [identity_line(snapshot)]
    for key in keys:
        lines.extend(["", f"{sections[key]} — {len(grouped[key])} topic(s)"])
        lines.extend(_part_lines(index, grouped[key]))
    print("\n".join(lines))
    return _EXIT_SUCCESS


@component(
    name="S0maDSL_cmd_docs_show",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Handler for `s0ma docs show`: renders one resolved topic in full, or "
        "the ranked candidates a question could have meant."
    ),
    idempotent=True,
    is_framework=True,
)
def cmd_docs_show(args: argparse.Namespace) -> int:
    """Implement ``s0ma docs show <id-or-alias>``.

    Three outcomes and three exit codes, because the resolver has three
    answers and collapsing two of them would throw away the difference
    between "respell it" and "pick one".
    """
    from s0ma_dsl.docs_model.render_json import render_json
    from s0ma_dsl.docs_model.resolve import resolve

    outcome = _snapshot_or_exit(args)
    if isinstance(outcome, int):
        return outcome
    snapshot = outcome
    index = topic_index(snapshot)
    resolution = resolve(index, args.topic)
    as_json = getattr(args, "output_format", "text") == "json"

    if resolution.topic is not None:
        if as_json:
            print(render_json(resolution.topic), end="")
        else:
            print(render_terminal(snapshot, resolution.topic), end="")
        return _EXIT_SUCCESS

    if resolution.candidates:
        if as_json:
            _print_json(
                {
                    "candidates": _candidate_documents(resolution.candidates),
                    "query": resolution.query,
                    "release_version": snapshot.release_version(),
                    "snapshot_hash": snapshot.snapshot_hash(),
                    "state": resolution.state(),
                }
            )
        else:
            print(identity_line(snapshot))
            print()
            print(
                f"{len(resolution.candidates)} topics match "
                f"{resolution.query!r} equally well. Ask for one of them "
                f"by id:"
            )
            print()
            print("\n".join(_candidate_lines(resolution.candidates)))
        return _EXIT_AMBIGUOUS

    finding = resolution.finding
    assert finding is not None  # noqa: S101 - the resolver's third shape
    if as_json:
        _print_json(
            {
                "code": finding.code,
                "message": finding.message,
                "query": resolution.query,
                "release_version": snapshot.release_version(),
                "remediation": finding.remediation,
                "snapshot_hash": snapshot.snapshot_hash(),
                "state": resolution.state(),
            }
        )
    else:
        print(identity_line(snapshot), file=sys.stderr)
        print(file=sys.stderr)
        print(f"{finding.message}.", file=sys.stderr)
        print(f"  → {finding.remediation}", file=sys.stderr)
    return _EXIT_VALIDATION_ERROR


@component(
    name="S0maDSL_cmd_docs_search",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Handler for `s0ma docs search`: prints every topic a question could "
        "have meant, strongest match first, each with the reason it matched."
    ),
    idempotent=True,
    is_framework=True,
)
def cmd_docs_search(args: argparse.Namespace) -> int:
    """Implement ``s0ma docs search <query>``.

    The resolver's ranking, shown whole. ``show`` and ``search`` ask the
    same function the same question — the only difference is that ``show``
    renders the one answer when there is exactly one, and this prints the
    ranked list whether there is one or twenty. A search with its own
    scoring would be a second answer to "what does this word mean here",
    and the two would disagree the first time either changed.
    """
    from s0ma_dsl.docs_model.resolve import resolve

    outcome = _snapshot_or_exit(args)
    if isinstance(outcome, int):
        return outcome
    snapshot = outcome
    index = topic_index(snapshot)
    query = " ".join(args.query) if isinstance(args.query, list) else args.query
    resolution = resolve(index, query)
    as_json = getattr(args, "output_format", "text") == "json"

    if not resolution.candidates:
        finding = resolution.finding
        assert finding is not None  # noqa: S101 - the resolver's third shape
        if as_json:
            _print_json(
                {
                    "code": finding.code,
                    "matches": [],
                    "message": finding.message,
                    "query": query,
                    "release_version": snapshot.release_version(),
                    "remediation": finding.remediation,
                    "snapshot_hash": snapshot.snapshot_hash(),
                }
            )
        else:
            print(identity_line(snapshot), file=sys.stderr)
            print(file=sys.stderr)
            print(f"{finding.message}.", file=sys.stderr)
            print(f"  → {finding.remediation}", file=sys.stderr)
        return _EXIT_VALIDATION_ERROR

    if as_json:
        _print_json(
            {
                "matches": _candidate_documents(resolution.candidates),
                "query": query,
                "release_version": snapshot.release_version(),
                "snapshot_hash": snapshot.snapshot_hash(),
            }
        )
        return _EXIT_SUCCESS

    lines = [
        identity_line(snapshot),
        "",
        f"{len(resolution.candidates)} topic(s) match {query!r}, "
        f"strongest match first.",
        "",
    ]
    for candidate in resolution.candidates:
        lines.append(f"  {candidate.id} — {candidate.reason}")
        short = _short_fact(index.views[candidate.id])
        if short:
            lines.append(f"{_ENTRY_INDENT}{short}")
    lines.extend(["", "  s0ma docs show <id>   for any one of these, in full"])
    print("\n".join(lines))
    return _EXIT_SUCCESS
