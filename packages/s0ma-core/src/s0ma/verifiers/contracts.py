"""Contract verifier — executes declared contracts as runtime assertions.

Phase 1 contracts are natural language strings. Phase 2 makes a subset
executable by supporting callable validators alongside the string
descriptions. The ContractVerifier reports on contract coverage (what
percentage of declared contracts have callable backing) and detects
violations through callable validator execution.

Components:
    ContractRegistry: Stores executable contract validators by component name
    ContractVerifier: Implements the Verifier protocol for contract checks
    precondition/postcondition/invariant: Decorators for executable contracts
"""

from __future__ import annotations

import functools
import os
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from s0ma.anomaly_stream import emit_runtime_anomaly
from s0ma.exceptions import ContractViolationError
from s0ma.models import Anomaly, VerificationResult
from s0ma.types import AnomalyKind, AnomalySeverity, VerificationScope

if TYPE_CHECKING:
    from collections.abc import Callable

    from s0ma.registry import ComponentRegistry
    from s0ma.verifiers.discovery import DiscoveredSurface

__all__ = [
    "ContractRegistry",
    "ContractVerifier",
    "get_contract_registry",
    "reset_contract_registry",
    "precondition",
    "postcondition",
    "invariant",
    "is_contract_verification_enabled",
    "set_contract_verification",
]

_F = TypeVar("_F", bound="Callable[..., Any]")
_T = TypeVar("_T")


# ======================================================================
# Global contract verification flag
# ======================================================================

_VERIFY_CONTRACTS = os.environ.get("S0MA_VERIFY_CONTRACTS", "1") != "0"


def is_contract_verification_enabled() -> bool:
    """Check whether contract verification is currently enabled."""
    return _VERIFY_CONTRACTS


def set_contract_verification(enabled: bool) -> None:
    """Enable or disable contract verification at runtime.

    When disabled, contract decorators pass through without checking.
    """
    global _VERIFY_CONTRACTS  # noqa: PLW0603
    _VERIFY_CONTRACTS = enabled


# ======================================================================
# Contract validator data structures
# ======================================================================


@dataclass
class ContractValidatorEntry:
    """A callable validator linked to a contract description string."""

    description: str
    validator: Callable[..., bool]
    kind: str  # "precondition", "postcondition", or "invariant"


@dataclass
class ContractValidators:
    """All callable validators for a single component."""

    component_name: str
    preconditions: list[ContractValidatorEntry] = field(default_factory=list)
    postconditions: list[ContractValidatorEntry] = field(default_factory=list)
    invariants: list[ContractValidatorEntry] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        """Total number of registered validators."""
        return (
            len(self.preconditions)
            + len(self.postconditions)
            + len(self.invariants)
        )


# ======================================================================
# Contract Registry
# ======================================================================


class ContractRegistry:
    """Stores executable contract validators linked to component names.

    Separate from the ComponentRegistry — this stores callable validators
    that back the string-based contracts in ComponentSpec. Validators can
    be registered programmatically or by the contract decorators.
    """

    def __init__(self) -> None:
        self._validators: dict[str, ContractValidators] = {}
        self._lock = threading.Lock()

    def register_precondition(
        self,
        component_name: str,
        description: str,
        validator: Callable[..., bool],
    ) -> None:
        """Register a precondition validator for a component."""
        with self._lock:
            vals = self._get_or_create(component_name)
            vals.preconditions.append(
                ContractValidatorEntry(description, validator, "precondition")
            )

    def register_postcondition(
        self,
        component_name: str,
        description: str,
        validator: Callable[..., bool],
    ) -> None:
        """Register a postcondition validator for a component."""
        with self._lock:
            vals = self._get_or_create(component_name)
            vals.postconditions.append(
                ContractValidatorEntry(description, validator, "postcondition")
            )

    def register_invariant(
        self,
        component_name: str,
        description: str,
        validator: Callable[..., bool],
    ) -> None:
        """Register an invariant validator for a component."""
        with self._lock:
            vals = self._get_or_create(component_name)
            vals.invariants.append(
                ContractValidatorEntry(description, validator, "invariant")
            )

    def get_validators(
        self, component_name: str
    ) -> ContractValidators | None:
        """Get all validators for a component, or None."""
        return self._validators.get(component_name)

    def get_all(self) -> dict[str, ContractValidators]:
        """Get a copy of all registered validators."""
        return dict(self._validators)

    def reset(self) -> None:
        """Clear all registered validators."""
        with self._lock:
            self._validators.clear()

    def _get_or_create(
        self, component_name: str
    ) -> ContractValidators:
        if component_name not in self._validators:
            self._validators[component_name] = ContractValidators(
                component_name=component_name
            )
        return self._validators[component_name]


