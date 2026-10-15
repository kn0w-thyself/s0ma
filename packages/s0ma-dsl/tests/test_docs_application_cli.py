"""The documentation application, and the four claims C8 is worth having for.

Milestone C8 of the docs-function plan (internal) §8. Everything before
this milestone could compose documentation; this one says how this
repository's documentation *is* composed, and puts a write command and a
check command over that one definition. The claims:

* **the loop is byte-stable.** Write, check, write, check — from clean,
  twice — and the second write reproduces the first one's bytes. A build
  that is not reproducible cannot be gated, because every run would report
  drift against the last one;
* **check mode never writes.** Not the artifact, not a temporary copy, not
  a parent directory (SDA-INV-9). Proved twice over: with
  ``git status --porcelain`` around a run against the real tree, and by
  running check against an empty directory and asserting it stays empty;
* **drift is named, not merely detected.** A hand-edited artifact fails
  with the line that differs and both sides of it. "Something changed" is
  a report somebody has to redo by hand;
* **findings are collected.** A planted fault produces every finding the
  gates have, each located, rather than the first one.

Plus the project itself: ``docs/`` is a s0ma project (owner decision D-3),
so it must build and check clean like any other, and its committed
``_built/`` must be what its sources produce.

The write path is exercised into ``tmp_path`` throughout. ``--output-dir``
overrides where output lands and never where sources are read, so the
whole loop runs against the real checkout without the suite writing a byte
into it — which is also the property the tree-untouched proofs need.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.docs_model.application import (
    APPLICATION_FLOORS,
    ARTIFACT_FLOOR,
    DOC_GATE_VACUOUS,
    DOC_OUTPUT_DRIFT,
    DOCS_ROOT,
    PRODUCT_CONCEPTS,
    PRODUCT_DOMAIN,
    SNAPSHOT_OUTPUT,
    STATIC_OUTPUTS,
    Artifact,
    Build,
    build,
    check,
    generated_outputs,
    registry,
    release_version,
    write,
)
from s0ma_dsl.docs_model.providers import (
    Finding,
    ProviderRegistry,
    ProviderResult,
    SourcedRecord,
)
from s0ma_dsl.docs_model.records import ConceptRecord, Provenance
from s0ma_dsl.docs_model.resolve import CoveragePolicy
from s0ma_dsl.docs_model.serialize import deserialize_bundle
from tests._committed_claim import claimed_head_tag, preview_tree_only

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = REPO_ROOT / DOCS_ROOT
SNAPSHOT = DOCS / Path(SNAPSHOT_OUTPUT)
PYPROJECT = DOCS / "pyproject.toml"
APPLICATION_SOURCE = DOCS / "s0ma_src" / "application.s0ma"

#: The ten readings this repository's documentation is composed from
#: (ADR-012 §1). Written out here rather than derived from
#: :func:`registry`, so that a provider silently leaving the composition
#: is a failing test rather than a quietly smaller build.
#:
#: Five arrived with the C phase and describe what the product *says*;
#: five arrived with the D phase and describe what it *serves*. D5b wired
#: the second five, and this constant is where that shows up as a claim
#: somebody has to change on purpose.
EXPECTED_PROVIDERS = (
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


def _claimed_tag_argv() -> list[str]:
    """What a ``docs check`` of the real tree adds to compare as the tree claims.

    Nothing on a preview tree, where the command runs exactly as written;
    ``--head-tag`` and the release's own tag on the one commit a tag names.
    """
    tag = claimed_head_tag()
    return ["--head-tag", tag] if tag else []


@pytest.fixture
def porcelain() -> Iterator[str]:
    """The working tree's state, asserted unchanged when the test ends."""
    before = _porcelain()
    yield before
    assert _porcelain() == before, (
        "the working tree changed during a test that must not write to it"
    )


def _porcelain() -> str:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell, repo-local
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],  # noqa: S607
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


def _codes(findings: tuple[Finding, ...] | list[Finding]) -> list[str]:
    return [item.code for item in findings]


# ---------------------------------------------------------------------------
# The docs/ project (T1)
# ---------------------------------------------------------------------------


