"""Four generated references: the MCP servers, studi0, the packages, the components.

Milestone F4 of the docs-function plan (internal) §11. D6 rendered two
indexes that answer "what is there" across every family at once. This
module renders the four pages that answer "what is there *here*" — inside
one server, one viewer, one distribution, one registry — which is the
question a reader actually arrives with, and the question a single index
of two hundred and forty-two rows answers for nobody.

**Why one module for four pages.** They are one rendering over one
reading. Every fact on all four comes from the composed bundle (surfaces,
authorities, documents) plus D6's component facts, and the four share the
table idiom, the link rule, the anchor rule and the counting rule. Split
across four modules, the shared half would either be copied — and two
renderers that escape a table cell differently disagree about one tool's
description on two committed pages — or would need a fifth module holding
nothing but the shared half.

**How the two MCP servers are told apart.** By
``SurfaceRecord.provenance.adapter_id``, which is the fact that is really
true of the record: :data:`AUTHORING_ADAPTER` read the authoring server's
served listing and :data:`RUNTIME_ADAPTER` read the runtime's own. Not by
the id, and not by a list of names written here — a name list would be a
third account of a surface set that already has three, and the day core
grows a tool it would file it under the wrong server silently. A record
stamped by neither adapter is rendered under its own adapter's heading
rather than dropped, for the reason
:func:`~s0ma_dsl.docs_model.inventories._channel_order` renders a channel
it has never heard of: a page that quietly omitted a family of served
capabilities is the failure ``DOC_SURFACE_UNCOVERED`` exists to catch, and
building the omission into the renderer would make the gate a test of
itself.

**Parity with the README generator, and what it means.**
``scripts/generate_mcp_readme_surfaces.py`` renders the same authoring
surface into the root and ``packages/s0ma-mcp`` READMEs from
``packages/s0ma-mcp/tests/snapshots/mcp_surface.json``. That snapshot is
one of the three accounts
:class:`~s0ma_dsl.docs_model.providers_mcp.McpProvider` cross-checks
before it emits a record, so the two renderings cannot describe different
surfaces without the provider having refused the build first. This module
therefore does not read the snapshot at all — reading it would be a second
opinion about a fact that already has a settled one — and
``test_docs_reference_surfaces.py`` asserts the agreement from outside
instead: same names, same URIs, same read/write facts.

**The approval column is a declared fact, not a judgement.** ``approval``
is one of the seven side-effect words a surface may declare, and two
authoring tools declare it. A surface that declares effects and does not
declare ``approval`` reads ``no``; a surface that declares no effects at
all reads ``not declared``, because "nobody wrote down what this touches"
and "this touches nothing" are different answers and only one of them is
true of core's server today.

**The license reading.** ``PackageFacts`` carries a distribution's version
and its in-workspace dependencies and nothing else, so the license and the
one-line description are read here — off the *same file each row already
names*, never off a second walk of ``packages/``. That is the whole of
:func:`distribution_facts`: the shared reading for the facts that already
have one, plus two more keys of the ``[project]`` table for the facts that
do not. Version and direction therefore cannot drift between this page and
the composed graph, which is what
:func:`~s0ma_dsl.docs_model.providers_repo.package_facts` was made single
for.

**Determinism.** No clock, no network, no machine path. Every collection is
sorted before it is rendered, every count is computed from the records
rather than written down, every link is repository-relative POSIX resolved
against the page's own place under the documentation root, and every
authored heading is slugged by :func:`~s0ma_dsl.docs_model.map_of_record.anchor`
so a contents entry and its heading cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.inventories import GENERATED_NOTE, cell, list_cell
from s0ma_dsl.docs_model.map_of_record import anchor
from s0ma_dsl.docs_model.providers_repo import facts_of, package_facts
from s0ma_dsl.docs_model.records import DocsModelError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from s0ma_dsl.docs_model.inventories import ComponentFact
    from s0ma_dsl.docs_model.providers_mcp import MirrorDocument
    from s0ma_dsl.docs_model.records import AuthorityRef, DocsBundle, SurfaceRecord

__all__ = [
    "APPROVAL",
    "AUTHORING_ADAPTER",
    "COMPONENT_INDEX_TITLE",
    "CONTRACT_PREFIX",
    "KIND_WORDS",
    "LAYER_WORDS",
    "MCP_CHANNELS",
    "MCP_TITLE",
    "PACKAGES_TITLE",
    "RUNTIME_ADAPTER",
    "SERVERS",
    "STUDI0_CHANNEL",
    "STUDI0_CONTRACTS",
    "STUDI0_TITLE",
    "VISIBILITY_ABSENT",
    "Contract",
    "DistributionFact",
    "DocsReferenceError",
    "Server",
    "approval_of",
    "component_index",
    "contracts_of",
    "distribution_facts",
    "mcp_reference",
    "packages_reference",
    "reaches_code",
    "studi0_reference",
]


class DocsReferenceError(DocsModelError):
    """A reference page cannot be rendered from what it was handed.

    Raised rather than reported, and always for the same shape of reason:
    a page whose subject is missing would render as a heading with an
    empty table under it, and an empty table is indistinguishable from a
    product that stopped serving something. The build stops instead, for
    the reason :func:`~s0ma_dsl.docs_model.inventories.component_facts`
    refuses a component no reading can describe.
    """


# ---------------------------------------------------------------------------
# Shared rendering
# ---------------------------------------------------------------------------


def _link(target: str, *, page: str, docs_root: str) -> str:
    """``target`` as a link from the page at ``page`` inside ``docs_root``.

    ``page`` is the artifact's own path relative to the documentation root,
    so a page that moves one directory deeper gets correct links without
    this function being told where it went. Repository-relative POSIX in,
    repository-relative POSIX out: :func:`posixpath.relpath` is string
    arithmetic and touches no filesystem, so no machine path can reach a
    rendered link (INV-5) and the same link is produced on every platform.
    """
    from posixpath import dirname, relpath

    return relpath(target, dirname(f"{docs_root}/{page}"))


def _tally(values: Iterable[str]) -> dict[str, int]:
    """How many times each value occurs, keyed by the value."""
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _contents(titles: Sequence[str]) -> list[str]:
    """The page's contents list, slugged the way its headings are."""
    return [
        "## Contents",
        "",
        *[f"- [{title}](#{anchor(title)})" for title in titles],
        "",
    ]


