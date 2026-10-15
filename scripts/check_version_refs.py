#!/usr/bin/env python3
"""Version-currency guard — the ``docs-version-currency`` stage.

Two invariants, both anchored on one lockstep version — s0ma-core's
``project.version`` (the bottom of the dependency stack; PRD INV-4):

1. LOCKSTEP INTEGRITY. All four distributions ship the same version. The
   ``project.version`` field of each ``packages/*/pyproject.toml`` and the
   ``__version__`` literal of each package ``__init__`` must equal the
   anchor. Before this gate that was enforced only by convention and the
   release script, so a hand-bump that missed one of the eight sites — or a
   merge that reverted one — shipped mismatched wheels with nothing in CI to
   catch it. LOCKSTEP_SITES below makes it mechanical.

2. LIVING-DOCS CURRENCY. Version strings in prose rot silently. A release
   bumps the eight lockstep sites, but a wheel filename buried in a README
   example or a version stamped in a page title is only ever caught by a
   human noticing. After a bump, every version-shaped string in the LIVING
   DOCS below must be the current lockstep version or an explicitly
   allowlisted historical fact.

LOCKSTEP_SITES are read structurally — tomllib for the pyprojects, ast for
the ``__version__`` literals — never imported (these ``__init__`` run
bootstrap import machinery) and never scanned as prose.

What the doc scan reads, and what it deliberately does not:

* LIVING_DOCS are pages that describe the CURRENT release to a reader
  installing or operating s0ma today. A stale version there is a defect.
* ``CHANGELOG.md`` and its mirror ``packages/s0ma-mcp/src/s0ma_mcp/_docs/
  CHANGELOG.md`` are NOT scanned and never should be: a changelog is a
  historical record whose released sections legitimately name every version
  s0ma has ever had.
* ``plans/``, ``docs/archive/``, ``docs/historical/`` and package changelogs
  are historical for the same reason.

Detection is deliberately broad: every LIVING_DOCS page is s0ma prose, so
every ``0.N.M`` in one is a s0ma version reference unless it sits directly
behind a third-party tool name (``uv 0.9.21``). Narrowing happens through
the explicit ALLOWLIST, not through clever heuristics — a genuinely
historical sentence becomes a recorded decision with a justification rather
than a silent regex exemption. The alternative (only look at lines that say
"s0ma" or "wheel") reads well but has a false-negative hole: a stale version
in a sentence that happens to name neither would sail straight through.

Anti-vacuity: a doc scan that finds fewer than ``MINIMUM_REFERENCES``
version references fails, exactly as ``scripts/check_links.py`` refuses a
linkless scan. Every invariant here is enforced by *finding* something —
a stale version is only reported once VERSION_RE has matched it — so a
matcher narrowed to nothing reports "0 version reference(s)" and passes
forever, which is the one way this gate can rot into decoration. The floor
says so instead. (The map half already had its floor in MIN_PACKAGES; the
scan half did not, which is what milestone I3 closed.)

The same stage carries one adjacent shape check (PACKAGE_MAPS below): every
distribution under ``packages/*/pyproject.toml`` must be named in
``CONTRIBUTING.md``'s workspace tree and in ``AGENTS.md``'s package map. The
toolchain was documented as three packages for several releases after
``s0ma-studi0`` joined it, because adding a package to the repo and adding it
to those two maps are separate acts and only the first one is enforced by
anything. The expected list is derived from the manifests, so a fifth package
is required in both maps from the moment its manifest exists.

Usage (no arguments, no network, deterministic):

    uv run python scripts/check_version_refs.py
    uv run python scripts/check.py --only docs-version-currency
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The lockstep version is read from s0ma-core's pyproject: all four
#: distributions carry the same version (PRD INV-4), and core is the anchor
#: at the bottom of the dependency stack.
VERSION_SOURCE = "packages/s0ma-core/pyproject.toml"


@dataclass(frozen=True)
class LockstepSite:
    """One site PRD INV-4 requires to carry the lockstep version.

    ``kind`` selects how the version is read without importing the file:
    ``"pyproject"`` parses ``project.version`` with tomllib, ``"module"``
    reads the module-level ``__version__`` string literal with ast.
    """

    path: str
    kind: str


#: Every site that must carry the anchor version verbatim (PRD INV-4): the
#: four ``project.version`` fields and the four package ``__version__``
#: literals. VERSION_SOURCE is itself listed — the check compares it to
#: itself, which costs nothing and keeps this the single complete roster of
#: INV-4 sites. Enforced here so a bump or bad merge that misses one site
#: fails CI, not only the release script (its sole guard before).
LOCKSTEP_SITES: tuple[LockstepSite, ...] = (
    LockstepSite(VERSION_SOURCE, "pyproject"),
    LockstepSite("packages/s0ma-dsl/pyproject.toml", "pyproject"),
    LockstepSite("packages/s0ma-mcp/pyproject.toml", "pyproject"),
    LockstepSite("packages/s0ma-studi0/pyproject.toml", "pyproject"),
    LockstepSite("packages/s0ma-core/src/s0ma/__init__.py", "module"),
    LockstepSite("packages/s0ma-dsl/src/s0ma_dsl/__init__.py", "module"),
    LockstepSite("packages/s0ma-mcp/src/s0ma_mcp/__init__.py", "module"),
    LockstepSite("packages/s0ma-studi0/src/s0ma_studi0/__init__.py", "module"),
)

#: Docs whose version references are claims about the CURRENT release.
#: Repo-relative POSIX paths. Add a page here when it starts naming a
#: version a reader is expected to install or run.
LIVING_DOCS: tuple[str, ...] = (
    "README.md",
    "docs/getting-started.md",
    "docs/walkthrough.md",
    "docs/hosting-getting-started.md",
    "docs/RELEASING.md",
    "AGENTS.md",
    # The contributor front door and the four package front doors. Each is the
    # first page a reader lands on for its subject and each names versions a
    # reader is expected to install or run, so each rots exactly the way the
    # root README does. Before they were scanned, docs/RELEASING.md told the
    # releaser to check them by hand — which is how a package README kept
    # naming a superseded wheel.
    "CONTRIBUTING.md",
    "editors/README.md",
    "packages/s0ma-core/README.md",
    "packages/s0ma-dsl/README.md",
    "packages/s0ma-mcp/README.md",
    "packages/s0ma-studi0/README.md",
    # beta-prep-5 B3. The rule was "no stale s0ma version numbers in living
    # documents" and the list was twelve files, so the pages a person actually
    # reads while deciding whether to trust s0ma, while something is going
    # wrong, and while taking it off again were not held to it at all. Every
    # page below is classified living-authored in the A6 ledger and describes
    # what s0ma does *now*; several carry no version at all today, which is the
    # cheapest possible moment to start holding them to the rule rather than
    # the moment one appears.
    #
    # The judgement that keeps the list honest: a page belongs here when a
    # stale version in it would mislead somebody operating s0ma today. That is
    # why `packages/*/docs/**` is still out — those are agent reference
    # material whose version strings are overwhelmingly "since 0.N.M" history,
    # and holding them here would mean an allowlist of hundreds of entries
    # saying the same thing. Also out, and for the reason the module docstring
    # gives: the changelogs, `docs/archive/`, and design notes named after the
    # release they designed.
    #
    # The four pages a user reads when things are going well, badly, or over.
    "docs/stability.md",
    "docs/trust-model.md",
    "docs/troubleshooting.md",
    "docs/uninstall.md",
    # The journeys and guides. Each is a page somebody follows with a keyboard.
    "docs/getting-started/first-project.md",
    "docs/guides/claude-integration.md",
    "docs/guides/drift-recovery.md",
    "docs/guides/first-module.md",
    "docs/guides/mcp-authoring.md",
    "docs/guides/retrofit-existing-codebase.md",
    "docs/guides/studi0-feedback.md",
    # The community files. SECURITY.md tells a reporter which versions get
    # fixes, which is a claim about the current release by definition.
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    # The two contributor pages that describe the machinery as it is today.
    "docs/documentation-subsystem.md",
    "docs/operations/docs-maintenance.md",
    # The six named commands the Claude plugin adds. They are instructions a
    # coding agent follows against the installed toolchain, so a version in one
    # of them is a statement about what is installed.
    "integrations/claude/plugin/skills/doctor/SKILL.md",
    "integrations/claude/plugin/skills/feedback/SKILL.md",
    "integrations/claude/plugin/skills/new/SKILL.md",
    "integrations/claude/plugin/skills/retrofit/SKILL.md",
    "integrations/claude/plugin/skills/setup/SKILL.md",
    "integrations/claude/plugin/skills/update/SKILL.md",
)

#: A s0ma version is ``0.N.M`` while the product is pre-1.0 (PRD INV-4 /
#: docs/RELEASING.md). The lookarounds keep the match from starting or ending
#: inside a longer dotted number (e.g. the ``0.15.1`` tail of a hypothetical
#: ``1.0.15.1``), so every hit is a whole version string. Widen the leading
#: ``0`` to ``\d+`` at 1.0.0 — and expect a burst of genuine hits from every
#: example that still shows a 0.x wheel.
#:
#: The trailing lookahead rejects a following digit, and a dot only when a
#: digit follows it. Rejecting every trailing dot (the shape this guard first
#: shipped with) opened two silent holes in the positions version strings most
#: often occupy: a version ending a sentence (``… through 0.4.0.``) and a
#: version inside a filename (``s0ma-dsl-spec-v0.17.0.md``). Both went
#: unscanned — a false negative rather than a recorded exemption, which is
#: precisely what the ALLOWLIST exists to prevent.
VERSION_RE = re.compile(r"(?<![\d.])0\.\d+\.\d+(?!\.?\d)")

#: The one class of ``0.N.M`` in these docs that is NOT a s0ma version: a
#: pinned third-party tool. Matched only when the tool name sits immediately
#: before the number (optionally through ``==``/``>=``/``v``/whitespace), so
#: an ordinary sentence mentioning `uv` earlier on the line still has its
#: s0ma version checked.
FOREIGN_TOOL_RE = re.compile(
    r"\b(?:uv|ruff|mypy|pytest|hypothesis|httpx|node|npm|pnpm|wrangler|hatchling|"
    r"setup-uv|actions/[\w-]+)\b[@\s]*[=<>~^]*\s*v?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Historical:
    """One version reference deliberately exempt from currency.

    Two reasons qualify, and ``why`` must say which. Either the reference
    dates a past release — a milestone heading, a "since 0.N.M" note, an
    example commit subject — so bumping it would make the sentence false; or
    it is a version on a different axis entirely (the DSL *language spec*,
    which versions separately from the distributions, or a third-party
    manifest quoted in an example), so the lockstep version was never the
    right value for it.

    ``on_line_containing`` pins the exemption to the sentence that justifies
    it: reword the sentence and the entry stops applying (and is reported as
    unused), so the allowlist cannot quietly outlive its reason.
    """

    path: str
    version: str
    on_line_containing: str
    why: str


#: Deliberately exempt version references. One entry per justified sentence —
#: each either says WHEN something happened (so bumping it to the current
#: version would make the sentence false) or names a version on an axis that
#: is not the lockstep release version at all.
ALLOWLIST: tuple[Historical, ...] = (
    # The embodiment capability (hardware inside the self-knowing boundary)
    # shipped in 0.15.0. The sentence dates that arrival; it is not a claim
    # about what the current release is.
    Historical(
        "README.md",
        "0.15.0",
        "Since 0.15.0 self-knowledge reaches physical hardware",
        "dates the arrival of hardware embodiment (0.15.0), not the current release",
    ),
    # The walkthrough's language notes date four DSL capabilities to the
    # release that introduced them (0.8.0): the read-for-real [tool.s0ma]
    # table, qualified cross-module edges, authored metadata, and py.typed.
    # These are "since when" facts a reader on an older wheel needs.
    Historical(
        "docs/walkthrough.md",
        "0.8.0",
        "since 0.8.0 the toolchain actually reads this table",
        "dates when [tool.s0ma].mode became load-bearing (0.8.0)",
    ),
    Historical(
        "docs/walkthrough.md",
        "0.8.0",
        "the 0.8.0 qualified `module.declaration` form",
        "dates qualified cross-module depends_on edges and authored metadata (0.8.0)",
    ),
    Historical(
        "docs/walkthrough.md",
        "0.8.0",
        "core and dsl both ship `py.typed` as of 0.8.0",
        "dates the py.typed / strict-clean emitter milestone (0.8.0)",
    ),
    Historical(
        "docs/walkthrough.md",
        "0.8.0",
        "**Language since 0.8.0, in one line:**",
        "the appendix is explicitly a since-0.8.0 language summary",
    ),
    # --- CONTRIBUTING.md ---
    Historical(
        "CONTRIBUTING.md",
        "0.13.0",
        "The build refuses NEW check errors (0.13.0 M2)",
        "dates when the build began refusing NEW check errors (0.13.0 M2)",
    ),
    # --- editors/README.md ---
    # The DSL language spec versions on its own axis (see the s0ma-dsl README
    # status note) and has its own currency gates: test_editor_grammar.py
    # harvests the highest on-disk spec, and s0ma-mcp's doc-drift test asserts
    # the packaged spec is the highest s0ma-dsl ships. The lockstep release
    # version was never the right value here.
    Historical(
        "editors/README.md",
        "0.17.0",
        "the full set harvested from spec v0.17.0",
        "the DSL language spec version the grammar was harvested from - spec axis",
    ),
    Historical(
        "editors/README.md",
        "0.17.0",
        "lexical/grammar sections",
        "the spec path the grammar tracks - spec axis, rotated when a new spec lands",
    ),
    # The sample package.json is a third-party manifest (a local VS Code
    # extension), and 0.0.1 is that extension's own version.
    Historical(
        "editors/README.md",
        "0.0.1",
        '"version": "0.0.1"',
        "the local VS Code extension manifest's own version, not a s0ma release",
    ),
    # --- packages/s0ma-core/README.md ---
    # The status note dates two filing facts: the root CHANGELOG became
    # canonical at the 0.5.0 monorepo consolidation, and core's own changelog
    # keeps the pre-monorepo history, which ends at 0.4.0.
    Historical(
        "packages/s0ma-core/README.md",
        "0.5.0",
        "canonical from 0.5.0 onward",
        "dates the monorepo consolidation (0.5.0) after which the root CHANGELOG is canonical",
    ),
    Historical(
        "packages/s0ma-core/README.md",
        "0.4.0",
        "pre-monorepo history through 0.4.0",
        "names the last pre-monorepo core release (0.4.0), where the package changelog stops",
    ),
    # --- packages/s0ma-dsl/README.md ---
    Historical(
        "packages/s0ma-dsl/README.md",
        "0.16.0",
        "last standalone DSL release: v0.16.0",
        "dates the final standalone s0ma-dsl release (v0.16.0), a pre-lockstep fact",
    ),
    # Spec axis again — the same status note states outright that the language
    # spec versions separately from the distributions.
    Historical(
        "packages/s0ma-dsl/README.md",
        "0.17.0",
        "The language spec is versioned separately",
        "the DSL language spec version (v0.17.0), a separate axis from the release version",
    ),
    Historical(
        "packages/s0ma-dsl/README.md",
        "0.17.0",
        "Normative language authority",
        "the spec filename in the documentation table - spec axis, not the release version",
    ),
    # --- docs/stability.md (beta-prep-5 B3) ---
    # A frozen contract is named after the release that froze it, so the file
    # name carries a version for the rest of its life. The page links to it
    # three times on one line (the table cell, and the deep link into its first
    # section); all three are the same name.
    Historical(
        "docs/stability.md",
        "0.14.0",
        "0.14.0-schema-and-surface-budget.md",
        "the frozen contract's own file name in a link - a name, not a claim about today",
    ),
    # --- the two worked examples (beta-prep-5 B3) ---
    # `version:` inside a module a reader is writing is the READER's project
    # version, on the reader's own axis. Starting a first module at 0.1.0 is
    # what the scaffolder does; bumping it to the s0ma release version would
    # teach the wrong thing.
    Historical(
        "docs/guides/first-module.md",
        "0.1.0",
        "version: 0.1.0",
        "the version field of the reader's own module in a worked example - their axis",
    ),
    Historical(
        "docs/getting-started/first-project.md",
        "0.1.0",
        "version: 0.1.0",
        "the version field of the reader's own module in a worked example - their axis",
    ),
    # --- docs/documentation-subsystem.md (beta-prep-5 B3) ---
    # The DSL language spec versions on its own axis, exactly as the editors
    # and s0ma-dsl README entries above record; this page cites it twice.
    Historical(
        "docs/documentation-subsystem.md",
        "0.17.0",
        "s0ma-dsl-spec-v0.17.0.md",
        "the DSL language spec's file name - spec axis, not the release version",
    ),
    Historical(
        "docs/documentation-subsystem.md",
        "0.8.0",
        "field was dropped in 0.8.0",
        "dates when a field was removed (0.8.0); bumping it would make the sentence false",
    ),
)


@dataclass(frozen=True)
class PackageMap:
    """One doc whose package map must name every distribution in the repo.

    ``heading`` locates the section and the check reads the FIRST fenced block
    under it — the tree or map itself, not the prose around it. Prose reliably
    names some packages in passing, so a whole-section search would have
    passed straight through the omission this check exists to catch.
    """

    path: str
    heading: str
    what: str


#: The two maps a human contributor and a coding agent read to learn what the
#: toolchain is made of. Adding a package to the repo and adding it to these
#: is not the same act, and only the first one used to be enforced.
PACKAGE_MAPS: tuple[PackageMap, ...] = (
    PackageMap("CONTRIBUTING.md", "## Workspace layout", "the workspace layout tree"),
    PackageMap("AGENTS.md", "## Package and dependency map", "the package and dependency map"),
)

#: Anti-vacuity floor. The workspace ships four distributions; a scan finding
#: fewer has lost its way (wrong root, renamed directory) rather than proving
#: anything. Deliberately dropping a package should be a recorded decision
#: here, not a silently weaker gate.
MIN_PACKAGES = 4

#: Anti-vacuity floor for the doc scan. The living docs carried 22 version
#: references when this floor was set (6 current, 16 allowlisted), and the
#: count moves slowly: the whole G phase of the doc-function initiative —
#: which rewrote four of these pages — moved it by five. Ten is far enough
#: below 22 that ordinary rewording never trips it, and far enough above
#: zero that a broken VERSION_RE, a truncated LIVING_DOCS, or a run rooted
#: somewhere else cannot report PASS. Genuinely retiring version-bearing
#: prose is a deliberate edit here, not a quietly weaker gate.
#:
#: beta-prep-5 B3 widened LIVING_DOCS from twelve pages to thirty-four and
#: the count rose to thirty. The floor is deliberately left where it was:
#: most of what B3 added carries no version at all, so the new headroom is
#: not headroom this floor earned, and raising a floor to sit just under a
#: number that happens to be true today is how a floor starts failing on
#: ordinary edits.
MINIMUM_REFERENCES = 10


def read_pyproject_version(root: Path, rel: str) -> str:
    """The ``project.version`` string from the pyproject at *rel*."""
    source = root / rel
    with source.open("rb") as handle:
        data = tomllib.load(handle)
    version = data["project"]["version"]
    if not isinstance(version, str):  # pragma: no cover - malformed pyproject
        raise TypeError(f"{rel}: project.version is not a string")
    return version


def read_lockstep_version(root: Path) -> str:
    """The current lockstep version, from s0ma-core's pyproject (the anchor)."""
    return read_pyproject_version(root, VERSION_SOURCE)


