"""The core provider: what ``s0ma-core`` registers, serves and can be asked.

Milestone C3 of the docs-function plan (internal) §8, completed by D5a,
architecture plan §7.2. One adapter over five readings of one package,
all taken in process and none of them from a file this module parses:

``python:s0ma._bootstrap.bootstrap_register``
    A fresh :class:`~s0ma.registry.ComponentRegistry` populated by
    core's handwritten bootstrap. This is the **component inventory** —
    the resolution universe every ``component:`` reference in the build
    is checked against. See :meth:`CoreProvider.component_ids`.
``python:s0ma.__all__``
    Core's own list of what it exports. The names on it that the
    bootstrap does *not* register are module-level callables and
    constants, and each becomes a ``python:`` surface. C3 could not
    emit these — no id form addressed a module-level name — and pinned
    the gap; D5a added the form, which is what this reading is for.
``python:s0ma.api.rest.create_app``
    The FastAPI application built over that same registry, read through
    its own route table. Every route of the self-description interface
    becomes a ``rest:`` surface.
``python:s0ma.api.mcp_server.create_mcp_server``
    Core's own MCP server, listed the way a client lists it. Its tools
    become ``mcp:tool/`` surfaces and its resources — both the concrete
    ones and the two templates — become ``mcp:resource/`` surfaces. C3
    emitted the tools only, because the ``mcp:resource/`` charset could
    not spell a braced template address and describing half a family
    would have been worse than describing none; D5a widened the charset
    by exactly ``{}``, so the family is whole here.
``python:s0ma.registry.ComponentRegistry.snapshot``
    The registry's documentation and example stores: registered
    doc-refs and doc-guides become catalog rows, registered examples
    become ``example:`` ids.

**This module is the sanctioned place for ``s0ma`` imports.** The rest
of ``docs_model`` is core-free by design (a renderer, a gate or a future
package must be able to read the model without taking on a framework
dependency); a provider is where the dependency belongs, and the
direction — dsl code importing core — is the one the repository already
runs in. Nothing here imports ``s0ma_mcp``, ``s0ma_studi0`` or anything
under ``scripts/``: the B3 spike proved this reading works and is
evidence, not a dependency, so the reading is written again here.

**Two source-identity conventions, and why this module only uses one.**
A code source is named by its *import path* — ``python:s0ma.api.rest.``
``create_app`` — because the file path of an installed package is a
machine path, and machine paths are what the determinism invariant
forbids. A file source would be named by its repository-relative path.
Everything this provider reads is code, so every source here is an
import path and every ``source_sha256`` is a digest of the surface that
was read rather than of a file: it moves when, and only when, the
introspected surface moves. That is the honest analogue of a file hash
for something that has no file, and it is what makes a drift check
possible at all.

**Honesty rules this module is held to** (plan §1.2 fact 11):

* REST facts are derived by introspection, never registry-declared, and
  the record says which by the only means ``@1`` gives it: a
  :class:`~s0ma_dsl.docs_model.records.Provenance` carries no authority
  class, so what marks these ``derived`` is the source identity —
  ``python:s0ma.api.rest.create_app`` names the callable that was asked,
  and a declared fact would name a declaration instead. No OpenAPI
  machinery is invented; the route table is asked what it holds.
* FastAPI's four built-in documentation routes (``/openapi.json``,
  ``/docs``, ``/docs/oauth2-redirect``, ``/redoc``) are the web
  framework's surface, not the product's, and are excluded — they are
  not ``APIRoute`` instances, so the exclusion is structural rather
  than a name list that could rot.
* A surface's ``intent`` is a quotation. It is the source's own summary
  line, whitespace-collapsed within that line and otherwise verbatim;
  where the source says nothing, the field is empty rather than
  invented.
* Where a fact was classified by hand rather than read, the record says
  so in its ``manual_exception``. There are three such classes here and
  all three are counted by this module's tests: a route whose method
  HTTP does not vouch for, whose effects a person read off the endpoint
  and wrote into :data:`_HAND_CLASSIFIED` — and which is *refused*
  rather than guessed at when nobody has — every served MCP tool and
  resource, which the SDK's public listing exposes without an
  implementing callable to bind to, and every ``python:`` surface,
  which is a module-level name of core's public API rather than a
  registered component and so has nothing in the inventory to point at.

**What this provider does not emit, and why.** Two of the milestone's
asks have no home in ``s0ma-docs-model@1`` and are recorded here rather
than forced into a field that means something else:

1. **Component records.** Architecture plan §6.1–§6.6 defines six record
   types and none of them is a component; C1's model follows it, and
   ``validate.ReferenceIndex`` says so in as many words — "a registered
   component and a registered example both live outside the
   documentation model — so the caller passes them in as
   ``external_ids``". A registered component is what a surface is
   *implemented by*, not a thing the documentation describes. So the
   inventory is built, counted against core's own pin, and handed to the
   caller through :meth:`CoreProvider.external_ids`; it is not minted
   into a record type that would have to lie about what it is. Giving
   components records of their own means a seventh bundle group, which
   is a model change and not this milestone's to make.
2. **Response-model schema names.** B4 deferred ``input_schema`` and
   ``output_schema`` from the record deliberately ("a large derived blob
   a provider copies verbatim"), so there is nowhere to put
   ``SelfOverviewResponse``. The route's own summary carries what a
   reader needs and the schema stays reachable through the source
   identity.

**Side effects are still not claimed for the MCP families.** Core's
tools declare no ``ToolAnnotations``, so no ``readOnlyHint`` says
whether one modifies anything, and a resource carries no annotation at
all. Both families therefore carry an empty ``side_effects`` rather
than a guess that every later gate would read as a declaration. Closing
that — including the honest-empty case — is the side-effect
completeness milestone's work, and D5a deliberately leaves it there
rather than settling it in passing.

**No side effects.** The registry is constructed with ``persist=False``
and never through :func:`s0ma.registry.get_registry`: the global
singleton would make this reading depend on whatever else the process
has imported, and its default would write ``.s0ma/registry.db``.
ADR-012 §5.4 names both. Nothing here opens a socket, and nothing
writes.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from s0ma._bootstrap import EXPECTED_FRAMEWORK_COMPONENT_COUNT, bootstrap_register
from s0ma.registry import ComponentRegistry

from s0ma_dsl.docs_model.ids import validate_id
from s0ma_dsl.docs_model.providers import (
    DocsProviderError,
    ProviderResult,
    SourcedRecord,
    sort_records,
)
from s0ma_dsl.docs_model.records import (
    SCHEMA,
    DocumentRecord,
    Provenance,
    SurfaceRecord,
)
from s0ma_dsl.docs_model.serialize import canonical_json, to_plain

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from s0ma.models import DocGuideRegistration, DocRefRegistration, RegistrySnapshot

__all__ = [
    "BOOTSTRAP_SOURCE",
    "EXPORTS_SOURCE",
    "FLOORS",
    "MCP_SOURCE",
    "PROVIDER_ID",
    "REST_SOURCE",
    "STORES_SOURCE",
    "CoreProvider",
    "CoreProviderError",
]

#: This adapter's stable id. It is also the ``adapter_id`` stamped on
#: every record's provenance: plan §5 speaks of ``(provider_id, source)``
#: and the model's word for the first half is ``adapter_id``.
PROVIDER_ID = "core"

#: The five sources, each named by import path. A code source has no
#: file whose bytes mean the same thing, and an installed package's file
#: path is a machine path.
#:
#: Four of the five stamp records. The bootstrap is the exception: what
#: it yields is the component inventory, which this model addresses and
#: does not hold, so it is named here for the same reason the others are
#: — a reader should be able to see every place this provider looked —
#: and no record is stamped with it.
BOOTSTRAP_SOURCE = "python:s0ma._bootstrap.bootstrap_register"
EXPORTS_SOURCE = "python:s0ma.__all__"
REST_SOURCE = "python:s0ma.api.rest.create_app"
MCP_SOURCE = "python:s0ma.api.mcp_server.create_mcp_server"
STORES_SOURCE = "python:s0ma.registry.ComponentRegistry.snapshot"

#: Anti-vacuity floors for this provider, in the shape
#: :func:`~s0ma_dsl.docs_model.validate.check_floors` reads. Forty-three
#: surfaces are observed today, in four families: fourteen REST routes
#: (plan §1.2 fact 11 pins fourteen), twelve core MCP tools, eight core
#: MCP resources — six concrete and two templates — and nine
#: module-level public exports. The floor is thirty-six, which is
#: forty-three less the smallest family plus one: the loss of *any* one
#: family trips it, and no rename or ordinary addition reaches it. C3's
#: number was twenty-four against twenty-six for the same reason, and it
#: rose here because D5a unlocked two families C3 could not address.
#:
#: The component inventory is not a bundle group, so its floor is not
#: expressible here; it is exact rather than a floor anyway, and
#: :meth:`CoreProvider.component_ids` is checked against core's own
#: ``EXPECTED_FRAMEWORK_COMPONENT_COUNT`` by this milestone's tests.
FLOORS: Mapping[tuple[str, str], int] = {
    (PROVIDER_ID, "surfaces"): 36,
}

#: Channel words, from the architecture plan's §6.3 list.
_REST_CHANNEL = "rest"
_MCP_TOOL_CHANNEL = "mcp_tool"
_MCP_RESOURCE_CHANNEL = "mcp_resource"
_PYTHON_CHANNEL = "python"

#: The methods HTTP itself promises are safe. For one of these the read
#: fact is derived from the method and needs no exception; for anything
#: else a person has to say what the route does.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Written by hand, and the records that carry them say so. Both are
#: single paragraphs: an authored-prose field may not contain a blank
#: line in this version of the model.
_POST_QUERY_EXCEPTION = (
    "The read classification of this route was made by hand. HTTP does "
    "not promise that a POST only reads, and this one does: the "
    "question travels in a body because a question does not fit in a "
    "URL, and the endpoint answers it out of the registry without "
    "changing anything."
)
_MCP_TOOL_EXCEPTION = (
    "The implementing component was not derived. The MCP SDK's public "
    "listing gives a tool's name, description and schema but not the "
    "callable behind it, and reaching into the server's private tool "
    "manager would bind this record to an SDK internal. The binding is "
    "left for the milestone that completes every surface's binding."
)
_MCP_RESOURCE_EXCEPTION = (
    "The implementing component was not derived. The MCP SDK's public "
    "listing gives a resource its address, name and description but not "
    "the callable that answers a read of it, and reaching into the "
    "server's private resource manager would bind this record to an SDK "
    "internal. The binding is left for the milestone that completes "
    "every surface's binding."
)
_PYTHON_EXCEPTION = (
    "The implementing component was not derived, because there is none "
    "to derive: this is a module-level callable or constant of core's "
    "public API, not a registered component, so the inventory every "
    "component reference resolves against holds nothing for it to point "
    "at. What binds it is its own import path, which is its id."
)

#: Every route whose method does not itself promise a read, and what a
#: person found when they read the endpoint. A route that reaches this
#: provider without an entry here is refused rather than guessed at:
#: recording a mutating route as a read is the one mistake a
#: documentation build must never make quietly.
_HAND_CLASSIFIED: Mapping[str, tuple[tuple[str, ...], str]] = {
    "rest:POST:/self/query": (("read",), _POST_QUERY_EXCEPTION),
}


class CoreProviderError(DocsProviderError):
    """The core provider cannot read what it was asked to read.

    A provider-contract failure, not a documentation finding: no author
    can fix a missing optional dependency or a registry that came back
    empty, and continuing would produce a build that is quietly smaller
    than the product it describes.
    """


# ---------------------------------------------------------------------------
# Small shared readings
# ---------------------------------------------------------------------------


def _summary_line(text: str | None) -> str:
    """The first non-empty line of ``text``, whitespace-collapsed.

    A record carries the source's summary line rather than its whole
    docstring: the full text stays reachable through the source
    identity, and a bundle that inlined every tool description would be
    mostly prose. Selecting the summary line is not a paraphrase — it is
    the sentence the author wrote first, which is what the architecture
    plan means by "sourced intent or summary" — and the collapse only
    touches runs of whitespace inside that one line.
    """
    if not text:
        return ""
    for line in text.splitlines():
        collapsed = " ".join(line.split())
        if collapsed:
            return collapsed
    return ""


def _surface_digest(drafts: Sequence[object]) -> str:
    """The sha256 of everything one source claimed, as 64 hex characters.

    Not a file hash: an import path names no file whose bytes mean the
    same thing. This digests the facts the records assert — and only
    those, never the provenance that is about to carry it — so it moves
    when the introspected surface moves and at no other time. The
    canonical form is C1's, so the digest cannot disagree with the bytes
    the bundle is serialized to.
    """
    return hashlib.sha256(canonical_json(to_plain(tuple(drafts))).encode("utf-8")).hexdigest()


def _provenance(source: str, digest: str) -> Provenance:
    """One source's stamp, with all four parts the contract requires."""
    return Provenance(
        adapter_id=PROVIDER_ID,
        schema_version=SCHEMA,
        source=source,
        source_sha256=digest,
    )


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
class _DocumentDraft:
    """A catalog row's facts before its provenance is known."""

    id: str
    title: str
    canonical_source: str
    prose_locator: str
    governed_by: tuple[str, ...]
    covers: tuple[str, ...]

    def record(self) -> DocumentRecord:
        """The real record. A catalog row carries no provenance field."""
        return DocumentRecord(
            id=self.id,
            title=self.title,
            canonical_source=self.canonical_source,
            prose_locator=self.prose_locator,
            governed_by=self.governed_by,
            covers=self.covers,
        )


