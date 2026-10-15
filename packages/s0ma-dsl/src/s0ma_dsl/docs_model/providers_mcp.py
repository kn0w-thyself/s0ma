"""The MCP provider: what the authoring server registers, serves and is pinned to.

Milestone D3 of the docs-function plan (internal) §9, architecture plan
§7.4. One adapter over three readings of one server, cross-checked
against each other before a single record is built:

``python:s0ma_mcp.get_self_registry``
    The package's own component catalog. Every served surface is a
    registered component carrying its serving identity as declared
    metadata — ``mcp_tool``, ``mcp_uri``, ``mcp_prompt`` — so the
    registration set is a *declaration* of what should be served and,
    at the same time, the binding this model calls ``component_refs``.
``packages/s0ma-mcp/tests/snapshots/mcp_surface.json``
    The committed client-visible surface snapshot: the drift gate the
    MCP package already keeps over names, schemas, annotations and
    descriptions. A file source, so it is named by its
    repository-relative path and hashed as bytes.
``python:s0ma_mcp.create_server``
    The live in-process listing, read exactly the way a client reads
    it: ``list_tools``, ``list_resources``, ``list_prompts``.

**The cross-check is the point, and it runs first.** Architecture plan
§7.4: "a disagreement among those sources is a surface error before
documentation rendering starts". So :class:`McpProvider` compares the
three identity sets — and, for tools, the annotation hints the
side-effect facts are derived from — and raises
:class:`McpSurfaceDisagreementError` naming all three sources and every
difference, rather than emitting a record set that is quietly the
intersection or quietly the union of three disagreeing accounts.

**Why the import of ``s0ma_mcp`` is deferred.** ``s0ma-dsl`` does not
depend on ``s0ma-mcp``; the dependency runs the other way, and a
module-level import here would invert it and make ``docs_model``
unimportable for everyone who only wanted the transpiler. The import
therefore happens inside the reading, refused with a sentence that says
what to install — the same shape C3 uses for core's optional extras.
This is the sanctioned place for it: a provider is where a package
dependency belongs, and nothing else under ``docs_model`` may follow.

**Honesty rules this module is held to:**

* A surface's ``intent`` is a quotation — the served description's own
  first line, whitespace-collapsed within that line and otherwise
  verbatim. Where a source says nothing the field is empty rather than
  invented.
* Side effects are derived from the annotation the tool *declares* and
  the server *serves*, which the cross-check has already proved equal.
  ``readOnlyHint`` is the MCP specification's own promise about whether
  a tool modifies its environment, so ``read`` and ``write`` are read
  off it the way C3 reads ``read`` off an HTTP safe method. Nothing
  else is inferred: no annotation promises ``network``, ``subprocess``,
  ``credential`` or ``approval``, so a tool whose own hints say the
  effect leaves the ordinary local case — ``destructiveHint`` or
  ``openWorldHint`` set — is *refused* until a person has read it and
  written the classification into :data:`_HAND_CLASSIFIED`, where the
  record quotes them through its ``manual_exception``.
* Bindings are declared, not guessed. ``serves_as``/``mcp_tool``,
  ``mcp_uri`` and ``mcp_prompt`` name the served surface in the
  component's own registration, so every one of this package's served
  surfaces reaches exactly one component and no surface here carries a
  binding exception.

**T0 — the resource-template id convention, settled and landed.** The
``mcp:resource/`` charset was ``[A-Za-z0-9_./-]+`` and excluded braces,
and the plan flagged that core serves two resource templates
(``s0ma://model/examples-for/{component}`` and
``s0ma://model/docs-for/{component}``). Three findings settled it:

1. **This server serves none.** ``list_resource_templates()`` on
   ``s0ma_mcp.create_server()`` returns empty, so D3 emits twelve
   concrete resource ids and needed no template id to describe the
   authoring server truthfully. The two templates belong to *core's*
   MCP server, and C3's provider emits them — D5a's other half.
2. **The convention is: keep the braces.** The model already addresses
   one parameterized served address, and it keeps its braces —
   ``rest:GET:/self/component/{name}``, whose form pattern is
   ``[A-Za-z0-9_./{}-]*``. A second convention for the same problem
   would be the drift this model exists against.
3. **No brace-free normalization round-trips.** Stripping the braces
   makes ``examples-for/{component}`` and a literal resource
   ``examples-for/component`` the same id; ``<param>`` and
   percent-encoding are outside the charset exactly as braces are. So
   the honest form genuinely needed the one-character-class change, and
   ``ids.py`` was not this milestone's to edit.

D5a made it: the ``mcp_resource`` pattern is now
``^mcp:resource/[a-z0-9_]+://[A-Za-z0-9_./{}-]+$``.
``TestResourceTemplateGap`` pinned both halves against the live servers
while the change was owed, and now asserts the same two facts from the
other side — this server still serves no template, and a braced address
is addressable when one arrives.

**What this provider does not emit, and why.**

1. **The ``GUIDE_DOCS`` mirrors as documents.** They are already
   catalog rows — one ``doc:mirror/s0ma-mcp-*`` entry per packaged
   document in ``docs/s0ma_src/catalog.json``, C6's to hold — and a second account
   of one file is the failure the merge rule exists to prevent. This
   provider's subject is the *served surface*, so the mirror facts
   reach a caller through :meth:`McpProvider.mirrored_documents`
   instead, and this milestone's tests assert the correspondence
   against the real catalog.
2. **A ``mirrors`` edge from a resource to its catalog row.** §6.7 has
   the edge and C2 deferred it in as many words: ``mirrors`` "needs the
   artifact record nothing produces yet". ``@1``'s ``SurfaceRecord``
   has no field whose meaning is "the cataloged document this surface
   serves"; ``governed_by`` resolves as ``authority_refs`` and would
   report a mirrored guide as an authority governing the resource that
   serves it, which is false. So the correspondence is exposed and
   tested, and not forced into a field that means something else.
3. **``governed_by`` citations.** Nothing structural links a served
   tool to the frozen contract that governs it; the link is an
   authored citation, and this provider derives rather than authors.
   The feedback tools' user-only approval boundary is carried where it
   is derivable — as the ``approval`` side-effect fact, classified from
   the tool's own annotations and served description.
4. **``errors``.** The declared postconditions say what a tool promises
   across the MCP boundary in prose; no diagnostic id is declared
   anywhere on this surface, and parsing a postcondition sentence into
   an error list would be a paraphrase, not a reading.
5. **``mcp_dependency``.** Prompts declare which surfaces their journey
   uses. That is a surface-to-surface edge, which ``@1`` carries only
   in a ``JourneyRecord`` — E-phase work, and not something to smuggle
   into a field of the wrong kind.
6. **Component records.** A registered component is what a surface is
   *implemented by*, not a thing the documentation describes, so the
   inventory is handed to the caller through
   :meth:`McpProvider.external_ids` the way C3 hands over core's. Two
   of this package's thirty-six registrations are module-level
   callables under a package-flat qualified name —
   ``s0ma_mcp.create_server`` and ``s0ma_mcp.get_self_registry`` — that
   the ``component:`` form refused until D5a relaxed its floor from
   three dotted segments to two. The collision the form exists for is
   answered by the *package* segment, so two was always the honest
   floor; the inventory is now whole and
   :meth:`McpProvider.unaddressable_components` returns nothing. It is
   kept, empty, for the reason every counted deferral here is kept: a
   registration this model cannot address has to be countable on the
   day it appears.

**No side effects.** The self registry is built ``persist=False`` by
the MCP package itself, ``create_server()`` constructs a server object
and opens no socket, and the only file read is the committed snapshot.
Nothing here writes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from s0ma_dsl.docs_model.ids import is_valid_id, validate_id
from s0ma_dsl.docs_model.providers import (
    DocsProviderError,
    ProviderResult,
    SourcedRecord,
    sort_records,
)
from s0ma_dsl.docs_model.records import SCHEMA, Provenance, SurfaceRecord
from s0ma_dsl.docs_model.serialize import canonical_json, to_plain

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

__all__ = [
    "MCP_FLOORS",
    "MIRROR_DIR",
    "PROVIDER_ID",
    "REGISTRATION_SOURCE",
    "SERVED_SOURCE",
    "SNAPSHOT_SOURCE",
    "McpProvider",
    "McpProviderError",
    "McpSurfaceDisagreementError",
    "MirrorDocument",
]

#: This adapter's stable id, and the ``adapter_id`` on every record it
#: stamps. Plan §5 speaks of ``(provider_id, source)``; the model's word
#: for the first half is ``adapter_id``.
PROVIDER_ID = "mcp"

#: The three sources §7.4 names, each identified the way its kind is
#: identified: code by import path, a file by its repository-relative
#: path. All three are cross-checked; the records are stamped with the
#: served listing, because what a client can call is what a surface
#: record is *about* — see :meth:`McpProvider.cross_checked_sources`
#: for the other two, whose digests a caller can still see.
REGISTRATION_SOURCE = "python:s0ma_mcp.get_self_registry"
SNAPSHOT_SOURCE = "packages/s0ma-mcp/tests/snapshots/mcp_surface.json"
SERVED_SOURCE = "python:s0ma_mcp.create_server"

#: Where the packaged mirrors of the guide documents live, relative to
#: the repository root. A repository-relative constant rather than a
#: path derived from ``s0ma_mcp.__file__``: an installed package's file
#: path is a machine path, and a record may not carry one.
MIRROR_DIR = "packages/s0ma-mcp/src/s0ma_mcp/_docs"

#: Anti-vacuity floor, in the shape
#: :func:`~s0ma_dsl.docs_model.validate.check_floors` reads. Thirty-six
#: surfaces are served today — fifteen tools, sixteen resources, five
#: prompts — and the floor is set so that losing the smallest family
#: trips it while an ordinary addition or removal does not. The
#: per-family guard that a floor cannot express (a family going empty
#: in all three sources at once) is :func:`_checked_kinds`, inside the
#: reading.
MCP_FLOORS: Mapping[tuple[str, str], int] = {(PROVIDER_ID, "surfaces"): 32}

#: Channel words, from architecture plan §6.3's list.
_TOOL_CHANNEL = "mcp_tool"
_RESOURCE_CHANNEL = "mcp_resource"
_PROMPT_CHANNEL = "mcp_prompt"

#: The three served kinds, in the order a report reads best, paired
#: with the metadata key a registration declares its serving identity
#: under. One table, so the three readings cannot disagree about what
#: "the tools" are.
_KINDS: tuple[tuple[str, str], ...] = (
    ("tools", "mcp_tool"),
    ("resources", "mcp_uri"),
    ("prompts", "mcp_prompt"),
)

#: The annotation hint that decides a tool's read/write fact, and what
#: each of its values means. This is the MCP specification's own
#: promise about whether a tool modifies its environment, which is why
#: it needs no exception: nobody classified it, the protocol did.
_READ_ONLY_HINT = "readOnlyHint"

#: The hints that say an effect has left the ordinary local case. A
#: tool setting either must be hand-classified; the provider refuses to
#: guess what "destructive" or "open world" means in side-effect terms.
_ESCALATING_HINTS = ("destructiveHint", "openWorldHint")

#: Every tool whose own hints escalate it, and what a person found when
#: they read its served description and declared contract. The tuple is
#: the *complete* side-effect fact — its read/write half is checked
#: against the annotation, so this table cannot quietly contradict the
#: hint it was written for.
_HAND_CLASSIFIED: Mapping[str, tuple[tuple[str, ...], str]] = {
    "mcp:tool/run_example": (
        ("subprocess", "write"),
        "The subprocess fact was classified by hand. The tool's "
        "annotations say destructive and not read-only, which says an "
        "effect happens but not where; its served description says the "
        "declaration is executed in a timeout-bounded subprocess, and "
        "that is the fact a reader needs before running one.",
    ),
    "mcp:tool/submit_feedback": (
        ("approval", "network", "write"),
        "The approval and network facts were classified by hand. No "
        "annotation carries either: what says them is the tool's own "
        "served description — it asks the user to approve the exact "
        "feedback data and only then sends it — and its declared "
        "contract, which requires the user's decision to arrive from "
        "the binding layer and never from the caller. This is the "
        "user-only approval boundary, recorded as a fact rather than "
        "as prose.",
    ),
    "mcp:tool/verify_host": (
        ("approval", "subprocess", "write"),
        "The approval and subprocess facts were classified by hand. "
        "The annotations say destructive, not read-only and open "
        "world, which is as far as a hint goes; the served description "
        "says it imports trusted project code in the application's own "
        "Python without a sandbox and that execution must be approved "
        "explicitly first.",
    ),
}


class McpProviderError(DocsProviderError):
    """The MCP provider cannot read what it was asked to read.

    A provider-contract failure, not a documentation finding. Nobody
    authoring documentation can fix an uninstalled package or a missing
    committed snapshot, and continuing would describe a smaller product
    than the one that ships.
    """


class McpSurfaceDisagreementError(McpProviderError):
    """The three accounts of the served surface do not agree (§7.4).

    Raised before any record is built, and it names all three sources
    and every difference. A provider that emitted the intersection
    would silently document less than is served; one that emitted the
    union would document what is not. Neither is a documentation
    problem an author can act on, so this is an error and not a
    finding.
    """


# ---------------------------------------------------------------------------
# Small shared readings
# ---------------------------------------------------------------------------


def _summary_line(text: str | None) -> str:
    """The first non-empty line of ``text``, whitespace-collapsed.

    A record carries the source's summary line rather than its whole
    description: the full text stays reachable through the source
    identity, and a bundle that inlined every tool description would be
    mostly prose. Selecting the first line is not a paraphrase — it is
    the sentence the author wrote first — and the collapse only touches
    runs of whitespace inside that one line.

    Written again here rather than shared with the core provider: the
    contract says providers run independently and read no other
    provider's output, and six lines of agreement is a smaller cost
    than a shared private helper two adapters would both constrain.
    """
    if not text:
        return ""
    for line in text.splitlines():
        collapsed = " ".join(line.split())
        if collapsed:
            return collapsed
    return ""


def _digest_of(value: object) -> str:
    """The sha256 of a canonical rendering of ``value``, as 64 hex chars.

    Not a file hash where the source is code: an import path names no
    file whose bytes mean the same thing. This digests the facts that
    were read — and only those, never the provenance about to carry it
    — so it moves when the served surface moves and at no other time.
    """
    return hashlib.sha256(canonical_json(to_plain(value)).encode("utf-8")).hexdigest()


def _provenance(source: str, digest: str) -> Provenance:
    """One source's stamp, with all four parts the contract requires."""
    return Provenance(
        adapter_id=PROVIDER_ID,
        schema_version=SCHEMA,
        source=source,
        source_sha256=digest,
    )


