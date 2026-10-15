"""Core types, enums, and type aliases for the s0ma framework.

This module defines the vocabulary of component classification:
- ComponentKind: what archetype a component follows (service, function, model, etc.)
- Layer: which architectural layer a component belongs to
- AnomalySeverity: how serious a code-model discrepancy is
- AnomalyKind: biological pathology taxonomy for discrepancies
"""

from enum import Enum, auto

__all__ = [
    "ComponentKind",
    "Layer",
    "AnomalySeverity",
    "AnomalyKind",
    "VerificationScope",
    "LifecycleAction",
    "ComponentName",
    "DependencyList",
    "KNOWN_RELATION_TYPES",
]


class ComponentKind(Enum):
    """Taxonomy of component archetypes."""

    SERVICE = auto()       # Long-running, stateful (e.g., database connection pool)
    FUNCTION = auto()      # Stateless transformation (e.g., tax calculator)
    MODEL = auto()         # Data structure with invariants (e.g., User, Order)
    ADAPTER = auto()       # Interface to external system (e.g., payment gateway client)
    ORCHESTRATOR = auto()  # Coordinates other components (e.g., request handler)
    FRAMEWORK = auto()     # s0ma's own infrastructure (e.g., registry, decorator)


class Layer(Enum):
    """Architectural layers for component classification."""

    DOMAIN = auto()         # Core business logic
    APPLICATION = auto()    # Use cases and orchestration
    INFRASTRUCTURE = auto()  # External system adapters
    PRESENTATION = auto()   # UI and API surface
    FRAMEWORK = auto()      # s0ma internals


class AnomalySeverity(Enum):
    """Severity levels for verification anomalies."""

    ERROR = auto()    # Must fix — system integrity compromised
    WARNING = auto()  # Should investigate — potential drift
    INFO = auto()     # Cosmetic — no functional impact


class AnomalyKind(Enum):
    """Biological pathology taxonomy for code-model discrepancies.

    Each kind maps to a specific detection algorithm and remediation strategy.
    These are not metaphors — they are concrete algorithmic patterns.
    """

    PHANTOM_LIMB = auto()      # Registry entry with no corresponding code
    VESTIGIAL_ORGAN = auto()   # Code that exists but is never used
    IMMUNE_RESPONSE = auto()   # Unregistered code detected (foreign body)
    ATROPHIED_MUSCLE = auto()  # Deprecated API still receiving traffic
    INFLAMMATION = auto()      # Component exceeding resource profile
    NOCICEPTION = auto()       # Live call violating an executable contract


class VerificationScope(Enum):
    """Categories of verification performed by the verification engine.

    Each verifier operates in one scope. The verify_all() orchestrator
    runs all scopes and aggregates results into a VerificationReport.
    """

    STRUCTURAL = auto()     # Code structure matches registry declarations
    CONTRACT = auto()       # Runtime behavior matches declared contracts
    INTEROCEPTION = auto()  # Resource usage matches declared profiles
    COVERAGE = auto()       # Code reachability and usage analysis
    SELF_MODEL = auto()     # Full bootstrap self-description accuracy


class LifecycleAction(Enum):
    """Types of component lifecycle operations."""

    REGISTER = auto()        # Initial registration (@component or bootstrap)
    UNREGISTER = auto()      # Single component removal
    UPDATE = auto()          # Spec replacement (unregister + register)
    CREATE_RUNTIME = auto()  # Dynamic creation from source code


# Known relation types for RelationshipEdge.relation.
# This is a frozenset (not an enum) because the relation field is a flexible
# string — unknown values are accepted, but these are the recognized types.
KNOWN_RELATION_TYPES: frozenset[str] = frozenset({
    "CALLS",
    "READS",
    "CONSTRUCTS",
    "CONFIGURES",
    "RAISES",
    "TYPE_USES",
    "OBSERVES",
    "PRODUCES",
    "CONSUMES",
})

# Type aliases
ComponentName = str
DependencyList = list[ComponentName]
