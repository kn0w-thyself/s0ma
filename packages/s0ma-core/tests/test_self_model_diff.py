"""Tests for ``s0ma.self_model.diff.compute_registry_diff``.

Covers the StructuredDiff invariants:
- empty diff for identical snapshots,
- detection of added / removed / modified components,
- field-level change attribution via canonical comparison,
- ``registered_at`` is excluded from diffs,
- output is deterministically sorted by name,
- ``to_dict`` round-trips for downstream serialisation.
"""

from __future__ import annotations

from s0ma.models import ComponentSpec, Contract
from s0ma.registry import ComponentRegistry
from s0ma.self_model.diff import (
    ComponentChange,
    StructuredDiff,
    compute_registry_diff,
)
from s0ma.types import ComponentKind, Layer


def _make_spec(name: str = "ExampleComponent", **overrides: object) -> ComponentSpec:
    """Construct a valid ComponentSpec with sensible defaults."""
    defaults: dict[str, object] = {
        "name": name,
        "kind": ComponentKind.SERVICE,
        "layer": Layer.DOMAIN,
        "intent": "An example component used in diff tests for validation",
        "module_path": f"tests.{name.lower()}",
        "qualified_name": f"tests.{name.lower()}.{name}",
    }
    defaults.update(overrides)
    return ComponentSpec(**defaults)  # type: ignore[arg-type]


def _registry_with(*specs: ComponentSpec) -> ComponentRegistry:
    reg = ComponentRegistry(persist=False)
    for spec in specs:
        reg.register(spec)
    return reg


class TestEmptyDiff:
    """A snapshot compared against itself produces an empty diff."""

    def test_diff_self_is_empty(self) -> None:
        reg = _registry_with(_make_spec("Alpha"), _make_spec("Beta"))
        snap = reg.snapshot()
        diff = compute_registry_diff(prior=snap, current=snap)
        assert diff.is_empty() is True
        assert diff.added == []
        assert diff.removed == []
        assert diff.modified == []

    def test_diff_two_empty_snapshots_is_empty(self) -> None:
        snap_a = ComponentRegistry(persist=False).snapshot()
        snap_b = ComponentRegistry(persist=False).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        assert diff.is_empty() is True


class TestAddedRemoved:
    """Component-level add / remove detection."""

    def test_added_component_listed(self) -> None:
        snap_a = _registry_with(_make_spec("Alpha")).snapshot()
        snap_b = _registry_with(
            _make_spec("Alpha"),
            _make_spec("Beta"),
        ).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        assert len(diff.added) == 1
        change = diff.added[0]
        assert change.name == "Beta"
        assert change.before is None
        assert change.after is not None
        assert change.after.name == "Beta"
        assert change.field_changes == {}
        assert diff.removed == []
        assert diff.modified == []

    def test_removed_component_listed(self) -> None:
        snap_a = _registry_with(
            _make_spec("Alpha"),
            _make_spec("Beta"),
        ).snapshot()
        snap_b = _registry_with(_make_spec("Alpha")).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        assert len(diff.removed) == 1
        change = diff.removed[0]
        assert change.name == "Beta"
        assert change.before is not None
        assert change.before.name == "Beta"
        assert change.after is None
        assert diff.added == []
        assert diff.modified == []

    def test_added_and_removed_in_same_diff(self) -> None:
        snap_a = _registry_with(_make_spec("Alpha")).snapshot()
        snap_b = _registry_with(_make_spec("Beta")).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        assert [c.name for c in diff.added] == ["Beta"]
        assert [c.name for c in diff.removed] == ["Alpha"]
        assert diff.modified == []


