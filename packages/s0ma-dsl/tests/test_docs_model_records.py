"""Gates for ``s0ma-docs-model@1`` — the documentation model's substrate.

Milestone C1 of the docs-function plan (internal) §8. What these tests hold
in place, in the order the module is built:

* the record shapes and the rulings the B gate ratified for them
  (the Phase B gate record (internal) §7, rows 1–10);
* every id form frozen by plan §5 as corrected at that gate, each with an
  accepted example and — where the correction exists because something
  nearly matched — a refusal;
* byte-stable serialization, which everything downstream assumes: the
  committed build, the channel comparisons, and the merge rule that lets
  two providers agree.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.docs_model import (
    BUILD_STAMP_ONLY_FIELDS,
    FIELD_CLASS,
    ID_FORMS,
    RECORD_TYPES,
    SCHEMA,
    AliasIndex,
    AuthorityDelegation,
    AuthorityRef,
    BuildStamp,
    ConceptRecord,
    DocsBundle,
    DocsIdError,
    DocsModelError,
    DocsSchemaVersionError,
    DocsSerializationError,
    DocumentRecord,
    ExampleRef,
    FieldClass,
    JourneyRecord,
    JourneyStep,
    Provenance,
    RecoveryPath,
    SurfaceRecord,
    TeachingSequence,
    TeachingStep,
    authored_prose_fields,
    canonical_json,
    cli_id,
    content_hash,
    deserialize_bundle,
    facts_hash,
    field_class,
    id_form,
    normalize_id,
    record_from_plain,
    same_identity,
    serialize_bundle,
    snapshot_hash,
    stamped,
    studi0_action_id,
    studi0_public_name,
    to_plain,
    validate_id,
    validate_schema_version,
)
from s0ma_dsl.docs_model import serialize as serialize_module

MODEL_DIR = Path(__file__).resolve().parents[1] / "src" / "s0ma_dsl" / "docs_model"
MODEL_FILES = (
    "__init__.py",
    "compose.py",
    "ids.py",
    "providers.py",
    "records.py",
    "serialize.py",
    "validate.py",
)


# ---------------------------------------------------------------------------
# A bundle with one record of every type
# ---------------------------------------------------------------------------


def _provenance(adapter: str = "dsl.cli-argparse") -> Provenance:
    return Provenance(
        adapter_id=adapter,
        schema_version=SCHEMA,
        source="packages/s0ma-dsl/src/s0ma_dsl/cli/main.py",
        source_sha256="c" * 64,
    )


def _surface(**overrides: Any) -> SurfaceRecord:
    values: dict[str, Any] = {
        "id": "cli:s0ma/check",
        "channel": "cli",
        "public_name": "check",
        "intent": "Validate .s0ma file(s) without generating output",
        "component_refs": ("component:s0ma_dsl.cli.main.S0maCLI",),
        "manual_exception": "",
        "governed_by": ("authority:spec/check-command",),
        "side_effects": ("read",),
        "errors": ("EXIT_VALIDATION_ERROR",),
        "provenance": _provenance(),
    }
    values.update(overrides)
    return SurfaceRecord(**values)


def _concept(**overrides: Any) -> ConceptRecord:
    values: dict[str, Any] = {
        "id": "concept:drift",
        "term": "drift",
        "summary": "The gap between what a system says it is and what it is.",
        "plain_definition": "Drift is a description that has stopped matching the thing.",
        "purpose": "It names the failure the whole product exists to prevent.",
        "use_when": "Use it when a description and its subject disagree.",
        "do_not_use_when": "Do not use it for a change that was made on purpose.",
        "governed_by": ("authority:spec/drift-check",),
        "examples": (ExampleRef("example:describe_the_running_server", "tools.s0ma"),),
    }
    values.update(overrides)
    return ConceptRecord(**values)


def _bundle() -> DocsBundle:
    """One record of every type, stamped for a fixed release."""
    authority = AuthorityRef(
        id="authority:prd/vision-self-knowledge",
        authority_class="prd",
        source="references/s0ma-prd.md",
        section="1",
        content_sha256="a" * 64,
        status="current",
        delegates=(AuthorityDelegation("language", "spec", "FR-DSL-1"),),
    )
    journey = JourneyRecord(
        id="journey:first-project",
        intent="Get from nothing to a project that checks clean.",
        steps=(
            JourneyStep("cli:s0ma/check", "Prove the source is valid.", "No findings."),
            JourneyStep("cli:s0ma/build", "Produce the modules.", "Files under the build."),
        ),
        recovery_paths=(RecoveryPath("The check fails.", "cli:s0ma/doctor", "Ask the doctor."),),
    )
    sequence = TeachingSequence(
        id="sequence:concept-tour",
        steps=(
            TeachingStep("concept:nerve", "Start with the part."),
            TeachingStep("concept:drift", "Then the failure it prevents."),
        ),
    )
    document = DocumentRecord(
        id="doc:normative/prd",
        title="The product requirements",
        canonical_source="references/s0ma-prd.md",
        prose_locator="references/s0ma-prd.md",
        governed_by=("authority:owner/product-direction",),
        covers=("concept:drift", "journey:first-project"),
    )
    unstamped = DocsBundle(
        stamp=BuildStamp(schema=SCHEMA, release_version="", snapshot_hash=""),
        authorities=(authority,),
        concepts=(_concept(),),
        surfaces=(_surface(),),
        journeys=(journey,),
        sequences=(sequence,),
        documents=(document,),
    )
    return stamped(unstamped, "0.18.1")


@pytest.fixture()
def bundle() -> DocsBundle:
    return _bundle()


# ---------------------------------------------------------------------------
# Record shapes and the rulings behind them
# ---------------------------------------------------------------------------


class TestRecordShapes:
    """The ratified field set, and the decisions that produced it."""

    def test_every_field_of_every_record_is_classified(self) -> None:
        """No field escapes the authored-or-sourced line (register row 5).

        A field with no classification would silently escape the voice
        gate and the single-paragraph rule, which is the one failure the
        classification exists to prevent — so an unclassified field fails
        here rather than in a renderer.
        """
        missing = [
            f"{record_type.__name__}.{item.name}"
            for record_type in RECORD_TYPES
            for item in fields(record_type)
            if (record_type.__name__, item.name) not in FIELD_CLASS
        ]
        assert missing == [], f"unclassified fields: {missing}"

    def test_the_classification_names_no_field_that_does_not_exist(self) -> None:
        """The map cannot outlive the fields it classifies."""
        real = {
            (record_type.__name__, item.name)
            for record_type in RECORD_TYPES
            for item in fields(record_type)
        }
        stale = sorted(key for key in FIELD_CLASS if key not in real)
        assert stale == [], f"classified fields that no longer exist: {stale}"

    def test_classification_is_a_lookup_not_a_guess(self) -> None:
        assert field_class(ConceptRecord, "purpose") is FieldClass.AUTHORED_PROSE
        assert field_class(ConceptRecord, "governed_by") is FieldClass.AUTHORED_DATA
        assert field_class(SurfaceRecord, "intent") is FieldClass.SOURCED
        with pytest.raises(DocsModelError, match="no authored-or-sourced classification"):
            field_class(ConceptRecord, "invented_field")

    def test_build_facts_live_on_the_stamp_and_nowhere_else(self) -> None:
        """Register row 2: no record may carry a copy of a build fact.

        Copying the release or the snapshot digest onto a record makes the
        first stale copy a disagreement that is nobody's fault. The model
        has nowhere to put one, and this is what says so.
        """
        offenders = [
            f"{record_type.__name__}.{item.name}"
            for record_type in RECORD_TYPES
            if record_type is not BuildStamp
            for item in fields(record_type)
            if item.name in BUILD_STAMP_ONLY_FIELDS
        ]
        assert offenders == [], f"build facts copied onto records: {offenders}"
        assert {item.name for item in fields(BuildStamp)} == BUILD_STAMP_ONLY_FIELDS

    def test_the_two_fields_row_10_scheduled_for_c5_are_back(self) -> None:
        """Row 10's two highest-priority re-adds, landed at C5a.

        The pin below used to fail if either field appeared early. C5a is
        the milestone the row named, so the pin becomes this: they are
        here, they default to empty, and adding them broke no existing
        construction — which is what "additive within @1" has to mean.
        """
        concept_fields = {item.name for item in fields(ConceptRecord)}
        assert "syntax" in concept_fields, "syntax returned at C5a"
        assert "related_concepts" in concept_fields, "related_concepts returned at C5a"
        assert _concept().syntax == ()
        assert _concept().related_concepts == ()

    def test_the_field_row_10_scheduled_for_c6_is_back(self) -> None:
        """Row 10's catalog re-add, landed at C6.

        B4 deferred ``DocumentRecord.authority`` with its cost named:
        ``doc:normative/prd`` was a normative document with no way to say
        so. C6 is the milestone the row named, and the catalog is where
        the cost became real — so the pin is now this: the field is here,
        it defaults to empty, and adding it broke no construction written
        against the previous version, which is what "additive within @1"
        has to mean.
        """
        assert "authority" in {item.name for item in fields(DocumentRecord)}
        assert (
            DocumentRecord(
                id="doc:guide/readme",
                title="s0ma",
                canonical_source="README.md",
                prose_locator="README.md",
                governed_by=(),
                covers=(),
            ).authority
            == ""
        )
        assert field_class(DocumentRecord, "authority") is FieldClass.AUTHORED_DATA

    def test_the_ratified_additions_are_present(self) -> None:
        """Rows 1, 3, 6 and 7, each as a field or a type that now exists."""
        concept_fields = {item.name for item in fields(ConceptRecord)}
        assert "summary" in concept_fields
        assert "governed_by" in {item.name for item in fields(SurfaceRecord)}
        assert "governed_by" in {item.name for item in fields(DocumentRecord)}
        assert "prose_locator" in {item.name for item in fields(DocumentRecord)}
        assert {item.name for item in fields(TeachingSequence)} == {"id", "steps"}
        assert {item.name for item in fields(TeachingStep)} == {"topic", "purpose"}

    def test_the_journey_fields_row_10_scheduled_for_e1_are_back(self) -> None:
        """Row 10's journey re-adds, landed at E1.

        B4 deferred ``concepts_taught`` and ``concepts_required`` with the
        cost named: D-10 makes journeys mandatory for primary
        capabilities, and a coverage gate that cannot ask which concepts a
        journey teaches cannot enforce that policy. E1 is the milestone
        the row named, and it brought two more fields with them —
        ``JourneyRecord.evidence``, which is what
        ``DOC_JOURNEY_UNTESTED`` asks about, and
        ``JourneyStep.approval_boundary``, which is what the approval gate
        reads instead of sniffing prose for the word "approve".

        All four default to empty, so every construction written against
        the previous version still builds. That is what "additive within
        @1" has to mean, and it is the same pin C5a and C6 turned into a
        presence assertion before this one.
        """
        journey_fields = {item.name for item in fields(JourneyRecord)}
        assert "concepts_taught" in journey_fields, "journey teaching returned at E1"
        assert "concepts_required" in journey_fields, "prerequisites returned at E1"
        assert "evidence" in journey_fields, "journey evidence arrived at E1"
        assert "approval_boundary" in {item.name for item in fields(JourneyStep)}
        journey = JourneyRecord(
            id="journey:first-project",
            intent="Get from a module to a system you can question.",
            steps=(),
            recovery_paths=(),
        )
        assert journey.concepts_taught == ()
        assert journey.concepts_required == ()
        assert journey.evidence == ()
        assert JourneyStep(
            surface="cli:s0ma/check", purpose="Why.", expected_outcome="What."
        ).approval_boundary == ""
        for name in ("concepts_taught", "concepts_required", "evidence"):
            assert field_class(JourneyRecord, name) is FieldClass.AUTHORED_DATA
        assert (
            field_class(JourneyStep, "approval_boundary") is FieldClass.AUTHORED_PROSE
        )

    def test_the_deferred_fields_are_still_deferred(self) -> None:
        """Row 10: what F6 and F7 re-add is not here yet.

        The deferral schedule is only real if adding a field early fails
        something. This is that something — and the rows it no longer
        covers are the proof that the schedule is a schedule rather than a
        list of regrets: C5a, C6 and E1 returned theirs, so those pins
        turned into the presence assertions above.
        """
        concept_fields = {item.name for item in fields(ConceptRecord)}
        assert "aliases" not in concept_fields, "concept aliases return at F6"
        assert "review_triggers" not in {item.name for item in fields(DocumentRecord)}, (
            "review triggers return at F"
        )
        assert "aliases" not in {item.name for item in fields(SurfaceRecord)}, (
            "served aliases return at F7"
        )

    def test_records_are_frozen(self) -> None:
        record = _concept()
        with pytest.raises(FrozenInstanceError):
            record.term = "something else"  # type: ignore[misc]

    def test_a_surface_may_have_component_refs_and_a_manual_exception(self) -> None:
        """Register row 4: two axes, not one.

        A studi0 route maps to registered components *and* carries facts a
        person transcribed. The architecture reads as exclusive; the real
        case is not, and nothing in the model refuses the pairing.
        """
        surface = _surface(
            id="studi0:action/api/graph",
            channel="studi0",
            public_name="/api/graph",
            component_refs=(
                "component:s0ma_studi0.server.route_request",
                "component:s0ma_studi0.server.graph_document",
            ),
            manual_exception=(
                "The served routes exist only inside one request handler, so "
                "these facts were read by a person and written down."
            ),
        )
        assert surface.component_refs and surface.manual_exception
        assert "manual_exception" in json.loads(canonical_json(to_plain(surface)))


class TestSingleParagraphRule:
    """Register row 9, enforced where the schema is, not where prose is read."""

    def test_a_blank_line_in_teaching_prose_is_refused(self) -> None:
        with pytest.raises(DocsModelError, match="contains a blank line"):
            _concept(purpose="One thought.\n\nA second thought.")

    def test_the_refusal_names_the_field_and_says_what_to_do(self) -> None:
        with pytest.raises(DocsModelError) as caught:
            _concept(summary="First.\n   \nSecond.")
        message = str(caught.value)
        assert "ConceptRecord.summary" in message
        assert "single paragraph" in message

    def test_every_authored_prose_field_is_covered(self) -> None:
        """The rule follows the classification, not a hand-written list."""
        assert authored_prose_fields(ConceptRecord) == (
            "summary",
            "plain_definition",
            "purpose",
            "use_when",
            "do_not_use_when",
        )
        for name in authored_prose_fields(JourneyStep):
            with pytest.raises(DocsModelError, match="contains a blank line"):
                JourneyStep(
                    **{
                        "surface": "cli:s0ma/check",
                        "purpose": "Why.",
                        "expected_outcome": "What.",
                        name: "One.\n\nTwo.",
                    }
                )

    def test_an_empty_field_is_not_a_paragraph_break(self) -> None:
        """Whether a field may be empty is a resolution gate's question."""
        assert _surface(manual_exception="").manual_exception == ""

    def test_surrounding_whitespace_is_not_a_paragraph_break(self) -> None:
        assert _concept(purpose="One thought.\n").purpose.endswith("\n")

    def test_a_sourced_field_is_left_alone(self) -> None:
        """A quotation is verbatim or absent — the rule may not reshape it.

        This is the same boundary that keeps the voice gate off quoted
        intent: applying an authoring rule to a quotation produces either a
        false quotation or a gate that can never go green.
        """
        surface = _surface(intent="A quoted intent.\n\nWith two paragraphs in the source.")
        assert "\n\n" in surface.intent


