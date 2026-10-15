"""H3 — the five media packages, and the five claims they are worth having for.

Milestone H3 of the docs-function plan (internal) §13, implementing the
architecture plan's §13.3. A media package is the release-bound input a
public walkthrough is produced from, and the whole reason it is generated
rather than written is that a video is otherwise a *second factual source*
about the product — one that goes stale silently, off camera, months after
anybody could check it. The claims:

* **the schema is architecture §13.3's, exactly.** Every field §13.3 names
  is present under a declared key, and nothing else is;
* **every factual field is derived.** Each one is asserted equal to the
  record it comes from — the journey, the surface it points at, the catalog
  document that publishes it, the build stamp — so a package that agreed
  with §13.3's shape while inventing its content still fails here;
* **the creative fields are absent, and the absence is pinned.** Tone,
  visual direction, music and pacing are H4's, and a schema that carried
  an empty key for them would invite this build to fill it in;
* **a journey edit invalidates its package.** The drift proof, run against
  a scratch copy of the checkout with one journey sentence changed;
* **it is byte-deterministic, and it carries no resolved path.** The
  transcript placeholders travel through as placeholders, because a
  production script pointing at ``/private/var/folders/...`` would be both
  wrong for the person shooting it and non-reproducible for the gate.

**The sixth journey.** ``journey:studi0-viewing`` is the B7 prototype and
no catalog document covers it, so :func:`approved_journeys` does not keep
it and no package is rendered. ``TestWhichJourneysAreApproved`` pins that
as a *rule* rather than an exclusion list, so publishing a guide for it
would emit its package with nothing here to edit.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.docs_model.application import (
    DOCS_ROOT,
    STATIC_OUTPUTS,
    Build,
    build,
    check,
    generated_outputs,
)
from s0ma_dsl.docs_model.evidence import PLACEHOLDERS
from s0ma_dsl.docs_model.manifest import artifact_format
from s0ma_dsl.docs_model.providers_catalog import CatalogProvider
from s0ma_dsl.docs_model.records import SCHEMA
from s0ma_dsl.docs_model.render_media import (
    CREATIVE_KEYS,
    JOURNEY_PREFIX,
    MEDIA_DIR,
    MEDIA_SCHEMA,
    QUIET_EFFECTS,
    DocsMediaError,
    approved_journeys,
    media_outputs,
    media_package,
    media_packages,
    package_path,
    stale_packages,
)
from s0ma_dsl.docs_model.validate import APPROVAL_EFFECT
from tests._committed_claim import claimed_head_tag, preview_tree_only

if TYPE_CHECKING:
    from s0ma_dsl.docs_model.records import DocsBundle, JourneyRecord

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The published journeys, by the milestone that authored each: the five
#: canonical E-phase paths, and the retrofit path beta-prep-1-retrofit
#: F2a added beside them. Written here as the *expectation* the
#: derivation is checked against — the renderer keeps journeys by the
#: catalog rule and never by this list, so a disagreement between the two
#: is a real finding rather than a stale constant.
CANONICAL = {
    "journey:first-project": "E3",
    "journey:first-module": "E4",
    "journey:mcp-authoring-loop": "E5",
    "journey:drift-recovery": "E6",
    "journey:studi0-feedback": "E7",
    "journey:retrofit-existing-codebase": "beta-prep-1-retrofit F2a",
}

#: The B7 prototype. Seven journeys exist and six are published; this is
#: the one that is not, and the plan's own §10 gate note calls it exactly
#: that.
PROTOTYPE = "journey:studi0-viewing"

#: An absolute POSIX path anywhere in a package. A media package is a
#: script performed on somebody else's machine, so a path from the machine
#: that composed it would be wrong even where it was deterministic.
_POSIX_PATH = re.compile(r"""(?:^|[\s"(\[])/(?:Users|home|private|tmp|var|opt)/""")


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


@pytest.fixture(scope="module")
def composed() -> Build:
    """One build of the real checkout, shared by every proof that reads it.

    Composed in the channel the committed tree claims, so it is the build
    the committed files came from: untagged on a preview tree, at the
    release's own tag on the one commit a tag names.
    """
    return build(REPO_ROOT, head_tag=claimed_head_tag())


@pytest.fixture(scope="module")
def rows() -> tuple:
    """The catalog's presentation half, read the way the application reads it."""
    return CatalogProvider(root=REPO_ROOT).rows()


def _scratch_checkout(destination: Path) -> Path:
    """A throwaway git copy of this checkout, the way the gate suite makes one.

    Tracked files plus untracked-and-not-ignored ones — what a commit of
    the working tree would contain — then ``git init`` and ``git add``,
    because the completeness gate's corpus is ``git ls-files`` and a copy
    without an index reports an empty one.
    """
    import shutil
    import subprocess

    listed: list[str] = []
    for arguments in (["-z"], ["--others", "--exclude-standard", "-z"]):
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(REPO_ROOT), "ls-files", *arguments],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        listed.extend(item for item in result.stdout.split("\0") if item)
    for relative in listed:
        source = REPO_ROOT / relative
        if not source.is_file():  # a deleted-but-still-indexed path
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for arguments in (["init", "-q"], ["add", "-A"]):
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(destination), *arguments],  # noqa: S607
            capture_output=True,
            check=True,
        )
    return destination


