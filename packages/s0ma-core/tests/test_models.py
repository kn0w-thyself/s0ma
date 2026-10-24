"""Tests for S0ma core data models.

Comprehensive tests for Contract, ResourceProfile, ComponentSpec, Anomaly,
and RegistrySnapshot — covering valid construction, validation failures,
serialization round-trips, and property-based testing with hypothesis.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from s0ma.exceptions import RegistrationError
from s0ma.models import (
    Anomaly,
    ComponentSpec,
    ConfigurableProperty,
    Contract,
    ModuleMetadata,
    PluginRegistration,
    ProtocolContract,
    RegistrySnapshot,
    RelationshipEdge,
    ResourceProfile,
    TestRegistration,
)
from s0ma.types import (
    KNOWN_RELATION_TYPES,
    AnomalyKind,
    AnomalySeverity,
    ComponentKind,
    Layer,
)

# ---------------------------------------------------------------------------
# Helpers: reusable factories for building valid test objects
# ---------------------------------------------------------------------------

def make_contract(**overrides: object) -> Contract:
    """Create a valid Contract with sensible defaults."""
    defaults = {
        "preconditions": ["input is valid"],
        "postconditions": ["returns result"],
        "invariants": ["no side effects on failure"],
        "max_latency_ms": 100.0,
        "error_rate_threshold": 0.01,
        "input_type": "str",
        "output_type": "dict",
    }
    defaults.update(overrides)
    return Contract(**defaults)  # type: ignore[arg-type]


def make_spec(**overrides: object) -> ComponentSpec:
    """Create a valid ComponentSpec with sensible defaults."""
    defaults: dict[str, object] = {
        "name": "TestComponent",
        "kind": ComponentKind.SERVICE,
        "layer": Layer.DOMAIN,
        "intent": "A test component used in unit tests for validation",
        "module_path": "tests.test_models",
        "qualified_name": "tests.test_models.TestComponent",
    }
    defaults.update(overrides)
    return ComponentSpec(**defaults)  # type: ignore[arg-type]


# ===========================================================================
# ConfigurableProperty Tests
# ===========================================================================

class TestConfigurableProperty:
    """Tests for the ConfigurableProperty dataclass."""

    def test_minimal_construction(self) -> None:
        """ConfigurableProperty can be constructed with just type and default."""
        prop = ConfigurableProperty(type="str", default="hello")
        assert prop.type == "str"
        assert prop.default == "hello"
        assert prop.description is None
        assert prop.constraints is None
        assert prop.category is None

    def test_full_construction(self) -> None:
        """ConfigurableProperty can be constructed with all fields."""
        prop = ConfigurableProperty(
            type="int",
            default=10,
            description="The maximum number of items",
            constraints={"min": 1, "max": 100},
            category="Display",
        )
        assert prop.type == "int"
        assert prop.default == 10
        assert prop.description == "The maximum number of items"
        assert prop.constraints == {"min": 1, "max": 100}
        assert prop.category == "Display"

    def test_str_type_valid(self) -> None:
        """Type 'str' with str default is valid."""
        prop = ConfigurableProperty(type="str", default="value")
        assert prop.type == "str"

    def test_int_type_valid(self) -> None:
        """Type 'int' with int default is valid."""
        prop = ConfigurableProperty(type="int", default=42)
        assert prop.default == 42

    def test_float_type_valid(self) -> None:
        """Type 'float' with float default is valid."""
        prop = ConfigurableProperty(type="float", default=3.14)
        assert prop.default == 3.14

    def test_float_type_accepts_int_default(self) -> None:
        """Type 'float' can have an int default (auto-converts)."""
        prop = ConfigurableProperty(type="float", default=10)
        assert prop.default == 10

    def test_bool_type_valid(self) -> None:
        """Type 'bool' with bool default is valid."""
        prop = ConfigurableProperty(type="bool", default=True)
        assert prop.default is True

    def test_enum_type_valid(self) -> None:
        """Type 'enum' with valid constraints is valid."""
        prop = ConfigurableProperty(
            type="enum",
            default="red",
            constraints={"allowed_values": ["red", "green", "blue"]},
        )
        assert prop.type == "enum"
        assert prop.default == "red"

    def test_invalid_type_rejected(self) -> None:
        """Invalid type value raises RegistrationError."""
        with pytest.raises(RegistrationError, match="type must be one of"):
            ConfigurableProperty(type="list", default=[])

    def test_type_mismatch_str(self) -> None:
        """Type 'str' with non-str default raises RegistrationError."""
        with pytest.raises(RegistrationError, match="type mismatch"):
            ConfigurableProperty(type="str", default=42)

    def test_type_mismatch_int(self) -> None:
        """Type 'int' with non-int default raises RegistrationError."""
        with pytest.raises(RegistrationError, match="type mismatch"):
            ConfigurableProperty(type="int", default="not an int")

    def test_type_mismatch_bool_int(self) -> None:
        """Type 'bool' with int default raises RegistrationError.

        In Python, bool is a subclass of int, so we explicitly reject
        an int default for the 'bool' type.
        """
        with pytest.raises(RegistrationError, match="type mismatch"):
            ConfigurableProperty(type="bool", default=1)

    def test_int_type_rejects_bool(self) -> None:
        """Type 'int' rejects bool values (even though bool is int subclass)."""
        with pytest.raises(RegistrationError, match="type mismatch"):
            ConfigurableProperty(type="int", default=True)

    def test_numeric_constraints_valid(self) -> None:
        """Numeric constraints with min < max are valid."""
        prop = ConfigurableProperty(
            type="int", default=5, constraints={"min": 0, "max": 10}
        )
        assert prop.constraints == {"min": 0, "max": 10}

    def test_numeric_constraints_min_gte_max_rejected(self) -> None:
        """Numeric constraints with min >= max are rejected."""
        with pytest.raises(RegistrationError, match="min.*must be less than max"):
            ConfigurableProperty(type="int", default=5, constraints={"min": 10, "max": 5})

    def test_numeric_constraints_min_equals_max_rejected(self) -> None:
        """Numeric constraints with min == max are rejected."""
        with pytest.raises(RegistrationError, match="min.*must be less than max"):
            ConfigurableProperty(type="int", default=5, constraints={"min": 5, "max": 5})

    def test_numeric_constraints_only_min_valid(self) -> None:
        """Numeric constraints with only min (no max) are valid."""
        prop = ConfigurableProperty(type="int", default=5, constraints={"min": 0})
        assert prop.constraints == {"min": 0}

    def test_numeric_constraints_only_max_valid(self) -> None:
        """Numeric constraints with only max (no min) are valid."""
        prop = ConfigurableProperty(type="int", default=5, constraints={"max": 10})
        assert prop.constraints == {"max": 10}

    def test_enum_without_allowed_values_rejected(self) -> None:
        """Type 'enum' without allowed_values in constraints is rejected."""
        with pytest.raises(RegistrationError, match="must have non-empty 'allowed_values'"):
            ConfigurableProperty(type="enum", default="red", constraints={})

    def test_enum_with_empty_allowed_values_rejected(self) -> None:
        """Type 'enum' with empty allowed_values list is rejected."""
        with pytest.raises(RegistrationError, match="must have non-empty 'allowed_values'"):
            ConfigurableProperty(type="enum", default="red", constraints={"allowed_values": []})

    def test_enum_with_non_list_allowed_values_rejected(self) -> None:
        """Type 'enum' with non-list allowed_values is rejected."""
        with pytest.raises(RegistrationError, match="'allowed_values' must be a list"):
            ConfigurableProperty(
                type="enum", default="red", constraints={"allowed_values": "not a list"}
            )

    def test_enum_default_not_in_allowed_values_rejected(self) -> None:
        """Type 'enum' with default not in allowed_values is rejected."""
        with pytest.raises(RegistrationError, match="not in allowed_values"):
            ConfigurableProperty(
                type="enum",
                default="yellow",
                constraints={"allowed_values": ["red", "green", "blue"]},
            )

    def test_to_dict_minimal(self) -> None:
        """to_dict() for minimal ConfigurableProperty includes only required fields."""
        prop = ConfigurableProperty(type="str", default="test")
        d = prop.to_dict()
        assert d == {"type": "str", "default": "test"}

    def test_to_dict_full(self) -> None:
        """to_dict() for full ConfigurableProperty includes all fields."""
        prop = ConfigurableProperty(
            type="int",
            default=10,
            description="Test property",
            constraints={"min": 0, "max": 100},
            category="Testing",
        )
        d = prop.to_dict()
        assert d == {
            "type": "int",
            "default": 10,
            "description": "Test property",
            "constraints": {"min": 0, "max": 100},
            "category": "Testing",
        }

    def test_to_dict_json_serializable(self) -> None:
        """to_dict() output is JSON-serializable."""
        prop = ConfigurableProperty(
            type="enum",
            default="red",
            constraints={"allowed_values": ["red", "green", "blue"]},
        )
        d = prop.to_dict()
        json.dumps(d)  # Should not raise

    def test_from_dict_minimal(self) -> None:
        """from_dict() reconstructs minimal ConfigurableProperty."""
        data = {"type": "str", "default": "test"}
        prop = ConfigurableProperty.from_dict(data)
        assert prop.type == "str"
        assert prop.default == "test"
        assert prop.description is None
        assert prop.constraints is None
        assert prop.category is None

    def test_from_dict_full(self) -> None:
        """from_dict() reconstructs full ConfigurableProperty with all fields."""
        data = {
            "type": "int",
            "default": 10,
            "description": "Test property",
            "constraints": {"min": 0, "max": 100},
            "category": "Testing",
        }
        prop = ConfigurableProperty.from_dict(data)
        assert prop.type == "int"
        assert prop.default == 10
        assert prop.description == "Test property"
        assert prop.constraints == {"min": 0, "max": 100}
        assert prop.category == "Testing"

    def test_from_dict_round_trip_minimal(self) -> None:
        """from_dict(to_dict()) round-trip preserves minimal ConfigurableProperty."""
        original = ConfigurableProperty(type="bool", default=True)
        reconstructed = ConfigurableProperty.from_dict(original.to_dict())
        assert reconstructed == original

    def test_from_dict_round_trip_full(self) -> None:
        """from_dict(to_dict()) round-trip preserves full ConfigurableProperty."""
        original = ConfigurableProperty(
            type="float",
            default=3.14,
            description="Pi approximation",
            constraints={"min": 0.0, "max": 10.0},
            category="Math",
        )
        reconstructed = ConfigurableProperty.from_dict(original.to_dict())
        assert reconstructed == original

    def test_from_dict_missing_type_raises(self) -> None:
        """from_dict() raises if 'type' field is missing."""
        data = {"default": "test"}
        with pytest.raises(RegistrationError, match="'type' field is required"):
            ConfigurableProperty.from_dict(data)

    def test_from_dict_missing_default_raises(self) -> None:
        """from_dict() raises if 'default' field is missing."""
        data = {"type": "str"}
        with pytest.raises(RegistrationError, match="'default' field is required"):
            ConfigurableProperty.from_dict(data)

    def test_from_dict_invalid_data_raises(self) -> None:
        """from_dict() raises if data fails validation."""
        data = {"type": "invalid_type", "default": "test"}
        with pytest.raises(RegistrationError):
            ConfigurableProperty.from_dict(data)

    def test_configurable_property_is_frozen(self) -> None:
        """ConfigurableProperty is immutable (frozen dataclass)."""
        prop = ConfigurableProperty(type="str", default="test")
        with pytest.raises(AttributeError):
            prop.default = "changed"  # type: ignore[misc]


# ===========================================================================
# ProtocolContract Tests
# ===========================================================================

class TestProtocolContract:
    """Tests for the ProtocolContract dataclass."""

    def test_minimal_construction(self) -> None:
        """ProtocolContract can be constructed with required fields only."""
        proto = ProtocolContract(
            protocol_type="websocket",
            message_types={"ping": {"type": "heartbeat"}},
        )
        assert proto.protocol_type == "websocket"
        assert proto.message_types == {"ping": {"type": "heartbeat"}}
        assert proto.description is None

    def test_full_construction(self) -> None:
        """ProtocolContract can be constructed with all fields."""
        proto = ProtocolContract(
            protocol_type="websocket",
            message_types={
                "message": {"role": "str", "content": "str"},
                "error": {"code": "int", "message": "str"},
            },
            description="Real-time chat protocol over WebSocket",
        )
        assert proto.protocol_type == "websocket"
        assert len(proto.message_types) == 2
        assert proto.description == "Real-time chat protocol over WebSocket"

    def test_rest_protocol_type(self) -> None:
        """ProtocolContract supports REST protocol type."""
        proto = ProtocolContract(
            protocol_type="rest",
            message_types={
                "GET /users": {"response": "list[User]"},
                "POST /users": {"body": "CreateUserRequest", "response": "User"},
            },
        )
        assert proto.protocol_type == "rest"

    def test_grpc_protocol_type(self) -> None:
        """ProtocolContract supports gRPC protocol type."""
        proto = ProtocolContract(
            protocol_type="grpc",
            message_types={
                "GetUser": {"request": "UserId", "response": "User"},
            },
        )
        assert proto.protocol_type == "grpc"

    def test_ipc_protocol_type(self) -> None:
        """ProtocolContract supports IPC protocol type."""
        proto = ProtocolContract(
            protocol_type="ipc",
            message_types={"signal": {"type": "shutdown"}},
        )
        assert proto.protocol_type == "ipc"

    def test_is_frozen(self) -> None:
        """ProtocolContract is immutable (frozen dataclass)."""
        proto = ProtocolContract(
            protocol_type="websocket",
            message_types={"msg": {}},
        )
        with pytest.raises(AttributeError):
            proto.protocol_type = "rest"  # type: ignore[misc]

    def test_to_dict_minimal(self) -> None:
        """to_dict() for minimal ProtocolContract includes only required fields."""
        proto = ProtocolContract(
            protocol_type="websocket",
            message_types={"ping": {"type": "heartbeat"}},
        )
        d = proto.to_dict()
        assert d == {
            "protocol_type": "websocket",
            "message_types": {"ping": {"type": "heartbeat"}},
        }
        assert "description" not in d

    def test_to_dict_full(self) -> None:
        """to_dict() for full ProtocolContract includes all fields."""
        proto = ProtocolContract(
            protocol_type="websocket",
            message_types={
                "message": {"role": "str", "content": "str"},
                "error": {"code": "int"},
            },
            description="Chat protocol",
        )
        d = proto.to_dict()
        assert d["protocol_type"] == "websocket"
        assert d["description"] == "Chat protocol"
        assert len(d["message_types"]) == 2

    def test_to_dict_json_serializable(self) -> None:
        """to_dict() output is JSON-serializable."""
        proto = ProtocolContract(
            protocol_type="rest",
            message_types={"GET /api": {"response": "dict"}},
            description="REST API contract",
        )
        d = proto.to_dict()
        json.dumps(d)  # Should not raise

    def test_from_dict_minimal(self) -> None:
        """from_dict() reconstructs minimal ProtocolContract."""
        data = {
            "protocol_type": "websocket",
            "message_types": {"ping": {}},
        }
        proto = ProtocolContract.from_dict(data)
        assert proto.protocol_type == "websocket"
        assert proto.message_types == {"ping": {}}
        assert proto.description is None

    def test_from_dict_full(self) -> None:
        """from_dict() reconstructs full ProtocolContract with all fields."""
        data = {
            "protocol_type": "grpc",
            "message_types": {"GetUser": {"request": "UserId"}},
            "description": "User service gRPC protocol",
        }
        proto = ProtocolContract.from_dict(data)
        assert proto.protocol_type == "grpc"
        assert proto.message_types == {"GetUser": {"request": "UserId"}}
        assert proto.description == "User service gRPC protocol"

    def test_from_dict_missing_protocol_type_raises(self) -> None:
        """from_dict() raises if protocol_type is missing."""
        data = {"message_types": {"ping": {}}}
        with pytest.raises(RegistrationError, match="'protocol_type' field is required"):
            ProtocolContract.from_dict(data)

    def test_from_dict_missing_message_types_raises(self) -> None:
        """from_dict() raises if message_types is missing."""
        data = {"protocol_type": "websocket"}
        with pytest.raises(RegistrationError, match="'message_types' field is required"):
            ProtocolContract.from_dict(data)

    def test_from_dict_round_trip_minimal(self) -> None:
        """from_dict(to_dict()) round-trip preserves minimal ProtocolContract."""
        original = ProtocolContract(
            protocol_type="websocket",
            message_types={"ping": {"type": "heartbeat"}},
        )
        reconstructed = ProtocolContract.from_dict(original.to_dict())
        assert reconstructed == original

    def test_from_dict_round_trip_full(self) -> None:
        """from_dict(to_dict()) round-trip preserves full ProtocolContract."""
        original = ProtocolContract(
            protocol_type="websocket",
            message_types={
                "message": {"role": "str", "content": "str"},
                "plan": {"steps": "list[str]", "status": "str"},
                "error": {"code": "int", "message": "str"},
            },
            description="Real-time chat protocol with planning support",
        )
        reconstructed = ProtocolContract.from_dict(original.to_dict())
        assert reconstructed == original

    def test_invalid_field_raises_registration_error(self) -> None:
        """ProtocolContract with invalid field raises RegistrationError."""
        with pytest.raises(
            RegistrationError,
            match="ProtocolContract\\(\\) received unexpected keyword argument",
        ):
            ProtocolContract(
                protocol_type="ws",
                message_types={},
                invalid_field="bad",  # type: ignore[call-arg]
            )

    def test_error_message_lists_valid_fields(self) -> None:
        """ProtocolContract error message lists valid fields."""
        try:
            ProtocolContract(
                protocol_type="ws",
                message_types={},
                bad_field="value",  # type: ignore[call-arg]
            )
        except RegistrationError as e:
            error_msg = str(e)
            assert "protocol_type" in error_msg
            assert "message_types" in error_msg
            assert "description" in error_msg


# ===========================================================================
# Contract Tests
# ===========================================================================

class TestContract:
    """Tests for the Contract dataclass."""

    def test_default_contract_is_valid(self) -> None:
        """An empty Contract (all defaults) should pass validation."""
        c = Contract()
        c.validate()  # should not raise

    def test_full_contract_construction(self) -> None:
        """A fully-specified Contract stores all fields correctly."""
        c = make_contract()
        assert c.preconditions == ["input is valid"]
        assert c.postconditions == ["returns result"]
        assert c.invariants == ["no side effects on failure"]
        assert c.max_latency_ms == 100.0
        assert c.error_rate_threshold == 0.01
        assert c.input_type == "str"
        assert c.output_type == "dict"

    def test_negative_latency_rejected(self) -> None:
        """max_latency_ms must be positive."""
        c = Contract(max_latency_ms=-5.0)
        with pytest.raises(RegistrationError, match="max_latency_ms must be positive"):
            c.validate()

    def test_zero_latency_rejected(self) -> None:
        """max_latency_ms=0 is not positive and should be rejected."""
        c = Contract(max_latency_ms=0.0)
        with pytest.raises(RegistrationError, match="max_latency_ms must be positive"):
            c.validate()

    def test_error_rate_above_one_rejected(self) -> None:
        """error_rate_threshold must be <= 1.0."""
        c = Contract(error_rate_threshold=1.5)
        with pytest.raises(RegistrationError, match="error_rate_threshold must be between"):
            c.validate()

    def test_error_rate_negative_rejected(self) -> None:
        """error_rate_threshold must be >= 0.0."""
        c = Contract(error_rate_threshold=-0.1)
        with pytest.raises(RegistrationError, match="error_rate_threshold must be between"):
            c.validate()

    def test_error_rate_boundary_zero(self) -> None:
        """error_rate_threshold=0.0 is valid (zero tolerance)."""
        c = Contract(error_rate_threshold=0.0)
        c.validate()

    def test_error_rate_boundary_one(self) -> None:
        """error_rate_threshold=1.0 is valid (accept all errors)."""
        c = Contract(error_rate_threshold=1.0)
        c.validate()

    def test_contract_to_dict(self) -> None:
        """to_dict() produces a JSON-serializable dictionary."""
        c = make_contract()
        d = c.to_dict()
        assert d["preconditions"] == ["input is valid"]
        assert d["max_latency_ms"] == 100.0
        assert d["input_type"] == "str"
        # Verify JSON-serializable
        json.dumps(d)

    def test_contract_to_dict_omits_none_optional_fields(self) -> None:
        """to_dict() omits optional fields that are None."""
        c = Contract()
        d = c.to_dict()
        assert "max_latency_ms" not in d
        assert "error_rate_threshold" not in d
        assert "input_type" not in d
        assert "output_type" not in d

    def test_contract_is_frozen(self) -> None:
        """Contract is immutable (frozen dataclass)."""
        c = Contract()
        with pytest.raises(AttributeError):
            c.max_latency_ms = 999.0  # type: ignore[misc]

    def test_contract_with_no_configurable_properties(self) -> None:
        """Contract without configurable_properties (default None) is valid."""
        c = Contract()
        assert c.configurable_properties is None
        c.validate()

    def test_contract_with_configurable_properties(self) -> None:
        """Contract with valid configurable_properties is valid."""
        props = {
            "theme_color": ConfigurableProperty(type="str", default="blue"),
            "max_items": ConfigurableProperty(type="int", default=10),
        }
        c = Contract(configurable_properties=props)
        assert c.configurable_properties == props
        c.validate()

    def test_contract_to_dict_includes_configurable_properties(self) -> None:
        """to_dict() includes configurable_properties when present."""
        props = {
            "theme_color": ConfigurableProperty(
                type="str",
                default="blue",
                description="Primary theme color",
            ),
            "show_header": ConfigurableProperty(type="bool", default=True),
        }
        c = Contract(configurable_properties=props)
        d = c.to_dict()

        assert "configurable_properties" in d
        assert d["configurable_properties"]["theme_color"]["type"] == "str"
        assert d["configurable_properties"]["theme_color"]["default"] == "blue"
        assert d["configurable_properties"]["show_header"]["type"] == "bool"
        assert d["configurable_properties"]["show_header"]["default"] is True

    def test_contract_to_dict_omits_configurable_properties_when_none(self) -> None:
        """to_dict() omits configurable_properties when None."""
        c = Contract()
        d = c.to_dict()
        assert "configurable_properties" not in d

    def test_contract_to_dict_with_configurable_properties_is_json_serializable(
        self,
    ) -> None:
        """to_dict() with configurable_properties is JSON-serializable."""
        props = {
            "max_items": ConfigurableProperty(
                type="int",
                default=10,
                constraints={"min": 1, "max": 100},
            ),
        }
        c = make_contract(configurable_properties=props)
        d = c.to_dict()
        json.dumps(d)  # Should not raise

    def test_contract_with_invalid_configurable_property_type_rejected(self) -> None:
        """Contract with invalid configurable property type raises RegistrationError."""
        # ConfigurableProperty validation happens in __post_init__,
        # so constructing an invalid property should fail
        with pytest.raises(RegistrationError, match="type must be one of"):
            ConfigurableProperty(type="invalid_type", default="value")

    def test_contract_with_configurable_property_type_mismatch_rejected(self) -> None:
        """Contract with configurable property type/default mismatch raises RegistrationError."""
        with pytest.raises(RegistrationError, match="type mismatch"):
            # Should fail at ConfigurableProperty construction time
            ConfigurableProperty(type="int", default="not an int")

    def test_contract_with_invalid_numeric_constraints_rejected(self) -> None:
        """Contract with invalid numeric constraints raises RegistrationError."""
        with pytest.raises(RegistrationError, match="min.*must be less than max"):
            ConfigurableProperty(
                type="int",
                default=5,
                constraints={"min": 10, "max": 5}
            )

    def test_contract_with_invalid_enum_constraints_rejected(self) -> None:
        """Contract with invalid enum constraints raises RegistrationError."""
        with pytest.raises(RegistrationError, match="must have non-empty 'allowed_values'"):
            ConfigurableProperty(
                type="enum",
                default="red",
                constraints={}  # Missing allowed_values
            )

    def test_contract_with_enum_default_not_in_allowed_values_rejected(self) -> None:
        """Contract with enum default not in allowed_values raises RegistrationError."""
        with pytest.raises(RegistrationError, match="not in allowed_values"):
            ConfigurableProperty(
                type="enum",
                default="yellow",
                constraints={"allowed_values": ["red", "green", "blue"]}
            )

    def test_contract_validate_with_valid_configurable_properties(self) -> None:
        """Contract.validate() succeeds with valid configurable_properties."""
        props = {
            "theme": ConfigurableProperty(type="str", default="dark"),
            "count": ConfigurableProperty(
                type="int", default=10, constraints={"min": 0, "max": 100},
            ),
            "enabled": ConfigurableProperty(type="bool", default=True),
        }
        c = Contract(configurable_properties=props)
        c.validate()  # Should not raise

    def test_from_dict_minimal(self) -> None:
        """from_dict() reconstructs minimal Contract with defaults."""
        data = {}  # Empty dict should use all defaults
        contract = Contract.from_dict(data)
        assert contract.preconditions == []
        assert contract.postconditions == []
        assert contract.invariants == []
        assert contract.max_latency_ms is None
        assert contract.error_rate_threshold is None
        assert contract.input_type is None
        assert contract.output_type is None
        assert contract.configurable_properties is None

    def test_from_dict_full(self) -> None:
        """from_dict() reconstructs full Contract with all fields."""
        data = {
            "preconditions": ["input valid"],
            "postconditions": ["output valid"],
            "invariants": ["no side effects"],
            "max_latency_ms": 50.0,
            "error_rate_threshold": 0.05,
            "input_type": "str",
            "output_type": "dict",
        }
        contract = Contract.from_dict(data)
        assert contract.preconditions == ["input valid"]
        assert contract.postconditions == ["output valid"]
        assert contract.invariants == ["no side effects"]
        assert contract.max_latency_ms == 50.0
        assert contract.error_rate_threshold == 0.05
        assert contract.input_type == "str"
        assert contract.output_type == "dict"

    def test_from_dict_with_configurable_properties(self) -> None:
        """from_dict() reconstructs Contract with configurable_properties."""
        data = {
            "configurable_properties": {
                "theme_color": {
                    "type": "str",
                    "default": "blue",
                    "description": "Theme color",
                },
                "max_items": {
                    "type": "int",
                    "default": 10,
                    "constraints": {"min": 1, "max": 100},
                },
            }
        }
        contract = Contract.from_dict(data)
        assert contract.configurable_properties is not None
        assert "theme_color" in contract.configurable_properties
        assert "max_items" in contract.configurable_properties
        assert contract.configurable_properties["theme_color"].type == "str"
        assert contract.configurable_properties["theme_color"].default == "blue"
        assert contract.configurable_properties["max_items"].default == 10

    def test_from_dict_round_trip_minimal(self) -> None:
        """from_dict(to_dict()) round-trip preserves minimal Contract."""
        original = Contract()
        reconstructed = Contract.from_dict(original.to_dict())
        # Compare field by field since Contract doesn't have __eq__
        assert reconstructed.preconditions == original.preconditions
        assert reconstructed.postconditions == original.postconditions
        assert reconstructed.invariants == original.invariants
        assert reconstructed.max_latency_ms == original.max_latency_ms
        assert reconstructed.error_rate_threshold == original.error_rate_threshold
        assert reconstructed.input_type == original.input_type
        assert reconstructed.output_type == original.output_type
        assert reconstructed.configurable_properties == original.configurable_properties

    def test_from_dict_round_trip_full(self) -> None:
        """from_dict(to_dict()) round-trip preserves full Contract."""
        props = {
            "theme_color": ConfigurableProperty(
                type="str",
                default="blue",
                description="Primary theme color",
            ),
            "max_items": ConfigurableProperty(
                type="int",
                default=10,
                constraints={"min": 1, "max": 100},
            ),
        }
        original = make_contract(configurable_properties=props)
        reconstructed = Contract.from_dict(original.to_dict())
        assert reconstructed.preconditions == original.preconditions
        assert reconstructed.postconditions == original.postconditions
        assert reconstructed.invariants == original.invariants
        assert reconstructed.max_latency_ms == original.max_latency_ms
        assert reconstructed.error_rate_threshold == original.error_rate_threshold
        assert reconstructed.input_type == original.input_type
        assert reconstructed.output_type == original.output_type
        assert reconstructed.configurable_properties == original.configurable_properties

    def test_from_dict_validates_result(self) -> None:
        """from_dict() calls validate() on the reconstructed Contract."""
        # Invalid latency should be caught
        data = {"max_latency_ms": -5.0}
        with pytest.raises(RegistrationError, match="max_latency_ms must be positive"):
            Contract.from_dict(data)

    # --- Protocol contract tests ---

    def test_contract_with_no_protocol(self) -> None:
        """Contract without protocol (default None) is valid."""
        c = Contract()
        assert c.protocol is None
        c.validate()

    def test_contract_with_protocol(self) -> None:
        """Contract with a valid protocol is valid."""
        proto = ProtocolContract(
            protocol_type="websocket",
            message_types={
                "message": {"role": "str", "content": "str"},
                "error": {"code": "int", "message": "str"},
            },
            description="Chat WebSocket protocol",
        )
        c = Contract(protocol=proto)
        assert c.protocol is not None
        assert c.protocol.protocol_type == "websocket"
        c.validate()

    def test_contract_to_dict_includes_protocol(self) -> None:
        """to_dict() includes protocol when present."""
        proto = ProtocolContract(
            protocol_type="websocket",
            message_types={"ping": {"type": "heartbeat"}},
        )
        c = Contract(protocol=proto)
        d = c.to_dict()
        assert "protocol" in d
        assert d["protocol"]["protocol_type"] == "websocket"
        assert d["protocol"]["message_types"] == {"ping": {"type": "heartbeat"}}

    def test_contract_to_dict_omits_protocol_when_none(self) -> None:
        """to_dict() omits protocol when None."""
        c = Contract()
        d = c.to_dict()
        assert "protocol" not in d

    def test_contract_to_dict_with_protocol_is_json_serializable(self) -> None:
        """to_dict() with protocol is JSON-serializable."""
        proto = ProtocolContract(
            protocol_type="rest",
            message_types={"GET /api": {"response": "dict"}},
            description="REST API",
        )
        c = Contract(protocol=proto)
        d = c.to_dict()
        json.dumps(d)  # Should not raise

    def test_from_dict_with_protocol(self) -> None:
        """from_dict() reconstructs Contract with protocol."""
        data = {
            "protocol": {
                "protocol_type": "websocket",
                "message_types": {
                    "message": {"role": "str", "content": "str"},
                },
                "description": "Chat protocol",
            },
        }
        contract = Contract.from_dict(data)
        assert contract.protocol is not None
        assert contract.protocol.protocol_type == "websocket"
        assert "message" in contract.protocol.message_types
        assert contract.protocol.description == "Chat protocol"

    def test_from_dict_round_trip_with_protocol(self) -> None:
        """from_dict(to_dict()) round-trip preserves protocol."""
        proto = ProtocolContract(
            protocol_type="websocket",
            message_types={
                "message": {"role": "str", "content": "str"},
                "plan": {"steps": "list"},
            },
            description="Full chat protocol",
        )
        original = Contract(
            preconditions=["connection established"],
            protocol=proto,
        )
        reconstructed = Contract.from_dict(original.to_dict())
        assert reconstructed.protocol is not None
        assert reconstructed.protocol == original.protocol
        assert reconstructed.preconditions == original.preconditions

    def test_contract_with_both_configurable_properties_and_protocol(self) -> None:
        """Contract can have both configurable_properties and protocol."""
        props = {
            "theme": ConfigurableProperty(type="str", default="dark"),
        }
        proto = ProtocolContract(
            protocol_type="websocket",
            message_types={"msg": {"text": "str"}},
        )
        c = Contract(configurable_properties=props, protocol=proto)
        assert c.configurable_properties is not None
        assert c.protocol is not None
        c.validate()

        # Round-trip
        d = c.to_dict()
        assert "configurable_properties" in d
        assert "protocol" in d
        reconstructed = Contract.from_dict(d)
        assert reconstructed.configurable_properties == c.configurable_properties
        assert reconstructed.protocol == c.protocol


# ===========================================================================
# ResourceProfile Tests
# ===========================================================================

class TestResourceProfile:
    """Tests for the ResourceProfile dataclass."""

    def test_default_profile_is_valid(self) -> None:
        """An empty ResourceProfile (all None) should construct fine."""
        rp = ResourceProfile()
        assert rp.expected_memory_mb is None
        assert rp.expected_latency_p50_ms is None

    def test_full_profile_construction(self) -> None:
        """A fully-specified ResourceProfile stores all fields correctly."""
        rp = ResourceProfile(
            expected_memory_mb=256.0,
            expected_latency_p50_ms=10.0,
            expected_latency_p99_ms=50.0,
            expected_error_rate=0.001,
            expected_call_frequency_per_min=1000.0,
        )
        assert rp.expected_memory_mb == 256.0
        assert rp.expected_latency_p99_ms == 50.0
        assert rp.expected_error_rate == 0.001

    def test_negative_memory_rejected(self) -> None:
        """Negative memory expectation is invalid."""
        with pytest.raises(RegistrationError, match="expected_memory_mb must be non-negative"):
            ResourceProfile(expected_memory_mb=-1.0)

    def test_negative_latency_rejected(self) -> None:
        """Negative latency expectation is invalid."""
        with pytest.raises(
            RegistrationError, match="expected_latency_p50_ms must be non-negative"
        ):
            ResourceProfile(expected_latency_p50_ms=-0.5)

    def test_error_rate_above_one_rejected(self) -> None:
        """expected_error_rate must be <= 1.0."""
        with pytest.raises(RegistrationError, match="expected_error_rate must be between"):
            ResourceProfile(expected_error_rate=2.0)

    def test_error_rate_negative_rejected(self) -> None:
        """expected_error_rate must be >= 0.0."""
        with pytest.raises(RegistrationError, match="expected_error_rate must be between"):
            ResourceProfile(expected_error_rate=-0.01)

    def test_physical_bounds_construction_and_round_trip(self) -> None:
        """Physical bounds (ADR-003 §4) store and round-trip through dicts."""
        rp = ResourceProfile(
            expected_max_current_ma=350.0,
            expected_max_temperature_c=75.0,
            expected_min_voltage_v=4.8,
        )
        data = rp.to_dict()
        assert data == {
            "expected_max_current_ma": 350.0,
            "expected_max_temperature_c": 75.0,
            "expected_min_voltage_v": 4.8,
        }
        assert ResourceProfile.from_dict(data) == rp

    def test_from_dict_tolerates_pre_physical_payloads(self) -> None:
        """Profiles persisted before the physical fields load unchanged."""
        rp = ResourceProfile.from_dict({"expected_memory_mb": 64.0})
        assert rp.expected_memory_mb == 64.0
        assert rp.expected_max_current_ma is None
        assert rp.expected_max_temperature_c is None
        assert rp.expected_min_voltage_v is None

    def test_negative_current_rejected(self) -> None:
        """expected_max_current_ma must be non-negative."""
        with pytest.raises(
            RegistrationError,
            match="expected_max_current_ma must be non-negative",
        ):
            ResourceProfile(expected_max_current_ma=-1.0)

    def test_negative_min_voltage_rejected(self) -> None:
        """expected_min_voltage_v must be non-negative."""
        with pytest.raises(
            RegistrationError,
            match="expected_min_voltage_v must be non-negative",
        ):
            ResourceProfile(expected_min_voltage_v=-0.1)

    def test_sub_zero_temperature_bound_is_valid(self) -> None:
        """Sub-zero temperature bounds are physically legitimate."""
        rp = ResourceProfile(expected_max_temperature_c=-10.0)
        assert rp.expected_max_temperature_c == -10.0

    def test_zero_values_are_valid(self) -> None:
        """Zero is a valid value for resource expectations."""
        rp = ResourceProfile(
            expected_memory_mb=0.0,
            expected_latency_p50_ms=0.0,
            expected_error_rate=0.0,
        )
        assert rp.expected_memory_mb == 0.0

    def test_to_dict_omits_none_fields(self) -> None:
        """to_dict() only includes non-None fields."""
        rp = ResourceProfile(expected_memory_mb=128.0)
        d = rp.to_dict()
        assert d == {"expected_memory_mb": 128.0}

    def test_to_dict_full(self) -> None:
        """to_dict() includes all set fields."""
        rp = ResourceProfile(
            expected_memory_mb=256.0,
            expected_latency_p50_ms=10.0,
            expected_latency_p99_ms=50.0,
            expected_error_rate=0.01,
            expected_call_frequency_per_min=500.0,
        )
        d = rp.to_dict()
        assert len(d) == 5
        json.dumps(d)  # JSON-serializable

    def test_profile_is_frozen(self) -> None:
        """ResourceProfile is immutable (frozen dataclass)."""
        rp = ResourceProfile()
        with pytest.raises(AttributeError):
            rp.expected_memory_mb = 999.0  # type: ignore[misc]

    def test_from_dict_minimal(self) -> None:
        """from_dict() reconstructs minimal ResourceProfile with all None."""
        data = {}
        profile = ResourceProfile.from_dict(data)
        assert profile.expected_memory_mb is None
        assert profile.expected_latency_p50_ms is None
        assert profile.expected_latency_p99_ms is None
        assert profile.expected_error_rate is None
        assert profile.expected_call_frequency_per_min is None

    def test_from_dict_full(self) -> None:
        """from_dict() reconstructs full ResourceProfile with all fields."""
        data = {
            "expected_memory_mb": 512.0,
            "expected_latency_p50_ms": 15.0,
            "expected_latency_p99_ms": 75.0,
            "expected_error_rate": 0.02,
            "expected_call_frequency_per_min": 2000.0,
        }
        profile = ResourceProfile.from_dict(data)
        assert profile.expected_memory_mb == 512.0
        assert profile.expected_latency_p50_ms == 15.0
        assert profile.expected_latency_p99_ms == 75.0
        assert profile.expected_error_rate == 0.02
        assert profile.expected_call_frequency_per_min == 2000.0

    def test_from_dict_round_trip_minimal(self) -> None:
        """from_dict(to_dict()) round-trip preserves minimal ResourceProfile."""
        original = ResourceProfile()
        reconstructed = ResourceProfile.from_dict(original.to_dict())
        assert reconstructed.expected_memory_mb == original.expected_memory_mb
        assert reconstructed.expected_latency_p50_ms == original.expected_latency_p50_ms
        assert reconstructed.expected_latency_p99_ms == original.expected_latency_p99_ms
        assert reconstructed.expected_error_rate == original.expected_error_rate
        assert (
            reconstructed.expected_call_frequency_per_min
            == original.expected_call_frequency_per_min
        )

    def test_from_dict_round_trip_full(self) -> None:
        """from_dict(to_dict()) round-trip preserves full ResourceProfile."""
        original = ResourceProfile(
            expected_memory_mb=256.0,
            expected_latency_p50_ms=10.0,
            expected_latency_p99_ms=50.0,
            expected_error_rate=0.001,
            expected_call_frequency_per_min=1000.0,
        )
        reconstructed = ResourceProfile.from_dict(original.to_dict())
        assert reconstructed.expected_memory_mb == original.expected_memory_mb
        assert reconstructed.expected_latency_p50_ms == original.expected_latency_p50_ms
        assert reconstructed.expected_latency_p99_ms == original.expected_latency_p99_ms
        assert reconstructed.expected_error_rate == original.expected_error_rate
        assert (
            reconstructed.expected_call_frequency_per_min
            == original.expected_call_frequency_per_min
        )

    def test_from_dict_validates_result(self) -> None:
        """from_dict() validates the reconstructed ResourceProfile."""
        # Invalid negative memory should be caught
        data = {"expected_memory_mb": -5.0}
        with pytest.raises(RegistrationError, match="must be non-negative"):
            ResourceProfile.from_dict(data)


# ===========================================================================
# ComponentSpec Tests
# ===========================================================================

class TestComponentSpec:
    """Tests for the ComponentSpec dataclass."""

    def test_valid_construction(self) -> None:
        """A valid ComponentSpec constructs without error."""
        spec = make_spec()
        assert spec.name == "TestComponent"
        assert spec.kind == ComponentKind.SERVICE
        assert spec.layer == Layer.DOMAIN
        assert len(spec.intent) >= 10

    def test_registered_at_is_set_automatically(self) -> None:
        """registered_at defaults to approximately now (UTC)."""
        before = datetime.now(UTC)
        spec = make_spec()
        after = datetime.now(UTC)
        assert before <= spec.registered_at <= after

    def test_default_contracts(self) -> None:
        """Default contracts is an empty Contract."""
        spec = make_spec()
        assert spec.contracts == Contract()

    def test_default_dependencies(self) -> None:
        """Default dependencies is an empty list."""
        spec = make_spec()
        assert spec.dependencies == []

    def test_default_version(self) -> None:
        """Default version is '0.1.0'."""
        spec = make_spec()
        assert spec.version == "0.1.0"

    def test_empty_name_rejected(self) -> None:
        """Component name must not be empty."""
        with pytest.raises(RegistrationError, match="name must not be empty"):
            make_spec(name="")

    def test_whitespace_name_rejected(self) -> None:
        """Component name must not contain spaces."""
        with pytest.raises(RegistrationError, match="must not contain whitespace"):
            make_spec(name="My Component")

    def test_tab_in_name_rejected(self) -> None:
        """Component name must not contain tabs."""
        with pytest.raises(RegistrationError, match="must not contain whitespace"):
            make_spec(name="My\tComponent")

    def test_newline_in_name_rejected(self) -> None:
        """Component name must not contain newlines."""
        with pytest.raises(RegistrationError, match="must not contain whitespace"):
            make_spec(name="My\nComponent")

    def test_short_intent_rejected(self) -> None:
        """Intent must be at least 10 characters."""
        with pytest.raises(RegistrationError, match="intent must be at least 10 characters"):
            make_spec(intent="Too short")

    def test_intent_exactly_10_chars(self) -> None:
        """Intent of exactly 10 characters is valid."""
        spec = make_spec(intent="0123456789")
        assert len(spec.intent) == 10

    def test_self_dependency_rejected(self) -> None:
        """A component cannot depend on itself."""
        with pytest.raises(RegistrationError, match="cannot depend on itself"):
            make_spec(name="Foo", dependencies=["Bar", "Foo"])

    def test_invalid_contract_caught_at_construction(self) -> None:
        """If a ComponentSpec has an invalid contract, it fails at __post_init__."""
        bad_contract = Contract(max_latency_ms=-10.0)
        with pytest.raises(RegistrationError, match="max_latency_ms must be positive"):
            make_spec(contracts=bad_contract)

    def test_dependencies_stored_correctly(self) -> None:
        """Declared dependencies are stored as-is."""
        spec = make_spec(dependencies=["DatabaseAdapter", "Logger"])
        assert spec.dependencies == ["DatabaseAdapter", "Logger"]

    def test_metadata_extensible(self) -> None:
        """metadata accepts arbitrary key-value pairs."""
        spec = make_spec(metadata={"owner": "team-a", "priority": 1})
        assert spec.metadata["owner"] == "team-a"
        assert spec.metadata["priority"] == 1

    def test_resource_profile_attached(self) -> None:
        """A resource profile can be attached to a ComponentSpec."""
        rp = ResourceProfile(expected_memory_mb=512.0)
        spec = make_spec(resource_profile=rp)
        assert spec.resource_profile is not None
        assert spec.resource_profile.expected_memory_mb == 512.0

    def test_is_framework_default_false(self) -> None:
        """is_framework defaults to False for user components."""
        spec = make_spec()
        assert spec.is_framework is False

    def test_is_framework_true(self) -> None:
        """Framework components can set is_framework=True."""
        spec = make_spec(is_framework=True)
        assert spec.is_framework is True

    def test_to_dict_serialization(self) -> None:
        """to_dict() produces a JSON-serializable dictionary with all fields."""
        spec = make_spec(
            dependencies=["Dep1"],
            resource_profile=ResourceProfile(expected_memory_mb=64.0),
            metadata={"tag": "test"},
        )
        d = spec.to_dict()

        assert d["name"] == "TestComponent"
        assert d["kind"] == "SERVICE"
        assert d["layer"] == "DOMAIN"
        assert d["dependencies"] == ["Dep1"]
        assert d["resource_profile"] == {"expected_memory_mb": 64.0}
        assert d["metadata"] == {"tag": "test"}
        assert d["is_framework"] is False

        # Must be JSON-serializable
        json_str = json.dumps(d)
        assert json_str  # non-empty

    def test_to_dict_none_resource_profile(self) -> None:
        """to_dict() sets resource_profile to None when not provided."""
        spec = make_spec()
        d = spec.to_dict()
        assert d["resource_profile"] is None

    def test_to_dict_registered_at_is_iso_string(self) -> None:
        """registered_at is serialized as an ISO format string."""
        spec = make_spec()
        d = spec.to_dict()
        # Should parse back without error
        datetime.fromisoformat(d["registered_at"])

    def test_component_spec_is_mutable(self) -> None:
        """ComponentSpec is NOT frozen — fields can be updated post-creation.

        This is intentional: the decorator needs to set module_path and
        qualified_name after initial construction.
        """
        spec = make_spec()
        spec.module_path = "updated.module.path"
        assert spec.module_path == "updated.module.path"

    def test_from_dict_minimal(self) -> None:
        """from_dict() reconstructs ComponentSpec with required fields only."""
        data = {
            "name": "MinimalComponent",
            "kind": "SERVICE",  # String enum name
            "layer": "DOMAIN",  # String enum name
            "intent": "A minimal component for testing deserialization",
        }
        spec = ComponentSpec.from_dict(data)
        assert spec.name == "MinimalComponent"
        assert spec.kind == ComponentKind.SERVICE
        assert spec.layer == Layer.DOMAIN
        assert spec.intent == "A minimal component for testing deserialization"
        assert spec.dependencies == []
        assert spec.version == "0.1.0"
        assert spec.module_path == ""
        assert spec.qualified_name == ""

    def test_from_dict_full(self) -> None:
        """from_dict() reconstructs full ComponentSpec with all fields."""
        data = {
            "name": "FullComponent",
            "kind": "ORCHESTRATOR",
            "layer": "APPLICATION",
            "intent": "A complete component with all fields populated",
            "contracts": {
                "preconditions": ["input valid"],
                "max_latency_ms": 50.0,
            },
            "dependencies": ["ComponentA", "ComponentB"],
            "resource_profile": {
                "expected_memory_mb": 128.0,
                "expected_latency_p50_ms": 10.0,
            },
            "version": "1.2.3",
            "metadata": {"author": "test"},
            "module_path": "test.module",
            "qualified_name": "test.module.FullComponent",
            "source_file": "/path/to/file.py",
            "is_framework": True,
        }
        spec = ComponentSpec.from_dict(data)
        assert spec.name == "FullComponent"
        assert spec.kind == ComponentKind.ORCHESTRATOR
        assert spec.layer == Layer.APPLICATION
        assert spec.dependencies == ["ComponentA", "ComponentB"]
        assert spec.contracts.max_latency_ms == 50.0
        assert spec.resource_profile is not None
        assert spec.resource_profile.expected_memory_mb == 128.0
        assert spec.version == "1.2.3"
        assert spec.metadata == {"author": "test"}
        assert spec.is_framework is True

    def test_from_dict_with_enum_values(self) -> None:
        """from_dict() accepts enum values (not just strings)."""
        data = {
            "name": "EnumComponent",
            "kind": ComponentKind.MODEL,  # Enum value directly
            "layer": Layer.INFRASTRUCTURE,  # Enum value directly
            "intent": "Testing with enum values instead of strings",
        }
        spec = ComponentSpec.from_dict(data)
        assert spec.kind == ComponentKind.MODEL
        assert spec.layer == Layer.INFRASTRUCTURE

    def test_from_dict_missing_required_fields_raises(self) -> None:
        """from_dict() raises if required fields are missing."""
        data = {
            "name": "IncompleteComponent",
            "kind": "SERVICE",
            # Missing 'layer' and 'intent'
        }
        with pytest.raises(RegistrationError, match="missing required fields"):
            ComponentSpec.from_dict(data)

    def test_from_dict_invalid_kind_raises(self) -> None:
        """from_dict() raises if kind string is not a valid enum name."""
        data = {
            "name": "BadComponent",
            "kind": "INVALID_KIND",
            "layer": "DOMAIN",
            "intent": "Testing invalid enum value",
        }
        with pytest.raises(ValueError, match="Invalid ComponentKind"):
            ComponentSpec.from_dict(data)

    def test_from_dict_invalid_layer_raises(self) -> None:
        """from_dict() raises if layer string is not a valid enum name."""
        data = {
            "name": "BadComponent",
            "kind": "SERVICE",
            "layer": "INVALID_LAYER",
            "intent": "Testing invalid enum value",
        }
        with pytest.raises(ValueError, match="Invalid Layer"):
            ComponentSpec.from_dict(data)

    def test_from_dict_round_trip_minimal(self) -> None:
        """from_dict(to_dict()) round-trip preserves minimal ComponentSpec."""
        original = make_spec()
        reconstructed = ComponentSpec.from_dict(original.to_dict())
        assert reconstructed.name == original.name
        assert reconstructed.kind == original.kind
        assert reconstructed.layer == original.layer
        assert reconstructed.intent == original.intent
        assert reconstructed.dependencies == original.dependencies
        assert reconstructed.version == original.version

    def test_from_dict_round_trip_full(self) -> None:
        """from_dict(to_dict()) round-trip preserves full ComponentSpec."""
        props = {
            "theme": ConfigurableProperty(type="str", default="dark"),
        }
        original = make_spec(
            contracts=make_contract(configurable_properties=props),
            dependencies=["DepA", "DepB"],
            resource_profile=ResourceProfile(expected_memory_mb=256.0),
            version="2.0.0",
            metadata={"test": "value"},
        )
        reconstructed = ComponentSpec.from_dict(original.to_dict())
        assert reconstructed.name == original.name
        assert reconstructed.kind == original.kind
        assert reconstructed.layer == original.layer
        assert reconstructed.intent == original.intent
        assert reconstructed.dependencies == original.dependencies
        assert reconstructed.version == original.version
        assert reconstructed.metadata == original.metadata
        # Check nested objects
        assert (
            reconstructed.contracts.configurable_properties
            == original.contracts.configurable_properties
        )
        assert reconstructed.resource_profile is not None
        assert reconstructed.resource_profile.expected_memory_mb == 256.0

    def test_from_dict_with_datetime_string(self) -> None:
        """from_dict() parses registered_at from ISO format string."""
        now = datetime.now(UTC)
        data = {
            "name": "TimeComponent",
            "kind": "SERVICE",
            "layer": "DOMAIN",
            "intent": "Testing datetime parsing",
            "registered_at": now.isoformat(),
        }
        spec = ComponentSpec.from_dict(data)
        # Parse the ISO string and compare (ignore microseconds for simplicity)
        assert spec.registered_at.date() == now.date()
        assert spec.registered_at.hour == now.hour

    def test_from_dict_validates_result(self) -> None:
        """from_dict() validates the reconstructed ComponentSpec."""
        # Self-dependency should be caught by __post_init__
        data = {
            "name": "SelfDependent",
            "kind": "SERVICE",
            "layer": "DOMAIN",
            "intent": "Testing validation on deserialization",
            "dependencies": ["SelfDependent"],  # Self-dependency
        }
        with pytest.raises(RegistrationError, match="cannot depend on itself"):
            ComponentSpec.from_dict(data)


# ===========================================================================
# Anomaly Tests
# ===========================================================================

class TestAnomaly:
    """Tests for the Anomaly dataclass."""

    def test_valid_construction(self) -> None:
        """A valid Anomaly constructs without error."""
        a = Anomaly(
            kind=AnomalyKind.PHANTOM_LIMB,
            severity=AnomalySeverity.ERROR,
            component_name="GhostComponent",
            message="Registry entry has no corresponding source code",
        )
        assert a.kind == AnomalyKind.PHANTOM_LIMB
        assert a.severity == AnomalySeverity.ERROR
        assert a.component_name == "GhostComponent"

    def test_anomaly_with_no_component(self) -> None:
        """component_name can be None for system-level anomalies."""
        a = Anomaly(
            kind=AnomalyKind.IMMUNE_RESPONSE,
            severity=AnomalySeverity.WARNING,
            component_name=None,
            message="Unregistered code detected in module",
        )
        assert a.component_name is None

    def test_anomaly_with_details(self) -> None:
        """details stores structured diagnostic data."""
        a = Anomaly(
            kind=AnomalyKind.INFLAMMATION,
            severity=AnomalySeverity.WARNING,
            component_name="SlowService",
            message="Component exceeding latency profile",
            details={"actual_p99_ms": 500.0, "expected_p99_ms": 100.0},
        )
        assert a.details["actual_p99_ms"] == 500.0

    def test_anomaly_to_dict(self) -> None:
        """to_dict() produces a JSON-serializable dictionary."""
        a = Anomaly(
            kind=AnomalyKind.VESTIGIAL_ORGAN,
            severity=AnomalySeverity.INFO,
            component_name="OldHelper",
            message="Code exists but is never called",
            details={"last_call": "never"},
        )
        d = a.to_dict()
        assert d["kind"] == "VESTIGIAL_ORGAN"
        assert d["severity"] == "INFO"
        assert d["component_name"] == "OldHelper"
        json.dumps(d)  # JSON-serializable

    def test_anomaly_detected_at_auto_set(self) -> None:
        """detected_at defaults to approximately now."""
        before = datetime.now(UTC)
        a = Anomaly(
            kind=AnomalyKind.PHANTOM_LIMB,
            severity=AnomalySeverity.ERROR,
            component_name=None,
            message="Test",
        )
        after = datetime.now(UTC)
        assert before <= a.detected_at <= after

    def test_anomaly_is_frozen(self) -> None:
        """Anomaly is immutable (frozen dataclass)."""
        a = Anomaly(
            kind=AnomalyKind.PHANTOM_LIMB,
            severity=AnomalySeverity.ERROR,
            component_name=None,
            message="Test",
        )
        with pytest.raises(AttributeError):
            a.message = "changed"  # type: ignore[misc]


# ===========================================================================
# RegistrySnapshot Tests
# ===========================================================================

class TestRegistrySnapshot:
    """Tests for the RegistrySnapshot dataclass."""

    @pytest.fixture()
    def sample_specs(self) -> dict[str, ComponentSpec]:
        """Create a set of sample ComponentSpecs for snapshot testing."""
        return {
            "UserService": ComponentSpec(
                name="UserService",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Manages user lifecycle including registration and authentication",
                dependencies=["DatabaseAdapter"],
                module_path="myapp.services.user",
                qualified_name="myapp.services.user.UserService",
            ),
            "DatabaseAdapter": ComponentSpec(
                name="DatabaseAdapter",
                kind=ComponentKind.ADAPTER,
                layer=Layer.INFRASTRUCTURE,
                intent="Provides database connectivity and query execution",
                module_path="myapp.adapters.database",
                qualified_name="myapp.adapters.database.DatabaseAdapter",
            ),
            "UserModel": ComponentSpec(
                name="UserModel",
                kind=ComponentKind.MODEL,
                layer=Layer.DOMAIN,
                intent="Represents a user entity with validation invariants",
                module_path="myapp.models.user",
                qualified_name="myapp.models.user.UserModel",
            ),
        }

    @pytest.fixture()
    def sample_snapshot(self, sample_specs: dict[str, ComponentSpec]) -> RegistrySnapshot:
        """Create a sample RegistrySnapshot."""
        return RegistrySnapshot(
            components=sample_specs,
            component_count=3,
            framework_component_count=0,
            layers={
                "DOMAIN": ["UserService", "UserModel"],
                "INFRASTRUCTURE": ["DatabaseAdapter"],
            },
            dependency_graph={
                "UserService": ["DatabaseAdapter"],
                "DatabaseAdapter": [],
                "UserModel": [],
            },
        )

    def test_snapshot_construction(self, sample_snapshot: RegistrySnapshot) -> None:
        """A valid snapshot constructs without error."""
        assert sample_snapshot.component_count == 3
        assert sample_snapshot.framework_component_count == 0

    def test_snapshot_to_dict(self, sample_snapshot: RegistrySnapshot) -> None:
        """to_dict() produces a JSON-serializable dictionary."""
        d = sample_snapshot.to_dict()
        assert d["component_count"] == 3
        assert "UserService" in d["components"]
        # Full JSON round-trip
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed["component_count"] == 3

    def test_snapshot_to_json(self, sample_snapshot: RegistrySnapshot) -> None:
        """to_json() produces a valid JSON string."""
        j = sample_snapshot.to_json()
        parsed = json.loads(j)
        assert parsed["component_count"] == 3

    def test_describe_contains_header(self, sample_snapshot: RegistrySnapshot) -> None:
        """describe() output includes the header."""
        desc = sample_snapshot.describe()
        assert "S0MA SYSTEM SELF-DESCRIPTION" in desc

    def test_describe_contains_summary(self, sample_snapshot: RegistrySnapshot) -> None:
        """describe() output includes component counts."""
        desc = sample_snapshot.describe()
        assert "Total components: 3" in desc
        assert "User components: 3" in desc
        assert "Framework components: 0" in desc

    def test_describe_contains_all_component_names(
        self, sample_snapshot: RegistrySnapshot
    ) -> None:
        """describe() output mentions every component by name."""
        desc = sample_snapshot.describe()
        assert "UserService" in desc
        assert "DatabaseAdapter" in desc
        assert "UserModel" in desc

    def test_describe_contains_intents(self, sample_snapshot: RegistrySnapshot) -> None:
        """describe() output includes component intents."""
        desc = sample_snapshot.describe()
        assert "Manages user lifecycle" in desc
        assert "Provides database connectivity" in desc

    def test_describe_contains_dependency_graph(
        self, sample_snapshot: RegistrySnapshot
    ) -> None:
        """describe() shows the dependency graph when dependencies exist."""
        desc = sample_snapshot.describe()
        assert "DEPENDENCY GRAPH" in desc
        assert "UserService -> DatabaseAdapter" in desc

    def test_describe_omits_dependency_graph_when_empty(self) -> None:
        """describe() omits DEPENDENCY GRAPH section when no deps exist."""
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
        )
        desc = snapshot.describe()
        assert "DEPENDENCY GRAPH" not in desc

    def test_describe_contains_layer_sections(
        self, sample_snapshot: RegistrySnapshot
    ) -> None:
        """describe() organizes components by layer."""
        desc = sample_snapshot.describe()
        assert "[DOMAIN]" in desc
        assert "[INFRASTRUCTURE]" in desc

    def test_describe_shows_component_kinds(
        self, sample_snapshot: RegistrySnapshot
    ) -> None:
        """describe() shows each component's kind."""
        desc = sample_snapshot.describe()
        assert "(service)" in desc
        assert "(adapter)" in desc
        assert "(model)" in desc

    def test_describe_contains_footer(self, sample_snapshot: RegistrySnapshot) -> None:
        """describe() output includes the explanatory footer."""
        desc = sample_snapshot.describe()
        assert "load-bearing registry" in desc

    def test_describe_is_substantive(self, sample_snapshot: RegistrySnapshot) -> None:
        """describe() output is non-trivial (the narrative test threshold)."""
        desc = sample_snapshot.describe()
        assert len(desc) > 500

    def test_empty_snapshot(self) -> None:
        """An empty snapshot is valid and produces minimal output."""
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
        )
        desc = snapshot.describe()
        assert "Total components: 0" in desc
        d = snapshot.to_dict()
        assert d["component_count"] == 0
        json.dumps(d)  # still JSON-serializable

    def test_snapshot_is_frozen(self, sample_snapshot: RegistrySnapshot) -> None:
        """RegistrySnapshot is immutable (frozen dataclass)."""
        with pytest.raises(AttributeError):
            sample_snapshot.component_count = 999  # type: ignore[misc]

    def test_snapshot_at_auto_set(self) -> None:
        """snapshot_at defaults to approximately now."""
        before = datetime.now(UTC)
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
        )
        after = datetime.now(UTC)
        assert before <= snapshot.snapshot_at <= after

    def test_describe_includes_configurable_properties(self) -> None:
        """describe() output includes configurable properties when present."""
        # Create a component with configurable properties
        spec_with_config = ComponentSpec(
            name="ConfigurableWidget",
            kind=ComponentKind.SERVICE,
            layer=Layer.PRESENTATION,
            intent="A widget with runtime-configurable theme and display options",
            contracts=Contract(
                configurable_properties={
                    "theme_color": ConfigurableProperty(
                        type="str",
                        default="blue",
                        description="Primary theme color",
                    ),
                    "max_items": ConfigurableProperty(
                        type="int",
                        default=10,
                        constraints={"min": 1, "max": 100},
                    ),
                }
            ),
            module_path="myapp.widgets.configurable",
            qualified_name="myapp.widgets.configurable.ConfigurableWidget",
        )

        snapshot = RegistrySnapshot(
            components={"ConfigurableWidget": spec_with_config},
            component_count=1,
            framework_component_count=0,
            layers={"PRESENTATION": ["ConfigurableWidget"]},
            dependency_graph={"ConfigurableWidget": []},
        )

        desc = snapshot.describe()
        # Verify configurable properties are shown
        assert "Configurable: theme_color (str), max_items (int)" in desc
        assert "ConfigurableWidget" in desc

    def test_describe_unchanged_without_configurable_properties(
        self, sample_snapshot: RegistrySnapshot
    ) -> None:
        """describe() output is unchanged when no components have configurable properties."""
        desc = sample_snapshot.describe()
        # None of the sample components have configurable properties
        assert "Configurable:" not in desc
        # But they should still be described normally
        assert "UserService" in desc
        assert "DatabaseAdapter" in desc

    def test_describe_includes_protocol_contract(self) -> None:
        """describe() output includes protocol contract info when present."""
        proto = ProtocolContract(
            protocol_type="websocket",
            message_types={
                "message": {"role": "str", "content": "str"},
                "error": {"code": "int"},
                "plan": {"steps": "list"},
            },
        )
        spec_with_proto = ComponentSpec(
            name="ChatServer",
            kind=ComponentKind.SERVICE,
            layer=Layer.PRESENTATION,
            intent="WebSocket server handling real-time chat communication",
            contracts=Contract(protocol=proto),
            module_path="myapp.server.chat",
            qualified_name="myapp.server.chat.ChatServer",
        )

        snapshot = RegistrySnapshot(
            components={"ChatServer": spec_with_proto},
            component_count=1,
            framework_component_count=0,
            layers={"PRESENTATION": ["ChatServer"]},
            dependency_graph={"ChatServer": []},
        )

        desc = snapshot.describe()
        assert "Protocol: websocket" in desc
        assert "message types:" in desc
        assert "error" in desc
        assert "message" in desc
        assert "plan" in desc

    def test_describe_omits_protocol_when_none(
        self, sample_snapshot: RegistrySnapshot
    ) -> None:
        """describe() output doesn't mention protocol when no components have one."""
        desc = sample_snapshot.describe()
        assert "Protocol:" not in desc

    def test_describe_includes_modules(self) -> None:
        """describe() includes MODULES section when modules are present."""
        mod = ModuleMetadata(
            name="config",
            layer="DOMAIN",
            version="0.1.0",
            intent="Application configuration",
            exports=["DEFAULT_MODEL", "TEST_MODEL"],
        )
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
            modules={"config": mod},
        )
        desc = snapshot.describe()
        assert "MODULES" in desc
        assert "config (DOMAIN, v0.1.0)" in desc
        assert "exports: [DEFAULT_MODEL, TEST_MODEL]" in desc

    def test_describe_includes_relationships(self) -> None:
        """describe() includes RELATIONSHIPS section when edges are present."""
        edges = [
            RelationshipEdge(
                source="Orchestrator",
                target="LLMAdapter",
                relation="CALLS",
                carries="ChatMessage",
            ),
            RelationshipEdge(
                source="Orchestrator",
                target="OrchestratorEvent",
                relation="PRODUCES",
            ),
        ]
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
            edges=edges,
        )
        desc = snapshot.describe()
        assert "RELATIONSHIPS" in desc
        assert "Orchestrator -> LLMAdapter (CALLS, carries: ChatMessage)" in desc
        assert "Orchestrator -> OrchestratorEvent (PRODUCES)" in desc

    def test_describe_includes_consumes_relationship(self) -> None:
        """describe() renders CONSUMES edges correctly."""
        edges = [
            RelationshipEdge(
                source="EventHandler",
                target="OrderCreated",
                relation="CONSUMES",
                carries="OrderPayload",
            ),
        ]
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
            edges=edges,
        )
        desc = snapshot.describe()
        assert "RELATIONSHIPS" in desc
        assert (
            "EventHandler -> OrderCreated"
            " (CONSUMES, carries: OrderPayload)"
            in desc
        )

    def test_describe_includes_test_coverage(self) -> None:
        """describe() includes TEST COVERAGE section with percentage."""
        specs = {
            "UserService": ComponentSpec(
                name="UserService",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Manages user lifecycle and authentication",
                module_path="myapp.services.user",
                qualified_name="myapp.services.user.UserService",
            ),
            "DatabaseAdapter": ComponentSpec(
                name="DatabaseAdapter",
                kind=ComponentKind.ADAPTER,
                layer=Layer.INFRASTRUCTURE,
                intent="Provides database connectivity and query execution",
                module_path="myapp.adapters.database",
                qualified_name="myapp.adapters.database.DatabaseAdapter",
            ),
        }
        test_reg = TestRegistration(
            name="test_user_service",
            intent="Validates user lifecycle operations",
            validates=["UserService"],
        )
        snapshot = RegistrySnapshot(
            components=specs,
            component_count=2,
            framework_component_count=0,
            layers={
                "DOMAIN": ["UserService"],
                "INFRASTRUCTURE": ["DatabaseAdapter"],
            },
            dependency_graph={},
            test_registrations={"test_user_service": test_reg},
        )
        desc = snapshot.describe()
        assert "TEST COVERAGE" in desc
        assert "1/2 components have tests (50%)" in desc
        assert "Untested: [DatabaseAdapter]" in desc

    def test_describe_omits_empty_sections(
        self, sample_snapshot: RegistrySnapshot
    ) -> None:
        """describe() omits MODULES/RELATIONSHIPS/TEST COVERAGE when empty."""
        desc = sample_snapshot.describe()
        assert "MODULES" not in desc
        assert "RELATIONSHIPS" not in desc
        assert "TEST COVERAGE" not in desc

    def test_to_dict_includes_configurable_properties(self) -> None:
        """to_dict() round-trip includes configurable properties data."""
        spec_with_config = ComponentSpec(
            name="ConfigurableWidget",
            kind=ComponentKind.SERVICE,
            layer=Layer.PRESENTATION,
            intent="A widget with runtime-configurable theme",
            contracts=Contract(
                configurable_properties={
                    "theme": ConfigurableProperty(
                        type="enum",
                        default="light",
                        constraints={"allowed_values": ["light", "dark", "auto"]},
                    ),
                }
            ),
            module_path="myapp.widgets.configurable",
            qualified_name="myapp.widgets.configurable.ConfigurableWidget",
        )

        snapshot = RegistrySnapshot(
            components={"ConfigurableWidget": spec_with_config},
            component_count=1,
            framework_component_count=0,
            layers={"PRESENTATION": ["ConfigurableWidget"]},
            dependency_graph={"ConfigurableWidget": []},
        )

        # Convert to dict
        snapshot_dict = snapshot.to_dict()

        # Verify configurable_properties are in the serialized data
        assert "components" in snapshot_dict
        assert "ConfigurableWidget" in snapshot_dict["components"]
        comp_data = snapshot_dict["components"]["ConfigurableWidget"]
        assert "contracts" in comp_data
        assert "configurable_properties" in comp_data["contracts"]

        config_props = comp_data["contracts"]["configurable_properties"]
        assert "theme" in config_props
        assert config_props["theme"]["type"] == "enum"
        assert config_props["theme"]["default"] == "light"
        assert "allowed_values" in config_props["theme"]["constraints"]

    def test_snapshot_to_dict_includes_modules(self) -> None:
        """to_dict() includes modules when present in snapshot."""
        mod = ModuleMetadata(
            name="config",
            layer="DOMAIN",
            version="0.1.0",
            intent="Application configuration",
            exports=["DEFAULT_MODEL", "TEST_MODEL"],
        )
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
            modules={"config": mod},
        )
        d = snapshot.to_dict()
        assert "modules" in d
        assert "config" in d["modules"]
        assert d["modules"]["config"]["layer"] == "DOMAIN"
        assert d["modules"]["config"]["exports"] == ["DEFAULT_MODEL", "TEST_MODEL"]

    def test_snapshot_to_dict_includes_edges(self) -> None:
        """to_dict() includes edges when present in snapshot."""
        edge = RelationshipEdge(
            source="Orchestrator",
            target="LLMAdapter",
            relation="CALLS",
            carries="ChatMessage",
        )
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
            edges=[edge],
        )
        d = snapshot.to_dict()
        assert "edges" in d
        assert len(d["edges"]) == 1
        assert d["edges"][0]["source"] == "Orchestrator"
        assert d["edges"][0]["relation"] == "CALLS"

    def test_snapshot_to_dict_includes_test_registrations(self) -> None:
        """to_dict() includes test_registrations when present in snapshot."""
        test_reg = TestRegistration(
            name="test_orchestrator_flow",
            intent="Validates orchestrator handles tool calls",
            validates=["Orchestrator"],
        )
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
            test_registrations={"test_orchestrator_flow": test_reg},
        )
        d = snapshot.to_dict()
        assert "test_registrations" in d
        assert "test_orchestrator_flow" in d["test_registrations"]
        assert d["test_registrations"]["test_orchestrator_flow"]["validates"] == [
            "Orchestrator"
        ]

    def test_snapshot_defaults_backward_compatible(self) -> None:
        """Constructing snapshot without new fields uses empty defaults."""
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
        )
        assert snapshot.modules == {}
        assert snapshot.edges == []
        assert snapshot.test_registrations == {}
        assert snapshot.ir == {}
        d = snapshot.to_dict()
        assert d["modules"] == {}
        assert d["edges"] == []
        assert d["test_registrations"] == {}
        assert d["ir"] == {}
        json.dumps(d)  # still JSON-serializable

    def test_snapshot_to_dict_includes_ir(self) -> None:
        """to_dict() includes IR data when present in snapshot."""
        ir_data: dict[str, object] = {
            "nerves": [{"name": "process_signal", "kind": "FUNCTION"}],
        }
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
            ir={"signal_processor": ir_data},
        )
        d = snapshot.to_dict()
        assert "ir" in d
        assert "signal_processor" in d["ir"]
        assert d["ir"]["signal_processor"]["nerves"][0]["name"] == "process_signal"

    def test_snapshot_ir_is_json_serializable(self) -> None:
        """Snapshot IR data survives a JSON round-trip."""
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
            ir={"mod": {"count": 3, "names": ["a", "b", "c"]}},
        )
        d = snapshot.to_dict()
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed["ir"]["mod"]["count"] == 3

    def test_snapshot_ir_empty_by_default(self) -> None:
        """Snapshot constructed without ir= has empty IR dict."""
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
        )
        assert snapshot.ir == {}
        assert snapshot.to_dict()["ir"] == {}