class TestSchemaVersion:
    def test_the_version_is_the_frozen_string(self) -> None:
        assert SCHEMA == "s0ma-docs-model@1"

    def test_another_version_is_refused_by_name(self) -> None:
        with pytest.raises(DocsSchemaVersionError, match="s0ma-docs-model@1"):
            validate_schema_version("s0ma-docs-model@2")


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

#: One accepted id per form, named by the form it must match. Every form
#: D5a widened or added carries its acceptance case here and its refusal
#: case in :class:`TestIdForms` — the ratified-forms discipline: a widened
#: charset that nobody wrote a refusal for is a charset nobody bounded.
ACCEPTED_IDS: tuple[tuple[str, str], ...] = (
    ("component", "component:s0ma.api.query_engine.QueryEngine"),
    ("component", "component:s0ma_studi0.server.graph_document"),
    # D5a: two segments, the package-flat registration form. The package
    # name is what answers the collision the form exists for.
    ("component", "component:s0ma_mcp.create_server"),
    ("python", "python:s0ma.verify"),
    ("python", "python:s0ma.__version__"),
    ("python", "python:s0ma.api.rest.create_app"),
    ("concept", "concept:self-knowledge"),
    ("cli", "cli:s0ma/check"),
    ("cli", "cli:s0ma/docs/render"),
    ("cli", "cli:s0ma/deferred-surface"),
    ("mcp_tool", "mcp:tool/learn_s0ma"),
    ("mcp_resource", "mcp:resource/s0ma://guide/errors"),
    # D5a: a resource template keeps its braces, as the rest form does.
    ("mcp_resource", "mcp:resource/s0ma://model/docs-for/{component}"),
    ("mcp_prompt", "mcp:prompt/author_module"),
    ("rest", "rest:GET:/self/components"),
    ("rest", "rest:GET:/self/component/{name}"),
    ("studi0", "studi0:action/api/graph"),
    # D5a: an asset route's last segment is a filename, and the root
    # route's whole path is the slash the id form drops.
    ("studi0", "studi0:action/assets/app.css"),
    ("studi0", "studi0:action/index"),
    ("example", "example:describe_the_running_server"),
    ("diagnostic", "diagnostic:PARSE_ERROR"),
    ("diagnostic", "diagnostic:EXIT_VALIDATION_ERROR"),
    ("config", "config:build_dir"),
    ("config", "config:mode"),
    ("journey", "journey:first-project"),
    ("sequence", "sequence:concept-tour"),
    ("doc", "doc:normative/prd"),
    ("authority", "authority:prd/vision-self-knowledge"),
    ("authority", "authority:frozen_contract/inv-7"),
)


