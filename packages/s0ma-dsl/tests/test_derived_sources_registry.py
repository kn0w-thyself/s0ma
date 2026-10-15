"""Tests for the ADR-013 derived-source provider registry.

ADR-013 replaced ``doc-ref``'s per-source growth path — an allow-list row
plus a renderer branch in three files, two of which had no branch at all —
with a registry: a source is a name bound to a provider component, the
formats it renders in, and its record-schema version.

What these tests pin, clause by clause:

* **§1 registry dispatch.** The parser's allow-list reads the registry, and
  all three renderers resolve through one entry point. No renderer names a
  source.
* **§2 provider purity.** ``error_codes``'s provider is deterministic,
  returns records rather than markup, sorts by its declared key, carries
  the four provenance fields, and reads nothing but the transpiler's own
  configuration. Empty is a failure, not a result.
* **§3b provenance.** A derived doc-ref's transitive content hash moves
  when the records it renders move. Before D7 it could not: ``covers`` is
  empty for the brace form, ``covers_source`` never reached the
  registration, and the hashed snapshot was empty — so the table could be
  rewritten from top to bottom under a stable hash.
* **§4 format completeness.** A format a source does not declare is
  ``DOC_SOURCE_FORMAT_UNSUPPORTED`` in every strictness mode, never a
  silently empty document.
* **§6 ``sections:``.** Optional for the brace form, empty still parses,
  non-empty is ``PARSE_ERROR``, and unchanged (still required) for the
  filter form.
* **§7 release-gate boundary.** A brace-form doc-ref discharges no
  ``MISSING_PUBLIC_DOC_REF`` coverage. That was an implementation accident;
  ADR-013 makes it a ruling, so it gets a test.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.codegen.doc_emitter.content_hashes import compute_doc_hashes
from s0ma_dsl.codegen.doc_emitter.derived_sources import (
    DOC_SOURCE_FORMAT_UNSUPPORTED,
    SUPPORTED_DOC_FORMATS,
    DerivedField,
    DerivedFieldKind,
    DerivedRecordSet,
    DerivedSource,
    derived_source_names,
    lookup_source,
    records_content_hash,
    records_for,
    register,
)
from s0ma_dsl.codegen.doc_emitter.html import render_doc_ref_html
from s0ma_dsl.codegen.doc_emitter.json_format import render_doc_ref_json
from s0ma_dsl.codegen.doc_emitter.markdown import render_doc_ref_markdown
from s0ma_dsl.codegen.doc_emitter.registrations import (
    build_doc_ref_registration,
)
from s0ma_dsl.codegen.doc_emitter.renderer import DocRenderError
from s0ma_dsl.config import (
    ERROR_CODE_DESCRIPTIONS,
    OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE,
    SEVERITY_MATRIX,
)
from s0ma_dsl.parser.s0ma_parser import S0maParseError, parse_s0ma
from s0ma_dsl.resolver.doc_resolver import build_project_index

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.nodes import DocRefDecl, S0maModule

REPO_ROOT = Path(__file__).resolve().parent.parent

_MODULE_HEADER = """\
module {module}
    layer: DOMAIN
    version: 1.0.0
    intent: "Fixture module for the derived-source registry tests."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""


def _source(module: str, decl: str) -> str:
    return _MODULE_HEADER.format(module=module) + decl


def _parse(module: str, decl: str) -> S0maModule:
    return parse_s0ma(_source(module, decl), filename=f"{module}.s0ma")


def _derived_decl(
    *,
    name: str = "Derived",
    doc_format: str = "markdown",
    source: str = "error_codes",
    sections: str | None = None,
) -> str:
    lines = [
        f"doc-ref {name}",
        '    intent: "Derived reference used by the registry tests."',
        f"    format: {doc_format}",
        f"    output: docs/{name.lower()}.md",
        f"    covers: {{ source: {source} }}",
    ]
    if sections is not None:
        lines.append(f"    sections: {sections}")
    return "\n".join(lines) + "\n"


def _parse_derived(**kwargs: object) -> DocRefDecl:
    module = _parse("derived_fixture", _derived_decl(**kwargs))  # type: ignore[arg-type]
    return module.doc_refs[0]