# ===========================================================================
# PluginRegistration Tests
# ===========================================================================

class TestPluginRegistration:
    """Tests for the PluginRegistration dataclass."""

    def test_to_dict_roundtrip(self) -> None:
        """Create PluginRegistration, to_dict(), from_dict(), verify equality."""
        plugin = PluginRegistration(
            name="tool_extensions",
            version="1.0.0",
            intent="Adds tool execution capabilities",
            registers=["ToolExecutor", "ToolCache"],
            requires_core=["Orchestrator", "ToolRegistry"],
            source_file="plugins/tools.py",
        )
        d = plugin.to_dict()
        restored = PluginRegistration.from_dict(d)
        assert restored.name == plugin.name
        assert restored.version == plugin.version
        assert restored.intent == plugin.intent
        assert restored.registers == plugin.registers
        assert restored.requires_core == plugin.requires_core
        assert restored.source_file == plugin.source_file

    def test_to_dict_omits_none_source_file(self) -> None:
        """source_file key is absent when None."""
        plugin = PluginRegistration(
            name="basic_plugin",
            version="0.1.0",
            intent="A basic plugin",
        )
        d = plugin.to_dict()
        assert "source_file" not in d

    def test_to_dict_includes_source_file_when_set(self) -> None:
        """source_file key is present when set."""
        plugin = PluginRegistration(
            name="basic_plugin",
            version="0.1.0",
            intent="A basic plugin",
            source_file="plugins/basic.py",
        )
        d = plugin.to_dict()
        assert d["source_file"] == "plugins/basic.py"

    def test_from_dict_defaults(self) -> None:
        """from_dict() handles missing optional fields."""
        d = {"name": "minimal", "version": "1.0.0", "intent": "Minimal"}
        plugin = PluginRegistration.from_dict(d)
        assert plugin.registers == []
        assert plugin.requires_core == []
        assert plugin.source_file is None

    def test_snapshot_to_dict_includes_plugins(self) -> None:
        """to_dict() includes plugins when present in snapshot."""
        plugin = PluginRegistration(
            name="tool_extensions",
            version="1.0.0",
            intent="Adds tool execution capabilities",
            registers=["ToolExecutor"],
            requires_core=["Orchestrator"],
        )
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
            plugins={"tool_extensions": plugin},
        )
        d = snapshot.to_dict()
        assert "plugins" in d
        assert "tool_extensions" in d["plugins"]
        assert d["plugins"]["tool_extensions"]["version"] == "1.0.0"
        assert d["plugins"]["tool_extensions"]["registers"] == ["ToolExecutor"]

    def test_snapshot_plugins_empty_by_default(self) -> None:
        """Snapshot constructed without plugins= has empty dict."""
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
        )
        assert snapshot.plugins == {}
        assert snapshot.to_dict()["plugins"] == {}

    def test_describe_includes_plugins(self) -> None:
        """describe() includes PLUGINS section when plugins are present."""
        plugin = PluginRegistration(
            name="tool_extensions",
            version="1.0.0",
            intent="Adds tool execution capabilities",
            registers=["ToolExecutor", "ToolCache"],
            requires_core=["Orchestrator", "ToolRegistry"],
        )
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
            plugins={"tool_extensions": plugin},
        )
        desc = snapshot.describe()
        assert "PLUGINS" in desc
        assert "tool_extensions v1.0.0" in desc
        assert "Adds tool execution capabilities" in desc
        assert "registers: [ToolExecutor, ToolCache]" in desc
        assert "requires: [Orchestrator, ToolRegistry]" in desc

    def test_describe_omits_plugins_when_empty(self) -> None:
        """describe() omits PLUGINS section when no plugins registered."""
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
        )
        desc = snapshot.describe()
        assert "PLUGINS" not in desc

    def test_snapshot_plugins_json_serializable(self) -> None:
        """Snapshot with plugins survives JSON round-trip."""
        plugin = PluginRegistration(
            name="test_plugin",
            version="2.0.0",
            intent="Test plugin",
            registers=["Comp1"],
        )
        snapshot = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
            plugins={"test_plugin": plugin},
        )
        d = snapshot.to_dict()
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed["plugins"]["test_plugin"]["version"] == "2.0.0"


