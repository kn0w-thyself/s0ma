"""H1 — the documentation manifest, and the four claims it is worth having for.

Milestone H1 of the docs-function plan (internal) §13. Before it a build
committed fifty-four artifacts and nothing said, in one place, *what build
they were*. The manifest says it, and the claims are:

* **the schema is architecture §13.1's, exactly.** Every field it names is
  present, each derived from one place, and the two additions this
  milestone makes are the ones §13.2 forces — a channel on the manifest and
  a channel on every artifact, without which none of §13.2's rules can be
  checked at all;
* **it is byte-deterministic, and nothing in it is a time.** Two builds of
  one tree write the same bytes. That is the acceptance criterion of the
  whole initiative, and the manifest is the artifact most likely to break
  it, because a manifest is exactly where a build wants to write a
  timestamp and a machine path;
* **the channel is derived and never hand-set.** :func:`channel_of` is one
  rule over two values, so the release case is provable from a fixture on a
  tree that carries no tags — which this repository's is, today, and every
  build here is therefore a preview build;
* **a preview build says so where a reader will see it.** The identity
  block of every rendered page carries the version with its channel, on
  every channel that renders a topic, because the labelling happens once in
  ``facts_of``.

The suite runs against the real checkout and writes nothing. The negative
proofs — a preview artifact in a release manifest, a version-switch, a
mixed build, a broken lockstep — belong to the negative battery
(``test_docs_model_negative.py``, ``TestTheReleaseCurrency``) where every
other ``DOC_*`` fixture lives and where the completeness audit can see them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.docs_model.application import (
    DOCS_MANIFEST_OUTPUT,
    DOCS_ROOT,
    STATIC_OUTPUTS,
    Build,
    build,
    generated_outputs,
    release_version,
)
from s0ma_dsl.docs_model.manifest import (
    ARTIFACT_FIELDS,
    LOCKSTEP_ANCHOR,
    MANIFEST_FIELDS,
    MANIFEST_SCHEMA,
    DocsManifestError,
    artifact_format,
    channel_of,
    manifest_from_json,
    manifest_of,
    product_version_of,
    render_manifest,
    source_commit_of,
    version_tag,
)
from s0ma_dsl.docs_model.providers_repo import package_facts
from s0ma_dsl.docs_model.records import (
    HISTORICAL_CHANNEL,
    PREVIEW_CHANNEL,
    RELEASE_CHANNEL,
    SCHEMA,
)
from s0ma_dsl.docs_model.serialize import content_hash
from s0ma_dsl.docs_model.validate import check_manifest
from tests._committed_claim import claimed_head_tag, preview_tree_only

if TYPE_CHECKING:
    from s0ma_dsl.docs_model.manifest import DocsManifest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = REPO_ROOT / DOCS_ROOT

#: An absolute POSIX path anywhere in a rendered artifact (the C3 form,
#: reused: a manifest is the one artifact that lists files, so it is the one
#: most likely to list them by the path they had on the machine that built
#: it).
_POSIX_PATH = re.compile(r"""(?:^|[\s"(\[])/(?:Users|home|private|tmp|var|opt)/""")

#: Anything that reads as a moment. Four shapes, because a build that wanted
#: to stamp a time could reach for any of them: an ISO date, an ISO
#: date-time, a ten-digit unix second, and the words a formatter writes.
_A_TIME = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:|\d{4}-\d{2}-\d{2}\b|\b1[0-9]{9}\b|"
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|GMT|UTC)\b"
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
def manifest(composed: Build) -> DocsManifest:
    """The manifest this build rendered, read back out of its own bytes."""
    return manifest_from_json(composed.artifact(DOCS_MANIFEST_OUTPUT).content)


# ---------------------------------------------------------------------------
# The schema (architecture §13.1)
# ---------------------------------------------------------------------------


