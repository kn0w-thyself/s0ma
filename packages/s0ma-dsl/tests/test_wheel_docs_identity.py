"""The exact-wheel documentation identity check, and proof it can fail.

Milestone H2 of the docs-function plan (internal) §13. ``scripts/wheel_smoke.py``
opens the built wheels and requires four things of what they carry:

1. the ``s0ma-core`` wheel's embedded teaching slice was rendered from the
   snapshot the release manifest names;
2. the ``s0ma-mcp`` wheel's ``_docs`` payload is the cataloged sources,
   byte for byte;
3. the ``s0ma-dsl`` wheel's packaged snapshot — what ``s0ma docs`` reads
   with no checkout — is that same composed snapshot, and byte-identical to
   the ``s0ma-mcp`` wheel's copy of it;
4. the version those payloads render is the version the wheels are.

The gate itself runs those assertions against **real wheels**, which is the
only way to know what a wheel contains — and that is also why the positive
case is not re-proved here: ``scripts/check.py`` builds four wheels and runs
the check on every gate run, so a green gate *is* the positive control.

What a gate cannot prove about itself is that it can fail. Every test below
that matters is a negative one, and each drives the real assertion code over
payloads doctored one field at a time — a slice from another build, a mirror
whose bytes moved, a manifest assembled from two composes, a wheel at the
wrong version. Building a deliberately-wrong wheel for each would cost a
minute an assertion and prove nothing the bytes do not already say, so the
payloads are read out of the committed mirrors instead: the same files the
wheels ship, which the gate's own ``_docs``/slice comparisons keep equal.

The release case is **simulated**, never cut. This repository has no tags and
this suite creates none: ``channel_of`` takes the tag as a value, so a
release-channel manifest is a fixture and the tag is a string.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from dataclasses import replace
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.docs_model.manifest import DocsManifest, manifest_from_json
from s0ma_dsl.docs_model.records import PREVIEW_CHANNEL, RELEASE_CHANNEL
from s0ma_dsl.docs_model.serialize import content_hash
from tests._committed_claim import preview_tree_only

if TYPE_CHECKING:
    from types import ModuleType

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]

WHEEL_SMOKE = REPO_ROOT / "scripts" / "wheel_smoke.py"
MANIFEST = REPO_ROOT / "docs" / "_generated" / "docs-manifest.json"
CORE_SLICE = REPO_ROOT / "packages/s0ma-core/src/s0ma/_teaching/slice.json"
MCP_DOCS = REPO_ROOT / "packages/s0ma-mcp/src/s0ma_mcp/_docs"
DSL_SNAPSHOT = (
    REPO_ROOT / "packages/s0ma-dsl/src/s0ma_dsl/_docs_snapshot/s0ma-docs-model.json"
)
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

#: The workflow that gates `main` and every pull request. It states no tag,
#: deliberately — see :class:`TestTheReleaseCheckJobStatesTheTag`.
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: How a tag push states the release tag to the standing gate (H2c). One
#: spelling, shared with ``scripts/check_docs_application.py``.
HEAD_TAG_ENV = "S0MA_HEAD_TAG"

#: The four lockstep distributions (PRD INV-4).
PACKAGES = ("s0ma-core", "s0ma-dsl", "s0ma-mcp", "s0ma-studi0")

requires_checkout = pytest.mark.skipif(
    not MANIFEST.is_file(), reason="not a repository checkout: no release manifest"
)


@cache
def _smoke() -> ModuleType:
    """Import ``scripts/wheel_smoke.py`` for unit-level proofs.

    Registered in ``sys.modules`` before execution for the reason
    ``test_check_links_script.py`` gives: ``@dataclass`` resolves a class's
    module through it, and a file-path module loaded without that
    registration fails inside the decorator.
    """
    spec = importlib.util.spec_from_file_location("s0ma_wheel_smoke", WHEEL_SMOKE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifest() -> DocsManifest:
    return manifest_from_json(MANIFEST.read_text(encoding="utf-8"))


def _the_other_channel() -> str:
    """The channel the committed manifest does not claim: release, on a preview tree."""
    if _manifest().build_channel == PREVIEW_CHANNEL:
        return RELEASE_CHANNEL
    return PREVIEW_CHANNEL


def _payloads(**overrides: object) -> object:
    """The payloads a wheel built from this tree would carry.

    Read out of the committed mirrors, which is exactly what the wheels
    ship: ``packages/s0ma-core/pyproject.toml`` packages the slice and
    ``s0ma_mcp/_docs`` is package data, and the gate's own comparisons hold
    all of them equal to these files.
    """
    smoke = _smoke()
    version = _manifest().product_version
    defaults: dict[str, object] = {
        "wheel_versions": dict.fromkeys(PACKAGES, version),
        "core_slice": CORE_SLICE.read_bytes(),
        "mcp_docs": {
            path.name: path.read_bytes()
            for path in sorted(MCP_DOCS.iterdir())
            if path.is_file()
        },
        "dsl_snapshot": DSL_SNAPSHOT.read_bytes(),
    }
    defaults.update(overrides)
    return smoke.DocsPayloads(**defaults)  # type: ignore[no-any-return]


def _rewrite_slice(**source_fields: str) -> bytes:
    """The committed slice with its ``source`` block edited, as bytes."""
    document = json.loads(CORE_SLICE.read_text(encoding="utf-8"))
    document["source"].update(source_fields)
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _bind(manifest: DocsManifest, path_or_uri: str, payload: bytes) -> DocsManifest:
    """``manifest`` with one artifact's ``content_hash`` set to ``payload``'s.

    Used to isolate an assertion. The content-hash binding is checked
    first, so a payload doctored in any way fails there before the
    field-level comparison it was written to exercise is ever reached;
    re-binding the hash lets the later assertion be the one under test.
    """
    updated = tuple(
        replace(record, content_hash=content_hash(payload.decode("utf-8")))
        if record.path_or_uri == path_or_uri
        else record
        for record in manifest.artifacts
    )
    return replace(manifest, artifacts=updated)


def _check(payloads: object, manifest: DocsManifest, **kwargs: str) -> list[str]:
    return _smoke().check_docs_identity(payloads, manifest, **kwargs)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# The check agrees with the tree it is run in
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheCommittedTreeAgrees:
    """The mirrors, the manifest and the versions are one build.

    Not a substitute for the gate's own run over real wheels — it is the
    same comparison one layer in, and it is what tells a developer *which*
    artifact drifted before a four-wheel build has to say so.
    """

    def test_the_four_assertions_pass_and_each_reports(self) -> None:
        report = _check(_payloads(), _manifest())
        assert len(report) == 4, report
        assert all(line.startswith("docs identity: ") for line in report), report

    def test_the_report_names_what_it_bound(self) -> None:
        """A passing check says what it compared, not just that it passed."""
        slice_line, docs_line, dsl_line, version_line = _check(
            _payloads(), _manifest()
        )
        assert "core-teaching-slice.json" in slice_line
        assert _manifest().snapshot_hash in slice_line
        assert "mirrors" in docs_line and "source_hashes" in docs_line
        assert "_docs_snapshot/s0ma-docs-model.json" in dsl_line
        assert f"{len(PACKAGES)} wheels at {_manifest().product_version}" in version_line

    def test_the_slice_carries_the_channel(self) -> None:
        """H2's additive field, on the file the wheel really ships."""
        source = json.loads(CORE_SLICE.read_text(encoding="utf-8"))["source"]
        manifest = _manifest()
        assert source["build_channel"] == manifest.build_channel
        assert source["snapshot_hash"] == manifest.snapshot_hash
        assert source["release_version"] == manifest.product_version

    @preview_tree_only
    def test_this_tree_is_a_preview_build(self) -> None:
        """Recorded rather than assumed: every fixture below leans on it."""
        assert _manifest().build_channel == PREVIEW_CHANNEL


