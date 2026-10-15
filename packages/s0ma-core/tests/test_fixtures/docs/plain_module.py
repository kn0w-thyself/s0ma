"""Fixture: a non-doc module that should import cleanly under the hook.

Regression guard — proves that extending the import hook with
documentation-subsystem checks did not affect plain registered modules.
"""

from __future__ import annotations

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer


@component(
    name="FixtureDocsPlainService",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="Plain registered component used as regression fixture",
    idempotent=True,
)
class FixtureDocsPlainService:
    """Ordinary registered component — no documentation markers."""

    def ping(self) -> str:
        return "pong"