class TestTheSchema:
    """§13.1's list, and the two fields §13.2 forces on top of it."""

    def test_the_fields_are_the_ones_the_architecture_names(self) -> None:
        """Written out here so a field added without a decision fails a test.

        The manifest is the document H2's wheel verification reads out of a
        release. A field that appeared without anybody deciding would be a
        contract change made by a diff nobody reviewed as one.
        """
        assert MANIFEST_FIELDS == (
            "schema",
            "product_version",
            "build_channel",
            "source_commit",
            "package_versions",
            "provider_schemas",
            "source_hashes",
            "snapshot_hash",
            "artifacts",
        )

    def test_an_artifact_row_is_architecture_6_6_plus_its_channel(self) -> None:
        assert ARTIFACT_FIELDS == (
            "id",
            "format",
            "source_document",
            "path_or_uri",
            "content_hash",
            "release_version",
            "source_snapshot",
            "build_channel",
        )

    def test_the_schema_is_the_models_own(self, manifest: DocsManifest) -> None:
        """One version line for the model and the manifest that describes it."""
        assert MANIFEST_SCHEMA == SCHEMA
        assert manifest.schema == SCHEMA

    def test_the_document_round_trips_through_the_house_reader(
        self, composed: Build
    ) -> None:
        """Written, read, written: the same bytes, or the schema is lying."""
        text = composed.artifact(DOCS_MANIFEST_OUTPUT).content
        assert render_manifest(manifest_from_json(text)) == text

    def test_a_document_with_a_field_nobody_declared_is_refused(
        self, composed: Build
    ) -> None:
        document = json.loads(composed.artifact(DOCS_MANIFEST_OUTPUT).content)
        document["generated_at"] = "2026-08-30T00:00:00Z"
        with pytest.raises(Exception, match="unexpected"):
            manifest_from_json(json.dumps(document))


# ---------------------------------------------------------------------------
# Where each fact comes from
# ---------------------------------------------------------------------------


class TestTheFacts:
    """Each one derived from a reading this build already made."""

    def test_the_product_version_is_the_lockstep_anchors(
        self, manifest: DocsManifest
    ) -> None:
        """PRD INV-4: s0ma-core's version is the product's."""
        anchored = {item.distribution: item.version for item in manifest.package_versions}
        assert anchored[LOCKSTEP_ANCHOR] == manifest.product_version

    def test_the_docs_project_version_is_deliberately_not_it(
        self, manifest: DocsManifest
    ) -> None:
        """``docs/pyproject.toml`` is pinned at 0.0.0 and is outside the lockstep.

        The documentation application ships in no wheel, so its own version
        says nothing about the product. Reading it would make every rendered
        page claim to document s0ma 0.0.0 — which is why the manifest reads
        the four distributions and not the project it is built by.
        """
        import tomllib

        declared = tomllib.loads((DOCS / "pyproject.toml").read_text(encoding="utf-8"))
        assert declared["project"]["version"] == "0.0.0"
        assert manifest.product_version != "0.0.0"

    def test_every_distribution_is_named_once(self, manifest: DocsManifest) -> None:
        read = {item.distribution: item.version for item in package_facts(REPO_ROOT)}
        assert {item.distribution for item in manifest.package_versions} == set(read)
        assert len(manifest.package_versions) == len(read)
        for item in manifest.package_versions:
            assert item.version == read[item.distribution]

    def test_every_provider_that_emitted_anything_names_its_schema(
        self, manifest: DocsManifest
    ) -> None:
        assert {item.provider_id for item in manifest.provider_schemas} == {
            "catalog",
            "cli",
            "concepts-language",
            "concepts-product",
            "config",
            "core",
            "diagnostics",
            "journeys",
            "mcp",
            "repo",
            "studi0",
        }
        assert {item.schema_version for item in manifest.provider_schemas} == {SCHEMA}

    def test_every_source_is_repository_relative_and_digested(
        self, manifest: DocsManifest
    ) -> None:
        assert manifest.source_hashes
        for item in manifest.source_hashes:
            assert not item.source.startswith("/"), item.source
            assert re.fullmatch(r"[0-9a-f]{64}", item.sha256), item.source

    @requires_checkout
    def test_a_source_digest_is_the_files_own(self, manifest: DocsManifest) -> None:
        """Not a digest of something else that happens to be nearby.

        One row is checked against the file on disk, which is enough: the
        provenance is stamped by one function and a wrong one would be
        wrong everywhere.
        """
        import hashlib

        checked = 0
        for item in manifest.source_hashes:
            target = REPO_ROOT.joinpath(*item.source.split("/"))
            if not target.is_file():
                continue
            text = target.read_text(encoding="utf-8").replace("\r\n", "\n")
            assert hashlib.sha256(text.encode("utf-8")).hexdigest() == item.sha256
            checked += 1
            if checked == 3:
                break
        assert checked == 3

    def test_the_snapshot_digest_is_the_bundles_own(
        self, composed: Build, manifest: DocsManifest
    ) -> None:
        assert manifest.snapshot_hash == composed.bundle.stamp.snapshot_hash

    def test_the_source_commit_is_the_identity_of_the_sources_it_read(
        self, manifest: DocsManifest
    ) -> None:
        """Computed from the source set, so it survives being committed.

        A git object name could not: the manifest is a committed artifact,
        so a value that changed with the commit containing it would be
        stale the instant it was written, every time.
        """
        assert manifest.source_commit == source_commit_of(manifest.source_hashes)
        assert manifest.source_commit.startswith("sha256:")

    def test_a_changed_source_moves_the_source_commit(
        self, manifest: DocsManifest
    ) -> None:
        import dataclasses

        moved = dataclasses.replace(manifest.source_hashes[0], sha256="f" * 64)
        assert source_commit_of((moved, *manifest.source_hashes[1:])) != (
            manifest.source_commit
        )


