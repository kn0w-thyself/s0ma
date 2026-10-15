"""Gates for E8 — the coverage policy, its loader, and the corpus it holds.

Milestone E8 of the docs-function plan (internal) §10, closing Phase E.
D-10 in code: reference coverage is owed to every public surface (D6's
``DOC_SURFACE_UNCOVERED``), journey coverage is owed to the *primary*
capabilities, and the exception is structured, named, reasoned and
counted rather than a free-form ignore list.

Three things are held here, in the order a build meets them:

* **the loader** (T1) — the authored policy's shape refused with the JSON
  path of the value that is wrong, so a half-read policy can never reach
  a gate and make it ask a smaller question than the author wrote;
* **the corpus** (T1) — the ten capabilities really are covered by the
  seven authored journeys, the surface exceptions really are
  used, and the two ledgers really do account for all two hundred and
  forty-two composed surfaces between them, checked against the *live*
  composition rather than against a fixture written to agree;
* **the posture** (T4) — what blocks, in which mode, and where the mode
  itself lands.

``DOC_CAPABILITY_UNCOVERED`` and the ``DOC_GATE_VACUOUS`` this gate
raises are **fired** in the two negative batteries — C9's
``test_docs_model_negative.py`` for the record-level classes and D8's
``test_docs_surfaces_negative.py`` for the composed path — which is where
every ``DOC_*`` name in the ``docs_model`` tree is accounted for. E1 drew
that line for the journey gates and this milestone keeps it: the battery
proves the gate fires, and this module proves it is green on the real
corpus and cannot pass by having nothing to look at.
"""

from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.docs_model.application import (
    COVERAGE_POLICY,
    REFERENCE_ONLY_CEILING,
    build,
    coverage_policy,
)
from s0ma_dsl.docs_model.ids import normalize_id
from s0ma_dsl.docs_model.resolve import (
    COVERAGE_POLICY_SCHEMA,
    DOC_CAPABILITY_UNCOVERED,
    MIN_REASON,
    MINTED_CODES,
    RELEASE_MODE,
    DocsResolveError,
    check_journey_coverage,
    coverage_policy_from_mapping,
)
from s0ma_dsl.docs_model.validate import (
    CHANNEL_EFFECTS,
    DEFERRED_GATES,
    check_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)

#: What this repository's policy says, written down rather than counted.
#: The point of a pinned count is the same as ``UNBOUND_CEILING``'s: an
#: exception ledger that grows quietly is an ignore list with extra steps,
#: and a number somebody has to edit is the review moment.
EXPECTED_CAPABILITIES = 10
#: Back to twenty-six at beta-prep-1-retrofit F2a. `cli:s0ma/adopt/scan`
#: (B4) and `cli:s0ma/adopt/init` (C1) were parked here rather than
#: claimed by a primary capability because a capability must name at
#: least one journey and the retrofit journey was a later milestone;
#: F2a wrote that journey, and both entries came out into
#: `retrofit-existing-codebase` exactly as they said they would. Every
#: later `s0ma adopt` sub-command joined that capability as it landed and
#: the last of them (`adopt status`, E3) had done so, so the family cost
#: the ledger nothing.
#: **Twenty-five since F2's close-out**, which is one *below* where the
#: plan started. `cli:s0ma/adopt/file` moved out of this ledger and into
#: `retrofit-existing-codebase`: recording a file that will stay plain
#: Python for a while is the optional second rung of that same ladder, and
#: the reason excusing it here — that teaching adoption would put the
#: exception before the rule — was written when no journey taught adoption
#: at all. The loader allows it: a capability's journeys must *intersect*
#: its surfaces (``resolve._capability_findings``), not exhaust them, so a
#: surface the journey does not step through is still legally claimed.
#: `cli:s0ma/adopt` (the bare group) stays here: it is the family's
#: reference entry, not a rung.
EXPECTED_SURFACE_EXCEPTIONS = 25
EXPECTED_CHANNEL_EXCEPTIONS = 5
#: Fifty-five since beta-prep-1-retrofit E3. D4 put `cli:s0ma/adopt/draft`
#: into `retrofit-existing-codebase` rather than into the ledger above, E2
#: put `cli:s0ma/adopt/baseline` and `cli:s0ma/adopt/verify-parity` there
#: beside it, and E3 finished the family with `cli:s0ma/adopt/status` —
#: the journey exists now, so the capability can hold them and the
#: reference-only count does not move.
#: Fifty-six at F2's close-out: `cli:s0ma/adopt/file` crossed over from
#: the reference-only ledger into the same capability, so this number and
#: :data:`EXPECTED_SURFACE_EXCEPTIONS` moved by one in opposite
#: directions — which is what a surface changing ledgers should look like.
EXPECTED_CLAIMED_SURFACES = 56


