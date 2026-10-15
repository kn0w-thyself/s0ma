"""Drift guard for the ``editors/`` TextMate grammar (UX phase 1, M5).

``editors/s0ma.tmLanguage.json`` is a standalone repo artifact — it is not
packaged or served — but its declaration-keyword set must track the language
spec. These tests are pure Python (no node tooling):

* the declaration set is harvested from the spec's section headings
  (``### 4.1 `nerve` (...)`` style) and compared against the keyword
  alternations in the grammar's three declaration rules;
* the ``---`` body-fence begin/end patterns are statically simulated against
  the multi-declaration fixture ``tests/fixtures/valid/signal_processor.s0ma``
  using Python's ``re`` as a proxy for TextMate's oniguruma engine — the
  grammar deliberately restricts itself to constructs the two engines share,
  which ``test_every_grammar_regex_compiles_under_python_re`` enforces.

What this does NOT verify: actual rendering inside VS Code / a real
TextMate host (no editor is available in CI). See ``editors/README.md``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_PACKAGE_DIR = _TESTS_DIR.parent
_REPO_ROOT = _PACKAGE_DIR.parent.parent
_GRAMMAR_PATH = _REPO_ROOT / "editors" / "s0ma.tmLanguage.json"
_FIXTURE_PATH = _TESTS_DIR / "fixtures" / "valid" / "signal_processor.s0ma"

# A declaration-defining spec heading is a section number immediately followed
# by a backticked lowercase name:  ### 4.1 `nerve` (Observable Function)
# Prose headings ("#### 4.1.1 The `raises` Field") and artifact headings
# ("#### 4.14.3 `build.s0ma.pyi` ...") do not match: the former because words
# precede the backtick, the latter because the name class forbids dots.
_SPEC_DECL_HEADING_RE = re.compile(
    r"^#{3,4} [0-9.]+[a-z]? `([a-z][a-z0-9-]*)`", re.MULTILINE
)

# An alternation group made up solely of lowercase keyword alternatives,
# e.g. (nerve|cell|ganglion|test|helper|integration) or (axon). Groups such
# as (\w+), (::) or ( {4}) contain characters outside the class and are
# ignored, so scanning a declaration rule's match string yields exactly its
# keyword alternation.
_KEYWORD_GROUP_RE = re.compile(r"\(([a-z][a-z0-9-]*(?:\|[a-z][a-z0-9-]*)*)\)")

_DECLARATION_RULES = (
    "declaration-layered",
    "declaration-axon",
    "declaration-unlayered",
)


def _load_grammar() -> dict:
    return json.loads(_GRAMMAR_PATH.read_text(encoding="utf-8"))


def _spec_path() -> Path:
    candidates = sorted(
        _PACKAGE_DIR.glob("docs/s0ma-dsl-spec-v*.md"),
        key=lambda p: tuple(
            int(part)
            for part in re.findall(r"\d+", p.stem.split("spec-v", 1)[1])
        ),
    )
    assert candidates, "no spec file found under packages/s0ma-dsl/docs/"
    return candidates[-1]


def _spec_declaration_set() -> set[str]:
    text = _spec_path().read_text(encoding="utf-8")
    found = set(_SPEC_DECL_HEADING_RE.findall(text))
    # Guard the harvest itself: if the spec's heading style ever changes,
    # fail loudly rather than vacuously comparing empty sets.
    core = {"module", "nerve", "cell", "ganglion", "axon", "helper", "test"}
    assert core <= found, (
        "spec declaration harvest looks broken; got only: "
        f"{sorted(found)} from {_spec_path().name}"
    )
    return found


def _grammar_declaration_set(grammar: dict) -> set[str]:
    keywords: set[str] = set()
    for rule_name in _DECLARATION_RULES:
        rule = grammar["repository"][rule_name]
        for group in _KEYWORD_GROUP_RE.findall(rule["match"]):
            keywords.update(group.split("|"))
    return keywords


def test_grammar_is_valid_json_with_expected_identity() -> None:
    grammar = _load_grammar()
    assert grammar["scopeName"] == "source.s0ma"
    assert grammar["fileTypes"] == ["s0ma"]
    for rule_name in _DECLARATION_RULES + ("body-fence", "field", "string", "comment"):
        assert rule_name in grammar["repository"], f"missing rule: {rule_name}"


def test_declaration_keywords_match_spec() -> None:
    grammar_set = _grammar_declaration_set(_load_grammar())
    spec_set = _spec_declaration_set()
    assert grammar_set == spec_set, (
        f"grammar/spec declaration drift: only in grammar = "
        f"{sorted(grammar_set - spec_set)}, only in spec = "
        f"{sorted(spec_set - grammar_set)}"
    )


def test_fence_end_pattern_covers_every_declaration_keyword() -> None:
    grammar = _load_grammar()
    end_pattern = grammar["repository"]["body-fence"]["end"]
    for keyword in _spec_declaration_set():
        assert keyword in end_pattern, (
            f"body-fence end pattern cannot terminate before a "
            f"'{keyword}' declaration"
        )


def test_field_rule_covers_appendix_a_core_keys() -> None:
    field_rule = _load_grammar()["repository"]["field"]["patterns"][0]["match"]
    groups = re.findall(r"\(([a-z_]+(?:\|[a-z_]+)+)\)", field_rule)
    assert groups, "known-field alternation not found in the field rule"
    known = set(groups[0].split("|"))
    core = {
        "intent", "kind", "visibility", "layer", "version", "expects",
        "guarantees", "evaluates_at", "exports", "uses", "requires",
        "schema", "observes", "tests", "depends_on", "raises",
    }
    assert core <= known, f"field rule missing core keys: {sorted(core - known)}"


def test_every_grammar_regex_compiles_under_python_re() -> None:
    """Keep the grammar inside the re/oniguruma shared-syntax subset."""
    grammar = _load_grammar()
    patterns: list[str] = []

    def _collect(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"match", "begin", "end"} and isinstance(value, str):
                    patterns.append(value)
                else:
                    _collect(value)
        elif isinstance(node, list):
            for item in node:
                _collect(item)

    _collect(grammar)
    assert len(patterns) >= 15
    for pattern in patterns:
        re.compile(pattern)  # raises re.error on drift outside the subset


def _simulate_fence_spans(
    lines: list[str], begin: re.Pattern[str], end: re.Pattern[str]
) -> list[tuple[int, int | None]]:
    """Line-level simulation of the TextMate begin/end block semantics.

    A block opens on a line matching ``begin`` and closes at the first
    subsequent line where the (zero-width, lookahead-only) ``end`` matches;
    that closing line is yielded back to top-level rules, mirroring how a
    TextMate host re-tokenises the remainder of the line after a zero-width
    block end. ``None`` as a close line means the block ran to EOF.
    """
    spans: list[tuple[int, int | None]] = []
    open_line: int | None = None
    for lineno, line in enumerate(lines, start=1):
        if open_line is None:
            if begin.match(line):
                open_line = lineno
        elif end.match(line):
            spans.append((open_line, lineno))
            open_line = None
    if open_line is not None:
        spans.append((open_line, None))
    return spans


def test_fence_boundary_against_multi_declaration_fixture() -> None:
    """The embedded-Python block must end exactly at the next declaration.

    ``signal_processor.s0ma`` carries four ``---`` bodies followed by, in
    order: a ``cell`` header, a ``nerve`` header, a ``nerve`` header, and an
    ``axon`` header (the last preceded by a column-0 ``#`` comment, which by
    design stays inside the Python block — Python highlights it as a comment
    anyway).
    """
    grammar = _load_grammar()
    fence = grammar["repository"]["body-fence"]
    begin = re.compile(fence["begin"])
    end = re.compile(fence["end"])
    lines = _FIXTURE_PATH.read_text(encoding="utf-8").splitlines()

    spans = _simulate_fence_spans(lines, begin, end)
    assert spans == [(23, 31), (39, 42), (63, 71), (93, 100)], (
        f"fence spans drifted: {spans}"
    )

    # The close line of every span is a declaration header line.
    layered = re.compile(grammar["repository"]["declaration-layered"]["match"])
    axon = re.compile(grammar["repository"]["declaration-axon"]["match"])
    for _, close in spans:
        assert close is not None
        header = lines[close - 1]
        assert layered.match(header) or axon.match(header), header

    # Spot-check Python body content is inside the spans, headers outside.
    assert lines[23].lstrip().startswith("@dataclass")  # line 24, in (23, 31)
    assert lines[63].lstrip().startswith("def validate_envelope")  # line 64
    unlayered = re.compile(grammar["repository"]["declaration-unlayered"]["match"])
    assert unlayered.match(lines[0])  # module header, line 1, outside any span
    inside = {
        lineno
        for begin_line, close in spans
        for lineno in range(begin_line + 1, (close or len(lines) + 1))
    }
    for header_line in (1, 14, 31, 42, 71, 100):
        assert header_line not in inside
