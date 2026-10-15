"""D6 — the generated inventories, and the four claims they are worth having for.

Milestone D6 of the docs-function plan (internal) §9. Before it, one build
rendered one machine-readable snapshot nobody but a program could open and
every count in the repository's prose was written by hand. This milestone
renders five more artifacts — three inventories and two reader pages — and
the claims are:

* **the component ruling holds.** C3 deferred where a registered
  component's facts live; D6 rules for a rendered artifact rather than a
  seventh bundle group, so the model's record types are untouched, every
  component the build addresses is described with its five facts, and each
  fact names the reading it came from. A component no reading can describe
  stops the build rather than appearing as a row of blanks;
* **the inventories are complete and the counts are computed.** Every
  concept, every surface, every component, each carrying the stable id the
  model addresses it by; and no number on either page is written down —
  they are counted from the records at render time, which is the whole
  reason a generated index beats a hand-kept one;
* **three more derived sources are registered** (ADR-013 §8), each
  declaring its formats, each refusing a format it does not declare, and
  the two that describe a checkout refusing to render at all rather than
  going looking for a root. ``package_inventory`` and the repository
  provider's authority records come from one reading, so a version cannot
  move in a table without moving in the graph;
* **``DOC_SURFACE_UNCOVERED`` has teeth.** The gate reads the rendered
  index rather than rendering one for itself, so a surfaces index that
  dropped a family would fail the build that produced it.

The whole suite runs against the real checkout. Nothing here writes: the
one build is shared, and the write path is proved in
``test_docs_application_cli.py`` where it belongs.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.codegen.doc_emitter.derived_sources import (
    DOC_SOURCE_FORMAT_UNSUPPORTED,
    SUPPORTED_DOC_FORMATS,
    DerivedInput,
    lookup_source,
    records_for,
)
from s0ma_dsl.codegen.doc_emitter.renderer import DocRenderError
from s0ma_dsl.docs_model.application import (
    COMPONENTS_INVENTORY_OUTPUT,
    CONCEPTS_INDEX_OUTPUT,
    CONCEPTS_INVENTORY_OUTPUT,
    DOCS_ROOT,
    STATIC_OUTPUTS,
    SURFACES_INDEX_OUTPUT,
    SURFACES_INVENTORY_OUTPUT,
    Build,
    build,
    check_surface_index,
    generated_outputs,
)
from s0ma_dsl.docs_model.inventories import (
    BUILT_IR_DIRS,
    CHANNEL_TITLES,
    DISTRIBUTION_BY_MODULE,
    INVENTORY_SCHEMA,
    REGISTRATION_SOURCE,
    DocsInventoryError,
    component_facts,
    surfaces_index,
)
from s0ma_dsl.docs_model.providers_repo import package_facts
from s0ma_dsl.docs_model.records import RECORD_TYPES, Provenance, SurfaceRecord
from s0ma_dsl.docs_model.resolve import DOC_SURFACE_UNCOVERED
from tests._committed_claim import claimed_head_tag

if TYPE_CHECKING:
    from s0ma_dsl.docs_model.records import DocsBundle

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = REPO_ROOT / DOCS_ROOT

#: The three inventories, and the group of the bundle each one lists. Written
#: out rather than derived so that an inventory quietly listing the wrong
#: group is a failing test.
INVENTORIES = (
    (CONCEPTS_INVENTORY_OUTPUT, "concepts", "concepts"),
    (SURFACES_INVENTORY_OUTPUT, "surfaces", "surfaces"),
)

#: An absolute POSIX path anywhere in a rendered artifact (the C3 form).
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


def _document(composed: Build, relative: str) -> dict[str, Any]:
    """One rendered inventory, read back as data."""
    loaded = json.loads(composed.artifact(relative).content)
    assert isinstance(loaded, dict)
    return loaded


def _surface(identifier: str, channel: str) -> SurfaceRecord:
    """A surface record standing in for one nobody has inventoried."""
    return SurfaceRecord(
        id=identifier,
        channel=channel,
        public_name=identifier,
        intent="A capability invented by a test, so a gate has something to miss.",
        component_refs=(),
        manual_exception="Invented by a test; nothing implements it.",
        governed_by=(),
        side_effects=("read",),
        errors=(),
        provenance=Provenance(
            adapter_id="test",
            schema_version="s0ma-docs-model@1",
            source="python:test_docs_inventories",
            source_sha256="0" * 64,
        ),
    )


# ---------------------------------------------------------------------------
# T1 — the component-facts ruling
# ---------------------------------------------------------------------------


class TestTheComponentRuling:
    """Components are external ids; their facts are a rendered artifact."""

    def test_the_model_grew_no_component_record_type(self) -> None:
        """The half of the ruling that keeps arch Risk 1 closed.

        A seventh bundle group would have made the documentation graph hold
        the framework's own inventory — a second self-model, composed,
        merged, hashed and gated as documentation. It is emphatically not
        that: ``@1``'s record types are exactly what C1 declared.
        """
        assert not any(
            item.__name__ == "ComponentRecord" for item in RECORD_TYPES
        )
        from s0ma_dsl.docs_model.serialize import _GROUPS

        assert "components" not in _GROUPS

    def test_every_component_the_build_addresses_is_described(
        self, composed: Build
    ) -> None:
        """Complete against the seam the build actually resolves through."""
        document = _document(composed, COMPONENTS_INVENTORY_OUTPUT)
        described = {entry["id"] for entry in document["entries"]}
        referenced = {
            item
            for record in composed.bundle.surfaces
            for item in record.component_refs
        }
        assert referenced <= described
        assert document["counts"]["components"] == len(described)

    def test_every_entry_carries_the_five_facts_and_its_reading(
        self, composed: Build
    ) -> None:
        """id, package, kind, layer, visibility, intent — and where from."""
        document = _document(composed, COMPONENTS_INVENTORY_OUTPUT)
        sources = {item["source"] for item in document["readings"]}
        assert sources
        for entry in document["entries"]:
            assert entry["id"].startswith("component:")
            assert entry["distribution"] in set(DISTRIBUTION_BY_MODULE.values())
            assert entry["kind"], entry["id"]
            assert entry["layer"], entry["id"]
            assert entry["intent"], entry["id"]
            assert entry["read_from"] in sources, entry["id"]
            # Absent is None and never a display string: a Python
            # registration has nowhere to declare visibility, and "unknown"
            # spelled out would read as a declared value.
            assert entry["visibility"] in {None, "PUBLIC", "INTERNAL"}

    def test_a_declared_visibility_is_carried_rather_than_guessed(
        self, composed: Build
    ) -> None:
        """The transpiled packages declare it; the reading keeps it."""
        document = _document(composed, COMPONENTS_INVENTORY_OUTPUT)
        declared = document["counts"]["by_visibility"]
        assert declared.get("PUBLIC", 0) > 0
        assert declared.get("INTERNAL", 0) > 0
        assert declared.get("(not declared)", 0) > 0

    def test_each_reading_is_used_and_names_what_it_read(
        self, composed: Build
    ) -> None:
        """Three readings, one per family, each accounted for.

        A reading nobody uses is the ``DOC_GATE_VACUOUS`` shape one layer
        down: it would look like provenance and stand for nothing.
        """
        document = _document(composed, COMPONENTS_INVENTORY_OUTPUT)
        readings = {item["source"]: item for item in document["readings"]}
        assert REGISTRATION_SOURCE in readings
        assert "python:s0ma._bootstrap.bootstrap_register" in readings
        for relative in BUILT_IR_DIRS.values():
            assert f"{relative}/*.s0ma.json" in readings
        for item in readings.values():
            assert item["components"] > 0
            assert re.fullmatch(r"[0-9a-f]{64}", item["content_sha256"])
        assert sum(item["components"] for item in readings.values()) == len(
            document["entries"]
        )

    def test_a_component_no_reading_can_describe_stops_the_build(self) -> None:
        """A hole in an inventory makes every count taken from it wrong."""
        with pytest.raises(DocsInventoryError, match="no reading can describe"):
            component_facts(REPO_ROOT, ["component:s0ma_dsl.not.a.thing"])

    def test_a_component_outside_the_four_distributions_is_refused(
        self,
    ) -> None:
        """The package column is a declared mapping, never a guess."""
        with pytest.raises(DocsInventoryError, match="four distributions"):
            component_facts(REPO_ROOT, ["component:elsewhere.Thing"])


# ---------------------------------------------------------------------------
# T2 — the inventories and the indexes
# ---------------------------------------------------------------------------


class TestTheInventories:
    """Complete, addressable, counted rather than claimed."""

    @pytest.mark.parametrize(("relative", "name", "group"), INVENTORIES)
    def test_an_inventory_lists_its_whole_group(
        self, composed: Build, relative: str, name: str, group: str
    ) -> None:
        document = _document(composed, relative)
        assert document["schema"] == INVENTORY_SCHEMA
        assert document["inventory"] == name
        records = getattr(composed.bundle, group)
        assert [entry["id"] for entry in document["entries"]] == sorted(
            record.id for record in records
        )
        assert document["counts"][name] == len(records)

    def test_every_inventory_names_the_build_it_was_rendered_from(
        self, composed: Build
    ) -> None:
        """A rendering with no way back to its source is a loose page."""
        for relative in (
            CONCEPTS_INVENTORY_OUTPUT,
            SURFACES_INVENTORY_OUTPUT,
            COMPONENTS_INVENTORY_OUTPUT,
        ):
            source = _document(composed, relative)["source"]
            assert source["model_schema"] == composed.bundle.stamp.schema
            assert source["release_version"] == composed.bundle.stamp.release_version
            assert source["snapshot_hash"] == composed.bundle.stamp.snapshot_hash

    def test_the_surface_inventory_carries_the_three_index_columns(
        self, composed: Build
    ) -> None:
        """Channel, side effects, binding state — the D6 columns."""
        document = _document(composed, SURFACES_INVENTORY_OUTPUT)
        by_id = {record.id: record for record in composed.bundle.surfaces}
        for entry in document["entries"]:
            record = by_id[entry["id"]]
            assert entry["channel"] == record.channel
            assert entry["side_effects"] == list(record.side_effects)
            assert entry["binding"] in {"bound", "exception", "unbound"}
            assert (entry["binding"] == "bound") == bool(record.component_refs)

    def test_the_counts_are_computed_from_the_records(
        self, composed: Build
    ) -> None:
        """Every tally re-derived, so a stale number cannot survive."""
        document = _document(composed, SURFACES_INVENTORY_OUTPUT)
        counts = document["counts"]
        channels: dict[str, int] = {}
        for record in composed.bundle.surfaces:
            channels[record.channel] = channels.get(record.channel, 0) + 1
        assert counts["by_channel"] == channels
        assert sum(counts["by_channel"].values()) == counts["surfaces"]
        assert sum(counts["by_binding"].values()) == counts["surfaces"]
        assert counts["undeclared_side_effects"] == sum(
            1 for record in composed.bundle.surfaces if not record.side_effects
        )

    def test_rendering_twice_produces_the_same_bytes(
        self, composed: Build
    ) -> None:
        """Determinism, asserted over the renderers rather than the build."""
        again = build(
            REPO_ROOT,
            version=composed.bundle.stamp.release_version,
            head_tag=claimed_head_tag(),
        )
        for relative in generated_outputs(composed.bundle):
            assert again.artifact(relative).content == composed.artifact(
                relative
            ).content, relative


class TestTheReaderIndexes:
    """Two pages a person opens, and what a generated page owes its reader."""

    @pytest.mark.parametrize(
        "relative", [CONCEPTS_INDEX_OUTPUT, SURFACES_INDEX_OUTPUT]
    )
    def test_the_page_says_it_is_generated(
        self, composed: Build, relative: str
    ) -> None:
        text = composed.artifact(relative).content
        assert text.startswith("# ")
        assert "This page is generated." in text
        assert "the place to make a change is the thing being described" in text

    @pytest.mark.parametrize(
        "relative", [CONCEPTS_INDEX_OUTPUT, SURFACES_INDEX_OUTPUT]
    )
    def test_no_page_carries_the_machine_that_built_it(
        self, composed: Build, relative: str
    ) -> None:
        text = composed.artifact(relative).content
        assert str(REPO_ROOT) not in text
        assert not _POSIX_PATH.search(text)

    def test_every_concept_has_a_row_carrying_its_id(
        self, composed: Build
    ) -> None:
        text = composed.artifact(CONCEPTS_INDEX_OUTPUT).content
        for record in composed.bundle.concepts:
            assert f"`{record.id}`" in text, record.id
            assert record.summary.split("|")[0][:40] in text, record.id

    def test_every_surface_has_a_row_carrying_its_id(
        self, composed: Build
    ) -> None:
        text = composed.artifact(SURFACES_INDEX_OUTPUT).content
        for record in composed.bundle.surfaces:
            assert f"`{record.id}`" in text, record.id

    def test_every_channel_gets_a_section(self, composed: Build) -> None:
        """Including one this renderer has no title for.

        A renderer that dropped an unknown channel would make
        ``DOC_SURFACE_UNCOVERED`` a test of itself, so the grouping appends
        what it does not recognise instead of leaving it out.
        """
        text = composed.artifact(SURFACES_INDEX_OUTPUT).content
        for channel in {record.channel for record in composed.bundle.surfaces}:
            assert f"Channel: `{channel}`" in text, channel

        invented = dataclasses.replace(
            composed.bundle,
            surfaces=(*composed.bundle.surfaces, _surface("hw:board/pin", "hw")),
        )
        rendered = surfaces_index(invented)
        assert "Channel: `hw`" in rendered
        assert "`hw:board/pin`" in rendered

    def test_every_table_row_has_the_columns_its_header_declares(
        self, composed: Build
    ) -> None:
        """A vertical bar in an intent would shift every column after it."""
        for relative in (CONCEPTS_INDEX_OUTPUT, SURFACES_INDEX_OUTPUT):
            width = 0
            for line in composed.artifact(relative).content.splitlines():
                if not line.startswith("|"):
                    width = 0
                    continue
                cells = len(re.findall(r"(?<!\\)\|", line))
                if width == 0:
                    width = cells
                assert cells == width, f"{relative}: {line[:80]}"

    def test_the_counts_in_the_prose_are_the_real_ones(
        self, composed: Build
    ) -> None:
        """No number on either page is written by hand."""
        concepts = composed.artifact(CONCEPTS_INDEX_OUTPUT).content
        surfaces = composed.artifact(SURFACES_INDEX_OUTPUT).content
        channels = {record.channel for record in composed.bundle.surfaces}
        assert f"teaches {len(composed.bundle.concepts)} concepts" in concepts
        assert (
            f"serves {len(composed.bundle.surfaces)} capabilities across "
            f"{len(channels)} channels" in surfaces
        )

    def test_the_channel_titles_are_reader_language(self) -> None:
        """The voice rule: a person reads these, not a protocol."""
        for title in CHANNEL_TITLES.values():
            assert title[0].isupper() or title.startswith("studi0"), title
            assert "payload" not in title.lower()


@requires_checkout
class TestTheCommittedArtifacts:
    """What is on disk is what a fresh build renders, byte for byte."""

    @pytest.mark.parametrize("relative", list(STATIC_OUTPUTS))
    def test_the_committed_artifact_matches_a_fresh_render(
        self, composed: Build, relative: str
    ) -> None:
        committed = (DOCS / Path(relative)).read_text(encoding="utf-8")
        assert committed == composed.artifact(relative).content

    @pytest.mark.parametrize("relative", list(STATIC_OUTPUTS))
    def test_the_committed_bytes_are_utf8_with_line_feeds(
        self, relative: str
    ) -> None:
        raw = (DOCS / Path(relative)).read_bytes()
        assert b"\r" not in raw
        assert raw.endswith(b"\n")

    def test_the_committed_computed_outputs_match_a_fresh_render(
        self, composed: Build
    ) -> None:
        """The half of the declared set a parametrize cannot name.

        ``generated_outputs`` needs a composed bundle and ``parametrize``
        runs at collection time, so the learning collection is walked here
        rather than parametrized above — same two assertions, over exactly
        the outputs this build declared and the two above do not cover.
        """
        computed = [
            relative
            for relative in generated_outputs(composed.bundle)
            if relative not in STATIC_OUTPUTS
        ]
        assert computed, "the declared set has stopped computing anything"
        for relative in computed:
            raw = (DOCS / Path(relative)).read_bytes()
            assert b"\r" not in raw, relative
            assert raw.endswith(b"\n"), relative
            assert raw.decode("utf-8") == composed.artifact(relative).content, relative
        raw.decode("utf-8")


# ---------------------------------------------------------------------------
# T3 — the three derived-source registrations
# ---------------------------------------------------------------------------


class TestTheRegisteredSources:
    """ADR-013 §8's next three rows, with their providers behind them."""

    @pytest.mark.parametrize(
        ("name", "needs_input"),
        [
            ("document_catalog", True),
            ("cli_commands", False),
            ("package_inventory", True),
        ],
    )
    def test_the_row_declares_all_three_formats_and_its_input(
        self, name: str, needs_input: bool
    ) -> None:
        source = lookup_source(name)
        assert source is not None
        assert source.formats == SUPPORTED_DOC_FORMATS
        assert source.narrowing_reason is None
        assert source.needs_input is needs_input
        assert source.intent

    @pytest.mark.parametrize(
        "name", ["document_catalog", "cli_commands", "package_inventory"]
    )
    def test_the_source_renders_records_in_every_format_it_declares(
        self, name: str
    ) -> None:
        source = lookup_source(name)
        assert source is not None
        handed = DerivedInput(root=REPO_ROOT) if source.needs_input else None
        first = records_for(
            name, doc_format="markdown", decl_name="probe", derived_input=handed
        )
        for doc_format in sorted(SUPPORTED_DOC_FORMATS):
            again = records_for(
                name,
                doc_format=doc_format,
                decl_name="probe",
                derived_input=handed,
            )
            assert again.records == first.records
            assert again.content_hash == first.content_hash
        assert first.records
        assert first.sort_key in first.field_names()
        assert first.schema_version == source.schema_version

    def test_an_undeclared_format_is_refused_by_name(self) -> None:
        """ADR-013 §4, restated for the sources this milestone adds."""
        with pytest.raises(DocRenderError) as caught:
            records_for(
                "cli_commands", doc_format="latex", decl_name="probe"
            )
        assert caught.value.code == DOC_SOURCE_FORMAT_UNSUPPORTED

    def test_a_checkout_scoped_source_refuses_to_guess_a_root(self) -> None:
        """ADR-013 §2: a provider is handed its input and never finds one.

        The failure is named and remediated rather than being an empty
        table, which is the shape a source nobody wired up would have.
        """
        for name in ("document_catalog", "package_inventory"):
            with pytest.raises(DocRenderError) as caught:
                records_for(name, doc_format="markdown", decl_name="probe")
            assert "describes a checkout" in str(caught.value)
            assert caught.value.remediation is not None
            assert "DerivedInput" in caught.value.remediation

    def test_document_catalog_renders_the_catalogs_own_rows(self) -> None:
        from s0ma_dsl.docs_model.providers_catalog import CatalogProvider

        rendered = records_for(
            "document_catalog",
            doc_format="markdown",
            decl_name="probe",
            derived_input=DerivedInput(root=REPO_ROOT),
        )
        documents = CatalogProvider(root=REPO_ROOT).documents()
        assert rendered.field_names() == (
            "id",
            "title",
            "path",
            "status",
            "authority",
        )
        rows = rendered.as_mappings()
        assert [row["id"] for row in rows] == sorted(
            record.id for record in documents
        )
        by_id = {record.id: record for record in documents}
        for row in rows:
            identifier = row["id"]
            assert identifier is not None
            assert row["path"] == by_id[identifier].canonical_source
            assert row["authority"] == (by_id[identifier].authority or None)

    def test_cli_commands_renders_the_interface_reading(self) -> None:
        from s0ma_dsl.docs_model.providers_cli import CliProvider

        rendered = records_for(
            "cli_commands", doc_format="markdown", decl_name="probe"
        )
        interfaces = CliProvider().interface()
        rows = rendered.as_mappings()
        assert rendered.field_names() == (
            "command",
            "intent",
            "arguments",
            "options",
            "effects",
        )
        assert {row["command"] for row in rows} == {
            item.public_name for item in interfaces
        }
        held = {row["command"]: row for row in rows}
        for item in interfaces:
            row = held[item.public_name]
            if item.arguments:
                assert row["arguments"] is not None
                assert item.arguments[0].dest in row["arguments"]
            else:
                assert row["arguments"] is None
            if item.options:
                assert row["options"] is not None
            else:
                assert row["options"] is None

    def test_package_inventory_renders_the_four_distributions(self) -> None:
        rendered = records_for(
            "package_inventory",
            doc_format="markdown",
            decl_name="probe",
            derived_input=DerivedInput(root=REPO_ROOT),
        )
        rows = rendered.as_mappings()
        assert rendered.field_names() == ("distribution", "version", "depends_on")
        assert [row["distribution"] for row in rows] == [
            "s0ma-core",
            "s0ma-dsl",
            "s0ma-mcp",
            "s0ma-studi0",
        ]
        versions = {row["version"] for row in rows}
        assert len(versions) == 1, f"INV-4 lockstep: {versions}"
        direction = {row["distribution"]: row["depends_on"] for row in rows}
        assert direction["s0ma-core"] is None
        assert direction["s0ma-dsl"] == "s0ma-core"
        assert direction["s0ma-mcp"] == "s0ma-core, s0ma-dsl"

    def test_the_inventory_and_the_authority_records_are_one_reading(
        self, composed: Build
    ) -> None:
        """C4's stopgap and §7.7's inventory now read the same file once.

        Two readings of one ``pyproject.toml`` is how a version in a
        rendered table drifts from a version in the composed graph with
        nobody at fault. This asserts the merge D6 made.
        """
        rendered = records_for(
            "package_inventory",
            doc_format="markdown",
            decl_name="probe",
            derived_input=DerivedInput(root=REPO_ROOT),
        )
        rows = {row["distribution"]: row for row in rendered.as_mappings()}
        for item in package_facts(REPO_ROOT):
            assert rows[item.distribution]["version"] == item.version
        for record in composed.bundle.authorities:
            if not record.id.startswith("authority:declared/package."):
                continue
            name = record.id.rpartition(".")[2]
            version = rows[name]["version"]
            assert version is not None
            assert f"version={version}" in record.status