def _page(lines: Sequence[str]) -> str:
    """One page's lines as its final bytes: LF-joined, one trailing newline.

    The same single opinion about the trailing byte the other renderers
    have, in one place, because four pages with four opinions is four
    chances for one of them to grow a blank line the drift gate reports
    and nobody can explain.
    """
    return "\n".join(lines).rstrip("\n") + "\n"


def reaches_code(record: SurfaceRecord) -> bool:
    """Whether this capability maps to a component the model can address.

    One fact rather than the three-word binding vocabulary D6's inventory
    renders. The vocabulary is that inventory's to define — two renderers
    with two spellings of "bound" would put two answers on two committed
    pages — and what a reference page needs is the count: how many of a
    server's capabilities a reader can follow back to real code.
    """
    return bool(record.component_refs)


#: The side-effect word that says a person is asked first.
APPROVAL = "approval"

#: What the approval column says when a surface declares no effects at
#: all. Not ``no``: "nobody wrote down what this touches" and "this
#: touches nothing" are different answers, and twenty of the surfaces on
#: the MCP page are honestly the first.
APPROVAL_UNDECLARED = "not declared"


def approval_of(record: SurfaceRecord) -> str:
    """Whether calling this capability asks the person first."""
    if not record.side_effects:
        return APPROVAL_UNDECLARED
    return "yes" if APPROVAL in record.side_effects else "no"


def _surface_rows(records: Sequence[SurfaceRecord]) -> list[str]:
    """One served capability per row: name, id, intent, effects, approval."""
    lines = [
        "| Name | Id | What it does | Effects | Asks you first |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| `{cell(item.public_name)}` | `{cell(item.id)}` | {cell(item.intent)} "
        f"| {list_cell(item.side_effects, absent='not declared')} "
        f"| {approval_of(item)} |"
        for item in records
    )
    lines.append("")
    return lines


def _effects_legend(*, approval_column: bool) -> list[str]:
    """What a page with an effects column owes its reader, before the table.

    The approval paragraph is written only where the column is, because a
    legend explaining a column the table does not have is the same defect
    as a column the legend does not explain.
    """
    lines = [
        "**Effects** are read from the capability itself wherever it declares "
        "them: `none`, `read`, `write`, `network`, `subprocess`, `credential`, "
        "`approval`. Where nothing declares them, the row says `not declared` "
        "rather than guessing — that is an answer about the capability's own "
        "description, not about what it does.",
        "",
    ]
    if approval_column:
        lines += [
            "**Asks you first** is `yes` where the capability declares the "
            "`approval` effect, which means it stops and waits for your "
            "decision before the irreversible part happens. `not declared` "
            "means the same thing the effects column means by it: nobody has "
            "written down what calling it touches.",
            "",
        ]
    return lines


# ---------------------------------------------------------------------------
# The MCP page
# ---------------------------------------------------------------------------

#: The adapter that read the authoring server's served listing, and the
#: one that read the runtime's own. These are ``Provenance.adapter_id``
#: values, which is the fact that is true of a record rather than a
#: property of its name.
AUTHORING_ADAPTER = "mcp"
RUNTIME_ADAPTER = "core"

#: The three MCP channels, in the order the sections appear, with the
#: heading each gets. The order is the order an agent meets them: a tool
#: is what it calls, a resource is what it reads, a prompt is where it
#: starts.
MCP_CHANNELS: tuple[tuple[str, str], ...] = (
    ("mcp_tool", "Tools"),
    ("mcp_resource", "Resources"),
    ("mcp_prompt", "Prompts"),
)

MCP_TITLE = "The MCP servers"


@dataclass(frozen=True)
class Server:
    """One MCP server: which adapter read it, and what it is for.

    ``adapter`` is the ``Provenance.adapter_id`` its records carry;
    ``distribution`` is the wheel that ships it, so a reader who has only
    one of the four knows which half of this page applies to them. It is
    empty for a server nobody has described here — an adapter id is not a
    distribution name, and rendering one as the other would put a wheel
    on the page that nothing ships.
    """

    adapter: str
    title: str
    distribution: str
    blurb: str


