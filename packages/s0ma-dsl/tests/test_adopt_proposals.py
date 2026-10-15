"""What the scan suggests, and why it says so (B3).

``s0ma_dsl/adopt/proposals.py`` is the first place the retrofit family
stops reporting facts and starts giving advice, so these tests are
mostly about the honesty of the advice rather than its cleverness:

- **Every suggestion carries its evidence.** A proposal with an empty
  ``reasons`` tuple is a guess wearing a report's clothes; the model
  forbids one and these tests check for it everywhere.
- **"High" is earned, not assumed.** Only the module's *name* agreeing
  with what it actually *imports* reaches ``"high"``. One family alone
  is ``"medium"``; families that disagree are ``"low"`` with the
  disagreement spelled out.
- **Nothing is invented.** A module with no signal at all comes back
  with ``layer=None`` and a sentence saying the choice is the author's,
  not with the least-bad guess.
- **The matrix is a finding, never an auto-fix.** When the proposed
  layers would make an import that already exists illegal, both modules
  are told, in a sentence naming both of them and both layers, and both
  drop to ``"low"``. Nothing is silently relabelled to make the matrix
  happy.
- **Determinism.** Two runs over the same facts — in any order — produce
  byte-identical JSON, because a golden report in a later milestone
  depends on it.

Every census here is built by hand from the frozen model, so these tests
depend on neither the census reader nor the brownfield fixtures. The
graph facts come from the real :func:`~s0ma_dsl.adopt.graph.build_graph`
over those same hand-built censuses: it is committed, it is what the
caller will pass, and hand-maintaining ``fan_in`` would only test the
fixture.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.adopt.graph import (
    ORIGIN_FIRST_PARTY,
    ORIGIN_STDLIB,
    ORIGIN_THIRD_PARTY,
    ORIGIN_UNRESOLVED,
    build_graph,
)
from s0ma_dsl.adopt.model import (
    EntityFact,
    GraphFacts,
    ImportFact,
    ModuleCensus,
    Proposal,
    SourceFile,
    dump_json,
)
from s0ma_dsl.adopt.proposals import (
    EFFORT_BASIS,
    PERIMETER_MODE,
    WARNING_NAME_COLLISION,
    collision_warnings,
    estimate_effort,
    framework_component_names,
    propose,
    suggest_perimeter,
)
from s0ma_dsl.ast_nodes.enums import Layer
from s0ma_dsl.resolver.dependency import _ALLOWED_TARGET_LAYERS

if TYPE_CHECKING:
    from collections.abc import Sequence

# ---------------------------------------------------------------------------
# Hand-built records
#
# No field in the frozen model has a default, so a census has to be
# constructed whole. These helpers supply valid placeholders for the
# fields a given test does not care about, and nothing else.
# ---------------------------------------------------------------------------

EMPTY_HASH = "sha256:" + "0" * 64

PROJECT_ROOT = Path("/not/read/by/anything")
"""Handed to :func:`suggest_perimeter`, which promises never to touch it."""


def an_import(
    module: str,
    *,
    names: Sequence[str] = (),
    line: int = 1,
    deferred: bool = False,
    type_checking: bool = False,
    origin: str = ORIGIN_UNRESOLVED,
) -> ImportFact:
    """One import record, defaulting to what the census reader leaves behind."""
    return ImportFact(
        module=module,
        names=tuple(names),
        line=line,
        deferred=deferred,
        type_checking=type_checking,
        origin=origin,
    )


def an_entity(
    name: str,
    *,
    category: str = "function",
    kind_hint: str = "FUNCTION",
    line: int = 1,
    public: bool = True,
    decorators: Sequence[str] = (),
    bases: Sequence[str] = (),
    has_docstring: bool = True,
    registered: bool = False,
) -> EntityFact:
    """One top-level definition, as the census would have recorded it."""
    return EntityFact(
        name=name,
        category=category,
        line=line,
        public=public,
        kind_hint=kind_hint,
        decorators=tuple(decorators),
        bases=tuple(bases),
        has_docstring=has_docstring,
        registered=registered,
    )


def a_source(
    module: str,
    *,
    role: str = "app",
    path: str | None = None,
    source_root: str = "src",
) -> SourceFile:
    """One discovered file; the path is derived from the module unless given."""
    if path is None:
        stem = module.replace(".", "/")
        prefix = "" if source_root == "." else source_root + "/"
        path = f"{prefix}{stem}.py"
    return SourceFile(path=path, module=module, source_root=source_root, role=role)


def a_module(
    module: str,
    *,
    imports: Sequence[ImportFact] = (),
    entities: Sequence[EntityFact] = (),
    role: str = "app",
    path: str | None = None,
    source_root: str = "src",
    sloc: int = 8,
    lines: int = 10,
    has_main_guard: bool = False,
    top_level_effects: int = 0,
    parse_error: str | None = None,
) -> ModuleCensus:
    """One census carrying only the facts a proposal reads."""
    return ModuleCensus(
        source=a_source(module, role=role, path=path, source_root=source_root),
        lines=lines,
        sloc=sloc,
        entities=tuple(entities),
        imports=tuple(imports),
        dunder_all=None,
        has_main_guard=has_main_guard,
        top_level_effects=top_level_effects,
        parse_error=parse_error,
        content_hash=EMPTY_HASH,
    )


def facts(censuses: Sequence[ModuleCensus]) -> GraphFacts:
    """The real graph over hand-built censuses — what the caller will pass."""
    return build_graph(censuses)


def only(censuses: Sequence[ModuleCensus], module: str) -> Proposal:
    """The one proposal for *module*, so a test can assert on it directly."""
    proposals = {
        proposal.module: proposal for proposal in propose(censuses, facts(censuses))
    }
    assert module in proposals, f"no proposal for {module}: {sorted(proposals)}"
    return proposals[module]


EMPTY_GRAPH = GraphFacts(
    edges=(), deferred_edges=(), cycles=(), order=(), fan_in=(), fan_out=()
)


# ---------------------------------------------------------------------------
# The layer names and the matrix come from the DSL, not from here
# ---------------------------------------------------------------------------


class TestTheLayerVocabularyIsBorrowed:
    """Proposals speak the language's own layer names, not a copy of them."""

    def test_every_proposed_layer_is_a_real_dsl_layer(self) -> None:
        censuses = [
            a_module("shop.api.routes"),
            a_module("shop.domain.rules", entities=[an_entity("allowed")]),
            a_module("shop.storage.db", imports=[an_import("sqlite3", origin=ORIGIN_STDLIB)]),
            a_module("shop.services.billing"),
        ]
        known = {layer.value for layer in Layer}
        for proposal in propose(censuses, facts(censuses)):
            assert proposal.layer is None or proposal.layer in known

    def test_framework_is_never_proposed(self) -> None:
        """FRAMEWORK is reserved for s0ma's own internals, not an application's."""
        censuses = [
            a_module("shop.framework.core", entities=[an_entity("run")]),
            a_module("framework", entities=[an_entity("run")]),
        ]
        for proposal in propose(censuses, facts(censuses)):
            assert proposal.layer != Layer.FRAMEWORK.value

    def test_the_matrix_this_module_checks_against_is_the_transpilers_own(self) -> None:
        """A sanity anchor: the rule under test is the one the build enforces."""
        assert _ALLOWED_TARGET_LAYERS[Layer.PRESENTATION] == {
            Layer.DOMAIN,
            Layer.APPLICATION,
            Layer.PRESENTATION,
            Layer.FRAMEWORK,
        }
        assert Layer.INFRASTRUCTURE not in _ALLOWED_TARGET_LAYERS[Layer.PRESENTATION]


