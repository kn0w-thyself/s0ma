"""Core-neutral description of a statically discovered project surface.

The DSL owns discovery.  Core verifiers only receive this small value object;
they never parse ``.s0ma`` files or read project configuration.  A caller may
therefore compare what it discovered with the runtime registry without
reversing the package dependency direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from s0ma.models import Anomaly
from s0ma.types import AnomalyKind, AnomalySeverity

__all__ = [
    "DiscoveredDeclaration",
    "DiscoveredSurface",
    "registered_surface_identifiers",
    "unregistered_surface_anomaly",
]

if TYPE_CHECKING:
    from collections.abc import Collection

    from s0ma.registry import ComponentRegistry

RegistrationStatus = Literal["componentized", "roster_adopted", "unknown"]


@dataclass(frozen=True)
class DiscoveredDeclaration:
    """One declaration or source module found by a caller-owned scanner."""

    identifier: str
    declaration_kind: str
    source_path: str
    registration_status: RegistrationStatus


@dataclass(frozen=True)
class DiscoveredSurface:
    """Deterministic, parser-agnostic input for core verifiers."""

    declarations: tuple[DiscoveredDeclaration, ...] = ()

    @property
    def componentized(self) -> tuple[DiscoveredDeclaration, ...]:
        """Declarations backed by the canonical component model."""
        return tuple(
            item
            for item in self.declarations
            if item.registration_status == "componentized"
        )

    @property
    def unregistered(self) -> tuple[DiscoveredDeclaration, ...]:
        """Discovered entries not backed by the canonical component model."""
        return tuple(
            item
            for item in self.declarations
            if item.registration_status != "componentized"
        )

    def unregistered_against(
        self, registered_identifiers: Collection[str],
    ) -> tuple[DiscoveredDeclaration, ...]:
        """Return the discovered-minus-registry delta.

        Runtime registry keys are historically unqualified component names,
        while DSL discovery uses canonical ``module::component`` identifiers.
        Accepting the unqualified tail preserves that public core registry
        contract without teaching core anything about the DSL parser.
        """
        registered = set(registered_identifiers)
        return tuple(
            item
            for item in self.declarations
            if item.registration_status != "componentized"
            or (
                item.identifier not in registered
                and item.identifier.rsplit("::", 1)[-1] not in registered
            )
        )


def registered_surface_identifiers(
    registry: ComponentRegistry,
) -> frozenset[str]:
    """Return component and module identities represented by *registry*."""
    identifiers = set(registry.get_all())
    identifiers.update(
        f"{module_name}::__module__"
        for module_name in registry.get_all_modules()
    )
    return frozenset(identifiers)


def unregistered_surface_anomaly(
    discovered_surface: DiscoveredSurface | None,
    registered_identifiers: Collection[str],
) -> Anomaly | None:
    """Return one aggregate fault for discovered non-componentized entries."""
    if discovered_surface is None:
        return None
    unregistered = discovered_surface.unregistered_against(
        registered_identifiers,
    )
    if not unregistered:
        return None
    exemplars = [
        {
            "identifier": item.identifier,
            "kind": item.declaration_kind,
            "source_path": item.source_path,
            "registration_status": item.registration_status,
        }
        for item in unregistered[:5]
    ]
    return Anomaly(
        kind=AnomalyKind.IMMUNE_RESPONSE,
        severity=AnomalySeverity.ERROR,
        component_name=None,
        message=(
            f"UNREGISTERED_SURFACE: {len(unregistered)} discovered surface "
            "item(s) are not represented by the canonical component model"
        ),
        details={
            "code": "UNREGISTERED_SURFACE",
            "count": len(unregistered),
            "exemplars": exemplars,
        },
    )
