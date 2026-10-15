"""Fixture: module with an example marker and a matching registration."""

from __future__ import annotations

from s0ma import register_example
from s0ma.models import EntityRef

__s0ma_example__ = ("fixture_example",)

register_example(
    name="fixture_example",
    module="tests.test_fixtures.docs.registered_example_module",
    intent="Fixture example used by import-hook tests",
    demonstrates=[EntityRef(kind="nerve", name="initialize", module="s0ma")],
    runs_in="standalone",
    body="",
    idempotent=True,
)