# ---------------------------------------------------------------------------
# Signal 1 — the name
# ---------------------------------------------------------------------------


NAME_CASES: tuple[tuple[str, str, str], ...] = (
    # module name, expected layer, the word the reason must name
    ("shop.api.orders", Layer.PRESENTATION.value, "api"),
    ("shop.web", Layer.PRESENTATION.value, "web"),
    ("shop.handlers", Layer.PRESENTATION.value, "handlers"),
    ("shop.cli", Layer.PRESENTATION.value, "cli"),
    ("shop.views", Layer.PRESENTATION.value, "views"),
    ("shop.services.billing", Layer.APPLICATION.value, "services"),
    ("shop.workflows", Layer.APPLICATION.value, "workflows"),
    ("shop.usecases", Layer.APPLICATION.value, "usecases"),
    ("shop.domain.money", Layer.DOMAIN.value, "domain"),
    ("shop.models", Layer.DOMAIN.value, "models"),
    ("shop.rules", Layer.DOMAIN.value, "rules"),
    ("shop.storage", Layer.INFRASTRUCTURE.value, "storage"),
    ("shop.repositories", Layer.INFRASTRUCTURE.value, "repositories"),
    ("shop.adapters.mail", Layer.INFRASTRUCTURE.value, "adapters"),
    ("shop.clients", Layer.INFRASTRUCTURE.value, "clients"),
)


class TestTheNameSignal:
    """What the author called it is evidence — the first kind a scan has."""

    @pytest.mark.parametrize(("module", "layer", "word"), NAME_CASES)
    def test_a_recognised_word_in_the_name_proposes_its_layer(
        self, module: str, layer: str, word: str
    ) -> None:
        # One first-party import keeps the place family quiet, so the
        # name is the only family speaking.
        censuses = [
            a_module(module, imports=[an_import("shop.util")]),
            a_module("shop.util"),
        ]
        proposal = only(censuses, module)
        assert proposal.layer == layer
        assert proposal.confidence == "medium"
        assert any(f"`{word}`" in reason for reason in proposal.reasons)

    def test_the_files_own_name_beats_the_folders_above_it(self) -> None:
        """``app/api/models.py`` is a pile of models that lives under the API."""
        censuses = [
            a_module("shop.api.models", imports=[an_import("shop.util")]),
            a_module("shop.util"),
        ]
        proposal = only(censuses, "shop.api.models")
        assert proposal.layer == Layer.DOMAIN.value
        assert any("`models`" in reason for reason in proposal.reasons)

    def test_an_underscored_name_is_read_word_by_word(self) -> None:
        censuses = [
            a_module("shop.db_client", imports=[an_import("shop.util")]),
            a_module("shop.util"),
        ]
        proposal = only(censuses, "shop.db_client")
        assert proposal.layer == Layer.INFRASTRUCTURE.value
        assert any("`client`" in reason for reason in proposal.reasons)

    def test_an_unremarkable_name_says_nothing(self) -> None:
        censuses = [
            a_module("shop.plumbing", imports=[an_import("shop.util")]),
            a_module("shop.util"),
        ]
        proposal = only(censuses, "shop.plumbing")
        assert proposal.layer is None


# ---------------------------------------------------------------------------
# Signal 2 — the libraries
# ---------------------------------------------------------------------------


LIBRARY_CASES: tuple[tuple[str, str, str], ...] = (
    # import target, its origin, expected layer
    ("flask", ORIGIN_THIRD_PARTY, Layer.PRESENTATION.value),
    ("django.http", ORIGIN_THIRD_PARTY, Layer.PRESENTATION.value),
    ("click", ORIGIN_THIRD_PARTY, Layer.PRESENTATION.value),
    ("argparse", ORIGIN_STDLIB, Layer.PRESENTATION.value),
    ("requests", ORIGIN_THIRD_PARTY, Layer.INFRASTRUCTURE.value),
    ("sqlalchemy.orm", ORIGIN_THIRD_PARTY, Layer.INFRASTRUCTURE.value),
    ("psycopg2", ORIGIN_THIRD_PARTY, Layer.INFRASTRUCTURE.value),
    ("sqlite3", ORIGIN_STDLIB, Layer.INFRASTRUCTURE.value),
    ("socket", ORIGIN_STDLIB, Layer.INFRASTRUCTURE.value),
)