class TestIdForms:
    @pytest.mark.parametrize(("expected", "identifier"), ACCEPTED_IDS)
    def test_a_real_id_matches_the_form_it_should(self, expected: str, identifier: str) -> None:
        assert id_form(identifier) == expected
        assert validate_id(identifier) == expected

    def test_every_form_has_an_accepted_example(self) -> None:
        """A form nobody exercised is a form nobody has checked."""
        covered = {name for name, _ in ACCEPTED_IDS}
        declared = {form.name for form in ID_FORMS}
        assert declared - covered == set(), f"forms with no accepted example: {declared - covered}"

    def test_the_forms_are_mutually_exclusive(self) -> None:
        for _, identifier in ACCEPTED_IDS:
            matches = [form.name for form in ID_FORMS if form.pattern.match(identifier)]
            assert len(matches) == 1, f"{identifier} matches {matches}"

    def test_a_flat_component_name_is_refused_by_name(self) -> None:
        """The correction that came from four packages sharing one registry."""
        with pytest.raises(DocsIdError) as caught:
            validate_id("component:S0maDSL_S0maCLI")
        message = str(caught.value)
        assert "flat" in message
        assert "component:<package>.<module>.<name>" in message

    def test_two_dotted_segments_are_enough(self) -> None:
        """D5a relaxed the floor from three segments to two.

        The collision argument the form exists for is answered by the
        *package* segment: four packages share one registry, and
        ``s0ma_mcp.create_server`` says which one. Insisting on a module
        segment as well addressed nothing and left two real registrations
        of ``s0ma-mcp`` uncountable — D3 counted them in
        ``unaddressable_components`` precisely because of this line.
        """
        assert validate_id("component:s0ma.QueryEngine") == "component"
        assert validate_id("component:s0ma_mcp.get_self_registry") == "component"

    def test_a_single_segment_component_name_is_still_refused(self) -> None:
        """The relaxation stops at one: a bare name still means nothing."""
        with pytest.raises(DocsIdError, match="flat component name"):
            validate_id("component:QueryEngine")

    def test_a_module_level_export_is_addressed_package_first(self) -> None:
        """D5a's ``python:`` form, both edges."""
        assert validate_id("python:s0ma.content_hash") == "python"
        with pytest.raises(DocsIdError, match="bare name"):
            validate_id("python:content_hash")

    def test_a_configuration_key_is_addressed_as_an_author_writes_it(self) -> None:
        """D5a's ``config:`` form, both edges."""
        assert validate_id("config:test_module_name_prefix_by_dir") == "config"
        for near_miss in ("config:Build_Dir", "config:build-dir", "config:1st", "config:"):
            with pytest.raises(DocsIdError):
                validate_id(near_miss)

    def test_a_resource_template_keeps_its_braces(self) -> None:
        """D5a widened the ``mcp:resource/`` charset by exactly ``{}``."""
        assert validate_id("mcp:resource/s0ma://model/examples-for/{component}") == (
            "mcp_resource"
        )
        # The two spellings the charset still refuses, which is why the
        # convention could not be a brace-free normalization instead.
        for candidate in ("<component>", "%7Bcomponent%7D"):
            with pytest.raises(DocsIdError):
                validate_id(f"mcp:resource/s0ma://model/examples-for/{candidate}")

    def test_a_route_segment_may_carry_a_dot_but_not_a_stray_one(self) -> None:
        """D5a widened the studi0 path piece, and only that piece."""
        assert validate_id("studi0:action/assets/app.js") == "studi0"
        for near_miss in (
            "studi0:action/assets/app..js",
            "studi0:action/assets/.js",
            "studi0:action/assets/app.",
            "studi0:action/Assets/app.js",
        ):
            with pytest.raises(DocsIdError):
                validate_id(near_miss)

    def test_the_dot_did_not_leak_into_the_other_path_forms(self) -> None:
        """``_ROUTE_PATH`` is a second piece, not a widening of ``_PATH``."""
        for unwidened in (
            "mcp:tool/learn.s0ma",
            "mcp:prompt/author.module",
            "example:describe.the.server",
        ):
            with pytest.raises(DocsIdError):
                validate_id(unwidened)

    def test_the_root_route_is_addressed_by_the_documented_word(self) -> None:
        """D5a's root convention: the id says ``index``, the name says ``/``."""
        assert studi0_action_id("/") == "studi0:action/index"
        assert studi0_public_name("studi0:action/index") == "/"

    def test_the_root_spelled_as_its_own_slash_is_refused_with_the_fix(self) -> None:
        for spelling in ("studi0:action/", "studi0:action//"):
            with pytest.raises(DocsIdError) as caught:
                validate_id(spelling)
            assert "studi0:action/index" in str(caught.value)
            assert "root" in str(caught.value)

    def test_a_literal_index_route_is_refused_rather_than_sharing_the_id(self) -> None:
        """Two routes on one id would silently replace each other."""
        with pytest.raises(DocsIdError, match="already holds"):
            studi0_action_id("/index")

    def test_the_doubled_colon_on_an_example_is_refused_explicitly(self) -> None:
        """One character apart from the authoring syntax already in prose."""
        with pytest.raises(DocsIdError) as caught:
            validate_id("example::describe_the_running_server")
        message = str(caught.value)
        assert "two colons" in message
        assert "example:describe_the_running_server" in message

    def test_a_lowercase_diagnostic_code_is_refused(self) -> None:
        with pytest.raises(DocsIdError, match="capitals with underscores"):
            validate_id("diagnostic:parse_error")

    def test_a_studi0_id_that_kept_its_slash_is_refused_with_the_fix(self) -> None:
        with pytest.raises(DocsIdError) as caught:
            validate_id("studi0:action//api/graph")
        assert "studi0:action/api/graph" in str(caught.value)

    @pytest.mark.parametrize(
        "identifier",
        [
            "",
            "concept",
            "concept:Nerve",
            "concept:self_knowledge",
            "cli:check",
            "cli:s0ma/Docs",
            "rest:get:/self/components",
            "authority:invented/thing",
            "doc:normative",
            "widget:thing",
            "sequence:Concept-Tour",
        ],
    )
    def test_a_near_miss_is_refused(self, identifier: str) -> None:
        assert id_form(identifier) is None
        with pytest.raises(DocsIdError):
            validate_id(identifier)

    def test_the_minted_sequence_form_says_it_is_not_frozen(self) -> None:
        """C1 minted ``sequence:``; the note is how the C gate finds out.

        The teaching-sequence record was ratified without an id form to
        address it. Rather than leave its ids unvalidatable, C1 mints one
        and marks it, the way the B gate handled the example form.
        """
        note = next(form.note for form in ID_FORMS if form.name == "sequence")
        assert "NOT part of the §5 frozen set" in note