# ---------------------------------------------------------------------------
# Reading (a) — the component inventory
# ---------------------------------------------------------------------------


def _component_id(module_path: str, name: str, qualified_name: str) -> str:
    """The package-qualified id of one registered component.

    The registration's own ``qualified_name`` is the id wherever the
    registry set one, which for core's bootstrap is every component.
    Where it is absent the id is derived from ``module_path`` and
    ``name`` — the two fields the qualified name is itself built from —
    and where neither can produce a package-qualified name the component
    is refused rather than addressed by a flat name that could mean a
    different component in another package (plan §5).
    """
    dotted = qualified_name or (f"{module_path}.{name}" if module_path else "")
    if not dotted:
        raise CoreProviderError(
            f"the registered component {name!r} names no module, so it cannot "
            f"be addressed as component:<package>.<module>.<name>. Four "
            f"packages register into one registry and a flat name collides "
            f"across them, so there is no honest id to give it."
        )
    identifier = f"component:{dotted}"
    validate_id(identifier)
    return identifier


def _component_index(registry: ComponentRegistry) -> dict[str, str]:
    """Every registered component's import path mapped to its id.

    Keyed by import path because that is what an introspected value can
    be recognized by: a closure holding a ``SelfModelInterface`` is
    evidence of ``s0ma.self_model.interface.SelfModelInterface``, and
    this is the table that turns the second into a ``component:`` id.
    """
    index: dict[str, str] = {}
    for spec in registry.get_all().values():
        identifier = _component_id(spec.module_path, spec.name, spec.qualified_name)
        dotted = identifier.removeprefix("component:")
        held = index.get(dotted)
        if held is not None:
            raise CoreProviderError(
                f"two registered components share the import path {dotted!r}, "
                f"so the id {identifier!r} would address both. One of them has "
                f"to be registered under its real module."
            )
        index[dotted] = identifier
    return index


