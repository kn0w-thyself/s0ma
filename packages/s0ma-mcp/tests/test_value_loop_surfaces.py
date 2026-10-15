"""M5 value-loop result, protocol, derived-map, and journey acceptance."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")

from conftest import make_project

from s0ma_mcp import create_server, tool_journey_map, tools

if TYPE_CHECKING:
    from pathlib import Path

    from mcp.server.fastmcp import FastMCP

TOOL_RESULT_SCHEMA = "s0ma-tool-result@1"
PRE_M5_LONGEST_DESCRIPTION_WORDS = 310


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _call(server: FastMCP, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    outcome = _run(server.call_tool(name, arguments))
    structured = outcome[1] if isinstance(outcome, tuple) else outcome
    assert isinstance(structured, dict)
    return structured


@pytest.fixture(scope="module")
def server() -> FastMCP:
    return create_server()


class TestCommonToolResult:
    """Every body result is common-envelope data with live-valid actions."""

    def test_every_tool_body_result_uses_common_envelope_and_live_actions(
        self, server: FastMCP, tmp_path: Path
    ) -> None:
        missing = str(tmp_path / "missing")
        calls: dict[str, dict[str, Any]] = {
            "adopt_file": {
                "project_root": missing,
                "path": "src/legacy.py",
                "description": "Legacy adapter",
            },
            "build_project": {"project_root": missing},
            "check": {"path": missing},
            "describe_server": {},
            "init_project": {"project_root": missing},
            "inspect_module": {"project_root": missing},
            "migrate_ext": {"project_root": missing},
            "project_status": {"project_root": missing},
            "run_example": {"project_root": missing},
            "scaffold_module": {
                "project_root": missing,
                "module_name": "Legacy",
            },
            "transpile": {"source_path": missing},
            "verify_host": {"project_root": missing},
            "prepare_feedback": {
                "summary": "The remediation text did not say where to move it",
                "category": "diagnostic_quality",
                "impact": "minor",
            },
            # Not the pair prepare_feedback returns, so this refuses before
            # anyone could be asked to approve anything (FB-M8).
            "submit_feedback": {
                "envelope": {},
                "payload_sha256": "sha256:" + "0" * 64,
            },
            # F7: the documentation read surface takes no project root —
            # it answers about s0ma, not about a tree — so its breadcrumb
            # is a next topic rather than a next call on this project.
            "learn_s0ma": {"topic": "concept:ganglion"},
        }
        listed = {tool.name for tool in _run(server.list_tools())}
        assert set(calls) == listed
        for name, arguments in calls.items():
            result = _call(server, name, arguments)
            assert result["schema"] == TOOL_RESULT_SCHEMA, name
            assert isinstance(result["ok"], bool), name
            assert isinstance(result["next_actions"], list), name
            expected_rendering = (
                result["next_actions"][0]["reason"]
                if result["next_actions"]
                else None
            )
            assert result.get("suggested_next_action") == expected_rendering
            for action in result["next_actions"]:
                assert action["tool"] in listed
                assert isinstance(action["arguments"], dict)
                assert action["reason"].strip()
            if result["ok"] is False:
                assert set(result["tool_map"]) == listed

    def test_host_evidence_has_one_nested_authority(
        self, server: FastMCP, project: Path
    ) -> None:
        pyproject = project / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8").replace(
                'version = "0.1.0"',
                'version = "0.1.0"\ndependencies = ["s0ma-core", "s0ma-dsl"]',
            ),
            encoding="utf-8",
        )
        assert tools.build_project_tool(str(project))["ok"] is True
        result = _call(
            server,
            "verify_host",
            {"project_root": str(project), "python": sys.executable},
        )
        assert result["schema"] == TOOL_RESULT_SCHEMA
        report = result["host_verification"]
        assert report["schema"] == "s0ma-host-verification@1"
        for field in ("gate", "interpreter", "modules", "dependencies"):
            assert field in report
            assert field not in result

    def test_schema_invalid_call_stays_a_protocol_error(
        self, server: FastMCP, tmp_path: Path
    ) -> None:
        with pytest.raises(Exception) as caught:
            _run(
                server.call_tool(
                    "project_status",
                    {"project_rooot": str(tmp_path)},
                )
            )
        rendered = str(caught.value)
        assert "validation error" in rendered
        assert TOOL_RESULT_SCHEMA not in rendered
        assert "tool_map" not in rendered

    def test_body_failure_is_structured_correction_data(
        self, server: FastMCP, tmp_path: Path
    ) -> None:
        result = _call(
            server,
            "project_status",
            {"project_root": str(tmp_path / "missing")},
        )
        assert result["ok"] is False
        assert result["schema"] == TOOL_RESULT_SCHEMA
        assert result["next_actions"][0]["tool"] == "describe_server"
        assert "project_status" in result["tool_map"]


class TestDerivedInspection:
    def test_pure_roster_inspection_is_derived_and_gate_inert(
        self, tmp_path: Path
    ) -> None:
        project = make_project(tmp_path / "roster", sources={})
        legacy = project / "src" / "legacy_impl.py"
        legacy.write_text(
            '"""Legacy payment adapter awaiting intent review."""\n'
            "import decimal\n\n"
            "def charge():\n"
            "    return decimal.Decimal('1.00')\n",
            encoding="utf-8",
        )
        adopted = tools.adopt_file_tool(
            str(project), "src/legacy_impl.py", "Legacy payment adapter"
        )
        assert adopted["ok"] is True
        score_args = [
            "--project-root",
            str(project),
            "score",
            "--format",
            "json",
            "--gate-mode",
            "release",
        ]
        _, before, _ = tools._run_cli(score_args)

        result = tools.inspect_module_tool(str(project), "legacy_impl")

        _, after, _ = tools._run_cli(score_args)
        assert before == after
        assert result["ok"] is True
        assert result["banner"] == (
            "DERIVED (unverified) — componentize to make this authoritative"
        )
        assert "ir" not in result
        surface = result["derived_surface"]
        assert surface["schema"] == "s0ma-derived-surface@1"
        assert surface["authority"] == "derived"
        assert surface["mapped"] is False
        assert surface["provenance"]["imports_executed"] is False
        assert surface["exports"] == ["charge"]
        assert surface["imports"] == ["decimal"]
        assert "does not satisfy score or gate" in surface["limitations"]

        status = tools.project_status_tool(str(project))
        assert status["module_registration"] == {
            "mapped": 0,
            "roster_adopted": 1,
        }
        roster_row = status["modules"][0]
        assert roster_row["registration"] == "roster_adopted"
        assert roster_row["mapped"] is False

    def test_project_status_roster_rows_are_current_plain_python_only(
        self, tmp_path: Path
    ) -> None:
        project = make_project(tmp_path / "roster-classification", sources={})
        fixtures = {
            "src/current.py": "def current():\n    return True\n",
            "src/missing.py": "def missing():\n    return True\n",
            "notes.txt": "migration notes\n",
            "build/converted.py": "def converted():\n    return True\n",
        }
        for relative, content in fixtures.items():
            path = project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            adopted = tools.adopt_file_tool(
                str(project), relative, f"Intent recorded for {relative}"
            )
            assert adopted["ok"] is True

        (project / "src" / "missing.py").unlink()
        (project / "build" / "converted.py").write_text(
            "# s0ma-source-hash: sha256:deadbeef\n"
            "# s0ma-output-hash: sha256:feedface\n"
            "def converted():\n    return True\n",
            encoding="utf-8",
        )

        status = tools.project_status_tool(str(project))

        assert {item["path"] for item in status["adopted_files"]} == set(fixtures)
        assert status["module_registration"] == {
            "mapped": 0,
            "roster_adopted": 1,
        }
        assert status["modules"] == [{
            "name": "current",
            "source": str(project / "src" / "current.py"),
            "status": "roster",
            "registration": "roster_adopted",
            "mapped": False,
        }]

    def test_canonical_inspection_carries_dependency_neighbor_actions(
        self, project: Path
    ) -> None:
        assert tools.build_project_tool(str(project))["ok"] is True
        result = tools.inspect_module_tool(str(project), "processing")
        assert result["ok"] is True
        relationships = {
            (action.get("relationship"), action["arguments"].get("module"))
            for action in result["next_actions"]
        }
        assert ("depends_on", "models") in relationships
        assert ("depended_by", "routing") in relationships


class TestJourneyAndDescriptions:
    def test_handshake_carries_journeys_and_jtbd_descriptions(
        self, server: FastMCP
    ) -> None:
        assert server.instructions is not None
        assert "look inward first" in server.instructions.lower()
        assert "diagnose_fault" in server.instructions
        assert "project_status" in server.instructions
        compact_journeys = json.dumps(
            tool_journey_map(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        assert f"Live situation-to-tool map: {compact_journeys}" in (
            server.instructions
        )
        for tool in _run(server.list_tools()):
            description = tool.description or ""
            assert "Example:" in description, tool.name
            assert len(description.split()) <= PRE_M5_LONGEST_DESCRIPTION_WORDS
        inspect_description = next(
            tool.description
            for tool in _run(server.list_tools())
            if tool.name == "inspect_module"
        )
        assert inspect_description.startswith(
            "Before grepping for where X is handled"
        )

    def test_describe_server_has_live_situation_map(
        self, server: FastMCP
    ) -> None:
        result = _call(server, "describe_server", {})
        listed = {tool.name for tool in _run(server.list_tools())}
        assert set(result["tool_map"]) == listed
        mapped = {
            tool
            for journey_tools in result["journeys"].values()
            for tool in journey_tools
        }
        assert mapped == listed
        assert {
            "orient in an unfamiliar project",
            "start a component from intent",
            "inspect before grepping",
            "repair authored diagnostics",
            "migrate pre-existing Python",
            "prove host runtime reality",
            "diagnose an observed runtime fault",
        } <= set(result["journeys"])
        assert result["journeys"]["inspect before grepping"] == [
            "inspect_module"
        ]

    def test_project_status_embeds_operate_diagnose_journey(
        self, tmp_path: Path
    ) -> None:
        project = make_project(tmp_path / "ops")
        pyproject = project / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8")
            + '\nrun_command = "uv run app"\nhealth_command = "curl /health"\n',
            encoding="utf-8",
        )
        result = tools.project_status_tool(str(project))
        journey = result["diagnose_journey"]
        assert journey["principle"].startswith("Look inward first")
        steps = journey["steps"]
        assert steps[0]["step"] == "fault"
        assert steps[1]["tool"] == "project_status"
        assert steps[2]["resource"] == "s0ma://project/runbook"
        assert steps[3]["tool"] == "inspect_module"
        assert steps[4]["step"] == "observed_behavior"

    def test_check_finding_names_resolvable_owner_and_intent(
        self, project: Path
    ) -> None:
        routing = project / "src" / "routing.s0ma"
        routing.write_text(
            routing.read_text(encoding="utf-8").replace(
                "models.UserModel", "models.DoesNotExist"
            ),
            encoding="utf-8",
        )
        result = tools.check_tool(project_root=str(project), mode="strict")
        assert result["ok"] is False
        owned = [
            finding
            for finding in result["diagnostics"]["errors"]
            if str(finding.get("owner", "")).startswith("routing::")
        ]
        assert owned
        assert all(finding.get("owner_intent") for finding in owned)
