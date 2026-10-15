"""The quick reference: what it may say, and what stops it saying anything else.

Two declared outputs rendered from one value —
``docs/reference/quick-reference-readable.md`` for a person and
``docs/_generated/quick-reference-machine.json`` for a program — composed
from three readings that are each held against the others: the language, the
composed model, and the explanations authored in
``docs/s0ma_src/quick-reference.json``.

This module is that page's whole proof, in the order the claims on the page
are made:

* :class:`TestTheLinesAreTheOnesTheCheckAccepts` — the page lists a line
  exactly when the ``UNKNOWN_FIELD`` report would not fire on it;
* :class:`TestTheWordsAndTheLanguageAgree` — every coverage rule, in both
  directions, with the entry named in the refusal;
* :class:`TestWhatThePageNamesIsReal` — commands down to the option, reports,
  agent tools and documents;
* :class:`TestTheSamplesAreChecked` — the half the build does, in process;
* :class:`TestWhatThePageSaysOfAKind` — sentences that are claims about the
  check, tried against it;
* :class:`TestTheSampleProjectReallyBuilds` — the half the build may not do:
  the project written out, built, tested and run by the real toolchain;
* :class:`TestEveryStateThePageShows` — each ``none`` and ``pending`` tried
  against the real parser, and each withheld one shown to be refused;
* :class:`TestThePageKeepsItsOwnChangelog` — the pins, and what they refuse;
* :class:`TestOneValueTwoRenderings`, :class:`TestTheAuthoredFileIsHeldToItsShape`,
  :class:`TestTheVoiceRule` and :class:`TestItIsADeclaredOutput`.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.docs_model import quick_reference as quick
from s0ma_dsl.docs_model.application import (
    DOC_GATE_VACUOUS,
    DOCS_MANIFEST_OUTPUT,
    DOCS_ROOT,
    STATIC_OUTPUTS,
    build,
    gate_modules,
    registry,
)
from s0ma_dsl.docs_model.inventories import GENERATED_NOTE
from s0ma_dsl.docs_model.providers import ProviderRegistry
from s0ma_dsl.docs_model.providers_cli import CliProvider
from s0ma_dsl.docs_model.providers_diagnostics import DiagnosticsProvider
from s0ma_dsl.docs_model.providers_repo import package_facts
from s0ma_dsl.docs_model.quick_reference import (
    QUICK_REFERENCE_MACHINE_OUTPUT,
    QUICK_REFERENCE_OUTPUT,
    QUICK_REFERENCE_SCHEMA,
    QUICK_REFERENCE_SOURCE,
    DocsQuickReferenceError,
    check_quick_reference_voice,
    fact_pins,
    language_facts,
    quick_reference,
    quick_reference_source,
    render_machine,
    render_readable,
    sample_files,
)
from s0ma_dsl.docs_model.records import RELEASE_CHANNEL
from s0ma_dsl.docs_model.reference_pages import anchor
from s0ma_dsl.errors import S0maError
from s0ma_dsl.parser.s0ma_parser import _known_fields, parse_s0ma_with_warnings
from s0ma_dsl.semantic.validator import validate_module
from s0ma_dsl.semantic_state import FIELD_CLASSIFICATIONS
from tests._committed_claim import claimed_head_tag, preview_tree_only

if TYPE_CHECKING:
    from collections.abc import Callable

    from s0ma_dsl.docs_model.application import Build

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]

requires_checkout = pytest.mark.skipif(
    not (REPO_ROOT / ".git").exists(), reason="not a git checkout (wheel-install context)"
)

pytestmark = requires_checkout


# ---------------------------------------------------------------------------
# One reading of this checkout, shared by every assertion below
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def composed() -> Build:
    """One build of this checkout, in the channel the committed tree claims."""
    return build(REPO_ROOT, head_tag=claimed_head_tag())


@pytest.fixture(scope="module")
def readings() -> dict[str, Any]:
    """What the application hands the quick reference, read the same way."""
    known = registry(REPO_ROOT)
    return {
        "facts": language_facts(),
        "interfaces": [
            item
            for provider in known.providers()
            if isinstance(provider, CliProvider)
            for item in provider.interface()
        ],
        "modes": next(
            provider.modes()
            for provider in known.providers()
            if isinstance(provider, DiagnosticsProvider)
        ),
        "packages": [(item.distribution, item.version) for item in package_facts(REPO_ROOT)],
        "docs_root": DOCS_ROOT,
    }


@pytest.fixture(scope="module")
def words() -> dict[str, Any]:
    return quick_reference_source(REPO_ROOT)


@pytest.fixture(scope="module")
def document(composed: Build, readings: dict[str, Any], words: dict[str, Any]) -> dict[str, Any]:
    return quick_reference(composed.bundle, source=words, **readings)


@pytest.fixture
def changed(
    composed: Build, readings: dict[str, Any], words: dict[str, Any]
) -> Callable[..., dict[str, Any]]:
    """Compose over a copy of the authored words with one thing changed.

    ``edit`` receives the copy and changes it in place. Anything else
    passed by name replaces one of the readings, so a test can also move
    the language under words that did not change.
    """

    def compose(edit: Callable[[dict[str, Any]], None] | None = None, **replaced: Any):
        source = copy.deepcopy(words)
        if edit is not None:
            edit(source)
        return quick_reference(composed.bundle, source=source, **{**readings, **replaced})

    return compose


def kind_of(source: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(item for item in source["kinds"] if item["kind"] == kind)


def refusal(compose: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    with pytest.raises(DocsQuickReferenceError) as caught:
        compose(*args, **kwargs)
    return str(caught.value)


# ---------------------------------------------------------------------------
# The lines
# ---------------------------------------------------------------------------


class TestTheLinesAreTheOnesTheCheckAccepts:
    """The page's central claim, held against the check's own reading."""

    def test_every_kind_the_language_has_is_on_the_page(self, document):
        shown = {item["kind"].replace("-", "_") for item in document["kinds"]}
        assert shown == set(FIELD_CLASSIFICATIONS)

    @pytest.mark.parametrize("kind", sorted(FIELD_CLASSIFICATIONS))
    def test_the_lines_shown_are_the_lines_the_line_check_knows(self, document, kind):
        shown = next(
            item for item in document["kinds"] if item["kind"].replace("-", "_") == kind
        )
        assert {line["line"] for line in shown["lines"]} == set(_known_fields(kind))

    @pytest.mark.parametrize("kind", sorted(FIELD_CLASSIFICATIONS))
    def test_whether_a_line_must_be_written_is_the_tables_answer(self, document, kind):
        classes = {
            "always": "semantic-required-state",
            "when-it-applies": "semantic-conditional-state",
            "optional": "presentation-optional",
        }
        shown = next(
            item for item in document["kinds"] if item["kind"].replace("-", "_") == kind
        )
        rows = FIELD_CLASSIFICATIONS[kind]
        for line in shown["lines"]:
            # Two spellings stand for a row under another name, or for none.
            row = rows.get("internal_helpers" if line["line"] == "internal" else line["line"])
            if row is None:
                assert line["line"] in {"content", "helpers"}, line
                continue
            assert classes[line["write"]] == row.field_class, (kind, line["line"])

    def test_what_s0ma_works_out_is_never_shown_as_a_line(self, document):
        for kind in document["kinds"]:
            written = {line["line"] for line in kind["lines"]}
            assert not written & set(kind.get("never_written", ())), kind["kind"]

    def test_the_indent_the_page_states_is_the_parsers(self, document, words):
        from s0ma_dsl.parser import s0ma_parser

        assert document["file"]["indent"] == s0ma_parser._FIELD_INDENT == 4
        assert any("exactly four spaces" in note for note in words["shape"]["notes"])

    def test_every_closed_set_names_a_line_the_language_has(self, readings):
        facts = readings["facts"]
        for choice in facts.choices:
            assert choice.values, choice.group
            for kind, line in choice.used_by:
                held = facts.kind(kind)
                assert held is not None, (choice.group, kind)
                assert line in {item.name for item in held.lines}, (choice.group, kind, line)

    def test_a_line_that_takes_a_closed_set_shows_exactly_that_set(self, document, readings):
        facts = readings["facts"]
        kept = {
            (group["choice"], value["value"])
            for group in document["choices"]
            for value in group["values"]
            if value.get("kept_for_s0ma")
        }
        for choice in facts.choices:
            for kind, name in choice.used_by:
                shown = next(item for item in document["kinds"] if item["kind"] == kind)
                line = next(item for item in shown["lines"] if item["line"] == name)
                expected = {
                    value for value in choice.values if (choice.group, value) not in kept
                }
                assert set(line["values"]) == expected, (kind, name)

    def test_every_layer_says_which_layers_it_may_reach(self, document):
        from s0ma_dsl.ast_nodes.enums import Layer
        from s0ma_dsl.resolver.dependency import _ALLOWED_TARGET_LAYERS

        layers = next(item for item in document["choices"] if item["choice"] == "layer")
        shown = {item["value"]: set(item["may_reach"]) for item in layers["values"]}
        assert shown == {
            layer.value: {item.value for item in _ALLOWED_TARGET_LAYERS[layer]}
            for layer in Layer
        }


# ---------------------------------------------------------------------------
# Coverage, both ways
# ---------------------------------------------------------------------------


class TestTheWordsAndTheLanguageAgree:
    def test_a_line_nobody_described_stops_the_page(self, changed):
        def edit(source):
            nerve = kind_of(source, "nerve")
            nerve["lines"] = [item for item in nerve["lines"] if item["line"] != "raises"]

        said = refusal(changed, edit)
        assert "a nerve accepts the line raises" in said
        assert "kinds[nerve].lines does not describe it" in said

    def test_a_description_of_a_line_the_language_lacks_stops_the_page(self, changed):
        def edit(source):
            kind_of(source, "helper")["lines"].append(
                {"line": "guarantees", "type": "text", "of": "", "also": "", "says": "Not here."}
            )

        said = refusal(changed, edit)
        assert "kinds[helper].lines describes guarantees" in said
        assert "a helper no longer accepts the line it" in said

    def test_a_line_described_twice_is_refused(self, changed):
        def edit(source):
            lines = kind_of(source, "axon")["lines"]
            lines.append(dict(lines[0]))

        assert "describes relation more than once" in refusal(changed, edit)

    def test_a_kind_nobody_described_stops_the_page(self, changed):
        def edit(source):
            source["kinds"] = [item for item in source["kinds"] if item["kind"] != "ganglion"]

        assert "the language has the kind ganglion" in refusal(changed, edit)

    def test_a_word_the_language_accepts_and_nobody_explained(self, changed):
        def edit(source):
            relation = next(item for item in source["choices"] if item["group"] == "relation")
            relation["values"] = [
                item for item in relation["values"] if item["value"] != "CONSUMES"
            ]

        said = refusal(changed, edit)
        assert "accepts CONSUMES" in said
        assert "choices[relation].values" in said

    def test_a_word_the_language_does_not_accept(self, changed):
        def edit(source):
            coupling = next(item for item in source["choices"] if item["group"] == "coupling")
            coupling["values"].append(
                {"value": "MEDIUM", "says": "Neither.", "looks_like": "", "reserved": False}
            )

        assert "choices[coupling].values describes MEDIUM" in refusal(changed, edit)

    def test_a_relation_s0ma_works_out_is_not_a_word_to_choose(self, document):
        relation = next(
            item for item in document["choices"] if item["choice"] == "relation"
        )
        assert {"RAISES", "TYPE_USES"}.isdisjoint(item["value"] for item in relation["values"])

    def test_a_choice_written_as_something_else_is_refused(self, changed):
        def edit(source):
            next(
                item for item in kind_of(source, "cell")["lines"] if item["line"] == "kind"
            )["type"] = "name"

        assert "takes one of a closed set of words (cell-kind)" in refusal(changed, edit)

    def test_a_line_written_as_a_choice_with_no_set_behind_it(self, changed):
        def edit(source):
            next(
                item for item in kind_of(source, "test")["lines"] if item["line"] == "tests"
            )["type"] = "choice"

        assert "no closed set of words is read for it" in refusal(changed, edit)

    def test_a_type_the_legend_does_not_explain(self, changed):
        def edit(source):
            kind_of(source, "axon")["lines"][1]["type"] = "sentence"

        assert "`types` explains no such word" in refusal(changed, edit)

    def test_a_legend_entry_no_line_uses(self, changed):
        def edit(source):
            source["types"].append({"type": "colour", "word": "colour", "looks_like": "`red`"})

        assert "`types` explains colour, and no line on the page holds one" in refusal(
            changed, edit
        )

    def test_code_described_where_the_kind_has_none(self, changed):
        def edit(source):
            kind_of(source, "axon")["code"] = {"write": "Always", "type": "code", "says": "x"}

        assert "describes code, and an axon has none" in refusal(changed, edit)

    def test_code_left_out_where_the_kind_has_it(self, changed):
        def edit(source):
            kind_of(source, "helper")["code"] = None

        assert "a helper has code after its `---` line" in refusal(changed, edit)

    def test_code_the_table_requires_cannot_be_called_optional(self, changed):
        def edit(source):
            kind_of(source, "test")["code"]["write"] = "Optional"

        assert "has a test's code as always" in refusal(changed, edit)

    def test_a_first_line_that_opens_with_another_word(self, changed):
        def edit(source):
            kind_of(source, "cell")["first_line"] = "nerve <name> :: <LAYER>"

        assert "the first line of a cell opens with the word cell" in refusal(changed, edit)

    def test_a_mode_nobody_described(self, changed):
        def edit(source):
            source["modes"]["values"].pop()

        assert "the check has the mode release" in refusal(changed, edit)

    def test_the_counts_beside_each_mode_are_the_registrys(self, document):
        from s0ma_dsl.config import SEVERITY_MATRIX

        assert document["modes"]["reports"] == len(SEVERITY_MATRIX)
        assert document["modes"]["refused_in_every_mode"] == sum(
            1 for row in SEVERITY_MATRIX.values() if set(row.values()) == {"error"}
        )
        for shown in document["modes"]["values"]:
            mode = StrictnessMode(shown["mode"])
            held = [row[mode] for row in SEVERITY_MATRIX.values()]
            assert shown["refuses"] == held.count("error"), shown["mode"]
            assert shown["warns"] == held.count("warning"), shown["mode"]
            assert shown["skips"] == held.count(None), shown["mode"]

    def test_what_only_one_mode_checks_is_read_from_the_registry(self, document, words):
        from s0ma_dsl.config import SEVERITY_MATRIX

        for shown in document["modes"]["values"]:
            mode = StrictnessMode(shown["mode"])
            expected = sorted(
                f"diagnostic:{code}"
                for code, row in SEVERITY_MATRIX.items()
                if row[mode] is not None
                and all(row[other] is None for other in StrictnessMode if other != mode)
            )
            assert shown.get("only_here", []) == expected, shown["mode"]
        release = document["modes"]["values"][-1]
        assert release["mode"] == "release" and len(release["only_here"]) == 3
        page = render_readable(document, words)
        assert "Made only in `release`: [`MISSING_EMBEDDED_EXAMPLE`]" in page

    def test_a_difference_the_table_never_allowed_is_refused(self, changed):
        def edit(source):
            source["known_differences"].append(
                {"kind": "axon", "line": "carries", "state": "pending", "why": "No reason."}
            )

        assert "does not allow it there in the first place" in refusal(changed, edit)

    def test_two_headings_that_would_share_an_anchor(self, composed, readings, words):
        source = copy.deepcopy(words)
        source["rules_section"]["heading"] = source["commands_section"]["heading"]
        held = quick_reference(composed.bundle, source=source, **readings)
        with pytest.raises(DocsQuickReferenceError, match="would both be reached at #"):
            render_readable(held, source)


# ---------------------------------------------------------------------------
# What the page names
# ---------------------------------------------------------------------------


def first_command(source: dict[str, Any]) -> dict[str, Any]:
    return source["commands"]["groups"][1]["commands"][0]


class TestWhatThePageNamesIsReal:
    def test_a_command_s0ma_does_not_serve(self, changed):
        def edit(source):
            first_command(source)["command"] = "cli:s0ma/polish"

        assert "s0ma serves nothing under that id" in refusal(changed, edit)

    def test_a_command_line_that_is_typed_another_way(self, changed):
        def edit(source):
            first_command(source)["write"] = "s0ma verify"

        assert "that command is typed `s0ma check`" in refusal(changed, edit)

    def test_an_option_the_command_does_not_have(self, changed):
        def edit(source):
            first_command(source)["write"] = "s0ma check --fast"

        said = refusal(changed, edit)
        assert "`s0ma check` has no option --fast" in said
        assert "--mode" in said

    def test_a_value_an_option_does_not_accept(self, changed):
        def edit(source):
            first_command(source)["write"] = "s0ma check --mode fastest"

        said = refusal(changed, edit)
        assert "is given 'fastest'" in said
        assert "migration, dev, strict, release" in said

    def test_an_option_left_without_its_value(self, changed):
        def edit(source):
            first_command(source)["write"] = "s0ma check --mode"

        assert "--mode takes a value that is not there" in refusal(changed, edit)

    def test_more_values_than_the_command_takes(self, changed):
        def edit(source):
            entry = source["commands"]["groups"][1]["commands"][3]
            assert entry["command"] == "cli:s0ma/inspect"
            entry["write"] = "s0ma inspect one two"

        assert "which gives 2 value(s); `s0ma inspect` takes 0 to 1" in refusal(changed, edit)

    def test_a_kind_of_thing_the_new_command_cannot_make(self, changed):
        def edit(source):
            source["commands"]["groups"][0]["commands"][1]["write"] = "s0ma new ganglion <name>"

        assert "is given 'ganglion'" in refusal(changed, edit)

    def test_an_option_an_explanation_mentions_in_passing(self, changed):
        def edit(source):
            entry = source["commands"]["groups"][0]["commands"][0]
            entry["says"] = entry["says"].replace("--template service", "--template castle")

        assert "is given 'castle'" in refusal(changed, edit)

    def test_a_first_session_line_that_is_not_a_command(self, changed):
        def edit(source):
            source["commands"]["first_session"][1]["write"] = "rm -rf library"

        assert "is a change of folder" in refusal(changed, edit)

    def test_a_report_s0ma_cannot_make(self, changed):
        def edit(source):
            source["rules"][0]["reports"] = ["diagnostic:FILE_WAS_TOUCHED"]

        assert "names diagnostic:FILE_WAS_TOUCHED" in refusal(changed, edit)

    def test_a_tool_the_agent_server_does_not_serve(self, changed):
        def edit(source):
            source["more"]["ask_agent"]["rows"][1]["with"] = ["mcp:tool/where_am_i"]

        assert "names mcp:tool/where_am_i" in refusal(changed, edit)

    def test_a_document_the_catalog_does_not_hold(self, changed):
        def edit(source):
            source["more"]["read"]["rows"][0]["document"] = "doc:guide/never-written"

        assert "the document catalog has no such document" in refusal(changed, edit)

    def test_every_link_on_the_page_lands_on_a_tracked_file(self, document, words):
        page = render_readable(document, words)
        here = (REPO_ROOT / DOCS_ROOT / QUICK_REFERENCE_OUTPUT).parent
        targets = {
            target.partition("#")[0]
            for target in re.findall(r"\]\(([^)#][^)]*)\)", page)
            if not target.startswith(("http://", "https://"))
        }
        assert len(targets) > 10
        for target in sorted(targets):
            assert (here / target).resolve().is_file(), target

    def test_every_anchor_on_the_page_names_a_heading_on_it(self, document, words):
        page = render_readable(document, words)
        headings = {
            anchor(line.lstrip("#").strip())
            for line in page.splitlines()
            if line.startswith("#")
        }
        wanted = set(re.findall(r"\]\(#([^)]+)\)", page))
        assert len(wanted) > 15
        assert wanted <= headings, sorted(wanted - headings)

    def test_a_setting_the_sample_project_sets_is_one_s0ma_reads(self, changed):
        def edit(source):
            source["sample"]["files"]["pyproject.toml"].append('shiny = "yes"')

        assert "sets shiny under [tool.s0ma], and s0ma reads no such setting" in refusal(
            changed, edit
        )

    def test_the_settings_shown_are_the_sample_projects_own(self, document, words):
        shown = document["file"]["settings"]
        assert shown[0] == "[tool.s0ma]"
        assert "\n".join(shown) in "\n".join(words["sample"]["files"]["pyproject.toml"])


# ---------------------------------------------------------------------------
# The samples: the half the build does
# ---------------------------------------------------------------------------


def sample_line(source: dict[str, Any], path: str, starts: str) -> int:
    lines = source["sample"]["files"][path]
    return next(index for index, line in enumerate(lines) if line.startswith(starts))


class TestTheSamplesAreChecked:
    DOMAIN = "src/library/library_domain.s0ma"

    def test_every_kind_is_shown_in_use(self, document):
        for kind in document["kinds"]:
            assert kind["samples"], kind["kind"]
            for sample in kind["samples"]:
                assert sample["text"].startswith(sample["declaration"].split()[0])

    def test_every_sample_is_cut_from_the_file_it_names(self, document, words):
        files = sample_files(words)
        for kind in document["kinds"]:
            for sample in kind["samples"]:
                assert sample["text"] in files[sample["file"]], sample["declaration"]

    def test_a_misspelt_line_in_a_sample_stops_the_page(self, changed):
        def edit(source):
            at = sample_line(source, self.DOMAIN, "    tags: [library, lending]")
            source["sample"]["files"][self.DOMAIN][at] = "    tagz: [library, lending]"

        said = refusal(changed, edit)
        assert f"the sample file {self.DOMAIN} does not pass the strictest check" in said
        assert "UNKNOWN_FIELD" in said

    def test_a_line_indented_wrongly_in_a_sample_stops_the_page(self, changed):
        def edit(source):
            at = sample_line(source, self.DOMAIN, "    tags: [catalogue]")
            source["sample"]["files"][self.DOMAIN][at] = "      tags: [catalogue]"

        assert "UNRECOGNIZED_LINE" in refusal(changed, edit)

    def test_a_required_line_missing_from_a_sample_stops_the_page(self, changed):
        def edit(source):
            at = sample_line(source, self.DOMAIN, "    soft_requires: none")
            del source["sample"]["files"][self.DOMAIN][at]

        assert "SEMANTIC_REQUIRED_STATE_OMITTED" in refusal(changed, edit)

    def test_a_test_the_runner_would_skip_stops_the_page(self, changed):
        path = "tests/reminders/reminders_application_tests.s0ma"

        def edit(source):
            at = sample_line(source, path, "    def test_reminder_is_two_days_early")
            source["sample"]["files"][path][at] = "    def reminder_is_two_days_early() -> None:"

        assert "TEST_NOT_COLLECTED" in refusal(changed, edit)

    def test_a_note_on_a_line_of_its_own_is_shown_and_accepted(self, document, words):
        header = next(item for item in document["kinds"] if item["kind"] == "module")
        assert "\n    # " in header["samples"][0]["text"]
        assert any("sits on a line of its own" in note for note in words["shape"]["notes"])

    @pytest.mark.parametrize(
        "line",
        ["    layer: DOMAIN", "    uses: none", "    tags: [library, lending]"],
        ids=["a word", "none", "a list"],
    )
    def test_a_note_written_after_an_answer_is_refused(self, changed, line):
        """What the page says about notes, held true from the other side."""

        def edit(source):
            at = sample_line(source, self.DOMAIN, line)
            source["sample"]["files"][self.DOMAIN][at] = f"{line}  # a note"

        assert "PARSE_ERROR" in refusal(changed, edit)

    def test_every_sample_file_is_plain_ascii(self, words):
        """So no platform's own idea of an encoding can misread one."""
        for path, text in sample_files(words).items():
            assert text.isascii(), path

    def test_a_sample_the_project_does_not_hold(self, changed):
        def edit(source):
            kind_of(source, "nerve")["samples"][0]["declaration"] = "nerve front_desk"

        assert "the sample project has no nerve by that first line there" in refusal(
            changed, edit
        )

    def test_a_sample_of_the_wrong_kind(self, changed):
        def edit(source):
            kind_of(source, "nerve")["samples"][0]["declaration"] = "cell Book"

        assert "has no nerve by that first line" in refusal(changed, edit)

    def test_the_check_reads_no_file_of_this_machine(self, document, monkeypatch, tmp_path):
        """The samples are checked under a name no file answers to.

        So the project's runner settings — which the check reads from the
        files around a test's source — cannot reach this build from wherever
        it happens to run.
        """
        (tmp_path / "pytest.ini").write_text("[pytest]\npython_functions = check_*\n")
        monkeypatch.chdir(tmp_path)
        assert not Path(f"{QUICK_REFERENCE_SOURCE}/tests").exists()
        assert document["sample"]["tests"] == 5