def _example_ids(snapshot: RegistrySnapshot) -> tuple[str, ...]:
    """Every registered example, addressed by the single-colon topic form.

    ``example:<name>``, never ``example::<name>``: the doubled form is
    the authoring syntax for an entity reference inside prose and means
    something else. Like a component, a registered example is a thing
    the model *addresses* rather than a thing it holds, so these are ids
    handed to the caller and not records.
    """
    ids = []
    for name in sorted(snapshot.examples):
        identifier = f"example:{name}"
        validate_id(identifier)
        ids.append(identifier)
    return tuple(ids)


# ---------------------------------------------------------------------------
# Reading (b) — the REST route table
# ---------------------------------------------------------------------------


def _route_effects(method: str, identifier: str) -> tuple[tuple[str, ...], str]:
    """One route's side-effect fact and the exception that explains it.

    A safe method is HTTP's own promise, so ``GET`` means read and the
    record carries no exception — nobody classified it, the protocol
    did. Every other method has to be read by a person, and what they
    found is written down in :data:`_HAND_CLASSIFIED` where the record
    can quote it. An unclassified one refuses the reading: a mutating
    route recorded as a read is worse than a build that stops.
    """
    if method in _SAFE_METHODS:
        return ("read",), ""
    classified = _HAND_CLASSIFIED.get(identifier)
    if classified is None:
        raise CoreProviderError(
            f"{identifier} serves a method HTTP does not promise is safe, and "
            f"nobody has said what it does. Read the endpoint and record its "
            f"side effects — none, read, write, network, subprocess, "
            f"credential or approval — with the reason, so the record can "
            f"quote a person rather than assume a method."
        )
    return classified


