"""``s0ma adopt`` — retrofitting an existing codebase, rung by rung.

This package holds the mechanisms behind the retrofit ladder: read a
tree and say what is in it, set a perimeter, draft a module, capture
what its public surface promised, and prove the converted module still
promises the same thing.

Nothing here imports or executes the code it is looking at. Every
mechanism is :mod:`ast` over files, so a scan is safe to run on a
codebase nobody trusts yet, and a parity check cannot be fooled by an
import side effect.

Public surface — the shared vocabulary from :mod:`s0ma_dsl.adopt.model`,
re-exported so every mechanism and every caller names things the same
way, plus **rung 0 whole**: the five functions that read a tree
(``discover_sources``, ``census_file``, ``classify_imports``,
``build_graph``, and the four suggestions in ``proposals``) and the two
that turn the result into a report somebody can act on
(:func:`~s0ma_dsl.adopt.report.build_scan_report` and
:func:`~s0ma_dsl.adopt.report.render_scan_text`). Rung 0 is re-exported
because it is the whole of what ``s0ma adopt scan`` is, and a caller who
wants to read a codebase without running a command should not have to
know which of five modules each step lives in.

The later rungs' mechanisms (``harvest``, ``draft_emit``, ``surface``,
``parity``, ``status``) are imported from their own modules.

The per-file adoption record store lives in :mod:`s0ma_dsl.adoption`
(schema ``s0ma-adopted-files@1``) and is a separate, older family.
"""

from __future__ import annotations

from s0ma_dsl.adopt.census import census_file
from s0ma_dsl.adopt.discovery import (
    discover_sources,
    is_transpiled_artifact,
    resolve_source_roots,
)
from s0ma_dsl.adopt.graph import (
    ORIGIN_FIRST_PARTY,
    ORIGIN_STDLIB,
    ORIGIN_THIRD_PARTY,
    ORIGIN_UNRESOLVED,
    build_graph,
    classify_imports,
)
from s0ma_dsl.adopt.model import (
    BASELINE_FILENAME,
    BASELINE_SCHEMA,
    DRAFT_INTENT_MARKER,
    DRAFT_UNPLACED_MARKER,
    SCAN_SCHEMA,
    DraftDeclaration,
    DraftModule,
    DraftUnplaced,
    EffortEstimate,
    EntityFact,
    GraphFacts,
    ImportFact,
    LadderStatus,
    ModuleCensus,
    ModuleSurface,
    ParityFinding,
    ParityResult,
    PerimeterSuggestion,
    Proposal,
    ScanReport,
    ScanWarning,
    SourceFile,
    SurfaceEntry,
    dump_json,
)
from s0ma_dsl.adopt.proposals import (
    EFFORT_BASIS,
    PERIMETER_MODE,
    WARNING_NAME_COLLISION,
    collision_warnings,
    estimate_effort,
    framework_component_names,
    propose,
    suggest_perimeter,
)
from s0ma_dsl.adopt.report import (
    WARNING_CYCLE,
    WARNING_DEFERRED_CYCLE,
    WARNING_DYNAMIC_EXPORTS,
    WARNING_PARSE_ERROR,
    build_scan_report,
    render_detail_text,
    render_scan_text,
)

__all__ = [
    "BASELINE_FILENAME",
    "BASELINE_SCHEMA",
    "DRAFT_INTENT_MARKER",
    "DRAFT_UNPLACED_MARKER",
    "EFFORT_BASIS",
    "ORIGIN_FIRST_PARTY",
    "ORIGIN_STDLIB",
    "ORIGIN_THIRD_PARTY",
    "ORIGIN_UNRESOLVED",
    "PERIMETER_MODE",
    "SCAN_SCHEMA",
    "WARNING_CYCLE",
    "WARNING_DEFERRED_CYCLE",
    "WARNING_DYNAMIC_EXPORTS",
    "WARNING_NAME_COLLISION",
    "WARNING_PARSE_ERROR",
    "DraftDeclaration",
    "DraftModule",
    "DraftUnplaced",
    "EffortEstimate",
    "EntityFact",
    "GraphFacts",
    "ImportFact",
    "LadderStatus",
    "ModuleCensus",
    "ModuleSurface",
    "ParityFinding",
    "ParityResult",
    "PerimeterSuggestion",
    "Proposal",
    "ScanReport",
    "ScanWarning",
    "SourceFile",
    "SurfaceEntry",
    "build_graph",
    "build_scan_report",
    "census_file",
    "classify_imports",
    "collision_warnings",
    "discover_sources",
    "dump_json",
    "estimate_effort",
    "framework_component_names",
    "is_transpiled_artifact",
    "propose",
    "render_detail_text",
    "render_scan_text",
    "resolve_source_roots",
    "suggest_perimeter",
]
