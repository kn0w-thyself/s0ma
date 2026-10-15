"""Every line of a description is read, or reported (spec §4.0.3).

Two reports, both about something a person wrote and s0ma did not act on:

* ``UNKNOWN_FIELD`` — a well-formed field line whose name that kind of
  declaration does not have. Before this check the line was stored and
  never read, so a misspelt optional field silently did nothing.
* ``UNRECOGNIZED_LINE`` — a line that is not a field, not part of a block
  and not a comment. Before this check the splitter skipped it.

Both ladder with the mode: warning in migration and dev, error in strict
and release.

A required field that is on the page under the wrong name or at the wrong
indentation is still an *omitted* field, and the omission is raised first,
in every mode. ``TestOmissionSaysWhereTheFieldIs`` pins that its
remediation names the line, which is what makes the two reports and the
omission one account rather than three.

The known-field set is derived from ``FIELD_CLASSIFICATIONS``.
``TestKnownFieldsComeFromTheFieldTable`` holds that derivation against the
fields the builders actually read, so neither can grow a field the other
has not heard of.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.config import SEVERITY_MATRIX, StrictnessMode
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.parser import s0ma_parser
from s0ma_dsl.parser.s0ma_parser import (
    _known_fields,
    parse_s0ma,
    parse_s0ma_with_warnings,
)
from s0ma_dsl.semantic_state import FIELD_CLASSIFICATIONS

HEADER = """\
module probe
    layer: DOMAIN
    version: 0.1.0
    intent: "A module to write mistakes into."
    exports: [greet]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""

NERVE = """
nerve greet :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Greet a person."
    expects: "A name."
    guarantees: "Returns a greeting."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def greet(name: str) -> str:
        return "Hello, " + name
"""

VALID = HEADER + NERVE

#: One line inserted after ``kind: FUNCTION``, which is line 15 of VALID.
AFTER_KIND = "    kind: FUNCTION\n"
INSERTED_LINE = 15


def with_line(line: str) -> str:
    """VALID with ``line`` written under the nerve's ``kind:``."""
    return VALID.replace(AFTER_KIND, AFTER_KIND + line + "\n")


def reports(source: str, mode: StrictnessMode = StrictnessMode.DEV) -> list[S0maParseError]:
    """The line reports a parse collects, as warnings."""
    _module, warnings = parse_s0ma_with_warnings(source, "probe.s0ma", mode)
    return [
        item
        for item in warnings
        if item.code in ("UNKNOWN_FIELD", "UNRECOGNIZED_LINE")
    ]


FIXTURES: dict[str, str] = {
    "UNKNOWN_FIELD": "unknown_field.s0ma",
    "UNRECOGNIZED_LINE": "unrecognized_line.s0ma",
}
"""The deliberately failing fixture for each code, under
``tests/fixtures/invalid/`` and named after the code it trips — the
repository's convention for a DSL diagnostic."""

_INVALID_DIR = Path(__file__).resolve().parent / "fixtures" / "invalid"


class TestTheNegativeFixtures:
    """What a person at a terminal sees: the real command, over a real file."""

    def check(self, code: str, mode: str, capsys) -> dict[str, list[dict]]:
        S0maCLI().run(
            ["check", str(_INVALID_DIR / FIXTURES[code]), "--mode", mode, "--format", "json"]
        )
        return json.loads(capsys.readouterr().out)

    @pytest.mark.parametrize("code", sorted(FIXTURES))
    def test_the_fixture_trips_its_code_and_nothing_else(self, code, capsys):
        report = self.check(code, "dev", capsys)
        assert report["errors"] == []
        assert [item["code"] for item in report["warnings"]] == [code]
        found = report["warnings"][0]
        assert found["line"] == 33
        assert found["remediation"]

    @pytest.mark.parametrize("code", sorted(FIXTURES))
    def test_before_shipping_the_same_line_is_refused(self, code, capsys):
        report = self.check(code, "release", capsys)
        assert code in [item["code"] for item in report["errors"]]


