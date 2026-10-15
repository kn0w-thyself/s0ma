"""Test fixture: dead/unreachable code for coverage auditor testing.

This module contains code that can be registered in the component
registry but is deliberately never imported or called by other
components. The coverage auditor should flag these as VESTIGIAL_ORGAN.
"""

from __future__ import annotations


class UnusedService:
    """A service that nothing depends on or imports.

    When registered as a component but not declared as a dependency
    by any other component, the coverage auditor should flag this
    as a potential vestigial organ.
    """

    def process(self) -> str:
        return "never called"


class DeprecatedHandler:
    """A handler marked as deprecated in component metadata.

    When registered with metadata={"deprecated": True} and still
    receiving calls in the metrics collector, the coverage auditor
    should flag this as ATROPHIED_MUSCLE.
    """

    def handle(self) -> str:
        return "deprecated but still running"


def orphaned_function() -> str:
    """A standalone function that nothing calls.

    When registered but never appears in any dependency list,
    the coverage auditor should flag this as potentially vestigial.
    """
    return "orphaned"