# ======================================================================
# Global contract registry singleton
# ======================================================================

_global_contract_registry: ContractRegistry | None = None
_global_contract_lock = threading.Lock()


def get_contract_registry() -> ContractRegistry:
    """Get or create the global ContractRegistry singleton."""
    global _global_contract_registry  # noqa: PLW0603
    if _global_contract_registry is None:
        with _global_contract_lock:
            if _global_contract_registry is None:
                _global_contract_registry = ContractRegistry()
    return _global_contract_registry


def reset_contract_registry() -> None:
    """Reset the global ContractRegistry singleton."""
    global _global_contract_registry  # noqa: PLW0603
    with _global_contract_lock:
        if _global_contract_registry is not None:
            _global_contract_registry.reset()
        _global_contract_registry = None


# ======================================================================
# Contract Decorators
# ======================================================================


def precondition(
    validator: Callable[..., bool],
    description: str = "",
) -> Callable[[_F], _F]:
    """Method decorator: check a precondition before invocation.

    When verification is enabled, the validator is called with the same
    arguments as the method. Returns False -> ContractViolationError.
    When disabled, passes through with only a boolean check overhead.

    Args:
        validator: Callable returning True if the precondition holds.
        description: Links to the corresponding string contract.
    """

    def decorator(func: _F) -> _F:
        if not hasattr(func, "__contract_preconditions__"):
            func.__contract_preconditions__ = []  # type: ignore[attr-defined]
        func.__contract_preconditions__.append(  # type: ignore[attr-defined]
            ContractValidatorEntry(description, validator, "precondition")
        )

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if _VERIFY_CONTRACTS and not validator(*args, **kwargs):
                message = (
                    f"Precondition failed for {func.__qualname__}: "
                    f"{description or 'unnamed precondition'}"
                )
                _emit_contract_violation(
                    "precondition", func.__qualname__, message, description
                )
                raise ContractViolationError(message)
            return func(*args, **kwargs)

        wrapper.__contract_preconditions__ = (  # type: ignore[attr-defined]
            func.__contract_preconditions__  # type: ignore[attr-defined]
        )
        return wrapper  # type: ignore[return-value]

    return decorator


def postcondition(
    validator: Callable[..., bool],
    description: str = "",
    *,
    pass_args: bool = False,
) -> Callable[[_F], _F]:
    """Method decorator: check a postcondition after invocation.

    The validator is called with the return value. Returns False ->
    ContractViolationError raised (when verification is enabled).

    With ``pass_args=True`` the validator is instead called as
    ``validator(result, *args, **kwargs)`` — the same arguments the
    method received, after the result. Effect-checking contracts need
    this to compare a commanded action against its measured outcome
    (ADR-003; hw-foundation M1). The default is byte-for-byte the old
    result-only behavior.

    Args:
        validator: Callable taking return value, True if postcondition holds.
        description: Links to the corresponding string contract.
        pass_args: Also hand the validator the call's arguments.
    """

    def decorator(func: _F) -> _F:
        if not hasattr(func, "__contract_postconditions__"):
            func.__contract_postconditions__ = []  # type: ignore[attr-defined]
        func.__contract_postconditions__.append(  # type: ignore[attr-defined]
            ContractValidatorEntry(description, validator, "postcondition")
        )

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = func(*args, **kwargs)
            if _VERIFY_CONTRACTS:
                holds = (
                    validator(result, *args, **kwargs)
                    if pass_args
                    else validator(result)
                )
                if not holds:
                    message = (
                        f"Postcondition failed for {func.__qualname__}: "
                        f"{description or 'unnamed postcondition'}"
                    )
                    _emit_contract_violation(
                        "postcondition", func.__qualname__, message, description
                    )
                    raise ContractViolationError(message)
            return result

        wrapper.__contract_postconditions__ = (  # type: ignore[attr-defined]
            func.__contract_postconditions__  # type: ignore[attr-defined]
        )
        return wrapper  # type: ignore[return-value]

    return decorator


