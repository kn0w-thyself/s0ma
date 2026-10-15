"""Gates for D4b — the studi0 provider.

Milestone D4 of the docs-function plan (internal) §9, over
``s0ma_dsl.docs_model.providers_studi0``. What these tests hold in place:

* **the declared table is the served table, from this side too.** The
  provider reads ``ROUTE_TABLE``; these tests read the ``if path ==``
  chain of ``route_request`` itself, out of the same committed build.
  Two independent readings of two different things, asserted equal —
  which is the only way a table meant for readers can be known to
  describe the routes a browser actually gets.
* **the deferral is over, and the conventions that ended it are pinned.**
  Three of studi0's five routes had no id until D5a completed the form:
  a path segment may now carry a dot, and the root route is addressed as
  ``studi0:action/index`` while its ``public_name`` stays ``/``. All five
  routes are emitted, nothing is deferred, and both conventions are
  asserted here on real records as well as through the id machinery — so
  a future route that cannot be addressed is counted rather than lost.
* **every binding resolves.** Each route names the declarations that
  answer it, and every one of those is a component studi0 really
  registers.
* **nothing is imported.** The provider never imports ``s0ma_studi0``:
  that package bootstraps its built modules at import time, and reading
  a constant is not worth executing a package's registrations. Asserted
  structurally over the module's own source.
* **the viewer's gestures stay undescribed.** ``app.js`` exposes no
  enumerable action set, so the provider emits none. The absence is
  pinned, with the property that would have to change first.
* **the output is deterministic.** Same checkout, same records, same
  bytes; no absolute path anywhere; a change to one built file moves the
  records read from that file and no others.
* **it composes clean.** Zero findings through every C2 gate, floors
  included.

The live repository is the fixture wherever the question is "what does
studi0 declare"; a copied tree is the fixture wherever the question is
"what happens when it declares something else", so no test edits the
checkout.
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

import pytest

from s0ma_dsl.docs_model.compose import compose
from s0ma_dsl.docs_model.ids import (
    DocsIdError,
    id_form,
    studi0_action_id,
    studi0_public_name,
)
from s0ma_dsl.docs_model.providers import ProviderRegistry
from s0ma_dsl.docs_model.providers_repo import decision_of, facts_of
from s0ma_dsl.docs_model.providers_studi0 import (
    BUILT_DIR,
    FLOORS,
    NARRATION_SOURCE,
    PROVIDER_ID,
    SELF_CONTEXT_SOURCE,
    SERVER_SOURCE,
    STATE_SOURCE,
    UNADDRESSABLE_ROUTES,
    WATCH_SOURCE,
    Studi0Provider,
    Studi0ProviderError,
)
from s0ma_dsl.docs_model.records import SCHEMA, AuthorityRef, SurfaceRecord
from s0ma_dsl.docs_model.serialize import serialize_bundle
from s0ma_dsl.docs_model.validate import validate_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "s0ma_dsl"
    / "docs_model"
    / "providers_studi0.py"
)
APP_JS = REPO_ROOT / "packages" / "s0ma-studi0" / "s0ma_src" / "assets" / "app.js"

RELEASE = "0.18.1"

#: Every file the provider reads, so a fixture checkout can carry the
#: same five and nothing else.
SOURCES = (
    SERVER_SOURCE,
    STATE_SOURCE,
    WATCH_SOURCE,
    NARRATION_SOURCE,
    SELF_CONTEXT_SOURCE,
)


@pytest.fixture(scope="module")
def provider() -> Studi0Provider:
    return Studi0Provider(REPO_ROOT)


# ---------------------------------------------------------------------------
# Reading the serving chain, independently of the provider
# ---------------------------------------------------------------------------


def _literals(node: ast.expr) -> list[str]:
    """Every string constant in ``node``, flattening one sequence level."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return [value for element in node.elts for value in _literals(element)]
    return []


