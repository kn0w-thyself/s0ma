"""Fixture: module with a doc-ref marker and a matching registration."""

from __future__ import annotations

from s0ma import register_doc_ref

__s0ma_doc_ref__ = ("fixture_api_ref",)

register_doc_ref(
    name="fixture_api_ref",
    module="tests.test_fixtures.docs.registered_doc_ref_module",
    intent="Fixture doc-ref used by import-hook tests",
    format="markdown",
    output="docs/fixture_api.md",
    idempotent=True,
)
