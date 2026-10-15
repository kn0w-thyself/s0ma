"""Tests for ``scripts/check_authored_lines.py`` — the ``authored-lines`` stage.

The stage refuses an authored line (``intent``, ``guarantees``,
``invariants``, ``schema``, ``forbids``) that leans on something its reader
cannot open — a milestone id, a run, a plan, a date, a ruling — and requires
every allowed form a line cites (a PRD id, an invariant id, an ADR number, a
contract revision, a specification section) to resolve against the record
that defines it.

Like every gate that is enforced by *finding* something, it has two ways to
rot: a matcher that stopped matching reports nothing and passes forever, and
an allowlist entry can outlive the sentence that justified it. Both are pinned
here, beside one red proof per row of each table.

Two fixture styles, for two different jobs:

* **A scratch repository** under ``tmp_path`` — a throwaway ``git init`` with
  one ``.s0ma`` file in each tree the stage reads, registrations written in
  Python under ``packages/*/src/``, and a miniature of every record the
  allowed forms resolve against — is where the red proofs live.
  The stage reads ``git ls-files``, so the scratch tree is a real index, the
  way ``test_check_links_script.py`` builds its own. Faults are planted in the
  copy, never in the checkout.
* **The real tree**, read-only, is where the floors and the allowlist are
  proved live: the shipped readers clear both anti-vacuity floors, and every
  shipped ALLOWLIST entry still matches the line that justifies it. Neither
  assertion depends on the stage's verdict, so each holds whether the real
  tree is green or not; the end-to-end test is the one that reads the
  verdict.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "check_authored_lines.py"
CHECK_PY = REPO_ROOT / "scripts" / "check.py"

_GIT = shutil.which("git")

requires_checkout = pytest.mark.skipif(
    not (REPO_ROOT / "references" / "s0ma-prd.md").is_file(),
    reason="not a monorepo checkout (wheel-install context)",
)

#: Where a planted fault goes: its own file in the authoring server's tree.
PLANTED = "packages/s0ma-mcp/s0ma_src/planted.s0ma"
#: Where a planted Python fault goes: its own module in the language package's
#: sources, and in the core package's, whose sections are the core spec's.
PLANTED_PY = "packages/s0ma-dsl/src/s0ma_dsl/planted.py"
PLANTED_CORE = "packages/s0ma-core/src/s0ma/planted.py"
#: The module of Python registrations that clears the second floor.
PYTHON_FILLER = "packages/s0ma-dsl/src/s0ma_dsl/filler.py"

#: Miniatures of the records the allowed forms resolve against. Each defines
#: its ids the way the real record does, and each holds one near miss.
SOURCES: dict[str, str] = {
    "references/s0ma-prd.md": (
        "# PRD\n\n"
        "## 5. Principles (P-#)\n\n"
        "- **P-6 — No LLM in the loadbearing path.** Body.\n\n"
        "## 6. Invariants (INV-#) — never break these\n\n"
        "- **INV-3 — File extensions.** Body.\n"
        "- **INV-5 — Deterministic artifacts.** Body.\n\n"
        "## 7. Functional requirements\n\n"
        "- **FR-DSL-6** MUST support the four strictness modes.\n"
        "- **FR-MCP-10 [NEW v1.1]** MUST serve meta resources.\n"
        "- **FR-STUDI0-8** MUST render the graph.\n"
        "- **INV-8 — Outside the invariants section.** Not a definition of it.\n\n"
        "## 8. Non-functional requirements (NFR)\n\n"
        "- **NFR-5 — Agent ergonomics.** Body.\n"
        "- **M-8 — A success metric.** Body.\n\n"
        "## 10. Success metrics\n\n"
        "| # | Metric | Target |\n|---|---|---|\n"
        "| M-10 | A tabled success metric | 1 |\n"
    ),
    # The newest by number is v0.10.0, which a string sort would put first.
    "packages/s0ma-core/docs/s0ma-core-spec-v0.2.0.md": (
        "# Core spec\n\n### INV-CORE-2 — Only in the older spec\n"
    ),
    "packages/s0ma-core/docs/s0ma-core-spec-v0.10.0.md": (
        "# Core spec\n\n### INV-CORE-1 — Registration is creation\n\n"
        "## 5. Registry\n\n### 5.3 Registration\n"
    ),
    "docs/adr/ADR-001-gate-integrity.md": "# ADR-001\n",
    "packages/s0ma-dsl/docs/adr/ADR-011-metadata.md": "# ADR-011\n",
    "docs/contracts/0.14.0-schema-and-surface-budget.md": (
        "# Contract\n\n"
        "## 10. Revisions\n\n"
        "### 10.5 Revision log\n\n"
        "| Revision | Change |\n|---|---|\n| R5 | a |\n| R1 | b |\n\n"
        "## 11. Later\n\n"
        "| R9 | a table outside the log |\n"
    ),
    "packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.1.0.md": (
        "# Spec\n\n"
        "## 2. Architecture\n\n"
        "### 2.1 Build Pipeline\n\n"
        "### 4.4a `helper` (Module-Private Function)\n\n"
        "```bash\n# 9.9 a shell comment, not a heading\n```\n"
    ),
}

#: One line that cites a resolving use of every allowed form, and one that
#: carries every product token the reader met shaped like an ephemeral form.
CITES_EVERY_FORM = (
    "Serves FR-DSL-6, FR-MCP-10 and FR-STUDI0-8 under P-6, NFR-5 and M-8, keeps INV-3, "
    "INV-5 and INV-CORE-1, follows ADR-001 and ADR-011 (e), contract revisions R1 and R5, "
    "and the specification's §2.1 and §4.4a."
)
PRODUCT_TEXT = (
    "Writes HTML5 as UTF-8 (utf-8 on the wire), counts from column-0, maps exit-code-3, "
    "binds 127.0.0.1, and owns the module's decision record."
)

#: The green registrations written in Python: the five fields through the
#: three calls, in every shape read as one line — a string, an implicit
#: concatenation, a list and a tuple of strings. Six lines in two files.
PYTHON_BASELINE: dict[str, str] = {
    "packages/s0ma-core/src/s0ma/registry.py": (
        "from s0ma.models import ComponentSpec, Contract\n\n"
        "SPECS = [\n"
        "    ComponentSpec(\n"
        '        name="Registry",\n'
        "        intent=(\n"
        '            "Holds every registered component "\n'
        '            "and answers lookups by name."\n'
        "        ),\n"
        "        contracts=[\n"
        "            Contract(\n"
        '                invariants=["One name, one component.", "A lookup never writes."],\n'
        '                forbids=("Registering one name twice.",),\n'
        "            )\n"
        "        ],\n"
        "    ),\n"
        "]\n"
    ),
    "packages/s0ma-dsl/src/s0ma_dsl/server.py": (
        "from s0ma import component\n\n"
        "@component(\n"
        '    name="S0maDSL_Server",\n'
        '    intent="Serves the compiled self-model.",\n'
        '    guarantees="Returns the same model for the same sources.",\n'
        '    schema="dict[str, str]",\n'
        ")\n"
        "class Server:\n"
        "    pass\n"
    ),
}


@cache
def _checker() -> ModuleType:
    """Import ``scripts/check_authored_lines.py`` for direct calls.

    Registered in ``sys.modules`` before execution because ``@dataclass``
    resolves a class's module through it.
    """
    spec = importlib.util.spec_from_file_location("s0ma_check_authored_lines", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _require_git() -> str:
    if _GIT is None:
        pytest.skip("git unavailable")
    return _GIT


def _module(name: str, intent: str, rest: str = "") -> str:
    """A module whose ``intent:`` sits on line 4 and holds *intent* verbatim."""
    return (
        f"module {name}\n    layer: APPLICATION\n    version: 0.1.0\n"
        f"    intent: {intent}\n{rest}"
    )


def _filler(count: int) -> str:
    """*count* authored lines (one ``intent`` per cell), to clear the floor."""
    cells = (f'\ncell FILLER_{index} :: DOMAIN\n    intent: "Filler line {index}."\n'
             for index in range(count))
    return _module("filler", '"Holds the filler cells."') + "".join(cells)


def _python_filler(count: int) -> str:
    """*count* Python-authored lines (one ``intent`` per registration), for the second floor."""
    registrations = (
        f'\n@component(name="Filler_{index}", intent="Filler registration {index}.")\n'
        f"def filler_{index}() -> None:\n    pass\n"
        for index in range(count)
    )
    return "from s0ma import component\n" + "".join(registrations)


def _registration(field: str, value: str) -> str:
    """A module whose one ``@component`` passes the Python source *value* as *field* on line 4."""
    return (
        f"from s0ma import component\n\n@component(\n    {field}={value},\n"
        '    name="S0maDSL_Planted",\n)\nclass Planted:\n    pass\n'
    )


def _tree(
    *, baseline: bool = True, filler: int | None = None, python_filler: int | None = None
) -> dict[str, str]:
    """A green scratch tree: a ``.s0ma`` file in every tree, registrations, every record.

    Built from the checker's own TREES, so a tree added there cannot leave this
    fixture quietly incomplete. ``filler`` defaults to the floor plus five, the
    baseline's own lines included, and ``python_filler`` to the second floor
    plus five; ``baseline=False`` leaves every file but the fillers without an
    authored line, so the counts are exactly ``filler`` + 1 and
    ``python_filler``.
    """
    checker = _checker()
    files = dict(SOURCES)
    for tree in checker.TREES:
        files[f"{tree}/placeholder.s0ma"] = "# no declaration here\n"
    if baseline:
        files["packages/s0ma-mcp/s0ma_src/server.s0ma"] = _module(
            "server",
            f'"{CITES_EVERY_FORM}"',
            f'\nnerve render :: APPLICATION\n    intent: "{PRODUCT_TEXT}"\n'
            '    guarantees: "Returns the page."\n    forbids: none\n'
            '\ncell STATE :: DOMAIN\n    intent: "The state."\n'
            '    invariants: "Holds one owner."\n    schema: "dict[str, str]"\n',
        )
        files["docs/s0ma_src/application.s0ma"] = _module(
            "application",
            '"The documentation application."',
            '\ndoc-ref guide_ref\n    intent: "Renders the guide."\n',
        )
        files.update(PYTHON_BASELINE)
    if filler is None:
        filler = checker.MINIMUM_AUTHORED_LINES + 5
    files["packages/s0ma-dsl/tests/fixtures/filler/filler.s0ma"] = _filler(filler)
    if python_filler is None:
        python_filler = checker.MINIMUM_PYTHON_LINES + 5
    files[PYTHON_FILLER] = _python_filler(python_filler)
    return files


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """A throwaway git repository whose index holds exactly *files*."""
    git = _require_git()
    root = tmp_path / "repo"
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    subprocess.run([git, "init", "-q"], cwd=root, check=True)
    subprocess.run([git, "add", "."], cwd=root, check=True)
    return root


def _plant(tmp_path: Path, text: str, *, at: str = PLANTED, **kwargs: object) -> Path:
    """The green tree with *text* as the whole of the file *at*, PLANTED unless named."""
    files = _tree(**kwargs)  # type: ignore[arg-type]
    files[at] = text
    return _make_repo(tmp_path, files)


def _check(root: Path) -> int:
    """Run the stage against *root* with no exemptions.

    The shipped ALLOWLIST pins lines in the real repository, so on a scratch
    tree every entry would report itself stale — noise that would bury the
    warning the allowlist tests are about.
    """
    return int(_checker().check(root, allowlist=()))


# ---------------------------------------------------------------------------
# The green baseline
# ---------------------------------------------------------------------------


def test_green_scratch_tree_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Every allowed form resolves and no product token is mistaken for a form.

    The baseline cites one resolving use of every allowed form, ``FR-DSL-6``
    beside ``FR-MCP-10`` and ``FR-STUDI0-8`` (an id row read before them would
    see ``DSL-6``, ``MCP-10`` and ``STUDI0-8``), and carries the product text
    shaped like an ephemeral form: ``HTML5``, ``UTF-8``, ``utf-8``,
    ``column-0``, ``exit-code-3``, ``127.0.0.1``, a module's "decision", an
    "owner". So every red case below means what it says. The registrations
    written in Python are read as well: each value of PYTHON_BASELINE is one
    line, the list and the tuple included, beside the filler's.
    """
    checker = _checker()
    assert _check(_make_repo(tmp_path, _tree())) == 0
    output = capsys.readouterr().out
    assert "authored-lines: PASS" in output
    assert (
        f"{checker.MINIMUM_PYTHON_LINES + 5 + 6} Python-authored line(s) read in 3 .py "
        f"file(s) (0 not read: not a literal)"
    ) in output
    assert "15 allowed form use(s) resolved" in output
    assert "VIOLATION" not in output
    assert "UNRESOLVED" not in output