class TestTheLibrarySignal:
    """What it imports is evidence of a different kind from what it is called."""

    @pytest.mark.parametrize(("target", "origin", "layer"), LIBRARY_CASES)
    def test_a_recognised_library_proposes_its_layer(
        self, target: str, origin: str, layer: str
    ) -> None:
        censuses = [
            a_module(
                "shop.thing",
                imports=[an_import("shop.util"), an_import(target, origin=origin)],
            ),
            a_module("shop.util"),
        ]
        proposal = only(censuses, "shop.thing")
        assert proposal.layer == layer
        assert any(f"`{target.split('.')[0]}`" in reason for reason in proposal.reasons)

    def test_the_reason_says_what_the_library_is(self) -> None:
        """Written for someone who has not memorised PyPI."""
        censuses = [a_module("shop.thing", imports=[an_import("flask")], entities=[])]
        proposal = only(censuses, "shop.thing")
        assert any("a web framework" in reason for reason in proposal.reasons)

    def test_an_unknown_library_says_nothing(self) -> None:
        censuses = [
            a_module(
                "shop.thing",
                imports=[an_import("shop.util"), an_import("leftpad")],
            ),
            a_module("shop.util"),
        ]
        assert only(censuses, "shop.thing").layer is None

    def test_a_deferred_import_still_counts_as_evidence(self) -> None:
        """A driver imported inside a function is still a driver."""
        censuses = [
            a_module(
                "shop.thing",
                imports=[
                    an_import("shop.util"),
                    an_import("psycopg2", deferred=True),
                ],
            ),
            a_module("shop.util"),
        ]
        assert only(censuses, "shop.thing").layer == Layer.INFRASTRUCTURE.value

    def test_libraries_pointing_two_ways_are_reported_as_a_judgement_call(self) -> None:
        censuses = [
            a_module(
                "shop.thing",
                imports=[
                    an_import("shop.util"),
                    an_import("flask"),
                    an_import("psycopg2"),
                ],
            ),
            a_module("shop.util"),
        ]
        proposal = only(censuses, "shop.thing")
        assert proposal.layer is None
        assert proposal.confidence == "low"
        joined = " ".join(proposal.reasons)
        assert "`flask`" in joined
        assert "`psycopg2`" in joined
        assert "judgement call" in joined

    def test_a_first_party_module_that_shadows_a_library_is_not_that_library(self) -> None:
        """``propose`` classifies imports itself, so a shadowing name cannot fool it."""
        censuses = [
            a_module("app", imports=[an_import("requests"), an_import("other")]),
            a_module("requests", entities=[an_entity("get")]),
            a_module("other"),
        ]
        proposal = only(censuses, "app")
        assert not any("web-request" in reason for reason in proposal.reasons)
        assert proposal.layer is None


# ---------------------------------------------------------------------------
# Signal 3 — where it sits
# ---------------------------------------------------------------------------


class TestThePlaceSignal:
    """Position in the project's own graph is the third, weakest, family."""

    def test_a_runnable_module_nothing_imports_is_a_way_in(self) -> None:
        censuses = [a_module("run", role="script", path="run.py", source_root=".")]
        proposal = only(censuses, "run")
        assert proposal.layer == Layer.PRESENTATION.value
        assert any("ways in to the program" in reason for reason in proposal.reasons)

    def test_a_main_guard_on_an_imported_module_is_not_a_way_in(self) -> None:
        """An importable module with a ``__main__`` block is not an entry point."""
        censuses = [
            a_module("shop.thing", has_main_guard=True, entities=[an_entity("go")]),
            a_module("shop.other", imports=[an_import("shop.thing")]),
        ]
        proposal = only(censuses, "shop.thing")
        assert any("self-contained domain logic" in reason for reason in proposal.reasons)

    def test_a_self_contained_leaf_looks_like_domain_logic(self) -> None:
        censuses = [a_module("shop.thing", entities=[an_entity("compute")])]
        proposal = only(censuses, "shop.thing")
        assert proposal.layer == Layer.DOMAIN.value
        assert proposal.confidence == "medium"

    def test_a_leaf_that_opens_a_door_to_the_world_is_not_domain_logic(self) -> None:
        """``sqlite3`` ships with Python and is still a door out of the process."""
        censuses = [
            a_module(
                "shop.thing",
                entities=[an_entity("load")],
                imports=[an_import("sqlite3", origin=ORIGIN_STDLIB)],
            )
        ]
        proposal = only(censuses, "shop.thing")
        assert proposal.layer == Layer.INFRASTRUCTURE.value
        assert not any("domain logic" in reason for reason in proposal.reasons)

    def test_an_empty_file_is_not_evidence_of_anything(self) -> None:
        """Leaning on nothing because there is nothing there proves nothing."""
        censuses = [a_module("shop", role="package_marker", path="src/shop/__init__.py")]
        proposal = only(censuses, "shop")
        assert proposal.layer is None


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


