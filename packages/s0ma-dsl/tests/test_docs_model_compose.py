"""Gates for C2 — the provider contract, the composition, and the checks.

Milestone C2 of the docs-function plan (internal) §8. What these tests
hold in place, in the order a build meets them:

* the provider contract (architecture plan §7.1) at the two points it is
  enforceable — a result that is sorted, normalized and stamped, and a
  registry in which no two providers share an id;
* the merge rule plan §5 froze and the B gate corrected (B7 report §6 row
  6): different facts under one id is a build error naming **both**
  provenances, identical facts merge to one record whose surviving
  provenance is the first-sorting ``(provider_id, source)``;
* determinism — the composed bundle is the same bytes under every
  provider order, on a second run, and under any hash seed;
* the gates over the composed bundle: every §6.7 edge resolves, every
  record can be traced to a source, no provider resolved empty, no
  teaching order repeats itself, and the authority comparison honors the
  delegation status plan §5 ratified.

Every fixture here is built in this file. The spikes that proved these
rules are evidence, not dependencies: nothing under ``scripts/spikes``
is imported, and a test asserts that of the modules too.
"""

from __future__ import annotations

import ast
import itertools
import os
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.docs_model.compose import (
    DOC_CANONICAL_DUPLICATE,
    Composition,
    DocsCompositionError,
    compose,
    compose_or_raise,
    merge,
)
from s0ma_dsl.docs_model.providers import (
    GROUP_NAMES,
    RECORD_GROUPS,
    DocProvider,
    DocsProviderError,
    Finding,
    ProviderRegistry,
    ProviderResult,
    SourcedRecord,
    group_of,
    sort_findings,
    sort_records,
)
from s0ma_dsl.docs_model.records import (
    SCHEMA,
    AuthorityDelegation,
    AuthorityRef,
    ConceptRecord,
    DocsModelError,
    DocumentRecord,
    ExampleRef,
    JourneyRecord,
    JourneyStep,
    Provenance,
    RecoveryPath,
    SurfaceRecord,
    TeachingSequence,
    TeachingStep,
)
from s0ma_dsl.docs_model.serialize import facts_hash, serialize_bundle, snapshot_hash
from s0ma_dsl.docs_model.validate import (
    DEFERRED_GATES,
    DOC_APPROVAL_UNDECLARED,
    DOC_AUTHORITY_CONFLICT,
    DOC_AUTHORITY_MISDECLARED,
    DOC_CONCEPT_UNRESOLVED,
    DOC_GATE_VACUOUS,
    DOC_JOURNEY_UNRESOLVED,
    DOC_PROVENANCE_MISSING,
    DOC_SEQUENCE_REPEATS,
    DOC_SURFACE_UNBOUND,
    DOC_TEACHING_ORDER,
    DOC_TOPIC_UNRESOLVED,
    MINTED_CODES,
    AuthorityClaim,
    ReferenceIndex,
    check_authority_records,
    check_floors,
    check_provenance,
    check_references,
    check_sequences,
    check_surface_binding,
    governing_authority,
    references,
    validate_bundle,
)

MODEL_DIR = Path(__file__).resolve().parents[1] / "src" / "s0ma_dsl" / "docs_model"
MODEL_FILES = ("compose.py", "providers.py", "validate.py")

RELEASE = "0.18.1"

#: The two ids the model addresses but does not hold. A registered
#: component and a registered example are records of the *registry*, not
#: of the documentation model, so the composition is told about them.
EXTERNAL_IDS = (
    "component:s0ma_dsl.cli.main.S0maCLI",
    "example:first_nerve",
)


# ---------------------------------------------------------------------------
# Record builders
# ---------------------------------------------------------------------------


def _provenance(
    adapter: str = "dsl",
    source: str = "packages/s0ma-dsl/src/s0ma_dsl/cli/main.py",
    **overrides: str,
) -> Provenance:
    values: dict[str, str] = {
        "adapter_id": adapter,
        "schema_version": SCHEMA,
        "source": source,
        "source_sha256": "a" * 64,
    }
    values.update(overrides)
    return Provenance(**values)


def _spec(**overrides: Any) -> AuthorityRef:
    values: dict[str, Any] = {
        "id": "authority:spec/nerve",
        "authority_class": "spec",
        "source": "references/s0ma-spec.md",
        "section": "4.3",
        "content_sha256": "b" * 64,
        "status": "current",
        "delegates": (),
    }
    values.update(overrides)
    return AuthorityRef(**values)


def _prd(**overrides: Any) -> AuthorityRef:
    """The product requirements, delegating the language to the spec.

    FR-DSL-1 is the worked case plan §5 ratified: the requirements name
    the versioned specification the normative language authority and
    decline to duplicate it.
    """
    values: dict[str, Any] = {
        "id": "authority:prd/vision",
        "authority_class": "prd",
        "source": "references/s0ma-prd.md",
        "section": "FR-DSL-1",
        "content_sha256": "c" * 64,
        "status": "current",
        "delegates": (AuthorityDelegation("language", "spec", "FR-DSL-1"),),
    }
    values.update(overrides)
    return AuthorityRef(**values)


def _concept(**overrides: Any) -> ConceptRecord:
    values: dict[str, Any] = {
        "id": "concept:nerve",
        "term": "nerve",
        "summary": "A function a module declares, with a stated purpose.",
        "plain_definition": "A nerve is a function the module declares.",
        "purpose": "It is the unit of behavior a module names.",
        "use_when": "Use it for one behavior with one purpose.",
        "do_not_use_when": "Do not use it for a bag of unrelated helpers.",
        "governed_by": ("authority:prd/vision", "authority:spec/nerve"),
        "examples": (ExampleRef("example:first_nerve", "tools.s0ma"),),
    }
    values.update(overrides)
    return ConceptRecord(**values)


def _surface(**overrides: Any) -> SurfaceRecord:
    values: dict[str, Any] = {
        "id": "cli:s0ma/check",
        "channel": "cli",
        "public_name": "check",
        "intent": "Validate .s0ma file(s) without generating output",
        "component_refs": ("component:s0ma_dsl.cli.main.S0maCLI",),
        "manual_exception": "",
        "governed_by": ("authority:spec/nerve",),
        "side_effects": ("read",),
        "errors": ("EXIT_VALIDATION_ERROR",),
        "provenance": _provenance(),
    }
    values.update(overrides)
    return SurfaceRecord(**values)


def _journey(**overrides: Any) -> JourneyRecord:
    values: dict[str, Any] = {
        "id": "journey:first-project",
        "intent": "Get from nothing to a project that checks clean.",
        "steps": (JourneyStep("cli:s0ma/check", "Prove it is valid.", "No findings."),),
        # The failure is the one ``_surface`` really declares. E1's
        # recovery gate answers "is this failure real" from the step
        # surfaces' own errors or from a registered diagnostic, so a
        # sentence here would be a recovery written against nothing.
        "recovery_paths": (
            RecoveryPath("EXIT_VALIDATION_ERROR", "cli:s0ma/check", "Read the finding."),
        ),
        # The three E1 edges, so the edge-set proof below is not asserting
        # against a journey that happens to carry none of them.
        "concepts_taught": ("concept:nerve",),
        "concepts_required": (),
        "evidence": (ExampleRef("example:first_nerve", "tools.s0ma"),),
    }
    values.update(overrides)
    return JourneyRecord(**values)