# ---------------------------------------------------------------------------
# Fixture material for the loader
# ---------------------------------------------------------------------------

_REASON = (
    "A written reason long enough to have been thought about: this fixture "
    "surface is not a place anybody goes, and its reference entry is the "
    "whole of what a reader needs about it."
)


def _document() -> dict[str, Any]:
    """One policy that loads, ready to be broken in exactly one place."""
    return {
        "primary_capabilities": [
            {
                "id": "check-a-project",
                "journeys": ["journey:first-project"],
                "surfaces": ["cli:s0ma/check"],
                "title": "Find out whether what you wrote holds together.",
                "why_primary": (
                    "The loop everybody lives in, and the first place a newcomer "
                    "meets a diagnostic and has to decide what to do about it."
                ),
            }
        ],
        "reference_only_channels": [{"channel": "diagnostic", "reason": _REASON}],
        "reference_only_surfaces": [{"reason": _REASON, "surface": "cli:s0ma/topo"}],
        "schema": COVERAGE_POLICY_SCHEMA,
    }


def _refuse(mutate: Any, match: str) -> None:
    """Break one thing in a good policy and check the refusal names it."""
    document = _document()
    mutate(document)
    with pytest.raises(DocsResolveError, match=match):
        coverage_policy_from_mapping(document, source="fixture.json")


# ---------------------------------------------------------------------------
# The loader (T1)
# ---------------------------------------------------------------------------