def _dotted_names(value: object) -> tuple[str, ...]:
    """The import paths ``value`` could be registered under.

    A closed-over class or function is evidence of itself; a closed-over
    instance is evidence of its class. Both are offered, and the caller
    keeps whichever the registry actually knows — asking the wrong
    question of the wrong kind of value produces a name nothing is
    registered under, which costs a dictionary lookup and no accuracy.
    """
    names: list[str] = []
    module = getattr(value, "__module__", None)
    qualname = getattr(value, "__qualname__", None)
    if isinstance(module, str) and isinstance(qualname, str):
        names.append(f"{module}.{qualname}")
    kind = type(value)
    names.append(f"{kind.__module__}.{kind.__qualname__}")
    return tuple(names)


def _bound_components(endpoint: Any, index: Mapping[str, str]) -> tuple[str, ...]:
    """The registered components an endpoint reaches, as sorted ids.

    Derived, not mapped by hand: every route of this application is a
    closure built inside ``create_app``, and what it closed over is what
    it is implemented by. A route that holds the self-model interface
    is implemented by the self-model interface, and asking the function
    object says so without anyone maintaining a table that can drift
    away from the code.
    """
    try:
        closure = inspect.getclosurevars(endpoint)
    except TypeError:  # pragma: no cover - every route here is a function
        return ()
    found: set[str] = set()
    for value in (*closure.nonlocals.values(), *closure.globals.values()):
        for dotted in _dotted_names(value):
            identifier = index.get(dotted)
            if identifier is not None:
                found.add(identifier)
    return tuple(sorted(found))