class TestWhatThePageSaysOfAKind:
    """Sentences on the page that are claims about the check, tried against it."""

    def reported(self, words: dict[str, Any], path: str, text: str) -> list[str]:
        try:
            module, warnings = parse_s0ma_with_warnings(text, path, mode=StrictnessMode.DEV)
            found = [*warnings, *validate_module(module, mode=StrictnessMode.DEV, filename=path)]
        except S0maError as error:
            return [error.code]
        return [item.code for item in found]

    def test_an_integration_lives_only_in_an_infrastructure_file(self, words):
        assert "It can only live in an `INFRASTRUCTURE` file" in kind_of(
            words, "integration"
        )["opening"]
        mail = sample_files(words)["src/mail/mail_infrastructure.s0ma"]
        moved_up = mail.replace("module mail_infrastructure", "module mail_application")
        moved_up = moved_up.replace("INFRASTRUCTURE", "APPLICATION")
        assert "LAYER_MISMATCH" in self.reported(
            words, "src/mail/mail_application.s0ma", moved_up
        )

    def test_the_check_that_a_connection_is_alive_may_live_in_another_file(self, document):
        """Which is why the page says the builder is beside it, and not both."""
        integration = next(item for item in document["kinds"] if item["kind"] == "integration")
        smoke = next(
            item for item in integration["lines"] if item["line"] == "smoke_test_primary"
        )
        assert "or one listed in `uses`" in smoke["holds"]
        assert "beside the nerve that builds it" in integration["opening"]

    def test_a_reference_page_takes_no_code(self, words):
        assert "no three-hyphen line" in kind_of(words, "doc-ref")["opening"]
        docs = sample_files(words)["src/library_docs.s0ma"]
        with_code = docs.replace(
            "    tags: [reference]\n", "    tags: [reference]\n    ---\n    words\n"
        )
        assert with_code != docs
        assert self.reported(words, "src/library_docs.s0ma", with_code) == [
            "PARSE_DOC_REF_BODY_PROHIBITED"
        ]

    def test_a_guide_takes_no_code_sample_typed_by_hand(self, words):
        assert "never typed in by hand" in kind_of(words, "doc-guide")["opening"]
        docs = sample_files(words)["src/library_docs.s0ma"]
        typed = docs.replace(
            "    {{example::lend_a_book}}\n",
            "    ```python\n    print(1)\n    ```\n",
        )
        assert typed != docs
        assert "PROSE_RAW_CODE_BLOCK" in self.reported(words, "src/library_docs.s0ma", typed)

    def test_a_constant_assigns_to_its_own_name(self, words):
        assert "assigns to its own name" in kind_of(words, "cell")["code"]["says"]
        domain = sample_files(words)["src/library/library_domain.s0ma"]
        renamed = domain.replace("    LOAN_DAYS = 21\n", "    DAYS = 21\n")
        assert renamed != domain
        assert "CONSTANT_NAME_MISMATCH" in self.reported(
            words, "src/library/library_domain.s0ma", renamed
        )

    def test_what_a_file_publishes_is_public(self, words):
        domain = sample_files(words)["src/library/library_domain.s0ma"]
        hidden = domain.replace(
            "cell Book :: DOMAIN\n    kind: MODEL\n    visibility: PUBLIC\n",
            "cell Book :: DOMAIN\n    kind: MODEL\n    visibility: INTERNAL\n",
        )
        assert hidden != domain
        assert "VISIBILITY_MISMATCH" in self.reported(
            words, "src/library/library_domain.s0ma", hidden
        )