#: The two servers this repository ships, in the order a reader meets
#: them. A server whose adapter is absent here is still rendered — see the
#: module docstring — under a heading made from its adapter id.
SERVERS: tuple[Server, ...] = (
    Server(
        adapter=AUTHORING_ADAPTER,
        title="The authoring server",
        distribution="s0ma-mcp",
        blurb=(
            "What a coding agent talks to while it writes s0ma. It scaffolds "
            "modules, runs the check-and-build loop, reads the language "
            "guides, and reports what a project currently looks like. This is "
            "the server the getting-started journey configures, and every "
            "capability below is served by the s0ma-mcp wheel."
        ),
    ),
    Server(
        adapter=RUNTIME_ADAPTER,
        title="The runtime's own server",
        distribution="s0ma-core",
        blurb=(
            "What an application built with s0ma serves about itself. It "
            "answers questions from the running self-model — what the system "
            "contains, what depends on what, what would be affected by a "
            "change — and it ships in the runtime wheel, so an application "
            "can offer it without the authoring toolchain being installed."
        ),
    ),
)


def _by_adapter(bundle: DocsBundle) -> dict[str, list[SurfaceRecord]]:
    """Every MCP surface this build composed, grouped by the adapter that read it."""
    grouped: dict[str, list[SurfaceRecord]] = {}
    channels = {channel for channel, _ in MCP_CHANNELS}
    for record in bundle.surfaces:
        if record.channel in channels:
            grouped.setdefault(record.provenance.adapter_id, []).append(record)
    return grouped


def _server_order(present: Iterable[str]) -> list[Server]:
    """The servers to render: the declared ones present, then any others.

    An adapter this module has never heard of is described by its own id
    rather than left off, and the sentence under it says plainly that
    nobody has written what it is for. That is worse-looking and more
    honest than a page that silently documents one server fewer than the
    product serves.
    """
    seen = set(present)
    known = [item for item in SERVERS if item.adapter in seen]
    extra = sorted(seen - {item.adapter for item in SERVERS})
    return known + [
        Server(
            adapter=adapter,
            title=f"Served by the {adapter} reading",
            distribution="",
            blurb=(
                "Nothing on this page says what this server is for, or "
                "which wheel ships it. Its capabilities are listed because "
                "they are served; the sentence that introduces them has to "
                "be written where the other servers' sentences are."
            ),
        )
        for adapter in extra
    ]


def _mirror_table(
    mirrors: Sequence[MirrorDocument], *, page: str, docs_root: str
) -> list[str]:
    """Which served resources are packaged copies of which documents."""
    lines = ["| Served as | The copy that ships | The original |", "| --- | --- | --- |"]
    lines.extend(
        f"| `{cell(item.resource)}` "
        f"| [`{cell(item.mirror)}`]({_link(item.mirror, page=page, docs_root=docs_root)}) "
        f"| [`{cell(item.canonical)}`]"
        f"({_link(item.canonical, page=page, docs_root=docs_root)}) |"
        for item in sorted(mirrors, key=lambda item: item.resource)
    )
    lines.append("")
    return lines


def mcp_reference(
    bundle: DocsBundle,
    *,
    mirrors: Sequence[MirrorDocument],
    page: str,
    docs_root: str,
) -> str:
    """Everything either MCP server serves, sectioned by server and by kind.

    ``mirrors`` is the authoring server's resource-to-document
    correspondence, handed over by
    :meth:`~s0ma_dsl.docs_model.providers_mcp.McpProvider.mirrored_documents`
    rather than re-derived here: which packaged file answers which URI is
    a fact of that reading, and a renderer that inferred it from a
    filename would be a second account of it.

    Raises:
        DocsReferenceError: when this build composed no MCP surface at
            all, or when the mirrors name a resource no section of the
            page lists. Both are pages that would render as headings over
            empty tables, which reads exactly like a product that has
            stopped serving something.
    """
    grouped = _by_adapter(bundle)
    total = sum(len(items) for items in grouped.values())
    if not total:
        raise DocsReferenceError(
            "this build composed no MCP surface at all, so the MCP reference "
            "would be a page of empty tables. Either the MCP providers did "
            "not run or they have stopped producing; check the provider "
            "before the page."
        )

    served = {record.id for items in grouped.values() for record in items}
    unknown = sorted({item.resource for item in mirrors} - served)
    if unknown:
        raise DocsReferenceError(
            f"{', '.join(unknown)} is named as a packaged copy of a document "
            f"and is not a resource this build composed. A mirror row for a "
            f"resource the page does not list points a reader at a URI "
            f"nothing serves."
        )

    servers = _server_order(grouped)
    mirror_title = "Documents the authoring server ships"
    titles = [item.title for item in servers] + [mirror_title]
    inventory = f"{docs_root}/_generated/inventory-surfaces.json"
    to_index = _link(
        f"{docs_root}/reference/surfaces-index.md", page=page, docs_root=docs_root
    )
    to_inventory = _link(inventory, page=page, docs_root=docs_root)

    lines = [
        f"# {MCP_TITLE}",
        "",
        GENERATED_NOTE,
        "",
        f"s0ma serves {total} capabilities over the Model Context Protocol, "
        f"across {len(servers)} servers that do different jobs. Each section "
        f"below says which wheel ships the one it describes. Every row is "
        f"read from a running server's own listing when this page is built, "
        f"so it is what the server really answers rather than what somebody "
        f"remembered it answering.",
        "",
        f"The complete list of everything s0ma serves — every channel, not "
        f"just this one — is in [what s0ma can do]({to_index}), and the same "
        f"rows in a form a program can read are in "
        f"[`{inventory}`]({to_inventory}).",
        "",
        *_contents(titles),
        "## How to read the tables",
        "",
        "**Name** is what a client calls the capability: a tool's name, a "
        "resource's URI, a prompt's name. **Id** is what this documentation "
        "addresses it by, and it is the stable one — the name is the "
        "product's, the id is the model's, and a link to a capability uses "
        "the id.",
        "",
        *_effects_legend(approval_column=True),
    ]

    for server in servers:
        held = sorted(grouped[server.adapter], key=lambda item: item.id)
        by_channel = {
            channel: [item for item in held if item.channel == channel]
            for channel, _ in MCP_CHANNELS
        }
        bound = sum(1 for item in held if reaches_code(item))
        lines.append(f"## {server.title}")
        lines.append("")
        lines.append(server.blurb)
        lines.append("")
        if bound == len(held):
            binding = (
                "Every one of them reaches a registered component, so a "
                "reader can follow any row back to the code that answers it."
            )
        elif bound:
            binding = (
                f"{bound} of them reach a registered component, so a reader "
                f"can follow the row back to the code that answers it; the "
                f"other {len(held) - bound} carry a written reason instead."
            )
        else:
            binding = (
                "None of them reaches a registered component: the protocol's "
                "public listing gives a capability its name, its description "
                "and its schema, and not the callable behind it. Each carries "
                "a written reason saying so."
            )
        shipped = (
            f", shipped in `{cell(server.distribution)}`"
            if server.distribution
            else ""
        )
        lines.append(f"{len(held)} of the {total} capabilities{shipped}. {binding}")
        lines.append("")
        for channel, heading in MCP_CHANNELS:
            records = by_channel[channel]
            if not records:
                continue
            lines.append(f"### {heading}")
            lines.append("")
            lines.append(f"{len(records)} of this server's {len(held)}.")
            lines.append("")
            lines.extend(_surface_rows(records))

    lines.append(f"## {mirror_title}")
    lines.append("")
    lines.append(
        f"The authoring server answers {len(mirrors)} of its resources out of "
        f"documents packaged inside its wheel, so an agent that installed "
        f"s0ma has them without a checkout. Read the original: the copy is "
        f"compared to it byte for byte at every build, and an edit made to "
        f"the copy is lost at the next one."
    )
    lines.append("")
    lines.extend(_mirror_table(mirrors, page=page, docs_root=docs_root))
    return _page(lines)


