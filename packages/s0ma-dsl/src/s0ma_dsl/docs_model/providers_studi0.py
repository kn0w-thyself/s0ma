"""studi0's served surface, read from the build studi0 ships.

Milestone D4b of the docs-function plan (internal) §9, architecture plan
§7.5. One adapter over five readings of one package, every one of them a
committed file of this repository:

``_built/studi0_server.py``
    ``ROUTE_TABLE`` — the route table D4a promoted into package data —
    and ``Studi0ServerConfig``. Every HTTP surface studi0 serves comes
    from here.
``_built/studi0_state.py``
    The wire identities: the two schema strings studi0 stamps, the
    schema string it expects to find inside the graph envelope, and the
    frozen key set of each document.
``_built/studi0_watch.py``
    ``Studi0WatchConfig`` — how often the project is re-read, and how
    long a shutdown waits.
``_built/studi0_narration.py``
    The narration event contract and the presence marker: the record
    type studi0 will render, the phases it knows, the window it bounds
    the served list to, and the two paths the side channel uses.
``_built/self_context.json``
    Every component studi0 registers. This is the resolution universe
    the route table's bindings are checked against. Four of the five
    stamp records; this one is the exception, for the same reason core's
    bootstrap is: what it yields is the component inventory, which this
    model addresses and does not hold. It is named here so a reader can
    see every place this provider looked, and no record carries it.

**Why the source is package data and not the serving code.** B3 read
this package and found *zero* addressable actions: the routes existed
only as an ``if path ==`` chain inside the ``route_request`` nerve body,
and the viewer's gestures only as anonymous handlers in ``app.js``.
Deriving a route table from either "is not derivation, it is guessing",
so the B gate ruled that studi0 must *declare* its table and a provider
must read the declaration. D4a declared it, and pinned it to the serving
chain with a parity test that fails when either side moves. This module
is the second half of that ruling: it reads what the package says about
itself, and it invents nothing that the package does not say.

**Read, never imported.** Nothing here imports ``s0ma_studi0``. That
package's ``__init__`` bootstraps its built modules at import time —
executing their registrations into whatever registry the process holds —
so importing it to read a constant would be a side effect, and importing
a module out of ``_built`` directly is what the package's own docstring
forbids ("that would execute the module a second time and double its
registrations"). Instead every value is lifted out of the committed
build with :mod:`ast`: parsed, never executed, and
:func:`ast.literal_eval` on the literal alone. The committed build is
byte-gated against its ``.s0ma`` sources by ``scripts/check.py``, so
what is read here cannot have drifted from what studi0 declares.

**A file source, and a file hash.** Unlike the core provider — whose
sources are import paths into an installed package — every source here
is a tracked file of this repository, so each is named by its
repository-relative POSIX path and each digest is the sha256 of that
file's LF-normalized bytes. A record moves when the file it was read
from moves, which for a committed build means: when somebody edits the
``.s0ma`` source and rebuilds.

**All five of studi0's routes have ids now.** D4b emitted two. The other
three — ``/``, ``/assets/app.css`` and ``/assets/app.js`` — were counted
deferrals rather than records, because ``§5``'s form spelled its path
segment with a charset that admitted neither a dot nor the empty string,
so the ids they needed were refused by the very function that mints
them. D5a completed the form on both edges, and both completions are
conventions rather than charset drift:

* a path segment may carry a dot, because an asset route's last segment
  is a filename and ``app.css`` is its name rather than a word to be
  repaired into ``app-css``;
* the root route is addressed as ``studi0:action/index`` — the second
  documented normalization of this form, alongside the leading-slash
  strip, performed by :func:`~s0ma_dsl.docs_model.ids.normalize_id` and
  reversed by :func:`~s0ma_dsl.docs_model.ids.studi0_public_name`, so
  the id says ``index`` and the served name still says ``/``.

The deferral machinery stays. :meth:`Studi0Provider.deferred_routes`
returns nothing today and :data:`UNADDRESSABLE_ROUTES` is empty, but a
route the form cannot spell — or one that wants an id another route
already holds — is still counted rather than dropped, and this
milestone's tests pin the empty set so a sixth route that cannot be
addressed turns the suite red instead of vanishing.

**The viewer's gestures are not declared, so they are not described.**
``s0ma_src/assets/app.js`` builds its toolbar out of anonymous handlers
passed to a helper (``toolbarButton("fit", function () {...})``), routes
keystrokes through one ``switch``-shaped handler, and attaches canvas
interaction imperatively. There is no registry, no ``data-action``
attribute and no stable name — nothing that could be enumerated without
scraping UI labels, which architecture §7.5 rules out in as many words:
"UI labels are consumers of stable surface ids; they are not the
canonical source of capability existence." So this provider describes
studi0's HTTP surface and says nothing at all about its gestures. Honest
absence, until studi0 makes them declarable.

**What is excluded on purpose.** The visual truth-language note at
``plans/notes/studi0-visual-truth-language.md`` is a *candidate*
contract, not an accepted authority (plan §1.2 fact 13). Nothing here
reads it, and a record citing it would give a proposal the standing of a
decision.

**No side effects.** Nothing here writes, opens a socket, or imports the
package it describes.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.ids import DocsIdError, studi0_action_id, studi0_public_name, validate_id
from s0ma_dsl.docs_model.providers import (
    DocsProviderError,
    ProviderResult,
    SourcedRecord,
    sort_records,
)
from s0ma_dsl.docs_model.providers_repo import status_line
from s0ma_dsl.docs_model.records import (
    SCHEMA,
    AuthorityRef,
    Provenance,
    SurfaceRecord,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

__all__ = [
    "BUILT_DIR",
    "FLOORS",
    "NARRATION_SOURCE",
    "PACKAGE",
    "PROVIDER_ID",
    "SELF_CONTEXT_SOURCE",
    "SERVER_SOURCE",
    "STATE_SOURCE",
    "UNADDRESSABLE_ROUTES",
    "WATCH_SOURCE",
    "Studi0Provider",
    "Studi0ProviderError",
]

#: This adapter's stable id, and the ``adapter_id`` stamped on every
#: record it emits.
PROVIDER_ID = "studi0"

#: The import package the components live in. A component id is
#: package-qualified — a flat ``route_request`` means nothing across four
#: packages — and studi0's own canonical ids are flat (``module::name``),
#: so this is the half the built artifacts do not carry.
PACKAGE = "s0ma_studi0"

#: Where the committed build lives, repository-relative.
BUILT_DIR = "packages/s0ma-studi0/src/s0ma_studi0/_built"

SERVER_SOURCE = f"{BUILT_DIR}/studi0_server.py"
STATE_SOURCE = f"{BUILT_DIR}/studi0_state.py"
WATCH_SOURCE = f"{BUILT_DIR}/studi0_watch.py"
NARRATION_SOURCE = f"{BUILT_DIR}/studi0_narration.py"
SELF_CONTEXT_SOURCE = f"{BUILT_DIR}/self_context.json"

#: The routes this provider cannot address, and therefore does not emit.
#: **Empty since D5a**, which completed the id form on both the edges
#: that made it non-empty — see this module's docstring. Kept rather than
#: deleted: a counted, reviewable deferral is the difference between a
#: known gap and a documentation build that is quietly smaller than the
#: product, and the mechanism has to already exist on the day a route
#: needs it. :meth:`Studi0Provider.deferred_routes` reports what was
#: actually skipped, and this milestone's tests assert the two agree — so
#: a sixth route that cannot be addressed turns a test red instead of
#: vanishing.
UNADDRESSABLE_ROUTES: tuple[str, ...] = ()

#: Anti-vacuity floors, in the shape
#: :func:`~s0ma_dsl.docs_model.validate.check_floors` reads. The
#: authorities floor is exact and that is forced rather than chosen: six
#: declared contracts leave no room between "all of them" and "none of
#: them". The surfaces floor is four against five live routes, which is
#: the first time this provider has had room for one at all — before D5a
#: only two routes were addressable and an exact floor was the only
#: honest number. Four is the usual shape: retiring one route does not
#: trip it, and losing the API pair — the half of the table that is the
#: product rather than the page it is served on — does.
FLOORS: Mapping[tuple[str, str], int] = {
    (PROVIDER_ID, "surfaces"): 4,
    (PROVIDER_ID, "authorities"): 6,
}

#: The channel word for an HTTP route of the viewer (architecture §6.3).
_STUDI0_CHANNEL = "studi0"

#: Every key a route-table entry carries. The table declares its own
#: shape in its ``schema`` field and studi0's tests hold it to that; this
#: is the same shape restated where a missing key would otherwise become
#: a ``KeyError`` in the middle of a build.
_ROUTE_KEYS = frozenset(
    {"answered_by", "effects", "errors", "media_type", "method", "path", "purpose"}
)

#: The side-effect vocabulary architecture §6.3 gives a surface. A route
#: whose declared word is outside it is refused rather than carried: a
#: word no gate recognizes reads to every later check as a class of
#: effect nobody has thought about.
_EFFECT_WORDS = frozenset(
    {"none", "read", "write", "network", "subprocess", "credential", "approval"}
)

#: The authority class every record this provider mints belongs to.
#: These are facts a package declares about itself in its own data —
#: weaker than an ADR and stronger than an observation, which is exactly
#: what ``declared`` ranks as.
_DECLARED = "declared"


class Studi0ProviderError(DocsProviderError):
    """The studi0 provider cannot read what it was asked to read.

    A provider-contract failure, not a documentation finding. A missing
    build, a route table that has lost a key, a binding that names a
    component nothing registers — no author can fix any of those by
    writing prose, and continuing would emit records that describe a
    studi0 that does not exist.
    """


# ---------------------------------------------------------------------------
# Reading files
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Source:
    """One file, read once: where it is, what it says, what it hashes to."""

    path: str
    text: str
    digest: str


def _digest_of(text: str) -> str:
    """The sha256 of ``text`` as LF-normalized UTF-8 bytes.

    The same rule the repository provider uses, and deliberately so: two
    providers that hashed one file differently would report a mismatch
    that is really a difference of convention. Equal to what
    ``sha256sum`` reports for the tracked file, and equal again in a
    checkout that lost the line-feed attribute.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _literal(node: ast.expr) -> object | None:
    """``node``'s value if it is a literal, else ``None``.

    ``None`` means "not a literal", which is why no constant read
    through here is allowed to *be* ``None``: the emitted build has
    none, and a constant that became one would read as absent and be
    refused by name rather than silently dropped.
    """
    try:
        value: object = ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None
    return value


