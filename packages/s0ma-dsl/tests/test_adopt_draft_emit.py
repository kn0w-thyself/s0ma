"""The draft emitter: a harvested module becomes ``.s0ma`` text that parses.

Four things are proved here, and the last two are the ones that matter.

**It is pure.** The same draft gives byte-identical text, with LF endings
and one trailing newline, carrying no timestamp and no absolute path.

**It writes a header the parser accepts.** All six requires-family
fields are authored on every module, ``none`` included — omitting one
raises ``SEMANTIC_REQUIRED_STATE_OMITTED`` before any placeholder
diagnostic is reached (friction F-D1-4).

**Bodies survive byte for byte.** A body carrying comments, odd spacing,
trailing whitespace, a line of only whitespace, a line reading ``---``
and lines that look like declaration headers comes back out of the real
parser exactly as it went in. That is the whole promise of a retrofit:
the code is moved, never rewritten.

**Every golden parses, and its debt is counted.** One golden per fixture
application module, compared byte for byte; each is run through the real
parser and the real intra-module validator; and each golden's count of
``FIXME(adopt):`` markers is asserted exactly, so D3 — which turns those
markers into refusals — has a precise target to hit.

Regenerating the goldens
------------------------

``S0MA_UPDATE_ADOPT_GOLDENS=1 uv run pytest
packages/s0ma-dsl/tests/test_adopt_draft_emit.py`` rewrites every golden
from the fixture applications and then checks them as usual. Read the
diff before committing it: a golden is evidence, and a changed golden
means the drafts every reader of the guide will see have changed too.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from s0ma_dsl.adopt.discovery import discover_sources
from s0ma_dsl.adopt.draft_emit import (
    DRAFT_VERSION,
    FALLBACK_LAYER,
    PLACEHOLDERS,
    PROVENANCE_PREFIX,
    UNPLACED_CELL_INTENT,
    emit_draft,
)
from s0ma_dsl.adopt.harvest import (
    UNPLACED_CELL_PREFIX,
    harvest_module,
    render_unplaced_value,
)
from s0ma_dsl.adopt.model import (
    DRAFT_INTENT_MARKER,
    DRAFT_UNPLACED_MARKER,
    DraftModule,
    SourceFile,
)
from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.semantic.validator import validate_module

_TESTS_DIR = Path(__file__).parent
_BROWNFIELD = _TESTS_DIR / "fixtures" / "brownfield"
_GOLDEN_DIR = _BROWNFIELD / "_golden" / "drafts"

_UPDATE_ENV = "S0MA_UPDATE_ADOPT_GOLDENS"

_DRAFTABLE_ROLES = frozenset({"app", "script"})
"""Roles that get a draft: everything but a test file and a package marker."""


# ---------------------------------------------------------------------------
# The goldens, and the debt each one carries
# ---------------------------------------------------------------------------

EXPECTED_PLACEHOLDERS: dict[str, int] = {
    "layered_app/__main__": 1,
    "layered_app/api": 34,
    "layered_app/catalog": 10,
    "layered_app/cli": 9,
    "layered_app/config": 15,
    "layered_app/errors": 21,
    "layered_app/lending": 11,
    "layered_app/models": 13,
    "layered_app/notifications": 17,
    "layered_app/storage": 3,
    "tiny_app/inventory": 22,
    "tiny_app/report": 7,
    "tiny_app/run": 15,
}
"""How many ``FIXME(adopt):`` markers each golden carries.

One per un-authored field: a module intent, then four per nerve
(intent, expects, guarantees, forbids), two per cell (intent, schema) and one per
helper (intent). The numbers are asserted exactly rather than as "more
than zero" so that D3, which makes every one of these an error, has a
target it can count against — and so that a change in what the emitter
asks an author for cannot slip through unnoticed.
"""

GOLDEN_WARNING_CODES = frozenset({"BARE_IMPORT"})
"""The only diagnostic a golden is allowed to raise, with its reason.

``BARE_IMPORT`` — a function-scoped import stays in the body verbatim
(bodies are never edited) while also riding in ``deferred_requires:``.
The diagnostic is a warning in migration mode and its own remediation
says the right thing: the header half is done, now delete the line from
the body. Anything else appearing here is a regression.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fixture_drafts(app: str) -> dict[str, DraftModule]:
    """Every draftable module of a fixture application, by file stem."""
    root = _BROWNFIELD / app
    sources = discover_sources(root)
    first_party = frozenset(source.module for source in sources)
    return {
        Path(source.path).stem: harvest_module(root, source, first_party=first_party)
        for source in sources
        if source.role in _DRAFTABLE_ROLES
    }


