"""Gates for D3 — the MCP provider, held against the live server.

Milestone D3 of the docs-function plan (internal) §9. Almost every check
here is made against the thing itself rather than against a fixture:
the server is asked what it lists, the package's registry is asked what
it declares, and the committed snapshot is read from the checkout. A
fixture would only prove that this file agrees with itself.

What these tests hold in place:

* **the three-source cross-check** (T1) — the registration set, the
  committed snapshot and the live listing agree on the live tree, and a
  tree whose snapshot has been edited fails with all three sources
  named;
* **the emitted surface** (T2) — one record per served surface and no
  more, counted against the live listing rather than against a number
  written here; every write, network, subprocess and approval effect
  present as a structural fact, which is what ``D5``'s
  ``DOC_SIDE_EFFECT_UNDECLARED`` will read;
* **binding** — every served surface reaches exactly one registered
  component, derived from the registration that names it, so this
  provider carries no binding exception at all;
* **the template-id gap** (T0) — the convention settled by this
  milestone, pinned from both live servers so the day the id form
  changes, the test that says "there is no way to say this" fails;
* **the mirror correspondence** — the packaged guide documents and the
  ``doc:mirror/`` catalog rows are the same set, asserted against the
  real catalog rather than asserted twice;
* **the provider contract, determinism and no machine paths** — the
  same three C3 holds, because they are the contract and not that
  milestone's opinion;
* **composition** — the provider composes with the five C-phase
  providers and every gate over the merged bundle stays silent.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.docs_model.application import SIDE_EFFECT_ALLOWANCES
from s0ma_dsl.docs_model.application import registry as application_registry
from s0ma_dsl.docs_model.compose import Composition, compose
from s0ma_dsl.docs_model.evidence import EvidenceLibrary
from s0ma_dsl.docs_model.ids import is_valid_id
from s0ma_dsl.docs_model.providers import ProviderRegistry, record_key, sort_records
from s0ma_dsl.docs_model.providers_core import CoreProvider
from s0ma_dsl.docs_model.providers_mcp import (
    _HAND_CLASSIFIED,
    MCP_FLOORS,
    MIRROR_DIR,
    PROVIDER_ID,
    REGISTRATION_SOURCE,
    SERVED_SOURCE,
    SNAPSHOT_SOURCE,
    McpProvider,
    McpProviderError,
    McpSurfaceDisagreementError,
)
from s0ma_dsl.docs_model.records import SCHEMA, DocumentRecord, SurfaceRecord
from s0ma_dsl.docs_model.serialize import serialize_bundle
from s0ma_dsl.docs_model.validate import DOC_GATE_VACUOUS, check_floors, validate_bundle

pytest.importorskip("mcp", reason="MCP SDK not installed")
pytest.importorskip("s0ma_mcp", reason="s0ma-mcp not installed")

REPO_ROOT = Path(__file__).resolve().parents[3]

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "s0ma_dsl"
    / "docs_model"
    / "providers_mcp.py"
)

RELEASE = "0.18.1"

#: Where the document catalog this provider's mirrors must correspond to
#: lives. Read here, never through the catalog provider: the point of
#: the correspondence test is that two independent readings agree.
CATALOG_PATH = REPO_ROOT / "docs" / "s0ma_src" / "catalog.json"

#: The two resource templates core's MCP server serves. Named here so
#: :class:`TestResourceTemplateGap` can say what the settled convention
#: is *about*; the templates themselves are read live, never from this
#: list.
CORE_TEMPLATE_MARKER = "{component}"

#: The five providers the C phase left behind, by id. Named rather than
#: taken wholesale from :func:`application_registry`, because the D phase
#: is adding providers to that registry concurrently and this milestone's
#: claim is about composing with *those five* — a claim that would
#: quietly become a different one as the registry grew.
C_PHASE_PROVIDERS = ("catalog", "concepts-language", "concepts-product", "core", "repo")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

#: An absolute POSIX path anywhere in a serialized build. The leading
#: context class keeps a served resource URI — ``s0ma://guide/errors``,
#: a name and not a file — from reading as one.
_POSIX_PATH = re.compile(r"""(?:^|[\s"(\[])/(?:Users|home|private|tmp|var|opt|usr|etc)/""")

#: A Windows drive letter, with the lookbehind that keeps ``s0ma://``
#: and ``mcp:resource/`` out of it.
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]")


# ---------------------------------------------------------------------------
# The live boundary, read independently of the provider
# ---------------------------------------------------------------------------


def _live_server() -> Any:
    from s0ma_mcp import create_server

    return create_server()