# ---------------------------------------------------------------------------
# The artifact list
# ---------------------------------------------------------------------------


class TestTheArtifacts:
    """Everything this build rendered, except the one file holding the list."""

    def test_it_lists_every_other_declared_output(
        self, composed: Build, manifest: DocsManifest
    ) -> None:
        listed = {item.path_or_uri for item in manifest.artifacts}
        expected = {
            f"{DOCS_ROOT}/{relative}"
            for relative in generated_outputs(composed.bundle)
            if relative != DOCS_MANIFEST_OUTPUT
        }
        assert listed == expected
        assert len(manifest.artifacts) == len(generated_outputs(composed.bundle)) - 1

    def test_it_does_not_list_itself(self, manifest: DocsManifest) -> None:
        """A content hash of bytes containing that hash has no fixed point.

        What covers the manifest instead is the byte gate over the
        committed file — the same gate that covers everything it lists.
        """
        assert f"{DOCS_ROOT}/{DOCS_MANIFEST_OUTPUT}" not in {
            item.path_or_uri for item in manifest.artifacts
        }

    def test_it_is_sorted(self, manifest: DocsManifest) -> None:
        paths = [item.path_or_uri for item in manifest.artifacts]
        assert paths == sorted(paths)

    def test_every_content_hash_is_the_rendered_bytes(
        self, composed: Build, manifest: DocsManifest
    ) -> None:
        by_path = {
            f"{DOCS_ROOT}/{item.relative}": item.content for item in composed.artifacts
        }
        for item in manifest.artifacts:
            assert item.content_hash == content_hash(by_path[item.path_or_uri])

    def test_every_row_carries_this_builds_identity(
        self, composed: Build, manifest: DocsManifest
    ) -> None:
        for item in manifest.artifacts:
            assert item.release_version == manifest.product_version
            assert item.source_snapshot == composed.bundle.stamp.snapshot_hash
            assert item.build_channel == manifest.build_channel

    def test_a_generated_page_names_the_catalog_row_it_renders(
        self, manifest: DocsManifest
    ) -> None:
        """Architecture §6.7's ``document --generated_as--> artifact`` edge."""
        rows = {item.path_or_uri: item.source_document for item in manifest.artifacts}
        assert rows[f"{DOCS_ROOT}/reference/cli.md"].startswith("doc:")
        assert rows[f"{DOCS_ROOT}/README.md"].startswith("doc:")

    def test_a_machine_artifact_names_no_document_and_says_why(
        self, manifest: DocsManifest
    ) -> None:
        """The catalog's corpus is tracked Markdown; ``_generated/`` holds none.

        Empty is the right answer rather than a gap — ADR-012 §2.3 rule B-2
        keeps reader-facing pages out of that directory entirely.
        """
        rows = {item.path_or_uri: item.source_document for item in manifest.artifacts}
        assert rows[f"{DOCS_ROOT}/_generated/inventory-concepts.json"] == ""
        assert rows[f"{DOCS_ROOT}/_generated/s0ma-docs-model.json"] == ""

    def test_the_formats_are_the_architectures_words(
        self, manifest: DocsManifest
    ) -> None:
        assert {item.format for item in manifest.artifacts} == {
            "markdown",
            "json",
            "package_data",
            "media_manifest",
        }

    def test_the_teaching_slice_is_package_data_because_that_is_what_it_is_for(
        self, manifest: DocsManifest
    ) -> None:
        """A format word says what an artifact is for, not what it parses as."""
        rows = {item.path_or_uri: item.format for item in manifest.artifacts}
        assert rows[f"{DOCS_ROOT}/_generated/core-teaching-slice.json"] == "package_data"
        assert rows[f"{DOCS_ROOT}/_generated/inventory-concepts.json"] == "json"

    def test_an_output_whose_format_nothing_names_is_refused(self) -> None:
        with pytest.raises(DocsManifestError, match="no format"):
            artifact_format("reference/cli.rst")

    def test_the_manifest_is_a_declared_output(self, composed: Build) -> None:
        """Declared, so ``write`` writes it and ``check`` compares it."""
        assert DOCS_MANIFEST_OUTPUT in STATIC_OUTPUTS
        assert DOCS_MANIFEST_OUTPUT in generated_outputs(composed.bundle)
        assert len(generated_outputs(composed.bundle)) == len(composed.artifacts)


