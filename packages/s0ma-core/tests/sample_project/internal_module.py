"""Sample module using @internal for intentionally unregistered helpers."""

from s0ma.decorators import component, internal
from s0ma.types import ComponentKind, Layer


@component(
    name="InternalModuleService",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="A registered service that coexists with internal helpers",
)
class InternalModuleService:
    """A registered component."""

    def work(self) -> str:
        return format_output("work")


@internal
def format_output(text: str) -> str:
    """An intentionally unregistered internal helper."""
    return f"[{text}]"


@internal(reason="Legacy helper kept for backward compatibility")
def legacy_helper() -> str:
    """Another internal helper with an explicit reason."""
    return "legacy"