# ---------------------------------------------------------------------------
# The studi0 page
# ---------------------------------------------------------------------------

#: The channel studi0's routes are served on (architecture §6.3).
STUDI0_CHANNEL = "studi0"

#: The id prefix every contract studi0 declares is addressed by. The
#: contracts are authority records rather than surfaces because they are
#: what the routes are *held to*, not something a client calls.
CONTRACT_PREFIX = "authority:declared/studi0."

STUDI0_TITLE = "studi0, the viewer"


@dataclass(frozen=True)
class Contract:
    """One promise studi0's build makes, and what it is a promise about.

    ``key`` is the tail of the authority id, ``title`` is the heading a
    reader sees, and ``blurb`` says what the contract is for in the words
    of somebody who has to decide whether to care about it. The facts
    themselves are never written here: they are read off the authority
    record's own status line, which the studi0 provider composed from the
    built source.
    """

    key: str
    title: str
    blurb: str


#: The six contracts studi0's build declares, in the order they matter to
#: somebody reading the page top to bottom: what it serves, what it
#: promises the two API routes will look like, what it does while it
#: watches, and what it writes. A contract absent from this tuple is
#: rendered after these under its own id rather than dropped.
STUDI0_CONTRACTS: tuple[Contract, ...] = (
    Contract(
        key="serving-contract",
        title="What the server will and will not do",
        blurb=(
            "The shape of the server itself: where it listens, which method "
            "it answers, how many routes it has, and what a request for "
            "anything else gets back. It listens on the loopback address "
            "only, which is the whole of its security model — studi0 shows "
            "you your own project on your own machine and is not something "
            "to put on a network."
        ),
    ),
    Contract(
        key="wire-graph",
        title="The graph document",
        blurb=(
            "What `/api/graph` answers with. The schema name is versioned "
            "and carried in the document itself, so a viewer that was "
            "written against an older one can say so instead of drawing the "
            "wrong picture."
        ),
    ),
    Contract(
        key="wire-state",
        title="The state document",
        blurb=(
            "What `/api/state` answers with. This is the cheap poll: it says "
            "which reading you are looking at and whether anything has moved "
            "since, so the expensive graph is fetched only when the sequence "
            "number says it is worth fetching."
        ),
    ),
    Contract(
        key="watch-contract",
        title="Watching the build",
        blurb=(
            "How studi0 notices that what you are looking at has gone stale. "
            "It reads build artifacts on a timer and it never raises: a "
            "viewer that crashed because a file was half-written would be a "
            "worse tool than one that says the picture is old."
        ),
    ),
    Contract(
        key="narration-event",
        title="What an agent says it is doing",
        blurb=(
            "The one thing studi0 shows that does not come from the build: a "
            "line an agent writes to say which phase of the work it is in. "
            "Anything that does not fit the declared shape is counted and "
            "never drawn, so a malformed line cannot put text of its own "
            "choosing on your screen."
        ),
    ),
    Contract(
        key="presence-marker",
        title="The one file studi0 writes",
        blurb=(
            "studi0 reads your project and does not change it, with exactly "
            "one exception, named here: a marker saying a viewer is "
            "currently bound to this project. It is written when the viewer "
            "binds and removed when it exits."
        ),
    ),
)


def contracts_of(bundle: DocsBundle) -> tuple[AuthorityRef, ...]:
    """Every contract studi0's build declares, sorted by id."""
    return tuple(
        sorted(
            (item for item in bundle.authorities if item.id.startswith(CONTRACT_PREFIX)),
            key=lambda item: item.id,
        )
    )


