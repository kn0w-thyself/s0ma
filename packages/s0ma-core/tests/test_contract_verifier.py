"""Tests for the contract verification engine (Phase 2, Milestone 3).

Tests cover:
- Contract decorators (@precondition, @postcondition, @invariant)
- ContractRegistry (programmatic validator registration)
- ContractVerifier (coverage reporting, performance/error rate checks)
- Global verification flag (enable/disable)
- Integration with ComponentSpec contracts
"""

from __future__ import annotations

import pytest

from s0ma.anomaly_stream import (
    reset_runtime_anomaly_subscribers,
    subscribe_runtime_anomalies,
)
from s0ma.exceptions import ContractViolationError
from s0ma.models import Anomaly, ComponentSpec, Contract
from s0ma.registry import ComponentRegistry
from s0ma.types import (
    AnomalyKind,
    AnomalySeverity,
    ComponentKind,
    Layer,
    VerificationScope,
)
from s0ma.verifiers.contracts import (
    ContractRegistry,
    ContractValidatorEntry,
    ContractValidators,
    ContractVerifier,
    get_contract_registry,
    is_contract_verification_enabled,
    postcondition,
    precondition,
    reset_contract_registry,
    set_contract_verification,
)


@pytest.fixture(autouse=True)
def _reset_contracts() -> None:
    """Reset contract verification state after each test."""
    yield  # type: ignore[misc]
    reset_contract_registry()
    set_contract_verification(enabled=True)


@pytest.fixture()
def contract_registry() -> ContractRegistry:
    """A fresh ContractRegistry instance."""
    return ContractRegistry()


@pytest.fixture()
def verifier() -> ContractVerifier:
    """A ContractVerifier instance."""
    return ContractVerifier()


def _make_spec(
    name: str,
    *,
    preconditions: list[str] | None = None,
    postconditions: list[str] | None = None,
    invariants: list[str] | None = None,
    max_latency_ms: float | None = None,
    error_rate_threshold: float | None = None,
) -> ComponentSpec:
    """Helper to create a ComponentSpec with contracts."""
    return ComponentSpec(
        name=name,
        kind=ComponentKind.SERVICE,
        layer=Layer.DOMAIN,
        intent="Test component for contract verification testing",
        contracts=Contract(
            preconditions=preconditions or [],
            postconditions=postconditions or [],
            invariants=invariants or [],
            max_latency_ms=max_latency_ms,
            error_rate_threshold=error_rate_threshold,
        ),
        module_path="tests.test_fixtures.contract_violators",
        qualified_name=(
            "tests.test_fixtures.contract_violators." + name
        ),
    )


# ======================================================================
# Test: Precondition Decorator
# ======================================================================


class TestPreconditionDecorator:
    """Tests for the @precondition decorator."""

    def test_precondition_passes_when_valid(self) -> None:
        """Precondition validator returns True -> method executes."""
        from tests.test_fixtures.contract_violators import Calculator

        calc = Calculator()
        result = calc.divide(10.0, 2.0)
        assert result == 5.0

    def test_precondition_violation_raises(self) -> None:
        """Precondition returns False -> ContractViolationError."""
        from tests.test_fixtures.contract_violators import Calculator

        calc = Calculator()
        with pytest.raises(
            ContractViolationError, match="Precondition failed"
        ):
            calc.divide(10.0, 0.0)

    def test_precondition_error_message_contains_description(
        self,
    ) -> None:
        """Error message includes the contract description."""
        from tests.test_fixtures.contract_violators import Calculator

        calc = Calculator()
        with pytest.raises(
            ContractViolationError,
            match="divisor must not be zero",
        ):
            calc.divide(10.0, 0.0)

    def test_precondition_disabled_allows_violation(self) -> None:
        """When verification disabled, precondition is not checked."""
        from tests.test_fixtures.contract_violators import Calculator

        set_contract_verification(enabled=False)
        calc = Calculator()
        # Would raise ZeroDivisionError, not ContractViolationError
        with pytest.raises(ZeroDivisionError):
            calc.divide(10.0, 0.0)

    def test_precondition_stores_metadata(self) -> None:
        """@precondition stores validators on the function."""
        from tests.test_fixtures.contract_violators import Calculator

        method = Calculator.divide
        assert hasattr(method, "__contract_preconditions__")
        entries = method.__contract_preconditions__
        assert len(entries) == 1
        assert entries[0].kind == "precondition"
        assert "divisor" in entries[0].description