# ---------------------------------------------------------------------------
# Assertion 1 — the embedded slice
# ---------------------------------------------------------------------------


@requires_checkout
class TestAMismatchedSliceFails:
    """The mission's negative: a slice from another snapshot is refused."""

    def test_a_slice_naming_another_snapshot_is_refused(self) -> None:
        """The assertion in isolation, with the content binding re-bound.

        This is the failure H2 exists for: the wheels were built before the
        mirror was refreshed, so the wheel teaches from the *previous*
        release's snapshot while every other gate stays green.
        """
        doctored = _rewrite_slice(snapshot_hash="sha256:0000000000000000")
        manifest = _bind(
            _manifest(), "docs/_generated/core-teaching-slice.json", doctored
        )
        with pytest.raises(AssertionError) as caught:
            _check(_payloads(core_slice=doctored), manifest)
        message = str(caught.value)
        assert "sha256:0000000000000000" in message
        assert manifest.snapshot_hash in message
        assert "snapshot" in message

    def test_a_slice_that_is_not_the_rendered_artifact_is_refused(self) -> None:
        """One byte is enough: the wheel must carry the file that was rendered."""
        doctored = CORE_SLICE.read_bytes() + b"\n"
        with pytest.raises(AssertionError, match="content_hash"):
            _check(_payloads(core_slice=doctored), _manifest())

    def test_a_slice_from_another_release_is_refused(self) -> None:
        doctored = _rewrite_slice(release_version="0.17.0")
        manifest = _bind(
            _manifest(), "docs/_generated/core-teaching-slice.json", doctored
        )
        with pytest.raises(AssertionError, match="release_version"):
            _check(_payloads(core_slice=doctored), manifest)

    def test_a_slice_from_another_channel_is_refused(self) -> None:
        """A preview manifest may not ship a slice claiming to be released.

        Nor a release manifest one claiming to be a preview: the slice is
        stamped with the channel the committed tree does not claim, which on
        a preview tree is the release channel, as it always was.
        """
        doctored = _rewrite_slice(build_channel=_the_other_channel())
        manifest = _bind(
            _manifest(), "docs/_generated/core-teaching-slice.json", doctored
        )
        with pytest.raises(AssertionError, match="build_channel"):
            _check(_payloads(core_slice=doctored), manifest)


