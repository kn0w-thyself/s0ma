"""Core data models for the s0ma framework.

Defines the data structures that represent components, contracts, resource
profiles, anomalies, and registry snapshots. These are pure data classes
with validation logic — the vocabulary of s0ma.

Key models:
    - Contract: behavioral expectations (pre/postconditions, invariants, performance)
    - ResourceProfile: performance and resource expectations (interoception config)
    - ComponentSpec: registration metadata for a single component
    - Anomaly: a detected code-model discrepancy
    - RegistrySnapshot: serializable view of the full registry state
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from s0ma.exceptions import RegistrationError

if TYPE_CHECKING:
    from s0ma.types import (
        AnomalyKind,
        AnomalySeverity,
        ComponentKind,
        Layer,
        LifecycleAction,
        VerificationScope,
    )

__all__ = [
    "Contract",
    "ConfigurableProperty",
    "ProtocolContract",
    "ResourceProfile",
    "ComponentSpec",
    "Anomaly",
    "ImportHookAnomaly",
    "RegistrySnapshot",
    "VerificationResult",
    "VerificationReport",
    "ReflexionAnalysis",
    "ErosionCoverageReport",
    "LifecycleEvent",
    "ModuleMetadata",
    "RelationshipEdge",
    "TestRegistration",
    "PluginRegistration",
    # Documentation subsystem (design §§6, 10.1)
    "SourceSpan",
    "EntityRef",
    "FilterExpr",
    "Section",
    "AssertExpr",
    "DocRefRegistration",
    "DocGuideRegistration",
    "ExampleRegistration",
    "DocsForResult",
]


def _wrap_init_with_field_hints(cls: type) -> type:
    """Wrap a dataclass __init__ to provide helpful error messages on invalid kwargs.

    When a dataclass receives an unexpected keyword argument, Python raises
    a generic TypeError that doesn't list the valid fields. This wrapper
    catches that error and re-raises as RegistrationError with a descriptive
    message listing all valid fields.

    This is especially helpful for LLM-generated code that may pass invalid
    fields based on outdated examples or pattern-matching.

    Args:
        cls: A dataclass to wrap.

    Returns:
        The same class with its __init__ wrapped.
    """
    original_init = cls.__init__  # type: ignore[misc]
    valid_fields = [f.name for f in fields(cls)]

    @functools.wraps(original_init)
    def wrapped_init(self: Any, *args: Any, **kwargs: Any) -> None:
        try:
            original_init(self, *args, **kwargs)
        except TypeError as e:
            error_msg = str(e)
            if "unexpected keyword argument" in error_msg:
                raise RegistrationError(
                    f"{cls.__name__}() received unexpected keyword argument. "
                    f"Valid fields are: {', '.join(valid_fields)}."
                ) from e
            raise

    cls.__init__ = wrapped_init  # type: ignore[misc]
    return cls


@dataclass(frozen=True)
class ConfigurableProperty:
    """Descriptor for a single runtime-configurable property.

    Configurable properties represent aspects of a component that can be
    changed at runtime without regeneration (theme colors, labels, layout
    options, etc.). Unlike structural properties that require code changes,
    configurable properties are part of the component's runtime interface.

    This descriptor declares the property's type, default value, constraints,
    and optional metadata for UI grouping and documentation.
    """

    type: str  # "str", "int", "float", "bool", "enum"
    default: Any
    description: str | None = None
    constraints: dict[str, Any] | None = None  # min, max, allowed_values
    category: str | None = None  # UI grouping

    def __post_init__(self) -> None:
        """Validate the configurable property descriptor.

        Raises:
            RegistrationError: If the property descriptor is invalid.
        """
        # Validate type is one of the allowed types
        allowed_types = {"str", "int", "float", "bool", "enum"}
        if self.type not in allowed_types:
            raise RegistrationError(
                f"ConfigurableProperty type must be one of {allowed_types}, "
                f"got '{self.type}'"
            )

        # Validate default value matches declared type
        type_validators = {
            "str": lambda v: isinstance(v, str),
            "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "bool": lambda v: isinstance(v, bool),
            "enum": lambda v: True,  # enum default validated against allowed_values
        }

        validator = type_validators.get(self.type)
        if validator and not validator(self.default):  # type: ignore[no-untyped-call]
            raise RegistrationError(
                f"ConfigurableProperty default value type mismatch: "
                f"expected {self.type}, got {type(self.default).__name__}"
            )

        # Validate constraints when provided
        if self.constraints is not None:
            if self.type in {"int", "float"}:
                # Numeric constraints: min < max
                min_val = self.constraints.get("min")
                max_val = self.constraints.get("max")
                if (
                    min_val is not None
                    and max_val is not None
                    and min_val >= max_val
                ):
                    raise RegistrationError(
                        f"ConfigurableProperty numeric constraint invalid: "
                        f"min ({min_val}) must be less than max ({max_val})"
                    )
            elif self.type == "enum":
                # Enum constraints: allowed_values must be non-empty list
                allowed_values = self.constraints.get("allowed_values")
                if not allowed_values:
                    raise RegistrationError(
                        "ConfigurableProperty with type 'enum' must have "
                        "non-empty 'allowed_values' in constraints"
                    )
                if not isinstance(allowed_values, list):
                    raise RegistrationError(
                        "ConfigurableProperty 'allowed_values' must be a list"
                    )
                # Default must be in allowed_values
                if self.default not in allowed_values:
                    raise RegistrationError(
                        f"ConfigurableProperty default value '{self.default}' "
                        f"not in allowed_values: {allowed_values}"
                    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary, omitting None values."""
        result: dict[str, Any] = {
            "type": self.type,
            "default": self.default,
        }
        if self.description is not None:
            result["description"] = self.description
        if self.constraints is not None:
            result["constraints"] = dict(self.constraints)
        if self.category is not None:
            result["category"] = self.category
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfigurableProperty:
        """Deserialize from a dictionary.

        Args:
            data: Dictionary with keys matching ConfigurableProperty fields.

        Returns:
            A fully constructed and validated ConfigurableProperty.

        Raises:
            RegistrationError: If the data is invalid or doesn't match the schema.
        """
        # Extract required fields
        if "type" not in data:
            raise RegistrationError("ConfigurableProperty.from_dict: 'type' field is required")
        if "default" not in data:
            raise RegistrationError("ConfigurableProperty.from_dict: 'default' field is required")

        # Construct with all fields, letting __post_init__ handle validation
        return cls(
            type=data["type"],
            default=data["default"],
            description=data.get("description"),
            constraints=data.get("constraints"),
            category=data.get("category"),
        )


# Apply descriptive error messages wrapper
ConfigurableProperty = _wrap_init_with_field_hints(ConfigurableProperty)  # type: ignore[misc, assignment]


