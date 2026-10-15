"""Tests for the additive ``module_scoped`` flag on ``ComponentSpec``.

When ``module_scoped=True``, the registry stores the spec under a qualified
``"<module_path>::<name>"`` key while ``spec.name`` retains the bare name.
This lets two specs with identical bare names — but different
``module_path`` values — coexist without collision.

The default (``module_scoped=False``) preserves bare-name keying — every
existing call site keeps working unchanged. The legacy regressions are
covered by ``tests/test_registry.py``; this file pins the new opt-in
behaviour.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from s0ma.exceptions import RegistrationError
from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from pathlib import Path


def _make_spec(
    name: str = "Foo",
    *,
    module_path: str = "tests.module_scoped_default",
    module_scoped: bool = False,
    intent: str | None = None,
    **overrides: object,
) -> ComponentSpec:
    """Construct a valid ComponentSpec for module-scoped tests."""
    defaults: dict[str, object] = {
        "name": name,
        "kind": ComponentKind.SERVICE,
        "layer": Layer.DOMAIN,
        "intent": intent or f"A test component named {name} for scoped registry tests",
        "module_path": module_path,
        "qualified_name": f"{module_path}.{name}",
        "module_scoped": module_scoped,
    }
    defaults.update(overrides)
    return ComponentSpec(**defaults)  # type: ignore[arg-type]


class TestDefaultKeyingUnchanged:
    """Bare-name keying is the default and continues to work."""

    def test_default_module_scoped_is_false(self) -> None:
        spec = _make_spec("Alpha")
        assert spec.module_scoped is False

    def test_default_keying_uses_bare_name(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Alpha"))
        # The internal store keys under bare name when ``module_scoped`` is False.
        assert "Alpha" in registry.get_all()
        assert registry.get("Alpha") is not None


class TestModuleScopedKeying:
    """``module_scoped=True`` opts into qualified-key storage."""

    def test_qualified_key_used_in_components(self) -> None:
        registry = ComponentRegistry(persist=False)
        spec = _make_spec("Foo", module_path="mod_a", module_scoped=True)
        registry.register(spec)
        all_components = registry.get_all()
        assert "mod_a::Foo" in all_components
        # The ``name`` on the spec stays bare — the spec doesn't lie about itself.
        assert all_components["mod_a::Foo"].name == "Foo"

    def test_two_modules_same_bare_name_coexist(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Foo", module_path="mod_a", module_scoped=True))
        registry.register(_make_spec("Foo", module_path="mod_b", module_scoped=True))
        assert registry.count() == 2
        keys = set(registry.get_all().keys())
        assert keys == {"mod_a::Foo", "mod_b::Foo"}


class TestLookupBehaviour:
    """``get`` / ``contains`` accept either bare or qualified identifiers."""

    def test_get_by_qualified_name_succeeds(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Foo", module_path="mod_a", module_scoped=True))
        spec = registry.get("mod_a::Foo")
        assert spec is not None
        assert spec.name == "Foo"
        assert spec.module_path == "mod_a"

    def test_get_by_bare_name_unique_match_succeeds(self) -> None:
        """When only one scoped spec carries the bare name, bare lookup works."""
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Foo", module_path="mod_a", module_scoped=True))
        spec = registry.get("Foo")
        assert spec is not None
        assert spec.module_path == "mod_a"

    def test_get_by_bare_name_ambiguous_returns_none(self) -> None:
        """Two scoped specs sharing a bare name → bare lookup returns None."""
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Foo", module_path="mod_a", module_scoped=True))
        registry.register(_make_spec("Foo", module_path="mod_b", module_scoped=True))
        assert registry.get("Foo") is None
        # Qualified lookups still work.
        assert registry.get("mod_a::Foo") is not None
        assert registry.get("mod_b::Foo") is not None

    def test_contains_with_qualified_and_bare(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Foo", module_path="mod_a", module_scoped=True))
        assert registry.contains("mod_a::Foo") is True
        assert registry.contains("Foo") is True  # unique bare match
        assert "mod_a::Foo" in registry
        assert "Foo" in registry

    def test_contains_returns_false_for_ambiguous_bare(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Foo", module_path="mod_a", module_scoped=True))
        registry.register(_make_spec("Foo", module_path="mod_b", module_scoped=True))
        assert registry.contains("Foo") is False
        assert "Foo" not in registry

    def test_unscoped_lookup_still_works_alongside_scoped(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Bar"))  # unscoped (legacy)
        registry.register(_make_spec("Foo", module_path="mod_a", module_scoped=True))
        assert registry.get("Bar") is not None
        assert registry.get("mod_a::Foo") is not None

    def test_qualified_direct_key_wins_over_bare_fallback(self) -> None:
        """A stored module-scoped key outranks the qualified-claim fallback
        onto a bare-keyed spec with the same module and name."""
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Foo", module_path="mod_a"))
        registry.register(
            _make_spec(
                "Foo",
                module_path="mod_a",
                module_scoped=True,
                intent="The module-scoped registration stored under mod_a::Foo",
            )
        )
        spec = registry.get("mod_a::Foo")
        assert spec is not None
        assert spec.module_scoped is True

    def test_doubly_qualified_name_stays_a_miss(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Foo", module_path="mod_a"))
        assert registry.get("mod_a::Foo::extra") is None


class TestUnregister:
    """``unregister`` accepts qualified or bare identifiers."""

    def test_unregister_by_qualified_key(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Foo", module_path="mod_a", module_scoped=True))
        spec = registry.unregister("mod_a::Foo")
        assert spec.name == "Foo"
        assert "mod_a::Foo" not in registry
        assert registry.count() == 0

    def test_unregister_by_bare_name_when_unique(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Foo", module_path="mod_a", module_scoped=True))
        spec = registry.unregister("Foo")
        assert spec.name == "Foo"
        assert registry.count() == 0


class TestCollisionDetection:
    """Collision detection still fires within the same module."""

    def test_collision_within_same_module_raises(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Foo", module_path="mod_a", module_scoped=True))
        with pytest.raises(RegistrationError):
            registry.register(
                _make_spec(
                    "Foo",
                    module_path="mod_a",
                    module_scoped=True,
                    intent="An overriding spec that should collide on the same key",
                )
            )


class TestSnapshotRoundTrip:
    """Snapshots preserve module-scoped keying."""

    def test_snapshot_components_keyed_by_qualified_name(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Foo", module_path="mod_a", module_scoped=True))
        registry.register(_make_spec("Foo", module_path="mod_b", module_scoped=True))
        snap = registry.snapshot()
        assert set(snap.components.keys()) == {"mod_a::Foo", "mod_b::Foo"}

    def test_snapshot_to_dict_round_trip(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Foo", module_path="mod_a", module_scoped=True))
        snap = registry.snapshot()
        payload = snap.to_dict()
        assert "mod_a::Foo" in payload["components"]
        # ``module_scoped`` is omitted from to_dict for legacy specs (default False)
        # but emitted when True so consumers can faithfully reconstruct.
        assert payload["components"]["mod_a::Foo"].get("module_scoped") is True

    def test_to_dict_omits_module_scoped_when_false(self) -> None:
        """Legacy specs serialise byte-identically — no spurious ``module_scoped`` key."""
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("Foo"))
        snap = registry.snapshot()
        payload = snap.to_dict()
        assert "module_scoped" not in payload["components"]["Foo"]

    def test_from_dict_round_trip_preserves_flag(self) -> None:
        spec = _make_spec("Foo", module_path="mod_a", module_scoped=True)
        round_tripped = ComponentSpec.from_dict(spec.to_dict())
        assert round_tripped.module_scoped is True
        assert round_tripped.module_path == "mod_a"
        assert round_tripped.name == "Foo"

    def test_from_dict_legacy_payload_defaults_to_false(self) -> None:
        """Legacy serialised specs (no ``module_scoped`` key) load unchanged."""
        legacy_payload = {
            "name": "LegacyComponent",
            "kind": "SERVICE",
            "layer": "DOMAIN",
            "intent": "A legacy component without module_scoped serialisation",
            "contracts": {"preconditions": [], "postconditions": [], "invariants": []},
            "dependencies": [],
            "metadata": {},
            "module_path": "legacy.module",
            "qualified_name": "",
            "source_file": None,
            "registered_at": "2024-01-01T00:00:00",
            "is_framework": False,
        }
        spec = ComponentSpec.from_dict(legacy_payload)
        assert spec.module_scoped is False


class TestSqlitePersistence:
    """Module-scoped specs survive a SQLite write/reopen round-trip."""

    def test_persisted_spec_round_trip(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry_module_scoped.db"

        # First registry: write
        reg1 = ComponentRegistry(persist=True, db_path=db_path)
        reg1.register(_make_spec("Foo", module_path="mod_a", module_scoped=True))
        reg1.register(_make_spec("Foo", module_path="mod_b", module_scoped=True))
        reg1.register(_make_spec("LegacyBar"))
        reg1.close()

        # Second registry: load from disk
        reg2 = ComponentRegistry(persist=True, db_path=db_path)
        try:
            assert reg2.count() == 3
            keys = set(reg2.get_all().keys())
            assert keys == {"mod_a::Foo", "mod_b::Foo", "LegacyBar"}

            mod_a_foo = reg2.get("mod_a::Foo")
            assert mod_a_foo is not None
            assert mod_a_foo.name == "Foo"
            assert mod_a_foo.module_scoped is True
            assert mod_a_foo.module_path == "mod_a"

            legacy = reg2.get("LegacyBar")
            assert legacy is not None
            assert legacy.module_scoped is False
        finally:
            reg2.close()