# ===========================================================================
# Enum Tests (carried forward from Milestone 1)
# ===========================================================================

class TestEnums:
    """Verify the core enums contain all planned members."""

    def test_component_kind_enum_has_expected_members(self) -> None:
        """ComponentKind contains all planned archetypes."""
        expected = {"SERVICE", "FUNCTION", "MODEL", "ADAPTER", "ORCHESTRATOR", "FRAMEWORK"}
        actual = {member.name for member in ComponentKind}
        assert actual == expected

    def test_layer_enum_has_expected_members(self) -> None:
        """Layer contains all planned architectural layers."""
        expected = {"DOMAIN", "APPLICATION", "INFRASTRUCTURE", "PRESENTATION", "FRAMEWORK"}
        actual = {member.name for member in Layer}
        assert actual == expected


# ===========================================================================
# Hypothesis Property-Based Tests
# ===========================================================================

# Strategies for generating valid enum values
component_kind_strategy = st.sampled_from(list(ComponentKind))
layer_strategy = st.sampled_from(list(Layer))

# Strategy for generating valid component names (non-empty, no whitespace)
valid_name_strategy = st.from_regex(r"[A-Za-z][A-Za-z0-9_]{0,49}", fullmatch=True)

# Strategy for generating valid intents (>= 10 characters)
valid_intent_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=10,
    max_size=200,
)