def _assigned(statements: Sequence[ast.stmt]) -> dict[str, object]:
    """Every literal a run of statements binds to a plain name."""
    found: dict[str, object] = {}
    for node in statements:
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.value is not None:
                value = _literal(node.value)
                if value is not None:
                    found[node.target.id] = value
        elif isinstance(node, ast.Assign):
            value = _literal(node.value)
            if value is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = value
    return found


def _module_constants(source: _Source) -> dict[str, object]:
    """Every module-level literal of one emitted module, parsed not run.

    Classes come back as dictionaries of their own literal members, which
    is how ``Studi0ServerConfig`` and ``Studi0WatchConfig`` — both plain
    holders of class-level constants — are read without constructing
    anything. Everything else in an emitted module (its imports, its
    ``register_module`` call, its decorated definitions) is not a literal
    and is passed over.
    """
    try:
        tree = ast.parse(source.text, filename=source.path)
    except SyntaxError as error:  # pragma: no cover - a broken build
        raise Studi0ProviderError(
            f"{source.path} is not parseable Python: {error}. The committed "
            f"build is what studi0 actually ships, so a build that cannot be "
            f"read is a release defect, not a documentation one."
        ) from error
    found = _assigned(tree.body)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            members = _assigned(node.body)
            if members:
                found[node.name] = members
    return found


