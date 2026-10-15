#!/usr/bin/env python3
"""s0ma workspace check — the monorepo's unified verification pipeline.

Ported from ``packages/s0ma-core/scripts/check.py`` (the single-package
self-check) to the workspace root for the 0.5.0 consolidation. One command
runs every CI gate (PRD NFR-1):

1. ruff over ``packages/``
2. mypy --strict over s0ma-core (run from the package directory so its
   ``[tool.mypy]`` overrides load — from the repo root they never do and
   mypy reports bogus import-untyped errors)
3. mypy --strict over s0ma-mcp (same from-the-package-dir rule)
4. mypy --strict over s0ma-dsl (same from-the-package-dir rule; gated
   since 0.8.0 DSL-M5 — the package is now strict-clean and ships
   ``py.typed``, closing the 0.5.0-era follow-up). Runs TWICE: the
   native view plus ``--platform win32``, because mypy resolves
   ``sys.platform`` conditionals for the running platform only — a
   Windows-only block can be strict-broken while every POSIX run stays
   green (the DSL-M5 repair lesson)
5. mypy --strict over s0ma-studi0 (same from-the-package-dir rule).
   Also runs TWICE, for a different reason — the ADR-001 self-hosted
   layout: the handwritten view with ``_built/`` excluded, then the
   committed build output analyzed FLAT with ``MYPYPATH`` pointing at
   it, because a single package-rooted walk cannot resolve the built
   modules' flat cross-imports (they import each other by canonical
   name, the way the runtime bootstrap loads them)
6. the s0ma-core test suite
7. the s0ma-dsl test suite
8. the s0ma-mcp test suite
9. the s0ma-studi0 test suite
10. the Claude integration (``integrations/``: the launcher, the Claude Code
    plugin and the Claude Desktop extension). Ruff over the whole tree, the
    launcher held to ``mypy --strict`` in BOTH the native and the
    ``--platform win32`` view (it is the one file two shipped packages carry
    a copy of, and it runs on Windows for real), the sync script's
    ``--check`` (the launcher copies, the three version sites and the
    feedback skill's body are what the monorepo says they are — see
    ``scripts/sync_integrations.py``), then the integrations test suite.
    Slotted after the four package suites because it is not one of them: it
    gates what is SHIPPED AROUND the packages, and its tests perform real
    offline installs with ``uv``, which takes about forty seconds
11. the documentation application (see ``scripts/check_docs_application.py``):
    compose ``docs/``'s snapshot from scratch, run every coverage /
    authority / link / version / mirror / drift gate, render every
    artifact to a temporary directory and byte-compare it against what is
    committed, and prove the committed ``docs/_built/`` tree is what the
    sources produce at another path. Offline and repository-write-free by
    construction (ADR-012 §4's charter). Slotted HERE, after the four
    suites and before ``selfhost-build``, because the suites must be green
    before anything composes their registries and because
    ``selfhost-build`` rebuilds committed builds in place — a
    documentation failure should be reported while the tree is still the
    tree that was committed
12. release integrity under the existing ``selfhost-build`` stage: rebuild
    each self-hosted package (packages/s0ma-mcp, packages/s0ma-studi0) from
    its .s0ma sources and byte-compare the committed output, check generated
    onboarding/surface inventories, build and inspect all four wheels'
    licenses and the studi0 wheel's shipped build payload, then execute the
    cold installed journey
13. the INV-1 spelling guard (see ``spelling_guard`` below)
14. the version-currency guard (see ``scripts/check_version_refs.py``): the
    four pyproject versions and four ``__version__`` literals are in INV-4
    lockstep, AND every version-shaped string in the docs that describe the
    current release is that lockstep version or an allowlisted historical fact
15. the authored-lines guard (see ``scripts/check_authored_lines.py``): every
    ``intent``, ``guarantees``, ``invariants``, ``schema`` and ``forbids`` line
    in the repository's own .s0ma sources, fixtures and spike fixtures, and in
    the registrations written in Python (``@component``, ``ComponentSpec`` and
    ``Contract`` under ``packages/*/src``), stands on its own - no milestone,
    run, plan, date or ruling - and every requirement, invariant, ADR,
    contract revision or specification section it cites resolves against the
    record that defines it
16. the intra-repo link and anchor guard (see ``scripts/check_links.py``):
    every repository-relative Markdown link resolves to a tracked file or
    directory, and every intra-repo ``#anchor`` resolves to a real heading

Unlike the original, this runner does NOT stop at the first failure: every
stage runs, each reports PASS/FAIL with its duration, a summary table is
printed, and the exit code is non-zero if ANY stage failed. (CI diagnosis
from a single run beats fail-fast here; use ``--only`` for a quick loop.)

Usage:
    uv run python scripts/check.py                 # everything (what CI runs)
    uv run python scripts/check.py --only ruff spelling
    uv run python scripts/check.py --list

Adding a package:
    ruff and the spelling guard pick it up automatically; add one
    ``Stage("pytest-<name>", ...)`` entry to STAGES below for its test
    suite (and a mypy stage if it is strict-clean — s0ma-mcp and
    s0ma-studi0 are, and carry both). If it is self-hosted (its build
    output is committed and shipped), add a ``SelfHosted`` record and one
    ``_selfhost`` sub-step to the selfhost-build stage.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Spelling guard (INV-1 — the naming law)
# ---------------------------------------------------------------------------
#
# The product is spelled "s0ma" (digit zero), always. The letter-o spelling
# must not appear in the tree outside a fixed allowlist (plan
# ``plans/s0ma-new-consolidation-1.md`` Part 1 §1.4/§1.5; PRD INV-1):
#
#   1. Directories named ``plans`` at any depth — the consolidation plan and
#      the historical per-package plans quote the forbidden spelling when
#      defining the rename.
#   2. The repo-root ``references/`` directory — the PRD necessarily quotes
#      the forbidden spelling where it defines the naming law itself
#      (INV-1). Exactly one PRD line needs this exemption today; its other
#      mentions carry both spellings and so pass as mixed lines. (Line
#      numbers are deliberately not cited: they drift with every PRD
#      amendment, and this comment outlived three of them.) The governance
#      doc that defines the rule is the same class as ``plans/`` even though
#      the PRD's own INV-1 exception list does not name it (the PRD is
#      non-self-referential, not a license to fail CI). ROOT-ONLY on
#      purpose: ``packages/*/docs/references/`` are product docs and ARE
#      guarded.
#   3. Per-package ``packages/*/CHANGELOG.md`` — pre-monorepo release history
#      describes artifacts as they were named then. The ROOT CHANGELOG.md is
#      deliberately NOT excluded: new entries must keep any legacy spelling
#      on the same line as its s0ma replacement (a "mixed" line, see below).
#   4. Lines marked ``# legacy-spelling: intentional`` (same line) — the
#      ``s0ma migrate-ext`` machinery and its tests must name the legacy
#      extensions/table they migrate.
#   5. "Mixed" lines that also contain the digit spelling (any case) — e.g.
#      changelog/docs lines of the form `old → new`. This mirrors the plan's
#      ``grep -viE 's0ma'`` filter.
#
# Implementation notes (hard-won in M2/M3 audits): the guard tests each
# line's CONTENT only. Filtering grep-style ``path:line:content`` strings
# self-destructs in this repo because every path contains "s0ma", so the
# digit-spelling filter would drop every hit. Hence pure Python, per line.
#
# The letter pattern is written with a one-character class, ``s[o]ma``, so
# that this file's own source never contains the forbidden literal (the
# classic self-excluding-grep trick); as a regex it still matches exactly
# the letter-o spelling, case-insensitively.

LETTER_RE = re.compile(r"s[o]ma", re.IGNORECASE)
DIGIT_RE = re.compile(r"s0ma", re.IGNORECASE)
LEGACY_MARKER = "legacy-spelling: intentional"

# Directory NAMES pruned at any depth.
EXCLUDED_DIR_NAMES = {
    # VCS / tool caches (the plan snippet's exclusion set)
    ".git",
    # Claude Code tool-state dir. Notably ``.claude/worktrees/`` holds
    # nested git worktrees — full repo checkouts at arbitrary (often
    # older) commits — which must not be re-scanned: they would flag
    # pre-consolidation content and make the guard non-deterministic
    # (dependent on which sessions left worktrees around). Pruned for
    # the same reason as ``.git`` — it is not the product source tree.
    ".claude",
    ".venv",
    "venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
    "__pycache__",
    # governance docs that define/quote the rule (allowlist item 1; the
    # root-only ``references/`` exclusion — item 2 — lives in the walk)
    "plans",
    # build outputs and regenerable s0ma caches (binary or derived-from-
    # guarded-sources; pruning avoids stale-cache false positives)
    "dist",
    ".s0ma.cache",
    "__s0ma_cache__",
    ".s0ma",
}


def _is_package_changelog(rel: Path) -> bool:
    """True for ``packages/<pkg>/CHANGELOG.md`` (allowlist item 3)."""
    parts = rel.parts
    return len(parts) == 3 and parts[0] == "packages" and parts[2] == "CHANGELOG.md"


def spelling_guard(root: Path = ROOT, *, quiet: bool = False) -> int:
    """Scan the tree for the forbidden letter-o spelling. Return violation count."""
    violations: list[tuple[Path, int, str]] = []
    skipped_dirs = 0
    scanned = 0

    stack = [root]
    while stack:
        directory = stack.pop()
        for entry in sorted(directory.iterdir()):
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if (
                    entry.name in EXCLUDED_DIR_NAMES
                    or entry.name.endswith(".egg-info")
                    # allowlist item 2: the ROOT governance dir only —
                    # packages/*/docs/references/ stay guarded
                    or entry.relative_to(root).parts == ("references",)
                ):
                    skipped_dirs += 1
                    continue
                stack.append(entry)
                continue
            if not entry.is_file():
                continue
            rel = entry.relative_to(root)
            if _is_package_changelog(rel):
                continue
            data = entry.read_bytes()
            if b"\0" in data[:8192]:  # binary, grep -I semantics
                continue
            scanned += 1
            for lineno, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                if not LETTER_RE.search(line):
                    continue
                if DIGIT_RE.search(line):  # mixed line (allowlist item 5)
                    continue
                if LEGACY_MARKER in line:  # marked line (allowlist item 4)
                    continue
                violations.append((rel, lineno, line.strip()))

    if not quiet:
        print(f"spelling guard: scanned {scanned} text files ({skipped_dirs} dirs excluded)")
    for rel, lineno, text in violations:
        print(f"VIOLATION {rel}:{lineno}: {text[:160]}")
    if violations and not quiet:
        print(
            f"\n{len(violations)} forbidden letter-o spelling(s) found. The product is"
            f" spelled s0ma (digit zero) — see PRD INV-1 and the root README."
        )
    return len(violations)


def _spelling_stage() -> int:
    return 0 if spelling_guard() == 0 else 1


# ---------------------------------------------------------------------------
# selfhost-build (FR-MCP-11 / selfhost plan D-4 — the committed-build
# equality gate)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SelfHosted:
    """A self-hosted package: .s0ma sources in ``s0ma_src/``, build committed.

    ``declared_mode`` mirrors the package's ``[tool.s0ma].mode``. The stage
    never passes ``--mode``: since 0.8.0 the CLI reads that key itself, and
    the build below deliberately proves the table-driven path (see the long
    note on the build invocation). The field exists so a red stage can print
    the package's own posture in its remediation hint.
    """

    distribution: str
    root: Path
    built: Path
    declared_mode: str


#: The self-hosted packages and their committed build directories (ADR-001:
#: .s0ma sources in s0ma_src/, build output committed under src/<pkg>/_built).
#: BOTH ship that output in their wheel, so for both a stale commit of it is
#: a release defect — s0ma-studi0 joined this gate at studi0-v1 M7, once its
#: committed build became load-bearing product rather than a scratch artifact.
MCP_SELFHOST = SelfHosted(
    distribution="s0ma-mcp",
    root=ROOT / "packages" / "s0ma-mcp",
    built=ROOT / "packages" / "s0ma-mcp" / "src" / "s0ma_mcp" / "_built",
    declared_mode="release",
)
STUDI0_SELFHOST = SelfHosted(
    distribution="s0ma-studi0",
    root=ROOT / "packages" / "s0ma-studi0",
    built=ROOT / "packages" / "s0ma-studi0" / "src" / "s0ma_studi0" / "_built",
    declared_mode="strict",
)


def _built_snapshot(built_dir: Path) -> dict[str, bytes]:
    """Every committed file under *built_dir* as relative-POSIX → bytes.

    The regenerable ``.s0ma.cache/`` subtree is not part of the build
    output (it is gitignored and the stage builds with ``--no-cache``)
    and is skipped if a local cached build left one behind.
    """
    snapshot: dict[str, bytes] = {}
    for path in sorted(built_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(built_dir).as_posix()
        if rel.startswith(".s0ma.cache/") or "/__pycache__/" in f"/{rel}":
            continue
        snapshot[rel] = path.read_bytes()
    return snapshot


def selfhost_build_stage(package: SelfHosted) -> int:
    """Rebuild *package* from its .s0ma sources; assert byte-equality.

    Every self-hosted package's wheel ships the transpiler's COMMITTED
    build output (``src/<pkg>/_built/``: FR-MCP-11 for s0ma-mcp, the
    same posture for s0ma-studi0 — its runtime bootstraps those emitted
    modules at import time), so the committed bytes must be exactly what
    ``s0ma build`` reproduces from ``s0ma_src/`` on every machine and
    OS. This stage rebuilds in place with the cache disabled
    (``--project-root`` per friction-log F-M0-1 — discovery anchors on
    the CWD, never the path argument), byte-compares every file against
    the pre-stage snapshot, lists each differing/missing/unexpected
    file, and ALWAYS restores the snapshot so a red stage never leaves
    the working tree dirty.

    A red stage means one of exactly two things, and both are real
    failures — never flaky:

    * you edited a ``.s0ma`` source (or the transpiler) and forgot to
      rebuild and commit the build output — remediation: run
      ``uv run s0ma --project-root packages/<pkg> build packages/<pkg>
      --mode <declared mode>`` and commit ``s0ma_src/`` and ``_built/``
      together (one commit, plan D-4); or
    * the transpiler stopped being deterministic/portable for the same
      input (a P-4/INV-5 regression — fix it in s0ma-dsl, never paper
      over it here). This stage is the standing cross-platform
      determinism regression test: the committed bytes were produced
      on one machine and re-derived on every CI OS.
    """
    label = package.distribution
    relative_root = package.root.relative_to(ROOT).as_posix()
    if not package.built.is_dir():
        print(f"selfhost-build ({label}): committed build dir missing: {package.built}")
        return 1

    before = _built_snapshot(package.built)
    if not before:
        print(f"selfhost-build ({label}): committed build dir is empty: {package.built}")
        return 1
    print(
        f"selfhost-build ({label}): rebuilding {relative_root} from .s0ma sources "
        f"({len(before)} committed file(s) under "
        f"{package.built.relative_to(ROOT).as_posix()})"
    )

    try:
        proc = subprocess.run(
            [
                # DSL-M4 (F-M0-3): ``-m s0ma_dsl`` (via the new package
                # ``__main__``) instead of ``-m s0ma_dsl.cli.main`` — the
                # latter trips a runpy RuntimeWarning that would pollute
                # this stage's captured stderr.
                sys.executable, "-m", "s0ma_dsl",
                "--project-root", str(package.root),
                "build", str(package.root),
                # DSL-M3 (friction log F-M1-2): no --mode flag. Each
                # package's pyproject declares [tool.s0ma].mode (release
                # for s0ma-mcp, strict for s0ma-studi0), and as of 0.8.0
                # the CLI READS that key (precedence:
                # --mode flag > [tool.s0ma].mode > the command's built-in
                # default), so this stage proves the table-driven path on
                # every gate run. Release mode still enforces the doc/test
                # coverage gates and renders the doc-ref/doc-guide artifacts
                # under _built/docs/ (byte-gated like every other output) —
                # but the strictness now flows from the table, not a
                # lockstep flag. (Pre-0.8.0 the table was declarative-only,
                # so the ramp dev -> strict -> release required editing this
                # stage in lockstep with pyproject and the README snippet;
                # that triple-edit collapses to the one-line pyproject key.)
                "--no-cache",
                "--quiet",
            ],
            cwd=ROOT,
        )
        if proc.returncode != 0:
            print(
                f"selfhost-build ({label}): `s0ma build` failed (exit "
                f"{proc.returncode}) — the .s0ma sources do not build; "
                f"fix them before worrying about byte-equality."
            )
            return 1

        after = _built_snapshot(package.built)
        changed = sorted(
            rel
            for rel in before.keys() & after.keys()
            if before[rel] != after[rel]
        )
        missing = sorted(before.keys() - after.keys())
        unexpected = sorted(after.keys() - before.keys())

        if not (changed or missing or unexpected):
            print(
                f"selfhost-build ({label}): PASS — rebuild byte-identical to "
                f"the committed build ({len(after)} file(s))"
            )
            return 0

        print(
            f"selfhost-build ({label}): FAIL — rebuild differs from the "
            f"committed build output:"
        )
        for rel in changed:
            print(f"  CHANGED    {rel}")
        for rel in missing:
            print(f"  MISSING    {rel} (committed, not re-emitted)")
        for rel in unexpected:
            print(f"  UNEXPECTED {rel} (re-emitted, not committed)")
        print(
            f"  -> either a .s0ma/transpiler change was not rebuilt+"
            f"committed (run `uv run s0ma --project-root {relative_root} "
            f"build {relative_root} --mode {package.declared_mode}` and "
            f"commit s0ma_src/ + _built/ together), or build determinism "
            f"regressed (P-4/INV-5 — fix s0ma-dsl). Both are real failures."
        )
        return 1
    finally:
        # Restore the committed bytes unconditionally so the gate never
        # mutates the tree it is checking (red or green, local or CI).
        for rel, data in before.items():
            target = package.built / Path(rel)
            if not target.is_file() or target.read_bytes() != data:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        for path in sorted(package.built.rglob("*"), reverse=True):
            if not path.is_file():
                continue
            rel = path.relative_to(package.built).as_posix()
            if rel.startswith(".s0ma.cache/") or "/__pycache__/" in f"/{rel}":
                continue
            if rel not in before:
                path.unlink()


def _selfhost(package: SelfHosted) -> Callable[[], int]:
    """Bind *package* into the zero-argument callable ``_seq`` runs."""

    def run() -> int:
        return selfhost_build_stage(package)

    return run


# ---------------------------------------------------------------------------
# Stage runner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Stage:
    name: str
    label: str
    action: Callable[[], int]


def _cmd(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> Callable[[], int]:
    """Run *args* in *cwd*; *env* entries overlay the inherited environment."""

    def run() -> int:
        overlay = {**os.environ, **env} if env else None
        return subprocess.run(args, cwd=cwd, env=overlay).returncode

    return run


def _seq(*steps: tuple[str, Callable[[], int]]) -> Callable[[], int]:
    """Compose labelled sub-commands into one stage.

    ALL steps run even after a failure (same diagnose-everything-in-one-pass
    philosophy as the stage runner itself); the first nonzero code wins.
    """

    def run() -> int:
        codes: list[int] = []
        for label, action in steps:
            print(f"  -- {label}", flush=True)
            codes.append(action())
        return next((code for code in codes if code != 0), 0)

    return run


PY = [sys.executable, "-m"]

STAGES: list[Stage] = [
    Stage("ruff", "ruff over packages/", _cmd([*PY, "ruff", "check", "packages/"], ROOT)),
    Stage(
        "mypy-core",
        "mypy --strict on s0ma-core (from packages/s0ma-core so [tool.mypy] loads)",
        _cmd([*PY, "mypy", "src/s0ma", "--strict"], ROOT / "packages" / "s0ma-core"),
    ),
    Stage(
        "mypy-mcp",
        "mypy --strict on s0ma-mcp (from packages/s0ma-mcp so [tool.mypy] loads)",
        _cmd([*PY, "mypy", "src/s0ma_mcp", "--strict"], ROOT / "packages" / "s0ma-mcp"),
    ),
    Stage(
        "mypy-dsl",
        "mypy --strict on s0ma-dsl, native + win32 views (from packages/s0ma-dsl)",
        _seq(
            (
                "native view",
                _cmd([*PY, "mypy", "src/s0ma_dsl", "--strict"], ROOT / "packages" / "s0ma-dsl"),
            ),
            (
                # mypy resolves sys.platform conditionals for the RUNNING
                # platform, so a Windows-only block is invisible to POSIX runs
                # (the DSL-M5 repair lesson: TextIO.reconfigure). The win32
                # re-analysis catches that class before CI does. Separate
                # cache dir — the two views would thrash one shared cache.
                "win32 view (--platform win32)",
                _cmd(
                    [
                        *PY,
                        "mypy",
                        "src/s0ma_dsl",
                        "--strict",
                        "--platform",
                        "win32",
                        "--cache-dir",
                        ".mypy_cache/win32",
                    ],
                    ROOT / "packages" / "s0ma-dsl",
                ),
            ),
        ),
    ),
    Stage(
        "mypy-studi0",
        "mypy --strict on s0ma-studi0, handwritten + built views (from packages/s0ma-studi0)",
        _seq(
            (
                # The single handwritten module (the bootstrap package
                # __init__). ``_built/`` is excluded here and checked by the
                # second view instead — see below.
                "handwritten view (_built excluded)",
                _cmd(
                    [*PY, "mypy", "src/s0ma_studi0", "--strict", "--exclude", "/_built/"],
                    ROOT / "packages" / "s0ma-studi0",
                ),
            ),
            (
                # The committed build output is held to the same --strict gate
                # as handwritten code (D-2/INV-8), but it cannot be checked by
                # the walk above: the emitted modules import each OTHER by
                # their canonical FLAT names (``import studi0_state``), which
                # is how the runtime bootstrap loads them and NOT how a
                # package-rooted walk resolves them (ADR-001 layout; found in
                # M3 of the studi0 plan). Analyzing _built as its own flat
                # root with MYPYPATH pointing at it reproduces the runtime's
                # module namespace exactly. Separate cache dir — the two views
                # give the same files different module names and would thrash
                # one shared cache.
                "built view (flat modules, MYPYPATH=_built)",
                _cmd(
                    [
                        *PY,
                        "mypy",
                        "--explicit-package-bases",
                        "src/s0ma_studi0/_built",
                        "--strict",
                        "--cache-dir",
                        ".mypy_cache/built",
                    ],
                    ROOT / "packages" / "s0ma-studi0",
                    {"MYPYPATH": "src/s0ma_studi0/_built"},
                ),
            ),
        ),
    ),
    Stage(
        "pytest-core",
        "s0ma-core test suite",
        _cmd([*PY, "pytest", "tests", "-q"], ROOT / "packages" / "s0ma-core"),
    ),
    Stage(
        "pytest-dsl",
        "s0ma-dsl test suite",
        _cmd([*PY, "pytest", "tests", "-q"], ROOT / "packages" / "s0ma-dsl"),
    ),
    Stage(
        "pytest-mcp",
        "s0ma-mcp test suite",
        _cmd([*PY, "pytest", "tests", "-q"], ROOT / "packages" / "s0ma-mcp"),
    ),
    Stage(
        "pytest-studi0",
        "s0ma-studi0 test suite",
        _cmd([*PY, "pytest", "tests", "-q"], ROOT / "packages" / "s0ma-studi0"),
    ),
    Stage(
        # What is shipped AROUND the four packages: one standard-library
        # launcher and the two thin wrappers that carry a copy of it (the
        # Claude Code plugin, the Claude Desktop extension). Placed after the
        # package suites — nothing here can be judged until the packages that
        # produce the version and the scaffolded feedback skill are green —
        # and before docs-application, which is where the tree stops being
        # the tree that was committed.
        #
        # Five steps, all of them run even after one fails (``_seq``):
        #
        #   1. ruff over integrations/ AND the two integration scripts (the
        #      sync script and the marketplace export), which live in
        #      scripts/ and are otherwise linted by nothing (the ruff stage
        #      above reads packages/ only).
        #   2-3. the launcher under ``mypy --strict`` TWICE. Same reason as
        #      mypy-dsl's second view: mypy resolves sys.platform
        #      conditionals for the running platform only, so the launcher's
        #      Windows branches — process spawning, signal forwarding,
        #      Scripts/ layouts — are invisible to a POSIX-only run. The
        #      launcher is one file two shipped packages copy, so a
        #      strict-broken Windows branch would ship twice. Ruled binding
        #      at the L1 gate (plan beta-prep-2-claude §4.3, ruling 7).
        #      Separate cache dir for the win32 view: the two views would
        #      thrash one shared cache.
        #   4. the sync script's --check: the two launcher copies are byte
        #      copies, the plugin manifest / extension manifest / extension
        #      pyproject all state the lockstep version, and the plugin's
        #      feedback skill has the body ``s0ma new project`` scaffolds.
        #      One command fixes every one of them, and it says so.
        #   5. the integrations suite. It takes about forty seconds because
        #      the launcher's tests perform real (offline) installs with uv
        #      against a fake control plane — deliberate: an install path
        #      proven with mocks is not proven.
        "integrations",
        "the Claude integration (lint, launcher strict-typed in both views, copies in step, tests)",
        _seq(
            (
                "ruff over integrations/, the sync script and the marketplace export",
                _cmd(
                    [
                        *PY,
                        "ruff",
                        "check",
                        "integrations/",
                        "scripts/sync_integrations.py",
                        "scripts/export_claude_marketplace.py",
                    ],
                    ROOT,
                ),
            ),
            (
                "launcher: mypy --strict, native view",
                _cmd([*PY, "mypy", "integrations/launcher/s0ma_launch.py", "--strict"], ROOT),
            ),
            (
                "launcher: mypy --strict, win32 view (--platform win32)",
                _cmd(
                    [
                        *PY,
                        "mypy",
                        "integrations/launcher/s0ma_launch.py",
                        "--strict",
                        "--platform",
                        "win32",
                        "--cache-dir",
                        ".mypy_cache/win32",
                    ],
                    ROOT,
                ),
            ),
            (
                "launcher copies, manifest versions and the feedback skill are in step",
                _cmd([sys.executable, "scripts/sync_integrations.py", "--check"], ROOT),
            ),
            (
                "integrations test suite",
                _cmd([*PY, "pytest", "integrations", "-q"], ROOT),
            ),
        ),
    ),
    Stage(
        # ADR-012 §4 fixes this slot: after the four suites, before
        # selfhost-build. The suites have to be green before anything
        # composes their registries, and selfhost-build rebuilds committed
        # _built/ trees IN PLACE — so a documentation failure has to be
        # reported while the tree is still the tree that was committed.
        # Unlike that stage, this one never writes under the checkout: it
        # builds a copy of the documentation project in a temporary
        # directory (which is also the cross-path determinism proof) and
        # renders every artifact to another one.
        "docs-application",
        "the documentation application (ADR-012 §4: compose, gate, byte-compare, offline)",
        _cmd([sys.executable, "scripts/check_docs_application.py"], ROOT),
    ),
    Stage(
        "selfhost-build",
        "release integrity (selfhost equality, generated knowledge, wheel licenses, cold install)",
        _seq(
            (
                "selfhost committed-build equality (s0ma-mcp)",
                _selfhost(MCP_SELFHOST),
            ),
            (
                # studi0's committed _built/ ships in its wheel and its
                # runtime bootstraps from it — held to the identical
                # byte-equality gate since studi0-v1 M7.
                "selfhost committed-build equality (s0ma-studi0)",
                _selfhost(STUDI0_SELFHOST),
            ),
            (
                "generated README/onboarding inventory",
                _cmd([sys.executable, "scripts/generate_mcp_readme_surfaces.py"], ROOT),
            ),
            (
                "wheel metadata and cold installed outcome journey",
                _cmd([sys.executable, "scripts/wheel_smoke.py"], ROOT),
            ),
        ),
    ),
    Stage("spelling", "spelling guard (INV-1: s0ma, never the letter-o spelling)", _spelling_stage),
    Stage(
        "docs-version-currency",
        "version currency (INV-4 lockstep across pyprojects/__version__ + no stale versions in the guides)",
        _cmd([sys.executable, "scripts/check_version_refs.py"], ROOT),
    ),
    Stage(
        "authored-lines",
        "authored lines stand on their own (no milestone/run/plan/date/ruling in intent, guarantees, invariants, schema, forbids; every cited id resolves)",
        _cmd([sys.executable, "scripts/check_authored_lines.py"], ROOT),
    ),
    Stage(
        "docs-links",
        "docs link + anchor resolution (no dead relative links or heading anchors)",
        _cmd([sys.executable, "scripts/check_links.py"], ROOT),
    ),
]


def main(argv: list[str] | None = None) -> int:
    # Windows consoles/redirections can default to cp1252, where the spelling
    # guard's VIOLATION echo and the em-dash summary line would raise
    # UnicodeEncodeError and kill the gate's own reporting. Force UTF-8 with
    # replacement; on POSIX (already UTF-8) this is byte-for-byte invisible.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # non-TextIOWrapper streams (e.g. captured/wrapped)
        pass

    parser = argparse.ArgumentParser(description="s0ma workspace check (all CI gates)")
    parser.add_argument(
        "--only",
        nargs="+",
        choices=[s.name for s in STAGES],
        metavar="STAGE",
        help=f"run only these stages (of: {', '.join(s.name for s in STAGES)})",
    )
    parser.add_argument("--list", action="store_true", help="list stages and exit")
    opts = parser.parse_args(argv)

    if opts.list:
        for stage in STAGES:
            print(f"{stage.name:12} {stage.label}")
        return 0

    selected = [s for s in STAGES if not opts.only or s.name in opts.only]
    print("=== s0ma workspace check ===")
    results: list[tuple[Stage, int, float]] = []
    for stage in selected:
        print(f"\n{'=' * 72}\n  {stage.name}: {stage.label}\n{'=' * 72}")
        start = time.monotonic()
        code = stage.action()
        elapsed = time.monotonic() - start
        results.append((stage, code, elapsed))
        print(f"  {'PASSED' if code == 0 else 'FAILED'}: {stage.name} ({elapsed:.1f}s)")

    print(f"\n{'=' * 72}\n  Summary\n{'=' * 72}")
    for stage, code, elapsed in results:
        print(f"  {'PASS' if code == 0 else 'FAIL':4}  {stage.name:12} {elapsed:7.1f}s")
    failed = [stage.name for stage, code, _ in results if code != 0]
    if failed:
        print(f"\nFAILED stage(s): {', '.join(failed)}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
