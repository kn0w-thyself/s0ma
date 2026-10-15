"""M0 schema-budget guard and quarantined MCP/release acceptance cases."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")

from s0ma_mcp import tools

pytestmark = pytest.mark.m0_contract

REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = Path(__file__).parent / "snapshots" / "mcp_surface.json"

BASELINE_TOOLS = {
    "adopt_file",
    "build_project",
    "check",
    "describe_server",
    "init_project",
    "inspect_module",
    "migrate_ext",
    "project_status",
    "run_example",
    "scaffold_module",
    "transpile",
}
M2_TOOLS = BASELINE_TOOLS | {"verify_host"}
#: FD-5 (0.14 surface budget §10 revision R1, owner-ratified 2026-08-27):
#: the ONLY authorized addition to the tool budget since M2 — the feedback
#: pair, landed at FB-M8. 12 tools to 14.
FD5_TOOLS = M2_TOOLS | {"prepare_feedback", "submit_feedback"}
#: F7 (doc-function plan §5, D-1..D-12 ratified 2026-08-28): the reserved
#: agent read surface. One tool, and the budget spends it on the question
#: the survival rules now tell every agent to ask. 14 tools to 15.
F7_TOOLS = FD5_TOOLS | {"learn_s0ma"}
BASELINE_RESOURCES = {
    "s0ma://guide/errors",
    "s0ma://guide/patterns",
    "s0ma://guide/quick-reference",
    "s0ma://guide/survival-card",
    "s0ma://guide/system-prompt",
    "s0ma://meta/changelog",
    "s0ma://meta/version",
    "s0ma://project/runbook",
    "s0ma://self/model",
    "s0ma://spec/current",
}
BASELINE_PROMPTS = {
    "author_module",
    "fix_check_failures",
    "migrate_project",
}
M5_PROMPTS = BASELINE_PROMPTS | {"diagnose_fault"}
#: FD-5 (same R1 revision): the ONLY authorized addition to the prompt
#: budget since M5 — the feedback journey, landed at FB-M9. 4 prompts to 5.
FD5_PROMPTS = M5_PROMPTS | {"feedback"}
M6_RESOURCES = BASELINE_RESOURCES | {"s0ma://guide/self-prompting"}
M7_RESOURCES = M6_RESOURCES | {"s0ma://guide/getting-started"}
#: F7 (same reservation): the s0ma://docs family. Three concrete
#: resources and no more — an index, the vocabulary, the worked paths —
#: because the per-topic question is the tool's job and 37 concept
#: resources in every client's listing is a context cost, not a feature.
F7_RESOURCES = M7_RESOURCES | {
    "s0ma://docs/index",
    "s0ma://docs/concepts",
    "s0ma://docs/journeys",
}
#: R5 (owner ruling 2026-09-29): the quick reference is a generated page
#: since that day, and an agent in somebody's project must be able to
#: reach every reference. ``s0ma://guide/quick-reference`` keeps its name
#: and answers with the page; its data twin is one new resource and the
#: only addition. 15/15/5 to 15/16/5.
R5_RESOURCES = F7_RESOURCES | {"s0ma://guide/quick-reference.json"}


def _surface() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_m7_surface_checkpoint_matches_the_frozen_budget() -> None:
    """The current surface consumes exactly the additions through M7, plus
    the later additions the owner authorized: the FD-5 feedback pair, the
    FD-5 feedback prompt, F7's reserved documentation read surface, and
    R5's data twin of the quick reference."""
    surface = _surface()
    assert {item["name"] for item in surface["tools"]} == F7_TOOLS
    assert {"prepare_feedback", "submit_feedback"} == FD5_TOOLS - M2_TOOLS
    assert {"learn_s0ma"} == F7_TOOLS - FD5_TOOLS
    assert {item["uri"] for item in surface["resources"]} == R5_RESOURCES
    assert {
        "s0ma://docs/index",
        "s0ma://docs/concepts",
        "s0ma://docs/journeys",
    } == F7_RESOURCES - M7_RESOURCES
    assert {"s0ma://guide/quick-reference.json"} == R5_RESOURCES - F7_RESOURCES
    # F7 spent no prompt budget: the journey binding rewrote what
    # author_module SAYS, and added no prompt to say it with.
    assert {item["name"] for item in surface["prompts"]} == FD5_PROMPTS
    assert {"feedback"} == FD5_PROMPTS - M5_PROMPTS
    verify_host = next(
        item for item in surface["tools"] if item["name"] == "verify_host"
    )
    assert verify_host["annotations"] == {
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
        "readOnlyHint": False,
        # Surface contract revision R3 (2026-09-18): every tool carries a
        # human-readable title, served here and as the tool's own ``title``.
        "title": "Verify imports in the app's Python",
    }
    assert verify_host["title"] == verify_host["annotations"]["title"]
    assert "diagnose_fault" in M5_PROMPTS
    assert "s0ma://guide/self-prompting" not in BASELINE_RESOURCES
    assert "s0ma://guide/getting-started" not in BASELINE_RESOURCES
    assert "s0ma://guide/getting-started" not in M6_RESOURCES