class TestAValidFileReportsNothing:
    def test_the_baseline_is_clean(self):
        assert reports(VALID) == []

    def test_a_comment_and_a_blank_line_are_not_reported(self):
        source = VALID.replace(AFTER_KIND, AFTER_KIND + "    # a note to a reader\n\n")
        assert reports(source) == []

    def test_the_continuation_of_a_long_value_is_not_reported(self):
        source = VALID.replace(
            '    intent: "Greet a person."\n',
            '    intent: "Greet a person,\n        and mean it."\n',
        )
        assert reports(source) == []

    def test_the_entries_of_a_block_are_not_reported(self):
        source = VALID.replace(
            "    internal: none\n",
            '    internal:\n      - _tidy: "Trim the name."\n',
        ).replace(
            "    declares_attributes: none\n",
            "    declares_attributes:\n      - landmark:header\n",
        ) + (
            "\ncell SETTING :: DOMAIN\n"
            "    kind: CONSTANT\n"
            "    visibility: INTERNAL\n"
            '    intent: "A setting."\n'
            '    schema: "A number."\n'
            "    invariants: none\n"
            "    covered_by: none\n"
            "    metadata:\n"
            '        owner: "front desk"\n'
            "        limit: 3\n"
            "    ---\n"
            "    SETTING = 3\n"
        )
        assert reports(source) == []


class TestUnknownField:
    def test_a_field_the_kind_does_not_have_is_reported(self):
        found = reports(with_line("    colour: blue"))
        assert [item.code for item in found] == ["UNKNOWN_FIELD"]
        report = found[0]
        assert report.line == INSERTED_LINE
        assert report.message == "Unknown field 'colour' on nerve 'greet'."
        assert report.context == {
            "declaration_type": "nerve",
            "declaration_name": "greet",
            "field": "colour",
        }

    def test_a_misspelling_names_the_field_that_was_meant(self):
        report = reports(with_line("    tgas: [a]"))[0]
        assert report.context["suggestion"] == "tags"
        assert report.remediation.startswith("Did you mean 'tags'?")

    def test_a_field_of_another_kind_says_whose_it_is(self):
        report = reports(with_line('    schema: "A name."'))[0]
        assert "'schema' is a field of cell; a nerve does not have it" in report.remediation

    def test_a_header_line_fact_says_where_it_belongs(self):
        report = reports(with_line("    layer: DOMAIN"))[0]
        assert report.remediation == (
            "A nerve's layer is written on its first line, not as a field. "
            "Remove this line."
        )

    def test_the_code_written_as_a_field_says_where_it_belongs(self):
        report = reports(with_line('    body: "x"'))[0]
        assert report.remediation.startswith("The code is written after the `---` line")

    def test_a_contract_on_a_helper_is_reported_and_points_at_a_nerve(self):
        source = VALID + (
            "\nhelper _tidy :: DOMAIN\n"
            '    intent: "Trim a name."\n'
            '    expects: "Some text."\n'
            "    ---\n"
            "    def _tidy(text: str) -> str:\n"
            "        return text.strip()\n"
        )
        report = reports(source)[0]
        assert report.message == "Unknown field 'expects' on helper '_tidy'."
        assert "declare this part as a nerve" in report.remediation

    def test_a_documentation_declaration_is_named_the_way_it_is_written(self):
        source = VALID + (
            "\ndoc-ref reference_page\n"
            '    intent: "A reference page."\n'
            "    format: markdown\n"
            "    output: docs/reference.md\n"
            "    covers: [nerve where visibility == PUBLIC]\n"
            "    sections: [intent]\n"
            "    titel: Reference\n"
        )
        report = reports(source)[0]
        assert report.message == "Unknown field 'titel' on doc-ref 'reference_page'."

    def test_a_derived_field_keeps_its_own_report(self):
        with pytest.raises(S0maParseError) as raised:
            parse_s0ma(with_line('    raw_body: "x"'), "probe.s0ma")
        assert raised.value.code == "SEMANTIC_DERIVED_FIELD_AUTHORED"


