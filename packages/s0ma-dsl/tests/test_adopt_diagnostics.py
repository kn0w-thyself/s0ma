"""D3 — a draft must never build or score as though it were finished.

``s0ma adopt draft`` (D4) turns an existing Python module into a DRAFT
``.s0ma`` file. A draft carries two kinds of unfinished business, and
until this milestone neither one stopped anything: a draft full of
un-authored meaning checked clean, and so did one still carrying source
the harvester could not place (friction ``F-D2-4``, recorded at the D2
gate as an asserted gap rather than an assumed one).

This module is the proof that the gap is closed:

``ADOPT_PLACEHOLDER_INTENT``
    An authored text field still holds the ``FIXME(adopt):`` marker —
    meaning nobody has written yet. One finding per field.

``ADOPT_UNPLACED_CODE``
    A declaration is one of the draft's quarantine cells: source text
    kept verbatim, as a string, because it belonged to no declaration.
    One finding per declaration.

Both are **error in every strictness mode**, migration included
(retrofit ruling R-5), and every mode is enumerated from the config
rather than listed here, so a fifth mode arrives as a red test.

The headline tests run the **real checker** over a real project built
in ``tmp_path``, the way ``test_adopt_draft_emit.py`` builds one, and
assert the exact set of findings on the two golden drafts:
``bookshelf.errors`` (placeholders only) and ``bookshelf.notifications``
(placeholders *and* the carrier). The rest are hand-written modules,
each as small as the thing it proves.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from s0ma_dsl.adopt.draft_emit import PLACEHOLDERS
from s0ma_dsl.adopt.harvest import UNPLACED_CELL_PREFIX
from s0ma_dsl.adopt.model import DRAFT_INTENT_MARKER, DRAFT_UNPLACED_MARKER
from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.config import (
    ERROR_CODE_DESCRIPTIONS,
    SEVERITY_MATRIX,
    StrictnessMode,
    get_severity,
)

PLACEHOLDER_CODE = "ADOPT_PLACEHOLDER_INTENT"
UNPLACED_CODE = "ADOPT_UNPLACED_CODE"

_TESTS_DIR = Path(__file__).resolve().parent
_INVALID_DIR = _TESTS_DIR / "fixtures" / "invalid"
_GOLDEN_DRAFTS = _TESTS_DIR / "fixtures" / "brownfield" / "_golden" / "drafts"

FIXTURES: dict[str, str] = {
    PLACEHOLDER_CODE: "adopt_placeholder_intent.s0ma",
    UNPLACED_CODE: "adopt_unplaced_code.s0ma",
}
"""The deliberately failing fixture for each code this milestone adds.