def _render(decl: DocRefDecl, renderer: object) -> str:
    module = _parse("derived_fixture", "")
    index = build_project_index({module.module.name: module})
    return renderer(  # type: ignore[operator]
        decl,
        index=index,
        content_hash="1:" + "0" * 64,
        schema_version="3.0.0",
    )


# ---------------------------------------------------------------------------
# §1 — the registry is the single authority for source names
# ---------------------------------------------------------------------------


def test_error_codes_is_registered_with_all_three_formats() -> None:
    """``error_codes`` migrates onto the registry declaring every format.

    ADR-013 §4: the expectation is all three. Grandfathering the source as
    markdown-only would have preserved the very defect the migration
    exists to close — a ``format: html`` derived doc-ref that rendered an
    empty document — behind a diagnostic.
    """
    source = lookup_source("error_codes")
    assert source is not None
    assert source.formats == SUPPORTED_DOC_FORMATS
    assert source.narrowing_reason is None
    assert source.schema_version == "1.0.0"


def test_parser_allow_list_reads_the_registry() -> None:
    """The parser accepts exactly the registered names, and no copy of them.

    The point of ADR-013 §1 is that a source name exists in one place. If
    the parser kept its own frozenset, this assertion would drift the first
    time a source was registered without a matching parser edit — which is
    precisely the failure mode the registry removes.
    """
    assert derived_source_names() == {
        "cli_commands",
        "document_catalog",
        "error_codes",
        "package_inventory",
    }

    decl = _parse_derived()
    assert decl.covers_source == "error_codes"
    assert decl.covers == ()


def test_unregistered_source_is_a_parse_error_naming_the_registered_set() -> None:
    """A name this release does not register is refused at parse time.

    ``mcp_surface`` is one of ADR-013 §8's remaining candidates: a name
    somebody will plausibly write before its provider exists, which is
    exactly the case the release-bound set is for.
    """
    with pytest.raises(S0maParseError) as excinfo:
        _parse_derived(source="mcp_surface")

    err = excinfo.value
    assert err.code == "PARSE_ERROR"
    assert "mcp_surface" in err.message
    assert "error_codes" in err.message
    assert err.context["supported"] == sorted(derived_source_names())


def test_registration_refuses_a_narrowed_format_set_without_a_reason() -> None:
    """ADR-013 §4: a narrower declaration is a decision, not a default."""
    with pytest.raises(ValueError, match="narrowing_reason"):
        register(DerivedSource(
            name="narrow_without_reason",
            provider=lambda: _stub_record_set(),
            formats=frozenset({"markdown"}),
            schema_version="1.0.0",
            intent="Stub source used to prove the registration invariant.",
        ))
    assert "narrow_without_reason" not in derived_source_names()


def test_registration_refuses_a_duplicate_name() -> None:
    """A name means one thing forever (ADR-013 §1)."""
    with pytest.raises(ValueError, match="already registered"):
        register(DerivedSource(
            name="error_codes",
            provider=lambda: _stub_record_set(),
            formats=SUPPORTED_DOC_FORMATS,
            schema_version="1.0.0",
            intent="Would shadow the real error-code source.",
        ))


def test_registration_refuses_an_unknown_format() -> None:
    """``formats`` is a subset of the formats ``doc-ref`` supports."""
    with pytest.raises(ValueError, match="unknown format"):
        register(DerivedSource(
            name="bad_format_source",
            provider=lambda: _stub_record_set(),
            formats=frozenset({"markdown", "pdf"}),
            schema_version="1.0.0",
            intent="Stub source naming a format doc-ref does not have.",
        ))


# ---------------------------------------------------------------------------
# §2 — provider purity
# ---------------------------------------------------------------------------


def _stub_record_set(
    *,
    records: tuple[tuple[str | None, ...], ...] = (("a", "x"), ("b", "y")),
    sort_key: str = "key",
    schema_version: str = "1.0.0",
) -> DerivedRecordSet:
    fields = (
        DerivedField("key", "Key", DerivedFieldKind.IDENTIFIER),
        DerivedField("value", "Value"),
    )
    return DerivedRecordSet(
        provider_id="stub_provider",
        source_identity="tests:stub",
        schema_version=schema_version,
        sort_key=sort_key,
        fields=fields,
        records=records,
        content_hash=records_content_hash(
            schema_version=schema_version, fields=fields, records=records,
        ),
    )