class TestNormalizationAndConstruction:
    def test_normalization_drops_the_studi0_leading_slash(self) -> None:
        assert normalize_id("studi0:action//api/graph") == "studi0:action/api/graph"

    def test_normalization_changes_nothing_else(self) -> None:
        for _, identifier in ACCEPTED_IDS:
            assert normalize_id(identifier) == identifier

    def test_normalization_maps_both_spellings_of_the_root(self) -> None:
        """D5a's second transformation, and the only other one there is."""
        assert normalize_id("studi0:action/") == "studi0:action/index"
        assert normalize_id("studi0:action//") == "studi0:action/index"

    def test_identity_compares_with_the_slash_stripped(self) -> None:
        assert same_identity("studi0:action//api/graph", "studi0:action/api/graph")
        assert not same_identity("cli:s0ma/check", "cli:s0ma/build")

    def test_identity_compares_the_root_through_the_documented_map(self) -> None:
        """The gate compares through the convention, not around it."""
        assert same_identity("studi0:action/", "studi0:action/index")
        assert same_identity("studi0:action//", "studi0:action/index")
        assert not same_identity("studi0:action/index", "studi0:action/api/graph")

    def test_the_served_name_keeps_the_slash(self) -> None:
        assert studi0_action_id("/api/graph") == "studi0:action/api/graph"
        assert studi0_action_id("api/graph") == "studi0:action/api/graph"
        assert studi0_public_name("studi0:action/api/graph") == "/api/graph"

    def test_every_served_route_round_trips_through_both_conventions(self) -> None:
        """id → name → id, over the five routes studi0 actually serves."""
        for route in ("/", "/api/state", "/api/graph", "/assets/app.css", "/assets/app.js"):
            identifier = studi0_action_id(route)
            assert studi0_public_name(identifier) == route
            assert studi0_action_id(studi0_public_name(identifier)) == identifier

    def test_a_command_path_joins_with_slashes(self) -> None:
        assert cli_id("check") == "cli:s0ma/check"
        assert cli_id("docs", "render") == "cli:s0ma/docs/render"
        with pytest.raises(DocsIdError, match="at least one path segment"):
            cli_id()