def _text(constants: Mapping[str, object], name: str, where: str) -> str:
    """One declared string constant, refused by name where it is absent."""
    value = constants.get(name)
    if not isinstance(value, str) or not value:
        raise Studi0ProviderError(
            f"{where} declares no {name}, so studi0's own account of this "
            f"contract cannot be read. The value moved, was renamed, or the "
            f"committed build is stale — rebuild the package and look again."
        )
    return value


def _words(constants: Mapping[str, object], name: str, where: str) -> tuple[str, ...]:
    """One declared tuple of strings, refused by name where it is absent."""
    value = constants.get(name)
    if not isinstance(value, tuple) or not value or not all(isinstance(x, str) for x in value):
        raise Studi0ProviderError(
            f"{where} declares no {name} as a non-empty tuple of strings, so "
            f"the frozen shape it names cannot be read."
        )
    return tuple(str(item) for item in value)


def _number(constants: Mapping[str, object], name: str, where: str) -> str:
    """One declared numeric constant, written as it was declared."""
    value = constants.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise Studi0ProviderError(
            f"{where} declares no {name} as a whole number, so the bound it "
            f"names cannot be reported. A bound nobody can read is one "
            f"nobody can check."
        )
    return str(value)


def _member(constants: Mapping[str, object], holder: str, name: str, where: str) -> str:
    """One class-level constant, written as it was declared."""
    members = constants.get(holder)
    if not isinstance(members, dict) or name not in members:
        raise Studi0ProviderError(
            f"{where} declares no {holder}.{name}, so the setting it names "
            f"cannot be reported. A contract fact nobody can read is one "
            f"nobody can check."
        )
    return str(members[name])


