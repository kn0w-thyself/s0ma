"""Derived-source provider registry for ``doc-ref covers: { source: <name> }``.

**Authority:** ``docs/adr/ADR-013-derived-source-registry.md`` (Accepted
2026-08-29). This module is the registry ADR-013 §1 freezes, and it is the
single place a derived source name exists. The parser's allow-list
(``parser/s0ma_parser.py``), all three renderers (``markdown.py``,
``html.py``, ``json_format.py``), and the spec's §4.12.1 enumeration read
from here rather than each maintaining a copy.

Before ADR-013, adding a derived source meant three edits in three files —
an allow-list row plus a renderer branch — of which two (``html.py`` and
``json_format.py``) had no derived handling at all, so a missed edit
produced an empty document rather than a diagnostic. Registration replaces
that: a source is *data plus a provider component*, and adding one touches
no renderer.

Provider purity (ADR-013 §2, frozen)
------------------------------------
Every provider is a registered component that satisfies the architecture
plan's §7.1 adapter contract:

* **input** — immutable; the transpiler's own configuration, or an
  already-composed snapshot handed to it. A provider never goes looking
  for its input. Sources whose records are facts about a *checkout*
  rather than about the toolchain declare ``needs_input`` and are handed
  a :class:`DerivedInput`; :func:`records_for` refuses to call one
  without it rather than letting it find a root of its own.
* **output** — a tuple of normalized records, sorted by a declared key.
* **records** — renderer-independent data. A provider never returns
  markup, never returns a table, never knows what Markdown is. Field
  *kinds* (:class:`DerivedFieldKind`) carry semantics, not presentation;
  each renderer decides how an identifier or an absent value looks.
* **provenance** — provider id + source identity + schema version +
  content hash, on every record set (:class:`DerivedRecordSet`).
* **side effects / network / filesystem writes** — none, forbidden,
  forbidden. Filesystem reads are limited to the immutable input the
  provider is handed; never a path it discovers, and never the
  documentation surface itself (ADR-010's "no docs-on-disk dependency").
* **determinism** — two calls, in one process and across processes and
  operating systems, produce equal records and equal hashes.
* **errors** — structured; never a partial record set, and never an empty
  one standing in for a failure (:func:`records_for` rejects an empty
  record set, ADR-013 §2's "emptiness is a failure, not a result").

Format completeness (ADR-013 §4)
--------------------------------
A source declares which ``doc-ref`` formats it renders in. A ``doc-ref``
whose ``format:`` is outside that set is a check-time error in every
strictness mode, reported as ``DOC_SOURCE_FORMAT_UNSUPPORTED``. The
expectation is all three formats — records are renderer-independent, so a
source that renders in Markdown renders in HTML and JSON by construction.
A narrower declaration is permitted only with a stated
``narrowing_reason``; :func:`register` refuses one without it.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, NoReturn, cast

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = [
    "DOC_SOURCE_FORMAT_UNSUPPORTED",
    "SUPPORTED_DOC_FORMATS",
    "DerivedField",
    "DerivedFieldKind",
    "DerivedInput",
    "DerivedRecordSet",
    "DerivedSource",
    "derived_source_names",
    "lookup_source",
    "records_for",
    "register",
]


#: The diagnostic ADR-013 §4 names for a ``doc-ref`` requesting a format
#: its derived source does not declare. Registered in
#: ``s0ma_dsl.config.SEVERITY_MATRIX`` as an error in every strictness
#: mode, for the same reason ``DOC_RENDER_ERROR`` is unconditional: a doc
#: that cannot produce its declared output is structurally broken, and
#: silently dropping it is the failure mode "no silent failures" exists to
#: prevent. ADR-013 §4's naming boundary: this is a s0ma-dsl diagnostic and
#: must never collide with the application-level ``DOC_*`` names of the
#: architecture plan §11.
DOC_SOURCE_FORMAT_UNSUPPORTED = "DOC_SOURCE_FORMAT_UNSUPPORTED"

#: The formats a ``doc-ref`` can declare. A source's ``formats`` is a
#: subset of this set; the expected declaration is all three.
SUPPORTED_DOC_FORMATS: frozenset[str] = frozenset({"markdown", "html", "json"})


@component(
    name="S0maDSL_DerivedFieldKind",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Semantic kind of one derived-source record field, so renderers can "
        "decide presentation without the provider expressing any."
    ),
    idempotent=True,
    is_framework=True,
)
class DerivedFieldKind(Enum):
    """What a record field *means*, never how it looks.

    ``IDENTIFIER`` marks a machine-facing name (an error code, a command
    path, a tool id): Markdown renders it in backticks, HTML in
    ``<code>``, JSON as a plain string. ``TEXT`` marks prose. The split
    exists so ADR-013 §2's "records, not markup" clause is enforceable —
    a provider that had to emit backticks would silently become a
    Markdown-only source.
    """

    IDENTIFIER = "identifier"
    TEXT = "text"


@component(
    name="S0maDSL_DerivedField",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "One field of a derived source's record schema: its record-schema "
        "name, its human column label, and its semantic kind."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class DerivedField:
    """One column of a derived source's record schema.

    ``name`` is the record-schema key (snake_case, stable, part of the
    source's ``schema_version`` contract). ``label`` is the human-facing
    column heading. ``kind`` drives per-renderer presentation.
    """

    name: str
    label: str
    kind: DerivedFieldKind = DerivedFieldKind.TEXT


@component(
    name="S0maDSL_DerivedRecordSet",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "A derived source's normalized records plus the four provenance "
        "fields ADR-013 requires: provider id, source identity, schema "
        "version, and a content hash over the records themselves."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class DerivedRecordSet:
    """Normalized, renderer-independent records with their provenance.

    ``records`` are positional tuples aligned to ``fields``. A ``None``
    value means *absent* — each renderer decides how absence reads (an
    em-dash in Markdown and HTML, ``null`` in JSON). Providers never
    substitute a display string for absence.

    ``schema_version`` is the **source's own** record-schema version. It
    is emphatically not the doc frontmatter's ``schema_version`` (the IR
    schema version, ``ir.schema.SCHEMA_VERSION``); ADR-013 §3a forbids
    conflating the two in code, in the spec, or in a rendered artifact.
    """

    provider_id: str
    """Registered component identity of the provider that produced this."""

    source_identity: str
    """What was read — precise enough to re-derive the records."""

    schema_version: str
    """The source's own record-schema version (never the IR schema's)."""

    sort_key: str
    """Name of the field ``records`` is sorted by (the declared key)."""

    fields: tuple[DerivedField, ...]
    """The record schema, in declared order."""

    records: tuple[tuple[str | None, ...], ...]
    """Rows, each aligned positionally to :attr:`fields`."""

    content_hash: str
    """``1:<sha256>`` over the normalized records — never over a rendering."""

    def field_names(self) -> tuple[str, ...]:
        """Record-schema field names in declared order."""
        return tuple(f.name for f in self.fields)

    def as_mappings(self) -> tuple[dict[str, str | None], ...]:
        """Rows as name-keyed dictionaries, for the JSON renderer."""
        names = self.field_names()
        return tuple(dict(zip(names, row, strict=True)) for row in self.records)


@component(
    name="S0maDSL_DerivedInput",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "The immutable input a derived source about a checkout is handed by "
        "its caller, so no provider has to go looking for a repository root."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class DerivedInput:
    """What a checkout-scoped derived source is given to read.

    Three of the nine sources ADR-013 §8 lists are facts about the
    *toolchain* — the error codes it can emit, the commands it serves —
    and read nothing but themselves. Three are facts about a *checkout*:
    what documents it catalogs, what distributions it ships, what
    authorities it declares. The second kind needs a root, and ADR-013 §2
    is explicit that a provider may read "an already-composed snapshot
    handed to the provider by its caller" and never "a path it discovers".
    This is that hand-off, given a type so the difference is declared in
    the registry rather than hidden inside a provider.

    ``root`` is a checkout directory. What lives under it is the caller's
    claim, not this type's: a provider that is handed the wrong tree
    fails on the file it cannot read, loudly, in one place.
    """

    root: Path


@component(
    name="S0maDSL_DerivedSource",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "One registry row: a derived source name bound to its provider "
        "component, the doc-ref formats it renders in, and its record-schema "
        "version."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class DerivedSource:
    """A registered derived source.

    ``name`` means one thing forever (ADR-013 §1): renaming a source, or
    reusing a retired name for different records, is a breaking change
    needing the spec sentence edited, an ADR amendment, and the usual
    deprecation courtesy to consumer projects whose ``.s0ma`` sources
    name it.
    """

    name: str
    provider: Callable[[], DerivedRecordSet] | Callable[[DerivedInput], DerivedRecordSet]
    formats: frozenset[str]
    schema_version: str
    intent: str
    narrowing_reason: str | None = None
    """Why ``formats`` is narrower than all three — required when it is."""

    needs_input: bool = False
    """Whether the provider is handed a :class:`DerivedInput`.

    Declared on the registry row rather than discovered at call time, so
    "this source describes a checkout" is a fact a reader of the registry
    can see. :func:`register` checks it against the provider's actual
    arity: a mismatch is a registration error, not a ``TypeError`` at
    render time in somebody else's build.
    """


_REGISTRY: dict[str, DerivedSource] = {}

#: Stand-in argument :func:`register` binds against a provider's signature
#: to check the ``needs_input`` declaration. Binding rather than counting
#: parameters is deliberate: a provider written with a default argument —
#: which several test stubs are, to close over a mutable value — takes one
#: parameter and is still callable with none, and a naive count would
#: refuse it for a shape that works.
_ARITY_PROBE = object()


@component(
    name="S0maDSL_register_derived_source",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Add one derived source to the registry, enforcing the ADR-013 "
        "registration invariants (unique snake_case name, known formats, a "
        "stated reason for any narrowed format set)."
    ),
    idempotent=False,
    is_framework=True,
)
def register(source: DerivedSource) -> None:
    """Register ``source``, refusing anything ADR-013 does not permit.

    Raises:
        ValueError: on a duplicate or malformed name, an unknown format,
            an empty format set, a narrowed format set with no stated
            reason (ADR-013 §4: "a recorded decision with a stated
            reason in the source's registration, not a default and not an
            oversight"), or a ``needs_input`` declaration that disagrees
            with the provider's arity.
    """
    name = source.name
    if not name or name != name.lower() or not name.replace("_", "").isalnum():
        raise ValueError(
            f"derived source name {name!r} must be lowercase snake_case"
        )
    if name in _REGISTRY:
        raise ValueError(f"derived source {name!r} is already registered")
    unknown = sorted(source.formats - SUPPORTED_DOC_FORMATS)
    if unknown:
        raise ValueError(
            f"derived source {name!r} declares unknown format(s) {unknown}; "
            f"doc-ref formats are {sorted(SUPPORTED_DOC_FORMATS)}"
        )
    if not source.formats:
        raise ValueError(
            f"derived source {name!r} declares no formats; a source that "
            f"renders in nothing cannot back a doc-ref"
        )
    if source.formats != SUPPORTED_DOC_FORMATS and not source.narrowing_reason:
        raise ValueError(
            f"derived source {name!r} declares only "
            f"{sorted(source.formats)} but states no narrowing_reason; "
            f"ADR-013 §4 requires a narrower declaration to be a recorded "
            f"decision with a stated reason"
        )
    signature = inspect.signature(source.provider)
    handed = (_ARITY_PROBE,) if source.needs_input else ()
    try:
        signature.bind(*handed)
    except TypeError as error:
        raise ValueError(
            f"derived source {name!r} declares needs_input="
            f"{source.needs_input}, so its provider is called with "
            f"{len(handed)} argument(s), and its signature {signature} does "
            f"not accept that: {error}. A source that describes a checkout "
            f"is handed a DerivedInput and one that describes the toolchain "
            f"is handed nothing; the registry row has to say which, because "
            f"records_for reads the row rather than the provider."
        ) from error
    _REGISTRY[name] = source


@component(
    name="S0maDSL_derived_source_names",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "The set of derived source names valid in this release — the single "
        "authority the parser's covers-source allow-list reads."
    ),
    idempotent=True,
    is_framework=True,
)
def derived_source_names() -> frozenset[str]:
    """Every registered source name (ADR-013 §5's release-bound set)."""
    return frozenset(_REGISTRY)


@component(
    name="S0maDSL_lookup_derived_source",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Return the registry row for a derived source name, or None when the "
        "name is not registered in this release."
    ),
    idempotent=True,
    is_framework=True,
)
def lookup_source(name: str) -> DerivedSource | None:
    """Return the :class:`DerivedSource` registered as ``name``."""
    return _REGISTRY.get(name)


def _raise_format_unsupported(
    *, decl_name: str, source: DerivedSource, doc_format: str,
) -> NoReturn:
    """Raise ADR-013 §4's ``DOC_SOURCE_FORMAT_UNSUPPORTED``.

    The import is function-local on purpose: ``renderer`` imports the three
    format modules, which import this one, so a module-level import back
    into ``renderer`` would close a cycle at package load.
    """
    from s0ma_dsl.codegen.doc_emitter.renderer import DocRenderError

    declared = ", ".join(sorted(source.formats))
    raise DocRenderError(
        f"doc-ref '{decl_name}' declares format '{doc_format}' over derived "
        f"source '{source.name}', which renders in: {declared}.",
        code=DOC_SOURCE_FORMAT_UNSUPPORTED,
        remediation=(
            f"Set the doc-ref's format: to one of {declared}, or widen "
            f"source '{source.name}' to declare '{doc_format}' in its "
            f"registration (codegen/doc_emitter/derived_sources.py). "
            f"Records are renderer-independent, so widening is normally "
            f"the right fix."
        ),
    )


def _raise_render_error(message: str, remediation: str) -> NoReturn:
    """Raise a structural ``DOC_RENDER_ERROR`` from the registry layer."""
    from s0ma_dsl.codegen.doc_emitter.renderer import DocRenderError

    raise DocRenderError(message, remediation=remediation)


@component(
    name="S0maDSL_derived_records_for",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Resolve a doc-ref's derived source to its records for one format: "
        "the single dispatch point all three renderers share, enforcing "
        "format completeness, provider purity, and non-vacuity."
    ),
    idempotent=True,
    is_framework=True,
)
def records_for(
    source_name: str,
    *,
    doc_format: str,
    decl_name: str,
    derived_input: DerivedInput | None = None,
) -> DerivedRecordSet:
    """Return the records ``source_name`` provides, for ``doc_format``.

    This is the whole of the renderers' knowledge of derived sources: they
    call it and render the result. Adding a source therefore never touches
    ``markdown.py``, ``html.py``, or ``json_format.py`` (ADR-013 §1).

    ``derived_input`` is the checkout a checkout-scoped source is handed.
    It is optional because most sources are not one, and it is a keyword
    with a default so that a caller who has no checkout in hand — every
    renderer, today — is unchanged. A source that needs one and is called
    without it fails with a named error and a remediation; it never
    silently produces an empty table, and it never goes looking for a root
    (ADR-013 §2).

    Raises:
        DocRenderError: with code ``DOC_SOURCE_FORMAT_UNSUPPORTED`` when
            the source does not declare ``doc_format``; with the default
            ``DOC_RENDER_ERROR`` when the name is unregistered, a
            checkout-scoped source was called with no input, the provider
            violates its contract (misaligned rows, unsorted records), or
            the record set is empty. Emptiness is a failure, not a result
            (ADR-013 §2) — an empty derived table is indistinguishable in
            the rendered output from a source nobody wired up.
    """
    source = _REGISTRY.get(source_name)
    if source is None:
        # Unreachable through the parser, which rejects unregistered names
        # at parse time. Reachable if a caller synthesises a DocRefDecl.
        _raise_render_error(
            f"doc-ref '{decl_name}' names derived source '{source_name}', "
            f"which is not registered in this release. Registered: "
            f"{', '.join(sorted(_REGISTRY)) or '(none)'}.",
            "Use a registered source name, or register the source with "
            "its provider component per ADR-013 §8.",
        )
    if doc_format not in source.formats:
        _raise_format_unsupported(
            decl_name=decl_name, source=source, doc_format=doc_format,
        )

    if source.needs_input:
        if derived_input is None:
            _raise_render_error(
                f"derived source '{source.name}' describes a checkout — "
                f"{source.intent} — and doc-ref '{decl_name}' was rendered "
                f"without one being handed to it.",
                "Pass derived_input=DerivedInput(root=<checkout>) to "
                "records_for. A provider is handed its input and never "
                "finds one for itself (ADR-013 §2), so a source about a "
                "repository cannot be rendered by a caller that has not "
                "said which repository.",
            )
        record_set = cast(
            "Callable[[DerivedInput], DerivedRecordSet]", source.provider
        )(derived_input)
    else:
        record_set = cast("Callable[[], DerivedRecordSet]", source.provider)()
    _verify_provider_output(record_set, source=source, decl_name=decl_name)
    return record_set


