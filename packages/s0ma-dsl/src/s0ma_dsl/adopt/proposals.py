"""Proposals — what the scan *suggests*, and why it says so (rung 0's advice).

The census says what is in a file and the graph says what depends on
what. Both are facts. This module is the first place the retrofit
family stops reporting and starts **suggesting**: which architectural
layer a module probably belongs in, what kinds of components it holds,
which files the project should declare as its perimeter, and roughly how
much work each module is.

Nothing here is a decision. A layer is an authored judgement about what
a module is *for*, and no static reader can see purpose. So every
suggestion travels with its evidence in plain sentences, and a
suggestion with no evidence behind it is not made at all: the layer
comes back as ``None`` with confidence ``"low"`` and a sentence saying
the choice is the author's.

The four suggestions, and where the collision names come from
-------------------------------------------------------------

* :func:`propose` — one :class:`~s0ma_dsl.adopt.model.Proposal` per
  non-test module, sorted by module.
* :func:`suggest_perimeter` — the ``[tool.s0ma]`` settings rung 1 would
  write, as a :class:`~s0ma_dsl.adopt.model.PerimeterSuggestion`.
* :func:`estimate_effort` — how big each conversion looks, in bands.
* :func:`collision_warnings` — names in the scanned tree that already
  belong to one of s0ma's own components.
* :func:`framework_component_names` — the name set the collision check
  reads, exposed because a report may want to say how many there are.

Every one is a pure function over the frozen model. Nothing here opens a
file, imports the scanned project, or writes anything (retrofit rules
R-1 and R-2). :func:`suggest_perimeter` takes the project root for
symmetry with the rest of the family and deliberately never touches it —
everything it needs is already in the ``SourceFile`` and
``ModuleCensus`` records it is handed.

The layer names and the reachability matrix are imported, never restated
------------------------------------------------------------------------

Layer names come from :class:`s0ma_dsl.ast_nodes.enums.Layer` and the
"may a module at layer L reach layer T?" matrix comes from
``s0ma_dsl.resolver.dependency._ALLOWED_TARGET_LAYERS`` — the same dict
the transpiler's ``CROSS_LAYER_DEPENDENCY`` check consults, imported as
data so the two cannot drift apart. That matters more here than the
private underscore suggests: the design draft's "Layer-matrix
divergence" risk is exactly the case where a proposal set verifies clean
against core's looser structural tolerance and is then unbuildable at
rung 3, and the mitigation it names is "the proposals use the DSL
matrix". A copy in this file would be that divergence, one release
later. (``packages/s0ma-dsl/tests/test_cross_layer_check.py`` imports
the same private name to pin the matrix; the house already reads it as
package-internal data rather than as a private implementation detail.)

``FRAMEWORK`` is never proposed. The language reserves it for s0ma's own
internals, and a retrofit is by definition converting somebody else's
application.

The three families of evidence
------------------------------

A proposal weighs three independent kinds of signal, in this order, and
each one that fires contributes one plain sentence to ``reasons``:

1. **Name** — what the module and the folders above it are called.
   ``billing.storage`` says "storage", and that is what the author
   called it.
2. **Libraries** — which outside libraries it imports. A web framework
   or a terminal toolkit is how a program gets reached from outside; a
   database driver or an HTTP client is how it reaches out.
3. **Place** — where it sits in the project's own import graph: whether
   anything imports it, whether it can be run on its own, whether it
   leans on nothing at all.

``confidence`` follows from how many families agreed, and **only the
name family plus one other can reach** ``"high"``: a name is what the
author meant, and an import is what the code does, so the two agreeing
is the one case where a static reader has genuinely independent
corroboration. One family alone is ``"medium"``. Families that disagree,
or a family that points two ways at once, is ``"low"`` — the proposal is
still made (the name is taken as the tie-break, because it is the
author's own word for the module) but the disagreement is spelled out.

Finally the whole proposal set is checked against the reachability
matrix along the import edges that already exist. An edge the matrix
forbids is **a finding for the person, never an auto-fix**: both modules
get a sentence naming both of them and both proposed layers, and both
drop to ``"low"``. Silently re-labelling one of them to make the matrix
happy would be the tool inventing an architecture, which is the one
thing rung 0 must not do.

Consumers: ``adopt/report.py`` (B4) prints all of this; ``adopt/harvest.py``
takes a proposed layer as its optional ``layer=`` argument.
"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
from typing import TYPE_CHECKING

from s0ma_dsl.adopt.graph import (
    ORIGIN_FIRST_PARTY,
    ORIGIN_THIRD_PARTY,
    classify_imports,
)
from s0ma_dsl.adopt.model import (
    EffortEstimate,
    PerimeterSuggestion,
    Proposal,
    ScanWarning,
)
from s0ma_dsl.ast_nodes.enums import Kind, Layer

# Imported as data on purpose — see the module docstring. This is the
# transpiler's own cross-module reachability matrix; restating it here
# would re-create the design draft's "Layer-matrix divergence" risk.
from s0ma_dsl.resolver.dependency import _ALLOWED_TARGET_LAYERS

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from s0ma_dsl.adopt.model import EntityFact, GraphFacts, ModuleCensus, SourceFile

__all__ = [
    "EFFORT_BASIS",
    "PERIMETER_MODE",
    "WARNING_NAME_COLLISION",
    "collision_warnings",
    "estimate_effort",
    "framework_component_names",
    "propose",
    "suggest_perimeter",
]


# ---------------------------------------------------------------------------
# Vocabulary fixed elsewhere
# ---------------------------------------------------------------------------

# Role strings, fixed by ``model.SourceFile``; discovery writes them.
_ROLE_APP = "app"
_ROLE_TEST = "test"
_ROLE_SCRIPT = "script"
_ROLE_PACKAGE_MARKER = "package_marker"

# Confidence words, fixed by ``model.Proposal``.
_CONFIDENCE_LOW = "low"
_CONFIDENCE_MEDIUM = "medium"
_CONFIDENCE_HIGH = "high"

# Effort bands, fixed by ``model.EffortEstimate``: all three are always
# reported, zeroes included, in this order.
_BAND_SMALL = "small"
_BAND_MEDIUM = "medium"
_BAND_LARGE = "large"
_BAND_ORDER = (_BAND_SMALL, _BAND_MEDIUM, _BAND_LARGE)

# Shape-based kind hints, fixed by ``census.py``. B1 emits these seven
# words; B3 is where they meet the language's own taxonomy.
_HINT_EXCEPTION = "EXCEPTION"
_HINT_ENUM = "ENUM"
_HINT_MODEL = "MODEL"
_HINT_PROTOCOL = "PROTOCOL"
_HINT_CONSTANT = "CONSTANT"
_HINT_FUNCTION = "FUNCTION"
_HINT_CLASS = "CLASS"

# Entity categories, fixed by ``model.EntityFact``.
_CATEGORY_CLASS = "class"
_CATEGORY_CONSTANT = "constant"

PERIMETER_MODE = "migration"
"""The strictness mode a perimeter suggestion always names.