# ---------------------------------------------------------------------------
# The component inventory
# ---------------------------------------------------------------------------


def _component_id(canonical: str, where: str) -> str:
    """``studi0_server::route_request`` as a package-qualified id.

    studi0's own ids are flat because a build is a single flat module
    namespace; the documentation model addresses components
    package-qualified because four packages share one registry. This is
    the one place the two vocabularies meet.
    """
    module, separator, name = canonical.partition("::")
    if not separator or not module or not name:
        raise Studi0ProviderError(
            f"{where} names {canonical!r}, which is not a canonical "
            f"module::name id, so there is nothing to address. Write the "
            f"declaration's own canonical id — studi0_state::state_document, "
            f"for one."
        )
    identifier = f"component:{PACKAGE}.{module}.{name}"
    validate_id(identifier)
    return identifier


def _inventory(source: _Source) -> dict[str, str]:
    """Every component studi0 registers: canonical id → addressable id.

    Read from the build's own self-context rather than from a registry,
    for the same reason everything else here is: describing studi0 must
    not mean importing it. The self-context is the package's own answer
    to "what do I contain", written at build time and committed beside
    the modules it describes.
    """
    try:
        document = json.loads(source.text)
    except ValueError as error:
        raise Studi0ProviderError(
            f"{source.path} is not readable as JSON: {error}"
        ) from error
    components = document.get("components") if isinstance(document, dict) else None
    if not isinstance(components, list) or not components:
        raise Studi0ProviderError(
            f"{source.path} lists no components, so nothing a route names can "
            f"be resolved. Every binding would have to be taken on trust, "
            f"which is the one thing this provider exists not to do."
        )
    index: dict[str, str] = {}
    for entry in components:
        canonical = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(canonical, str) or not canonical:
            raise Studi0ProviderError(
                f"{source.path} carries a component with no id, so the "
                f"inventory it stands for is incomplete."
            )
        index[canonical] = _component_id(canonical, source.path)
    return index


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------


def _collapse(text: str) -> str:
    """One line of prose, runs of whitespace collapsed, otherwise verbatim.

    A surface's ``intent`` is a quotation — here, of the ``purpose`` the
    package wrote for the route. Nothing is paraphrased and nothing is
    invented; the only change is that the emitted build may have wrapped
    the sentence, and a record holds one line.
    """
    return " ".join(text.split())


def _route_table(constants: Mapping[str, object]) -> tuple[dict[str, str], ...]:
    """``ROUTE_TABLE``, checked into the shape it declares for itself."""
    table = constants.get("ROUTE_TABLE")
    if not isinstance(table, tuple) or not table:
        raise Studi0ProviderError(
            f"{SERVER_SOURCE} declares no ROUTE_TABLE, so studi0's served "
            f"routes exist only inside a function body again. The B gate "
            f"ruled that deriving them from that body is guessing; declare "
            f"the table in the package and rebuild."
        )
    rows: list[dict[str, str]] = []
    for entry in table:
        if not isinstance(entry, dict):
            raise Studi0ProviderError(
                f"ROUTE_TABLE carries {entry!r}, which is not a route entry."
            )
        missing = sorted(_ROUTE_KEYS - set(entry))
        if missing:
            raise Studi0ProviderError(
                f"the route {entry.get('path', '?')!r} declares no "
                f"{', '.join(missing)}. Every entry carries the same seven "
                f"keys — the table's own schema says so — because a record "
                f"built from half an entry says less than no record."
            )
        rows.append({str(key): str(value) for key, value in entry.items()})
    return tuple(rows)