def _contract_order(present: Sequence[AuthorityRef]) -> list[tuple[Contract, AuthorityRef]]:
    """The declared contracts in this module's order, then any others.

    A contract this module has no sentence for is rendered under its own
    key rather than left off, and its sentence says so. The alternative —
    dropping it — is a page that describes fewer promises than the build
    makes, which is the one thing a contract page must never do.
    """
    by_key = {item.id.removeprefix(CONTRACT_PREFIX): item for item in present}
    ordered = [
        (contract, by_key[contract.key])
        for contract in STUDI0_CONTRACTS
        if contract.key in by_key
    ]
    named = {contract.key for contract in STUDI0_CONTRACTS}
    ordered.extend(
        (
            Contract(
                key=key,
                title=f"The {key.replace('-', ' ')} contract",
                blurb=(
                    "Nothing on this page says what this contract is for. "
                    "Its facts are listed because the build declares them; "
                    "the sentence that introduces them has to be written "
                    "where the other contracts' sentences are."
                ),
            ),
            by_key[key],
        )
        for key in sorted(set(by_key) - named)
    )
    return ordered


def _fact_table(record: AuthorityRef) -> list[str]:
    """One contract's declared facts, as they were read from its source."""
    facts = facts_of(record.status)
    if not facts:
        return [
            "This contract declares no facts in this build, which is either a "
            "contract that has stopped being read or a status line that has "
            "stopped carrying its facts. The studi0 provider is where to "
            "look.",
            "",
        ]
    lines = ["| Fact | Value |", "| --- | --- |"]
    lines.extend(
        f"| `{cell(key)}` | `{cell(facts[key])}` |" for key in sorted(facts)
    )
    lines.append("")
    return lines


def studi0_reference(
    bundle: DocsBundle,
    *,
    page: str,
    docs_root: str,
) -> str:
    """studi0's routes and the contracts its build declares, on one page.

    Raises:
        DocsReferenceError: when this build composed no studi0 route or no
            studi0 contract. Either one alone would render as a heading
            over an empty table, and a viewer reference with no routes in
            it describes a product that does not exist.
    """
    routes = sorted(
        (item for item in bundle.surfaces if item.channel == STUDI0_CHANNEL),
        key=lambda item: item.id,
    )
    contracts = _contract_order(contracts_of(bundle))
    if not routes or not contracts:
        raise DocsReferenceError(
            f"this build composed {len(routes)} studi0 routes and "
            f"{len(contracts)} studi0 contracts, and the page needs both: a "
            f"viewer reference with an empty table under a heading reads "
            f"exactly like a viewer that stopped serving. Check the studi0 "
            f"provider before the page."
        )

    serving = next(
        (record for contract, record in contracts if contract.key == "serving-contract"),
        None,
    )
    serving_facts = facts_of(serving.status) if serving is not None else {}
    routes_title = "The routes it answers"
    contracts_title = "The contracts its build declares"
    titles = [routes_title, contracts_title] + [
        contract.title for contract, _ in contracts
    ]

    lines = [
        f"# {STUDI0_TITLE}",
        "",
        GENERATED_NOTE,
        "",
        f"studi0 shows you the project you just built: every component it "
        f"contains, how they are wired, and whether what you are looking at "
        f"is still current. It answers {len(routes)} routes and its build "
        f"declares {len(contracts)} contracts — promises about what it "
        f"serves, what those answers look like, and what it touches on your "
        f"machine.",
        "",
        "Every fact on this page is read from studi0's own built source when "
        "the documentation is built, so it describes the viewer that ships "
        "rather than the one somebody meant to ship.",
        "",
        *_contents(titles),
        f"## {routes_title}",
        "",
    ]

    method = serving_facts.get("methods", "")
    host = serving_facts.get("host", "")
    unserved = serving_facts.get("unserved", "")
    data = sum(1 for item in routes if item.public_name.startswith("/api/"))
    opening = (
        f"{len(routes)} routes, and nothing else is served. {data} of them "
        f"answer with the data the page draws itself from; the other "
        f"{len(routes) - data} are the page."
    )
    if host:
        opening += f" The server listens on `{cell(host)}` and nowhere else."
    if unserved:
        opening += f" Anything not listed here answers `{cell(unserved)}`."
    lines.append(opening)
    lines.append("")
    lines.extend(_effects_legend(approval_column=False))
    lines.append(
        "| Route | Id | Method | What it is for | Effects | Reports |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- |")
    lines.extend(
        f"| `{cell(item.public_name)}` | `{cell(item.id)}` "
        f"| {f'`{cell(method)}`' if method else 'not declared'} "
        f"| {cell(item.intent)} "
        f"| {list_cell(item.side_effects, absent='not declared')} "
        f"| {list_cell(item.errors, absent='—')} |"
        for item in routes
    )
    lines.append("")

    lines.append(f"## {contracts_title}")
    lines.append("")
    lines.append(
        f"A contract is a promise the build makes and this documentation "
        f"reads back: each one names the file it is declared in and the "
        f"declaration inside it, so the promise and the code that keeps it "
        f"are never two separate things to maintain. {len(contracts)} of "
        f"them."
    )
    lines.append("")
    for contract, record in contracts:
        lines.append(f"### {contract.title}")
        lines.append("")
        lines.append(contract.blurb)
        lines.append("")
        lines.append(
            f"Id `{cell(record.id)}`, declared as `{cell(record.section)}` in "
            f"[`{cell(record.source)}`]"
            f"({_link(record.source, page=page, docs_root=docs_root)})."
        )
        lines.append("")
        lines.extend(_fact_table(record))
    return _page(lines)