class TestConfidenceIsEarned:
    """Only a name agreeing with an import reaches ``high``."""

    def test_name_and_library_agreeing_is_high(self) -> None:
        censuses = [
            a_module(
                "shop.storage.db",
                imports=[an_import("shop.util"), an_import("psycopg2")],
                entities=[an_entity("load")],
            ),
            a_module("shop.util"),
        ]
        proposal = only(censuses, "shop.storage.db")
        assert proposal.layer == Layer.INFRASTRUCTURE.value
        assert proposal.confidence == "high"
        assert len(proposal.reasons) >= 2

    def test_name_and_place_agreeing_is_high(self) -> None:
        censuses = [a_module("shop.domain.rules", entities=[an_entity("allowed")])]
        proposal = only(censuses, "shop.domain.rules")
        assert proposal.layer == Layer.DOMAIN.value
        assert proposal.confidence == "high"

    def test_one_family_alone_is_medium(self) -> None:
        censuses = [
            a_module("shop.views", imports=[an_import("shop.util")]),
            a_module("shop.util"),
        ]
        assert only(censuses, "shop.views").confidence == "medium"

    def test_families_that_disagree_are_low_and_say_so(self) -> None:
        censuses = [
            a_module(
                "shop.models",
                imports=[an_import("shop.util"), an_import("flask")],
            ),
            a_module("shop.util"),
        ]
        proposal = only(censuses, "shop.models")
        # The name is the tie-break: it is the author's own word for it.
        assert proposal.layer == Layer.DOMAIN.value
        assert proposal.confidence == "low"
        joined = " ".join(proposal.reasons)
        assert Layer.DOMAIN.value in joined
        assert Layer.PRESENTATION.value in joined
        assert "argue with" in joined

    def test_every_proposal_carries_at_least_one_reason(self) -> None:
        censuses = [
            a_module("shop.plumbing", imports=[an_import("shop.util")]),
            a_module("shop.util", entities=[an_entity("helper")]),
            a_module("shop.api", imports=[an_import("flask")]),
        ]
        for proposal in propose(censuses, facts(censuses)):
            assert proposal.reasons
            assert all(reason.strip() for reason in proposal.reasons)


class TestAModuleWithNoSignalsAtAll:
    """Nothing is invented: no evidence means no answer, said out loud."""

    def test_no_layer_no_confidence_and_a_sentence_handing_the_choice_back(self) -> None:
        censuses = [
            a_module("shop.plumbing", imports=[an_import("shop.util")]),
            a_module("shop.util", entities=[an_entity("helper")]),
        ]
        proposal = only(censuses, "shop.plumbing")
        assert proposal.layer is None
        assert proposal.confidence == "low"
        assert proposal.reasons == (
            "nothing in its name, its imports or its place in the project points at "
            "a layer, so this one is yours to choose.",
        )

    def test_it_still_reports_what_the_module_holds(self) -> None:
        censuses = [
            a_module(
                "shop.plumbing",
                imports=[an_import("shop.util")],
                entities=[an_entity("Thing", category="class", kind_hint="MODEL")],
            ),
            a_module("shop.util", entities=[an_entity("helper")]),
        ]
        assert only(censuses, "shop.plumbing").kind_mix == (("MODEL", 1),)


# ---------------------------------------------------------------------------
# The reachability matrix
# ---------------------------------------------------------------------------


class TestALayeringTheMatrixForbids:
    """An illegal edge is a finding for the person, never an auto-fix."""

    @staticmethod
    def forbidden() -> list[ModuleCensus]:
        """Presentation reaching straight into infrastructure — the classic one."""
        return [
            a_module(
                "shop.web.routes",
                imports=[an_import("flask"), an_import("shop.storage.db")],
                entities=[an_entity("index")],
            ),
            a_module(
                "shop.storage.db",
                imports=[an_import("psycopg2")],
                entities=[an_entity("load")],
            ),
        ]

    def test_the_reason_names_both_modules_and_both_layers(self) -> None:
        censuses = self.forbidden()
        proposal = only(censuses, "shop.web.routes")
        finding = next(
            reason for reason in proposal.reasons if "shop.storage.db" in reason
        )
        assert "shop.web.routes" in finding
        assert "shop.storage.db" in finding
        assert Layer.PRESENTATION.value in finding
        assert Layer.INFRASTRUCTURE.value in finding

    def test_both_ends_of_the_edge_are_told(self) -> None:
        """Changing either end fixes it, so a reader of either file needs to know."""
        censuses = self.forbidden()
        by_module = {p.module: p for p in propose(censuses, facts(censuses))}
        for module in ("shop.web.routes", "shop.storage.db"):
            joined = " ".join(by_module[module].reasons)
            assert "shop.web.routes" in joined
            assert "shop.storage.db" in joined

    def test_confidence_drops_to_low_even_when_the_evidence_was_strong(self) -> None:
        censuses = self.forbidden()
        by_module = {p.module: p for p in propose(censuses, facts(censuses))}
        # Both would be "high" on their own evidence: name and library agree.
        assert by_module["shop.web.routes"].confidence == "low"
        assert by_module["shop.storage.db"].confidence == "low"

    def test_neither_layer_is_quietly_changed_to_make_the_matrix_happy(self) -> None:
        censuses = self.forbidden()
        by_module = {p.module: p for p in propose(censuses, facts(censuses))}
        assert by_module["shop.web.routes"].layer == Layer.PRESENTATION.value
        assert by_module["shop.storage.db"].layer == Layer.INFRASTRUCTURE.value

    def test_a_legal_edge_produces_no_finding(self) -> None:
        censuses = [
            a_module(
                "shop.web.routes",
                imports=[an_import("flask"), an_import("shop.domain.rules")],
                entities=[an_entity("index")],
            ),
            a_module("shop.domain.rules", entities=[an_entity("allowed")]),
        ]
        for proposal in propose(censuses, facts(censuses)):
            assert not any("layer rules" in reason for reason in proposal.reasons)
        by_module = {p.module: p for p in propose(censuses, facts(censuses))}
        assert by_module["shop.domain.rules"].confidence == "high"

    def test_an_edge_to_a_module_with_no_proposed_layer_is_not_a_finding(self) -> None:
        censuses = [
            a_module(
                "shop.web.routes",
                imports=[an_import("flask"), an_import("shop.plumbing")],
                entities=[an_entity("index")],
            ),
            a_module("shop.plumbing", imports=[an_import("shop.util")]),
            a_module("shop.util", entities=[an_entity("helper")]),
        ]
        for proposal in propose(censuses, facts(censuses)):
            assert not any("layer rules" in reason for reason in proposal.reasons)

    def test_a_deferred_import_is_not_checked_against_the_matrix(self) -> None:
        """Only load-time edges constrain a build, and only they are reported."""
        censuses = [
            a_module(
                "shop.web.routes",
                imports=[
                    an_import("flask"),
                    an_import("shop.storage.db", deferred=True),
                ],
                entities=[an_entity("index")],
            ),
            a_module(
                "shop.storage.db",
                imports=[an_import("psycopg2")],
                entities=[an_entity("load")],
            ),
        ]
        for proposal in propose(censuses, facts(censuses)):
            assert not any("layer rules" in reason for reason in proposal.reasons)