def _verify_provider_output(
    record_set: DerivedRecordSet,
    *,
    source: DerivedSource,
    decl_name: str,
) -> None:
    """Check the ADR-013 §2 output invariants a provider must satisfy."""
    if not record_set.records:
        _raise_render_error(
            f"derived source '{source.name}' produced zero records for "
            f"doc-ref '{decl_name}'. An empty derived table is "
            f"indistinguishable from a source nobody wired up, so ADR-013 "
            f"§2 treats emptiness as a failure rather than a result.",
            f"Fix the provider ({record_set.provider_id}) or its input; a "
            f"zero-record outcome here indicates a structural transpiler "
            f"bug, not authoring drift.",
        )
    width = len(record_set.fields)
    for row in record_set.records:
        if len(row) != width:
            _raise_render_error(
                f"derived source '{source.name}' returned a record of "
                f"width {len(row)} against a {width}-field schema.",
                f"Fix the provider ({record_set.provider_id}): every "
                f"record must align positionally with the declared "
                f"fields.",
            )
    names = record_set.field_names()
    if record_set.sort_key not in names:
        _raise_render_error(
            f"derived source '{source.name}' declares sort key "
            f"'{record_set.sort_key}', which is not one of its fields "
            f"{list(names)}.",
            f"Fix the provider ({record_set.provider_id}): the declared "
            f"sort key must name a schema field.",
        )
    key_index = names.index(record_set.sort_key)
    keys = [row[key_index] for row in record_set.records]
    if any(k is None for k in keys):
        _raise_render_error(
            f"derived source '{source.name}' has a record with no value "
            f"for its sort key '{record_set.sort_key}'.",
            f"Fix the provider ({record_set.provider_id}): the sort key "
            f"must be present on every record.",
        )
    ordered = [k for k in keys if k is not None]
    if ordered != sorted(ordered):
        _raise_render_error(
            f"derived source '{source.name}' returned records that are "
            f"not sorted by its declared key '{record_set.sort_key}'.",
            f"Fix the provider ({record_set.provider_id}): ADR-013 §2 "
            f"requires records sorted by a declared key so the rendering "
            f"is deterministic across processes and operating systems.",
        )
    if source.schema_version != record_set.schema_version:
        _raise_render_error(
            f"derived source '{source.name}' is registered at record "
            f"schema {source.schema_version} but its provider returned "
            f"{record_set.schema_version}.",
            "Bump the registration and the provider together; the "
            "registry row is the declared schema version.",
        )