# ======================================================================
# Test: Postcondition Decorator
# ======================================================================


class TestPostconditionDecorator:
    """Tests for the @postcondition decorator."""

    def test_postcondition_passes_when_valid(self) -> None:
        """Postcondition returns True -> result returned normally."""
        from tests.test_fixtures.contract_violators import Calculator

        calc = Calculator()
        result = calc.absolute(-5.0)
        assert result == 5.0

    def test_postcondition_violation_raises(self) -> None:
        """Postcondition returns False -> ContractViolationError."""
        from tests.test_fixtures.contract_violators import Calculator

        calc = Calculator()
        with pytest.raises(
            ContractViolationError, match="Postcondition failed"
        ):
            calc.broken_absolute(5.0)

    def test_postcondition_error_message_contains_description(
        self,
    ) -> None:
        """Error message includes the contract description."""
        from tests.test_fixtures.contract_violators import Calculator

        calc = Calculator()
        with pytest.raises(
            ContractViolationError,
            match="result must be non-negative",
        ):
            calc.broken_absolute(5.0)

    def test_postcondition_disabled_allows_violation(self) -> None:
        """When verification disabled, bad return is not checked."""
        from tests.test_fixtures.contract_violators import Calculator

        set_contract_verification(enabled=False)
        calc = Calculator()
        result = calc.broken_absolute(5.0)
        assert result == -5.0  # Violation allowed when disabled

    def test_stacked_pre_and_postcondition(self) -> None:
        """Both @precondition and @postcondition on one method."""
        from tests.test_fixtures.contract_violators import Calculator

        calc = Calculator()
        result = calc.double_positive(3.0)
        assert result == 6.0

    def test_stacked_precondition_catches_first(self) -> None:
        """Precondition checked before execution."""
        from tests.test_fixtures.contract_violators import Calculator

        calc = Calculator()
        with pytest.raises(
            ContractViolationError, match="input must be positive"
        ):
            calc.double_positive(-1.0)

    def test_postcondition_pass_args_receives_call_arguments(self) -> None:
        """pass_args=True hands the validator (result, *args, **kwargs)."""
        seen: list[tuple[float, float, float]] = []

        def _validator(result: float, x: float, *, offset: float = 0.0) -> bool:
            seen.append((result, x, offset))
            return result == x + offset

        @postcondition(_validator, "result equals x plus offset", pass_args=True)
        def shift(x: float, *, offset: float = 0.0) -> float:
            return x + offset

        assert shift(2.0, offset=1.0) == 3.0
        assert seen == [(3.0, 2.0, 1.0)]

    def test_postcondition_pass_args_violation_raises(self) -> None:
        """An effect-checking validator can fail the contract."""

        @postcondition(
            lambda result, x: bool(result > x),
            "result must exceed input",
            pass_args=True,
        )
        def identity(x: float) -> float:
            return x

        with pytest.raises(
            ContractViolationError, match="result must exceed input"
        ):
            identity(1.0)

    def test_postcondition_default_still_receives_result_only(self) -> None:
        """Without pass_args, the validator sees only the return value."""
        seen: list[float] = []

        def _validator(result: float) -> bool:
            seen.append(result)
            return True

        @postcondition(_validator, "records result")
        def echo(x: float) -> float:
            return x

        assert echo(4.0) == 4.0
        assert seen == [4.0]


# ======================================================================
# Test: Contract violations publish on the runtime anomaly stream
# ======================================================================