def _named(value: Any) -> str:
    """What ``value`` is, in the words a refusal should use."""
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, str):
        return "text"
    return "a number"


def _object(value: Any, where: str) -> dict[str, Any]:
    """``value`` as a JSON object, refusing anything else by name."""
    if not isinstance(value, dict):
        raise McpProviderError(f"{where}: expected an object, got {_named(value)}")
    return value


def _array(value: Any, where: str) -> list[Any]:
    """``value`` as a JSON array, refusing anything else by name."""
    if not isinstance(value, list):
        raise McpProviderError(f"{where}: expected a list, got {_named(value)}")
    return value


def _text(value: Any, where: str) -> str:
    """``value`` as a non-empty string, refusing anything else by name."""
    if not isinstance(value, str):
        raise McpProviderError(f"{where}: expected text, got {_named(value)}")
    if not value.strip():
        raise McpProviderError(
            f"{where}: is empty. A served name is an identity, and an empty "
            f"one addresses nothing."
        )
    return value


# ---------------------------------------------------------------------------
# What one reading of the surface looks like
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Reading:
    """One account of the served surface: its names, and its tool hints.

    ``names`` maps kind to the sorted served identities of that kind —
    a tool name, a resource URI, a prompt name. ``hints`` maps a tool
    name to the annotation hints that account says it sets, with the
    unset ones dropped: an unset hint is deliberately unset (the MCP
    package's own snapshot docstring says so), and comparing ``None``
    against an absent key would report a disagreement between two
    sources that agree.
    """

    names: Mapping[str, tuple[str, ...]]
    hints: Mapping[str, Mapping[str, object]]