@component(
    name="S0maDSL_derived_records_content_hash",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Hash a derived source's normalized records and record schema so a "
        "doc-ref's transitive content hash can move when the records move."
    ),
    idempotent=True,
    is_framework=True,
)
def records_content_hash(
    *,
    schema_version: str,
    fields: tuple[DerivedField, ...],
    records: tuple[tuple[str | None, ...], ...],
) -> str:
    """Return ``1:<sha256>`` over the record schema and the records.

    Deliberately hashes the *data* — schema version, field names, field
    kinds, and values — and not the provider's Python identity, not the
    human column labels, and not any rendering of the records (ADR-013
    §3). Two providers that produce equal records therefore produce equal
    hashes, and a column heading reworded for readers does not invalidate
    every downstream artifact.
    """
    payload = {
        "schema_version": schema_version,
        "fields": [[f.name, f.kind.value] for f in fields],
        "records": [list(row) for row in records],
    }
    blob = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return "1:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Initial population (ADR-013 §8)
#
# ``error_codes`` migrates first and proves the registry against a source
# that already ships. The other eight candidates in the ADR's table land
# with the providers that produce their records — never earlier. Three of
# them land at D6, which is the milestone their providers were finished at:
# ``document_catalog`` (C6's catalog), ``cli_commands`` (D1's interface
# reading), and ``package_inventory`` (the four distributions, read once in
# ``providers_repo.package_facts``).
# ---------------------------------------------------------------------------

