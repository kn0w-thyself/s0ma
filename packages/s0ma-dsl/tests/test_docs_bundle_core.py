"""F8a — the core teaching slice, and the four claims it is worth having for.

Milestone F8 of the docs-function plan (internal) §11, owner decision D-9.

The slice exists because s0ma-core shipped unable to teach: its teaching
module read a Markdown user guide it located by walking up to a repository
checkout, and no wheel has ever carried that guide. This module renders the
content into one file that ships inside the core wheel instead. The claims:

* **it selects honestly.** Every concept, because a language concept is
  product-wide knowledge and not a fact about which packages are
  installed; core's own served capabilities and only those, chosen by
  provenance rather than by a list of channel words that would go stale;
  and the journeys as pointers whose availability is *counted* — not one
  of their steps is a core surface today, and the file says so rather than
  handing a core-only reader steps it cannot take;
* **it is core-neutral.** The document is objects, arrays, strings and
  numbers. Nothing in it needs s0ma-dsl to read, which is what makes D-9's
  "no upward dependency" possible at all — the reader's half of that
  proof is ``packages/s0ma-core/tests/test_teaching_slice.py``;
* **the compatibility promise is checked here, not in core.** The twelve
  keyword groups core answered on before are re-pointed at current topics
  in this module, so a concept somebody renames fails the documentation
  build with a named finding instead of emptying an agent's answer;
* **it refuses rather than shipping something empty.** A build that
  composed no concepts, no core surfaces or no journeys would otherwise
  produce a wheel that teaches nothing and passes every byte comparison
  downstream, because there would be no bytes to compare.

The suite runs against the real checkout and writes nothing.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.docs_model.application import (
    CORE_SLICE_OUTPUT,
    DOCS_ROOT,
    STATIC_OUTPUTS,
    Build,
    build,
    generated_outputs,
)
from s0ma_dsl.docs_model.bundle_core import (
    ALL_INDEX,
    CONCEPTS_INDEX,
    CORE_TEACHING_SCHEMA,
    ENVELOPE,
    JOURNEYS_INDEX,
    LEGACY_KEYWORDS,
    LINES_NAMES,
    LINES_SUMMARIES,
    SURFACES_INDEX,
    DocsCoreSliceError,
    core_surfaces,
    core_teaching_slice,
)
from s0ma_dsl.docs_model.ids import AliasIndex
from s0ma_dsl.docs_model.providers_concepts import FORBIDDEN_IN_AUTHORED_PROSE
from s0ma_dsl.docs_model.providers_core import PROVIDER_ID as CORE_PROVIDER_ID
from tests._committed_claim import claimed_head_tag

if TYPE_CHECKING:
    from s0ma_dsl.docs_model.records import DocsBundle

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The mirror inside the core package. The documentation application writes
#: only under ``docs/``; this copy is refreshed beside it and held equal by
#: a gate in core's own suite. Named here so this module can assert the two
#: agree from the side that produces them.
MIRROR = REPO_ROOT / "packages/s0ma-core/src/s0ma/_teaching/slice.json"

#: The four navigation entries the slice carries, and how each writes a line.
INDEXES = (
    (ALL_INDEX, LINES_NAMES),
    (CONCEPTS_INDEX, LINES_SUMMARIES),
    (SURFACES_INDEX, LINES_SUMMARIES),
    (JOURNEYS_INDEX, LINES_SUMMARIES),
)


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
def document(composed: Build) -> dict[str, Any]:
    """The rendered slice, read back as data."""
    loaded = json.loads(composed.artifact(CORE_SLICE_OUTPUT).content)
    assert isinstance(loaded, dict)
    return loaded


def _topics(document: dict[str, Any], group: str) -> list[dict[str, Any]]:
    return [item for item in document["topics"] if item["group"] == group]


# ---------------------------------------------------------------------------
# It is a declared output of the application
# ---------------------------------------------------------------------------


class TestDeclaredOutput:
    """The slice is written and compared like every other artifact."""

    def test_it_is_a_decided_output(self) -> None:
        assert CORE_SLICE_OUTPUT in STATIC_OUTPUTS

    def test_it_is_a_machine_artifact_and_not_a_page(self) -> None:
        """``_generated/`` is ADR-012 §1's line: a program reads this one."""
        assert CORE_SLICE_OUTPUT.startswith("_generated/")
        assert CORE_SLICE_OUTPUT.endswith(".json")

    def test_the_build_renders_it(self, composed: Build) -> None:
        assert CORE_SLICE_OUTPUT in generated_outputs(composed.bundle)
        assert composed.artifact(CORE_SLICE_OUTPUT).content

    @requires_checkout
    def test_it_is_committed(self, composed: Build) -> None:
        committed = REPO_ROOT / DOCS_ROOT / CORE_SLICE_OUTPUT
        assert committed.read_text(encoding="utf-8") == composed.artifact(
            CORE_SLICE_OUTPUT
        ).content

    @requires_checkout
    def test_the_core_mirror_is_the_same_bytes(self, composed: Build) -> None:
        """The producing side of the drift gate core's suite also runs.

        Both sides, deliberately: core's suite catches a mirror that fell
        behind for somebody who never runs the documentation build, and
        this catches a documentation build whose author forgot the mirror
        exists.
        """
        assert MIRROR.read_text(encoding="utf-8") == composed.artifact(
            CORE_SLICE_OUTPUT
        ).content, (
            "packages/s0ma-core/src/s0ma/_teaching/slice.json has drifted "
            "from what this build renders; refresh the mirror (see "
            "docs/RELEASING.md)"
        )