class TestUnrecognizedLine:
    @pytest.mark.parametrize("spaces", [1, 2, 3, 5, 6])
    def test_a_field_at_the_wrong_indentation_is_reported(self, spaces):
        found = reports(with_line(" " * spaces + "tags: [a]"))
        assert [item.code for item in found] == ["UNRECOGNIZED_LINE"]
        report = found[0]
        assert report.line == INSERTED_LINE
        assert report.message == (
            f"Line {INSERTED_LINE} looks like the field 'tags' of nerve 'greet', "
            f"but it starts with {spaces} space(s)."
        )
        assert report.context["indent"] == spaces

    def test_a_line_that_is_not_a_field_at_all_is_reported(self):
        report = reports(with_line("    remember to ask Sam"))[0]
        assert report.code == "UNRECOGNIZED_LINE"
        assert "'remember to ask Sam'" in report.message
        assert "A note to a reader starts with `#`" in report.remediation

    def test_a_field_left_inside_the_indentation_of_a_block_is_reported(self):
        source = VALID.replace(
            "    depends_on: none\n",
            "    depends_on:\n"
            '        other_part: {relation: CALLS, carries: "x", coupling: LOOSE}\n'
            "        tags: [a]\n",
        )
        found = reports(source)
        assert [item.code for item in found] == ["UNRECOGNIZED_LINE"]
        assert "looks like the field 'tags'" in found[0].message


class TestTheLadder:
    @pytest.mark.parametrize("code", ["UNKNOWN_FIELD", "UNRECOGNIZED_LINE"])
    def test_warning_while_working_and_error_before_shipping(self, code):
        assert SEVERITY_MATRIX[code] == {
            StrictnessMode.MIGRATION: "warning",
            StrictnessMode.DEV: "warning",
            StrictnessMode.STRICT: "error",
            StrictnessMode.RELEASE: "error",
        }

    @pytest.mark.parametrize("mode", [StrictnessMode.MIGRATION, StrictnessMode.DEV])
    @pytest.mark.parametrize(
        "line, code",
        [("    colour: blue", "UNKNOWN_FIELD"), ("  tags: [a]", "UNRECOGNIZED_LINE")],
    )
    def test_a_forgiving_mode_parses_and_warns(self, mode, line, code):
        found = reports(with_line(line), mode)
        assert [(item.code, item.severity) for item in found] == [(code, "warning")]

    @pytest.mark.parametrize("mode", [StrictnessMode.STRICT, StrictnessMode.RELEASE])
    @pytest.mark.parametrize(
        "line, code",
        [("    colour: blue", "UNKNOWN_FIELD"), ("  tags: [a]", "UNRECOGNIZED_LINE")],
    )
    @pytest.mark.parametrize("parse", [parse_s0ma, parse_s0ma_with_warnings])
    def test_a_strict_mode_refuses(self, mode, line, code, parse):
        with pytest.raises(S0maParseError) as raised:
            parse(with_line(line), "probe.s0ma", mode)
        assert raised.value.code == code
        assert raised.value.severity == "error"


class TestOmissionSaysWhereTheFieldIs:
    """``SEMANTIC_REQUIRED_STATE_OMITTED`` is raised before anything else
    about a declaration can be collected, so it is the only report an
    author sees. It has to say where the field is when the page shows it."""

    def omitted(self, source: str) -> S0maParseError:
        with pytest.raises(S0maParseError) as raised:
            parse_s0ma(source, "probe.s0ma")
        assert raised.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        return raised.value

    def test_a_required_field_at_the_wrong_indentation(self):
        error = self.omitted(VALID.replace("    guarantees:", "  guarantees:"))
        assert error.remediation.startswith(
            "Line 18 holds 'guarantees:' and starts with 2 space(s); "
            "a field starts with exactly 4. "
        )
        assert error.context["misplaced_line"] == 18
        assert error.context["indent"] == 2

    def test_a_required_field_under_a_misspelt_name(self):
        error = self.omitted(VALID.replace("    guarantees:", "    guarantes:"))
        assert error.remediation.startswith(
            "Line 18 holds 'guarantes:', which is not a field of a nerve; "
            "'guarantees' was probably meant. "
        )
        assert error.context["misspelt_field"] == "guarantes"

    def test_a_block_whose_entries_could_not_be_read(self):
        error = self.omitted(
            VALID.replace(
                "    depends_on: none\n",
                "    depends_on:\n"
                '      other_part: {relation: CALLS, carries: "x", coupling: LOOSE}\n',
            )
        )
        assert error.remediation.startswith(
            "Line 26 opens 'depends_on:' and line 27 under it could not be read"
        )

    def test_a_field_that_really_is_missing_says_nothing_extra(self):
        error = self.omitted(VALID.replace('    guarantees: "Returns a greeting."\n', ""))
        assert error.remediation.startswith("Author 'guarantees:' with ")
        assert "misplaced_line" not in error.context
        assert "misspelt_field" not in error.context