def _sequence(**overrides: Any) -> TeachingSequence:
    values: dict[str, Any] = {
        "id": "sequence:concept-tour",
        "steps": (TeachingStep("concept:nerve", "Start with the part."),),
    }
    values.update(overrides)
    return TeachingSequence(**values)


def _document(**overrides: Any) -> DocumentRecord:
    values: dict[str, Any] = {
        "id": "doc:normative/prd",
        "title": "The product requirements",
        "canonical_source": "references/s0ma-prd.md",
        "prose_locator": "references/s0ma-prd.md",
        "governed_by": ("authority:prd/vision",),
        "covers": ("concept:nerve", "journey:first-project"),
    }
    values.update(overrides)
    return DocumentRecord(**values)


# ---------------------------------------------------------------------------
# Fixture providers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FixtureProvider:
    """A provider that hands over a result it was built with.

    ``provider_id`` is a read-only property, which is the shape the
    protocol declares and the shape a real provider will have.
    """

    result: ProviderResult

    @property
    def provider_id(self) -> str:
        return self.result.provider_id

    def provide(self) -> ProviderResult:
        return self.result


@dataclass
class CountingProvider:
    """A provider that records how many times it was asked."""

    result: ProviderResult
    calls: int = 0

    @property
    def provider_id(self) -> str:
        return self.result.provider_id

    def provide(self) -> ProviderResult:
        self.calls += 1
        return self.result


def _result(provider_id: str, *records: SourcedRecord) -> ProviderResult:
    return ProviderResult(provider_id=provider_id, records=sort_records(records))


def _authored(adapter: str = "repo", source: str = "references/docs-catalog.json") -> Provenance:
    """The provenance of a record a person wrote, in the file they wrote it in."""
    return _provenance(adapter=adapter, source=source)


def _governance_provider() -> FixtureProvider:
    """Authorities and the served surface: the derived half of the build."""
    return FixtureProvider(
        _result(
            "core",
            SourcedRecord(_spec(), _authored("core", "references/s0ma-spec.md")),
            SourcedRecord(_prd(), _authored("core", "references/s0ma-prd.md")),
            SourcedRecord.of(_surface()),
        )
    )


def _authoring_provider() -> FixtureProvider:
    """Concepts, journeys, sequences and catalog rows: the authored half."""
    return FixtureProvider(
        _result(
            "repo",
            SourcedRecord(_concept(), _authored()),
            SourcedRecord(_journey(), _authored()),
            SourcedRecord(_sequence(), _authored()),
            SourcedRecord(_document(), _authored()),
        )
    )


def _healthy() -> tuple[FixtureProvider, FixtureProvider]:
    """Two providers that compose into a build with nothing wrong with it."""
    return _governance_provider(), _authoring_provider()


def _compose(*providers: DocProvider) -> Composition:
    return compose(ProviderRegistry.of(*providers), release_version=RELEASE)


def _composed_text() -> str:
    """The healthy build's canonical text. Read from a subprocess too."""
    return serialize_bundle(_compose(*_healthy()).bundle)


@pytest.fixture()
def healthy() -> Composition:
    return _compose(*_healthy())


def _codes(findings: Any) -> list[str]:
    return sorted(finding.code for finding in findings)


# ---------------------------------------------------------------------------
# The provider contract (architecture plan §7.1)
# ---------------------------------------------------------------------------


class TestProviderContract:
    """What a provider must hand over, checked where it hands it over."""

    def test_a_fixture_provider_satisfies_the_protocol(self) -> None:
        """The declared shape is one a plain object can actually have.

        A protocol nothing implements is a protocol nobody checked.
        """
        provider: DocProvider = _governance_provider()
        assert provider.provider_id == "core"
        assert provider.provide().provider_id == "core"

    def test_records_must_arrive_sorted(self) -> None:
        """The contract says sorted; an out-of-order result is refused.

        Composition sorts anyway. The refusal is not about the composed
        output — it is about the provider, whose own order is what a
        reviewer reads and what a later in-provider gate would walk.
        """
        first = SourcedRecord(_concept(), _authored())
        second = SourcedRecord(_document(), _authored())
        with pytest.raises(DocsProviderError, match="out of order"):
            ProviderResult(provider_id="repo", records=(second, first))
        ProviderResult(provider_id="repo", records=(first, second))

    def test_an_un_normalized_id_is_refused_at_the_boundary(self) -> None:
        """A studi0 route handed over by its served name, not its id.

        The one id form that normalizes to something else. Caught here
        rather than three merges later, where it would look like two
        different capabilities.
        """
        served = _surface(
            id="studi0:action//api/graph",
            channel="studi0",
            public_name="/api/graph",
            component_refs=(),
            manual_exception="The route table is not declared yet.",
        )
        with pytest.raises(DocsProviderError, match="comparable form"):
            _result("studi0", SourcedRecord.of(served))

    def test_a_provider_without_an_id_is_refused(self) -> None:
        with pytest.raises(DocsProviderError, match="no provider id"):
            ProviderResult(provider_id="", records=())

    def test_a_record_and_its_provider_cannot_disagree_about_its_origin(self) -> None:
        """Two accounts of one origin is the failure provenance prevents.

        ``SurfaceRecord`` carries its own provenance. If the provider
        stamps a different one, one of the two is a lie and no later gate
        can tell which.
        """
        with pytest.raises(DocsProviderError, match="its own provenance"):
            SourcedRecord(_surface(), _provenance(adapter="mcp"))

    def test_a_record_that_carries_its_provenance_can_be_wrapped_from_it(self) -> None:
        wrapped = SourcedRecord.of(_surface())
        assert wrapped.provenance == _surface().provenance
        assert wrapped.id == "cli:s0ma/check"

    def test_sources_are_derived_from_the_records_not_declared_beside_them(self) -> None:
        """A second list of sources is a copy that can disagree with the first."""
        result = _governance_provider().provide()
        assert result.sources() == (
            ("packages/s0ma-dsl/src/s0ma_dsl/cli/main.py", "a" * 64),
            ("references/s0ma-prd.md", "a" * 64),
            ("references/s0ma-spec.md", "a" * 64),
        )

    def test_counts_show_the_empty_groups_too(self) -> None:
        """A floor on a group a provider stopped producing must see the zero."""
        counts = _authoring_provider().provide().counts()
        assert counts["concepts"] == 1
        assert counts["surfaces"] == 0
        assert set(counts) == set(GROUP_NAMES)

    def test_every_bundle_group_has_exactly_one_record_type(self) -> None:
        """The grouping table and the bundle's own fields cannot drift apart."""
        assert sorted(RECORD_GROUPS.values()) == sorted(GROUP_NAMES)
        assert group_of(_concept()) == "concepts"
        assert group_of(_surface()) == "surfaces"

    def test_a_record_type_a_bundle_does_not_carry_is_refused_by_name(self) -> None:
        with pytest.raises(DocsProviderError, match="not a record type"):
            group_of(ExampleRef("example:first_nerve", "tools.s0ma"))  # type: ignore[arg-type]