_ERROR_CODES_SCHEMA_VERSION = "1.0.0"

_ERROR_CODES_FIELDS: tuple[DerivedField, ...] = (
    DerivedField("code", "Code", DerivedFieldKind.IDENTIFIER),
    DerivedField("migration", "Migration"),
    DerivedField("dev", "Dev"),
    DerivedField("strict", "Strict"),
    DerivedField("release", "Release"),
    DerivedField("description", "Description"),
)


@component(
    name="S0maDSL_error_codes_provider",
    kind=ComponentKind.ADAPTER,
    layer=Layer.FRAMEWORK,
    intent=(
        "Derived-source provider for `error_codes`: the canonical union of "
        "SEVERITY_MATRIX and OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE "
        "as normalized records with per-mode severities and descriptions."
    ),
    idempotent=True,
    is_framework=True,
)
def error_codes_provider() -> DerivedRecordSet:
    """Produce the error-code records from the transpiler's configuration.

    Purity: the input is ``s0ma_dsl.config`` — the transpiler's own
    immutable configuration, which ADR-013 §2 names as the one input a
    provider may read without being handed it. No filesystem, no network,
    no docs-on-disk dependency (ADR-010's rule, unchanged).

    Absence is ``None``, never a display string: out-of-matrix codes do
    not pass through the strictness ladder and have no per-mode severity,
    and a code with no registered description has none. Renderers decide
    that absence reads as an em-dash.
    """
    # Local import: this module lives in the codegen layer, and importing
    # config eagerly at module load would couple registry construction to
    # configuration import order. The imports are idempotent and the
    # records are rebuilt from scratch on every call (cheap — the registry
    # has tens of codes, not thousands).
    from s0ma_dsl.config import (
        ERROR_CODE_DESCRIPTIONS,
        OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE,
        SEVERITY_MATRIX,
        StrictnessMode,
    )

    modes_in_order = (
        StrictnessMode.MIGRATION,
        StrictnessMode.DEV,
        StrictnessMode.STRICT,
        StrictnessMode.RELEASE,
    )
    out_of_matrix = set(OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE)

    records: list[tuple[str | None, ...]] = []
    for code in sorted(set(SEVERITY_MATRIX.keys()) | out_of_matrix):
        if code in SEVERITY_MATRIX:
            severities: tuple[str | None, ...] = tuple(
                SEVERITY_MATRIX[code].get(mode) for mode in modes_in_order
            )
        else:
            # Out-of-matrix codes are structural / load-time and do not
            # vary by strictness mode: the severity is absent, not empty.
            severities = (None, None, None, None)
        records.append(
            (code, *severities, ERROR_CODE_DESCRIPTIONS.get(code)),
        )

    frozen = tuple(records)
    return DerivedRecordSet(
        provider_id="S0maDSL_error_codes_provider",
        source_identity=(
            "s0ma_dsl.config:SEVERITY_MATRIX"
            "+OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE"
            "+ERROR_CODE_DESCRIPTIONS"
        ),
        schema_version=_ERROR_CODES_SCHEMA_VERSION,
        sort_key="code",
        fields=_ERROR_CODES_FIELDS,
        records=frozen,
        content_hash=records_content_hash(
            schema_version=_ERROR_CODES_SCHEMA_VERSION,
            fields=_ERROR_CODES_FIELDS,
            records=frozen,
        ),
    )


