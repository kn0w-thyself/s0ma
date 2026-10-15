"""M3A/M3B tagged semantic-state, requiredness, and canonical IR3 contracts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.cli.main import EXIT_VALIDATION_ERROR, S0maCLI
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.ir import build_ir
from s0ma_dsl.ir.schema import IRSchemaVersionError, validate_ir_schema_version
from s0ma_dsl.parser import parse_s0ma
from s0ma_dsl.semantic.validator import validate_module
from s0ma_dsl.semantic_state import SemanticState, completeness_credit

if TYPE_CHECKING:
    from pathlib import Path

_SOURCE = '''\
module state_demo
    layer: DOMAIN
    version: 1.0.0
    intent: "The word none is ordinary authored content."
    exports: [run]
    requires: {requires}
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve run :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Run deterministically."
    expects: none
    guarantees: "Returns one."
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
    def run():
        return 1
'''


def test_ast_retains_tagged_state_and_internal_primitive_projection() -> None:
    module = parse_s0ma(_SOURCE.format(requires='pending("review dependencies")'))
    state = dict(module.module.semantic_states)["requires"]
    assert state.to_dict() == {"state": "pending", "reason": "review dependencies"}
    assert module.module.requires == ()


def test_quoted_none_is_content_not_control_state() -> None:
    module = parse_s0ma(_SOURCE.format(requires='[json]'))
    assert dict(module.module.semantic_states)["intent"].to_dict() == {
        "state": "value",
        "value": "The word none is ordinary authored content.",
    }


@pytest.mark.parametrize("raw", ['pending("")', 'pending("   ")', "pending(reason)"])
def test_pending_requires_a_non_empty_quoted_reason(raw: str) -> None:
    with pytest.raises(S0maParseError) as excinfo:
        parse_s0ma(_SOURCE.format(requires=raw), filename="pending.s0ma")
    assert excinfo.value.code in {
        "SEMANTIC_PENDING_REASON_EMPTY", "SEMANTIC_PENDING_INVALID"
    }
    assert "pending" in excinfo.value.remediation


def test_required_omission_has_field_specific_machine_remediation() -> None:
    source = _SOURCE.format(requires="[json]").replace("    uses: none\n", "")
    with pytest.raises(S0maParseError) as excinfo:
        parse_s0ma(source, filename="omitted.s0ma")
    diagnostic = excinfo.value
    assert diagnostic.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
    assert diagnostic.context == {
        "declaration_type": "module",
        "declaration_name": "state_demo",
        "field": "uses",
    }
    assert "uses:" in diagnostic.remediation
    assert "s0ma migrate grammar --apply" in diagnostic.remediation


def test_none_is_rejected_for_value_only_semantic_field() -> None:
    source = _SOURCE.format(requires="[json]").replace(
        '    intent: "Run deterministically."', "    intent: none"
    )
    with pytest.raises(S0maParseError) as excinfo:
        parse_s0ma(source, filename="illegal_none.s0ma")
    diagnostic = excinfo.value
    assert diagnostic.code == "SEMANTIC_NONE_NOT_ALLOWED"
    assert diagnostic.context["field"] == "intent"
    assert diagnostic.context["state"] == "none"
    assert "intent: none" in diagnostic.remediation


def test_pending_is_rejected_for_structural_value_field() -> None:
    source = _SOURCE.format(requires="[json]").replace(
        "    version: 1.0.0", '    version: pending("choose version")'
    )
    with pytest.raises(S0maParseError) as excinfo:
        parse_s0ma(source, filename="illegal_pending.s0ma")
    assert excinfo.value.code == "SEMANTIC_PENDING_NOT_ALLOWED"
    assert excinfo.value.context == {
        "declaration_type": "module",
        "declaration_name": "state_demo",
        "field": "version",
        "state": "pending",
    }


def test_authored_derived_field_is_rejected_with_remove_action() -> None:
    source = _SOURCE.format(requires="[json]").replace(
        "    exports: [run]", "    exports: [run]\n    location: forged"
    )
    with pytest.raises(S0maParseError) as excinfo:
        parse_s0ma(source, filename="derived.s0ma")
    diagnostic = excinfo.value
    assert diagnostic.code == "SEMANTIC_DERIVED_FIELD_AUTHORED"
    assert diagnostic.context["field"] == "location"
    assert "Remove the 'location:' field" in diagnostic.remediation


def test_ir3_uses_tagged_semantic_fields() -> None:
    source = _SOURCE.format(requires="[json]")
    payload = build_ir(parse_s0ma(source), source_text=source).to_dict()
    assert payload["schema_version"] == "3.0.0"
    assert payload["imports"]["requires"] == {
        "state": "value", "value": ["json"]
    }
    assert payload["imports"]["uses"] == {"state": "none"}


def test_ir3_serialization_is_repeatable_without_double_wrapping() -> None:
    source = _SOURCE.format(requires='pending("review dependencies")')
    document = build_ir(parse_s0ma(source), source_text=source)
    assert document.to_dict() == document.to_dict()


def test_unknown_ir_major_is_refused_with_migration_and_rebuild_action() -> None:
    with pytest.raises(IRSchemaVersionError) as excinfo:
        validate_ir_schema_version({"schema_version": "4.0.0"})
    message = str(excinfo.value)
    assert "UNSUPPORTED_IR_SCHEMA_MAJOR" in message
    assert "s0ma migrate grammar" in message
    assert "s0ma build" in message


def test_verify_reader_refuses_unknown_ir_major(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "plain.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "future.s0ma.json").write_text(
        json.dumps({"schema_version": "4.0.0"}),
        encoding="utf-8",
    )
    assert S0maCLI().run(["verify", str(tmp_path)]) == EXIT_VALIDATION_ERROR
    assert "UNSUPPORTED_IR_SCHEMA_MAJOR" in capsys.readouterr().err


def test_completeness_credit_respects_the_field_matrix() -> None:
    assert completeness_credit("module", "requires", SemanticState.none()) == 1
    assert completeness_credit("module", "intent", SemanticState.none()) == 0
    assert completeness_credit(
        "module", "requires", SemanticState.pending("review")
    ) == 0


def test_pending_debt_warns_in_dev_and_blocks_strict_release() -> None:
    module = parse_s0ma(_SOURCE.format(requires='pending("review dependencies")'))
    for mode, severity in (
        (StrictnessMode.DEV, "warning"),
        (StrictnessMode.STRICT, "error"),
        (StrictnessMode.RELEASE, "error"),
    ):
        pending = [
            diagnostic
            for diagnostic in validate_module(module, mode=mode)
            if diagnostic.code == "SEMANTIC_PENDING_DEBT"
        ]
        assert len(pending) == 1
        assert pending[0].severity == severity
        assert pending[0].context == {
            "declaration": "state_demo::state_demo",
            "owner": "state_demo::state_demo",
            "field": "requires",
            "reason": "review dependencies",
            "completeness_credit": 0,
        }