class TestTheLoaderRefusesWhatItCannotTrust:
    """A policy that half-loaded would make the gate ask a smaller question."""

    def test_the_base_document_loads(self) -> None:
        policy = coverage_policy_from_mapping(_document(), source="fixture.json")
        assert policy.source == "fixture.json"
        assert [item.id for item in policy.capabilities] == ["check-a-project"]
        assert policy.claimed_surfaces() == {"cli:s0ma/check"}
        assert policy.excused_surfaces() == {"cli:s0ma/topo"}
        assert policy.excused_channels() == {"diagnostic"}

    def test_a_stray_top_level_key(self) -> None:
        _refuse(lambda doc: doc.update({"ignore": []}), "unexpected")

    def test_an_absent_top_level_key(self) -> None:
        _refuse(lambda doc: doc.pop("reference_only_channels"), "absent")

    def test_another_schema_version(self) -> None:
        _refuse(lambda doc: doc.update({"schema": "s0ma-docs-coverage-policy@2"}), "schema")

    def test_a_policy_with_no_primary_capability(self) -> None:
        """The one answer this gate must never be able to give itself."""
        _refuse(lambda doc: doc.update({"primary_capabilities": []}), "is empty")

    def test_a_capability_that_owes_no_journey(self) -> None:
        """"Primary" means a journey owes it a path; an empty list withdraws that."""
        _refuse(
            lambda doc: doc["primary_capabilities"][0].update({"journeys": []}),
            "is empty",
        )

    def test_a_capability_that_serves_nothing(self) -> None:
        _refuse(
            lambda doc: doc["primary_capabilities"][0].update({"surfaces": []}),
            "is empty",
        )

    def test_a_capability_id_that_is_not_a_slug(self) -> None:
        _refuse(
            lambda doc: doc["primary_capabilities"][0].update({"id": "capability:Check"}),
            "lowercase hyphenated slug",
        )

    def test_a_journey_list_naming_something_that_is_not_a_journey(self) -> None:
        _refuse(
            lambda doc: doc["primary_capabilities"][0].update(
                {"journeys": ["cli:s0ma/check"]}
            ),
            "is a cli id and this list names journey ids",
        )

    def test_a_surface_id_matching_no_form(self) -> None:
        _refuse(
            lambda doc: doc["primary_capabilities"][0].update({"surfaces": ["check"]}),
            "matches no id form",
        )

    def test_an_unsorted_list_of_surfaces(self) -> None:
        _refuse(
            lambda doc: doc["primary_capabilities"][0].update(
                {"surfaces": ["cli:s0ma/check", "cli:s0ma/build"]}
            ),
            "not sorted",
        )

    def test_a_title_written_over_two_lines(self) -> None:
        _refuse(
            lambda doc: doc["primary_capabilities"][0].update({"title": "One\nTwo"}),
            "line break",
        )

    def test_a_reason_too_short_to_have_been_written(self) -> None:
        _refuse(
            lambda doc: doc["reference_only_surfaces"][0].update({"reason": "not needed"}),
            f"at least {MIN_REASON}",
        )

    def test_a_capability_rationale_too_short_to_have_been_written(self) -> None:
        _refuse(
            lambda doc: doc["primary_capabilities"][0].update({"why_primary": "it is"}),
            f"at least {MIN_REASON}",
        )

    def test_a_channel_the_model_has_not_classified(self) -> None:
        """The rule that stops a channel ruling becoming a wildcard."""
        _refuse(
            lambda doc: doc["reference_only_channels"][0].update({"channel": "everything"}),
            "not a channel this model has classified",
        )

    def test_a_surface_claimed_and_excused_at_once(self) -> None:
        _refuse(
            lambda doc: doc["reference_only_surfaces"][0].update(
                {"surface": "cli:s0ma/check"}
            ),
            "claimed by a primary capability and excused",
        )

    def test_unsorted_capabilities(self) -> None:
        def mutate(document: dict[str, Any]) -> None:
            second = copy.deepcopy(document["primary_capabilities"][0])
            second["id"] = "author-a-module"
            document["primary_capabilities"].append(second)

        _refuse(mutate, "not sorted by id")

    def test_one_surface_excused_twice(self) -> None:
        def mutate(document: dict[str, Any]) -> None:
            document["reference_only_surfaces"].append(
                dict(document["reference_only_surfaces"][0])
            )

        _refuse(mutate, "not sorted by surface, or excuses one surface twice")

    def test_a_capability_that_is_not_an_object(self) -> None:
        _refuse(
            lambda doc: doc.update({"primary_capabilities": ["check-a-project"]}),
            "expected an object",
        )

    def test_a_ledger_that_is_not_a_list(self) -> None:
        _refuse(
            lambda doc: doc.update({"reference_only_surfaces": {}}),
            "expected a list",
        )


class TestReadingTheAuthoredFile:
    """The file half: where it lives, and what an unreadable one does."""

    @requires_checkout
    def test_the_repository_policy_loads(self) -> None:
        policy = coverage_policy(REPO_ROOT)
        assert policy.source == COVERAGE_POLICY
        assert COVERAGE_POLICY == "docs/s0ma_src/coverage-policy.json"

    def test_a_missing_policy_refuses_the_build(self, tmp_path: Path) -> None:
        """No fallback, on purpose: an absent policy would excuse everything."""
        with pytest.raises(DocsResolveError, match="is not there"):
            coverage_policy(tmp_path)

    def test_a_policy_that_is_not_json(self, tmp_path: Path) -> None:
        target = tmp_path.joinpath(*COVERAGE_POLICY.split("/"))
        target.parent.mkdir(parents=True)
        target.write_text("{not json", encoding="utf-8")
        with pytest.raises(DocsResolveError, match="not valid JSON"):
            coverage_policy(tmp_path)


