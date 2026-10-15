#!/usr/bin/env python3
"""Markdown link + anchor guard — the ``docs-links`` stage.

Nothing in this repo has ever validated a documentation link. The August
2026 docs audit (``plans/notes/docs-audit-28AUG2026.md`` §6.2 item 4) put it
plainly: no markdown lint, no relative-link validation, no pre-commit hook,
no git hook — and it listed live casualties, a dead ``#`` anchor in
``docs/RELEASING.md`` and a pointer that survived the file it pointed at.
A moved doc, a renamed heading, or a section renumbering breaks every
citation of it silently, and the reader who finds out is a beta tester
following a 404. This gate makes that class mechanical.

What it checks, for every scanned link:

* **Targets.** A repository-relative (or ``/``-rooted, which GitHub reads as
  repo-root-relative) link must resolve to a TRACKED path. ``git ls-files``
  is the universe on purpose: a file that exists only in the working tree
  is a file every other clone 404s on, so "it opens locally" is not the
  question this gate asks. A target that names a tracked DIRECTORY passes —
  GitHub renders directory links, and the repo uses them (``README.md`` ->
  ``packages/s0ma-core``).
* **Anchors.** An intra-repo ``#fragment`` must name a real heading in the
  target Markdown file, slugged by GitHub's rules (see ``slugify``). A
  fragment on a non-Markdown or directory target is not checkable and is
  skipped rather than guessed at.
* **External links are skipped entirely.** ``http(s)``, ``mailto:`` and any
  other URI scheme are never touched: this gate is offline by construction
  (INV: no network in a check stage), and link-rot on somebody else's
  server is not a defect in this tree.

What it scans, and what it deliberately does not. The scanned set is the
prose a reader actually navigates: the three root docs, ``docs/``, and each
package's ``README.md`` plus ``docs/``. Four directory names are excluded
wherever they appear:

* ``_docs/``, ``_built/``, ``_generated/`` — mirrors and emitted output.
  These are byte-gated against their sources already (the s0ma-mcp
  ``TestDocDrift`` gate, the ``selfhost-build`` equality stage), so a link
  defect in one is a defect in the source, reported once, at the source.
  Scanning both would double every finding and invite fixing the copy.
* ``historical/`` — frozen by definition. A historical document's links
  describe the tree as it was; repairing them would falsify the record.
* ``plans/`` — working notes, not shipped prose (the same carve-out the
  spelling guard and the patterns-guide gate make).

Known limitations, both deliberate, both verified absent from the tree at
the time of writing:

* Headings are ATX only (``## Title``). No scanned document uses setext
  underlining, and inferring setext headings risks inventing one, which
  would shift the ``-1``/``-2`` duplicate suffixes of every later heading
  with the same title and turn a correct link red.
* ``_underscore emphasis_`` in a heading is not unwrapped. ``_`` is a legal
  slug character that github-slugger keeps, and no heading in the tree uses
  it as an emphasis delimiter; the naive unwrap would corrupt the many
  headings that carry identifiers like ``hw_*`` or ``module_path``.

Both would surface as a loud, self-diagnosing failure (the report lists the
target's nearest real anchors), never as a silent pass.

Anti-vacuity: a scan that finds fewer than ``MINIMUM_LINKS`` links fails.
Every guard that walks a computed file set can be moved, renamed out from
under, or run from the wrong directory into a vacuous green; this one says
so instead (the audit's §6.2 item 8, made a rule rather than a wish).

Usage (no arguments, no network, deterministic):

    uv run python scripts/check_links.py
    uv run python scripts/check.py --only docs-links

An optional positional argument points the scan at another checkout root;
it exists for the test suite and changes nothing about the default run.
"""

from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent

#: Root-level documents in the scanned set.
SCANNED_ROOT_DOCS: frozenset[str] = frozenset(
    {
        "README.md",
        "CONTRIBUTING.md",
        "AGENTS.md",
    }
)

#: Directory names excluded wherever they appear in a path (see the module
#: docstring for why each one is out).
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        "plans",
        "historical",
        "_built",
        "_docs",
        "_generated",
    }
)

#: The anti-vacuity floor. The scanned set carried ~200 intra-repo links
#: when this gate was written; 50 is far enough below that ordinary doc
#: churn never trips it, and far enough above zero that a scan pointed at
#: the wrong directory — or narrowed to nothing by a bad edit to the scope
#: rules — cannot report PASS.
MINIMUM_LINKS = 50