# ---------------------------------------------------------------------------
# The packages page
# ---------------------------------------------------------------------------

#: No count in the title, deliberately. There are four distributions
#: today and every number on the page below is computed from what was
#: read; a heading that spelled the count out would be the one line on a
#: generated page that could go stale without anything noticing.
PACKAGES_TITLE = "The distributions s0ma ships"

#: What a license identifier means for somebody deciding whether they may
#: use a wheel. A license absent from this mapping renders under its own
#: identifier with no sentence, which is the honest answer: the identifier
#: is the fact, and inventing a summary of a license nobody has read here
#: would be worse than saying nothing.
LICENSE_WORDS: Mapping[str, str] = {
    "Apache-2.0": (
        "an open license: you may use, change and redistribute it, "
        "including commercially, on the terms in the license file"
    ),
    "LicenseRef-Proprietary": (
        "not an open license: what you may do with it is what the license "
        "file beside it says, and nothing is implied beyond that"
    ),
}


@dataclass(frozen=True)
class DistributionFact:
    """One distribution: what ships it, what it says it is, and on what terms.

    ``version``, ``depends_on`` and ``source`` are
    :class:`~s0ma_dsl.docs_model.providers_repo.PackageFacts` unchanged —
    the shared reading, so a version here cannot differ from the version in
    the composed graph. ``description`` and ``license`` are two more keys
    of the same ``[project]`` table, read off the file ``source`` already
    names.
    """

    distribution: str
    version: str
    license: str
    license_files: tuple[str, ...]
    description: str
    depends_on: tuple[str, ...]
    source: str


def distribution_facts(root: Path) -> tuple[DistributionFact, ...]:
    """Every distribution this workspace ships, with its license.

    :func:`~s0ma_dsl.docs_model.providers_repo.package_facts` is the
    reading — it walks ``packages/`` once and it is the same call the
    repository provider's authority records and D6's
    ``package_inventory`` derived source make — and this adds the two
    ``[project]`` keys that reading has no field for. The files opened are
    exactly the ones ``package_facts`` already named, so this is a second
    *fact*, never a second walk and never a second answer about a fact
    that already has one.

    Raises:
        DocsReferenceError: when a distribution declares no license. A
            packages page that left the license column empty for one row
            would be the one question it exists to answer, unanswered.
    """
    import tomllib

    found: list[DistributionFact] = []
    for item in package_facts(root):
        path = root.joinpath(*item.source.split("/"))
        try:
            document = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise DocsReferenceError(
                f"{item.source} named a distribution and cannot be read back "
                f"for its license: {error}"
            ) from error
        project = document.get("project")
        project = project if isinstance(project, dict) else {}
        declared = project.get("license")
        if not isinstance(declared, str) or not declared.strip():
            raise DocsReferenceError(
                f"{item.source} declares no `license` in its [project] table, "
                f"so nothing says on what terms {item.distribution} may be "
                f"used. A packages reference with an empty license cell "
                f"answers the one question it exists for with a blank."
            )
        raw_files = project.get("license-files")
        license_files = tuple(
            sorted(entry for entry in raw_files if isinstance(entry, str))
            if isinstance(raw_files, list)
            else ()
        )
        description = project.get("description")
        found.append(
            DistributionFact(
                distribution=item.distribution,
                version=item.version,
                license=declared.strip(),
                license_files=license_files,
                description=" ".join(description.split())
                if isinstance(description, str)
                else "",
                depends_on=item.depends_on,
                source=item.source,
            )
        )
    return tuple(sorted(found, key=lambda item: item.distribution))


def _front_doors(bundle: DocsBundle) -> dict[str, str]:
    """Every package front door the catalog carries, keyed by its directory.

    Keyed by the directory rather than by the distribution name, because
    those are two different facts that happen to be spelled the same
    today: the name is the ``[project]`` table's and the directory is the
    checkout's. A distribution is matched to its front door through the
    ``pyproject.toml`` its own reading named, so a package that renamed
    itself without moving still gets the right link — and a document the
    catalog does not carry gets no link at all rather than a guessed one.
    """
    found: dict[str, str] = {}
    for record in bundle.documents:
        parts = record.canonical_source.split("/")
        if len(parts) == 3 and parts[0] == "packages" and parts[2] == "README.md":
            found[f"{parts[0]}/{parts[1]}"] = record.canonical_source
    return found