def _served_paths() -> set[str]:
    """Every path ``route_request`` decides on, read from the committed build.

    Deliberately *not* the reading the provider does. The provider asks
    the declared table what studi0 serves; this asks the function that
    serves it. The whole value of D4a's promotion is that those two
    answers are the same, and an assertion is the only thing that keeps
    them so.
    """
    tree = ast.parse((REPO_ROOT / SERVER_SOURCE).read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "route_request"
    )
    found: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Compare):
            continue
        if not (isinstance(node.left, ast.Name) and node.left.id == "path"):
            continue
        for operator, comparator in zip(node.ops, node.comparators, strict=True):
            if isinstance(operator, ast.Eq | ast.In):
                found.update(_literals(comparator))
    # ``route_request`` answers "" and "/" alike; no HTTP request line
    # can carry the empty spelling, so the two fold into the one a
    # caller can ask for.
    return {path or "/" for path in found}


def _surfaces(provider: Studi0Provider) -> tuple[SurfaceRecord, ...]:
    return tuple(
        item.record for item in provider.provide().records if isinstance(item.record, SurfaceRecord)
    )


def _authorities(provider: Studi0Provider) -> dict[str, AuthorityRef]:
    return {
        item.record.id: item.record
        for item in provider.provide().records
        if isinstance(item.record, AuthorityRef)
    }


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------


class TestTheRoutesAreTheServedRoutes:
    """The declared table, the served chain, and the records agree."""

    def test_the_serving_chain_is_readable_at_all(self) -> None:
        """Anti-vacuity: an empty reading would make every parity test pass."""
        assert _served_paths(), "no route literals were read from route_request"

    def test_every_served_route_is_emitted_or_counted(
        self, provider: Studi0Provider
    ) -> None:
        emitted = {surface.public_name for surface in _surfaces(provider)}
        assert emitted | set(provider.deferred_routes()) == _served_paths()

    def test_no_route_is_both_emitted_and_deferred(self, provider: Studi0Provider) -> None:
        emitted = {surface.public_name for surface in _surfaces(provider)}
        assert not emitted & set(provider.deferred_routes())

    def test_the_emitted_routes_are_all_five_declared_routes(
        self, provider: Studi0Provider
    ) -> None:
        """D5a's emission: what D4b counted as deferrals is now records."""
        assert {surface.id for surface in _surfaces(provider)} == {
            "studi0:action/index",
            "studi0:action/assets/app.css",
            "studi0:action/assets/app.js",
            "studi0:action/api/state",
            "studi0:action/api/graph",
        }

    def test_the_id_drops_the_slash_and_the_served_name_keeps_it(
        self, provider: Studi0Provider
    ) -> None:
        """The ratified convention (B7 §6 row 5), asserted on real records."""
        for surface in _surfaces(provider):
            assert not surface.id.removeprefix("studi0:action/").startswith("/")
            assert surface.public_name.startswith("/")

    def test_every_id_and_served_name_agree_through_the_id_machinery(
        self, provider: Studi0Provider
    ) -> None:
        """The stronger form of the old ``endswith`` check.

        ``endswith`` could say the two agreed while the root convention
        was absent; it cannot say it once ``studi0:action/index`` serves
        ``/``. So the pairing is asserted through the two functions that
        define it, in both directions, which is what makes the root a
        documented map rather than a special case in a provider.
        """
        for surface in _surfaces(provider):
            assert studi0_public_name(surface.id) == surface.public_name
            assert studi0_action_id(surface.public_name) == surface.id

    def test_the_root_route_is_addressed_by_the_documented_word(
        self, provider: Studi0Provider
    ) -> None:
        """D5a's root convention, on the record that needed it."""
        by_name = {surface.public_name: surface for surface in _surfaces(provider)}
        assert by_name["/"].id == "studi0:action/index"

    def test_an_asset_route_keeps_its_filename(self, provider: Studi0Provider) -> None:
        """Not ``app-css``: the segment is a filename, and that is its name."""
        by_name = {surface.public_name: surface for surface in _surfaces(provider)}
        assert by_name["/assets/app.css"].id == "studi0:action/assets/app.css"
        assert by_name["/assets/app.js"].id == "studi0:action/assets/app.js"

    def test_every_surface_is_on_the_studi0_channel(self, provider: Studi0Provider) -> None:
        for surface in _surfaces(provider):
            assert surface.channel == "studi0"

    def test_every_route_names_components_this_package_registers(
        self, provider: Studi0Provider
    ) -> None:
        known = set(provider.component_ids())
        for surface in _surfaces(provider):
            assert surface.component_refs, surface.id
            assert set(surface.component_refs) <= known, surface.id

    def test_no_route_record_needs_a_manual_exception(
        self, provider: Studi0Provider
    ) -> None:
        """What D4a bought, stated as a test.

        Before the table was package data, every studi0 surface record
        carried an exception saying a person had transcribed its facts.
        A record here that still needed one would mean the promotion did
        not actually move the source of truth.
        """
        for surface in _surfaces(provider):
            assert surface.manual_exception == ""

    def test_the_side_effect_facts_are_declared_not_guessed(
        self, provider: Studi0Provider
    ) -> None:
        """Read off the table, which is why the three static routes differ.

        HTTP's promise about ``GET`` would make all five of these reads.
        studi0 declares otherwise about the three routes that hand back
        bytes the build embedded, and the whole point of D4a's promotion
        is that the record says what the package says. Before D5a only
        the two ``read`` routes were emitted, so this could not tell the
        difference; now it can, and it asserts the split.
        """
        declared = {surface.public_name: surface.side_effects for surface in _surfaces(provider)}
        assert declared == {
            "/": ("none",),
            "/assets/app.css": ("none",),
            "/assets/app.js": ("none",),
            "/api/state": ("read",),
            "/api/graph": ("read",),
        }

    def test_the_graph_route_carries_its_error(self, provider: Studi0Provider) -> None:
        by_id = {surface.id: surface for surface in _surfaces(provider)}
        assert by_id["studi0:action/api/graph"].errors == ("NOT_BUILT",)
        assert by_id["studi0:action/api/state"].errors == ()

    def test_every_intent_is_one_line_of_real_prose(
        self, provider: Studi0Provider
    ) -> None:
        for surface in _surfaces(provider):
            assert surface.intent.strip()
            assert "\n" not in surface.intent
            assert surface.intent == " ".join(surface.intent.split())