@dataclass(frozen=True)
class Allowed:
    """One deliberately-unresolvable link, exempt from the gate.

    ``path`` is the repo-relative file containing the link and ``link`` is
    its exact target text, so an entry covers one specific link and stops
    applying the moment that link is edited (it is then reported as unused,
    and cannot quietly outlive its reason).

    Reach for this last. A link that does not resolve is nearly always a
    defect in the link; the honest fixes are to repoint it, to drop it, or
    to track the file it names.
    """

    path: str
    link: str
    why: str


#: Deliberately-unresolvable links. Empty on purpose: every finding this
#: gate has produced so far was a real broken link, and each was routed to
#: a fix rather than an exemption. Add an entry only with a justification
#: that says why the link CANNOT resolve and should still be written.
ALLOWLIST: tuple[Allowed, ...] = (
    Allowed(
        "docs/contracts/0.14.0-schema-and-surface-budget.md",
        "../../plans/complete/s0ma-release-pipeline-feedback-1.md",
        "a frozen contract's revision record cites the plan that ratified "
        "it; the plan is internal and the contract must not be edited",
    ),
    Allowed(
        "docs/documentation-subsystem.md",
        "archive/pre-monorepo/s0ma-dsl/plans/TODO.md",
        "the subsystem guide cites the pre-monorepo TODO for provenance; "
        "that archived plan tree is not published",
    ),
    Allowed(
        "packages/s0ma-core/docs/references/documentation_subsystem.md",
        "../../../../docs/archive/pre-monorepo/s0ma-core/plans/documentation_subsystem_implementation_plan.md",
        "a frozen reference page cites the plan that produced it",
    ),
    Allowed(
        "packages/s0ma-dsl/docs/adr/ADR-007-single-build-layout.md",
        "../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/s0ma-dsl-feedback-5.5.md",
        "an accepted ADR's provenance line; the ADR is the record and is "
        "not rewritten to tidy a pointer",
    ),
    Allowed(
        "packages/s0ma-dsl/docs/adr/ADR-007-single-build-layout.md",
        "../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/s0ma-dsl-feedback-5.md",
        "same ADR, its second consumer-feedback document, withheld with "
        "the archive",
    ),
    Allowed(
        "packages/s0ma-dsl/docs/adr/ADR-007-single-build-layout.md",
        "../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/s0ma-dsl-feedback-6.md",
        "same ADR, its third consumer-feedback document, withheld with "
        "the archive",
    ),
    Allowed(
        "packages/s0ma-dsl/docs/adr/ADR-008-test-visibility.md",
        "../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/s0ma-dsl-feedback-5.5.md",
        "an accepted ADR's provenance line, withheld with the archive",
    ),
    Allowed(
        "packages/s0ma-dsl/docs/adr/ADR-008-test-visibility.md",
        "../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/5-6_deviations.md",
        "same ADR, the deviations record it was decided against",
    ),
    Allowed(
        "packages/s0ma-dsl/docs/adr/ADR-009-canonical-body-storage.md",
        "../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/5-6_follow-up_plan.md",
        "an accepted ADR's provenance line, withheld with the archive",
    ),
    Allowed(
        "packages/s0ma-dsl/docs/adr/ADR-009-canonical-body-storage.md",
        "../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/feedback_5-6_smoke_results.md",
        "same ADR, the smoke record it cites as evidence",
    ),
    Allowed(
        "packages/s0ma-dsl/docs/adr/ADR-010-derived-doc-targets.md",
        "../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/5-6_cleanup_plan.md",
        "an accepted ADR's provenance line, withheld with the archive",
    ),
    Allowed(
        "packages/s0ma-dsl/docs/references/documentation_subsystem.md",
        "../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/TODO.md",
        "a frozen reference page's pointer into the archived plan tree",
    ),
    Allowed(
        "packages/s0ma-dsl/docs/references/documentation_subsystem.md",
        "../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/documentation_subsystem_implementation_plan.md",
        "same page, the plan that produced the subsystem",
    ),
)


# ---------------------------------------------------------------------------
# Markdown scanning
# ---------------------------------------------------------------------------

#: A fenced code block delimiter: up to three leading spaces, then three or
#: more backticks or tildes, then an optional info string.
_FENCE_RE = re.compile(r"^ {0,3}(?P<ticks>`{3,}|~{3,})(?P<info>.*)$")

#: An ATX heading. The optional trailing ``#`` run is a closing sequence and
#: is not part of the heading text.
_HEADING_RE = re.compile(r"^ {0,3}(?P<hashes>#{1,6})\s+(?P<title>.*?)\s*(?<!\\)#*\s*$")

