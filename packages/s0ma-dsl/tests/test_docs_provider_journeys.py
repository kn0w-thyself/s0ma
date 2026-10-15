"""Gates for E1 — the authored journeys, their loader, and their four rules.

Milestone E1 of the docs-function plan (internal) §10. Three things are
held in place here, in the order a build meets them:

* **the loader** (T1) — one file per journey, its shape refused with the
  JSON path of the value that is wrong, its content reported as findings;
* **the three real journeys** (T3) — every step, every taught concept and
  every recovery failure resolves against the *live* composition, not
  against a fixture written to agree with them;
* **the renderer flow** (T4) — ``journey:first-project`` through all three
  channels with the new fields carried, read back, and compared against
  the fact reading rather than against another rendering.

The four gates themselves are fired in the C9 battery
(``test_docs_model_negative.py``, ``TestJourneys``), which is where every
``DOC_*`` code in the ``docs_model`` tree is accounted for. What is here
is the other half: that they are green on the corpus, and that the
teaching gate has real prerequisite edges to walk rather than passing by
having nothing to look at.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.docs_model import render_agent as agent_channel
from s0ma_dsl.docs_model import render_human as human_channel
from s0ma_dsl.docs_model import render_json as json_channel
from s0ma_dsl.docs_model.application import build as build_documentation
from s0ma_dsl.docs_model.application import registry
from s0ma_dsl.docs_model.ids import normalize_id
from s0ma_dsl.docs_model.providers_concepts import DOC_VOICE_VIOLATION
from s0ma_dsl.docs_model.providers_journeys import (
    JOURNEY_FLOORS,
    JOURNEYS_DIR,
    JOURNEYS_SCHEMA,
    NOT_A_SURFACE,
    ONE_LINE_FIELDS,
    DocsJourneysError,
    JourneysProvider,
)
from s0ma_dsl.docs_model.records import SCHEMA, JourneyRecord
from s0ma_dsl.docs_model.render_agent import check_budget, render_agent
from s0ma_dsl.docs_model.render_human import render_human
from s0ma_dsl.docs_model.render_json import render_json
from s0ma_dsl.docs_model.resolve import TopicIndex, canonical_fact
from s0ma_dsl.docs_model.validate import (
    DOC_APPROVAL_UNDECLARED,
    DOC_JOURNEY_UNRESOLVED,
    DOC_JOURNEY_UNTESTED,
    DOC_TEACHING_ORDER,
    TEACHING_PREREQUISITE,
    ReferenceIndex,
    check_journeys,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: What E1 migrates from the B-phase prototypes, with the step count each
#: was authored with. Written down rather than counted, because the point
#: of the migration is that these three paths are the ones B4 and B7
#: proved and not three paths that happen to be here.
EXPECTED_JOURNEYS: tuple[tuple[str, int, int], ...] = (
    ("journey:drift-recovery", 6, 3),
    ("journey:first-module", 3, 1),
    ("journey:first-project", 7, 2),
    ("journey:mcp-authoring-loop", 5, 3),
    ("journey:retrofit-existing-codebase", 9, 1),
    ("journey:studi0-feedback", 5, 1),
    ("journey:studi0-viewing", 3, 1),
)


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


# ---------------------------------------------------------------------------
# Fixture material
# ---------------------------------------------------------------------------


def _step(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "approval_boundary": "",
        "expected_outcome": "A skeleton, and a note saying what went where.",
        "purpose": "Get a folder that is already a project.",
        "surface": "cli:s0ma/new",
    }
    values.update(overrides)
    return values


def _record(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "concepts_required": [],
        "concepts_taught": [],
        "evidence": [],
        "id": "journey:first-project",
        "intent": "Take somebody from an empty folder to a check they trust.",
        "recovery_paths": [],
        "steps": [_step()],
    }
    values.update(overrides)
    return values


def _written(
    tmp_path: Path, *, stem: str = "first-project", schema: str = JOURNEYS_SCHEMA, **overrides: Any
) -> JourneysProvider:
    """One journeys directory holding one file, ready to be read."""
    directory = tmp_path / "journeys"
    directory.mkdir(exist_ok=True)
    document: dict[str, Any] = {"record": _record(**overrides), "schema": schema}
    (directory / f"{stem}.json").write_text(
        json.dumps(document, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return JourneysProvider(root=tmp_path, relative="journeys")


def _raw(tmp_path: Path, text: str, *, stem: str = "first-project") -> JourneysProvider:
    """A journeys directory holding text this loader has to refuse or read."""
    directory = tmp_path / "journeys"
    directory.mkdir(exist_ok=True)
    (directory / f"{stem}.json").write_text(text, encoding="utf-8", newline="\n")
    return JourneysProvider(root=tmp_path, relative="journeys")


# ---------------------------------------------------------------------------
# The loader's shape refusals (T1)
# ---------------------------------------------------------------------------


class TestTheFileShape:
    """A file whose shape is wrong yields no record, and says which value."""

    def test_a_well_formed_file_reads(self, tmp_path: Path) -> None:
        result = _written(tmp_path).provide()
        assert result.provider_id == "journeys"
        assert [item.record.id for item in result.records] == ["journey:first-project"]

    def test_a_missing_directory_is_refused_by_name(self, tmp_path: Path) -> None:
        provider = JourneysProvider(root=tmp_path, relative="nowhere")
        with pytest.raises(DocsJourneysError, match="not a directory"):
            provider.provide()

    def test_a_file_that_is_not_json(self, tmp_path: Path) -> None:
        with pytest.raises(DocsJourneysError, match="not readable as JSON"):
            _raw(tmp_path, "{ nope\n").provide()

    def test_another_schema_version(self, tmp_path: Path) -> None:
        with pytest.raises(DocsJourneysError, match="#/schema"):
            _written(tmp_path, schema="s0ma-docs-journeys@2").provide()

    def test_a_stray_key_and_a_missing_one_are_both_refused(self, tmp_path: Path) -> None:
        """C1's reason: a reader that tolerated either would drop what was written."""
        for edit, expected in (("add", "audiences"), ("drop", "intent")):
            record = _record()
            if edit == "add":
                record["audiences"] = []
            else:
                del record["intent"]
            text = json.dumps(
                {"record": record, "schema": JOURNEYS_SCHEMA}, sort_keys=True, indent=2
            )
            with pytest.raises(DocsJourneysError, match=expected):
                _raw(tmp_path, text + "\n").provide()

    def test_the_file_name_and_the_record_have_to_agree(self, tmp_path: Path) -> None:
        """A file renamed without its record is orphaned, not silently fine."""
        with pytest.raises(DocsJourneysError) as caught:
            _written(tmp_path, stem="something-else").provide()
        assert "something-else.json" in str(caught.value)
        assert "journey:first-project" in str(caught.value)

    def test_an_id_that_is_not_a_journey(self, tmp_path: Path) -> None:
        with pytest.raises(DocsJourneysError, match="not a journey id"):
            _written(tmp_path, id="concept:first-project").provide()

    def test_a_journey_with_no_steps(self, tmp_path: Path) -> None:
        with pytest.raises(DocsJourneysError, match="is empty"):
            _written(tmp_path, steps=[]).provide()

    @pytest.mark.parametrize("form", sorted(NOT_A_SURFACE))
    def test_a_step_naming_something_that_is_not_a_capability(
        self, tmp_path: Path, form: str
    ) -> None:
        """B7 finding 4, acted on: the refusal says where it belongs instead.

        A step naming ``concept:nerve`` used to report "surface
        concept:nerve does not resolve", which sends an author looking for
        a missing surface rather than telling them that ordered teaching
        over concepts is a different record.
        """
        named = {
            "concept": "concept:nerve",
            "config": "config:build_dir",
            "diagnostic": "diagnostic:PARSE_ERROR",
            "journey": "journey:studi0-viewing",
            "sequence": "sequence:concept-tour",
            "doc": "doc:normative/prd",
            "authority": "authority:prd/P-1",
            "example": "example:first_nerve",
        }[form]
        with pytest.raises(DocsJourneysError) as caught:
            _written(tmp_path, steps=[_step(surface=named)]).provide()
        assert named in str(caught.value)
        assert NOT_A_SURFACE[form].split(".")[0] in str(caught.value)

    def test_a_teaching_order_that_says_one_concept_twice(self, tmp_path: Path) -> None:
        with pytest.raises(DocsJourneysError, match="taught twice"):
            _written(
                tmp_path, concepts_taught=["concept:nerve", "concept:nerve"]
            ).provide()

    def test_a_prerequisite_list_that_is_not_sorted(self, tmp_path: Path) -> None:
        with pytest.raises(DocsJourneysError, match="not sorted"):
            _written(
                tmp_path, concepts_required=["concept:nerve", "concept:layer"]
            ).provide()

    def test_a_teaching_order_that_is_not_sorted_is_fine(self, tmp_path: Path) -> None:
        """The one list this model reads in the author's order, on purpose."""
        provider = _written(
            tmp_path, concepts_taught=["concept:nerve", "concept:layer"]
        )
        record = provider.provide().records[0].record
        assert isinstance(record, JourneyRecord)
        assert record.concepts_taught == ("concept:nerve", "concept:layer")

    def test_evidence_that_is_not_an_example_id(self, tmp_path: Path) -> None:
        with pytest.raises(DocsJourneysError, match="not an example id"):
            _written(
                tmp_path, evidence=[{"id": "example::doubled", "source": "x.s0ma"}]
            ).provide()

    def test_two_recoveries_for_one_failure(self, tmp_path: Path) -> None:
        recovery = {
            "action": "Read the first finding.",
            "next_surface": "cli:s0ma/check",
            "when": "PARSE_ERROR",
        }
        with pytest.raises(DocsJourneysError, match="already has a recovery path"):
            _written(tmp_path, recovery_paths=[recovery, dict(recovery)]).provide()

    @pytest.mark.parametrize("field", ("purpose", "expected_outcome", "approval_boundary"))
    def test_a_line_break_in_a_field_written_one_to_a_line(
        self, tmp_path: Path, field: str
    ) -> None:
        assert field in ONE_LINE_FIELDS
        with pytest.raises(DocsJourneysError, match="line break"):
            _written(tmp_path, steps=[_step(**{field: "One.\nTwo."})]).provide()

    def test_two_files_claiming_one_journey(self, tmp_path: Path) -> None:
        directory = tmp_path / "journeys"
        directory.mkdir()
        for stem in ("first-project", "second-project"):
            document = {"record": _record(id=f"journey:{stem}"), "schema": JOURNEYS_SCHEMA}
            (directory / f"{stem}.json").write_text(
                json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
        # Make the second file claim the first file's id, keeping its name.
        second = directory / "second-project.json"
        second.write_text(
            json.dumps(
                {"record": _record(id="journey:first-project"), "schema": JOURNEYS_SCHEMA},
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        with pytest.raises(DocsJourneysError):
            JourneysProvider(root=tmp_path, relative="journeys").provide()


# ---------------------------------------------------------------------------
# The provider contract
# ---------------------------------------------------------------------------


class TestTheProviderContract:
    """Sorted, normalized, stamped, and the same answer twice."""

    def test_the_records_are_stamped_with_the_file_they_came_from(
        self, tmp_path: Path
    ) -> None:
        import hashlib

        provider = _written(tmp_path)
        held = provider.provide().records[0]
        text = (tmp_path / "journeys" / "first-project.json").read_text(encoding="utf-8")
        assert held.provenance.adapter_id == "journeys"
        assert held.provenance.schema_version == SCHEMA
        assert held.provenance.source == "journeys/first-project.json"
        assert held.provenance.source_sha256 == hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()

    def test_every_id_is_already_its_comparable_form(self, tmp_path: Path) -> None:
        for item in _written(tmp_path).provide().records:
            assert normalize_id(item.record.id) == item.record.id

    def test_two_readings_in_one_process_are_equal(self, tmp_path: Path) -> None:
        provider = _written(tmp_path)
        assert provider.provide() == provider.provide()
        assert provider.findings() == provider.findings()

    def test_reading_writes_nothing(self, tmp_path: Path) -> None:
        provider = _written(tmp_path)
        before = sorted(path.name for path in (tmp_path / "journeys").iterdir())
        provider.provide()
        provider.findings()
        assert sorted(path.name for path in (tmp_path / "journeys").iterdir()) == before


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------


class TestVoice:
    """Every word of a journey is authored, so the rule reaches all of it."""

    @pytest.mark.parametrize(
        ("where", "overrides"),
        (
            ("intent", {"intent": "Send the payload to the server."}),
            ("steps[0].purpose", {"steps": [_step(purpose="Read the payload back.")]}),
            (
                "recovery_paths[0].action",
                {
                    "recovery_paths": [
                        {
                            "action": "Look at the payload again.",
                            "next_surface": "cli:s0ma/check",
                            "when": "PARSE_ERROR",
                        }
                    ]
                },
            ),
        ),
    )
    def test_a_word_the_product_does_not_use(
        self, tmp_path: Path, where: str, overrides: dict[str, Any]
    ) -> None:
        """A finding, not a refusal: the record is still built and reported on."""
        provider = _written(tmp_path, **overrides)
        assert provider.provide().records
        findings = provider.findings()
        assert [item.code for item in findings] == [DOC_VOICE_VIOLATION]
        assert where in findings[0].message
        assert findings[0].location == "journeys/first-project.json"

    def test_the_authored_files_are_clean(self, tmp_path: Path) -> None:
        assert _written(tmp_path).findings() == ()


# ---------------------------------------------------------------------------
# The three real journeys (T3)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live() -> Any:
    """The whole documentation build, composed once for this module."""
    return build_documentation(REPO_ROOT)


@requires_checkout
class TestTheAuthoredJourneys:
    """B7's three prototypes, migrated onto the final schema."""

    def test_the_three_are_composed_with_the_step_counts_they_were_authored_with(
        self, live: Any
    ) -> None:
        found = tuple(
            (record.id, len(record.steps), len(record.recovery_paths))
            for record in live.bundle.journeys
        )
        assert found == EXPECTED_JOURNEYS

    def test_the_composition_reports_nothing(self, live: Any) -> None:
        assert [item.rendered() for item in live.findings] == []

    def test_every_step_names_a_surface_this_build_really_serves(
        self, live: Any
    ) -> None:
        """The ids moved between B7 and now; this is what says they landed."""
        served = {normalize_id(record.id) for record in live.bundle.surfaces}
        for journey in live.bundle.journeys:
            for step in journey.steps:
                assert normalize_id(step.surface) in served, step.surface
            for path in journey.recovery_paths:
                assert normalize_id(path.next_surface) in served, path.next_surface

    def test_every_taught_and_required_concept_is_one_somebody_wrote(
        self, live: Any
    ) -> None:
        written = {normalize_id(record.id) for record in live.bundle.concepts}
        for journey in live.bundle.journeys:
            for identifier in (*journey.concepts_taught, *journey.concepts_required):
                assert normalize_id(identifier) in written, identifier

    def test_the_three_channels_are_all_walked(self, live: Any) -> None:
        """One journey per channel family, which is what B7 set out to prove."""
        channels = {
            step.surface.partition(":")[0]
            for journey in live.bundle.journeys
            for step in journey.steps
        }
        assert channels == {"cli", "mcp", "studi0"}

    def test_the_floor_is_the_count_the_directory_holds(self, live: Any) -> None:
        assert JOURNEY_FLOORS[("journeys", "journeys")] == len(EXPECTED_JOURNEYS)
        assert len(live.bundle.journeys) >= JOURNEY_FLOORS[("journeys", "journeys")]

    def test_the_files_are_where_the_application_says_they_are(self) -> None:
        directory = REPO_ROOT / JOURNEYS_DIR
        assert directory.is_dir()
        stems = sorted(path.stem for path in directory.glob("*.json"))
        assert stems == sorted(
            identifier.partition(":")[2] for identifier, _, _ in EXPECTED_JOURNEYS
        )

    def test_the_files_are_utf8_with_line_feeds_and_one_trailing_newline(self) -> None:
        for path in sorted((REPO_ROOT / JOURNEYS_DIR).glob("*.json")):
            raw = path.read_bytes()
            assert b"\r" not in raw, path
            assert raw.endswith(b"\n") and not raw.endswith(b"\n\n"), path
            raw.decode("utf-8")

    def test_the_provider_is_registered_with_the_application(self) -> None:
        assert "journeys" in registry(REPO_ROOT).ids()


# ---------------------------------------------------------------------------
# The gates, on the corpus (T2)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheGatesOnTheCorpus:
    """Green, and green for a reason rather than for lack of a subject."""

    def test_the_four_gates_find_nothing(self, live: Any) -> None:
        index = ReferenceIndex.of(live.bundle)
        assert check_journeys(live.bundle, index) == []

    def test_the_teaching_gate_has_real_prerequisites_to_walk(
        self, live: Any
    ) -> None:
        """The anti-vacuity clause: a gate with nothing to check passes.

        Counted rather than asserted as a boolean, because the number is
        what says the concept graph is carrying the rule: the three
        journeys teach concepts that between them rest on other concepts
        several times over, and every one of those edges is a comparison
        this gate really made.
        """
        prerequisites = {
            normalize_id(record.id): tuple(
                target
                for relation, target in record.related_concepts
                if relation == TEACHING_PREREQUISITE
            )
            for record in live.bundle.concepts
        }
        walked = sum(
            len(prerequisites.get(normalize_id(taught), ()))
            for journey in live.bundle.journeys
            for taught in journey.concepts_taught
        )
        assert walked >= 5, "the teaching gate is passing by having nothing to check"

    def test_the_untested_gate_is_a_seam_and_not_a_hole(self, live: Any) -> None:
        """No resolver means the question is not asked; a resolver asks it.

        E2 lands the runner that can be one. Until then the honest state
        is three journeys with no evidence and a gate nobody has asked, and
        this is what says the gate would fire the moment somebody does.
        """
        index = ReferenceIndex.of(live.bundle)
        assert [
            item.code
            for item in check_journeys(
                live.bundle, index, evidence_resolver=lambda _: ()
            )
        ] == [DOC_JOURNEY_UNTESTED] * len(EXPECTED_JOURNEYS)

    def test_the_approval_boundary_is_crossed_only_where_declared(self, live: Any) -> None:
        """The positive form the "yet" test retired into at the E wave.

        E7's `journey:studi0-feedback` is the gate's first subject: its
        compose and submit steps take approval-class surfaces and each
        carries an authored boundary. Every other journey stays outside
        the asking set with every boundary empty — the both-directions
        rule `check_journeys` enforces, restated here over the live corpus
        so the corpus itself documents where consent happens.
        """
        asking = {
            record.id for record in live.bundle.surfaces if "approval" in record.side_effects
        }
        assert asking, "no surface declares an approval, so the gate has no subject"
        crossings = {
            (journey.id, step.surface)
            for journey in live.bundle.journeys
            for step in journey.steps
            if step.surface in asking
        }
        assert crossings == {
            ("journey:studi0-feedback", "cli:s0ma/feedback"),
            ("journey:studi0-feedback", "cli:s0ma/feedback/submit"),
        }
        for journey in live.bundle.journeys:
            for step in journey.steps:
                assert (step.approval_boundary != "") == (step.surface in asking), (
                    f"{journey.id} step {step.surface}: boundary and "
                    f"approval-class membership must agree"
                )

    def test_every_recovery_failure_is_answerable_and_says_how(
        self, live: Any
    ) -> None:
        """The two ways a failure is real, both exercised by the corpus."""
        addressed = {normalize_id(record.id) for record in live.bundle.surfaces}
        by_diagnostic = 0
        by_declared_error = 0
        for journey in live.bundle.journeys:
            declared = {
                code
                for step in journey.steps
                for record in live.bundle.surfaces
                if normalize_id(record.id) == normalize_id(step.surface)
                for code in record.errors
            }
            for path in journey.recovery_paths:
                if path.when in declared:
                    by_declared_error += 1
                elif normalize_id(f"diagnostic:{path.when}") in addressed:
                    by_diagnostic += 1
                else:  # pragma: no cover - the gate above already refused it
                    pytest.fail(f"{journey.id} recovers from {path.when}, unanswerably")
        assert by_diagnostic and by_declared_error


# ---------------------------------------------------------------------------
# The renderer flow (T4)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheRendererFlow:
    """``journey:first-project`` on three channels, with the new fields."""

    @pytest.fixture()
    def view(self, live: Any) -> Any:
        return TopicIndex.of(live.bundle).view("journey:first-project")

    def test_the_page_names_every_new_fact_it_carries(self, view: Any) -> None:
        page = render_human(view)
        spec = human_channel.spec_for("journeys")
        for fact in ("concepts_taught", "concepts_required"):
            assert spec.label_of(fact) in page, fact
            for identifier in view.items(fact):
                assert f"- `{identifier}`" in page, identifier

    def test_an_empty_non_identity_fact_leaves_its_section_out(self, view: Any) -> None:
        """These journeys cross no boundary, so the page says nothing about one."""
        assert view.items("approval_boundaries") == ()
        assert "Where you are asked first" not in render_human(view)

    def test_the_teaching_order_is_written_in_order(self, view: Any) -> None:
        """A sorted rendering of an ordered fact would lose the whole fact."""
        page = render_human(view)
        positions = [page.index(f"- `{item}`") for item in view.items("concepts_taught")]
        assert positions == sorted(positions)
        assert view.items("concepts_taught") != tuple(sorted(view.items("concepts_taught")))

    def test_the_json_channel_writes_them_at_a_declared_key(self, view: Any) -> None:
        document = json.loads(render_json(view))
        assert document["topic"]["concepts_taught"] == list(view.items("concepts_taught"))
        assert document["topic"]["concepts_required"] == list(
            view.items("concepts_required")
        )
        assert document["topic"]["approval_boundaries"] == []
        spec = json_channel.spec_for("journeys")
        assert json_channel.undeclared_keys(render_json(view), spec) == ()

    def test_the_bounded_channel_omits_them_and_points(self, view: Any) -> None:
        """Rule (b): a bounded channel gets smaller by omitting, never by rewriting."""
        answer = render_agent(view)
        assert check_budget(view, answer) == []
        assert "concept:strictness-mode" not in answer
        assert "Read more" in answer
        assert agent_channel.undeclared_labels(answer, agent_channel.spec_for("journeys")) == ()

    def test_every_fact_survives_the_round_trip_on_every_channel(
        self, view: Any
    ) -> None:
        """B5's residue rule: verbatim or absent, compared against the facts.

        Read back from the rendered text rather than from the record, so
        an edit to a rendering changes what this compares — which is what
        stops the check being a renderer talking to itself.
        """
        channels = (
            (human_channel.spec_for("journeys"), render_human(view), human_channel.extract),
            (json_channel.spec_for("journeys"), render_json(view), json_channel.extract),
            (agent_channel.spec_for("journeys"), render_agent(view), agent_channel.extract),
        )
        for spec, text, extract in channels:
            read = extract(text, spec)
            for fact in spec.order:
                expected = canonical_fact(fact, view.value(fact))
                if fact not in read:
                    # Absent is allowed only where the value is empty and
                    # the fact is not identity; the page's own rule.
                    assert expected in ("", ()), f"{spec.channel} dropped {fact}"
                    continue
                assert canonical_fact(fact, read[fact]) == expected, (
                    f"{spec.channel} changed {fact}"
                )

    def test_the_page_adds_no_heading_no_declaration_accounts_for(
        self, view: Any
    ) -> None:
        page = render_human(view)
        spec = human_channel.spec_for("journeys")
        assert human_channel.undeclared_headings(page, spec) == ()

    def test_the_other_two_journeys_render_too(self, live: Any) -> None:
        index = TopicIndex.of(live.bundle)
        for identifier, _, _ in EXPECTED_JOURNEYS:
            held = index.view(identifier)
            for rendered in (render_human(held), render_json(held), render_agent(held)):
                assert identifier in rendered
                assert rendered.endswith("\n") and "\r" not in rendered


# ---------------------------------------------------------------------------
# The codes this milestone minted
# ---------------------------------------------------------------------------


class TestTheMintedCodes:
    """Named here so a reader of this file meets them beside their gate."""

    def test_the_three_journey_codes_are_distinct(self) -> None:
        assert len({DOC_TEACHING_ORDER, DOC_APPROVAL_UNDECLARED, DOC_JOURNEY_UNRESOLVED}) == 3
        assert DOC_JOURNEY_UNTESTED.startswith("DOC_")