def _set_hints(raw: Mapping[str, Any] | None) -> dict[str, object]:
    """The hints an account actually sets, with the unset ones dropped."""
    if not raw:
        return {}
    return {key: value for key, value in raw.items() if value is not None}


def _comparable(hints: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    """One account's hints as sorted ``(name, written value)`` pairs.

    Sorted and hashable so three accounts can be compared as a set, and
    written through the JSON writer so ``true`` and ``"true"`` do not
    compare equal — a hint whose type changed is a disagreement.
    """
    return tuple(
        sorted((key, json.dumps(value, sort_keys=True)) for key, value in hints.items())
    )


def _reading_facts(reading: _Reading) -> tuple[object, ...]:
    """A reading as plain nested tuples, for a digest that covers it all."""
    return (
        tuple((kind, reading.names[kind]) for kind, _key in _KINDS),
        tuple((name, _comparable(reading.hints[name])) for name in sorted(reading.hints)),
    )


def _registration_reading(registry: Any) -> _Reading:
    """What the package's own catalog declares it should serve.

    Every served component carries its serving identity as declared
    metadata, so this reading is a *declaration* and not an
    observation: it says what ought to be there, which is exactly what
    makes it worth comparing against what is.
    """
    names: dict[str, list[str]] = {kind: [] for kind, _ in _KINDS}
    hints: dict[str, Mapping[str, object]] = {}
    for spec in registry.get_all().values():
        metadata: Mapping[str, Any] = spec.metadata or {}
        for kind, key in _KINDS:
            served = metadata.get(key)
            if served is None:
                continue
            names[kind].append(_text(served, f"{REGISTRATION_SOURCE}/{spec.name}/{key}"))
            if kind == "tools":
                hints[str(served)] = _set_hints(metadata.get("mcp_tool_annotations"))
    return _Reading(
        names={kind: tuple(sorted(found)) for kind, found in names.items()},
        hints=hints,
    )


def _snapshot_reading(text: str, where: str) -> _Reading:
    """What the committed drift snapshot pins the surface to."""
    document = _object(json.loads(text), where)
    names: dict[str, tuple[str, ...]] = {}
    hints: dict[str, Mapping[str, object]] = {}
    for kind, _key in _KINDS:
        if kind not in document:
            raise McpProviderError(
                f"{where}: carries no {kind!r} list. The snapshot is the "
                f"committed account of the whole client-visible surface; one "
                f"missing kind makes it an account of part of it."
            )
        field = "uri" if kind == "resources" else "name"
        found: list[str] = []
        for position, entry in enumerate(_array(document[kind], f"{where}/{kind}")):
            item = _object(entry, f"{where}/{kind}/{position}")
            served = _text(item.get(field), f"{where}/{kind}/{position}/{field}")
            found.append(served)
            if kind == "tools":
                hints[served] = _set_hints(item.get("annotations"))
        names[kind] = tuple(sorted(found))
    return _Reading(names=names, hints=hints)


def _served_reading(server: Any) -> tuple[_Reading, dict[str, str], dict[str, str]]:
    """What a client sees, plus the descriptions the records will quote.

    Three questions to one server object, asked the way the MCP
    package's own parity test asks them. The two mappings alongside the
    reading are the served descriptions — by served identity — and the
    tool titles, so the caller does not have to list the server twice.
    """
    tools = asyncio.run(server.list_tools())
    resources = asyncio.run(server.list_resources())
    prompts = asyncio.run(server.list_prompts())

    descriptions: dict[str, str] = {}
    hints: dict[str, Mapping[str, object]] = {}
    names: dict[str, tuple[str, ...]] = {}

    tool_names: list[str] = []
    for tool in tools:
        served = _text(str(tool.name), f"{SERVED_SOURCE}/tools/name")
        tool_names.append(served)
        descriptions[f"tools/{served}"] = tool.description or ""
        annotations = tool.annotations
        hints[served] = _set_hints(
            annotations.model_dump(mode="json") if annotations is not None else None
        )
    names["tools"] = tuple(sorted(tool_names))

    resource_names: list[str] = []
    for resource in resources:
        served = _text(str(resource.uri), f"{SERVED_SOURCE}/resources/uri")
        resource_names.append(served)
        descriptions[f"resources/{served}"] = resource.description or ""
    names["resources"] = tuple(sorted(resource_names))

    prompt_names: list[str] = []
    for prompt in prompts:
        served = _text(str(prompt.name), f"{SERVED_SOURCE}/prompts/name")
        prompt_names.append(served)
        descriptions[f"prompts/{served}"] = prompt.description or ""
    names["prompts"] = tuple(sorted(prompt_names))

    templates = asyncio.run(server.list_resource_templates())
    template_uris = {str(template.uriTemplate) for template in templates}
    return _Reading(names=names, hints=hints), descriptions, dict.fromkeys(template_uris, "")


# ---------------------------------------------------------------------------
# The cross-check (T1)
# ---------------------------------------------------------------------------


def _difference_lines(
    kind: str, accounts: Sequence[tuple[str, tuple[str, ...]]]
) -> list[str]:
    """Every source's difference from the others, said from both sides.

    A source that is *missing* something and a source that *alone* has
    something are the two shapes a disagreement takes, and a report
    that gave only the first would leave the source carrying the
    invented surface named nowhere but in the header.
    """
    everything = sorted({name for _source, found in accounts for name in found})
    lines: list[str] = []
    for source, found in accounts:
        missing = [name for name in everything if name not in found]
        if missing:
            lines.append(f"  {kind}: {source} does not have {missing}")
        alone = [
            name
            for name in found
            if all(name not in other for that, other in accounts if that != source)
        ]
        if alone:
            lines.append(f"  {kind}: {source} alone has {alone}")
    return lines


def _cross_check(accounts: Sequence[tuple[str, _Reading]]) -> None:
    """Refuse unless all three accounts of the surface are the same one.

    Architecture plan §7.4's rule, and the reason this provider exists
    in the shape it does. Every difference is reported at once, and
    every source is named in every difference, because a report that
    said only "they disagree" would leave a reader to diff three files
    by hand.
    """
    problems: list[str] = []
    for kind, _key in _KINDS:
        found = [(source, reading.names[kind]) for source, reading in accounts]
        if len({names for _source, names in found}) > 1:
            problems.extend(_difference_lines(kind, found))

    tools = sorted({name for _source, reading in accounts for name in reading.hints})
    for name in tools:
        stated = [
            (source, _comparable(reading.hints.get(name, {})))
            for source, reading in accounts
        ]
        if len({hint for _source, hint in stated}) > 1:
            for source, hint in stated:
                written = dict(hint) if hint else "nothing"
                problems.append(f"  annotations: {source} says {name} sets {written}")

    if problems:
        named = ", ".join(source for source, _reading in accounts)
        raise McpSurfaceDisagreementError(
            "the three accounts of the served MCP surface disagree, so no "
            "record can be built from them. Sources compared: "
            f"{named}.\n" + "\n".join(problems) + "\n"
            "Every side-effect fact this provider emits is read off an "
            "annotation, and every binding off a registration, so a "
            "disagreement here is not a documentation problem to report — it "
            "is one of the three being wrong. Regenerate the committed "
            "snapshot if the change was deliberate, or fix the registration "
            "that stopped matching what is served."
        )


def _checked_kinds(reading: _Reading) -> None:
    """Refuse a surface where a whole family came back empty.

    A floor cannot see this: three sources that agree the tools are
    gone pass the cross-check, and the surfaces group would still be
    full of resources and prompts. The families are named individually
    here for that reason.
    """
    empty = sorted(kind for kind, _key in _KINDS if not reading.names[kind])
    if empty:
        raise McpProviderError(
            f"the MCP server serves no {', '.join(empty)}. Three sources "
            f"agreeing that a whole family of surfaces vanished is still a "
            f"reading this provider will not hand over: the anti-vacuity "
            f"floor counts surfaces of every kind together and cannot see one "
            f"family go to zero."
        )


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


def _tool_effects(identifier: str, hints: Mapping[str, object]) -> tuple[tuple[str, ...], str]:
    """One tool's side-effect facts and the exception that explains them.

    ``readOnlyHint`` decides ``read`` or ``write`` and needs no
    exception: the protocol promises it. A tool that also sets an
    escalating hint has an effect the annotation does not describe, and
    is refused until :data:`_HAND_CLASSIFIED` says what a person found
    — the hand-written tuple's read/write half is checked against the
    hint, so the table cannot contradict the annotation it explains.
    """
    read_only = hints.get(_READ_ONLY_HINT)
    if not isinstance(read_only, bool):
        raise McpProviderError(
            f"{identifier} declares no {_READ_ONLY_HINT}, so nothing says "
            f"whether calling it changes anything. Every side-effect fact "
            f"this provider emits is read off that hint; a tool without one "
            f"could only be guessed at, and a mutating tool recorded as a "
            f"read is the mistake a documentation build must never make "
            f"quietly."
        )
    derived = "read" if read_only else "write"
    escalating = sorted(hint for hint in _ESCALATING_HINTS if hints.get(hint) is True)
    if not escalating:
        return (derived,), ""

    classified = _HAND_CLASSIFIED.get(identifier)
    if classified is None:
        raise McpProviderError(
            f"{identifier} sets {escalating}, which says its effect leaves "
            f"the ordinary local case, and no annotation says where it goes. "
            f"Read the tool and record its side effects — none, read, write, "
            f"network, subprocess, credential or approval — with the reason, "
            f"so the record can quote a person rather than a hint."
        )
    effects, exception = classified
    if derived not in effects:
        raise McpProviderError(
            f"{identifier} is classified as {list(effects)} and its "
            f"{_READ_ONLY_HINT} says {derived!r}. The hand-written "
            f"classification explains the annotation; it may not contradict "
            f"it."
        )
    return tuple(sorted(effects)), exception


@dataclass(frozen=True)
class _SurfaceDraft:
    """A surface's facts before its provenance is known.

    The digest of a source covers the facts read from it, and those
    facts have to exist before the stamp that carries the digest can be
    built. A draft is that intermediate state, and it is a dataclass so
    the same canonical serializer covers it.
    """

    id: str
    channel: str
    public_name: str
    intent: str
    component_refs: tuple[str, ...]
    manual_exception: str
    governed_by: tuple[str, ...]
    side_effects: tuple[str, ...]
    errors: tuple[str, ...]

    def record(self, provenance: Provenance) -> SurfaceRecord:
        """The real record, stamped."""
        return SurfaceRecord(
            id=self.id,
            channel=self.channel,
            public_name=self.public_name,
            intent=self.intent,
            component_refs=self.component_refs,
            manual_exception=self.manual_exception,
            governed_by=self.governed_by,
            side_effects=self.side_effects,
            errors=self.errors,
            provenance=provenance,
        )


@dataclass(frozen=True)
class MirrorDocument:
    """A served resource, the file it ships, and where that file comes from.

    The correspondence ``GUIDE_DOCS`` already holds, in the model's own
    vocabulary: ``resource`` is the ``mcp:resource/`` id, ``mirror`` is
    the packaged copy the server actually reads, and ``canonical``
    is the in-repository document that copy was made from. Both paths
    are repository-relative POSIX, so nothing here carries a machine
    path.

    Not a record: see this module's docstring. It is the seam a caller
    uses to hold the served surface and the document catalog against
    each other without either provider reading the other's output.
    """

    resource: str
    mirror: str
    canonical: str


def _component_id(qualified_name: str) -> str:
    """The package-qualified id of one registered component.

    Never a flat name: four packages register components into one
    registry, and a name with no package segment could mean a different
    component in another package (plan §5; D5a set the floor at two
    dotted segments, which is where the package segment is).
    """
    identifier = f"component:{qualified_name}"
    validate_id(identifier)
    return identifier


def _inventory(registry: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """This package's component inventory, split by what can be addressed.

    The second half is empty today. Two of the package's registrations
    are module-level callables whose qualified name is package-flat —
    ``s0ma_mcp.create_server`` and ``s0ma_mcp.get_self_registry`` — and
    the ``component:`` form used to refuse a name with fewer than three
    dotted segments. D5a relaxed the floor to two: four packages
    register into one registry and it is the *package* segment that
    tells them apart, so insisting on a module segment refused two real
    registrations without answering anything.

    The split stays. A registration the form cannot address is counted
    and handed back separately rather than dropped, because an inventory
    that silently lost an entry is the failure an inventory exists to
    prevent — and that has to be true on the day it happens, not
    arranged afterwards.
    """
    addressable: list[str] = []
    flat: list[str] = []
    for spec in registry.get_all().values():
        dotted = str(spec.qualified_name)
        identifier = f"component:{dotted}"
        if is_valid_id(identifier):
            addressable.append(identifier)
        else:
            flat.append(dotted)
    return tuple(sorted(addressable)), tuple(sorted(flat))


def _binding(registry: Any) -> dict[str, tuple[str, ...]]:
    """Served identity mapped to the components that implement it.

    Declared, not derived from a closure: a served surface names itself
    in its own registration, which is the strongest binding evidence
    this model can have. Two components claiming one served name is
    refused — the served surface would then be implemented by two
    things the server can only have derived one of.
    """
    bound: dict[str, tuple[str, ...]] = {}
    for spec in sorted(registry.get_all().values(), key=lambda item: str(item.name)):
        metadata: Mapping[str, Any] = spec.metadata or {}
        for kind, key in _KINDS:
            served = metadata.get(key)
            if served is None:
                continue
            identifier = _component_id(str(spec.qualified_name))
            slot = f"{kind}/{served}"
            held = bound.get(slot)
            if held is not None:
                raise McpProviderError(
                    f"{slot} is claimed by {held[0]} and by {identifier}. One "
                    f"served surface is implemented by one registration; two "
                    f"claims make the binding depend on which was registered "
                    f"first."
                )
            bound[slot] = (identifier,)
    return bound


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


class McpProvider:
    """One deterministic reading of the authoring MCP server.

    ``root`` is the immutable input the provider contract asks for: the
    repository whose committed snapshot the served surface is checked
    against. Point it at a copy and the snapshot of the copy is what is
    compared, which is how the cross-check's failure is proved.

    Everything is read when the provider is built and :meth:`provide`
    hands over what was read, so "reads nothing at call time" is a
    property of the object rather than a promise: calling it twice
    returns the same object.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        registry, server = self._imports()

        snapshot_path = root / SNAPSHOT_SOURCE
        if not snapshot_path.is_file():
            raise McpProviderError(
                f"the committed MCP surface snapshot is not at "
                f"{SNAPSHOT_SOURCE} under the given root. It is one of the "
                f"three accounts §7.4 requires to agree, so without it this "
                f"provider can only report what one source says and call it "
                f"three."
            )
        # Read as bytes and decode here rather than through read_text:
        # the digest below is the *file's* digest, and text mode would
        # translate line endings on a checkout that has them, making one
        # file hash to two things on two platforms.
        snapshot_bytes = snapshot_path.read_bytes()
        snapshot_text = snapshot_bytes.decode("utf-8")

        registration = _registration_reading(registry)
        snapshot = _snapshot_reading(snapshot_text, SNAPSHOT_SOURCE)
        served, descriptions, templates = _served_reading(server)

        _cross_check(
            (
                (REGISTRATION_SOURCE, registration),
                (SNAPSHOT_SOURCE, snapshot),
                (SERVED_SOURCE, served),
            )
        )
        _checked_kinds(served)

        self._templates = tuple(sorted(templates))
        self._component_ids, self._flat_components = _inventory(registry)
        drafts = self._drafts(served, descriptions, _binding(registry))
        provenance = _provenance(SERVED_SOURCE, _digest_of(drafts))
        self._result = ProviderResult(
            provider_id=PROVIDER_ID,
            records=sort_records(
                SourcedRecord.of(draft.record(provenance)) for draft in drafts
            ),
        )
        self._checked = (
            (REGISTRATION_SOURCE, _digest_of(_reading_facts(registration))),
            (SNAPSHOT_SOURCE, hashlib.sha256(snapshot_bytes).hexdigest()),
            (SERVED_SOURCE, provenance.source_sha256),
        )
        self._mirrors = self._mirrored()

    # -- reading -----------------------------------------------------------

    def _imports(self) -> tuple[Any, Any]:
        """The MCP package's registry and a server, imported here on purpose.

        ``s0ma-dsl`` does not depend on ``s0ma-mcp``. A module-level
        import would invert the dependency direction and make
        ``docs_model`` unimportable wherever only the transpiler was
        wanted, so the import lives inside the reading that needs it and
        refuses with a sentence naming what to install.
        """
        try:
            from s0ma_mcp import create_server, get_self_registry
        except ImportError as error:  # pragma: no cover - exercised by hand
            raise McpProviderError(
                "the authoring MCP surface cannot be read without s0ma-mcp "
                "installed. A documentation build that quietly skipped a "
                "served channel would describe a smaller product than the "
                "one that ships."
            ) from error
        return get_self_registry(), create_server()

    def _drafts(
        self,
        served: _Reading,
        descriptions: Mapping[str, str],
        bound: Mapping[str, tuple[str, ...]],
    ) -> tuple[_SurfaceDraft, ...]:
        """Every served surface, as facts, in one pass over the listing."""
        drafts: list[_SurfaceDraft] = []
        for kind, _key in _KINDS:
            for name in served.names[kind]:
                drafts.append(
                    self._draft(kind, name, served, descriptions, bound)
                )
        return tuple(drafts)

    def _draft(
        self,
        kind: str,
        name: str,
        served: _Reading,
        descriptions: Mapping[str, str],
        bound: Mapping[str, tuple[str, ...]],
    ) -> _SurfaceDraft:
        """One served surface's facts.

        The read fact for a resource and the ``none`` fact for a prompt
        are the protocol's own promises about its primitives, the way
        ``GET`` is HTTP's: reading a resource returns content, and a
        prompt hands back a message template for the client to render.
        Neither is this provider's inference, so neither carries an
        exception; a tool, whose primitive promises nothing, is
        classified from its annotations instead.
        """
        if kind == "tools":
            identifier = f"mcp:tool/{name}"
            channel = _TOOL_CHANNEL
        elif kind == "resources":
            identifier = f"mcp:resource/{name}"
            channel = _RESOURCE_CHANNEL
        else:
            identifier = f"mcp:prompt/{name}"
            channel = _PROMPT_CHANNEL
        validate_id(identifier)

        if kind == "tools":
            side_effects, exception = _tool_effects(identifier, served.hints.get(name, {}))
        elif kind == "resources":
            side_effects, exception = ("read",), ""
        else:
            side_effects, exception = ("none",), ""

        refs = bound.get(f"{kind}/{name}")
        if refs is None:
            raise McpProviderError(
                f"{identifier} is served and no registration claims it. Every "
                f"surface of this package is a registered component that "
                f"names the surface it serves, so an unclaimed one means the "
                f"server grew a surface outside the catalog it is derived "
                f"from."
            )
        return _SurfaceDraft(
            id=identifier,
            channel=channel,
            public_name=name,
            intent=_summary_line(descriptions.get(f"{kind}/{name}")),
            component_refs=refs,
            manual_exception=exception,
            governed_by=(),
            side_effects=side_effects,
            errors=(),
        )

    def _mirrored(self) -> tuple[MirrorDocument, ...]:
        """The packaged guide documents, as resource-to-document facts.

        ``GUIDE_DOCS`` already holds every part: the URI the server
        registers, the filename it ships, and the in-repository
        document that file is a committed copy of. All this does is say
        the three in the model's vocabulary and check that the packaged
        file is really there — a mirror record naming a file nobody
        ships would be the vacuity this whole phase is written against.
        """
        try:
            from s0ma_mcp import resources
        except ImportError as error:  # pragma: no cover - exercised by hand
            raise McpProviderError(
                "the packaged guide documents cannot be read without "
                "s0ma-mcp installed."
            ) from error

        found: list[MirrorDocument] = []
        for doc in resources.GUIDE_DOCS.values():
            mirror = f"{MIRROR_DIR}/{doc.filename}"
            if not (self._root / mirror).is_file():
                raise McpProviderError(
                    f"{doc.uri} is served from {mirror}, which this checkout "
                    f"does not have. A mirror fact naming a file nobody ships "
                    f"describes a resource that cannot answer."
                )
            identifier = f"mcp:resource/{doc.uri}"
            validate_id(identifier)
            found.append(
                MirrorDocument(resource=identifier, mirror=mirror, canonical=doc.source)
            )
        return tuple(sorted(found, key=lambda item: item.resource))

    # -- the contract ------------------------------------------------------

    @property
    def provider_id(self) -> str:
        """This adapter's stable id, unique across the registry."""
        return PROVIDER_ID

    def provide(self) -> ProviderResult:
        """The records read at construction, sorted, stamped, unchanged."""
        return self._result

    # -- what the provider knows and does not hold -------------------------

    def component_ids(self) -> tuple[str, ...]:
        """Every component this package registers that the model addresses.

        The resolution universe for the ``component:`` references this
        provider's records make. It is not a bundle group — a
        registered component has no record type — so it reaches a build
        through :class:`~s0ma_dsl.docs_model.validate.ReferenceIndex`'s
        ``external_ids``, the seam C2 built for exactly this.
        """
        return self._component_ids

    def unaddressable_components(self) -> tuple[str, ...]:
        """The registrations no id form reaches, by qualified name.

        Empty since D5a relaxed the ``component:`` floor to two dotted
        segments — see :func:`_inventory`. Kept so a caller can count a
        future one rather than discover it missing.
        """
        return self._flat_components

    def external_ids(self) -> tuple[str, ...]:
        """Everything this provider vouches for but does not hold.

        Components only: this package registers no runnable examples,
        so the second class C3 hands over is empty here rather than
        absent — a caller merging several providers' external ids
        should get the same shape from each.
        """
        return self._component_ids

    def cross_checked_sources(self) -> tuple[tuple[str, str], ...]:
        """Every source this provider looked at, with its digest.

        ``ProviderResult.sources`` names only what a record was stamped
        with, which is the served listing. The registration set and the
        committed snapshot were read too, and a reader should be able
        to see every place this provider looked — including the two
        whose only job was to agree.
        """
        return self._checked

    def mirrored_documents(self) -> tuple[MirrorDocument, ...]:
        """Which served resources are packaged copies of which documents.

        The correspondence the document catalog holds from the other
        side. Handed over rather than emitted: see this module's
        docstring for why ``@1`` has nowhere to put it.
        """
        return self._mirrors

    def resource_templates(self) -> tuple[str, ...]:
        """Every resource template this server serves. Empty, today.

        Kept as a reading rather than as an assumption: T0 settled the
        template-id convention on the evidence that this server has
        none, and the day it grows one this returns it and the id form
        that cannot address it becomes the milestone's problem rather
        than a surprise in a build.
        """
        return self._templates
