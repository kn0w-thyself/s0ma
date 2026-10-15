"""The generated inventories: what this build knows, listed once, rendered.

Milestone D6 of the docs-function plan (internal) §9. Everything before this
module composes and gates a snapshot nobody but a program can read. This is
where the composed snapshot becomes something a person opens — two reader
indexes — and something another document may cite instead of counting by
hand — three machine-readable inventories.

**Why the component facts are here and not in the bundle.** Milestone C3
left one question open and named this milestone as the place to answer it:
the model addresses a registered component as an external id and gives it no
record type, so the facts about a component — what it is for, what kind of
thing it is, which layer it sits in, whether it is public — have nowhere to
live. The two candidate answers were a seventh bundle group and a
renderer-side artifact. D6 rules for the artifact, for four reasons:

1. **The architecture's first risk.** Arch Risk 1 is that the documentation
   graph quietly becomes a second self-model. A ``ComponentRecord`` group
   would put the framework's own inventory inside the bundle, where it would
   be composed, merged, hashed and gated as documentation — a second account
   of the registry, with its own drift surface, maintained by this build.
   The artifact renders the inventory instead of holding it.
2. **``@1`` has a strict reader.** ``serialize.record_from_plain`` refuses an
   unknown key by design, so a seventh group is not an additive field: it is a
   schema revision, which re-stamps every committed snapshot and every mirror
   for facts nothing in the model resolves *against*. Component references
   already resolve through :class:`~s0ma_dsl.docs_model.validate.ReferenceIndex`'s
   external-id seam and would resolve no better.
3. **Cost.** A group touches ``DocsBundle``, ``RECORD_TYPES``,
   ``FIELD_CLASS``, ``serialize._GROUPS``, ``compose``, ``validate`` — and
   ``resolve``, where every record type in the bundle acquires a coverage
   obligation on both reader channels. Every registered component in the
   workspace would have to be renderable as a topic on the human page and
   the agent channel, which nobody asked for.
4. **The pin stays true.** C3's ``TestComponentsAreNotRecords`` says a
   component is an external id, not a record. It still is. What changes is
   that the facts about those ids are now written down, with provenance, in
   a byte-gated file — which is what the milestone needed and all it needed.

**Where the facts come from.** Three readings, one per family, each the one
the corresponding provider already trusts, and each fixed by the *id* rather
than by what happens to be importable — a reading that varied with the
environment would move the artifact's bytes between machines and the drift
gate would report it:

* ``s0ma.*`` — core's own bootstrap, booted fresh for this build the way
  ADR-012 §3 requires: the same registrations ``CoreProvider`` holds to
  core's own ``EXPECTED_FRAMEWORK_COMPONENT_COUNT``.
* ``s0ma_mcp.*`` and ``s0ma_studi0.*`` — the committed canonical IR beside
  each package's build (``_built/*.s0ma.json``), which carries every
  declared component's kind, visibility and intent, and its module's layer.
  Read as files, never imported, which is the stance those two providers
  already take.
* anything else — the ``@component`` registration attached to the object
  itself, read the way
  :func:`~s0ma_dsl.docs_model.providers_cli._registration` reads a
  handler's: off the object's own ``__dict__``, so a subclass cannot
  inherit its parent's registration and claim to be it.

A component id no reading can answer is refused, never rendered with an
absent fact. An inventory with a hole in it is worse than no inventory,
because every count taken from it is wrong by an amount nobody knows.

**Determinism.** No clock, no network, no machine path. Every collection is
sorted before it reaches a rendering, counts are computed from the records
rather than written down, and the JSON is
:func:`~s0ma_dsl.docs_model.serialize.canonical_json`.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from s0ma_dsl.docs_model.records import DocsModelError
from s0ma_dsl.docs_model.serialize import canonical_json

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from s0ma_dsl.docs_model.records import ConceptRecord, DocsBundle, SurfaceRecord

__all__ = [
    "BUILT_IR_DIRS",
    "CHANNEL_TITLES",
    "COMPONENT_PREFIX",
    "DISTRIBUTION_BY_MODULE",
    "GENERATED_NOTE",
    "INVENTORY_SCHEMA",
    "REGISTRATION_SOURCE",
    "ComponentFact",
    "DocsInventoryError",
    "Reading",
    "cell",
    "component_facts",
    "components_inventory",
    "concepts_index",
    "concepts_inventory",
    "list_cell",
    "surfaces_index",
    "surfaces_inventory",
]

#: The inventory artifacts' own format version. Emphatically not the
#: model's ``s0ma-docs-model@1``: an inventory is a *rendering* of a
#: snapshot, and the two version independently. Each artifact names the
#: snapshot it was rendered from under ``source``, so a reader can always
#: get back to the build.
INVENTORY_SCHEMA = "s0ma-docs-inventory@1"

#: The id prefix a registered component is addressed by (plan §5).
COMPONENT_PREFIX = "component:"

#: Top-level module name to the distribution that ships it. The four
#: distributions of INV-6, and the mapping is declared rather than derived
#: because ``s0ma`` and ``s0ma-core`` differ and no rule turns one into the
#: other.
DISTRIBUTION_BY_MODULE: Mapping[str, str] = {
    "s0ma": "s0ma-core",
    "s0ma_dsl": "s0ma-dsl",
    "s0ma_mcp": "s0ma-mcp",
    "s0ma_studi0": "s0ma-studi0",
}

#: How the ``@component`` reading names itself. One string for the whole
#: reading rather than one per object: the object it read is the one the
#: component's own id names, so a per-object source would be a second copy
#: of the id and the roll-up of readings would have a row per component
#: instead of a row per source.
REGISTRATION_SOURCE = "python:<component>.__component__"

#: The two packages whose components are read from their committed build
#: rather than by importing them, and where that build lives. Both are
#: transpiled packages: the canonical IR beside the emitted modules is the
#: package's own declaration of what it contains, written at build time and
#: byte-gated against its sources.
BUILT_IR_DIRS: Mapping[str, str] = {
    "s0ma_mcp": "packages/s0ma-mcp/src/s0ma_mcp/_built",
    "s0ma_studi0": "packages/s0ma-studi0/src/s0ma_studi0/_built",
}

#: What each channel is called on a page a person reads. The order is the
#: order the sections appear in, chosen so the surfaces somebody meets
#: first come first. A channel absent from this mapping is **not** dropped:
#: it renders under its own name, after these, which is what keeps the
#: index complete when a new channel arrives before this table hears of it.
CHANNEL_TITLES: Mapping[str, str] = {
    "cli": "Command line",
    "mcp_tool": "Tools an agent can call",
    "mcp_resource": "Resources an agent can read",
    "mcp_prompt": "Prompts an agent can start from",
    "studi0": "The studi0 viewer",
    "rest": "The self-description interface",
    "config": "Project settings",
    "diagnostic": "Reports s0ma can make",
    "python": "The Python interface",
}


class DocsInventoryError(DocsModelError):
    """An inventory cannot be built from what this reading found."""


# ---------------------------------------------------------------------------
# Component facts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reading:
    """One source the component facts were read out of, and what it gave.

    ``content_sha256`` is a digest of the *facts this reading produced*,
    not of the bytes it read them from. The two differ on purpose: two of
    the three readings are of code rather than of a file, so a file digest
    would be absent for them and the field would mean something different
    per row. A digest of the produced facts means one thing everywhere —
    "these are the values this source gave" — and moves exactly when the
    inventory would.
    """

    source: str
    components: int
    content_sha256: str


@dataclass(frozen=True)
class ComponentFact:
    """What is known about one registered component.

    ``visibility`` is ``None`` where the registration declares none, which
    is the honest answer for every component registered by core's bootstrap
    and by hand-written Python: visibility is a field of the s0ma language,
    declared on a cell or a nerve, and a Python registration has nowhere to
    put one. Absent is not "internal" and it is not "public"; renderers show
    it as absent and never guess.
    """

    id: str
    distribution: str
    kind: str
    layer: str
    visibility: str | None
    intent: str
    read_from: str


def _sha256_of(text: str) -> str:
    """The full sha256 of ``text`` as UTF-8, the house form for a source digest."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dotted(identifier: str) -> str:
    """The import path inside a ``component:`` id."""
    return identifier.removeprefix(COMPONENT_PREFIX)


