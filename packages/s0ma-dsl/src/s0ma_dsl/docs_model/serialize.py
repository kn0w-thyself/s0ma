"""Canonical serialization and content hashing for the documentation model.

One byte-form per bundle, and one digest form. Both matter more than they
look: the documentation build commits its output, several channels render
from the same records and must be comparable, and two providers that derive
one truth from two sources have to be recognizable as agreeing. All three
rest on the same guarantee — the same records serialize to the same bytes,
on any platform, in any process.

What makes that true here:

* keys sorted, so no dictionary's insertion order and no hash seed can
  reach the output;
* record groups sorted by id, so provider order and merge order cannot
  reach it either;
* line feeds and one trailing newline, written explicitly rather than
  inherited from the platform;
* no decimal numbers anywhere — :func:`to_plain` refuses one rather than
  emit a value whose written form varies between runtimes;
* no timestamps: the only build facts recorded are the release version and
  the snapshot digest, both on the stamp.

The digest form is the house one — ``sha256:`` and the first sixteen hex
characters — the same shape the transpiler stamps into generated modules,
so a reader who has seen one has seen both.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import fields
from typing import Any, TypeVar, get_args, get_origin, get_type_hints

from s0ma_dsl.docs_model.records import (
    PREVIEW_CHANNEL,
    SCHEMA,
    BuildStamp,
    DocsBundle,
    DocsModelError,
    validate_schema_version,
)

__all__ = [
    "DIGEST_CHARS",
    "DIGEST_PREFIX",
    "DocsSerializationError",
    "canonical_json",
    "content_hash",
    "deserialize_bundle",
    "facts_hash",
    "record_from_plain",
    "serialize_bundle",
    "snapshot_hash",
    "stamped",
    "to_plain",
]

#: The house digest form: this prefix plus the first :data:`DIGEST_CHARS`
#: hex characters of a sha256.
DIGEST_PREFIX = "sha256:"
DIGEST_CHARS = 16

#: The bundle's record groups, in the order they are declared. The stamp is
#: not among them: it describes the build, not the records, and the digest
#: of the records must not depend on the digest of the records.
#:
#: ``aliases`` is not among them either, for a different reason (F9). An
#: alias states no fact: it says that a question spelled one way is the
#: question already answered under another id. The snapshot digest is the
#: identity of what a build *says*, so widening the ways of asking must not
#: re-stamp every page that says the same thing it said before. Aliases are
#: still written into the snapshot — see :func:`serialize_bundle` — and the
#: committed file is byte-gated, so a change to them is still caught; it is
#: caught as the file change it is rather than as a false claim that the
#: knowledge moved.
_GROUPS = (
    "authorities",
    "concepts",
    "surfaces",
    "journeys",
    "sequences",
    "documents",
)

#: The bundle's one non-record group, written beside the stamp.
_ALIASES = "aliases"

T = TypeVar("T")


class DocsSerializationError(DocsModelError):
    """A value cannot be written to, or read from, the canonical form."""


# ---------------------------------------------------------------------------
# Records to data
# ---------------------------------------------------------------------------


def to_plain(value: Any) -> Any:
    """Records to data a JSON writer accepts. Tuples become lists, in order.

    Decimal numbers are refused rather than written. Nothing in the model
    is one, and a decimal that appeared would print differently on
    different runtimes — exactly the class of drift this serializer exists
    to make impossible.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {item.name: to_plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple | list):
        return [to_plain(item) for item in value]
    if isinstance(value, bool | str) or value is None:
        return value
    if isinstance(value, float):
        raise DocsSerializationError(
            "the documentation model does not carry decimal numbers, because "
            "their written form varies between runtimes; record the value as "
            "text instead"
        )
    if isinstance(value, int):
        return value
    raise DocsSerializationError(f"a value of type {type(value).__name__} cannot be written")


def canonical_json(document: Any) -> str:
    """The one text form a documentation document may have.

    Sorted keys make key order irrelevant on the way in; two-space
    indentation keeps a committed build readable in review; non-ASCII stays
    as itself so authored prose reads as written; the text ends with
    exactly one line feed.
    """
    return json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def _digest(text: str) -> str:
    return DIGEST_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()[:DIGEST_CHARS]


