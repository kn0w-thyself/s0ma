"""Tests for the ``project_status`` orientation tool (PRD FR-MCP-9).

Exercised end to end against *real* temp projects (the conftest fixture
assembled from s0ma-dsl's own ``valid/multi_module`` files) — no mocks:

* orientation — a non-project directory is a valid ``ok: true,
  is_project: false`` answer, never an error (plan M2);
* freshness — a freshly built project reports ``fresh`` everywhere and
  flips to ``stale`` when a source is touched, judged by the build
  manifest's own recorded hashes (re-implementing the hashing would be
  a defect per the plan's risk register — these tests pin behavioral
  agreement with ``build.s0ma.json``);
* ``suggested_next_action`` — the exact short-imperative strings ship
  as product copy and are asserted verbatim;
* boundary — invalid roots behave exactly like every other tool
  (``_resolve_root``'s structured ``not a directory`` error, NFR-6).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")

from conftest import GREETINGS_S0MA, make_project
from s0ma_mcp.tools import build_project_tool as build_project
from s0ma_mcp.tools import project_status_tool as project_status

#: The fixture project's modules (conftest ``valid/multi_module``).
FIXTURE_MODULES = {"models", "processing", "routing"}

#: STD-M4 (usability plan): the exact authoring confirmation handshake the
#: tool returns as ``suggested_next_action`` for an ``authoring = "on"``
#: project (the default posture). Ships as product copy — asserted
#: verbatim. AGENTS.md (M6) references this same string.
AUTHORING_HANDSHAKE = (
    "s0ma project; authoring is ON — confirm you will author "
    "components as .s0ma via this server before writing code"
)


def _set_authoring_off(project: Path) -> None:
    """Append ``authoring = "off"`` to a project's ``[tool.s0ma]`` table.

    The conftest fixtures omit the key (so they default to ``"on"`` and
    get the handshake); the off-posture tests need the opposite branch,
    where ``suggested_next_action`` carries the plain build/check guidance.
    """
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8") + 'authoring = "off"\n',
        encoding="utf-8",
    )


def _build(project: Path) -> None:
    result = build_project(project_root=str(project))
    assert result["ok"] is True, f"fixture build failed: {result}"


def _touch(source: Path) -> None:
    """Change a source's *content* (mtime alone must not matter)."""
    source.write_text(
        source.read_text(encoding="utf-8") + "\n# touched by test\n",
        encoding="utf-8",
    )


class TestNonProjects:
    """Non-projects are orientation answers, not errors."""

    def test_empty_dir_is_not_a_project_but_ok(self, tmp_path: Path) -> None:
        result = project_status(project_root=str(tmp_path))
        assert result["ok"] is True
        assert result["is_project"] is False
        assert result["project_root"] == str(tmp_path.resolve())
        # Pilot-01 F3: the non-project answer is the adoption moment —
        # it must name the [tool.s0ma] prerequisite, the tool that
        # creates it (init_project), the follow-up (scaffold_module),
        # and the compact guide. Pinned verbatim as product copy.
        assert result["suggested_next_action"] == (
            "not a s0ma project yet — no [tool.s0ma] table in "
            "pyproject.toml. Bootstrap in two steps: (1) call "
            "init_project to add the [tool.s0ma] table (minimum "
            'source_roots = ["src"]), then (2) call scaffold_module to '
            "create the first module. After every edit: check, then "
            "build_project. Compact rules: read "
            "s0ma://guide/survival-card"
        )
        # P2-9: the toolchain note steers agents away from shelling out
        # to a CLI that is not on PATH in agent environments.
        assert "MCP tools" in result["note"]

    def test_pyproject_without_tool_s0ma_is_not_a_project(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "plain"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )
        result = project_status(project_root=str(tmp_path))
        assert result["ok"] is True
        assert result["is_project"] is False

    def test_nonexistent_root_fails_like_every_other_tool(self) -> None:
        """NFR-6 boundary: same _resolve_root contract as check/build."""
        result = project_status(project_root="/nonexistent/project/root")
        assert result["ok"] is False
        assert "not a directory" in result["error"]
        assert "Traceback (most recent call last)" not in str(result)


