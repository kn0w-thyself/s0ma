"""Stable identity for everything the documentation model addresses.

One table of anchored patterns — :data:`ID_FORMS` — and the handful of
functions that validate, normalize and build ids against it. Every form
frozen by the docs-function plan (internal) §5, as corrected and ratified at
the B gate on 2026-08-29, is here with the note that says what its edges
are and why.

Identity is the model's only join key: a concept, a served capability, a
journey, a catalog row and a citation address each other by id and by
nothing else. An id that *nearly* matches a form is therefore worse than
one that plainly does not, and every refusal below names the form it
expected and says what to write instead.

The refusals a person will actually meet:

* A flat component name. Four packages register components into one
  registry, so a flat name can mean two different components; the model
  requires the package-qualified form and says so by name.
* Two colons after ``example``. ``example::name`` is the authoring syntax
  for an entity reference inside prose and it already appears in written
  guides; ``example:name`` is a topic id. One character apart, so the
  doubled form is refused explicitly rather than left to fail silently.
* A leading slash on a studi0 route. The id drops it, the served name
  keeps it, and :func:`normalize_id` is the one place that happens.
* studi0's root route spelled as the slash the id form drops, which
  leaves nothing to address. The root is ``studi0:action/index`` — the
  second documented normalization, and the same function performs it.

Three forms here are **not** in the §5 frozen set: ``sequence:``,
minted by C1, and ``python:`` and ``config:``, completed by D5a. Each
says so in its own note, and each says what it was completed for.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.records import AUTHORITY_ORDER, DocsModelError

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "ID_CLASSES",
    "ID_FORMS",
    "AliasIndex",
    "DocsIdError",
    "IdForm",
    "cli_id",
    "id_form",
    "is_valid_id",
    "normalize_id",
    "same_identity",
    "studi0_action_id",
    "studi0_public_name",
    "validate_id",
]


class DocsIdError(DocsModelError):
    """An id does not match any form the model addresses things by."""


# ---------------------------------------------------------------------------
# Pattern pieces
# ---------------------------------------------------------------------------

#: A lowercase hyphenated word: ``first-project``, ``drift``.
_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"

#: A plain name, for the dotted segments of a component id.
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"

#: A lowercase name that may carry hyphens and slashes: ``docs/render``.
_PATH = r"[a-z0-9_]+(?:[-/][a-z0-9_]+)*"

#: The same, with a dot admitted as a separator too: ``assets/app.css``.
#: A served route's last segment is a filename, and a filename has a
#: suffix. Kept as a second piece rather than folded into :data:`_PATH`
#: on purpose — only the studi0 form has a demonstrated need for the
#: dot, and widening the tool, prompt and example forms at the same time
#: would ratify three charsets nobody asked for. Like :data:`_PATH`, it
#: admits a dot only *between* word chunks, so a leading dot, a trailing
#: dot and a doubled dot are all still refused.
_ROUTE_PATH = r"[a-z0-9_]+(?:[-/.][a-z0-9_]+)*"

#: The methods the self-description interface serves, spelled its way.
_METHOD = r"GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS"

#: A diagnostic code: capitals, digits and underscores, starting with a
#: letter. Single-word codes are accepted because the product has them.
_CODE = r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*"

_AUTHORITY_CLASS = "|".join(AUTHORITY_ORDER)

_STUDI0_PREFIX = "studi0:action/"

#: How studi0's root route is spelled once the leading slash is dropped.
#: ``/`` is *entirely* the slash the id form drops, so the stripped form
#: is empty and empty addresses nothing. The convention is a documented
#: normalization of exactly the kind the leading-slash strip already is:
#: the id is ``studi0:action/index``, the ``public_name`` stays ``/``,
#: and :func:`normalize_id` is the one place the map is applied — so an
#: identity gate that compares normalized ids compares through it. The
#: word is ``index`` because that is what the web has called the
#: document served at a directory's root since before this product, and
#: because it stays inside the frozen ``studi0:action/<path>`` shape
#: rather than inventing a spelling beside it. The cost is that a
#: literal ``/index`` route would want the same id;
#: :func:`studi0_action_id` refuses that route by name rather than
#: letting two routes share one id.
_STUDI0_ROOT = "index"


@dataclass(frozen=True)
class IdForm:
    """One addressable form: its name, its kind word, its pattern, its edges."""

    name: str
    class_word: str
    pattern: re.Pattern[str]
    note: str


#: Every form the model addresses something by. Anchored at both ends and
#: mutually exclusive — an id matches one form or none. Order affects
#: reporting only.
ID_FORMS: tuple[IdForm, ...] = (
    IdForm(
        "component",
        "component",
        re.compile(rf"^component:{_IDENT}(?:\.{_IDENT})+$"),
        "Package-qualified and never flat: component:<package>.<module>.<name>. "
        "Four packages register components into one registry and a flat name "
        "collides across them, so a name with fewer than two dotted segments "
        "is refused. Two is the floor rather than three because the package "
        "name is the half that answers the collision: s0ma_mcp.create_server "
        "is a real registration whose qualified name is package-flat, and "
        "refusing it addressed nothing while leaving two of that package's "
        "components uncountable.",
    ),
    IdForm(
        "python",
        "python",
        re.compile(rf"^python:{_IDENT}(?:\.{_IDENT})+$"),
        "A module-level callable or constant of a package's public API, "
        "addressed by the import path a caller writes: python:s0ma.verify. "
        "Package-qualified for the component form's reason and refused with "
        "one segment. NOT part of the §5 frozen set: completed by D5a for "
        "the names a package exports that no registration reaches — C3 "
        "counted core's, could not address them, and pinned the gap.",
    ),
    IdForm(
        "concept",
        "concept",
        re.compile(rf"^concept:{_SLUG}$"),
        "A taught idea, addressed by its term as a lowercase hyphenated "
        "slug: concept:self-knowledge.",
    ),
    IdForm(
        "cli",
        "cli",
        re.compile(rf"^cli:s0ma/{_SLUG}(?:/{_SLUG})*$"),
        "A command path, not a single word: nested commands join with a "
        "slash, so cli:s0ma/docs/render addresses the render command under "
        "docs. Roughly a third of the registered commands are nested.",
    ),
    IdForm(
        "mcp_tool",
        "mcp",
        re.compile(rf"^mcp:tool/{_PATH}$"),
        "A served agent tool, addressed by the name the agent calls.",
    ),
    IdForm(
        "mcp_resource",
        "mcp",
        re.compile(r"^mcp:resource/[a-z0-9_]+://[A-Za-z0-9_./{}-]+$"),
        "A served agent resource, addressed by its whole address including "
        "the scheme: mcp:resource/s0ma://guide/errors. A resource template "
        "keeps its braces — mcp:resource/s0ma://model/docs-for/{component} — "
        "because the rest form already addresses a parameterized served "
        "address that way and a second convention for one problem is the "
        "drift this model exists against. Stripping them instead would give "
        "a template and a literal resource of the brace-free address the "
        "same id, which is why D3 asked for the character class rather than "
        "a normalization.",
    ),
    IdForm(
        "mcp_prompt",
        "mcp",
        re.compile(rf"^mcp:prompt/{_PATH}$"),
        "A served agent prompt, addressed by the name the agent asks for.",
    ),
    IdForm(
        "rest",
        "rest",
        re.compile(rf"^rest:(?:{_METHOD}):/[A-Za-z0-9_./{{}}-]*$"),
        "A route of the self-description interface: the method in capitals, "
        "then the path with its braces intact, as in "
        "rest:GET:/self/component/{name}.",
    ),
    IdForm(
        "studi0",
        "studi0",
        re.compile(rf"^studi0:action/{_ROUTE_PATH}$"),
        "A studi0 route or viewer action. The id drops the leading slash and "
        "the served name keeps it, so the route /api/graph is addressed as "
        "studi0:action/api/graph and identity comparisons run on the "
        "stripped form. Two documented normalizations, both performed by "
        "normalize_id and by nothing else: that slash, and the root route — "
        "which is nothing *but* that slash — addressed as "
        "studi0:action/index while its public_name stays /. A segment may "
        "carry a dot, because an asset route's last segment is a filename "
        "and app.css is its name rather than a word to be repaired.",
    ),
    IdForm(
        "example",
        "example",
        re.compile(rf"^example:{_PATH}$"),
        "A registered runnable example. One colon, always: the doubled form "
        "is the authoring syntax for an entity reference inside prose and "
        "appears in written guides today, so it is refused explicitly "
        "rather than merely failing to match.",
    ),
    IdForm(
        "diagnostic",
        "diagnostic",
        re.compile(rf"^diagnostic:{_CODE}$"),
        "A diagnostic the product can emit, addressed by its code in "
        "capitals with underscores, exactly as the code is registered.",
    ),
    IdForm(
        "config",
        "config",
        re.compile(r"^config:[a-z][a-z0-9_]*$"),
        "One key of the [tool.s0ma] table, addressed exactly as an author "
        "writes it: lowercase with underscores, config:build_dir. NOT part "
        "of the §5 frozen set: completed by D5a for the key set D2 reads "
        "out of the project loader, which minted the form locally and "
        "escalated it because ids.py was not that milestone's to edit.",
    ),
    IdForm(
        "journey",
        "journey",
        re.compile(rf"^journey:{_SLUG}$"),
        "An authored path through several surfaces: journey:first-project.",
    ),
    IdForm(
        "sequence",
        "sequence",
        re.compile(rf"^sequence:{_SLUG}$"),
        "An ordered teaching sequence over topics. NOT part of the §5 frozen "
        "set: minted by C1 because the ratified teaching-sequence record "
        "needs an addressable id and no frozen form fits one — a journey "
        "resolves against surfaces, and a catalog row throws order away. "
        "Raised at the C gate for ratification, the way the B gate ratified "
        "the example and diagnostic forms.",
    ),
    IdForm(
        "doc",
        "doc",
        re.compile(rf"^doc:{_SLUG}/{_SLUG}$"),
        "A document in the catalog, addressed by category and slug: "
        "doc:normative/prd.",
    ),
    IdForm(
        "authority",
        "authority",
        re.compile(rf"^authority:(?:{_AUTHORITY_CLASS})/[A-Za-z0-9][A-Za-z0-9._-]*$"),
        "A written authority, addressed by its class and a stable name. The "
        "class segment must be one of the ranked classes, and it is the "
        "segment a gate compares against the record's own class field.",
    ),
)

#: The distinct kind words an id may start with, sorted for reporting.
ID_CLASSES: tuple[str, ...] = tuple(sorted({form.class_word for form in ID_FORMS}))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def id_form(identifier: str) -> str | None:
    """The name of the form ``identifier`` matches, or ``None`` for none."""
    for form in ID_FORMS:
        if form.pattern.match(identifier):
            return form.name
    return None


def is_valid_id(identifier: str) -> bool:
    """Does ``identifier`` match a form the model addresses things by?"""
    return id_form(identifier) is not None


def validate_id(identifier: str) -> str:
    """Return the form ``identifier`` matches, or refuse it by name.

    The refusal says what was expected, because an id one character away
    from correct is the failure this model actually produces.
    """
    matched = id_form(identifier)
    if matched is not None:
        return matched
    raise DocsIdError(_diagnose(identifier))


def _diagnose(identifier: str) -> str:
    """A plain-language account of why ``identifier`` matches no form."""
    if not identifier:
        return "an empty id addresses nothing; write the id of the thing you mean"

    kind, separator, remainder = identifier.partition(":")
    kinds = ", ".join(ID_CLASSES)

    if not separator:
        return (
            f"{identifier!r} names no kind of thing. An id starts with its "
            f"kind and a colon, one of: {kinds}."
        )

    if kind == "component":
        if len(remainder.split(".")) < 2:
            return (
                f"{identifier!r} is a flat component name. Components are "
                f"addressed package-qualified, as "
                f"component:<package>.<module>.<name> — for example "
                f"component:s0ma.api.query_engine.QueryEngine. Four packages "
                f"share one registry, so a flat name can mean two different "
                f"components."
            )
        return (
            f"{identifier!r} is not a component id. Every dotted segment has "
            f"to be a plain name: component:<package>.<module>.<name>."
        )

    if kind == "python":
        if len(remainder.split(".")) < 2:
            return (
                f"{identifier!r} is a bare name. A module-level export is "
                f"addressed by the import path a caller writes, package "
                f"first — python:<package>.<name>, as in python:s0ma.verify."
            )
        return (
            f"{identifier!r} is not a python id. Every dotted segment has to "
            f"be a plain name: python:<package>.<module>.<name>."
        )

    if remainder.startswith(":"):
        if kind == "example":
            return (
                f"{identifier!r} uses two colons. A topic reference to an "
                f"example takes one — example:{remainder.lstrip(':')} — "
                f"because the doubled form is the authoring syntax for an "
                f"entity reference inside prose, which is a different thing."
            )
        return f"{identifier!r} uses two colons after {kind!r}. An id takes one."

    if kind == "diagnostic":
        return (
            f"{identifier!r} is not a diagnostic id. A diagnostic is "
            f"addressed by its code in capitals with underscores, exactly as "
            f"the code is registered — diagnostic:PARSE_ERROR, for one."
        )

    if identifier.startswith(_STUDI0_PREFIX):
        route = identifier[len(_STUDI0_PREFIX) :]
        if route.lstrip("/") == "":
            return (
                f"{identifier!r} addresses studi0's root route by the slash "
                f"the id form drops, which leaves nothing to address. The "
                f"root is {_STUDI0_PREFIX + _STUDI0_ROOT!r} — a documented "
                f"normalization, like the leading-slash strip — and its "
                f"served name stays '/'."
            )
        if route.startswith("/"):
            return (
                f"{identifier!r} keeps the route's leading slash. The id "
                f"drops it — {normalize_id(identifier)!r} — while the served "
                f"name keeps it. Normalize before comparing or storing."
            )

    if kind == "cli" and not remainder.startswith("s0ma/"):
        return (
            f"{identifier!r} is not a command id. Commands are addressed "
            f"under the program name and join their path with slashes: "
            f"cli:s0ma/docs/render."
        )

    if kind not in ID_CLASSES:
        return (
            f"{identifier!r} names {kind!r}, which is not a kind of thing "
            f"this model addresses. The kinds are: {kinds}."
        )

    note = next(form.note for form in ID_FORMS if form.class_word == kind)
    return f"{identifier!r} does not match the {kind} form. {note}"


# ---------------------------------------------------------------------------
# Normalization and construction
# ---------------------------------------------------------------------------


def normalize_id(identifier: str) -> str:
    """The comparable form of ``identifier``.

    Exactly two transformations, both of them documented conventions of the
    studi0 form and neither of them applied anywhere else: an action id
    drops the route's leading slash, and the root route — whose whole path
    *is* that slash — is addressed as ``studi0:action/index``. Both spellings
    of the root (``studi0:action/`` and ``studi0:action//``) land on the same
    id, so an identity gate that compares normalized ids compares through the
    map rather than around it.

    Everything else is returned unchanged — trimming or lowercasing an id
    here would hide an authoring mistake the model would rather refuse.

    Normalization does not validate. Normalize, then validate.
    """
    if identifier.startswith(_STUDI0_PREFIX):
        route = identifier[len(_STUDI0_PREFIX) :]
        if route.startswith("/"):
            route = route[1:]
        return _STUDI0_PREFIX + (route or _STUDI0_ROOT)
    return identifier


def same_identity(left: str, right: str) -> bool:
    """Do two ids address the same thing once normalized?"""
    return normalize_id(left) == normalize_id(right)


def cli_id(*command_path: str) -> str:
    """The id of a command, from its path: ``cli_id("docs", "render")``.

    Joining is the point of the form — a nested command is addressed by its
    whole path, not by its last word.
    """
    if not command_path:
        raise DocsIdError("a command id needs at least one path segment")
    identifier = "cli:s0ma/" + "/".join(command_path)
    validate_id(identifier)
    return identifier


def studi0_action_id(route: str) -> str:
    """The id of a studi0 route, from the route as it is served.

    ``/api/graph`` becomes ``studi0:action/api/graph`` and ``/`` becomes
    ``studi0:action/index``. Exactly one leading slash is dropped; a doubled
    slash is a malformed route and is refused rather than silently repaired.

    A literal ``/index`` route is refused by name. It would want the id the
    root already holds, and two routes sharing one id is worse than a route
    with no id: the second one would silently replace the first in every
    index the model builds.
    """
    trimmed = route[1:] if route.startswith("/") else route
    if trimmed == _STUDI0_ROOT:
        raise DocsIdError(
            f"the route {route!r} wants the id studi0's root route already "
            f"holds — {_STUDI0_PREFIX + _STUDI0_ROOT!r}, the documented "
            f"spelling of '/'. Serve it under another name, or change the "
            f"root convention here rather than letting two routes share one "
            f"id."
        )
    identifier = _STUDI0_PREFIX + (trimmed or _STUDI0_ROOT)
    validate_id(identifier)
    return identifier


def studi0_public_name(identifier: str) -> str:
    """The served name of a studi0 action id: the route as it is served.

    The inverse of :func:`studi0_action_id`, both conventions included:
    the leading slash is restored, and ``studi0:action/index`` gives back
    the root ``/`` rather than a route studi0 does not serve.
    """
    if not identifier.startswith(_STUDI0_PREFIX):
        raise DocsIdError(f"{identifier!r} is not a studi0 action id")
    route = identifier[len(_STUDI0_PREFIX) :]
    return "/" if route == _STUDI0_ROOT else "/" + route


# ---------------------------------------------------------------------------
# Aliases and supersession
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AliasIndex:
    """Old ids mapped to the ids that replace them.

    Renames happen: a command is regrouped, a concept's term settles, a
    served resource is superseded but stays served. The model keeps the old
    id addressable by mapping it forward, rather than by leaving two
    records that both claim to be the thing.

    No record type carries an alias field in this version — concept aliases
    arrive with search at F6 and served aliases with the agent read surface
    at F7. This index is the resolution those milestones feed: supply the
    pairs, resolve through them.
    """

    entries: tuple[tuple[str, str], ...]

    @classmethod
    def of(cls, pairs: Mapping[str, str] | Iterable[tuple[str, str]]) -> AliasIndex:
        """Build an index, sorted so two equal indexes serialize alike."""
        items = pairs.items() if isinstance(pairs, Mapping) else pairs
        return cls(entries=tuple(sorted((old, new) for old, new in items)))

    def canonical(self, identifier: str) -> str:
        """Follow ``identifier`` to the id that survives.

        Chains are followed, so an id renamed twice resolves to its current
        name in one call. A circle is refused: it means two records each
        claim the other replaced them, and no answer to that is honest.
        """
        forward = dict(self.entries)
        seen = [identifier]
        current = identifier
        while current in forward:
            current = forward[current]
            if current in seen:
                trail = " -> ".join([*seen, current])
                raise DocsIdError(
                    f"these ids replace each other in a circle, so none of "
                    f"them is the current one: {trail}"
                )
            seen.append(current)
        return current