@dataclass(frozen=True)
class ProtocolContract:
    """Declares an interface contract that crosses language/process boundaries.

    Protocol contracts capture the schema of cross-boundary interfaces — WebSocket
    messages, REST endpoints, gRPC services, IPC channels — so the self-model is
    aware of interfaces that span the Python/non-Python boundary.

    In the current phase this is declarative metadata only. Runtime verification
    of protocol conformance is deferred to a future phase. The value now is in
    *capturing* the contract in the self-model so the system knows the interface
    exists and what it promises.
    """

    protocol_type: str  # "websocket", "rest", "grpc", "ipc", etc.
    message_types: dict[str, dict[str, Any]]  # Message name -> schema
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary, omitting None values."""
        result: dict[str, Any] = {
            "protocol_type": self.protocol_type,
            "message_types": {
                name: dict(schema)
                for name, schema in self.message_types.items()
            },
        }
        if self.description is not None:
            result["description"] = self.description
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProtocolContract:
        """Deserialize from a dictionary.

        Args:
            data: Dictionary with keys matching ProtocolContract fields.

        Returns:
            A fully constructed ProtocolContract.

        Raises:
            RegistrationError: If required fields are missing.
        """
        if "protocol_type" not in data:
            raise RegistrationError(
                "ProtocolContract.from_dict: 'protocol_type' field is required"
            )
        if "message_types" not in data:
            raise RegistrationError(
                "ProtocolContract.from_dict: 'message_types' field is required"
            )

        return cls(
            protocol_type=data["protocol_type"],
            message_types=data["message_types"],
            description=data.get("description"),
        )


# Apply descriptive error messages wrapper
ProtocolContract = _wrap_init_with_field_hints(ProtocolContract)  # type: ignore[misc, assignment]


@dataclass(frozen=True)
class Contract:
    """Behavioral contract for a component.

    Declares expectations about a component's behavior: what must be true
    before invocation, what it guarantees after execution, and properties
    that must always hold.

    In Phase 1, contracts are declarative metadata. In Phase 2, the
    verification engine will execute them as runtime assertions.
    """

    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    invariants: list[str] = field(default_factory=list)
    max_latency_ms: float | None = None
    error_rate_threshold: float | None = None
    input_type: str | None = None
    output_type: str | None = None
    configurable_properties: dict[str, ConfigurableProperty] | None = None
    protocol: ProtocolContract | None = None
    # What the component must never do, however it is called and
    # whatever happens while it runs. Shown with the component;
    # nothing executes it.
    forbids: list[str] = field(default_factory=list)

    def validate(self) -> None:
        """Validate internal consistency of the contract.

        Raises:
            RegistrationError: If any contract field has an invalid value.
        """
        if self.max_latency_ms is not None and self.max_latency_ms <= 0:
            raise RegistrationError(
                f"max_latency_ms must be positive, got {self.max_latency_ms}"
            )
        if (
            self.error_rate_threshold is not None
            and not (0.0 <= self.error_rate_threshold <= 1.0)
        ):
            raise RegistrationError(
                f"error_rate_threshold must be between 0.0 and 1.0, "
                f"got {self.error_rate_threshold}"
            )

        # Validate configurable properties when provided
        if self.configurable_properties is not None:
            for prop_name, _prop in self.configurable_properties.items():
                # ConfigurableProperty.__post_init__ handles validation
                # This validates that the property itself is well-formed
                try:
                    # The __post_init__ was already called during construction,
                    # but we can do additional checks here if needed
                    pass
                except Exception as e:
                    raise RegistrationError(
                        f"Invalid configurable property '{prop_name}': {e}"
                    ) from e

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: dict[str, Any] = {
            "preconditions": list(self.preconditions),
            "postconditions": list(self.postconditions),
            "invariants": list(self.invariants),
        }
        if self.max_latency_ms is not None:
            result["max_latency_ms"] = self.max_latency_ms
        if self.error_rate_threshold is not None:
            result["error_rate_threshold"] = self.error_rate_threshold
        if self.input_type is not None:
            result["input_type"] = self.input_type
        if self.output_type is not None:
            result["output_type"] = self.output_type
        if self.configurable_properties is not None:
            result["configurable_properties"] = {
                name: prop.to_dict()
                for name, prop in self.configurable_properties.items()
            }
        if self.protocol is not None:
            result["protocol"] = self.protocol.to_dict()
        if self.forbids:
            result["forbids"] = list(self.forbids)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Contract:
        """Deserialize from a dictionary.

        Args:
            data: Dictionary with keys matching Contract fields.

        Returns:
            A fully constructed and validated Contract.

        Raises:
            RegistrationError: If the data is invalid or validation fails.
        """
        # Handle configurable_properties deserialization
        configurable_properties = None
        if "configurable_properties" in data and data["configurable_properties"] is not None:
            configurable_properties = {
                name: ConfigurableProperty.from_dict(prop_data)
                for name, prop_data in data["configurable_properties"].items()
            }

        # Handle protocol deserialization
        protocol = None
        if "protocol" in data and data["protocol"] is not None:
            protocol = ProtocolContract.from_dict(data["protocol"])

        # Construct with all fields, using defaults for missing optional fields
        contract = cls(
            preconditions=data.get("preconditions", []),
            postconditions=data.get("postconditions", []),
            invariants=data.get("invariants", []),
            max_latency_ms=data.get("max_latency_ms"),
            error_rate_threshold=data.get("error_rate_threshold"),
            input_type=data.get("input_type"),
            output_type=data.get("output_type"),
            configurable_properties=configurable_properties,
            protocol=protocol,
            forbids=data.get("forbids", []),
        )

        # Validate the constructed contract
        contract.validate()
        return contract


# Apply descriptive error messages wrapper
Contract = _wrap_init_with_field_hints(Contract)  # type: ignore[misc, assignment]


@dataclass(frozen=True)
class ResourceProfile:
    """Expected resource usage profile for a component.

    All fields are optional — interoception is opt-in. When declared,
    the Phase 2 interoception monitor will compare actual metrics against
    these expectations and flag deviations as INFLAMMATION anomalies.

    The physical bounds (ADR-003 §4) describe hardware-facing components:
    ``expected_max_current_ma`` and ``expected_max_temperature_c`` are
    upper bounds, ``expected_min_voltage_v`` is a lower bound (supply
    sag). Actuals are app-reported via
    ``MetricsCollector.record_physical`` — s0ma never reads hardware
    itself.
    """

    expected_memory_mb: float | None = None
    expected_latency_p50_ms: float | None = None
    expected_latency_p99_ms: float | None = None
    expected_error_rate: float | None = None
    expected_call_frequency_per_min: float | None = None
    expected_max_current_ma: float | None = None
    expected_max_temperature_c: float | None = None
    expected_min_voltage_v: float | None = None

    def __post_init__(self) -> None:
        """Validate resource profile values are non-negative when set."""
        for field_name in (
            "expected_memory_mb",
            "expected_latency_p50_ms",
            "expected_latency_p99_ms",
            "expected_call_frequency_per_min",
            "expected_max_current_ma",
            "expected_min_voltage_v",
        ):
            # expected_max_temperature_c is deliberately absent: sub-zero
            # temperature bounds are physically legitimate.
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise RegistrationError(
                    f"{field_name} must be non-negative, got {value}"
                )
        if (
            self.expected_error_rate is not None
            and not (0.0 <= self.expected_error_rate <= 1.0)
        ):
            raise RegistrationError(
                f"expected_error_rate must be between 0.0 and 1.0, "
                f"got {self.expected_error_rate}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: dict[str, Any] = {}
        if self.expected_memory_mb is not None:
            result["expected_memory_mb"] = self.expected_memory_mb
        if self.expected_latency_p50_ms is not None:
            result["expected_latency_p50_ms"] = self.expected_latency_p50_ms
        if self.expected_latency_p99_ms is not None:
            result["expected_latency_p99_ms"] = self.expected_latency_p99_ms
        if self.expected_error_rate is not None:
            result["expected_error_rate"] = self.expected_error_rate
        if self.expected_call_frequency_per_min is not None:
            result["expected_call_frequency_per_min"] = self.expected_call_frequency_per_min
        if self.expected_max_current_ma is not None:
            result["expected_max_current_ma"] = self.expected_max_current_ma
        if self.expected_max_temperature_c is not None:
            result["expected_max_temperature_c"] = self.expected_max_temperature_c
        if self.expected_min_voltage_v is not None:
            result["expected_min_voltage_v"] = self.expected_min_voltage_v
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceProfile:
        """Deserialize from a dictionary.

        Args:
            data: Dictionary with keys matching ResourceProfile fields.

        Returns:
            A fully constructed and validated ResourceProfile.

        Raises:
            RegistrationError: If the data is invalid or validation fails.
        """
        # All fields are optional, use .get() with None default
        return cls(
            expected_memory_mb=data.get("expected_memory_mb"),
            expected_latency_p50_ms=data.get("expected_latency_p50_ms"),
            expected_latency_p99_ms=data.get("expected_latency_p99_ms"),
            expected_error_rate=data.get("expected_error_rate"),
            expected_call_frequency_per_min=data.get("expected_call_frequency_per_min"),
            expected_max_current_ma=data.get("expected_max_current_ma"),
            expected_max_temperature_c=data.get("expected_max_temperature_c"),
            expected_min_voltage_v=data.get("expected_min_voltage_v"),
        )


# Apply descriptive error messages wrapper
ResourceProfile = _wrap_init_with_field_hints(ResourceProfile)  # type: ignore[misc, assignment]


def _now() -> datetime:
    """Return the current UTC time. Extracted for testability."""
    return datetime.now(UTC)


@dataclass
class ComponentSpec:
    """Registration metadata for a single component.

    This is the core data structure — what gets stored in the registry
    per component. It captures everything the system knows about a
    registered code entity: its identity, classification, behavioral
    contracts, dependencies, and source location.

    Required fields: name, kind, layer, intent.
    Auto-derived fields (set at registration time): module_path,
    qualified_name, source_file, registered_at.
    """

    # --- Required fields (developer-provided) ---
    name: str
    kind: ComponentKind
    layer: Layer
    intent: str

    # --- Optional fields with defaults ---
    contracts: Contract = field(default_factory=Contract)
    dependencies: list[str] = field(default_factory=list)
    resource_profile: ResourceProfile | None = None
    version: str = "0.1.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    # --- Auto-derived fields (set at registration time) ---
    module_path: str = ""
    qualified_name: str = ""
    source_file: str | None = None
    registered_at: datetime = field(default_factory=_now)
    is_framework: bool = False

    # --- Identity-scoping (additive, default-False) ---
    # When True, the registry stores this spec under a module-qualified key
    # ("<module_path>::<name>") rather than the bare ``name``. The spec's own
    # ``name`` field is unaffected — only the registry's lookup key changes.
    # Two specs with identical bare ``name`` but different ``module_path`` may
    # coexist when both opt in. ``module_scoped=True`` requires
    # ``module_path`` to be non-empty.
    module_scoped: bool = False

    def __post_init__(self) -> None:
        """Validate the component specification at construction time.

        Raises:
            RegistrationError: If any required field is invalid.
        """
        # Name validation
        if not self.name:
            raise RegistrationError("Component name must not be empty")
        if any(c.isspace() for c in self.name):
            raise RegistrationError(
                f"Component name must not contain whitespace, got '{self.name}'"
            )

        # Intent validation
        if len(self.intent) < 10:
            raise RegistrationError(
                f"Component intent must be at least 10 characters, "
                f"got {len(self.intent)} characters: '{self.intent}'"
            )

        # Self-dependency check
        if self.name in self.dependencies:
            raise RegistrationError(
                f"Component '{self.name}' cannot depend on itself"
            )

        # Contract validation
        self.contracts.validate()

    def replace(self, **overrides: Any) -> ComponentSpec:
        """Create a new ComponentSpec with the given field overrides.

        Unlike dataclasses.replace(), this method constructs a brand new
        ComponentSpec, triggering __post_init__ validation on the result.
        This ensures the replaced spec is always valid.

        Only explicitly provided keyword arguments are overridden.
        Omitted fields retain their current values.

        Args:
            **overrides: Fields to override. Must be valid ComponentSpec fields.

        Returns:
            A new, validated ComponentSpec.

        Raises:
            RegistrationError: If the resulting spec fails validation
                (e.g., empty intent, self-dependency).
            TypeError: If an unknown field name is provided.
        """
        valid_fields = {f.name for f in fields(self)}
        unknown = set(overrides.keys()) - valid_fields
        if unknown:
            raise TypeError(
                f"Unknown ComponentSpec fields: {sorted(unknown)}. "
                f"Valid fields: {sorted(valid_fields)}"
            )

        kwargs: dict[str, Any] = {}
        for f in fields(self):
            if f.name in overrides:
                kwargs[f.name] = overrides[f.name]
            else:
                kwargs[f.name] = getattr(self, f.name)

        try:
            return ComponentSpec(**kwargs)
        except (ValueError, TypeError) as e:
            raise RegistrationError(
                f"Invalid replacement for component '{self.name}': {e}"
            ) from e

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary.

        ``module_scoped`` is omitted when False to keep snapshots byte-identical
        for legacy specs that never opt into module-qualified keying.
        """
        result: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind.name,
            "layer": self.layer.name,
            "intent": self.intent,
            "contracts": self.contracts.to_dict(),
            "dependencies": list(self.dependencies),
            "resource_profile": (
                self.resource_profile.to_dict() if self.resource_profile else None
            ),
            "version": self.version,
            "metadata": dict(self.metadata),
            "module_path": self.module_path,
            "qualified_name": self.qualified_name,
            "source_file": self.source_file,
            "registered_at": self.registered_at.isoformat(),
            "is_framework": self.is_framework,
        }
        if self.module_scoped:
            result["module_scoped"] = True
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComponentSpec:
        """Deserialize from a dictionary.

        Args:
            data: Dictionary with keys matching ComponentSpec fields.
                Enum fields can be strings (enum names) or enum values.

        Returns:
            A fully constructed and validated ComponentSpec.

        Raises:
            RegistrationError: If required fields are missing or validation fails.
            ValueError: If enum string values are invalid.
        """
        # Import types here to avoid circular imports
        from s0ma.types import ComponentKind, Layer

        # Validate required fields are present
        required_fields = ["name", "kind", "layer", "intent"]
        missing = [f for f in required_fields if f not in data]
        if missing:
            raise RegistrationError(
                f"ComponentSpec.from_dict: missing required fields: {missing}"
            )

        # Convert string enum names to enum values
        kind_value = data["kind"]
        if isinstance(kind_value, str):
            try:
                kind_value = ComponentKind[kind_value]
            except KeyError:
                valid_kinds = [k.name for k in ComponentKind]
                raise ValueError(
                    f"Invalid ComponentKind: '{kind_value}'. "
                    f"Valid values: {valid_kinds}"
                ) from None

        layer_value = data["layer"]
        if isinstance(layer_value, str):
            try:
                layer_value = Layer[layer_value]
            except KeyError:
                valid_layers = [la.name for la in Layer]
                raise ValueError(
                    f"Invalid Layer: '{layer_value}'. "
                    f"Valid values: {valid_layers}"
                ) from None

        # Deserialize nested Contract
        contracts_data = data.get("contracts", {})
        contracts = Contract.from_dict(contracts_data) if contracts_data else Contract()

        # Deserialize nested ResourceProfile
        resource_profile = None
        if "resource_profile" in data and data["resource_profile"] is not None:
            resource_profile = ResourceProfile.from_dict(data["resource_profile"])

        # Parse registered_at datetime
        registered_at = _now()
        if "registered_at" in data and data["registered_at"] is not None:
            registered_at_str = data["registered_at"]
            if isinstance(registered_at_str, str):
                registered_at = datetime.fromisoformat(registered_at_str)
            elif isinstance(registered_at_str, datetime):
                registered_at = registered_at_str

        # Construct the ComponentSpec with all fields
        return cls(
            name=data["name"],
            kind=kind_value,
            layer=layer_value,
            intent=data["intent"],
            contracts=contracts,
            dependencies=list(data.get("dependencies", [])),
            resource_profile=resource_profile,
            version=data.get("version", "0.1.0"),
            metadata=dict(data.get("metadata", {})),
            module_path=data.get("module_path", ""),
            qualified_name=data.get("qualified_name", ""),
            source_file=data.get("source_file"),
            registered_at=registered_at,
            is_framework=data.get("is_framework", False),
            module_scoped=data.get("module_scoped", False),
        )


