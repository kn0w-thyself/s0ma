"""s0ma exception hierarchy.

All exceptions raised by the s0ma framework inherit from S0maError,
enabling callers to catch framework errors with a single except clause.
"""

__all__ = [
    "S0maError",
    "RegistrationError",
    "UnregisteredComponentError",
    "ContractViolationError",
    "RegistryIntegrityError",
    "BootstrapError",
    "LifecycleError",
    "TransactionError",
    "ExampleTimeoutError",
]


class S0maError(Exception):
    """Base exception for all s0ma errors."""


class RegistrationError(S0maError):
    """Raised when component registration fails.

    Common causes: missing required fields, duplicate component name,
    invalid metadata, or self-dependency in the dependency list.
    """


class UnregisteredComponentError(S0maError):
    """Raised by the import hook when unregistered public code is detected.

    This exception is the enforcement mechanism that makes the self-model
    load-bearing. In strict mode, importing a module with unregistered
    public classes or functions will raise this error.
    """


class ContractViolationError(S0maError):
    """Raised when a component's runtime behavior violates its declared contracts.

    Used by the verification engine (Phase 2) to report precondition,
    postcondition, or invariant failures.
    """


class RegistryIntegrityError(S0maError):
    """Raised when the registry's internal state is inconsistent.

    Examples: orphaned dependencies, phantom limbs (registry entries
    without corresponding code), or corruption in SQLite persistence.
    """


class BootstrapError(S0maError):
    """Raised when the framework's self-registration fails the bootstrap test.

    If this error occurs, s0ma cannot accurately describe itself,
    which means the core invariant of the framework is broken.
    """


class LifecycleError(S0maError):
    """Raised when a lifecycle operation fails.

    Lifecycle operations include unregister, update, and runtime creation.
    This error indicates the operation was rejected or rolled back, and
    the registry remains in its pre-operation state.
    """


class TransactionError(S0maError):
    """Raised when a transaction fails to commit or rollback.

    This indicates a serious error — the transaction context could not
    cleanly restore the registry to a consistent state.
    """


class ExampleTimeoutError(S0maError):
    """Raised when a registered example exceeds its configured timeout budget.

    The example runner surfaces this error on the ``ExampleResult`` rather
    than propagating it to the caller of ``run_all()``; a direct invocation
    of ``ExampleRunner.run()`` that hits the timeout receives the error on
    the returned result, not raised. The exception exists as a structured
    marker for consumers that inspect execution failures by type.
    """

    def __init__(self, example_name: str, timeout_seconds: float) -> None:
        super().__init__(
            f"Example '{example_name}' exceeded {timeout_seconds}s timeout"
        )
        self.example_name = example_name
        self.timeout_seconds = timeout_seconds