# ---------------------------------------------------------------------------
# Assertion 2b — the snapshot the command line reads
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheCommandLineSnapshotMustBeThisBuilds:
    """The dsl wheel's copy, bound twice: to the build, and to the mcp copy.

    The assertion this class proves can fail is the one whose *absence*
    shipped a broken product. The snapshot went into the ``s0ma-mcp`` wheel
    for the MCP resources and into ``s0ma-core`` as a teaching slice; the
    ``s0ma-dsl`` wheel got nothing, so every ``s0ma docs`` command from an
    installed toolchain answered "no documentation snapshot was found" for
    four releases, with every gate in this repository green — because every
    gate ran inside a checkout, which is the one place the gap did not
    show.
    """

    def test_a_copy_the_other_wheel_does_not_carry_is_refused(self) -> None:
        """The half-run loop: the mcp mirror copied, the dsl one not.

        One byte is enough, and the message has to name the loop rather
        than the digest — a person meeting this has a `cp` to run, not a
        mystery to solve.
        """
        with pytest.raises(AssertionError, match="their bytes differ"):
            _check(_payloads(dsl_snapshot=DSL_SNAPSHOT.read_bytes() + b"\n"), _manifest())

    def test_a_copy_that_is_not_this_builds_snapshot_is_refused(self) -> None:
        """The second binding, driven on its own.

        End to end it is unreachable, and deliberately so: the mcp check
        runs first and already holds *its* copy of this artifact to the
        manifest, so two copies that agree with each other and not with the
        build are caught there. The binding is kept because it binds this
        copy to the manifest **directly** — a claim that should not depend
        on another wheel's check continuing to exist — and it is driven
        here, at the function, so it is still a proven-able assertion
        rather than a line nobody has ever seen fail.
        """
        doctored = DSL_SNAPSHOT.read_bytes() + b"\n"
        payloads = _payloads(
            dsl_snapshot=doctored,
            mcp_docs={**_payloads().mcp_docs, "s0ma-docs-model.json": doctored},  # type: ignore[attr-defined]
        )
        with pytest.raises(AssertionError, match="not the snapshot this build composed"):
            _smoke()._check_dsl_snapshot(payloads, _manifest())


