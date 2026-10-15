"""Sample module with both registered and unregistered entities.

This module should fail import hook enforcement because it contains
at least one unregistered public entity.
"""

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer


@component(
    name="MixedRegisteredClass",
    kind=ComponentKind.MODEL,
    layer=Layer.DOMAIN,
    intent="A registered model in a mixed module for testing enforcement",
)
class MixedRegisteredClass:
    """This class is properly registered."""

    pass


class MixedUnregisteredClass:
    """This class is NOT registered — should trigger enforcement."""

    pass