#: An inline code span, matched with a backreference so ``` ``a`b`` ``` and
#: ``` `a` `` are both handled. Masked out before links are extracted: a
#: link inside a code span is displayed literally, not linked.
_CODE_SPAN_RE = re.compile(r"(?P<ticks>`+)(?P<body>.*?)(?P=ticks)")

#: An inline link or image. The text may contain one level of nested
#: brackets (``[`[tool.s0ma]`](#anchor)``); the target may not contain
#: whitespace or parentheses, and an optional quoted title follows it.
_LINK_RE = re.compile(
    r"!?\[(?P<text>(?:[^\[\]]|\[[^\[\]]*\])*)\]"
    r"\((?P<target>[^()\s]*)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'))?\)"
)

#: A URI scheme (``https:``, ``mailto:``, ``s0ma:``) or a protocol-relative
#: URL. Everything matching is external and skipped without inspection.
_EXTERNAL_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)")

#: A markdown link in heading text — only the link TEXT is rendered, so only
#: the text may reach the slug. (No heading in the tree carries one today;
#: this keeps a future one from slugging its URL.)
_HEADING_LINK_RE = re.compile(r"!?\[(?P<text>[^\[\]]*)\]\([^()\s]*(?:\s+[^()]*)?\)")

#: An HTML tag in heading text: the rendered heading keeps the tag's text
#: content, not its markup.
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")

#: The characters github-slugger strips before spaces become hyphens: the
#: ASCII control and punctuation ranges, plus the Unicode punctuation blocks
#: (which is why an em dash vanishes and leaves the two spaces around it —
#: hence the doubled hyphen in real anchors like
#: ``#6-owner-runbook--provisioning-a-tester``). ``-`` and ``_`` are
#: deliberately NOT in the class: both are legal slug characters.
_PUNCTUATION_RE = re.compile(
    "["
    "\x00-\x1f"  # control characters
    "!-,"  # ! " # $ % & ' ( ) * + ,
    "./"  # . /
    ":-@"  # : ; < = > ? @
    "\\[-\\^"  # [ \ ] ^
    "`"
    "{-~"  # { | } ~
    " ¡§«¶·»¿"
    " -⁯"  # general punctuation (en/em dash, curly quotes, ellipsis)
    "⸀-⹿"  # supplemental punctuation
    "　-〿"  # CJK symbols and punctuation
    "]"
)


def slugify(text: str) -> str:
    """The GitHub heading anchor for *text*, by github-slugger's rules.

    Rendered heading text first (markup is not part of the anchor), then
    lowercase, then drop the punctuation class, then spaces become hyphens.
    Duplicate handling is NOT here — it is per-document state and lives in
    ``document_anchors``.
    """
    rendered = _HTML_TAG_RE.sub("", _HEADING_LINK_RE.sub(r"\g<text>", text))
    return _PUNCTUATION_RE.sub("", rendered.strip().lower()).replace(" ", "-")


def _outside_fences(lines: list[str]) -> list[tuple[int, str]]:
    """``(lineno, line)`` for every line NOT inside a fenced code block.

    Fences matter twice over: a link in a sample is not a link, and — the
    sharper one — a shell comment in a ``bash`` block (``# rebuild the
    wheels``) is not a heading. Reading one as a heading would invent an
    anchor and shift every later duplicate suffix.
    """
    live: list[tuple[int, str]] = []
    fence: str | None = None
    for lineno, line in enumerate(lines, 1):
        match = _FENCE_RE.match(line)
        if match:
            ticks = match.group("ticks")
            if fence is None:
                # An opener may carry an info string; a backtick fence's
                # info string may not itself contain a backtick.
                if not (ticks[0] == "`" and "`" in match.group("info")):
                    fence = ticks
                    continue
            elif (
                ticks[0] == fence[0]
                and len(ticks) >= len(fence)
                and not match.group("info").strip()
            ):
                fence = None
                continue
        if fence is None:
            live.append((lineno, line))
    return live


def document_anchors(text: str) -> list[str]:
    """Every heading anchor in *text*, in document order.

    Duplicate titles take github-slugger's disambiguation suffixes: the
    first ``## Notes`` is ``notes``, the second ``notes-1``, the third
    ``notes-2``.
    """
    anchors: list[str] = []
    seen: dict[str, int] = {}
    for _lineno, line in _outside_fences(text.splitlines()):
        match = _HEADING_RE.match(line)
        if not match:
            continue
        base = slugify(match.group("title"))
        if not base:
            continue
        if base in seen:
            seen[base] += 1
            anchors.append(f"{base}-{seen[base]}")
        else:
            seen[base] = 0
            anchors.append(base)
    return anchors


@dataclass(frozen=True)
class Link:
    """One inline link found in a scanned document."""

    path: str
    lineno: int
    text: str
    target: str