@pytest.fixture(scope="module")
def packages(composed: Build, rows: tuple) -> dict[str, dict]:
    """Every package this build rendered, parsed, keyed by journey id."""
    return {
        json.loads(text)["identity"]["journey"]: json.loads(text)
        for text in media_packages(composed.bundle, rows=rows).values()
    }


def _journey(bundle: DocsBundle, journey_id: str) -> JourneyRecord:
    for record in bundle.journeys:
        if record.id == journey_id:
            return record
    raise AssertionError(f"{journey_id} is not composed")


# ---------------------------------------------------------------------------
# Which journeys are approved (§13.3's own word)
# ---------------------------------------------------------------------------


class TestWhichJourneysAreApproved:
    """§13.3 emits a package per *approved* journey. Publication is the test."""

    def test_the_approved_set_is_the_published_journeys(
        self, composed: Build
    ) -> None:
        assert {record.id for record in approved_journeys(composed.bundle)} == set(
            CANONICAL
        )

    def test_the_repository_holds_one_journey_more_than_it_publishes(
        self, composed: Build
    ) -> None:
        """The count the plan's §10 gate note states, plus what came after it."""
        assert len(composed.bundle.journeys) == len(CANONICAL) + 1
        assert {record.id for record in composed.bundle.journeys} == set(CANONICAL) | {
            PROTOTYPE
        }

    def test_the_prototype_is_excluded_because_no_document_publishes_it(
        self, composed: Build
    ) -> None:
        """The evidence for the exclusion, stated as the rule that produces it.

        Not an ignore entry and not a name in a list here: every canonical
        journey is covered by a catalog document and this one is covered by
        none, which is what "approved" means structurally in a repository
        whose catalog is the publication decision.
        """
        published = {
            covered
            for document in composed.bundle.documents
            for covered in document.covers
            if covered.startswith(JOURNEY_PREFIX)
        }
        assert published == set(CANONICAL)
        assert PROTOTYPE not in published
        assert PROTOTYPE not in {
            record.id for record in approved_journeys(composed.bundle)
        }

    def test_publishing_a_journey_is_what_would_add_its_package(
        self, composed: Build, rows: tuple
    ) -> None:
        """A rule, not a list: cover the prototype and its package appears.

        Composed in memory rather than committed, because committing a
        document row for a prototype is precisely the decision this
        milestone is not authorised to take.
        """
        import dataclasses

        document = next(
            item for item in composed.bundle.documents if item.id == "doc:guide/first-project"
        )
        widened = dataclasses.replace(
            composed.bundle,
            documents=(
                *(item for item in composed.bundle.documents if item.id != document.id),
                dataclasses.replace(document, covers=(*document.covers, PROTOTYPE)),
            ),
        )
        assert PROTOTYPE in {record.id for record in approved_journeys(widened)}
        assert f"{MEDIA_DIR}/studi0-viewing.json" in media_outputs(widened)
        # And it renders, rather than merely being declared.
        assert f"{MEDIA_DIR}/studi0-viewing.json" in media_packages(widened, rows=rows)


