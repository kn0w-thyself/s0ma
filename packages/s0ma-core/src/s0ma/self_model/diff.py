"""Structured registry diffing.

Given two :class:`~s0ma.models.RegistrySnapshot` instances, produce a
:class:`StructuredDiff` enumerating the components that were added,
removed, or modified. Field-level changes are recorded as
``(before, after)`` pairs keyed by field name on the surviving spec.

The comparator delegates to
:func:`s0ma.hashing.canonical.canonicalize` so dict and set ordering
do not produce false positives, and so the answer matches whatever the
content-hash subsystem says about deeper equality.

Output is deterministic: the ``added``, ``removed``, and ``modified``
lists are all sorted by component name, and the ``field_changes`` dict
on each ``ComponentChange`` is built in declaration order.

The ``registered_at`` timestamp on :class:`~s0ma.models.ComponentSpec`
is excluded from comparison — it shifts on every fresh registration
and is not load-bearing for the diff's intent (detecting structural
change between two snapshots).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from s0ma.hashing.canonical import canonicalize

if TYPE_CHECKING:
    from s0ma.models import ComponentSpec, RegistrySnapshot

__all__ = [
    "ComponentChange",
    "StructuredDiff",
    "compute_registry_diff",
]

# Fields on ``ComponentSpec`` excluded from the field-by-field comparison.
# ``registered_at`` is the only one — the rest of the spec is the structural
# surface we want to diff.
_IGNORED_FIELDS: frozenset[str] = frozenset({"registered_at"})


@dataclass(frozen=True)
class ComponentChange:
    """A single change to a component between two snapshots.

    For an *added* component, ``before`` is ``None`` and ``after`` carries the
    new spec. For a *removed* component, ``after`` is ``None`` and ``before``
    carries the prior spec. For a *modified* component, both are populated and
    ``field_changes`` enumerates the fields that differ as
    ``(before_value, after_value)`` pairs.
    """

    name: str
    before: ComponentSpec | None
    after: ComponentSpec | None
    field_changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary.

        Spec values inside ``field_changes`` are passed through as-is — the
        consumer is expected to handle further serialisation.
        """
        return {
            "name": self.name,
            "before": self.before.to_dict() if self.before is not None else None,
            "after": self.after.to_dict() if self.after is not None else None,
            "field_changes": {
                fname: list(pair) for fname, pair in self.field_changes.items()
            },
        }


@dataclass(frozen=True)
class StructuredDiff:
    """The result of comparing two registry snapshots.

    The three lists are sorted by ``name`` for deterministic output.
    """

    added: list[ComponentChange] = field(default_factory=list)
    removed: list[ComponentChange] = field(default_factory=list)
    modified: list[ComponentChange] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Return True iff no component was added, removed, or modified."""
        return not (self.added or self.removed or self.modified)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "added": [c.to_dict() for c in self.added],
            "removed": [c.to_dict() for c in self.removed],
            "modified": [c.to_dict() for c in self.modified],
        }


def compute_registry_diff(
    *,
    prior: RegistrySnapshot,
    current: RegistrySnapshot,
) -> StructuredDiff:
    """Compare two registry snapshots and return the structured difference.

    Components are matched by their key in :attr:`RegistrySnapshot.components`
    (typically the bare component name; module-scoped components use a
    qualified ``"<module_path>::<name>"`` key — both forms compare cleanly).

    Field comparison uses :func:`canonicalize` so dict / set ordering and
    nested dataclass identity do not produce spurious diffs. The
    ``registered_at`` timestamp is excluded.
    """
    prior_keys = set(prior.components)
    current_keys = set(current.components)

    added: list[ComponentChange] = [
        ComponentChange(
            name=key,
            before=None,
            after=current.components[key],
        )
        for key in sorted(current_keys - prior_keys)
    ]

    removed: list[ComponentChange] = [
        ComponentChange(
            name=key,
            before=prior.components[key],
            after=None,
        )
        for key in sorted(prior_keys - current_keys)
    ]

    modified: list[ComponentChange] = []
    for key in sorted(prior_keys & current_keys):
        before_spec = prior.components[key]
        after_spec = current.components[key]
        field_changes = _compare_specs(before_spec, after_spec)
        if field_changes:
            modified.append(
                ComponentChange(
                    name=key,
                    before=before_spec,
                    after=after_spec,
                    field_changes=field_changes,
                )
            )

    return StructuredDiff(added=added, removed=removed, modified=modified)


def _compare_specs(
    before: ComponentSpec,
    after: ComponentSpec,
) -> dict[str, tuple[Any, Any]]:
    """Return field-by-field differences between two specs.

    Iterates ``ComponentSpec`` fields in declaration order. For each field
    not in ``_IGNORED_FIELDS``, compares values via canonical bytes.
    """
    changes: dict[str, tuple[Any, Any]] = {}
    for f in dataclasses.fields(before):
        if f.name in _IGNORED_FIELDS:
            continue
        before_val = getattr(before, f.name)
        after_val = getattr(after, f.name)
        if canonicalize(before_val) != canonicalize(after_val):
            changes[f.name] = (before_val, after_val)
    return changes