register(DerivedSource(
    name="error_codes",
    provider=error_codes_provider,
    # All three, deliberately: ADR-013 §4 — closing the existing HTML/JSON
    # hole is the point of the migration, and grandfathering this source as
    # markdown-only would preserve the defect behind a diagnostic.
    formats=SUPPORTED_DOC_FORMATS,
    schema_version=_ERROR_CODES_SCHEMA_VERSION,
    intent=(
        "Every registered s0ma-dsl diagnostic: code, per-mode severity, and "
        "a one-sentence description."
    ),
))


# -- document_catalog (provider from C6) ------------------------------------

_DOCUMENT_CATALOG_SCHEMA_VERSION = "1.0.0"

_DOCUMENT_CATALOG_FIELDS: tuple[DerivedField, ...] = (
    DerivedField("id", "Id", DerivedFieldKind.IDENTIFIER),
    DerivedField("title", "Title"),
    DerivedField("path", "Canonical source", DerivedFieldKind.IDENTIFIER),
    DerivedField("status", "Status", DerivedFieldKind.IDENTIFIER),
    DerivedField("authority", "Authority", DerivedFieldKind.IDENTIFIER),
)


@component(
    name="S0maDSL_document_catalog_provider",
    kind=ComponentKind.ADAPTER,
    layer=Layer.FRAMEWORK,
    intent=(
        "Derived-source provider for `document_catalog`: every row of a "
        "checkout's document catalog as normalized records — id, title, "
        "canonical source, status, and the authority the document is."
    ),
    idempotent=True,
    is_framework=True,
)
def document_catalog_provider(value: DerivedInput) -> DerivedRecordSet:
    """Produce the catalog's rows from the checkout it is handed.

    Purity: the input is a :class:`DerivedInput` given by the caller, and
    the file read is ``docs/s0ma_src/catalog.json`` under it. That file is
    *authored source data*, not a rendered document — ADR-010's
    "no docs-on-disk dependency" is about a generator reading its own
    output back, and this reads none. Nothing is discovered: the root is
    handed over, the path inside it is the catalog provider's own constant.

    ``status`` is not a second reading of the file's status field. The
    catalog refuses a row whose id category and status disagree, so the
    category *is* the status, and deriving it here from the id keeps this
    source unable to report one the catalog would have refused.

    Absence is ``None``: most documents are not a written authority, and
    an empty string in that column would read as a document whose
    authority is the empty name.
    """
    from s0ma_dsl.docs_model.providers_catalog import (
        STATUS_BY_CATEGORY,
        CatalogProvider,
    )

    documents = CatalogProvider(root=value.root).documents()
    records: list[tuple[str | None, ...]] = []
    for record in sorted(documents, key=lambda item: item.id):
        category = record.id.partition(":")[2].partition("/")[0]
        records.append(
            (
                record.id,
                record.title,
                record.canonical_source,
                STATUS_BY_CATEGORY[category],
                record.authority or None,
            )
        )

    frozen = tuple(records)
    return DerivedRecordSet(
        provider_id="S0maDSL_document_catalog_provider",
        source_identity="docs/s0ma_src/catalog.json#/documents",
        schema_version=_DOCUMENT_CATALOG_SCHEMA_VERSION,
        sort_key="id",
        fields=_DOCUMENT_CATALOG_FIELDS,
        records=frozen,
        content_hash=records_content_hash(
            schema_version=_DOCUMENT_CATALOG_SCHEMA_VERSION,
            fields=_DOCUMENT_CATALOG_FIELDS,
            records=frozen,
        ),
    )