# ---------------------------------------------------------------------------
# T2 — kind mix
# ---------------------------------------------------------------------------


KIND_CASES: tuple[tuple[str, str, str], ...] = (
    # census hint, entity category, the language's kind
    ("EXCEPTION", "class", "EXCEPTION"),
    ("ENUM", "class", "ENUM"),
    ("MODEL", "class", "MODEL"),
    ("PROTOCOL", "class", "TYPE"),
    ("CLASS", "class", "SERVICE"),
    ("CONSTANT", "constant", "CONSTANT"),
    ("FUNCTION", "function", "FUNCTION"),
    ("FUNCTION", "async_function", "FUNCTION"),
)


class TestTheKindMix:
    """The census says what a definition looks like; this says what it would be."""

    @pytest.mark.parametrize(("hint", "category", "kind"), KIND_CASES)
    def test_each_hint_maps_onto_the_languages_taxonomy(
        self, hint: str, category: str, kind: str
    ) -> None:
        censuses = [
            a_module(
                "shop.thing",
                entities=[an_entity("Thing", category=category, kind_hint=hint)],
            )
        ]
        assert only(censuses, "shop.thing").kind_mix == ((kind, 1),)

    def test_an_unknown_hint_falls_back_on_the_category(self) -> None:
        """A census that grows an eighth hint widens the mix; it never crashes."""
        censuses = [
            a_module(
                "shop.thing",
                entities=[
                    an_entity("Thing", category="class", kind_hint="SOMETHING_NEW"),
                    an_entity("VALUE", category="constant", kind_hint="SOMETHING_NEW"),
                    an_entity("go", category="function", kind_hint="SOMETHING_NEW"),
                ],
            )
        ]
        assert only(censuses, "shop.thing").kind_mix == (
            ("CONSTANT", 1),
            ("FUNCTION", 1),
            ("SERVICE", 1),
        )

    def test_the_mix_is_counted_and_sorted_by_kind(self) -> None:
        censuses = [
            a_module(
                "shop.thing",
                entities=[
                    an_entity("go"),
                    an_entity("stop"),
                    an_entity("Thing", category="class", kind_hint="MODEL"),
                ],
            )
        ]
        assert only(censuses, "shop.thing").kind_mix == (("FUNCTION", 2), ("MODEL", 1))

    def test_private_definitions_are_counted_too(self) -> None:
        """A private function may become an INTERNAL component or a helper."""
        censuses = [
            a_module(
                "shop.thing",
                entities=[an_entity("go"), an_entity("_helper", public=False)],
            )
        ]
        assert only(censuses, "shop.thing").kind_mix == (("FUNCTION", 2),)

    def test_a_module_that_defines_nothing_has_an_empty_mix(self) -> None:
        censuses = [a_module("shop.thing", imports=[an_import("flask")])]
        assert only(censuses, "shop.thing").kind_mix == ()


# ---------------------------------------------------------------------------
# Which modules get a proposal
# ---------------------------------------------------------------------------


class TestTheModulesCovered:
    """One proposal per non-test module, sorted by module, no duplicates."""

    def test_test_files_get_no_proposal(self) -> None:
        censuses = [
            a_module("shop.thing", entities=[an_entity("go")]),
            a_module(
                "tests.test_thing",
                role="test",
                path="tests/test_thing.py",
                source_root=".",
                imports=[an_import("shop.thing")],
            ),
        ]
        assert [p.module for p in propose(censuses, facts(censuses))] == ["shop.thing"]

    def test_proposals_are_sorted_by_module(self) -> None:
        censuses = [
            a_module("shop.zebra"),
            a_module("shop.apple"),
            a_module("shop.mango"),
        ]
        modules = [p.module for p in propose(censuses, facts(censuses))]
        assert modules == sorted(modules)

    def test_two_files_claiming_one_name_produce_one_proposal(self) -> None:
        censuses = [
            a_module("shop.thing", path="src/shop/thing.py"),
            a_module("shop.thing", path="vendor/shop/thing.py", source_root="vendor"),
        ]
        proposals = propose(censuses, facts(censuses))
        assert [p.module for p in proposals] == ["shop.thing"]

    def test_an_empty_project_proposes_nothing(self) -> None:
        assert propose([], EMPTY_GRAPH) == ()


# ---------------------------------------------------------------------------
# T3 — the perimeter
# ---------------------------------------------------------------------------


