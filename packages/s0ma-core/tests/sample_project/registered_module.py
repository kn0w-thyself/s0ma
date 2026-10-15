"""Sample module where all public entities are registered with @component."""

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer


@component(
    name="SampleService",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="A sample service for testing import hook enforcement",
)
class SampleService:
    """A fully registered service component."""

    def process(self) -> str:
        return "processed"


@component(
    name="sample_helper",
    kind=ComponentKind.FUNCTION,
    layer=Layer.DOMAIN,
    intent="A sample function for testing import hook enforcement",
)
def sample_helper() -> str:
    """A fully registered function component."""
    return "helped"
