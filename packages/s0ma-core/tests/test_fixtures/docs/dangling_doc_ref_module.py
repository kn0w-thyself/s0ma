"""Fixture: declares a doc-ref marker but never calls register_doc_ref.

Simulates stale generated output — the DSL source was removed or renamed
but the transpiled ``.py`` file still advertises the registration.
"""

from __future__ import annotations

__s0ma_doc_ref__ = ("fixture_missing_ref",)