class TestKnownFieldsComeFromTheFieldTable:
    """The known set is derived, and the derivation is held against the
    code that reads the fields — so a field added to one and not the other
    fails here rather than being reported to an author as unknown."""

    BUILDERS = {
        "_build_module": "module",
        "_build_nerve": "nerve",
        "_build_cell": "cell",
        "_build_ganglion": "ganglion",
        "_build_test": "test",
        "_build_axon": "axon",
        "_build_helper": "helper",
        "_build_integration": "integration",
        "_build_doc_ref": "doc_ref",
        "_build_doc_guide": "doc_guide",
        "_build_example": "example",
    }

    def fields_read_by(self, function: ast.FunctionDef) -> set[str]:
        """Every field name a builder reads out of ``decl.fields``."""
        names: set[str] = set()
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
                and ast.unparse(node.value).endswith("fields")
            ):
                names.add(node.slice.value)
            if isinstance(node, ast.Call) and node.args:
                called = ast.unparse(node.func)
                first = node.args[0]
                if (
                    called.endswith(("fields.get", "fields.pop")) or called == "_require_field"
                ) and isinstance(first, ast.Constant) and isinstance(first.value, str):
                    names.add(first.value)
            if (
                isinstance(node, ast.Compare)
                and len(node.ops) == 1
                and isinstance(node.ops[0], ast.In | ast.NotIn)
                and isinstance(node.left, ast.Constant)
                and isinstance(node.left.value, str)
                and ast.unparse(node.comparators[0]).endswith("fields")
            ):
                names.add(node.left.value)
        return names

    def test_every_field_a_builder_reads_is_known(self):
        tree = ast.parse(Path(s0ma_parser.__file__).read_text(encoding="utf-8"))
        builders = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in self.BUILDERS
        }
        assert set(builders) == set(self.BUILDERS)
        unknown = {
            (kind, name)
            for function, kind in self.BUILDERS.items()
            for name in self.fields_read_by(builders[function])
            if name not in _known_fields(kind)
        }
        assert unknown == set()

    def test_every_kind_in_the_field_table_has_a_known_set(self):
        assert set(self.BUILDERS.values()) == set(FIELD_CLASSIFICATIONS)
        for kind in FIELD_CLASSIFICATIONS:
            assert _known_fields(kind), kind

    def test_header_facts_and_the_code_are_not_fields(self):
        assert "layer" in _known_fields("module")
        assert "layer" not in _known_fields("nerve")
        assert "name" not in _known_fields("nerve")
        for kind in FIELD_CLASSIFICATIONS:
            assert not _known_fields(kind) & {"body", "prose_body", "python_body"}

    def test_the_two_authored_spellings_the_table_does_not_name(self):
        assert "content" in _known_fields("cell")
        assert "helpers" in _known_fields("module")
        assert "internal" in _known_fields("nerve")
        assert "internal_helpers" not in _known_fields("nerve")


class TestTheRepositorysOwnSources:
    """s0ma's own packages build in strict and release mode, so its own
    authored sources have to be free of both reports."""

    ROOT = Path(__file__).resolve().parents[3]
    SOURCES = (
        "docs/s0ma_src",
        "packages/s0ma-mcp/s0ma_src",
        "packages/s0ma-studi0/s0ma_src",
        "packages/s0ma-dsl/docs/_generators",
    )

    def test_no_authored_source_carries_a_line_s0ma_does_not_read(self):
        found: list[str] = []
        checked = 0
        for relative in self.SOURCES:
            for path in sorted((self.ROOT / relative).rglob("*.s0ma")):
                checked += 1
                declarations = s0ma_parser._split_declarations(
                    path.read_text(encoding="utf-8"), str(path),
                )
                found.extend(
                    f"{path.relative_to(self.ROOT)}:{item.line} {item.code}"
                    for item in s0ma_parser._check_declaration_lines(
                        declarations, str(path), StrictnessMode.RELEASE,
                    )
                )
        assert checked >= 8, "the authored sources were not found"
        assert found == []