# ---------------------------------------------------------------------------
# The samples: the half the build may not do
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def project(tmp_path_factory, words) -> Path:
    """The sample project, written out exactly as the authored file holds it."""
    root = tmp_path_factory.mktemp("quick-reference") / words["sample"]["name"]
    for relative, text in sample_files(words).items():
        target = root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    return root


def run_s0ma(project: Path, *argv: str, extra: dict[str, str] | None = None):
    """One real command, under the discipline the transcript replays use."""
    from s0ma.examples.timeout import run_subprocess_with_timeout

    from s0ma_dsl.docs_model.evidence import _child_env, _program

    return run_subprocess_with_timeout(
        [*_program("s0ma"), *argv],
        cwd=project,
        env={**_child_env(project.parent), **(extra or {})},
        timeout_seconds=120.0,
        input_text="",
    )


class TestTheSampleProjectReallyBuilds:
    """What the page says of its samples, done rather than said.

    In the order a person would: check at the strictest mode, build, run
    the tests, run the example. Each step leaves the project as the next
    one needs it, which is why this is one test and not four.
    """

    def test_it_checks_builds_tests_and_runs(self, project, document):
        checked = run_s0ma(project, "check", "--mode", "release", "--format", "json")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        report = json.loads(checked.stdout)
        assert report["errors"] == []
        assert report["warnings"] == []
        assert report["summary"]["files_processed"] == document["sample"]["modules"]

        built = run_s0ma(project, "build", ".", "--mode", "release", "--no-cache")
        assert built.returncode == 0, built.stdout + built.stderr
        assert (project / "build" / "library_domain.py").is_file()
        assert (project / "build" / "library_domain.s0ma.json").is_file()
        assert (project / "build" / "docs" / "lending_guide.md").is_file()

        tested = run_s0ma(project, "test")
        assert tested.returncode == 0, tested.stdout + tested.stderr
        assert f"{document['sample']['tests']} passed" in tested.stdout

        ran = run_s0ma(
            project,
            "examples",
            "run",
            "src",
            extra={"PYTHONPATH": str(project / "build")},
        )
        assert ran.returncode == 0, ran.stdout + ran.stderr

    def test_the_example_needs_to_be_told_where_the_build_is(self, words):
        """The page's one instruction that is about a shell, kept true."""
        example = kind_of(words, "example")
        assert any(
            'PYTHONPATH="$PWD/build" s0ma examples run src' in note
            for note in example["after_samples"]
        )