# ---------------------------------------------------------------------------
# The schema (architecture §13.3)
# ---------------------------------------------------------------------------


class TestTheSchema:
    """Every field §13.3 names, under a declared key, and nothing else."""

    def test_the_envelope_is_schema_identity_package(
        self, packages: dict[str, dict]
    ) -> None:
        for package in packages.values():
            assert set(package) == {"schema", "identity", "package"}

    def test_the_schema_is_the_models_own(self, packages: dict[str, dict]) -> None:
        """A package is a rendering of the model, so it versions with it."""
        assert MEDIA_SCHEMA == SCHEMA
        for package in packages.values():
            assert package["schema"] == SCHEMA

    def test_every_field_the_architecture_names_is_present(
        self, packages: dict[str, dict]
    ) -> None:
        """§13.3's list, one key per item, with nothing added and nothing left.

        ``teaches`` and ``published_by`` are the two keys §13.3 does not
        write in those words. The first is the other half of
        "prerequisites" — §13.3 asks for the learning *outcome* and the
        journey states it twice, as an intent sentence and as the ordered
        concepts a walker leaves with, and dropping the second would throw
        away the only structured form of the outcome the model has. The
        second is the provenance of the title and audience: those are the
        publishing document's facts, and an artifact that stated them
        without naming where they came from would break SDA-INV-10.
        """
        for package in packages.values():
            assert set(package["package"]) == {
                "audience",
                "cautions",
                "chapters",
                "consent",
                "evidence",
                "outcome",
                "prerequisites",
                "recovery",
                "steps",
                "teaches",
                "title",
            }
            assert set(package["identity"]) == {
                "channel",
                "journey",
                "published_by",
                "release",
                "snapshot",
            }

    def test_a_journey_id_that_names_no_package_path_is_refused(self) -> None:
        with pytest.raises(DocsMediaError, match="not a journey id"):
            package_path("concept:module")
        with pytest.raises(DocsMediaError, match="single-segment"):
            package_path("journey:")

    def test_a_package_is_read_back_by_the_house_reader(
        self, composed: Build, rows: tuple
    ) -> None:
        """Canonical JSON, sorted keys, one trailing line feed."""
        for text in media_packages(composed.bundle, rows=rows).values():
            assert text.endswith("}\n")
            assert not text.endswith("}\n\n")
            reread = json.dumps(
                json.loads(text), sort_keys=True, indent=2, ensure_ascii=False
            )
            assert reread + "\n" == text


# ---------------------------------------------------------------------------
# Derivation, not authoring
# ---------------------------------------------------------------------------