def _rest_drafts(
    registry: ComponentRegistry, index: Mapping[str, str]
) -> tuple[_SurfaceDraft, ...]:
    """Every route of the self-description interface, read in process.

    Only ``APIRoute`` entries are the product's surface. FastAPI's four
    documentation routes are plain Starlette routes, so excluding them
    is a type test rather than a list of paths that would rot the first
    time the web framework renamed one.

    The method decides the side-effect fact for every route but one:
    ``GET`` means read, which is HTTP's own promise and not this
    provider's inference. The exception is written down as an exception.
    """
    try:
        from fastapi.routing import APIRoute
        from s0ma.api.rest import create_app
    except ImportError as error:  # pragma: no cover - exercised by hand
        raise CoreProviderError(
            "the REST surface cannot be read without core's api extra; "
            "install s0ma-core[api]. A documentation build that quietly "
            "skipped a served channel would describe a smaller product "
            "than the one that ships."
        ) from error

    app = create_app(registry)
    drafts: list[_SurfaceDraft] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        component_refs = _bound_components(route.endpoint, index)
        for method in sorted(route.methods):
            identifier = f"rest:{method}:{route.path}"
            validate_id(identifier)
            side_effects, exception = _route_effects(method, identifier)
            drafts.append(
                _SurfaceDraft(
                    id=identifier,
                    channel=_REST_CHANNEL,
                    public_name=f"{method} {route.path}",
                    intent=_summary_line(route.description or route.summary),
                    component_refs=component_refs,
                    manual_exception=exception,
                    governed_by=(),
                    side_effects=side_effects,
                    errors=(),
                )
            )
    return tuple(drafts)


# ---------------------------------------------------------------------------
# Reading (c) — core's own MCP tools
# ---------------------------------------------------------------------------