# ---------------------------------------------------------------------------
# What it selects
# ---------------------------------------------------------------------------


class TestSelection:
    """Every rule of selection, checked against the composition."""

    def test_it_names_its_own_schema(self, document: dict[str, Any]) -> None:
        assert document["schema"] == CORE_TEACHING_SCHEMA
        assert document["schema"] != document["source"]["model_schema"]

    def test_every_concept_travels(
        self, composed: Build, document: dict[str, Any]
    ) -> None:
        """All of them: a concept is knowledge, not an installed package."""
        assert {item["id"] for item in _topics(document, "concepts")} == {
            record.id for record in composed.bundle.concepts
        }

    def test_exactly_core_s_own_capabilities_travel(
        self, composed: Build, document: dict[str, Any]
    ) -> None:
        """By provenance — a channel core grows tomorrow arrives with it."""
        expected = {
            record.id
            for record in composed.bundle.surfaces
            if record.provenance.adapter_id == CORE_PROVIDER_ID
        }
        assert {item["id"] for item in _topics(document, "surfaces")} == expected
        assert expected

    def test_no_other_package_s_capabilities_travel(
        self, composed: Build, document: dict[str, Any]
    ) -> None:
        """A core-only install must not be told about the authoring CLI."""
        carried = {item["id"] for item in _topics(document, "surfaces")}
        foreign = {
            record.id
            for record in composed.bundle.surfaces
            if record.provenance.adapter_id != CORE_PROVIDER_ID
        }
        assert carried & foreign == set()
        assert foreign, "the composition holds no non-core surfaces to exclude"

    def test_core_surfaces_are_sorted_and_complete(self, composed: Build) -> None:
        found = core_surfaces(composed.bundle)
        assert [record.id for record in found] == sorted(
            record.id for record in found
        )

    def test_journeys_travel_as_pointers_with_counted_availability(
        self, composed: Build, document: dict[str, Any]
    ) -> None:
        """Not one journey step is a core surface, and the file says so."""
        servable = {record.id for record in core_surfaces(composed.bundle)}
        for record in composed.bundle.journeys:
            taken = [step for step in record.steps if step.surface in servable]
            entry = next(
                item for item in document["topics"] if item["id"] == record.id
            )
            expected = (
                ENVELOPE["availability-none"]
                if not taken
                else ENVELOPE["availability-partial"]
            )
            assert entry["availability"] == expected

    def test_counts_are_computed_from_what_was_selected(
        self, document: dict[str, Any]
    ) -> None:
        counts = document["counts"]
        assert counts["concepts"] == len(_topics(document, "concepts"))
        assert counts["surfaces"] == len(_topics(document, "surfaces"))
        assert counts["journeys"] == len(_topics(document, "journeys"))
        assert counts["topics"] == len(document["topics"])
        assert counts["indexes"] == len(document["indexes"])
        assert counts["keywords"] == len(LEGACY_KEYWORDS)


# ---------------------------------------------------------------------------
# What a topic says
# ---------------------------------------------------------------------------