def invariant(
    validator: Callable[..., bool],
    description: str = "",
) -> Callable[[_T], _T]:
    """Class decorator: register an invariant validator.

    Stores the validator on the class for discovery by the
    ContractVerifier. The validator takes a class instance and
    returns True if the invariant holds.

    Args:
        validator: Callable taking instance, True if invariant holds.
        description: Links to the corresponding string contract.
    """

    def decorator(cls: _T) -> _T:
        if not hasattr(cls, "__contract_invariants__"):
            cls.__contract_invariants__ = []  # type: ignore[attr-defined]
        cls.__contract_invariants__.append(  # type: ignore[attr-defined]
            ContractValidatorEntry(description, validator, "invariant")
        )
        return cls

    return decorator


def _emit_contract_violation(
    contract_kind: str,
    qualname: str,
    message: str,
    description: str,
) -> None:
    """Publish a NOCICEPTION anomaly for a live contract violation.

    Runs on the failing call's thread immediately before the
    ContractViolationError is raised, so runtime-anomaly subscribers
    hear the pain signal even when the caller swallows the exception.
    """
    emit_runtime_anomaly(
        Anomaly(
            kind=AnomalyKind.NOCICEPTION,
            severity=AnomalySeverity.ERROR,
            component_name=qualname,
            message=message,
            details={
                "contract_kind": contract_kind,
                "description": description,
                "source": "contract_decorator",
            },
        )
    )


# ======================================================================
# Contract Verifier
# ======================================================================