class TestModifiedFieldChanges:
    """Field-level attribution on modified components."""

    def test_intent_change_recorded(self) -> None:
        snap_a = _registry_with(
            _make_spec("Alpha", intent="Original intent string for diffing"),
        ).snapshot()
        snap_b = _registry_with(
            _make_spec("Alpha", intent="Modified intent string for diffing"),
        ).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        assert len(diff.modified) == 1
        change = diff.modified[0]
        assert change.name == "Alpha"
        assert "intent" in change.field_changes
        before_val, after_val = change.field_changes["intent"]
        assert before_val == "Original intent string for diffing"
        assert after_val == "Modified intent string for diffing"

    def test_dependency_change_recorded(self) -> None:
        snap_a = _registry_with(
            _make_spec("Beta"),
            _make_spec("Alpha", dependencies=["Beta"]),
        ).snapshot()
        snap_b = _registry_with(
            _make_spec("Beta"),
            _make_spec("Gamma"),
            _make_spec("Alpha", dependencies=["Beta", "Gamma"]),
        ).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        modified_names = [c.name for c in diff.modified]
        assert "Alpha" in modified_names
        alpha_change = next(c for c in diff.modified if c.name == "Alpha")
        assert "dependencies" in alpha_change.field_changes
        before_val, after_val = alpha_change.field_changes["dependencies"]
        assert before_val == ["Beta"]
        assert after_val == ["Beta", "Gamma"]

    def test_metadata_dict_reorder_is_not_a_change(self) -> None:
        """Re-ordering keys inside ``metadata`` must not produce a false positive.

        ``canonicalize`` sorts dict keys, so two metadata dicts with the same
        contents in different insertion orders compare equal.
        """
        snap_a = _registry_with(
            _make_spec("Alpha", metadata={"a": 1, "b": 2, "c": 3}),
        ).snapshot()
        snap_b = _registry_with(
            _make_spec("Alpha", metadata={"c": 3, "a": 1, "b": 2}),
        ).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        assert diff.is_empty() is True

    def test_contract_nested_change_recorded(self) -> None:
        snap_a = _registry_with(
            _make_spec(
                "Alpha",
                contracts=Contract(preconditions=["x is non-null"]),
            ),
        ).snapshot()
        snap_b = _registry_with(
            _make_spec(
                "Alpha",
                contracts=Contract(preconditions=["x is non-null", "x is non-empty"]),
            ),
        ).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        assert len(diff.modified) == 1
        change = diff.modified[0]
        assert "contracts" in change.field_changes

    def test_unchanged_field_not_listed(self) -> None:
        """Only differing fields appear in ``field_changes``."""
        snap_a = _registry_with(
            _make_spec("Alpha", intent="Same intent value, different version"),
        ).snapshot()
        snap_b = _registry_with(
            _make_spec(
                "Alpha",
                intent="Same intent value, different version",
                version="0.2.0",
            ),
        ).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        assert len(diff.modified) == 1
        change = diff.modified[0]
        # ``intent`` did not change, so it must be absent from field_changes.
        assert "intent" not in change.field_changes
        assert "version" in change.field_changes

    def test_no_change_components_excluded_from_modified(self) -> None:
        """Identical specs in both snapshots produce no ``ComponentChange``."""
        spec = _make_spec("Alpha")
        snap_a = _registry_with(spec).snapshot()
        snap_b = _registry_with(_make_spec("Alpha")).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        # Two distinct registrations with identical fields except registered_at —
        # the diff must be empty.
        assert diff.is_empty() is True


class TestRegisteredAtIgnored:
    """``registered_at`` shifts on every fresh registration; never a diff."""

    def test_registered_at_difference_does_not_appear_in_diff(self) -> None:
        snap_a = _registry_with(_make_spec("Alpha")).snapshot()
        snap_b = _registry_with(_make_spec("Alpha")).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        # Same shape, only ``registered_at`` differs across the two snapshots.
        assert diff.is_empty() is True


class TestDeterministicOrdering:
    """Output is sorted by name throughout."""

    def test_added_sorted_by_name(self) -> None:
        snap_a = ComponentRegistry(persist=False).snapshot()
        snap_b = _registry_with(
            _make_spec("Charlie"),
            _make_spec("Alpha"),
            _make_spec("Bravo"),
        ).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        assert [c.name for c in diff.added] == ["Alpha", "Bravo", "Charlie"]

    def test_removed_sorted_by_name(self) -> None:
        snap_a = _registry_with(
            _make_spec("Charlie"),
            _make_spec("Alpha"),
            _make_spec("Bravo"),
        ).snapshot()
        snap_b = ComponentRegistry(persist=False).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        assert [c.name for c in diff.removed] == ["Alpha", "Bravo", "Charlie"]

    def test_modified_sorted_by_name(self) -> None:
        snap_a = _registry_with(
            _make_spec("Charlie", intent="Charlie original intent string"),
            _make_spec("Alpha", intent="Alpha original intent string"),
            _make_spec("Bravo", intent="Bravo original intent string"),
        ).snapshot()
        snap_b = _registry_with(
            _make_spec("Charlie", intent="Charlie modified intent string"),
            _make_spec("Alpha", intent="Alpha modified intent string"),
            _make_spec("Bravo", intent="Bravo modified intent string"),
        ).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        assert [c.name for c in diff.modified] == ["Alpha", "Bravo", "Charlie"]


class TestSerialization:
    """``StructuredDiff.to_dict`` produces JSON-serialisable output."""

    def test_to_dict_round_trip_keys(self) -> None:
        snap_a = _registry_with(_make_spec("Alpha")).snapshot()
        snap_b = _registry_with(
            _make_spec("Alpha", intent="Alpha modified intent string"),
            _make_spec("Beta"),
        ).snapshot()
        diff = compute_registry_diff(prior=snap_a, current=snap_b)
        payload = diff.to_dict()
        assert set(payload.keys()) == {"added", "removed", "modified"}
        assert len(payload["added"]) == 1
        assert payload["added"][0]["name"] == "Beta"
        assert payload["added"][0]["before"] is None
        assert payload["added"][0]["after"]["name"] == "Beta"
        assert len(payload["modified"]) == 1
        assert payload["modified"][0]["name"] == "Alpha"
        assert "intent" in payload["modified"][0]["field_changes"]

    def test_component_change_to_dict_handles_none_sides(self) -> None:
        change = ComponentChange(name="X", before=None, after=None)
        payload = change.to_dict()
        assert payload["before"] is None
        assert payload["after"] is None
        assert payload["field_changes"] == {}


class TestEmptyDiffConstruction:
    """``StructuredDiff()`` with default factories is empty."""

    def test_default_constructed_diff_is_empty(self) -> None:
        diff = StructuredDiff()
        assert diff.is_empty() is True
        assert diff.added == []
        assert diff.removed == []
        assert diff.modified == []