A tree that has converted nothing cannot honestly claim more, and
``migration`` is the mode whose severity matrix expects an ``UNKNOWN``
backlog. Fixed by ``model.PerimeterSuggestion``.
"""

WARNING_NAME_COLLISION = "ADOPT_SCAN_NAME_COLLISION"
"""Warning code for a name the framework has already taken (§5.4).

A report-only string carried in ``ScanReport.warnings``, not a raised
diagnostic: a scan reads and never refuses.
"""


# ---------------------------------------------------------------------------
# Hint → kind
#
# The census reports what a definition *looks* like; the language has its
# own taxonomy (spec §3.1). This map is the whole of the translation, and
# it is deliberately conservative. ``ADAPTER``, ``ORCHESTRATOR`` and
# ``CONFIG`` are never proposed: the difference between a SERVICE and an
# ADAPTER is whether the thing talks to an external system, which is a
# statement about meaning, and this file only ever saw a class statement.
# ---------------------------------------------------------------------------

_HINT_KINDS: dict[str, Kind] = {
    _HINT_EXCEPTION: Kind.EXCEPTION,
    _HINT_ENUM: Kind.ENUM,
    _HINT_MODEL: Kind.MODEL,
    _HINT_PROTOCOL: Kind.TYPE,
    _HINT_CONSTANT: Kind.CONSTANT,
    _HINT_FUNCTION: Kind.FUNCTION,
    _HINT_CLASS: Kind.SERVICE,
}


# ---------------------------------------------------------------------------
# Signal 1 — the name
#
# One word per concept plus its plural, matched against the dotted module
# name's segments and against the parts of an underscored segment
# (``db_client`` reaches ``client``). The file's own name is checked
# before the folders above it, because the closer a word sits to the
# code the more specific it is: ``app/api/models.py`` is a pile of
# models that happens to live under the API, not the other way round.
#
# Every word here is one somebody would use in a folder name without
# thinking about s0ma at all. Words that genuinely point two ways
# (``http`` — a server or a client? ``schema`` — a domain shape or a
# database table?) are left out rather than guessed at.
# ---------------------------------------------------------------------------

_NAME_SIGNALS: dict[str, Layer] = {
    # The ways in: what a person or another program talks to.
    "api": Layer.PRESENTATION,
    "apis": Layer.PRESENTATION,
    "cli": Layer.PRESENTATION,
    "command": Layer.PRESENTATION,
    "commands": Layer.PRESENTATION,
    "console": Layer.PRESENTATION,
    "controller": Layer.PRESENTATION,
    "controllers": Layer.PRESENTATION,
    "endpoint": Layer.PRESENTATION,
    "endpoints": Layer.PRESENTATION,
    "handler": Layer.PRESENTATION,
    "handlers": Layer.PRESENTATION,
    "route": Layer.PRESENTATION,
    "router": Layer.PRESENTATION,
    "routers": Layer.PRESENTATION,
    "routes": Layer.PRESENTATION,
    "template": Layer.PRESENTATION,
    "templates": Layer.PRESENTATION,
    "ui": Layer.PRESENTATION,
    "view": Layer.PRESENTATION,
    "views": Layer.PRESENTATION,
    "web": Layer.PRESENTATION,
    # The work the application coordinates.
    "application": Layer.APPLICATION,
    "orchestration": Layer.APPLICATION,
    "orchestrator": Layer.APPLICATION,
    "orchestrators": Layer.APPLICATION,
    "service": Layer.APPLICATION,
    "services": Layer.APPLICATION,
    "task": Layer.APPLICATION,
    "tasks": Layer.APPLICATION,
    "usecase": Layer.APPLICATION,
    "usecases": Layer.APPLICATION,
    "workflow": Layer.APPLICATION,
    "workflows": Layer.APPLICATION,
    # What the business is about, independent of anything technical.
    "domain": Layer.DOMAIN,
    "entities": Layer.DOMAIN,
    "entity": Layer.DOMAIN,
    "model": Layer.DOMAIN,
    "models": Layer.DOMAIN,
    "policies": Layer.DOMAIN,
    "policy": Layer.DOMAIN,
    "rule": Layer.DOMAIN,
    "rules": Layer.DOMAIN,
    # The ways out: databases, files, other people's systems.
    "adapter": Layer.INFRASTRUCTURE,
    "adapters": Layer.INFRASTRUCTURE,
    "cache": Layer.INFRASTRUCTURE,
    "client": Layer.INFRASTRUCTURE,
    "clients": Layer.INFRASTRUCTURE,
    "database": Layer.INFRASTRUCTURE,
    "db": Layer.INFRASTRUCTURE,
    "gateway": Layer.INFRASTRUCTURE,
    "gateways": Layer.INFRASTRUCTURE,
    "infra": Layer.INFRASTRUCTURE,
    "infrastructure": Layer.INFRASTRUCTURE,
    "persistence": Layer.INFRASTRUCTURE,
    "repo": Layer.INFRASTRUCTURE,
    "repos": Layer.INFRASTRUCTURE,
    "repositories": Layer.INFRASTRUCTURE,
    "repository": Layer.INFRASTRUCTURE,
    "storage": Layer.INFRASTRUCTURE,
    "store": Layer.INFRASTRUCTURE,
}


# ---------------------------------------------------------------------------
# Signal 2 — the libraries
#
# Keyed by the first dotted segment of an import target, which is what
# names the library. The second item is a plain noun phrase, so the
# reason can say what the thing *is* rather than assume the reader knows
# every package on PyPI.
#
# Only two layers appear. No library says "this is domain logic" — domain
# is what is left when nothing outside is involved — and no library says
# "this coordinates the application", which is a statement about how the
# code is arranged rather than about what it imports.
# ---------------------------------------------------------------------------

_LIBRARY_SIGNALS: dict[str, tuple[Layer, str]] = {
    # Ways in — web frameworks, terminal and desktop toolkits.
    "argparse": (Layer.PRESENTATION, "the command-line argument reader"),
    "bottle": (Layer.PRESENTATION, "a web framework"),
    "click": (Layer.PRESENTATION, "a command-line toolkit"),
    "cmd": (Layer.PRESENTATION, "the interactive-prompt toolkit"),
    "curses": (Layer.PRESENTATION, "a terminal-screen toolkit"),
    "django": (Layer.PRESENTATION, "a web framework"),
    "falcon": (Layer.PRESENTATION, "a web framework"),
    "fastapi": (Layer.PRESENTATION, "a web framework"),
    "flask": (Layer.PRESENTATION, "a web framework"),
    "getopt": (Layer.PRESENTATION, "the command-line argument reader"),
    "gradio": (Layer.PRESENTATION, "a web-interface toolkit"),
    "jinja2": (Layer.PRESENTATION, "a page-template engine"),
    "kivy": (Layer.PRESENTATION, "a desktop-interface toolkit"),
    "litestar": (Layer.PRESENTATION, "a web framework"),
    "pyramid": (Layer.PRESENTATION, "a web framework"),
    "quart": (Layer.PRESENTATION, "a web framework"),
    "rich": (Layer.PRESENTATION, "a terminal-output toolkit"),
    "sanic": (Layer.PRESENTATION, "a web framework"),
    "starlette": (Layer.PRESENTATION, "a web framework"),
    "streamlit": (Layer.PRESENTATION, "a web-interface toolkit"),
    "textual": (Layer.PRESENTATION, "a terminal-interface toolkit"),
    "tkinter": (Layer.PRESENTATION, "a desktop-interface toolkit"),
    "tornado": (Layer.PRESENTATION, "a web framework"),
    "typer": (Layer.PRESENTATION, "a command-line toolkit"),
    "uvicorn": (Layer.PRESENTATION, "a web server"),
    "werkzeug": (Layer.PRESENTATION, "a web-request toolkit"),
    "wsgiref": (Layer.PRESENTATION, "the built-in web-server plumbing"),
    # Ways out — databases, message queues, network and remote services.
    "aiofiles": (Layer.INFRASTRUCTURE, "a file-reading library"),
    "aiohttp": (Layer.INFRASTRUCTURE, "a web-request library"),
    "aiomysql": (Layer.INFRASTRUCTURE, "a database driver"),
    "aiopg": (Layer.INFRASTRUCTURE, "a database driver"),
    "asyncpg": (Layer.INFRASTRUCTURE, "a database driver"),
    "boto3": (Layer.INFRASTRUCTURE, "a cloud-service client"),
    "botocore": (Layer.INFRASTRUCTURE, "a cloud-service client"),
    "cassandra": (Layer.INFRASTRUCTURE, "a database driver"),
    "confluent_kafka": (Layer.INFRASTRUCTURE, "a message-queue client"),
    "elasticsearch": (Layer.INFRASTRUCTURE, "a search-service client"),
    "ftplib": (Layer.INFRASTRUCTURE, "the built-in file-transfer client"),
    "grpc": (Layer.INFRASTRUCTURE, "a remote-call library"),
    "httpx": (Layer.INFRASTRUCTURE, "a web-request library"),
    "imaplib": (Layer.INFRASTRUCTURE, "the built-in mail-reading client"),
    "kafka": (Layer.INFRASTRUCTURE, "a message-queue client"),
    "minio": (Layer.INFRASTRUCTURE, "a file-storage client"),
    "motor": (Layer.INFRASTRUCTURE, "a database driver"),
    "mysql": (Layer.INFRASTRUCTURE, "a database driver"),
    "neo4j": (Layer.INFRASTRUCTURE, "a database driver"),
    "paramiko": (Layer.INFRASTRUCTURE, "a remote-shell client"),
    "peewee": (Layer.INFRASTRUCTURE, "a database toolkit"),
    "pika": (Layer.INFRASTRUCTURE, "a message-queue client"),
    "poplib": (Layer.INFRASTRUCTURE, "the built-in mail-reading client"),
    "psycopg": (Layer.INFRASTRUCTURE, "a database driver"),
    "psycopg2": (Layer.INFRASTRUCTURE, "a database driver"),
    "pymongo": (Layer.INFRASTRUCTURE, "a database driver"),
    "pymysql": (Layer.INFRASTRUCTURE, "a database driver"),
    "pyodbc": (Layer.INFRASTRUCTURE, "a database driver"),
    "redis": (Layer.INFRASTRUCTURE, "a key-value store client"),
    "requests": (Layer.INFRASTRUCTURE, "a web-request library"),
    "s3fs": (Layer.INFRASTRUCTURE, "a file-storage client"),
    "smtplib": (Layer.INFRASTRUCTURE, "the built-in mail-sending client"),
    "socket": (Layer.INFRASTRUCTURE, "the built-in network plumbing"),
    "sqlalchemy": (Layer.INFRASTRUCTURE, "a database toolkit"),
    "sqlite3": (Layer.INFRASTRUCTURE, "the built-in database"),
    "sqlmodel": (Layer.INFRASTRUCTURE, "a database toolkit"),
    "tortoise": (Layer.INFRASTRUCTURE, "a database toolkit"),
    "urllib": (Layer.INFRASTRUCTURE, "the built-in web-request library"),
    "urllib3": (Layer.INFRASTRUCTURE, "a web-request library"),
    "xmlrpc": (Layer.INFRASTRUCTURE, "the built-in remote-call plumbing"),
}

_MAX_NAMED_LIBRARIES = 3
"""How many libraries a reason names before it says "and N others"."""


# ---------------------------------------------------------------------------
# Effort scoring thresholds
#
# Four things a static reader can honestly see. Size and the number of
# definitions each contribute 0, 1 or 2 points, as does the amount of
# work done at import time; being caught in an import cycle adds one
# more, and a file that will not parse adds two (nobody can size what
# nobody could read).
#
# The bands then say how much about a module stands out: **small** —
# nothing does; **medium** — one thing does; **large** — several do.
# ---------------------------------------------------------------------------

_SLOC_SMALL = 100
_SLOC_MEDIUM = 400
_ENTITIES_SMALL = 5
_ENTITIES_MEDIUM = 20
_EFFECTS_MEDIUM = 2
_BAND_SMALL_CEILING = 0
_BAND_MEDIUM_CEILING = 2

EFFORT_BASIS = (
    "Bands come from four things that can be seen without running anything — how many "
    "lines of real code a module has, how many things it defines, how much of it runs "
    "the moment it is imported, and whether it is tangled in an import cycle — so they "
    "sort the work from easiest to hardest and are not hours, not a schedule and not a "
    "promise."
)
"""One sentence, printed beside every estimate so nobody reads it as a plan."""


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _article(word: str) -> str:
    """``"a"`` or ``"an"`` for *word*, so a generated sentence reads right."""
    return "an" if word[:1].upper() in "AEIOU" else "a"


def _join(items: Sequence[str]) -> str:
    """``"a"`` / ``"a and b"`` / ``"a, b and c"`` — an English list, not a repr."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _plural(count: int, singular: str, plural: str) -> str:
    """``"1 thing"`` / ``"3 things"`` — a counted noun that is not embarrassing."""
    return f"{count} {singular}" if count == 1 else f"{count} {plural}"