def content_hash(value: Any) -> str:
    """The digest of anything the model can serialize.

    Everything the value carries is covered, provenance included. Two
    records with this same digest are the same record.
    """
    return _digest(canonical_json(to_plain(value)))


def facts_hash(record: Any) -> str:
    """The digest of what a record *claims*, ignoring where it was read.

    This is the comparison the merge rule needs. Two providers deriving one
    truth from two sources produce records with different provenance and
    identical facts; on this digest they agree, so the composition keeps
    one record instead of reporting a conflict that does not exist. Two
    providers that disagree about the facts still differ here, and that is
    a build error.

    Only the record's own provenance is set aside. Every other field, and
    every nested record, is covered.
    """
    plain = to_plain(record)
    if isinstance(plain, dict):
        plain = {key: item for key, item in plain.items() if key != "provenance"}
    return _digest(canonical_json(plain))


def snapshot_hash(bundle: DocsBundle) -> str:
    """The digest of every record in ``bundle``, ignoring its stamp.

    A documentation snapshot identifies a build: two topics rendered from
    one build carry one snapshot digest, and any record moving re-stamps
    every page. The stamp is excluded because the stamp is where this
    digest is about to be written.
    """
    # Groups are sorted here, at the source, so a hand-built bundle with
    # unsorted tuples cannot produce an order-dependent digest (compose
    # sorts too; this makes the digest safe without it).
    return _digest(
        canonical_json(
            {
                name: sorted(
                    (to_plain(record) for record in getattr(bundle, name)),
                    key=canonical_json,
                )
                for name in _GROUPS
            }
        )
    )


def stamped(
    bundle: DocsBundle,
    release_version: str,
    *,
    build_channel: str = PREVIEW_CHANNEL,
) -> DocsBundle:
    """``bundle`` with its stamp filled in for this release.

    The one supported way to build a stamp, so the model version and the
    snapshot digest cannot disagree with the records they describe.

    ``build_channel`` defaults to preview (H1, architecture §13.2). A
    caller that does not say which channel it is building has not
    established that it is building a release, and defaulting the other
    way would make every unconfigured build claim to be one. It reaches
    the stamp and not the digest: see
    :func:`snapshot_hash`.
    """
    return dataclasses.replace(
        bundle,
        stamp=BuildStamp(
            schema=SCHEMA,
            release_version=release_version,
            snapshot_hash=snapshot_hash(bundle),
            build_channel=build_channel,
        ),
    )


# ---------------------------------------------------------------------------
# Bundles out
# ---------------------------------------------------------------------------


def _sorted_group(records: tuple[Any, ...]) -> list[Any]:
    """One group's records as data, ordered by id.

    Sorting here is what makes the output independent of the order the
    providers ran in, and of the order a merge happened to produce.
    """
    return [to_plain(record) for record in sorted(records, key=lambda record: record.id)]


def serialize_bundle(bundle: DocsBundle) -> str:
    """``bundle`` as its canonical text.

    The schema version appears once, on the stamp. No record carries a copy
    of it, or of any other fact about the build.

    The alias table is written like a record group — sorted by id, each
    entry in full — and read back the same way, so a snapshot carries every
    way of asking that the build it came from knew about. That is what
    makes an installed wheel answer to an alternate term at all: before
    F9 the pairs never left the checkout, and a reader who arrived holding
    an older word got a miss from every served channel.
    """
    validate_schema_version(bundle.stamp.schema)
    document: dict[str, Any] = {name: _sorted_group(getattr(bundle, name)) for name in _GROUPS}
    document[_ALIASES] = _sorted_group(bundle.aliases)
    document["stamp"] = to_plain(bundle.stamp)
    return canonical_json(document)


# ---------------------------------------------------------------------------
# Bundles in
# ---------------------------------------------------------------------------

_HINTS: dict[type[Any], dict[str, Any]] = {}