# ---------------------------------------------------------------------------
# The ephemeral forms: one refusal per row, and per shape the rows cover
# ---------------------------------------------------------------------------


def test_every_row_refuses_its_own_example(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each EPHEMERAL row's ``refused`` example is refused, under that row's label."""
    checker = _checker()
    for index, row in enumerate(checker.EPHEMERAL):
        root = _plant(tmp_path / str(index), _module("planted", f'"{row.refused}"'))
        assert _check(root) != 0, row.form
        output = capsys.readouterr().out
        assert f"VIOLATION {PLANTED}:4: intent of module:planted: " in output, row.form
        assert f"({row.key})" in output, row.form


@pytest.mark.parametrize(
    ("value", "forms"),
    [
        pytest.param("Pinned by M5 acceptance.", ["'M5' (id)"], id="milestone-id"),
        pytest.param("The G7a derived-docs fixture.", ["'G7a' (id)"], id="letter-suffixed-id"),
        pytest.param("Exercises the M02 shape.", ["'M02' (id)"], id="zero-padded-id"),
        pytest.param(
            "Imports deferred (DSL-M2, F-M3-1 restored), (CRIT-3), (POST-4c).",
            ["'DSL-M2' (id)", "'F-M3-1' (id)", "'CRIT-3' (id)", "'POST-4c' (id)"],
            id="word-prefixed-id",
        ),
        pytest.param(
            "Off silences offers only (FD-13), and D-11 holds.",
            ["'FD-13' (id)", "'D-11' (id)"],
            id="hyphenated-decision-id",
        ),
        pytest.param(
            "The rules (batch-01a D1/O2).",
            ["'batch-01a' (id)", "'D1' (id)", "'O2' (id)"],
            id="batch-id",
        ),
        pytest.param(
            "pilot-01 saw it; feedback-5 and feedback-5.5 too.",
            ["'pilot-01' (run id)", "'feedback-5' (run id)", "'feedback-5.5' (run id)"],
            id="lowercase-run-id",
        ),
        pytest.param(
            "Sequenced in plans/next.md, this wave, after the milestone and its audit.",
            [
                "'plans/' (planning word)",
                "'wave' (planning word)",
                "'milestone' (planning word)",
                "'audit' (planning word)",
            ],
            id="planning-words",
        ),
        pytest.param(
            "(plan §3.6: the graph document) and §1.2 fact 15 is the caveat.",
            ["'plan §3.6' (plan clause)", "'§1.2 fact 15' (plan clause)"],
            id="section-citing-a-plan",
        ),
        pytest.param("Cut on 2026-08-30.", ["'2026-08-30' (date)"], id="date"),
        pytest.param(
            "Owner-ratified; an owner ruling settled it.",
            ["'Owner-ratified' (ruling)", "'owner ruling' (ruling)"],
            id="ruling",
        ),
        pytest.param(
            "Kept because the owner asked for it.", ["'the owner asked' (ruling)"], id="person"
        ),
    ],
)
def test_an_ephemeral_form_is_refused_with_file_line_field_and_form(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str, forms: list[str]
) -> None:
    """The gate's whole purpose, proved failing, in the format the stage promises.

    Each refusal names the file and the line the field starts on, the field,
    and every matched form; the three legitimate answers follow once, so a
    contributor meeting this for the first time needs no other page.
    """
    assert _check(_plant(tmp_path, _module("planted", f'"{value}"'))) == 1
    output = capsys.readouterr().out
    (violation,) = [line for line in output.splitlines() if line.startswith("VIOLATION")]
    assert violation.startswith(f"VIOLATION {PLANTED}:4: intent of module:planted: ")
    assert violation.endswith(": " + ", ".join(forms))
    assert "reword it to stand alone" in output
    assert "replace the reference with an allowed form" in output
    assert "record it in ALLOWLIST" in output
    assert "authored-lines: FAIL - 1 line(s) refused" in output


@pytest.mark.parametrize(
    ("text", "lineno", "field"),
    [
        pytest.param(
            _module("planted", '"First physical line,\n        then the owner\n'
                    '        decision on a third."'),
            4, "intent", id="quoted-over-several-lines",
        ),
        pytest.param(
            _module("planted", "|\n        A block scalar\n        that names G7b."),
            4, "intent", id="block-scalar",
        ),
        pytest.param(_module("planted", 'pending("until M5 lands")'), 4, "intent", id="pending"),
        pytest.param(
            _module("planted", '"Plain."', '\nnerve planted_nerve :: APPLICATION\n'
                    '    intent: "Plain."\n    guarantees:\n        - "Holds the line."\n'
                    '        - "Cut on 2026-08-30."\n    forbids: none\n'),
            8, "guarantees", id="block-list",
        ),
        pytest.param(
            _module("planted", '"Plain."', '\ncell PLANTED :: DOMAIN\n    intent: "Plain."\n'
                    '    invariants: "Plain."\n    schema: "str, pinned by M5"\n'),
            9, "schema", id="schema",
        ),
        pytest.param(
            _module("planted", '"Plain."', '\ndoc-ref planted_doc\n    intent: "G7a fixture."\n'),
            7, "intent", id="doc-ref-intent",
        ),
    ],
)
def test_every_value_shape_is_read_at_the_line_its_field_starts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, lineno: int, field: str
) -> None:
    """The parser's splitter decides where a field starts and ends.

    A quoted string over several physical lines is one line (the phrase broken
    across two of them is still the phrase), and so are a block scalar, a
    pending reason and a block list. A ``doc-ref`` is the matrix's ``doc_ref``:
    keyed on the header word instead, a reader skips its ``intent`` silently.
    """
    assert _check(_plant(tmp_path, text)) == 1
    output = capsys.readouterr().out
    assert f"VIOLATION {PLANTED}:{lineno}: {field} of " in output


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            _module("planted", '"Plain."', '\nnerve planted_nerve :: APPLICATION\n'
                    '    intent: "Plain."\n    guarantees: "Plain."\n    forbids: none\n'
                    "---\n# pinned by M5, cut on 2026-08-30 (owner ruling)\nreturn None\n"),
            id="the-body-after-the-separator",
        ),
        pytest.param(
            _module("planted", '"Plain."', '\nnerve planted_nerve :: APPLICATION\n'
                    '    intent: "Plain."\n    guarantees: "Plain."\n    forbids: none\n'
                    '    returns: "pinned by M5"\n'),
            id="a-field-outside-the-five",
        ),
        pytest.param(
            _module("planted", '"Plain."', '\nnerve planted_nerve :: APPLICATION\n'
                    '    intent: "Plain."\n    guarantees: "Plain."\n    forbids: none\n'
                    '    schema: "pinned by M5"\n'),
            id="a-field-the-matrix-does-not-list-for-the-kind",
        ),
    ],
)
def test_what_is_not_an_authored_line_is_not_read(tmp_path: Path, text: str) -> None:
    """Code, other fields, and fields the matrix does not give a kind are not read."""
    assert _check(_plant(tmp_path, text)) == 0


def test_an_untracked_file_is_invisible(tmp_path: Path) -> None:
    """The corpus is ``git ls-files``, as every other corpus gate reads it."""
    root = _make_repo(tmp_path, _tree())
    (root / PLANTED).write_text(_module("planted", '"Pinned by M5."'), encoding="utf-8")
    assert _check(root) == 0


# ---------------------------------------------------------------------------
# The registrations written in Python, and the spike fixtures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "key", "form"),
    [
        pytest.param("intent", "id", "'M5' (id)", id="intent"),
        pytest.param("guarantees", "run id", "'pilot-01' (run id)", id="guarantees"),
        pytest.param("invariants", "planning word", "'plan' (planning word)", id="invariants"),
        pytest.param("schema", "date", "'2026-08-30' (date)", id="schema"),
        pytest.param("forbids", "ruling", "'owner-ratified' (ruling)", id="forbids"),
    ],
)
def test_a_python_literal_is_refused_in_every_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], field: str, key: str, form: str
) -> None:
    """Each of the five keywords is read on a registration, and refused in the same format.

    The refusal names the file, the line the keyword starts on, the field, the
    registration as ``<call>:<name>`` and the form; the planted text is the
    row's own example.
    """
    (row,) = [row for row in _checker().EPHEMERAL if row.key == key]
    root = _plant(tmp_path, _registration(field, repr(row.refused)), at=PLANTED_PY)
    assert _check(root) == 1
    output = capsys.readouterr().out
    (violation,) = [line for line in output.splitlines() if line.startswith("VIOLATION")]
    assert violation == f"VIOLATION {PLANTED_PY}:4: {field} of component:S0maDSL_Planted: {form}"
    assert "authored-lines: FAIL - 1 line(s) refused" in output


@pytest.mark.parametrize(
    ("field", "value", "form"),
    [
        pytest.param(
            "intent", '(\n        "Pinned by M"\n        "5 acceptance."\n    )', "'M5' (id)",
            id="implicit-concatenation",
        ),
        pytest.param(
            "invariants", '["Kept because the owner", "asked for it."]',
            "'the owner asked' (ruling)", id="list-of-literals",
        ),
        pytest.param(
            "forbids", '("Kept because the owner", "asked for it.")',
            "'the owner asked' (ruling)", id="tuple-of-literals",
        ),
    ],
)
def test_a_value_written_in_pieces_is_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], field: str, value: str, form: str
) -> None:
    """The pieces are one line: a phrase split between two of them is still the phrase.

    ``ast`` folds an implicit concatenation into one constant; a list or a
    tuple of literals is joined with single spaces, as a block list is one
    field. Read piece by piece, neither half would match.
    """
    assert _check(_plant(tmp_path, _registration(field, value), at=PLANTED_PY)) == 1
    output = capsys.readouterr().out
    assert f"VIOLATION {PLANTED_PY}:4: {field} of component:S0maDSL_Planted: {form}" in output


@pytest.mark.parametrize(
    "value",
    [
        pytest.param('f"Pinned by M5 for {version}."', id="f-string"),
        pytest.param("PINNED_BY_M5", id="name"),
        pytest.param('describe("pinned by M5")', id="call"),
        pytest.param("spec.pinned_by_m5", id="attribute"),
        pytest.param('["Plain.", PINNED_BY_M5]', id="list-holding-a-name"),
    ],
)
def test_a_value_that_is_not_a_literal_is_counted_not_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    """It is made somewhere else, not written at the call; the summary says how many."""
    assert _check(_plant(tmp_path, _registration("intent", value), at=PLANTED_PY)) == 0
    output = capsys.readouterr().out
    assert "(1 not read: not a literal)" in output
    assert "VIOLATION" not in output


def test_a_nested_contract_is_reported_under_its_registration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ``Contract`` carries no name: it belongs to the ``ComponentSpec`` it is passed to."""
    text = (
        "from s0ma.models import ComponentSpec, Contract\n\n"
        "SPEC = ComponentSpec(\n"
        '    name="Planted",\n'
        '    intent="Plain.",\n'
        "    contracts=[\n"
        "        Contract(\n"
        '            invariants=["Holds one owner.", "Pinned by M5 acceptance."],\n'
        "        )\n"
        "    ],\n"
        ")\n"
    )
    assert _check(_plant(tmp_path, text, at=PLANTED_CORE)) == 1
    output = capsys.readouterr().out
    assert f"VIOLATION {PLANTED_CORE}:8: invariants of Contract:Planted: 'M5' (id)" in output


@pytest.mark.parametrize(
    "rel",
    [
        pytest.param("packages/s0ma-mcp/src/s0ma_mcp/_built/tools.py", id="under-built"),
        pytest.param("packages/s0ma-dsl/tests/test_planted.py", id="outside-src"),
        pytest.param("scripts/planted.py", id="outside-packages"),
    ],
)
def test_a_python_file_outside_the_sources_is_invisible(tmp_path: Path, rel: str) -> None:
    """The build output repeats the ``.s0ma`` sources; a test or a script registers nothing."""
    text = _registration("intent", '"Pinned by M5 acceptance."')
    assert _check(_plant(tmp_path, text, at=rel)) == 0


def test_an_untracked_python_file_is_invisible(tmp_path: Path) -> None:
    """The Python half reads ``git ls-files`` too."""
    root = _make_repo(tmp_path, _tree())
    planted = root / PLANTED_PY
    planted.write_text(_registration("intent", '"Pinned by M5 acceptance."'), encoding="utf-8")
    assert _check(root) == 0


def test_a_python_file_that_does_not_parse_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Lines that cannot be read are not lines that passed."""
    assert _check(_plant(tmp_path, "@component(\n    intent=\n", at=PLANTED_PY)) == 1
    output = capsys.readouterr().out
    assert f"ERROR {PLANTED_PY}: this file cannot be read as Python source" in output
    assert "1 file(s) unreadable" in output


def test_a_spike_fixture_is_read_and_refused_when_it_leans(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``scripts/spikes`` is one of the trees: a spike's fixture teaches the language too."""
    spike = "scripts/spikes/planted/s0ma_src/fixture.s0ma"
    root = _plant(tmp_path, _module("spike", '"pilot-01 saw four sessions shell out"'), at=spike)
    assert _check(root) == 1
    output = capsys.readouterr().out
    assert f"VIOLATION {spike}:4: intent of module:spike: 'pilot-01' (run id)" in output


@pytest.mark.parametrize(
    ("rel", "cited", "against"),
    [
        pytest.param(PLANTED_CORE, "§5.3", None, id="core-line-core-section"),
        pytest.param(PLANTED_PY, "§2.1", None, id="language-line-language-section"),
        pytest.param(
            PLANTED_CORE, "§2.1", "packages/s0ma-core/docs/s0ma-core-spec-v",
            id="core-line-language-section",
        ),
        pytest.param(
            PLANTED_PY, "§5.3", "packages/s0ma-dsl/docs/s0ma-dsl-spec-v",
            id="language-line-core-section",
        ),
    ],
)
def test_a_section_resolves_against_the_specification_of_its_project(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    rel: str,
    cited: str,
    against: str | None,
) -> None:
    """A line under the core package cites the core specification; every other the language one."""
    text = _registration("intent", f'"Follows {cited} to the letter."')
    code = _check(_plant(tmp_path, text, at=rel))
    output = capsys.readouterr().out
    if against is None:
        assert code == 0, output
        assert "UNRESOLVED" not in output
    else:
        assert code == 1
        assert f"UNRESOLVED {rel}:4: intent of component:S0maDSL_Planted cites {cited!r}" in output
        assert f"no heading of the newest {against}*.md" in output


# ---------------------------------------------------------------------------
# The allowed forms: one unresolved use per row
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cited",
    [
        pytest.param("FR-ZZZ-9", id="prd-id-with-no-definition-item"),
        pytest.param("M-9", id="prd-metric-with-no-definition-item"),
        pytest.param("INV-99", id="invariant-with-no-definition-item"),
        pytest.param("INV-8", id="invariant-defined-outside-the-invariants-section"),
        pytest.param("INV-CORE-2", id="core-invariant-only-in-an-older-spec"),
        pytest.param("ADR-099", id="adr-with-no-record"),
        pytest.param("R9", id="revision-with-no-row-in-the-log"),
        pytest.param("§9.9", id="section-with-no-heading"),
    ],
)
def test_an_allowed_form_that_resolves_to_nothing_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], cited: str
) -> None:
    """An allowed form is durable only while the record it names exists."""
    root = _plant(tmp_path, _module("planted", f'"Follows {cited} to the letter."'))
    assert _check(root) == 1
    output = capsys.readouterr().out
    assert f"UNRESOLVED {PLANTED}:4: intent of module:planted cites {cited!r}" in output
    assert "VIOLATION" not in output
    assert "1 allowed form use(s) unresolved" in output