def _golden_keys() -> list[str]:
    """``<app>/<stem>`` for every module that should have a golden."""
    return sorted(
        f"{app}/{stem}"
        for app in ("layered_app", "tiny_app")
        for stem in _fixture_drafts(app)
    )


def _golden_text(key: str) -> str:
    """The golden on disk, read as bytes so its line endings stay visible.

    ``read_text`` would translate a stray CRLF into a bare newline and
    hide exactly the drift these goldens exist to catch.
    """
    return (_GOLDEN_DIR / f"{key}.s0ma").read_bytes().decode("utf-8")


def _emit_fixture(key: str) -> str:
    """Emit the draft for ``<app>/<stem>`` from the fixture tree."""
    app, _, stem = key.partition("/")
    return emit_draft(_fixture_drafts(app)[stem])


def _write(tmp_path: Path, relative: str, text: str) -> SourceFile:
    """Write a module into *tmp_path* and describe it as a discovered file."""
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    dotted = relative[: -len(".py")].replace("/", ".")
    return SourceFile(path=relative, module=dotted, source_root=".", role="app")


def _draft(tmp_path: Path, relative: str, text: str, **kwargs: object) -> DraftModule:
    """Write a module and harvest it in one step."""
    source = _write(tmp_path, relative, text)
    return harvest_module(tmp_path, source, **kwargs)  # type: ignore[arg-type]


DRAFT_DEBT_PREFIX = "ADOPT_"
"""The diagnostic family a draft is *supposed* to trip (D3).

``ADOPT_PLACEHOLDER_INTENT`` and ``ADOPT_UNPLACED_CODE`` are what a
draft is for: they name the meaning nobody has written yet and the
source nobody has placed yet, and they are errors in every mode so that
a draft cannot build or score as though it were finished. This file
asks a different question — is what the emitter writes *structurally*
sound — so :func:`_parse` sets that family aside and everything else
still has to be empty. The family's own findings are asserted exactly,
per golden and per mode, in ``test_adopt_diagnostics.py``.
"""


def _parse(text: str, filename: str) -> list[object]:
    """Parse and validate *text*, returning every structural diagnostic.

    Every diagnostic the parser and the intra-module validator produce,
    less the :data:`DRAFT_DEBT_PREFIX` family — see that constant.
    """
    module, warnings = parse_s0ma_with_warnings(
        text, filename, mode=StrictnessMode.MIGRATION
    )
    errors = validate_module(
        module, mode=StrictnessMode.MIGRATION, filename=filename
    )
    return [
        diagnostic
        for diagnostic in (*warnings, *errors)
        if not diagnostic.code.startswith(DRAFT_DEBT_PREFIX)
    ]


def _bodies(text: str, filename: str) -> dict[str, str]:
    """Every declaration body the parser read back out of *text*."""
    module, _ = parse_s0ma_with_warnings(text, filename, mode=StrictnessMode.MIGRATION)
    bodies: dict[str, str] = {}
    for declaration in module.all_declarations:
        name = getattr(declaration, "name", None)
        body = getattr(declaration, "body", None)
        if name is not None and isinstance(body, str):
            bodies[name] = body
    return bodies