# ---------------------------------------------------------------------------
# none and pending
# ---------------------------------------------------------------------------

#: A header that publishes nothing, so `exports: none` is a statement about
#: the line and not about the parts of the file it is written in.
MODULE_BASE = ("src/library_docs.s0ma", "module library_docs")


def with_line(text: str, block: str, line: str, value: str) -> str:
    """``text`` with one line of one declaration set to ``value``.

    Replaces the line and anything written underneath as part of it, or
    writes the line in directly under the declaration's first line.
    """
    rows = block.split("\n")
    end = next((at for at, row in enumerate(rows) if row.strip() == "---"), len(rows))
    written = f"    {line}: {value}"
    for at in range(1, end):
        if re.match(rf"^    {re.escape(line)}:", rows[at]):
            after = at + 1
            while after < end and rows[after].startswith("     ") and rows[after].strip():
                after += 1
            return text.replace(block, "\n".join([*rows[:at], written, *rows[after:]]))
    return text.replace(block, "\n".join([rows[0], written, *rows[1:]]))


def tried(words: dict[str, Any], kind: dict[str, Any], line: str, value: str) -> str | None:
    """The code the check refuses ``line: value`` with, or ``None``."""
    files = sample_files(words)
    if kind["kind"] == "module":
        path, declaration = MODULE_BASE
        block = quick._declarations(files[path])[declaration][1]
    else:
        path, block = kind["samples"][0]["file"], kind["samples"][0]["text"]
    probe = with_line(files[path], block, line, value)
    assert f"    {line}: {value}" in probe
    try:
        module, _warnings = parse_s0ma_with_warnings(probe, path, mode=StrictnessMode.DEV)
        errors = [
            item
            for item in validate_module(module, mode=StrictnessMode.DEV, filename=path)
            if item.severity == "error"
        ]
    except S0maError as error:
        return error.code
    return errors[0].code if errors else None


