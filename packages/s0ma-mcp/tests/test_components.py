"""Tests for the s0ma-mcp self-model (PRD FR-MCP-7, plan invariants D-1/D-3/D-6).

Three layers:

* registration — the dedicated self-registry populates exactly once,
  idempotently, with agent-quality metadata on every component;
* surfaces — ``s0ma://self/model`` and ``describe_server`` round-trip
  the live component graph over the in-process MCP boundary;
* the derived surface (SH-M4, the repurposed D-6 gate) — since
  ``create_server`` DERIVES every FastMCP registration from the
  self-model catalog, set-drift between the registry and the served
  surface is structurally impossible; what these tests assert instead
  is (a) every MCP-surfaced component carries COMPLETE serving
  metadata and actually appears in ``list_tools`` / ``list_resources``
  / ``list_prompts``, (b) the catalog partitions exactly into served
  surfaces and the documented ``UNSERVED_COMPONENTS`` plumbing, (c)
  derivation is real — an injected fake component with MCP metadata is
  served WITHOUT touching the factory, and (d) the package contains
  exactly ONE handwritten Python module (D-1, read from the
  filesystem).

How to add a surface: author a ``.s0ma`` declaration carrying the
``mcp_*`` attributes (see the ``s0ma_mcp`` bootstrap-module docstring)
— the bridge catalogs it and the factory serves it; nothing here needs
editing. Only a new piece of *unserved* internal plumbing needs an
``UNSERVED_COMPONENTS`` entry.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")

from s0ma.decorators import get_component_spec, is_component
from s0ma.models import ComponentSpec
from s0ma.types import ComponentKind, Layer

import s0ma_mcp
from s0ma_mcp import (
    SERVER_NAME,
    UNSERVED_COMPONENTS,
    create_server,
    get_self_registry,
    prompts,
    resources,
    self_model_document,
    tools,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

#: Every MCP tool the server serves (drift-gated below; the fixed list
#: here additionally pins the M0 floor so a tool cannot silently vanish).
EXPECTED_TOOL_COMPONENTS = {
    "transpile",
    "build_project",
    "adopt_file",
    "check",
    "verify_host",
    "inspect_module",
    "project_status",
    "init_project",
    "run_example",
    "migrate_ext",
    "scaffold_module",
    "describe_server",
    "prepare_feedback",
    "submit_feedback",
    # F7: the documentation read surface.
    "learn_s0ma",
}

EXPECTED_RESOURCE_COMPONENTS = {
    "s0ma://guide/getting-started",
    "s0ma://guide/self-prompting",
    "s0ma://guide/survival-card",
    "s0ma://guide/system-prompt",
    "s0ma://guide/quick-reference",
    # Surface contract R5 (owner ruling 2026-09-29): the quick reference's
    # data twin, served beside the page from the same packaged pair.
    "s0ma://guide/quick-reference.json",
    "s0ma://guide/patterns",
    "s0ma://guide/errors",
    "s0ma://spec/current",
    "s0ma://meta/changelog",
    "s0ma://meta/version",
    "s0ma://self/model",
    # F7: the documentation resource family, served from the packaged
    # snapshot. The three s0ma://docs/* addresses core's runtime server
    # serves are NOT these and are not served here (see the index).
    "s0ma://docs/index",
    "s0ma://docs/concepts",
    "s0ma://docs/journeys",
}

#: Every MCP prompt the server serves (M1, FR-MCP-6).
EXPECTED_PROMPT_COMPONENTS = {
    "author_module",
    "fix_check_failures",
    "migrate_project",
}


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _served_surface(mcp_server: FastMCP) -> set[str]:
    """Every name the server actually serves over MCP.

    Tools and prompts list by name; resources by URI — matching the
    component-naming rule in components.py. Prompts are collected from
    M0 onward so M1 needs no test changes.
    """
    tool_names = {t.name for t in _run(mcp_server.list_tools())}
    resource_uris = {str(r.uri) for r in _run(mcp_server.list_resources())}
    prompt_names = {p.name for p in _run(mcp_server.list_prompts())}
    return tool_names | resource_uris | prompt_names


@pytest.fixture(scope="module")
def mcp_server() -> FastMCP:
    return create_server()


class TestSelfRegistration:
    """The dedicated registry: populated once, idempotently, truthfully."""

    def test_registry_is_a_stable_singleton(self) -> None:
        assert get_self_registry() is get_self_registry()

    def test_repeated_factory_calls_do_not_grow_the_registry(self) -> None:
        before = get_self_registry().snapshot().component_count
        create_server()
        create_server()
        assert get_self_registry().snapshot().component_count == before

    def test_component_floor(self) -> None:
        """M0 acceptance: at least 9 components (7 tools + factory + providers)."""
        assert get_self_registry().snapshot().component_count >= 9

    def test_all_mcp_surfaces_are_registered(self) -> None:
        names = set(get_self_registry().snapshot().components)
        assert names >= EXPECTED_TOOL_COMPONENTS
        assert names >= EXPECTED_RESOURCE_COMPONENTS
        assert names >= EXPECTED_PROMPT_COMPONENTS

    def test_every_component_has_an_agent_quality_intent(self) -> None:
        for name, spec in get_self_registry().snapshot().components.items():
            assert spec.intent and len(spec.intent) >= 10, (
                f"component '{name}' has no usable intent — these strings "
                "are the product (FR-MCP-7)"
            )

    def test_every_component_carries_kind_layer_and_version(self) -> None:
        for spec in get_self_registry().snapshot().components.values():
            assert isinstance(spec.kind, ComponentKind)
            assert isinstance(spec.layer, Layer)
            assert spec.version == s0ma_mcp.__version__
            assert spec.module_path.startswith("s0ma_mcp")

    def test_dependency_graph_is_closed(self) -> None:
        """Every declared dependency is itself a registered component."""
        components = get_self_registry().snapshot().components
        for name, spec in components.items():
            dangling = set(spec.dependencies) - set(components)
            assert not dangling, (
                f"component '{name}' depends on unregistered {sorted(dangling)}"
            )

    def test_served_components_follow_the_taxonomy_recipe(self) -> None:
        """Served tools/resources/prompts are FUNCTION/PRESENTATION.

        Deliberate friction: a new surface choosing a different kind or
        layer should update the taxonomy rationale in the components.py
        docstring (and this test), not drift silently.
        """
        components = get_self_registry().snapshot().components
        served = (
            EXPECTED_TOOL_COMPONENTS
            | EXPECTED_RESOURCE_COMPONENTS
            | EXPECTED_PROMPT_COMPONENTS
        )
        for name in served:
            spec = components[name]
            assert spec.kind is ComponentKind.FUNCTION, name
            assert spec.layer is Layer.PRESENTATION, name

    def test_core_introspection_works_on_decorated_entities(self) -> None:
        """``__component__`` rides every surface entity, both authoring modes.

        Handwritten surfaces carry the catalog name via
        ``@self_component``; converted ``.s0ma`` surfaces (SH-M1) carry
        their DSL-declared identifier spec from the emitted
        ``@component`` — the catalog name mapping (URI /
        ``guide_doc_loader``) is the bridge's job, asserted in
        ``test_bridged_resources_carry_catalog_identity``.
        """
        for entity, expected_name in (
            (tools.check_tool, "check_tool"),
            (tools.describe_server_tool, "describe_server_tool"),
            (resources.load_doc, "load_doc"),
            (resources.self_model_resource, "self_model_resource"),
            (prompts.author_module_prompt, "author_module_prompt"),
            (create_server, "create_server"),
        ):
            assert is_component(entity)
            spec = get_component_spec(entity)
            assert spec is not None and spec.name == expected_name

    def test_bridged_resources_carry_catalog_identity(self) -> None:
        """SH-M1: the converted resources surface is bridged faithfully.

        Every served resource URI is cataloged with the built module's
        intent byte-for-byte, the URI stamped in ``metadata["mcp_uri"]``
        (the M4 carrier convention, ADR-001), and the package-stamped
        module path; the plumbing rename keeps ``guide_doc_loader`` as
        the catalog identity of the built ``load_doc``.
        """
        components = get_self_registry().snapshot().components
        expected_mime_types = {
            "s0ma://meta/version": "application/json",
            "s0ma://self/model": "application/json",
            "s0ma://docs/index": "text/markdown",
            "s0ma://docs/concepts": "text/markdown",
            "s0ma://docs/journeys": "text/markdown",
            # Surface contract R5: the generated quick reference is served as
            # the Markdown it is, and its data twin as JSON.
            "s0ma://guide/quick-reference": "text/markdown",
            "s0ma://guide/quick-reference.json": "application/json",
        }
        for uri in EXPECTED_RESOURCE_COMPONENTS:
            spec = components[uri]
            assert spec.metadata.get("mcp_uri") == uri, uri
            assert spec.metadata.get("mcp_mime_type") == (
                expected_mime_types.get(uri)
            ), uri  # SH-M4: authored mcp_mime_type rides the carrier
            assert spec.module_path == "s0ma_mcp.resources", uri
            provider_name = spec.qualified_name.rsplit(".", 1)[-1]
            provider = getattr(resources, provider_name)
            built_spec = get_component_spec(provider)
            assert built_spec is not None
            assert spec.intent == built_spec.intent, uri
        loader = components["guide_doc_loader"]
        assert loader.qualified_name == "s0ma_mcp.resources.load_doc"
        assert loader.kind is ComponentKind.ADAPTER
        assert loader.layer is Layer.PRESENTATION  # F-M0-6 re-layering

    def test_bridged_prompts_carry_catalog_identity(self) -> None:
        """SH-M2: the converted prompts surface is bridged faithfully.

        Every served prompt is cataloged under its MCP prompt name
        (read from the IR's authored ``mcp_prompt:`` attribute — the
        built declaration itself is ``_prompt``-suffixed so the
        self/global registry name-disjointness invariant survives
        identifier-shaped prompt names), with the name stamped in
        ``metadata["mcp_prompt"]``, the built module's intent
        byte-for-byte, the package-stamped module path, and the
        referential dependency edges (``mcp_dependency:`` attributes —
        the tools/resources the rendered copy names) in authored order.
        """
        components = get_self_registry().snapshot().components
        expected_referential_deps = {
            "author_module": [
                "s0ma://guide/quick-reference",
                "s0ma://docs/journeys",
                "scaffold_module",
                "check",
                "transpile",
                "build_project",
                "inspect_module",
            ],
            "fix_check_failures": ["check", "s0ma://guide/errors"],
            "migrate_project": ["migrate_ext", "build_project", "check"],
        }
        expected_titles = {
            "author_module": "Author a new s0ma module",
            "fix_check_failures": "Fix s0ma check failures",
            "migrate_project": "Migrate a legacy s0ma project",
        }
        for prompt_name in EXPECTED_PROMPT_COMPONENTS:
            spec = components[prompt_name]
            assert spec.metadata.get("mcp_prompt") == prompt_name, prompt_name
            assert spec.metadata.get("mcp_prompt_title") == (
                expected_titles[prompt_name]
            ), prompt_name  # SH-M4: authored mcp_prompt_title rides the carrier
            assert spec.module_path == "s0ma_mcp.prompts", prompt_name
            assert spec.qualified_name == (
                f"s0ma_mcp.prompts.{prompt_name}_prompt"
            ), prompt_name
            assert spec.dependencies == (
                expected_referential_deps[prompt_name]
            ), prompt_name
            provider = getattr(prompts, f"{prompt_name}_prompt")
            built_spec = get_component_spec(provider)
            assert built_spec is not None
            assert built_spec.name == f"{prompt_name}_prompt"
            assert spec.intent == built_spec.intent, prompt_name

    def test_bridged_tools_carry_catalog_identity(self) -> None:
        """SH-M3: the converted tools surface is bridged faithfully.

        Every served tool is cataloged under its MCP tool name (read
        from the IR's authored ``mcp_tool:`` attribute — the built
        declaration itself is ``_tool``-suffixed for the self/global
        registry name-disjointness invariant, exactly like prompts),
        with the name stamped in ``metadata["mcp_tool"]``, the authored
        FR-MCP-8 hints in ``metadata["mcp_tool_annotations"]`` (the M4
        carrier convention; unset hints absent), the built module's
        intent byte-for-byte, the package-stamped module path, and the
        translated/referential dependency edges; the plumbing rename
        keeps ``dsl_cli_bridge`` as the catalog identity of the built
        ``_run_cli``.
        """
        components = get_self_registry().snapshot().components
        expected_dependencies = {
            "transpile": ["dsl_cli_bridge"],
            "build_project": ["dsl_cli_bridge"],
            "adopt_file": ["dsl_cli_bridge"],
            "check": ["dsl_cli_bridge"],
            "verify_host": ["dsl_cli_bridge"],
            "inspect_module": ["dsl_cli_bridge"],
            "migrate_ext": ["dsl_cli_bridge"],
            "scaffold_module": ["dsl_cli_bridge", "check"],
            "init_project": [],
            "describe_server": ["self_registry"],
            "project_status": [],
            "run_example": [],
            "prepare_feedback": [],
            "submit_feedback": [],
            # F7: the topic query names the three resources it points a
            # reader at, and nothing else — resolution and rendering are
            # the model's, not another catalog component's.
            "learn_s0ma": [
                "s0ma://docs/index",
                "s0ma://docs/concepts",
                "s0ma://docs/journeys",
            ],
        }
        expected_annotation_metadata = {
            "check": {"readOnlyHint": True, "openWorldHint": False},
            "verify_host": {
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
            "inspect_module": {"readOnlyHint": True, "openWorldHint": False},
            "describe_server": {"readOnlyHint": True, "openWorldHint": False},
            "project_status": {"readOnlyHint": True, "openWorldHint": False},
            "transpile": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            "build_project": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            "adopt_file": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": False,
                "openWorldHint": False,
            },
            "scaffold_module": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            "init_project": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            "migrate_ext": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            "run_example": {
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": False,
            },
            "prepare_feedback": {
                "readOnlyHint": True,
                "openWorldHint": False,
            },
            "submit_feedback": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": True,
            },
            # F7: reads packaged data and nothing else, and the same
            # question always returns the same answer from one build.
            "learn_s0ma": {
                "readOnlyHint": True,
                "openWorldHint": False,
                "idempotentHint": True,
            },
        }
        # Surface contract revision R3 (2026-09-18): every tool's authored
        # ``mcp_tool_title`` joins its hint dict under ``title``. The fifteen
        # wordings were approved by the owner one by one; pinning them here
        # makes a reworded title a decision somebody takes in this file.
        expected_titles = {
            "project_status": "Project status",
            "describe_server": "Describe this server",
            "learn_s0ma": "Ask about s0ma",
            "init_project": "Set up a s0ma project",
            "scaffold_module": "Start a new component",
            "check": "Check s0ma source",
            "transpile": "Transpile one source file",
            "build_project": "Build the project",
            "verify_host": "Verify imports in the app's Python",
            "inspect_module": "Inspect the self-model",
            "run_example": "Run a documented example",
            "adopt_file": "Record a legacy Python file",
            "migrate_ext": "Migrate old file extensions",
            "prepare_feedback": "Prepare feedback for review",
            "submit_feedback": "Send approved feedback",
        }
        assert set(expected_titles) == EXPECTED_TOOL_COMPONENTS
        for tool_name in EXPECTED_TOOL_COMPONENTS:
            spec = components[tool_name]
            assert spec.metadata.get("mcp_tool") == tool_name, tool_name
            assert spec.metadata.get("mcp_tool_annotations") == {
                **expected_annotation_metadata[tool_name],
                "title": expected_titles[tool_name],
            }, tool_name
            assert spec.module_path == "s0ma_mcp.tools", tool_name
            assert spec.qualified_name == (
                f"s0ma_mcp.tools.{tool_name}_tool"
            ), tool_name
            assert spec.dependencies == expected_dependencies[tool_name], tool_name
            provider = getattr(tools, f"{tool_name}_tool")
            built_spec = get_component_spec(provider)
            assert built_spec is not None
            assert built_spec.name == f"{tool_name}_tool"
            assert spec.intent == built_spec.intent, tool_name
        bridge = components["dsl_cli_bridge"]
        assert bridge.qualified_name == "s0ma_mcp.tools._run_cli"
        assert bridge.kind is ComponentKind.ADAPTER
        assert bridge.layer is Layer.PRESENTATION  # F-M0-6 re-layering

    def test_built_callables_carry_served_names_at_import(self) -> None:
        """DSL-M1: the EMITTER stamps served ``__name__``s at build time.

        Every converted tool and prompt authors ``serves_as:``, so the
        built callable already carries the served name in its
        ``__name__``/``__qualname__`` straight from the emitted module —
        BEFORE any binding-layer rename (``_served_as`` is now an
        idempotent guard, not the mechanism). The module ATTRIBUTE keeps
        the declaration identifier (registry disjointness), which is the
        asymmetry F-M4-2 documented: schema titles read ``__name__``,
        the registry reads the symbol.
        """
        for tool_name in EXPECTED_TOOL_COMPONENTS:
            provider = getattr(tools, f"{tool_name}_tool")
            assert provider.__name__ == tool_name, tool_name
            assert provider.__qualname__ == tool_name, tool_name
        for prompt_name in EXPECTED_PROMPT_COMPONENTS:
            provider = getattr(prompts, f"{prompt_name}_prompt")
            assert provider.__name__ == prompt_name, prompt_name
            assert provider.__qualname__ == prompt_name, prompt_name

    def test_s0ma_sources_author_no_prefixed_attribute_strings(self) -> None:
        """DSL-M1 conversion gate: the ``mcp_*:`` namespace is retired.

        The ``declares_attributes`` prefixed-string convention
        (``"mcp_uri:s0ma://..."``, seven namespaces by SH-M4) is fully
        replaced by first-class ``metadata:`` maps and ``serves_as:``
        fields; this regression gate keeps the workaround from sneaking
        back into the authored sources.
        """
        s0ma_src = Path(s0ma_mcp.__file__).parent.parent.parent / "s0ma_src"
        sources = sorted(s0ma_src.glob("*.s0ma"))
        assert len(sources) >= 3, "expected the three authored modules"
        prefixed = re.compile(r'"mcp_[a-z_]+:')
        for source in sources:
            text = source.read_text(encoding="utf-8")
            assert not re.search(
                r'^\s*declares_attributes:\s*\[(?:[^\]]*"mcp_)',
                text,
                flags=re.MULTILINE,
            ), source.name
            assert not prefixed.search(text), (
                f"{source.name} authors a prefixed mcp_* attribute string —"
                " use metadata:/serves_as: instead (DSL-M1)"
            )

    def test_served_annotations_equal_the_authored_attributes(self) -> None:
        """FR-MCP-8 end to end: served hints == the .s0ma-authored hints.

        ``create_server`` binds each tool with the ``ToolAnnotations``
        built from the catalog metadata
        (``components.built_tool_annotations``); this pins the served
        objects field-by-field to the bridged metadata so the authored
        ``mcp_tool_annotations`` attributes are provably the single
        source of truth (and unset hints stay unset).
        """
        components = get_self_registry().snapshot().components
        served = {t.name: t.annotations for t in _run(create_server().list_tools())}
        assert set(served) == EXPECTED_TOOL_COMPONENTS
        for tool_name, served_annotations in served.items():
            assert served_annotations is not None, tool_name
            authored = components[tool_name].metadata["mcp_tool_annotations"]
            served_hints = {
                field: value
                for field, value in (
                    ("readOnlyHint", served_annotations.readOnlyHint),
                    ("destructiveHint", served_annotations.destructiveHint),
                    ("idempotentHint", served_annotations.idempotentHint),
                    ("openWorldHint", served_annotations.openWorldHint),
                    ("title", served_annotations.title),
                )
                if value is not None
            }
            assert served_hints == authored, tool_name

    def test_converted_intents_match_their_s0ma_declarations(self) -> None:
        """SH-M2 acceptance: catalog intents == the ``.s0ma`` source text.

        ``s0ma://self/model`` lists converted components sourced from
        emitted registrations; this pins (for one converted prompt and
        one converted resource) that the served intent string is the
        literal ``intent:`` text of its ``.s0ma`` declaration — the
        no-drift clause made structural (FR-MCP-11).
        """

        def declared_intent(s0ma_source: Path, declaration: str) -> str:
            text = s0ma_source.read_text(encoding="utf-8")
            match = re.search(
                rf"^nerve {re.escape(declaration)} ::"
                rf".*?^\s+intent: \"([^\n]+)\"$",
                text,
                re.MULTILINE | re.DOTALL,
            )
            assert match, f"no intent found for '{declaration}' in {s0ma_source}"
            return match.group(1)

        s0ma_src = Path(__file__).resolve().parents[1] / "s0ma_src"
        components = get_self_registry().snapshot().components
        for source, declaration, catalog_name in (
            ("prompts.s0ma", "author_module_prompt", "author_module"),
            ("resources.s0ma", "self_model_resource", "s0ma://self/model"),
            ("tools.s0ma", "check_tool", "check"),
        ):
            intent = declared_intent(s0ma_src / source, declaration)
            assert components[catalog_name].intent == intent, catalog_name

    def test_self_registry_is_separate_from_the_global_registry(self) -> None:
        """The self-model must not pollute process-global state."""
        from s0ma.registry import get_registry

        self_registry = get_self_registry()
        global_registry = get_registry(persist=False)
        assert self_registry is not global_registry
        assert not (
            set(self_registry.snapshot().components)
            & set(global_registry.snapshot().components)
        )


class TestSelfModelResource:
    """``s0ma://self/model`` — the live graph as JSON over MCP."""

    def test_resolves_to_valid_json(self, mcp_server: FastMCP) -> None:
        contents = list(_run(mcp_server.read_resource("s0ma://self/model")))
        assert len(contents) == 1
        document = json.loads(contents[0].content)
        assert document["server"]["name"] == SERVER_NAME
        assert document["server"]["package"] == "s0ma-mcp"
        assert document["server"]["version"] == s0ma_mcp.__version__
        assert document["component_count"] >= 9

    def test_is_served_as_json(self, mcp_server: FastMCP) -> None:
        listed = {
            str(r.uri): r for r in _run(mcp_server.list_resources())
        }
        assert listed["s0ma://self/model"].mimeType == "application/json"

    def test_every_mcp_tool_appears_with_nonempty_intent(
        self, mcp_server: FastMCP
    ) -> None:
        """M0 acceptance: the graph lists every tool as a component."""
        contents = list(_run(mcp_server.read_resource("s0ma://self/model")))
        components = json.loads(contents[0].content)["self_model"]["components"]
        served_tools = {t.name for t in _run(mcp_server.list_tools())}
        for tool_name in served_tools:
            assert tool_name in components, f"tool '{tool_name}' not in self-model"
            entry = components[tool_name]
            assert entry["intent"], f"tool '{tool_name}' has empty intent"
            assert entry["kind"] and entry["layer"]
            assert isinstance(entry["dependencies"], list)

    def test_renders_through_core_snapshot_serialization(self) -> None:
        """The JSON body is core's RegistrySnapshot.to_dict, not hand-rolled."""
        document = self_model_document()
        snapshot_dict = get_self_registry().snapshot().to_dict()
        assert set(document["self_model"]) == set(snapshot_dict)
        assert document["self_model"]["components"].keys() == (
            snapshot_dict["components"].keys()
        )

    def test_describes_the_bootstrap_module_that_serves_it(
        self, mcp_server: FastMCP
    ) -> None:
        """SH-M4 step 5: the self-model now describes its own server.

        The factory component must be present, live in the single
        bootstrap module (``s0ma_mcp`` — the package ``__init__``), and
        carry an intent that honestly states the surface is DERIVED from
        the self-model registry (FR-MCP-11's end state, not the old
        hand-wiring story).
        """
        contents = list(_run(mcp_server.read_resource("s0ma://self/model")))
        components = json.loads(contents[0].content)["self_model"]["components"]
        factory = components["create_server"]
        assert factory["kind"] == "ORCHESTRATOR"
        spec = get_self_registry().snapshot().components["create_server"]
        assert spec.module_path == "s0ma_mcp"
        assert spec.qualified_name == "s0ma_mcp.create_server"
        assert "deriving" in factory["intent"]
        assert "self-model registry" in factory["intent"]