def _field(text: str, declaration: str, field: str) -> str:
    """The raw value written after ``<field>:`` inside one declaration."""
    lines = text.split("\n")
    start = next(
        index
        for index, line in enumerate(lines)
        if line.startswith((f"module {declaration}", f"nerve {declaration} ::"))
        or line.startswith((f"cell {declaration} ::", f"helper {declaration} ::"))
    )
    for line in lines[start + 1 :]:
        if line and not line.startswith(" "):
            break
        if line.startswith(f"    {field}:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"{declaration} has no {field}: field in\n{text}")


# ---------------------------------------------------------------------------
# T1 — the file the emitter writes
# ---------------------------------------------------------------------------


SIMPLE = '''"""A tiny module. It has a "quoted" word in its docstring.

A second paragraph nobody should ever see in the intent.
"""

MAX_ITEMS = 3


def keep(name: str) -> str:
    """Keep one name."""
    return name.strip()


def _trim(name: str) -> str:
    return name.strip()
'''


def test_the_draft_opens_with_the_provenance_comment(tmp_path: Path) -> None:
    """Which bytes this draft came from, as the first line of the file."""
    draft = _draft(tmp_path, "sample.py", SIMPLE)
    first = emit_draft(draft).split("\n", 1)[0]

    assert first == f"{PROVENANCE_PREFIX}sample.py@{draft.source_hash}"
    assert first.startswith("# "), "provenance rides as a comment, not a field"


def test_the_header_authors_all_six_requires_family_fields(tmp_path: Path) -> None:
    """F-D1-4: omitting even one is an error at parse time, in every mode."""
    text = emit_draft(_draft(tmp_path, "sample.py", SIMPLE))

    for field in (
        "requires",
        "uses",
        "soft_requires",
        "runtime_only_requires",
        "deferred_requires",
        "exports_helpers",
    ):
        assert f"\n    {field}: " in text, f"the header omits {field}:"


def test_the_header_fields_are_written_in_one_fixed_order(tmp_path: Path) -> None:
    """The order the house's own modules use, so drafts read like them."""
    text = emit_draft(_draft(tmp_path, "sample.py", SIMPLE))
    header = text.split("\nmodule sample\n", 1)[1].split("\ncell ", 1)[0]
    written = [
        line.split(":", 1)[0].strip()
        for line in header.split("\n")
        if line.startswith("    ") and ":" in line
    ]

    assert written == [
        "layer",
        "version",
        "intent",
        "exports",
        "requires",
        "uses",
        "soft_requires",
        "runtime_only_requires",
        "deferred_requires",
        "exports_helpers",
    ]


def test_a_draft_opens_at_version_0_1_0(tmp_path: Path) -> None:
    """A draft is a work in progress and says so in its version."""
    text = emit_draft(_draft(tmp_path, "sample.py", SIMPLE))
    assert _field(text, "sample", "version") == DRAFT_VERSION


def test_declarations_keep_the_order_they_had_in_the_python(tmp_path: Path) -> None:
    """A draft should read like the file it came from."""
    text = emit_draft(_draft(tmp_path, "sample.py", SIMPLE))
    order = re.findall(r"^(?:nerve|cell|helper) (\w+) ::", text, flags=re.MULTILINE)

    assert order == ["MAX_ITEMS", "keep", "_trim"]


def test_a_public_name_is_public_and_a_private_one_is_internal(
    tmp_path: Path,
) -> None:
    """Visibility is the Python convention read back, not a judgement."""
    text = emit_draft(_draft(tmp_path, "sample.py", SIMPLE))

    assert _field(text, "keep", "visibility") == "PUBLIC"
    assert _field(text, "MAX_ITEMS", "visibility") == "PUBLIC"
    assert "helper _trim :: " in text


def test_a_helper_named_in_dunder_all_is_not_quietly_exported(
    tmp_path: Path,
) -> None:
    """The harvester's ruling reaches the file: no export, and a note saying so.

    Helpers are private to their module. The draft leaves the name out
    of both export fields and carries the harvester's sentence telling
    the author to promote it to a nerve if it really is public — rather
    than writing it into ``exports_helpers:`` and overruling that.
    """
    source = '__all__ = ["_trim"]\n\n\ndef _trim(name: str) -> str:\n    return name\n'
    draft = _draft(tmp_path, "sample.py", source)
    text = emit_draft(draft)

    assert _field(text, "sample", "exports") == "none"
    assert _field(text, "sample", "exports_helpers") == "none"
    assert "promote one to a nerve" in text
    assert _parse(text, "sample.s0ma") == []


def test_a_long_list_takes_the_block_form(tmp_path: Path) -> None:
    """Fine on one line up to four entries; past that it is unreadable."""
    names = [f"name_{index}" for index in range(6)]
    source = "__all__ = [" + ", ".join(f'"{name}"' for name in names) + "]\n\n"
    source += "".join(f"\n\ndef {name}() -> None:\n    pass\n" for name in names)
    text = emit_draft(_draft(tmp_path, "sample.py", source))

    assert "\n    exports:\n      - name_0\n" in text
    assert _parse(text, "sample.s0ma") == []


# ---------------------------------------------------------------------------
# T1 — placeholders: meaning is asked for, never invented
# ---------------------------------------------------------------------------


def test_every_un_authored_meaning_field_carries_the_marker(tmp_path: Path) -> None:
    """Module intent, nerve contract, cell schema, helper intent — all asked."""
    text = emit_draft(_draft(tmp_path, "sample.py", SIMPLE))

    assert _field(text, "sample", "intent").startswith(f'"{DRAFT_INTENT_MARKER}')
    assert _field(text, "keep", "intent").startswith(f'"{DRAFT_INTENT_MARKER}')
    assert _field(text, "keep", "expects").startswith(f'"{DRAFT_INTENT_MARKER}')
    assert _field(text, "keep", "guarantees").startswith(f'"{DRAFT_INTENT_MARKER}')
    assert _field(text, "keep", "forbids").startswith(f'"{DRAFT_INTENT_MARKER}')
    assert _field(text, "MAX_ITEMS", "schema").startswith(f'"{DRAFT_INTENT_MARKER}')
    assert _field(text, "_trim", "intent").startswith(f'"{DRAFT_INTENT_MARKER}')


def test_each_placeholder_says_what_to_write_not_what_is_missing() -> None:
    """Written for somebody finishing a draft, not for a compiler."""
    for (form, field), sentence in PLACEHOLDERS.items():
        assert sentence.startswith("say "), (form, field, sentence)
        assert '"' not in sentence, "a .s0ma quoted string has no escape for a quote"
        assert "\n" not in sentence, "a field value is one line"
        assert len(sentence) > 30, (form, field)


def test_the_module_docstring_is_offered_but_never_promoted(tmp_path: Path) -> None:
    """Prose about a file is not a declared intent — it is a suggestion."""
    text = emit_draft(_draft(tmp_path, "sample.py", SIMPLE))
    intent = _field(text, "sample", "intent")

    assert intent.startswith(f'"{DRAFT_INTENT_MARKER}')
    assert "A tiny module. It has a 'quoted' word in its docstring." in intent
    assert "second paragraph" not in intent, "only the first line is offered"


def test_a_module_with_no_docstring_gets_no_suggestion(tmp_path: Path) -> None:
    text = emit_draft(_draft(tmp_path, "sample.py", "VALUE = 1\n"))

    assert "The Python file's docstring began" not in text


def test_a_real_authored_intent_is_carried_over_word_for_word(
    tmp_path: Path,
) -> None:
    """An intent somebody wrote is real and is never replaced."""
    source = (
        "from s0ma import component\n"
        "from s0ma.enums import ComponentKind, S0maLayer\n\n\n"
        "@component(\n"
        '    name="keep",\n'
        "    kind=ComponentKind.FUNCTION,\n"
        "    layer=S0maLayer.APPLICATION,\n"
        '    intent="Keeps one name, trimmed of the spaces a form leaves behind.",\n'
        ")\n"
        "def keep(name: str) -> str:\n"
        "    return name.strip()\n"
    )
    draft = _draft(tmp_path, "sample.py", source)
    text = emit_draft(draft)

    assert _field(text, "keep", "intent") == (
        '"Keeps one name, trimmed of the spaces a form leaves behind."'
    )
    assert DRAFT_INTENT_MARKER not in _field(text, "keep", "intent")
    assert "@component" not in text, "the registration moved into the header"
    assert _parse(text, "sample.s0ma") == []


def test_a_lifted_forbids_is_carried_over_and_quoted(tmp_path: Path) -> None:
    """A prohibition the registration already declared is never asked for again."""
    source = (
        "from s0ma import component\n"
        "from s0ma.enums import ComponentKind, S0maLayer\n"
        "from s0ma.models import Contract\n\n\n"
        "@component(\n"
        '    name="keep",\n'
        "    kind=ComponentKind.FUNCTION,\n"
        "    layer=S0maLayer.APPLICATION,\n"
        "    contracts=Contract(\n"
        '        forbids=["Never change the name beyond trimming its outer spaces."],\n'
        "    ),\n"
        ")\n"
        "def keep(name: str) -> str:\n"
        "    return name.strip()\n"
    )
    text = emit_draft(_draft(tmp_path, "sample.py", source))

    assert _field(text, "keep", "forbids") == (
        '"Never change the name beyond trimming its outer spaces."'
    )
    assert _field(text, "keep", "guarantees").startswith(f'"{DRAFT_INTENT_MARKER}')
    assert _parse(text, "sample.s0ma") == []


def test_a_quote_in_a_lifted_value_becomes_a_single_quote(tmp_path: Path) -> None:
    """A ``.s0ma`` quoted string runs to the next ``"``; there is no escape."""
    source = '"""A docstring with a "quoted" word and\na second line."""\n\nVALUE = 1\n'
    text = emit_draft(_draft(tmp_path, "sample.py", source))
    intent = _field(text, "sample", "intent")

    assert intent.count('"') == 2, "only the opening and closing quote"
    assert "'quoted'" in intent
    assert _parse(text, "sample.s0ma") == []


# ---------------------------------------------------------------------------
# T1 — bodies are moved, never rewritten
# ---------------------------------------------------------------------------


HOSTILE_BODY = (
    '# A comment block sitting directly above the definition,\n'
    '#   indented oddly on purpose.\n'
    'def render() -> str:\n'
    '    """Render it.\n'
    '\n'
    '    Notes\n'
    '    -----\n'
    '    A markdown rule follows, at the very left margin:\n'
    '    """\n'
    '    template = """\n'
    '---\n'
    '   \n'
    'module fake\n'
    'nerve g :: DOMAIN\n'
    'cell C :: DOMAIN\n'
    '"""\n'
    '    spaced   =    1   \n'
    '\n'
    '\n'
    '    return template * spaced\n'
)


def test_a_body_survives_the_round_trip_byte_for_byte(tmp_path: Path) -> None:
    """Comments, odd spacing, a ``---`` line and fake headers all survive.

    The uniform body indent is what makes this safe: the declaration
    splitter ends a body only at a line that is unindented *and* matches
    a declaration header, so an indented ``---`` or ``module fake`` is
    carried through rather than cutting the declaration short. The one
    thing the parser does take is a run of blank lines at the very end
    of a body, which it strips before the body is stored.
    """
    draft = _draft(tmp_path, "sample.py", HOSTILE_BODY)
    text = emit_draft(draft)
    authored = draft.declarations[0].body

    read_back = _bodies(text, "sample.s0ma")["render"]

    assert read_back == authored.rstrip("\n")
    assert "\n    ---\n" in text, "the body's own --- line is still in the file"
    assert text.count("\n---\n") == 0, "no --- of the body's sits at column 0"


def test_the_only_change_to_a_body_line_is_the_body_indent(tmp_path: Path) -> None:
    """Every line shifts right by exactly four spaces; empty lines stay empty."""
    draft = _draft(tmp_path, "sample.py", HOSTILE_BODY)
    text = emit_draft(draft)
    emitted = text.split("\n    ---\n", 1)[1].rstrip("\n").split("\n")
    authored = draft.declarations[0].body.rstrip("\n").split("\n")

    assert len(emitted) == len(authored)
    for written, original in zip(emitted, authored, strict=True):
        assert written == (f"    {original}" if original else "")


def test_a_body_is_never_reindented_or_reformatted(tmp_path: Path) -> None:
    """``ast.unparse`` would tidy this; the emitter must not."""
    source = "def f(  a,b ):\n" "    # keep me\n" "    return (  a  +b )\n"
    draft = _draft(tmp_path, "sample.py", source)
    text = emit_draft(draft)

    assert "    def f(  a,b ):" in text
    assert "        return (  a  +b )" in text
    assert _bodies(text, "sample.s0ma")["f"] == source.rstrip("\n")


# ---------------------------------------------------------------------------
# T2 — the layer
# ---------------------------------------------------------------------------


def test_a_proposed_layer_is_used_and_asks_for_nothing(tmp_path: Path) -> None:
    text = emit_draft(
        _draft(tmp_path, "sample.py", SIMPLE), proposed_layer="INFRASTRUCTURE"
    )

    assert _field(text, "sample", "layer") == "INFRASTRUCTURE"
    assert "choose this module's layer" not in text


def test_a_layer_on_the_draft_is_used_when_no_proposal_is_given(
    tmp_path: Path,
) -> None:
    draft = _draft(tmp_path, "sample.py", SIMPLE, layer="PRESENTATION")
    text = emit_draft(draft)

    assert _field(text, "sample", "layer") == "PRESENTATION"
    assert "choose this module's layer" not in text


def test_with_no_layer_anywhere_the_placeholder_names_the_candidates(
    tmp_path: Path,
) -> None:
    """A guess dressed up as an answer is the thing to avoid here."""
    text = emit_draft(
        _draft(tmp_path, "sample.py", SIMPLE),
        layer_candidates=("APPLICATION", "INFRASTRUCTURE"),
    )
    intent = _field(text, "sample", "intent")

    assert _field(text, "sample", "layer") == FALLBACK_LAYER
    assert "choose this module's layer" in intent
    assert "APPLICATION or INFRASTRUCTURE" in intent
    assert "sits at exactly one layer" in intent


def test_with_no_candidates_the_placeholder_names_all_four_layers(
    tmp_path: Path,
) -> None:
    intent = _field(emit_draft(_draft(tmp_path, "sample.py", SIMPLE)), "sample", "intent")

    assert "DOMAIN, APPLICATION, INFRASTRUCTURE or PRESENTATION" in intent


def test_every_declaration_shares_the_module_layer(tmp_path: Path) -> None:
    """One layer per module is a language rule (``LAYER_MISMATCH``)."""
    text = emit_draft(_draft(tmp_path, "sample.py", SIMPLE), proposed_layer="APPLICATION")
    layers = re.findall(r"^(?:nerve|cell|helper) \w+ :: (\w+)$", text, flags=re.MULTILINE)

    assert set(layers) == {"APPLICATION"}
    assert _parse(text, "sample.s0ma") == []


# ---------------------------------------------------------------------------
# The un-placeable-source carrier
# ---------------------------------------------------------------------------


UNPLACEABLE = (
    "import logging\n"
    "\n"
    "logger = logging.getLogger(__name__)\n"
    "\n"
    "\n"
    "def use() -> None:\n"
    "    logger.info('hello')\n"
)


def test_unplaced_source_rides_in_the_carrier_the_harvester_defined(
    tmp_path: Path,
) -> None:
    """The emitter reads the carrier's shape from harvest, never re-derives it."""
    draft = _draft(tmp_path, "sample.py", UNPLACEABLE)
    text = emit_draft(draft)
    block = draft.unplaced[0]
    name = f"{UNPLACED_CELL_PREFIX}{block.start_line:04d}_{block.end_line:04d}"

    assert f"cell {name} :: " in text
    assert _field(text, name, "kind") == "CONSTANT"
    assert _field(text, name, "visibility") == "INTERNAL"
    assert _field(text, name, "intent") == f'"{UNPLACED_CELL_INTENT}"'
    assert DRAFT_UNPLACED_MARKER in _field(text, name, "schema")
    assert f"    {name} = {render_unplaced_value(block.text)}".split("\n")[0] in text
    assert _parse(text, "sample.s0ma") == []


def test_the_carrier_intent_is_an_instruction_not_a_placeholder(
    tmp_path: Path,
) -> None:
    """Two kinds of debt, two markers: un-written meaning and un-placed code."""
    text = emit_draft(_draft(tmp_path, "sample.py", UNPLACEABLE))

    assert DRAFT_INTENT_MARKER not in _field(
        text, f"{UNPLACED_CELL_PREFIX}0003_0003", "intent"
    )


def test_a_carrier_sits_where_its_text_sat_in_the_python(tmp_path: Path) -> None:
    """Declarations and carriers are interleaved in source order."""
    text = emit_draft(_draft(tmp_path, "sample.py", UNPLACEABLE))
    order = re.findall(r"^(?:nerve|cell|helper) (\w+) ::", text, flags=re.MULTILINE)

    assert order == [f"{UNPLACED_CELL_PREFIX}0003_0003", "use"]


# ---------------------------------------------------------------------------
# Cell kinds reconciled against the body's shape
# ---------------------------------------------------------------------------


def test_a_protocol_becomes_a_model_cell_and_says_why(tmp_path: Path) -> None:
    """A TYPE cell must hold a type alias; a ``Protocol`` is a class."""
    source = (
        "from typing import Protocol\n\n\n"
        "class Sender(Protocol):\n"
        "    def send(self, text: str) -> None:\n"
        "        ...\n"
    )
    draft = _draft(tmp_path, "sample.py", source)
    assert draft.declarations[0].kind == "TYPE", "the harvester's hint under test"

    text = emit_draft(draft)

    assert _field(text, "Sender", "kind") == "MODEL"
    assert "may not hold a class" in _field(text, "Sender", "intent")
    assert _parse(text, "sample.s0ma") == []


def test_the_kind_is_left_alone_when_the_body_agrees_with_it(
    tmp_path: Path,
) -> None:
    source = "class Broken(Exception):\n    pass\n"
    text = emit_draft(_draft(tmp_path, "sample.py", source))

    assert _field(text, "Broken", "kind") == "EXCEPTION"
    assert "may not hold" not in text


# ---------------------------------------------------------------------------
# Purity, determinism and text discipline
# ---------------------------------------------------------------------------


def test_the_same_draft_always_gives_the_same_bytes(tmp_path: Path) -> None:
    draft = _draft(tmp_path, "sample.py", SIMPLE)

    assert emit_draft(draft) == emit_draft(draft)


def test_the_text_is_lf_only_and_ends_with_exactly_one_newline(
    tmp_path: Path,
) -> None:
    text = emit_draft(_draft(tmp_path, "sample.py", SIMPLE))

    assert "\r" not in text
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_no_golden_carries_an_absolute_path_or_a_backslash() -> None:
    """Every recorded path is project-relative and forward-slashed."""
    for key in _golden_keys():
        text = _golden_text(key)
        assert "/Users/" not in text, key
        assert "\\" not in text.split("\n")[0], key
        assert "\r" not in text, key


def test_emitting_reads_the_draft_and_writes_nothing(tmp_path: Path) -> None:
    """``emit_draft`` is a pure function of its argument (rule R-2)."""
    draft = _draft(tmp_path, "sample.py", SIMPLE)
    before = sorted(path.name for path in tmp_path.rglob("*"))

    emit_draft(draft)

    assert sorted(path.name for path in tmp_path.rglob("*")) == before


# ---------------------------------------------------------------------------
# T3 — the goldens
# ---------------------------------------------------------------------------


def test_there_is_one_golden_for_every_draftable_fixture_module() -> None:
    """A new fixture module cannot arrive without a golden to go with it."""
    on_disk = sorted(
        path.relative_to(_GOLDEN_DIR).with_suffix("").as_posix()
        for path in _GOLDEN_DIR.rglob("*.s0ma")
    )

    assert _golden_keys() == sorted(EXPECTED_PLACEHOLDERS)
    assert on_disk == sorted(EXPECTED_PLACEHOLDERS)


@pytest.mark.parametrize("key", sorted(EXPECTED_PLACEHOLDERS))
def test_the_golden_matches_the_draft_the_emitter_writes_today(key: str) -> None:
    """Byte for byte. Set S0MA_UPDATE_ADOPT_GOLDENS=1 to rewrite them."""
    emitted = _emit_fixture(key)
    path = _GOLDEN_DIR / f"{key}.s0ma"

    if os.environ.get(_UPDATE_ENV):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(emitted, encoding="utf-8", newline="\n")

    assert _golden_text(key) == emitted, (
        f"the draft for {key} has changed. Read the diff; if the new draft is "
        f"right, regenerate with {_UPDATE_ENV}=1."
    )


@pytest.mark.parametrize("key", sorted(EXPECTED_PLACEHOLDERS))
def test_every_golden_parses(key: str) -> None:
    """The real parser and the real intra-module validator, on every golden.

    Parsing raises on anything of error severity, so reaching the end of
    this test is the proof that no golden carries a syntax-level fault.
    The warnings that remain are named in
    :data:`GOLDEN_WARNING_CODES` with the reason each one is expected.
    """
    filename = (_GOLDEN_DIR / f"{key}.s0ma").as_posix()
    diagnostics = _parse(_golden_text(key), filename)

    unexpected = sorted(
        f"{d.severity}/{d.code}"
        for d in diagnostics
        if d.code not in GOLDEN_WARNING_CODES
    )
    assert unexpected == [], f"{key}: {unexpected}"


@pytest.mark.parametrize("key", sorted(EXPECTED_PLACEHOLDERS))
def test_every_golden_carries_exactly_the_debt_it_should(key: str) -> None:
    """The precise target D3's ``ADOPT_PLACEHOLDER_INTENT`` has to hit."""
    text = _golden_text(key)

    assert text.count(DRAFT_INTENT_MARKER) == EXPECTED_PLACEHOLDERS[key]


def test_the_goldens_carry_the_unplaced_debt_the_fixtures_hold() -> None:
    """Exactly four fixture modules hold text no declaration can take.

    A ``__main__`` guard, a module-level logger, an ``if TYPE_CHECKING:``
    block that reaches a first-party module, and a script's own entry
    point. The fifth candidate — ``models``' ``TYPE_CHECKING`` block —
    is not here because every name in it is standard library, which D1b
    promotes into ``requires:``; a stdlib typing import cannot close a
    first-party cycle, so there is nothing to decide.
    """
    carrying = sorted(
        key for key in _golden_keys() if DRAFT_UNPLACED_MARKER in _golden_text(key)
    )

    assert carrying == [
        "layered_app/__main__",
        "layered_app/notifications",
        "layered_app/storage",
        "tiny_app/run",
    ]


# ---------------------------------------------------------------------------
# T4 — the round trip: fill the placeholders, then check the project
# ---------------------------------------------------------------------------


FILLED_VALUES = {
    "intent": "This carries one named responsibility of the lending service.",
    "expects": "Every argument already holds the type the signature names.",
    "guarantees": "Returns what the signature names, or raises a declared error.",
    "schema": "The fields this holds, each one named and typed as the body declares.",
}
"""What the round trip writes over each placeholder — a real sentence.

Ten characters is the floor an authored intent has to clear; these are
well past it and read like something a person would write, because the
point of the round trip is to prove that a *finished* draft checks
clean, not that a longer placeholder does.
"""

_PLACEHOLDER_LINE = re.compile(r'^(\s*)(\w+): "FIXME\(adopt\): .*"$')


FILLED_STATES = {"forbids": "none"}
"""Fields the round trip answers with a state rather than a sentence.

``none`` is a real answer: nothing is ruled out. It is the one answer
the round trip can give honestly for every function it finishes, where
one prohibition written over all of them would be untrue of most.
"""


def fill_placeholders(text: str, *, layer: str | None = None) -> str:
    """Replace every ``FIXME(adopt):`` value with a real sentence.

    A placeholder always occupies one whole field line, because every
    quoted value the emitter writes is collapsed onto one line, so a
    line-by-line substitution is exact. *layer*, when given, is written
    over the module's layer and over every declaration's, which is what
    finishing a draft whose layer was the fallback amounts to.
    """
    lines: list[str] = []
    for line in text.split("\n"):
        match = _PLACEHOLDER_LINE.match(line)
        if match:
            indent, field = match.group(1), match.group(2)
            if field in FILLED_STATES:
                lines.append(f"{indent}{field}: {FILLED_STATES[field]}")
                continue
            lines.append(f'{indent}{field}: "{FILLED_VALUES[field]}"')
            continue
        if layer is not None:
            line = re.sub(r"^(    layer: )\w+$", rf"\g<1>{layer}", line)
            line = re.sub(
                r"^((?:nerve|cell|helper) \w+ :: )\w+$", rf"\g<1>{layer}", line
            )
        lines.append(line)
    return "\n".join(lines)


def _check_project(tmp_path: Path, stem: str, text: str, capsys) -> list[str]:
    """Write *text* as the only module of a project and check it.

    The project-level check, through the same programmatic entry point
    the other project tests use, in migration mode — the mode a retrofit
    runs in.
    """
    root = tmp_path / stem
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "bookshelf"\nversion = "0.1.0"\n\n'
        '[tool.s0ma]\nsource_roots = ["src"]\nmode = "migration"\n',
        encoding="utf-8",
        newline="\n",
    )
    (root / "src" / f"{stem}.s0ma").write_text(text, encoding="utf-8", newline="\n")

    S0maCLI().run([
        "--project-root", str(root),
        "check", str(root),
        "--mode", "migration",
        "--format", "json",
    ])
    report = json.loads(capsys.readouterr().out)
    return sorted(
        entry["code"]
        for group in ("errors", "warnings")
        for record in report["by_file"]
        for entry in record[group]
    )