def _mcp_drafts(registry: ComponentRegistry) -> tuple[_SurfaceDraft, ...]:
    """Core's served agent surface, listed the way a client lists it.

    Three listings, in the order a client makes them: ``list_tools``,
    ``list_resources``, ``list_resource_templates``. Core serves no
    prompts, and ``list_prompts`` is asked anyway so that "none" is a
    reading rather than an assumption — a prompt appearing there without
    a record would be exactly the silent shrinkage this provider exists
    to prevent, so it is refused by name.

    These are **core's** tools and resources, not the authoring
    server's. The two servers are different products with different
    names, and the thing that keeps them apart in the data is the
    source: an id under ``mcp:tool/`` says what an agent calls, and the
    provenance says which package answers when it does. B4 deferred an
    ``availability`` field for exactly this reason — the source already
    names the package — so no record carries a second, driftable copy.

    A template keeps its braces: ``s0ma://model/docs-for/{component}``
    is addressed as it is served, which is the convention D3 settled and
    D5a's charset made spellable. Stripping them would give the template
    and a literal resource of the brace-free address the same id.

    No side-effect fact is emitted for either family. Core's tools
    declare no ``ToolAnnotations``, so there is no ``readOnlyHint`` to
    read, and a resource carries no annotation at all; a guess here
    would be indistinguishable from a declaration to every later gate.
    """
    try:
        from s0ma.api.mcp_server import create_mcp_server
    except ImportError as error:  # pragma: no cover - exercised by hand
        raise CoreProviderError(
            "core's MCP surface cannot be listed without core's mcp extra; "
            "install s0ma-core[mcp]. A documentation build that quietly "
            "skipped a served channel would describe a smaller product "
            "than the one that ships."
        ) from error

    server = create_mcp_server(registry)
    tools = asyncio.run(server.list_tools())
    resources = asyncio.run(server.list_resources())
    templates = asyncio.run(server.list_resource_templates())
    prompts = asyncio.run(server.list_prompts())
    if prompts:
        raise CoreProviderError(
            f"core's MCP server now serves {len(prompts)} prompts, which this "
            f"reading does not describe. A served family nothing emits is a "
            f"documentation build quietly smaller than the product; add the "
            f"mcp:prompt/ drafts here rather than letting the family go "
            f"unrecorded."
        )

    drafts: list[_SurfaceDraft] = []
    for tool in tools:
        identifier = f"mcp:tool/{tool.name}"
        validate_id(identifier)
        drafts.append(
            _SurfaceDraft(
                id=identifier,
                channel=_MCP_TOOL_CHANNEL,
                public_name=tool.name,
                intent=_summary_line(tool.description),
                component_refs=(),
                manual_exception=_MCP_TOOL_EXCEPTION,
                governed_by=(),
                side_effects=(),
                errors=(),
            )
        )
    served = [str(resource.uri) for resource in resources]
    served.extend(str(template.uriTemplate) for template in templates)
    described = [resource.description for resource in resources]
    described.extend(template.description for template in templates)
    for address, description in zip(served, described, strict=True):
        identifier = f"mcp:resource/{address}"
        validate_id(identifier)
        drafts.append(
            _SurfaceDraft(
                id=identifier,
                channel=_MCP_RESOURCE_CHANNEL,
                public_name=address,
                intent=_summary_line(description),
                component_refs=(),
                manual_exception=_MCP_RESOURCE_EXCEPTION,
                governed_by=(),
                side_effects=(),
                errors=(),
            )
        )
    return tuple(drafts)


# ---------------------------------------------------------------------------
# Reading (e) — core's public Python API
# ---------------------------------------------------------------------------


def _export_intent(value: object) -> str:
    """One export's summary line, quoted, or nothing.

    A routine is asked for its own docstring. Anything else is not:
    :func:`inspect.getdoc` on a string constant answers with the
    docstring of :class:`str`, and a record carrying the standard
    library's prose as core's intent would be a fabrication that reads
    like a quotation. Two of the nine exports are strings, so this is
    the live case rather than a hypothetical, and the honest answer for
    them is the empty field the honesty rules already provide for.
    """
    if not inspect.isroutine(value):
        return ""
    return _summary_line(inspect.getdoc(value))


def _export_drafts(registry: ComponentRegistry) -> tuple[_SurfaceDraft, ...]:
    """Every public export of ``s0ma`` that is not a registered component.

    Core's ``__all__`` is its own statement of what it offers. Most of
    the names on it are registered components and are addressed as
    components; the rest are module-level callables and constants, which
    the ``component:`` form cannot address and should not — a function
    that no registration knows about is not a component. D5a's
    ``python:`` form addresses them by the import path a caller writes,
    which is also the only binding they have.

    The split is derived, not listed: what makes a name a component here
    is that the bootstrap registered it, so a registration added or
    removed moves a name between the two halves without an edit.
    """
    import s0ma

    exported = getattr(s0ma, "__all__", ())
    if not exported:
        raise CoreProviderError(
            "s0ma declares no __all__, so there is no statement of what core "
            "offers to read. This provider would emit no python surfaces and "
            "say nothing about it, which is the silent shrinkage the "
            "anti-vacuity floors exist to catch — but a floor cannot see a "
            "family that was never read."
        )
    registered = {spec.name for spec in registry.get_all().values()}
    drafts: list[_SurfaceDraft] = []
    for name in sorted(exported):
        if name in registered:
            continue
        identifier = f"python:s0ma.{name}"
        validate_id(identifier)
        drafts.append(
            _SurfaceDraft(
                id=identifier,
                channel=_PYTHON_CHANNEL,
                public_name=f"s0ma.{name}",
                intent=_export_intent(getattr(s0ma, name)),
                component_refs=(),
                manual_exception=_PYTHON_EXCEPTION,
                governed_by=(),
                side_effects=(),
                errors=(),
            )
        )
    if not drafts:
        raise CoreProviderError(
            "every name in s0ma.__all__ is a registered component, so this "
            "reading produced nothing. That would be good news, and it is "
            "not what C3 found; a reading that has silently stopped seeing "
            "core's module-level API looks exactly the same from here."
        )
    return tuple(drafts)