The repository's convention for a DSL diagnostic: one minimal module
under ``tests/fixtures/invalid/``, named after the code it trips, and
named by the suite that fires it (``test_error_ux.py`` and
``test_golden.py`` keep their own such tables). The docs-model negative
inventory audits a different universe — self-naming ``DOC_*`` constants
— and neither sees nor wants these two, which is what plan §5.4
anticipated when it said the bijection does not apply to the
``ADOPT_`` family.
"""


# ---------------------------------------------------------------------------
# Running the real checker
# ---------------------------------------------------------------------------


def check_project(
    tmp_path: Path, stem: str, text: str, capsys, *, mode: str = "migration"
) -> list[dict[str, object]]:
    """Write *text* as the only module of a project and check it for real.

    The same shape ``test_adopt_draft_emit.py`` uses: a throwaway project
    with one source root, checked through the CLI's own JSON output, so
    what this module asserts is what a person at a terminal would see and
    not a validator called in isolation.
    """
    root = tmp_path / f"{stem}_{mode}"
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "bookshelf"\nversion = "0.1.0"\n\n'
        f'[tool.s0ma]\nsource_roots = ["src"]\nmode = "{mode}"\n',
        encoding="utf-8",
        newline="\n",
    )
    (root / "src" / f"{stem}.s0ma").write_text(text, encoding="utf-8", newline="\n")

    S0maCLI().run([
        "--project-root", str(root),
        "check", str(root),
        "--mode", mode,
        "--format", "json",
    ])
    report = json.loads(capsys.readouterr().out)
    return [
        dict(entry, severity=group[:-1])
        for record in report["by_file"]
        for group in ("errors", "warnings")
        for entry in record[group]
    ]


def codes_of(findings: list[dict[str, object]]) -> list[str]:
    """Just the codes, in the order the checker reported them."""
    return [str(finding["code"]) for finding in findings]


def adopt_findings(findings: list[dict[str, object]]) -> list[dict[str, object]]:
    """Only this family's findings.

    Release mode runs release-only gates of its own —
    ``MISSING_TEST_COVERAGE`` and ``MISSING_PUBLIC_DOC_REF`` fire on any
    module that has neither a test nor a public doc-ref — and those are
    somebody else's rules about a finished module, not evidence about
    these two. A per-mode test that demanded an empty remainder would be
    asserting the release gate's contents, so it filters instead.
    """
    return [
        finding for finding in findings if str(finding["code"]).startswith("ADOPT_")
    ]


def emitter_marker_counts() -> dict[str, int]:
    """``EXPECTED_PLACEHOLDERS`` from D2's suite, parsed and not imported.

    The house idiom for reading one test module's table from another
    (``test_docs_negative_inventory.py`` reads both negative batteries
    this way): two independent readings can be compared where one shared
    import would only be one reading twice — and a test module is not an
    importable module here in any case.
    """
    source = (_TESTS_DIR / "test_adopt_draft_emit.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="test_adopt_draft_emit.py")
    for node in tree.body:
        targets = (
            [node.target]
            if isinstance(node, ast.AnnAssign)
            else node.targets
            if isinstance(node, ast.Assign)
            else []
        )
        if any(
            isinstance(target, ast.Name) and target.id == "EXPECTED_PLACEHOLDERS"
            for target in targets
        ) and node.value is not None:
            return dict(ast.literal_eval(node.value))
    raise AssertionError(
        "test_adopt_draft_emit.py no longer defines a module-level "
        "EXPECTED_PLACEHOLDERS. That table is the emitter's own count of "
        "the markers it writes, and this module holds its findings against "
        "it; if the table has moved, this reader moves with it rather than "
        "quietly finding nothing."
    )


def golden(name: str) -> str:
    """One golden draft, read as bytes so its line endings stay visible."""
    return (_GOLDEN_DRAFTS / f"{name}.s0ma").read_bytes().decode("utf-8")


def fixture(code: str) -> str:
    """The deliberately failing fixture registered for *code*."""
    return (_INVALID_DIR / FIXTURES[code]).read_bytes().decode("utf-8")


# ---------------------------------------------------------------------------
# Hand-written modules, each as small as the thing it proves
# ---------------------------------------------------------------------------


def module_text(*, intent: str, declarations: str = "", exports: str = "[]") -> str:
    """A one-module ``.s0ma`` file with *declarations* appended."""
    return (
        "module sample\n"
        "    layer: DOMAIN\n"
        "    version: 1.0.0\n"
        f'    intent: "{intent}"\n'
        f"    exports: {exports}\n"
        "\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        f"{declarations}"
    )


def constant_cell(
    name: str,
    *,
    intent: str,
    schema: str,
    value: str = '"kept verbatim"',
    visibility: str = "INTERNAL",
    invariants: str | None = None,
) -> str:
    """One ``kind: CONSTANT`` cell, the shape the carrier takes.

    ``invariants`` is an authored text field the draft tool never writes,
    which is how a test reaches a field with no instruction of its own.
    """
    return (
        f"\ncell {name} :: DOMAIN\n"
        "    kind: CONSTANT\n"
        f"    visibility: {visibility}\n"
        f'    intent: "{intent}"\n'
        f'    schema: "{schema}"\n'
        + (
            "    invariants: none\n"
            if invariants is None
            else f'    invariants: "{invariants}"\n'
        )
        + "    covered_by: none\n"
        "    ---\n"
        f"    {name} = {value}\n"
    )


def function_nerve(
    name: str, *, intent: str, expects: str, guarantees: str
) -> str:
    """One ``kind: FUNCTION`` nerve — the form with three authored fields."""
    return (
        f"\nnerve {name} :: DOMAIN\n"
        "    kind: FUNCTION\n"
        "    visibility: PUBLIC\n"
        f'    intent: "{intent}"\n'
        f'    expects: "{expects}"\n'
        f'    guarantees: "{guarantees}"\n'
        "    forbids: none\n"
        "    evaluates_at: FUNCTION_BOUNDARY\n"
        "    provides: none\n"
        "    returns: none\n"
        "    raises: none\n"
        "    interface: none\n"
        "    latency_ms: none\n"
        "    depends_on: none\n"
        "    internal: none\n"
        "    expected_exceptions: none\n"
        "    consumes_via_dict: none\n"
        "    declares_attributes: none\n"
        "    covered_by: none\n"
        "    ---\n"
        f"    def {name}() -> int:\n"
        '        """Return the one number this example exists to return."""\n'
        "        return 1\n"
    )


def module_helper(name: str, *, intent: str) -> str:
    """One module-private helper — the form with a single authored field."""
    return (
        f"\nhelper {name} :: DOMAIN\n"
        f'    intent: "{intent}"\n'
        "    ---\n"
        f"    def {name}() -> int:\n"
        "        return 1\n"
    )


GOOD_INTENT = "Holds the one value the example was written to hold."
GOOD_SCHEMA = "One string, fixed at authoring time and never rebound."


_PLACEHOLDER_LINE = re.compile(r'^(\s*)(\w+): "FIXME\(adopt\): .*"$')

_WRITTEN = {
    "intent": "This carries one named responsibility of the lending service.",
    "expects": "Every argument already holds the type the signature names.",
    "guarantees": "Returns what the signature names, or raises a declared error.",
    "schema": "The fields this holds, each one named and typed as the body declares.",
}

_WRITTEN_STATES = {"forbids": "none"}
"""Fields an author answers with a state rather than a sentence.