class TestEveryStateThePageShows:
    VALUES = {"none": "none", "pending": 'pending("not decided yet")'}

    def test_every_state_shown_is_one_the_check_accepts(self, document, words):
        shown = [
            (kind, line["line"], state)
            for kind in document["kinds"]
            for line in kind["lines"]
            for state in line.get("may_be", ())
        ]
        assert len(shown) > 80
        refused = {
            (kind["kind"], line, state): code
            for kind, line, state in shown
            if (code := tried(words, kind, line, self.VALUES[state])) is not None
        }
        assert refused == {}

    def test_every_state_withheld_is_one_the_check_refuses(self, document, words):
        """The ledger of differences, held from the other side.

        An entry the check has stopped refusing has expired: the language
        and its table agree again, and the page should say so.
        """
        by_kind = {kind["kind"]: kind for kind in document["kinds"]}
        assert len(document["known_differences"]) == 3
        for entry in document["known_differences"]:
            code = tried(words, by_kind[entry["kind"]], entry["line"], self.VALUES[entry["state"]])
            assert code is not None, entry

    def test_the_table_and_the_page_differ_only_where_the_ledger_says(self, document, readings):
        withheld = set()
        for fact in readings["facts"].kinds:
            shown = next(item for item in document["kinds"] if item["kind"] == fact.word)
            for line in fact.lines:
                held = set(
                    next(item for item in shown["lines"] if item["line"] == line.name).get(
                        "may_be", ()
                    )
                )
                allowed = {
                    state
                    for state, may in (("none", line.may_be_none), ("pending", line.may_be_pending))
                    if may
                }
                assert held <= allowed, (fact.word, line.name)
                withheld |= {(fact.word, line.name, state) for state in allowed - held}
        assert withheld == {
            (item["kind"], item["line"], item["state"]) for item in document["known_differences"]
        }

    @pytest.mark.parametrize("state", ["none", "pending"])
    def test_a_line_that_stands_in_for_the_code_takes_no_state(self, document, words, state):
        cell = next(item for item in document["kinds"] if item["kind"] == "cell")
        content = next(item for item in cell["lines"] if item["line"] == "content")
        assert "may_be" not in content
        constant = {**cell, "samples": [cell["samples"][1]]}
        assert constant["samples"][0]["declaration"] == "cell LOAN_DAYS"
        assert tried(words, constant, "content", self.VALUES[state]) == "PARSE_ERROR"


