"""Tests for the packaged agent-guide + meta resources (FR-MCP-3/-10).

Two layers of protection:

* resolution tests — every resource resolves to non-empty, on-topic
  content through both the loader API and the MCP server boundary
  (including ``s0ma://meta/version``, which is rendered live rather
  than packaged);
* drift gate — the committed copies under ``s0ma_mcp/_docs/`` are
  byte-compared against their in-repo sources (the s0ma-dsl docs, the
  generated error catalog, and — first source outside the dsl docs
  tree — the root ``CHANGELOG.md``), and the packaged spec is asserted
  to be the highest version s0ma-dsl ships (the package README
  documents this strategy).
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import platform
import re
from typing import Any

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")

from conftest import DSL_DOCS, REPO_ROOT
from s0ma_mcp.resources import GUIDE_DOCS, load_doc

from s0ma_mcp import __version__, create_server


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class TestLoadDoc:
    def test_all_known_keys_resolve_to_nonempty_text(self) -> None:
        for key in GUIDE_DOCS:
            text = load_doc(key)
            assert isinstance(text, str)
            assert len(text) > 1_000, f"resource '{key}' suspiciously small"

    def test_unknown_key_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            load_doc("nonexistent-guide")

    def test_system_prompt_is_the_authoring_prompt(self) -> None:
        text = load_doc("system-prompt")
        assert "Coding Agent System Prompt" in text
        assert ".s0ma" in text

    def test_getting_started_is_the_canonical_outcome_journey(self) -> None:
        text = load_doc("getting-started")
        assert "s0ma in 30 seconds" in text
        assert "When not to use it" in text
        assert "project_status" in text
        assert "inspect_module" in text
        assert "GENERATED_FILE_DRIFT" in text
        assert "verify-host" in text
        source = (REPO_ROOT / "docs/getting-started.md").read_text(encoding="utf-8")
        assert text == source
        root_readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        marker = "<!-- BEGIN GENERATED GETTING STARTED -->\n"
        embedded = root_readme.split(marker, 1)[1].split(
            "\n<!-- END GENERATED GETTING STARTED -->", 1
        )[0]
        assert embedded == source.rstrip()

    def test_quick_reference_is_the_generated_page(self) -> None:
        """The served quick reference is the documentation build's page.

        Owner ruling 2026-09-29: an agent in somebody's project must be
        able to reach every reference, so the page the build renders
        from the language itself is what this address answers with.
        """
        text = load_doc("quick-reference")
        assert text.startswith("# s0ma quick reference\n")
        assert "This page is generated." in text
        assert "## Each declaration, line by line" in text
        assert "s0ma check" in text

    def test_quick_reference_machine_twin_is_the_same_facts_as_data(self) -> None:
        """The data twin parses, names its schema, and describes the page."""
        document = json.loads(load_doc("quick-reference-machine"))
        assert document["schema"] == "s0ma-quick-reference@1"
        assert document["title"] == "s0ma quick reference"
        assert document["identity"]["readable"] == (
            "docs/reference/quick-reference-readable.md"
        )
        assert document["identity"]["machine"] == (
            "docs/_generated/quick-reference-machine.json"
        )
        assert {kind["kind"] for kind in document["kinds"]} >= {"module", "nerve", "cell"}

    def test_patterns_guide_is_the_patterns_guide(self) -> None:
        assert "pattern" in load_doc("patterns").lower()

    def test_spec_is_the_language_spec(self) -> None:
        text = load_doc("spec")
        assert "s0ma" in text
        assert len(text) > 100_000  # the spec is the big one

    def test_errors_is_the_error_catalog(self) -> None:
        """M2 (FR-MCP-10): the generated per-code severity/fix table."""
        text = load_doc("errors")
        assert "| Code | Migration | Dev | Strict | Release |" in text
        assert "`BARE_IMPORT`" in text  # a known diagnostic code

    def test_changelog_is_the_keep_a_changelog_file(self) -> None:
        """M2 (FR-MCP-10): the monorepo's canonical changelog (INV-4)."""
        text = load_doc("changelog")
        assert "Keep a Changelog" in text
        assert f"## [{__version__}]" in text
        assert "## [0.5.0]" in text


class TestResourcesOverMcp:
    """Resources resolve through the server (in-process, no transport)."""

    @pytest.fixture(scope="class")
    def server(self) -> Any:
        return create_server()

    @pytest.mark.parametrize("doc", list(GUIDE_DOCS.values()), ids=lambda d: d.key)
    def test_resource_resolves_nonempty(self, server: Any, doc: Any) -> None:
        contents = list(_run(server.read_resource(doc.uri)))
        assert len(contents) == 1
        assert len(contents[0].content) > 1_000

    def test_resource_content_matches_loader(self, server: Any) -> None:
        doc = GUIDE_DOCS["quick-reference"]
        contents = list(_run(server.read_resource(doc.uri)))
        assert contents[0].content == load_doc("quick-reference")

    def test_the_quick_reference_pair_is_served_with_its_own_mime_types(
        self, server: Any
    ) -> None:
        """The page is Markdown and its twin is JSON, and a client can tell."""
        listed = {str(r.uri): r for r in _run(server.list_resources())}
        assert listed["s0ma://guide/quick-reference"].mimeType == "text/markdown"
        assert listed["s0ma://guide/quick-reference.json"].mimeType == "application/json"
        twin = list(_run(server.read_resource("s0ma://guide/quick-reference.json")))
        assert json.loads(twin[0].content)["schema"] == "s0ma-quick-reference@1"