``none`` is a real answer: nothing is ruled out. It is the one answer
that is true of every function these drafts hold, where one prohibition
written over all of them would be untrue of most.
"""


def write_the_meaning(text: str) -> str:
    """Do to a draft what an author does: write over every placeholder.

    Every quoted value the emitter writes is collapsed onto one line, so
    a line-by-line substitution is exact. This is the *fixture-building*
    half of D2's ``fill_placeholders`` — the layer rewriting is left out
    because a golden's layer is already a concrete word, and a test
    helper that quietly did more than its name says would be the thing
    this suite exists to catch.
    """
    written: list[str] = []
    for line in text.split("\n"):
        match = _PLACEHOLDER_LINE.match(line)
        if match is None:
            written.append(line)
            continue
        indent, field = match.group(1), match.group(2)
        if field in _WRITTEN_STATES:
            written.append(f"{indent}{field}: {_WRITTEN_STATES[field]}")
            continue
        written.append(f'{indent}{field}: "{_WRITTEN[field]}"')
    return "\n".join(written)


def drop_declaration(text: str, name_prefix: str) -> str:
    """Delete whole declarations whose name starts with *name_prefix*.

    What a person does when they have placed a quarantine's contents and
    no longer need the cell. A declaration runs from its unindented
    header line to the next unindented line, which is the language's own
    block shape.
    """
    kept: list[str] = []
    dropping = False
    for line in text.split("\n"):
        starts_block = bool(line) and not line[0].isspace() and not line.startswith("#")
        if starts_block:
            dropping = f" {name_prefix}" in line
        if not dropping:
            kept.append(line)
    return "\n".join(kept)


# ---------------------------------------------------------------------------
# The registry: both codes exist, and are errors in every mode
# ---------------------------------------------------------------------------


class TestBothCodesAreRefusedInEveryMode:
    """R-5, proven per mode rather than asserted once.

    A draft is a work-in-progress artifact. Migration mode exists to let
    a half-converted project keep working — not to let un-written
    meaning or un-placed code pass for done — so neither code softens
    anywhere on the ladder.
    """

    @pytest.mark.parametrize("code", [PLACEHOLDER_CODE, UNPLACED_CODE])
    def test_the_code_is_registered(self, code: str) -> None:
        assert code in SEVERITY_MATRIX
        assert code in ERROR_CODE_DESCRIPTIONS

    @pytest.mark.parametrize("code", [PLACEHOLDER_CODE, UNPLACED_CODE])
    @pytest.mark.parametrize("mode", list(StrictnessMode), ids=lambda m: m.value)
    def test_the_severity_is_error_in_this_mode(
        self, code: str, mode: StrictnessMode
    ) -> None:
        """Every mode the config knows about, by name, including the
        most permissive one — enumerated from ``StrictnessMode`` so a
        fifth mode cannot land without this test naming it."""
        assert get_severity(code, mode) == "error"

    @pytest.mark.parametrize("mode", list(StrictnessMode), ids=lambda m: m.value)
    def test_the_checker_refuses_a_placeholder_in_this_mode(
        self, tmp_path: Path, capsys, mode: StrictnessMode
    ) -> None:
        findings = adopt_findings(check_project(
            tmp_path,
            "adopt_placeholder_intent",
            fixture(PLACEHOLDER_CODE),
            capsys,
            mode=mode.value,
        ))
        assert codes_of(findings) == [PLACEHOLDER_CODE]
        assert findings[0]["severity"] == "error"

    @pytest.mark.parametrize("mode", list(StrictnessMode), ids=lambda m: m.value)
    def test_the_checker_refuses_a_quarantine_in_this_mode(
        self, tmp_path: Path, capsys, mode: StrictnessMode
    ) -> None:
        findings = adopt_findings(check_project(
            tmp_path,
            "adopt_unplaced_code",
            fixture(UNPLACED_CODE),
            capsys,
            mode=mode.value,
        ))
        assert codes_of(findings) == [UNPLACED_CODE]
        assert findings[0]["severity"] == "error"


# ---------------------------------------------------------------------------
# The two golden drafts, checked for real
# ---------------------------------------------------------------------------


class TestTheGoldenDraftsFailWithExactlyTheseFindings:
    """The milestone's headline, on the drafts D2 actually emits.

    ``errors`` carries only un-authored meaning; ``notifications`` also
    carries the one quarantine left in the fixture corpus (its
    ``if TYPE_CHECKING:`` block reaches a first-party module, which is
    the case the carrier genuinely exists for — friction ``F-D2-3``).
    Both counts are asserted exactly: "at least one" would pass on a
    rule that fired once and stopped.
    """

    def test_errors_fails_with_placeholders_and_nothing_else(
        self, tmp_path: Path, capsys
    ) -> None:
        findings = check_project(
            tmp_path, "errors", golden("layered_app/errors"), capsys
        )

        assert codes_of(findings) == [PLACEHOLDER_CODE] * 21
        assert all(finding["severity"] == "error" for finding in findings)

    def test_notifications_fails_with_placeholders_and_its_one_quarantine(
        self, tmp_path: Path, capsys
    ) -> None:
        findings = check_project(
            tmp_path, "notifications", golden("layered_app/notifications"), capsys
        )

        counted = {
            code: codes_of(findings).count(code)
            for code in (PLACEHOLDER_CODE, UNPLACED_CODE)
        }
        assert counted == {PLACEHOLDER_CODE: 17, UNPLACED_CODE: 1}
        assert set(codes_of(findings)) == {PLACEHOLDER_CODE, UNPLACED_CODE}

    def test_the_counts_are_the_emitters_own_count_of_its_markers(self) -> None:
        """The numbers above are not two independent opinions.

        ``test_adopt_draft_emit.EXPECTED_PLACEHOLDERS`` counts the markers
        each golden carries; one finding per marker is the whole rule, so
        the two tables must agree. Read rather than imported side by side
        so that moving either one is visible here.
        """
        counts = emitter_marker_counts()

        assert counts["layered_app/errors"] == 21
        assert counts["layered_app/notifications"] == 17

    def test_every_golden_that_carries_a_marker_is_refused(
        self, tmp_path: Path, capsys
    ) -> None:
        """No golden with un-finished business in it checks clean.

        The generalisation of the two tests above over the whole golden
        corpus: whatever a draft carries, ``s0ma check`` says so.
        """
        for path in sorted(_GOLDEN_DRAFTS.rglob("*.s0ma")):
            text = path.read_bytes().decode("utf-8")
            findings = check_project(tmp_path, path.stem, text, capsys)
            codes = set(codes_of(findings))
            assert (DRAFT_INTENT_MARKER in text) == (PLACEHOLDER_CODE in codes), path
            assert (UNPLACED_CELL_PREFIX in text) == (UNPLACED_CODE in codes), path


# ---------------------------------------------------------------------------
# A finished module checks clean
# ---------------------------------------------------------------------------


class TestAFinishedModuleIsLeftAlone:
    """The other half of the promise: the refusal ends when the work does."""

    def test_a_module_with_neither_marker_is_clean(
        self, tmp_path: Path, capsys
    ) -> None:
        text = module_text(
            intent="Holds one finished constant and says so.",
            declarations=constant_cell(
                "SAMPLE_VALUE", intent=GOOD_INTENT, schema=GOOD_SCHEMA
            ),
        )

        assert check_project(tmp_path, "sample", text, capsys) == []

    def test_the_finished_draft_of_a_real_module_is_clean(
        self, tmp_path: Path, capsys
    ) -> None:
        """``bookshelf.errors``, with every placeholder written over.

        The same round trip D2 proved parseable, now proved *finishable*
        past the two new refusals: write the meaning and the module is
        simply a module.
        """
        text = write_the_meaning(golden("layered_app/errors"))

        assert DRAFT_INTENT_MARKER not in text
        assert check_project(tmp_path, "errors", text, capsys) == []

    def test_deleting_the_quarantine_ends_the_refusal(
        self, tmp_path: Path, capsys
    ) -> None:
        """The way out named in the message, walked.

        ``notifications`` finished *and* with its carrier removed — the
        author having placed those imports or decided they were not
        needed — checks clean. Nothing else about the draft stands in
        the way.
        """
        filled = write_the_meaning(golden("layered_app/notifications"))
        text = drop_declaration(filled, UNPLACED_CELL_PREFIX)

        assert text != filled, "the carrier moved; this test is about deleting it"
        assert UNPLACED_CELL_PREFIX not in text
        assert DRAFT_UNPLACED_MARKER not in text
        assert check_project(tmp_path, "notifications", text, capsys) == []


# ---------------------------------------------------------------------------
# What the placeholder rule does and does not catch
# ---------------------------------------------------------------------------


class TestThePlaceholderRuleCannotBeHalfSatisfied:
    """The marker anywhere in an authored field is a finding.

    No finished field has a reason to contain ``FIXME(adopt):`` — it is
    the draft tool's own marker, not a word of English — so "contains"
    costs nothing in false positives and catches the half-edit that
    "starts with" would let through.
    """

    def test_a_marker_left_mid_sentence_is_still_a_finding(
        self, tmp_path: Path, capsys
    ) -> None:
        text = module_text(
            intent="Holds one constant whose intent was edited, but not finished.",
            declarations=constant_cell(
                "SAMPLE_VALUE",
                intent=(
                    "Holds the retry ceiling. FIXME(adopt): and say who reads it."
                ),
                schema=GOOD_SCHEMA,
            ),
        )

        assert codes_of(check_project(tmp_path, "sample", text, capsys)) == [
            PLACEHOLDER_CODE
        ]

    def test_one_finding_per_field_not_per_declaration(
        self, tmp_path: Path, capsys
    ) -> None:
        text = module_text(
            intent="Holds one constant with two un-authored fields.",
            declarations=constant_cell(
                "SAMPLE_VALUE",
                intent=f"{DRAFT_INTENT_MARKER} say why this exists.",
                schema=f"{DRAFT_INTENT_MARKER} say what shape this has.",
            ),
        )

        findings = check_project(tmp_path, "sample", text, capsys)

        assert codes_of(findings) == [PLACEHOLDER_CODE, PLACEHOLDER_CODE]
        assert sorted(str(finding["context"]["field"]) for finding in findings) == [
            "intent",
            "schema",
        ]

    def test_the_module_header_is_covered_too(
        self, tmp_path: Path, capsys
    ) -> None:
        """A draft's module intent is a placeholder like any other."""
        text = module_text(
            intent=f"{DRAFT_INTENT_MARKER} say what this module is responsible for."
        )

        findings = check_project(tmp_path, "sample", text, capsys)

        assert codes_of(findings) == [PLACEHOLDER_CODE]
        assert findings[0]["context"]["declaration_type"] == "module"

    def test_a_body_that_mentions_the_marker_is_not_a_finding(
        self, tmp_path: Path, capsys
    ) -> None:
        """Bodies are code, carried across verbatim, and are never read.

        A retrofitted file whose own Python carries an ``FIXME(adopt):``
        comment would otherwise be refused for its source text rather
        than for anything left unwritten — and the quarantine cell's
        body is arbitrary source held as a string, which is the same
        hazard with the volume turned up.
        """
        text = module_text(
            intent="Holds one constant whose value mentions the marker.",
            declarations=constant_cell(
                "SAMPLE_VALUE",
                intent=GOOD_INTENT,
                schema=GOOD_SCHEMA,
                value=f'"# {DRAFT_INTENT_MARKER} written by a previous owner"',
            ),
        )

        assert check_project(tmp_path, "sample", text, capsys) == []

    def test_the_message_names_the_declaration_the_field_and_the_way_out(
        self, tmp_path: Path, capsys
    ) -> None:
        findings = check_project(
            tmp_path,
            "adopt_placeholder_intent",
            fixture(PLACEHOLDER_CODE),
            capsys,
        )
        message = str(findings[0]["message"])
        remediation = str(findings[0]["remediation"])

        assert "nerve 'drafted'" in message.lower()
        assert "`intent:`" in message
        assert "s0ma adopt draft" in message
        assert message.endswith(f"{PLACEHOLDERS['nerve', 'intent']}.")
        assert "s0ma check" in remediation
        assert "payload" not in (message + remediation).lower()