class TestContractViolationEmission:
    """Violations emit NOCICEPTION on the runtime anomaly stream."""

    @pytest.fixture(autouse=True)
    def _reset_stream(self) -> None:
        """Isolate runtime-anomaly subscribers between tests."""
        yield  # type: ignore[misc]
        reset_runtime_anomaly_subscribers()

    def test_precondition_violation_emits_nociception(self) -> None:
        """A failing precondition publishes before raising."""
        from tests.test_fixtures.contract_violators import Calculator

        received: list[Anomaly] = []
        subscribe_runtime_anomalies(received.append)

        calc = Calculator()
        with pytest.raises(ContractViolationError):
            calc.divide(10.0, 0.0)

        assert len(received) == 1
        anomaly = received[0]
        assert anomaly.kind is AnomalyKind.NOCICEPTION
        assert anomaly.severity is AnomalySeverity.ERROR
        assert anomaly.component_name == "Calculator.divide"
        assert anomaly.details["contract_kind"] == "precondition"
        assert "Precondition failed" in anomaly.message

    def test_postcondition_violation_emits_nociception(self) -> None:
        """A failing postcondition publishes before raising."""
        from tests.test_fixtures.contract_violators import Calculator

        received: list[Anomaly] = []
        subscribe_runtime_anomalies(received.append)

        calc = Calculator()
        with pytest.raises(ContractViolationError):
            calc.broken_absolute(5.0)

        assert len(received) == 1
        assert received[0].kind is AnomalyKind.NOCICEPTION
        assert received[0].details["contract_kind"] == "postcondition"

    def test_passing_contract_emits_nothing(self) -> None:
        """Clean calls stay silent on the stream."""
        from tests.test_fixtures.contract_violators import Calculator

        received: list[Anomaly] = []
        subscribe_runtime_anomalies(received.append)

        assert Calculator().divide(10.0, 2.0) == 5.0
        assert received == []

    def test_no_emission_when_verification_disabled(self) -> None:
        """Disabled verification means no checks and no pain signals."""
        from tests.test_fixtures.contract_violators import Calculator

        received: list[Anomaly] = []
        subscribe_runtime_anomalies(received.append)

        set_contract_verification(enabled=False)
        assert Calculator().broken_absolute(5.0) == -5.0
        assert received == []


# ======================================================================
# Test: Invariant Decorator
# ======================================================================


class TestInvariantDecorator:
    """Tests for the @invariant class decorator."""

    def test_invariant_stores_metadata(self) -> None:
        """@invariant stores validators on the class."""
        from tests.test_fixtures.contract_violators import BankAccount

        assert hasattr(BankAccount, "__contract_invariants__")
        entries = BankAccount.__contract_invariants__
        assert len(entries) == 1
        assert entries[0].kind == "invariant"
        assert "balance" in entries[0].description

    def test_invariant_holds_for_valid_state(self) -> None:
        """Invariant validator returns True for valid instance."""
        from tests.test_fixtures.contract_violators import BankAccount

        account = BankAccount(100.0)
        entry = BankAccount.__contract_invariants__[0]
        assert entry.validator(account) is True

    def test_invariant_fails_for_invalid_state(self) -> None:
        """Invariant validator returns False for invalid instance."""
        from tests.test_fixtures.contract_violators import BankAccount

        account = BankAccount(-50.0)
        entry = BankAccount.__contract_invariants__[0]
        assert entry.validator(account) is False

    def test_invariant_class_still_functional(self) -> None:
        """@invariant doesn't break normal class behavior."""
        from tests.test_fixtures.contract_violators import BankAccount

        account = BankAccount(100.0)
        account.deposit(50.0)
        assert account.balance == 150.0
        account.withdraw(30.0)
        assert account.balance == 120.0


# ======================================================================
# Test: ContractRegistry
# ======================================================================