def document_links(path: str, text: str) -> list[Link]:
    """Every inline link in *text* that a reader can actually click."""
    found: list[Link] = []
    for lineno, line in _outside_fences(text.splitlines()):
        masked = _CODE_SPAN_RE.sub(lambda match: " " * len(match.group()), line)
        for match in _LINK_RE.finditer(masked):
            found.append(Link(path, lineno, match.group("text"), match.group("target")))
    return found


# ---------------------------------------------------------------------------
# The tracked universe and the scanned set
# ---------------------------------------------------------------------------


def tracked_files(root: Path) -> frozenset[str]:
    """Every path git tracks under *root*, as repo-relative POSIX strings.

    ``-z`` keeps git from quoting non-ASCII paths, so the bytes come back
    exactly as recorded and decode as UTF-8.
    """
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return frozenset(part for part in result.stdout.decode("utf-8").split("\0") if part)


def tracked_directories(tracked: frozenset[str]) -> frozenset[str]:
    """Every directory implied by *tracked* — the universe for dir links."""
    directories: set[str] = set()
    for rel in tracked:
        parts = rel.split("/")
        for index in range(1, len(parts)):
            directories.add("/".join(parts[:index]))
    return frozenset(directories)


def in_scope(rel: str) -> bool:
    """True when *rel* is a document this gate scans (module docstring)."""
    if not rel.endswith(".md"):
        return False
    parts = rel.split("/")
    if EXCLUDED_DIR_NAMES.intersection(parts[:-1]):
        return False
    if rel in SCANNED_ROOT_DOCS:
        return True
    if parts[0] == "docs":
        return True
    if parts[0] == "packages" and len(parts) >= 3:
        return parts[2] == "README.md" or (len(parts) >= 4 and parts[2] == "docs")
    return False


def scanned_set(tracked: frozenset[str]) -> list[str]:
    """The scanned documents, sorted for a deterministic report."""
    return sorted(rel for rel in tracked if in_scope(rel))


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Miss:
    """One link that does not resolve, with the fix it wants."""

    path: str
    lineno: int
    target: str
    reason: str
    remedy: str

    @property
    def sort_key(self) -> tuple[str, int, str]:
        return (self.path, self.lineno, self.target)


def _resolve(source: str, target_path: str) -> str | None:
    """*target_path* as a repo-relative POSIX path, or None if it escapes.

    A leading ``/`` is repo-root-relative — that is how GitHub reads it, and
    reading it as a filesystem path is exactly the bug that lets an absolute
    developer-machine path (``/Users/...``) look plausible in prose.
    """
    if target_path.startswith("/"):
        candidate = PurePosixPath(target_path.lstrip("/"))
    else:
        candidate = PurePosixPath(source).parent / target_path
    parts: list[str] = []
    for part in candidate.parts:
        if part in {".", ""}:
            continue
        if part == "..":
            if not parts:
                return None  # escapes the repository root
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _anchor_miss(
    link: Link,
    target_rel: str,
    fragment: str,
    read: dict[str, str],
    root: Path,
    tracked: frozenset[str],
) -> Miss | None:
    """Check *fragment* against the headings of *target_rel*, if checkable."""
    if not target_rel.endswith(".md") or target_rel not in tracked:
        # A directory link, an image, a source file: GitHub's fragment
        # semantics there are not heading slugs, so there is nothing this
        # gate can honestly assert.
        return None
    if target_rel not in read:
        read[target_rel] = (root / target_rel).read_text(encoding="utf-8")
    anchors = document_anchors(read[target_rel])
    if fragment in anchors:
        return None
    near = difflib.get_close_matches(fragment, anchors, n=3, cutoff=0.6)
    hint = ", ".join(f"#{anchor}" for anchor in near) if near else "(no similar heading)"
    return Miss(
        link.path,
        link.lineno,
        link.target,
        f"anchor #{fragment} names no heading in {target_rel}",
        f"nearest headings there: {hint}",
    )