def packages_reference(
    bundle: DocsBundle,
    *,
    distributions: Sequence[DistributionFact],
    components: Sequence[ComponentFact],
    page: str,
    docs_root: str,
) -> str:
    """The distributions this workspace ships: version, license, direction, purpose.

    Raises:
        DocsReferenceError: when nothing was handed over. A packages page
            with no packages on it is a reading that stopped working, not
            a workspace that ships nothing.
    """
    ordered = sorted(distributions, key=lambda item: item.distribution)
    if not ordered:
        raise DocsReferenceError(
            "no distribution was handed to the packages reference, so the "
            "page would claim this workspace ships nothing. The reading is "
            "what to check: a checkout with no packages/ directory reads as "
            "empty by design."
        )

    doors = _front_doors(bundle)
    to_components = _link(
        f"{docs_root}/architecture/component-index.md", page=page, docs_root=docs_root
    )
    per_package = _tally(item.distribution for item in components)
    by_license = _tally(item.license for item in ordered)
    versions = sorted({item.version for item in ordered})
    overview_title = "What ships, and on what terms"
    titles = [overview_title] + [item.distribution for item in ordered]

    lockstep = (
        f"All {len(ordered)} are released together at version "
        f"`{cell(versions[0])}`, which is what lets one of them declare a "
        f"floor on another and mean it."
        if len(versions) == 1
        else (
            f"They are at {len(versions)} different versions in this "
            f"checkout — `{'`, `'.join(cell(item) for item in versions)}` — "
            f"which is worth knowing, because they are meant to be released "
            f"together."
        )
    )
    split = "; ".join(
        f"{count} under `{cell(name)}`" for name, count in sorted(by_license.items())
    )
    #: One license across every distribution reads as one sentence, several as
    #: a split. Saying "they are not all under the same license" when they are
    #: would be the one line on a generated page that contradicts the table
    #: directly beneath it.
    licensing = (
        f"They are all under the same license, `{cell(sorted(by_license)[0])}`. "
        if len(by_license) == 1
        else f"They are not all under the same license, and the split is {split}. "
    )

    lines = [
        f"# {PACKAGES_TITLE}",
        "",
        GENERATED_NOTE,
        "",
        f"s0ma is {len(ordered)} installable distributions rather than one, so "
        f"you take the parts you need: the runtime alone if you are shipping "
        f"an application, the whole toolchain if you are writing s0ma. "
        f"{lockstep}",
        "",
        f"{licensing}"
        f"Each row below names the license exactly as the distribution "
        f"declares it, and the license file that ships beside it is the "
        f"authority on what the identifier means.",
        "",
        *_contents(titles),
        f"## {overview_title}",
        "",
        "**Depends on** lists only the other distributions in this "
        "workspace. Third-party requirements are facts about a build "
        "environment; what this column shows is the direction s0ma is "
        "allowed to point in, and it points one way.",
        "",
        "The sentence quoted under each name below is the distribution's "
        "own, taken from the packaging metadata every install reads, so it "
        "is what the wheel says about itself rather than a second "
        "description kept somewhere else.",
        "",
        "| Distribution | Version | License | Depends on | Components |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| `{cell(item.distribution)}` | `{cell(item.version)}` "
        f"| `{cell(item.license)}` "
        f"| {list_cell([f'`{name}`' for name in item.depends_on], absent='nothing')} "
        f"| {per_package.get(item.distribution, 0)} |"
        for item in ordered
    )
    lines.append("")

    for item in ordered:
        lines.append(f"## {item.distribution}")
        lines.append("")
        lines.append(
            f"> {item.description}"
            if item.description
            else "This distribution's packaging metadata carries no "
            "description, so nothing here says in one line what it is for. "
            "The place to write one is the `[project]` table the other "
            "sentences are quoted from."
        )
        lines.append("")
        meaning = LICENSE_WORDS.get(item.license)
        license_line = f"Version `{cell(item.version)}`, licensed `{cell(item.license)}`"
        license_line += f" — {meaning}." if meaning else "."
        if item.license_files:
            names = ", ".join(f"`{cell(name)}`" for name in item.license_files)
            license_line += f" The license text ships as {names} inside the wheel."
        lines.append(license_line)
        lines.append("")
        depends = (
            "It depends on "
            + ", ".join(f"`{cell(name)}`" for name in item.depends_on)
            + ", and on nothing else in this workspace."
            if item.depends_on
            else "It depends on nothing else in this workspace — it is the "
            "bottom of the stack."
        )
        count = per_package.get(item.distribution, 0)
        lines.append(
            f"{depends} It registers {count} components, listed with what "
            f"each is for in the [component index]({to_components})."
        )
        lines.append("")
        door = doors.get(item.source.rpartition("/")[0])
        if door is not None:
            lines.append(
                f"Declared in "
                f"[`{cell(item.source)}`]"
                f"({_link(item.source, page=page, docs_root=docs_root)}); its "
                f"front door is "
                f"[`{cell(door)}`]({_link(door, page=page, docs_root=docs_root)})."
            )
        else:
            lines.append(
                f"Declared in "
                f"[`{cell(item.source)}`]"
                f"({_link(item.source, page=page, docs_root=docs_root)}). It "
                f"has no README the document catalog knows about, which is "
                f"the first thing a reader arriving at the package would "
                f"look for."
            )
        lines.append("")
    return _page(lines)


# ---------------------------------------------------------------------------
# The component index
# ---------------------------------------------------------------------------

COMPONENT_INDEX_TITLE = "Component index"

#: What the registry's kinds are called in a sentence a reader can use.
#: A kind absent here renders under its own name — the taxonomy is the
#: language's and this table is a courtesy, so a new kind arriving must
#: not be able to remove a component from the page.
KIND_WORDS: Mapping[str, str] = {
    "ADAPTER": "adapter",
    "CONFIG": "configuration",
    "CONSTANT": "constant",
    "FRAMEWORK": "framework",
    "FUNCTION": "function",
    "MODEL": "model",
    "ORCHESTRATOR": "orchestrator",
    "SERVICE": "service",
}

#: The same courtesy for layers, with the same rule about an unknown one.
LAYER_WORDS: Mapping[str, str] = {
    "APPLICATION": "application",
    "FRAMEWORK": "framework",
    "PRESENTATION": "presentation",
}