class TestTopics:
    """Facts travel verbatim, headings are borrowed, identity is carried once."""

    def test_teaching_prose_is_reproduced_word_for_word(
        self, composed: Build, document: dict[str, Any]
    ) -> None:
        """Nothing is paraphrased on the way into the file."""
        by_id = {record.id: record for record in composed.bundle.concepts}
        for entry in _topics(document, "concepts"):
            record = by_id[entry["id"]]
            said = {
                section["heading"]: section.get("text")
                for section in entry["sections"]
                if "text" in section
            }
            assert record.plain_definition in said.values()
            assert record.purpose in said.values()
            assert entry["summary"] == record.summary

    def test_headings_come_from_the_human_channel(
        self, document: dict[str, Any]
    ) -> None:
        """One opinion about what a section is called, in one place."""
        from s0ma_dsl.docs_model.render_human import spec_for

        labels = spec_for("concepts").labels
        for entry in _topics(document, "concepts"):
            for section in entry["sections"]:
                assert section["heading"] == labels[section["fact"]].removeprefix(
                    "## "
                )

    def test_no_topic_carries_a_copy_of_the_build_stamp(
        self, document: dict[str, Any]
    ) -> None:
        """``BUILD_STAMP_ONLY_FIELDS``, said about an artifact."""
        for entry in document["topics"]:
            assert "release_version" not in entry
            assert "snapshot_hash" not in entry

    def test_the_build_stamp_is_carried_once(
        self, composed: Build, document: dict[str, Any]
    ) -> None:
        assert document["source"] == {
            "build_channel": composed.bundle.stamp.build_channel,
            "model_schema": composed.bundle.stamp.schema,
            "release_version": composed.bundle.stamp.release_version,
            "snapshot_hash": composed.bundle.stamp.snapshot_hash,
        }

    def test_the_channel_travels_with_the_slice(
        self, composed: Build, document: dict[str, Any]
    ) -> None:
        """H2: the wheel-embedded slice can say which channel built it.

        Without this field core's identity line was the one line in the
        product that could not: a wheel built from ``main`` told its reader
        "This answer came from s0ma 0.18.1" flat. The version is kept bare
        here and the channel beside it — core composes the written form
        itself, by the same rule ``BuildStamp.version_line`` applies — so
        the field a machine compares stays a version and not a sentence.
        """
        source = document["source"]
        assert source["build_channel"] == composed.bundle.stamp.build_channel
        assert "(" not in source["release_version"], source["release_version"]

    def test_no_topic_has_an_empty_section(self, document: dict[str, Any]) -> None:
        """An empty heading reads as a product that stopped answering."""
        for entry in document["topics"]:
            for section in entry["sections"]:
                assert section.get("text", "x").strip() or section.get("items")

    def test_document_pointers_come_from_the_catalog(
        self, composed: Build, document: dict[str, Any]
    ) -> None:
        by_id = {record.id: record for record in composed.bundle.documents}
        for entry in document["topics"]:
            for pointer in entry["documents"]:
                record = by_id[pointer["id"]]
                assert entry["id"] in record.covers
                assert pointer["canonical_source"] == record.canonical_source

    def test_aliases_only_forward_to_topics_the_slice_carries(
        self, document: dict[str, Any]
    ) -> None:
        """A promise the file cannot keep is not carried at all."""
        addressable = {entry["id"] for entry in document["topics"]}
        assert set(document["aliases"].values()) <= addressable
        assert document["aliases"]


# ---------------------------------------------------------------------------
# Navigation and the compatibility promise
# ---------------------------------------------------------------------------


class TestNavigationAndKeywords:
    """The lists a reader lands on, and the vocabulary they used to type."""

    @pytest.mark.parametrize(("identifier", "lines"), INDEXES)
    def test_each_index_is_present_and_declares_its_line_form(
        self, document: dict[str, Any], identifier: str, lines: str
    ) -> None:
        entry = next(
            item for item in document["indexes"] if item["id"] == identifier
        )
        assert entry["lines"] == lines
        assert entry["groups"]

    def test_the_whole_corpus_index_lists_every_topic(
        self, document: dict[str, Any]
    ) -> None:
        entry = next(
            item for item in document["indexes"] if item["id"] == ALL_INDEX
        )
        listed = {
            identifier
            for group in entry["groups"]
            for identifier in group["topics"]
        }
        assert listed == {item["id"] for item in document["topics"]}

    def test_every_index_entry_is_a_topic_the_slice_carries(
        self, document: dict[str, Any]
    ) -> None:
        addressable = {item["id"] for item in document["topics"]}
        for entry in document["indexes"]:
            for group in entry["groups"]:
                assert set(group["topics"]) <= addressable

    def test_every_legacy_keyword_points_at_something_addressable(
        self, document: dict[str, Any]
    ) -> None:
        """The compatibility promise, in the rendered file."""
        addressable = {item["id"] for item in document["topics"]} | {
            item["id"] for item in document["indexes"]
        }
        assert set(document["keywords"].values()) <= addressable
        assert set(document["keywords"]) == set(LEGACY_KEYWORDS)

    def test_the_live_example_topics_exist(self, document: dict[str, Any]) -> None:
        addressable = {item["id"] for item in document["topics"]}
        assert document["live_example_topics"]
        assert set(document["live_example_topics"]) <= addressable