def _live_names() -> dict[str, set[str]]:
    """What a client sees, built here rather than asked of the provider.

    A different server object and a different set of calls, so every
    comparison below is a parity check and not a restatement.
    """
    server = _live_server()
    return {
        "tools": {str(tool.name) for tool in asyncio.run(server.list_tools())},
        "resources": {
            str(resource.uri) for resource in asyncio.run(server.list_resources())
        },
        "prompts": {str(prompt.name) for prompt in asyncio.run(server.list_prompts())},
    }


def _live_annotations() -> dict[str, dict[str, object]]:
    """Every served tool's set annotation hints, unset ones dropped."""
    server = _live_server()
    found: dict[str, dict[str, object]] = {}
    for tool in asyncio.run(server.list_tools()):
        raw = tool.annotations.model_dump(mode="json") if tool.annotations else {}
        found[str(tool.name)] = {
            key: value for key, value in raw.items() if value is not None
        }
    return found


def _catalog_rows() -> dict[str, str]:
    """Every catalog row, canonical source mapped to its ``doc:`` id."""
    document = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {row["canonical_source"]: row["id"] for row in document["documents"]}


def _composed() -> Composition:
    return compose(
        ProviderRegistry.of(McpProvider(root=REPO_ROOT)), release_version=RELEASE
    )


def _composed_text() -> str:
    """The MCP build's canonical text. Read from a subprocess too."""
    return serialize_bundle(_composed().bundle)


@pytest.fixture(scope="module")
def provider() -> McpProvider:
    """One reading of the server, shared by every test that inspects it."""
    return McpProvider(root=REPO_ROOT)


@pytest.fixture(scope="module")
def composition() -> Composition:
    return _composed()


def _surfaces(provider: McpProvider, channel: str) -> list[SurfaceRecord]:
    return sorted(
        (
            item.record
            for item in provider.provide().records
            if isinstance(item.record, SurfaceRecord) and item.record.channel == channel
        ),
        key=lambda record: record.id,
    )


def _c_phase() -> tuple[Any, ...]:
    """The five C-phase providers, in registration order, and no others."""
    held = {
        provider.provider_id: provider
        for provider in application_registry(REPO_ROOT).providers()
    }
    missing = [name for name in C_PHASE_PROVIDERS if name not in held]
    assert missing == [], f"the C-phase providers have moved: {missing}"
    return tuple(held[name] for name in C_PHASE_PROVIDERS)


def _root_with_snapshot(destination: Path, text: str) -> Path:
    """A minimal root carrying one snapshot file, for the failure cases."""
    path = destination / SNAPSHOT_SOURCE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return destination


# ---------------------------------------------------------------------------
# T1 — the three-source cross-check
# ---------------------------------------------------------------------------