def _basename(path: str) -> str:
    """The filename at the end of a project-relative POSIX path.

    ``str.rsplit`` rather than :class:`pathlib.Path`: every path in the
    model is POSIX by construction, and ``Path`` would read a backslash
    as a separator on Windows and as a filename character elsewhere.
    """
    return path.rsplit("/", 1)[-1]


def _conversion_censuses(censuses: Sequence[ModuleCensus]) -> tuple[ModuleCensus, ...]:
    """The modules a conversion is about: non-test, one per dotted name.

    Test files are left out, matching the graph — a test suite imports
    everything, and nobody converts one to decide where a layer boundary
    falls. Two files claiming one dotted name (a vendored copy, say) are
    one module; the one whose path sorts first is the one described, so
    the choice is stable across runs rather than dependent on walk order.
    """
    selected: dict[str, ModuleCensus] = {}
    ordered = sorted(censuses, key=lambda census: (census.source.module, census.source.path))
    for census in ordered:
        if census.source.role == _ROLE_TEST:
            continue
        selected.setdefault(census.source.module, census)
    return tuple(selected.values())


# ---------------------------------------------------------------------------
# T2 — kind mix
# ---------------------------------------------------------------------------


def _entity_kind(entity: EntityFact) -> Kind:
    """The language's kind for one definition, from its shape hint.

    Falls back on the entity's category when the hint is a word this map
    has not met — a census that grows an eighth hint should widen a
    module's kind mix, never crash a scan or quietly drop a definition
    out of the count.
    """
    kind = _HINT_KINDS.get(entity.kind_hint)
    if kind is not None:
        return kind
    if entity.category == _CATEGORY_CLASS:
        return Kind.SERVICE
    if entity.category == _CATEGORY_CONSTANT:
        return Kind.CONSTANT
    return Kind.FUNCTION