class TestTheIdFormGapIsClosed:
    """The three routes that had no id have one, and the form is why.

    D4b's version of this class pinned the deferral and said the day the
    form grew these would turn red, which is the signal to emit the
    records. D5a grew it. The same questions are asked from the other
    side now: nothing is deferred, every served route is addressable,
    and the deferral machinery still refuses what it should so a future
    gap is counted rather than invented around.
    """

    def test_nothing_is_deferred(self, provider: Studi0Provider) -> None:
        assert provider.deferred_routes() == ()
        assert UNADDRESSABLE_ROUTES == ()

    def test_every_served_route_is_addressable(self) -> None:
        for route in ("/", "/assets/app.css", "/assets/app.js", "/api/state", "/api/graph"):
            assert id_form(studi0_action_id(route)) == "studi0"

    @pytest.mark.parametrize(
        "route",
        [
            "/Assets/app.css",
            "/assets/app..css",
            "/assets/.css",
            "//api/graph",
            "/index",
        ],
    )
    def test_a_route_the_form_still_cannot_address_is_refused(self, route: str) -> None:
        """The guard the deferral machinery exists for, still armed.

        Four of these are outside the charset. ``/index`` is inside it
        and refused anyway: it wants the id the root convention already
        holds, and two routes on one id is the failure a documented
        normalization has to answer for.
        """
        with pytest.raises(DocsIdError):
            studi0_action_id(route)

    def test_a_route_the_form_cannot_address_is_counted_not_dropped(
        self, tmp_path: Path
    ) -> None:
        """The machinery, exercised against a table that needs it.

        Nothing studi0 declares today reaches this branch, so the branch
        is proved on a copied checkout whose table names a route the form
        refuses. A provider that had quietly stopped counting would emit
        five records and say nothing.
        """
        root = _checkout(tmp_path)
        text = (root / SERVER_SOURCE).read_text(encoding="utf-8")
        (root / SERVER_SOURCE).write_text(
            text.replace('"path": "/assets/app.css"', '"path": "/assets/App.css"', 1),
            encoding="utf-8",
        )
        provider = Studi0Provider(root)
        assert provider.deferred_routes() == ("/assets/App.css",)
        assert "/assets/App.css" not in {
            surface.public_name for surface in _surfaces(provider)
        }

    def test_no_invented_id_stands_in_for_a_refused_one(
        self, provider: Studi0Provider
    ) -> None:
        """No record addresses a route by anything but its own path."""
        served = _served_paths()
        for surface in _surfaces(provider):
            assert surface.public_name in served