class TestContractRegistry:
    """Tests for the ContractRegistry."""

    def test_register_precondition(
        self, contract_registry: ContractRegistry
    ) -> None:
        """Register and retrieve a precondition validator."""
        contract_registry.register_precondition(
            "Foo", "x > 0", lambda x: x > 0
        )
        vals = contract_registry.get_validators("Foo")
        assert vals is not None
        assert len(vals.preconditions) == 1
        assert vals.preconditions[0].description == "x > 0"

    def test_register_postcondition(
        self, contract_registry: ContractRegistry
    ) -> None:
        """Register and retrieve a postcondition validator."""
        contract_registry.register_postcondition(
            "Foo", "result > 0", lambda r: r > 0
        )
        vals = contract_registry.get_validators("Foo")
        assert vals is not None
        assert len(vals.postconditions) == 1

    def test_register_invariant(
        self, contract_registry: ContractRegistry
    ) -> None:
        """Register and retrieve an invariant validator."""
        contract_registry.register_invariant(
            "Foo", "state valid", lambda self: True
        )
        vals = contract_registry.get_validators("Foo")
        assert vals is not None
        assert len(vals.invariants) == 1

    def test_get_validators_returns_none_for_unknown(
        self, contract_registry: ContractRegistry
    ) -> None:
        """get_validators returns None for unregistered component."""
        assert contract_registry.get_validators("Unknown") is None

    def test_total_count(
        self, contract_registry: ContractRegistry
    ) -> None:
        """total_count sums all validator types."""
        contract_registry.register_precondition(
            "Foo", "a", lambda: True
        )
        contract_registry.register_postcondition(
            "Foo", "b", lambda: True
        )
        contract_registry.register_invariant(
            "Foo", "c", lambda: True
        )
        vals = contract_registry.get_validators("Foo")
        assert vals is not None
        assert vals.total_count == 3

    def test_reset_clears_all(
        self, contract_registry: ContractRegistry
    ) -> None:
        """reset() clears all validators."""
        contract_registry.register_precondition(
            "Foo", "a", lambda: True
        )
        contract_registry.reset()
        assert contract_registry.get_validators("Foo") is None

    def test_global_singleton(self) -> None:
        """get_contract_registry returns a singleton."""
        reg1 = get_contract_registry()
        reg2 = get_contract_registry()
        assert reg1 is reg2


# ======================================================================
# Test: ContractVerifier
# ======================================================================