def _kind_mix(census: ModuleCensus) -> tuple[tuple[str, int], ...]:
    """``(kind, count)`` pairs for one module's definitions, sorted by kind.

    Counts **every** top-level definition, not only the public ones. A
    private function may become an INTERNAL component or a module-private
    helper, and which of the two it becomes is the author's call at
    conversion time; leaving them out would under-report the work.
    """
    counts = Counter(_entity_kind(entity).value for entity in census.entities)
    return tuple(sorted(counts.items()))


# ---------------------------------------------------------------------------
# T1 — layer proposals: the three families of evidence
# ---------------------------------------------------------------------------


def _name_tokens(module: str) -> tuple[str, ...]:
    """The words in a dotted module name, most specific first.

    ``"shop.storage.db_client"`` gives ``("db_client", "client", "db",
    "storage", "shop")``: each dotted segment from the file's own name
    outward, and within a segment the whole word before the parts of an
    underscored one (also right to left, because ``db_client`` is a
    client).
    """
    tokens: list[str] = []
    for segment in reversed(module.split(".")):
        lowered = segment.strip("_").lower()
        if not lowered:
            continue
        tokens.append(lowered)
        if "_" in lowered:
            tokens.extend(part for part in reversed(lowered.split("_")) if part)
    return tuple(tokens)