# ---------------------------------------------------------------------------
# Reading (d) — the registry's documentation stores
# ---------------------------------------------------------------------------


def _doc_slug(name: str) -> str:
    """A registration name as the slug half of a ``doc:`` id.

    Registration names are written in the snake case a declaration uses;
    a catalog id is a lowercase hyphenated slug. The single
    transformation is underscore to hyphen, and the registration's real
    name stays visible in the row's prose locator, so nothing is lost by
    it. A name that still does not form a valid id is refused by the
    caller rather than repaired further.
    """
    return name.replace("_", "-")


def _covered_ids(
    covers: Sequence[Any], index: Mapping[str, str], registry: ComponentRegistry, where: str
) -> tuple[str, ...]:
    """One registration's covered entities, as sorted component ids.

    An entity reference names a declaration, and the registry is what
    turns a declaration into an addressable component. A reference the
    registry does not know is refused: the model addresses components
    package-qualified, a declaration's own module name is not a package
    path, and minting an id out of one would produce something that
    looks addressable and resolves to nothing.
    """
    found: set[str] = set()
    for entity in covers:
        spec = registry.get(str(entity.name))
        identifier = None
        if spec is not None:
            dotted = spec.qualified_name or f"{spec.module_path}.{spec.name}"
            identifier = index.get(dotted)
        if identifier is None:
            raise CoreProviderError(
                f"{where} covers {entity.name!r}, which no registered "
                f"component answers to, so there is no id to point at. Either "
                f"the declaration it names is not registered, or the "
                f"registration and the reference disagree about its name."
            )
        found.add(identifier)
    return tuple(sorted(found))


def _document_drafts(
    snapshot: RegistrySnapshot, index: Mapping[str, str], registry: ComponentRegistry
) -> tuple[_DocumentDraft, ...]:
    """Registered doc-refs and doc-guides as catalog rows.

    A registered documentation declaration *is* a catalog row: it has a
    title its author wrote, a destination it is rendered to, a place its
    words actually live, and — for a guide — the entities it covers.
    ``prose_locator`` is the field that matters here: a guide's words
    are a declaration body inside a ``.s0ma`` source, not the generated
    file the row's canonical source names, and a finding about the prose
    has to point at the line an author may edit.

    Core's own bootstrap registers no documentation, so this reading is
    empty for the provider's default registry. That is a fact about
    core, not a hole in this provider: the stores are filled by the
    generated modules a project imports, and the reading is here so that
    a registry which has them is described rather than silently halved.
    """
    drafts: list[_DocumentDraft] = []
    for name in sorted(snapshot.doc_refs):
        reference: DocRefRegistration = snapshot.doc_refs[name]
        drafts.append(
            _DocumentDraft(
                id=_doc_id("generated", name),
                title=reference.intent,
                canonical_source=reference.output,
                prose_locator=_prose_locator(reference, "doc-ref", name),
                governed_by=(),
                # A doc-ref selects its subjects with filter expressions
                # rather than by naming them, and a filter is not a set
                # of ids until it is run against a registry. Resolving
                # it here would make the row's coverage a function of
                # this provider's registry rather than of the
                # declaration, so the row states what it can prove.
                covers=(),
            )
        )
    for name in sorted(snapshot.doc_guides):
        guide: DocGuideRegistration = snapshot.doc_guides[name]
        drafts.append(
            _DocumentDraft(
                id=_doc_id("guide", name),
                title=guide.intent,
                canonical_source=guide.output,
                prose_locator=_prose_locator(guide, "doc-guide", name),
                governed_by=(),
                covers=_covered_ids(guide.covers, index, registry, f"doc-guide {name!r}"),
            )
        )
    seen: set[str] = set()
    for draft in drafts:
        if draft.id in seen:
            raise CoreProviderError(
                f"two documentation registrations produce the catalog id "
                f"{draft.id!r}. Names differing only in an underscore or a "
                f"hyphen collide once they are slugged; rename one."
            )
        seen.add(draft.id)
    return tuple(drafts)


def _doc_id(category: str, name: str) -> str:
    """The catalog id of a registered documentation declaration."""
    identifier = f"doc:{category}/{_doc_slug(name)}"
    validate_id(identifier)
    return identifier