class TestContractVerifier:
    """Tests for the ContractVerifier class."""

    def test_verifier_name_and_scope(
        self, verifier: ContractVerifier
    ) -> None:
        """Verifier has correct name and scope."""
        assert verifier.name == "Contract Verifier"
        assert verifier.scope == VerificationScope.CONTRACT

    def test_verify_empty_registry(
        self, verifier: ContractVerifier
    ) -> None:
        """verify() on empty registry produces clean result."""
        registry = ComponentRegistry(persist=False)
        result = verifier.verify(registry)
        assert result.passed
        assert result.components_checked == 0
        assert result.scope == VerificationScope.CONTRACT

    def test_verify_components_with_no_contracts(
        self, verifier: ContractVerifier
    ) -> None:
        """Components without contracts report honest zero coverage."""
        registry = ComponentRegistry(persist=False)
        spec = ComponentSpec(
            name="NoContracts",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A component with default empty contracts",
        )
        registry.register(spec)

        result = verifier.verify(registry)
        assert result.passed
        coverage = result.details["contract_coverage"]
        assert coverage["total_string_contracts"] == 0
        assert coverage["coverage_percentage"] == 0.0

    def test_verify_coverage_report_accurate(
        self, verifier: ContractVerifier
    ) -> None:
        """Coverage report correctly counts string vs executable."""
        registry = ComponentRegistry(persist=False)
        spec = _make_spec(
            "TestSvc",
            preconditions=["input valid", "state ready"],
            postconditions=["returns result"],
        )
        registry.register(spec)

        # Register 1 executable validator out of 3 string contracts
        creg = get_contract_registry()
        creg.register_precondition(
            "TestSvc", "input valid", lambda: True
        )

        result = verifier.verify(registry)
        coverage = result.details["contract_coverage"]
        assert coverage["total_string_contracts"] == 3
        assert coverage["total_executable_contracts"] == 1
        assert coverage["documentation_only"] == 2
        assert abs(coverage["coverage_percentage"] - 1 / 3) < 0.01

    def test_verify_documentation_only_not_failures(
        self, verifier: ContractVerifier
    ) -> None:
        """Documentation-only contracts are tracked, not failures."""
        registry = ComponentRegistry(persist=False)
        spec = _make_spec(
            "DocOnly",
            preconditions=["something complex"],
            invariants=["no side effects"],
        )
        registry.register(spec)

        result = verifier.verify(registry)
        assert result.passed  # No errors — doc-only is not a failure
        coverage = result.details["contract_coverage"]
        assert coverage["documentation_only"] == 2

    def test_verify_passes_for_valid_components(
        self, verifier: ContractVerifier
    ) -> None:
        """Verifier passes for well-formed components."""
        registry = ComponentRegistry(persist=False)
        spec = _make_spec(
            "ValidSvc",
            preconditions=["input > 0"],
        )
        registry.register(spec)

        creg = get_contract_registry()
        creg.register_precondition(
            "ValidSvc", "input > 0", lambda x: x > 0
        )

        result = verifier.verify(registry)
        assert result.passed
        coverage = result.details["contract_coverage"]
        assert coverage["coverage_percentage"] == 1.0

    def test_verify_handles_no_contracts_gracefully(
        self, verifier: ContractVerifier
    ) -> None:
        """Components with default empty contracts produce no anomalies."""
        registry = ComponentRegistry(persist=False)
        spec = ComponentSpec(
            name="Plain",
            kind=ComponentKind.FUNCTION,
            layer=Layer.APPLICATION,
            intent="A plain function with no declared contracts",
        )
        registry.register(spec)

        result = verifier.verify(registry)
        assert result.passed
        assert len(result.anomalies) == 0

    def test_verify_incremental_existing(
        self, verifier: ContractVerifier
    ) -> None:
        """verify_incremental for an existing component."""
        registry = ComponentRegistry(persist=False)
        spec = _make_spec(
            "IncSvc",
            preconditions=["ready"],
        )
        registry.register(spec)

        result = verifier.verify_incremental(registry, "IncSvc")
        assert result.passed
        assert result.components_checked == 1

    def test_verify_incremental_unregistered(
        self, verifier: ContractVerifier
    ) -> None:
        """verify_incremental for unregistered component -> error."""
        registry = ComponentRegistry(persist=False)
        result = verifier.verify_incremental(registry, "Ghost")
        assert not result.passed
        assert result.anomalies[0].kind == AnomalyKind.PHANTOM_LIMB


# ======================================================================
# Test: Performance Contract
# ======================================================================


class TestPerformanceContract:
    """Tests for performance contract checking."""

    def test_performance_within_threshold(self) -> None:
        """Fast function within max_latency_ms -> no anomalies."""
        from tests.test_fixtures.contract_violators import (
            fast_function,
        )

        _, anomalies = ContractVerifier.check_performance(
            fast_function, 1000.0, "FastFunc"
        )
        assert len(anomalies) == 0

    def test_performance_exceeds_threshold(self) -> None:
        """Slow function exceeding max_latency_ms -> INFLAMMATION."""
        from tests.test_fixtures.contract_violators import (
            slow_function,
        )

        _, anomalies = ContractVerifier.check_performance(
            slow_function, 10.0, "SlowFunc"
        )
        assert len(anomalies) == 1
        assert anomalies[0].kind == AnomalyKind.INFLAMMATION
        assert anomalies[0].severity == AnomalySeverity.WARNING
        assert anomalies[0].details["gate_relevant"] is True
        assert anomalies[0].details["gate_category"] == "performance_contract"
        assert "exceeded" in anomalies[0].message

    def test_performance_returns_result(self) -> None:
        """check_performance returns the function's return value."""
        from tests.test_fixtures.contract_violators import (
            fast_function,
        )

        result, _ = ContractVerifier.check_performance(
            fast_function, 1000.0, "FastFunc"
        )
        assert result == "done"