# ---------------------------------------------------------------------------
# The page's own changelog
# ---------------------------------------------------------------------------


def moved(facts: quick.LanguageFacts, kind: str, line: str, **changes: Any) -> quick.LanguageFacts:
    """``facts`` with one line of one kind changed, and nothing else."""
    return dataclasses.replace(
        facts,
        kinds=tuple(
            dataclasses.replace(
                held,
                lines=tuple(
                    dataclasses.replace(item, **changes) if item.name == line else item
                    for item in held.lines
                ),
            )
            if held.word == kind
            else held
            for held in facts.kinds
        ),
    )


class TestThePageKeepsItsOwnChangelog:
    def test_the_newest_edition_pins_what_the_language_accepts_today(self, words, readings):
        assert words["editions"][-1]["facts"] == fact_pins(readings["facts"], readings["modes"])

    def test_the_page_states_its_edition_and_when_it_was_revised(self, document, words):
        newest = words["editions"][-1]
        assert document["identity"]["edition"] == newest["edition"]
        assert document["identity"]["revised"] == newest["date"]
        page = render_readable(document, words)
        assert f"edition {newest['edition']}, last revised {newest['date']}" in page

    def test_a_change_to_the_language_stops_the_page_until_it_is_written_up(
        self, changed, readings, words
    ):
        newest = words["editions"][-1]["edition"]
        facts = moved(readings["facts"], "nerve", "latency_ms", write="optional")
        said = refusal(changed, facts=facts)
        assert f"what s0ma accepts has changed since edition {newest}" in said
        assert "What moved: kind:nerve." in said
        assert f"Add an edition {newest + 1}" in said
        pins = json.loads(said[said.index("{") :])
        assert pins == fact_pins(facts, readings["modes"])

    def test_writing_it_up_is_what_lets_the_page_through(
        self, changed, readings, words
    ):
        newest = words["editions"][-1]["edition"]
        later = "2026-12-31"
        facts = moved(readings["facts"], "nerve", "latency_ms", write="optional")

        def edit(source):
            source["editions"].append(
                {
                    "edition": newest + 1,
                    "date": later,
                    "written_for": "0.18.1",
                    "changes": ["`latency_ms` on a nerve may now be left out."],
                    "facts": fact_pins(facts, readings["modes"]),
                }
            )

        held = changed(edit, facts=facts)
        assert [item["edition"] for item in held["editions"]] == list(
            range(1, newest + 2)
        )
        assert held["identity"]["edition"] == newest + 1
        assert held["identity"]["revised"] == later

    @pytest.mark.parametrize(
        "line, change",
        [
            ("intent", {"may_be_pending": False}),
            ("intent", {"may_be_none": True}),
            ("intent", {"write": "optional"}),
            ("visibility", {"values": ("PUBLIC", "INTERNAL")}),
        ],
    )
    def test_each_fact_about_a_line_is_pinned(self, readings, line, change):
        before = fact_pins(readings["facts"], readings["modes"])
        changed = moved(readings["facts"], "cell", line, **change)
        after = fact_pins(changed, readings["modes"])
        assert {key for key in before if before[key] != after[key]} == {"kind:cell"}

    def test_the_strictness_ladder_is_pinned(self, readings):
        before = fact_pins(readings["facts"], readings["modes"])
        after = fact_pins(readings["facts"], (*readings["modes"], "paranoid"))
        assert {key for key in before if before[key] != after[key]} == {"modes"}

    def test_editions_are_numbered_from_one_in_order(self, changed):
        def edit(source):
            source["editions"][0]["edition"] = 3

        assert "numbered from 1, so this one is 1" in refusal(changed, edit)

    def test_a_date_is_written_year_month_day(self, changed):
        def edit(source):
            source["editions"][0]["date"] = "29 September 2026"

        assert "a date is written year-month-day" in refusal(changed, edit)

    def test_an_edition_says_what_changed(self, changed):
        def edit(source):
            source["editions"][0]["changes"] = []

        assert "An edition exists because something did" in refusal(changed, edit)

    def test_the_page_names_no_clock(self, document, words):
        """The date is the authored one, so two builds a year apart agree."""
        page = render_readable(document, words)
        dates = set(re.findall(r"\b20\d\d-\d\d-\d\d\b", page))
        assert dates == {entry["date"] for entry in words["editions"]}