class TestUnbuiltProjects:
    def test_project_with_sources_but_no_build(self, project: Path) -> None:
        result = project_status(project_root=str(project))
        assert result["ok"] is True
        assert result["is_project"] is True
        assert result["project_root"] == str(project.resolve())
        assert result["build"]["built"] is False
        assert result["build"]["status"] == "unbuilt"
        assert result["build"]["manifest_path"] is None
        assert result["build"]["transpiler_version"] is None
        assert result["build"]["stale_modules"] == []
        statuses = {m["name"]: m["status"] for m in result["modules"]}
        assert set(statuses) == FIXTURE_MODULES
        assert set(statuses.values()) == {"unbuilt"}
        # STD-M4: default posture is authoring-on, so the handshake leads
        # regardless of build state.
        assert result["authoring"] == "on"
        assert result["suggested_next_action"] == AUTHORING_HANDSHAKE

    def test_project_with_no_modules_suggests_scaffolding(
        self, tmp_path: Path
    ) -> None:
        project = make_project(tmp_path / "proj", sources={})
        result = project_status(project_root=str(project))
        assert result["ok"] is True
        assert result["is_project"] is True
        assert result["modules"] == []
        # STD-M4: authoring-on (default) — the handshake supersedes the
        # "scaffold the first module" suggestion.
        assert result["authoring"] == "on"
        assert result["suggested_next_action"] == AUTHORING_HANDSHAKE

    def test_mode_defaults_to_dev(self, project: Path) -> None:
        assert project_status(project_root=str(project))["mode"] == "dev"

    def test_declared_mode_is_reported(self, tmp_path: Path) -> None:
        """``[tool.s0ma].mode`` (FR-DSL-5 writes it) surfaces verbatim."""
        project = make_project(
            tmp_path / "proj", sources={"greetings.s0ma": GREETINGS_S0MA}
        )
        pyproject = project / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8") + 'mode = "strict"\n',
            encoding="utf-8",
        )
        assert project_status(project_root=str(project))["mode"] == "strict"

    def test_pending_semantic_debt_lists_owner_field_reason_and_release_block(
        self, tmp_path: Path
    ) -> None:
        source = GREETINGS_S0MA.replace(
            "    requires: none\n",
            '    requires: pending("choose the runtime dependency set")\n',
        )
        project = make_project(
            tmp_path / "proj", sources={"greetings.s0ma": source}
        )
        debt = project_status(project_root=str(project))["semantic_debt"]
        assert debt == {
            "pending_count": 1,
            "pending_fields": [{
                "owner": "greetings::greetings",
                "field": "requires",
                "reason": "choose the runtime dependency set",
                "source": str(project / "src" / "greetings.s0ma"),
            }],
            "completeness_credit": 0,
            "blocks_release": True,
        }


class TestFreshAndStale:
    """The M2 acceptance flip: fresh build → touch a source → stale."""

    def test_fresh_build_reports_fresh_everywhere(self, project: Path) -> None:
        _build(project)
        result = project_status(project_root=str(project))
        assert result["ok"] is True
        assert result["is_project"] is True
        build = result["build"]
        assert build["built"] is True
        assert build["status"] == "fresh"
        assert build["stale_modules"] == []
        manifest_path = Path(build["manifest_path"])
        assert manifest_path.name == "build.s0ma.json"
        assert manifest_path.is_file()
        assert build["transpiler_version"]
        statuses = {m["name"]: m["status"] for m in result["modules"]}
        assert set(statuses) == FIXTURE_MODULES
        assert set(statuses.values()) == {"fresh"}
        # STD-M4: authoring-on (default) — the handshake leads even for a
        # fresh build (the off-posture tests assert "run check").
        assert result["authoring"] == "on"
        assert result["suggested_next_action"] == AUTHORING_HANDSHAKE

    def test_touching_one_source_flips_it_to_stale(self, project: Path) -> None:
        _build(project)
        _touch(project / "src" / "models.s0ma")
        result = project_status(project_root=str(project))
        build = result["build"]
        assert build["built"] is True
        assert build["status"] == "stale"
        assert build["stale_modules"] == ["models"]
        statuses = {m["name"]: m["status"] for m in result["modules"]}
        assert statuses["models"] == "stale"
        assert statuses["processing"] == "fresh"
        assert statuses["routing"] == "fresh"
        # STD-M4: authoring-on (default) — handshake leads over the stale
        # build guidance; build["status"] still reports the staleness.
        assert result["suggested_next_action"] == AUTHORING_HANDSHAKE

    def test_stale_count_pluralizes(self, project: Path) -> None:
        _build(project)
        _touch(project / "src" / "models.s0ma")
        _touch(project / "src" / "routing.s0ma")
        result = project_status(project_root=str(project))
        assert result["build"]["stale_modules"] == ["models", "routing"]
        # STD-M4: authoring-on (default) — handshake leads. The pluralized
        # "N modules stale" guidance is asserted under the off posture.
        assert result["suggested_next_action"] == AUTHORING_HANDSHAKE

    def test_rebuild_restores_fresh(self, project: Path) -> None:
        _build(project)
        _touch(project / "src" / "models.s0ma")
        _build(project)
        result = project_status(project_root=str(project))
        assert result["build"]["status"] == "fresh"
        # STD-M4: authoring-on (default) — handshake leads.
        assert result["suggested_next_action"] == AUTHORING_HANDSHAKE

    def test_new_source_after_build_is_unbuilt_and_stale(
        self, project: Path
    ) -> None:
        _build(project)
        (project / "src" / "latecomer.s0ma").write_text(
            "module latecomer\n", encoding="utf-8"
        )
        result = project_status(project_root=str(project))
        statuses = {m["name"]: m["status"] for m in result["modules"]}
        assert statuses["latecomer"] == "unbuilt"
        assert result["build"]["status"] == "stale"
        assert "latecomer" in result["build"]["stale_modules"]
        # STD-M4: authoring-on (default) — handshake leads.
        assert result["suggested_next_action"] == AUTHORING_HANDSHAKE

    def test_deleted_source_is_orphaned(self, project: Path) -> None:
        _build(project)
        (project / "src" / "models.s0ma").unlink()
        result = project_status(project_root=str(project))
        statuses = {m["name"]: m["status"] for m in result["modules"]}
        assert statuses["models"] == "orphaned"
        assert result["build"]["status"] == "stale"
        assert "models" in result["build"]["stale_modules"]