# ---------------------------------------------------------------------------
# Assertion 2 — the served documents
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheServedDocumentsMustBeTheCatalogedSources:
    """``_docs`` is the catalog's bytes, and the set is not hand-written."""

    def test_a_mirror_whose_bytes_moved_is_refused(self) -> None:
        docs = dict(_payloads().mcp_docs)  # type: ignore[attr-defined]
        docs["getting-started.md"] = docs["getting-started.md"] + b"\ndrift\n"
        with pytest.raises(AssertionError, match="differs from its cataloged source"):
            _check(_payloads(mcp_docs=docs), _manifest())

    def test_a_mirror_bound_by_the_manifest_is_bound_by_its_full_digest(self) -> None:
        """The strong binding, shown to be load-bearing rather than decorative.

        ``CHANGELOG.md`` is one of the sources the build actually reads, so
        the manifest carries its sha256. Moving that digest — the manifest
        describing a different state of the file than the wheel ships — has
        to fail even though the wheel and the checkout still agree.
        """
        manifest = _manifest()
        moved = tuple(
            replace(record, sha256="0" * 64)
            if record.source == "CHANGELOG.md"
            else record
            for record in manifest.source_hashes
        )
        assert moved != manifest.source_hashes, "CHANGELOG.md is no longer a read source"
        with pytest.raises(AssertionError, match="source_hashes entry"):
            _check(_payloads(), replace(manifest, source_hashes=moved))

    def test_a_missing_document_is_refused(self) -> None:
        docs = dict(_payloads().mcp_docs)  # type: ignore[attr-defined]
        del docs["survival_card.md"]
        with pytest.raises(AssertionError, match="missing="):
            _check(_payloads(mcp_docs=docs), _manifest())

    def test_a_document_nobody_declared_is_refused(self) -> None:
        """A file riding along in the wheel is a served document nothing gates."""
        docs = dict(_payloads().mcp_docs)  # type: ignore[attr-defined]
        docs["stowaway.md"] = b"# not declared anywhere\n"
        with pytest.raises(AssertionError, match="unexpected="):
            _check(_payloads(mcp_docs=docs), _manifest())

    def test_a_snapshot_that_is_not_the_composed_one_is_refused(self) -> None:
        docs = dict(_payloads().mcp_docs)  # type: ignore[attr-defined]
        docs["s0ma-docs-model.json"] = docs["s0ma-docs-model.json"] + b"\n"
        with pytest.raises(AssertionError, match="not the snapshot this build composed"):
            _check(_payloads(mcp_docs=docs), _manifest())

    def test_every_mirror_is_bound_by_something_named(self) -> None:
        """The two bindings between them cover the whole payload.

        Derived, not counted: the report states how many mirrors each
        binding took, and the two have to add up to the declared set. A
        tenth document that no source hash and no catalog row reached would
        make the check say so instead of passing over it.
        """
        from s0ma_mcp.resources import GUIDE_DOCS

        docs_line = _check(_payloads(), _manifest())[1]
        assert f"{len(GUIDE_DOCS)} mirrors" in docs_line
        declared, strong, weak = (
            int(found) for found in re.findall(r"\b(\d+)\b", docs_line)[:3]
        )
        assert declared == len(GUIDE_DOCS), docs_line
        assert strong + weak == declared, docs_line


# ---------------------------------------------------------------------------
# Assertion 3 — the version the wheels are
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheRenderedVersionMustBeTheWheelsVersion:
    """What the documentation says a reader has installed is what they have."""

    def test_a_wheel_at_another_version_is_refused(self) -> None:
        versions = dict.fromkeys(PACKAGES, _manifest().product_version)
        versions["s0ma-mcp"] = "0.17.0"
        with pytest.raises(AssertionError, match="product_version"):
            _check(_payloads(wheel_versions=versions), _manifest())

    def test_a_manifest_assembled_from_two_composes_is_refused(self) -> None:
        """DOC_VERSION_MISMATCH: an artifact whose row disagrees with the head."""
        manifest = _manifest()
        mixed = (replace(manifest.artifacts[0], release_version="0.17.0"),) + tuple(
            manifest.artifacts[1:]
        )
        with pytest.raises(AssertionError, match="DOC_VERSION_MISMATCH"):
            _check(_payloads(), replace(manifest, artifacts=mixed))

    def test_a_preview_artifact_in_a_release_manifest_is_refused(self) -> None:
        """One artifact row on the channel the committed manifest does not claim."""
        manifest = _manifest()
        mixed = (replace(manifest.artifacts[0], build_channel=_the_other_channel()),) + tuple(
            manifest.artifacts[1:]
        )
        with pytest.raises(AssertionError, match="DOC_VERSION_MISMATCH"):
            _check(_payloads(), replace(manifest, artifacts=mixed))

    def test_a_snapshot_stamped_for_another_build_is_refused(self) -> None:
        """The served snapshot's own stamp, not just the manifest's copy of it."""
        docs = dict(_payloads().mcp_docs)  # type: ignore[attr-defined]
        document = json.loads(docs["s0ma-docs-model.json"])
        document["stamp"]["release_version"] = "0.17.0"
        payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
        docs["s0ma-docs-model.json"] = payload
        manifest = _bind(_manifest(), "docs/_generated/s0ma-docs-model.json", payload)
        with pytest.raises(AssertionError, match="tell its reader the wrong build"):
            _check(_payloads(mcp_docs=docs, dsl_snapshot=payload), manifest)

    @preview_tree_only
    def test_the_preview_label_is_part_of_the_served_identity(self) -> None:
        """The whole point of the channel: the label is checked, not just carried."""
        version = _manifest().product_version
        report = _check(_payloads(), _manifest())
        assert f"'{version} ({PREVIEW_CHANNEL})'" in report[-1], report


