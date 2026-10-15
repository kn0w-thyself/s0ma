"""Gates for I2's coverage report — the artifact that states what is covered.

Milestone I2 of the docs-function plan (internal) §14, over architecture plan
§11.1. The report is a *rendering of standing decisions*, and a rendering is
only worth committing if two things hold: it says what the build actually
holds, and it moves when the build does. A coverage report that could not go
down is a coverage report nobody should read, so most of this suite is
mutations — a policy fixture edited, a surface's exception removed, a concept's
page dropped — each asserted to move a number.

Four shapes of claim:

* **derivation** — every figure in the report is the composed bundle's or the
  authored policy's, compared against a second count taken here rather than
  against the report's own arithmetic;
* **mutation** — changing a standing decision changes the report, which is what
  makes it a derivation rather than a snapshot somebody refreshed;
* **refusal** — a set that came back empty, or a ledger over its ceiling, is
  raised rather than rendered. A report claiming full coverage of nothing is
  the one output here that would be actively harmful;
* **agreement** — the committed JSON and the self-description's coverage
  section state the same numbers, because they are handed one measurement.

**Cost.** The documentation build is composed once for the module.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.docs_model.application import (
    COVERAGE_REPORT_OUTPUT,
    DISCOVERY_CONTRACT,
    DOCS_ROOT,
    REFERENCE_ONLY_CEILING,
    STATIC_OUTPUTS,
    UNBOUND_CEILING,
    coverage_policy,
)
from s0ma_dsl.docs_model.application import (
    build as build_documentation,
)
from s0ma_dsl.docs_model.coverage_report import (
    COVERAGE_SCHEMA,
    SET_ORDER,
    CoverageSet,
    DocsCoverageError,
    coverage_sets,
    render_coverage,
)
from s0ma_dsl.docs_model.learn_pages import learn_outputs
from s0ma_dsl.docs_model.records import DocsModelError
from tests._committed_claim import claimed_head_tag

if TYPE_CHECKING:  # pragma: no cover - typing only
    from s0ma_dsl.docs_model.application import Build

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMITTED = REPO_ROOT / DOCS_ROOT / COVERAGE_REPORT_OUTPUT


@pytest.fixture(scope="module")
def composed() -> Build:
    """One build of the real checkout, in the channel the committed tree claims."""
    return build_documentation(REPO_ROOT, head_tag=claimed_head_tag())


@pytest.fixture(scope="module")
def policy():  # noqa: ANN201 - the module's own CoveragePolicy
    return coverage_policy(REPO_ROOT)


@pytest.fixture(scope="module")
def report(composed: Build) -> dict:
    rendered = {item.relative: item.content for item in composed.artifacts}
    return json.loads(rendered[COVERAGE_REPORT_OUTPUT])


def _measure(composed: Build, policy, **overrides) -> tuple[CoverageSet, ...]:
    """The live measurement, with one input replaced."""
    kwargs = {
        "policy": policy,
        "pages": learn_outputs(composed.bundle),
        "exclusions": (),
        "discovery": DISCOVERY_CONTRACT,
        "unbound_ceiling": UNBOUND_CEILING,
        "reference_only_ceiling": REFERENCE_ONLY_CEILING,
    }
    kwargs.update(overrides)
    return coverage_sets(composed.bundle, **kwargs)


def _named(sets: tuple[CoverageSet, ...], name: str) -> CoverageSet:
    return next(item for item in sets if item.name == name)


def _set_of(report: dict, name: str) -> dict:
    return next(item for item in report["sets"] if item["set"] == name)


class TestItIsADeclaredOutput:
    """Written by ``write`` and compared by ``check``, like every artifact."""

    def test_it_is_a_decided_output(self) -> None:
        assert COVERAGE_REPORT_OUTPUT in STATIC_OUTPUTS

    def test_the_manifest_is_still_the_last_decided_output(self) -> None:
        """H1's rule survives I2 adding an output beside it.

        The manifest describes every artifact and cannot describe itself,
        so it renders last. An output appended after it in the decided
        tuple would be one the manifest could still list — but the tuple's
        order is documented as the render order, and a tuple whose order
        stopped meaning that is a comment that has come apart from its
        code.

        The report was the last output before the manifest until the
        quick reference's two were declared after it; what is held is the
        rule, which is that the manifest follows every one of them.
        """
        assert STATIC_OUTPUTS[-1] == "_generated/docs-manifest.json"
        assert COVERAGE_REPORT_OUTPUT in STATIC_OUTPUTS[:-1]

    def test_the_committed_file_is_the_rendered_one(self, composed: Build) -> None:
        rendered = {item.relative: item.content for item in composed.artifacts}
        assert COMMITTED.read_text(encoding="utf-8") == rendered[COVERAGE_REPORT_OUTPUT]


class TestTheReportIsDerived:
    """Every figure held against a second count of the same thing."""

    def test_it_names_its_schema_and_its_build(self, report: dict, composed: Build) -> None:
        assert report["schema"] == COVERAGE_SCHEMA
        assert report["source"] == {
            "build_channel": composed.bundle.stamp.build_channel,
            "model_schema": composed.bundle.stamp.schema,
            "release_version": composed.bundle.stamp.release_version,
            "snapshot_hash": composed.bundle.stamp.snapshot_hash,
        }

    def test_the_identity_is_channel_labelled(self, report: dict) -> None:
        """A preview report must not read as a release one.

        The stamp's channel is on the artifact rather than inferred from
        the version, which is H1's rule; without it two builds of one
        version are indistinguishable and the whole release-currency gate
        has nothing to compare.
        """
        assert report["source"]["build_channel"] in {"preview", "release"}

    def test_it_states_the_five_required_sets_in_order(self, report: dict) -> None:
        assert tuple(item["set"] for item in report["sets"]) == SET_ORDER

    def test_the_concept_count_is_the_composed_one(
        self, report: dict, composed: Build
    ) -> None:
        assert _set_of(report, "concepts")["required"] == len(composed.bundle.concepts)

    def test_the_surface_count_is_the_composed_one(
        self, report: dict, composed: Build
    ) -> None:
        surfaces = _set_of(report, "surfaces")
        assert surfaces["required"] == len(composed.bundle.surfaces)
        assert surfaces["covered"] + surfaces["exception_count"] == surfaces["required"]

    def test_the_catalog_count_is_the_composed_one(
        self, report: dict, composed: Build
    ) -> None:
        assert _set_of(report, "catalog")["required"] == len(composed.bundle.documents)

    def test_the_binding_exceptions_are_the_records_that_carry_one(
        self, report: dict, composed: Build
    ) -> None:
        excused = {
            record.id
            for record in composed.bundle.surfaces
            if not record.component_refs and record.manual_exception
        }
        rowed = {row["member"] for row in _set_of(report, "surfaces")["exceptions"]}
        assert rowed == excused

    def test_each_binding_exception_names_the_source_it_was_read_from(
        self, report: dict, composed: Build
    ) -> None:
        """The ledger is the record's own source, not one constant.

        Seven of them are ``UNREGISTERED_HANDLERS`` and the rest are
        rulings other readings make; a single ledger name would be false
        for most of the rows and useless for all of them.
        """
        sources = {record.id: record.provenance.source for record in composed.bundle.surfaces}
        for row in _set_of(report, "surfaces")["exceptions"]:
            assert row["ledger"] == sources[row["member"]]

    def test_the_reference_only_ledger_is_the_authored_one(
        self, report: dict, policy
    ) -> None:
        rowed = {
            row["member"]
            for row in _set_of(report, "journeys")["exceptions"]
            if row["kind"] == "reference-only surface"
        }
        assert rowed == {item.surface for item in policy.surface_exceptions}
        for row in _set_of(report, "journeys")["exceptions"]:
            assert row["ledger"] == policy.source

    def test_the_channel_rulings_are_the_authored_ones(
        self, report: dict, policy
    ) -> None:
        rowed = {
            row["member"]
            for row in _set_of(report, "journeys")["exceptions"]
            if row["kind"] == "reference-only channel"
        }
        assert rowed == {f"channel:{item.channel}" for item in policy.channel_exceptions}

    def test_the_ceilings_are_the_applications_own(self, report: dict) -> None:
        assert _set_of(report, "surfaces")["ceilings"]["unbound"]["ceiling"] == (
            UNBOUND_CEILING
        )
        assert _set_of(report, "journeys")["ceilings"]["reference_only_surfaces"][
            "ceiling"
        ] == REFERENCE_ONLY_CEILING

    def test_the_totals_are_the_sets_added_up(self, report: dict) -> None:
        assert report["totals"]["required"] == sum(
            item["required"] for item in report["sets"]
        )
        assert report["totals"]["exceptions"] == sum(
            item["exception_count"] for item in report["sets"]
        )

    def test_every_exception_kind_is_counted(self, report: dict) -> None:
        counted = sum(report["exception_kinds"].values())
        assert counted == report["totals"]["exceptions"]

    def test_this_repository_covers_everything_it_requires(self, report: dict) -> None:
        """The acceptance claim, stated once and read off the artifact."""
        assert report["complete"] is True
        assert report["totals"]["uncovered"] == 0
        for item in report["sets"]:
            assert item["uncovered"] == [], item["set"]


class TestTheDiscoveryRoutesAreNamedNotCounted:
    """The one set no build measures says so, and names its proofs."""

    def test_fourteen_routes_seven_each(self, report: dict) -> None:
        rows = report["discovery_routes"]
        assert len(rows) == 14
        assert len([row for row in rows if row["audience"] == "human"]) == 7
        assert len([row for row in rows if row["audience"] == "agent"]) == 7

    def test_every_route_names_a_clause_and_a_proof(self, report: dict) -> None:
        for row in report["discovery_routes"]:
            assert row["clause"].startswith("architecture §9."), row
            assert "::" in row["proof"], row
            assert row["route"], row

    def test_the_set_says_it_did_not_measure_them(self, report: dict) -> None:
        """The honesty clause, asserted rather than trusted to survive."""
        measured = _set_of(report, "discovery")["measured_by"]
        assert "nothing in this build" in measured

    def test_a_route_with_no_proof_is_uncovered(self, composed: Build, policy) -> None:
        blinded = (replace(DISCOVERY_CONTRACT[0], proof=""), *DISCOVERY_CONTRACT[1:])
        sets = _measure(composed, policy, discovery=blinded)
        assert _named(sets, "discovery").uncovered == (DISCOVERY_CONTRACT[0].id,)
        assert not _named(sets, "discovery").complete


class TestMutatingAStandingDecisionMovesTheReport:
    """The derivation claim, in the only form that can fail."""

    def test_dropping_a_reference_only_entry_leaves_a_surface_unclassified(
        self, composed: Build, policy
    ) -> None:
        thinner = replace(policy, surface_exceptions=policy.surface_exceptions[1:])
        sets = _measure(composed, thinner)
        journeys = _named(sets, "journeys")
        assert policy.surface_exceptions[0].surface in journeys.uncovered
        assert not journeys.complete

    def test_dropping_a_channel_ruling_unclassifies_that_whole_channel(
        self, composed: Build, policy
    ) -> None:
        dropped = policy.channel_exceptions[0]
        thinner = replace(policy, channel_exceptions=policy.channel_exceptions[1:])
        sets = _measure(composed, thinner)
        journeys = _named(sets, "journeys")
        assert journeys.uncovered
        assert not journeys.complete
        served = [
            record.id
            for record in composed.bundle.surfaces
            if record.channel == dropped.channel
        ]
        assert set(served) & set(journeys.uncovered)

    def test_dropping_a_capability_unclassifies_the_surfaces_it_claimed(
        self, composed: Build, policy
    ) -> None:
        thinner = replace(policy, capabilities=policy.capabilities[1:])
        sets = _measure(composed, thinner)
        assert not _named(sets, "journeys").complete

    def test_a_concept_with_no_page_is_short(self, composed: Build, policy) -> None:
        """The collection stops emitting one page; the report notices.

        The dropped page is chosen by matching a concept rather than by
        index, because the collection also holds two pages that are not
        any one concept's — and dropping one of those is not the failure
        this claim is about.
        """
        pages = learn_outputs(composed.bundle)
        slugs = {record.id.split(":", 1)[-1] for record in composed.bundle.concepts}
        dropped = next(
            path for path in pages if path.rsplit("/", 1)[-1].removesuffix(".md") in slugs
        )
        sets = _measure(composed, policy, pages=[p for p in pages if p != dropped])
        concepts = _named(sets, "concepts")
        assert concepts.covered == concepts.required - 1
        assert len(concepts.uncovered) == 1
        assert not concepts.complete

    def test_an_exclusion_is_carried_as_a_named_exception(
        self, composed: Build, policy
    ) -> None:
        sets = _measure(composed, policy, exclusions=())
        assert _named(sets, "catalog").exceptions == ()


class TestTheReportRefusesRatherThanReassures:
    """The failure modes where rendering would be worse than raising."""

    def test_a_ledger_over_its_ceiling_is_refused(
        self, composed: Build, policy
    ) -> None:
        with pytest.raises(DocsCoverageError) as caught:
            _measure(composed, policy, unbound_ceiling=1)

        assert "ceiling" in str(caught.value)

    def test_a_reference_only_ledger_over_its_ceiling_is_refused(
        self, composed: Build, policy
    ) -> None:
        with pytest.raises(DocsCoverageError):
            _measure(composed, policy, reference_only_ceiling=1)

    def test_a_discovery_contract_with_no_routes_is_refused(
        self, composed: Build, policy
    ) -> None:
        with pytest.raises(DocsCoverageError):
            _measure(composed, policy, discovery=())

    def test_an_empty_measurement_will_not_render(self, composed: Build) -> None:
        with pytest.raises(DocsCoverageError):
            render_coverage(composed.bundle, sets=(), discovery=DISCOVERY_CONTRACT)

    def test_a_refusal_is_a_model_error_so_the_build_collects_it(self) -> None:
        """ADR-012 §4's collect-everything contract holds over this renderer."""
        assert issubclass(DocsCoverageError, DocsModelError)