def test_a_prd_id_defined_by_a_table_row_resolves(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The PRD tables its success metrics: a first cell that is the id defines it."""
    assert _check(_plant(tmp_path, _module("planted", '"Holds M-10 to its target."'))) == 0
    output = capsys.readouterr().out
    assert "UNRESOLVED" not in output
    assert "authored-lines: PASS" in output


def test_an_allowed_form_is_taken_out_before_the_id_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``FR-DSL-7`` unresolved is one finding about ``FR-DSL-7``, never the id ``DSL-7``."""
    assert _check(_plant(tmp_path, _module("planted", '"Serves FR-DSL-7."'))) == 1
    output = capsys.readouterr().out
    assert "cites 'FR-DSL-7'" in output
    assert "DSL-7' (id)" not in output


# ---------------------------------------------------------------------------
# The allowlist
# ---------------------------------------------------------------------------


def test_an_allowlisted_form_is_kept_and_only_that_form(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The exemption covers the matched word on its line, never the whole line."""
    checker = _checker()
    entry = checker.Exempt(
        path=PLANTED,
        form="plan",
        on_line_containing="migrate_ext dry-run plan",
        why="fixture: the dry-run plan a tool produces",
    )
    clean = _plant(tmp_path / "clean", _module("planted", '"The migrate_ext dry-run plan."'))
    assert checker.check(clean, allowlist=(entry,)) == 0
    assert "1 form(s) allowlisted" in capsys.readouterr().out

    leaning = _plant(
        tmp_path / "leaning", _module("planted", '"The migrate_ext dry-run plan, after M5."')
    )
    assert checker.check(leaning, allowlist=(entry,)) == 1
    output = capsys.readouterr().out
    assert f"VIOLATION {PLANTED}:4: intent of module:planted: 'M5' (id)" in output
    assert "'plan'" not in output


def test_an_allowlist_entry_whose_line_was_reworded_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``on_line_containing`` is what stops an exemption outliving its reason."""
    checker = _checker()
    entry = checker.Exempt(
        path=PLANTED,
        form="plan",
        on_line_containing="a line that is no longer there",
        why="fixture: the line it covered was reworded",
    )
    root = _plant(tmp_path, _module("planted", '"Plain."'))
    assert checker.check(root, allowlist=(entry,)) == 0
    assert "WARNING stale allowlist entry" in capsys.readouterr().out


def test_an_allowlist_entry_for_a_python_line_is_kept_pinned_and_retired(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same entry, path and line text, covers a registration written in Python."""
    checker = _checker()
    entry = checker.Exempt(
        path=PLANTED_PY,
        form="audit",
        on_line_containing="for audit logging",
        why="fixture: the audit log an operation is recorded for",
    )
    kept = _plant(
        tmp_path / "kept",
        _registration("intent", '"Records an operation for audit logging."'),
        at=PLANTED_PY,
    )
    assert checker.check(kept, allowlist=(entry,)) == 0
    output = capsys.readouterr().out
    assert "1 form(s) allowlisted" in output
    assert "WARNING" not in output

    reworded = _plant(
        tmp_path / "reworded",
        _registration("intent", '"Records an operation for the audit trail."'),
        at=PLANTED_PY,
    )
    assert checker.check(reworded, allowlist=(entry,)) == 1
    output = capsys.readouterr().out
    assert f"WARNING stale allowlist entry: {PLANTED_PY} 'audit'" in output
    assert (
        f"VIOLATION {PLANTED_PY}:4: intent of component:S0maDSL_Planted: 'audit' (planning word)"
    ) in output


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("README.md", id="unread-file"),
        pytest.param("scripts/check.py", id="python-outside-the-sources"),
        pytest.param("packages/s0ma-mcp/src/s0ma_mcp/_built/tools.py", id="python-under-built"),
    ],
)
def test_an_allowlist_entry_outside_the_trees_is_an_error(
    capsys: pytest.CaptureFixture[str], path: str
) -> None:
    """An entry naming an unread file could never apply to anything."""
    checker = _checker()
    entry = checker.Exempt(path=path, form="plan", on_line_containing="x", why="fixture")
    assert checker.check(REPO_ROOT, allowlist=(entry,)) == 1
    assert "ERROR allowlist entry names a file outside TREES" in capsys.readouterr().out


def test_every_shipped_allowlist_entry_is_in_the_trees_and_justified() -> None:
    """Each entry names a read file, a tree's or a Python source, and says why, once."""
    checker = _checker()
    prefixes = tuple(f"{tree}/" for tree in checker.TREES)
    for entry in checker.ALLOWLIST:
        assert entry.path.startswith(prefixes) or checker.is_python_source(entry.path), entry
        assert entry.why.strip(), entry


@requires_checkout
def test_every_shipped_allowlist_entry_still_matches_its_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Liveness, not merely syntax: a warning does not change the exit code.

    Asserted on the stage's output whatever its verdict, so it holds while the
    real tree is still red.
    """
    _require_git()
    _checker().check(REPO_ROOT)
    assert "WARNING stale allowlist entry" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The anti-vacuity floor
# ---------------------------------------------------------------------------


def test_a_tree_with_no_authored_line_is_red(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Files present, authored lines absent: nothing was verified."""
    files = _tree(baseline=False, filler=0)
    files["packages/s0ma-dsl/tests/fixtures/filler/filler.s0ma"] = "axon a -> b\n"
    assert _check(_make_repo(tmp_path, files)) != 0
    output = capsys.readouterr().out
    assert "VACUOUS SCAN" in output
    assert "0 authored line(s) read" in output
    assert "PASS" not in output


def test_the_floor_is_exact_at_its_boundary(tmp_path: Path) -> None:
    """The boundary is where an off-by-one would hide (the filler module adds one line)."""
    floor = _checker().MINIMUM_AUTHORED_LINES
    under = _make_repo(tmp_path / "under", _tree(baseline=False, filler=floor - 2))
    at = _make_repo(tmp_path / "at", _tree(baseline=False, filler=floor - 1))
    assert _check(under) != 0
    assert _check(at) == 0


def test_the_python_floor_is_exact_at_its_boundary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The second floor: a reader that lost a package's registrations cannot pass."""
    floor = _checker().MINIMUM_PYTHON_LINES
    under = _make_repo(tmp_path / "under", _tree(baseline=False, python_filler=floor - 1))
    at = _make_repo(tmp_path / "at", _tree(baseline=False, python_filler=floor))
    assert _check(under) != 0
    output = capsys.readouterr().out
    assert f"VACUOUS SCAN: {floor - 1} Python-authored line(s) read in 1 .py file(s)" in output
    assert "PASS" not in output
    assert _check(at) == 0


def test_a_tree_without_a_tracked_s0ma_file_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tree that moved must fail loudly; reading all but one proves less."""
    files = _tree()
    del files["docs/s0ma_src/placeholder.s0ma"]
    del files["docs/s0ma_src/application.s0ma"]
    assert _check(_make_repo(tmp_path, files)) == 1
    assert "ERROR no tracked .s0ma file under docs/s0ma_src" in capsys.readouterr().out


def test_a_checkout_without_the_spike_tree_is_green_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The public export withholds ``scripts/spikes`` whole; that tree is optional."""
    files = {rel: text for rel, text in _tree().items() if not rel.startswith("scripts/spikes/")}
    assert _check(_make_repo(tmp_path, files)) == 0
    output = capsys.readouterr().out
    assert "NOTE no tracked .s0ma file under scripts/spikes - withheld" in output
    assert "across 5 trees" in output
    assert "ERROR" not in output


@requires_checkout
def test_the_real_tree_clears_the_floor(capsys: pytest.CaptureFixture[str]) -> None:
    """Both floors are live measurements, read from the stage's own count line."""
    _require_git()
    checker = _checker()
    checker.check(REPO_ROOT)
    output = capsys.readouterr().out
    found = re.search(r"(\d+) authored line\(s\) read", output)
    python = re.search(r"(\d+) Python-authored line\(s\) read", output)
    assert found is not None
    assert python is not None
    assert int(found.group(1)) >= checker.MINIMUM_AUTHORED_LINES
    assert int(python.group(1)) >= checker.MINIMUM_PYTHON_LINES


# ---------------------------------------------------------------------------
# Wiring — the stage is registered and the real tree is green
# ---------------------------------------------------------------------------


@requires_checkout
def test_the_script_runs_green_end_to_end() -> None:
    """The real exit code the stage consumes, in one process."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "authored-lines: PASS" in result.stdout


def test_the_stage_is_registered_in_the_canonical_gate() -> None:
    """The script is only a gate if ``check.py`` runs it."""
    source = CHECK_PY.read_text(encoding="utf-8")
    assert '"authored-lines"' in source
    assert "scripts/check_authored_lines.py" in source