class TestDescribeServer:
    """The ``describe_server`` tool round-trips over the MCP boundary."""

    def _call(self, mcp_server: FastMCP) -> dict[str, Any]:
        outcome = _run(mcp_server.call_tool("describe_server", {}))
        if isinstance(outcome, tuple):
            _content, structured = outcome
            assert isinstance(structured, dict)
            return structured
        assert isinstance(outcome, dict)
        return outcome

    def test_round_trips_with_ok_true(self, mcp_server: FastMCP) -> None:
        result = self._call(mcp_server)
        assert result["ok"] is True
        assert result["server"]["name"] == SERVER_NAME
        assert result["component_count"] == len(
            result["self_model"]["components"]
        )

    def test_carries_an_llm_ready_text_rendering(
        self, mcp_server: FastMCP
    ) -> None:
        result = self._call(mcp_server)
        text = result["explain_for_llm"]
        assert isinstance(text, str)
        assert "S0MA SYSTEM SELF-DESCRIPTION" in text
        assert "describe_server" in text  # the graph includes this very tool


class TestDerivedSurface:
    """D-3 / FR-MCP-7 / FR-MCP-11 (SH-M4): the registry IS the surface.

    ``create_server`` derives every FastMCP registration from the
    self-model catalog, so the old set-equality drift gate is obsolete —
    set-drift is structurally impossible. These are its repurposed
    assertions: completeness of the serving metadata, totality of the
    served/unserved partition, the D-1 single-handwritten-module end
    state, and a positive proof that the derivation is real (an
    injected fake component is served without touching the factory).
    """

    def test_every_mcp_surfaced_component_is_complete_and_served(
        self, mcp_server: FastMCP
    ) -> None:
        """The repurposed D-6 core: complete metadata, and actually served.

        For every catalog component carrying MCP identity metadata:
        tools must carry their served name and an authored
        ``mcp_tool_annotations`` hint dict (FR-MCP-8), prompts their
        served name and title, resources their URI (plus a MIME type
        only where one is authored); every one must resolve to a live
        provider callable through pure registry data
        (``module_path``/``qualified_name``) and appear in the
        corresponding ``list_tools``/``list_resources``/``list_prompts``
        listing.
        """
        served_tools = {t.name for t in _run(mcp_server.list_tools())}
        served_uris = {str(r.uri) for r in _run(mcp_server.list_resources())}
        served_prompts = {p.name for p in _run(mcp_server.list_prompts())}
        surfaced = 0
        for name, spec in get_self_registry().snapshot().components.items():
            metadata = spec.metadata
            identities = {
                key: metadata.get(key)
                for key in ("mcp_tool", "mcp_uri", "mcp_prompt")
                if metadata.get(key) is not None
            }
            if not identities:
                continue
            surfaced += 1
            assert len(identities) == 1, (
                f"'{name}' carries more than one MCP identity: {identities}"
            )
            # The provider must resolve from registry data alone.
            module = sys.modules[spec.module_path]
            provider = getattr(module, spec.qualified_name.rsplit(".", 1)[-1])
            assert callable(provider), name
            assert spec.intent and len(spec.intent) >= 10, name
            if "mcp_tool" in identities:
                assert identities["mcp_tool"] == name, name
                hints = metadata.get("mcp_tool_annotations")
                assert isinstance(hints, dict) and hints, (
                    f"tool '{name}' carries no authored ToolAnnotations "
                    "hints (FR-MCP-8) — author mcp_tool_annotations "
                    "attributes on its declaration"
                )
                assert set(hints) <= {
                    "readOnlyHint",
                    "destructiveHint",
                    "idempotentHint",
                    "openWorldHint",
                    "title",
                }, name
                assert all(
                    isinstance(value, bool)
                    for key, value in hints.items()
                    if key != "title"
                ), name
                # Surface contract revision R3: a served tool has a title.
                assert isinstance(hints.get("title"), str) and hints["title"], name
                assert name in served_tools, f"tool '{name}' not served"
            elif "mcp_uri" in identities:
                assert identities["mcp_uri"] == name, name
                mime_type = metadata.get("mcp_mime_type")
                assert mime_type is None or (
                    isinstance(mime_type, str) and "/" in mime_type
                ), name
                assert name in served_uris, f"resource '{name}' not served"
            else:
                assert identities["mcp_prompt"] == name, name
                assert isinstance(metadata.get("mcp_prompt_title"), str), (
                    f"prompt '{name}' carries no authored mcp_prompt_title"
                )
                assert name in served_prompts, f"prompt '{name}' not served"
        assert surfaced >= 21  # includes the M5 diagnose_fault prompt

    def test_served_surface_equals_the_mcp_surfaced_catalog(
        self, mcp_server: FastMCP
    ) -> None:
        """Both directions, per kind: served sets == metadata-derived sets."""
        components = get_self_registry().snapshot().components
        assert {t.name for t in _run(mcp_server.list_tools())} == {
            spec.metadata["mcp_tool"]
            for spec in components.values()
            if "mcp_tool" in spec.metadata
        }
        assert {str(r.uri) for r in _run(mcp_server.list_resources())} == {
            spec.metadata["mcp_uri"]
            for spec in components.values()
            if "mcp_uri" in spec.metadata
        }
        assert {p.name for p in _run(mcp_server.list_prompts())} == {
            spec.metadata["mcp_prompt"]
            for spec in components.values()
            if "mcp_prompt" in spec.metadata
        }

    def test_catalog_partition_is_total(self) -> None:
        """Every component is MCP-surfaced XOR documented unserved plumbing."""
        for name, spec in get_self_registry().snapshot().components.items():
            has_identity = any(
                key in spec.metadata
                for key in ("mcp_tool", "mcp_uri", "mcp_prompt")
            )
            if name in UNSERVED_COMPONENTS:
                assert not has_identity, (
                    f"'{name}' is listed in UNSERVED_COMPONENTS but carries "
                    "MCP identity metadata — it would be served"
                )
            else:
                assert has_identity, (
                    f"'{name}' carries no MCP identity metadata and is not "
                    "in UNSERVED_COMPONENTS — register it as a served "
                    "surface (mcp_tool/mcp_uri/mcp_prompt attribute) or "
                    "document it as plumbing"
                )

    def test_catalog_equals_registry_component_set(self) -> None:
        """Deriving from the catalog ≡ deriving from the registry.

        ``create_server`` iterates the insertion-ordered catalog (the
        registry's authoritative feed); :func:`get_self_registry`
        registers exactly that catalog. This pins the equivalence the
        D-3 phrasing ("derived from the s0ma registry") relies on.
        """
        assert set(s0ma_mcp._CATALOG) == set(
            get_self_registry().snapshot().components
        )

    def test_exactly_one_handwritten_python_module(self) -> None:
        """D-1 reached its FR-MCP-11 end state — read from the filesystem.

        Walks every ``.py`` file in the installed package and classifies
        it by CONTENT: transpiled modules carry the emitter's
        ``# s0ma-source-hash:`` comment, the build-dir ``__init__.py``
        carries the build's generated-marker docstring; manifest/IR/map
        are not ``.py`` and the ``build.s0ma.pyi`` stub is not ``.py``
        either. Regenerable cache copies (``.s0ma.cache/``, gitignored
        and wheel-excluded) and bytecode dirs are skipped by path.
        Exactly ONE file may remain: the package ``__init__.py`` — the
        single bootstrap module.
        """
        generated_markers = (
            "# s0ma-source-hash:",
            "Auto-generated by `s0ma build`",
        )
        package_dir = Path(s0ma_mcp.__file__).resolve().parent
        handwritten = [
            path
            for path in sorted(package_dir.rglob("*.py"))
            if "__pycache__" not in path.parts
            and ".s0ma.cache" not in path.parts
            and not any(
                marker in path.read_text(encoding="utf-8")
                for marker in generated_markers
            )
        ]
        assert handwritten == [package_dir / "__init__.py"], (
            "FR-MCP-11/D-1: the package must contain exactly ONE "
            "handwritten Python module (the bootstrap __init__.py); "
            f"found: {[str(p.relative_to(package_dir)) for p in handwritten]}"
        )

    def test_fake_component_is_served_without_touching_the_factory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The SH-M4 acceptance negative test: derivation, not enumeration.

        Injects a fake module plus catalog specs carrying the mcp_*
        metadata (one tool with annotations, one resource with a MIME
        type, one prompt with a title) and asserts ``create_server`` —
        UNCHANGED — serves all three, with the metadata-borne facts and
        cleandoc-normalized descriptions intact, the tool callable live
        over the boundary. ``monkeypatch`` restores the catalog and
        ``sys.modules``, so the real surface is untouched afterwards.
        """
        fake_module = types.ModuleType("m4_fake_surface")

        def fake_tool(path: str) -> dict[str, Any]:
            """Echo a path back, proving the surface is derived.

            Args:
                path: Any string; returned unchanged.
            """
            return {
                "schema": "s0ma-tool-result@1",
                "ok": True,
                "next_actions": [],
                "echo": path,
            }

        def fake_resource() -> str:
            """Serve a constant document for the derivation proof."""
            return '{"fake": true}'

        def fake_prompt(topic: str) -> str:
            """Render a one-line prompt for the derivation proof."""
            return f"Say something about {topic}."

        fake_module.fake_tool = fake_tool  # type: ignore[attr-defined]
        fake_module.fake_resource = fake_resource  # type: ignore[attr-defined]
        fake_module.fake_prompt = fake_prompt  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "m4_fake_surface", fake_module)

        def fake_spec(name: str, attr: str, metadata: dict[str, Any]) -> ComponentSpec:
            return ComponentSpec(
                name=name,
                kind=ComponentKind.FUNCTION,
                layer=Layer.PRESENTATION,
                intent="Fake surface for the SH-M4 derivation proof — never shipped",
                dependencies=[],
                version=s0ma_mcp.__version__,
                metadata=metadata,
                module_path="m4_fake_surface",
                qualified_name=f"m4_fake_surface.{attr}",
            )

        fakes = (
            fake_spec(
                "m4_fake_tool",
                "fake_tool",
                {
                    "mcp_tool": "m4_fake_tool",
                    "mcp_tool_annotations": {"readOnlyHint": True},
                },
            ),
            fake_spec(
                "s0ma://m4/fake",
                "fake_resource",
                {"mcp_uri": "s0ma://m4/fake", "mcp_mime_type": "application/json"},
            ),
            fake_spec(
                "m4_fake_prompt",
                "fake_prompt",
                {
                    "mcp_prompt": "m4_fake_prompt",
                    "mcp_prompt_title": "Fake derivation-proof prompt",
                },
            ),
        )
        for spec in fakes:
            monkeypatch.setitem(s0ma_mcp._CATALOG, spec.name, spec)

        probe = create_server()  # the factory is NOT modified by this test

        served_tool = {t.name: t for t in _run(probe.list_tools())}["m4_fake_tool"]
        assert served_tool.annotations is not None
        assert served_tool.annotations.readOnlyHint is True
        assert served_tool.description == (
            "Echo a path back, proving the surface is derived.\n\n"
            "Args:\n    path: Any string; returned unchanged."
        )  # cleandoc-normalized via the factory's binding path
        assert served_tool.inputSchema["title"] == "m4_fake_toolArguments"
        outcome = _run(probe.call_tool("m4_fake_tool", {"path": "x"}))
        structured = outcome[1] if isinstance(outcome, tuple) else outcome
        assert structured == {
            "schema": "s0ma-tool-result@1",
            "ok": True,
            "next_actions": [],
            "echo": "x",
        }

        served_resource = {
            str(r.uri): r for r in _run(probe.list_resources())
        }["s0ma://m4/fake"]
        assert served_resource.mimeType == "application/json"
        contents = list(_run(probe.read_resource("s0ma://m4/fake")))
        assert contents[0].content == '{"fake": true}'

        served_prompt = {
            p.name: p for p in _run(probe.list_prompts())
        }["m4_fake_prompt"]
        assert served_prompt.title == "Fake derivation-proof prompt"

        # The injection is test-local: a fresh derivation after monkeypatch
        # cleanup serves exactly the real surface again (asserted by the
        # other tests in this class, which run against the module-scoped
        # server fixture built from the un-patched catalog).

    def test_unserved_allowlist_entries_are_real_components(self) -> None:
        """The plumbing inventory cannot rot: every entry stays registered."""
        registered = set(get_self_registry().snapshot().components)
        assert registered >= UNSERVED_COMPONENTS

    def test_factory_dependencies_track_the_served_surface(
        self, mcp_server: FastMCP
    ) -> None:
        """create_server's edge list equals what it actually serves."""
        factory_spec = get_self_registry().snapshot().components["create_server"]
        assert set(factory_spec.dependencies) == _served_surface(mcp_server), (
            "create_server's dependencies diverged from the served "
            "surface — the factory decoration must stay AFTER the "
            "bootstrap + bridge block in the s0ma_mcp bootstrap module"
        )