def _prose_locator(registration: Any, kind: str, name: str) -> str:
    """Where a registration's words are, as far as the registration knows.

    ``<path>#<kind>:<name>`` where the declaration recorded its source
    span, and the rendered destination otherwise. An absolute span is
    refused: a machine path in a record is the one thing the determinism
    invariant forbids outright, and a record that carried one would
    serialize differently on every checkout.
    """
    span = registration.source_span
    if span is None:
        output: str = registration.output
        return output
    file: str = span.file
    if file.startswith("/") or file.startswith("\\") or (len(file) > 1 and file[1] == ":"):
        raise CoreProviderError(
            f"the {kind} {name!r} records the absolute source path {file!r}. A "
            f"record may not carry a machine path — the same build would "
            f"serialize differently on another checkout — so the registration "
            f"has to name its source relative to the project."
        )
    return f"{file}#{kind}:{name}"


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


class CoreProvider:
    """One deterministic reading of ``s0ma-core``.

    Everything is read when the provider is built, and :meth:`provide`
    hands over what was read. That is what the contract means by "reads
    nothing at call time": calling it twice in one process returns the
    same records because it returns the same object, so the
    composition's determinism rests on nothing more than that.

    A registry may be supplied, which is how a caller describes a
    process that has imported generated modules — the documentation and
    example stores are empty in a bootstrap-only registry, and a
    provider that could only ever see an empty store could not be shown
    to read a full one. When no registry is supplied this provider
    builds its own and holds it to core's own pin: exactly
    ``EXPECTED_FRAMEWORK_COMPONENT_COUNT`` components, because a
    bootstrap that registered half of itself is the failure an
    anti-vacuity floor cannot see (the inventory is not a bundle group)
    and every later ``component:`` reference would resolve to nothing.
    """

    def __init__(self, registry: ComponentRegistry | None = None) -> None:
        owned = registry is None
        live = ComponentRegistry(persist=False) if registry is None else registry
        if owned:
            bootstrap_register(live)

        index = _component_index(live)
        if owned and len(index) != EXPECTED_FRAMEWORK_COMPONENT_COUNT:
            raise CoreProviderError(
                f"core's bootstrap registered {len(index)} components and its "
                f"own EXPECTED_FRAMEWORK_COMPONENT_COUNT says "
                f"{EXPECTED_FRAMEWORK_COMPONENT_COUNT}. Either the bootstrap "
                f"has stopped registering part of the framework or the pin is "
                f"stale; every component: reference in the build resolves "
                f"against this inventory, so it cannot be taken on trust."
            )

        snapshot = live.snapshot()
        exports = _export_drafts(live)
        rest = _rest_drafts(live, index)
        mcp = _mcp_drafts(live)
        documents = _document_drafts(snapshot, index, live)

        records: list[SourcedRecord] = []
        for source, drafts in (
            (EXPORTS_SOURCE, exports),
            (REST_SOURCE, rest),
            (MCP_SOURCE, mcp),
        ):
            provenance = _provenance(source, _surface_digest(drafts))
            records.extend(SourcedRecord.of(draft.record(provenance)) for draft in drafts)
        stores = _provenance(STORES_SOURCE, _surface_digest(documents))
        records.extend(SourcedRecord(draft.record(), stores) for draft in documents)

        self._component_ids = tuple(sorted(index.values()))
        self._example_ids = _example_ids(snapshot)
        self._result = ProviderResult(
            provider_id=PROVIDER_ID,
            records=sort_records(records),
        )

    @property
    def provider_id(self) -> str:
        """This adapter's stable id, unique across the registry."""
        return PROVIDER_ID

    def provide(self) -> ProviderResult:
        """The records read at construction, sorted, stamped, unchanged."""
        return self._result

    def component_ids(self) -> tuple[str, ...]:
        """Every component core registers, sorted.

        The resolution universe for ``component:`` references. It is not
        a bundle group — architecture plan §6 gives a registered
        component no record type — so it reaches a build through
        :func:`~s0ma_dsl.docs_model.validate.ReferenceIndex`'s
        ``external_ids``, which is the seam C2 built for exactly this.
        """
        return self._component_ids

    def example_ids(self) -> tuple[str, ...]:
        """Every registered runnable example, sorted, same seam."""
        return self._example_ids

    def external_ids(self) -> tuple[str, ...]:
        """Everything this provider vouches for but does not hold.

        Hand this to ``ReferenceIndex`` or ``validate_bundle``: the two
        classes of id the model addresses and does not carry are exactly
        components and examples, and this provider knows core's.
        """
        return tuple(sorted((*self._component_ids, *self._example_ids)))