def _name_signal(census: ModuleCensus) -> tuple[Layer, str] | None:
    """The layer this module's own name points at, with its sentence.

    The first token that means something wins, and tokens run from the
    file's own name outward, so the closest word to the code decides.
    ``None`` when nothing in the name is a word this recognises.
    """
    for token in _name_tokens(census.source.module):
        layer = _NAME_SIGNALS.get(token)
        if layer is None:
            continue
        reason = (
            f"its name contains `{token}`, and things called that are usually "
            f"{_article(layer.value)} {layer.value} concern."
        )
        return layer, reason
    return None


def _library_hits(census: ModuleCensus) -> dict[str, tuple[Layer, str]]:
    """``root -> (layer, description)`` for the outside libraries a module imports.

    Deferred and ``TYPE_CHECKING`` imports count: a database driver
    imported inside a function is still a database driver, and hiding it
    from the evidence would make a module look more self-contained than
    it is. First-party imports are somebody else's module, not a
    library, and are the place family's business.
    """
    hits: dict[str, tuple[Layer, str]] = {}
    for record in census.imports:
        if record.origin == ORIGIN_FIRST_PARTY:
            continue
        root = record.module.split(".", 1)[0]
        signal = _LIBRARY_SIGNALS.get(root)
        if signal is not None:
            hits[root] = signal
    return hits


def _describe_libraries(hits: Mapping[str, tuple[Layer, str]], layer: Layer) -> str:
    """``"`flask` (a web framework)"``-style list of one layer's libraries."""
    phrases = [
        f"`{root}` ({description})"
        for root, (hit_layer, description) in sorted(hits.items())
        if hit_layer is layer
    ]
    if len(phrases) > _MAX_NAMED_LIBRARIES:
        extra = len(phrases) - _MAX_NAMED_LIBRARIES
        return _join(phrases[:_MAX_NAMED_LIBRARIES]) + f" and {_plural(extra, 'other', 'others')}"
    return _join(phrases)


_LIBRARY_SENTENCES: dict[Layer, str] = {
    Layer.PRESENTATION: (
        "it imports {libraries}, which is how a program gets reached from outside — "
        "that is presentation work."
    ),
    Layer.INFRASTRUCTURE: (
        "it imports {libraries}, which is how a program reaches out to the world beyond "
        "itself — that is infrastructure work."
    ),
}


def _library_signal(census: ModuleCensus) -> tuple[Layer | None, str] | None:
    """The layer this module's imports point at, with its sentence.

    ``None`` when it imports nothing recognisable. A ``None`` layer with
    a sentence when the libraries point two ways at once — a module that
    imports both a web framework and a database driver is a real thing,
    and the honest report is that it straddles a boundary rather than a
    coin toss between the two.
    """
    hits = _library_hits(census)
    if not hits:
        return None
    layers = {layer for layer, _ in hits.values()}
    if len(layers) == 1:
        layer = next(iter(layers))
        template = _LIBRARY_SENTENCES[layer]
        return layer, template.format(libraries=_describe_libraries(hits, layer))
    split = _join(
        [
            _describe_libraries(hits, layer)
            for layer in sorted(layers, key=lambda candidate: candidate.value)
        ]
    )
    return None, (
        f"it imports both {split}, which point at different layers, so this one is "
        f"a judgement call rather than a guess."
    )


def _place_signal(
    census: ModuleCensus,
    fan_in: Mapping[str, int],
    fan_out: Mapping[str, int],
) -> tuple[Layer, str] | None:
    """The layer this module's position in the project points at.

    Two rules, the more specific one first:

    * A module nothing imports that can be run on its own is a way *in*
      to the program, which is presentation.
    * A module that defines something real and leans on nothing — not
      another module of this project, not an outside library, not a
      standard-library tool for reaching past the process — is what pure
      domain logic looks like.

    ``None`` for everything in between, which is most of a real project
    and is exactly when the other two families have to carry the answer.

    The two conditions on the second rule are there to stop it answering
    when it has nothing to go on. A file that defines nothing leans on
    nothing because there is nothing in it, and calling that domain logic
    would be the tool talking to itself. And "no outside library" has to
    mean ``sqlite3`` too: the standard library contains plenty of doors
    to the world, and a leaf that opens one is an adapter, not a domain
    model — without that clause the place family would contradict the
    library family every time a module imported a built-in driver.
    """
    module = census.source.module
    runnable = census.source.role == _ROLE_SCRIPT or census.has_main_guard
    if runnable and fan_in.get(module, 0) == 0:
        return Layer.PRESENTATION, (
            "nothing else in the project imports it and it can be run on its own, "
            "which makes it one of the ways in to the program."
        )
    if not census.entities:
        return None
    leans_on_project = fan_out.get(module, 0) > 0 or any(
        record.origin == ORIGIN_FIRST_PARTY for record in census.imports
    )
    if leans_on_project:
        return None
    leans_outward = _library_hits(census) or any(
        record.origin == ORIGIN_THIRD_PARTY for record in census.imports
    )
    if leans_outward:
        return None
    return Layer.DOMAIN, (
        "it defines things of its own and imports nothing — not another module of this "
        "project, not a library that reaches outside the program — which is what a "
        "piece of self-contained domain logic looks like."
    )