# ---------------------------------------------------------------------------
# One value, two renderings
# ---------------------------------------------------------------------------


class TestOneValueTwoRenderings:
    def test_the_data_is_the_value_written_down(self, document):
        assert json.loads(render_machine(document)) == document
        assert document["schema"] == QUICK_REFERENCE_SCHEMA

    def test_every_line_in_the_data_is_a_row_on_the_page(self, document, words):
        page = render_readable(document, words)
        for kind in document["kinds"]:
            section = page[page.index(f"\n### {kind['kind']}\n") :]
            for line in kind["lines"]:
                assert f"\n| `{line['line']}` | " in section, (kind["kind"], line["line"])
            for sample in kind["samples"]:
                assert sample["text"] in section

    def test_every_word_command_rule_and_mode_in_the_data_is_on_the_page(
        self, document, words
    ):
        page = render_readable(document, words)
        for group in document["choices"]:
            for value in group["values"]:
                assert f"`{value['value']}`" in page
        for group in document["commands"]["groups"]:
            for command in group["commands"]:
                assert f"[`{command['write']}`]" in page
        for rule in document["rules"]:
            assert f"**{rule['rule']}**" in page
            for report in rule.get("reports", ()):
                assert f"[`{report.partition(':')[2]}`]" in page
        for mode in document["modes"]["values"]:
            assert f"| `{mode['mode']}` | " in page

    def test_the_data_carries_nothing_that_says_nothing(self, document):
        def empty(value: Any, where: str) -> list[str]:
            if isinstance(value, dict):
                return [
                    found
                    for key, item in value.items()
                    for found in empty(item, f"{where}.{key}")
                ]
            if isinstance(value, list):
                return [
                    found
                    for index, item in enumerate(value)
                    for found in empty(item, f"{where}[{index}]")
                ] or ([where] if not value and where.count(".") > 1 else [])
            return [where] if value == "" else []

        assert empty(document["kinds"], "kinds") == []
        assert empty(document["choices"], "choices") == []
        assert empty(document["rules"], "rules") == []

    def test_composing_twice_gives_the_same_bytes(self, composed, readings, words, document):
        again = quick_reference(composed.bundle, source=words, **readings)
        assert render_machine(again) == render_machine(document)
        assert render_readable(again, words) == render_readable(document, words)

    def test_both_end_with_one_line_feed_and_name_no_machine_path(self, document, words):
        for text in (render_readable(document, words), render_machine(document)):
            assert text.endswith("\n") and not text.endswith("\n\n")
            assert "\r" not in text
            assert str(REPO_ROOT) not in text
            assert str(Path.home()) not in text

    def test_the_page_says_it_is_generated_and_where_its_twin_is(self, document, words):
        page = render_readable(document, words)
        assert page.count(GENERATED_NOTE) == 1
        assert f"`{DOCS_ROOT}/{QUICK_REFERENCE_MACHINE_OUTPUT}`" in page
        assert f"`{QUICK_REFERENCE_SOURCE}`" in page

    @preview_tree_only
    def test_a_preview_build_says_what_preview_means(self, document, words):
        assert document["identity"]["build_channel"] != RELEASE_CHANNEL
        assert words["page"]["preview_note"] in render_readable(document, words)

    def test_a_release_build_does_not(self, document, words):
        released = copy.deepcopy(document)
        released["identity"]["build_channel"] = RELEASE_CHANNEL
        released["identity"]["release"] = released["identity"]["release_version"]
        page = render_readable(released, words)
        assert words["page"]["preview_note"] not in page
        assert "(preview)" not in page

    def test_packages_out_of_step_are_named_with_their_versions(self, document, words):
        uneven = copy.deepcopy(document)
        uneven["identity"]["packages"][0]["version"] = "9.9.9"
        page = render_readable(uneven, words)
        assert "`s0ma-core` 9.9.9" in page
        assert words["identity"]["packages_note"] not in page

    def test_what_each_kind_is_for_is_the_concepts_own_sentence(self, document, composed):
        concepts = {record.id: record for record in composed.bundle.concepts}
        for kind in document["kinds"]:
            assert kind["in_short"] == concepts[kind["concept"]].summary


# ---------------------------------------------------------------------------
# The authored file
# ---------------------------------------------------------------------------


def written(tmp_path: Path, source: Any) -> Path:
    target = tmp_path.joinpath(*QUICK_REFERENCE_SOURCE.split("/"))
    target.parent.mkdir(parents=True)
    text = source if isinstance(source, str) else json.dumps(source)
    target.write_text(text, encoding="utf-8")
    return tmp_path


class TestTheAuthoredFileIsHeldToItsShape:
    def test_the_real_file_is_canonical_json(self):
        text = (REPO_ROOT / QUICK_REFERENCE_SOURCE).read_text(encoding="utf-8")
        assert text == json.dumps(
            json.loads(text), sort_keys=True, indent=2, ensure_ascii=False
        ) + "\n"

    def test_a_missing_file_is_refused_by_name(self, tmp_path):
        with pytest.raises(DocsQuickReferenceError, match="is not there"):
            quick_reference_source(tmp_path)

    def test_a_file_that_is_not_json(self, tmp_path):
        with pytest.raises(DocsQuickReferenceError, match="is not valid JSON"):
            quick_reference_source(written(tmp_path, "{not json"))

    def test_another_schema(self, tmp_path, words):
        source = {**words, "schema": "s0ma-docs-quick-reference@2"}
        with pytest.raises(DocsQuickReferenceError, match="this reader understands"):
            quick_reference_source(written(tmp_path, source))

    def test_a_key_nothing_reads(self, tmp_path, words):
        source = copy.deepcopy(words)
        source["orientation"]["footnote"] = "Never shown."
        with pytest.raises(
            DocsQuickReferenceError, match="orientation carries footnote, which nothing reads"
        ):
            quick_reference_source(written(tmp_path, source))

    def test_a_key_that_is_missing(self, tmp_path, words):
        source = copy.deepcopy(words)
        del source["kinds"][2]["lines"][0]["says"]
        with pytest.raises(
            DocsQuickReferenceError, match=r"kinds\[2\]\.lines\[0\] is missing says"
        ):
            quick_reference_source(written(tmp_path, source))

    def test_an_explanation_left_empty(self, tmp_path, words):
        source = copy.deepcopy(words)
        source["rules"][3]["detail"] = "   "
        with pytest.raises(
            DocsQuickReferenceError, match=r"rules\[3\]\.detail has to be text with something"
        ):
            quick_reference_source(written(tmp_path, source))

    def test_a_line_break_inside_an_entry(self, tmp_path, words):
        source = copy.deepcopy(words)
        source["orientation"]["paragraphs"][0] += "\nAnd a second paragraph."
        with pytest.raises(DocsQuickReferenceError, match="holds a line break"):
            quick_reference_source(written(tmp_path, source))

    def test_a_flag_that_is_not_true_or_false(self, tmp_path, words):
        source = copy.deepcopy(words)
        source["choices"][0]["values"][0]["reserved"] = "no"
        with pytest.raises(DocsQuickReferenceError, match="has to be true or false"):
            quick_reference_source(written(tmp_path, source))