register(DerivedSource(
    name="document_catalog",
    provider=document_catalog_provider,
    formats=SUPPORTED_DOC_FORMATS,
    schema_version=_DOCUMENT_CATALOG_SCHEMA_VERSION,
    needs_input=True,
    intent=(
        "Every document a checkout catalogs: id, title, canonical source, "
        "standing, and the written authority the document itself is."
    ),
))


# -- cli_commands (provider from D1) ----------------------------------------

_CLI_COMMANDS_SCHEMA_VERSION = "1.0.0"

_CLI_COMMANDS_FIELDS: tuple[DerivedField, ...] = (
    DerivedField("command", "Command", DerivedFieldKind.IDENTIFIER),
    DerivedField("intent", "What it does"),
    DerivedField("arguments", "Arguments", DerivedFieldKind.IDENTIFIER),
    DerivedField("options", "Options", DerivedFieldKind.IDENTIFIER),
    DerivedField("effects", "Effects", DerivedFieldKind.IDENTIFIER),
)


def _argument_text(interface: object) -> str | None:
    """One command's positionals, in declaration order, or ``None``.

    A trailing ``?`` marks a positional that may be left out. It is data
    and not decoration: "may be omitted" is a fact about the command, the
    same fact ``CommandArgument.required`` carries, and a record schema of
    flat values has one column to put it in.
    """
    arguments = getattr(interface, "arguments", ())
    written = [
        item.dest if item.required else f"{item.dest}?" for item in arguments
    ]
    return ", ".join(written) if written else None