def _weigh(
    name: tuple[Layer, str] | None,
    library: tuple[Layer | None, str] | None,
    place: tuple[Layer, str] | None,
) -> tuple[Layer | None, str, tuple[str, ...]]:
    """Combine the three families into a layer, a confidence and reasons.

    ``high`` needs the name family and one other to agree — a name is
    what the author meant and an import is what the code does, so those
    two lining up is the one genuinely independent corroboration a static
    reader can get. One family alone is ``medium``. Disagreement is
    ``low``, and the name wins the tie-break because it is the author's
    own word for the module.
    """
    signals: list[tuple[Layer | None, str]] = [
        signal for signal in (name, library, place) if signal is not None
    ]
    reasons = [reason for _, reason in signals]
    votes: list[Layer] = [layer for layer, _ in signals if layer is not None]
    if not votes:
        if not reasons:
            reasons.append(
                "nothing in its name, its imports or its place in the project points at "
                "a layer, so this one is yours to choose."
            )
        else:
            reasons.append("no layer can be read off that honestly, so the choice is yours.")
        return None, _CONFIDENCE_LOW, tuple(reasons)

    name_layer = name[0] if name is not None else None
    others = [
        signal[0]
        for signal in (library, place)
        if signal is not None and signal[0] is not None
    ]
    agreed = len(set(votes)) == 1

    if not agreed:
        chosen = name_layer if name_layer is not None else votes[0]
        disagreement = _join(sorted({layer.value for layer in votes}))
        reasons.append(
            f"those point at different layers ({disagreement}), so this is a suggestion "
            f"to argue with, not an answer."
        )
        return chosen, _CONFIDENCE_LOW, tuple(reasons)

    chosen = votes[0]
    if name_layer is not None and others:
        return chosen, _CONFIDENCE_HIGH, tuple(reasons)
    # Either one family spoke, or two agreed but neither of them was the
    # name. What the code does, without what it is called, is
    # corroboration of one kind only — and a layer is a claim about
    # intent, which is what a name carries.
    return chosen, _CONFIDENCE_MEDIUM, tuple(reasons)


# ---------------------------------------------------------------------------
# T1 — the matrix pass
# ---------------------------------------------------------------------------


_LAYERS_BY_VALUE: dict[str, Layer] = {layer.value: layer for layer in Layer}


def _matrix_sentences(
    layers: Mapping[str, str | None],
    edges: Sequence[tuple[str, str]],
) -> dict[str, list[str]]:
    """Import edges the proposed layers would make illegal, per module.

    Walks the import edges that **already exist** and asks the DSL's own
    reachability matrix whether the proposed layers permit them. Every
    answer of "no" is a finding for the person: both ends get the same
    sentence, naming both modules and both layers, because changing
    either end fixes it and a reader who opens only one of the two files
    still has to know.

    Nothing is re-labelled to make the matrix happy. A tool that quietly
    moved a module to a layer it never had evidence for would be
    inventing an architecture, which is the one thing rung 0 must not do.
    """
    findings: dict[str, list[str]] = {}
    for importer, imported in sorted(edges):
        source_name = layers.get(importer)
        target_name = layers.get(imported)
        if source_name is None or target_name is None:
            continue
        source_layer = _LAYERS_BY_VALUE.get(source_name)
        target_layer = _LAYERS_BY_VALUE.get(target_name)
        if source_layer is None or target_layer is None:
            continue
        if target_layer in _ALLOWED_TARGET_LAYERS.get(source_layer, set()):
            continue
        sentence = (
            f"`{importer}` already imports `{imported}` when it loads, but the layer "
            f"rules do not let {_article(source_name)} {source_name} module reach "
            f"{_article(target_name)} {target_name} one — if both of these proposed "
            f"layers are right, that import has to change before the converted project "
            f"will build."
        )
        findings.setdefault(importer, []).append(sentence)
        findings.setdefault(imported, []).append(sentence)
    return findings