class TestTheVoiceRule:
    def test_the_real_file_is_in_the_products_voice(self, words):
        assert check_quick_reference_voice(words) == []

    @pytest.mark.parametrize(
        "word", ["payload", "s" + "oma", "studi" + "o"], ids=["feedback", "name", "viewer"]
    )
    def test_a_word_the_product_does_not_use_is_reported(self, words, word):
        source = copy.deepcopy(words)
        source["rules"][0]["detail"] += f" See the {word}."
        found = check_quick_reference_voice(source)
        assert [item.code for item in found] == ["DOC_VOICE_VIOLATION"]
        assert found[0].location == QUICK_REFERENCE_SOURCE
        assert "rules[0].detail" in found[0].message
        assert found[0].remediation

    def test_the_sample_project_is_source_and_not_a_sentence(self, words):
        source = copy.deepcopy(words)
        source["sample"]["files"]["tests/test_lending.py"].append("payload = {}")
        assert check_quick_reference_voice(source) == []


# ---------------------------------------------------------------------------
# The application
# ---------------------------------------------------------------------------


class TestItIsADeclaredOutput:
    def test_both_are_decided_outputs_and_the_manifest_still_comes_last(self):
        assert QUICK_REFERENCE_OUTPUT in STATIC_OUTPUTS
        assert QUICK_REFERENCE_MACHINE_OUTPUT in STATIC_OUTPUTS
        assert STATIC_OUTPUTS[-1] == DOCS_MANIFEST_OUTPUT

    def test_the_page_is_a_reader_page_and_the_data_is_not(self):
        assert not QUICK_REFERENCE_OUTPUT.startswith("_generated/")
        assert QUICK_REFERENCE_MACHINE_OUTPUT.startswith("_generated/")
        assert QUICK_REFERENCE_MACHINE_OUTPUT.endswith(".json")

    def test_the_build_renders_both_from_what_this_module_composes(
        self, composed, document, words
    ):
        assert composed.ok, [item.rendered() for item in composed.findings]
        assert composed.artifact(QUICK_REFERENCE_OUTPUT).content == render_readable(
            document, words
        )
        assert composed.artifact(QUICK_REFERENCE_MACHINE_OUTPUT).content == render_machine(
            document
        )

    @pytest.mark.parametrize(
        "relative", [QUICK_REFERENCE_OUTPUT, QUICK_REFERENCE_MACHINE_OUTPUT]
    )
    def test_the_committed_file_is_what_this_build_renders(self, composed, relative):
        committed = (REPO_ROOT / DOCS_ROOT).joinpath(*relative.split("/"))
        assert committed.read_text(encoding="utf-8") == composed.artifact(relative).content

    def test_the_manifest_lists_both(self, composed):
        manifest = json.loads(composed.artifact(DOCS_MANIFEST_OUTPUT).content)
        listed = json.dumps(manifest)
        assert f"{DOCS_ROOT}/{QUICK_REFERENCE_OUTPUT}" in listed
        assert f"{DOCS_ROOT}/{QUICK_REFERENCE_MACHINE_OUTPUT}" in listed

    def test_the_catalog_has_a_row_for_the_page(self, composed):
        rows = {
            record.canonical_source: record for record in composed.bundle.documents
        }
        row = rows[f"{DOCS_ROOT}/{QUICK_REFERENCE_OUTPUT}"]
        assert row.id == "doc:generated/quick-reference"
        assert row.title == "s0ma quick reference"

    def test_its_gate_lives_where_the_application_says_gates_live(self):
        assert quick in gate_modules()

    def test_over_a_directory_that_is_not_a_workspace_both_are_refused_not_raised(
        self, tmp_path
    ):
        """A caller that brings its own providers meets the refusal at the pages.

        The authored file is not there, so neither output can be rendered —
        and the build says so twice, once at each, instead of ending at the
        first thing it could not read.
        """
        from s0ma_dsl.docs_model.resolve import CoveragePolicy

        result = build(
            tmp_path,
            providers=ProviderRegistry.of(),
            floors={},
            allowances={},
            coverage=CoveragePolicy(
                source="fixture", capabilities=(), surface_exceptions=(), channel_exceptions=()
            ),
        )
        refused = {
            item.location: item
            for item in result.findings
            if item.code == DOC_GATE_VACUOUS and "quick-reference" in item.location
        }
        assert set(refused) == {
            f"{DOCS_ROOT}/{QUICK_REFERENCE_OUTPUT}",
            f"{DOCS_ROOT}/{QUICK_REFERENCE_MACHINE_OUTPUT}",
        }
        for finding in refused.values():
            assert f"{QUICK_REFERENCE_SOURCE} is not there" in finding.message
        assert all("quick-reference" not in item.relative for item in result.artifacts)

    def test_a_refusal_while_composing_lands_on_both_outputs(self, composed, readings, words):
        source = copy.deepcopy(words)
        kind_of(source, "axon")["lines"].pop()
        readable, machine = quick.compose(
            composed.bundle,
            source,
            interfaces=readings["interfaces"],
            modes=readings["modes"],
            packages=readings["packages"],
            docs_root=DOCS_ROOT,
        )
        for render in (readable, machine):
            with pytest.raises(DocsQuickReferenceError, match="an axon accepts the line coupling"):
                render()

    def test_the_run_does_not_depend_on_where_it_is_started(self, composed, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setitem(os.environ, "TZ", "Pacific/Kiritimati")
        again = build(REPO_ROOT, head_tag=claimed_head_tag())
        for relative in (QUICK_REFERENCE_OUTPUT, QUICK_REFERENCE_MACHINE_OUTPUT):
            assert again.artifact(relative).content == composed.artifact(relative).content