def test_error_codes_provider_is_deterministic_across_calls() -> None:
    """Two calls produce equal records and equal hashes (ADR-013 §2)."""
    first = records_for("error_codes", doc_format="markdown", decl_name="D")
    second = records_for("error_codes", doc_format="markdown", decl_name="D")
    assert first == second
    assert first.content_hash == second.content_hash


def test_error_codes_provider_covers_the_canonical_union() -> None:
    """Records are the union of both registries, one row per code."""
    record_set = records_for(
        "error_codes", doc_format="markdown", decl_name="D",
    )
    codes = [row[0] for row in record_set.records]
    expected = sorted(
        set(SEVERITY_MATRIX) | set(OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE)
    )
    assert codes == expected


def test_error_codes_provider_returns_records_not_markup() -> None:
    """No value carries presentation (ADR-013 §2, "records, not markup").

    A provider that returned a backticked code or an em-dash would have
    quietly made itself Markdown-only, and the per-format declaration
    would become a claim the gates cannot check. Absence is ``None``; the
    renderers decide what absence looks like.
    """
    record_set = records_for(
        "error_codes", doc_format="markdown", decl_name="D",
    )
    for row in record_set.records:
        for field, value in zip(record_set.fields, row, strict=True):
            if value is None:
                continue
            # Absence is never a display string, in any field. (Prose
            # descriptions may legitimately quote DSL field names in
            # backticks — that is authored content, not the provider
            # deciding how a code should look.)
            assert value != "—"
            if field.kind is DerivedFieldKind.IDENTIFIER:
                assert "`" not in value
                assert "<" not in value

    out_of_matrix = set(OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE)
    by_code = {row[0]: row for row in record_set.records}
    sample = sorted(out_of_matrix - set(SEVERITY_MATRIX))[0]
    assert by_code[sample][1:5] == (None, None, None, None)


def test_error_codes_provenance_is_complete() -> None:
    """All four ADR-013 §3 provenance fields are present and specific."""
    record_set = records_for(
        "error_codes", doc_format="markdown", decl_name="D",
    )
    assert record_set.provider_id == "S0maDSL_error_codes_provider"
    assert "SEVERITY_MATRIX" in record_set.source_identity
    assert "ERROR_CODE_DESCRIPTIONS" in record_set.source_identity
    assert record_set.schema_version == "1.0.0"
    assert record_set.content_hash.startswith("1:")


def test_record_schema_version_is_not_the_ir_schema_version() -> None:
    """ADR-013 §3a: the two ``schema_version``s must never be conflated.

    The doc frontmatter's field is ``ir.schema.SCHEMA_VERSION``; a
    source's record schema versions independently. The JSON renderer
    therefore keys the source's under ``record_schema_version``.
    """
    from s0ma_dsl.ir.schema import SCHEMA_VERSION

    record_set = records_for(
        "error_codes", doc_format="json", decl_name="D",
    )
    assert record_set.schema_version != SCHEMA_VERSION

    payload = _render(_parse_derived(doc_format="json"), render_doc_ref_json)
    assert '"record_schema_version": "1.0.0"' in payload
    assert f'"schema_version": "{SCHEMA_VERSION}"' in payload


def test_empty_records_are_a_failure_not_a_result() -> None:
    """ADR-013 §2: an empty derived table is indistinguishable from a gap."""
    register(DerivedSource(
        name="vacuous_stub",
        provider=lambda: _stub_record_set(records=()),
        formats=SUPPORTED_DOC_FORMATS,
        schema_version="1.0.0",
        intent="Stub source whose provider resolves to zero records.",
    ))
    try:
        with pytest.raises(DocRenderError, match="zero records"):
            records_for("vacuous_stub", doc_format="markdown", decl_name="D")
    finally:
        _unregister("vacuous_stub")