class TestRegistry:
    """One id, one provider — the structural half of the purity contract."""

    def test_two_providers_cannot_share_one_id(self) -> None:
        """The merge rule breaks every tie with ``(provider_id, source)``.

        Two providers under one id make the surviving record depend on
        which of them ran first, which is the one thing the composition
        promises cannot happen.
        """
        registry = ProviderRegistry.of(_governance_provider())
        with pytest.raises(DocsProviderError, match="already registered"):
            registry.register(_governance_provider())
        assert registry.ids() == ("core",)

    def test_registration_order_is_kept(self) -> None:
        """Order-independence has to be provable, so it is not built in.

        A registry that sorted itself would make the permutation proof
        vacuous: the merge is what is order-independent.
        """
        first, second = _healthy()
        forward = ProviderRegistry.of(first, second).providers()
        backward = ProviderRegistry.of(second, first).providers()
        assert [item.provider_id for item in forward] == ["core", "repo"]
        assert [item.provider_id for item in backward] == ["repo", "core"]

    def test_something_that_is_not_a_provider_is_refused_by_name(self) -> None:
        registry = ProviderRegistry()
        with pytest.raises(DocsProviderError, match="no provider id"):
            registry.register(object())  # type: ignore[arg-type]
        with pytest.raises(DocsProviderError, match="no provide"):
            registry.register(_result("lonely"))  # type: ignore[arg-type]

    def test_each_provider_is_asked_exactly_once(self) -> None:
        """A provider read twice is a provider that could answer twice."""
        counting = CountingProvider(_authoring_provider().provide())
        compose(
            ProviderRegistry.of(_governance_provider(), counting),
            release_version=RELEASE,
        )
        assert counting.calls == 1

    def test_a_result_stamped_with_another_id_is_refused(self) -> None:
        """The registry's key and the result's id are one identity."""

        @dataclass(frozen=True)
        class Liar:
            @property
            def provider_id(self) -> str:
                return "core"

            def provide(self) -> ProviderResult:
                return _result("repo")

        with pytest.raises(DocsProviderError, match="stamped"):
            _compose(Liar())


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