def read_module_version(root: Path, rel: str) -> str:
    """The module-level ``__version__`` string literal from the file at *rel*.

    Parsed with ast, never imported: these packages' ``__init__`` run
    bootstrap import machinery at load time, so the gate reads the literal
    without executing any of it.
    """
    source = root / rel
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in tree.body:  # module scope only — __version__ is a global
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value: ast.expr | None = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
            value = node.value  # AnnAssign.value is Optional (bare annotation)
        else:
            continue
        if "__version__" not in names:
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        raise TypeError(f"{rel}: __version__ is not a string literal")  # pragma: no cover
    raise ValueError(f'{rel}: no module-level __version__ = "..." found')  # pragma: no cover


def _site_version(root: Path, site: LockstepSite) -> str:
    """Read *site*'s stamped version by its kind."""
    if site.kind == "pyproject":
        return read_pyproject_version(root, site.path)
    if site.kind == "module":
        return read_module_version(root, site.path)
    raise ValueError(f"unknown lockstep site kind: {site.kind!r}")  # pragma: no cover


def check_lockstep(root: Path, current: str) -> int:
    """Assert every LOCKSTEP_SITES version equals *current*. Return the mismatch count.

    PRD INV-4: the four distributions ship one version in step. A missing
    file or an unreadable version field is itself a failure (named and
    counted), never a silent skip.
    """
    mismatches = 0
    for site in LOCKSTEP_SITES:
        if not (root / site.path).is_file():
            print(f"VIOLATION {site.path}: lockstep site missing (INV-4)")
            mismatches += 1
            continue
        try:
            found = _site_version(root, site)
        except (KeyError, ValueError, TypeError, SyntaxError, OSError) as exc:
            print(f"VIOLATION {site.path}: cannot read version — {exc} (INV-4)")
            mismatches += 1
            continue
        if found != current:
            print(
                f"VIOLATION {site.path}: version {found} does not match the lockstep "
                f"anchor {current} (from {VERSION_SOURCE}; INV-4)"
            )
            mismatches += 1

    if mismatches:
        print(
            f"\n{mismatches} lockstep version mismatch(es). All four "
            f"packages/*/pyproject.toml project.version fields and all four package "
            f"__version__ strings must equal {current} (PRD INV-4). Bump the named "
            f"file(s) into lockstep — mid-release, re-run the release script so every "
            f"site moves together."
        )
    else:
        print(f"version-currency: lockstep OK — {len(LOCKSTEP_SITES)} sites at {current}")
    return mismatches