def _distribution(dotted: str) -> str:
    """Which of the four distributions ships the component at ``dotted``."""
    top = dotted.partition(".")[0]
    named = DISTRIBUTION_BY_MODULE.get(top)
    if named is None:
        raise DocsInventoryError(
            f"{dotted} is not in any of the four distributions "
            f"({', '.join(sorted(set(DISTRIBUTION_BY_MODULE.values())))}). A "
            f"component the workspace does not ship cannot be inventoried, "
            f"and guessing a package for it would put a false fact in a file "
            f"other documents are meant to cite."
        )
    return named


def _text_value(raw: Any) -> str:
    """One line of prose out of the IR's ``{state, value}`` field wrapper.

    The canonical IR wraps a field value in a state marker so an absent
    field and an empty one stay distinguishable. Only ``value`` carries
    text; anything else is read as no text at all rather than as the word
    the marker happens to be spelled with.
    """
    if isinstance(raw, str):
        return " ".join(raw.split())
    if isinstance(raw, dict) and raw.get("state") == "value":
        inner = raw.get("value")
        if isinstance(inner, str):
            return " ".join(inner.split())
    return ""


def _core_facts() -> dict[str, tuple[str, str, str | None, str]]:
    """Core's own components, from a registry booted for this build.

    ADR-012 §3: every build boots its own registry. Nothing persisted, and
    nothing read out of whatever else this process imported — the same
    bootstrap ``CoreProvider`` holds to its own count.
    """
    from s0ma._bootstrap import bootstrap_register
    from s0ma.registry import ComponentRegistry

    registry = ComponentRegistry(persist=False)
    bootstrap_register(registry)
    found: dict[str, tuple[str, str, str | None, str]] = {}
    for spec in registry.get_all().values():
        dotted = spec.qualified_name or f"{spec.module_path}.{spec.name}"
        if not dotted:
            continue
        metadata = spec.metadata or {}
        declared = metadata.get("visibility")
        found[dotted] = (
            spec.kind.name,
            spec.layer.name,
            declared if isinstance(declared, str) and declared else None,
            " ".join((spec.intent or "").split()),
        )
    return found


