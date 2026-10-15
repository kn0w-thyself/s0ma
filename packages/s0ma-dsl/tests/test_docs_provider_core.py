"""Gates for C3 — the core provider, held against the live boundary.

Milestone C3 of the docs-function plan (internal) §8, completed by D5a.
The provider reads ``s0ma-core`` in process, so almost every check here
can be made against the thing itself rather than against a fixture: the
registry is asked how many components it has, the application is asked
what routes it serves, the MCP server is asked what it lists, and the
package is asked what it exports. A fixture would only prove that this
file agrees with itself.

What these tests hold in place:

* **parity with the live boundary** — the component inventory equals
  core's own ``EXPECTED_FRAMEWORK_COMPONENT_COUNT`` (read live, never
  copied here), every ``APIRoute`` of the application appears exactly
  once, FastAPI's own documentation routes appear not at all, every
  served MCP tool and resource is present — templates included, with
  their braces — and every name in ``s0ma.__all__`` that the bootstrap
  does not register has a ``python:`` record;
* **the provider contract** — sorted, normalized, four-part provenance
  on every record, and a full sha256 for every source;
* **determinism** — two readings are the same bytes, in this process
  and in a fresh one under three hash seeds;
* **no machine paths** — nothing absolute reaches the serialized build;
* **anti-vacuity** — the floors this provider ships are met, and a floor
  raised past the truth reports a vacuous gate;
* **composition** — the provider registers, composes with no findings,
  and every gate over the composed bundle is silent when it is handed
  the component and example ids the model addresses but does not hold.

Two things the milestone asked for and the model could not carry were
recorded here as tests rather than as prose, so that the day a form or
a field arrived, the test that said "there is no way to say this" would
fail and point at the milestone that changed. One of them has:
:class:`TestPythonSurfaceGap` now asserts the emission D5a's
``python:`` form unlocked, and :class:`TestMcpResourceSurfaces` does the
same for the resource family its braced-template charset unlocked.
:class:`TestComponentsAreNotRecords` is the third: D6 ruled that a
component's facts live in a rendered artifact rather than in a seventh
bundle group, so the class keeps its original claim — a component is an
external id, not a record — and gained the assertion that says where the
facts went instead.

Nothing under ``scripts/spikes`` is imported. B3 proved this reading and
is evidence, not a dependency; a test asserts that of the module too.
"""

from __future__ import annotations

import ast
import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from s0ma._bootstrap import EXPECTED_FRAMEWORK_COMPONENT_COUNT, bootstrap_register
from s0ma.models import EntityRef, SourceSpan
from s0ma.registry import ComponentRegistry

from s0ma_dsl.docs_model.application import SIDE_EFFECT_ALLOWANCES
from s0ma_dsl.docs_model.compose import Composition, compose
from s0ma_dsl.docs_model.ids import id_form, is_valid_id
from s0ma_dsl.docs_model.providers import (
    ProviderRegistry,
    record_key,
    sort_records,
)
from s0ma_dsl.docs_model.providers_core import (
    _HAND_CLASSIFIED,
    BOOTSTRAP_SOURCE,
    EXPORTS_SOURCE,
    FLOORS,
    MCP_SOURCE,
    PROVIDER_ID,
    REST_SOURCE,
    STORES_SOURCE,
    CoreProvider,
    CoreProviderError,
    _route_effects,
)
from s0ma_dsl.docs_model.records import SCHEMA, DocumentRecord, SurfaceRecord
from s0ma_dsl.docs_model.serialize import serialize_bundle
from s0ma_dsl.docs_model.validate import DOC_GATE_VACUOUS, check_floors, validate_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "s0ma_dsl"
    / "docs_model"
    / "providers_core.py"
)

RELEASE = "0.18.1"

#: FastAPI's own documentation routes. The provider excludes them
#: structurally — they are not ``APIRoute`` instances — and this list
#: exists only so a test can say what must be absent.
FRAMEWORK_ROUTES = ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

#: An absolute POSIX path, anywhere in the serialized build. The leading
#: context class keeps ``rest:GET:/self/overview`` — a served route, not
#: a file — from reading as one.
_POSIX_PATH = re.compile(r"""(?:^|[\s"(\[])/(?:Users|home|private|tmp|var|opt|usr|etc)/""")

#: A Windows drive letter. The lookbehind keeps ``rest:GET:/self`` out:
#: the letter before that colon is part of a word.
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]")


# ---------------------------------------------------------------------------
# The live boundary, read once
# ---------------------------------------------------------------------------


def _bootstrapped() -> ComponentRegistry:
    """A fresh registry with core's framework in it and nothing else."""
    registry = ComponentRegistry(persist=False)
    bootstrap_register(registry)
    return registry