def _option_text(interface: object) -> str | None:
    """One command's flags, each spelling joined by ``/``, or ``None``."""
    options = getattr(interface, "options", ())
    written = ["/".join(item.flags) for item in options]
    return ", ".join(written) if written else None


@component(
    name="S0maDSL_cli_commands_provider",
    kind=ComponentKind.ADAPTER,
    layer=Layer.FRAMEWORK,
    intent=(
        "Derived-source provider for `cli_commands`: every `s0ma` command "
        "the constructed parser serves, with its positionals, its flags, "
        "and what running it touches."
    ),
    idempotent=True,
    is_framework=True,
)
def cli_commands_provider() -> DerivedRecordSet:
    """Produce the command records from the CLI the toolchain ships.

    Purity: the input is the ``s0ma`` command line itself — the toolchain's
    own configuration, the one input ADR-013 §2 lets a provider read
    without being handed it, and the same input ``error_codes`` reads. No
    checkout, no filesystem, no network. ``CliProvider`` builds the real
    argparse tree and walks it, so this is the served interface rather than
    a table somebody kept up to date.

    Two readings of one provider meet here: ``provide()`` for what a
    command *does* and what it touches, and ``interface()`` for its
    positionals and flags, which ``s0ma-docs-model@1`` has no field for.
    """
    from s0ma_dsl.docs_model.providers_cli import CliProvider
    from s0ma_dsl.docs_model.records import SurfaceRecord

    provider = CliProvider()
    surfaces = {
        item.record.id: item.record
        for item in provider.provide().records
        if isinstance(item.record, SurfaceRecord)
    }
    records: list[tuple[str | None, ...]] = []
    for interface in provider.interface():
        surface = surfaces.get(interface.id)
        effects = tuple(surface.side_effects) if surface is not None else ()
        records.append(
            (
                interface.public_name,
                interface.intent,
                _argument_text(interface),
                _option_text(interface),
                ", ".join(effects) if effects else None,
            )
        )

    frozen = tuple(sorted(records, key=lambda row: row[0] or ""))
    return DerivedRecordSet(
        provider_id="S0maDSL_cli_commands_provider",
        source_identity="python:s0ma_dsl.cli.main.S0maCLI.build_parser",
        schema_version=_CLI_COMMANDS_SCHEMA_VERSION,
        sort_key="command",
        fields=_CLI_COMMANDS_FIELDS,
        records=frozen,
        content_hash=records_content_hash(
            schema_version=_CLI_COMMANDS_SCHEMA_VERSION,
            fields=_CLI_COMMANDS_FIELDS,
            records=frozen,
        ),
    )