class TestAuthoringPosture:
    """STD-M4: the [tool.s0ma].authoring posture surfaces and gates the
    confirmation handshake.

    The conftest fixtures omit the key, so they default to ``"on"`` and
    get the handshake (asserted across TestUnbuiltProjects /
    TestFreshAndStale). These tests pin the ``"off"`` branch — the
    posture is reported verbatim and ``suggested_next_action`` carries
    the plain build/check guidance instead of the handshake.
    """

    def test_authoring_on_is_the_default_and_handshakes(
        self, tmp_path: Path
    ) -> None:
        """An absent key → posture ``"on"`` → the exact handshake string."""
        project = make_project(
            tmp_path / "proj", sources={"greetings.s0ma": GREETINGS_S0MA}
        )
        result = project_status(project_root=str(project))
        assert result["authoring"] == "on"
        assert result["suggested_next_action"] == AUTHORING_HANDSHAKE

    def test_authoring_off_unbuilt_gives_build_guidance(
        self, project: Path
    ) -> None:
        _set_authoring_off(project)
        result = project_status(project_root=str(project))
        assert result["authoring"] == "off"
        # No handshake — the build/check guidance returns.
        assert result["suggested_next_action"] == (
            "run build_project — project not built yet"
        )

    def test_authoring_off_no_modules_suggests_scaffolding(
        self, tmp_path: Path
    ) -> None:
        project = make_project(tmp_path / "proj", sources={})
        _set_authoring_off(project)
        result = project_status(project_root=str(project))
        assert result["authoring"] == "off"
        assert result["suggested_next_action"] == (
            "call scaffold_module to create the first module"
        )

    def test_authoring_off_fresh_build_suggests_check(
        self, project: Path
    ) -> None:
        _set_authoring_off(project)
        _build(project)
        result = project_status(project_root=str(project))
        assert result["authoring"] == "off"
        assert result["build"]["status"] == "fresh"
        assert result["suggested_next_action"] == "run check"

    def test_authoring_off_stale_build_suggests_rebuild(
        self, project: Path
    ) -> None:
        _set_authoring_off(project)
        _build(project)
        _touch(project / "src" / "models.s0ma")
        result = project_status(project_root=str(project))
        assert result["authoring"] == "off"
        assert result["suggested_next_action"] == (
            "run build_project — 1 module stale"
        )

    def test_non_project_has_no_authoring_key(self, tmp_path: Path) -> None:
        """A non-project answer carries no authoring posture (no project)."""
        result = project_status(project_root=str(tmp_path))
        assert result["is_project"] is False
        assert "authoring" not in result


class TestOverMcpBoundary:
    """The tool round-trips through the in-process MCP server."""

    def _call(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from s0ma_mcp import create_server

        outcome = asyncio.run(
            create_server().call_tool("project_status", arguments)
        )
        if isinstance(outcome, tuple):
            _content, structured = outcome
            assert isinstance(structured, dict)
            return structured
        assert isinstance(outcome, dict)
        return outcome

    def test_round_trips_fresh_project(self, project: Path) -> None:
        _build(project)
        result = self._call({"project_root": str(project)})
        assert result["ok"] is True
        assert result["is_project"] is True
        assert result["build"]["status"] == "fresh"
        # STD-M4: authoring posture survives the MCP boundary round-trip.
        assert result["authoring"] == "on"
        assert result["suggested_next_action"] == AUTHORING_HANDSHAKE

    def test_round_trips_non_project(self, tmp_path: Path) -> None:
        result = self._call({"project_root": str(tmp_path)})
        assert result["ok"] is True
        assert result["is_project"] is False
        assert "init_project" in result["suggested_next_action"]