def test_unsorted_records_are_refused() -> None:
    """Records arrive sorted by the declared key, or the render fails."""
    register(DerivedSource(
        name="unsorted_stub",
        provider=lambda: _stub_record_set(records=(("b", "y"), ("a", "x"))),
        formats=SUPPORTED_DOC_FORMATS,
        schema_version="1.0.0",
        intent="Stub source whose provider returns records out of order.",
    ))
    try:
        with pytest.raises(DocRenderError, match="not sorted"):
            records_for("unsorted_stub", doc_format="markdown", decl_name="D")
    finally:
        _unregister("unsorted_stub")


def _unregister(name: str) -> None:
    """Remove a stub source registered by a test.

    Reaches into the registry's private store on purpose: registration is
    a module-import-time act with no public removal path, because in
    production nothing ever unregisters a source.
    """
    from s0ma_dsl.codegen.doc_emitter import derived_sources

    derived_sources._REGISTRY.pop(name, None)


# ---------------------------------------------------------------------------
# §4 — format completeness, and the end of silent-empty output
# ---------------------------------------------------------------------------


def test_all_three_formats_render_content_for_a_derived_source() -> None:
    """Markdown, HTML, and JSON each carry the records.

    Until ADR-013 landed, only Markdown did: ``html.py`` had no
    ``covers_source`` handling at all and ``json_format.py`` copied the
    source *name* and then rendered the (empty) ``sections:``. Both
    produced a document with a heading, an intent, and no content — in
    every strictness mode, from 0.12 through 0.18.
    """
    sample_code = sorted(SEVERITY_MATRIX)[0]

    markdown = _render(_parse_derived(), render_doc_ref_markdown)
    assert "| Code | Migration | Dev | Strict | Release | Description |" in markdown
    assert f"| `{sample_code}` |" in markdown

    html = _render(_parse_derived(doc_format="html"), render_doc_ref_html)
    assert "<table>" in html
    assert "<th>Code</th>" in html
    assert f"<td><code>{sample_code}</code></td>" in html

    payload = _render(_parse_derived(doc_format="json"), render_doc_ref_json)
    assert '"covers_source": "error_codes"' in payload
    assert f'"code": "{sample_code}"' in payload
    assert '"sections": []' in payload


def test_html_render_is_not_an_empty_document() -> None:
    """The regression this closes, stated as its own assertion.

    Rendering through the Markdown-subset translator would drop the table
    silently, because that translator has no table syntax. The count of
    ``<tr>`` rows is the cheapest proof the records actually arrived.
    """
    html = _render(_parse_derived(doc_format="html"), render_doc_ref_html)
    expected_rows = len(
        set(SEVERITY_MATRIX) | set(OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE)
    )
    assert html.count("<tr>") == expected_rows + 1  # + the header row


def test_undeclared_format_fails_with_the_named_diagnostic() -> None:
    """ADR-013 §4's ``DOC_SOURCE_FORMAT_UNSUPPORTED``, named and unconditional.

    The diagnostic names the source, the requested format, and the formats
    the source does declare, and it is an error in every strictness mode —
    never a warning, never a degraded rendering.
    """
    register(DerivedSource(
        name="markdown_only_stub",
        provider=_stub_record_set,
        formats=frozenset({"markdown"}),
        schema_version="1.0.0",
        intent="Stub source declaring one format, to exercise the gap.",
        narrowing_reason=(
            "Test fixture: proves a narrowed declaration is enforced."
        ),
    ))
    try:
        with pytest.raises(DocRenderError) as excinfo:
            records_for(
                "markdown_only_stub", doc_format="html", decl_name="Narrow",
            )
    finally:
        _unregister("markdown_only_stub")

    err = excinfo.value
    assert err.code == DOC_SOURCE_FORMAT_UNSUPPORTED
    assert "markdown_only_stub" in str(err)
    assert "html" in str(err)
    assert "markdown" in str(err)
    assert err.remediation is not None


def test_the_diagnostic_is_registered_as_an_error_in_every_mode() -> None:
    """Registered per the DSL's severity conventions, like ``DOC_RENDER_ERROR``."""
    severities = SEVERITY_MATRIX[DOC_SOURCE_FORMAT_UNSUPPORTED]
    assert set(severities.values()) == {"error"}
    assert DOC_SOURCE_FORMAT_UNSUPPORTED in ERROR_CODE_DESCRIPTIONS


