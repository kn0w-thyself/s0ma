"""The ``forbids:`` line on nerves and ganglia.

``forbids:`` says what a part must never do, however it is called and
whatever happens while it runs. s0ma checks that the line is there and what
state it is in; it does not read the sentence. The line belongs to nerves
and ganglia only, takes one text value in every shape ``expects`` accepts,
and has the states ``none`` and ``pending("reason")``.

The line is required. A nerve or a ganglion that leaves it out is refused
in every mode with ``SEMANTIC_REQUIRED_STATE_OMITTED``, and
``s0ma migrate grammar --apply`` writes ``forbids: none`` into a source
that lacks it. The tests in ``TestRequired`` pin both.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.cli.migrate_grammar import plan_grammar_migration
from s0ma_dsl.codegen.build_manifest import ModuleManifestEntry
from s0ma_dsl.codegen.self_context import build_self_context_document
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.ir import build_ir
from s0ma_dsl.ir.schema import SCHEMA_VERSION
from s0ma_dsl.parser import parse_s0ma
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.semantic.validator import validate_module
from s0ma_dsl.semantic_state import (
    FIELD_CLASSIFICATIONS,
    FieldClassification,
    authored_lines,
)

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.nodes import S0maModule

KINDS = ("nerve", "ganglion")
_PROJECT = Path(__file__).parent / "fixtures" / "forbids" / "project"
_EXPECTS = '"An account number."'


def _source(
    *,
    nerve: str | None = None,
    ganglion: str | None = None,
    expects: str = _EXPECTS,
) -> str:
    """One module with a nerve and a ganglion, in the full 0.14 form.

    *nerve* and *ganglion* are the lines written where ``forbids:`` goes
    on each: ``forbids: none`` by default, and an empty string leaves the
    line out. *expects* is the value of the nerve's ``expects:`` line.
    """
    return (
        "module ledger_probe\n"
        "    layer: DOMAIN\n"
        "    version: 1.0.0\n"
        '    intent: "Settles accounts and watches the settlements for drift."\n'
        "    exports: [settle]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "\n"
        "nerve settle :: DOMAIN\n"
        "    kind: FUNCTION\n"
        "    visibility: PUBLIC\n"
        '    intent: "Settles one account and returns its balance."\n'
        f"    expects: {expects}\n"
        '    guarantees: "Returns the settled balance as a whole number."\n'
        + (
            '    forbids: none\n'
            if nerve is None else nerve
        )
        + "    evaluates_at: FUNCTION_BOUNDARY\n"
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
        "    def settle(account):\n"
        "        return 0\n"
        "\n"
        "ganglion watch_settle :: DOMAIN\n"
        "    visibility: INTERNAL\n"
        "    scope: SUBSYSTEM\n"
        '    intent: "Watches settlements for drift."\n'
        "    observes: [settle]\n"
        '    on_anomaly: "Logs the drift and carries on."\n'
        + (
            '    forbids: none\n'
            if ganglion is None else ganglion
        )
        + '    priors: "Balances never go negative."\n'
        "    depends_on: none\n"
        "    covered_by: none\n"
        "    ---\n"
        "    def watch_settle(signal):\n"
        "        return signal\n"
    )


def _with_line(kind: str, value: str) -> str:
    """The probe module with ``forbids: <value>`` written on *kind*."""
    line = f"    forbids: {value}\n"
    return _source(**{kind: line})


def _parse(source: str, mode: StrictnessMode = StrictnessMode.DEV) -> S0maModule:
    return parse_s0ma(source, filename="ledger_probe.s0ma", mode=mode)


def _node(module: S0maModule, kind: str) -> Any:
    return module.nerves[0] if kind == "nerve" else module.ganglia[0]


def _state(module: S0maModule, kind: str, field: str = "forbids") -> dict[str, Any]:
    return dict(_node(module, kind).semantic_states)[field].to_dict()


def _ir_fields(source: str, module: S0maModule, kind: str) -> dict[str, Any]:
    payload = build_ir(module, source_text=source).to_dict()
    [component] = [
        item for item in payload["components"] if item["declaration_type"] == kind
    ]
    fields: dict[str, Any] = component["fields"]
    return fields


# ---------------------------------------------------------------------------
# The value and the two states
# ---------------------------------------------------------------------------


class TestStates:
    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize(
        ("written", "projected", "state"),
        [
            (
                '"Never writes a file or reaches the network."',
                "Never writes a file or reaches the network.",
                {
                    "state": "value",
                    "value": "Never writes a file or reaches the network.",
                },
            ),
            ("none", "", {"state": "none"}),
            ('pending("x")', "", {"state": "pending", "reason": "x"}),
        ],
        ids=["value", "none", "pending"],
    )
    def test_reaches_the_ast_the_state_and_the_ir(
        self, kind: str, written: str, projected: str, state: dict[str, Any],
    ) -> None:
        source = _with_line(kind, written)
        module = _parse(source)
        assert _node(module, kind).forbids == projected
        assert _state(module, kind) == state
        assert _ir_fields(source, module, kind)["forbids"] == state

    @pytest.mark.parametrize("kind", KINDS)
    def test_quoted_none_is_content(self, kind: str) -> None:
        source = _with_line(kind, '"none"')
        module = _parse(source)
        assert _node(module, kind).forbids == "none"
        assert _state(module, kind) == {"state": "value", "value": "none"}
        assert _ir_fields(source, module, kind)["forbids"] == {
            "state": "value", "value": "none",
        }

    @pytest.mark.parametrize("kind", KINDS)
    def test_the_empty_quoted_string_is_handled_as_expects_handles_it(
        self, kind: str,
    ) -> None:
        source = _with_line(kind, '""')
        module = _parse(source)
        reference = _parse(_source(expects='""'))
        assert _state(module, kind) == _state(reference, "nerve", "expects")
        assert _node(module, kind).forbids == reference.nerves[0].expects == ""
        assert _ir_fields(source, module, kind)["forbids"] == {
            "state": "value", "value": "",
        }

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize(
        "raw", ['pending("")', 'pending("   ")', "pending(reason)"],
    )
    def test_a_bad_pending_reason_is_refused_as_for_expects(
        self, kind: str, raw: str,
    ) -> None:
        with pytest.raises(S0maParseError) as reference:
            _parse(_source(expects=raw))
        with pytest.raises(S0maParseError) as excinfo:
            _parse(_with_line(kind, raw))
        assert excinfo.value.code == reference.value.code
        assert excinfo.value.code in {
            "SEMANTIC_PENDING_REASON_EMPTY", "SEMANTIC_PENDING_INVALID",
        }
        assert "forbids" in excinfo.value.remediation

    @pytest.mark.parametrize("kind", KINDS)
    def test_pending_is_debt_as_for_expects(self, kind: str) -> None:
        module = _parse(_with_line(kind, 'pending("not settled yet")'))
        reference = _parse(_source(expects='pending("not settled yet")'))
        for mode, severity in (
            (StrictnessMode.DEV, "warning"),
            (StrictnessMode.STRICT, "error"),
            (StrictnessMode.RELEASE, "error"),
        ):
            debt = [
                item
                for item in validate_module(module, mode=mode)
                if item.code == "SEMANTIC_PENDING_DEBT"
            ]
            expects_debt = [
                item
                for item in validate_module(reference, mode=mode)
                if item.code == "SEMANTIC_PENDING_DEBT"
            ]
            assert len(debt) == 1
            assert debt[0].severity == severity == expects_debt[0].severity
            assert debt[0].context["field"] == "forbids"
            assert debt[0].context["reason"] == "not settled yet"
            assert "'forbids'" in debt[0].message


# ---------------------------------------------------------------------------
# The shapes of a value
# ---------------------------------------------------------------------------


class TestShapes:
    @pytest.mark.parametrize("kind", KINDS)
    def test_a_multi_line_quoted_value_survives(self, kind: str) -> None:
        value = '"Never writes a file.\n        Never reaches the network."'
        source = _with_line(kind, value)
        module = _parse(source)
        expected = "Never writes a file.\nNever reaches the network."
        assert _node(module, kind).forbids == expected
        assert _parse(_source(expects=value)).nerves[0].expects == expected
        assert _ir_fields(source, module, kind)["forbids"] == {
            "state": "value", "value": expected,
        }

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_block_value_survives(self, kind: str) -> None:
        value = (
            "|\n"
            "        Never writes a file.\n"
            "\n"
            "        Never reaches the network:\n"
            "          not even to report a drift."
        )
        source = _with_line(kind, value)
        module = _parse(source)
        written = _node(module, kind).forbids
        assert written == _parse(_source(expects=value)).nerves[0].expects
        assert written.splitlines() == [
            "Never writes a file.",
            "",
            "Never reaches the network:",
            "  not even to report a drift.",
        ]
        assert _ir_fields(source, module, kind)["forbids"] == {
            "state": "value", "value": written,
        }


# ---------------------------------------------------------------------------
# Where the line belongs
# ---------------------------------------------------------------------------


_MODULE_HEAD = (
    "module probe_mod\n"
    "    layer: DOMAIN\n"
    "    version: 1.0.0\n"
    '    intent: "Holds one value."\n'
    "    exports: []\n"
    "    requires: none\n"
    "    uses: none\n"
    "    soft_requires: none\n"
    "    runtime_only_requires: none\n"
    "    deferred_requires: none\n"
    "    exports_helpers: none\n"
)
_FORBIDS = '    forbids: "Never writes a file."\n'


def _cell(extra: str = "") -> str:
    return (
        "\ncell VALUE :: DOMAIN\n"
        "    kind: CONSTANT\n"
        "    visibility: INTERNAL\n"
        '    intent: "Holds the number one."\n'
        '    schema: "int"\n'
        "    invariants: none\n"
        "    covered_by: none\n"
        + extra
        + "    ---\n"
        "    VALUE = 1\n"
    )


_OTHER_KINDS: dict[str, str] = {
    "cell": _MODULE_HEAD + _cell(_FORBIDS),
    "helper": (
        _MODULE_HEAD
        + "\nhelper _double :: DOMAIN\n"
        '    intent: "Doubles a number."\n'
        + _FORBIDS
        + "    ---\n"
        "    def _double(number):\n"
        "        return number * 2\n"
    ),
    "test": (
        _MODULE_HEAD
        + _cell()
        + "\ntest test_value :: DOMAIN\n"
        '    intent: "Checks the value is one."\n'
        "    tests: [VALUE]\n"
        "    expects: none\n"
        "    depends_on: none\n"
        "    mocks: none\n"
        + _FORBIDS
        + "    ---\n"
        "    def test_value():\n"
        "        assert VALUE == 1\n"
    ),
    "module": _MODULE_HEAD + _FORBIDS + _cell(),
    "integration": (
        "module calendar_link\n"
        "    layer: INFRASTRUCTURE\n"
        "    version: 0.1.0\n"
        '    intent: "Connects to a calendar service."\n'
        "    exports: [CalendarLink]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "integration CalendarLink :: INFRASTRUCTURE\n"
        "    version: 0.1.0\n"
        '    intent: "Connects to a calendar service."\n'
        "    factory: F\n"
        "    smoke_test_primary: S\n"
        "    manifest: {}\n"
        "    requires: none\n"
        "    uses: none\n"
        "    raises: none\n"
        + _FORBIDS
    ),
}


class TestWhereTheLineBelongs:
    @pytest.mark.parametrize("kind", sorted(_OTHER_KINDS))
    def test_on_another_kind_it_is_an_unknown_field_naming_nerve_and_ganglion(
        self, kind: str,
    ) -> None:
        source = _OTHER_KINDS[kind]
        _module, warnings = parse_s0ma_with_warnings(
            source, "probe.s0ma", StrictnessMode.DEV,
        )
        found = [item for item in warnings if item.code == "UNKNOWN_FIELD"]
        assert len(found) == 1
        report = found[0]
        assert report.severity == "warning"
        assert report.context["declaration_type"] == kind
        assert report.context["field"] == "forbids"
        assert "suggestion" not in report.context
        assert "'forbids' is a field of ganglion, nerve" in report.remediation
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(source, filename="probe.s0ma", mode=StrictnessMode.STRICT)
        assert excinfo.value.code == "UNKNOWN_FIELD"

    def test_under_a_provides_entry_it_is_the_existing_parse_error(self) -> None:
        source = _source().replace(
            "    provides: none\n",
            "    provides:\n"
            "      - settle:\n"
            '          returns: "int"\n'
            '          forbids: "Never writes a file."\n',
        )
        with pytest.raises(S0maParseError) as excinfo:
            _parse(source)
        assert excinfo.value.code == "PARSE_ERROR"
        assert excinfo.value.context == {
            "sub_field": "forbids",
            "valid": ["expects", "guarantees", "returns"],
        }
        assert "expects, guarantees, returns" in excinfo.value.message


# ---------------------------------------------------------------------------
# The table and the order of the lines
# ---------------------------------------------------------------------------


class TestTable:
    @pytest.mark.parametrize("kind", KINDS)
    def test_the_row_is_required_and_allows_none_and_pending(self, kind: str) -> None:
        assert FIELD_CLASSIFICATIONS[kind]["forbids"] == FieldClassification(
            "semantic-required-state", allow_none=True, allow_pending=True,
        )

    @pytest.mark.parametrize(
        ("kind", "before"), [("nerve", "guarantees"), ("ganglion", "on_anomaly")],
    )
    def test_authored_lines_list_it_directly_after_its_neighbour(
        self, kind: str, before: str,
    ) -> None:
        lines = authored_lines(kind)
        names = [line.name for line in lines]
        assert names.index("forbids") == names.index(before) + 1
        line = lines[names.index("forbids")]
        assert line.field == "forbids"
        assert line.place == "line"
        assert line.classification is not None
        assert line.classification.field_class == "semantic-required-state"
        assert line.classification.allow_value
        assert line.classification.allow_none
        assert line.classification.allow_pending

    def test_no_other_kind_has_the_row(self) -> None:
        owners = sorted(
            kind for kind, rows in FIELD_CLASSIFICATIONS.items() if "forbids" in rows
        )
        assert owners == ["ganglion", "nerve"]


# ---------------------------------------------------------------------------
# Required: the line may not be left out
# ---------------------------------------------------------------------------

_NAMES = {"nerve": "settle", "ganglion": "watch_settle"}


def _refusal(source: str, mode: StrictnessMode = StrictnessMode.DEV) -> S0maParseError:
    with pytest.raises(S0maParseError) as excinfo:
        _parse(source, mode)
    return excinfo.value


class TestRequired:
    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize(
        "mode",
        [StrictnessMode.DEV, StrictnessMode.STRICT, StrictnessMode.RELEASE],
        ids=lambda mode: mode.value,
    )
    def test_an_omitted_line_is_refused_in_every_mode(
        self, kind: str, mode: StrictnessMode,
    ) -> None:
        error = _refusal(_source(**{kind: ""}), mode)
        assert error.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert (
            f"Semantic-required field 'forbids' is omitted from {kind} "
            f"'{_NAMES[kind]}'."
        ) in str(error)
        assert error.remediation == (
            "Author 'forbids:' with a real value, `none`, "
            '`pending("non-empty reason")`; for a legacy project run '
            "`s0ma migrate grammar --apply`."
        )

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_misspelt_line_gets_the_misspelling_hint(self, kind: str) -> None:
        source = _source(**{kind: "    forbid: none\n"})
        number = source.splitlines().index("    forbid: none") + 1
        error = _refusal(source)
        assert error.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert error.remediation.startswith(
            f"Line {number} holds 'forbid:', which is not a field of a {kind}; "
            "'forbids' was probably meant. "
        )
        assert error.context["misspelt_field"] == "forbid"

    def test_migrate_grammar_writes_the_line_on_both_kinds(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        source = tmp_path / "ledger_probe.s0ma"
        source.write_text(_source(nerve="", ganglion=""), encoding="utf-8")
        rc = S0maCLI().run(["migrate", "grammar", "--apply", str(tmp_path)])
        manifest = json.loads(capsys.readouterr().out)
        assert rc == EXIT_SUCCESS
        [change] = manifest["changes"]
        assert change["inserted_fields"] == [
            "nerve:settle.forbids", "ganglion:watch_settle.forbids",
        ]
        module = _parse(source.read_text(encoding="utf-8"), StrictnessMode.RELEASE)
        for kind in KINDS:
            assert _state(module, kind) == {"state": "none"}
        assert plan_grammar_migration(tmp_path).changes == ()


# ---------------------------------------------------------------------------
# The canonical IR and the build
# ---------------------------------------------------------------------------


def _build(project: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, bytes]:
    """Build *project* without the cache and return every file it holds."""
    rc = S0maCLI().run(["build", str(project), "--no-cache", "--quiet"])
    captured = capsys.readouterr()
    assert rc == EXIT_SUCCESS, captured.out + captured.err
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }


class TestBuild:
    def test_the_schema_version_is_unchanged(self) -> None:
        source = _with_line("nerve", '"Never writes a file."')
        payload = build_ir(_parse(source), source_text=source).to_dict()
        assert SCHEMA_VERSION == "3.0.0"
        assert payload["schema_version"] == "3.0.0"

    def test_two_builds_are_byte_equal_and_carry_the_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        project = tmp_path / "project"
        shutil.copytree(_PROJECT, project)
        first = _build(project, capsys)
        second = _build(project, capsys)
        assert first == second
        payload = json.loads(first["ledger_demo.s0ma.json"].decode("utf-8"))
        assert payload["schema_version"] == "3.0.0"
        forbids = {
            item["declaration_type"]: item["fields"]["forbids"]
            for item in payload["components"]
        }
        assert forbids == {
            "nerve": {
                "state": "value",
                "value": "Never writes a file or reaches the network.",
            },
            "ganglion": {"state": "none"},
        }

    def test_inspect_reads_a_build_that_carries_the_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        project = tmp_path / "project"
        shutil.copytree(_PROJECT, project)
        _build(project, capsys)
        ir_path = str(project / "ledger_demo.s0ma.json")
        assert S0maCLI().run(["inspect", ir_path]) == EXIT_SUCCESS
        text = capsys.readouterr().out
        assert "ledger_demo::settle [PUBLIC FUNCTION nerve]" in text
        assert "ledger_demo::watch_settle [INTERNAL ganglion]" in text
        assert S0maCLI().run(["inspect", "--format", "json", ir_path]) == EXIT_SUCCESS
        document = json.loads(capsys.readouterr().out)
        assert {
            item["declaration_type"]: item["fields"]["forbids"]["state"]
            for item in document["components"]
        } == {"nerve": "value", "ganglion": "none"}

    def test_self_context_reads_a_build_that_carries_the_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        project = tmp_path / "project"
        shutil.copytree(_PROJECT, project)
        _build(project, capsys)
        entry = ModuleManifestEntry(
            name="ledger_demo",
            source="ledger_demo.s0ma",
            output="ledger_demo.py",
            ir="ledger_demo.s0ma.json",
            source_map="ledger_demo.s0ma.map",
            source_hash="",
            output_hash="",
            role="source",
            source_root=".",
            logical_path="ledger_demo.s0ma",
        )
        document = build_self_context_document(project, [entry])
        names = json.dumps(document, sort_keys=True)
        assert "ledger_demo::settle" in names
        assert "ledger_demo::watch_settle" in names