def _action_id(path: str) -> str | None:
    """The id of one route, or ``None`` where the form cannot address it.

    Every route studi0 declares today has an id: D5a completed the form
    for the filename dot and for the root, which were the two refusals
    this branch was written for. It stays because the two refusals that
    remain are real — a path with a character the form does not spell,
    and a route that wants the id the root convention already holds —
    and returning ``None`` is what makes either a counted deferral
    instead of a swallowed exception. See :data:`UNADDRESSABLE_ROUTES`.
    """
    try:
        return studi0_action_id(path)
    except DocsIdError:
        return None


def _bindings(entry: Mapping[str, str], inventory: Mapping[str, str]) -> tuple[str, ...]:
    """The components one route names, as sorted ids, all of them real.

    A binding the inventory does not know is refused rather than emitted:
    a reference that resolves to nothing is worse than an unbound
    surface, because the unbound one says so.
    """
    named = [item.strip() for item in entry["answered_by"].split(",") if item.strip()]
    if not named:
        raise Studi0ProviderError(
            f"the route {entry['path']!r} names nothing that answers it. The "
            f"declared table binds each route to the declarations that serve "
            f"it; an unbound route is a documented capability with nothing "
            f"behind it."
        )
    found: set[str] = set()
    for canonical in named:
        identifier = inventory.get(canonical)
        if identifier is None:
            raise Studi0ProviderError(
                f"the route {entry['path']!r} is answered by {canonical!r}, "
                f"which studi0 does not register, so the binding points at "
                f"nothing. Either the declaration was renamed and the table "
                f"was not, or the committed build is stale."
            )
        found.add(identifier)
    return tuple(sorted(found))


def _effects(entry: Mapping[str, str]) -> tuple[str, ...]:
    """One route's side-effect fact, as the package declared it.

    Declared, not derived from the method: HTTP promises that a ``GET``
    is safe, which would make every one of these a read, and studi0 knows
    better than that about its own asset routes — they hand back bytes
    the build embedded and touch nothing at all. This is exactly what the
    promotion bought, so it is read rather than inferred.
    """
    word = entry["effects"].strip()
    if word not in _EFFECT_WORDS:
        raise Studi0ProviderError(
            f"the route {entry['path']!r} declares its side effects as "
            f"{word!r}. Write one of {', '.join(sorted(_EFFECT_WORDS))} — an "
            f"unclassified surface is the one a later gate cannot check, and "
            f"a word outside the vocabulary is worse than none because it "
            f"looks classified."
        )
    return (word,)


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