def propose(censuses: Sequence[ModuleCensus], graph: GraphFacts) -> tuple[Proposal, ...]:
    """Suggest a layer and a kind mix for every module, with the reasoning.

    One :class:`~s0ma_dsl.adopt.model.Proposal` per non-test module,
    sorted by dotted module name. Imports are classified first (the
    census leaves origins unresolved on purpose), so a caller may hand
    over raw censuses or already-classified ones — the answer is the
    same either way.

    Read the result as advice with its evidence attached. ``layer`` is
    ``None`` whenever the evidence does not point anywhere, ``confidence``
    is ``"high"`` only when the module's name and what it actually
    imports agree, and any module whose proposed layer would make an
    import it already has illegal carries a sentence saying so and drops
    to ``"low"``.

    Package markers are proposed on too, because the graph carries them
    and a report that skipped them would not line up with the conversion
    order printed beside it. One usually comes back with no layer, which
    is the right answer for a file that exists to mark a directory.
    """
    resolved = classify_imports(censuses)
    conversion = _conversion_censuses(resolved)
    fan_in = dict(graph.fan_in)
    fan_out = dict(graph.fan_out)

    drafts: list[tuple[str, Layer | None, str, list[str], tuple[tuple[str, int], ...]]] = []
    for census in conversion:
        layer, confidence, reasons = _weigh(
            _name_signal(census),
            _library_signal(census),
            _place_signal(census, fan_in, fan_out),
        )
        drafts.append(
            (census.source.module, layer, confidence, list(reasons), _kind_mix(census))
        )

    proposed_layers = {
        module: None if layer is None else layer.value for module, layer, _, _, _ in drafts
    }
    findings = _matrix_sentences(proposed_layers, graph.edges)

    proposals: list[Proposal] = []
    for module, layer, weighed, weighed_reasons, kind_mix in drafts:
        extra = findings.get(module, [])
        proposals.append(
            Proposal(
                module=module,
                layer=None if layer is None else layer.value,
                # An illegal edge drops straight to "low", not one step
                # down: the proposal set contradicts itself, and a
                # medium-confidence contradiction still reads as an answer.
                confidence=_CONFIDENCE_LOW if extra else weighed,
                reasons=(*weighed_reasons, *extra),
                kind_mix=kind_mix,
            )
        )
    return tuple(proposals)


# ---------------------------------------------------------------------------
# T3 — the perimeter
# ---------------------------------------------------------------------------


def _marker_note(path: str, census: ModuleCensus | None) -> str:
    """One sentence about an ``__init__.py`` that is doing real work."""
    if census is not None and census.entities:
        does = f"it defines {_plural(len(census.entities), 'thing', 'things')}"
    elif census is not None and census.top_level_effects:
        does = "it runs code the moment the package is imported"
    else:
        does = "it carries more than a docstring, some imports and a list of exports"
    return (
        f"`{path}` is a package `__init__.py` that does real work ({does}), so it is not "
        f"offered as a package marker — move that code into a module of its own, or list "
        f"the file under `bootstrap_files` once you have decided it is a deliberate "
        f"exception."
    )