def _live_rest_ids() -> set[str]:
    """Every ``rest:`` id the application actually serves, read here.

    Built independently of the provider — a different registry, a
    different application object — so the comparison is a parity check
    and not a restatement.
    """
    from fastapi.routing import APIRoute
    from s0ma.api.rest import create_app

    app = create_app(_bootstrapped())
    return {
        f"rest:{method}:{route.path}"
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


def _live_mcp_tool_names() -> set[str]:
    """Every tool core's MCP server lists, the way a client lists them."""
    from s0ma.api.mcp_server import create_mcp_server

    server = create_mcp_server(_bootstrapped())
    return {tool.name for tool in asyncio.run(server.list_tools())}


def _live_mcp_resource_addresses() -> set[str]:
    """Every resource address core serves, concrete and templated alike.

    Read independently of the provider, from a different registry and a
    different server object, so the comparison is a parity check and not
    a restatement.
    """
    from s0ma.api.mcp_server import create_mcp_server

    server = create_mcp_server(_bootstrapped())
    served = {str(resource.uri) for resource in asyncio.run(server.list_resources())}
    served |= {
        str(template.uriTemplate)
        for template in asyncio.run(server.list_resource_templates())
    }
    return served


def _live_public_exports() -> tuple[set[str], set[str]]:
    """``s0ma.__all__``, split into what the bootstrap registers and what it does not.

    The same split the provider makes, taken here from the live export
    list and a fresh registry. Twelve names are components; the rest are
    module-level callables and constants, which is the family D5a's
    ``python:`` form addresses.
    """
    import s0ma

    registered = {spec.name for spec in _bootstrapped().get_all().values()}
    exported = set(s0ma.__all__)
    return exported & registered, exported - registered


def _composed() -> Composition:
    return compose(ProviderRegistry.of(CoreProvider()), release_version=RELEASE)


def _composed_text() -> str:
    """The core build's canonical text. Read from a subprocess too."""
    return serialize_bundle(_composed().bundle)


@pytest.fixture(scope="module")
def provider() -> CoreProvider:
    """One reading of core, shared by every test that only inspects it."""
    return CoreProvider()


@pytest.fixture(scope="module")
def composition() -> Composition:
    return _composed()


def _surfaces(provider: CoreProvider, channel: str) -> list[SurfaceRecord]:
    return sorted(
        (
            item.record
            for item in provider.provide().records
            if isinstance(item.record, SurfaceRecord) and item.record.channel == channel
        ),
        key=lambda record: record.id,
    )


# ---------------------------------------------------------------------------
# The component inventory
# ---------------------------------------------------------------------------


class TestComponentInventory:
    """The resolution universe every ``component:`` reference is checked against."""

    def test_the_inventory_equals_cores_own_pin(self, provider: CoreProvider) -> None:
        """Exact, against the live constant — never a number written here.

        ``EXPECTED_FRAMEWORK_COMPONENT_COUNT`` is core's own tripwire for
        a bootstrap that forgot something. Copying its value into this
        file would give the documentation build a second pin to keep in
        step, and the two would part company on the first framework
        component anyone adds.
        """
        assert len(provider.component_ids()) == EXPECTED_FRAMEWORK_COMPONENT_COUNT

    def test_every_component_id_is_package_qualified(self, provider: CoreProvider) -> None:
        """Flat names collide across the four packages, so there are none."""
        for identifier in provider.component_ids():
            assert id_form(identifier) == "component", identifier
            dotted = identifier.removeprefix("component:")
            assert dotted.startswith("s0ma."), identifier
            assert dotted.count(".") >= 2, identifier

    def test_the_inventory_is_sorted_and_holds_no_duplicates(
        self, provider: CoreProvider
    ) -> None:
        ids = provider.component_ids()
        assert list(ids) == sorted(ids)
        assert len(set(ids)) == len(ids)

    def test_the_inventory_matches_the_registry_it_was_read_from(
        self, provider: CoreProvider
    ) -> None:
        """Every registered component is in it, addressed by its import path."""
        expected = {
            f"component:{spec.qualified_name}"
            for spec in _bootstrapped().get_all().values()
        }
        assert set(provider.component_ids()) == expected

    def test_a_bootstrap_that_lost_components_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The inventory is not a bundle group, so no floor can see it.

        A floor catches a provider that stopped producing *records*. The
        component inventory produces none — it is the universe references
        resolve against — so the pin is checked where it is read, and a
        disagreement refuses the reading rather than composing a build in
        which every ``component:`` reference silently fails.
        """
        monkeypatch.setattr(
            "s0ma_dsl.docs_model.providers_core.EXPECTED_FRAMEWORK_COMPONENT_COUNT",
            EXPECTED_FRAMEWORK_COMPONENT_COUNT + 1,
        )
        with pytest.raises(CoreProviderError) as caught:
            CoreProvider()
        assert "EXPECTED_FRAMEWORK_COMPONENT_COUNT" in str(caught.value)

    def test_a_supplied_registry_is_taken_at_its_word(self) -> None:
        """The pin belongs to core's bootstrap, not to every registry.

        A caller describing a process that imported generated modules has
        a registry with more in it than the bootstrap put there. Holding
        that one to core's count would refuse the case the parameter
        exists for.
        """
        provider = CoreProvider(_bootstrapped())
        assert len(provider.component_ids()) == EXPECTED_FRAMEWORK_COMPONENT_COUNT


class TestComponentsAreNotRecords:
    """Where a registered component lives in this model, and why.

    Architecture plan §6.1–§6.6 names six record types and none of them
    is a component; ``validate.ReferenceIndex`` says the same thing from
    the other end — a registered component is passed in as an external
    id. So the provider hands the inventory over rather than minting
    records for it.

    **D6 answered the question C3 left open here** and the answer kept
    this class true. The facts about a component — intent, kind, layer,
    visibility, package — needed somewhere to live, and the two candidates
    were a seventh bundle group and a renderer-side artifact. D6 ruled for
    the artifact (``docs/_generated/inventory-components.json``, rendered
    by :mod:`s0ma_dsl.docs_model.inventories`), so a component is still an
    external id and still not a record, and the facts are written down
    with provenance in a byte-gated file instead. The last test below is
    the flipped pin: it used to say only that no component record exists,
    and now also says where the facts went. If a component record type
    ever arrives, the first two fail and name the decision to revisit.
    """

    def test_no_record_the_provider_emits_is_addressed_as_a_component(
        self, provider: CoreProvider
    ) -> None:
        for item in provider.provide().records:
            assert not item.record.id.startswith("component:"), item.record.id

    def test_the_inventory_reaches_a_build_through_the_external_id_seam(
        self, provider: CoreProvider
    ) -> None:
        external = provider.external_ids()
        assert set(provider.component_ids()) <= set(external)
        assert set(provider.example_ids()) <= set(external)
        assert list(external) == sorted(external)

    def test_the_facts_about_a_component_live_in_the_d6_artifact(
        self, provider: CoreProvider
    ) -> None:
        """The C3 deferral, answered: an artifact, not a bundle group.

        Every component this provider vouches for is described in the
        rendered inventory, with the five facts the milestone asked for —
        and the model's record types are untouched, which is the half of
        the ruling that keeps arch Risk 1 closed.
        """
        from s0ma_dsl.docs_model.inventories import component_facts
        from s0ma_dsl.docs_model.records import RECORD_TYPES

        assert not any(
            item.__name__ == "ComponentRecord" for item in RECORD_TYPES
        )

        facts, readings = component_facts(REPO_ROOT, provider.component_ids())
        described = {item.id for item in facts}
        assert described == set(provider.component_ids())
        assert readings
        for fact in facts:
            assert fact.kind and fact.layer and fact.intent, fact.id
            assert fact.distribution == "s0ma-core", fact.id


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------


class TestRestSurfaces:
    """The self-description interface, read from its own route table."""

    def test_every_route_is_present_exactly_once(self, provider: CoreProvider) -> None:
        records = _surfaces(provider, "rest")
        ids = [record.id for record in records]
        assert len(ids) == len(set(ids))
        assert set(ids) == _live_rest_ids()

    def test_the_web_frameworks_own_routes_are_not_the_products(
        self, provider: CoreProvider
    ) -> None:
        """``/docs`` belongs to FastAPI. The product does not serve it."""
        served = {record.id for record in _surfaces(provider, "rest")}
        for path in FRAMEWORK_ROUTES:
            assert not any(identifier.endswith(f":{path}") for identifier in served), path

    def test_the_route_family_is_not_empty(self, provider: CoreProvider) -> None:
        """B3's floor for this family, restated where it can go red.

        Twelve, against fourteen observed: low enough that renaming a
        route cannot trip it, high enough that losing the family must.
        """
        assert len(_surfaces(provider, "rest")) >= 12

    def test_every_route_binds_to_a_registered_component(
        self, provider: CoreProvider
    ) -> None:
        """Derived binding, not a hand-kept table.

        Every route of this application is a closure built inside
        ``create_app``; what it closed over is what implements it. If a
        future route reaches no registered component the record has to
        carry a written exception instead, and this test is where that
        change becomes visible.
        """
        inventory = set(provider.component_ids())
        for record in _surfaces(provider, "rest"):
            assert record.component_refs, record.id
            assert set(record.component_refs) <= inventory, record.id

    def test_a_get_reads_and_the_one_post_says_who_classified_it(
        self, provider: CoreProvider
    ) -> None:
        """HTTP promises that a GET reads. It promises nothing of a POST.

        So the read fact on a GET is derived and carries no exception,
        and the read fact on the POST is a person's reading of the
        endpoint and says so in writing.
        """
        for record in _surfaces(provider, "rest"):
            method = record.id.split(":")[1]
            assert record.side_effects == ("read",), record.id
            if method == "GET":
                assert record.manual_exception == "", record.id
            else:
                assert record.manual_exception, record.id
                assert "by hand" in record.manual_exception

    def test_intent_quotes_the_route_and_never_paraphrases_it(
        self, provider: CoreProvider
    ) -> None:
        """A surface's intent is the source's own summary line, verbatim."""
        from fastapi.routing import APIRoute
        from s0ma.api.rest import create_app

        app = create_app(_bootstrapped())
        written = {
            f"rest:{method}:{route.path}": (route.description or route.summary or "")
            for route in app.routes
            if isinstance(route, APIRoute)
            for method in route.methods
        }
        for record in _surfaces(provider, "rest"):
            source = written[record.id]
            assert record.intent == " ".join(source.splitlines()[0].split())

    def test_rest_records_say_they_were_introspected(
        self, provider: CoreProvider
    ) -> None:
        """§1.2 fact 11: FastAPI-introspected, never registry-declared."""
        for record in _surfaces(provider, "rest"):
            assert record.provenance.source == REST_SOURCE
            assert record.provenance.adapter_id == PROVIDER_ID


class TestSideEffectClassification:
    """A method HTTP does not vouch for is refused, never assumed.

    The classifier is exercised directly because the failure it exists
    to prevent is a route this application does not have yet: the day
    someone adds a mutating ``POST``, the build must stop rather than
    record it as a read because the last POST happened to be one.
    """

    def test_a_safe_method_is_read_with_no_exception(self) -> None:
        assert _route_effects("GET", "rest:GET:/self/overview") == (("read",), "")
        assert _route_effects("HEAD", "rest:HEAD:/self/overview") == (("read",), "")

    def test_the_known_post_is_a_read_a_person_vouched_for(self) -> None:
        effects, exception = _route_effects("POST", "rest:POST:/self/query")
        assert effects == ("read",)
        assert "by hand" in exception

    def test_an_unclassified_mutating_method_stops_the_reading(self) -> None:
        with pytest.raises(CoreProviderError) as caught:
            _route_effects("DELETE", "rest:DELETE:/self/component/{name}")
        assert "nobody has said what it does" in str(caught.value)

    def test_every_hand_classified_route_is_one_this_build_serves(self) -> None:
        """A stale entry would vouch for a route that no longer exists."""
        assert set(_HAND_CLASSIFIED) <= _live_rest_ids()


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------


class TestMcpToolSurfaces:
    """Core's own agent tools — a different server from the authoring one."""

    def test_every_served_tool_is_present_exactly_once(
        self, provider: CoreProvider
    ) -> None:
        records = _surfaces(provider, "mcp_tool")
        ids = [record.id for record in records]
        assert len(ids) == len(set(ids))
        assert set(ids) == {f"mcp:tool/{name}" for name in _live_mcp_tool_names()}

    def test_the_serving_package_is_carried_by_the_source(
        self, provider: CoreProvider
    ) -> None:
        """``mcp:tool/<name>`` is one namespace and two servers serve into it.

        What keeps core's ``learn_about_s0ma`` apart from anything the
        authoring server may serve is the provenance: the source names
        the module, and therefore the package, that answers when an agent
        calls the tool. B4 deferred an ``availability`` field for exactly
        this reason, so no record carries a second copy of the fact.
        """
        records = _surfaces(provider, "mcp_tool")
        assert records
        for record in records:
            assert record.provenance.source == MCP_SOURCE
            assert "s0ma.api.mcp_server" in record.provenance.source

    def test_no_side_effect_fact_is_invented(self, provider: CoreProvider) -> None:
        """Core's tools declare no annotations, so there is nothing to read.

        Every one of them only reads, and saying so here would be a guess
        that later gates could not tell apart from a declaration. The
        honest record is empty, and the milestone that completes
        side-effect classification is where it stops being empty.
        """
        for record in _surfaces(provider, "mcp_tool"):
            assert record.side_effects == (), record.id

    def test_every_tool_carries_a_written_reason_for_its_unbound_state(
        self, provider: CoreProvider
    ) -> None:
        """The counted exception list this milestone hands to the next one."""
        records = _surfaces(provider, "mcp_tool")
        for record in records:
            assert record.component_refs == ()
            assert record.manual_exception
            assert "\n\n" not in record.manual_exception

    def test_intent_quotes_the_tools_own_summary_line(
        self, provider: CoreProvider
    ) -> None:
        from s0ma.api.mcp_server import create_mcp_server

        server = create_mcp_server(_bootstrapped())
        written = {
            f"mcp:tool/{tool.name}": tool.description or ""
            for tool in asyncio.run(server.list_tools())
        }
        for record in _surfaces(provider, "mcp_tool"):
            source = written[record.id]
            assert record.intent == " ".join(source.splitlines()[0].split())


class TestMcpResourceSurfaces:
    """D5a's other unlocked family: core's six resources and two templates.

    C3 emitted core's tools and stopped, because the ``mcp:resource/``
    charset could not spell a braced template address — and describing
    six of eight resources would have been worse than describing none,
    since the two missing ones are the parameterized reads. D5a widened
    the charset by exactly ``{}``, and this class holds the whole family
    against the live server.
    """

    def test_every_served_resource_is_present_exactly_once(
        self, provider: CoreProvider
    ) -> None:
        records = _surfaces(provider, "mcp_resource")
        ids = [record.id for record in records]
        assert len(ids) == len(set(ids))
        assert set(ids) == {
            f"mcp:resource/{address}" for address in _live_mcp_resource_addresses()
        }

    def test_the_two_templates_keep_their_braces(self, provider: CoreProvider) -> None:
        """The convention D3 settled, on the records that needed it."""
        braced = {
            record.id
            for record in _surfaces(provider, "mcp_resource")
            if "{" in record.id
        }
        assert braced == {
            "mcp:resource/s0ma://model/docs-for/{component}",
            "mcp:resource/s0ma://model/examples-for/{component}",
        }
        for identifier in braced:
            assert id_form(identifier) == "mcp_resource"

    def test_a_template_and_a_brace_free_resource_are_different_ids(self) -> None:
        """Why the convention could not have been "strip the braces"."""
        assert (
            "mcp:resource/s0ma://model/docs-for/{component}"
            != "mcp:resource/s0ma://model/docs-for/component"
        )
        assert is_valid_id("mcp:resource/s0ma://model/docs-for/component")

    def test_the_serving_package_is_carried_by_the_source(
        self, provider: CoreProvider
    ) -> None:
        records = _surfaces(provider, "mcp_resource")
        assert records
        for record in records:
            assert record.provenance.source == MCP_SOURCE

    def test_the_served_name_is_the_whole_address(self, provider: CoreProvider) -> None:
        for record in _surfaces(provider, "mcp_resource"):
            assert record.public_name == record.id.removeprefix("mcp:resource/")
            assert record.public_name.startswith("s0ma://")

    def test_no_side_effect_fact_is_invented(self, provider: CoreProvider) -> None:
        """A resource carries no annotation at all, so there is nothing to read."""
        for record in _surfaces(provider, "mcp_resource"):
            assert record.side_effects == (), record.id

    def test_every_resource_carries_a_written_reason_for_its_unbound_state(
        self, provider: CoreProvider
    ) -> None:
        records = _surfaces(provider, "mcp_resource")
        assert records
        for record in records:
            assert record.component_refs == ()
            assert record.manual_exception
            assert "\n\n" not in record.manual_exception

    def test_intent_quotes_the_resources_own_summary_line(
        self, provider: CoreProvider
    ) -> None:
        from s0ma.api.mcp_server import create_mcp_server

        server = create_mcp_server(_bootstrapped())
        written = {
            f"mcp:resource/{resource.uri}": resource.description or ""
            for resource in asyncio.run(server.list_resources())
        }
        written.update(
            {
                f"mcp:resource/{template.uriTemplate}": template.description or ""
                for template in asyncio.run(server.list_resource_templates())
            }
        )
        for record in _surfaces(provider, "mcp_resource"):
            source = written[record.id]
            assert record.intent == " ".join(source.splitlines()[0].split())

    def test_a_served_prompt_would_be_refused_rather_than_unrecorded(self) -> None:
        """Core serves no prompts, and the reading says so out loud.

        The failure this guards is the one the whole provider exists
        against: a family the product starts serving and the build never
        mentions. A floor cannot see it — the count goes *up* — so the
        reading refuses instead.
        """
        from s0ma.api.mcp_server import create_mcp_server

        server = create_mcp_server(_bootstrapped())
        assert asyncio.run(server.list_prompts()) == []
        module = MODULE_PATH.read_text(encoding="utf-8")
        assert "list_prompts" in module, "the prompt family is not read at all"


# ---------------------------------------------------------------------------
# The documentation and example stores
# ---------------------------------------------------------------------------


def _registry_with_documentation() -> ComponentRegistry:
    """A registry shaped like a process that imported generated modules.

    Core's bootstrap registers no documentation of its own, so the only
    way to prove the reading works is to hand the provider a registry
    that has some. The entities the guide covers are real registered
    components, because a guide covering something the registry does not
    know is a broken registration and the provider refuses it.
    """
    registry = _bootstrapped()
    registry.register_doc_ref(
        name="api_reference",
        module="tools",
        intent="Every registered component, rendered as a reference page.",
        format="markdown",
        output="docs/api-reference.md",
        source_span=SourceSpan(file="tools.s0ma", start_line=10, end_line=20),
    )
    registry.register_doc_guide(
        name="getting_started",
        module="tools",
        intent="How to get from an empty directory to a project that checks clean.",
        format="markdown",
        output="docs/getting-started.md",
        covers=[EntityRef(kind="cell", name="ComponentRegistry")],
        source_span=SourceSpan(file="tools.s0ma", start_line=30, end_line=60),
    )
    registry.register_example(
        name="first_nerve",
        module="tools",
        intent="The smallest module that declares one nerve.",
        demonstrates=[EntityRef(kind="cell", name="ComponentRegistry")],
    )
    return registry


class TestDocumentationStores:
    """What the registry's own documentation stores become."""

    def test_cores_bootstrap_registers_no_documentation(self) -> None:
        """A live-boundary fact, not a hole in the provider.

        The stores are filled by the generated modules a project
        imports; core's handwritten bootstrap registers components and
        nothing else. Recording it here means the day core registers a
        guide of its own, this test fails and someone looks.
        """
        snapshot = _bootstrapped().snapshot()
        assert snapshot.doc_refs == {}
        assert snapshot.doc_guides == {}
        assert snapshot.examples == {}

    def test_the_default_reading_has_no_catalog_rows(
        self, provider: CoreProvider
    ) -> None:
        assert provider.provide().counts()["documents"] == 0
        assert provider.example_ids() == ()

    def test_a_registry_with_registrations_produces_catalog_rows(self) -> None:
        provider = CoreProvider(_registry_with_documentation())
        rows = {
            item.record.id: item.record
            for item in provider.provide().records
            if isinstance(item.record, DocumentRecord)
        }
        assert set(rows) == {"doc:generated/api-reference", "doc:guide/getting-started"}

        guide = rows["doc:guide/getting-started"]
        assert guide.canonical_source == "docs/getting-started.md"
        assert guide.prose_locator == "tools.s0ma#doc-guide:getting_started"
        assert guide.covers == ("component:s0ma.registry.ComponentRegistry",)
        assert guide.title.startswith("How to get from an empty directory")

        reference = rows["doc:generated/api-reference"]
        assert reference.prose_locator == "tools.s0ma#doc-ref:api_reference"
        # A doc-ref selects its subjects with a filter, not by naming
        # them, so the row states nothing it cannot prove.
        assert reference.covers == ()

    def test_registered_examples_become_addressable_ids(self) -> None:
        provider = CoreProvider(_registry_with_documentation())
        assert provider.example_ids() == ("example:first_nerve",)
        assert "example:first_nerve" in provider.external_ids()

    def test_the_single_colon_form_is_the_one_that_is_minted(self) -> None:
        """``example::name`` is prose syntax and means something else."""
        provider = CoreProvider(_registry_with_documentation())
        for identifier in provider.example_ids():
            assert id_form(identifier) == "example"
            assert "::" not in identifier

    def test_a_guide_covering_an_unregistered_entity_is_refused(self) -> None:
        registry = _bootstrapped()
        registry.register_doc_guide(
            name="orphan",
            module="tools",
            intent="A guide about something the registry has never heard of.",
            format="markdown",
            output="docs/orphan.md",
            covers=[EntityRef(kind="cell", name="NoSuchComponent")],
        )
        with pytest.raises(CoreProviderError) as caught:
            CoreProvider(registry)
        assert "NoSuchComponent" in str(caught.value)

    def test_an_absolute_source_span_is_refused(self) -> None:
        """A machine path in a record would serialize differently elsewhere."""
        registry = _bootstrapped()
        registry.register_doc_guide(
            name="absolute",
            module="tools",
            intent="A guide whose registration recorded a machine path.",
            format="markdown",
            output="docs/absolute.md",
            source_span=SourceSpan(
                file="/Users/somebody/project/tools.s0ma", start_line=1, end_line=2
            ),
        )
        with pytest.raises(CoreProviderError) as caught:
            CoreProvider(registry)
        assert "machine path" in str(caught.value)

    def test_two_names_that_slug_alike_are_refused(self) -> None:
        registry = _bootstrapped()
        for name in ("release_notes", "release-notes"):
            registry.register_doc_ref(
                name=name,
                module="tools",
                intent="What changed in this release, rendered from the registry.",
                format="markdown",
                output=f"docs/{name}.md",
            )
        with pytest.raises(CoreProviderError) as caught:
            CoreProvider(registry)
        assert "collide" in str(caught.value)

    def test_catalog_rows_are_stamped_with_the_store_they_came_from(self) -> None:
        provider = CoreProvider(_registry_with_documentation())
        for item in provider.provide().records:
            if isinstance(item.record, DocumentRecord):
                assert item.provenance.source == STORES_SOURCE


# ---------------------------------------------------------------------------
# The two things the model cannot say
# ---------------------------------------------------------------------------


class TestPythonSurfaceGap:
    """C3's T2, and the id form D5a added for it.

    Core's public Python API is twenty-one names. Twelve of them are
    registered components and were already addressable. The other nine
    are module-level functions and constants — ``initialize``,
    ``verify``, ``canonicalize`` and the rest — and no frozen id form
    addressed one, so C3 emitted no ``python`` channel record rather
    than minting a form in a module that does not own the form table.

    D5a added ``python:<dotted>`` and this class flipped with it: every
    half is still asserted from the live export list, so none of it can
    rot, and what used to say "no form reaches these" now says "the form
    reaches every one of them, and the provider emits every one".
    """

    def test_the_exports_that_are_components_are_addressed_as_components(
        self, provider: CoreProvider
    ) -> None:
        inventory = {
            identifier.rsplit(".", 1)[1] for identifier in provider.component_ids()
        }
        addressable, _ = _live_public_exports()
        assert addressable
        assert addressable <= inventory

    def test_the_form_addresses_every_module_level_export(self) -> None:
        _, unaddressable = _live_public_exports()
        assert unaddressable, "core exports nothing but components — revisit T2"
        for name in unaddressable:
            assert is_valid_id(f"python:s0ma.{name}"), name

    def test_a_module_level_export_is_still_not_a_component(self) -> None:
        """The relaxed component floor did not swallow this family.

        D5a also relaxed ``component:`` to two dotted segments, which
        makes ``component:s0ma.verify`` a well-formed id. It is still
        the wrong one: nothing registers ``verify``, so that id would
        resolve to nothing. The distinction the two forms carry is
        registration, and this asserts the provider keeps it.
        """
        _, unaddressable = _live_public_exports()
        inventory = set(CoreProvider().component_ids())
        for name in unaddressable:
            assert f"component:s0ma.{name}" not in inventory, name

    def test_the_provider_emits_one_record_per_unregistered_export(
        self, provider: CoreProvider
    ) -> None:
        _, unaddressable = _live_public_exports()
        records = _surfaces(provider, "python")
        assert {record.id for record in records} == {
            f"python:s0ma.{name}" for name in unaddressable
        }

    def test_every_python_record_is_stamped_with_the_export_list(
        self, provider: CoreProvider
    ) -> None:
        for record in _surfaces(provider, "python"):
            assert record.provenance.source == EXPORTS_SOURCE

    def test_the_served_name_is_the_import_path_a_caller_writes(
        self, provider: CoreProvider
    ) -> None:
        for record in _surfaces(provider, "python"):
            assert record.public_name == record.id.removeprefix("python:")
            assert record.public_name.startswith("s0ma.")

    def test_every_python_record_carries_a_written_reason_for_being_unbound(
        self, provider: CoreProvider
    ) -> None:
        """The counted exception list this milestone hands to the next one."""
        records = _surfaces(provider, "python")
        assert records
        for record in records:
            assert record.component_refs == ()
            assert record.manual_exception
            assert "\n\n" not in record.manual_exception

    def test_intent_quotes_the_callable_and_stays_empty_for_a_constant(
        self, provider: CoreProvider
    ) -> None:
        """The honesty rule, at the one place it bites.

        ``inspect.getdoc`` on a string constant answers with the
        docstring of ``str``. Two of the nine exports are strings, so a
        provider that asked the wrong question would put the standard
        library's prose in a record and it would read like a quotation
        of core. The field is empty for those two and a real quotation
        for the seven callables.
        """
        import inspect

        import s0ma

        for record in _surfaces(provider, "python"):
            name = record.public_name.removeprefix("s0ma.")
            value = getattr(s0ma, name)
            if inspect.isroutine(value):
                written = inspect.getdoc(value) or ""
                assert record.intent == " ".join(written.splitlines()[0].split())
                assert record.intent
            else:
                assert record.intent == "", name

    def test_no_record_carries_the_string_classs_docstring(
        self, provider: CoreProvider
    ) -> None:
        """The failure the test above exists to prevent, named."""
        for record in _surfaces(provider, "python"):
            assert "str(object=" not in record.intent, record.id


# ---------------------------------------------------------------------------
# The provider contract
# ---------------------------------------------------------------------------


class TestProviderContract:
    """Architecture plan §7.1, at the points it is checkable."""

    def test_the_provider_satisfies_the_protocol(self, provider: CoreProvider) -> None:
        assert provider.provider_id == PROVIDER_ID
        assert provider.provide().provider_id == PROVIDER_ID

    def test_the_records_arrive_sorted(self, provider: CoreProvider) -> None:
        records = provider.provide().records
        assert list(records) == sorted(records, key=record_key)
        assert records == sort_records(records)

    def test_reading_twice_returns_the_same_records(
        self, provider: CoreProvider
    ) -> None:
        """"Reads nothing at call time", proved rather than promised."""
        assert provider.provide() is provider.provide()

    def test_every_record_carries_all_four_parts_of_its_provenance(
        self, provider: CoreProvider
    ) -> None:
        for item in provider.provide().records:
            provenance = item.provenance
            assert provenance.adapter_id == PROVIDER_ID
            assert provenance.schema_version == SCHEMA
            assert provenance.source
            assert _SHA256.match(provenance.source_sha256), item.record.id

    def test_every_source_is_an_import_path(self, provider: CoreProvider) -> None:
        """A code source has no file whose bytes mean the same thing."""
        known = {
            BOOTSTRAP_SOURCE,
            EXPORTS_SOURCE,
            REST_SOURCE,
            MCP_SOURCE,
            STORES_SOURCE,
        }
        for source, digest in provider.provide().sources():
            assert source in known, source
            assert source.startswith("python:")
            assert _SHA256.match(digest)

    def test_a_surface_agrees_with_the_provenance_it_was_stamped_with(
        self, provider: CoreProvider
    ) -> None:
        """``SourcedRecord`` refuses a disagreement; this proves it was asked."""
        for item in provider.provide().records:
            own = getattr(item.record, "provenance", None)
            if own is not None:
                assert own == item.provenance

    def test_the_ids_are_already_their_comparable_form(
        self, provider: CoreProvider
    ) -> None:
        for item in provider.provide().records:
            assert is_valid_id(item.record.id), item.record.id


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """The same reading is the same bytes, here and in a fresh process."""

    def test_two_readings_are_byte_identical(self) -> None:
        assert _composed_text() == _composed_text()

    def test_two_providers_produce_equal_results(self) -> None:
        first = CoreProvider().provide()
        second = CoreProvider().provide()
        assert first == second

    def test_the_digest_of_a_source_covers_only_what_it_read(
        self, provider: CoreProvider
    ) -> None:
        """Two sources, two digests. One digest for both would hide a move."""
        digests = dict(provider.provide().sources())
        assert digests[REST_SOURCE] != digests[MCP_SOURCE]

    def test_the_build_is_the_same_under_any_hash_seed(self) -> None:
        """Dictionary iteration is how a hash seed reaches output.

        The registry, the route table and the tool listing are all
        dictionaries somewhere, so this can only be proved in a fresh
        process with the seed set.
        """
        script = (
            "from tests.test_docs_provider_core import _composed_text;"
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


class TestNoMachinePaths:
    """The determinism invariant's hardest edge: nothing absolute, anywhere."""

    def test_no_absolute_path_reaches_the_serialized_build(self) -> None:
        text = _composed_text()
        assert not _POSIX_PATH.search(text), "an absolute POSIX path reached a record"
        assert not _WINDOWS_PATH.search(text), "a Windows path reached a record"

    def test_this_checkout_is_not_in_the_build(self) -> None:
        """The strongest form of the same check: this machine's own paths."""
        text = _composed_text()
        for path in (Path(__file__).resolve().parents[3], Path.home()):
            assert str(path) not in text, path

    def test_the_pattern_would_notice_a_machine_path(self) -> None:
        """A guard nothing can trip is a guard nobody tested."""
        assert _POSIX_PATH.search('  "source": "/Users/somebody/s0ma/core.py"')
        assert _WINDOWS_PATH.search('  "source": "C:\\\\s0ma\\\\core.py"')
        assert not _POSIX_PATH.search('  "id": "rest:GET:/self/overview"')
        assert not _WINDOWS_PATH.search('  "id": "rest:GET:/self/overview"')


# ---------------------------------------------------------------------------
# Composition and the floors
# ---------------------------------------------------------------------------


class TestComposition:
    """The provider in a build, with every gate C2 owns run over it."""

    def test_it_registers_and_composes_with_nothing_wrong(
        self, composition: Composition
    ) -> None:
        assert composition.ok
        assert composition.findings == ()

    def test_every_gate_over_the_composed_bundle_is_silent(
        self, provider: CoreProvider, composition: Composition
    ) -> None:
        """Handed the ids the model addresses and does not hold.

        An empty ``external_ids`` would report every ``component:``
        reference as unresolved, which is the truthful answer when
        nobody has said what components exist. This provider has said.
        """
        findings = validate_bundle(
            composition.bundle,
            results=composition.results,
            floors=FLOORS,
            external_ids=provider.external_ids(),
            # Twenty-nine of this provider's own surfaces declare no
            # side effects — the MCP families whose listing carries no
            # annotation, and the module-level exports that declare
            # theirs nowhere a reading can reach. The application's
            # written allowances are what permit that silence.
            allowances=SIDE_EFFECT_ALLOWANCES,
        )
        assert findings == (), [finding.rendered() for finding in findings]

    def test_the_surfaces_are_the_only_group_this_provider_fills(
        self, provider: CoreProvider
    ) -> None:
        counts = provider.provide().counts()
        assert counts["surfaces"] > 0
        for group in ("authorities", "concepts", "journeys", "sequences"):
            assert counts[group] == 0, group

    def test_the_shipped_floors_are_met(self, composition: Composition) -> None:
        assert check_floors(composition.results, FLOORS) == []

    def test_a_floor_past_the_truth_reports_a_vacuous_gate(
        self, composition: Composition
    ) -> None:
        """The floors are only worth having if one of them can go red."""
        findings = check_floors(composition.results, {(PROVIDER_ID, "surfaces"): 10_000})
        assert [finding.code for finding in findings] == [DOC_GATE_VACUOUS]

    def test_a_floor_naming_a_provider_that_did_not_run_is_a_finding(self) -> None:
        findings = check_floors((), FLOORS)
        assert [finding.code for finding in findings] == [DOC_GATE_VACUOUS]

    def test_every_surface_is_bound_or_says_why_it_is_not(
        self, provider: CoreProvider
    ) -> None:
        """``component_refs`` and ``manual_exception`` are independent axes.

        What no surface may do is neither. This provider's REST records
        take the first axis and its MCP records the second, and the one
        POST route honestly takes both.
        """
        for item in provider.provide().records:
            record = item.record
            if isinstance(record, SurfaceRecord):
                assert record.component_refs or record.manual_exception.strip(), record.id


# ---------------------------------------------------------------------------
# What the module is allowed to depend on
# ---------------------------------------------------------------------------


class TestDependencies:
    """ADR-012 and the C3 independence rule, checked against the source."""

    def test_the_module_imports_nothing_it_should_not(self) -> None:
        """Core, this package, and the standard library. Nothing else.

        Core is the point of this module. The other two packages are
        not: a provider that reached into ``s0ma_mcp`` or ``s0ma_studi0``
        would make core's reading depend on packages core does not know
        about, and their surfaces have providers of their own. The spikes
        are evidence, not dependencies, so nothing under ``scripts/``
        may be imported either.
        """
        forbidden = ("s0ma_mcp", "s0ma_studi0", "spike_", "scripts.")
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        offenders = [name for name in imported if name.startswith(forbidden)]
        assert offenders == [], f"providers_core.py imports {offenders}"

    def test_the_optional_extras_are_imported_where_they_are_used(self) -> None:
        """``fastapi`` and ``mcp`` are core's extras, not the DSL's.

        A module-level import of either would make ``docs_model``
        unimportable in an environment that installed neither, which is
        every environment that only wanted the transpiler.
        """
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        top_level: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level.append(node.module)
        for name in top_level:
            assert not name.startswith(("fastapi", "mcp", "s0ma.api")), name

    def test_the_source_is_utf8_with_line_feeds(self) -> None:
        raw = MODULE_PATH.read_bytes()
        raw.decode("utf-8")
        assert b"\r\n" not in raw