# ---------------------------------------------------------------------------
# T4 — DOC_SURFACE_UNCOVERED has teeth
# ---------------------------------------------------------------------------


class TestSurfaceCoverageHasTeeth:
    """The gate reads the index this build commits, and can fail on it."""

    def test_the_real_build_is_covered(self, composed: Build) -> None:
        index = composed.artifact(SURFACES_INDEX_OUTPUT).content
        assert check_surface_index(composed.bundle, index=index) == []
        assert not [
            item for item in composed.findings if item.code == DOC_SURFACE_UNCOVERED
        ]

    def test_the_wired_gate_reads_the_rendered_artifact(
        self, composed: Build
    ) -> None:
        """Truncate what the build rendered and the gate notices.

        This is the proof that the gate is wired to the artifact rather
        than to a second rendering of the bundle: the only thing changed is
        the text the caller hands over.
        """
        index = composed.artifact(SURFACES_INDEX_OUTPUT).content
        head, _, _ = index.partition("## ")
        findings = check_surface_index(composed.bundle, index=head)
        assert findings
        assert {item.code for item in findings} == {DOC_SURFACE_UNCOVERED}
        assert all(
            item.location == f"{DOCS_ROOT}/{SURFACES_INDEX_OUTPUT}"
            for item in findings
        )
        assert all(item.remediation for item in findings)

    def test_a_surface_nobody_inventoried_fails_the_gate(
        self, composed: Build
    ) -> None:
        """The fixture the milestone asks for: a public tool, uninventoried.

        The bundle is the requirement and the index is what is actually
        reachable, and they are allowed to differ — a gate that read both
        from one place would pass by construction.
        """
        planted: DocsBundle = dataclasses.replace(
            composed.bundle,
            surfaces=(
                *composed.bundle.surfaces,
                _surface("mcp:tool/invented_tool", "mcp_tool"),
            ),
        )
        index = composed.artifact(SURFACES_INDEX_OUTPUT).content
        findings = check_surface_index(planted, index=index)
        assert [item.code for item in findings] == [DOC_SURFACE_UNCOVERED]
        assert "mcp:tool/invented_tool" in findings[0].message

        # Inventoried, it passes — which is what makes the failure above a
        # statement about coverage rather than about the planted record.
        assert check_surface_index(planted, index=surfaces_index(planted)) == []