@pytest.mark.parametrize("stem", ["errors", "models", "config"])
def test_a_finished_draft_checks_clean(tmp_path: Path, stem: str, capsys) -> None:
    """Draft a real module, write the meaning in, and the project is clean.

    This is the milestone's headline: what the emitter writes is not
    merely parseable, it is *finishable*. Nothing about the draft — not
    the field order, not the six ``none``s, not a body moved across
    verbatim — stands between an author who has written the meaning and
    a clean ``s0ma check``.
    """
    text = fill_placeholders(_emit_fixture(f"layered_app/{stem}"), layer="DOMAIN")

    assert DRAFT_INTENT_MARKER not in text
    assert _check_project(tmp_path, stem, text, capsys) == []


def test_a_finished_draft_still_carries_its_unplaced_code(
    tmp_path: Path, capsys
) -> None:
    """``bookshelf.notifications`` keeps a carrier, because that is its job.

    Its ``if TYPE_CHECKING:`` block reaches a first-party module, so it
    stays un-placeable: moving that import to load time can close a
    cycle the guard was holding open. Writing every intent does not
    discharge that debt — the carrier is still there, still named, still
    marked. What is not here yet is the refusal.
    ``ADOPT_UNPLACED_CODE`` arrives with D3; until then a project with a
    carrier in it checks clean, and this test says so out loud so the
    gap is a recorded fact rather than a surprise. When D3 lands, the
    ``ADOPT_``-prefixed codes it raises are the ones filtered here.
    """
    text = fill_placeholders(_emit_fixture("layered_app/notifications"), layer="DOMAIN")

    assert DRAFT_INTENT_MARKER not in text
    assert DRAFT_UNPLACED_MARKER in text
    assert UNPLACED_CELL_PREFIX in text

    codes = _check_project(tmp_path, "notifications", text, capsys)

    assert [code for code in codes if not code.startswith("ADOPT_")] == []