# ---------------------------------------------------------------------------
# The release case, simulated
# ---------------------------------------------------------------------------


def _released(manifest: DocsManifest) -> tuple[DocsManifest, object]:
    """A release-channel manifest and the payloads that would match it.

    Everything the release compose would write, written here instead: the
    manifest and every artifact row on the release channel, the slice and
    the served snapshot stamped the same, and the artifact hashes re-bound
    to the payloads that result. No tag is created and none is consulted —
    ``channel_of`` takes the tag as a value, which is the property that
    makes this fixture possible at all.
    """
    released = replace(
        manifest,
        build_channel=RELEASE_CHANNEL,
        artifacts=tuple(
            replace(record, build_channel=RELEASE_CHANNEL)
            for record in manifest.artifacts
        ),
    )
    slice_bytes = _rewrite_slice(build_channel=RELEASE_CHANNEL)
    released = _bind(
        released, "docs/_generated/core-teaching-slice.json", slice_bytes
    )

    docs = {
        path.name: path.read_bytes() for path in sorted(MCP_DOCS.iterdir()) if path.is_file()
    }
    document = copy.deepcopy(json.loads(docs["s0ma-docs-model.json"]))
    document["stamp"]["build_channel"] = RELEASE_CHANNEL
    snapshot_bytes = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    docs["s0ma-docs-model.json"] = snapshot_bytes
    released = _bind(released, "docs/_generated/s0ma-docs-model.json", snapshot_bytes)
    # Both mirrors of that one artifact, refreshed together — which is what
    # the release procedure's step 4 does, and what this fixture simulates.
    return released, _payloads(
        core_slice=slice_bytes, mcp_docs=docs, dsl_snapshot=snapshot_bytes
    )


@requires_checkout
class TestTheReleaseCaseIsSimulated:
    """What a real release has to look like, proved without cutting one."""

    def test_a_release_build_serves_the_bare_version(self) -> None:
        manifest, payloads = _released(_manifest())
        report = _check(payloads, manifest)
        assert f"'{manifest.product_version}'" in report[-1], report
        assert PREVIEW_CHANNEL not in report[-1]

    def test_the_tag_the_release_is_cut_under_agrees(self) -> None:
        manifest, payloads = _released(_manifest())
        report = _check(
            payloads, manifest, head_tag=f"v{manifest.product_version}"
        )
        assert report[-1].endswith("manifest agrees"), report

    @preview_tree_only
    def test_a_tag_naming_another_version_is_not_a_release_of_this_one(self) -> None:
        """A tree standing on an older tag with this version in its manifests."""
        manifest = _manifest()
        report = _check(_payloads(), manifest, head_tag="v0.1.0")
        assert f"implies {PREVIEW_CHANNEL}" in report[-1], report

    @preview_tree_only
    def test_a_tagged_commit_carrying_preview_documentation_is_refused(self) -> None:
        """The condition the workflow's activation waits on.

        Composing at the release commit and then tagging it produces exactly
        this: wheels at the tag, documentation composed as preview, and every
        served identity line telling the reader the release they installed is
        not a release. The check refuses it and says which step is missing.

        Since H2b that step is a command rather than a description, so the
        remediation is asserted to *be* the command, with the stated tag
        already substituted in. That is the difference between a refusal
        somebody has to interpret and one they can run.
        """
        manifest = _manifest()
        tag = f"v{manifest.product_version}"
        with pytest.raises(AssertionError, match="Recompose with the tag stated"):
            _check(_payloads(), manifest, head_tag=tag)
        try:
            _check(_payloads(), manifest, head_tag=tag)
        except AssertionError as refusal:
            assert f"docs compose --output-dir docs --head-tag {tag}" in str(refusal)
        else:  # pragma: no cover - the raise above already failed the test
            pytest.fail("a preview-composed build at a tag must be refused")

    def test_the_verification_never_looks_a_tag_up_from_a_fixture(self) -> None:
        """The tag arrives as a value, in the gate as in ``channel_of``.

        A verification that shelled out to ``git`` for its own channel could
        not run inside a wheel, could not be tested without cutting a tag,
        and would decide what kind of build it was from the state of a
        working tree rather than from what it was told. This pins the
        property at the source rather than trusting the docstring.
        """
        source = WHEEL_SMOKE.read_text(encoding="utf-8")
        for forbidden in ("git describe", "git tag", "git rev-parse"):
            assert forbidden not in source, forbidden