class TestThePerimeterSuggestion:
    """What ``s0ma adopt init`` would write, shown before anything is written."""

    def test_the_ordinary_shape(self) -> None:
        sources = [
            a_source("shop", role="package_marker", path="src/shop/__init__.py"),
            a_source("shop.thing", path="src/shop/thing.py"),
            a_source("run", role="script", path="run.py", source_root="."),
            a_source("tests.test_thing", role="test", path="tests/test_thing.py", source_root="."),
        ]
        suggestion = suggest_perimeter(PROJECT_ROOT, sources, [])
        assert suggestion.source_roots == ("src",)
        assert suggestion.bootstrap_files == ("run.py",)
        assert suggestion.package_markers == ("src/shop/__init__.py",)
        assert suggestion.mode == PERIMETER_MODE == "migration"

    def test_a_dunder_main_is_bootstrap_even_inside_a_package(self) -> None:
        sources = [
            a_source("shop.__main__", path="src/shop/__main__.py"),
            a_source("shop.thing", path="src/shop/thing.py"),
        ]
        suggestion = suggest_perimeter(PROJECT_ROOT, sources, [])
        assert suggestion.bootstrap_files == ("src/shop/__main__.py",)

    def test_a_script_at_the_root_does_not_drag_the_root_into_the_source_roots(self) -> None:
        """``source_roots = [".", "src"]`` is a pair s0ma refuses; never suggest it."""
        sources = [
            a_source("shop.thing", path="src/shop/thing.py"),
            a_source("run", role="script", path="run.py", source_root="."),
        ]
        assert suggest_perimeter(PROJECT_ROOT, sources, []).source_roots == ("src",)

    def test_nested_source_roots_are_called_out_rather_than_suggested_quietly(self) -> None:
        sources = [
            a_source("shop.thing", path="src/shop/thing.py"),
            a_source("stray", path="stray.py", source_root="."),
        ]
        suggestion = suggest_perimeter(PROJECT_ROOT, sources, [])
        assert suggestion.source_roots == (".", "src")
        assert any("sit inside one another" in note for note in suggestion.notes)

    def test_a_flat_tree_with_tests_is_warned_about_the_overlap(self) -> None:
        sources = [
            a_source("thing", path="thing.py", source_root="."),
            a_source("tests.test_thing", role="test", path="tests/test_thing.py", source_root="."),
        ]
        suggestion = suggest_perimeter(PROJECT_ROOT, sources, [])
        assert suggestion.source_roots == (".",)
        note = next(note for note in suggestion.notes if "test root" in note)
        assert "s0ma adopt init" in note

    def test_an_empty_tree_says_so(self) -> None:
        suggestion = suggest_perimeter(PROJECT_ROOT, [], [])
        assert suggestion.source_roots == (".",)
        assert any("No Python files were found" in note for note in suggestion.notes)

    def test_lists_are_sorted_and_deduplicated(self) -> None:
        sources = [
            a_source("b", role="package_marker", path="src/b/__init__.py"),
            a_source("a", role="package_marker", path="src/a/__init__.py"),
            a_source("z", role="script", path="z.py", source_root="."),
            a_source("a_script", role="script", path="a_script.py", source_root="."),
        ]
        suggestion = suggest_perimeter(PROJECT_ROOT, sources, [])
        assert suggestion.package_markers == ("src/a/__init__.py", "src/b/__init__.py")
        assert suggestion.bootstrap_files == ("a_script.py", "z.py")


class TestAPackageInitThatContainsRealLogic:
    """Not a marker, and the reader is told why rather than left to notice."""

    @staticmethod
    def tree() -> tuple[list[SourceFile], list[ModuleCensus]]:
        working = a_module(
            "shop.helpers",
            path="src/shop/helpers/__init__.py",
            entities=[an_entity("thing"), an_entity("other")],
        )
        marker = a_module(
            "shop", role="package_marker", path="src/shop/__init__.py"
        )
        return [working.source, marker.source], [working, marker]

    def test_it_is_not_offered_as_a_package_marker(self) -> None:
        sources, censuses = self.tree()
        suggestion = suggest_perimeter(PROJECT_ROOT, sources, censuses)
        assert "src/shop/helpers/__init__.py" not in suggestion.package_markers
        assert suggestion.package_markers == ("src/shop/__init__.py",)

    def test_a_note_names_the_file_and_says_why(self) -> None:
        sources, censuses = self.tree()
        suggestion = suggest_perimeter(PROJECT_ROOT, sources, censuses)
        note = next(
            note for note in suggestion.notes if "src/shop/helpers/__init__.py" in note
        )
        assert "does real work" in note
        assert "2 things" in note
        assert "bootstrap_files" in note

    def test_the_note_describes_import_time_work_when_there_are_no_definitions(self) -> None:
        working = a_module(
            "shop.helpers", path="src/shop/helpers/__init__.py", top_level_effects=3
        )
        suggestion = suggest_perimeter(PROJECT_ROOT, [working.source], [working])
        note = next(note for note in suggestion.notes if "helpers" in note)
        assert "runs code the moment the package is imported" in note

    def test_notes_about_several_files_are_sorted_by_path(self) -> None:
        sources = [
            a_source("b", path="src/b/__init__.py"),
            a_source("a", path="src/a/__init__.py"),
        ]
        notes = suggest_perimeter(PROJECT_ROOT, sources, []).notes
        assert notes[0].startswith("`src/a/__init__.py`")
        assert notes[1].startswith("`src/b/__init__.py`")


class TestThePerimeterReadsNothing:
    """Retrofit rules R-1 and R-2: the root is accepted and never touched."""

    def test_a_root_that_does_not_exist_is_fine(self) -> None:
        sources = [a_source("shop.thing", path="src/shop/thing.py")]
        suggestion = suggest_perimeter(Path("/no/such/directory/anywhere"), sources, [])
        assert suggestion.source_roots == ("src",)

    def test_nothing_appears_beside_a_real_directory(self, tmp_path: Path) -> None:
        before = sorted(path.name for path in tmp_path.iterdir())
        suggest_perimeter(tmp_path, [a_source("shop.thing")], [])
        assert sorted(path.name for path in tmp_path.iterdir()) == before


# ---------------------------------------------------------------------------
# T4 — effort
# ---------------------------------------------------------------------------


EFFORT_CASES: tuple[tuple[str, dict[str, int], str], ...] = (
    ("a short module with a handful of definitions", {"sloc": 40}, "small"),
    ("a short module with nothing remarkable about it", {"sloc": 90, "entities": 4}, "small"),
    ("a few hundred lines", {"sloc": 200}, "medium"),
    ("a long module", {"sloc": 900}, "medium"),
    ("a long module with a lot in it", {"sloc": 900, "entities": 30}, "large"),
    ("a little work at import time", {"sloc": 40, "top_level_effects": 1}, "medium"),
    ("a lot of work at import time", {"sloc": 200, "top_level_effects": 5}, "large"),
    ("many definitions", {"sloc": 40, "entities": 12}, "medium"),
    ("very many definitions", {"sloc": 200, "entities": 30}, "large"),
)