class ContractVerifier:
    """Verifies component contracts: coverage reporting and validation.

    Reports on contract coverage (executable vs documentation-only)
    and provides methods to check performance and error rate contracts.
    Runtime precondition/postcondition checking is handled by the
    contract decorators; this verifier performs structural analysis.
    """

    @property
    def name(self) -> str:
        """Human-readable name for this verifier."""
        return "Contract Verifier"

    @property
    def scope(self) -> VerificationScope:
        """This verifier performs contract checks."""
        return VerificationScope.CONTRACT

    def verify(
        self,
        registry: ComponentRegistry,
        *,
        discovered_surface: DiscoveredSurface | None = None,
    ) -> VerificationResult:
        """Run contract verification against all registered components.

        Counts declared string contracts vs executable validators
        and computes coverage percentage.
        """
        start_ns = time.perf_counter_ns()
        anomalies: list[Anomaly] = []
        components_checked = 0
        checks_performed = 0
        total_string = 0
        total_executable = 0

        contract_reg = get_contract_registry()

        from s0ma.verifiers.discovery import (
            registered_surface_identifiers,
            unregistered_surface_anomaly,
        )

        registered_specs = registry.get_all()
        registered_surface = registered_surface_identifiers(registry)
        discovery_anomaly = unregistered_surface_anomaly(
            discovered_surface, registered_surface,
        )
        if discovery_anomaly is not None:
            anomalies.append(discovery_anomaly)
            checks_performed += 1

        for comp_name, spec in registered_specs.items():
            components_checked += 1
            checks_performed += 1

            string_count = (
                len(spec.contracts.preconditions)
                + len(spec.contracts.postconditions)
                + len(spec.contracts.invariants)
            )
            total_string += string_count

            validators = contract_reg.get_validators(comp_name)
            exec_count = validators.total_count if validators else 0
            total_executable += min(exec_count, string_count)

            if spec.contracts.max_latency_ms is not None:
                checks_performed += 1
            if spec.contracts.error_rate_threshold is not None:
                checks_performed += 1

        coverage = total_executable / total_string if total_string > 0 else 0.0
        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

        return VerificationResult(
            verifier_name=self.name,
            scope=self.scope,
            anomalies=anomalies,
            components_checked=components_checked,
            checks_performed=checks_performed,
            duration_ms=elapsed_ms,
            details={
                "contract_coverage": {
                    "total_string_contracts": total_string,
                    "total_executable_contracts": total_executable,
                    "coverage_percentage": coverage,
                    "documentation_only": (
                        total_string - total_executable
                    ),
                },
                "discovered_surface": {
                    "provided": discovered_surface is not None,
                    "count": (
                        len(discovered_surface.declarations)
                        if discovered_surface is not None
                        else 0
                    ),
                    "unregistered": (
                        len(
                            discovered_surface.unregistered_against(
                                registered_surface,
                            )
                        )
                        if discovered_surface is not None
                        else 0
                    ),
                },
            },
        )

    def verify_incremental(
        self, registry: ComponentRegistry, component_name: str
    ) -> VerificationResult:
        """Verify contracts for a single component."""
        start_ns = time.perf_counter_ns()

        spec = registry.get(component_name)
        if spec is None:
            elapsed_ms = (
                (time.perf_counter_ns() - start_ns) / 1_000_000
            )
            return VerificationResult(
                verifier_name=self.name,
                scope=self.scope,
                anomalies=[
                    Anomaly(
                        kind=AnomalyKind.PHANTOM_LIMB,
                        severity=AnomalySeverity.ERROR,
                        component_name=component_name,
                        message=(
                            f"Component '{component_name}' "
                            f"is not registered"
                        ),
                    )
                ],
                components_checked=0,
                checks_performed=1,
                duration_ms=elapsed_ms,
            )

        string_count = (
            len(spec.contracts.preconditions)
            + len(spec.contracts.postconditions)
            + len(spec.contracts.invariants)
        )
        contract_reg = get_contract_registry()
        validators = contract_reg.get_validators(component_name)
        exec_count = validators.total_count if validators else 0
        capped = min(exec_count, string_count)
        coverage = capped / string_count if string_count > 0 else 0.0
        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

        return VerificationResult(
            verifier_name=self.name,
            scope=self.scope,
            anomalies=[],
            components_checked=1,
            checks_performed=1,
            duration_ms=elapsed_ms,
            details={
                "contract_coverage": {
                    "total_string_contracts": string_count,
                    "total_executable_contracts": capped,
                    "coverage_percentage": coverage,
                    "documentation_only": string_count - capped,
                },
            },
        )

    @staticmethod
    def check_performance(
        func: Callable[..., Any],
        max_latency_ms: float,
        component_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[Any, list[Anomaly]]:
        """Invoke a callable and check against a performance contract.

        Times the invocation and compares against max_latency_ms.

        Returns:
            Tuple of (result, anomalies).
        """
        anomalies: list[Anomaly] = []
        start_ns = time.perf_counter_ns()
        result = func(*args, **kwargs)
        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

        if elapsed_ms > max_latency_ms:
            anomalies.append(
                Anomaly(
                    kind=AnomalyKind.INFLAMMATION,
                    severity=AnomalySeverity.WARNING,
                    component_name=component_name,
                    message=(
                        f"Component '{component_name}' exceeded "
                        f"max_latency_ms ({max_latency_ms}ms): "
                        f"actual {elapsed_ms:.1f}ms"
                    ),
                    details={
                        "max_latency_ms": max_latency_ms,
                        "actual_latency_ms": elapsed_ms,
                        "gate_relevant": True,
                        "gate_category": "performance_contract",
                    },
                )
            )
        return result, anomalies

    @staticmethod
    def check_error_rate(
        error_count: int,
        total_count: int,
        threshold: float,
        component_name: str,
    ) -> list[Anomaly]:
        """Check if error rate exceeds the declared threshold.

        Returns:
            List of anomalies (empty if within threshold).
        """
        if total_count == 0:
            return []

        error_rate = error_count / total_count
        if error_rate > threshold:
            return [
                Anomaly(
                    kind=AnomalyKind.INFLAMMATION,
                    severity=AnomalySeverity.WARNING,
                    component_name=component_name,
                    message=(
                        f"Component '{component_name}' error rate "
                        f"({error_rate:.2%}) exceeds threshold "
                        f"({threshold:.2%})"
                    ),
                    details={
                        "error_rate": error_rate,
                        "threshold": threshold,
                        "error_count": error_count,
                        "total_count": total_count,
                        "gate_relevant": True,
                        "gate_category": "error_rate_contract",
                    },
                )
            ]
        return []
