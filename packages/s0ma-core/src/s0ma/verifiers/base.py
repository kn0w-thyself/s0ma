"""Base verifier protocol and shared utilities.

Defines the Verifier protocol that all s0ma verifiers implement.
Each verifier checks one aspect of model-reality correspondence and
returns a VerificationResult containing any anomalies found.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from s0ma.models import VerificationResult
    from s0ma.registry import ComponentRegistry
    from s0ma.types import VerificationScope

__all__ = ["Verifier"]


@runtime_checkable
class Verifier(Protocol):
    """Protocol for all s0ma verifiers.

    Each verifier checks one aspect of model-reality correspondence
    and returns a VerificationResult containing any anomalies found.
    """

    @property
    def name(self) -> str:
        """Human-readable name for this verifier (e.g., 'Structural Verifier')."""
        ...

    @property
    def scope(self) -> VerificationScope:
        """What category of verification this performs."""
        ...

    def verify(self, registry: ComponentRegistry) -> VerificationResult:
        """Run verification and return results.

        Args:
            registry: The ComponentRegistry to verify against.

        Returns:
            VerificationResult with anomalies, stats, and timing.
        """
        ...

    def verify_incremental(
        self, registry: ComponentRegistry, component_name: str
    ) -> VerificationResult:
        """Verify only the named component and its direct dependencies.

        This enables per-component verification after individual changes,
        avoiding full-registry scans in tight iteration loops (e.g.,
        runtime component creation by downstream consumers like STEMCELL).

        Args:
            registry: The ComponentRegistry to verify against.
            component_name: Name of the component to verify.

        Returns:
            VerificationResult scoped to the named component and its deps.
        """
        ...