# ======================================================================
# Test: Error Rate Contract
# ======================================================================


class TestErrorRateContract:
    """Tests for error rate threshold checking."""

    def test_error_rate_within_threshold(self) -> None:
        """Error rate below threshold -> no anomalies."""
        anomalies = ContractVerifier.check_error_rate(
            error_count=1,
            total_count=100,
            threshold=0.05,
            component_name="LowErr",
        )
        assert len(anomalies) == 0

    def test_error_rate_exceeds_threshold(self) -> None:
        """Error rate above threshold -> INFLAMMATION."""
        anomalies = ContractVerifier.check_error_rate(
            error_count=20,
            total_count=100,
            threshold=0.1,
            component_name="HighErr",
        )
        assert len(anomalies) == 1
        assert anomalies[0].kind == AnomalyKind.INFLAMMATION
        assert anomalies[0].severity == AnomalySeverity.WARNING
        assert anomalies[0].details["gate_relevant"] is True
        assert anomalies[0].details["gate_category"] == "error_rate_contract"
        assert "20.00%" in anomalies[0].message

    def test_error_rate_zero_total(self) -> None:
        """Zero total invocations -> no anomalies."""
        anomalies = ContractVerifier.check_error_rate(
            error_count=0,
            total_count=0,
            threshold=0.1,
            component_name="NoData",
        )
        assert len(anomalies) == 0

    def test_error_rate_details(self) -> None:
        """Error rate anomaly includes detailed metrics."""
        anomalies = ContractVerifier.check_error_rate(
            error_count=5,
            total_count=10,
            threshold=0.1,
            component_name="DetailTest",
        )
        assert len(anomalies) == 1
        details = anomalies[0].details
        assert details["error_rate"] == 0.5
        assert details["threshold"] == 0.1
        assert details["error_count"] == 5
        assert details["total_count"] == 10


# ======================================================================
# Test: Verification Flag
# ======================================================================


class TestVerificationFlag:
    """Tests for the global verification enable/disable flag."""

    def test_enabled_by_default(self) -> None:
        """Contract verification is enabled by default."""
        assert is_contract_verification_enabled() is True

    def test_disable_and_enable(self) -> None:
        """set_contract_verification toggles the flag."""
        set_contract_verification(enabled=False)
        assert is_contract_verification_enabled() is False
        set_contract_verification(enabled=True)
        assert is_contract_verification_enabled() is True

    def test_decorators_no_effect_when_disabled(self) -> None:
        """Contract decorators have no effect when disabled."""
        set_contract_verification(enabled=False)

        @precondition(lambda x: x > 0, "positive")
        def guarded(x: int) -> int:
            return x

        # Negative input should pass through without error
        result = guarded(-1)
        assert result == -1


# ======================================================================
# Test: Data Structures
# ======================================================================


class TestContractDataStructures:
    """Tests for ContractValidatorEntry and ContractValidators."""

    def test_validator_entry_creation(self) -> None:
        """ContractValidatorEntry can be constructed."""
        entry = ContractValidatorEntry(
            description="x > 0",
            validator=lambda x: x > 0,
            kind="precondition",
        )
        assert entry.description == "x > 0"
        assert entry.kind == "precondition"
        assert entry.validator(5) is True
        assert entry.validator(-1) is False

    def test_validators_empty(self) -> None:
        """ContractValidators defaults to empty lists."""
        vals = ContractValidators(component_name="Test")
        assert vals.total_count == 0
        assert len(vals.preconditions) == 0
        assert len(vals.postconditions) == 0
        assert len(vals.invariants) == 0