class TestHypothesisComponentSpec:
    """Property-based tests for ComponentSpec using hypothesis."""

    @given(
        name=valid_name_strategy,
        kind=component_kind_strategy,
        layer=layer_strategy,
        intent=valid_intent_strategy,
    )
    @settings(max_examples=200)
    def test_valid_specs_always_construct(
        self,
        name: str,
        kind: ComponentKind,
        layer: Layer,
        intent: str,
    ) -> None:
        """Any valid combination of name/kind/layer/intent constructs."""
        spec = ComponentSpec(
            name=name,
            kind=kind,
            layer=layer,
            intent=intent,
        )
        assert spec.name == name
        assert spec.kind == kind
        assert spec.layer == layer

    @given(
        name=valid_name_strategy,
        kind=component_kind_strategy,
        layer=layer_strategy,
        intent=valid_intent_strategy,
    )
    @settings(max_examples=100)
    def test_valid_specs_round_trip_through_dict(
        self,
        name: str,
        kind: ComponentKind,
        layer: Layer,
        intent: str,
    ) -> None:
        """Valid specs survive to_dict() and JSON serialization."""
        spec = ComponentSpec(name=name, kind=kind, layer=layer, intent=intent)
        d = spec.to_dict()
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed["name"] == name
        assert parsed["kind"] == kind.name
        assert parsed["layer"] == layer.name

    @given(
        name=st.text(min_size=0, max_size=0)
        | st.from_regex(r".*\s+.*", fullmatch=True).filter(lambda s: len(s) > 0),
    )
    @settings(max_examples=50)
    def test_invalid_names_always_rejected(self, name: str) -> None:
        """Empty names or names with whitespace are always rejected."""
        with pytest.raises(RegistrationError):
            ComponentSpec(
                name=name,
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="A valid intent string for testing purposes",
            )

    @given(intent=st.text(max_size=9))
    @settings(max_examples=50)
    def test_short_intents_always_rejected(self, intent: str) -> None:
        """Intents shorter than 10 characters are always rejected."""
        with pytest.raises(RegistrationError, match="intent must be at least 10 characters"):
            ComponentSpec(
                name="ValidName",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent=intent,
            )