def _is_s0ma_version(line: str, match: re.Match[str]) -> bool:
    """True unless *match* is a pinned third-party tool version on *line*."""
    return not FOREIGN_TOOL_RE.search(line[: match.start()])


def _allowed(
    allowlist: tuple[Historical, ...],
    entry_used: set[int],
    path: str,
    version: str,
    line: str,
) -> bool:
    """True when an *allowlist* entry covers this occurrence (marking it used)."""
    hit = False
    for index, entry in enumerate(allowlist):
        if entry.path == path and entry.version == version and entry.on_line_containing in line:
            entry_used.add(index)
            hit = True
    return hit


def check(root: Path = ROOT, allowlist: tuple[Historical, ...] = ALLOWLIST) -> int:
    """Report lockstep drift and stale doc references. Return the total count.

    *allowlist* is a parameter for the same reason ``scripts/check_links.py``
    takes one: the exemption mechanism is testable against a scratch tree
    only if the caller can state which exemptions apply there. The shipped
    ALLOWLIST is the default and the only value the stage ever passes.
    """
    current = read_lockstep_version(root)
    print(f"version-currency: lockstep version {current} (from {VERSION_SOURCE})")

    # INV-4 first: every pyproject/__version__ must equal the anchor. The
    # doc-currency scan below checks prose against this same version, so a
    # drifted anchor would quietly invalidate its result — catch it up front.
    lockstep_mismatches = check_lockstep(root, current)

    for entry in allowlist:
        if entry.path not in LIVING_DOCS:  # pragma: no cover - config error
            print(f"ERROR allowlist entry names a non-living doc: {entry.path}")
            return 1

    violations: list[tuple[str, int, str, str]] = []
    entry_used: set[int] = set()
    scanned = 0
    references = 0
    historical = 0

    for rel in LIVING_DOCS:
        path = root / rel
        if not path.is_file():
            print(f"ERROR living doc missing: {rel} (update LIVING_DOCS in {Path(__file__).name})")
            return 1
        scanned += 1
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in VERSION_RE.finditer(line):
                if not _is_s0ma_version(line, match):
                    continue
                references += 1
                found = match.group()
                if found == current:
                    continue
                if _allowed(allowlist, entry_used, rel, found, line):
                    historical += 1
                    continue
                violations.append((rel, lineno, found, line.strip()))

    for index, entry in enumerate(allowlist):
        if index not in entry_used:
            print(
                f"WARNING stale allowlist entry: {entry.path} {entry.version} "
                f"on a line containing {entry.on_line_containing!r} no longer matches "
                f"anything - the sentence changed; delete the entry."
            )

    for rel, lineno, found, text in violations:
        print(f"VIOLATION {rel}:{lineno}: stale version {found} (current is {current})")
        print(f"          | {text[:160]}")

    if violations:
        print(
            f"\n{len(violations)} stale version reference(s) in the living docs. "
            f"For each one, do exactly one of:\n"
            f"  * update it to {current} - it is load-bearing (a wheel filename, a\n"
            f"    v-tag example, the lockstep version line). docs/RELEASING.md step 2\n"
            f"    lists the version-bearing prose sites a release must touch;\n"
            f"  * reword it version-agnostically - preferred wherever the prose allows,\n"
            f"    because a site that names no version can never go stale;\n"
            f"  * add it to ALLOWLIST at the top of scripts/check_version_refs.py with a\n"
            f"    one-line justification, if it deliberately dates a past release or\n"
            f"    names a version on another axis (the DSL language spec, a third-party\n"
            f"    manifest quoted in an example)."
        )
        return lockstep_mismatches + len(violations)

    # Nothing above this line can fail on a scan that matched nothing: every
    # violation is a reference the matcher found. A green verdict therefore
    # has to prove the scan still reaches the prose it is meant to police.
    if references < MINIMUM_REFERENCES:
        print(
            f"\nVACUOUS SCAN: {references} version reference(s) found across "
            f"{scanned} living doc(s), fewer than the {MINIMUM_REFERENCES} this\n"
            f"repository is known to carry. Nothing was really checked - this gate\n"
            f"only ever reports what VERSION_RE matches, so a matcher that matches\n"
            f"nothing passes every time. Either the run is rooted somewhere else, or\n"
            f"VERSION_RE / FOREIGN_TOOL_RE / LIVING_DOCS in "
            f"{Path(__file__).name} stopped\n"
            f"matching the tree. Fix the scan before trusting a green result; lower\n"
            f"MINIMUM_REFERENCES only if the living docs genuinely stopped naming\n"
            f"versions."
        )
        return lockstep_mismatches + 1

    if lockstep_mismatches == 0:
        print(
            f"version-currency: PASS - {scanned} living doc(s), {references} version "
            f"reference(s): {references - historical} at {current}, {historical} "
            f"deliberately historical"
        )
    return lockstep_mismatches