# Apply descriptive error messages wrapper
ComponentSpec = _wrap_init_with_field_hints(ComponentSpec)  # type: ignore[misc, assignment]


@dataclass(frozen=True)
class Anomaly:
    """A detected code-model discrepancy.

    Anomalies are classified using the biological pathology taxonomy:
    phantom limbs, vestigial organs, immune responses, etc. Each maps
    to a specific detection algorithm and remediation strategy.
    """

    kind: AnomalyKind
    severity: AnomalySeverity
    component_name: str | None
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    detected_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "kind": self.kind.name,
            "severity": self.severity.name,
            "component_name": self.component_name,
            "message": self.message,
            "details": dict(self.details),
            "detected_at": self.detected_at.isoformat(),
        }


@dataclass(frozen=True)
class ImportHookAnomaly:
    """A foreign-code surveillance anomaly raised by the s0ma import hook.

    The import hook scans every module that loads under the configured
    project root for unregistered public entities and for documentation
    declarations that do not resolve in the registry. Each violation
    detected is captured here as an :class:`ImportHookAnomaly` and
    appended to the global registry's anomaly buffer so downstream
    consumers (notably the B1 ``IMMUNE_RESPONSE`` detection layer) can
    poll or subscribe to them without having to scrape log output.

    Fields:
        name: The fully qualified module name the anomaly originated in
            (e.g. ``"myapp.services.unregistered_module"``).
        description: Human-readable explanation of what the hook saw —
            the same text the hook would otherwise emit as a warning
            (for lenient mode) or attach to ``UnregisteredComponentError``
            (for strict mode).
        severity: ``AnomalySeverity`` value classifying how serious the
            anomaly is. The import hook emits ``ERROR`` for strict-mode
            violations and ``WARNING`` for lenient-mode violations.
        layer: ``Layer | None`` — the architectural layer the offending
            module belongs to, if discoverable from the registry. Many
            anomalies are detected before any registration completes for
            the module, so ``None`` is the common case.
        detected_at: UTC timestamp captured at the moment the anomaly
            was recorded. Populated automatically.

    Instances are frozen and hashable, so callers can keep them in sets
    or use them as dict keys without further wrapping.
    """

    name: str
    description: str
    severity: AnomalySeverity
    layer: Layer | None = None
    detected_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "severity": self.severity.name,
            "layer": self.layer.name if self.layer is not None else None,
            "detected_at": self.detected_at.isoformat(),
        }