# ---------------------------------------------------------------------------
# The workflow that runs it on a tag
# ---------------------------------------------------------------------------

#: The job that gates a tag on the check above, and the two things it must
#: stay: ahead of everything that publishes, and incapable of publishing.
GATE_JOB = "verify-docs-identity"

#: The job that first puts something outside the runner. Everything the
#: release does that a tester or the public can see is downstream of it.
FIRST_PUBLISHING_JOB = "release"


def _workflow_text() -> str:
    return RELEASE_WORKFLOW.read_text(encoding="utf-8")


def _gating_step(workflow: Path) -> dict[str, Any]:
    """The one step of *workflow*'s ``check`` job that runs the standing gate.

    Found by what it runs rather than by what it is called, so renaming
    the step cannot quietly move the environment off it.
    """
    yaml = pytest.importorskip("yaml", reason="PyYAML not installed")
    document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    steps = document["jobs"]["check"]["steps"]
    gating = [step for step in steps if "scripts/check.py" in (step.get("run") or "")]
    assert len(gating) == 1, steps
    return gating[0]


class TestTheReleaseWorkflowGate:
    """The drafted release job: where it sits, and what it may not do.

    Merging this workflow is not activating it — the job runs on every tag
    but its verification steps wait on a repository variable the owner
    sets, the same shape the R2 and served-verification gates already use.
    What these tests hold is the part that is *not* a switch: the job
    exists, it is upstream of everything that publishes, and it has no way
    to publish anything itself.

    The parse skips where PyYAML is unavailable (it is not a declared
    dependency of this package), so the structural claims are also made at
    the text level, where they need nothing at all. A skipped parse plus a
    passing text check is a report; a skipped parse alone is silence.
    """

    def test_the_workflow_parses(self) -> None:
        yaml = pytest.importorskip("yaml", reason="PyYAML not installed")
        document = yaml.safe_load(_workflow_text())
        assert isinstance(document, dict) and document["jobs"], document

    def test_the_gate_runs_before_anything_is_published(self) -> None:
        yaml = pytest.importorskip("yaml", reason="PyYAML not installed")
        jobs = yaml.safe_load(_workflow_text())["jobs"]
        assert GATE_JOB in jobs, sorted(jobs)
        needs = jobs[FIRST_PUBLISHING_JOB]["needs"]
        assert GATE_JOB in ([needs] if isinstance(needs, str) else needs), needs
        # And the serving jobs are downstream of that one, so the ordering
        # holds transitively rather than by a rule somebody remembers.
        assert jobs["mirror-r2"]["needs"] == FIRST_PUBLISHING_JOB
        assert jobs["verify-served"]["needs"] == "mirror-r2"

    def test_the_gate_job_is_never_skipped(self) -> None:
        """A job skipped by ``if:`` skips its dependents — including the release.

        This is why the switch is on the *steps* and not on the job, and it
        is the one mistake that would turn "the gate is not armed" into "the
        release does not happen".
        """
        yaml = pytest.importorskip("yaml", reason="PyYAML not installed")
        job = yaml.safe_load(_workflow_text())["jobs"][GATE_JOB]
        assert "if" not in job, job.get("if")
        assert job["needs"] == "check"

    def test_the_gate_cannot_publish_anything(self) -> None:
        """Verification only: no write permission, no secrets, no upload."""
        yaml = pytest.importorskip("yaml", reason="PyYAML not installed")
        job = yaml.safe_load(_workflow_text())["jobs"][GATE_JOB]
        assert "permissions" not in job, job.get("permissions")
        rendered = "\n".join(
            f"{step.get('name', '')}\n{step.get('run', '')}\n{step.get('uses', '')}"
            for step in job["steps"]
        )
        assert "secrets." not in rendered, rendered
        for forbidden in (
            "gh release",
            "mirror_to_r2",
            "verify_served",
            "wrangler",
            "uv publish",
            "upload",
        ):
            assert forbidden not in rendered, forbidden

    def test_the_gate_is_named_in_the_workflow_header(self) -> None:
        """The header lists the jobs in order; a fifth cannot arrive unlisted."""
        header = _workflow_text().partition("name: Release")[0]
        assert GATE_JOB in header, header

    def test_the_text_says_the_same_without_a_parser(self) -> None:
        """The companion that runs where PyYAML does not."""
        text = _workflow_text()
        assert f"\n  {GATE_JOB}:\n" in text
        assert f"needs: [check, {GATE_JOB}]" in text
        assert "--docs-identity-only" in text
        assert '--head-tag "${GITHUB_REF_NAME}"' in text
        assert "S0MA_DOCS_IDENTITY_GATE" in text


