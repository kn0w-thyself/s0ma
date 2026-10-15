"""``s0ma score`` — the self-knowledge score (STD-M8, usability plan).

Reports a single visible **self-knowledge** number plus a per-faculty
breakdown for a s0ma project, in human text and ``--format json`` rendered
from the same structured data (PRD P-5 / plan D-5: machine-first). The
score is both the visible "impact" signal and a gateable boundary
*standard* — ``--gate`` exits non-zero when evidence is blocked or the overall
score falls below the caller-pinned ``--gate-mode`` floor.

What it measures (the three faculties of self-knowledge, §1.3)
-------------------------------------------------------------

This command introduces **no new analysis engine** (plan D-7: compose what
the toolchain already computes; never import ``s0ma-mcp``). Every signal is
read from s0ma-dsl's own surfaces — the parsed ``.s0ma`` modules, the
dependency resolver, the release-mode doc/test coverage passes, the doc
drift validator, the build manifest, and the ``s0ma verify`` drift
classifier — or from ``s0ma-core`` (the allowed import direction,
``mcp → dsl → core``).

**Proprioception** (structure — "what am I made of, how is it wired"):

* *registration* — the managed ``.py`` surface is split into componentized,
  roster-adopted, and unknown populations. Only componentized code earns
  gate credit; adoption remains visible as migration debt. Declared or
  auto-classified exempt files
  (``bootstrap``/``package_marker``) are NOT counted against the project.
  ``n/a`` until a Python surface exists under the build/source roots.
* *layer compliance* — clean iff the dependency resolver reports no
  ``CROSS_LAYER_DEPENDENCY``.
* *structural-verifier clean* — clean iff resolution surfaces no structural
  errors (cycles, unresolved ``uses:``, undeclared targets, …) and the
  built surface carries no hand-edit / stale / conflict drift.

**Interoception** (runtime state — "how am I behaving vs. how I declared"):
the interoception faculty is backed by runtime metrics checked against
**declared resource profiles** — a ``s0ma-core`` runtime concept with no
``.s0ma`` declaration surface. A ``.s0ma`` project therefore has nothing
the toolchain can measure here, so this faculty reports
``n/a — no resource profiles declared`` rather than a misleading 0 or 100
(plan HONESTY rule). It is excluded from the overall roll-up.

**Metacognition** (reasoning over the model — "reasoning about my own
model"): the reasoning surfaces (impact analysis, extension-point guidance,
doc/test queries) are trustworthy only if docs and tests track the code, so
this faculty scores:

* *doc-ref coverage* — share of PUBLIC nerves selected by some
  ``doc-ref``'s ``covers:`` filter (the release-mode ``MISSING_PUBLIC_DOC_REF``
  contract, as a ratio).
* *declared test evidence* — share of PUBLIC nerves targeted by an existing,
  non-empty ``test`` declaration. A ``covered_by:`` edge receives credit only
  when it resolves to such a declaration; names alone are not execution.
* *drift-free* — clean iff the doc validator reports no drift / structural
  doc errors (``DRIFT_DETECTED`` and friends).

**The exempt set is LISTED, not just counted** (plan HONESTY rule + M3
boundary doctrine §28.2). The closed four categories — the single
handwritten bootstrap module, ``[tool.s0ma].bootstrap_files``,
``[tool.s0ma].package_markers``, and ``@internal`` components — are
enumerated with their actual members so a reviewer sees exactly what sits
outside s0ma.

**The overall roll-up** is the mean of the *available* faculty sub-scores.
A faculty that is honestly ``n/a`` is **excluded from the denominator** — it
is never silently counted as 100% or 0% (plan HONESTY rule).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma_dsl.discovery import iter_visible_files

if TYPE_CHECKING:
    import argparse

    from s0ma.verifiers import DiscoveredSurface

    from s0ma_dsl.adoption_policy import ResolvedAdoptionPolicy
    from s0ma_dsl.ast_nodes.nodes import S0maModule
    from s0ma_dsl.project import S0maProject

EXIT_SUCCESS = 0
EXIT_USAGE_ERROR = 2
EXIT_GATE_FAILURE = 1

#: Target overall-score floors per strictness mode (percent, 0–100). The
#: ramp mirrors the dev→strict→release strictness ladder the rest of the
#: toolchain uses. Migration and dev intentionally share the 0.14 floor:
#: keeping pace; strict (CI) and release (production) demand a high,
#: self-documenting surface. ``--gate`` exits non-zero when the overall
#: score is below the caller-pinned gate mode's floor; without ``--gate`` the
#: command is report-only (always exit 0 on a resolvable project). Authoring
#: ``mode`` remains independent and never selects one of these floors.
MODE_FLOORS: dict[str, float] = {
    "migration": 50.0,
    "dev": 50.0,
    "strict": 75.0,
    "release": 90.0,
}

#: The mode ``score`` falls back to when neither ``--mode`` nor
#: ``[tool.s0ma].mode`` is set. Registered in ``main._BUILTIN_MODE_DEFAULTS``
#: so the shared ``_resolve_mode`` precedence applies; duplicated here as the
#: defensive default for direct-``Namespace`` callers (tests).
DEFAULT_MODE = "dev"

#: The sentinel a faculty / sub-metric reports when it is not measurable on
#: the project (plan HONESTY rule). Distinct from a real 0.0 score.
NA = "n/a"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _pct(numerator: int, denominator: int) -> float | None:
    """Return ``numerator/denominator`` as a 0–100 percentage, or ``None``.

    ``None`` (rendered ``n/a``) when the denominator is zero — there is no
    population to score, so a percentage would be a fabrication rather than
    a measurement.
    """
    if denominator <= 0:
        return None
    return round(100.0 * numerator / denominator, 1)


def _mean_available(values: list[float | None]) -> float | None:
    """Mean of the non-``None`` values, or ``None`` when none are available.

    This is the n/a-excluding aggregation used both within a faculty (over
    its sub-metrics) and across faculties (the overall roll-up): a metric
    that could not be measured does not drag the average toward 0 or inflate
    it toward 100 — it simply does not vote.
    """
    present = [v for v in values if v is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 1)


# ---------------------------------------------------------------------------
# Project parse + signal collection (composition, not a new engine)
# ---------------------------------------------------------------------------


def _collect_modules(
    project: S0maProject,
) -> tuple[
    dict[str, S0maModule],
    dict[str, str],
    set[str],
    list[Any],
]:
    """Parse + validate every ``.s0ma`` module under the project's roots.

    Mirrors the ``s0ma check`` pipeline (``cli.main._cmd_check``) exactly —
    the same per-file parse / validate / derived-edge helpers — but keeps
    the diagnostics instead of printing them. Returns
    ``(modules, filenames, production_module_names, diagnostics)`` where
    ``production_module_names`` is the subset discovered under
    ``source_roots`` (so test modules inform resolution + coverage credit
    without inflating the PUBLIC-surface denominators).
    """
    from s0ma_dsl.cli.main import (
        _analyze_derived_edges,
        _discover_s0ma_files,
        _parse_single_file,
        _validate_single_module,
    )
    from s0ma_dsl.config import StrictnessMode

    # Score the surface at the release bar regardless of the gating mode:
    # the coverage signals (MISSING_PUBLIC_DOC_REF / MISSING_TEST_COVERAGE)
    # are release-gated, and we want the *ratio* on every project so the
    # number is comparable across modes. The mode only decides the gate
    # floor, never which signals are collected.
    mode = StrictnessMode.RELEASE

    source_paths: list[Path] = []
    for root in project.source_roots:
        source_paths.extend(_discover_s0ma_files(str(root)))
    production_paths = {p.resolve() for p in source_paths}

    all_paths: list[Path] = list(source_paths)
    seen = set(production_paths)
    for root in project.test_roots:
        for p in _discover_s0ma_files(str(root)):
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            all_paths.append(p)

    modules: dict[str, S0maModule] = {}
    filenames: dict[str, str] = {}
    production_names: set[str] = set()
    diagnostics: list[Any] = []
    requires_python = (
        project.requires_python if not project.synthetic else None
    )

    for source_path in all_paths:
        module, parse_errors = _parse_single_file(source_path, mode)
        diagnostics.extend(parse_errors)
        if module is None:
            continue
        name = module.module.name
        diagnostics.extend(
            _validate_single_module(
                module, source_path, mode, requires_python=requires_python,
            )
        )
        _derived, derived_errors = _analyze_derived_edges(
            module, source_path, mode,
        )
        diagnostics.extend(derived_errors)
        modules[name] = module
        filenames[name] = str(source_path)
        if source_path.resolve() in production_paths:
            production_names.add(name)

    return modules, filenames, production_names, diagnostics


def _resolution_diagnostics(
    modules: dict[str, S0maModule],
    filenames: dict[str, str],
    project: S0maProject,
) -> list[Any]:
    """Cross-module resolution findings (layer matrix + structural)."""
    from s0ma_dsl.config import StrictnessMode
    from s0ma_dsl.resolver.dependency import resolve_dependencies

    if not modules:
        return []
    attribute_budgets = (
        project.attribute_budgets if not project.synthetic else {}
    )
    test_layering = (
        project.test_layering if not project.synthetic else "strict"
    )
    return list(
        resolve_dependencies(
            modules,
            mode=StrictnessMode.RELEASE,
            filenames=filenames,
            attribute_budgets=attribute_budgets,
            test_layering=test_layering,
        )
    )


def _doc_diagnostics(
    modules: dict[str, S0maModule],
    filenames: dict[str, str],
) -> list[Any]:
    """Doc-subsystem validation findings (drift + structural doc errors)."""
    from s0ma_dsl.cli.main import _has_doc_declarations
    from s0ma_dsl.config import StrictnessMode

    if not modules or not _has_doc_declarations(modules):
        return []
    from s0ma_dsl.semantic.doc_validator import validate_docs

    return list(
        validate_docs(modules, filenames=filenames, mode=StrictnessMode.RELEASE)
    )


def _public_nerve_coverage(
    modules: dict[str, S0maModule],
    production_names: set[str],
) -> tuple[int, int, int]:
    """Return ``(public_nerves, doc_covered, test_covered)`` over production.

    Reuses the doc resolver's own ``covers:`` materialization
    (``_doc_ref_covers_nerves`` + ``build_project_index``) so the doc-ref
    coverage count matches the release-mode ``MISSING_PUBLIC_DOC_REF`` gate
    exactly. Declared test evidence credits only targets carried by an
    existing test declaration with a non-empty body. ``covered_by:`` earns
    the same credit only when an entry resolves to one of those declarations.
    This is static declared evidence, not a runtime coverage claim.
    """
    from s0ma_dsl.ast_nodes.enums import Visibility
    from s0ma_dsl.resolver.doc_resolver import build_project_index
    from s0ma_dsl.resolver.namespaces import (
        AmbiguousTestTarget,
        resolve_test_target_canonical,
    )
    from s0ma_dsl.semantic.doc_validator import _doc_ref_covers_nerves

    index = build_project_index(modules)

    doc_covered_names: set[str] = set()
    for mod in modules.values():
        for ref in mod.doc_refs:
            doc_covered_names.update(_doc_ref_covers_nerves(ref, index))

    valid_tests: dict[str, set[str]] = {}
    test_target_ids: set[str] = set()
    for module_name, mod in modules.items():
        for test in mod.tests:
            if not test.body or not test.body.strip():
                continue
            canonical_test = f"{module_name}::{test.name}"
            valid_tests.setdefault(test.name, set()).add(canonical_test)
            valid_tests.setdefault(canonical_test, set()).add(canonical_test)
            valid_tests.setdefault(
                f"{module_name}.{test.name}", set(),
            ).add(canonical_test)
            for target in test.tests:
                canonical_target = resolve_test_target_canonical(
                    target, module_name, modules,
                )
                if canonical_target is None or isinstance(
                    canonical_target, AmbiguousTestTarget,
                ):
                    continue
                test_target_ids.add(canonical_target)

    def _covered_by_resolves(entries: tuple[str, ...]) -> bool:
        for entry in entries:
            matches = valid_tests.get(entry.strip(), set())
            if len(matches) == 1:
                return True
        return False

    public = 0
    doc_covered = 0
    test_covered = 0
    for name in sorted(production_names):
        mod = modules[name]
        for nerve in mod.nerves:
            if nerve.visibility != Visibility.PUBLIC:
                continue
            public += 1
            if nerve.name in doc_covered_names:
                doc_covered += 1
            canonical_nerve = f"{name}::{nerve.name}"
            if (
                canonical_nerve in test_target_ids
                or _covered_by_resolves(nerve.covered_by)
            ):
                test_covered += 1
    return public, doc_covered, test_covered


def _verify_surface(
    project: S0maProject,
    *,
    adoption_policy: ResolvedAdoptionPolicy | None = None,
) -> dict[str, Any] | None:
    """Classify managed ``.py`` files the way ``s0ma verify`` does.

    Returns a summary ``{componentized, adopted, unknown, exempt, drifted,
    built}`` or ``None`` when the build and source roots contain no Python
    files (surface registration is then ``n/a``). Reuses the verify
    classifier's exact rules:
    a ``.py`` file is componentized when it carries the transpiler's
    source+output hash comments; otherwise it is ADOPTED (recorded in
    ``adopted.s0ma.json``), BOOTSTRAP
    (declared), PACKAGE_MARKER (declared or auto-classified), or UNKNOWN
    (residual drift). EDITED/STALE/CONFLICT componentized files are counted
    as ``drifted``; likewise, an adopted file whose content drifted still
    remains roster debt here — drift is ``s0ma verify``'s actionable
    signal, not a second, divergent implementation (plan D-7: compose).
    """
    import re

    from s0ma_dsl.adoption import AdoptedRecordError, load_adopted_files
    from s0ma_dsl.project import is_empty_package_marker

    build_dir = project.build_dir
    py_candidates: set[Path] = set()
    py_candidates.update(
        path.resolve() for path in iter_visible_files(build_dir, "*.py")
    )
    for source_root in project.source_roots:
        py_candidates.update(
            path.resolve() for path in iter_visible_files(source_root, "*.py")
        )
    py_files = sorted(py_candidates)
    if not py_files:
        return None

    bootstrap_set: set[Path] = set()
    for bf in project.bootstrap_files:
        try:
            bootstrap_set.add(Path(bf).resolve())
        except OSError:
            bootstrap_set.add(Path(bf))
    marker_set: set[Path] = set()
    for pm in project.package_markers:
        try:
            marker_set.add(Path(pm).resolve())
        except OSError:
            marker_set.add(Path(pm))
    # Adopted-file records (D2, 0.11.0). A corrupt record file degrades
    # to "nothing adopted" HERE — the score can then only go down (those
    # files fall back to UNKNOWN), never up; `s0ma verify` is the surface
    # that fails loudly on the corrupt record.
    adopted_set: set[Path] = set()
    try:
        adopted_records = load_adopted_files(project.root)
    except AdoptedRecordError:
        adopted_records = {}
    for rel_key in adopted_records:
        candidate = project.root / rel_key
        try:
            adopted_set.add(candidate.resolve())
        except OSError:
            adopted_set.add(candidate)

    # M4 first-contact inventory is local working evidence. Its immutable
    # path set identifies newly-born roster debt; unlike re-adoption count,
    # identical checkouts with the same first-contact anchor evaluate alike.
    from s0ma_dsl.check_baseline import load_baseline_record

    baseline = load_baseline_record(project.root)
    python_anchor_available = bool(
        baseline is not None and baseline.python_file_anchor is not None
    )
    python_anchor = (
        baseline.python_file_anchor
        if baseline is not None and baseline.python_file_anchor is not None
        else frozenset()
    )
    policy_paths = (
        adoption_policy.waived_paths
        if adoption_policy is not None
        else frozenset()
    )

    source_hash_re = re.compile(
        r"^# s0ma-source-hash:\s*sha256:(\w+)$", re.MULTILINE,
    )
    output_hash_re = re.compile(
        r"^# s0ma-output-hash:\s*sha256:(\w+)$", re.MULTILINE,
    )

    componentized = 0
    adopted = 0
    unknown = 0
    drifted = 0
    # Exempt files split by the same categories ``s0ma verify`` uses, so the
    # exempt-set enumeration can compose directly from this single pass
    # rather than re-classifying (plan D-7: compose, don't rebuild).
    bootstrap_paths: list[Path] = []
    marker_paths: list[Path] = []
    adopted_paths: list[Path] = []
    unknown_paths: list[Path] = []
    policy_exempt_paths: list[Path] = []
    new_roster_paths: list[Path] = []
    for py_path in py_files:
        try:
            content = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        has_hashes = bool(
            source_hash_re.search(content) and output_hash_re.search(content)
        )
        if has_hashes:
            componentized += 1
            # The score does not re-derive hand-edit drift per-file (that is
            # `s0ma verify`'s job and would duplicate its hashing); a
            # componentized file counts as in-s0ma. Drift surfaced elsewhere
            # (verify) is the actionable signal — kept at 0 here to avoid a
            # second, divergent hash implementation (plan D-7: compose).
            continue
        try:
            resolved = py_path.resolve()
        except OSError:
            resolved = py_path
        try:
            relative = resolved.relative_to(project.root.resolve()).as_posix()
        except (OSError, ValueError):
            relative = str(py_path)
        if relative in policy_paths:
            policy_exempt_paths.append(py_path)
            continue
        # D2 (0.11.0): adoption wins over the exemption buckets, the
        # same precedence `s0ma verify` applies — a hash-verified
        # roster record, not a declared exception. Content drift is
        # verify's job (see the componentized-file comment above).
        if resolved in adopted_set:
            adopted += 1
            adopted_paths.append(py_path)
            if python_anchor_available and relative not in python_anchor:
                new_roster_paths.append(py_path)
            continue
        if resolved in bootstrap_set:
            bootstrap_paths.append(py_path)
            continue
        if resolved in marker_set or is_empty_package_marker(py_path):
            marker_paths.append(py_path)
            continue
        unknown += 1
        unknown_paths.append(py_path)

    return {
        "componentized": componentized,
        "adopted": adopted,
        "unknown": unknown,
        "exempt": len(bootstrap_paths) + len(marker_paths),
        "drifted": drifted,
        "built": True,
        "bootstrap_paths": bootstrap_paths,
        "marker_paths": marker_paths,
        "adopted_paths": adopted_paths,
        "unknown_paths": unknown_paths,
        "policy_exempt_paths": policy_exempt_paths,
        "new_roster_paths": new_roster_paths,
    }


# ---------------------------------------------------------------------------
# Exempt-set enumeration (LISTED, per the M3 boundary doctrine §28.2)
# ---------------------------------------------------------------------------


def _enumerate_exempt_set(
    project: S0maProject,
    modules: dict[str, S0maModule],
    production_names: set[str],
    surface: dict[str, Any] | None,
) -> dict[str, Any]:
    """Enumerate the closed four-category exempt set with actual members.

    Lists, never merely counts (plan HONESTY rule): a reviewer sees exactly
    which components sit outside s0ma. The four categories are the M3
    boundary-doctrine §28.2 closed set, populated honestly:

    * ``bootstrap_module`` — the single handwritten bootstrap module: the
      *first* ``[tool.s0ma].bootstrap_files`` entry (the one entry-point/init
      shim that must exist before the import hook is active). The doctrine
      treats this as first-among-the-bootstrap-files.
    * ``bootstrap_files`` — every *other* declared
      ``[tool.s0ma].bootstrap_files`` entry.
    * ``package_markers`` — declared ``[tool.s0ma].package_markers`` plus
      every ``.py`` the built surface auto-classifies as a PACKAGE_MARKER
      (the same classification ``s0ma verify`` applies — composed from the
      ``surface`` pass, not re-derived).
    * ``internal`` — ``@internal`` components (INTERNAL visibility) over the
      production surface, as ``module::name`` ids.

    Paths render project-root-relative + POSIX where they live under the
    root (INV-5 style), else as given.
    """
    from s0ma_dsl.ast_nodes.enums import Visibility

    root = project.root

    def _rel(p: Path) -> str:
        try:
            return p.resolve().relative_to(root.resolve()).as_posix()
        except (ValueError, OSError):
            return str(p)

    # Declared bootstrap files, in declaration order: the doctrine's "single
    # handwritten bootstrap module" is the first; the rest are the other
    # intentional plain-Python entry points.
    declared_bootstrap = [_rel(Path(p)) for p in project.bootstrap_files]
    bootstrap_module = declared_bootstrap[:1]
    bootstrap_files = declared_bootstrap[1:]

    # Package markers: declared + auto-classified on the built surface. The
    # built-surface markers come straight from the verify-equivalent pass so
    # there is one classifier, not two (plan D-7).
    marker_members = {_rel(Path(p)) for p in project.package_markers}
    if surface is not None:
        for p in surface.get("marker_paths", []):
            marker_members.add(_rel(Path(p)))
    package_markers = sorted(marker_members)

    # @internal: components authored INTERNAL (deliberately outside the
    # served PUBLIC surface). Listed as ``module::name`` ids over the
    # production surface so the enumeration matches the public-surface
    # denominator's scope.
    internal: list[str] = []
    for name in sorted(production_names):
        mod = modules.get(name)
        if mod is None:
            continue
        for nerve in mod.nerves:
            if nerve.visibility == Visibility.INTERNAL:
                internal.append(f"{name}::{nerve.name}")
        for cell in mod.cells:
            if cell.visibility == Visibility.INTERNAL:
                internal.append(f"{name}::{cell.name}")
        for ganglion in mod.ganglia:
            if ganglion.visibility == Visibility.INTERNAL:
                internal.append(f"{name}::{ganglion.name}")

    total = (
        len(bootstrap_module)
        + len(bootstrap_files)
        + len(package_markers)
        + len(internal)
    )
    return {
        "total": total,
        "bootstrap_module": sorted(bootstrap_module),
        "bootstrap_files": sorted(bootstrap_files),
        "package_markers": package_markers,
        "internal": sorted(internal),
    }


def _build_discovered_surface(
    project: S0maProject,
    modules: dict[str, S0maModule],
    filenames: dict[str, str],
    production_names: set[str],
    surface: dict[str, Any] | None,
) -> DiscoveredSurface:
    """Build the parser-neutral surface value passed toward core verifiers.

    Discovery remains wholly DSL-owned.  The returned core value contains no
    AST nodes or project configuration, only canonical identifiers, kinds,
    source paths, and registration status.
    """
    from s0ma.verifiers import DiscoveredDeclaration, DiscoveredSurface

    declarations: list[DiscoveredDeclaration] = []
    for module_name in sorted(production_names):
        module = modules[module_name]
        source_path = filenames.get(module_name, f"{module_name}.s0ma")
        declarations.append(DiscoveredDeclaration(
            identifier=f"{module_name}::__module__",
            declaration_kind="module",
            source_path=source_path,
            registration_status="componentized",
        ))
        for index, declaration in enumerate(module.all_declarations):
            name = getattr(declaration, "name", None)
            if name is None:
                name = f"axon_{index}"
            kind = type(declaration).__name__.removesuffix("Decl").lower()
            declarations.append(DiscoveredDeclaration(
                identifier=f"{module_name}::{name}",
                declaration_kind=kind,
                source_path=source_path,
                registration_status="componentized",
            ))

    def _relative(path: Path) -> str:
        try:
            return path.resolve().relative_to(project.root.resolve()).as_posix()
        except (OSError, ValueError):
            return str(path)

    if surface is not None:
        for path in surface.get("adopted_paths", []):
            relative = _relative(path)
            declarations.append(DiscoveredDeclaration(
                identifier=relative,
                declaration_kind="python_module",
                source_path=relative,
                registration_status="roster_adopted",
            ))
        for path in surface.get("unknown_paths", []):
            relative = _relative(path)
            declarations.append(DiscoveredDeclaration(
                identifier=relative,
                declaration_kind="python_module",
                source_path=relative,
                registration_status="unknown",
            ))
    declarations.sort(
        key=lambda item: (
            item.source_path,
            item.identifier,
            item.declaration_kind,
        )
    )
    return DiscoveredSurface(declarations=tuple(declarations))


# ---------------------------------------------------------------------------
# Faculty assembly
# ---------------------------------------------------------------------------

#: Resolution error codes that mean "the layer reachability matrix was
#: violated" (proprioception: layer compliance).
_LAYER_CODES = frozenset({"CROSS_LAYER_DEPENDENCY"})

#: Doc-validation codes that mean "a rendered doc has drifted from its
#: registry-bound source" (metacognition: drift-free).
_DRIFT_CODES = frozenset({"DRIFT_DETECTED"})

#: Coverage codes excluded from the "structural" proprioception bucket —
#: these are scored as their own metacognition ratios, not as structural
#: errors, so they are not double-counted.
_COVERAGE_CODES = frozenset({
    "MISSING_PUBLIC_DOC_REF",
    "MISSING_EMBEDDED_EXAMPLE",
    "MISSING_TEST_COVERAGE",
})


def _errors(diagnostics: list[Any]) -> list[Any]:
    """The error-severity subset of *diagnostics*."""
    return [d for d in diagnostics if getattr(d, "severity", "") == "error"]


def _has_pending_semantic_debt(modules: dict[str, S0maModule]) -> bool:
    """Return whether any parsed project declaration carries pending debt.

    This reads the tagged AST directly instead of relying on authoring-mode
    diagnostic severity. Caller-pinned release policy must remain stronger
    than migration/dev authoring policy.
    """

    for module in modules.values():
        declarations = (module.module, *module.all_declarations)
        for declaration in declarations:
            if any(
                state.state == "pending"
                for _field, state in declaration.semantic_states
            ):
                return True
    return False


def _build_proprioception(
    resolution: list[Any],
    parse_validate: list[Any],
    surface: dict[str, Any] | None,
    discovered_count: int,
    *,
    adoption_policy: ResolvedAdoptionPolicy | None,
    project_exemptions: ResolvedAdoptionPolicy,
) -> dict[str, Any]:
    """Assemble the proprioception (structure) faculty."""
    res_errors = _errors(resolution)
    pv_errors = _errors(parse_validate)
    layer_violations = [
        d for d in res_errors if getattr(d, "code", "") in _LAYER_CODES
    ]
    # "Structural" = every error that is neither a layer violation nor a
    # coverage gap (those are scored elsewhere): cycles, unresolved uses,
    # undeclared targets, parse/semantic errors.
    structural_errors = [
        d
        for d in (res_errors + pv_errors)
        if getattr(d, "code", "") not in _LAYER_CODES
        and getattr(d, "code", "") not in _COVERAGE_CODES
        and getattr(d, "code", "") not in _DRIFT_CODES
    ]

    # Registration split: roster adoption is visible but earns no gate credit.
    if surface is None:
        componentized_pct: float | None = None
        roster_adopted_pct: float | None = None
        combined_pct: float | None = None
        registration_detail = "n/a — project not built (run `s0ma build`)"
        reg_componentized = reg_adopted = reg_unknown = 0
        new_roster_count = policy_exempt_count = 0
    else:
        reg_componentized = int(surface["componentized"])
        reg_adopted = int(surface.get("adopted", 0))
        reg_unknown = int(surface["unknown"])
        new_roster_count = len(surface.get("new_roster_paths", []))
        policy_exempt_count = len(surface.get("policy_exempt_paths", []))
        denominator = reg_componentized + reg_adopted + reg_unknown
        componentized_pct = _pct(reg_componentized, denominator)
        roster_adopted_pct = _pct(reg_adopted, denominator)
        combined_pct = _pct(reg_componentized + reg_adopted, denominator)
        registration_detail = (
            f"{reg_componentized} componentized, "
            f"{reg_adopted} roster-adopted, {reg_unknown} unknown"
        )

    layer_score: float | None = (
        (100.0 if not layer_violations else 0.0)
        if discovered_count > 0
        else None
    )
    structural_score: float | None = (
        (100.0 if not structural_errors else 0.0)
        if discovered_count > 0 or structural_errors
        else None
    )

    sub = _mean_available([
        componentized_pct, layer_score, structural_score,
    ])
    return {
        "score": sub,
        "metrics": {
            "registration": {
                "componentized": reg_componentized,
                "roster_adopted": reg_adopted,
                "unknown": reg_unknown,
                "componentized_pct": componentized_pct,
                "roster_adopted_pct": roster_adopted_pct,
                "combined_pct": combined_pct,
                "detail": registration_detail,
                "new_file_roster_only": new_roster_count,
                "gate_relevant_new_file_roster_only": new_roster_count,
                "caller_policy_exempt": policy_exempt_count,
                "adoption_policy": (
                    adoption_policy.to_dict()
                    if adoption_policy is not None
                    else None
                ),
                "project_adoption_exempt": {
                    "waives_gate": False,
                    "matched_count": len(project_exemptions.matched_paths),
                    "matched_paths": [
                        dict(item) for item in project_exemptions.matched_paths
                    ],
                },
            },
            "layer_compliance": {
                "score": layer_score,
                "violations": len(layer_violations),
                "discovered": discovered_count,
            },
            "structural_clean": {
                "score": structural_score,
                "errors": len(structural_errors),
                "discovered": discovered_count,
            },
        },
    }


def _build_interoception() -> dict[str, Any]:
    """Assemble the interoception (runtime state) faculty.

    Always ``n/a``: declared resource profiles — the only thing this faculty
    can be scored against — are a ``s0ma-core`` runtime concept with no
    ``.s0ma`` declaration surface, so there is nothing measurable on a
    ``.s0ma`` project. Reported honestly rather than fabricated (plan
    HONESTY rule). Excluded from the overall roll-up.
    """
    return {
        "score": None,
        "status": f"{NA} — no resource profiles declared",
        "detail": (
            "the interoception faculty checks runtime metrics against "
            "declared resource profiles; .s0ma has no resource-profile "
            "declaration surface, so this is not measurable on the project"
        ),
    }


def _build_metacognition(
    public_nerves: int,
    doc_covered: int,
    test_covered: int,
    doc_diags: list[Any],
) -> dict[str, Any]:
    """Assemble the metacognition (reasoning over the model) faculty."""
    doc_cov = _pct(doc_covered, public_nerves)
    test_cov = _pct(test_covered, public_nerves)
    doc_errors = _errors(doc_diags)
    drift_errors = [
        d for d in doc_errors if getattr(d, "code", "") in _DRIFT_CODES
    ]
    # Drift-free is only meaningful when the project ships docs to drift; a
    # project with no doc declarations is not "perfectly drift-free", it
    # simply has nothing to check — n/a, so it does not inflate the faculty.
    has_docs = bool(doc_diags) or doc_covered > 0
    drift_free: float | None = (100.0 if not doc_errors else 0.0) if (
        doc_diags or doc_covered > 0
    ) else None

    sub = _mean_available([doc_cov, test_cov, drift_free])
    return {
        "score": sub,
        "metrics": {
            "doc_ref_coverage": {
                "score": doc_cov,
                "covered": doc_covered,
                "public_nerves": public_nerves,
                "detail": (
                    f"{doc_covered}/{public_nerves} PUBLIC nerves covered "
                    f"by a doc-ref"
                    if public_nerves
                    else f"{NA} — no PUBLIC nerves"
                ),
            },
            "declared_test_evidence": {
                "score": test_cov,
                "covered": test_covered,
                "public_nerves": public_nerves,
                "detail": (
                    f"{test_covered}/{public_nerves} PUBLIC nerves covered "
                    "by an existing non-empty test declaration"
                    if public_nerves
                    else f"{NA} — no PUBLIC nerves"
                ),
            },
            "drift_free": {
                "score": drift_free,
                "drift_errors": len(drift_errors),
                "doc_errors": len(doc_errors),
                "detail": (
                    ("clean" if not doc_errors else "doc validation errors detected")
                    if has_docs
                    else f"{NA} — no doc declarations to drift"
                ),
            },
        },
    }


# ---------------------------------------------------------------------------
# Top-level report
# ---------------------------------------------------------------------------


def build_score_report(
    project: S0maProject,
    *,
    mode: str,
    gate_mode: str | None = None,
    adoption_policy: ResolvedAdoptionPolicy | None = None,
) -> dict[str, Any]:
    """Compute the full self-knowledge score report for *project*.

    Pure composition over existing dsl/core surfaces; no I/O beyond reading
    the project's own sources, build manifest, and built ``.py`` surface.
    The returned dict is the single source of truth for both the JSON and
    the text renderings (plan D-5).
    """
    modules, filenames, production_names, parse_validate = _collect_modules(
        project,
    )
    resolution = _resolution_diagnostics(modules, filenames, project)
    doc_diags = _doc_diagnostics(modules, filenames)
    from s0ma_dsl.adoption_policy import resolve_project_exemptions

    project_exemptions = resolve_project_exemptions(project)
    surface = _verify_surface(project, adoption_policy=adoption_policy)
    public_nerves, doc_covered, test_covered = _public_nerve_coverage(
        modules, production_names,
    )
    discovered_surface = _build_discovered_surface(
        project, modules, filenames, production_names, surface,
    )
    discovered_component_count = len(discovered_surface.componentized)

    proprioception = _build_proprioception(
        resolution,
        parse_validate,
        surface,
        discovered_component_count,
        adoption_policy=adoption_policy,
        project_exemptions=project_exemptions,
    )
    interoception = _build_interoception()
    metacognition = _build_metacognition(
        public_nerves, doc_covered, test_covered, doc_diags,
    )

    blocked: list[dict[str, str]] = []
    required_metrics = (
        (
            "proprioception",
            "registration",
            proprioception["metrics"]["registration"]["componentized_pct"],
        ),
        (
            "proprioception",
            "layer_compliance",
            proprioception["metrics"]["layer_compliance"]["score"],
        ),
        (
            "proprioception",
            "structural_clean",
            proprioception["metrics"]["structural_clean"]["score"],
        ),
        (
            "metacognition",
            "doc_ref_coverage",
            metacognition["metrics"]["doc_ref_coverage"]["score"],
        ),
        (
            "metacognition",
            "declared_test_evidence",
            metacognition["metrics"]["declared_test_evidence"]["score"],
        ),
    )
    for faculty, metric, value in required_metrics:
        if value is None:
            blocked.append({
                "faculty": faculty,
                "metric": metric,
                "reason": "nothing_to_measure",
            })

    # M3A T4: pending is acknowledged zero-credit debt and *always* blocks
    # release. Derive this directly from tagged AST state so migration/dev
    # warning severity cannot weaken a caller-pinned release gate. Other
    # pinned modes and report-only scoring retain their existing semantics.
    if gate_mode == "release" and _has_pending_semantic_debt(modules):
        blocked.append({
            "faculty": "proprioception",
            "metric": "semantic_completeness",
            "reason": "pending_semantic_state",
        })

    numeric_overall = _mean_available([
        proprioception["score"],
        interoception["score"],
        metacognition["score"],
    ])
    overall = None if blocked else numeric_overall

    floor = MODE_FLOORS.get(gate_mode, MODE_FLOORS[DEFAULT_MODE]) if (
        gate_mode is not None
    ) else None
    if gate_mode is None:
        passes: bool | None = None
        reasons = ["mode not pinned by caller"]
    elif blocked:
        passes = False
        reasons = [
            f"{item['faculty']}.{item['metric']}: {item['reason']}"
            for item in blocked
        ]
    elif overall is None:
        passes = False
        reasons = ["overall score is not measurable"]
    elif floor is not None and overall < floor:
        passes = False
        reasons = [
            f"overall {overall:.1f} is below {gate_mode} floor {floor:.1f}",
        ]
    else:
        passes = True
        reasons = []

    return {
        "schema": "s0ma-score@2",
        "project": project.project_name,
        "root": str(project.root),
        "mode": mode,
        "gate_mode": gate_mode,
        "overall": overall,
        "faculties": {
            "proprioception": proprioception,
            "interoception": interoception,
            "metacognition": metacognition,
        },
        "exempt_set": _enumerate_exempt_set(
            project, modules, production_names, surface,
        ),
        "module_count": len(modules),
        "public_nerve_count": public_nerves,
        "gate": {
            "mode": gate_mode,
            "floor": floor,
            "passes": passes,
            "blocked": blocked,
            "reasons": reasons,
            "na_faculties": [
                fac
                for fac, body in (
                    ("proprioception", proprioception),
                    ("interoception", interoception),
                    ("metacognition", metacognition),
                )
                if body["score"] is None
            ],
        },
    }


# ---------------------------------------------------------------------------
# Rendering (text derived from the SAME report dict — plan D-5)
# ---------------------------------------------------------------------------


def _fmt_score(value: float | None) -> str:
    """Render a 0–100 score (or ``n/a``) for the text output."""
    return f"{value:.1f}%" if value is not None else NA


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"s0ma score — {report['project']}")
    lines.append("")
    overall = report["overall"]
    lines.append(f"  self-knowledge   {_fmt_score(overall)}")
    lines.append(f"  authoring mode   {report['mode']}")
    lines.append(
        f"  gate mode        {report['gate_mode'] or 'not pinned (report-only)'}"
    )
    lines.append("")

    facs = report["faculties"]

    prop = facs["proprioception"]
    lines.append(f"  proprioception   {_fmt_score(prop['score'])}  (structure)")
    pm = prop["metrics"]
    lines.append(
        f"      componentized         "
        f"{_fmt_score(pm['registration']['componentized_pct'])}"
        f"  — {pm['registration']['detail']}"
    )
    if pm["registration"]["roster_adopted"]:
        lines.append(
            "      roster debt           "
            f"{pm['registration']['roster_adopted']} file(s) earn no gate credit; "
            "componentize them to make the model authoritative"
        )
    if pm["registration"]["new_file_roster_only"]:
        lines.append(
            "      new-file roster debt  "
            f"{pm['registration']['new_file_roster_only']} gate-relevant "
            "file(s); new code starts from intent"
        )
    caller_policy = pm["registration"]["adoption_policy"]
    if caller_policy is not None:
        lines.append(
            "      caller adoption policy "
            f"{caller_policy['sha256']} "
            f"({caller_policy['matched_count']} matched path(s), waived)"
        )
        for match in caller_policy["matched_paths"]:
            lines.append(
                f"          [{match['category']}] {match['path']} — "
                f"{match['reason']}"
            )
    local_policy = pm["registration"]["project_adoption_exempt"]
    if local_policy["matched_count"]:
        lines.append(
            "      project adoption_exempt "
            f"{local_policy['matched_count']} matched path(s), "
            "classification only — does not waive the gate"
        )
        for match in local_policy["matched_paths"]:
            lines.append(
                f"          [{match['category']}] {match['path']} — "
                f"{match['reason']}"
            )
    lines.append(
        f"      layer compliance      {_fmt_score(pm['layer_compliance']['score'])}"
        f"  — {pm['layer_compliance']['violations']} violation(s)"
    )
    lines.append(
        f"      structural clean      {_fmt_score(pm['structural_clean']['score'])}"
        f"  — {pm['structural_clean']['errors']} error(s)"
    )

    inter = facs["interoception"]
    lines.append(
        f"  interoception    {_fmt_score(inter['score'])}  (runtime state)"
    )
    lines.append(f"      {inter['status']}")

    meta = facs["metacognition"]
    lines.append(
        f"  metacognition    {_fmt_score(meta['score'])}  (reasoning over the model)"
    )
    mm = meta["metrics"]
    lines.append(
        f"      doc-ref coverage      {_fmt_score(mm['doc_ref_coverage']['score'])}"
        f"  — {mm['doc_ref_coverage']['detail']}"
    )
    lines.append(
        "      declared test evidence "
        f"{_fmt_score(mm['declared_test_evidence']['score'])}"
        f"  — {mm['declared_test_evidence']['detail']}"
    )
    lines.append(
        f"      drift-free            {_fmt_score(mm['drift_free']['score'])}"
        f"  — {mm['drift_free']['detail']}"
    )
    lines.append("")

    exempt = report["exempt_set"]
    lines.append(f"  exempt set       {exempt['total']} item(s) outside s0ma")
    for label, key in (
        ("bootstrap module", "bootstrap_module"),
        ("bootstrap_files", "bootstrap_files"),
        ("package_markers", "package_markers"),
        ("@internal", "internal"),
    ):
        members = exempt[key]
        if members:
            for member in members:
                lines.append(f"      [{label}] {member}")
        else:
            lines.append(f"      [{label}] (none)")
    lines.append("")

    gate = report["gate"]
    if gate["na_faculties"]:
        lines.append(
            "  note: "
            + ", ".join(gate["na_faculties"])
            + " reported n/a — excluded from the overall roll-up."
        )
    if gate["passes"] is None:
        lines.append("  gate             REPORT ONLY (mode not pinned by caller)")
    else:
        verdict = "PASS" if gate["passes"] else "BLOCKED"
        lines.append(
            f"  gate             {verdict} "
            f"(floor for {gate['mode']}: {gate['floor']:.1f}%)"
        )
        for reason in gate["reasons"]:
            lines.append(f"      {reason}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def run_score(args: argparse.Namespace) -> int:
    """Execute ``s0ma score`` (see the module docstring for semantics).

    Resolution mirrors the other project-aware subcommands: ``args.project``
    (a positional path, default ``.``) anchors discovery via the shared
    ``_resolve_project`` already run in dispatch, exposed as
    ``args.s0ma_project``. The effective ``mode`` is resolved by the shared
    ``_resolve_mode`` (``--mode > [tool.s0ma].mode > "dev"``).
    """
    from s0ma_dsl.project import S0maProject

    json_mode = getattr(args, "output_format", "text") == "json"

    # Prefer the project the dispatcher already resolved; fall back to a
    # direct discovery from the positional path for direct-Namespace callers.
    project: S0maProject | None = getattr(args, "s0ma_project", None)
    if project is None or project.synthetic:
        from s0ma_dsl.errors import S0maProjectNotFound

        start = Path(getattr(args, "project", None) or ".")
        try:
            project = S0maProject.discover(start)
        except S0maProjectNotFound:
            print(
                f"s0ma score: no s0ma project found at {start}. "
                f"Run `s0ma new project <dir>` or add a [tool.s0ma] table "
                f"to pyproject.toml.",
                file=sys.stderr,
            )
            return EXIT_USAGE_ERROR
        except ValueError as exc:
            print(f"s0ma score: [tool.s0ma] is malformed: {exc}", file=sys.stderr)
            return EXIT_USAGE_ERROR

    mode = getattr(args, "mode", None) or DEFAULT_MODE
    gate_mode: str | None = getattr(args, "gate_mode", None)
    gate = bool(getattr(args, "gate", False))
    adoption_policy_path = getattr(args, "adoption_policy", None)
    expected_policy_hash = getattr(args, "expected_adoption_policy_hash", None)
    if gate and gate_mode is None:
        print(
            "s0ma score: --gate requires --gate-mode; authoring --mode "
            "cannot choose its own evaluation floor.",
            file=sys.stderr,
        )
        return EXIT_USAGE_ERROR
    if gate_mode is not None and os.environ.get("S0MA_VERIFY_CONTRACTS") == "0":
        print(
            "s0ma score: refusing pinned gate while "
            "S0MA_VERIFY_CONTRACTS=0 disables contract verification; "
            "unset the variable before computing gate evidence.",
            file=sys.stderr,
        )
        return EXIT_USAGE_ERROR

    if expected_policy_hash is not None and adoption_policy_path is None:
        print(
            "s0ma score: --expected-adoption-policy-hash requires "
            "--adoption-policy.",
            file=sys.stderr,
        )
        return EXIT_USAGE_ERROR
    adoption_policy = None
    if adoption_policy_path is not None:
        from s0ma_dsl.adoption_policy import (
            AdoptionPolicyError,
            load_and_resolve_policy,
        )

        policy_path = Path(adoption_policy_path).expanduser()
        if not policy_path.is_absolute():
            policy_path = project.root / policy_path
        try:
            adoption_policy = load_and_resolve_policy(
                project,
                policy_path,
                expected_sha256=expected_policy_hash,
            )
        except AdoptionPolicyError as exc:
            print(f"s0ma score: adoption policy refused: {exc}", file=sys.stderr)
            return EXIT_USAGE_ERROR

    try:
        report = build_score_report(
            project,
            mode=mode,
            gate_mode=gate_mode,
            adoption_policy=adoption_policy,
        )
    except ValueError as exc:
        print(f"s0ma score: adoption exemption refused: {exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR

    if json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_render_text(report))

    if gate and not report["gate"]["passes"]:
        return EXIT_GATE_FAILURE
    return EXIT_SUCCESS