class TestTheApplicationProject:
    """``docs/`` is a s0ma project, so it answers to the toolchain like one."""

    @requires_checkout
    def test_the_project_checks_clean(self) -> None:
        """The invocation a contributor runs, with its real exit code."""
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-m", "s0ma_dsl.cli.main",
             "--project-root", DOCS_ROOT, "check", DOCS_ROOT],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    @requires_checkout
    def test_the_committed_build_is_what_the_sources_produce(self) -> None:
        """``build --check`` transpiles to a temp dir and compares bytes.

        The same gate the other three committed ``_built/`` trees are held
        to. It writes nothing: that is what ``--check`` means here.
        """
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-m", "s0ma_dsl.cli.main",
             "--project-root", DOCS_ROOT, "build", DOCS_ROOT, "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_pyproject_declares_what_adr_012_requires(self) -> None:
        import tomllib

        table = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["s0ma"]
        assert table["source_roots"] == ["s0ma_src"]
        assert table["build_dir"] == "_built"
        # ADR-012 §2.2: the loader refuses "." outright, and a project that
        # tried it would fail at load rather than here. Pinned so the
        # refusal is not rediscovered as a defect.
        assert table["build_dir"] != "."

    def test_the_declared_mode_is_recorded_rather_than_assumed(self) -> None:
        """Release, with the reason written where the key is.

        C8 shipped ``strict`` and recorded why — ADR-012 §1 asked for
        ``release`` from a spike fixture that had doc declarations to
        cover, and this project had none. F1 raised it, because the
        project now carries a ``doc-ref`` over its three PUBLIC nerves
        and the page it renders has a reader. The test still pins the
        value *and* the presence of the reason, because a mode changed
        without one is how a project loses a gate — and it names the
        gate the raise switched on, so a silent slide back to strict
        fails here rather than in a build nobody reads.
        """
        import tomllib

        text = PYPROJECT.read_text(encoding="utf-8")
        table = tomllib.loads(text)["tool"]["s0ma"]
        assert table["mode"] == "release"
        assert "MISSING_PUBLIC_DOC_REF" in text
        assert "docs-application" in text

    def test_the_project_is_not_a_workspace_member(self) -> None:
        """ADR-012 §1: the documentation project is not a distribution."""
        import tomllib

        root = tomllib.loads(
            (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        members = root["tool"]["uv"]["workspace"]["members"]
        assert DOCS_ROOT not in members
        assert all(not member.startswith(f"{DOCS_ROOT}/") for member in members)

    def test_the_application_names_its_own_places(self) -> None:
        """The ``covered_by`` of the four cells in ``application.s0ma``.

        The authored source and the module it describes agree about where
        the application lives and what it renders. Two names for one place
        is how a build and its gate end up looking at different files.

        D6 added the fifth and sixth outputs and the two reader pages, so
        the source names them too: every declared output appears in the
        project's own description of itself, exactly once — the snapshot in
        its own cell, the other sixteen decided outputs in
        ``GENERATED_INVENTORIES``. The learning collection is not among
        them and must not be: its pages are computed from the concepts,
        and ``LEARNING_COLLECTION`` names the directory rather than
        thirty-nine paths somebody would have to keep.
        """
        text = APPLICATION_SOURCE.read_text(encoding="utf-8")
        assert f'DOCUMENTATION_ROOT: str = "{DOCS_ROOT}"' in text
        assert f'COMPOSED_SNAPSHOT: str = "{SNAPSHOT_OUTPUT}"' in text
        for provider_id in EXPECTED_PROVIDERS:
            assert f'"{provider_id}"' in text, provider_id
        for relative in STATIC_OUTPUTS:
            assert text.count(f'"{relative}"') == 1, relative
        assert text.count('LEARNING_COLLECTION: str = "learn"') == 1

    def test_the_source_is_utf8_with_lf_endings(self) -> None:
        for path in (PYPROJECT, APPLICATION_SOURCE):
            raw = path.read_bytes()
            assert b"\r" not in raw, path
            assert raw.endswith(b"\n"), path
            raw.decode("utf-8")


# ---------------------------------------------------------------------------
# The composition (T2)
# ---------------------------------------------------------------------------


class TestTheComposition:
    """Eleven providers, one bundle, and nothing wrong with it."""

    def test_the_registry_holds_exactly_the_eleven(self) -> None:
        assert tuple(sorted(registry(REPO_ROOT).ids())) == EXPECTED_PROVIDERS

    def test_a_clean_composition_reports_nothing(self, composed: Build) -> None:
        """The ``covered_by`` of two nerves in ``application.s0ma``."""
        assert [item.rendered() for item in composed.findings] == []
        assert composed.ok
        assert len(composed.artifacts) >= ARTIFACT_FLOOR
        assert len(composed.artifacts) == len(generated_outputs(composed.bundle))

    def test_composing_twice_settles_the_same_way(self) -> None:
        """The ``covered_by`` of ``compose_documentation``.

        Two builds of one tree, compared as bytes rather than as objects:
        the artifacts are what a gate compares, so they are what has to be
        equal.
        """
        first = build(REPO_ROOT)
        second = build(REPO_ROOT)
        assert first.artifacts == second.artifacts
        assert first.bundle.stamp.snapshot_hash == second.bundle.stamp.snapshot_hash

    def test_provider_order_does_not_reach_the_artifacts(self) -> None:
        """Every rotation of the eleven, plus the reversal, renders one byte string.

        Reversal alone was the C8 proof and was enough for five providers
        read from five unrelated sources. Ten is a different claim: five
        of the D-phase readings vouch for ids the others cite, so the
        order they are asked in now decides the order a *union* is built
        in as well as the order records arrive in. Rotations exercise
        every provider in every position, which reversal does for two.

        The providers are read once and re-keyed, not rebuilt. A provider
        is one immutable reading by contract, so building eleven copies
        would prove eleven readings agree — a different and weaker claim
        than this one, which is that the composition does not care what
        order it is handed them in.
        """
        providers = list(registry(REPO_ROOT).providers())
        expected = build(REPO_ROOT, providers=ProviderRegistry.of(*providers)).artifacts

        orders: list[list[Any]] = [list(reversed(providers))]
        orders.extend(
            providers[offset:] + providers[:offset]
            for offset in range(1, len(providers))
        )
        for order in orders:
            shuffled = build(REPO_ROOT, providers=ProviderRegistry.of(*order))
            assert shuffled.artifacts == expected, [
                provider.provider_id for provider in order
            ]

    def test_the_snapshot_is_stamped_with_the_toolchain_version(
        self, composed: Build
    ) -> None:
        assert composed.bundle.stamp.release_version == release_version()

    def test_every_floor_names_a_provider_that_ran(self, composed: Build) -> None:
        """A floor over a provider that did not run is itself a finding."""
        named = {provider_id for provider_id, _ in APPLICATION_FLOORS}
        assert named == set(EXPECTED_PROVIDERS)
        assert DOC_GATE_VACUOUS not in _codes(composed.findings)

    def test_the_product_concepts_constants_match_the_file_they_name(self) -> None:
        assert PRODUCT_CONCEPTS.startswith(f"{DOCS_ROOT}/s0ma_src/concepts/")
        assert PRODUCT_CONCEPTS.endswith(f"/{PRODUCT_DOMAIN}.json")
        assert (REPO_ROOT / PRODUCT_CONCEPTS).is_file()


class TestTheRenderedArtifacts:
    """What a build renders, and the shape every artifact has to have."""

    def test_the_build_renders_exactly_the_declared_outputs(
        self, composed: Build
    ) -> None:
        """The pin C8 set at one artifact, flipped by D6 to the declared set.

        It is deliberately an equality against the declared set rather
        than a count: the write command writes what the build rendered and
        the check command compares what the build rendered, so a further
        artifact appearing without being declared would be written and
        gated by nobody's decision. Since F5 the declared set is asked of
        the build rather than read off a constant, because half of it is
        computed from the concepts that build composed.
        """
        assert [item.relative for item in composed.artifacts] == list(
            generated_outputs(composed.bundle)
        )
        assert SNAPSHOT_OUTPUT in STATIC_OUTPUTS

    def test_every_artifact_is_canonical(self, composed: Build) -> None:
        """UTF-8, LF, one trailing newline, forward-slashed relative path."""
        for artifact in composed.artifacts:
            assert "\r" not in artifact.content, artifact.relative
            assert artifact.content.endswith("\n"), artifact.relative
            assert not artifact.content.endswith("\n\n"), artifact.relative
            artifact.content.encode("utf-8")
            assert not artifact.relative.startswith("/")
            assert "\\" not in artifact.relative
            assert ".." not in artifact.relative.split("/")

    def test_no_artifact_carries_the_machine_that_built_it(
        self, composed: Build
    ) -> None:
        """ADR-012 §3: a machine path in a rendered page survives a re-run."""
        for artifact in composed.artifacts:
            assert str(REPO_ROOT) not in artifact.content, artifact.relative

    def test_the_snapshot_round_trips_through_the_model(
        self, composed: Build
    ) -> None:
        artifact = composed.artifact(SNAPSHOT_OUTPUT)
        assert deserialize_bundle(artifact.content) == composed.bundle

    def test_asking_for_an_artifact_this_build_never_made_is_refused(
        self, composed: Build
    ) -> None:
        from s0ma_dsl.docs_model.records import DocsModelError

        with pytest.raises(DocsModelError, match="renders nothing"):
            composed.artifact("_generated/not-a-thing.json")


# ---------------------------------------------------------------------------
# The write/check loop (T2, T4)
# ---------------------------------------------------------------------------


class TestTheWriteCheckLoop:
    """Write, check, write, check — from clean, twice."""

    def test_the_loop_is_clean_twice_from_clean(
        self, composed: Build, tmp_path: Path
    ) -> None:
        first = write(composed, tmp_path)
        assert [
            path.relative_to(tmp_path).as_posix() for path in first
        ] == sorted(generated_outputs(composed.bundle))
        assert check(composed, tmp_path) == ()

        bytes_after_first = {path: path.read_bytes() for path in first}

        second = write(composed, tmp_path)
        assert second == first
        assert check(composed, tmp_path) == ()
        assert {path: path.read_bytes() for path in second} == bytes_after_first

    def test_a_second_composition_writes_the_same_bytes(
        self, tmp_path: Path
    ) -> None:
        """The loop survives re-composition, not only re-writing."""
        left, right = tmp_path / "left", tmp_path / "right"
        write(build(REPO_ROOT), left)
        write(build(REPO_ROOT), right)
        assert (left / SNAPSHOT_OUTPUT).read_bytes() == (
            right / SNAPSHOT_OUTPUT
        ).read_bytes()

    def test_write_creates_the_directories_an_artifact_needs(
        self, composed: Build, tmp_path: Path
    ) -> None:
        base = tmp_path / "never" / "existed"
        write(composed, base)
        assert (base / SNAPSHOT_OUTPUT).is_file()

    @requires_checkout
    def test_what_is_committed_is_what_a_fresh_build_renders(
        self, composed: Build
    ) -> None:
        """The drift gate itself, run over the real tree."""
        assert check(composed, DOCS) == ()

    def test_the_written_bytes_have_no_carriage_returns(
        self, composed: Build, tmp_path: Path
    ) -> None:
        """Written with an explicit newline, so Windows writes LF too."""
        for path in write(composed, tmp_path):
            assert b"\r" not in path.read_bytes(), path


class TestCheckModeWritesNothing:
    """SDA-INV-9, proved two independent ways."""

    @requires_checkout
    def test_a_check_against_the_real_tree_changes_no_file(
        self, composed: Build, porcelain: str
    ) -> None:
        """``git status --porcelain`` is identical either side of the run."""
        assert check(composed, DOCS) == ()
        # The fixture asserts the porcelain again on teardown; this reads
        # it here too so a failure points at this line rather than at a
        # fixture.
        assert _porcelain() == porcelain

    def test_a_check_against_an_empty_directory_leaves_it_empty(
        self, composed: Build, tmp_path: Path
    ) -> None:
        """Not the artifact, not a parent directory, not a temporary copy."""
        base = tmp_path / "empty"
        base.mkdir()
        findings = check(composed, base)
        assert _codes(findings) == [DOC_OUTPUT_DRIFT] * len(composed.artifacts)
        assert list(base.iterdir()) == []

    @requires_checkout
    def test_the_check_command_changes_no_file(self, porcelain: str) -> None:
        """The same claim through the CLI, which is where a gate runs it."""
        assert S0maCLI().run([
            "--project-root", str(DOCS), "docs", "check", "--output-dir", str(DOCS),
            *_claimed_tag_argv(),
        ]) == 0
        assert _porcelain() == porcelain


# ---------------------------------------------------------------------------
# Drift (T2, T4)
# ---------------------------------------------------------------------------


class TestDriftIsNamed:
    """A report that says only "different" is a report somebody has to redo."""

    @pytest.fixture
    def committed(self, composed: Build, tmp_path: Path) -> Path:
        write(composed, tmp_path)
        return tmp_path / SNAPSHOT_OUTPUT

    def test_a_hand_edited_artifact_is_named_with_its_line(
        self, composed: Build, committed: Path, tmp_path: Path
    ) -> None:
        lines = committed.read_text(encoding="utf-8").splitlines(keepends=True)
        edited = 40
        lines[edited] = lines[edited].replace('"', "'", 1)
        committed.write_text("".join(lines), encoding="utf-8", newline="\n")

        findings = check(composed, tmp_path)
        assert _codes(findings) == [DOC_OUTPUT_DRIFT]
        finding = findings[0]
        assert finding.location == f"{DOCS_ROOT}/{SNAPSHOT_OUTPUT}"
        assert f"line {edited + 1} differs" in finding.message
        assert "committed" in finding.message
        assert "rendered" in finding.message
        assert finding.remediation

    def test_a_truncated_artifact_is_reported_by_its_missing_lines(
        self, composed: Build, committed: Path, tmp_path: Path
    ) -> None:
        text = committed.read_text(encoding="utf-8")
        committed.write_text(
            "\n".join(text.splitlines()[:-3]) + "\n", encoding="utf-8", newline="\n"
        )
        findings = check(composed, tmp_path)
        assert _codes(findings) == [DOC_OUTPUT_DRIFT]
        assert "line(s)" in findings[0].message

    def test_a_missing_artifact_says_it_was_never_written(
        self, composed: Build, tmp_path: Path
    ) -> None:
        findings = check(composed, tmp_path / "nowhere")
        assert _codes(findings) == [DOC_OUTPUT_DRIFT] * len(
            generated_outputs(composed.bundle)
        )
        for finding in findings:
            assert "never been written" in finding.message
            assert finding.remediation

    def test_every_drift_finding_is_located_and_remediated(
        self, composed: Build, committed: Path, tmp_path: Path
    ) -> None:
        committed.write_text("{}\n", encoding="utf-8", newline="\n")
        for finding in check(composed, tmp_path):
            assert finding.location.startswith(f"{DOCS_ROOT}/")
            assert finding.message
            assert finding.remediation

    def test_the_diagnostic_name_is_not_minted_here(self) -> None:
        """``DOC_OUTPUT_DRIFT`` is the architecture plan's §11 name."""
        plan = REPO_ROOT / "plans" / "s0ma-self-documenting-application-1.md"
        if not plan.is_file():  # pragma: no cover - wheel-install context
            pytest.skip("architecture plan not available")
        assert DOC_OUTPUT_DRIFT in plan.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Planted failures (T4)
# ---------------------------------------------------------------------------

_FIXTURE_PROVENANCE = Provenance(
    adapter_id="fixture",
    schema_version="s0ma-docs-model@1",
    source="tests/fixtures/planted.json",
    source_sha256="0" * 64,
)


def _planted_concept(identifier: str, *, cites: str) -> SourcedRecord:
    """One authored-looking concept citing an authority nobody emits."""
    return SourcedRecord(
        record=ConceptRecord(
            id=identifier,
            term="A planted concept",
            summary="Exists so a gate has something wrong to find.",
            plain_definition="A record written by a test, cited by nothing real.",
            purpose="To prove that a finding is collected rather than raised.",
            use_when="Never outside this test module.",
            do_not_use_when="Anywhere a person might read it as documentation.",
            governed_by=(cites,),
            examples=(),
        ),
        provenance=_FIXTURE_PROVENANCE,
    )


class _PlantedProvider:
    """A provider whose records are wrong on purpose."""

    def __init__(self, *records: SourcedRecord) -> None:
        self._records = records

    @property
    def provider_id(self) -> str:
        return "fixture"

    def provide(self) -> ProviderResult:
        from s0ma_dsl.docs_model.providers import sort_records

        return ProviderResult(provider_id="fixture", records=sort_records(self._records))


class TestPlantedFailuresAreCollected:
    """Every finding the gates have, each located — never only the first."""

    def test_an_unresolved_citation_is_reported_against_the_composition(
        self,
    ) -> None:
        planted = _PlantedProvider(
            _planted_concept(
                "concept:planted-one", cites="authority:adr/repo.ADR-000-nonexistent"
            )
        )
        result = build(
            REPO_ROOT,
            providers=ProviderRegistry.of(*registry(REPO_ROOT).providers(), planted),
        )
        assert not result.ok
        # A concept citing an authority nobody emits is an unresolved
        # *topic* reference: the citation names an id, and the code is
        # about the id rather than about the record type that wrote it.
        assert "DOC_TOPIC_UNRESOLVED" in _codes(result.findings)

    def test_two_faults_produce_two_findings_rather_than_the_first(self) -> None:
        planted = _PlantedProvider(
            _planted_concept(
                "concept:planted-one", cites="authority:adr/repo.ADR-000-nonexistent"
            ),
            _planted_concept(
                "concept:planted-two", cites="authority:adr/repo.ADR-000-also-absent"
            ),
        )
        result = build(
            REPO_ROOT,
            providers=ProviderRegistry.of(*registry(REPO_ROOT).providers(), planted),
        )
        located = [
            item
            for item in result.findings
            if item.code == "DOC_TOPIC_UNRESOLVED"
            and "planted" in item.message
        ]
        assert len(located) == 2, [item.rendered() for item in located]
        for finding in located:
            assert finding.message
            assert finding.remediation

    def test_the_build_still_renders_so_every_gate_gets_to_run(self) -> None:
        """A failing composition is reported whole, not abandoned at phase 5."""
        planted = _PlantedProvider(
            _planted_concept(
                "concept:planted-one", cites="authority:adr/repo.ADR-000-nonexistent"
            )
        )
        result = build(
            REPO_ROOT,
            providers=ProviderRegistry.of(*registry(REPO_ROOT).providers(), planted),
        )
        assert result.artifacts
        assert len(result.findings) >= 1

    def test_a_missing_provider_is_a_vacuous_gate_rather_than_a_smaller_build(
        self,
    ) -> None:
        """The floors are what make the provider-shaped gates non-optional."""
        without_catalog = ProviderRegistry.of(
            *(
                provider
                for provider in registry(REPO_ROOT).providers()
                if provider.provider_id != "catalog"
            )
        )
        result = build(REPO_ROOT, providers=without_catalog)
        assert DOC_GATE_VACUOUS in _codes(result.findings)
        assert any(
            "catalog" in item.message
            for item in result.findings
            if item.code == DOC_GATE_VACUOUS
        )

    def test_a_caller_that_brings_its_own_providers_brings_its_own_policy(
        self,
    ) -> None:
        """The policy overrides are one decision, so they travel together.

        A consumer composing a different provider set and left with this
        repository's floors would be told nine providers it never
        registered did not run — and, since D5b, that it holds three
        standing permissions for a silence no surface of its own is
        keeping. Since E8 there is a third claim of the same kind: this
        repository's coverage policy names nine capabilities and
        twenty-seven exceptions over surfaces somebody else's composition
        has never heard of. All of them are the same rule wearing three
        names: a claim about *these* readings, asserted over somebody
        else's, reports the absence of this repository rather than
        anything about theirs.

        Overriding all of them is the supported way, and this is the proof
        that it works rather than merely type-checks.
        """
        one = ProviderRegistry.of(
            *(
                provider
                for provider in registry(REPO_ROOT).providers()
                if provider.provider_id == "catalog"
            )
        )
        stranded = build(REPO_ROOT, providers=one)
        assert DOC_GATE_VACUOUS in _codes(stranded.findings)
        assert any(
            "allowance" in item.message
            for item in stranded.findings
            if item.code == DOC_GATE_VACUOUS
        )

        matched = build(
            REPO_ROOT,
            providers=one,
            floors={("catalog", "documents"): 1},
            allowances={},
            coverage=CoveragePolicy(
                source="test_docs_application_cli.py",
                capabilities=(),
                surface_exceptions=(),
                channel_exceptions=(),
            ),
        )
        # Since F3–F5 there is a fourth claim of the same kind, and it is
        # not a policy override: five of the declared outputs describe
        # families this composition did not register — the two MCP
        # servers, the viewer, the registered components and the concepts
        # — so their renderers refuse rather than commit a page of empty
        # tables, and the artifact floor reports the short set. The quick
        # reference is a fifth of the same kind, in both its renderings: it
        # names kinds, commands and reports a catalog alone does not
        # compose. Those are findings about the pages, located at the
        # pages; what the policy overrides settle is everything else.
        left = [
            item
            for item in matched.findings
            if item.code == DOC_GATE_VACUOUS
            and not item.message.startswith(
                (
                    "reference/",
                    "architecture/",
                    "learn/",
                    "_generated/core-teaching-slice",
                    "_generated/quick-reference-machine",
                )
            )
            and item.location != DOCS_ROOT
        ]
        assert left == [], [item.rendered() for item in left]

    def test_an_empty_render_is_a_vacuous_gate(self, composed: Build) -> None:
        """A build that renders nothing passes every comparison after it.

        The floor takes the bundle since F5: half the declared set is
        computed from the concepts that build composed, so how many
        artifacts *this* build owed is a question about this build.
        """
        from s0ma_dsl.docs_model.application import _artifact_floor

        findings = _artifact_floor((), composed.bundle)
        assert _codes(findings) == [DOC_GATE_VACUOUS]
        assert findings[0].remediation
        assert str(len(generated_outputs(composed.bundle))) in findings[0].message
        assert _artifact_floor(composed.artifacts, composed.bundle) == []


# ---------------------------------------------------------------------------
# The CLI (T2, T3, T4)
# ---------------------------------------------------------------------------


def _run(*argv: str) -> int:
    return S0maCLI().run(list(argv))


class TestTheCommands:
    """The two invocations a contributor runs, through the real argv path."""

    def test_bare_docs_shows_navigation_and_no_longer_exits_two(
        self, capsys: Any
    ) -> None:
        """F6 (T1) replaced C8's usage line, exactly as C8 said it would.

        C8 pinned ``s0ma docs`` at exit 2 and wrote that F6's navigation
        surface would replace it. This is that replacement, re-pinned in
        place rather than deleted: a person who runs the command with
        nothing after it was asking what is here, and arch §9.3 row 3
        makes the answer a map rather than a complaint. The authoring
        pair below is untouched, which is the other half of the claim.
        """
        assert _run("docs") == 0
        captured = capsys.readouterr()
        assert "s0ma docs list" in captured.out
        assert "Usage:" not in captured.err

    def test_compose_writes_and_check_agrees(self, tmp_path: Path) -> None:
        assert _run(
            "--project-root", str(DOCS), "docs", "compose", "--output-dir", str(tmp_path)
        ) == 0
        assert (tmp_path / SNAPSHOT_OUTPUT).is_file()
        assert _run(
            "--project-root", str(DOCS), "docs", "check", "--output-dir", str(tmp_path)
        ) == 0

    def test_check_is_red_when_the_artifact_was_edited(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        assert _run(
            "--project-root", str(DOCS), "docs", "compose", "--output-dir", str(tmp_path)
        ) == 0
        target = tmp_path / SNAPSHOT_OUTPUT
        target.write_text("{}\n", encoding="utf-8", newline="\n")
        capsys.readouterr()
        assert _run(
            "--project-root", str(DOCS), "docs", "check", "--output-dir", str(tmp_path)
        ) == 1
        out = capsys.readouterr().out
        assert DOC_OUTPUT_DRIFT in out
        assert SNAPSHOT_OUTPUT in out

    def test_check_is_red_before_anything_has_been_written(
        self, tmp_path: Path
    ) -> None:
        assert _run(
            "--project-root", str(DOCS), "docs", "check", "--output-dir", str(tmp_path)
        ) == 1

    @requires_checkout
    def test_the_committed_artifact_passes_the_check_command(self) -> None:
        assert _run(
            "--project-root", str(DOCS), "docs", "check", "--output-dir", str(DOCS),
            *_claimed_tag_argv(),
        ) == 0

    def test_the_json_form_is_canonical_and_parses(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        assert _run(
            "--project-root", str(DOCS), "docs", "compose",
            "--output-dir", str(tmp_path), "--format", "json",
        ) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["written"]
        assert payload["snapshot_hash"].startswith("sha256:")

        assert _run(
            "--project-root", str(DOCS), "docs", "check",
            "--output-dir", str(tmp_path), "--format", "json",
        ) == 0
        assert json.loads(capsys.readouterr().out) == {"findings": []}

    def test_a_checkout_without_a_catalog_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        """Exit 2, and the message says what was looked for and where."""
        monkeypatch.chdir(tmp_path)
        assert _run("docs", "check") == 2
        err = capsys.readouterr().err
        assert "catalog.json" in err
        assert "--project-root" in err

    @requires_checkout
    def test_the_documented_invocations_run_as_written(self) -> None:
        """The two commands the report names, with real exit codes.

        ``compose`` renders into a scratch base rather than the tree so
        the suite still writes nothing; the only difference from the
        documented form is that one path. On the one commit a release tag
        names, each also states that tag, so the check composes the channel
        the committed tree claims.
        """
        claimed = _claimed_tag_argv()
        for argv in (
            ["--project-root", DOCS_ROOT, "docs", "check", "--output-dir", DOCS_ROOT],
            ["--project-root", DOCS_ROOT, "docs", "check"],
        ):
            result = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [sys.executable, "-m", "s0ma_dsl.cli.main", *argv, *claimed],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr


class TestTheStatedHeadTag:
    """``--head-tag``: the one thing the build is *told* (H2b).

    H1 made the channel a pure function of the version and a tag, and H2
    made a release verify against it — but nothing fed the rule from the
    command line, so every compose in this repository was a preview and a
    tagged release could not have been proved. This is the flag that
    closes that, and the four claims worth having it for:

    * **absent is today.** A run without the flag composes exactly the
      bytes a run before the flag existed composed. Proved as bytes, over
      every declared artifact, rather than by reading the channel off the
      stamp — the stamp agreeing is the weaker half of the claim;
    * **a tag naming another version is not a release of this one.** It
      composes preview, byte-identically to no tag at all, because
      ``channel_of`` says so and the CLI adds no second opinion;
    * **the matching tag composes a release**, in the manifest, on every
      artifact row, and in the version every identity line renders — bare,
      with no ``(preview)`` label anywhere in the build;
    * **the tag is a value, never a lookup.** The mismatch case is the
      proof: on a checkout standing at no tag at all, stating one is
      enough, and stating the wrong one is not.

    Every compose here writes into ``tmp_path``. The committed tree stays
    preview-composed and no test in this class writes a byte into it.
    """

    def _compose(self, base: Path, *extra: str) -> int:
        return _run(
            "--project-root", str(DOCS), "docs", "compose",
            "--output-dir", str(base), *extra,
        )

    def _manifest(self, base: Path) -> dict[str, Any]:
        return json.loads(
            (base / "_generated" / "docs-manifest.json").read_text(encoding="utf-8")
        )

    def _bytes(self, base: Path) -> dict[str, bytes]:
        return {
            path.relative_to(base).as_posix(): path.read_bytes()
            for path in sorted(base.rglob("*"))
            if path.is_file()
        }

    def test_both_subcommands_accept_the_flag_and_default_to_no_tag(self) -> None:
        """Parsed, defaulted, and stored under the name the handler reads.

        The default is the empty string rather than ``None``: it is fed to
        a rule whose parameter is a tag, and "the tag nobody stated" is
        the empty tag rather than a missing argument.
        """
        parser = S0maCLI().build_parser()
        for command in ("compose", "check"):
            stated = parser.parse_args(
                ["docs", command, "--head-tag", "v1.2.3"]
            )
            assert stated.head_tag == "v1.2.3"
            assert parser.parse_args(["docs", command]).head_tag == ""

    def test_without_the_flag_the_bytes_are_the_ones_committed_today(
        self, tmp_path: Path
    ) -> None:
        """Absent means preview, and preview means unchanged.

        The strong form: every artifact this build renders equals the file
        committed under ``docs/``. That is the same comparison the drift
        gate makes, made here about the flag — so an ``--head-tag`` that
        had leaked into the default path would fail as drift on every
        identity line rather than as a channel somebody has to notice.
        """
        assert self._compose(tmp_path) == 0
        assert self._manifest(tmp_path)["build_channel"] == "preview"
        assert check(build(REPO_ROOT), tmp_path) == ()

    def test_a_tag_naming_another_version_composes_the_same_preview(
        self, tmp_path: Path
    ) -> None:
        """``channel_of``'s rule, reached through the CLI rather than asserted.

        Byte-identical to the no-tag build, which is the claim: the CLI
        carries the tag to the rule and forms no opinion of its own about
        a tag it does not recognise.
        """
        plain, stray = tmp_path / "plain", tmp_path / "stray"
        assert self._compose(plain) == 0
        assert self._compose(stray, "--head-tag", "v9.9.9") == 0
        assert self._manifest(stray)["build_channel"] == "preview"
        assert self._bytes(stray) == self._bytes(plain)

    def test_the_matching_tag_composes_a_release_through_and_through(
        self, tmp_path: Path
    ) -> None:
        """The manifest, every artifact row, and the snapshot's own stamp."""
        version = release_version()
        assert self._compose(tmp_path, "--head-tag", f"v{version}") == 0

        manifest = self._manifest(tmp_path)
        assert manifest["build_channel"] == "release"
        assert manifest["product_version"] == version
        assert {row["build_channel"] for row in manifest["artifacts"]} == {"release"}
        assert {row["release_version"] for row in manifest["artifacts"]} == {version}

        snapshot = json.loads((tmp_path / SNAPSHOT_OUTPUT).read_text(encoding="utf-8"))
        assert snapshot["stamp"]["build_channel"] == "release"

    def test_a_release_build_renders_the_bare_version_everywhere(
        self, tmp_path: Path
    ) -> None:
        """H1's ``version_line`` for the release channel, over the whole build.

        ``0.18.1``, never ``0.18.1 (preview)``. Asserted as the absence of
        the label from *every* rendered artifact rather than from a page
        somebody picked, because the failure this guards against is one
        channel forgetting: thirty-nine identity lines render this fact,
        and a release that carried the label on one of them tells that
        page's reader they are looking at something they are not.
        """
        version = release_version()
        assert self._compose(tmp_path, "--head-tag", f"v{version}") == 0

        labelled = [
            relative
            for relative, raw in self._bytes(tmp_path).items()
            if f"{version} (preview)".encode() in raw
        ]
        assert labelled == []
        assert any(
            f"`{version}`".encode() in raw for raw in self._bytes(tmp_path).values()
        ), "the release version is rendered somewhere, unlabelled"

    def test_the_stamp_says_release_only_when_the_rule_says_so(self) -> None:
        """The build API under the CLI, at both ends of the rule.

        ``version_line`` is the one string every channel renders the
        version through, so pinning it here pins what the pages say
        without re-rendering them.
        """
        version = release_version()
        assert build(
            REPO_ROOT, head_tag=f"v{version}"
        ).bundle.stamp.version_line() == version
        for tag in ("", "v9.9.9", version, f"release-{version}"):
            assert build(REPO_ROOT, head_tag=tag).bundle.stamp.version_line() == (
                f"{version} (preview)"
            ), tag

    @requires_checkout
    @preview_tree_only
    def test_checking_the_committed_tree_as_a_release_is_red(
        self, capsys: Any, porcelain: str
    ) -> None:
        """The proof a release cut needs, and it fails here on purpose.

        ``docs check --head-tag v<version>`` composes the release build in
        memory and holds the committed files against it. This tree is
        preview-composed by design, so it must be red — and the line above
        the findings has to say *which build was asked for*, or forty-odd
        drift reports read as a broken tree rather than as a channel the
        operator stated. Writing nothing while doing it is the same
        SDA-INV-9 claim the rest of the check path makes.
        """
        version = release_version()
        capsys.readouterr()
        assert _run(
            "--project-root", str(DOCS), "docs", "check",
            "--output-dir", str(DOCS), "--head-tag", f"v{version}",
        ) == 1
        out = capsys.readouterr().out
        assert f"Channel: release — v{version} is the tag of {version}." in out
        assert DOC_OUTPUT_DRIFT in out
        assert '"build_channel": "preview"' in out
        assert '"build_channel": "release"' in out
        assert _porcelain() == porcelain

    @requires_checkout
    @preview_tree_only
    def test_checking_the_committed_tree_without_a_tag_stays_green(self) -> None:
        """The other half: the flag is opt-in and the standing gate is untouched."""
        assert _run(
            "--project-root", str(DOCS), "docs", "check", "--output-dir", str(DOCS)
        ) == 0

    def test_no_tag_prints_no_channel_line(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        """Absent is byte-identical on stdout too, not only on disk."""
        capsys.readouterr()
        assert self._compose(tmp_path) == 0
        assert "Channel:" not in capsys.readouterr().out

    def test_a_mistyped_tag_says_so_rather_than_composing_quietly(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        """The case an operator can get wrong, reported at the moment it happens.

        A release cut that mistypes its tag has asked for a release and
        been handed a preview, correctly and without complaint. The line
        is what stops that from being discovered later, by a gate, in the
        wheels.
        """
        capsys.readouterr()
        assert self._compose(tmp_path, "--head-tag", "v9.9.9") == 0
        out = capsys.readouterr().out
        assert "Channel: preview" in out
        assert "v9.9.9 is not" in out
        assert f"v{release_version()}" in out

    def test_nothing_in_the_build_looks_a_tag_up(self) -> None:
        """The tag arrives as a value: no ``git`` on the compose path.

        Asserted over the two modules the flag threads through, because
        the temptation this guards against is a convenience — deriving the
        tag when the operator did not state one — and it would turn a
        stated fact into a property of whichever checkout ran the build.

        Read off the import lines rather than the file: a module that
        never imports a way to start a process cannot start one, and
        matching the word anywhere would catch the prose that explains why
        SDA-INV-8 forbids it.
        """
        for module in (
            REPO_ROOT / "packages/s0ma-dsl/src/s0ma_dsl/docs_model/application.py",
            REPO_ROOT / "packages/s0ma-dsl/src/s0ma_dsl/cli/docs_commands.py",
        ):
            imports = [
                line.strip()
                for line in module.read_text(encoding="utf-8").splitlines()
                if line.strip().startswith(("import ", "from "))
            ]
            assert not [line for line in imports if "subprocess" in line], module
            assert not [line for line in imports if line.endswith(" os")], module


def _roots(output_dir: str | None) -> tuple[Path, Path]:
    """``(checkout, base)`` as the CLI would resolve them for ``docs/``."""
    import argparse

    from s0ma_dsl.cli.docs_commands import _resolve_application_roots
    from s0ma_dsl.cli.main import _resolve_project

    args = argparse.Namespace(
        output_dir=output_dir, project_root=str(DOCS), output_format="json"
    )
    args.s0ma_project = _resolve_project(args)
    return _resolve_application_roots(args)


class TestBaseResolution:
    """Where output lands, and where it never lands."""

    def test_the_output_base_is_the_project_root_not_its_build_dir(self) -> None:
        """The one place ADR-012 §1 says a structured output never goes."""
        checkout, base = _roots(None)
        assert base == DOCS
        assert base != DOCS / "_built"
        assert checkout == REPO_ROOT

    def test_an_explicit_output_dir_wins(self, tmp_path: Path) -> None:
        checkout, base = _roots(str(tmp_path))
        # An output override moves the output and never the sources.
        assert base == tmp_path
        assert checkout == REPO_ROOT

    def test_the_snapshot_lands_in_the_machine_readable_directory(self) -> None:
        """ADR-012 §2.3 rule B-2, and rule B-1 by construction."""
        assert SNAPSHOT_OUTPUT.startswith("_generated/")
        assert not SNAPSHOT_OUTPUT.startswith("_built/")


# ---------------------------------------------------------------------------
# The double-copy question (T3)
# ---------------------------------------------------------------------------


class TestTheDoubleCopyDoesNotMaterialize:
    """ADR-012 §2.4 left ``docs_output_dir`` to C8; the answer is still no.

    The duplication §2.4 describes is a *project build* rendering declared
    ``output:`` paths a second time under ``build_dir``. Its precondition
    is a doc declaration. C8 had none and said so here, with the note that
    these tests fail the day the precondition arrives — and at F1 it did:
    raising the project to ``release`` mode meant covering its three PUBLIC
    nerves with a ``doc-ref``, and that one declaration renders one page.

    So the measurement is now a bound rather than a zero, and the bound is
    exactly what ADR-012 §1 addition 2 predicted: **one** declared output,
    **one** copy of it under ``_built/``, and the composed artifacts — the
    six the application itself renders — still not duplicated at all,
    because those never go through the doc emitter. The copy is cataloged
    as an exclusion (a build artifact, never linked, never read) and
    byte-gated by ``scripts/check_docs_application.py``.

    ``docs_output_dir`` would remove that one copy. It is still not
    adopted: ADR-012 §2.4 rules the layout works either way, and the key
    touches the project loader and two CLI call sites, which is a change
    the milestone that wants it should make deliberately.
    """

    @requires_checkout
    def test_the_committed_build_holds_no_copy_of_any_artifact(
        self, composed: Build
    ) -> None:
        built = DOCS / "_built"
        assert built.is_dir(), "the application build is committed"
        names = {path.name for path in built.rglob("*") if path.is_file()}
        for artifact in composed.artifacts:
            assert Path(artifact.relative).name not in names, artifact.relative

    @requires_checkout
    def test_the_build_directory_holds_no_generated_tree(self) -> None:
        assert not (DOCS / "_built" / "_generated").exists()

    def test_the_application_declares_exactly_one_doc_output(self) -> None:
        """The precondition, arrived — and held to one.

        One ``doc-ref``, one ``output:``, no ``doc-guide``. Each further
        declaration is a further copy under ``_built/``, so the count is
        the thing worth pinning: it makes growing the duplication a
        decision somebody takes here rather than a cost that accumulates.
        """
        lines = APPLICATION_SOURCE.read_text(encoding="utf-8").splitlines()
        # Declarations start a line at column zero; the same words inside a
        # cell's intent are prose about the declaration, not a second one.
        assert [line for line in lines if line.startswith("doc-ref ")] == [
            "doc-ref documentation_application_reference"
        ]
        assert not [line for line in lines if line.startswith("doc-guide ")]
        assert [line for line in lines if line.startswith("    output: ")] == [
            "    output: reference/documentation-application.md"
        ]

    @requires_checkout
    def test_the_build_carries_exactly_one_copy_of_that_output(self) -> None:
        """ADR-012 §1 addition 2's known cost, measured rather than assumed."""
        built = DOCS / "_built"
        copies = sorted(
            path.relative_to(DOCS).as_posix()
            for path in built.rglob("*.md")
            if path.is_file()
            and path.name != "self_prompt_card.md"
            # A project build leaves a transpile cache beside its output;
            # it is git-ignored, regenerable debris rather than a committed
            # copy. Skip the same two subtrees
            # scripts/check_docs_application.py:_built_snapshot skips — the
            # .s0ma.cache/ cache and any __pycache__/ — keyed on the path
            # under _built rather than the absolute one, so the measurement
            # holds whatever cache the working tree carries and wherever the
            # checkout lives (e.g. under a dotted .claude/worktrees/ parent).
            and not any(
                part in {".s0ma.cache", "__pycache__"}
                for part in path.relative_to(built).parts
            )
        )
        assert copies == ["_built/reference/documentation-application.md"]
        rendered = DOCS / "reference" / "documentation-application.md"
        assert rendered.is_file(), "the reader-facing copy is the real one"
        assert (DOCS / copies[0]).read_bytes() == rendered.read_bytes()

    def test_the_project_config_carries_no_docs_output_dir_key(self) -> None:
        """Not adopted. ADR-012 §2.4 says the layout works either way."""
        import tomllib

        table = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["s0ma"]
        assert "docs_output_dir" not in table


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


class TestTheShapeOfTheApplication:
    """Small facts that would be silent regressions."""

    def test_an_artifact_places_itself_under_a_base(self, tmp_path: Path) -> None:
        artifact = Artifact(relative="_generated/x.json", content="{}\n")
        assert artifact.path(tmp_path) == tmp_path / "_generated" / "x.json"

    def test_a_build_with_no_findings_is_ok(self, composed: Build) -> None:
        assert Build(bundle=composed.bundle, artifacts=(), findings=()).ok
        assert not Build(
            bundle=composed.bundle,
            artifacts=(),
            findings=(
                Finding(code="X", location="", message="m", remediation="r"),
            ),
        ).ok

    def test_the_release_version_is_the_toolchain_version(self) -> None:
        from s0ma_dsl import __version__

        assert release_version() == __version__