#: What a component with no declared visibility says. Absent is not
#: ``internal`` and it is not ``public``: visibility is a field of the
#: s0ma language, and a component registered from hand-written Python has
#: nowhere to put one.
VISIBILITY_ABSENT = "not declared"


def _component_rows(facts: Sequence[ComponentFact]) -> list[str]:
    """One registered component per row, sorted by id."""
    lines = [
        "| Component | Kind | Layer | Visible | What it is for |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| `{cell(item.id)}` "
        f"| {cell(KIND_WORDS.get(item.kind, item.kind))} "
        f"| {cell(LAYER_WORDS.get(item.layer, item.layer))} "
        f"| {cell(item.visibility.lower()) if item.visibility else VISIBILITY_ABSENT} "
        f"| {cell(item.intent) if item.intent else '—'} |"
        for item in sorted(facts, key=lambda item: item.id)
    )
    lines.append("")
    return lines


def component_index(
    bundle: DocsBundle,
    *,
    components: Sequence[ComponentFact],
    page: str,
    docs_root: str,
) -> str:
    """Every registered component this build can address, grouped by distribution.

    The honest successor to a hand-maintained architecture document: the
    grouping, the counts and every row are read from the same component
    facts D6's machine-readable inventory is rendered from, so the page
    cannot claim a count the registry does not have.

    ``bundle`` is here for the build it names rather than for records —
    a component is not a record and deliberately never became one (D6) —
    and the page says which snapshot it describes so a reader who found it
    out of context can tell.

    Raises:
        DocsReferenceError: when no component was handed over. An index of
            nothing passes every completeness question asked of it,
            because there is nothing to ask about.
    """
    ordered = sorted(components, key=lambda item: item.id)
    if not ordered:
        raise DocsReferenceError(
            "no component was handed to the component index, so the page "
            "would list nothing and every count taken from it would be zero. "
            "The reading is what to check."
        )

    grouped: dict[str, list[ComponentFact]] = {}
    for item in ordered:
        grouped.setdefault(item.distribution, []).append(item)
    distributions = sorted(grouped)
    by_layer = _tally(item.layer for item in ordered)
    by_kind = _tally(item.kind for item in ordered)
    public = sum(1 for item in ordered if item.visibility == "PUBLIC")
    undeclared = sum(1 for item in ordered if not item.visibility)

    layers = ", ".join(
        f"{count} {cell(LAYER_WORDS.get(name, name))}"
        for name, count in sorted(by_layer.items(), key=lambda pair: (-pair[1], pair[0]))
    )
    inventory = f"{docs_root}/_generated/inventory-components.json"
    to_inventory = _link(inventory, page=page, docs_root=docs_root)
    to_packages = _link(
        f"{docs_root}/reference/packages.md", page=page, docs_root=docs_root
    )

    lines = [
        f"# {COMPONENT_INDEX_TITLE}",
        "",
        GENERATED_NOTE,
        "",
        f"Every component s0ma registers about itself: {len(ordered)} of "
        f"them, across {len(distributions)} distributions and "
        f"{len(by_kind)} kinds. This is the inventory the framework holds "
        f"about its own code — the same self-model an application built with "
        f"s0ma keeps about its code — read out of a registry booted for this "
        f"build and out of the committed build artifacts of the packages "
        f"that are written in s0ma itself.",
        "",
        f"By layer: {layers}. {public} of the {len(ordered)} declare "
        f"themselves public and {undeclared} declare no visibility at all, "
        f"which is the honest answer for a component registered from "
        f"hand-written Python: visibility is a field of the s0ma language, "
        f"and a Python registration has nowhere to put one.",
        "",
        f"This page describes the build stamped "
        f"`{cell(bundle.stamp.snapshot_hash)}` at version "
        f"`{cell(bundle.stamp.release_version)}`. The same rows in a form a "
        f"program can read, with the reading each fact came from, are in "
        f"[`{inventory}`]({to_inventory}).",
        "",
        *_contents(distributions),
        "## How to read the tables",
        "",
        "**Component** is the id this documentation addresses it by, which "
        "is its import path with a prefix. **Kind** is what sort of thing it "
        "is and **Layer** is where it sits: a presentation component may "
        "reach an application one and an application one may reach the "
        "framework, never the other way round, and that rule is checked at "
        "build time rather than asserted here. The two columns answer "
        "different questions and their answers may read the same — a "
        "framework-kind component sitting in the framework layer is the "
        "ordinary case, not a repetition.",
        "",
        f"**Visible** is the declared visibility, or `{VISIBILITY_ABSENT}` "
        f"where the registration carries none. **What it is for** is the "
        f"component's own stated intent, quoted rather than rewritten — "
        f"every registered component has to say what it is for, and this is "
        f"what each of them said.",
        "",
    ]

    for distribution in distributions:
        held = grouped[distribution]
        kinds = _tally(item.kind for item in held)
        by_count = sorted(kinds.items(), key=lambda pair: (-pair[1], pair[0]))
        summary = (
            f"all of them {cell(KIND_WORDS.get(by_count[0][0], by_count[0][0]))}"
            if len(by_count) == 1
            else ", ".join(
                f"{count} {cell(KIND_WORDS.get(name, name))}"
                for name, count in by_count
            )
        )
        lines.append(f"## {distribution}")
        lines.append("")
        lines.append(
            f"{len(held)} of the {len(ordered)} components: {summary}. What "
            f"the distribution itself is, and what it depends on, is on the "
            f"[distributions page]({to_packages})."
        )
        lines.append("")
        lines.extend(_component_rows(held))
    return _page(lines)