class TestThreeSourceCrossCheck:
    """Architecture plan §7.4: three accounts, agreeing, before any record."""

    def test_the_three_sources_agree_on_the_live_tree(self) -> None:
        """Constructing the provider *is* the assertion — it refuses otherwise."""
        assert McpProvider(root=REPO_ROOT).provide().records

    def test_every_source_is_named_with_its_own_digest(
        self, provider: McpProvider
    ) -> None:
        checked = dict(provider.cross_checked_sources())
        assert set(checked) == {REGISTRATION_SOURCE, SNAPSHOT_SOURCE, SERVED_SOURCE}
        for source, digest in checked.items():
            assert _SHA256.match(digest), source
        assert len(set(checked.values())) == 3, (
            "two sources share a digest, so one of them is not being read"
        )

    def test_the_snapshot_digest_is_the_committed_file(
        self, provider: McpProvider
    ) -> None:
        """A file source is hashed as bytes, not as the facts read from it."""
        import hashlib

        raw = (REPO_ROOT / SNAPSHOT_SOURCE).read_bytes()
        assert dict(provider.cross_checked_sources())[SNAPSHOT_SOURCE] == (
            hashlib.sha256(raw).hexdigest()
        )

    def test_a_snapshot_that_lost_a_tool_fails_naming_all_three(
        self, tmp_path: Path
    ) -> None:
        document = json.loads((REPO_ROOT / SNAPSHOT_SOURCE).read_text(encoding="utf-8"))
        dropped = document["tools"].pop()
        root = _root_with_snapshot(tmp_path / "lost", json.dumps(document))
        with pytest.raises(McpSurfaceDisagreementError) as caught:
            McpProvider(root=root)
        message = str(caught.value)
        for source in (REGISTRATION_SOURCE, SNAPSHOT_SOURCE, SERVED_SOURCE):
            assert source in message, source
        assert dropped["name"] in message
        assert "regenerate" in message.lower()

    def test_a_snapshot_that_invented_a_resource_fails_naming_all_three(
        self, tmp_path: Path
    ) -> None:
        document = json.loads((REPO_ROOT / SNAPSHOT_SOURCE).read_text(encoding="utf-8"))
        document["resources"].append({**document["resources"][0], "uri": "s0ma://made/up"})
        root = _root_with_snapshot(tmp_path / "invented", json.dumps(document))
        with pytest.raises(McpSurfaceDisagreementError) as caught:
            McpProvider(root=root)
        message = str(caught.value)
        assert "s0ma://made/up" in message
        assert message.count(SNAPSHOT_SOURCE) >= 2, (
            "the source that has the extra resource must be named in the "
            "difference, not only in the header"
        )

    def test_a_snapshot_whose_annotation_moved_fails(self, tmp_path: Path) -> None:
        """The hint the side-effect facts are read off cannot drift silently."""
        document = json.loads((REPO_ROOT / SNAPSHOT_SOURCE).read_text(encoding="utf-8"))
        target = next(item for item in document["tools"] if item["name"] == "check")
        target["annotations"]["readOnlyHint"] = False
        root = _root_with_snapshot(tmp_path / "hint", json.dumps(document))
        with pytest.raises(McpSurfaceDisagreementError) as caught:
            McpProvider(root=root)
        message = str(caught.value)
        assert "annotations" in message
        assert "check" in message

    def test_an_absent_snapshot_is_refused_rather_than_skipped(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(McpProviderError) as caught:
            McpProvider(root=tmp_path / "empty")
        assert SNAPSHOT_SOURCE in str(caught.value)

    def test_a_malformed_snapshot_says_what_was_expected(self, tmp_path: Path) -> None:
        root = _root_with_snapshot(tmp_path / "partial", json.dumps({"tools": []}))
        with pytest.raises(McpProviderError) as caught:
            McpProvider(root=root)
        assert "resources" in str(caught.value)


# ---------------------------------------------------------------------------
# T2 — the emitted surface
# ---------------------------------------------------------------------------


class TestServedSurfaces:
    """One record per served surface, counted against the live listing."""

    def test_the_record_count_equals_the_live_listing(
        self, provider: McpProvider
    ) -> None:
        live = _live_names()
        expected = sum(len(found) for found in live.values())
        assert provider.provide().counts()["surfaces"] == expected

    def test_every_served_tool_has_exactly_one_record(
        self, provider: McpProvider
    ) -> None:
        served = _live_names()["tools"]
        records = _surfaces(provider, "mcp_tool")
        assert [record.public_name for record in records] == sorted(served)
        assert {record.id for record in records} == {
            f"mcp:tool/{name}" for name in served
        }

    def test_every_served_resource_has_exactly_one_record(
        self, provider: McpProvider
    ) -> None:
        served = _live_names()["resources"]
        records = _surfaces(provider, "mcp_resource")
        assert [record.public_name for record in records] == sorted(served)
        assert {record.id for record in records} == {
            f"mcp:resource/{uri}" for uri in served
        }

    def test_every_served_prompt_has_exactly_one_record(
        self, provider: McpProvider
    ) -> None:
        served = _live_names()["prompts"]
        records = _surfaces(provider, "mcp_prompt")
        assert [record.public_name for record in records] == sorted(served)

    def test_no_record_is_on_a_channel_this_provider_does_not_serve(
        self, provider: McpProvider
    ) -> None:
        channels = {
            item.record.channel
            for item in provider.provide().records
            if isinstance(item.record, SurfaceRecord)
        }
        assert channels == {"mcp_tool", "mcp_resource", "mcp_prompt"}

    def test_every_id_is_a_form_the_model_addresses(
        self, provider: McpProvider
    ) -> None:
        for item in provider.provide().records:
            assert is_valid_id(item.record.id), item.record.id

    def test_the_intent_is_the_served_descriptions_first_line(
        self, provider: McpProvider
    ) -> None:
        """A quotation, not a summary: the sentence the author wrote first."""
        server = _live_server()
        served = {
            f"mcp:tool/{tool.name}": (tool.description or "")
            for tool in asyncio.run(server.list_tools())
        }
        for record in _surfaces(provider, "mcp_tool"):
            first = next(
                (
                    " ".join(line.split())
                    for line in served[record.id].splitlines()
                    if line.strip()
                ),
                "",
            )
            assert record.intent == first, record.id
            assert "\n" not in record.intent

    def test_no_record_claims_an_error_or_an_authority(
        self, provider: McpProvider
    ) -> None:
        """Both are honest emptiness — see the module docstring's list."""
        for item in provider.provide().records:
            record = item.record
            assert isinstance(record, SurfaceRecord)
            assert record.errors == ()
            assert record.governed_by == ()


# ---------------------------------------------------------------------------
# Side effects — the DOC_SIDE_EFFECT_UNDECLARED seed
# ---------------------------------------------------------------------------

#: The vocabulary architecture plan §6.3 gives the field.
EFFECTS = frozenset(
    {"none", "read", "write", "network", "subprocess", "credential", "approval"}
)


class TestSideEffectFacts:
    """Every effect present, every one of them read off something."""

    def test_every_surface_declares_at_least_one_effect(
        self, provider: McpProvider
    ) -> None:
        for item in provider.provide().records:
            record = item.record
            assert isinstance(record, SurfaceRecord)
            assert record.side_effects, record.id
            assert set(record.side_effects) <= EFFECTS, record.id
            assert list(record.side_effects) == sorted(record.side_effects)

    def test_the_read_write_fact_matches_the_served_annotation(
        self, provider: McpProvider
    ) -> None:
        """``readOnlyHint`` is the protocol's promise, so it is the source."""
        annotations = _live_annotations()
        for record in _surfaces(provider, "mcp_tool"):
            hint = annotations[record.public_name]["readOnlyHint"]
            expected = "read" if hint else "write"
            assert expected in record.side_effects, record.id
            assert ("write" in record.side_effects) is not bool(hint), record.id

    def test_every_write_tool_is_visible_as_one(self, provider: McpProvider) -> None:
        annotations = _live_annotations()
        writing = {
            name for name, hints in annotations.items() if hints["readOnlyHint"] is False
        }
        assert writing, "no tool writes — the annotations stopped being read"
        recorded = {
            record.public_name
            for record in _surfaces(provider, "mcp_tool")
            if "write" in record.side_effects
        }
        assert recorded == writing

    def test_the_escalated_tools_carry_facts_no_hint_could_give(
        self, provider: McpProvider
    ) -> None:
        """The seed D5 reads: network, subprocess and approval, present."""
        by_id = {record.id: record for record in _surfaces(provider, "mcp_tool")}
        assert "network" in by_id["mcp:tool/submit_feedback"].side_effects
        assert "approval" in by_id["mcp:tool/submit_feedback"].side_effects
        assert "subprocess" in by_id["mcp:tool/run_example"].side_effects
        assert "subprocess" in by_id["mcp:tool/verify_host"].side_effects
        assert "approval" in by_id["mcp:tool/verify_host"].side_effects

    def test_the_feedback_boundary_is_on_submit_and_not_on_prepare(
        self, provider: McpProvider
    ) -> None:
        """The frozen contract's shape, carried structurally.

        ``prepare_feedback`` writes nothing and asks nothing; the
        user-only approval and the send both live on ``submit_feedback``.
        A record that put the approval on the preparing tool would
        describe a product that asks before it has anything to show.
        """
        by_id = {record.id: record for record in _surfaces(provider, "mcp_tool")}
        prepare = by_id["mcp:tool/prepare_feedback"]
        submit = by_id["mcp:tool/submit_feedback"]
        assert prepare.side_effects == ("read",)
        assert set(submit.side_effects) == {"approval", "network", "write"}

    def test_every_hand_classification_is_explained_in_its_record(
        self, provider: McpProvider
    ) -> None:
        by_id = {record.id: record for record in _surfaces(provider, "mcp_tool")}
        for identifier, (effects, reason) in _HAND_CLASSIFIED.items():
            record = by_id[identifier]
            assert record.side_effects == tuple(sorted(effects))
            assert record.manual_exception == reason
            assert "by hand" in reason

    def test_only_the_escalated_tools_carry_an_exception(
        self, provider: McpProvider
    ) -> None:
        """Everything else is derived, and says so by saying nothing."""
        annotations = _live_annotations()
        escalated = {
            f"mcp:tool/{name}"
            for name, hints in annotations.items()
            if hints.get("destructiveHint") is True or hints.get("openWorldHint") is True
        }
        assert escalated == set(_HAND_CLASSIFIED)
        with_exception = {
            item.record.id
            for item in provider.provide().records
            if isinstance(item.record, SurfaceRecord) and item.record.manual_exception
        }
        assert with_exception == escalated

    def test_a_resource_reads_and_a_prompt_does_not_act(
        self, provider: McpProvider
    ) -> None:
        for record in _surfaces(provider, "mcp_resource"):
            assert record.side_effects == ("read",), record.id
        for record in _surfaces(provider, "mcp_prompt"):
            assert record.side_effects == ("none",), record.id

    def test_an_unclassified_escalated_tool_would_be_refused(self) -> None:
        """The refusal, exercised without a server that has one.

        A mutating tool recorded as a plain local write is the mistake
        the hand-classification exists against, so the refusal is
        proved rather than assumed.
        """
        from s0ma_dsl.docs_model.providers_mcp import _tool_effects

        with pytest.raises(McpProviderError) as caught:
            _tool_effects(
                "mcp:tool/invented",
                {"readOnlyHint": False, "openWorldHint": True},
            )
        assert "openWorldHint" in str(caught.value)
        assert "credential" in str(caught.value)

    def test_a_tool_without_the_hint_is_refused(self) -> None:
        from s0ma_dsl.docs_model.providers_mcp import _tool_effects

        with pytest.raises(McpProviderError) as caught:
            _tool_effects("mcp:tool/invented", {})
        assert "readOnlyHint" in str(caught.value)

    def test_a_classification_contradicting_its_hint_is_refused(self) -> None:
        from s0ma_dsl.docs_model.providers_mcp import _tool_effects

        with pytest.raises(McpProviderError) as caught:
            _tool_effects(
                "mcp:tool/run_example",
                {"readOnlyHint": True, "destructiveHint": True},
            )
        assert "may not contradict" in str(caught.value)


# ---------------------------------------------------------------------------
# Binding — the provider where it should be total
# ---------------------------------------------------------------------------


class TestBinding:
    """Every served surface reaches the registration that names it."""

    def test_every_surface_binds_to_exactly_one_component(
        self, provider: McpProvider
    ) -> None:
        for item in provider.provide().records:
            record = item.record
            assert isinstance(record, SurfaceRecord)
            assert len(record.component_refs) == 1, record.id
            assert is_valid_id(record.component_refs[0]), record.id

    def test_the_binding_is_total(self, provider: McpProvider) -> None:
        """The ratio D3 reports: thirty-one of thirty-one, no exceptions."""
        records = [item.record for item in provider.provide().records]
        bound = [
            record
            for record in records
            if isinstance(record, SurfaceRecord) and record.component_refs
        ]
        assert len(bound) == len(records)

    def test_no_surface_carries_a_binding_exception(
        self, provider: McpProvider
    ) -> None:
        """An exception here would mean a binding somebody guessed at.

        Every ``manual_exception`` this provider emits explains a
        side-effect classification. None explains a binding, because
        the binding is declared in the registration itself.
        """
        for item in provider.provide().records:
            record = item.record
            assert isinstance(record, SurfaceRecord)
            if record.manual_exception:
                assert record.id in _HAND_CLASSIFIED

    def test_every_binding_is_in_the_inventory_this_provider_vouches_for(
        self, provider: McpProvider
    ) -> None:
        inventory = set(provider.component_ids())
        for item in provider.provide().records:
            record = item.record
            assert isinstance(record, SurfaceRecord)
            assert set(record.component_refs) <= inventory, record.id

    def test_the_binding_points_at_the_registration_that_declares_it(
        self, provider: McpProvider
    ) -> None:
        """Parity against the live registry, read here independently."""
        from s0ma_mcp import get_self_registry

        declared: dict[str, str] = {}
        for spec in get_self_registry().get_all().values():
            metadata = spec.metadata or {}
            for key, prefix in (
                ("mcp_tool", "mcp:tool/"),
                ("mcp_uri", "mcp:resource/"),
                ("mcp_prompt", "mcp:prompt/"),
            ):
                served = metadata.get(key)
                if served is not None:
                    declared[f"{prefix}{served}"] = f"component:{spec.qualified_name}"
        emitted = {
            item.record.id: item.record.component_refs[0]
            for item in provider.provide().records
            if isinstance(item.record, SurfaceRecord)
        }
        assert emitted == declared

    def test_every_registration_is_addressable(self, provider: McpProvider) -> None:
        """D5a's flip: the flat-name family is addressed, not counted.

        D3 pinned two registrations — ``s0ma_mcp.create_server`` and
        ``s0ma_mcp.get_self_registry`` — as unaddressable, because the
        ``component:`` form demanded three dotted segments. D5a relaxed
        the floor to two, so the inventory is whole: the split still
        exists as a guard, and the deferred half is empty.
        """
        from s0ma_mcp import get_self_registry

        registered = len(get_self_registry().get_all())
        assert len(provider.component_ids()) == registered
        assert provider.unaddressable_components() == ()

    def test_the_two_package_flat_registrations_are_in_the_inventory(
        self, provider: McpProvider
    ) -> None:
        """Named, so the emptiness above cannot be an empty registry.

        Read from the live registry rather than written out: these two
        are the exact registrations D3 could not address, and the point
        of the flip is that they are ids now.
        """
        from s0ma_mcp import get_self_registry

        flat = sorted(
            f"component:{spec.qualified_name}"
            for spec in get_self_registry().get_all().values()
            if str(spec.qualified_name).count(".") == 1
        )
        assert flat, "s0ma-mcp registers nothing package-flat — revisit D3's finding"
        for identifier in flat:
            assert is_valid_id(identifier), identifier
            assert identifier in provider.component_ids(), identifier

    def test_a_registration_the_form_cannot_reach_would_still_be_counted(
        self, provider: McpProvider
    ) -> None:
        """The guard, still armed against the case that has no package at all."""
        assert not is_valid_id("component:create_server")

    def test_the_external_ids_are_the_component_inventory(
        self, provider: McpProvider
    ) -> None:
        assert provider.external_ids() == provider.component_ids()


# ---------------------------------------------------------------------------
# T0 — the resource-template id convention
# ---------------------------------------------------------------------------


class TestResourceTemplateGap:
    """D3's T0, and the id form D5a added to close it.

    The convention this milestone settled: a parameterized served
    address keeps its braces in its id, the way ``rest:`` already does.
    The ``mcp:resource/`` charset excluded them, so the form could not
    say it and ``ids.py`` was not D3's to edit.

    D5a widened the charset by exactly ``{}``. Every half is still
    asserted from a live server, so none of it can rot — the second
    test used to say a braced address was unaddressable and now says it
    is addressable, which is the flip that records the completion.
    """

    def test_this_server_serves_no_resource_template(
        self, provider: McpProvider
    ) -> None:
        """The evidence T0 rests on, read live rather than assumed."""
        server = _live_server()
        assert asyncio.run(server.list_resource_templates()) == []
        assert provider.resource_templates() == ()

    def test_the_form_addresses_a_braced_resource_address(self) -> None:
        """Read off core's live templates, which are the ones that needed it."""
        core = pytest.importorskip("s0ma.api.mcp_server")
        from s0ma._bootstrap import bootstrap_register
        from s0ma.registry import ComponentRegistry

        live = ComponentRegistry(persist=False)
        bootstrap_register(live)
        templates = asyncio.run(
            core.create_mcp_server(live).list_resource_templates()
        )
        parameterized = [
            str(template.uriTemplate)
            for template in templates
            if CORE_TEMPLATE_MARKER in str(template.uriTemplate)
        ]
        assert parameterized, "core serves no template — revisit T0"
        for uri in parameterized:
            assert is_valid_id(f"mcp:resource/{uri}"), uri

    def test_the_rest_form_is_the_precedent_the_convention_follows(self) -> None:
        """One parameterized served address is already addressed with braces."""
        assert is_valid_id("rest:GET:/self/component/{name}")

    def test_a_brace_free_normalization_would_not_round_trip(self) -> None:
        """Why the convention is not "strip them": two things, one id."""
        stripped = "mcp:resource/s0ma://model/examples-for/component"
        assert is_valid_id(stripped)
        # ...and that is exactly the id a literal resource of that
        # address would carry, so the template and the concrete
        # resource would be indistinguishable.
        assert stripped == "mcp:resource/" + "s0ma://model/examples-for/component"
        for candidate in ("<component>", "%7Bcomponent%7D"):
            assert not is_valid_id(f"mcp:resource/s0ma://model/examples-for/{candidate}")


# ---------------------------------------------------------------------------
# The mirror correspondence
# ---------------------------------------------------------------------------


class TestMirroredDocuments:
    """The served resource and the catalog row, held against each other."""

    def test_the_provider_emits_no_document_record(
        self, provider: McpProvider
    ) -> None:
        """Documents belong to the catalog; a second account would drift."""
        assert provider.provide().counts()["documents"] == 0
        for item in provider.provide().records:
            assert not isinstance(item.record, DocumentRecord)

    def test_every_mirror_is_a_catalog_row(self, provider: McpProvider) -> None:
        rows = _catalog_rows()
        for mirror in provider.mirrored_documents():
            assert mirror.mirror in rows, mirror.mirror
            assert rows[mirror.mirror].startswith("doc:mirror/"), mirror.mirror

    def test_every_cataloged_mirror_is_served(self, provider: McpProvider) -> None:
        """The other direction: a packaged copy nobody serves is dead weight."""
        cataloged = {
            source for source in _catalog_rows() if source.startswith(f"{MIRROR_DIR}/")
        }
        assert cataloged == {mirror.mirror for mirror in provider.mirrored_documents()}

    def test_every_canonical_source_is_itself_cataloged(
        self, provider: McpProvider
    ) -> None:
        """The mirror points at a document the catalog also holds."""
        rows = _catalog_rows()
        for mirror in provider.mirrored_documents():
            assert mirror.canonical in rows, mirror.canonical

    def test_every_mirror_names_a_resource_this_provider_emits(
        self, provider: McpProvider
    ) -> None:
        emitted = {record.id for record in _surfaces(provider, "mcp_resource")}
        for mirror in provider.mirrored_documents():
            assert mirror.resource in emitted, mirror.resource

    def test_the_paths_are_repository_relative(self, provider: McpProvider) -> None:
        for mirror in provider.mirrored_documents():
            for path in (mirror.mirror, mirror.canonical):
                assert not path.startswith("/"), path
                assert "\\" not in path, path
                assert (REPO_ROOT / path).is_file(), path

    def test_a_missing_packaged_copy_is_refused(
        self, tmp_path: Path, provider: McpProvider
    ) -> None:
        """A mirror fact naming a file nobody ships describes nothing."""
        root = tmp_path / "hollow"
        (root / SNAPSHOT_SOURCE).parent.mkdir(parents=True)
        shutil.copy(REPO_ROOT / SNAPSHOT_SOURCE, root / SNAPSHOT_SOURCE)
        with pytest.raises(McpProviderError) as caught:
            McpProvider(root=root)
        assert MIRROR_DIR in str(caught.value)


# ---------------------------------------------------------------------------
# The provider contract
# ---------------------------------------------------------------------------


class TestProviderContract:
    """Architecture plan §7.1, at the points it is checkable."""

    def test_the_provider_satisfies_the_protocol(self, provider: McpProvider) -> None:
        assert provider.provider_id == PROVIDER_ID
        assert provider.provide().provider_id == PROVIDER_ID

    def test_the_records_arrive_sorted(self, provider: McpProvider) -> None:
        records = provider.provide().records
        assert list(records) == sorted(records, key=record_key)
        assert records == sort_records(records)

    def test_reading_twice_returns_the_same_records(
        self, provider: McpProvider
    ) -> None:
        assert provider.provide() is provider.provide()

    def test_every_record_carries_all_four_parts_of_its_provenance(
        self, provider: McpProvider
    ) -> None:
        for item in provider.provide().records:
            provenance = item.provenance
            assert provenance.adapter_id == PROVIDER_ID
            assert provenance.schema_version == SCHEMA
            assert provenance.source == SERVED_SOURCE
            assert _SHA256.match(provenance.source_sha256), item.record.id

    def test_the_provider_registers_under_its_own_id(
        self, provider: McpProvider
    ) -> None:
        holder = ProviderRegistry.of(provider)
        assert holder.ids() == (PROVIDER_ID,)


# ---------------------------------------------------------------------------
# Determinism and machine paths
# ---------------------------------------------------------------------------


class TestDeterminism:
    """The same reading is the same bytes, here and in a fresh process."""

    def test_two_readings_are_byte_identical(self) -> None:
        assert _composed_text() == _composed_text()

    def test_two_providers_produce_equal_results(self) -> None:
        assert McpProvider(root=REPO_ROOT).provide() == McpProvider(
            root=REPO_ROOT
        ).provide()

    def test_the_build_is_the_same_under_any_hash_seed(self) -> None:
        """The registry and the three listings are dictionaries somewhere."""
        script = (
            "from tests.test_docs_provider_mcp import _composed_text;"
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
        text = _composed_text()
        for path in (REPO_ROOT, Path.home()):
            assert str(path) not in text, path

    def test_the_pattern_would_notice_a_machine_path(self) -> None:
        assert _POSIX_PATH.search('  "source": "/Users/somebody/s0ma/mcp.py"')
        assert _WINDOWS_PATH.search('  "source": "C:\\\\s0ma\\\\mcp.py"')
        assert not _POSIX_PATH.search('  "id": "mcp:resource/s0ma://guide/errors"')
        assert not _WINDOWS_PATH.search('  "id": "mcp:resource/s0ma://guide/errors"')


# ---------------------------------------------------------------------------
# Composition and the floors
# ---------------------------------------------------------------------------


class TestComposition:
    """The provider in a build, with every gate C2 owns run over it."""

    def test_it_composes_alone_with_nothing_wrong(
        self, composition: Composition
    ) -> None:
        assert composition.ok
        assert composition.findings == ()

    def test_every_gate_is_silent_when_the_inventory_is_handed_over(
        self, provider: McpProvider, composition: Composition
    ) -> None:
        findings = validate_bundle(
            composition.bundle,
            results=composition.results,
            external_ids=provider.external_ids(),
            floors=MCP_FLOORS,
        )
        assert findings == ()

    def test_without_the_inventory_every_surface_is_unbound(
        self, composition: Composition
    ) -> None:
        """The truthful answer when nobody has said what components exist."""
        findings = validate_bundle(composition.bundle, results=composition.results)
        assert findings
        assert {finding.code for finding in findings} == {"DOC_SURFACE_UNBOUND"}

    def test_it_composes_with_the_c_phase_providers_and_finds_nothing(self) -> None:
        """D3 beside C3–C6: six providers, one bundle, zero findings.

        The surface gates are the ones this milestone can be held to:
        every record resolves, nothing contradicts itself, and the MCP
        floor is met. The C phase's own authority anchors are its
        milestone's business and are not re-asserted here.
        """
        # Since the E wave the catalog's guide rows cover journeys, which
        # step through D-phase surfaces and recover through diagnostics —
        # so the "beside the five C-phase providers" subset cannot compose
        # clean by construction any more. The claim this test now holds is
        # the surviving strong one: the provider composes inside the full
        # application registry with zero findings and its records intact.
        registry = application_registry(REPO_ROOT)
        merged = compose(registry, release_version=RELEASE)
        assert merged.findings == ()

        external: set[str] = set(EvidenceLibrary.load(REPO_ROOT).ids())
        for item in registry.providers():
            if hasattr(item, "external_ids"):
                external.update(item.external_ids())
        findings = validate_bundle(
            merged.bundle,
            results=merged.results,
            external_ids=sorted(external),
            floors=MCP_FLOORS,
            # Core is one of the C-phase providers here, and twenty-nine
            # of its surfaces declare no side effects: its MCP tools carry
            # no ToolAnnotations, which is the asymmetry this provider's
            # tools are the other half of. D5b's allowances say so in
            # writing, per source.
            allowances=SIDE_EFFECT_ALLOWANCES,
        )
        assert [finding.rendered() for finding in findings] == []

    def test_no_c_phase_provider_already_emits_these_ids(self) -> None:
        """A merge that silently replaced a record would be invisible here."""
        emitted = {
            item.record.id for item in McpProvider(root=REPO_ROOT).provide().records
        }
        for item in _c_phase():
            existing = {entry.record.id for entry in item.provide().records}
            assert not (emitted & existing), (
                f"{item.provider_id} already emits {sorted(emitted & existing)}"
            )

    def test_the_shipped_floor_is_met(self, composition: Composition) -> None:
        assert check_floors(composition.results, MCP_FLOORS) == []

    def test_a_floor_above_the_truth_reports_a_vacuous_gate(
        self, composition: Composition
    ) -> None:
        served = composition.results[0].counts()["surfaces"]
        findings = check_floors(composition.results, {(PROVIDER_ID, "surfaces"): served + 1})
        assert [finding.code for finding in findings] == [DOC_GATE_VACUOUS]

    def test_the_floor_would_notice_a_family_going_missing(
        self, composition: Composition
    ) -> None:
        """Set so the smallest family cannot vanish under it."""
        counts = {kind: len(names) for kind, names in _live_names().items()}
        served = sum(counts.values())
        floor = MCP_FLOORS[(PROVIDER_ID, "surfaces")]
        assert floor <= served
        assert served - min(counts.values()) < floor


# ---------------------------------------------------------------------------
# Source hygiene
# ---------------------------------------------------------------------------


class TestDependencies:
    """The dependency direction, checked against the source itself."""

    def test_the_mcp_package_is_never_imported_at_module_level(self) -> None:
        """``s0ma-dsl`` does not depend on ``s0ma-mcp``, and must not.

        A module-level import would invert the direction the four
        packages ship in and make ``docs_model`` unimportable for
        anyone who installed only the transpiler.
        """
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        top_level: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level.append(node.module)
        for name in top_level:
            assert not name.startswith(("s0ma_mcp", "s0ma.", "mcp")), name
        assert "s0ma" not in top_level

    def test_the_module_imports_nothing_it_should_not(self) -> None:
        """This package, the standard library, and the MCP package. No more."""
        forbidden = ("s0ma_studi0", "fastapi", "spike_", "scripts.")
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        offenders = [name for name in imported if name.startswith(forbidden)]
        assert offenders == [], f"providers_mcp.py imports {offenders}"

    def test_the_source_is_utf8_with_line_feeds(self) -> None:
        raw = MODULE_PATH.read_bytes()
        raw.decode("utf-8")
        assert b"\r\n" not in raw

    def test_the_provider_reads_no_registry_core_would_persist(self) -> None:
        """Nothing here builds a core registry, let alone a persisted one."""
        text = MODULE_PATH.read_text(encoding="utf-8")
        assert "get_registry" not in text
        assert "ComponentRegistry(" not in text


class TestCoreProviderStaysOutOfThisChannel:
    """C3 emits core's tools; D3 emits the authoring server's. Not both."""

    def test_the_two_providers_describe_different_servers(self) -> None:
        core = {item.record.id for item in CoreProvider().provide().records}
        mine = {item.record.id for item in McpProvider(root=REPO_ROOT).provide().records}
        assert core & mine == set()