def _ir_facts(
    root: Path, needed: Iterable[str]
) -> dict[str, tuple[str, str, str | None, str]]:
    """The transpiled packages' components, from their committed IR.

    One file per module, read as files. The module block carries the layer
    — a layer is a property of a module in the language, not of each
    declaration in it — and each component carries its own kind, visibility
    and intent.

    Only the packages in ``needed`` are read, and a missing build directory
    is refused only when something asked for a component from it. A caller
    describing a composition that addresses no component of a transpiled
    package — the negative battery's planted builds, a consumer project —
    is not missing anything, and a reading that refused it would be
    complaining about a file nobody wanted.
    """
    found: dict[str, tuple[str, str, str | None, str]] = {}
    for module_name in sorted(set(needed) & set(BUILT_IR_DIRS)):
        relative = BUILT_IR_DIRS[module_name]
        directory = root / relative
        if not directory.is_dir():
            raise DocsInventoryError(
                f"{relative} is not in this checkout, so {module_name}'s "
                f"components cannot be read. The committed build ships in the "
                f"wheel; if it is missing, rebuild the package."
            )
        for path in sorted(directory.glob("*.s0ma.json")):
            document = _ir_document(path, relative)
            layer = ""
            module = document.get("module")
            if isinstance(module, dict):
                declared_layer = module.get("layer")
                layer = declared_layer if isinstance(declared_layer, str) else ""
            components = document.get("components")
            if not isinstance(components, list):
                continue
            for entry in components:
                if not isinstance(entry, dict):
                    continue
                canonical = entry.get("canonical_id")
                if not isinstance(canonical, str) or "::" not in canonical:
                    continue
                inner, _, name = canonical.partition("::")
                kind = entry.get("kind")
                visibility = entry.get("visibility")
                found[f"{module_name}.{inner}.{name}"] = (
                    kind if isinstance(kind, str) else "",
                    layer,
                    visibility if isinstance(visibility, str) and visibility else None,
                    _text_value(entry.get("intent")),
                )
    return found