class TestAliases:
    def test_a_renamed_id_resolves_forward(self) -> None:
        index = AliasIndex.of({"cli:s0ma/old-name": "cli:s0ma/new-name"})
        assert index.canonical("cli:s0ma/old-name") == "cli:s0ma/new-name"

    def test_a_chain_of_renames_resolves_in_one_call(self) -> None:
        index = AliasIndex.of(
            {"concept:one": "concept:two", "concept:two": "concept:three"}
        )
        assert index.canonical("concept:one") == "concept:three"

    def test_an_unknown_id_is_its_own_answer(self) -> None:
        assert AliasIndex.of({}).canonical("concept:drift") == "concept:drift"

    def test_a_circle_is_refused(self) -> None:
        index = AliasIndex.of({"concept:one": "concept:two", "concept:two": "concept:one"})
        with pytest.raises(DocsIdError, match="circle"):
            index.canonical("concept:one")

    def test_entries_are_sorted_so_two_equal_indexes_are_equal(self) -> None:
        first = AliasIndex.of([("b", "x"), ("a", "y")])
        second = AliasIndex.of([("a", "y"), ("b", "x")])
        assert first == second


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _permute(value: Any) -> Any:
    """The same data with every object's keys in reverse order."""
    if isinstance(value, dict):
        return {key: _permute(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [_permute(item) for item in value]
    return value


class TestCanonicalSerialization:
    def test_a_bundle_round_trips_byte_for_byte(self, bundle: DocsBundle) -> None:
        text = serialize_bundle(bundle)
        assert serialize_bundle(deserialize_bundle(text)) == text

    def test_reading_a_bundle_back_gives_the_same_records(self, bundle: DocsBundle) -> None:
        assert deserialize_bundle(serialize_bundle(bundle)) == bundle

    def test_key_order_on_the_way_in_does_not_reach_the_output(
        self, bundle: DocsBundle
    ) -> None:
        text = serialize_bundle(bundle)
        shuffled = json.dumps(_permute(json.loads(text)), indent=2, ensure_ascii=False) + "\n"
        assert shuffled != text, "the permutation did not actually change the text"
        assert serialize_bundle(deserialize_bundle(shuffled)) == text

    def test_record_order_within_a_group_does_not_reach_the_output(self) -> None:
        bundle = _bundle()
        second = dataclasses.replace(_concept(), id="concept:nerve", term="nerve")
        forwards = dataclasses.replace(bundle, concepts=(*bundle.concepts, second))
        backwards = dataclasses.replace(bundle, concepts=(second, *bundle.concepts))
        assert serialize_bundle(forwards) == serialize_bundle(backwards)

    def test_the_text_ends_with_exactly_one_line_feed(self, bundle: DocsBundle) -> None:
        text = serialize_bundle(bundle)
        assert text.endswith("\n")
        assert not text.endswith("\n\n")
        assert "\r" not in text

    def test_the_same_records_serialize_the_same_under_any_hash_seed(self) -> None:
        """Determinism rule 4, proved the only way it can be proved.

        Dictionary iteration is the usual way a hash seed reaches output,
        so the check has to happen in a fresh process with the seed set.
        """
        script = (
            "from tests.test_docs_model_records import _bundle;"
            "from s0ma_dsl.docs_model import serialize_bundle;"
            "print(serialize_bundle(_bundle()), end='')"
        )
        root = Path(__file__).resolve().parents[1]
        outputs = []
        for seed in ("0", "1", "524287"):
            environment = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(root)}
            result = subprocess.run(
                [sys.executable, "-c", script],
                check=True,
                capture_output=True,
                text=True,
                cwd=root,
                env=environment,
            )
            outputs.append(result.stdout)
        assert outputs[0] == outputs[1] == outputs[2]
        assert outputs[0] == serialize_bundle(_bundle())

    def test_a_decimal_number_is_refused_rather_than_written(self) -> None:
        with pytest.raises(DocsSerializationError, match="decimal numbers"):
            to_plain(1.5)
        with pytest.raises(DocsSerializationError, match="decimal numbers"):
            to_plain((0.1, 0.2))


class TestBuildStamp:
    def test_the_schema_is_stamped_exactly_once(self, bundle: DocsBundle) -> None:
        """Row 2, at the level of bytes: one stamp, no per-record copies."""
        text = serialize_bundle(bundle)
        assert text.count('"schema":') == 1
        assert json.loads(text)["stamp"]["schema"] == SCHEMA

    def test_a_provider_may_still_name_the_version_it_emitted_against(
        self, bundle: DocsBundle
    ) -> None:
        """``schema_version`` on provenance is a different claim, not a copy."""
        document = json.loads(serialize_bundle(bundle))
        assert document["surfaces"][0]["provenance"]["schema_version"] == SCHEMA
        assert "schema" not in document["surfaces"][0]["provenance"]

    def test_the_snapshot_digest_covers_the_records_and_not_the_stamp(self) -> None:
        bundle = _bundle()
        restamped = stamped(bundle, "9.9.9")
        assert snapshot_hash(bundle) == snapshot_hash(restamped)
        assert restamped.stamp.release_version == "9.9.9"
        assert restamped.stamp.snapshot_hash == snapshot_hash(bundle)

    def test_moving_one_record_restamps_the_snapshot(self) -> None:
        bundle = _bundle()
        changed = dataclasses.replace(
            bundle, concepts=(_concept(summary="A different short form."),)
        )
        assert snapshot_hash(changed) != snapshot_hash(bundle)

    def test_the_serializer_refuses_a_bundle_stamped_with_another_version(
        self, bundle: DocsBundle
    ) -> None:
        wrong = dataclasses.replace(
            bundle, stamp=dataclasses.replace(bundle.stamp, schema="s0ma-docs-model@0")
        )
        with pytest.raises(DocsSchemaVersionError):
            serialize_bundle(wrong)

    def test_the_groups_the_serializer_writes_are_the_bundle_s_own(self) -> None:
        """Every field of the bundle is written, and the digest says which.

        Flipped at F9, knowingly. ``aliases`` is a field of the bundle and
        is written like a group, but it is deliberately outside
        ``_GROUPS`` — the snapshot digest covers what a build *says*, and
        an alias says nothing new, it only widens the ways of asking. So
        the invariant is now stated in two halves: the serializer writes
        every field, and exactly one written field is outside the digest.
        """
        declared = {item.name for item in fields(DocsBundle)}
        written = set(serialize_module._GROUPS) | {"stamp", serialize_module._ALIASES}

        assert written == declared
        assert serialize_module._ALIASES not in serialize_module._GROUPS


class TestHashing:
    def test_the_digest_is_the_house_form(self) -> None:
        digest = content_hash(_surface())
        assert digest.startswith("sha256:")
        body = digest.removeprefix("sha256:")
        assert len(body) == 16
        assert all(character in "0123456789abcdef" for character in body)

    def test_two_equal_records_have_one_digest(self) -> None:
        assert content_hash(_surface()) == content_hash(_surface())

    def test_a_changed_fact_changes_the_digest(self) -> None:
        assert content_hash(_surface()) != content_hash(_surface(public_name="verify"))

    def test_agreement_across_two_sources_is_agreement(self) -> None:
        """The merge rule's comparison: same facts, different provenance.

        Two providers deriving one truth from two sources must be
        recognizable as agreeing, or the composition reports a conflict
        that does not exist.
        """
        first = _surface()
        second = _surface(provenance=_provenance(adapter="mcp.snapshot"))
        assert facts_hash(first) == facts_hash(second)
        assert content_hash(first) != content_hash(second)

    def test_disagreement_about_the_facts_still_shows(self) -> None:
        first = _surface()
        second = _surface(
            public_name="verify", provenance=_provenance(adapter="mcp.snapshot")
        )
        assert facts_hash(first) != facts_hash(second)


class TestReadingBack:
    def test_an_unknown_key_is_refused(self) -> None:
        raw = to_plain(_concept())
        raw["invented"] = "x"
        with pytest.raises(DocsSerializationError, match="unexpected"):
            record_from_plain(ConceptRecord, raw, "concepts[0]")

    def test_a_missing_key_is_refused(self) -> None:
        raw = to_plain(_concept())
        del raw["summary"]
        with pytest.raises(DocsSerializationError, match="absent"):
            record_from_plain(ConceptRecord, raw, "concepts[0]")

    def test_a_wrong_type_is_refused_with_the_place_it_happened(self) -> None:
        raw = to_plain(_concept())
        raw["governed_by"] = "authority:spec/drift-check"
        with pytest.raises(DocsSerializationError, match=r"concepts\[0\].governed_by"):
            record_from_plain(ConceptRecord, raw, "concepts[0]")

    def test_a_nested_record_is_built_and_checked(self) -> None:
        raw = to_plain(_surface())
        del raw["provenance"]["source"]
        with pytest.raises(DocsSerializationError, match=r"surfaces\[0\].provenance"):
            record_from_plain(SurfaceRecord, raw, "surfaces[0]")

    def test_a_bundle_from_another_version_is_refused_for_that_reason(
        self, bundle: DocsBundle
    ) -> None:
        document = json.loads(serialize_bundle(bundle))
        document["stamp"]["schema"] = "s0ma-docs-model@2"
        with pytest.raises(DocsSchemaVersionError):
            deserialize_bundle(json.dumps(document))

    def test_a_bundle_with_no_stamp_names_no_version(self) -> None:
        with pytest.raises(DocsSerializationError, match="no build stamp"):
            deserialize_bundle('{"concepts": []}')

    def test_the_rules_are_enforced_on_the_way_in_too(self, bundle: DocsBundle) -> None:
        """A blank line cannot enter through a file either."""
        document = json.loads(serialize_bundle(bundle))
        document["concepts"][0]["purpose"] = "One.\n\nTwo."
        with pytest.raises(DocsModelError, match="contains a blank line"):
            deserialize_bundle(json.dumps(document))


# ---------------------------------------------------------------------------
# What the model is allowed to depend on
# ---------------------------------------------------------------------------


class TestDependencies:
    """ADR-012 and the D-4 guard, checked against the source itself."""

    @pytest.mark.parametrize("filename", MODEL_FILES)
    def test_the_model_imports_nothing_it_should_not(self, filename: str) -> None:
        """Stdlib and this package only.

        Every provider, gate, renderer and read surface reads these
        records. If the model reached into the framework, the agent
        interface or the viewer, each of them would inherit that reach.
        """
        forbidden = ("s0ma.", "s0ma_mcp", "s0ma_studi0", "spike_", "scripts.")
        tree = ast.parse((MODEL_DIR / filename).read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        offenders = [
            name
            for name in imported
            if name == "s0ma" or name.startswith(forbidden)
        ]
        assert offenders == [], f"{filename} imports {offenders}"

    @pytest.mark.parametrize("filename", MODEL_FILES)
    def test_the_source_is_utf8_with_line_feeds(self, filename: str) -> None:
        raw = (MODEL_DIR / filename).read_bytes()
        raw.decode("utf-8")
        assert b"\r\n" not in raw
