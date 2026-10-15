"""The feedback journey the agent is taught: prompt, instruction, offer.

FB-M9 adds no new mechanism — ``prepare_feedback`` and ``submit_feedback``
already carry the whole trust contract. What it adds is *recognition*, in
three places with three different reaches:

* the ``feedback`` **prompt** (FD-5's one authorized prompt) — the journey
  a client can invoke by name, seeded from the user's own words;
* the server-level **recognition instruction** — always served, so an agent
  reacts to a user who explicitly asks to send feedback about s0ma. It
  carries the A-1 disambiguation rule (feedback that never named s0ma is
  confirmed first — other tools collect feedback too) and the two
  prohibitions: never submit outside the approval interaction, and never
  read frustration as consent;
* the FD-13 **suggest-offer line** — served per rules render, and ONLY to a
  project whose ``[tool.s0ma]`` says ``feedback = "suggest"``. This is the
  D-11 narration-rule mechanism reused exactly: configuration read per
  render, every other reading absent, absent never an error, and absent
  meaning byte-identical rules.

The asymmetry is the product rule, and it is asserted here: ``"off"``
silences the OFFER and nothing else. A user who asks for feedback out loud
is always heard, because the instruction that teaches that is unconditional
and no project setting can reach it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")

from conftest import mainline_rules, make_project

from s0ma_mcp import create_server, resources, tools

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

#: The committed self-prompt card — a static build artifact.
SELF_PROMPT_CARD = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "s0ma_mcp"
    / "_built"
    / "self_prompt_card.md"
)

#: The three rules-bearing calls that name a project root, and so can read
#: that project's declared feedback posture. ``describe_server`` answers
#: about the server and names no project, so it is covered separately.
ROOTED_CHANNELS = ("project_status", "init_project", "scaffold_module")

#: The rules with nothing conditional fired (conftest holds the one
#: definition): the canonical block plus F7's unconditional docs line.
MAINLINE_RULES = mainline_rules()

#: Where the offer lands when it fires. It is appended to the canonical
#: block BEFORE the unconditional docs line and the conditional narration
#: line, so its index is the end of the canonical block in every posture —
#: which is what lets one index serve the studi0-off and studi0-on cases.
OFFER_INDEX = len(tools._SURVIVAL_RULES)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def mcp_server() -> FastMCP:
    return create_server()


def _render(mcp_server: FastMCP, arguments: dict[str, str]) -> str:
    result = _run(mcp_server.get_prompt("feedback", arguments))
    assert len(result.messages) == 1
    text: str = result.messages[0].content.text
    return text


def project_with(root: Path, posture: str | None) -> Path:
    """A real project declaring (or omitting) ``[tool.s0ma] feedback``."""
    made = make_project(root, sources={})
    if posture is not None:
        pyproject = made / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8") + f'feedback = "{posture}"\n',
            encoding="utf-8",
        )
    return made


def rules_for(call: str, root: Path) -> list[str]:
    """The rules list one rules-bearing tool result carries for *root*."""
    calls = {
        "project_status": lambda: tools.project_status_tool(str(root)),
        "init_project": lambda: tools.init_project_tool(str(root)),
        "scaffold_module": lambda: tools.scaffold_module_tool(str(root), "probe"),
    }
    rules: list[str] = calls[call]()["rules"]
    return rules


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------


class TestFeedbackPrompt:
    """The one prompt FD-5 authorized, and the journey it carries."""

    def test_it_is_served_with_a_title_and_one_optional_argument(
        self, mcp_server: FastMCP
    ) -> None:
        listed = {p.name: p for p in _run(mcp_server.list_prompts())}
        prompt = listed["feedback"]

        assert prompt.title == "Send feedback to the s0ma team"
        assert {
            a.name: a.required for a in prompt.arguments or []
        } == {"message": False}

    def test_the_users_words_seed_the_draft(self, mcp_server: FastMCP) -> None:
        text = _render(mcp_server, {"message": "the remediation was unclear"})

        assert "the remediation was unclear" in text
        assert "__MESSAGE__" not in text

    def test_an_absent_message_asks_rather_than_invents(
        self, mcp_server: FastMCP
    ) -> None:
        """The one place the journey may interrupt: it has nothing yet."""
        text = _render(mcp_server, {})

        assert "__MESSAGE__" not in text
        assert "ONE short question" in text

    def test_the_journey_runs_prepare_then_review_then_submit(
        self, mcp_server: FastMCP
    ) -> None:
        text = _render(mcp_server, {"message": "check output is noisy"})
        anchors = [
            "did not name s0ma",
            "prepare_feedback",
            "redaction report",
            "submit_feedback",
            "s0ma feedback",
        ]
        positions = [text.index(anchor) for anchor in anchors]

        assert positions == sorted(positions), (
            "feedback copy lost its journey order"
        )

    def test_the_copy_never_claims_the_users_approval(
        self, mcp_server: FastMCP
    ) -> None:
        text = _render(mcp_server, {"message": "x"})

        assert "approval form does the asking" in text
        assert "never state or assume that the user" in text
        assert "never read frustration" in text.replace("\n", " ")

    def test_the_copy_speaks_the_users_language(
        self, mcp_server: FastMCP
    ) -> None:
        """A-2: the served word is "feedback data", never "payload"."""
        listed = {p.name: p for p in _run(mcp_server.list_prompts())}
        text = _render(mcp_server, {"message": "x"})

        assert "feedback data" in text
        assert "payload" not in text.lower()
        assert "payload" not in (listed["feedback"].description or "").lower()


# ---------------------------------------------------------------------------
# The always-served recognition instruction
# ---------------------------------------------------------------------------


class TestRecognitionInstruction:
    """Unconditional: no project setting can switch this off."""

    def test_it_teaches_the_explicit_route(self, mcp_server: FastMCP) -> None:
        instructions = mcp_server.instructions or ""

        assert "explicitly asks to send feedback about s0ma" in instructions
        assert "feedback prompt's journey" in instructions

    def test_it_carries_the_a1_disambiguation_rule(
        self, mcp_server: FastMCP
    ) -> None:
        """Feedback that never named s0ma is confirmed before anything else."""
        instructions = mcp_server.instructions or ""

        assert "never named s0ma or kn0wthyself" in instructions
        assert "other tools collect feedback too" in instructions

    def test_it_carries_both_prohibitions(self, mcp_server: FastMCP) -> None:
        instructions = mcp_server.instructions or ""

        assert "Never submit without the client's approval interaction" in (
            instructions
        )
        assert "never read frustration as consent" in instructions

    def test_it_does_not_restate_the_journey_map_entry(
        self, mcp_server: FastMCP
    ) -> None:
        """The map names the tools; the instruction teaches the behavior.

        Both are always served, so duplicated wording would be duplicated
        context cost (NFR-5). The situation-to-tool map's own entry stays
        the single place the tool NAMES appear for this journey.
        """
        instructions = mcp_server.instructions or ""

        assert "send feedback about s0ma" in instructions  # the map entry
        assert instructions.count("prepare_feedback") == 1
        assert instructions.count("submit_feedback") == 1


# ---------------------------------------------------------------------------
# FD-13: the offer line, served only where the project asked for it
# ---------------------------------------------------------------------------


class TestSuggestOffer:
    """suggest → present; off → absent; no key → absent; and never cached."""

    @pytest.mark.parametrize("call", ROOTED_CHANNELS)
    def test_suggest_appends_exactly_one_line(
        self, call: str, tmp_path: Path
    ) -> None:
        root = project_with(tmp_path / "proj", "suggest")
        rules = rules_for(call, root)

        assert rules == [
            *tools._SURVIVAL_RULES, rules[OFFER_INDEX], tools._DOCS_RULE
        ]
        assert len(rules) == len(MAINLINE_RULES) + 1
        assert "offer to draft feedback for the s0ma team" in rules[OFFER_INDEX]

    def test_the_offer_is_one_line_carrying_the_whole_rule(
        self, tmp_path: Path
    ) -> None:
        """NFR-5 context economy: one line, and it says everything."""
        root = project_with(tmp_path / "proj", "suggest")
        rule = rules_for("project_status", root)[OFFER_INDEX]

        assert "\n" not in rule
        for marker in (
            "When s0ma itself is the obstacle",  # specific, not ambient
            "non-blocking offer",  # never blocks the work
            "prepare_feedback only after the user agrees",
            "approves the exact feedback data before anything is sent",
        ):
            assert marker in rule, marker

    @pytest.mark.parametrize("posture", ["off", None, "", "Suggest", "on"])
    def test_every_other_posture_is_byte_identical_silence(
        self, posture: str | None, tmp_path: Path
    ) -> None:
        """"off" and an absent key read the same, and neither costs a byte."""
        root = project_with(tmp_path / f"proj_{posture or 'absent'}", posture)

        result = tools.project_status_tool(str(root))
        assert result["ok"] is True
        assert result["rules"] == MAINLINE_RULES

    def test_a_directory_that_is_not_a_project_never_offers(
        self, tmp_path: Path
    ) -> None:
        """No pyproject means no declared posture, and absent is not an error."""
        root = tmp_path / "bare"
        root.mkdir()

        result = tools.project_status_tool(str(root))
        assert result["ok"] is True and result["is_project"] is False
        assert result["rules"] == MAINLINE_RULES

    @pytest.mark.parametrize(
        ("label", "text"),
        [
            ("empty", ""),
            ("truncated table header", "[tool.s0ma\n"),
            ("not toml at all", "s0ma was here\n"),
            ("no tool table", '[project]\nname = "x"\n'),
            ("tool is not a table", 'tool = "s0ma"\n'),
            ("s0ma is not a table", '[tool]\ns0ma = "on"\n'),
            ("feedback is not a string", "[tool.s0ma]\nfeedback = true\n"),
            ("feedback is a list", '[tool.s0ma]\nfeedback = ["suggest"]\n'),
        ],
    )
    def test_an_unreadable_posture_is_absent_never_an_error(
        self, label: str, text: str, tmp_path: Path
    ) -> None:
        """Every reading but the exact opt-in is silence, and none raises.

        Asserted on the reader itself: a malformed ``pyproject.toml``
        fails project discovery long before the rules are rendered, so
        the tool-result layer cannot show what this reader does with one.
        """
        root = tmp_path / f"probe_{label.replace(' ', '_')}"
        root.mkdir()
        (root / "pyproject.toml").write_text(text, encoding="utf-8")

        assert tools._feedback_offers_enabled(root) is False, label

    def test_a_directory_where_the_pyproject_should_be_is_absent(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "probe"
        (root / "pyproject.toml").mkdir(parents=True)

        assert tools._feedback_offers_enabled(root) is False

    def test_no_root_in_scope_is_absent(self) -> None:
        assert tools._feedback_offers_enabled(None) is False

    def test_describe_server_names_no_project_so_it_never_offers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No root in scope is answered honestly — not guessed from cwd."""
        root = project_with(tmp_path / "proj", "suggest")
        monkeypatch.chdir(root)

        assert tools.describe_server_tool()["rules"] == MAINLINE_RULES

    def test_a_neighbouring_projects_posture_is_not_this_projects(
        self, tmp_path: Path
    ) -> None:
        opted_in = project_with(tmp_path / "opted_in", "suggest")
        opted_out = project_with(tmp_path / "opted_out", "off")

        assert tools.project_status_tool(str(opted_out))["rules"] == MAINLINE_RULES
        assert "offer to draft feedback" in (
            tools.project_status_tool(str(opted_in))["rules"][OFFER_INDEX]
        )

    def test_editing_the_posture_mid_session_is_noticed(
        self, tmp_path: Path
    ) -> None:
        """Read per render — the same process answers the current truth."""
        root = project_with(tmp_path / "proj", None)
        pyproject = root / "pyproject.toml"
        canonical = MAINLINE_RULES
        base = pyproject.read_text(encoding="utf-8")

        assert tools.project_status_tool(str(root))["rules"] == canonical

        pyproject.write_text(base + 'feedback = "suggest"\n', encoding="utf-8")
        assert "offer to draft feedback" in (
            tools.project_status_tool(str(root))["rules"][OFFER_INDEX]
        )

        pyproject.write_text(base + 'feedback = "off"\n', encoding="utf-8")
        assert tools.project_status_tool(str(root))["rules"] == canonical