def distribution_names(root: Path) -> list[str]:
    """Every workspace distribution, sorted, named by its own manifest."""
    names: list[str] = []
    for manifest in sorted((root / "packages").glob("*/pyproject.toml")):
        with manifest.open("rb") as handle:
            data = tomllib.load(handle)
        names.append(str(data["project"]["name"]))
    return sorted(names)


def _first_code_block(text: str, heading: str) -> tuple[int, str] | None:
    """The first fenced block under *heading* as (1-based line, body).

    ``None`` when the heading is absent, or when no complete fenced block
    appears before the next ``## `` heading.
    """
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index
            break
    if start is None:
        return None

    opened_at = None
    body: list[str] = []
    for index, line in enumerate(lines[start + 1 :], start + 2):
        if line.startswith("## "):
            break
        if line.startswith("```"):
            if opened_at is None:
                opened_at = index
                continue
            return opened_at, "\n".join(body)
        if opened_at is not None:
            body.append(line)
    return None


def check_package_maps(root: Path = ROOT) -> int:
    """Every distributed package must be named in both maps. Count failures."""
    names = distribution_names(root)
    if len(names) < MIN_PACKAGES:
        print(
            f"ERROR package scan found {len(names)} distribution(s) under packages/ "
            f"({', '.join(names) or 'none'}); at least {MIN_PACKAGES} expected. Either "
            f"the scan is looking in the wrong place, or a package was removed - if "
            f"removed, lower MIN_PACKAGES in {Path(__file__).name} deliberately."
        )
        return 1

    failures = 0
    for spec in PACKAGE_MAPS:
        path = root / spec.path
        if not path.is_file():
            print(f"ERROR package map missing: {spec.path} ({spec.what})")
            failures += 1
            continue
        found = _first_code_block(path.read_text(encoding="utf-8"), spec.heading)
        if found is None:
            print(
                f"ERROR {spec.path}: no fenced block under {spec.heading!r} - "
                f"{spec.what} is where every package must be named. Restore it, or "
                f"update PACKAGE_MAPS in {Path(__file__).name} if the doc moved."
            )
            failures += 1
            continue
        lineno, body = found
        for name in names:
            if name not in body:
                print(
                    f"VIOLATION {spec.path}:{lineno}: {spec.what} does not name "
                    f"{name}. The workspace ships {len(names)} distributions "
                    f"({', '.join(names)}); a package these maps omit is one that "
                    f"readers and agents never learn exists."
                )
                failures += 1

    if failures:
        return failures

    print(
        f"package-maps: PASS - {len(names)} distribution(s) named in "
        f"{len(PACKAGE_MAPS)} map(s): {', '.join(names)}"
    )
    return 0


def main() -> int:
    # Windows consoles/redirections can default to cp1252, where echoing an
    # offending line (living docs are full of em-dashes) would raise
    # UnicodeEncodeError and kill this gate's own reporting. Same guard, and
    # same reason, as scripts/check.py; a subprocess needs its own.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # non-TextIOWrapper streams (e.g. captured/wrapped)
        pass
    # Both checks always run: one report of everything wrong beats fail-fast,
    # for the same reason scripts/check.py runs every stage.
    return 0 if check() + check_package_maps() == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