@dataclass(frozen=True)
class RegistrySnapshot:
    """A serializable, frozen view of the full registry state.

    This is the output of registry.snapshot() — a point-in-time capture
    of all registered components, their relationships, and summary
    statistics. The describe() method produces the human-readable
    self-description that the bootstrap test validates.
    """

    components: dict[str, ComponentSpec]
    component_count: int
    framework_component_count: int
    layers: dict[str, list[str]]
    dependency_graph: dict[str, list[str]]
    modules: dict[str, ModuleMetadata] = field(default_factory=dict)
    edges: list[RelationshipEdge] = field(default_factory=list)
    test_registrations: dict[str, TestRegistration] = field(default_factory=dict)
    ir: dict[str, dict[str, object]] = field(default_factory=dict)
    plugins: dict[str, PluginRegistration] = field(default_factory=dict)
    doc_refs: dict[str, DocRefRegistration] = field(default_factory=dict)
    doc_guides: dict[str, DocGuideRegistration] = field(default_factory=dict)
    examples: dict[str, ExampleRegistration] = field(default_factory=dict)
    adopted_files: dict[str, AdoptedFile] = field(default_factory=dict)
    snapshot_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary.

        Returns a fully JSON-serializable dict suitable for persistence
        or API responses.
        """
        result: dict[str, Any] = {
            "components": {
                name: spec.to_dict() for name, spec in self.components.items()
            },
            "component_count": self.component_count,
            "framework_component_count": self.framework_component_count,
            "layers": {layer: list(names) for layer, names in self.layers.items()},
            "dependency_graph": {
                name: list(deps) for name, deps in self.dependency_graph.items()
            },
            "modules": {
                name: meta.to_dict()
                for name, meta in self.modules.items()
            },
            "edges": [edge.to_dict() for edge in self.edges],
            "test_registrations": {
                name: reg.to_dict()
                for name, reg in self.test_registrations.items()
            },
            "ir": dict(self.ir),
            "plugins": {
                name: plugin.to_dict()
                for name, plugin in self.plugins.items()
            },
        }
        # Documentation stores (design §10.4 / plan M4): emit only when
        # non-empty so existing snapshot consumers see no new keys until
        # the documentation subsystem is in use.
        if self.doc_refs:
            result["doc_refs"] = {
                name: ref.to_dict() for name, ref in self.doc_refs.items()
            }
        if self.doc_guides:
            result["doc_guides"] = {
                name: guide.to_dict() for name, guide in self.doc_guides.items()
            }
        if self.examples:
            result["examples"] = {
                name: ex.to_dict() for name, ex in self.examples.items()
            }
        # Adopted files (0.11.0, batch-01a D2): emitted only when non-empty
        # so existing snapshot consumers see no new key until adoption is
        # in use — the same additive policy as the documentation stores.
        if self.adopted_files:
            result["adopted_files"] = {
                path: rec.to_dict()
                for path, rec in self.adopted_files.items()
            }
        result["snapshot_at"] = self.snapshot_at.isoformat()
        return result

    def describe(self) -> str:
        """Produce a human-readable description of the system.

        This is the output the bootstrap test validates. It must be
        accurate enough that a fresh reader (human or LLM) can understand
        the system's architecture.
        """
        lines: list[str] = []

        # Header
        lines.append("=" * 72)
        lines.append("S0MA SYSTEM SELF-DESCRIPTION")
        lines.append(f"Snapshot taken: {self.snapshot_at.isoformat()}")
        lines.append("=" * 72)
        lines.append("")

        # Summary
        user_count = self.component_count - self.framework_component_count
        lines.append("SUMMARY")
        lines.append(f"  Total components: {self.component_count}")
        lines.append(f"  Framework components: {self.framework_component_count}")
        lines.append(f"  User components: {user_count}")
        lines.append("")

        # Components by layer
        lines.append("COMPONENTS BY LAYER")
        for layer_name, component_names in sorted(self.layers.items()):
            if component_names:
                lines.append(f"  [{layer_name}]")
                for comp_name in sorted(component_names):
                    spec = self.components.get(comp_name)
                    if spec:
                        kind_label = spec.kind.name.lower()
                        lines.append(f"    - {comp_name} ({kind_label})")
                        lines.append(f"      Intent: {spec.intent}")
                        if spec.dependencies:
                            dep_names = ", ".join(spec.dependencies)
                            lines.append(f"      Dependencies: {dep_names}")
                        # Show configurable properties if present
                        if spec.contracts and spec.contracts.configurable_properties:
                            props = spec.contracts.configurable_properties
                            prop_summary = ", ".join(
                                f"{name} ({prop.type})"
                                for name, prop in props.items()
                            )
                            lines.append(f"      Configurable: {prop_summary}")
                        # Show protocol contract if present
                        if spec.contracts and spec.contracts.protocol:
                            proto = spec.contracts.protocol
                            msg_names = ", ".join(sorted(proto.message_types.keys()))
                            lines.append(
                                f"      Protocol: {proto.protocol_type} "
                                f"with message types: {msg_names}"
                            )
                lines.append("")

        # Modules (only shown when module metadata is registered)
        if self.modules:
            lines.append("MODULES")
            for mod_name, mod in sorted(self.modules.items()):
                entry = f"  {mod_name} ({mod.layer}, v{mod.version})"
                if mod.exports:
                    joined = ", ".join(mod.exports)
                    entry += f" \u2014 exports: [{joined}]"
                lines.append(entry)
            lines.append("")

        # Adopted files (only shown when files were registered by
        # adoption - 0.11.0, batch-01a D2). Listed with their recorded
        # content hashes so the self-description names exactly which
        # real files the model stands behind.
        if self.adopted_files:
            lines.append("ADOPTED FILES")
            for path, rec in sorted(self.adopted_files.items()):
                entry = f"  {path} ({rec.content_hash or 'no hash recorded'})"
                if rec.description:
                    entry += f" \u2014 {rec.description}"
                lines.append(entry)
            lines.append("")

        # Relationships (only shown when relationship edges exist)
        if self.edges:
            lines.append("RELATIONSHIPS")
            for edge in self.edges:
                # ASCII "->" (not U+2192): runtime output must survive
                # cp1252-encoded Windows consoles (Windows-support plan C-3).
                entry = f"  {edge.source} -> {edge.target} ({edge.relation}"
                if edge.carries:
                    entry += f", carries: {edge.carries}"
                entry += ")"
                lines.append(entry)
            lines.append("")

        # Test coverage (only shown when test registrations exist)
        if self.test_registrations:
            lines.append("TEST COVERAGE")
            tested: set[str] = set()
            for reg in self.test_registrations.values():
                tested.update(reg.validates)
            non_fw = {
                name for name, spec in self.components.items()
                if spec.kind.name != "FRAMEWORK"
            }
            tested_count = len(tested & non_fw)
            total = len(non_fw)
            if total > 0:
                pct = tested_count * 100 // total
                lines.append(
                    f"  {tested_count}/{total} components"
                    f" have tests ({pct}%)"
                )
                untested = sorted(non_fw - tested)
                if untested:
                    joined = ", ".join(untested)
                    lines.append(f"  Untested: [{joined}]")
            else:
                count = len(self.test_registrations)
                lines.append(f"  {count} test(s) registered")
            lines.append("")

        # Plugins (only shown when plugins are registered)
        if self.plugins:
            lines.append("PLUGINS")
            for plugin_name, plugin in sorted(self.plugins.items()):
                lines.append(
                    f"  {plugin_name} v{plugin.version}"
                    f' — "{plugin.intent}"'
                )
                if plugin.registers:
                    joined = ", ".join(plugin.registers)
                    lines.append(f"    registers: [{joined}]")
                if plugin.requires_core:
                    joined = ", ".join(plugin.requires_core)
                    lines.append(f"    requires: [{joined}]")
            lines.append("")

        # Documentation (only shown when doc-refs or doc-guides exist)
        if self.doc_refs or self.doc_guides:
            lines.append("DOCUMENTATION")
            for ref_name, ref in sorted(self.doc_refs.items()):
                lines.append(
                    f"  doc-ref {ref_name} ({ref.format} -> {ref.output})"
                )
                lines.append(f"    Intent: {ref.intent}")
                if ref.covers:
                    covers_summary = ", ".join(c.raw for c in ref.covers)
                    lines.append(f"    Covers: {covers_summary}")
            for guide_name, guide in sorted(self.doc_guides.items()):
                lines.append(
                    f"  doc-guide {guide_name} ({guide.format} -> {guide.output})"
                )
                lines.append(f"    Intent: {guide.intent}")
                if guide.covers:
                    covers_summary = ", ".join(
                        f"{c.kind}:{c.name}" for c in guide.covers
                    )
                    lines.append(f"    Covers: {covers_summary}")
            lines.append("")

        # Examples (only shown when examples exist)
        if self.examples:
            lines.append("EXAMPLES")
            for ex_name, ex in sorted(self.examples.items()):
                demo_summary = ", ".join(
                    f"{d.kind}:{d.name}" for d in ex.demonstrates
                )
                lines.append(
                    f"  {ex_name} (runs_in={ex.runs_in})"
                )
                lines.append(f"    Intent: {ex.intent}")
                lines.append(f"    Demonstrates: {demo_summary}")
            lines.append("")

        # Dependency graph
        has_dependencies = any(
            deps for deps in self.dependency_graph.values()
        )
        if has_dependencies:
            lines.append("DEPENDENCY GRAPH")
            for comp_name, deps in sorted(self.dependency_graph.items()):
                if deps:
                    dep_str = ", ".join(sorted(deps))
                    lines.append(f"  {comp_name} -> {dep_str}")
            lines.append("")

        # Footer
        lines.append("=" * 72)
        lines.append(
            "This description was generated by the s0ma self-model. "
            "Every component listed above is registered in the framework's "
            "load-bearing registry. Unregistered code cannot be imported."
        )
        lines.append("=" * 72)

        return "\n".join(lines)

    def to_json(self, indent: int = 2) -> str:
        """Serialize the snapshot to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def examples_for(
        self, entity_ref: EntityRef | str
    ) -> list[ExampleRegistration]:
        """Return registered examples whose ``demonstrates`` includes ``entity_ref``.

        Accepts either an :class:`EntityRef` or a string shortcut. The
        string forms ``"module::name"`` and ``"name"`` are accepted —
        when the module portion is omitted, examples are matched on
        ``name`` alone (and module disambiguation is left to the caller).

        Matching is intentionally coarse for v1 (design §10.4): name
        equality is required; modules must agree only when both sides
        supply one; ``kind`` is not compared because callers frequently
        do not know it.
        """
        target = _coerce_entity_ref(entity_ref)
        return [
            ex
            for _, ex in sorted(self.examples.items())
            if any(_entity_refs_match(target, demo) for demo in ex.demonstrates)
        ]

    def docs_for(self, entity_ref: EntityRef | str) -> DocsForResult:
        """Return registered docs that cover ``entity_ref``.

        Returns a :class:`DocsForResult` with ``refs`` (matching
        ``DocRefRegistration``s) and ``guides`` (matching
        ``DocGuideRegistration``s) in two separate lists, resolving the
        plan §11 open question in favor of a structured wrapper rather
        than a union type — callers can iterate either list without
        runtime ``isinstance`` dispatch.

        Matching for ``DocGuideRegistration.covers`` (typed
        :class:`EntityRef` list) is the same coarse name+module rule
        used by :meth:`examples_for`. Matching for
        ``DocRefRegistration.covers`` (typed :class:`FilterExpr` list)
        is, per the plan, a coarse textual containment check on the
        filter's ``raw`` source — full filter-expression evaluation
        lands later in s0ma-dsl.
        """
        target = _coerce_entity_ref(entity_ref)
        guides = [
            guide
            for _, guide in sorted(self.doc_guides.items())
            if any(_entity_refs_match(target, cov) for cov in guide.covers)
        ]
        refs = [
            ref
            for _, ref in sorted(self.doc_refs.items())
            if any(target.name in cov.raw for cov in ref.covers)
        ]
        return DocsForResult(refs=refs, guides=guides)