class TestHypothesisContract:
    """Property-based tests for Contract validation."""

    @given(
        latency=st.floats(
            min_value=0.001, max_value=1e6, allow_nan=False, allow_infinity=False
        ),
        error_rate=st.floats(
            min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=100)
    def test_valid_contracts_always_validate(
        self, latency: float, error_rate: float
    ) -> None:
        """Valid latency and error rate values always pass validation."""
        c = Contract(max_latency_ms=latency, error_rate_threshold=error_rate)
        c.validate()  # should not raise

    @given(
        latency=st.floats(
            max_value=0.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=50)
    def test_non_positive_latency_always_rejected(self, latency: float) -> None:
        """Non-positive latency values are always rejected."""
        c = Contract(max_latency_ms=latency)
        with pytest.raises(RegistrationError):
            c.validate()


# ===========================================================================
# Error Message Tests (Milestone 4)
# ===========================================================================

class TestDataclassErrorMessages:
    """Tests for descriptive error messages on invalid keyword arguments."""

    def test_contract_invalid_field_raises_registration_error(self) -> None:
        """Contract with invalid field raises RegistrationError (not TypeError)."""
        with pytest.raises(
            RegistrationError,
            match="Contract\\(\\) received unexpected keyword argument",
        ):
            Contract(invalid_field="value")  # type: ignore[call-arg]

    def test_contract_error_message_lists_valid_fields(self) -> None:
        """Contract error message lists all valid fields."""
        with pytest.raises(RegistrationError, match="Valid fields are:"):
            Contract(bad_field="value")  # type: ignore[call-arg]

        # Verify the error message contains expected field names
        try:
            Contract(bad_field="value")  # type: ignore[call-arg]
        except RegistrationError as e:
            error_msg = str(e)
            # Check that key fields are mentioned
            assert "preconditions" in error_msg
            assert "postconditions" in error_msg
            assert "invariants" in error_msg
            assert "max_latency_ms" in error_msg
            assert "error_rate_threshold" in error_msg
            assert "configurable_properties" in error_msg
            assert "protocol" in error_msg

    def test_contract_with_configurable_properties_still_works(self) -> None:
        """Contract with configurable_properties (valid field from M1) works."""
        props = {
            "theme": ConfigurableProperty(type="str", default="dark"),
        }
        c = Contract(configurable_properties=props)
        assert c.configurable_properties == props

    def test_component_spec_invalid_field_raises_registration_error(self) -> None:
        """ComponentSpec with invalid field raises RegistrationError."""
        with pytest.raises(
            RegistrationError,
            match="ComponentSpec\\(\\) received unexpected keyword argument",
        ):
            ComponentSpec(
                name="Test",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="A valid intent for testing purposes",
                bad_kwarg="value",  # type: ignore[call-arg]
            )

    def test_component_spec_error_message_lists_valid_fields(self) -> None:
        """ComponentSpec error message lists valid fields."""
        with pytest.raises(RegistrationError, match="Valid fields are:"):
            ComponentSpec(
                name="Test",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="A valid intent for testing",
                unknown_field="value",  # type: ignore[call-arg]
            )

        # Verify key fields are mentioned
        try:
            ComponentSpec(
                name="Test",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="A valid intent for testing",
                unknown_field="value",  # type: ignore[call-arg]
            )
        except RegistrationError as e:
            error_msg = str(e)
            assert "name" in error_msg
            assert "kind" in error_msg
            assert "layer" in error_msg
            assert "intent" in error_msg
            assert "contracts" in error_msg
            assert "dependencies" in error_msg

    def test_resource_profile_invalid_field_raises_registration_error(self) -> None:
        """ResourceProfile with invalid field raises RegistrationError."""
        with pytest.raises(
            RegistrationError,
            match="ResourceProfile\\(\\) received unexpected keyword argument",
        ):
            ResourceProfile(invalid_kwarg=123.0)  # type: ignore[call-arg]

    def test_resource_profile_error_message_lists_valid_fields(self) -> None:
        """ResourceProfile error message lists valid fields."""
        with pytest.raises(RegistrationError, match="Valid fields are:"):
            ResourceProfile(bad_field=0.5)  # type: ignore[call-arg]

        # Verify key fields are mentioned
        try:
            ResourceProfile(bad_field=0.5)  # type: ignore[call-arg]
        except RegistrationError as e:
            error_msg = str(e)
            assert "expected_memory_mb" in error_msg
            assert "expected_latency_p50_ms" in error_msg
            assert "expected_error_rate" in error_msg

    def test_configurable_property_invalid_field_raises_registration_error(self) -> None:
        """ConfigurableProperty with invalid field raises RegistrationError."""
        with pytest.raises(
            RegistrationError,
            match="ConfigurableProperty\\(\\) received unexpected keyword argument",
        ):
            ConfigurableProperty(
                type="str", default="test", invalid_kwarg="value",
            )  # type: ignore[call-arg]

    def test_configurable_property_error_message_lists_valid_fields(self) -> None:
        """ConfigurableProperty error message lists valid fields."""
        with pytest.raises(RegistrationError, match="Valid fields are:"):
            ConfigurableProperty(type="str", default="test", bad_field="value")  # type: ignore[call-arg]

        # Verify key fields are mentioned
        try:
            ConfigurableProperty(type="str", default="test", bad_field="value")  # type: ignore[call-arg]
        except RegistrationError as e:
            error_msg = str(e)
            assert "type" in error_msg
            assert "default" in error_msg
            assert "description" in error_msg
            assert "constraints" in error_msg
            assert "category" in error_msg

    def test_valid_constructions_unchanged(self) -> None:
        """Valid dataclass constructions still work exactly as before."""
        # Contract
        c = Contract(
            preconditions=["input valid"],
            max_latency_ms=100.0,
            configurable_properties={
                "theme": ConfigurableProperty(type="str", default="dark"),
            },
        )
        assert c.max_latency_ms == 100.0

        # ComponentSpec
        spec = ComponentSpec(
            name="TestComponent",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A valid test component for validation purposes",
        )
        assert spec.name == "TestComponent"

        # ResourceProfile
        rp = ResourceProfile(expected_memory_mb=512.0)
        assert rp.expected_memory_mb == 512.0

        # ConfigurableProperty
        prop = ConfigurableProperty(type="int", default=10, constraints={"min": 0, "max": 100})
        assert prop.default == 10


# ===========================================================================
# KNOWN_RELATION_TYPES Tests
# ===========================================================================


class TestKnownRelationTypes:
    """Tests for the KNOWN_RELATION_TYPES constant."""

    def test_contains_all_documented_types(self) -> None:
        """All nine documented relation types are present."""
        expected = {
            "CALLS", "READS", "CONSTRUCTS", "CONFIGURES",
            "RAISES", "TYPE_USES", "OBSERVES",
            "PRODUCES", "CONSUMES",
        }
        assert expected == KNOWN_RELATION_TYPES

    def test_is_frozenset(self) -> None:
        """KNOWN_RELATION_TYPES is immutable."""
        assert isinstance(KNOWN_RELATION_TYPES, frozenset)

    def test_produces_and_consumes_present(self) -> None:
        """PRODUCES and CONSUMES are recognized relation types."""
        assert "PRODUCES" in KNOWN_RELATION_TYPES
        assert "CONSUMES" in KNOWN_RELATION_TYPES


class TestSnapshotFrameworkVisibility:
    """The snapshot lists the application's components unless asked otherwise."""

    @staticmethod
    def _snapshot() -> RegistrySnapshot:
        from s0ma.registry import ComponentRegistry

        registry = ComponentRegistry(persist=False)
        registry.register(
            ComponentSpec(
                name="S0maDSL_helper",
                kind=ComponentKind.FUNCTION,
                layer=Layer.FRAMEWORK,
                intent="A framework helper that is not the application's.",
                is_framework=True,
            )
        )
        registry.register(
            ComponentSpec(
                name="Scheduler",
                kind=ComponentKind.SERVICE,
                layer=Layer.APPLICATION,
                intent="Runs the application's scheduled tasks.",
                dependencies=["S0maDSL_helper"],
            )
        )
        return registry.snapshot()

    def test_visible_components_defaults_to_the_application(self) -> None:
        snapshot = self._snapshot()
        assert list(snapshot.visible_components()) == ["Scheduler"]
        assert list(snapshot.visible_components(False)) == ["Scheduler"]
        assert sorted(snapshot.visible_components(True)) == ["S0maDSL_helper", "Scheduler"]
        assert snapshot.application_component_count == 1

    def test_a_framework_only_snapshot_shows_the_framework(self) -> None:
        from s0ma.registry import ComponentRegistry

        registry = ComponentRegistry(persist=False)
        registry.register(
            ComponentSpec(
                name="S0maDSL_helper",
                kind=ComponentKind.FUNCTION,
                layer=Layer.FRAMEWORK,
                intent="A framework helper that is not the application's.",
                is_framework=True,
            )
        )
        snapshot = registry.snapshot()
        assert list(snapshot.visible_components()) == ["S0maDSL_helper"]
        assert list(snapshot.visible_components(False)) == []

    def test_describe_lists_the_application_and_says_what_it_omits(self) -> None:
        text = self._snapshot().describe()
        assert "Total components: 2" in text
        assert "Framework components: 1" in text
        assert "User components: 1" in text
        assert "Listed below: 1 application component(s)" in text
        listing = text[text.index("COMPONENTS BY LAYER"):text.index("DEPENDENCY GRAPH")]
        assert "- Scheduler (service)" in listing
        # The framework helper is not listed as a component of the
        # application; it is still named as what the application depends on.
        assert "- S0maDSL_helper (function)" not in listing
        assert "Dependencies: S0maDSL_helper" in listing
        assert "Scheduler -> S0maDSL_helper" in text
        everything = self._snapshot().describe(include_framework=True)
        assert "S0maDSL_helper (function)" in everything
        assert "Listed below:" not in everything