register(DerivedSource(
    name="cli_commands",
    provider=cli_commands_provider,
    formats=SUPPORTED_DOC_FORMATS,
    schema_version=_CLI_COMMANDS_SCHEMA_VERSION,
    intent=(
        "Every command the s0ma command line serves: what it does, what it "
        "takes, and what running it touches."
    ),
))


# -- package_inventory (provider from C4's reading) -------------------------

_PACKAGE_INVENTORY_SCHEMA_VERSION = "1.0.0"

_PACKAGE_INVENTORY_FIELDS: tuple[DerivedField, ...] = (
    DerivedField("distribution", "Distribution", DerivedFieldKind.IDENTIFIER),
    DerivedField("version", "Version", DerivedFieldKind.IDENTIFIER),
    DerivedField("depends_on", "Depends on", DerivedFieldKind.IDENTIFIER),
)


@component(
    name="S0maDSL_package_inventory_provider",
    kind=ComponentKind.ADAPTER,
    layer=Layer.FRAMEWORK,
    intent=(
        "Derived-source provider for `package_inventory`: the distributions "
        "a checkout ships, their versions, and which of them depend on "
        "which."
    ),
    idempotent=True,
    is_framework=True,
)
def package_inventory_provider(value: DerivedInput) -> DerivedRecordSet:
    """Produce the distribution records from the checkout it is handed.

    Purity: the input is a :class:`DerivedInput` given by the caller, and
    the files read are the ``[project]`` tables of ``packages/*/``. The
    reading itself is
    :func:`~s0ma_dsl.docs_model.providers_repo.package_facts`, shared with
    the authority records the repository provider emits — architecture
    §7.7's inventory and C4's status-grammar stopgap now describe one
    reading rather than two, so a version cannot move in a rendered table
    without moving in the composed graph.

    Only in-workspace dependencies appear. ``fastapi`` and ``lark`` are
    facts about a build environment; ``s0ma-mcp → s0ma-dsl → s0ma-core`` is
    the direction INV-6 names, and a distribution that depends on none of
    its siblings says so with ``None`` rather than with an empty cell.
    """
    from s0ma_dsl.docs_model.providers_repo import package_facts

    records: list[tuple[str | None, ...]] = [
        (
            item.distribution,
            item.version,
            ", ".join(item.depends_on) if item.depends_on else None,
        )
        for item in package_facts(value.root)
    ]

    frozen = tuple(sorted(records, key=lambda row: row[0] or ""))
    return DerivedRecordSet(
        provider_id="S0maDSL_package_inventory_provider",
        source_identity="packages/*/pyproject.toml#/project",
        schema_version=_PACKAGE_INVENTORY_SCHEMA_VERSION,
        sort_key="distribution",
        fields=_PACKAGE_INVENTORY_FIELDS,
        records=frozen,
        content_hash=records_content_hash(
            schema_version=_PACKAGE_INVENTORY_SCHEMA_VERSION,
            fields=_PACKAGE_INVENTORY_FIELDS,
            records=frozen,
        ),
    )


register(DerivedSource(
    name="package_inventory",
    provider=package_inventory_provider,
    formats=SUPPORTED_DOC_FORMATS,
    schema_version=_PACKAGE_INVENTORY_SCHEMA_VERSION,
    needs_input=True,
    intent=(
        "The distributions this workspace ships: identity, version, and "
        "which of them depends on which."
    ),
))