def test_derived_surface_cannot_masquerade_as_canonical_ir(project: Path) -> None:
    legacy = project / "src" / "legacy_impl.py"
    legacy.write_text(
        '"""Legacy helper awaiting componentization."""\n\nVALUE = 1\n',
        encoding="utf-8",
    )
    adopted = tools.adopt_file_tool(
        project_root=str(project),
        path="src/legacy_impl.py",
        description="Legacy helper awaiting componentization.",
    )
    assert adopted["ok"] is True

    result = tools.inspect_module_tool(
        project_root=str(project), module="legacy_impl"
    )
    assert result["ok"] is True
    assert "ir" not in result
    derived = result["derived_surface"]
    assert derived["schema"] == "s0ma-derived-surface@1"
    assert derived["authority"] == "derived"
    assert derived["mapped"] is False
    assert derived["provenance"] == {
        "method": "static_python_ast",
        "imports_executed": False,
    }
    assert "does not satisfy score or gate" in derived["limitations"]


def test_license_and_surface_metadata_are_current_and_generated() -> None:
    """The repaired license metadata stays pinned while stale inventories stay red."""
    expected = {
        "s0ma-core": (
            "Apache-2.0",
            "License :: OSI Approved :: Apache Software License",
            "Apache License",
        ),
        "s0ma-dsl": (
            "Apache-2.0",
            "License :: OSI Approved :: Apache Software License",
            "Apache License",
        ),
        "s0ma-mcp": (
            "Apache-2.0",
            "License :: OSI Approved :: Apache Software License",
            "Apache License",
        ),
    }
    for package, (expression, classifier, license_heading) in expected.items():
        package_root = REPO_ROOT / "packages" / package
        pyproject = tomllib.loads(
            (package_root / "pyproject.toml").read_text(encoding="utf-8")
        )
        project = pyproject["project"]
        assert project["license"] == expression
        assert classifier in project["classifiers"]
        # lstrip: the canonical Apache-2.0 text opens with a centered
        # (whitespace-led) title line.
        assert (package_root / "LICENSE").read_text(
            encoding="utf-8"
        ).lstrip().startswith(license_heading)

    surface = _surface()
    marker_start = "<!-- BEGIN GENERATED MCP SURFACE -->"
    marker_end = "<!-- END GENERATED MCP SURFACE -->"
    for readme_path in (REPO_ROOT / "README.md", REPO_ROOT / "packages" / "s0ma-mcp" / "README.md"):
        readme = readme_path.read_text(encoding="utf-8")
        assert marker_start in readme and marker_end in readme
        generated = readme.split(marker_start, 1)[1].split(marker_end, 1)[0]
        for tool in surface["tools"]:
            assert f"`{tool['name']}`" in generated
        for resource in surface["resources"]:
            assert f"`{resource['uri']}`" in generated
        for prompt in surface["prompts"]:
            assert f"`{prompt['name']}`" in generated