class TestTheViewerGesturesStayUndescribed:
    """studi0's gestures are not declarable, so nothing here describes them.

    Architecture §7.5: "UI labels are consumers of stable surface ids;
    they are not the canonical source of capability existence." The
    handlers in ``app.js`` are anonymous closures passed to a helper, so
    the only enumerable thing about them is their button label — and
    scraping labels is the guessing this whole milestone exists to
    replace.
    """

    def test_app_js_still_exposes_no_enumerable_action_set(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        assert "data-action" not in source
        assert "ACTIONS" not in source
        # The property that would have to change first: gestures are
        # built by passing an anonymous function to one helper.
        assert 'toolbarButton("fit", function ()' in source

    def test_no_record_describes_a_gesture(self, provider: Studi0Provider) -> None:
        served = _served_paths()
        for surface in _surfaces(provider):
            assert surface.public_name in served


# ---------------------------------------------------------------------------
# The declared contracts
# ---------------------------------------------------------------------------


class TestTheDeclaredContracts:
    """The wire, serving, watch and narration contracts, as data."""

    def test_every_contract_is_present(self, provider: Studi0Provider) -> None:
        assert set(_authorities(provider)) == {
            "authority:declared/studi0.narration-event",
            "authority:declared/studi0.presence-marker",
            "authority:declared/studi0.serving-contract",
            "authority:declared/studi0.watch-contract",
            "authority:declared/studi0.wire-graph",
            "authority:declared/studi0.wire-state",
        }

    def test_every_contract_declares_itself_declared(
        self, provider: Studi0Provider
    ) -> None:
        for record in _authorities(provider).values():
            assert record.authority_class == "declared"
            assert decision_of(record.status) == "Declared"

    def test_the_wire_identities_are_the_frozen_ones(
        self, provider: Studi0Provider
    ) -> None:
        """The three schema strings B3 found pinned only in a studi0 test.

        Written out here as literals on purpose: this is the documentation
        side's own pin, and a promotion that moved the values as well as
        their home would otherwise pass unnoticed on both sides.
        """
        state = facts_of(_authorities(provider)["authority:declared/studi0.wire-state"].status)
        graph = facts_of(_authorities(provider)["authority:declared/studi0.wire-graph"].status)
        assert state["schema"] == "s0ma-studi0-state@2"
        assert state["keys"] == "build_status,narration,schema,seq,stale_modules"
        assert state["narration_keys"] == "entries,invalid,total"
        assert graph["schema"] == "s0ma-studi0-graph@1"
        assert graph["keys"] == "graph,schema,seq"
        assert graph["carries"] == "s0ma-graph@2"

    def test_the_watch_contract_carries_its_three_guarantees(
        self, provider: Studi0Provider
    ) -> None:
        facts = facts_of(_authorities(provider)["authority:declared/studi0.watch-contract"].status)
        assert facts["poll_seconds"] == "0.75"
        assert facts["writes"] == "none"
        assert facts["raises"] == "never"

    def test_the_narration_event_contract_is_the_frozen_one(
        self, provider: Studi0Provider
    ) -> None:
        facts = facts_of(
            _authorities(provider)["authority:declared/studi0.narration-event"].status
        )
        assert facts["type"] == "work.narrated"
        assert facts["phases"] == "orient,author,verify,move_on"
        assert facts["window"] == "50"
        assert facts["log"] == ".s0ma/studi0/session.jsonl"

    def test_the_presence_marker_is_the_only_file_studi0_writes(
        self, provider: Studi0Provider
    ) -> None:
        facts = facts_of(
            _authorities(provider)["authority:declared/studi0.presence-marker"].status
        )
        assert facts["path"] == ".s0ma/studi0/active.json"

    def test_the_serving_contract_says_where_studi0_binds(
        self, provider: Studi0Provider
    ) -> None:
        facts = facts_of(
            _authorities(provider)["authority:declared/studi0.serving-contract"].status
        )
        assert facts["host"] == "127.0.0.1"
        assert facts["methods"] == "GET"
        assert facts["unserved"] == "NOT_FOUND"
        assert facts["routes"] == str(len(_served_paths()))

    def test_the_api_routes_cite_the_contracts_that_govern_them(
        self, provider: Studi0Provider
    ) -> None:
        """Only the two API routes: an asset route answers to no document.

        The provider's ``_governing`` has always said so; before D5a the
        three routes that cite nothing were not emitted, so the claim was
        untestable from this side. It is testable now, and the honest
        shape is a split rather than "every surface cites something".
        """
        known = set(_authorities(provider))
        citing = {
            surface.public_name for surface in _surfaces(provider) if surface.governed_by
        }
        assert citing == {"/api/state", "/api/graph"}
        for surface in _surfaces(provider):
            assert set(surface.governed_by) <= known

    def test_the_candidate_truth_language_note_is_not_cited(
        self, provider: Studi0Provider
    ) -> None:
        """A candidate is not an authority (plan §1.2 fact 13)."""
        text = MODULE.read_text(encoding="utf-8")
        assert "studi0-visual-truth-language.md" in text, "the exclusion is unexplained"
        for record in provider.provide().records:
            assert "truth-language" not in record.record.id
            assert "visual-truth" not in record.provenance.source


# ---------------------------------------------------------------------------
# Provenance, determinism, and the reading posture
# ---------------------------------------------------------------------------


class TestHowItReads:
    def test_nothing_imports_the_package_it_describes(self) -> None:
        """Reading a constant is not worth executing a package's registrations."""
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not any(name.startswith("s0ma_studi0") for name in imported)
        assert not any(name == "s0ma" or name.startswith("s0ma.") for name in imported)

    def test_every_record_is_stamped_with_the_file_it_was_read_from(
        self, provider: Studi0Provider
    ) -> None:
        for item in provider.provide().records:
            assert item.provenance.adapter_id == PROVIDER_ID
            assert item.provenance.schema_version == SCHEMA
            assert item.provenance.source in SOURCES
            assert len(item.provenance.source_sha256) == 64

    def test_every_source_is_a_committed_file_named_relatively(
        self, provider: Studi0Provider
    ) -> None:
        for source, _ in provider.provide().sources():
            assert not source.startswith("/")
            assert source.startswith(BUILT_DIR)
            assert (REPO_ROOT / source).is_file()

    def test_no_record_names_this_machine(self, provider: Studi0Provider) -> None:
        text = serialize_bundle(
            compose(ProviderRegistry.of(provider), release_version=RELEASE).bundle
        )
        assert str(REPO_ROOT) not in text
        assert str(REPO_ROOT.resolve()) not in text

    def test_two_readings_of_one_checkout_are_the_same_bytes(self) -> None:
        first = compose(
            ProviderRegistry.of(Studi0Provider(REPO_ROOT)), release_version=RELEASE
        )
        second = compose(
            ProviderRegistry.of(Studi0Provider(REPO_ROOT)), release_version=RELEASE
        )
        assert serialize_bundle(first.bundle) == serialize_bundle(second.bundle)

    def test_provide_returns_the_same_records_every_time(
        self, provider: Studi0Provider
    ) -> None:
        assert provider.provide() is provider.provide()


# ---------------------------------------------------------------------------
# A copied checkout: what happens when studi0 declares something else
# ---------------------------------------------------------------------------


def _checkout(root: Path) -> Path:
    """The five files the provider reads, copied at their real paths."""
    for relative in SOURCES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    return root


def _stamps(provider: Studi0Provider) -> dict[str, object]:
    """Each record's id mapped to the provenance it carries."""
    return {item.record.id: item.provenance for item in provider.provide().records}


def _rewrite(root: Path, relative: str, old: str, new: str) -> None:
    """One targeted edit inside a copied build."""
    path = root / relative
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{relative} does not contain {old!r}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


class TestWhenTheBuildMoves:
    def test_a_copy_reads_exactly_as_the_checkout_does(self, tmp_path: Path) -> None:
        copied = Studi0Provider(_checkout(tmp_path)).provide()
        assert copied == Studi0Provider(REPO_ROOT).provide()

    def test_editing_one_built_file_restamps_only_its_records(
        self, tmp_path: Path
    ) -> None:
        """A digest moves with the file it is a digest of, and no other."""
        root = _checkout(tmp_path)
        before = _stamps(Studi0Provider(root))
        _rewrite(root, WATCH_SOURCE, "poll_seconds: float = 0.75", "poll_seconds: float = 0.5")
        after = _stamps(Studi0Provider(root))

        moved = {key for key in before if before[key] != after[key]}
        assert moved == {"authority:declared/studi0.watch-contract"}
        assert facts_of(
            next(
                item.record.status
                for item in Studi0Provider(root).provide().records
                if item.record.id == "authority:declared/studi0.watch-contract"
                and isinstance(item.record, AuthorityRef)
            )
        )["poll_seconds"] == "0.5"

    def test_a_missing_build_is_refused_by_name(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        (root / STATE_SOURCE).unlink()
        with pytest.raises(Studi0ProviderError, match="studi0_state.py"):
            Studi0Provider(root)

    def test_a_table_that_lost_its_declaration_is_refused(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        _rewrite(root, SERVER_SOURCE, "ROUTE_TABLE: tuple", "_RETIRED_TABLE: tuple")
        with pytest.raises(Studi0ProviderError, match="declares no ROUTE_TABLE"):
            Studi0Provider(root)

    def test_an_entry_missing_a_key_is_refused_by_name(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        _rewrite(root, SERVER_SOURCE, '        "effects": "read",\n', "", )
        with pytest.raises(Studi0ProviderError, match="declares no effects"):
            Studi0Provider(root)

    def test_a_binding_nothing_registers_is_refused(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        _rewrite(
            root,
            SERVER_SOURCE,
            "studi0_state::state_document",
            "studi0_state::state_documnet",
        )
        with pytest.raises(Studi0ProviderError, match="which studi0 does not register"):
            Studi0Provider(root)

    def test_a_flat_binding_is_refused(self, tmp_path: Path) -> None:
        """And on the root route, which has no id — so the check is not skipped.

        The first entry of the table is ``/``, the route ``§5``'s id form
        cannot spell. Reading it is still part of reading the table
        honestly: a defect there must not hide behind the gap that keeps
        the route out of the record set.
        """
        root = _checkout(tmp_path)
        _rewrite(root, SERVER_SOURCE, "studi0_server::route_request", "route_request")
        with pytest.raises(Studi0ProviderError, match="which studi0 does not register"):
            Studi0Provider(root)

    def test_a_side_effect_word_outside_the_vocabulary_is_refused(
        self, tmp_path: Path
    ) -> None:
        root = _checkout(tmp_path)
        _rewrite(root, SERVER_SOURCE, '"effects": "read"', '"effects": "cheap"')
        with pytest.raises(Studi0ProviderError, match="cheap"):
            Studi0Provider(root)

    def test_a_bound_that_stopped_being_a_number_is_refused(
        self, tmp_path: Path
    ) -> None:
        root = _checkout(tmp_path)
        _rewrite(root, NARRATION_SOURCE, "NARRATION_WINDOW: int = 50", "NARRATION_WINDOW: int = ()")
        with pytest.raises(Studi0ProviderError, match="NARRATION_WINDOW"):
            Studi0Provider(root)

    def test_a_wire_identity_that_vanished_is_refused_by_name(
        self, tmp_path: Path
    ) -> None:
        root = _checkout(tmp_path)
        _rewrite(root, STATE_SOURCE, "CARRIED_GRAPH_SCHEMA: str", "_GONE: str")
        with pytest.raises(Studi0ProviderError, match="CARRIED_GRAPH_SCHEMA"):
            Studi0Provider(root)

    def test_an_empty_inventory_is_refused(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        (root / SELF_CONTEXT_SOURCE).write_text('{"components": []}', encoding="utf-8")
        with pytest.raises(Studi0ProviderError, match="lists no components"):
            Studi0Provider(root)


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


class TestItComposes:
    """The records have to survive C2's gates to be worth citing."""

    def test_the_provider_composes_with_nothing_reported(
        self, provider: Studi0Provider
    ) -> None:
        composition = compose(ProviderRegistry.of(provider), release_version=RELEASE)
        assert composition.findings == ()
        assert composition.ok

    def test_every_gate_is_green_over_the_composed_bundle(
        self, provider: Studi0Provider
    ) -> None:
        composition = compose(ProviderRegistry.of(provider), release_version=RELEASE)
        assert (
            validate_bundle(
                composition.bundle,
                results=composition.results,
                floors=dict(FLOORS),
                external_ids=provider.external_ids(),
                claims=(),
            )
            == ()
        )

    def test_the_floors_are_met_by_the_live_reading(
        self, provider: Studi0Provider
    ) -> None:
        counts = provider.provide().counts()
        for (adapter, group), floor in FLOORS.items():
            assert adapter == PROVIDER_ID
            assert counts[group] >= floor

    def test_a_provider_that_saw_nothing_would_trip_the_floors(
        self, tmp_path: Path
    ) -> None:
        """The floors are worth having only if a thin reading fails them.

        A route table emptied to its one page route is exactly the
        failure a floor exists to catch: a source that moved and a
        provider that consequently sees almost nothing. Before D5a that
        entry could not be addressed and the reading was empty; now it
        is one surface against a floor of four, which is the same
        finding for the same reason and a stronger test — an empty
        reading would trip any floor at all, and one this near the truth
        proves the number was chosen.
        """
        root = _checkout(tmp_path)
        text = (root / SERVER_SOURCE).read_text(encoding="utf-8")
        opening = text.index("ROUTE_TABLE: tuple[dict[str, str], ...] = (")
        closing = text.index("\n)\n", opening)
        emptied = (
            text[:opening]
            + "ROUTE_TABLE: tuple[dict[str, str], ...] = (\n"
            + "    {\n"
            + '        "path": "/",\n'
            + '        "method": "GET",\n'
            + '        "purpose": "The sh0w page.",\n'
            + '        "effects": "none",\n'
            + '        "answered_by": "studi0_server::route_request",\n'
            + '        "media_type": "text/html; charset=utf-8",\n'
            + '        "errors": "",\n'
            + "    },"
            + text[closing:]
        )
        (root / SERVER_SOURCE).write_text(emptied, encoding="utf-8")

        result = Studi0Provider(root).provide()
        assert result.counts()["surfaces"] == 1
        assert result.counts()["surfaces"] < FLOORS[(PROVIDER_ID, "surfaces")]
        composition = compose(
            ProviderRegistry.of(Studi0Provider(root)), release_version=RELEASE
        )
        findings = validate_bundle(
            composition.bundle,
            results=composition.results,
            floors=dict(FLOORS),
            claims=(),
        )
        assert any(finding.code == "DOC_GATE_VACUOUS" for finding in findings), findings