# ---------------------------------------------------------------------------
# Determinism (SDA-INV-8, and the initiative's acceptance criterion)
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Two builds of one tree, byte for byte."""

    def test_two_builds_write_one_manifest(self, composed: Build) -> None:
        again = build(REPO_ROOT, head_tag=claimed_head_tag())
        assert (
            again.artifact(DOCS_MANIFEST_OUTPUT).content
            == composed.artifact(DOCS_MANIFEST_OUTPUT).content
        )

    def test_rebuilding_the_manifest_from_one_build_is_stable(
        self, composed: Build
    ) -> None:
        """The renderer itself, called twice over one composition."""
        packages = [(item.distribution, item.version) for item in package_facts(REPO_ROOT)]
        artifacts = [
            (item.relative, item.content)
            for item in composed.artifacts
            if item.relative != DOCS_MANIFEST_OUTPUT
        ]
        first = render_manifest(
            manifest_of(
                composed.bundle,
                results=(),
                packages=packages,
                artifacts=artifacts,
                docs_root=DOCS_ROOT,
            )
        )
        second = render_manifest(
            manifest_of(
                composed.bundle,
                results=(),
                packages=list(reversed(packages)),
                artifacts=list(reversed(artifacts)),
                docs_root=DOCS_ROOT,
            )
        )
        assert first == second

    def test_nothing_in_it_reads_as_a_moment(self, composed: Build) -> None:
        """Architecture §13.1: publication time is release infrastructure's.

        The digests are checked for too, because a sixteen-hex digest can
        contain ten digits and this pattern must not be satisfied by one.
        """
        text = composed.artifact(DOCS_MANIFEST_OUTPUT).content
        assert _A_TIME.search(text) is None, _A_TIME.search(text)

    def test_no_machine_path_reaches_it(self, composed: Build) -> None:
        text = composed.artifact(DOCS_MANIFEST_OUTPUT).content
        assert _POSIX_PATH.search(text) is None
        assert str(REPO_ROOT) not in text

    def test_the_module_reaches_for_no_clock(self) -> None:
        """Read from the source, because a rule nothing enforces is a hope.

        The imports are read as syntax rather than grepped as text: the
        module's own docstring explains at length why it does not shell out
        to git, and a grep for the word would find the explanation.
        """
        import ast

        from s0ma_dsl.docs_model import manifest as module

        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.partition(".")[0])
        assert imported & {"time", "datetime", "os", "subprocess", "random", "socket"} == (
            set()
        ), sorted(imported)

    @requires_checkout
    def test_the_committed_file_is_what_this_build_renders(
        self, composed: Build
    ) -> None:
        committed = (DOCS / "_generated" / "docs-manifest.json").read_text(
            encoding="utf-8"
        )
        assert committed == composed.artifact(DOCS_MANIFEST_OUTPUT).content


# ---------------------------------------------------------------------------
# The channel rule (architecture §13.2)
# ---------------------------------------------------------------------------


class TestTheChannelRule:
    """Derived from a tag, never hand-set, and provable without one."""

    def test_a_tag_that_names_this_version_is_a_release_build(self) -> None:
        assert channel_of(product_version="0.18.1", head_tag="v0.18.1") == RELEASE_CHANNEL
        assert version_tag("0.18.1") == "v0.18.1"

    def test_no_tag_is_a_preview_build(self) -> None:
        assert channel_of(product_version="0.18.1") == PREVIEW_CHANNEL
        assert channel_of(product_version="0.18.1", head_tag="") == PREVIEW_CHANNEL

    def test_a_tag_for_another_version_is_not_a_release_of_this_one(self) -> None:
        """A tree standing on v0.17.0 with 0.18.1 in its manifests."""
        assert channel_of(product_version="0.18.1", head_tag="v0.17.0") == PREVIEW_CHANNEL

    def test_a_tag_that_is_not_a_version_tag_at_all(self) -> None:
        assert channel_of(product_version="0.18.1", head_tag="0.18.1") == PREVIEW_CHANNEL
        assert channel_of(product_version="0.18.1", head_tag="release-0.18.1") == (
            PREVIEW_CHANNEL
        )

    def test_historical_is_declared_and_never_derived(self) -> None:
        """No property of a tree says a snapshot is being kept as history."""
        assert HISTORICAL_CHANNEL not in {
            channel_of(product_version="0.18.1"),
            channel_of(product_version="0.18.1", head_tag="v0.18.1"),
        }

    @preview_tree_only
    def test_this_repository_builds_preview_documentation(
        self, manifest: DocsManifest, composed: Build
    ) -> None:
        """Stated as a fact of today rather than assumed: the tags are local-only.

        When a release build is first cut this becomes the test that says
        so, which is the point of writing it down.
        """
        assert manifest.build_channel == PREVIEW_CHANNEL
        assert composed.bundle.stamp.build_channel == PREVIEW_CHANNEL

    def test_the_manifest_and_the_stamp_cannot_disagree(
        self, composed: Build, manifest: DocsManifest
    ) -> None:
        assert manifest.build_channel == composed.bundle.stamp.build_channel


# ---------------------------------------------------------------------------
# The visible label
# ---------------------------------------------------------------------------


class TestThePreviewIsVisible:
    """Architecture §13.2: preview documentation is visibly labelled."""

    @preview_tree_only
    def test_every_rendered_identity_line_says_which_channel(
        self, composed: Build
    ) -> None:
        """Every page that carries an identity block, not most of them.

        The count is derived rather than written: the learning collection
        is the output family whose pages carry the block, so the number of
        labelled lines is the size of that collection — and if a page ever
        renders one without the label, the equality is what says so.
        """
        from s0ma_dsl.docs_model.learn_pages import learn_outputs

        expected = f"- Release: `{composed.bundle.stamp.version_line()}`"
        found = 0
        for item in composed.artifacts:
            for line in item.content.splitlines():
                if line.startswith("- Release: "):
                    assert line == expected, f"{item.relative}: {line}"
                    found += 1
        assert found == len(learn_outputs(composed.bundle))
        assert "(preview)" in expected

    @preview_tree_only
    def test_the_collection_pages_carry_it_too(self, composed: Build) -> None:
        """The glossary and the anatomy page render outside ``facts_of``.

        They were the only two rendered pages that could have carried the
        version unlabelled, which is why they get their own proof.
        """
        for relative in ("learn/glossary.md", "learn/anatomy-of-a-s0ma-file.md"):
            assert "(preview)" in composed.artifact(relative).content

    def test_the_stamp_writes_the_bare_version_for_a_release(self) -> None:
        from s0ma_dsl.docs_model.records import BuildStamp

        released = BuildStamp(
            schema=SCHEMA,
            release_version="0.18.1",
            snapshot_hash="sha256:0000000000000000",
            build_channel=RELEASE_CHANNEL,
        )
        assert released.version_line() == "0.18.1"

    def test_the_default_channel_is_the_cautious_one(self) -> None:
        """A build nobody told is a release is not one."""
        from s0ma_dsl.docs_model.records import BuildStamp

        assert (
            BuildStamp(
                schema=SCHEMA, release_version="0.18.1", snapshot_hash=""
            ).build_channel
            == PREVIEW_CHANNEL
        )


# ---------------------------------------------------------------------------
# The gate over the real build
# ---------------------------------------------------------------------------


class TestTheGateOverTheRealBuild:
    """The positive control the negative battery's fixtures are measured against."""

    def test_the_real_manifest_reports_nothing(
        self, composed: Build, manifest: DocsManifest
    ) -> None:
        assert check_manifest(manifest, stamp=composed.bundle.stamp) == []

    def test_the_build_runs_the_gate(self, composed: Build) -> None:
        """Not just reachable: actually wired into ``build``."""
        assert composed.ok, [finding.rendered() for finding in composed.findings]
        assert "DOC_VERSION_MISMATCH" not in {
            finding.code for finding in composed.findings
        }

    def test_a_build_that_cannot_name_a_product_version_refuses(self) -> None:
        """Rather than guessing one. Every artifact would then claim it."""
        with pytest.raises(DocsManifestError, match=LOCKSTEP_ANCHOR):
            product_version_of(())

    def test_the_stamped_version_and_the_product_version_agree_today(
        self, manifest: DocsManifest
    ) -> None:
        """The toolchain that composed and the product it describes, in lockstep."""
        assert release_version() == manifest.product_version
