"""Per-operation contracts as a first-class view of a component.

A SERVICE nerve's ``provides:`` entries may each carry ``returns``,
``expects`` and ``guarantees``. The DSL emitter has stored them since
0.15.0 as ``metadata["provides_contracts"]``, where nothing read them.
These tests pin the typed view the registry now offers over that stored
form: :class:`OperationContract`, :attr:`ComponentSpec.provides` and
:attr:`ComponentSpec.provides_contracts`.
"""

from __future__ import annotations

import pytest

from s0ma.exceptions import RegistrationError
from s0ma.models import ComponentSpec, OperationContract
from s0ma.types import ComponentKind, Layer

_CONTRACTS = [
    {"name": "get_spec", "returns": "list[ToolSpec]"},
    {
        "name": "pip_install",
        "returns": "ToolResult",
        "expects": "package str; the code_execution.pip_install grant",
        "guarantees": "runs python -m pip install in the workspace",
    },
    {"name": "run_code"},
]


def _executor(metadata: dict[str, object]) -> ComponentSpec:
    return ComponentSpec(
        name="CodeExecutor",
        kind=ComponentKind.SERVICE,
        layer=Layer.INFRASTRUCTURE,
        intent="Runs Python snippets and installs packages for the agent.",
        metadata=metadata,
    )


class TestOperationContract:
    def test_round_trip_writes_only_authored_slots(self) -> None:
        contract = OperationContract.from_dict(_CONTRACTS[1])
        assert contract.name == "pip_install"
        assert contract.expects == "package str; the code_execution.pip_install grant"
        assert contract.to_dict() == _CONTRACTS[1]
        bare = OperationContract.from_dict({"name": "run_code"})
        assert bare.to_dict() == {"name": "run_code"}
        assert bare.returns is None and bare.expects is None and bare.guarantees is None

    def test_entry_without_a_name_is_refused(self) -> None:
        with pytest.raises(RegistrationError, match="no string 'name'"):
            OperationContract.from_dict({"expects": "anything"})

    def test_non_string_slots_read_as_absent(self) -> None:
        contract = OperationContract.from_dict({"name": "x", "returns": 3})
        assert contract.returns is None


class TestComponentSpecOperations:
    def test_provides_and_contracts_read_from_metadata(self) -> None:
        spec = _executor({
            "provides": ["get_spec", "pip_install", "run_code"],
            "provides_contracts": _CONTRACTS,
        })
        assert spec.provides == ("get_spec", "pip_install", "run_code")
        contracts = spec.provides_contracts
        assert [contract.name for contract in contracts] == [
            "get_spec", "pip_install", "run_code",
        ]
        assert contracts[1].guarantees == "runs python -m pip install in the workspace"

    def test_names_fall_back_to_the_contracts_when_no_flat_list_is_stored(self) -> None:
        spec = _executor({"provides_contracts": _CONTRACTS})
        assert spec.provides == ("get_spec", "pip_install", "run_code")

    def test_component_without_operations_answers_empty(self) -> None:
        spec = _executor({"visibility": "PUBLIC"})
        assert spec.provides == ()
        assert spec.provides_contracts == ()

    def test_mis_shaped_entries_are_skipped_not_raised(self) -> None:
        spec = _executor({
            "provides_contracts": [
                {"name": "ok"},
                "not an object",
                {"expects": "no name"},
            ],
        })
        assert [contract.name for contract in spec.provides_contracts] == ["ok"]

    def test_the_metadata_copy_stays_the_stored_form(self) -> None:
        spec = _executor({"provides_contracts": _CONTRACTS})
        assert spec.to_dict()["metadata"]["provides_contracts"] == _CONTRACTS
        restored = ComponentSpec.from_dict(spec.to_dict())
        assert restored.provides_contracts == spec.provides_contracts