class TestTheEffortEstimate:
    """Bands, not hours — and the estimate says so itself."""

    @pytest.mark.parametrize(("label", "shape", "band"), EFFORT_CASES)
    def test_the_bands_come_from_what_can_be_seen(
        self, label: str, shape: dict[str, int], band: str
    ) -> None:
        entities = [an_entity(f"thing_{index}") for index in range(shape.get("entities", 1))]
        census = a_module(
            "shop.thing",
            sloc=shape["sloc"],
            top_level_effects=shape.get("top_level_effects", 0),
            entities=entities,
        )
        estimate = estimate_effort([census], facts([census]))
        assert estimate.per_module == (("shop.thing", band),), label

    def test_being_caught_in_a_cycle_costs_a_point(self) -> None:
        tangled = [
            a_module("a", imports=[an_import("b")], sloc=900),
            a_module("b", imports=[an_import("a")], sloc=900),
        ]
        loose = [a_module("a", sloc=900)]
        assert estimate_effort(tangled, facts(tangled)).per_module[0][1] == "large"
        assert estimate_effort(loose, facts(loose)).per_module[0][1] == "medium"

    def test_a_file_that_will_not_parse_is_work_nobody_can_size(self) -> None:
        broken = a_module(
            "shop.thing", sloc=200, parse_error="line 3: unexpected indent"
        )
        estimate = estimate_effort([broken], facts([broken]))
        assert estimate.per_module == (("shop.thing", "large"),)

    def test_all_three_bands_are_always_reported(self) -> None:
        estimate = estimate_effort([a_module("shop.thing")], facts([a_module("shop.thing")]))
        assert [band for band, _ in estimate.bands] == ["small", "medium", "large"]
        assert dict(estimate.bands)["large"] == 0

    def test_the_counts_add_up_to_the_modules(self) -> None:
        censuses = [
            a_module("a", sloc=10),
            a_module("b", sloc=200),
            a_module("c", sloc=900, entities=[an_entity(f"x{i}") for i in range(30)]),
        ]
        estimate = estimate_effort(censuses, facts(censuses))
        assert sum(count for _, count in estimate.bands) == len(estimate.per_module) == 3

    def test_the_basis_says_the_bands_are_not_a_promise(self) -> None:
        estimate = estimate_effort([a_module("a")], facts([a_module("a")]))
        assert estimate.basis == EFFORT_BASIS
        assert "not a promise" in estimate.basis

    def test_test_files_are_left_out_the_way_proposals_leave_them_out(self) -> None:
        censuses = [
            a_module("shop.thing"),
            a_module("tests.test_thing", role="test", path="tests/test_thing.py"),
        ]
        estimate = estimate_effort(censuses, facts(censuses))
        assert [module for module, _ in estimate.per_module] == ["shop.thing"]

    def test_per_module_is_sorted(self) -> None:
        censuses = [a_module("shop.zebra"), a_module("shop.apple")]
        estimate = estimate_effort(censuses, facts(censuses))
        assert [module for module, _ in estimate.per_module] == ["shop.apple", "shop.zebra"]


# ---------------------------------------------------------------------------
# T5 — collisions with the framework's own names
# ---------------------------------------------------------------------------


class TestFrameworkComponentNames:
    """Read from core's registry, never copied into a list that could drift."""

    def test_the_names_come_from_a_real_bootstrap(self) -> None:
        names = framework_component_names()
        assert isinstance(names, frozenset)
        assert len(names) > 40
        assert "ComponentRegistry" in names
        assert "Contract" in names

    def test_reading_them_writes_nothing_and_needs_no_project(self, tmp_path: Path) -> None:
        framework_component_names.cache_clear()
        before = sorted(path.name for path in tmp_path.iterdir())
        assert framework_component_names()
        assert sorted(path.name for path in tmp_path.iterdir()) == before

    def test_the_answer_is_cached(self) -> None:
        first = framework_component_names()
        assert framework_component_names() is first


class TestCollisionWarnings:
    """Find the clash at scan time, not at registration time."""

    def test_a_name_the_framework_already_has_is_warned_about(self) -> None:
        censuses = [
            a_module(
                "shop.deals",
                entities=[an_entity("Contract", category="class", kind_hint="MODEL")],
            )
        ]
        warnings = collision_warnings(censuses)
        assert len(warnings) == 1
        assert warnings[0].code == WARNING_NAME_COLLISION == "ADOPT_SCAN_NAME_COLLISION"
        assert warnings[0].module == "shop.deals"
        assert "`Contract`" in warnings[0].message
        assert "rename" in warnings[0].message

    def test_an_ordinary_name_is_not_warned_about(self) -> None:
        censuses = [a_module("shop.deals", entities=[an_entity("Discount")])]
        assert collision_warnings(censuses) == ()

    def test_warnings_are_sorted_by_module_then_name(self) -> None:
        censuses = [
            a_module(
                "shop.zebra",
                entities=[an_entity("Contract", category="class", kind_hint="MODEL")],
            ),
            a_module(
                "shop.apple",
                entities=[
                    an_entity("Verifier", category="class", kind_hint="CLASS"),
                    an_entity("ComponentSpec", category="class", kind_hint="MODEL"),
                ],
            ),
        ]
        warnings = collision_warnings(censuses)
        assert [(w.module, w.message.split("`")[1]) for w in warnings] == [
            ("shop.apple", "ComponentSpec"),
            ("shop.apple", "Verifier"),
            ("shop.zebra", "Contract"),
        ]

    def test_a_test_file_is_not_warned_about(self) -> None:
        censuses = [
            a_module(
                "tests.test_deals",
                role="test",
                path="tests/test_deals.py",
                entities=[an_entity("Contract", category="class", kind_hint="MODEL")],
            )
        ]
        assert collision_warnings(censuses) == ()

    def test_a_private_definition_collides_too(self) -> None:
        """An INTERNAL component is registered under its name like any other."""
        censuses = [
            a_module(
                "shop.deals",
                entities=[an_entity("Contract", public=False, category="class")],
            )
        ]
        assert len(collision_warnings(censuses)) == 1


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def a_whole_project() -> tuple[list[SourceFile], list[ModuleCensus]]:
    """A small tree with one of everything the proposals have an opinion about."""
    censuses = [
        a_module("shop", role="package_marker", path="src/shop/__init__.py"),
        a_module(
            "shop.web.routes",
            imports=[an_import("flask"), an_import("shop.storage.db")],
            entities=[an_entity("index"), an_entity("health")],
            sloc=220,
        ),
        a_module(
            "shop.storage.db",
            imports=[an_import("psycopg2")],
            entities=[an_entity("load"), an_entity("Contract", category="class")],
        ),
        a_module(
            "shop.domain.rules",
            entities=[an_entity("allowed"), an_entity("MAX", category="constant",
                                                      kind_hint="CONSTANT")],
        ),
        a_module("shop.plumbing", imports=[an_import("shop.domain.rules")]),
        a_module("shop.helpers", path="src/shop/helpers/__init__.py",
                 entities=[an_entity("thing")]),
        a_module("run", role="script", path="run.py", source_root=".", has_main_guard=True),
        a_module(
            "tests.test_routes",
            role="test",
            path="tests/test_routes.py",
            source_root=".",
            imports=[an_import("shop.web.routes")],
        ),
    ]
    return [census.source for census in censuses], censuses