# ---------------------------------------------------------------------------
# G3c — the advice fits the field it is about
# ---------------------------------------------------------------------------


#: One module carrying an un-authored field of every kind the draft tool
#: writes, plus one it does not (``invariants:``). Built once and checked
#: once, because what is being asserted is that the seven findings differ
#: from each other — which a per-field module could not show.
_EVERY_FIELD = module_text(
    intent=f"{DRAFT_INTENT_MARKER} say what this module is responsible for.",
    exports="[drafted]",
    declarations=(
        function_nerve(
            "drafted",
            intent=f"{DRAFT_INTENT_MARKER} say what this function is for.",
            expects=f"{DRAFT_INTENT_MARKER} say what has to be true first.",
            guarantees=f"{DRAFT_INTENT_MARKER} say what the caller gets back.",
        )
        + constant_cell(
            "SAMPLE_VALUE",
            intent=f"{DRAFT_INTENT_MARKER} say why this exists.",
            schema=f"{DRAFT_INTENT_MARKER} say what shape this has.",
            invariants=f"{DRAFT_INTENT_MARKER} say what stays true of it.",
        )
        + module_helper(
            "_drafted_helper",
            intent=f"{DRAFT_INTENT_MARKER} say why this helper exists.",
        )
    ),
)


class TestTheAdviceFitsTheFieldItIsAbout:
    """G3c: one refusal covers every authored field, so it cannot answer one.

    The message used to close "for an intent, why this part exists and
    what would break without it" whatever field it had found the marker
    on. For a ``schema:`` that is the wrong question, and a person who
    took it at its word would write an intent into a field that wants a
    shape. The closing clause is now the field's own — read from the
    sentences ``s0ma adopt draft`` writes into the file, so the refusal
    and the placeholder it is about cannot say two different things.

    The diagnostic code does not move: this is the runtime message, not
    the registered description, and the ledger it sits in stays where it
    is.
    """

    @pytest.mark.parametrize(
        ("form", "field"),
        [
            ("module", "intent"),
            ("nerve", "intent"),
            ("nerve", "expects"),
            ("nerve", "guarantees"),
            ("cell", "intent"),
            ("cell", "schema"),
            ("helper", "intent"),
        ],
    )
    def test_the_message_closes_with_what_this_field_is_for(
        self, tmp_path: Path, capsys, form: str, field: str
    ) -> None:
        """Every field the emitter writes a sentence for gets that sentence."""
        message = _message_for(tmp_path, capsys, form, field)

        assert message.endswith(f"{PLACEHOLDERS[form, field]}.")

    def test_a_field_the_draft_tool_does_not_write_gets_the_true_thing(
        self, tmp_path: Path, capsys
    ) -> None:
        """``invariants:`` has no instruction of its own, and is not given one.

        The rule covers every authored text field, so it reaches fields
        the emitter never writes. Inventing advice for one would be the
        same fault in a new place; the message says the one thing that is
        true of every placeholder instead.
        """
        message = _message_for(tmp_path, capsys, "cell", "invariants")

        assert ("cell", "invariants") not in PLACEHOLDERS
        assert message.endswith("the placeholder text says what belongs there.")

    def test_eight_findings_carry_eight_different_answers(
        self, tmp_path: Path, capsys
    ) -> None:
        """The whole point: a reader of two findings reads two answers."""
        findings = _placeholder_findings(tmp_path, capsys)
        closings = {
            str(finding["message"]).rsplit("—", 1)[-1].strip() for finding in findings
        }

        assert len(findings) == 8, "seven fields the draft tool writes, and one it does not"
        assert len(closings) == 8, "no two of them say the same thing"

    def test_the_code_and_its_registered_description_do_not_move(self) -> None:
        """The runtime message changed; the ledger entry did not.

        Said as a test because the unbound-surface ledger is counted at
        every gate and a new code — or a re-worded description — would
        move it.
        """
        assert PLACEHOLDER_CODE in ERROR_CODE_DESCRIPTIONS
        assert "intent" not in ERROR_CODE_DESCRIPTIONS[PLACEHOLDER_CODE].split("`")[0]
        assert DRAFT_INTENT_MARKER in ERROR_CODE_DESCRIPTIONS[PLACEHOLDER_CODE]