class TestTheReleaseCheckJobStatesTheTag:
    """H2c: the tag reaches the standing gate, and only where there is one.

    ``scripts/check.py``'s ``docs-application`` stage composes the tree it
    gates, so it follows the channel the committed manifest claims: a
    release-composed tree needs the tag stated, and is refused without it.
    A tag push is one of the two places that states it (the other is the
    release cut, by hand — ``docs/RELEASING.md`` step 5).

    The counterpart claim is the one about ``ci.yml``, and it is a claim
    about an *absence*, which is why it is written down. Trees on ``main``
    and in pull requests claim ``preview`` and compose untagged; a
    variable exported there would be a way for release-labelled
    documentation to gate green on a branch, which is the property H2c
    exists to remove.
    """

    def test_the_workflow_only_ever_runs_on_a_tag(self) -> None:
        """Which is what makes a plain ``env:`` correct and a guard needless.

        If this workflow ever gained a branch or a manual trigger, the
        step's ``env:`` would state ``github.ref_name`` for a *branch* —
        a value no version's tag ever equals, so ``channel_of`` would call
        it a preview and the refusal would fire on a tree that claimed
        one. This test is the tripwire on that change.
        """
        yaml = pytest.importorskip("yaml", reason="PyYAML not installed")
        document = yaml.safe_load(_workflow_text())
        # PyYAML reads a bare `on:` key as the boolean True (the YAML 1.1
        # spelling), so both are accepted here rather than one guessed.
        triggers = document.get("on", document.get(True))
        assert set(triggers) == {"push"}, triggers
        assert triggers["push"] == {"tags": ["v*"]}, triggers["push"]

    def test_the_check_step_states_the_tag_being_released(self) -> None:
        step = _gating_step(RELEASE_WORKFLOW)
        assert step.get("env", {}).get(HEAD_TAG_ENV) == "${{ github.ref_name }}"

    def test_the_main_branch_workflow_states_no_tag(self) -> None:
        """The absence, asserted — not left to be noticed."""
        assert HEAD_TAG_ENV not in CI_WORKFLOW.read_text(encoding="utf-8")
        assert HEAD_TAG_ENV not in (_gating_step(CI_WORKFLOW).get("env") or {})

    def test_the_text_says_the_same_without_a_parser(self) -> None:
        text = _workflow_text()
        assert f"          {HEAD_TAG_ENV}: ${{{{ github.ref_name }}}}\n" in text
        assert HEAD_TAG_ENV not in CI_WORKFLOW.read_text(encoding="utf-8")
