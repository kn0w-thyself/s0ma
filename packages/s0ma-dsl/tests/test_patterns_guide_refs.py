"""Patterns-guide section-reference drift gate (0.13.0 candidate).

The patterns guide (``docs/references/dsl_patterns_guide.md``) is numbered
prose — ``## 24. Project layout (feature-first)``, ``### 24.5 Archetype
starters`` — and live surfaces all over the repo cite those numbers: the
quick reference's standards row (``**§24 Project layout (feature-first)**``),
the agent system prompt (``s0ma://guide/patterns §24–§28``), the ``new
project`` AGENTS.md scaffold (``**§24** project layout, …``), ``score.py``'s
boundary-doctrine comments (§27.2), and the guide's own cross-reference
sections. Inserting or removing a numbered section renumbers everything
after it and silently invalidates every one of those citations: the
batch-01c wave's new §24 (commit 0e44a18) shifted the standards block
§24–29 → §25–30, and the stale citations were caught only by a one-off
manual grep during orchestrator review. This gate makes that catch
mechanical, in the spirit of ``test_doc_consistency.py`` and the s0ma-mcp
``TestDocDrift`` byte gate.

What counts as a patterns-guide reference. The repo uses ``§`` for several
documents (the DSL spec, the PRD, ADRs, the handbook, plan files), so the
scan favours few false positives (PRD P-3 — a gate has no advisory tier):

* anywhere in the scanned surface: a ``§N`` whose same-line lead-in names
  the guide ("Patterns Guide §24.5", "patterns guide §24/§28",
  "s0ma://guide/patterns §24–§28");
* in ``BARE_GUIDE_NAMESPACE_FILES`` — surfaces whose bare ``§N``
  conventionally means the patterns guide (the guide itself, the quick
  reference, the agent system prompt, their ``_docs`` mirrors, the two
  guide-citing CLI modules, and the MCP ``s0ma_src`` sources): every
  ``§N`` token.

Either way a token is *skipped* when the immediately preceding word names
another document ("spec §4.13", "walkthrough §5"), when the trailing text
does ("§4.13 of the spec"), or when the number resolves in a shipped DSL
spec's heading namespace but not in the guide's (bare spec citations like
"per §4.13" — the guide has no §4.13). A number found in NEITHER namespace
fails. A reference that carries a bold or quoted title on the same line
(``**§24 Project layout (feature-first)**``, ``§24 ("Project layout")``)
must also match the title actually at that number — em-dash trailers are
deliberately NOT title-checked (they are usually free-form descriptions,
e.g. the guide's own "§13.2 — generic inversion remediation").

Historical records are exempt: every ``CHANGELOG.md`` (root Keep-a-Changelog,
frozen pre-monorepo package changelogs, the ``_docs`` mirror), ``plans/``
trees, ``docs/historical/``, and generated ``_built/`` output.

If this gate is red after editing the guide: fix every citation it lists
(they are live surfaces — MCP-served docs, scaffold text, CLI docstrings),
refresh the byte-identical ``_docs`` mirrors (the s0ma-mcp drift gate), and
rebuild + commit the MCP self-host if a ``.s0ma`` source changed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Roots. The package root works in any checkout of s0ma-dsl; the monorepo
# root (two levels further up) is required only by the cross-repo scan,
# which skips itself outside a workspace checkout (same stance as the
# s0ma-mcp drift gate's repo-checkout guard).
# ---------------------------------------------------------------------------

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
MONOREPO_ROOT = PACKAGE_ROOT.parent.parent
GUIDE_PATH = PACKAGE_ROOT / "docs" / "references" / "dsl_patterns_guide.md"

#: Surfaces whose bare ``§N`` tokens mean the patterns guide (see module
#: docstring). Monorepo-root-relative POSIX paths; extend this set when a
#: new surface adopts the bare-citation convention.
BARE_GUIDE_NAMESPACE_FILES = {
    "packages/s0ma-dsl/docs/references/dsl_patterns_guide.md",
    "packages/s0ma-dsl/docs/agent_system_prompt.md",
    "packages/s0ma-mcp/src/s0ma_mcp/_docs/dsl_patterns_guide.md",
    "packages/s0ma-mcp/src/s0ma_mcp/_docs/agent_system_prompt.md",
    "packages/s0ma-dsl/src/s0ma_dsl/cli/new_project.py",
    "packages/s0ma-dsl/src/s0ma_dsl/cli/score.py",
}
BARE_GUIDE_NAMESPACE_PREFIXES = ("packages/s0ma-mcp/s0ma_src/",)

#: Path-part / filename carve-outs: historical records and generated output.
EXCLUDED_PART_NAMES = {
    "plans",
    "historical",
    "_built",
    ".s0ma.cache",
    "__s0ma_cache__",
    "__pycache__",
}
EXCLUDED_FILE_NAMES = {"CHANGELOG.md"}

# ---------------------------------------------------------------------------
# Parsing: numbered headings and § reference tokens
# ---------------------------------------------------------------------------

#: ``## 24. Title`` / ``### 24.5 Title`` / ``#### 2.1.1 Title`` (the guide
#: writes a trailing dot at the top level only; both forms are accepted).
_HEADING_RE = re.compile(r"^#{2,4}\s+(\d+(?:\.\d+)*)\.?\s+(\S.*?)\s*$")
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")

_REF_RE = re.compile(r"§(\d+(?:\.\d+)*)")
#: Unprefixed second endpoint of a range: ``§24–27`` / ``§18-22``. A
#: §-prefixed endpoint (``§24–§28``) is found by ``_REF_RE`` on its own.
_RANGE_TAIL_RE = re.compile(r"\s?[–—-]\s?(\d+(?:\.\d+)*)")
#: The guide named in the same-line lead-in (searched in a bounded window
#: before the token): prose ("Patterns Guide", "patterns-guide", the
#: ``dsl_patterns_guide`` filename) or the served URI (``guide/patterns``).
_GUIDE_PHRASE_RE = re.compile(r"patterns[ _-]guide|guide/patterns", re.IGNORECASE)
_GUIDE_PHRASE_WINDOW = 60
#: Immediately preceding word that hands the token to another document's
#: namespace ("spec §4.13", "PRD §7.5", "ADR-011 §3", "walkthrough §5").
_OTHER_DOC_WORD_RE = re.compile(
    r"(?:spec|prd|adr(?:-\d+)?|handbook|walkthrough|overview|plan|part|changelog|rfc|readme)"
    r"['’]?s?[\s:,;(]*$",
    re.IGNORECASE,
)
#: Trailing hand-off to another document: ``§4.13 of the spec``.
_OF_THE_DOC_RE = re.compile(r"\s+of\s+the\s+(?:spec|prd|handbook)\b", re.IGNORECASE)
#: Title-bearing forms. Bold-inline must start two characters before the
#: token (``**§24 Project layout**``); quoted follows the token, optionally
#: parenthesised (``§24 ("Project layout")``).
_BOLD_TITLE_RE = re.compile(r"\*\*§(\d+(?:\.\d+)*)\s+([^*]+?)\*\*")
_QUOTED_TITLE_RE = re.compile(r"^\s*\(?[\"“]([^\"”]{2,90})[\"”]\)?")


def numbered_heading_pairs(text: str) -> list[tuple[str, str]]:
    """Every fence-exempt numbered heading in *text* as (number, title)."""
    pairs: list[tuple[str, str]] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if match:
            pairs.append((match.group(1), match.group(2)))
    return pairs


@dataclass(frozen=True)
class CandidateRef:
    """One §-token attributed to the patterns guide, before resolution."""

    lineno: int
    number: str
    title_claim: str | None
    context: str


def _context(line: str, start: int, end: int) -> str:
    snippet = line[max(0, start - 45) : min(len(line), end + 45)].strip()
    return snippet[:100]


def extract_candidate_refs(text: str, *, bare_namespace: bool) -> list[CandidateRef]:
    """Collect the §-tokens in *text* that are patterns-guide citations.

    Pure classification — existence against the guide/spec namespaces is
    ``classify_refs``'s job. ``bare_namespace`` marks files from
    ``BARE_GUIDE_NAMESPACE_FILES`` where every bare token qualifies;
    elsewhere only tokens with the guide named in the lead-in window do.
    """
    refs: list[CandidateRef] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if "§" not in line:
            continue
        for token in _REF_RE.finditer(line):
            before = line[: token.start()]
            if _OTHER_DOC_WORD_RE.search(before[-40:]):
                continue  # "spec §4.13", "walkthrough §5" — another namespace
            named_in_lead_in = bool(
                _GUIDE_PHRASE_RE.search(before[-_GUIDE_PHRASE_WINDOW:])
            )
            if not (named_in_lead_in or bare_namespace):
                continue
            tail = _RANGE_TAIL_RE.match(line, token.end())
            after = line[tail.end() if tail else token.end() :]
            if _OF_THE_DOC_RE.match(after):
                continue  # "§4.13 of the spec"
            title_claim: str | None = None
            bold = _BOLD_TITLE_RE.match(line, token.start() - 2)
            if bold is not None and bold.group(1) == token.group(1):
                title_claim = bold.group(2)
            else:
                quoted = _QUOTED_TITLE_RE.match(after)
                if quoted is not None:
                    title_claim = quoted.group(1)
            context = _context(line, token.start(), token.end())
            refs.append(CandidateRef(lineno, token.group(1), title_claim, context))
            if tail is not None:
                refs.append(CandidateRef(lineno, tail.group(1), None, context))
    return refs


def _norm_title_tokens(text: str) -> list[str]:
    """Case/punctuation-insensitive word list for title comparison."""
    return re.findall(r"[a-z0-9]+", text.replace("&", " and ").lower())


def classify_refs(
    refs: list[CandidateRef],
    guide: dict[str, str],
    spec_numbers: set[str],
) -> tuple[list[CandidateRef], list[tuple[int, str]]]:
    """Resolve candidates against the guide → (checked refs, violations).

    A candidate whose number is missing from the guide but present in a
    shipped spec's heading namespace is presumed a bare spec citation and
    dropped (neither checked nor failed) — see the module docstring.
    Violations are (lineno, message) pairs; the caller prefixes the path.
    """
    checked: list[CandidateRef] = []
    violations: list[tuple[int, str]] = []
    for ref in refs:
        actual = guide.get(ref.number)
        if actual is None:
            if ref.number in spec_numbers:
                continue
            checked.append(ref)
            violations.append(
                (
                    ref.lineno,
                    f"§{ref.number} — the guide has no such section"
                    f" (cited as: {ref.context!r})",
                )
            )
            continue
        checked.append(ref)
        if ref.title_claim is None:
            continue
        claim_tokens = _norm_title_tokens(ref.title_claim)
        actual_tokens = _norm_title_tokens(actual)
        if not claim_tokens or claim_tokens != actual_tokens[: len(claim_tokens)]:
            violations.append(
                (
                    ref.lineno,
                    f"§{ref.number} — cited with title {ref.title_claim!r}"
                    f" but the guide's §{ref.number} is {actual!r}",
                )
            )
    return checked, violations


# ---------------------------------------------------------------------------
# The real corpora: guide sections, spec namespace, scan surface
# ---------------------------------------------------------------------------


@cache
def guide_sections() -> dict[str, str]:
    pairs = numbered_heading_pairs(GUIDE_PATH.read_text(encoding="utf-8"))
    return dict(pairs)


@cache
def spec_section_numbers() -> set[str]:
    """Union of numbered-heading numbers across every shipped DSL spec."""
    numbers: set[str] = set()
    for spec in sorted((PACKAGE_ROOT / "docs").glob("s0ma-dsl-spec-v*.md")):
        for number, _title in numbered_heading_pairs(spec.read_text(encoding="utf-8")):
            numbers.add(number)
    return numbers


def _excluded(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    return bool(EXCLUDED_PART_NAMES.intersection(rel.parts)) or (
        path.name in EXCLUDED_FILE_NAMES
    )


@cache
def scan_files() -> tuple[Path, ...]:
    """Every live text surface scanned by the gate, monorepo-wide."""
    root = MONOREPO_ROOT
    bases: list[tuple[Path, str]] = [(root / "docs", "*.md"), (root / "references", "*.md")]
    singles: list[Path] = [root / "README.md", root / "CONTRIBUTING.md"]
    for pkg in sorted((root / "packages").iterdir()):
        if not pkg.is_dir():
            continue
        singles.append(pkg / "README.md")
        bases.append((pkg / "docs", "*.md"))
        bases.append((pkg / "src", "*.py"))
        bases.append((pkg / "src", "*.md"))  # the s0ma-mcp _docs mirrors
        for pattern in ("*.s0ma", "*.md", "*.txt"):
            bases.append((pkg / "s0ma_src", pattern))
    files: set[Path] = {single for single in singles if single.is_file()}
    for base, pattern in bases:
        if base.is_dir():
            files.update(p for p in base.rglob(pattern) if p.is_file())
    return tuple(sorted(p for p in files if not _excluded(p, root)))


def _require_monorepo() -> None:
    if not (MONOREPO_ROOT / "packages").is_dir():  # pragma: no cover
        pytest.skip("monorepo workspace not available (standalone package checkout)")


def _scan_repo() -> tuple[list[CandidateRef], list[str]]:
    """Run the gate over the workspace → (checked refs, violation lines)."""
    guide = guide_sections()
    spec_numbers = spec_section_numbers()
    all_checked: list[CandidateRef] = []
    failures: list[str] = []
    for path in scan_files():
        rel = path.relative_to(MONOREPO_ROOT).as_posix()
        bare = rel in BARE_GUIDE_NAMESPACE_FILES or rel.startswith(
            BARE_GUIDE_NAMESPACE_PREFIXES
        )
        text = path.read_text(encoding="utf-8", errors="replace")
        refs = extract_candidate_refs(text, bare_namespace=bare)
        checked, violations = classify_refs(refs, guide, spec_numbers)
        all_checked.extend(checked)
        failures.extend(f"{rel}:{lineno}: {message}" for lineno, message in violations)
    return all_checked, failures


# ---------------------------------------------------------------------------
# Guide-parse sanity
# ---------------------------------------------------------------------------


def test_guide_headings_parse_sanely() -> None:
    """The heading parser sees the real guide, and its numbers are unique.

    Floors, not pinned counts (NFR-2): the guide currently has 29 top-level
    sections and ~100 subsections; a parser regression that silently
    returned nothing would otherwise make the reference gate vacuous.
    """
    pairs = numbered_heading_pairs(GUIDE_PATH.read_text(encoding="utf-8"))
    numbers = [number for number, _title in pairs]
    duplicates = sorted({number for number in numbers if numbers.count(number) > 1})
    assert not duplicates, (
        f"duplicate section number(s) in the patterns guide: {duplicates} — "
        "two headings claim the same §; renumber before trusting any citation"
    )
    top_level = [number for number in numbers if "." not in number]
    assert len(top_level) >= 25, f"only {len(top_level)} top-level sections parsed"
    assert len(pairs) >= 60, f"only {len(pairs)} numbered headings parsed"


def test_spec_namespace_parses() -> None:
    """The bare-spec-citation fallback has a real namespace to consult."""
    numbers = spec_section_numbers()
    assert len(numbers) >= 60, f"only {len(numbers)} spec headings parsed"
    assert "4.13" in numbers  # the quick reference's favourite bare spec citation


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_live_guide_citations_resolve() -> None:
    """Every live patterns-guide citation names a real section, with a
    matching title where one rides the citation."""
    _require_monorepo()
    _checked, failures = _scan_repo()
    if failures:
        listing = "\n  ".join(failures)
        pytest.fail(
            f"{len(failures)} stale patterns-guide citation(s):\n  {listing}\n"
            "Renumbered the guide? Every citation above is a live surface "
            "(MCP-served doc, scaffold text, CLI docstring) — update them, "
            "refresh the byte-identical _docs mirrors under "
            "packages/s0ma-mcp/src/s0ma_mcp/_docs/, and rebuild + commit the "
            "MCP self-host if a .s0ma source changed. Historical records "
            "(CHANGELOGs, plans/, docs/historical/, _built/) are exempt — "
            "see this file's docstring."
        )


def test_gate_sees_a_healthy_citation_corpus() -> None:
    """The scan actually covers the surfaces that drifted in batch-01c.

    If a rename or glob rot silently dropped them, the gate would pass
    vacuously — fail loudly instead (the drift-gate idiom).
    """
    _require_monorepo()
    checked, _failures = _scan_repo()
    assert len(checked) >= 15, (
        f"only {len(checked)} patterns-guide citations found repo-wide — "
        "the scan surface has rotted (see scan_files/BARE_GUIDE_NAMESPACE_FILES)"
    )
    per_file: dict[str, int] = {}
    for path in scan_files():
        rel = path.relative_to(MONOREPO_ROOT).as_posix()
        bare = rel in BARE_GUIDE_NAMESPACE_FILES or rel.startswith(
            BARE_GUIDE_NAMESPACE_PREFIXES
        )
        text = path.read_text(encoding="utf-8", errors="replace")
        refs = extract_candidate_refs(text, bare_namespace=bare)
        checked_here, _ = classify_refs(refs, guide_sections(), spec_section_numbers())
        per_file[rel] = len(checked_here)
    for surface in (
        "packages/s0ma-dsl/docs/agent_system_prompt.md",
        "packages/s0ma-dsl/src/s0ma_dsl/cli/new_project.py",
        "packages/s0ma-dsl/docs/references/dsl_patterns_guide.md",
    ):
        assert per_file.get(surface, 0) >= 1, (
            f"no patterns-guide citations seen in {surface} — a batch-01c "
            "drift surface fell out of the scan"
        )


# ---------------------------------------------------------------------------
# Classifier heuristics, pinned on synthetic lines
# ---------------------------------------------------------------------------


def test_classifier_heuristics() -> None:
    """The scope rules that keep the gate quiet on other §-namespaces."""
    guide = {
        "24": "Project layout (feature-first)",
        "24.5": "Archetype starters (`--template`)",
        "27": "The boundary doctrine",
        "28": "The app-map pattern",
    }
    spec = {"4", "4.13"}

    def run(line: str, *, bare: bool) -> tuple[int, list[str]]:
        refs = extract_candidate_refs(line, bare_namespace=bare)
        checked, violations = classify_refs(refs, guide, spec)
        return len(checked), [message for _lineno, message in violations]

    # Another document named just before the token — never considered.
    assert run("full contract in spec §4.13 as shipped", bare=True) == (0, [])
    assert run("adapted from walkthrough §5 verbatim", bare=True) == (0, [])
    # Trailing hand-off to another document — never considered.
    assert run("resolved per §4.13 of the spec", bare=True) == (0, [])
    # Bare number that exists in the spec namespace, not the guide: a bare
    # spec citation ("per §4.13, or --output-dir") — dropped, not failed.
    assert run("resolved per §4.13, or --output-dir", bare=True) == (0, [])
    # Bare number in neither namespace: a real stale citation.
    count, messages = run("resolved per §41.3, always", bare=True)
    assert count == 1 and "no such section" in messages[0]
    # Outside a bare-namespace file, bare tokens are ignored entirely...
    assert run("resolved per §41.3, always", bare=False) == (0, [])
    # ...but naming the guide in the lead-in opts the token in, anywhere.
    count, messages = run("see the Patterns Guide §31 recipe", bare=False)
    assert count == 1 and "no such section" in messages[0]
    assert run("see Patterns Guide §24.5 for the archetypes", bare=False) == (1, [])
    assert run("standards live in `s0ma://guide/patterns` — **§24** rules", bare=False) == (1, [])
    # Ranges: both endpoints checked, prefixed or bare tail.
    assert run("the standards (patterns guide §27–§28) apply", bare=False) == (2, [])
    count, messages = run("the standards (patterns guide §27–29) apply", bare=False)
    assert count == 2 and len(messages) == 1 and "§29" in messages[0]
    # Bold-inline titles are checked against the section actually there.
    assert run("see **§24 Project layout (feature-first)** for the shape", bare=True) == (1, [])
    count, messages = run("see **§24 Late-bind dependency slot recipe** now", bare=True)
    assert count == 1 and "cited with title" in messages[0]
    # Quoted titles too; prefix words are enough, paraphrase is not.
    assert run('the guide’s §24 ("Project layout") section', bare=True) == (1, [])
    count, messages = run('the guide’s §27 ("Boundary rules") section', bare=True)
    assert count == 1 and "cited with title" in messages[0]
    # Em-dash trailers are descriptions, not titles — existence-checked only.
    assert run("Patterns guide §27 — keep the exempt set closed", bare=False) == (1, [])