def _placeholder_findings(tmp_path: Path, capsys) -> list[dict[str, object]]:
    """Every placeholder finding on the one module that carries them all."""
    findings = [
        finding
        for finding in check_project(tmp_path, "sample", _EVERY_FIELD, capsys)
        if str(finding["code"]) == PLACEHOLDER_CODE
    ]
    assert findings, "the module carrying every un-authored field was not refused"
    return findings


def _message_for(tmp_path: Path, capsys, form: str, field: str) -> str:
    """The message reported for one ``(form, field)`` of that module."""
    for finding in _placeholder_findings(tmp_path, capsys):
        context = finding["context"]
        assert isinstance(context, dict)
        if (context["declaration_type"], context["field"]) == (form, field):
            return str(finding["message"])
    raise AssertionError(f"no finding for {form}.{field}")


# ---------------------------------------------------------------------------
# What the quarantine rule does and does not catch
# ---------------------------------------------------------------------------


class TestTheQuarantineRuleHasTwoIndependentKeys:
    """Either key is enough, so neither edit alone silences the refusal.

    The contract D1 wrote down and the emitter honours. Both directions
    are tested because the whole point of a quarantine is that it cannot
    be tidied away without being dealt with.
    """

    def test_the_name_alone_is_enough(self, tmp_path: Path, capsys) -> None:
        """Marker deleted from ``schema:``, carrier still there."""
        text = module_text(
            intent="A draft whose carrier had its marker edited away.",
            declarations=constant_cell(
                f"{UNPLACED_CELL_PREFIX}0010_0011",
                intent="Source the retrofit could not place.",
                schema="One string, held verbatim.",
            ),
        )

        assert DRAFT_UNPLACED_MARKER not in text
        findings = check_project(tmp_path, "sample", text, capsys)

        assert codes_of(findings) == [UNPLACED_CODE]
        assert findings[0]["context"]["matched_name_prefix"] is True
        assert findings[0]["context"]["matched_marker_field"] is None

    def test_the_marker_alone_is_enough(self, tmp_path: Path, capsys) -> None:
        """Carrier renamed to something innocent, marker still there."""
        text = module_text(
            intent="A draft whose carrier was renamed but not dealt with.",
            declarations=constant_cell(
                "LEFTOVERS",
                intent="Source the retrofit could not place.",
                schema=f"{DRAFT_UNPLACED_MARKER} - src/example.py lines 10-11",
            ),
        )

        assert UNPLACED_CELL_PREFIX not in text
        findings = check_project(tmp_path, "sample", text, capsys)

        assert codes_of(findings) == [UNPLACED_CODE]
        assert findings[0]["context"]["matched_marker_field"] == "schema"

    def test_both_keys_together_are_still_one_finding(
        self, tmp_path: Path, capsys
    ) -> None:
        """What the emitter actually writes: one cell, one refusal."""
        findings = check_project(
            tmp_path, "adopt_unplaced_code", fixture(UNPLACED_CODE), capsys
        )

        assert codes_of(findings) == [UNPLACED_CODE]

    def test_an_ordinary_constant_is_not_a_quarantine(
        self, tmp_path: Path, capsys
    ) -> None:
        """Neither key, so nothing fires — including on a near miss.

        ``ADOPTION_RECORD`` shares five letters with the prefix and is an
        entirely ordinary name; the rule reads the whole reserved prefix,
        which ``s0ma adopt draft`` mints and uses for nothing else.
        """
        text = module_text(
            intent="Holds two ordinary constants, neither of them a quarantine.",
            declarations=(
                constant_cell("ADOPTION_RECORD", intent=GOOD_INTENT, schema=GOOD_SCHEMA)
                + constant_cell("ADOPT_LIMIT", intent=GOOD_INTENT, schema=GOOD_SCHEMA)
            ),
        )

        assert check_project(tmp_path, "sample", text, capsys) == []

    def test_the_message_names_the_cell_its_line_range_and_both_ways_out(
        self, tmp_path: Path, capsys
    ) -> None:
        findings = check_project(
            tmp_path, "adopt_unplaced_code", fixture(UNPLACED_CODE), capsys
        )
        message = str(findings[0]["message"])
        remediation = str(findings[0]["remediation"])

        assert "ADOPT_UNPLACED_0010_0011" in message
        assert "lines 10-11" in message
        assert "kept word for word" in message
        assert "move it into the declaration it belongs to" in remediation
        assert "delete it" in remediation
        assert "cannot build" in remediation
        assert "payload" not in (message + remediation).lower()

    def test_a_hand_edited_name_still_fires_without_inventing_a_range(
        self, tmp_path: Path, capsys
    ) -> None:
        """A carrier whose numbers were edited off is still a carrier.

        The finding then says what it can — that the name opens with the
        reserved prefix — rather than reporting a line range it does not
        have.
        """
        text = module_text(
            intent="A draft whose carrier name lost its line numbers.",
            declarations=constant_cell(
                f"{UNPLACED_CELL_PREFIX}BLOCK",
                intent="Source the retrofit could not place.",
                schema="One string, held verbatim.",
            ),
        )

        findings = check_project(tmp_path, "sample", text, capsys)

        assert codes_of(findings) == [UNPLACED_CODE]
        assert "lines" not in str(findings[0]["message"])
        assert UNPLACED_CELL_PREFIX in str(findings[0]["message"])
