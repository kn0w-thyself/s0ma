"""Tests for the authoring-journey MCP prompts (PRD FR-MCP-6).

Three layers over five served journeys:

* listing — the served prompt set is exact, titled, described, and the
  declared arguments (required vs optional) match each journey;
* rendering — each prompt renders over the in-process boundary with its
  arguments interpolated into the copy, and missing required arguments
  are rejected;
* copy quality — the texts are product copy (PRD P-5): bounded length
  (the plan's ~40-line budget), standalone (every surface a prompt's
  self-model dependencies declare is actually named in its text), the
  golden rule and remediation discipline taught explicitly, INV-1
  spelling at the rendered surface.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")

from s0ma_mcp import create_server, get_self_registry

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

#: Every MCP prompt the server serves (drift-gated by test_components;
#: the fixed list here pins the M1 floor so a prompt cannot vanish).
EXPECTED_PROMPTS = {
    "author_module",
    "diagnose_fault",
    "feedback",
    "fix_check_failures",
    "migrate_project",
}

#: The plan's copy budget: each prompt stays within ~40 lines of text.
MAX_PROMPT_LINES = 40


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def mcp_server() -> FastMCP:
    return create_server()


def _render(mcp_server: FastMCP, name: str, arguments: dict[str, str]) -> str:
    """Render a prompt over the in-process boundary; return its text."""
    result = _run(mcp_server.get_prompt(name, arguments))
    assert len(result.messages) == 1
    message = result.messages[0]
    assert message.role == "user"
    assert message.content.type == "text"
    text: str = message.content.text
    return text


class TestPromptListing:
    """list_prompts: the exact journey set with honest metadata."""

    def test_lists_exactly_the_five_journey_prompts(
        self, mcp_server: FastMCP
    ) -> None:
        prompts = _run(mcp_server.list_prompts())
        assert {p.name for p in prompts} == EXPECTED_PROMPTS

    def test_prompts_carry_titles_and_descriptions(
        self, mcp_server: FastMCP
    ) -> None:
        for prompt in _run(mcp_server.list_prompts()):
            assert prompt.title, f"prompt '{prompt.name}' has no title"
            assert prompt.description and len(prompt.description) > 40, (
                f"prompt '{prompt.name}' description too thin for a "
                "client's command picker"
            )

    def test_author_module_argument_declaration(
        self, mcp_server: FastMCP
    ) -> None:
        listed = {p.name: p for p in _run(mcp_server.list_prompts())}
        arguments = {
            a.name: a.required for a in listed["author_module"].arguments or []
        }
        assert arguments == {
            "project_root": True,
            "module_name": True,
            "kind": False,
        }

    @pytest.mark.parametrize(
        "prompt_name", ["fix_check_failures", "migrate_project"]
    )
    def test_single_argument_prompts_require_project_root(
        self, mcp_server: FastMCP, prompt_name: str
    ) -> None:
        listed = {p.name: p for p in _run(mcp_server.list_prompts())}
        arguments = {
            a.name: a.required for a in listed[prompt_name].arguments or []
        }
        assert arguments == {"project_root": True}

    def test_diagnose_fault_argument_declaration(
        self, mcp_server: FastMCP
    ) -> None:
        listed = {p.name: p for p in _run(mcp_server.list_prompts())}
        arguments = {
            a.name: a.required for a in listed["diagnose_fault"].arguments or []
        }
        assert arguments == {"project_root": True, "fault": True}


class TestPromptRendering:
    """get_prompt: arguments interpolate; required ones are enforced."""

    def test_author_module_renders_the_full_journey(
        self, mcp_server: FastMCP
    ) -> None:
        text = _render(
            mcp_server,
            "author_module",
            {"project_root": "/tmp/demo-proj", "module_name": "Billing"},
        )
        assert "/tmp/demo-proj" in text
        assert "Billing" in text
        # The journey, in order: survival card → orient → scaffold →
        # check → build → IR confirmation. Since F7 the five tool steps
        # are rendered from journey:mcp-authoring-loop rather than
        # written into the copy, so the order asserted here is the
        # order the record walks (test_docs_agent_surface proves the two
        # are the same walk).
        anchors = [
            "s0ma://guide/survival-card",
            "project_status",
            "scaffold_module",
            "check",
            "build_project",
            "inspect_module",
        ]
        positions = [text.index(anchor) for anchor in anchors]
        assert positions == sorted(positions), (
            "author_module copy lost its journey order"
        )
        # The bootstrap call is named as the recovery for a directory
        # that is not a project yet — off the journey, so it has no
        # position on the ladder.
        assert "init_project" in text

    def test_author_module_interpolates_the_optional_kind(
        self, mcp_server: FastMCP
    ) -> None:
        with_kind = _render(
            mcp_server,
            "author_module",
            {
                "project_root": "/tmp/p",
                "module_name": "Billing",
                "kind": "ADAPTER",
            },
        )
        assert 'kind="ADAPTER"' in with_kind
        without_kind = _render(
            mcp_server,
            "author_module",
            {"project_root": "/tmp/p", "module_name": "Billing"},
        )
        assert "kind=" not in without_kind

    def test_fix_check_failures_teaches_the_remediation_loop(
        self, mcp_server: FastMCP
    ) -> None:
        text = _render(
            mcp_server, "fix_check_failures", {"project_root": "/tmp/p"}
        )
        assert "/tmp/p" in text
        assert "remediation" in text
        assert "severity" in text
        assert "group" in text.lower()

    def test_fix_check_failures_references_the_error_catalog(
        self, mcp_server: FastMCP
    ) -> None:
        """M2 cleared M1's debt: ``s0ma://guide/errors`` now exists.

        The copy references the error catalog unconditionally — the M1
        "if this server offers it" hedge must be gone — and the URI is
        a declared component dependency (the copy↔deps coherence test
        below enforces the naming side).
        """
        text = _render(
            mcp_server, "fix_check_failures", {"project_root": "/tmp/p"}
        )
        assert "s0ma://guide/errors" in text
        assert "if this server offers it" not in text
        assert "if available" not in text

    def test_migrate_project_plans_before_applying(
        self, mcp_server: FastMCP
    ) -> None:
        text = _render(
            mcp_server, "migrate_project", {"project_root": "/tmp/legacy"}
        )
        assert "/tmp/legacy" in text
        assert "dry_run=false" in text
        # Plan (dry run) must come before apply; apply before rebuild.
        assert text.index("Plan first") < text.index("dry_run=false")
        assert text.index("dry_run=false") < text.index("build_project")
        assert "regenera" in text  # caches are regenerable/regenerated

    def test_diagnose_fault_is_look_inward_first(
        self, mcp_server: FastMCP
    ) -> None:
        text = _render(
            mcp_server,
            "diagnose_fault",
            {"project_root": "/tmp/app", "fault": "checkout returns 500"},
        )
        assert "checkout returns 500" in text
        assert "Look inward first" in text
        anchors = ["project_status", "s0ma://project/runbook", "inspect_module"]
        positions = [text.index(anchor) for anchor in anchors]
        assert positions == sorted(positions)
        assert "observed behavior" in text

    def test_missing_required_argument_is_rejected(
        self, mcp_server: FastMCP
    ) -> None:
        with pytest.raises(ValueError, match="module_name"):
            _run(
                mcp_server.get_prompt(
                    "author_module", {"project_root": "/tmp/p"}
                )
            )


class TestPromptCopyQuality:
    """The texts are product copy: bounded, standalone, on-message."""

    ARGUMENTS: dict[str, dict[str, str]] = {
        "author_module": {"project_root": "/tmp/p", "module_name": "Billing"},
        "diagnose_fault": {"project_root": "/tmp/p", "fault": "HTTP 500"},
        "feedback": {"message": "the remediation was unclear"},
        "fix_check_failures": {"project_root": "/tmp/p"},
        "migrate_project": {"project_root": "/tmp/p"},
    }

    def test_prompt_texts_stay_within_the_length_budget(
        self, mcp_server: FastMCP
    ) -> None:
        for name, arguments in self.ARGUMENTS.items():
            text = _render(mcp_server, name, arguments)
            lines = len(text.splitlines())
            assert lines <= MAX_PROMPT_LINES, (
                f"prompt '{name}' renders {lines} lines — the plan budget "
                f"is ~{MAX_PROMPT_LINES}; tighten the copy"
            )

    def test_copy_names_every_declared_dependency(
        self, mcp_server: FastMCP
    ) -> None:
        """A prompt's self-model dependencies are referential edges: the
        surfaces its rendered text instructs the agent to call. Each one
        must actually be named in the copy — a renamed tool rots the
        copy, and this is where that rot surfaces.
        """
        components = get_self_registry().snapshot().components
        for name, arguments in self.ARGUMENTS.items():
            text = _render(mcp_server, name, arguments)
            for dependency in components[name].dependencies:
                assert dependency in text, (
                    f"prompt '{name}' declares dependency '{dependency}' "
                    "but its rendered copy never names it"
                )

    def test_copy_teaches_the_golden_rule(self, mcp_server: FastMCP) -> None:
        """Authoring/fixing copy must forbid editing generated Python."""
        for name in ("author_module", "fix_check_failures"):
            text = _render(mcp_server, name, self.ARGUMENTS[name])
            assert "only ever edit .s0ma" in text.lower()
            assert ".py" in text

    def test_rendered_copy_honors_the_naming_law(
        self, mcp_server: FastMCP
    ) -> None:
        """INV-1 at the product surface: digit zero, never letter o."""
        forbidden = r"soma"  # legacy-spelling: intentional (the guard pattern)
        for name, arguments in self.ARGUMENTS.items():
            text = _render(mcp_server, name, arguments)
            assert not re.search(forbidden, text, re.IGNORECASE), (
                f"prompt '{name}' rendered the forbidden letter-o spelling"
            )