class TestDeterminism:
    """Two runs over the same facts diff empty — a golden report depends on it."""

    def test_the_same_input_twice_gives_the_same_json(self) -> None:
        sources, censuses = a_whole_project()
        graph = facts(censuses)

        def render() -> str:
            return dump_json(
                {
                    "proposals": [p.to_dict() for p in propose(censuses, graph)],
                    "perimeter": suggest_perimeter(PROJECT_ROOT, sources, censuses).to_dict(),
                    "effort": estimate_effort(censuses, graph).to_dict(),
                    "warnings": [w.to_dict() for w in collision_warnings(censuses)],
                }
            )

        assert render() == render()

    def test_the_input_order_does_not_change_the_output(self) -> None:
        sources, censuses = a_whole_project()
        shuffled = list(reversed(censuses))
        shuffled_sources = list(reversed(sources))

        assert dump_json(
            [p.to_dict() for p in propose(censuses, facts(censuses))]
        ) == dump_json([p.to_dict() for p in propose(shuffled, facts(shuffled))])
        assert dump_json(
            estimate_effort(censuses, facts(censuses)).to_dict()
        ) == dump_json(estimate_effort(shuffled, facts(shuffled)).to_dict())
        assert dump_json(
            suggest_perimeter(PROJECT_ROOT, sources, censuses).to_dict()
        ) == dump_json(suggest_perimeter(PROJECT_ROOT, shuffled_sources, shuffled).to_dict())
        assert dump_json(
            [w.to_dict() for w in collision_warnings(censuses)]
        ) == dump_json([w.to_dict() for w in collision_warnings(shuffled)])

    def test_already_classified_censuses_give_the_same_answer(self) -> None:
        """``propose`` classifies imports itself, and classification is idempotent."""
        censuses = [
            a_module(
                "shop.web.routes",
                imports=[
                    an_import("flask", origin=ORIGIN_THIRD_PARTY),
                    an_import("shop.storage.db", origin=ORIGIN_FIRST_PARTY),
                ],
                entities=[an_entity("index")],
            ),
            a_module(
                "shop.storage.db",
                imports=[an_import("psycopg2", origin=ORIGIN_THIRD_PARTY)],
                entities=[an_entity("load")],
            ),
        ]
        raw = [
            a_module(
                "shop.web.routes",
                imports=[an_import("flask"), an_import("shop.storage.db")],
                entities=[an_entity("index")],
            ),
            a_module(
                "shop.storage.db",
                imports=[an_import("psycopg2")],
                entities=[an_entity("load")],
            ),
        ]
        assert dump_json(
            [p.to_dict() for p in propose(censuses, facts(censuses))]
        ) == dump_json([p.to_dict() for p in propose(raw, facts(raw))])


# ---------------------------------------------------------------------------
# The whole thing, read as a person would read it
# ---------------------------------------------------------------------------


class TestTheAdviceReadsLikeAdvice:
    """Written for an intelligent non-programmer, not for a compiler."""

    def test_no_reason_uses_the_word_this_project_has_banned(self) -> None:
        sources, censuses = a_whole_project()
        graph = facts(censuses)
        text = " ".join(
            [
                *(reason for p in propose(censuses, graph) for reason in p.reasons),
                *suggest_perimeter(PROJECT_ROOT, sources, censuses).notes,
                *(w.message for w in collision_warnings(censuses)),
                estimate_effort(censuses, graph).basis,
            ]
        )
        assert "payload" not in text.lower()

    def test_the_framework_is_always_spelled_with_a_zero(self) -> None:
        sources, censuses = a_whole_project()
        text = " ".join(
            [
                *suggest_perimeter(PROJECT_ROOT, sources, censuses).notes,
                *(w.message for w in collision_warnings(censuses)),
            ]
        )
        assert "soma" not in text.lower().replace("s0ma", "")

    def test_every_sentence_ends_like_a_sentence(self) -> None:
        sources, censuses = a_whole_project()
        graph = facts(censuses)
        sentences = [
            *(reason for p in propose(censuses, graph) for reason in p.reasons),
            *suggest_perimeter(PROJECT_ROOT, sources, censuses).notes,
            *(w.message for w in collision_warnings(censuses)),
            estimate_effort(censuses, graph).basis,
        ]
        assert sentences
        for sentence in sentences:
            assert sentence.endswith("."), sentence