def suggest_perimeter(
    root: Path,
    sources: Sequence[SourceFile],
    censuses: Sequence[ModuleCensus],
    *,
    source_roots: Sequence[str] | None = None,
) -> PerimeterSuggestion:
    """The ``[tool.s0ma]`` settings rung 1 would write for this tree.

    Rung 1 makes a tree a s0ma project without touching a line of
    application code: it declares where the source lives, which files are
    deliberate plain-Python exceptions, and which ``__init__.py`` files
    only mark a package. This is what that would look like, so a person
    can read it before anything is written.

    **The roots a caller names are the roots this writes.** *source_roots*
    is passed by everything that knows which directories the scan read —
    which is everything, since the scan decides that before it discovers
    anything — and they are written through untouched. Re-deriving them
    from where the files turned out to be is what made ``adopt init``
    refuse its own proposal on the first multi-package repository it met:
    anything outside the named roots is attributed to ``"."``, and ``"."``
    beside a named root is a pair the project loader rejects. When it is
    left out, the roots are read back off the files as before, which is
    right for the one case that has no other answer (a tree discovered
    without scoping).

    *root* is accepted for symmetry with the rest of the family and is
    deliberately never touched: everything this needs is already in the
    records it is handed, and a suggestion that re-read the tree could
    disagree with the census it is printed beside. Nothing here opens a
    file (retrofit rules R-1 and R-2).
    """
    del root  # Intentionally unread — see the docstring.

    censuses_by_path = {census.source.path: census for census in censuses}

    if source_roots:
        roots = list(dict.fromkeys(source_roots))
    else:
        # Only the files a source root is *for*: application code and the
        # package markers that hold it together. A stand-alone script at
        # the project root is declared as bootstrap, and letting it drag
        # `"."` into the source roots beside `src` would propose a pair
        # s0ma refuses (one root inside the other) on nearly every real
        # tree.
        holds_source = [
            source for source in sources if source.role in (_ROLE_APP, _ROLE_PACKAGE_MARKER)
        ]
        roots = sorted({source.source_root for source in holds_source})
        if not roots:
            roots = sorted(
                {source.source_root for source in sources if source.role != _ROLE_TEST}
            )
        if not roots:
            roots = ["."]

    bootstrap = sorted(
        {
            source.path
            for source in sources
            if source.role == _ROLE_SCRIPT or _basename(source.path) == "__main__.py"
        }
    )
    markers = sorted(source.path for source in sources if source.role == _ROLE_PACKAGE_MARKER)

    notes: list[str] = []
    if not sources:
        notes.append(
            "No Python files were found here, so there is nothing to set a perimeter "
            "around yet — check that this is the right directory."
        )
    if "." in roots and len(roots) > 1:
        others = _join([f"`{root}`" for root in roots if root != "."])
        notes.append(
            f"Some application files sit in the project directory itself and others under "
            f"{others}. s0ma refuses source roots that sit inside one another, so decide "
            f"which directory holds the code — and move the stragglers into it — before "
            f"running `s0ma adopt init`."
        )
    elif roots == ["."] and any(source.role == _ROLE_TEST for source in sources):
        notes.append(
            "The source root comes out as the project directory itself, because there is "
            "no separate directory holding the code. s0ma refuses a source root and a "
            "test root when one sits inside the other, so `s0ma adopt init` will declare "
            "no test roots at all — and the test files here will keep counting as "
            "unconverted for as long as that lasts. Moving the application code into a "
            "directory of its own (`src/`, say) is what lets the tests be named."
        )
    working_markers = [
        source
        for source in sources
        if source.role == _ROLE_APP and _basename(source.path) == "__init__.py"
    ]
    notes.extend(
        _marker_note(source.path, censuses_by_path.get(source.path))
        for source in sorted(working_markers, key=lambda source: source.path)
    )

    return PerimeterSuggestion(
        source_roots=tuple(roots),
        bootstrap_files=tuple(bootstrap),
        package_markers=tuple(markers),
        mode=PERIMETER_MODE,
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# T4 — effort
# ---------------------------------------------------------------------------


def _effort_points(census: ModuleCensus, *, in_cycle: bool) -> int:
    """How much work one module looks like, in points, from four visible facts."""
    points = 0
    if census.sloc > _SLOC_MEDIUM:
        points += 2
    elif census.sloc > _SLOC_SMALL:
        points += 1
    if len(census.entities) > _ENTITIES_MEDIUM:
        points += 2
    elif len(census.entities) > _ENTITIES_SMALL:
        points += 1
    if census.top_level_effects > _EFFECTS_MEDIUM:
        points += 2
    elif census.top_level_effects > 0:
        points += 1
    if in_cycle:
        points += 1
    if census.parse_error is not None:
        # Nothing could be read, so nothing can be sized: a file that
        # does not parse has to be opened by a person first.
        points += 2
    return points


def _band(points: int) -> str:
    """The band *points* falls in."""
    if points <= _BAND_SMALL_CEILING:
        return _BAND_SMALL
    if points <= _BAND_MEDIUM_CEILING:
        return _BAND_MEDIUM
    return _BAND_LARGE


def estimate_effort(censuses: Sequence[ModuleCensus], graph: GraphFacts) -> EffortEstimate:
    """Size every module's conversion, in bands rather than hours.

    Covers the same modules as :func:`propose` — non-test, one per dotted
    name — so the two can be printed side by side without a reader
    wondering why a row is missing.

    The bands are a sorting aid. :data:`EFFORT_BASIS` is carried in the
    estimate and says so in one sentence, because a number beside a
    module name is read as a promise unless it says otherwise.
    """
    conversion = _conversion_censuses(censuses)
    tangled = {module for cycle in graph.cycles for module in cycle}

    per_module = tuple(
        (
            census.source.module,
            _band(_effort_points(census, in_cycle=census.source.module in tangled)),
        )
        for census in conversion
    )
    counts = Counter(band for _, band in per_module)
    bands = tuple((band, counts.get(band, 0)) for band in _BAND_ORDER)
    return EffortEstimate(
        bands=bands,
        per_module=tuple(sorted(per_module)),
        basis=EFFORT_BASIS,
    )


# ---------------------------------------------------------------------------
# T5 — name collisions with the framework's own components
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def framework_component_names() -> frozenset[str]:
    """Every name s0ma's own framework components already occupy.

    Read from core the way core reads it itself: a fresh
    ``ComponentRegistry(persist=False)`` with ``bootstrap_register``
    called on it, which is the same two lines
    ``s0ma_dsl.docs_model.inventories`` uses to hold the docs corpus to
    core's ``EXPECTED_FRAMEWORK_COMPONENT_COUNT``. A registry bootstrap
    and nothing more: no database file (``persist=False``), no printing,
    no import hook, and — the point of doing it this way — no static copy
    of the list in this file that would drift the first time core gains a
    component.

    It costs one import of core plus the bootstrap, tens of milliseconds
    once per process, and the result is cached. The scanned project is
    never imported: these are s0ma's names, read from s0ma.
    """
    from s0ma._bootstrap import bootstrap_register
    from s0ma.registry import ComponentRegistry

    registry = ComponentRegistry(persist=False)
    bootstrap_register(registry)
    return frozenset(registry.get_all())


def _collision_message(name: str) -> str:
    """One plain sentence about a name the framework has already taken."""
    return (
        f"This module defines `{name}`, which is also the name of one of s0ma's own "
        f"building blocks. Registered components share one set of names, so two things "
        f"called `{name}` cannot both exist — rename yours before converting this module "
        f"(something that says whose it is, like `Order{name}`, usually does it)."
    )


def collision_warnings(censuses: Sequence[ModuleCensus]) -> tuple[ScanWarning, ...]:
    """Warn about names the framework's own components have already taken.

    Converting a module registers what it declares, and registered
    components share a single set of names across the framework and the
    project together. A project with its own ``Contract`` or
    ``QueryEngine`` finds that out at registration time, in a message
    about the registry rather than about their code; finding out at scan
    time, before anything has been converted, is the whole point of
    rung 0.

    One warning per colliding definition, sorted by module and then by
    name. Every top-level definition is checked, not only the public
    ones: an INTERNAL component is registered under its name too.
    """
    taken = framework_component_names()
    warnings: list[tuple[str, str]] = []
    for census in _conversion_censuses(censuses):
        for name in sorted({entity.name for entity in census.entities if entity.name in taken}):
            warnings.append((census.source.module, name))
    return tuple(
        ScanWarning(
            code=WARNING_NAME_COLLISION,
            module=module,
            message=_collision_message(name),
        )
        for module, name in sorted(warnings)
    )