# ---------------------------------------------------------------------------
# The authored policy itself (T1)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def policy() -> Any:
    return coverage_policy(REPO_ROOT)


@pytest.fixture(scope="module")
def composed() -> Any:
    return build(REPO_ROOT).bundle


@requires_checkout
class TestTheAuthoredPolicy:
    """What this repository has actually decided, pinned so a change is seen."""

    def test_the_counts_are_the_ones_that_were_reviewed(self, policy: Any) -> None:
        assert len(policy.capabilities) == EXPECTED_CAPABILITIES
        assert len(policy.surface_exceptions) == EXPECTED_SURFACE_EXCEPTIONS
        assert len(policy.channel_exceptions) == EXPECTED_CHANNEL_EXCEPTIONS
        assert len(policy.claimed_surfaces()) == EXPECTED_CLAIMED_SURFACES

    def test_the_exception_ledger_is_inside_its_budget(self, policy: Any) -> None:
        """``UNBOUND_CEILING``'s idiom, over the other ledger this repository keeps."""
        assert len(policy.surface_exceptions) <= REFERENCE_ONLY_CEILING, sorted(
            item.surface for item in policy.surface_exceptions
        )
        assert REFERENCE_ONLY_CEILING == 30
        assert len(policy.surface_exceptions) < REFERENCE_ONLY_CEILING, (
            "the ledger is at its ceiling; the next exception has to be argued "
            "rather than added"
        )

    def test_the_capabilities_a_user_comes_for_are_all_named(self, policy: Any) -> None:
        """The list itself, so a capability quietly leaving it is a diff somebody reads."""
        assert [item.id for item in policy.capabilities] == [
            "ask-the-self-model",
            "author-a-module",
            "build-a-project",
            "check-a-project",
            "diagnose-and-recover",
            "orient-in-a-project",
            "retrofit-existing-codebase",
            "send-feedback",
            "start-a-project",
            "view-the-project",
        ]

    def test_every_capability_says_why_it_is_primary(self, policy: Any) -> None:
        for capability in policy.capabilities:
            assert len(capability.why_primary.strip()) >= MIN_REASON, capability.id
            assert capability.title.strip(), capability.id

    def test_every_exception_carries_a_substantive_reason(self, policy: Any) -> None:
        for item in policy.surface_exceptions:
            assert len(item.reason.strip()) >= MIN_REASON, item.surface
        for ruling in policy.channel_exceptions:
            assert len(ruling.reason.strip()) >= MIN_REASON, ruling.channel

    def test_no_two_exceptions_share_one_reason(self, policy: Any) -> None:
        """A copied excuse is a reason nobody wrote for the thing it excuses."""
        reasons = [item.reason.strip() for item in policy.surface_exceptions]
        reasons.extend(ruling.reason.strip() for ruling in policy.channel_exceptions)
        assert len(set(reasons)) == len(reasons)

    def test_the_file_is_utf8_with_line_feeds_in_canonical_form(self) -> None:
        target = REPO_ROOT.joinpath(*COVERAGE_POLICY.split("/"))
        raw = target.read_bytes()
        assert b"\r\n" not in raw
        text = raw.decode("utf-8")
        assert text.endswith("\n")
        rewritten = (
            json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
        assert text == rewritten


@requires_checkout
class TestThePolicyAgainstTheLiveComposition:
    """The half a fixture cannot prove: the claims are true of this build."""

    def test_the_gate_is_green_on_the_corpus(self, policy: Any, composed: Any) -> None:
        assert check_journey_coverage(composed, policy) == []

    def test_every_capability_is_walked_by_every_journey_it_names(
        self, policy: Any, composed: Any
    ) -> None:
        """The claim is exact, not aspirational: each named journey walks it."""
        journeys = {normalize_id(item.id): item for item in composed.journeys}
        for capability in policy.capabilities:
            wanted = {normalize_id(item) for item in capability.surfaces}
            for journey_id in capability.journeys:
                record = journeys[normalize_id(journey_id)]
                walked = {normalize_id(step.surface) for step in record.steps}
                walked.update(
                    normalize_id(path.next_surface) for path in record.recovery_paths
                )
                assert walked & wanted, f"{capability.id} names {journey_id}"

    def test_every_authored_journey_carries_a_primary_capability(
        self, policy: Any, composed: Any
    ) -> None:
        cited = {
            normalize_id(journey)
            for capability in policy.capabilities
            for journey in capability.journeys
        }
        assert cited == {normalize_id(item.id) for item in composed.journeys}

    def test_the_two_ledgers_account_for_every_composed_surface(
        self, policy: Any, composed: Any
    ) -> None:
        """The completeness half, stated as arithmetic over the real bundle."""
        claimed = policy.claimed_surfaces()
        excused = policy.excused_surfaces()
        channels = policy.excused_channels()
        unclassified = sorted(
            record.id
            for record in composed.surfaces
            if normalize_id(record.id) not in claimed
            and normalize_id(record.id) not in excused
            and record.channel not in channels
        )
        assert unclassified == []
        by_channel = len(
            [record for record in composed.surfaces if record.channel in channels]
        )
        assert len(claimed) + len(excused) + by_channel == len(composed.surfaces)

    def test_no_channel_ruling_swallows_a_primary_capability(
        self, policy: Any, composed: Any
    ) -> None:
        """The rule that keeps the channel form from becoming an ignore list.

        Proved against the composed surfaces rather than against the
        spelling of an id: what a surface's channel *is* is a fact of its
        record, and a ruling that covered a channel one primary capability
        is served on would make "the command line is reference-only"
        writable.
        """
        claimed = policy.claimed_surfaces()
        primary_channels = {
            record.channel
            for record in composed.surfaces
            if normalize_id(record.id) in claimed
        }
        assert policy.excused_channels() & primary_channels == set()
        assert policy.excused_channels() == {
            "config",
            "diagnostic",
            "mcp_resource",
            "python",
            "rest",
        }

    def test_every_exception_names_the_surface_it_excuses(
        self, policy: Any, composed: Any
    ) -> None:
        """A reason that does not name its subject is boilerplate wearing a paragraph.

        Checked against the surface's ``public_name`` — the product's own
        spelling, read off the composed record rather than restated here —
        so an exception copied onto the wrong surface fails, and so does
        one whose command has been renamed underneath it.
        """
        names = {
            normalize_id(record.id): record.public_name for record in composed.surfaces
        }
        for item in policy.surface_exceptions:
            spelling = names[normalize_id(item.surface)]
            assert spelling.lower() in item.reason.lower(), item.surface

    def test_every_exception_still_excuses_something(
        self, policy: Any, composed: Any
    ) -> None:
        """The self-expiring half, asked of the corpus rather than of a fixture."""
        served = {normalize_id(record.id) for record in composed.surfaces}
        for item in policy.surface_exceptions:
            assert normalize_id(item.surface) in served, item.surface
        channels = {record.channel for record in composed.surfaces}
        for ruling in policy.channel_exceptions:
            assert ruling.channel in channels, ruling.channel

    def test_the_gate_cannot_pass_by_looking_at_nothing(
        self, policy: Any, composed: Any
    ) -> None:
        """The vacuity control: the corpus it walks is the real, large one."""
        assert len(composed.surfaces) >= 200
        assert len(composed.journeys) == 7
        assert len(policy.claimed_surfaces()) >= 40


# ---------------------------------------------------------------------------
# The minted code, and the release posture (T2, T4)
# ---------------------------------------------------------------------------


class TestTheMintedCode:
    """``resolve`` mints one code, and says where it came from."""

    def test_every_minted_code_says_where_it_came_from(self) -> None:
        assert set(MINTED_CODES) == {DOC_CAPABILITY_UNCOVERED}
        for code, reason in MINTED_CODES.items():
            assert code.startswith("DOC_")
            assert "E8" in reason

    def test_the_code_is_its_own_spelling(self) -> None:
        """C9's rule, kept here too: a constant that lies makes the audit lie."""
        assert DOC_CAPABILITY_UNCOVERED == "DOC_CAPABILITY_UNCOVERED"

    def test_the_subject_of_the_name_is_the_thing_that_lacks_coverage(self) -> None:
        """The naming rule ``*_UNCOVERED`` follows across the whole model.

        A concept with no page, a surface with no reference, a capability
        with no journey: the record that is missing something comes first,
        and the thing that would have supplied it does not appear in the
        name at all.
        """
        from s0ma_dsl.docs_model.resolve import (
            DOC_CONCEPT_UNCOVERED,
            DOC_SURFACE_UNCOVERED,
        )

        subjects = [
            code.removeprefix("DOC_").removesuffix("_UNCOVERED")
            for code in (
                DOC_CAPABILITY_UNCOVERED,
                DOC_CONCEPT_UNCOVERED,
                DOC_SURFACE_UNCOVERED,
            )
        ]
        assert subjects == ["CAPABILITY", "CONCEPT", "SURFACE"]
        assert "JOURNEY" not in DOC_CAPABILITY_UNCOVERED


class TestTheReleasePosture:
    """T4: which findings block, in which mode, and where the mode lands.

    Recorded rather than implemented, and the difference matters. There is
    no release mode to hang a split on today, so this milestone does not
    invent one: it writes down the decision H1 will inherit and leaves a
    marker that turns red when H1 arrives.
    """

    def test_the_posture_is_written_down(self) -> None:
        assert "release-blocking" in RELEASE_MODE
        assert "H1" in RELEASE_MODE

    def test_the_mode_this_gate_would_split_on_does_not_exist_yet(self) -> None:
        """The self-expiring marker.

        When ``build`` grows a mode, this test goes red and whoever added
        it reads :data:`~s0ma_dsl.docs_model.resolve.RELEASE_MODE` — which
        is the whole point of leaving a marker rather than a comment.

        ``head_tag`` (H2b) is in the set and is deliberately **not** the
        mode this marker is watching for. A mode would decide which
        findings block; the tag decides which channel the build composes,
        and no finding is graded differently for having been told one. The
        marker keeps its equality against the whole signature rather than
        only testing for ``"mode"``, because a mode that arrived under
        another name would slip past the narrower check — so a parameter
        added here is meant to be read and re-agreed, which is what this
        paragraph is.
        """
        parameters = set(inspect.signature(build).parameters)
        assert "mode" not in parameters
        assert parameters == {
            "root",
            "version",
            "head_tag",
            "providers",
            "floors",
            "allowances",
            "evidence",
            "coverage",
        }

    def test_the_milestone_that_brings_the_mode_is_the_one_named(self) -> None:
        """H1, and its sibling gate landed there — which is the evidence now.

        Until H1 this read the deferral map, because ``DOC_VERSION_MISMATCH``
        was the entry that named the milestone. H1 arrived, the entry left
        the map, and the same claim is now made by the thing that replaced
        it: the release-currency gate exists and ``build`` still has no
        mode, so the marker above is still the one that expires.
        """
        assert "DOC_VERSION_MISMATCH" not in DEFERRED_GATES
        assert check_manifest.__module__ == "s0ma_dsl.docs_model.validate"

    def test_the_policy_is_the_callers_and_has_no_default_in_the_machinery(self) -> None:
        """``check_journey_coverage`` cannot satisfy itself with an empty policy."""
        assert "policy" in inspect.signature(check_journey_coverage).parameters
        assert (
            inspect.signature(check_journey_coverage).parameters["policy"].default
            is inspect.Parameter.empty
        )

    def test_the_channel_vocabulary_a_ruling_may_name_is_the_models_own(self) -> None:
        """Nine words, closed, and shared with the side-effect gate."""
        assert len(CHANNEL_EFFECTS) == 9
        assert set(coverage_policy(REPO_ROOT).excused_channels()) <= set(CHANNEL_EFFECTS)