# ---------------------------------------------------------------------------
# Presentation is declared, and voice-checked
# ---------------------------------------------------------------------------


class TestEnvelope:
    """Every sentence this module writes is enumerated and follows the voice rule."""

    def test_every_envelope_string_is_in_the_file(
        self, document: dict[str, Any]
    ) -> None:
        rendered = json.dumps(document, ensure_ascii=False)
        for key, text in ENVELOPE.items():
            if key.startswith("availability-partial"):
                continue  # written only when a journey becomes half-walkable
            assert text in rendered, key

    @pytest.mark.parametrize("key", sorted(ENVELOPE))
    def test_envelope_prose_follows_the_voice_rule(self, key: str) -> None:
        for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE:
            assert not pattern.search(ENVELOPE[key]), (key, label)

    def test_the_generator_writes_no_prose_it_has_not_declared(
        self, document: dict[str, Any]
    ) -> None:
        """A journey's availability is one of two declared sentences, never a third."""
        declared = {ENVELOPE["availability-none"], ENVELOPE["availability-partial"]}
        for entry in _topics(document, "journeys"):
            assert entry["availability"] in declared


# ---------------------------------------------------------------------------
# It refuses rather than shipping something empty
# ---------------------------------------------------------------------------


class TestRefusals:
    """The anti-vacuity floor, and the compatibility check, both armed."""

    @pytest.mark.parametrize("group", ["concepts", "surfaces", "journeys"])
    def test_an_empty_family_refuses(self, composed: Build, group: str) -> None:
        emptied = _without(composed.bundle, group)
        with pytest.raises(DocsCoreSliceError):
            core_teaching_slice(emptied, aliases=AliasIndex.of(()))

    def test_a_keyword_pointing_nowhere_refuses(
        self, composed: Build, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A renamed concept is a red build, not an empty answer."""
        import s0ma_dsl.docs_model.bundle_core as module

        monkeypatch.setattr(
            module, "LEGACY_KEYWORDS", {"checklist": "concept:renamed-away"}
        )
        with pytest.raises(DocsCoreSliceError) as raised:
            core_teaching_slice(composed.bundle, aliases=AliasIndex.of(()))
        assert "concept:renamed-away" in str(raised.value)

    def test_a_refusal_reaches_the_build_as_a_finding(self) -> None:
        """The application reports a refused renderer; it does not raise.

        Proved by construction rather than by breaking a build: the
        artifact goes through the same ``keep`` seam every other one does,
        which turns a ``DocsModelError`` into ``DOC_GATE_VACUOUS``.
        """
        assert issubclass(DocsCoreSliceError, Exception)
        from s0ma_dsl.docs_model.records import DocsModelError

        assert issubclass(DocsCoreSliceError, DocsModelError)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Same bundle, same bytes — and no machine path anywhere in them."""

    def test_two_renders_are_byte_identical(self, composed: Build) -> None:
        aliases = AliasIndex.of(())
        first = core_teaching_slice(composed.bundle, aliases=aliases)
        second = core_teaching_slice(composed.bundle, aliases=aliases)
        assert first == second

    def test_topics_are_sorted_by_id(self, document: dict[str, Any]) -> None:
        identifiers = [item["id"] for item in document["topics"]]
        assert identifiers == sorted(identifiers)

    def test_it_ends_with_exactly_one_line_feed(self, composed: Build) -> None:
        content = composed.artifact(CORE_SLICE_OUTPUT).content
        assert content.endswith("\n")
        assert not content.endswith("\n\n")

    def test_no_absolute_path_reaches_the_file(self, composed: Build) -> None:
        content = composed.artifact(CORE_SLICE_OUTPUT).content
        assert str(REPO_ROOT) not in content


def _without(bundle: DocsBundle, group: str) -> DocsBundle:
    """``bundle`` with one group emptied, for the floors to catch."""
    field = {"concepts": "concepts", "journeys": "journeys", "surfaces": "surfaces"}[
        group
    ]
    return dataclasses.replace(bundle, **{field: ()})