class Studi0Provider:
    """One deterministic reading of the studi0 package.

    ``root`` is the repository the records describe, fixed when the
    provider is built. Everything is read at construction and
    :meth:`provide` hands over what was read, so calling it twice in one
    process returns the same object and the composition's determinism
    rests on nothing more than that.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        server = self._read(SERVER_SOURCE)
        state = self._read(STATE_SOURCE)
        watch = self._read(WATCH_SOURCE)
        narration = self._read(NARRATION_SOURCE)
        context = self._read(SELF_CONTEXT_SOURCE)

        inventory = _inventory(context)
        server_constants = _module_constants(server)
        state_constants = _module_constants(state)
        watch_constants = _module_constants(watch)
        narration_constants = _module_constants(narration)

        table = _route_table(server_constants)
        records: list[SourcedRecord] = []
        deferred: list[str] = []
        for entry in table:
            # Every entry is read and checked, addressable or not. A
            # route the id form cannot spell is still a route studi0
            # serves, and a broken binding on one of those must not hide
            # behind the gap that keeps it out of the record set.
            bindings = _bindings(entry, inventory)
            effects = _effects(entry)
            identifier = _action_id(entry["path"])
            if identifier is None:
                deferred.append(entry["path"])
                continue
            records.append(
                SourcedRecord.of(
                    SurfaceRecord(
                        id=identifier,
                        channel=_STUDI0_CHANNEL,
                        public_name=studi0_public_name(identifier),
                        intent=_collapse(entry["purpose"]),
                        component_refs=bindings,
                        # Nothing here was transcribed by hand: the route
                        # table is package data and this is a reading of
                        # it. That is the whole point of D4a — before it,
                        # every studi0 surface record carried an exception
                        # saying a person had written its facts out.
                        manual_exception="",
                        governed_by=self._governing(entry["path"]),
                        side_effects=effects,
                        errors=tuple(
                            sorted(
                                item.strip()
                                for item in entry["errors"].split(",")
                                if item.strip()
                            )
                        ),
                        provenance=_provenance(server),
                    )
                )
            )

        records.extend(self._wire_records(state, state_constants))
        records.append(self._serving_record(server, server_constants, len(table)))
        records.append(self._watch_record(watch, watch_constants))
        records.extend(self._narration_records(narration, narration_constants))

        self._deferred = tuple(sorted(deferred))
        self._component_ids = tuple(sorted(inventory.values()))
        self._result = ProviderResult(
            provider_id=PROVIDER_ID,
            records=sort_records(records),
        )

    # -- reading -----------------------------------------------------------

    def _read(self, relative: str) -> _Source:
        """One committed file of the checkout, refused by name if absent."""
        path = self._root / relative
        if not path.is_file():
            raise Studi0ProviderError(
                f"{relative} is not in this checkout, so studi0's declared "
                f"surface cannot be read. The committed build ships in the "
                f"wheel; if it is missing, rebuild the package with "
                f"`s0ma --project-root packages/s0ma-studi0 build "
                f"packages/s0ma-studi0`."
            )
        text = path.read_text(encoding="utf-8")
        return _Source(path=relative, text=text, digest=_digest_of(text))

    # -- the authority records ---------------------------------------------

    def _authority(
        self, *, name: str, source: _Source, section: str, facts: Mapping[str, str]
    ) -> SourcedRecord:
        """One declared contract of this package, stamped and addressable."""
        identifier = f"authority:{_DECLARED}/studi0.{name}"
        validate_id(identifier)
        return SourcedRecord(
            record=AuthorityRef(
                id=identifier,
                authority_class=_DECLARED,
                source=source.path,
                section=section,
                content_sha256=source.digest,
                status=status_line("Declared", dict(facts)),
                delegates=(),
            ),
            provenance=_provenance(source),
        )

    def _wire_records(
        self, source: _Source, constants: Mapping[str, object]
    ) -> list[SourcedRecord]:
        """The two documents' identities, as the package declares them.

        Until D4a these were three set literals near the top of
        ``tests/test_api.py``, which made a test the owner of a contract
        a page is built against. The keys are listed in the fact grammar
        because a key set *is* the contract: a reader who knows the
        schema string and not the keys knows the name of something they
        still cannot parse.
        """
        return [
            self._authority(
                name="wire-state",
                source=source,
                section="STATE_SCHEMA",
                facts={
                    "schema": _text(constants, "STATE_SCHEMA", source.path),
                    "keys": ",".join(_words(constants, "STATE_DOCUMENT_KEYS", source.path)),
                    "narration_keys": ",".join(
                        _words(constants, "NARRATION_BLOCK_KEYS", source.path)
                    ),
                    "route": "/api/state",
                },
            ),
            self._authority(
                name="wire-graph",
                source=source,
                section="GRAPH_SCHEMA",
                facts={
                    "schema": _text(constants, "GRAPH_SCHEMA", source.path),
                    "keys": ",".join(_words(constants, "GRAPH_DOCUMENT_KEYS", source.path)),
                    # The envelope and the graph it carries version
                    # independently on purpose: the transport is studi0's,
                    # the graph contract is the dsl's.
                    "carries": _text(constants, "CARRIED_GRAPH_SCHEMA", source.path),
                    "route": "/api/graph",
                },
            ),
        ]

    def _serving_record(
        self, source: _Source, constants: Mapping[str, object], routes: int
    ) -> SourcedRecord:
        """How studi0 serves: where it binds, what it answers, what it refuses."""
        return self._authority(
            name="serving-contract",
            source=source,
            section="Studi0ServerConfig",
            facts={
                "host": _member(constants, "Studi0ServerConfig", "host", source.path),
                "methods": "GET",
                "routes": str(routes),
                "unserved": "NOT_FOUND",
                "client_poll_ms": _member(
                    constants, "Studi0ServerConfig", "client_poll_interval_ms", source.path
                ),
                "shutdown_poll_seconds": _member(
                    constants, "Studi0ServerConfig", "shutdown_poll_seconds", source.path
                ),
            },
        )

    def _watch_record(self, source: _Source, constants: Mapping[str, object]) -> SourcedRecord:
        """The artifact watcher's contract, as ``studi0_watch`` declares it.

        The three guarantees this carries are the ones a consumer of the
        API depends on without ever seeing the watch: the project is
        re-read on a cadence, nothing is written back, and a failure
        costs one tick rather than the view. The cadence numbers are read
        from the config; the read-only and never-raises facts are the
        registered guarantees of ``poll_once`` and of the module itself,
        which is why they are stated as facts of this record rather than
        derived from anything.
        """
        return self._authority(
            name="watch-contract",
            source=source,
            section="Studi0WatchConfig",
            facts={
                "poll_seconds": _member(
                    constants, "Studi0WatchConfig", "poll_seconds", source.path
                ),
                "join_seconds": _member(
                    constants, "Studi0WatchConfig", "join_seconds", source.path
                ),
                "reads": "build_artifacts",
                "writes": "none",
                "raises": "never",
                "reports": "once_per_failure",
            },
        )

    def _narration_records(
        self, source: _Source, constants: Mapping[str, object]
    ) -> list[SourcedRecord]:
        """The narration side channel: the event contract, and the marker.

        Two records because they are two contracts with two audiences.
        The event contract is what an agent writes and studi0 will
        render — one record type, four phases, a bounded window. The
        presence marker is the one file studi0 ever writes into the tree
        it is watching, and the authoring MCP server reads it to decide
        whether to ask for narration at all.
        """
        return [
            self._authority(
                name="narration-event",
                source=source,
                section="NARRATION_TYPE",
                facts={
                    "type": _text(constants, "NARRATION_TYPE", source.path),
                    "phases": ",".join(_words(constants, "NARRATION_PHASES", source.path)),
                    "window": _number(constants, "NARRATION_WINDOW", source.path),
                    "log": "/".join(_words(constants, "SESSION_LOG_PATH_PARTS", source.path)),
                    "invalid": "counted_never_rendered",
                },
            ),
            self._authority(
                name="presence-marker",
                source=source,
                section="PRESENCE_PATH_PARTS",
                facts={
                    "path": "/".join(_words(constants, "PRESENCE_PATH_PARTS", source.path)),
                    "written": "on_bind",
                    "removed": "on_exit",
                    "scope": "the_only_file_studi0_writes",
                },
            ),
        ]

    def _governing(self, path: str) -> tuple[str, ...]:
        """The declared contracts one route answers under.

        Only the two API routes are governed by a wire contract: the
        asset routes hand back embedded bytes and answer to no document
        shape. Every route is served under the serving contract, and the
        two API routes are as current as the watch makes them, which is
        why the watch is cited there and nowhere else.
        """
        wire = {
            "/api/state": f"authority:{_DECLARED}/studi0.wire-state",
            "/api/graph": f"authority:{_DECLARED}/studi0.wire-graph",
        }.get(path)
        if wire is None:
            return ()
        return tuple(
            sorted(
                (
                    wire,
                    f"authority:{_DECLARED}/studi0.serving-contract",
                    f"authority:{_DECLARED}/studi0.watch-contract",
                )
            )
        )

    # -- the contract ------------------------------------------------------

    @property
    def provider_id(self) -> str:
        """This adapter's stable id, unique across the registry."""
        return PROVIDER_ID

    def provide(self) -> ProviderResult:
        """The records read at construction, sorted, stamped, unchanged."""
        return self._result

    def component_ids(self) -> tuple[str, ...]:
        """Every component studi0 registers, sorted.

        The resolution universe for this provider's ``component_refs``.
        A registered component has no record type in ``@1`` — it is what
        a surface is *implemented by*, not a thing the documentation
        describes — so it reaches a build through ``external_ids``.
        """
        return self._component_ids

    def external_ids(self) -> tuple[str, ...]:
        """Everything this provider vouches for but does not hold."""
        return self._component_ids

    def deferred_routes(self) -> tuple[str, ...]:
        """Every declared route this provider could not address, sorted.

        Not an ignore list: a counted, reviewable artifact. Empty since
        D5a grew the id form — the records the three deferrals stood in
        for are emitted now — and kept so that a route the form still
        cannot address is counted on the day it arrives rather than
        discovered missing. See this module's docstring.
        """
        return self._deferred


def _provenance(source: _Source) -> Provenance:
    """This provider's account of having read one file."""
    return Provenance(
        adapter_id=PROVIDER_ID,
        schema_version=SCHEMA,
        source=source.path,
        source_sha256=source.digest,
    )