def _hints(record_type: type[Any]) -> dict[str, Any]:
    """The resolved annotations of a record type, worked out once."""
    cached = _HINTS.get(record_type)
    if cached is None:
        cached = get_type_hints(record_type)
        _HINTS[record_type] = cached
    return cached


def _coerce(annotation: Any, value: Any, where: str) -> Any:
    """One field's data, checked against the field's declared type."""
    if annotation is str:
        if not isinstance(value, str):
            raise DocsSerializationError(f"{where}: expected text, got {type(value).__name__}")
        return value
    if get_origin(annotation) is tuple:
        args = get_args(annotation)
        if len(args) != 2 or args[1] is not Ellipsis:
            raise DocsSerializationError(f"{where}: unsupported field type {annotation!r}")
        if not isinstance(value, list):
            raise DocsSerializationError(f"{where}: expected a list, got {type(value).__name__}")
        return tuple(
            _coerce(args[0], item, f"{where}[{index}]") for index, item in enumerate(value)
        )
    if dataclasses.is_dataclass(annotation) and isinstance(annotation, type):
        return record_from_plain(annotation, value, where)
    raise DocsSerializationError(f"{where}: unsupported field type {annotation!r}")


def _defaulted(record_type: type[Any]) -> frozenset[str]:
    """The fields of ``record_type`` that declare a default.

    These are exactly the fields a document may leave out, because they
    are exactly the fields that were added inside ``@1`` — the model's
    additive rule (``records`` property 2) makes a default the price of
    adding a field at all.
    """
    return frozenset(
        item.name
        for item in fields(record_type)
        if item.default is not dataclasses.MISSING
        or item.default_factory is not dataclasses.MISSING
    )


def record_from_plain(record_type: type[T], raw: Any, where: str) -> T:
    """Build a record from data, refusing any mismatch against its type.

    An unknown key is an error. A reader that tolerated a stray key could
    not promise round-trip stability, because the stray key would vanish on
    the way back out — and a build that silently drops what an author wrote
    is the failure this whole model is against.

    A *missing* key is an error too, unless the field declares a default.
    That exception is what makes ``@1``'s additive rule real rather than
    aspirational: a field added inside the version must default, and a
    document written before it was added has to stay readable or the
    addition is a schema revision wearing a smaller word. The writer always
    emits every field, so a document this module produced round-trips
    exactly; a document that omits a defaulted field is normalized to the
    default on the way in and written out in full on the way back.
    """
    if not isinstance(raw, dict):
        raise DocsSerializationError(f"{where}: expected an object, got {type(raw).__name__}")
    declared = {item.name for item in fields(record_type)}  # type: ignore[arg-type]
    unknown = sorted(set(raw) - declared)
    missing = sorted(declared - set(raw) - _defaulted(record_type))
    if unknown or missing:
        raise DocsSerializationError(
            f"{where}: does not match {record_type.__name__} "
            f"(unexpected: {unknown}, absent: {missing})"
        )
    hints = _hints(record_type)
    values = {
        name: _coerce(hints[name], raw[name], f"{where}.{name}")
        for name in sorted(declared & set(raw))
    }
    return record_type(**values)


def deserialize_bundle(text: str) -> DocsBundle:
    """Read a bundle back from its canonical text.

    The schema version is checked before anything else, so a document from
    another version of the model is refused for the reason it is actually
    wrong rather than for the first field that happens to differ.

    A snapshot written before F9 carries no ``aliases`` key and is read as
    carrying none, which is the additive rule
    :func:`record_from_plain` states in full.
    """
    document = json.loads(text)
    if not isinstance(document, dict):
        raise DocsSerializationError("a bundle is an object; this text is not one")
    stamp = document.get("stamp")
    if not isinstance(stamp, dict) or "schema" not in stamp:
        raise DocsSerializationError("this bundle carries no build stamp, so it names no version")
    schema = stamp["schema"]
    if not isinstance(schema, str):
        raise DocsSerializationError("the build stamp's schema version is not text")
    validate_schema_version(schema)
    return record_from_plain(DocsBundle, document, "bundle")
