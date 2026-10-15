"""Sample module with unregistered public code — should be caught by the import hook."""


class UnregisteredService:
    """A public class with no @component or @internal decorator."""

    def run(self) -> str:
        return "running"


def unregistered_function() -> str:
    """A public function with no decorator."""
    return "no registration"