def _coerce_entity_ref(value: EntityRef | str) -> EntityRef:
    """Normalize a string shortcut to an :class:`EntityRef`.

    ``"module::name"`` parses to ``EntityRef(kind="", name=name,
    module=module)``; a bare ``"name"`` parses to ``EntityRef(kind="",
    name=name, module=None)``. ``kind`` is left empty because reverse
    lookups never compare it.
    """
    if isinstance(value, EntityRef):
        return value
    if "::" in value:
        module, _, name = value.partition("::")
        return EntityRef(kind="", name=name, module=module or None)
    return EntityRef(kind="", name=value, module=None)


def _entity_refs_match(target: EntityRef, candidate: EntityRef) -> bool:
    """Return True if ``target`` and ``candidate`` refer to the same entity.

    Match rule: ``name`` must be equal; ``module`` must be equal when
    both sides supply one. ``kind`` is ignored — see :meth:`docs_for`.
    """
    if target.name != candidate.name:
        return False
    if target.module is not None and candidate.module is not None:
        return target.module == candidate.module
    return True


@dataclass(frozen=True)
class DocsForResult:
    """Structured result of :meth:`RegistrySnapshot.docs_for`.

    Splits matches into ``refs`` and ``guides`` so callers can iterate
    either list without runtime type dispatch. Resolves plan §11 open
    question in favor of a wrapper over a union return.
    """

    refs: list[DocRefRegistration] = field(default_factory=list)
    guides: list[DocGuideRegistration] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "refs": [r.to_dict() for r in self.refs],
            "guides": [g.to_dict() for g in self.guides],
        }

    def is_empty(self) -> bool:
        """Return True when neither ``refs`` nor ``guides`` has matches."""
        return not self.refs and not self.guides