class TestVersionResource:
    """``s0ma://meta/version`` — live from importlib.metadata (FR-MCP-10).

    Not a packaged file (and deliberately absent from ``GUIDE_DOCS`` /
    the drift gate): the document is rendered at read time, offline
    (PRD P-6 / plan D-2).
    """

    @pytest.fixture(scope="class")
    def server(self) -> Any:
        return create_server()

    def _document(self, server: Any) -> dict[str, Any]:
        contents = list(_run(server.read_resource("s0ma://meta/version")))
        assert len(contents) == 1
        document = json.loads(contents[0].content)
        assert isinstance(document, dict)
        return document

    def test_is_not_a_packaged_doc(self) -> None:
        assert all(d.uri != "s0ma://meta/version" for d in GUIDE_DOCS.values())

    def test_is_served_as_json(self, server: Any) -> None:
        listed = {str(r.uri): r for r in _run(server.list_resources())}
        assert listed["s0ma://meta/version"].mimeType == "application/json"

    def test_carries_exactly_the_documented_keys(self, server: Any) -> None:
        document = self._document(server)
        assert set(document) == {
            "server",
            "s0ma_core",
            "s0ma_dsl",
            "s0ma_mcp",
            "s0ma_studi0",
            "mcp_sdk",
            "python",
        }

    def test_values_are_the_installed_versions(self, server: Any) -> None:
        document = self._document(server)
        assert document["server"] == "s0ma-authoring"
        assert document["s0ma_core"] == importlib.metadata.version("s0ma-core")
        assert document["s0ma_dsl"] == importlib.metadata.version("s0ma-dsl")
        assert document["s0ma_mcp"] == importlib.metadata.version("s0ma-mcp")
        assert document["mcp_sdk"] == importlib.metadata.version("mcp")
        assert document["python"] == platform.python_version()

    def test_studi0_is_reported_honestly_when_optional(self, server: Any) -> None:
        """s0ma-studi0 is an optional leaf: a version, or an honest None.

        Present in a workspace checkout, legitimately absent from a
        minimal install — the surface reports whichever is true rather
        than omitting the key.
        """
        expected: str | None
        try:
            expected = importlib.metadata.version("s0ma-studi0")
        except importlib.metadata.PackageNotFoundError:
            expected = None
        assert self._document(server)["s0ma_studi0"] == expected


class TestDocDrift:
    """The drift gate for the committed-copies packaging strategy.

    If one of these fails, an in-repo source changed (a s0ma-dsl guide,
    the generated error catalog, or the root changelog): refresh the
    copy (``cp`` the source file over ``s0ma_mcp/_docs/`` and commit).
    For the error catalog, regenerate the source first if the
    grammar/diagnostics changed
    (``make -C packages/s0ma-dsl docs-derived S0MA="uv run s0ma"``).
    """

    @pytest.fixture(autouse=True)
    def _require_repo_checkout(self) -> None:
        if not DSL_DOCS.is_dir():  # pragma: no cover - wheel-install context
            pytest.skip("s0ma-dsl docs not available (not a repo checkout)")

    @pytest.mark.parametrize("doc", list(GUIDE_DOCS.values()), ids=lambda d: d.key)
    def test_packaged_copy_matches_dsl_source(self, doc: Any) -> None:
        source = REPO_ROOT / doc.source
        assert source.is_file(), f"drift-gate source moved: {doc.source}"
        assert load_doc(doc.key) == source.read_text(encoding="utf-8"), (
            f"s0ma_mcp/_docs/{doc.filename} has drifted from {doc.source}; "
            "refresh the committed copy (see the s0ma-mcp README)"
        )

    def test_packaged_spec_is_the_current_one(self) -> None:
        """s0ma://spec/current must track the highest dsl spec version."""
        versions = {}
        for spec in DSL_DOCS.glob("s0ma-dsl-spec-v*.md"):
            match = re.fullmatch(r"s0ma-dsl-spec-v(\d+)\.(\d+)\.(\d+)\.md", spec.name)
            if match:
                versions[tuple(int(g) for g in match.groups())] = spec.name
        assert versions, "no versioned spec files found in s0ma-dsl docs"
        newest = versions[max(versions)]
        assert GUIDE_DOCS["spec"].filename == newest, (
            f"s0ma-dsl's current spec is {newest} but s0ma-mcp packages "
            f"{GUIDE_DOCS['spec'].filename}; update resources.GUIDE_DOCS "
            "and the committed copy"
        )