class TestEveryFactIsDerived:
    """Each field asserted equal to the record it is read from."""

    def test_the_title_and_audience_are_the_publishing_documents(
        self, composed: Build, packages: dict[str, dict], rows: tuple
    ) -> None:
        by_id = {item.id: item for item in composed.bundle.documents}
        row_by_id = {item.id: item for item in rows}
        for journey_id, package in packages.items():
            document_id = package["identity"]["published_by"]
            assert package["package"]["title"] == by_id[document_id].title
            assert package["package"]["audience"] == list(row_by_id[document_id].audiences)
            assert journey_id in by_id[document_id].covers

    def test_the_outcome_is_the_journeys_own_intent(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        for journey_id, package in packages.items():
            assert package["package"]["outcome"] == _journey(
                composed.bundle, journey_id
            ).intent

    def test_the_prerequisites_are_the_journeys_required_concepts(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        terms = {record.id: record.term for record in composed.bundle.concepts}
        for journey_id, package in packages.items():
            record = _journey(composed.bundle, journey_id)
            assert package["package"]["prerequisites"] == [
                {"concept": concept, "term": terms[concept]}
                for concept in sorted(record.concepts_required)
            ]

    def test_the_teaching_list_keeps_the_journeys_order(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        """Ordered, not sorted: the order is the whole content of the rule."""
        for journey_id, package in packages.items():
            record = _journey(composed.bundle, journey_id)
            assert [
                item["concept"] for item in package["package"]["teaches"]
            ] == list(record.concepts_taught)

    def test_the_steps_are_the_journeys_steps_in_order(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        for journey_id, package in packages.items():
            record = _journey(composed.bundle, journey_id)
            steps = package["package"]["steps"]
            assert len(steps) == len(record.steps)
            for index, (written, authored) in enumerate(
                zip(steps, record.steps, strict=True), start=1
            ):
                assert written["ordinal"] == str(index)
                assert written["surface"] == authored.surface
                assert written["purpose"] == authored.purpose
                assert written["expected_visible_state"] == authored.expected_outcome

    def test_every_surface_fact_is_the_surface_records(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        surfaces = {record.id: record for record in composed.bundle.surfaces}
        for package in packages.values():
            for step in package["package"]["steps"]:
                surface = surfaces[step["surface"]]
                assert step["surface_name"] == surface.public_name
                assert step["channel"] == surface.channel
                assert step["side_effects"] == sorted(surface.side_effects)

    def test_the_evidence_is_the_journeys_registered_transcript(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        """The transcript is *named*, never inlined — it is the replayed one."""
        for journey_id, package in packages.items():
            record = _journey(composed.bundle, journey_id)
            assert package["package"]["evidence"] == [
                {"id": item.id, "source": item.source}
                for item in sorted(record.evidence, key=lambda item: item.id)
            ]
            assert package["package"]["evidence"]
            for item in package["package"]["evidence"]:
                assert (REPO_ROOT / item["source"]).is_file()

    def test_the_recovery_beats_are_the_journeys_recovery_paths(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        surfaces = {record.id: record for record in composed.bundle.surfaces}
        for journey_id, package in packages.items():
            record = _journey(composed.bundle, journey_id)
            assert package["package"]["recovery"] == [
                {
                    "action": path.action,
                    "next_surface": path.next_surface,
                    "next_surface_name": surfaces[path.next_surface].public_name,
                    "when": path.when,
                }
                for path in record.recovery_paths
            ]

    def test_the_identity_is_the_build_stamps(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        stamp = composed.bundle.stamp
        for package in packages.values():
            assert package["identity"]["release"] == stamp.version_line()
            assert package["identity"]["snapshot"] == stamp.snapshot_hash
            assert package["identity"]["channel"] == stamp.build_channel

    @preview_tree_only
    def test_a_preview_build_labels_its_packages(
        self, packages: dict[str, dict]
    ) -> None:
        """H1's channel rule reaches this channel too (SDA-INV-11).

        Every build of this repository is a preview build, so every package
        says so on the one field a producer would otherwise read as the
        released version.
        """
        for package in packages.values():
            assert package["identity"]["release"].endswith(
                f"({package['identity']['channel']})"
            )

    def test_a_step_on_a_surface_nothing_serves_is_refused(
        self, composed: Build, rows: tuple
    ) -> None:
        """A walkthrough naming a command the product does not answer."""
        import dataclasses

        record = _journey(composed.bundle, "journey:first-project")
        broken = dataclasses.replace(
            record,
            steps=(
                dataclasses.replace(record.steps[0], surface="cli:s0ma/does-not-exist"),
                *record.steps[1:],
            ),
        )
        bundle = dataclasses.replace(
            composed.bundle,
            journeys=(
                *(item for item in composed.bundle.journeys if item.id != record.id),
                broken,
            ),
        )
        with pytest.raises(DocsMediaError, match="composed no surface"):
            media_package(bundle, broken, rows=rows)


# ---------------------------------------------------------------------------
# The chapter outline
# ---------------------------------------------------------------------------


class TestTheChapterOutline:
    """Suggested chapters and captions, derived from the step order."""

    def test_there_is_one_chapter_per_step_because_journeys_carry_no_grouping(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        """The design constraint, stated as a test rather than a comment.

        ``JourneyRecord`` has ``steps`` and nothing that groups them, so
        the outline is the steps. Inventing a grouping would be a teaching
        decision taken by a renderer.
        """
        for journey_id, package in packages.items():
            record = _journey(composed.bundle, journey_id)
            chapters = package["package"]["chapters"]
            assert len(chapters) == len(record.steps)
            assert [item["step"] for item in chapters] == [
                item["ordinal"] for item in package["package"]["steps"]
            ]

    def test_the_caption_is_the_steps_own_purpose_quoted(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        """Verbatim or absent — never paraphrased by a renderer."""
        for journey_id, package in packages.items():
            record = _journey(composed.bundle, journey_id)
            assert [item["caption"] for item in package["package"]["chapters"]] == [
                step.purpose for step in record.steps
            ]

    def test_the_chapter_title_is_the_surfaces_public_name(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        surfaces = {record.id: record for record in composed.bundle.surfaces}
        for journey_id, package in packages.items():
            record = _journey(composed.bundle, journey_id)
            assert [item["title"] for item in package["package"]["chapters"]] == [
                surfaces[step.surface].public_name for step in record.steps
            ]


# ---------------------------------------------------------------------------
# Cautions and consent (SDA-INV-12)
# ---------------------------------------------------------------------------


class TestTheCautionAndConsentBeats:
    """Consent and side effects are documentation facts, so they are derived."""

    def test_every_step_with_a_loud_effect_carries_a_caution_beat(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        surfaces = {record.id: record for record in composed.bundle.surfaces}
        for journey_id, package in packages.items():
            record = _journey(composed.bundle, journey_id)
            expected = {
                str(index)
                for index, step in enumerate(record.steps, start=1)
                if set(surfaces[step.surface].side_effects)
                - QUIET_EFFECTS
                - {APPROVAL_EFFECT}
            }
            assert {
                item["step"] for item in package["package"]["cautions"]
            } == expected

    def test_a_read_only_step_carries_no_caution_beat(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        """The other direction: a beat on a step that changes nothing is noise."""
        surfaces = {record.id: record for record in composed.bundle.surfaces}
        package = packages["journey:first-project"]
        record = _journey(composed.bundle, "journey:first-project")
        quiet = {
            str(index)
            for index, step in enumerate(record.steps, start=1)
            if not set(surfaces[step.surface].side_effects) - QUIET_EFFECTS
        }
        assert quiet, "this journey is supposed to end on two read-only steps"
        assert quiet.isdisjoint(
            {item["step"] for item in package["package"]["cautions"]}
        )

    def test_the_approval_step_emits_a_consent_beat_quoting_the_boundary(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        """The one journey that asks: ``journey:studi0-feedback`` (E7).

        Both of its send-class steps declare the ``approval`` effect, and
        both quote the journey's own boundary sentence rather than a
        wording this renderer chose — the words of a consent moment are the
        one place a walkthrough must not improvise.
        """
        package = packages["journey:studi0-feedback"]
        record = _journey(composed.bundle, "journey:studi0-feedback")
        beats = package["package"]["consent"]
        assert [item["surface"] for item in beats] == [
            "cli:s0ma/feedback",
            "cli:s0ma/feedback/submit",
        ]
        boundaries = [
            step.approval_boundary
            for step in record.steps
            if step.approval_boundary.strip()
        ]
        assert [item["boundary"] for item in beats] == boundaries
        for item in beats:
            assert APPROVAL_EFFECT in item["effects"]

    def test_a_consent_beat_is_emitted_for_every_approval_surface_and_no_other(
        self, composed: Build, packages: dict[str, dict]
    ) -> None:
        surfaces = {record.id: record for record in composed.bundle.surfaces}
        for journey_id, package in packages.items():
            record = _journey(composed.bundle, journey_id)
            expected = {
                str(index)
                for index, step in enumerate(record.steps, start=1)
                if APPROVAL_EFFECT in surfaces[step.surface].side_effects
            }
            assert {
                item["step"] for item in package["package"]["consent"]
            } == expected

    def test_only_the_feedback_journey_asks_for_approval(
        self, packages: dict[str, dict]
    ) -> None:
        """Recorded so a surface that later gains ``approval`` turns this red."""
        asking = {
            journey_id
            for journey_id, package in packages.items()
            if package["package"]["consent"]
        }
        assert asking == {"journey:studi0-feedback"}

    def test_an_approval_surface_whose_step_declares_no_boundary_is_refused(
        self, composed: Build, rows: tuple
    ) -> None:
        """The consent beat cannot be emitted empty; it refuses instead."""
        import dataclasses

        record = _journey(composed.bundle, "journey:studi0-feedback")
        stripped = dataclasses.replace(
            record,
            steps=tuple(
                dataclasses.replace(step, approval_boundary="") for step in record.steps
            ),
        )
        with pytest.raises(DocsMediaError, match="declares no approval boundary"):
            media_package(composed.bundle, stripped, rows=rows)


# ---------------------------------------------------------------------------
# The creative fields are H4's, not this build's
# ---------------------------------------------------------------------------


class TestTheCreativeFieldsAreAbsent:
    """§13.3: scripting, performance and visual direction stay creative work."""

    def test_no_package_carries_a_creative_key(
        self, composed: Build, rows: tuple
    ) -> None:
        """Anywhere in the document, at any depth, under any nesting."""

        def keys(value: object) -> set[str]:
            if isinstance(value, dict):
                found = set(value)
                for item in value.values():
                    found |= keys(item)
                return found
            if isinstance(value, list):
                found: set[str] = set()
                for item in value:
                    found |= keys(item)
                return found
            return set()

        for text in media_packages(composed.bundle, rows=rows).values():
            assert keys(json.loads(text)).isdisjoint(CREATIVE_KEYS)

    def test_the_named_creative_fields_are_the_ones_the_architecture_defers(
        self,
    ) -> None:
        """The list is reviewable, so the H4 handoff can name the same words."""
        for word in ("tone", "visual_direction", "music", "pacing"):
            assert word in CREATIVE_KEYS

    def test_the_renderer_module_writes_no_creative_prose(self) -> None:
        """A structural guard on the source: no key literal from that list.

        The document proof above can only see what a package *rendered*;
        this one sees a key that was added and left empty for a journey
        that happens not to fill it in.
        """
        source = (
            Path(__file__).resolve().parents[1]
            / "src/s0ma_dsl/docs_model/render_media.py"
        ).read_text(encoding="utf-8")
        for word in CREATIVE_KEYS:
            assert f'"{word}":' not in source


# ---------------------------------------------------------------------------
# Placeholders, determinism, and no machine paths
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Two builds of one tree, byte for byte, with no path from either."""

    def test_two_builds_write_one_set_of_packages(
        self, composed: Build, rows: tuple
    ) -> None:
        again = build(REPO_ROOT, head_tag=claimed_head_tag())
        assert media_packages(again.bundle, rows=rows) == media_packages(
            composed.bundle, rows=rows
        )

    def test_no_package_carries_a_machine_path(
        self, composed: Build, rows: tuple
    ) -> None:
        for relative, text in media_packages(composed.bundle, rows=rows).items():
            assert not _POSIX_PATH.search(text), relative

    def test_a_placeholder_travels_through_as_a_placeholder(
        self, composed: Build, rows: tuple
    ) -> None:
        """The closed set of :data:`PLACEHOLDERS`, written through unresolved.

        A package is a script performed later, on somebody else's machine.
        Resolving ``{project}`` would name a directory that will not exist
        when the walkthrough is shot, and would not be deterministic either.

        Planted rather than found, and the difference is the point. No
        journey record quotes a placeholder today — they live in the
        *transcript fixtures*, which a package names rather than inlines —
        so a scan of the committed packages would assert nothing and pass
        forever. Putting one into a step's expected outcome and rendering
        it proves the property the scan only gestures at: this renderer
        substitutes nothing, so a journey that quotes the toolchain's own
        placeholder gets it back verbatim.
        """
        import dataclasses

        assert not any(
            token in text
            for text in media_packages(composed.bundle, rows=rows).values()
            for token in PLACEHOLDERS
        ), "a journey now quotes a placeholder; prefer asserting on that"

        record = _journey(composed.bundle, "journey:first-project")
        quoted = " ".join(sorted(PLACEHOLDERS))
        planted = dataclasses.replace(
            record,
            steps=(
                dataclasses.replace(
                    record.steps[0],
                    expected_outcome=f"A new folder under {quoted}.",
                ),
                *record.steps[1:],
            ),
        )
        written = media_package(composed.bundle, planted, rows=rows)
        for token in PLACEHOLDERS:
            assert token in written, token
        assert json.loads(written)["package"]["steps"][0][
            "expected_visible_state"
        ] == f"A new folder under {quoted}."

    def test_the_packages_are_lean(self, composed: Build, rows: tuple) -> None:
        """A production script, not a mirror of the guide it comes from.

        A generous ceiling rather than a tight one: the point is that a
        package cannot quietly grow into a second copy of a whole guide,
        not that any particular size is right.
        """
        for relative, text in media_packages(composed.bundle, rows=rows).items():
            assert len(text.encode("utf-8")) < 32_768, relative


# ---------------------------------------------------------------------------
# Registration: the byte gate covers them
# ---------------------------------------------------------------------------


class TestTheyAreDeclaredOutputs:
    """Declared, so ``write`` writes them and ``check`` compares them."""

    def test_the_declared_set_grew_by_one_package_per_published_journey(
        self, composed: Build
    ) -> None:
        outputs = generated_outputs(composed.bundle)
        assert len(outputs) == len(composed.artifacts) == 67
        assert len(
            [item for item in outputs if item.startswith(f"{MEDIA_DIR}/")]
        ) == len(CANONICAL)

    def test_they_are_computed_and_not_decided(self, composed: Build) -> None:
        """Membership follows the catalog, so no path is listed by hand."""
        for relative in media_outputs(composed.bundle):
            assert relative not in STATIC_OUTPUTS
            assert relative in generated_outputs(composed.bundle)

    def test_each_package_is_rendered_and_addressable(self, composed: Build) -> None:
        for relative in media_outputs(composed.bundle):
            assert composed.artifact(relative).content.endswith("\n")

    @requires_checkout
    def test_the_committed_packages_match_this_build(self, composed: Build) -> None:
        """The byte gate, run over exactly the published journeys' paths."""
        findings = check(composed, REPO_ROOT / DOCS_ROOT)
        media = [
            item
            for item in findings
            if f"{DOCS_ROOT}/{MEDIA_DIR}/" in item.location
        ]
        assert media == [], [item.message for item in media]
        for relative in media_outputs(composed.bundle):
            committed = (REPO_ROOT / DOCS_ROOT / relative).read_text(encoding="utf-8")
            assert committed == composed.artifact(relative).content

    def test_the_manifest_calls_them_media_manifests(self) -> None:
        """§6.6's sixth format word, claimed the way ``package_data`` is."""
        assert (
            artifact_format(
                f"{MEDIA_DIR}/first-project.json",
                media=frozenset({f"{MEDIA_DIR}/first-project.json"}),
            )
            == "media_manifest"
        )
        assert artifact_format(f"{MEDIA_DIR}/first-project.json") == "json"

    def test_a_stale_package_is_reported(self, composed: Build) -> None:
        """The computed-collection sweep: a file no journey renders any more."""
        present = [*media_outputs(composed.bundle), f"{MEDIA_DIR}/retired.json"]
        assert stale_packages(present, composed.bundle) == (
            f"{MEDIA_DIR}/retired.json",
        )
        assert stale_packages(media_outputs(composed.bundle), composed.bundle) == ()

    def test_an_empty_collection_is_honest_rather_than_a_refusal(
        self, composed: Build
    ) -> None:
        """A caller composing a smaller provider set is supported (ADR-012 §4).

        Every negative fixture in this suite builds without a journeys
        provider, so an empty collection has to be a *state* rather than a
        finding here. What covers it is the two gates that can see more
        than this renderer: the journey floors, and the stale sweep — and
        the second is what fires in the case this fixture describes, where
        the journeys exist and the catalog stopped publishing them.
        """
        import dataclasses

        bundle = dataclasses.replace(
            composed.bundle,
            documents=tuple(
                dataclasses.replace(
                    item,
                    covers=tuple(
                        covered
                        for covered in item.covers
                        if not covered.startswith(JOURNEY_PREFIX)
                    ),
                )
                for item in composed.bundle.documents
            ),
        )
        assert media_packages(bundle, rows=()) == {}
        assert media_outputs(bundle) == ()
        # And every committed file becomes a file nothing renders.
        assert len(
            stale_packages(media_outputs(composed.bundle), bundle)
        ) == len(CANONICAL)


# ---------------------------------------------------------------------------
# Drift: a journey edit invalidates its package
# ---------------------------------------------------------------------------


class TestAJourneyEditInvalidatesItsPackage:
    """H3's acceptance: the package cannot fall out of step with its journey."""

    @requires_checkout
    def test_editing_a_journey_sentence_turns_its_package_red(
        self, tmp_path: Path
    ) -> None:
        """The whole drift proof, on a scratch copy of the checkout.

        One sentence changed in one journey record; the build recomposed
        from the scratch tree; the byte gate run against the *committed*
        packages. The edited journey's package is reported and the other
        four are reported too — because the snapshot digest every package
        carries moves when any record does, which is
        :func:`~s0ma_dsl.docs_model.serialize.snapshot_hash` doing exactly
        what it is for. Both halves matter: the first says the edit reached
        its own package, the second says no package can be stale about
        which build it belongs to.
        """
        scratch = _scratch_checkout(tmp_path / "checkout")
        target = scratch / "docs/s0ma_src/journeys/first-project.json"
        document = json.loads(target.read_text(encoding="utf-8"))
        original = document["record"]["steps"][0]["expected_outcome"]
        document["record"]["steps"][0]["expected_outcome"] = (
            "A new folder, and nothing else worth mentioning."
        )
        assert document["record"]["steps"][0]["expected_outcome"] != original
        target.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        edited = build(scratch)
        findings = check(edited, scratch / DOCS_ROOT)
        drifted = {
            item.location
            for item in findings
            if f"{DOCS_ROOT}/{MEDIA_DIR}/" in item.location
        }
        assert f"{DOCS_ROOT}/{MEDIA_DIR}/first-project.json" in drifted
        assert len(drifted) == len(CANONICAL)

        # And the edit is *in* the package, not merely detected beside it.
        rendered = json.loads(edited.artifact(f"{MEDIA_DIR}/first-project.json").content)
        assert (
            rendered["package"]["steps"][0]["expected_visible_state"]
            == "A new folder, and nothing else worth mentioning."
        )

    @requires_checkout
    def test_unpublishing_a_journey_leaves_its_package_reported_as_stale(
        self, tmp_path: Path
    ) -> None:
        """The other drift direction, which the byte comparison cannot see.

        Remove the journey from its document's ``covers`` and the journey
        stops being approved: the build renders one package fewer and the
        committed file it used to render becomes a file nothing renders —
        reported by the collection sweep rather than left in the tree.
        """
        scratch = _scratch_checkout(tmp_path / "checkout")
        catalog_path = scratch / "docs/s0ma_src/catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        for document in catalog["documents"]:
            if document["id"] == "doc:guide/first-project":
                document["covers"] = [
                    covered
                    for covered in document["covers"]
                    if covered != "journey:first-project"
                ]
        catalog_path.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        edited = build(scratch)
        assert "journey:first-project" not in {
            record.id for record in approved_journeys(edited.bundle)
        }
        assert len(media_outputs(edited.bundle)) == len(CANONICAL) - 1
        stale = {
            item.location
            for item in check(edited, scratch / DOCS_ROOT)
            if "is committed and this build renders nothing" in item.message
        }
        assert f"{DOCS_ROOT}/{MEDIA_DIR}/first-project.json" in stale