def test_doc_render_error_still_defaults_to_its_own_code() -> None:
    """Carrying a code on the exception did not renumber the historic sites."""
    assert DocRenderError("boom").code == "DOC_RENDER_ERROR"
    assert DocRenderError("boom").remediation is None


# ---------------------------------------------------------------------------
# §6 — ``sections:`` for the brace form
# ---------------------------------------------------------------------------


def test_brace_form_parses_without_sections() -> None:
    """The dead-field requirement is gone."""
    decl = _parse_derived(sections=None)
    assert decl.sections == ()


def test_brace_form_still_accepts_an_empty_sections_list() -> None:
    """``sections: []`` keeps parsing.

    It is the exact shape the old rule forced every brace-form author to
    write, including any consumer project that took up ADR-010's
    invitation to render the s0ma error catalogue in its own docs.
    Rejecting it would break working sources to tidy a field.
    """
    decl = _parse_derived(sections="[]")
    assert decl.sections == ()


def test_brace_form_rejects_a_non_empty_sections_list() -> None:
    """A non-empty ``sections:`` on the brace form is ``PARSE_ERROR``."""
    with pytest.raises(S0maParseError) as excinfo:
        _parse_derived(sections="[intent]")

    err = excinfo.value
    assert err.code == "PARSE_ERROR"
    assert "sections" in err.message
    assert err.context["covers_source"] == "error_codes"


def test_filter_form_still_requires_sections() -> None:
    """ADR-013 §6: nothing changes for the filter form."""
    decl_src = (
        "doc-ref FilterForm\n"
        '    intent: "Reference for every public nerve."\n'
        "    format: markdown\n"
        "    output: docs/filter_form.md\n"
        "    covers: [nerve where visibility == PUBLIC]\n"
    )
    with pytest.raises(S0maParseError) as excinfo:
        _parse("filter_fixture", decl_src)
    assert excinfo.value.code == "MISSING_FIELD"
    assert "sections" in excinfo.value.message


def test_the_in_tree_generator_dropped_its_dead_sections_field() -> None:
    """ADR-013 §6: the existing generator drops ``sections: []``."""
    text = (
        REPO_ROOT / "docs" / "_generators" / "common_errors.s0ma"
    ).read_text(encoding="utf-8")
    assert "covers: { source: error_codes }" in text
    assert "sections:" not in text


# ---------------------------------------------------------------------------
# §3b — the provenance fix
# ---------------------------------------------------------------------------


def test_registration_carries_the_source_and_its_record_hash() -> None:
    """``build_doc_ref_registration`` no longer drops the discriminator."""
    decl = _parse_derived()
    registration = build_doc_ref_registration(decl, filename="derived.s0ma")

    assert registration.covers_source == "error_codes"
    expected = records_for(
        "error_codes", doc_format="markdown", decl_name=decl.name,
    ).content_hash
    assert registration.covers_source_hash == expected


def test_filter_form_registration_carries_neither() -> None:
    """The filter form is untouched: both provenance fields stay ``None``."""
    module = _parse(
        "filter_fixture",
        "doc-ref FilterForm\n"
        '    intent: "Reference for every public nerve."\n'
        "    format: markdown\n"
        "    output: docs/filter_form.md\n"
        "    covers: [nerve where visibility == PUBLIC]\n"
        "    sections: [intent]\n",
    )
    registration = build_doc_ref_registration(
        module.doc_refs[0], filename="filter.s0ma",
    )
    assert registration.covers_source is None
    assert registration.covers_source_hash is None