@dataclass(frozen=True)
class LifecycleEvent:
    """Records a lifecycle operation for audit logging.

    Each lifecycle operation (register, unregister, update, create)
    produces a LifecycleEvent that captures what happened, whether
    it succeeded, and enough detail to understand or reverse it.
    """

    action: LifecycleAction
    component_name: str
    timestamp: datetime
    success: bool
    details: dict[str, Any] = field(default_factory=dict)
    previous_spec: ComponentSpec | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON output."""
        result: dict[str, Any] = {
            "action": self.action.name,
            "component_name": self.component_name,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
        }
        if self.details:
            result["details"] = self.details
        if self.error_message is not None:
            result["error_message"] = self.error_message
        return result


# ======================================================================
# Phase 2: Verification models
# ======================================================================


@dataclass(frozen=True)
class ReflexionAnalysis:
    """Murphy's Reflexion Model output categories.

    The structural verifier classifies each finding into one of
    Murphy et al.'s three categories:
    - Convergences: model and code agree
    - Divergences: model and code conflict (anomalies)
    - Absences: expected elements missing (anomalies)

    Reference: Murphy, Notkin & Sullivan (2001), IEEE TSE 27(4).
    """

    convergences: list[str] = field(default_factory=list)
    divergences: list[Anomaly] = field(default_factory=list)
    absences: list[Anomaly] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "convergences": list(self.convergences),
            "divergences": [a.to_dict() for a in self.divergences],
            "absences": [a.to_dict() for a in self.absences],
        }


@dataclass(frozen=True)
class VerificationResult:
    """Result from a single verifier run.

    Captures the anomalies found, timing information, and summary
    statistics from one verifier's execution. Multiple results are
    aggregated into a VerificationReport.
    """

    verifier_name: str
    scope: VerificationScope
    anomalies: list[Anomaly] = field(default_factory=list)
    components_checked: int = 0
    checks_performed: int = 0
    duration_ms: float = 0.0
    verified_at: datetime = field(default_factory=_now)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """True if no ERROR-severity anomalies were found."""
        from s0ma.types import AnomalySeverity

        return not any(a.severity == AnomalySeverity.ERROR for a in self.anomalies)

    @property
    def error_count(self) -> int:
        """Count of ERROR-severity anomalies."""
        from s0ma.types import AnomalySeverity

        return sum(1 for a in self.anomalies if a.severity == AnomalySeverity.ERROR)

    @property
    def warning_count(self) -> int:
        """Count of WARNING-severity anomalies."""
        from s0ma.types import AnomalySeverity

        return sum(1 for a in self.anomalies if a.severity == AnomalySeverity.WARNING)

    @property
    def info_count(self) -> int:
        """Count of INFO-severity anomalies."""
        from s0ma.types import AnomalySeverity

        return sum(1 for a in self.anomalies if a.severity == AnomalySeverity.INFO)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "verifier_name": self.verifier_name,
            "scope": self.scope.name,
            "anomalies": [a.to_dict() for a in self.anomalies],
            "components_checked": self.components_checked,
            "checks_performed": self.checks_performed,
            "duration_ms": self.duration_ms,
            "verified_at": self.verified_at.isoformat(),
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "details": self.details,
        }

    def describe(self) -> str:
        """Produce a human-readable summary of the verification result."""
        lines: list[str] = []
        status = "PASSED" if self.passed else "FAILED"
        lines.append(f"[{status}] {self.verifier_name} ({self.scope.name})")
        lines.append(
            f"  Components checked: {self.components_checked}, "
            f"Checks performed: {self.checks_performed}, "
            f"Duration: {self.duration_ms:.1f}ms"
        )
        lines.append(
            f"  Errors: {self.error_count}, "
            f"Warnings: {self.warning_count}, "
            f"Info: {self.info_count}"
        )
        if self.anomalies:
            lines.append("  Anomalies:")
            for anomaly in self.anomalies:
                lines.append(
                    f"    [{anomaly.severity.name}] "
                    f"{anomaly.kind.name}: {anomaly.message}"
                )
        return "\n".join(lines)

    def explain_for_llm(self) -> str:
        """Produce structured, actionable context for LLM consumers.

        Unlike describe() which targets human terminal output,
        explain_for_llm() provides richer context with:
        - What went wrong (each anomaly with full detail)
        - What exists (registered components context)
        - Suggested fixes with alternatives when references are invalid
        - Enough context for an LLM to retry intelligently

        Returns:
            Structured text optimized for LLM consumption.
        """
        lines: list[str] = []
        status = "PASSED" if self.passed else "FAILED"
        lines.append(f"## Verification Result: {self.verifier_name} — {status}")
        lines.append(f"Scope: {self.scope.name}")
        lines.append(
            f"Checked {self.components_checked} components, "
            f"performed {self.checks_performed} checks "
            f"in {self.duration_ms:.1f}ms."
        )
        lines.append("")

        if not self.anomalies:
            lines.append("No anomalies found. All checks passed.")
            return "\n".join(lines)

        lines.append(
            f"### Issues Found: {self.error_count} errors, "
            f"{self.warning_count} warnings, {self.info_count} info"
        )
        lines.append("")

        for i, anomaly in enumerate(self.anomalies, 1):
            lines.append(f"**Issue {i}** [{anomaly.severity.name}]")
            lines.append(f"  Type: {anomaly.kind.name}")
            if anomaly.component_name:
                lines.append(f"  Component: {anomaly.component_name}")
            lines.append(f"  Problem: {anomaly.message}")

            if anomaly.details:
                lines.append("  Context:")
                for key, value in anomaly.details.items():
                    lines.append(f"    {key}: {value}")

            lines.append(
                f"  Suggestion: {_suggest_fix(anomaly)}"
            )
            lines.append("")

        return "\n".join(lines)


@dataclass(frozen=True)
class VerificationReport:
    """Aggregated results from running multiple verifiers.

    This is the top-level output from verify_all(). It combines
    results from all verifier scopes and provides summary statistics.
    """

    results: list[VerificationResult] = field(default_factory=list)
    total_anomalies: int = 0
    total_errors: int = 0
    total_warnings: int = 0
    total_duration_ms: float = 0.0
    report_at: datetime = field(default_factory=_now)

    @property
    def passed(self) -> bool:
        """True if all verifiers passed (no ERROR anomalies)."""
        return all(r.passed for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "results": [r.to_dict() for r in self.results],
            "total_anomalies": self.total_anomalies,
            "total_errors": self.total_errors,
            "total_warnings": self.total_warnings,
            "total_duration_ms": self.total_duration_ms,
            "report_at": self.report_at.isoformat(),
            "passed": self.passed,
        }

    def describe(self) -> str:
        """Produce a human-readable verification report."""
        lines: list[str] = []
        status = "PASSED" if self.passed else "FAILED"
        lines.append("=" * 72)
        lines.append(f"VERIFICATION REPORT — {status}")
        lines.append(f"Report generated: {self.report_at.isoformat()}")
        lines.append("=" * 72)
        lines.append("")
        lines.append("SUMMARY")
        lines.append(f"  Verifiers run: {len(self.results)}")
        lines.append(f"  Total anomalies: {self.total_anomalies}")
        lines.append(
            f"  Errors: {self.total_errors}, "
            f"Warnings: {self.total_warnings}"
        )
        lines.append(f"  Total duration: {self.total_duration_ms:.1f}ms")
        lines.append("")

        for result in self.results:
            lines.append(result.describe())
            lines.append("")

        # Footer: include erosion coverage and automation metric
        for result in self.results:
            erosion = result.details.get("erosion_coverage")
            if erosion and isinstance(erosion, dict):
                from s0ma.models import ErosionCoverageReport

                report = ErosionCoverageReport(
                    minimise_active=erosion.get("minimise_active", False),
                    prevent_active=erosion.get("prevent_active", False),
                    repair_active=erosion.get("repair_active", False),
                    minimise_coverage=erosion.get("minimise_coverage", 0.0),
                    prevent_coverage=erosion.get("prevent_coverage", 0.0),
                    repair_coverage=erosion.get("repair_coverage", 0.0),
                )
                lines.append(report.describe())
                lines.append("")

            automation = result.details.get("automation_metric")
            if automation is not None:
                lines.append(
                    f"AUTOMATION METRIC (Kounev & Spinner 2015): "
                    f"{automation:.1%}"
                )
                lines.append("")

        lines.append("=" * 72)
        return "\n".join(lines)

    def explain_for_llm(self) -> str:
        """Produce structured, actionable context for LLM consumers.

        Aggregates explain_for_llm() from each VerificationResult,
        providing a complete picture of system health with enough
        context for an LLM to understand and fix all issues without
        additional queries.

        Returns:
            Structured text optimized for LLM consumption.
        """
        lines: list[str] = []
        status = "PASSED" if self.passed else "FAILED"
        lines.append(f"# Verification Report — {status}")
        lines.append(
            f"Ran {len(self.results)} verifiers. "
            f"Found {self.total_anomalies} anomalies "
            f"({self.total_errors} errors, "
            f"{self.total_warnings} warnings) "
            f"in {self.total_duration_ms:.1f}ms."
        )
        lines.append("")

        # Group results by pass/fail for LLM prioritization
        failed = [r for r in self.results if not r.passed]
        passed = [r for r in self.results if r.passed]

        if failed:
            lines.append("## Failed Verifiers (action required)")
            lines.append("")
            for result in failed:
                lines.append(result.explain_for_llm())
                lines.append("")

        if passed:
            lines.append("## Passed Verifiers")
            for result in passed:
                lines.append(
                    f"- {result.verifier_name}: "
                    f"{result.components_checked} components OK"
                )
            lines.append("")

        # Include erosion coverage and automation metric if available
        for result in self.results:
            erosion = result.details.get("erosion_coverage")
            if erosion:
                lines.append("## Erosion Coverage (de Silva 2012)")
                for key, value in erosion.items():
                    lines.append(f"  {key}: {value}")
                lines.append("")

            automation = result.details.get("automation_metric")
            if automation is not None:
                lines.append(
                    f"## Automation Metric (Kounev & Spinner 2015): "
                    f"{automation:.1%}"
                )
                lines.append("")

        return "\n".join(lines)


def _suggest_fix(anomaly: Anomaly) -> str:
    """Generate a fix suggestion based on anomaly kind and details.

    Provides actionable guidance for each biological pathology type,
    including available alternatives when references are invalid.
    """
    from s0ma.types import AnomalyKind

    if anomaly.kind == AnomalyKind.PHANTOM_LIMB:
        if "not registered" in anomaly.message:
            return (
                "Register the component with @component decorator, "
                "or remove the reference if the component was deleted."
            )
        if "cannot be imported" in anomaly.message:
            return (
                "Check that the module path is correct and the "
                "module file exists. The component may have been "
                "moved or renamed."
            )
        return (
            "Ensure the component's source code exists at the "
            "declared module_path and qualified_name."
        )

    if anomaly.kind == AnomalyKind.VESTIGIAL_ORGAN:
        return (
            "This component appears unused. Either add it as a "
            "dependency of another component, verify it is an entry "
            "point, or remove it if no longer needed."
        )

    if anomaly.kind == AnomalyKind.IMMUNE_RESPONSE:
        return (
            "Register the entity with @component, mark it with "
            "@internal if it is a private helper, or install the "
            "import hook to enforce registration."
        )

    if anomaly.kind == AnomalyKind.ATROPHIED_MUSCLE:
        return (
            "This deprecated component is still receiving calls. "
            "Migrate callers to the replacement component, then "
            "remove the deprecated one."
        )

    if anomaly.kind == AnomalyKind.INFLAMMATION:
        details = anomaly.details
        if "max_latency_ms" in details:
            return (
                f"Component exceeded its latency contract "
                f"({details.get('max_latency_ms')}ms). "
                f"Optimize the implementation or update the "
                f"declared max_latency_ms threshold."
            )
        if "error_rate" in details:
            return (
                f"Error rate ({details.get('error_rate', 0):.2%}) "
                f"exceeds threshold. Fix the underlying errors or "
                f"update the declared error_rate_threshold."
            )
        if "layer" in anomaly.message.lower():
            return (
                "A layer boundary violation was detected. "
                "Move the dependency to the correct layer or "
                "reconsider the component's architectural placement."
            )
        return (
            "The component is showing signs of stress. Review "
            "its resource usage and declared profile."
        )

    return "Review the anomaly details and take corrective action."


@dataclass(frozen=True)
class ErosionCoverageReport:
    """de Silva et al. (2012) erosion-control strategy coverage.

    s0ma implements all three strategies simultaneously:
    - Minimise: prevent drift at creation (@component decorator)
    - Prevent: block unregistered code (import hook)
    - Repair: detect and report drift (this verification engine)

    Reference: de Silva & Balasubramaniam (2012), JSS 85(1).
    """

    minimise_active: bool = False
    prevent_active: bool = False
    repair_active: bool = False
    minimise_coverage: float = 0.0
    prevent_coverage: float = 0.0
    repair_coverage: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "minimise_active": self.minimise_active,
            "prevent_active": self.prevent_active,
            "repair_active": self.repair_active,
            "minimise_coverage": self.minimise_coverage,
            "prevent_coverage": self.prevent_coverage,
            "repair_coverage": self.repair_coverage,
            "all_strategies_active": self.all_strategies_active,
        }

    @property
    def all_strategies_active(self) -> bool:
        """True if all three erosion-control strategies are active."""
        return (
            self.minimise_active
            and self.prevent_active
            and self.repair_active
        )

    def describe(self) -> str:
        """Produce a human-readable erosion coverage report."""
        lines: list[str] = []
        lines.append("DE SILVA EROSION COVERAGE")
        lines.append(
            f"  Minimise (prevent drift at creation): "
            f"{'ACTIVE' if self.minimise_active else 'INACTIVE'} "
            f"({self.minimise_coverage:.1%})"
        )
        lines.append(
            f"  Prevent (block unregistered code): "
            f"{'ACTIVE' if self.prevent_active else 'INACTIVE'} "
            f"({self.prevent_coverage:.1%})"
        )
        lines.append(
            f"  Repair (detect and report drift): "
            f"{'ACTIVE' if self.repair_active else 'INACTIVE'} "
            f"({self.repair_coverage:.1%})"
        )
        return "\n".join(lines)


# ======================================================================
# DSL Expansion Models — Module, Edge, and Test Registration
# ======================================================================
#
# These models support the s0ma DSL transpiler's expanded registration
# surface. They are additive — no existing models are modified.
# See PRD §2.7.1 (new registration functions) and §2.7.2 (registry
# schema expansion).


@dataclass
class ModuleMetadata:
    """Metadata for a module-level registration.

    Captures the architectural identity of a ``.s0ma`` module: its layer,
    version, intent, exported component names, content hash, and optional
    tags. Registered via ``register_module()`` in transpiled output.

    This is distinct from ``ComponentSpec`` — it describes a *module*,
    not an individual component.
    """

    name: str
    layer: str
    version: str
    intent: str
    exports: list[str] = field(default_factory=list)
    content_hash: str = ""
    tags: list[str] = field(default_factory=list)
    source_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
        return {
            "name": self.name,
            "layer": self.layer,
            "version": self.version,
            "intent": self.intent,
            "exports": list(self.exports),
            "content_hash": self.content_hash,
            "tags": list(self.tags),
            "source_file": self.source_file,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModuleMetadata:
        """Deserialize from a dictionary."""
        return cls(
            name=data["name"],
            layer=data["layer"],
            version=data["version"],
            intent=data["intent"],
            exports=data.get("exports", []),
            content_hash=data.get("content_hash", ""),
            tags=data.get("tags", []),
            source_file=data.get("source_file"),
        )


@dataclass
class AdoptedFile:
    """A real (non-generated) file registered into the self-model by adoption.

    Adoption (0.11.0, batch-01a D2) makes plain files the model would
    otherwise know nothing about first-class: registered by path,
    verified by content hash, and counted in registration ratios. This
    is the per-file *primitive* under the ``s0ma adopt`` command family
    — the brownfield adoption plan's conversion ladder builds on it.

    Field shapes mirror :class:`ModuleMetadata` (``content_hash`` /
    the path-string convention of ``source_file``). ``path`` is stored
    project-root-relative in POSIX form by the DSL tooling so records
    stay portable; the core registry treats it as an opaque key.
    """

    path: str
    description: str
    content_hash: str = ""
    re_adopt_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Enforce authored intent and advisory-counter invariants at creation."""
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError(
                "AdoptedFile.description is required and must be non-empty; "
                "supply the file's authored intent."
            )
        self.description = self.description.strip()
        if not isinstance(self.re_adopt_count, int) or isinstance(
            self.re_adopt_count, bool
        ):
            raise ValueError("AdoptedFile.re_adopt_count must be an integer.")
        if self.re_adopt_count < 0:
            raise ValueError("AdoptedFile.re_adopt_count cannot be negative.")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "description": self.description,
            "re_adopt_count": self.re_adopt_count,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdoptedFile:
        """Deserialize from a dictionary."""
        description = data.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(
                "AdoptedFile.description is required and must be non-empty; "
                "add an authored intent before loading the adoption record."
            )
        return cls(
            path=data["path"],
            description=description.strip(),
            content_hash=data.get("content_hash", ""),
            re_adopt_count=data.get("re_adopt_count", 0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class RelationshipEdge:
    """A dependency relationship between two components.

    Represents both authored edges (declared via ``depends_on`` or standalone
    ``axon``) and derived edges (inferred from ``raises`` fields or function
    signature annotations). Each edge carries its origin for auditability.

    See PRD §1.12 for authored vs. derived relationship rules.
    """

    source: str
    target: str
    relation: str
    intent: str = ""
    carries: str = ""
    coupling: str = ""
    origin: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "intent": self.intent,
            "carries": self.carries,
            "coupling": self.coupling,
            "origin": self.origin,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RelationshipEdge:
        """Deserialize from a dictionary."""
        return cls(
            source=data["source"],
            target=data["target"],
            relation=data["relation"],
            intent=data.get("intent", ""),
            carries=data.get("carries", ""),
            coupling=data.get("coupling", ""),
            origin=data.get("origin", ""),
        )


@dataclass
class TestRegistration:
    """Registration metadata for a test declaration.

    Links a test to the components it validates, enabling coverage
    queries like "which tests validate this PUBLIC nerve?" and
    release-mode checks for untested PUBLIC nerves.
    """

    name: str
    intent: str
    validates: list[str] = field(default_factory=list)
    source_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
        return {
            "name": self.name,
            "intent": self.intent,
            "validates": list(self.validates),
            "source_file": self.source_file,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestRegistration:
        """Deserialize from a dictionary."""
        return cls(
            name=data["name"],
            intent=data["intent"],
            validates=data.get("validates", []),
            source_file=data.get("source_file"),
        )


@dataclass
class PluginRegistration:
    """Metadata for a registered plugin.

    Represents a first-class plugin that registers components at runtime.
    Tracks what the plugin provides (registers) and what it depends on
    from the core system (requires_core), with dependency validation
    at registration time.
    """

    name: str
    version: str
    intent: str
    registers: list[str] = field(default_factory=list)
    requires_core: list[str] = field(default_factory=list)
    source_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
        result: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "intent": self.intent,
            "registers": list(self.registers),
            "requires_core": list(self.requires_core),
        }
        if self.source_file is not None:
            result["source_file"] = self.source_file
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginRegistration:
        """Deserialize from a dictionary."""
        return cls(
            name=data["name"],
            version=data["version"],
            intent=data["intent"],
            registers=list(data.get("registers", [])),
            requires_core=list(data.get("requires_core", [])),
            source_file=data.get("source_file"),
        )


# ======================================================================
# Documentation subsystem — data models
# ======================================================================
#
# Types that back the doc-ref, doc-guide, and example first-class
# registrations. See design overview §§5, 6, 10.1 and the documentation
# subsystem implementation plan, Milestone 1.
#
# These are pure data carriers — Milestone 1 introduces the types and the
# registry stores only. Registration functions, import-hook integration,
# snapshot surfacing, and downstream API exposure arrive in later
# milestones (M2–M8).


@dataclass(frozen=True)
class SourceSpan:
    """Location of a declaration in its source file.

    Captures the file path and line range so that drift reports, error
    messages, and tooling can point agents and humans back to the exact
    declaration that produced a registration.
    """

    file: str
    start_line: int
    end_line: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "file": self.file,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceSpan:
        """Deserialize from a dictionary."""
        return cls(
            file=data["file"],
            start_line=data["start_line"],
            end_line=data["end_line"],
        )


@dataclass(frozen=True)
class EntityRef:
    """Typed reference to a registered entity.

    Identifies a target of a doc-guide's ``covers`` list, an example's
    ``demonstrates`` list, or any other cross-reference in the
    documentation subsystem. ``module`` is optional for short-form
    references resolved against the enclosing module at registration time.
    """

    kind: str
    name: str
    module: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary, omitting None module."""
        result: dict[str, Any] = {"kind": self.kind, "name": self.name}
        if self.module is not None:
            result["module"] = self.module
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EntityRef:
        """Deserialize from a dictionary."""
        return cls(
            kind=data["kind"],
            name=data["name"],
            module=data.get("module"),
        )


@dataclass(frozen=True)
class FilterExpr:
    """A filter expression used by doc-refs to select the entities they cover.

    Captures the parsed form used by the resolver (``target_kind`` +
    optional ``predicate``) alongside the raw source text so that
    diagnostics can surface the author's original wording.
    """

    target_kind: str
    predicate: str | None
    raw: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "target_kind": self.target_kind,
            "predicate": self.predicate,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FilterExpr:
        """Deserialize from a dictionary."""
        return cls(
            target_kind=data["target_kind"],
            predicate=data.get("predicate"),
            raw=data["raw"],
        )


@dataclass(frozen=True)
class Section:
    """A rendering section inside a doc-ref declaration.

    Each section describes one block of emitted documentation: its title,
    whether it iterates over a collection (``iterate``), how items are
    grouped (``group_by``), and a structured render directive (``render``).
    """

    title: str
    iterate: str | None = None
    group_by: str | None = None
    render: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "title": self.title,
            "iterate": self.iterate,
            "group_by": self.group_by,
            "render": dict(self.render),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Section:
        """Deserialize from a dictionary."""
        return cls(
            title=data["title"],
            iterate=data.get("iterate"),
            group_by=data.get("group_by"),
            render=dict(data.get("render", {})),
        )


@dataclass(frozen=True)
class AssertExpr:
    """A verifiable assertion attached to a doc-guide.

    Stores the assertion's expression text alongside its source span so
    verifiers can report failures with a precise source location.
    """

    expression: str
    source_span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "expression": self.expression,
            "source_span": self.source_span.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssertExpr:
        """Deserialize from a dictionary."""
        return cls(
            expression=data["expression"],
            source_span=SourceSpan.from_dict(data["source_span"]),
        )


@dataclass(frozen=True)
class DocRefRegistration:
    """Registration record for a ``doc-ref`` declaration.

    A doc-ref is a generated-documentation artifact: it selects entities
    from the registry via ``covers`` filter expressions and emits
    structured sections. The ``content_hash`` is a deterministic digest
    over the referenced state, used for drift detection.

    A doc-ref may instead cover a **derived source** — a non-component
    registry named by ``covers: { source: <name> }`` in the DSL — in
    which case ``covers`` is empty and the two ``covers_source*`` fields
    below carry what it selects. They exist so the transitive
    ``content_hash`` moves when the records the doc renders move: before
    they did, a derived doc-ref's registration dropped the discriminator
    entirely, so the hashed snapshot was empty and the rendered table
    could be rewritten from top to bottom under a stable hash (ADR-013
    §3b, and Context fact 5 for how that was found).
    """

    name: str
    module: str
    intent: str
    format: str
    output: str
    covers: list[FilterExpr] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    content_hash: str = ""
    source_span: SourceSpan | None = None
    covers_source: str | None = None
    """Derived source name, or ``None`` for the ``covers`` filter form."""

    covers_source_hash: str | None = None
    """The derived source provider's own hash over its normalized records.

    Not a hash of any rendering of them, and not this registration's
    ``content_hash``: it is the provider's provenance digest, carried here
    so the transitive hash depends on the records. ``None`` whenever
    ``covers_source`` is.
    """

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "name": self.name,
            "module": self.module,
            "intent": self.intent,
            "format": self.format,
            "output": self.output,
            "covers": [c.to_dict() for c in self.covers],
            "sections": [s.to_dict() for s in self.sections],
            "content_hash": self.content_hash,
            "source_span": (
                self.source_span.to_dict() if self.source_span is not None else None
            ),
            "covers_source": self.covers_source,
            "covers_source_hash": self.covers_source_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocRefRegistration:
        """Deserialize from a dictionary."""
        span_data = data.get("source_span")
        return cls(
            name=data["name"],
            module=data["module"],
            intent=data["intent"],
            format=data["format"],
            output=data["output"],
            covers=[FilterExpr.from_dict(c) for c in data.get("covers", [])],
            sections=[Section.from_dict(s) for s in data.get("sections", [])],
            content_hash=data.get("content_hash", ""),
            source_span=SourceSpan.from_dict(span_data) if span_data else None,
            covers_source=data.get("covers_source"),
            covers_source_hash=data.get("covers_source_hash"),
        )


@dataclass(frozen=True)
class DocGuideRegistration:
    """Registration record for a ``doc-guide`` declaration.

    A doc-guide is an authored piece of prose with embedded
    ``{{example::X}}`` references. It covers explicit entities
    (``covers``), asserts declarative properties (``asserts``), and
    references canonical examples (``examples``). Body is stored verbatim.
    """

    name: str
    module: str
    intent: str
    format: str
    output: str
    covers: list[EntityRef] = field(default_factory=list)
    asserts: list[AssertExpr] = field(default_factory=list)
    examples: list[EntityRef] = field(default_factory=list)
    body: str = ""
    content_hash: str = ""
    source_span: SourceSpan | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "name": self.name,
            "module": self.module,
            "intent": self.intent,
            "format": self.format,
            "output": self.output,
            "covers": [c.to_dict() for c in self.covers],
            "asserts": [a.to_dict() for a in self.asserts],
            "examples": [e.to_dict() for e in self.examples],
            "body": self.body,
            "content_hash": self.content_hash,
            "source_span": (
                self.source_span.to_dict() if self.source_span is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocGuideRegistration:
        """Deserialize from a dictionary."""
        span_data = data.get("source_span")
        return cls(
            name=data["name"],
            module=data["module"],
            intent=data["intent"],
            format=data["format"],
            output=data["output"],
            covers=[EntityRef.from_dict(c) for c in data.get("covers", [])],
            asserts=[AssertExpr.from_dict(a) for a in data.get("asserts", [])],
            examples=[EntityRef.from_dict(e) for e in data.get("examples", [])],
            body=data.get("body", ""),
            content_hash=data.get("content_hash", ""),
            source_span=SourceSpan.from_dict(span_data) if span_data else None,
        )


@dataclass(frozen=True)
class ExampleRegistration:
    """Registration record for an ``example`` declaration.

    An example demonstrates one or more components (``demonstrates`` is
    mandatory per design R-30) and runs under the dispatcher selected by
    ``runs_in``. The body is the executable source, stored verbatim so
    that runners can materialize it and drift-checks can hash it.
    """

    name: str
    module: str
    intent: str
    demonstrates: list[EntityRef] = field(default_factory=list)
    runs_in: Literal["standalone", "pytest", "integration"] = "standalone"
    body: str = ""
    source_span: SourceSpan | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "name": self.name,
            "module": self.module,
            "intent": self.intent,
            "demonstrates": [d.to_dict() for d in self.demonstrates],
            "runs_in": self.runs_in,
            "body": self.body,
            "source_span": (
                self.source_span.to_dict() if self.source_span is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExampleRegistration:
        """Deserialize from a dictionary."""
        span_data = data.get("source_span")
        runs_in_value: Literal["standalone", "pytest", "integration"] = (
            data.get("runs_in", "standalone")
        )
        return cls(
            name=data["name"],
            module=data["module"],
            intent=data["intent"],
            demonstrates=[
                EntityRef.from_dict(d) for d in data.get("demonstrates", [])
            ],
            runs_in=runs_in_value,
            body=data.get("body", ""),
            source_span=SourceSpan.from_dict(span_data) if span_data else None,
        )