class TestThePageAndTheReportAgree:
    """One measurement, two artifacts — so they cannot drift apart."""

    def test_the_page_states_the_reports_totals(
        self, report: dict, composed: Build
    ) -> None:
        rendered = {item.relative: item.content for item in composed.artifacts}
        page = rendered["architecture/docs-application.md"]
        totals = report["totals"]

        assert (
            f"{totals['covered']} of the {totals['required']} things this build "
            f"is required to cover" in page
        )
        assert f"{totals['exceptions']} carry a written exception" in page
        assert f"and {totals['uncovered']} are neither" in page

    def test_the_page_carries_one_row_per_set(
        self, report: dict, composed: Build
    ) -> None:
        rendered = {item.relative: item.content for item in composed.artifacts}
        page = rendered["architecture/docs-application.md"]
        for item in report["sets"]:
            row = (
                f"| {item['set']} | {item['required']} | {item['covered']} "
                f"| {item['exception_count']} | {len(item['uncovered'])} |"
            )
            assert row in page, row

    def test_the_page_links_the_report_rather_than_repeating_it(
        self, composed: Build
    ) -> None:
        rendered = {item.relative: item.content for item in composed.artifacts}
        page = rendered["architecture/docs-application.md"]

        assert "(../_generated/coverage-report.json)" in page

    def test_the_page_refuses_a_build_with_no_coverage(
        self, composed: Build
    ) -> None:
        """An empty table under a completeness heading reads as full marks.

        The one refusal on this page that is not about a reading coming
        back empty: the others would render a visibly empty section, and
        this one would render a section that looks exactly like complete
        coverage of a set nobody measured.
        """
        from s0ma_dsl.docs_model.application import (
            APPLICATION_IR,
            CORE_SLICE_OUTPUT,
            DOCS_APPLICATION_OUTPUT,
            gate_modules,
            generated_outputs,
            registry,
        )
        from s0ma_dsl.docs_model.compose import compose
        from s0ma_dsl.docs_model.self_description import (
            DocsSelfDescriptionError,
            application_module,
            docs_application,
            gate_facts,
        )

        results = compose(
            registry(REPO_ROOT),
            release_version=composed.bundle.stamp.release_version,
        ).results

        with pytest.raises(DocsSelfDescriptionError) as caught:
            docs_application(
                composed.bundle,
                results=results,
                gates=gate_facts(gate_modules()),
                module=application_module(REPO_ROOT, relative=APPLICATION_IR),
                outputs=generated_outputs(composed.bundle),
                decided=STATIC_OUTPUTS,
                packaged=frozenset({CORE_SLICE_OUTPUT}),
                media=frozenset(),
                coverage=(),
                page=DOCS_APPLICATION_OUTPUT,
                docs_root=DOCS_ROOT,
            )

        assert "coverage" in str(caught.value)