class TestComposition:
    """One bundle out of several providers, and the same one every time."""

    def test_the_bundle_holds_every_record_grouped_and_stamped(
        self, healthy: Composition
    ) -> None:
        bundle = healthy.bundle
        assert healthy.ok
        assert [item.id for item in bundle.authorities] == [
            "authority:prd/vision",
            "authority:spec/nerve",
        ]
        assert [item.id for item in bundle.concepts] == ["concept:nerve"]
        assert [item.id for item in bundle.surfaces] == ["cli:s0ma/check"]
        assert [item.id for item in bundle.journeys] == ["journey:first-project"]
        assert [item.id for item in bundle.sequences] == ["sequence:concept-tour"]
        assert [item.id for item in bundle.documents] == ["doc:normative/prd"]
        assert bundle.stamp.schema == SCHEMA
        assert bundle.stamp.release_version == RELEASE
        assert bundle.stamp.snapshot_hash == snapshot_hash(
            replace(bundle, stamp=bundle.stamp)
        )

    def test_every_group_is_sorted_by_id(self, healthy: Composition) -> None:
        """The snapshot digest hashes the groups as it finds them.

        ``snapshot_hash`` does not sort — it is taken over the bundle's
        own tuples — so an unsorted group would put the provider order
        straight into the digest that identifies the build.
        """
        for group in GROUP_NAMES:
            ids = [record.id for record in getattr(healthy.bundle, group)]
            assert ids == sorted(ids)

    def test_the_survivors_keep_their_provenance(self, healthy: Composition) -> None:
        """SDA-INV-10: provenance survives every projection.

        Five of the six record types have no provenance field, so without
        this the merge rule's survivor would be unobservable for them.
        """
        assert healthy.provenance_of("concept:nerve").adapter_id == "repo"
        assert healthy.provenance_of("cli:s0ma/check").adapter_id == "dsl"
        assert [item.id for item in healthy.survivors] == sorted(
            item.id for item in healthy.survivors
        )
        with pytest.raises(DocsModelError, match="composed nothing"):
            healthy.provenance_of("concept:absent")

    def test_provider_order_does_not_reach_the_output(self) -> None:
        """The permutation proof, promoted from B3's proof 2.

        Three providers, six orders, one text. The third provider agrees
        with the second about one record, so the merge rule's survivor
        choice is exercised by the permutation rather than only the
        grouping.
        """
        agreeing = FixtureProvider(
            _result("aaa-mirror", SourcedRecord(_concept(), _authored("aaa-mirror")))
        )
        providers = (*_healthy(), agreeing)
        texts = {
            serialize_bundle(_compose(*order).bundle)
            for order in itertools.permutations(providers)
        }
        digests = {_compose(*order).bundle.stamp.snapshot_hash for order in
                   itertools.permutations(providers)}
        assert len(texts) == 1
        assert len(digests) == 1

    def test_two_runs_produce_the_same_bytes(self) -> None:
        assert _composed_text() == _composed_text()

    def test_the_same_records_compose_the_same_under_any_hash_seed(self) -> None:
        """Determinism rule 4, proved the only way it can be proved.

        Dictionary iteration is the usual way a hash seed reaches output,
        and the merge is built on dictionaries, so the check has to happen
        in a fresh process with the seed set.
        """
        script = (
            "from tests.test_docs_model_compose import _composed_text;"
            "print(_composed_text(), end='')"
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
        assert outputs[0] == _composed_text()

    def test_a_provider_that_gives_nothing_composes_to_nothing(self) -> None:
        """An empty build is a build. The vacuity floor is what refuses it."""
        composition = _compose(FixtureProvider(_result("empty")))
        assert composition.ok
        assert composition.bundle.concepts == ()


class TestDuplicateRule:
    """Plan §5, as corrected at the B gate (B7 report §6 row 6)."""

    def test_two_providers_agreeing_merge_to_one_record(self) -> None:
        """Identical facts from two sources is agreement, not conflict.

        The moment the application has two providers deriving one truth
        from two sources this is the normal case. Treating it as an error
        would forbid honest agreement.
        """
        left = FixtureProvider(
            _result("b-provider", SourcedRecord(_concept(), _authored("b-provider")))
        )
        right = FixtureProvider(
            _result("a-provider", SourcedRecord(_concept(), _authored("a-provider")))
        )
        composition = _compose(left, right)
        assert composition.ok
        assert len(composition.bundle.concepts) == 1
        assert facts_hash(_concept()) == facts_hash(_concept())

    def test_the_surviving_provenance_is_the_first_sorting_one(self) -> None:
        """Not the first to arrive: the first in ``(provider_id, source)``.

        First-writer-wins would make the result depend on provider order
        and break the permutation proof.
        """
        left = FixtureProvider(
            _result("b-provider", SourcedRecord(_concept(), _authored("b-provider")))
        )
        right = FixtureProvider(
            _result("a-provider", SourcedRecord(_concept(), _authored("a-provider")))
        )
        for order in itertools.permutations((left, right)):
            composition = _compose(*order)
            assert composition.provenance_of("concept:nerve").adapter_id == "a-provider"

    def test_one_source_before_another_under_one_provider(self) -> None:
        """The pair sorts on the source when the provider id is equal."""
        records = (
            SourcedRecord(_concept(), _authored("repo", "references/second.json")),
            SourcedRecord(_concept(), _authored("repo", "references/first.json")),
        )
        composition = _compose(FixtureProvider(_result("repo", *records)))
        assert composition.ok
        assert composition.provenance_of("concept:nerve").source == "references/first.json"

    def test_different_facts_under_one_id_name_both_provenances(self) -> None:
        """The build error §5 froze, with the evidence a person needs.

        Naming one source would send an author to read a file that may be
        the correct one.
        """
        left = FixtureProvider(
            _result("core", SourcedRecord(_concept(), _authored("core", "core.json")))
        )
        right = FixtureProvider(
            _result(
                "mcp",
                SourcedRecord(_concept(term="axon"), _authored("mcp", "mcp.json")),
            )
        )
        composition = _compose(left, right)
        assert _codes(composition.findings) == [DOC_CANONICAL_DUPLICATE]
        message = composition.findings[0].message
        for expected in ("core", "core.json", "mcp", "mcp.json", "concept:nerve"):
            assert expected in message
        assert "must stop claiming" in composition.findings[0].remediation

    def test_the_duplicate_finding_does_not_depend_on_provider_order(self) -> None:
        """A three-way disagreement reports one finding, the same one.

        Every claimant is collected before any of them is judged, so the
        report cannot depend on which pair was compared first.
        """
        providers = tuple(
            FixtureProvider(
                _result(
                    name,
                    SourcedRecord(_concept(term=name), _authored(name, f"{name}.json")),
                )
            )
            for name in ("alpha", "beta", "gamma")
        )
        rendered = {
            tuple(finding.rendered() for finding in _compose(*order).findings)
            for order in itertools.permutations(providers)
        }
        assert len(rendered) == 1
        assert len(next(iter(rendered))) == 1
        assert "3 records" in next(iter(rendered))[0]

    def test_a_disagreement_still_composes_a_deterministic_bundle(self) -> None:
        """Determinism in the presence of a reported error, not a resolution.

        The bundle keeps the same claimant under every order — and the
        finding is what stops the build using it.
        """
        left = FixtureProvider(
            _result("core", SourcedRecord(_concept(), _authored("core", "core.json")))
        )
        right = FixtureProvider(
            _result(
                "mcp",
                SourcedRecord(_concept(term="axon"), _authored("mcp", "mcp.json")),
            )
        )
        texts = {
            serialize_bundle(_compose(*order).bundle)
            for order in itertools.permutations((left, right))
        }
        assert len(texts) == 1

    def test_one_provider_can_contradict_itself(self) -> None:
        """Nothing about the rule depends on there being two providers."""
        records = (
            SourcedRecord(_concept(), _authored("repo", "one.json")),
            SourcedRecord(_concept(term="axon"), _authored("repo", "two.json")),
        )
        composition = _compose(FixtureProvider(_result("repo", *records)))
        assert _codes(composition.findings) == [DOC_CANONICAL_DUPLICATE]

    def test_two_record_types_cannot_share_an_id(self) -> None:
        """The merge is global, so a cross-group collision is caught too."""
        collision = _document(id="concept:nerve", covers=(), governed_by=())
        left = FixtureProvider(
            _result("core", SourcedRecord(_concept(), _authored("core")))
        )
        right = FixtureProvider(
            _result("repo", SourcedRecord(collision, _authored("repo")))
        )
        assert _codes(_compose(left, right).findings) == [DOC_CANONICAL_DUPLICATE]

    def test_merge_is_callable_on_its_own(self) -> None:
        """The rule is a function of the results, and testable as one."""
        kept, findings = merge([_governance_provider().provide()])
        assert findings == ()
        assert sorted(kept) == [
            "authority:prd/vision",
            "authority:spec/nerve",
            "cli:s0ma/check",
        ]

    def test_build_mode_refuses_rather_than_returning_a_bundle(self) -> None:
        """SDA-INV-9: a build produces true documentation or nothing."""
        left = FixtureProvider(
            _result("core", SourcedRecord(_concept(), _authored("core", "core.json")))
        )
        right = FixtureProvider(
            _result(
                "mcp",
                SourcedRecord(_concept(term="axon"), _authored("mcp", "mcp.json")),
            )
        )
        registry = ProviderRegistry.of(left, right)
        with pytest.raises(DocsCompositionError) as caught:
            compose_or_raise(registry, release_version=RELEASE)
        assert caught.value.findings[0].code == DOC_CANONICAL_DUPLICATE
        assert "core.json" in str(caught.value)

    def test_check_mode_returns_everything_that_is_wrong(self) -> None:
        assert compose_or_raise(
            ProviderRegistry.of(*_healthy()), release_version=RELEASE
        ).stamp.release_version == RELEASE


# ---------------------------------------------------------------------------
# Edges (architecture plan §6.7)
# ---------------------------------------------------------------------------


class TestEdgeResolution:
    """All targets must resolve, and a finding says where to go."""

    def test_a_healthy_build_resolves_completely(self, healthy: Composition) -> None:
        index = ReferenceIndex.of(healthy.bundle, EXTERNAL_IDS)
        assert check_references(index) == []

    def test_every_edge_the_model_carries_is_walked(self, healthy: Composition) -> None:
        """The §6.7 edge set, restricted to what ``@1`` can hold.

        A gate that silently skips an edge kind passes everything on that
        edge, which is the failure mode this asserts against.
        """
        found = references(healthy.bundle)
        assert {reference.edge for reference in found} == {
            "covers",
            "demonstrated_by",
            "governed_by",
            "illustrated_by",
            "implemented_by",
            "teaches",
            "uses",
        }
        # ``requires`` needs a prerequisite, and this fixture has exactly
        # one concept — which the journey teaches. Proved on its own
        # record rather than by inventing a second concept every other
        # assertion in this file would then have to expect.
        assumed = replace(
            healthy.bundle,
            journeys=(_journey(concepts_taught=(), concepts_required=("concept:nerve",)),),
        )
        assert "requires" in {reference.edge for reference in references(assumed)}
        assert {reference.source_group for reference in found} == {
            "concepts",
            "surfaces",
            "journeys",
            "sequences",
            "documents",
        }
        assert ("journeys", "recovery_paths[0].next_surface") in {
            (reference.source_group, reference.field) for reference in found
        }

    def test_a_catalog_row_covering_an_absent_concept_is_located(self) -> None:
        """Red, with the file the author can actually edit.

        A catalog row's prose locator is where its words are, which is
        not always the file it is about (B6 finding 2).
        """
        provider = FixtureProvider(
            _result(
                "repo",
                SourcedRecord(
                    _document(covers=("concept:absent",), governed_by=()),
                    _authored(),
                ),
            )
        )
        composition = _compose(provider)
        findings = check_references(ReferenceIndex.of(composition.bundle))
        assert [finding.code for finding in findings] == [DOC_CONCEPT_UNRESOLVED]
        assert findings[0].location == "references/s0ma-prd.md"
        assert "covers[0]" in findings[0].message
        assert "doc:normative/prd" in findings[0].message

    def test_a_journey_step_naming_a_missing_surface_is_the_journey_code(self) -> None:
        """§11 keys this on the citing record, not on the target's class."""
        provider = FixtureProvider(
            _result(
                "repo",
                SourcedRecord(
                    _journey(
                        steps=(JourneyStep("cli:s0ma/absent", "Do it.", "Done."),),
                        recovery_paths=(),
                        concepts_taught=(),
                        evidence=(),
                    ),
                    _authored(),
                ),
            )
        )
        findings = check_references(ReferenceIndex.of(_compose(provider).bundle))
        assert [finding.code for finding in findings] == [DOC_JOURNEY_UNRESOLVED]

    def test_a_surface_naming_a_missing_component_is_unbound(self) -> None:
        """§11's ``DOC_SURFACE_UNBOUND``, on the edge §11 defines it for."""
        composition = _compose(*_healthy())
        index = ReferenceIndex.of(composition.bundle, ("example:first_nerve",))
        findings = check_references(index)
        assert [finding.code for finding in findings] == [DOC_SURFACE_UNBOUND]
        assert findings[0].location == "packages/s0ma-dsl/src/s0ma_dsl/cli/main.py"

    def test_an_unresolved_authority_falls_to_the_general_code(self) -> None:
        """Neither §11 row fits a concept citing an absent authority."""
        provider = FixtureProvider(
            _result(
                "repo",
                SourcedRecord(
                    _concept(governed_by=("authority:spec/absent",), examples=()),
                    _authored(),
                ),
            )
        )
        findings = check_references(ReferenceIndex.of(_compose(provider).bundle))
        assert [finding.code for finding in findings] == [DOC_TOPIC_UNRESOLVED]

    def test_a_malformed_target_is_told_it_is_malformed(self) -> None:
        """Two failures, two remedies.

        A flat component name matches no form at all — a mistake in the
        shape of the id — and that is a different fix from a well-formed
        id nobody has written a record for.
        """
        provider = FixtureProvider(
            _result(
                "repo",
                SourcedRecord(
                    _concept(governed_by=(), examples=(ExampleRef("Widget", "x.py"),)),
                    _authored(),
                ),
            )
        )
        findings = check_references(ReferenceIndex.of(_compose(provider).bundle))
        assert [finding.code for finding in findings] == [DOC_TOPIC_UNRESOLVED]
        assert "matches no id form" in findings[0].remediation

    def test_the_universe_is_the_callers_and_the_gate_does_not_guess(self) -> None:
        """A component id is not a bundle record, so the caller supplies it.

        With nothing supplied every component reference is unresolved,
        which is the truthful answer when nobody has said what components
        exist — the gate does not quietly excuse a class of edge.

        Three findings over the two ids of :data:`EXTERNAL_IDS`, because
        the registered example is cited twice: the concept illustrates
        itself with it and the journey names it as the evidence that its
        path still works.
        """
        composition = _compose(*_healthy())
        with_nothing = check_references(ReferenceIndex.of(composition.bundle))
        with_both = check_references(
            ReferenceIndex.of(composition.bundle, EXTERNAL_IDS)
        )
        assert len(with_nothing) == 3
        assert with_both == []


class TestSurfaceBinding:
    """``component_refs`` and ``manual_exception`` are independent axes."""

    def test_a_surface_that_reaches_nothing_and_says_nothing_is_unbound(self) -> None:
        surface = _surface(component_refs=(), manual_exception="", governed_by=())
        provider = FixtureProvider(_result("dsl", SourcedRecord.of(surface)))
        findings = check_surface_binding(_compose(provider).bundle)
        assert [finding.code for finding in findings] == [DOC_SURFACE_UNBOUND]
        assert "no reason" in findings[0].message

    def test_a_written_exception_is_a_reason(self) -> None:
        """The studi0 case: authored records until D4a declares the routes."""
        surface = _surface(
            id="studi0:action/api/graph",
            channel="studi0",
            public_name="/api/graph",
            component_refs=(),
            manual_exception="The studi0 route table is not declared yet.",
            governed_by=(),
        )
        provider = FixtureProvider(_result("studi0", SourcedRecord.of(surface)))
        assert check_surface_binding(_compose(provider).bundle) == []

    def test_a_surface_may_honestly_carry_both(self) -> None:
        """B7 register row 4: the axes are independent, and nothing refuses both."""
        surface = _surface(
            manual_exception="Its errors were transcribed from the help text.",
        )
        provider = FixtureProvider(_result("dsl", SourcedRecord.of(surface)))
        assert check_surface_binding(_compose(provider).bundle) == []


class TestChangeImpact:
    """The reverse index architecture plan §11.2 asks for."""

    def test_a_changed_authority_lists_what_cites_it(self, healthy: Composition) -> None:
        index = ReferenceIndex.of(healthy.bundle, EXTERNAL_IDS)
        assert index.referrers("authority:spec/nerve") == (
            "cli:s0ma/check",
            "concept:nerve",
        )

    def test_the_impact_set_follows_the_chain(self, healthy: Composition) -> None:
        """changed authority -> concepts/surfaces -> journeys -> documents.

        The point of reporting the set even when regeneration would
        produce no diff: a reviewer can tell "checked and unchanged" from
        "never considered".
        """
        index = ReferenceIndex.of(healthy.bundle, EXTERNAL_IDS)
        assert index.impact_of("authority:spec/nerve") == (
            "cli:s0ma/check",
            "concept:nerve",
            "doc:normative/prd",
            "journey:first-project",
            "sequence:concept-tour",
        )

    def test_nothing_is_in_its_own_impact_set(self, healthy: Composition) -> None:
        index = ReferenceIndex.of(healthy.bundle, EXTERNAL_IDS)
        assert "concept:nerve" not in index.impact_of("concept:nerve")

    def test_an_uncited_thing_affects_nothing(self, healthy: Composition) -> None:
        index = ReferenceIndex.of(healthy.bundle, EXTERNAL_IDS)
        assert index.impact_of("doc:normative/prd") == ()
        assert index.referrers("concept:absent") == ()


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------


class TestAuthority:
    """The order, and the delegation status the B gate ratified."""

    def _authorities(self, *refs: AuthorityRef) -> dict[str, AuthorityRef]:
        return {ref.id: ref for ref in refs}

    def test_the_stronger_authority_governs_by_default(self) -> None:
        """Lower never overrides higher, and no conflict is reported for it."""
        decision = governing_authority(
            record_id="concept:nerve",
            cited=("authority:prd/vision", "authority:spec/nerve"),
            authorities=self._authorities(_prd(delegates=()), _spec()),
            domain="language",
        )
        assert decision.governing == ("authority:prd/vision",)
        assert decision.findings == ()

    def test_a_recorded_delegation_hands_the_domain_down(self) -> None:
        """FR-DSL-1, the case plan §5 ratified.

        The requirements name the versioned specification the normative
        language authority. For a language claim the specification wins,
        and **no conflict is reported** — the stronger authority deferred
        by its own instruction, in writing, citably.
        """
        decision = governing_authority(
            record_id="concept:nerve",
            cited=("authority:prd/vision", "authority:spec/nerve"),
            authorities=self._authorities(_prd(), _spec()),
            domain="language",
        )
        assert decision.governing == ("authority:spec/nerve",)
        assert decision.delegated_from == ("authority:prd/vision",)
        assert decision.findings == ()

    def test_a_delegation_only_covers_the_domain_it_names(self) -> None:
        """The domain is load-bearing, not decoration."""
        decision = governing_authority(
            record_id="concept:nerve",
            cited=("authority:prd/vision", "authority:spec/nerve"),
            authorities=self._authorities(_prd(), _spec()),
            domain="pricing",
        )
        assert decision.governing == ("authority:prd/vision",)
        assert decision.findings == ()

    def test_an_undeclared_equal_rank_conflict_refuses(self) -> None:
        """Two authorities of one class, one domain-scoped question.

        Nothing decides between them, so the comparison says so rather
        than picking one. The finding names both.
        """
        other = _spec(id="authority:spec/axon", section="4.4")
        decision = governing_authority(
            record_id="concept:nerve",
            cited=("authority:spec/nerve", "authority:spec/axon"),
            authorities=self._authorities(_spec(), other),
            domain="language",
        )
        assert [finding.code for finding in decision.findings] == [DOC_AUTHORITY_CONFLICT]
        assert decision.governing == ("authority:spec/axon", "authority:spec/nerve")
        message = decision.findings[0].message
        assert "authority:spec/nerve" in message
        assert "authority:spec/axon" in message

    def test_sections_of_one_document_may_co_govern_an_undomained_question(self) -> None:
        """"What governs this record" and "who decides this" are different.

        Two sections of the specification both governing a concept is
        ordinary. Refusing it would make the gate noise, and §5's refusal
        is about a domain nobody has assigned.
        """
        other = _spec(id="authority:spec/axon", section="4.4")
        decision = governing_authority(
            record_id="concept:nerve",
            cited=("authority:spec/nerve", "authority:spec/axon"),
            authorities=self._authorities(_spec(), other),
        )
        assert decision.governing == ("authority:spec/axon", "authority:spec/nerve")
        assert decision.findings == ()

    def test_a_circle_of_delegations_holds_nobody(self) -> None:
        prd = _prd()
        spec = _spec(delegates=(AuthorityDelegation("language", "prd", "§1"),))
        decision = governing_authority(
            record_id="concept:nerve",
            cited=("authority:prd/vision", "authority:spec/nerve"),
            authorities=self._authorities(prd, spec),
            domain="language",
        )
        assert [finding.code for finding in decision.findings] == [DOC_AUTHORITY_CONFLICT]
        assert "circle" in decision.findings[0].message

    def test_a_delegate_that_is_not_cited_leaves_the_delegator_governing(self) -> None:
        """Requiring the delegate to be cited is a coverage rule, not this one."""
        decision = governing_authority(
            record_id="concept:nerve",
            cited=("authority:prd/vision",),
            authorities=self._authorities(_prd()),
            domain="language",
        )
        assert decision.governing == ("authority:prd/vision",)
        assert decision.findings == ()

    def test_an_unknown_citation_is_not_reported_twice(self) -> None:
        """The unresolved reference is the reference resolver's finding."""
        decision = governing_authority(
            record_id="concept:nerve",
            cited=("authority:spec/absent",),
            authorities=self._authorities(_spec()),
            domain="language",
        )
        assert decision.governing == ()
        assert decision.findings == ()

    def test_a_class_that_disagrees_with_its_own_id_is_reported(self) -> None:
        """The gate C1 repeated ``authority_class`` on the record to allow.

        A record that ranks differently depending on which field is read
        cannot govern anything.
        """
        wrong = _spec(id="authority:adr/nerve")
        provider = FixtureProvider(_result("core", SourcedRecord(wrong, _authored())))
        findings = check_authority_records(_compose(provider).bundle)
        assert [finding.code for finding in findings] == [DOC_AUTHORITY_MISDECLARED]
        assert findings[0].location == "references/s0ma-spec.md#4.3"

    def test_a_delegation_up_the_order_is_reported(self) -> None:
        """Delegation is a stronger authority handing a domain *down*."""
        upward = _spec(delegates=(AuthorityDelegation("language", "owner", "§1"),))
        provider = FixtureProvider(_result("core", SourcedRecord(upward, _authored())))
        findings = check_authority_records(_compose(provider).bundle)
        assert [finding.code for finding in findings] == [DOC_AUTHORITY_MISDECLARED]
        assert "rather than down it" in findings[0].message

    def test_a_delegation_nobody_can_cite_is_reported(self) -> None:
        """"A delegation nobody can cite is an assumption" — C1's own words."""
        vague = _prd(delegates=(AuthorityDelegation("language", "spec", ""),))
        provider = FixtureProvider(_result("core", SourcedRecord(vague, _authored())))
        findings = check_authority_records(_compose(provider).bundle)
        assert [finding.code for finding in findings] == [DOC_AUTHORITY_MISDECLARED]
        assert "where it says so" in findings[0].message

    def test_a_healthy_authority_set_reports_nothing(self, healthy: Composition) -> None:
        assert check_authority_records(healthy.bundle) == []

    def test_the_comparison_is_reachable_from_the_aggregate(
        self, healthy: Composition
    ) -> None:
        """A caller asks a domain-scoped question through ``claims``."""
        assert (
            validate_bundle(
                healthy.bundle,
                results=healthy.results,
                external_ids=EXTERNAL_IDS,
                claims=(AuthorityClaim("concept:nerve", "language"),),
            )
            == ()
        )

    def test_asking_the_question_of_a_record_that_cites_nothing_is_refused(
        self, healthy: Composition
    ) -> None:
        with pytest.raises(DocsModelError, match="cites no authority"):
            validate_bundle(
                healthy.bundle,
                external_ids=EXTERNAL_IDS,
                claims=(AuthorityClaim("journey:first-project", "language"),),
            )

    def test_asking_about_a_record_nothing_answers_to_is_refused(
        self, healthy: Composition
    ) -> None:
        with pytest.raises(DocsModelError, match="addresses nothing"):
            validate_bundle(
                healthy.bundle,
                external_ids=EXTERNAL_IDS,
                claims=(AuthorityClaim("concept:absent", "language"),),
            )


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class TestProvenance:
    """``DOC_PROVENANCE_MISSING`` — SDA-INV-10 at the record level."""

    def test_a_healthy_build_is_traceable(self, healthy: Composition) -> None:
        assert check_provenance(healthy.bundle, healthy.results) == []

    def test_a_blank_field_is_named(self) -> None:
        blank = _provenance(source="")
        provider = FixtureProvider(
            _result("repo", SourcedRecord(_concept(), blank))
        )
        composition = _compose(provider)
        findings = check_provenance(composition.bundle, composition.results)
        assert [finding.code for finding in findings] == [DOC_PROVENANCE_MISSING]
        assert "source" in findings[0].message

    def test_an_authored_record_is_checked_too(self) -> None:
        """Not only the type that happens to carry a provenance field.

        A concept nobody can trace to a file is as unfixable as a surface
        nobody can trace to a registry.
        """
        empty = Provenance(adapter_id="", schema_version="", source="", source_sha256="")
        provider = FixtureProvider(_result("repo", SourcedRecord(_sequence(), empty)))
        composition = _compose(provider)
        findings = check_provenance(composition.bundle, composition.results)
        assert [finding.code for finding in findings] == [DOC_PROVENANCE_MISSING]
        for field in ("adapter_id", "schema_version", "source", "source_sha256"):
            assert field in findings[0].message

    def test_a_placeholder_digest_is_not_a_digest(self) -> None:
        """A placeholder reads as a real digest to every later gate."""
        surface = _surface(provenance=_provenance(source_sha256="TODO"))
        provider = FixtureProvider(_result("dsl", SourcedRecord.of(surface)))
        findings = check_provenance(_compose(provider).bundle)
        assert [finding.code for finding in findings] == [DOC_PROVENANCE_MISSING]
        assert "not a sha256" in findings[0].message

    def test_a_surface_is_asked_once_though_two_sets_hold_it(self) -> None:
        """The bundle's surfaces and the results overlap; the finding does not.

        One mistake is one finding even for a caller that does not run
        this through the aggregate.
        """
        surface = _surface(provenance=_provenance(source=""))
        composition = _compose(FixtureProvider(_result("dsl", SourcedRecord.of(surface))))
        findings = check_provenance(composition.bundle, composition.results)
        assert [finding.code for finding in findings] == [DOC_PROVENANCE_MISSING]

    def test_a_record_that_merged_away_is_still_checked(self) -> None:
        """A provider with unstamped records is a provider to fix.

        The losing record is gone from the bundle; the provider that
        emitted it has not gone anywhere.
        """
        good = FixtureProvider(
            _result("a-provider", SourcedRecord(_concept(), _authored("a-provider")))
        )
        bad = FixtureProvider(
            _result(
                "b-provider",
                SourcedRecord(_concept(), _provenance(adapter="b-provider", source="")),
            )
        )
        composition = _compose(good, bad)
        assert composition.ok
        findings = check_provenance(composition.bundle, composition.results)
        assert [finding.code for finding in findings] == [DOC_PROVENANCE_MISSING]

    def test_the_schema_version_a_provider_emitted_against_is_not_the_stamp(
        self, healthy: Composition
    ) -> None:
        """C1 gave the field its own name so a lagging provider stays visible.

        Comparing it against the build stamp is still not *this* gate's
        job: provenance asks whether a record can be traced at all. Since
        H1 the comparison exists one gate over, in ``check_manifest``,
        which is where a build finally states one model version and can be
        held to it — so the deferral entry is gone and this asserts the
        division of labour rather than the absence of the rule.
        """
        lagging = _provenance(schema_version="s0ma-docs-model@0")
        provider = FixtureProvider(_result("old", SourcedRecord(_concept(), lagging)))
        composition = _compose(provider)
        assert check_provenance(composition.bundle, composition.results) == []
        assert "DOC_VERSION_MISMATCH" not in DEFERRED_GATES


# ---------------------------------------------------------------------------
# Anti-vacuity floors
# ---------------------------------------------------------------------------


class TestFloors:
    """``DOC_GATE_VACUOUS`` — a gate that resolves empty passes everything."""

    def test_a_met_floor_says_nothing(self, healthy: Composition) -> None:
        assert check_floors(healthy.results, {("core", "surfaces"): 1}) == []

    def test_an_empty_provider_trips_its_floor(self) -> None:
        composition = _compose(
            _governance_provider(), FixtureProvider(_result("repo"))
        )
        findings = check_floors(composition.results, {("repo", "concepts"): 1})
        assert [finding.code for finding in findings] == [DOC_GATE_VACUOUS]
        assert "produced 0 concepts" in findings[0].message

    def test_a_floor_for_a_provider_that_never_ran_is_the_same_failure(
        self, healthy: Composition
    ) -> None:
        """A provider nobody registered looks exactly like an empty one."""
        findings = check_floors(healthy.results, {("studi0", "surfaces"): 1})
        assert [finding.code for finding in findings] == [DOC_GATE_VACUOUS]
        assert "did not run" in findings[0].message

    def test_floors_are_the_callers_and_never_this_modules(self) -> None:
        """A floor is a claim about one provider reading one tree.

        Hard-coding one here would make the model lie about somebody
        else's build, so the module holds none and the signature requires
        them.
        """
        source = (MODEL_DIR / "validate.py").read_text(encoding="utf-8")
        assert "FLOORS = " not in source
        assert check_floors((), {}) == []

    def test_a_floor_on_something_that_is_not_a_group_is_refused(self) -> None:
        with pytest.raises(DocsModelError, match="not a bundle group"):
            check_floors((), {("core", "widgets"): 1})


# ---------------------------------------------------------------------------
# Teaching sequences
# ---------------------------------------------------------------------------


class TestSequences:
    """The gate B6 wrote and C1's record type waited for."""

    def _index(self, sequence: TeachingSequence, *extra: SourcedRecord) -> Any:
        provider = FixtureProvider(
            _result("repo", SourcedRecord(sequence, _authored()), *extra)
        )
        composition = _compose(provider)
        return composition.bundle, ReferenceIndex.of(composition.bundle)

    def test_a_healthy_sequence_says_nothing(self, healthy: Composition) -> None:
        index = ReferenceIndex.of(healthy.bundle, EXTERNAL_IDS)
        assert check_sequences(healthy.bundle, index) == []

    def test_a_repeated_topic_is_the_constraint_only_an_order_can_carry(self) -> None:
        """B6 finding 9, and the reason ``TeachingSequence`` exists.

        A catalog row's ``covers`` is a sorted set, so it throws order
        away and cannot say a topic twice. An ordered form can, and a
        teaching order that teaches one topic twice has lost its order.
        """
        repeating = _sequence(
            steps=(
                TeachingStep("concept:nerve", "Start here."),
                TeachingStep("concept:nerve", "And again."),
            )
        )
        bundle, index = self._index(
            repeating, SourcedRecord(_concept(governed_by=(), examples=()), _authored())
        )
        findings = check_sequences(bundle, index)
        assert [finding.code for finding in findings] == [DOC_SEQUENCE_REPEATS]
        assert "step 2" in findings[0].message

    def test_an_unresolved_step_is_reported_by_the_gate_itself(self) -> None:
        """The gate is complete on its own, the way B6's was."""
        bundle, index = self._index(
            _sequence(steps=(TeachingStep("concept:absent", "Teach it."),))
        )
        findings = check_sequences(bundle, index)
        assert [finding.code for finding in findings] == [DOC_CONCEPT_UNRESOLVED]

    def test_a_sequence_with_no_steps_resolves_empty(self) -> None:
        """An empty sequence passes every check it is subject to."""
        bundle, index = self._index(_sequence(steps=()))
        findings = check_sequences(bundle, index)
        assert [finding.code for finding in findings] == [DOC_GATE_VACUOUS]

    def test_the_aggregate_reports_one_finding_for_one_mistake(self) -> None:
        """The sequence gate and the resolver ask the same question on purpose.

        Both are right to ask; an author should still see it once.
        """
        provider = FixtureProvider(
            _result(
                "repo",
                SourcedRecord(
                    _sequence(steps=(TeachingStep("concept:absent", "Teach it."),)),
                    _authored(),
                ),
            )
        )
        findings = validate_bundle(_compose(provider).bundle)
        assert [finding.code for finding in findings] == [DOC_CONCEPT_UNRESOLVED]


# ---------------------------------------------------------------------------
# Findings themselves
# ---------------------------------------------------------------------------


class TestFindings:
    """Structured, sorted, collected — never raised and never first-only."""

    def test_a_finding_carries_all_four_parts(self) -> None:
        provider = FixtureProvider(
            _result(
                "repo",
                SourcedRecord(_document(covers=("concept:absent",)), _authored()),
            )
        )
        findings = validate_bundle(_compose(provider).bundle)
        finding = findings[0]
        assert finding.code.startswith("DOC_")
        assert finding.message
        assert finding.remediation
        assert finding.location == "references/s0ma-prd.md"
        assert finding.rendered().startswith("references/s0ma-prd.md: DOC_")

    def test_a_finding_the_model_cannot_place_reads_as_a_sentence(self) -> None:
        """``@1`` records no line numbers, and an empty path is not a path."""
        unplaced = Finding(code="DOC_GATE_VACUOUS", location="", message="x", remediation="y")
        assert unplaced.rendered() == "DOC_GATE_VACUOUS: x"

    def test_every_problem_is_reported_not_only_the_first(self) -> None:
        """A build with three problems reports three."""
        broken = FixtureProvider(
            _result(
                "repo",
                SourcedRecord(
                    _concept(governed_by=("authority:spec/absent",), examples=()),
                    _authored(),
                ),
                SourcedRecord(
                    _document(covers=("journey:absent",), governed_by=()), _authored()
                ),
                SourcedRecord(
                    _sequence(steps=(TeachingStep("concept:absent", "Teach it."),)),
                    _authored(),
                ),
            )
        )
        findings = validate_bundle(_compose(broken).bundle)
        assert len(findings) == 3

    def test_findings_sort_by_code_then_place(self) -> None:
        one = Finding(code="DOC_B", location="b.md", message="m", remediation="r")
        two = Finding(code="DOC_A", location="z.md", message="m", remediation="r")
        three = Finding(code="DOC_A", location="a.md", message="m", remediation="r")
        assert sort_findings([one, two, three]) == (three, two, one)

    def test_an_exact_repeat_is_dropped(self) -> None:
        one = Finding(code="DOC_A", location="a.md", message="m", remediation="r")
        assert sort_findings([one, one]) == (one,)

    def test_the_minted_codes_say_why_they_exist(self) -> None:
        """Not silently added to a frozen namespace.

        C1 flagged the ``sequence:`` id form for ratification rather than
        minting it quietly; these are the same kind of debt and they are
        recorded the same way.
        """
        assert set(MINTED_CODES) == {
            DOC_SEQUENCE_REPEATS,
            DOC_TOPIC_UNRESOLVED,
            DOC_AUTHORITY_MISDECLARED,
            DOC_TEACHING_ORDER,
            DOC_APPROVAL_UNDECLARED,
        }
        for code, reason in MINTED_CODES.items():
            assert code.startswith("DOC_")
            assert len(reason) > 40

    def test_the_module_names_the_gates_it_does_not_implement(self) -> None:
        """A reader who expects a coverage gate finds out why it is not here.

        ``DOC_COVERAGE_UNMENTIONED`` needs the prose, and no prose reader
        exists before the F phase — which is exactly why the rule was
        raised: resolution alone makes over-claiming free.
        """
        assert "DOC_COVERAGE_UNMENTIONED" in DEFERRED_GATES
        assert "F" in DEFERRED_GATES["DOC_COVERAGE_UNMENTIONED"]
        for reason in DEFERRED_GATES.values():
            assert len(reason) > 40

    def test_a_healthy_build_reports_nothing_at_all(self, healthy: Composition) -> None:
        """The whole aggregate, green, so a red one means something."""
        assert (
            validate_bundle(
                healthy.bundle,
                results=healthy.results,
                external_ids=EXTERNAL_IDS,
                floors={("core", "surfaces"): 1, ("repo", "concepts"): 1},
                claims=(AuthorityClaim("concept:nerve", "language"),),
            )
            == ()
        )


# ---------------------------------------------------------------------------
# What these modules are allowed to depend on
# ---------------------------------------------------------------------------


class TestDependencies:
    """ADR-012 and the D-4 guard, checked against the source itself."""

    @pytest.mark.parametrize("filename", MODEL_FILES)
    def test_the_module_imports_nothing_it_should_not(self, filename: str) -> None:
        """Stdlib and this package only, spikes included.

        The spikes proved these rules and are evidence, not dependencies:
        a module that imported one would tie the shipped model to a
        script under ``scripts/``. Core is forbidden here too — a provider
        that needs core runs later and lives in its own module.
        """
        forbidden = ("s0ma.", "s0ma_mcp", "s0ma_studi0", "spike_", "scripts.")
        tree = ast.parse((MODEL_DIR / filename).read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        offenders = [name for name in imported if name == "s0ma" or name.startswith(forbidden)]
        assert offenders == [], f"{filename} imports {offenders}"

    @pytest.mark.parametrize("filename", MODEL_FILES)
    def test_the_source_is_utf8_with_line_feeds(self, filename: str) -> None:
        raw = (MODEL_DIR / filename).read_bytes()
        raw.decode("utf-8")
        assert b"\r\n" not in raw