def _ir_document(path: Path, relative: str) -> dict[str, Any]:
    """One canonical IR file, refused by name when it is not readable."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise DocsInventoryError(
            f"{relative}/{path.name} is not readable as JSON: {error}"
        ) from error
    if not isinstance(document, dict):
        raise DocsInventoryError(f"{relative}/{path.name} is not an IR document")
    return document


_MISSING = object()


def _registered_fact(dotted: str) -> tuple[str, str, str | None, str] | None:
    """The ``@component`` registration attached to the object at ``dotted``.

    The longest importable prefix is found first and the rest is walked
    with ``getattr``, which is how a dotted path that mixes a module with
    an attribute walk is resolved anywhere in this model. ``__dict__`` is
    consulted rather than ``getattr`` for the spec itself so a subclass
    does not inherit its parent's registration and report it as its own.
    """
    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        try:
            module = importlib.import_module(".".join(parts[:split]))
        except ImportError:
            continue
        target: Any = module
        for attribute in parts[split:]:
            target = getattr(target, attribute, _MISSING)
            if target is _MISSING:
                return None
        own: Any = getattr(target, "__dict__", None)
        spec = own.get("__component__") if hasattr(own, "get") else None
        if spec is None:
            return None
        metadata = getattr(spec, "metadata", None) or {}
        declared = metadata.get("visibility")
        return (
            getattr(spec.kind, "name", str(spec.kind)),
            getattr(spec.layer, "name", str(spec.layer)),
            declared if isinstance(declared, str) and declared else None,
            " ".join((getattr(spec, "intent", "") or "").split()),
        )
    return None


def component_facts(
    root: Path, component_ids: Iterable[str]
) -> tuple[tuple[ComponentFact, ...], tuple[Reading, ...]]:
    """What is known about every component this build addresses, and whence.

    ``component_ids`` is the set the build's providers vouch for — the same
    external-id seam ``ReferenceIndex`` resolves against — so the inventory
    describes exactly the components the documentation can point at, no
    more and no fewer. Which reading answers an id is decided by the id, not
    by what this process managed to import: see the module docstring.

    Raises:
        DocsInventoryError: when an id reaches no reading. A component with
            no facts is not rendered as an absent row; the build stops,
            because every count taken from a holed inventory is wrong by an
            unknown amount.
    """
    wanted = sorted({item for item in component_ids if item.startswith(COMPONENT_PREFIX)})
    families = {_dotted(item).partition(".")[0] for item in wanted}
    core = _core_facts() if "s0ma" in families else {}
    emitted = _ir_facts(root, families)

    facts: list[ComponentFact] = []
    per_source: dict[str, list[ComponentFact]] = {}
    for identifier in wanted:
        dotted = _dotted(identifier)
        distribution = _distribution(dotted)
        top = dotted.partition(".")[0]
        found: tuple[str, str, str | None, str] | None = None
        source = ""
        if top == "s0ma":
            found = core.get(dotted)
            source = "python:s0ma._bootstrap.bootstrap_register"
        elif top in BUILT_IR_DIRS:
            found = emitted.get(dotted)
            source = f"{BUILT_IR_DIRS[top]}/*.s0ma.json"
        if found is None:
            found = _registered_fact(dotted)
            source = REGISTRATION_SOURCE
        if found is None:
            raise DocsInventoryError(
                f"{identifier} is a component this build addresses and no "
                f"reading can describe: it is not in core's bootstrap, not in "
                f"a transpiled package's committed IR, and carries no "
                f"@component registration this process can reach. A component "
                f"listed without its facts would make every count taken from "
                f"the inventory wrong by an amount nobody can see."
            )
        kind, layer, visibility, intent = found
        fact = ComponentFact(
            id=identifier,
            distribution=distribution,
            kind=kind,
            layer=layer,
            visibility=visibility,
            intent=intent,
            read_from=source,
        )
        facts.append(fact)
        per_source.setdefault(source, []).append(fact)

    readings = tuple(
        Reading(
            source=source,
            components=len(group),
            content_sha256=_sha256_of(
                canonical_json([_component_row(item) for item in group])
            ),
        )
        for source, group in sorted(per_source.items())
    )
    return tuple(facts), readings


# ---------------------------------------------------------------------------
# The three machine-readable inventories
# ---------------------------------------------------------------------------


def _source_of(bundle: DocsBundle) -> dict[str, str]:
    """Which build an inventory was rendered from.

    The stamp is not copied onto anything the model calls a record
    (``records.BUILD_STAMP_ONLY_FIELDS``); an artifact is not a record, and
    a rendering that could not name the build it came from would be a page
    with no way back to its source.
    """
    return {
        "model_schema": bundle.stamp.schema,
        "release_version": bundle.stamp.release_version,
        "snapshot_hash": bundle.stamp.snapshot_hash,
    }


def _tally(values: Iterable[str]) -> dict[str, int]:
    """How many times each value occurs, keyed by the value."""
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _concept_row(record: ConceptRecord) -> dict[str, Any]:
    """One concept, listed rather than reproduced.

    The summary is here because it is the authored short form a bounded
    channel is allowed to fall back to; the long definitions stay in the
    snapshot, which is the document that holds the model rather than an
    index into it.
    """
    return {
        "id": record.id,
        "term": record.term,
        "summary": record.summary,
        "governed_by": list(record.governed_by),
        "syntax_forms": len(record.syntax),
        "related_concepts": [list(edge) for edge in record.related_concepts],
        "examples": [item.id for item in record.examples],
    }


def concepts_inventory(bundle: DocsBundle) -> str:
    """Every concept this build composed, as canonical JSON."""
    records = sorted(bundle.concepts, key=lambda item: item.id)
    document = {
        "schema": INVENTORY_SCHEMA,
        "inventory": "concepts",
        "source": _source_of(bundle),
        "counts": {
            "concepts": len(records),
            "with_syntax": sum(1 for item in records if item.syntax),
            "with_related_concepts": sum(1 for item in records if item.related_concepts),
            "with_examples": sum(1 for item in records if item.examples),
        },
        "entries": [_concept_row(item) for item in records],
    }
    return canonical_json(document)


def _binding_of(record: SurfaceRecord) -> str:
    """Whether a surface reaches a component the model can address.

    Two words, and the second is not "unbound": a surface with no component
    reference and a written exception is a decision somebody took and wrote
    down, which is a different thing from one nobody has looked at. The
    exception text itself is in the snapshot; what an index needs is the
    state.
    """
    if record.component_refs:
        return "bound"
    return "exception" if record.manual_exception else "unbound"


def _surface_row(record: SurfaceRecord) -> dict[str, Any]:
    """One served capability, listed with the facts an index sorts on."""
    return {
        "id": record.id,
        "channel": record.channel,
        "public_name": record.public_name,
        "intent": record.intent,
        "side_effects": list(record.side_effects),
        "binding": _binding_of(record),
        "component_refs": list(record.component_refs),
        "governed_by": list(record.governed_by),
        "errors": list(record.errors),
    }


def surfaces_inventory(bundle: DocsBundle) -> str:
    """Every served capability this build composed, as canonical JSON."""
    records = sorted(bundle.surfaces, key=lambda item: item.id)
    return canonical_json(
        {
            "schema": INVENTORY_SCHEMA,
            "inventory": "surfaces",
            "source": _source_of(bundle),
            "counts": {
                "surfaces": len(records),
                "by_channel": _tally(item.channel for item in records),
                "by_side_effect": _tally(
                    effect for item in records for effect in item.side_effects
                ),
                "by_binding": _tally(_binding_of(item) for item in records),
                "undeclared_side_effects": sum(
                    1 for item in records if not item.side_effects
                ),
            },
            "entries": [_surface_row(item) for item in records],
        }
    )


def _component_row(fact: ComponentFact) -> dict[str, Any]:
    """One registered component, with the reading that described it."""
    return {
        "id": fact.id,
        "distribution": fact.distribution,
        "kind": fact.kind,
        "layer": fact.layer,
        "visibility": fact.visibility,
        "intent": fact.intent,
        "read_from": fact.read_from,
    }


def components_inventory(
    bundle: DocsBundle,
    facts: Sequence[ComponentFact],
    readings: Sequence[Reading],
) -> str:
    """Every component this build addresses, with its facts, as canonical JSON.

    The artifact C3 deferred and this milestone rules for. It is not a
    bundle group and nothing composes it: it is a rendering, stamped with
    the build it describes and with the three readings its facts came from.
    """
    ordered = sorted(facts, key=lambda item: item.id)
    return canonical_json(
        {
            "schema": INVENTORY_SCHEMA,
            "inventory": "components",
            "source": _source_of(bundle),
            "readings": [
                {
                    "source": item.source,
                    "components": item.components,
                    "content_sha256": item.content_sha256,
                }
                for item in sorted(readings, key=lambda item: item.source)
            ],
            "counts": {
                "components": len(ordered),
                "by_distribution": _tally(item.distribution for item in ordered),
                "by_kind": _tally(item.kind for item in ordered),
                "by_layer": _tally(item.layer for item in ordered),
                "by_visibility": _tally(
                    item.visibility or "(not declared)" for item in ordered
                ),
            },
            "entries": [_component_row(item) for item in ordered],
        }
    )


# ---------------------------------------------------------------------------
# The two reader indexes
# ---------------------------------------------------------------------------

#: The sentence every generated page carries, so a reader who arrives at one
#: knows it is not a page to edit and knows where the edit goes instead.
#: Public because F2's map of record is a generated page too, and one
#: sentence written twice is one sentence that can be edited once.
GENERATED_NOTE = (
    "This page is generated. Every line below is read from s0ma itself when "
    "the documentation is built, so editing it here would be undone by the "
    "next build — the place to make a change is the thing being described."
)


def cell(text: str) -> str:
    """One table cell: a single line, with the column separator escaped.

    A vertical bar inside a cell ends the cell, so an intent that contains
    one would silently shift every column after it. Runs of whitespace are
    collapsed for the same reason a wrapped intent cannot be trusted to stay
    on one line.

    Public for :mod:`~s0ma_dsl.docs_model.map_of_record`'s sake: two
    renderers that escaped a table cell differently would disagree about
    one document's title on two committed pages.
    """
    collapsed = " ".join(text.split())
    return collapsed.replace("|", "\\|")


def list_cell(values: Sequence[str], *, absent: str) -> str:
    """A list of values in one cell, or a stated word when there are none."""
    return ", ".join(cell(item) for item in values) if values else absent


def _channel_order(channels: Iterable[str]) -> list[str]:
    """The channels present, titled ones first in their declared order.

    A channel this module has never heard of sorts to the end under its own
    name rather than being left out. An index that quietly dropped a family
    of surfaces would be the one thing ``DOC_SURFACE_UNCOVERED`` exists to
    catch, and building the drop into the renderer would make the gate a
    test of itself.
    """
    present = set(channels)
    known = [name for name in CHANNEL_TITLES if name in present]
    return known + sorted(present - set(CHANNEL_TITLES))


def concepts_index(bundle: DocsBundle) -> str:
    """The reader's index of every concept, as Markdown.

    Every count in the page is computed here; none is written down. A
    hand-written number in a generated page is a number that goes wrong
    silently, which is the whole reason this page exists.
    """
    records = sorted(bundle.concepts, key=lambda item: item.term.lower())
    lines = [
        "# Concepts index",
        "",
        GENERATED_NOTE,
        "",
        f"s0ma teaches {len(records)} concepts. Each one has a short "
        f"definition here and a full entry — what it is for, when to reach "
        f"for it, when not to — in the composed model at "
        f"`docs/_generated/inventory-concepts.json`.",
        "",
        "| Concept | Id | In short |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| {cell(item.term)} | `{cell(item.id)}` | {cell(item.summary)} |"
        for item in records
    )
    lines.append("")
    return "\n".join(lines)


def surfaces_index(bundle: DocsBundle) -> str:
    """The reader's index of everything s0ma serves, as Markdown.

    Grouped by channel, because "what can I do with s0ma" is asked from
    inside one — at a terminal, from an agent, in a browser — and a single
    list of two hundred rows answers none of them. Every group is rendered,
    including one this module has no title for.
    """
    records = sorted(bundle.surfaces, key=lambda item: item.id)
    by_channel: dict[str, list[SurfaceRecord]] = {}
    for record in records:
        by_channel.setdefault(record.channel, []).append(record)
    order = _channel_order(by_channel)
    bound = sum(1 for item in records if _binding_of(item) == "bound")

    lines = [
        "# What s0ma can do",
        "",
        GENERATED_NOTE,
        "",
        f"s0ma serves {len(records)} capabilities across {len(order)} "
        f"channels. Each row names one of them: what it is called, the id "
        f"the model addresses it by, what it does, what calling it touches, "
        f"and whether the model can point at the code behind it. "
        f"{bound} of the {len(records)} reach a registered component; the "
        f"rest carry a written reason instead, and both are listed with "
        f"their reasons in `docs/_generated/inventory-surfaces.json`.",
        "",
        "Effects are read from the thing itself wherever the thing declares "
        "them: `none`, `read`, `write`, `network`, `subprocess`, "
        "`credential`, `approval`. Where a capability declares nothing, the "
        "row says so rather than guessing.",
        "",
    ]
    for channel in order:
        held = by_channel[channel]
        title = CHANNEL_TITLES.get(channel, channel)
        lines.append(f"## {title}")
        lines.append("")
        lines.append(f"{len(held)} of the {len(records)}. Channel: `{channel}`.")
        lines.append("")
        lines.append("| Name | Id | What it does | Effects | Binding |")
        lines.append("| --- | --- | --- | --- | --- |")
        lines.extend(
            f"| {cell(item.public_name)} | `{cell(item.id)}` | "
            f"{cell(item.intent)} | "
            f"{list_cell(item.side_effects, absent='not declared')} | "
            f"{_binding_of(item)} |"
            for item in held
        )
        lines.append("")
    return "\n".join(lines)