class TestOfferAndNarrationCoexist:
    """Two independent conditions, and the measured line keeps its place."""

    def test_the_frozen_narration_line_stays_last(self, tmp_path: Path) -> None:
        """The M8 bench measured the narration line at the END of the rules.

        The offer is inserted before it rather than after, and F7's
        unconditional docs line between the two, so a project that turns
        both on does not move the one line whose position was measured.
        """
        from test_narration_rule import NARRATION_RULE, arm

        root = project_with(tmp_path / "proj", "suggest")
        arm(root)

        rules = tools.project_status_tool(str(root))["rules"]
        assert rules[:OFFER_INDEX] == list(tools._SURVIVAL_RULES)
        assert "offer to draft feedback" in rules[OFFER_INDEX]
        assert rules[-2] == tools._DOCS_RULE
        assert rules[-1] == NARRATION_RULE
        # Both conditions fired, so exactly two lines beyond the mainline.
        assert len(rules) == len(MAINLINE_RULES) + 2


class TestTheOfferStaysDynamic:
    """Config-conditional content can never reach a static artifact."""

    def test_the_static_survival_card_never_carries_the_offer(self) -> None:
        assert "offer to draft feedback" not in resources.survival_card_resource()

    def test_the_self_prompt_card_never_carries_the_offer(self) -> None:
        card = SELF_PROMPT_CARD.read_text(encoding="utf-8")

        assert "offer to draft feedback" not in card

    def test_the_offer_never_became_a_tool(self, mcp_server: FastMCP) -> None:
        served = {tool.name for tool in _run(mcp_server.list_tools())}

        assert len(served) == 15  # 12 at M11, +2 at FB-M8, +learn_s0ma at F7
        assert not [name for name in served if "offer" in name]
