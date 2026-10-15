"""Fixture: module with a doc-guide marker and a matching registration."""

from __future__ import annotations

from s0ma import register_doc_guide

__s0ma_doc_guide__ = ("fixture_guide",)

register_doc_guide(
    name="fixture_guide",
    module="tests.test_fixtures.docs.registered_doc_guide_module",
    intent="Fixture doc-guide used by import-hook tests",
    format="markdown",
    output="docs/fixture_guide.md",
    idempotent=True,
)