def _link_miss(
    link: Link,
    root: Path,
    tracked: frozenset[str],
    directories: frozenset[str],
    read: dict[str, str],
) -> Miss | None:
    """The one thing wrong with *link*, or None when it resolves."""
    target = link.target.strip()
    if not target or _EXTERNAL_RE.match(target):
        return None

    path_part, _, fragment = target.partition("#")
    path_part = unquote(path_part.split("?")[0])
    fragment = unquote(fragment)

    if not path_part:
        target_rel = link.path  # a same-document ``#anchor``
    else:
        resolved = _resolve(link.path, path_part)
        if resolved is None:
            return Miss(
                link.path,
                link.lineno,
                link.target,
                "target escapes the repository root",
                "repoint it at a tracked path inside this repository",
            )
        target_rel = resolved
        if target_rel not in tracked:
            if target_rel in directories:
                if not fragment:
                    return None
                return _anchor_miss(link, target_rel, fragment, read, root, tracked)
            return Miss(
                link.path,
                link.lineno,
                link.target,
                f"target {target_rel} is not tracked in this repository",
                "repoint it at the file's current path, drop the link, or "
                "`git add` the file it names",
            )

    if not fragment:
        return None
    return _anchor_miss(link, target_rel, fragment, read, root, tracked)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def check(root: Path = ROOT, allowlist: tuple[Allowed, ...] = ALLOWLIST) -> int:
    """Report unresolvable links and anchors. Return the violation count."""
    try:
        tracked = tracked_files(root)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"ERROR cannot list tracked files under {root.name}/: {error}")
        print("      this gate reads `git ls-files` as its universe; run it in a checkout.")
        return 1

    documents = scanned_set(tracked)
    directories = tracked_directories(tracked)
    read: dict[str, str] = {}

    misses: list[Miss] = []
    used: set[int] = set()
    checked = 0
    external = 0
    exempt = 0

    for rel in documents:
        read[rel] = (root / rel).read_text(encoding="utf-8")
        for link in document_links(rel, read[rel]):
            target = link.target.strip()
            if not target or _EXTERNAL_RE.match(target):
                external += 1
                continue
            checked += 1
            miss = _link_miss(link, root, tracked, directories, read)
            if miss is None:
                continue
            covered = False
            for index, entry in enumerate(allowlist):
                if entry.path == link.path and entry.link == link.target:
                    used.add(index)
                    covered = True
            if covered:
                exempt += 1
                continue
            misses.append(miss)

    for index, entry in enumerate(allowlist):
        if index not in used:
            print(
                f"WARNING stale allowlist entry: {entry.path} -> {entry.link!r} "
                f"matches no unresolvable link any more - the link changed or was "
                f"fixed; delete the entry."
            )

    for miss in sorted(misses, key=lambda item: item.sort_key):
        print(f"VIOLATION {miss.path}:{miss.lineno}: {miss.reason}")
        print(f"          | link: {miss.target}")
        print(f"          -> {miss.remedy}")

    if misses:
        print(
            f"\n{len(misses)} unresolvable link(s) across {len(documents)} document(s). "
            f"For each one, do exactly one of:\n"
            f"  * repoint it - the file moved or the heading was renamed (this is\n"
            f"    almost always the answer; the report names the nearest real\n"
            f"    headings for an anchor miss);\n"
            f"  * delete the link - the thing it named is gone and nothing replaced it;\n"
            f"  * add it to ALLOWLIST at the top of scripts/check_links.py with a\n"
            f"    one-line justification, if it deliberately cannot resolve.\n"
            f"Headings are read as ATX (`## Title`) only - a setext-underlined\n"
            f"heading has no anchor here even though GitHub gives it one."
        )
        return len(misses)

    if checked < MINIMUM_LINKS:
        print(
            f"\nVACUOUS SCAN: {checked} intra-repo link(s) found, fewer than the "
            f"{MINIMUM_LINKS} this repository is known to carry.\n"
            f"Nothing was really checked. Either the scan is pointed at the wrong\n"
            f"root, or the scope rules in scripts/check_links.py (SCANNED_ROOT_DOCS /\n"
            f"in_scope / EXCLUDED_DIR_NAMES) stopped matching the tree. Fix the scan\n"
            f"before trusting a green result; lower MINIMUM_LINKS only if the docs\n"
            f"genuinely shrank."
        )
        return 1

    print(
        f"docs-links: PASS - {len(documents)} document(s), {checked} intra-repo "
        f"link(s) resolved ({exempt} allowlisted), {external} external link(s) "
        f"skipped without contacting anything"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows consoles/redirections can default to cp1252, where echoing a
    # link text (the docs are full of em-dashes) would raise
    # UnicodeEncodeError and kill this gate's own reporting. Same guard, and
    # same reason, as scripts/check.py; a subprocess needs its own.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # non-TextIOWrapper streams (e.g. captured/wrapped)
        pass

    parser = argparse.ArgumentParser(description="s0ma docs link + anchor guard")
    parser.add_argument(
        "root",
        nargs="?",
        default=None,
        help="checkout root to scan (default: this script's repository)",
    )
    options = parser.parse_args(argv)
    root = ROOT if options.root is None else Path(options.root).resolve()
    return 0 if check(root) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