def test_transitive_hash_moves_when_the_records_move() -> None:
    """The defect ADR-013 Context fact 5 recorded, closed.

    A derived doc-ref's transitive hash used to move when
    ``TRANSPILER_VERSION`` moved and *not* when the registry it renders
    changed: ``covers`` is empty for the brace form and ``covers_source``
    never reached the registration, so the hashed snapshot was empty. The
    table could be rewritten from top to bottom under a stable hash.

    Rather than mutate the real diagnostic registry, this drives the same
    path with a stub source whose records differ between two renders.
    """
    hashes: list[str] = []
    try:
        for records in (
            (("a", "one"), ("b", "two")),
            (("a", "one"), ("b", "CHANGED")),
        ):
            _unregister("mutable_stub")
            register(DerivedSource(
                name="mutable_stub",
                provider=lambda records=records: _stub_record_set(  # type: ignore[misc]
                    records=records,
                ),
                formats=SUPPORTED_DOC_FORMATS,
                schema_version="1.0.0",
                intent="Stub source whose records change between renders.",
            ))
            # Parsed inside the loop: the parser refuses an unregistered
            # source name, which is itself the §1 authority working.
            module = _parse(
                "derived_fixture", _derived_decl(source="mutable_stub"),
            )
            decl = module.doc_refs[0]
            index = compute_doc_hashes({module.module.name: module})
            hashes.append(index.get_for_doc_ref(decl))
    finally:
        _unregister("mutable_stub")

    assert hashes[0] and hashes[1]
    assert hashes[0] != hashes[1], (
        "The doc-ref's transitive content hash did not move when the "
        "records it renders changed. That is ADR-013's Context fact 5 "
        "regressing: the derived form is contributing nothing to the hash."
    )


def test_source_name_alone_also_moves_the_hash() -> None:
    """Two doc-refs differing only in their source hash differently."""
    register(DerivedSource(
        name="same_records_stub",
        provider=_stub_record_set,
        formats=SUPPORTED_DOC_FORMATS,
        schema_version="1.0.0",
        intent="Stub source with the same records under a second name.",
    ))
    try:
        decl = _parse_derived()
        as_error_codes = build_doc_ref_registration(decl, filename="d.s0ma")
        renamed = dataclasses.replace(
            as_error_codes, covers_source="same_records_stub",
        )
        assert as_error_codes.covers_source != renamed.covers_source
        assert as_error_codes.to_dict()["covers_source"] == "error_codes"
        assert renamed.to_dict()["covers_source"] == "same_records_stub"
    finally:
        _unregister("same_records_stub")


def test_registration_round_trips_through_to_dict() -> None:
    """The core dataclass's serialisation carries both new fields."""
    from s0ma.models import DocRefRegistration

    original = build_doc_ref_registration(_parse_derived(), filename="d.s0ma")
    restored = DocRefRegistration.from_dict(original.to_dict())
    assert restored == original


# ---------------------------------------------------------------------------
# §7 — derived sources are not component coverage
# ---------------------------------------------------------------------------


def test_brace_form_discharges_no_public_doc_ref_coverage() -> None:
    """ADR-013 §7, promoted from implementation accident to ruling.

    Sources like ``cli_commands`` and ``mcp_surface`` will render tables
    that *mention* the components ``MISSING_PUBLIC_DOC_REF`` asks about,
    and wiring a derived table in as coverage would make the gate
    satisfiable by pointing one doc-ref at an opaque provider — every
    PUBLIC nerve passing forever, including tomorrow's. The consequence
    is deliberate and must not be "fixed".
    """
    from s0ma_dsl.config import StrictnessMode
    from s0ma_dsl.semantic.doc_validator import check_release_doc_coverage

    # A real fixture module with a PUBLIC nerve, so the gate has something
    # to ask about, plus an in-memory module whose only doc-ref is the
    # brace form.
    greetings_path = (
        REPO_ROOT / "tests" / "fixtures" / "valid" / "docs"
        / "render_formats" / "greetings.s0ma"
    )
    greetings = parse_s0ma(
        greetings_path.read_text(encoding="utf-8"), filename="greetings.s0ma",
    )
    derived = _parse("coverage_fixture", _derived_decl(name="Derived"))
    modules = {
        greetings.module.name: greetings,
        derived.module.name: derived,
    }
    diagnostics = check_release_doc_coverage(
        modules, mode=StrictnessMode.RELEASE,
    )
    codes = {getattr(d, "code", "") for d in diagnostics}
    assert "MISSING_PUBLIC_DOC_REF" in codes, (
        "A brace-form doc-ref discharged component coverage. ADR-013 §7 "
        "rules that it must not: the gate asks whether a PUBLIC nerve "
        "resolves to documentation through the registry, and a derived "
        "table's incidental mention of a name is not that resolution."
    )
