"""The agent discovery contract, through real in-process results (F9).

Milestone F9 of the docs-function plan (internal) §11, the agent half.
Architecture §9.6 lists seven ways an *agent* comes to know that this
product documents itself, and it closes with the rule this file exists to
obey: "Discovery must be tested through actual in-process MCP results.
The existence of a resource URI alone does not satisfy this contract."
Everything below therefore boots ``create_server()`` and calls it. Nothing
here asserts about a registration table.

Three things are proved, in the order the milestone asks for them:

* **the seven routes** (§9.6), each mapped to a class by
  :data:`AGENT_ENTRY_POINTS` so the contract cannot shrink by deletion;
* **the budgets**, read out of B6's ``fixtures/budgets.json`` and out of
  the model's own ``AGENT_BYTE_BUDGET`` — never restated here, because a
  suite that agreed with a number nobody declared would be agreeing with
  itself;
* **channel parity** (§9.7): one topic through the terminal and through
  ``learn_s0ma`` carrying the same identity and the same facts verbatim,
  and a four-channel identity sweep — committed page, terminal, tool,
  resource — over three topics.

The human half is ``s0ma-dsl``'s ``tests/test_docs_discovery_contract.py``.
The two meet at the composed snapshot and nowhere else, which is the
point: this package reads the copy packaged inside its own wheel, and the
parity proof below is what says the two copies answer alike.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("mcp", reason="MCP SDK not installed")

from conftest import REPO_ROOT, make_project

from s0ma_mcp import create_server, prompts, resources, tools

B6_BUDGETS = (
    REPO_ROOT
    / "scripts"
    / "spikes"
    / "docs_model"
    / "spike_b6_discovery"
    / "fixtures"
    / "budgets.json"
)

#: The names a discovery failure and a parity failure are reported under.
#: Both are milestone-local, following the precedent
#: ``test_docs_resolve_render`` set for ``DOC_CHANNEL_DIVERGENCE``: neither
#: gate reads a *record*, so neither has a home in
#: ``docs_model.validate`` — they read what a running server actually
#: hands an agent, which no build-time validator has in front of it.
DOC_DISCOVERY_BROKEN = "DOC_DISCOVERY_BROKEN"
DOC_CHANNEL_DIVERGENCE = "DOC_CHANNEL_DIVERGENCE"

#: Architecture §9.6's seven, in its order, each mapped to the class that
#: proves it.
AGENT_ENTRY_POINTS: dict[str, str] = {
    "1-instructions-name-the-query-and-index": "TestInstructionsNameTheQuery",
    "2-tool-descriptions-say-when-to-consult": "TestToolDescriptionsSayWhen",
    "3-high-traffic-results-carry-a-pointer": "TestHighTrafficResultsCarryAPointer",
    "4-failing-diagnostics-deep-link": "TestFailingDiagnosticsDeepLink",
    "5-prompts-name-their-dependencies": "TestPromptsNameTheirDependencies",
    "6-generated-agents-md-establishes-both": "TestGeneratedAgentsMd",
    "7-the-index-describes-its-own-retrieval": "TestTheIndexDescribesItself",
}

#: The docs paragraph inside the served instructions, located by its own
#: opening and closing sentences (F7's idiom — the instructions are one
#: string, so the paragraph is found rather than stored twice).
INSTRUCTIONS_DOCS_OPENING = "This server documents itself:"
INSTRUCTIONS_DOCS_CLOSING = "Ask rather than guess what a s0ma word means. "

#: The three F7 resources, and the three core's runtime server serves
#: under the same scheme without collision.
DOCS_RESOURCES = frozenset(
    {"s0ma://docs/index", "s0ma://docs/concepts", "s0ma://docs/journeys"}
)

#: Three topics for the residue comparison: two concepts (one with a
#: written syntax form, one without) and one journey, so the comparison
#: covers more than one shape of record rather than three of a kind.
PARITY_TOPICS: tuple[str, ...] = (
    "concept:nerve",
    "concept:self-knowledge",
    "journey:first-project",
)

#: Three topics for the *four*-channel identity sweep, and all three are
#: concepts on purpose. A concept is the one kind of record this build
#: projects onto a committed Markdown page of its own
#: (``docs/learn/<term>.md``, stamped with the build that wrote it), so a
#: concept is the only topic that really has four channels. What a
#: journey has instead is recorded and asserted by
#: :meth:`TestFourChannelIdentity.test_a_journeys_markdown_is_a_pointer_not_a_projection`.
SWEEP_TOPICS: tuple[str, ...] = (
    "concept:nerve",
    "concept:self-knowledge",
    "concept:ganglion",
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def server() -> Any:
    return create_server()


@pytest.fixture(scope="module")
def served(server: Any) -> dict[str, Any]:
    return {
        "tools": {str(item.name): item for item in _run(server.list_tools())},
        "resources": {str(item.uri): item for item in _run(server.list_resources())},
        "prompts": {str(item.name): item for item in _run(server.list_prompts())},
    }


def _read(server: Any, uri: str) -> str:
    contents = list(_run(server.read_resource(uri)))
    assert len(contents) == 1, uri
    return str(contents[0].content)


def _call(server: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """One tool call across the real MCP boundary."""
    outcome = _run(server.call_tool(name, arguments))
    structured = outcome[1] if isinstance(outcome, tuple) else outcome
    assert isinstance(structured, dict), name
    return structured


def _budget(artifact: str) -> dict[str, Any]:
    document = json.loads(B6_BUDGETS.read_text(encoding="utf-8"))
    for entry in document["budgets"]:
        if entry["artifact"] == artifact:
            return dict(entry)
    raise AssertionError(f"B6 declared no budget for {artifact!r}")


def _docs_paragraph(server: Any) -> str:
    instructions = server.instructions or ""
    assert INSTRUCTIONS_DOCS_OPENING in instructions
    start = instructions.index(INSTRUCTIONS_DOCS_OPENING)
    end = instructions.index(INSTRUCTIONS_DOCS_CLOSING) + len(
        INSTRUCTIONS_DOCS_CLOSING
    )
    return instructions[start:end]


def _addresses(text: str) -> set[str]:
    """Every ``s0ma://`` address named in a piece of text."""
    return {
        word.strip(".,;:()`\"'")
        for word in text.split()
        if word.startswith("s0ma://")
    }


def _resolves(identifier: str) -> None:
    """``identifier`` is a question this served build can answer."""
    answered = tools.learn_s0ma_tool(identifier)

    assert answered["ok"] is True, (
        f"{DOC_DISCOVERY_BROKEN}: a discovery route names {identifier!r} and "
        f"this build does not address it"
    )


# ---------------------------------------------------------------------------
# 1 — server instructions
# ---------------------------------------------------------------------------


class TestInstructionsNameTheQuery:
    """§9.6.1: instructions name the one topic query and the docs index.

    The B7 baseline: the served instructions did not contain the word
    "docs" at all. They do now, in a paragraph inside its own budget, and
    everything the paragraph names is served — which is the whole content
    of ``DOC_DISCOVERY_BROKEN`` on this channel.
    """

    def test_the_paragraph_names_the_tool_and_the_index(
        self, server: Any, served: dict[str, Any]
    ) -> None:
        paragraph = _docs_paragraph(server)

        assert "learn_s0ma(topic)" in paragraph
        assert "s0ma://docs/index" in paragraph
        assert "learn_s0ma" in served["tools"]

    def test_every_address_it_names_is_really_served(
        self, server: Any, served: dict[str, Any]
    ) -> None:
        for uri in sorted(_addresses(_docs_paragraph(server))):
            assert uri in served["resources"], (
                f"{DOC_DISCOVERY_BROKEN}: the instructions send an agent to "
                f"{uri} and this server does not serve it"
            )

    def test_each_address_it_names_actually_answers(self, server: Any) -> None:
        """Existing and answering are different facts (§9.6 closing rule)."""
        for uri in sorted(_addresses(_docs_paragraph(server))):
            assert len(_read(server, uri).strip()) > 500, uri

    def test_the_paragraph_fits_the_budget_b6_declared(self, server: Any) -> None:
        declared = _budget("server_instructions")
        paragraph = _docs_paragraph(server)
        instructions = server.instructions or ""

        assert len(paragraph.encode("utf-8")) <= declared["budget_bytes"], (
            f"the docs paragraph is {len(paragraph.encode('utf-8'))} bytes "
            f"against {declared['budget_bytes']} ({declared['rule']})"
        )
        # B6 derived the budget as a fifth of the served blob and recorded
        # the measurement. Re-derive rather than trust: a blob that grew
        # means the budget is stale, not that the paragraph got cheaper.
        served_bytes = len(instructions.encode("utf-8"))
        assert served_bytes >= declared["recorded_bytes"], (
            f"the served instructions are now {served_bytes} bytes and B6 "
            f"measured {declared['recorded_bytes']}; re-derive the budget"
        )
        assert declared["budget_bytes"] * declared["divisor"] <= served_bytes


# ---------------------------------------------------------------------------
# 2 — tool descriptions
# ---------------------------------------------------------------------------


class TestToolDescriptionsSayWhen:
    """§9.6.2: tool descriptions state when a topic should be consulted.

    Two halves, and the second is stated precisely because it is only
    partly met. The topic query's own description says what kind of
    question it answers and carries a worked **concept** id, which is
    asserted to resolve. It does **not** name a journey; the journey half
    of §9.6.2's "a concept or journey" is carried by the instructions
    (``s0ma://docs/journeys``) and by the prompts (§9.6.5), both proved
    elsewhere in this file. That is written down here rather than papered
    over with a looser assertion.
    """

    def test_the_topic_query_says_what_it_answers(
        self, served: dict[str, Any]
    ) -> None:
        description = " ".join(str(served["tools"]["learn_s0ma"].description).split())

        assert "one question about s0ma" in description
        assert "Read-only, offline" in description

    def test_the_worked_id_in_its_description_resolves(
        self, served: dict[str, Any]
    ) -> None:
        """A description that taught a form nothing answers would teach a lie."""
        description = str(served["tools"]["learn_s0ma"].description)
        ids = re.findall(r'topic="([a-z0-9_]+:[^"]+)"', description)

        assert ids, f"{DOC_DISCOVERY_BROKEN}: the description works no id"
        for identifier in ids:
            _resolves(identifier)

    def test_every_tool_leads_with_a_written_first_sentence(
        self, served: dict[str, Any]
    ) -> None:
        """The pre-existing idiom the docs tool joined, held to.

        Most descriptions here open with the situation the tool is for —
        "When…", "After…", "Before…" — and that opening is what makes the
        served tool map skimmable. Three do not (the topic query and the
        two feedback tools open with what they do instead), so what is
        asserted is the part that is true of all of them: every tool leads
        with a written sentence rather than a label. A stricter pattern
        would be a rule this product does not actually follow.
        """
        for name, tool in sorted(served["tools"].items()):
            opening = " ".join(str(tool.description or "").split()).split(".")[0]
            assert len(opening) > 20, name
            assert " " in opening, name

    def test_the_journey_half_is_reachable_even_though_unnamed_here(
        self, server: Any
    ) -> None:
        """Stated as the fallback it is, and proved to work."""
        assert "s0ma://docs/journeys" in _docs_paragraph(server)
        _resolves("journey:first-project")


# ---------------------------------------------------------------------------
# 3 — high-traffic results
# ---------------------------------------------------------------------------


class TestHighTrafficResultsCarryAPointer:
    """§9.6.3: high-traffic results carry a bounded documentation pointer.

    The batch-01c M4 evidence is that rules riding a tool result landed
    36/36 bench sessions while the same content served as a resource
    landed 0/36 — and plan §1.2 fact 15's caveat is that arrival is
    necessary and not sufficient, so the line is bounded and its position
    is fixed. All three are asserted here from real results.
    """

    def test_project_status_carries_it(self, server: Any, tmp_path: Path) -> None:
        root = make_project(tmp_path / "proj", sources={})
        result = _call(server, "project_status", {"project_root": str(root)})

        assert tools._DOCS_RULE in result["rules"]

    def test_the_scaffolding_results_carry_it_too(
        self, server: Any, tmp_path: Path
    ) -> None:
        """Initialization and scaffolding, named by §9.6.3 beside status."""
        root = make_project(tmp_path / "proj", sources={})
        for name, arguments in (
            ("init_project", {"project_root": str(root)}),
            (
                "scaffold_module",
                {"project_root": str(root), "module_name": "probe"},
            ),
            ("describe_server", {}),
        ):
            result = _call(server, name, arguments)
            assert tools._DOCS_RULE in result["rules"], name

    def test_the_line_is_one_line_inside_b6s_budget(self) -> None:
        declared = _budget("project_status_footer")
        rule = tools._DOCS_RULE

        assert "\n" not in rule
        assert declared["max_lines"] == 1
        assert len(rule.encode("utf-8")) <= declared["budget_bytes"], (
            f"the footer is {len(rule.encode('utf-8'))} bytes against "
            f"{declared['budget_bytes']} ({declared['rule']})"
        )

    def test_it_is_never_the_longest_line_on_its_own_channel(
        self, server: Any, tmp_path: Path
    ) -> None:
        """B6's rule for this channel, checked against the real rules list."""
        root = make_project(tmp_path / "proj", sources={})
        rules = _call(server, "project_status", {"project_root": str(root)})["rules"]
        longest = max(len(line.encode("utf-8")) for line in rules)

        assert len(tools._DOCS_RULE.encode("utf-8")) <= longest

    def test_everything_the_line_names_is_served(
        self, server: Any, served: dict[str, Any]
    ) -> None:
        rule = tools._DOCS_RULE

        assert "learn_s0ma" in rule
        assert "learn_s0ma" in served["tools"]
        for uri in sorted(_addresses(rule)):
            assert uri in served["resources"], (
                f"{DOC_DISCOVERY_BROKEN}: the footer sends an agent to {uri} "
                f"and this server does not serve it"
            )

    def test_the_worked_id_the_line_carries_resolves(self) -> None:
        for identifier in re.findall(r'topic="([a-z0-9_]+:[^"]+)"', tools._DOCS_RULE):
            _resolves(identifier)


# ---------------------------------------------------------------------------
# 4 — failing diagnostics
# ---------------------------------------------------------------------------


class TestFailingDiagnosticsDeepLink:
    """§9.6.4: a failing diagnostic points at its exact remediation topic.

    The chain that exists today, proved end to end: a real failing
    ``check`` names its codes, gives a per-code anchor into the served
    error catalog, the anchor's code is really in that catalog's text, and
    the same code is a topic ``learn_s0ma`` answers with a remediation.

    **The observation this class records.** The per-code pointer is the
    pre-F7 catalog anchor (``s0ma://guide/errors#CODE``), not the F7 topic
    id (``diagnostic:CODE``). Both resolve, so the contract is met by the
    route an agent is actually given; the second route exists and is
    proved reachable here, but the failing result does not name it.
    Naming it is a ``tools.s0ma`` edit, which is F7's file rather than
    F9's, so this is recorded rather than changed.
    """

    def _failing(self, tmp_path: Path) -> Any:
        root = make_project(
            tmp_path / "broken",
            sources={"broken.s0ma": "module broken\n    layer: DOMAIN\n"},
        )
        return tools.check_tool(str(root))

    def test_a_failing_check_names_a_per_code_anchor(self, tmp_path: Path) -> None:
        result = self._failing(tmp_path)

        assert result["ok"] is False
        assert "error_help" in result, (
            f"{DOC_DISCOVERY_BROKEN}: a failing check points nowhere"
        )
        assert "s0ma://guide/errors#" in result["error_help"]

    def test_the_anchor_lands_on_the_code_in_the_served_catalog(
        self, server: Any, tmp_path: Path
    ) -> None:
        result = self._failing(tmp_path)
        anchors = re.findall(
            r"s0ma://guide/errors#([A-Z][A-Z0-9_]*)", result["error_help"]
        )
        catalog = _read(server, "s0ma://guide/errors")

        assert anchors, f"{DOC_DISCOVERY_BROKEN}: no code anchor was offered"
        for code in anchors:
            assert code in catalog, (
                f"{DOC_DISCOVERY_BROKEN}: the result anchors at {code} and the "
                f"served catalog does not carry it"
            )

    def test_the_same_code_is_a_topic_with_a_remediation(
        self, tmp_path: Path
    ) -> None:
        """The F7 route, reachable even though the result does not name it."""
        result = self._failing(tmp_path)
        codes = re.findall(
            r"s0ma://guide/errors#([A-Z][A-Z0-9_]*)", result["error_help"]
        )

        for code in codes:
            answered = tools.learn_s0ma_tool(f"diagnostic:{code}")
            assert answered["ok"] is True, code
            assert answered["topic_id"] == f"diagnostic:{code}"
            assert answered["read_more"]["page"].startswith(
                "docs/reference/diagnostics.md#"
            ), code

    def test_the_diagnostics_page_the_answer_names_is_committed(
        self, tmp_path: Path
    ) -> None:
        result = self._failing(tmp_path)
        code = re.findall(
            r"s0ma://guide/errors#([A-Z][A-Z0-9_]*)", result["error_help"]
        )[0]
        page = tools.learn_s0ma_tool(f"diagnostic:{code}")["read_more"]["page"]

        assert (REPO_ROOT / page.partition("#")[0]).is_file(), page


# ---------------------------------------------------------------------------
# 5 — journey prompts
# ---------------------------------------------------------------------------


class TestPromptsNameTheirDependencies:
    """§9.6.5: journey prompts name their dependencies structurally.

    F7 bound the prompt to a ``JourneyRecord`` id so the steps stopped
    being independently maintained prose. What F9 adds is the discovery
    half: the ladder the served prompt carries names surfaces this build
    addresses, so a step is followable rather than merely readable.
    """

    def _rendered(self, server: Any, name: str) -> str:
        result = _run(
            server.get_prompt(
                name, {"project_root": "/tmp/demo", "module_name": "Billing"}
            )
        )
        return "\n".join(str(message.content.text) for message in result.messages)

    def test_the_bound_prompt_carries_the_recorded_ladder(self, server: Any) -> None:
        journey = prompts.PROMPT_JOURNEYS["author_module"]

        assert prompts.journey_ladder(journey) in self._rendered(
            server, "author_module"
        )

    def test_every_journey_a_prompt_names_is_one_this_build_records(self) -> None:
        recorded = {journey.id for journey in resources.docs_bundle().journeys}

        for name, journey in sorted(prompts.PROMPT_JOURNEYS.items()):
            assert journey in recorded, (
                f"{DOC_DISCOVERY_BROKEN}: the {name} prompt is bound to "
                f"{journey}, which this build does not record"
            )
            _resolves(journey)

    def test_every_surface_the_ladder_walks_is_addressable(self) -> None:
        """Structural, not decorative: each step names something answerable."""
        index = resources.docs_topic_index()
        for journey in sorted(prompts.PROMPT_JOURNEYS.values()):
            steps = resources.docs_journey_steps(journey)
            assert steps, journey
            for step in steps:
                assert step["surface"] in index.views, (
                    f"{DOC_DISCOVERY_BROKEN}: {journey} walks "
                    f"{step['surface']}, which this build does not address"
                )

    def test_a_prompt_with_no_journey_says_why_at_length(self) -> None:
        for name, reason in sorted(prompts.PROMPT_WITHOUT_JOURNEY.items()):
            assert len(reason) > 80, name


# ---------------------------------------------------------------------------
# 6 — the generated AGENTS.md
# ---------------------------------------------------------------------------


class TestGeneratedAgentsMd:
    """§9.6.6: generated instructions establish the query and the fallbacks.

    Read from this side too, and deliberately: the file is written by the
    dsl's scaffolder and read by whatever client attaches to *this*
    server, so the guarantee that matters is that everything it tells an
    agent to call is something this server really serves.
    """

    @pytest.fixture(scope="class")
    def agents_md(self, tmp_path_factory: pytest.TempPathFactory) -> str:
        from s0ma_dsl.cli.main import S0maCLI

        target = tmp_path_factory.mktemp("scaffolded") / "app"
        assert S0maCLI().run(["new", "project", str(target), "--quiet"]) == 0
        return (target / "AGENTS.md").read_text(encoding="utf-8")

    def _docs_bullet(self, agents_md: str) -> str:
        bullets = re.findall(r"(?ms)^- .*?(?=\n(?:- |\n|#)|\Z)", agents_md)
        found = [item for item in bullets if "Ask s0ma about s0ma" in item]
        assert len(found) == 1
        return found[0]

    def test_it_establishes_the_topic_query(
        self, agents_md: str, served: dict[str, Any]
    ) -> None:
        bullet = self._docs_bullet(agents_md)

        assert "learn_s0ma(topic=...)" in bullet
        assert "learn_s0ma" in served["tools"]

    def test_it_establishes_the_local_cli_fallback(self, agents_md: str) -> None:
        """The "local Markdown/CLI fallbacks" half of §9.6.6, added at F9."""
        bullet = self._docs_bullet(agents_md)

        assert "s0ma docs show" in bullet

    def test_every_address_it_names_is_served_here(
        self, agents_md: str, served: dict[str, Any]
    ) -> None:
        for uri in sorted(_addresses(self._docs_bullet(agents_md))):
            assert uri in served["resources"], (
                f"{DOC_DISCOVERY_BROKEN}: the generated AGENTS.md sends an "
                f"agent to {uri} and this server does not serve it"
            )

    def test_the_bullet_stays_inside_b6s_budget(self, agents_md: str) -> None:
        declared = _budget("agents_snippet")
        size = len(self._docs_bullet(agents_md).encode("utf-8"))

        assert size <= declared["budget_bytes"], (
            f"the documentation bullet is {size} bytes against "
            f"{declared['budget_bytes']} ({declared['rule']})"
        )


# ---------------------------------------------------------------------------
# 7 — the index describes itself
# ---------------------------------------------------------------------------


class TestTheIndexDescribesItself:
    """§9.6.7: the index names its categories, ids, aliases and retrieval.

    The alias sentence is new at F9 and it is only honest because the
    aliases are: before this milestone the alternate terms never left the
    checkout, so an index served from a wheel that claimed earlier names
    resolved would have been claiming something false on this channel.
    """

    def test_it_names_every_category_with_a_count(self, server: Any) -> None:
        index = _read(server, "s0ma://docs/index")
        prefixes = {
            identifier.partition(":")[0]
            for identifier in resources.docs_topic_index().ids()
        }

        for prefix in sorted(prefixes):
            assert re.search(rf"^- {re.escape(prefix)}: \d+ topics", index, re.M), (
                f"{DOC_DISCOVERY_BROKEN}: the index describes no {prefix} "
                f"category and this build addresses {prefix} topics"
            )

    def test_every_worked_id_it_offers_resolves(self, server: Any) -> None:
        index = _read(server, "s0ma://docs/index")
        offered = re.findall(r"as in ([a-z0-9_]+:\S+?), which", index)

        assert len(offered) == len(
            {identifier.partition(":")[0] for identifier in offered}
        ), "the index works two ids for one category"
        for identifier in offered:
            _resolves(identifier)

    def test_it_names_the_retrieval_command(self, server: Any) -> None:
        index = _read(server, "s0ma://docs/index")

        assert "learn_s0ma" in index
        assert 'learn_s0ma(topic="' in index

    def test_it_says_that_earlier_names_answer(self, server: Any) -> None:
        index = _read(server, "s0ma://docs/index")
        entries = resources.docs_bundle().aliases

        assert entries, "this build declares no alternate terms"
        assert f"{len(entries)} earlier names still answer" in index

    def test_the_alias_it_works_really_answers(self, server: Any) -> None:
        """The claim the index makes, tested as a call rather than read."""
        index = _read(server, "s0ma://docs/index")
        worked = re.findall(
            r'learn_s0ma\(topic="([a-z0-9_]+:[^"]+)"\) answers about (\S+)', index
        )

        assert worked, f"{DOC_DISCOVERY_BROKEN}: the index works no alias"
        for old, current in worked:
            answered = _call(server, "learn_s0ma", {"topic": old})
            assert answered["ok"] is True, old
            assert answered["topic_id"] == current.rstrip(".")

    def test_it_stays_inside_the_context_economy_ceiling(self, server: Any) -> None:
        """The survival card's 4 KB ceiling, F7's declared number."""
        assert len(_read(server, "s0ma://docs/index").encode("utf-8")) <= 4_096

    def test_it_only_points_at_things_that_answer(
        self, server: Any, served: dict[str, Any]
    ) -> None:
        index = _read(server, "s0ma://docs/index")
        core_family = {
            "s0ma://docs/user-guide",
            "s0ma://docs/compliance-rules",
            "s0ma://docs/architecture",
        }

        for uri in sorted(_addresses(index)):
            assert uri in served["resources"] or uri in core_family, (
                f"{DOC_DISCOVERY_BROKEN}: the index names {uri} and nothing "
                f"serves it"
            )


# ---------------------------------------------------------------------------
# T3 — the agent budgets, from the declarations that own them
# ---------------------------------------------------------------------------


class TestAgentBudgets:
    """Every first-pointed agent artifact, against its declared ceiling."""

    def test_every_topic_this_build_serves_fits_the_answer_budget(self) -> None:
        """750 bytes, over all 690 topics — the model's own constant."""
        from s0ma_dsl.docs_model.render_agent import AGENT_BYTE_BUDGET

        index = resources.docs_topic_index()
        oversized: list[tuple[str, int]] = []
        for identifier in index.ids():
            answered = tools.learn_s0ma_tool(identifier)
            assert answered["answer_budget_bytes"] == AGENT_BYTE_BUDGET, identifier
            if answered["answer_bytes"] > AGENT_BYTE_BUDGET:
                oversized.append((identifier, answered["answer_bytes"]))
                assert answered["budget_findings"], identifier
        assert oversized == []

    def test_the_alternate_terms_answer_inside_the_same_budget(self) -> None:
        """An alias is a way of asking, not a different answer.

        F9 made the aliases reachable on this channel; if answering by an
        earlier name produced a different or larger answer, the two ways
        of asking would be two topics wearing one id.
        """
        from s0ma_dsl.docs_model.render_agent import AGENT_BYTE_BUDGET

        for entry in resources.docs_bundle().aliases:
            by_alias = tools.learn_s0ma_tool(entry.id)
            by_id = tools.learn_s0ma_tool(entry.canonical)

            assert by_alias["ok"] is True, entry.id
            assert by_alias["topic_id"] == entry.canonical
            assert by_alias["answer"] == by_id["answer"]
            assert by_alias["answer_bytes"] <= AGENT_BYTE_BUDGET

    def test_the_three_agent_budgets_are_the_three_b6_declared(self) -> None:
        document = json.loads(B6_BUDGETS.read_text(encoding="utf-8"))
        declared = {entry["artifact"] for entry in document["budgets"]}

        assert {
            "server_instructions",
            "project_status_footer",
            "agents_snippet",
        } <= declared


# ---------------------------------------------------------------------------
# T4 — channel parity
# ---------------------------------------------------------------------------


def _terminal_facts(identifier: str) -> dict[str, Any]:
    """One topic's facts as the terminal channel carries them.

    Read through ``s0ma docs show --format json``'s own renderer rather
    than through the CLI process, so the comparison is against the same
    records the human surface prints and not against a re-parse of a
    terminal frame. The extractor is the product's, not this file's — B5
    finding 2: the renderer registry is load-bearing for a gate.
    """
    from s0ma_dsl.cli.docs_commands import topic_index
    from s0ma_dsl.docs_model import render_json
    from s0ma_dsl.docs_model.bundle import load_snapshot
    from s0ma_dsl.docs_model.resolve import canonical_fact

    snapshot = load_snapshot(REPO_ROOT)
    view = topic_index(snapshot).view(identifier)
    spec = render_json.spec_for(view.group)
    artifact = render_json.render_json(view)
    return {
        name: canonical_fact(name, value)
        for name, value in render_json.extract(artifact, spec).items()
    }


def _tool_facts(identifier: str) -> dict[str, Any]:
    """The same topic's facts as ``learn_s0ma`` carries them."""
    from s0ma_dsl.docs_model import render_agent
    from s0ma_dsl.docs_model.resolve import canonical_fact

    index = resources.docs_topic_index()
    view = index.view(identifier)
    spec = render_agent.spec_for(view.group)
    artifact = tools.learn_s0ma_tool(identifier)["answer"]
    return {
        name: canonical_fact(name, value)
        for name, value in render_agent.extract(artifact, spec).items()
    }


class TestTerminalAndToolParity:
    """§9.7 over the two live read surfaces: ``s0ma docs show`` ≡ ``learn_s0ma``.

    The residue half of B5, now across a package boundary and across two
    copies of the snapshot — the checkout's and the one packaged inside
    this wheel. The agent channel is allowed to omit; it is not allowed to
    differ. So every fact it carries must be the terminal's fact word for
    word, and the identity core must be on both.
    """

    def test_the_identity_core_is_on_both_and_is_the_same(self) -> None:
        from s0ma_dsl.docs_model.resolve import IDENTITY_FACTS

        for identifier in PARITY_TOPICS:
            terminal = _terminal_facts(identifier)
            tool = _tool_facts(identifier)
            for fact in IDENTITY_FACTS:
                assert fact in terminal, f"{identifier}: terminal drops {fact}"
                assert fact in tool, f"{identifier}: the tool drops {fact}"
                assert terminal[fact] == tool[fact], (
                    f"{DOC_CHANNEL_DIVERGENCE}: {fact} of {identifier} is "
                    f"{tool[fact]!r} to the tool and {terminal[fact]!r} in the "
                    f"terminal"
                )

    def test_every_fact_the_tool_carries_is_verbatim_or_absent(self) -> None:
        for identifier in PARITY_TOPICS:
            terminal = _terminal_facts(identifier)
            tool = _tool_facts(identifier)
            for fact, value in sorted(tool.items()):
                assert fact in terminal, (
                    f"{DOC_CHANNEL_DIVERGENCE}: the tool carries {fact} of "
                    f"{identifier} and the terminal has no such fact"
                )
                assert value == terminal[fact], (
                    f"{DOC_CHANNEL_DIVERGENCE}: {fact} of {identifier} is "
                    f"{value!r} to the tool and {terminal[fact]!r} in the "
                    f"terminal"
                )

    def test_the_omissions_are_omissions_and_not_rewrites(self) -> None:
        """The bounded channel earns its budget by dropping, never by paraphrase."""
        for identifier in PARITY_TOPICS:
            dropped = set(_terminal_facts(identifier)) - set(_tool_facts(identifier))
            assert dropped, (
                f"{identifier}: the agent channel carries every fact, so it is "
                f"not the bounded channel this comparison assumes"
            )


class TestFourChannelIdentity:
    """§9.7's four addresses of one topic, carrying one build identity.

    ``s0ma docs show T`` · ``learn_s0ma(topic=T)`` · ``s0ma://docs/…`` ·
    the committed Markdown. Two of them read the checkout's snapshot and
    two read the copy packaged in this wheel, which is exactly why the
    sweep is worth running: a stale mirror shows up here as two builds
    claiming to be one.

    The sweep runs on :data:`SWEEP_TOPICS`, all three of them concepts,
    and the reason is a fact about the corpus rather than a convenience —
    see the last test in this class.
    """

    def test_all_four_name_one_release_and_one_snapshot(
        self, server: Any
    ) -> None:
        from s0ma_dsl.cli.docs_commands import (
            identity_line,
            render_terminal,
            topic_index,
        )
        from s0ma_dsl.docs_model.bundle import load_snapshot
        from s0ma_dsl.docs_model.learn_pages import page_path

        snapshot = load_snapshot(REPO_ROOT)
        identity = resources.docs_snapshot_identity()
        index = topic_index(snapshot)

        assert snapshot.release_version() == identity["release_version"]
        assert snapshot.snapshot_hash() == identity["snapshot_hash"]

        for identifier in SWEEP_TOPICS:
            answer = tools.learn_s0ma_tool(identifier)
            channels = {
                "terminal": render_terminal(snapshot, index.view(identifier)),
                "tool": answer["answer"],
                "resource": _read(server, answer["read_more"]["resource"]),
                "page": (REPO_ROOT / "docs" / page_path(identifier)).read_text(
                    encoding="utf-8"
                ),
            }

            assert len(channels) == 4, identifier
            for name, text in sorted(channels.items()):
                assert identity["release_version"] in text, f"{identifier}/{name}"
                assert identity["snapshot_hash"] in text, f"{identifier}/{name}"

        assert identity["snapshot_hash"] in identity_line(snapshot)

    def test_the_committed_page_the_tool_names_exists(self) -> None:
        for identifier in (*SWEEP_TOPICS, *PARITY_TOPICS):
            page = tools.learn_s0ma_tool(identifier)["read_more"]["page"]
            assert (REPO_ROOT / page.partition("#")[0]).is_file(), identifier

    def test_a_journeys_markdown_is_a_pointer_not_a_projection(self) -> None:
        """Why the sweep is three concepts, recorded rather than glossed.

        A concept is projected onto a generated page of its own and that
        page is stamped with the build that wrote it. A journey is not: no
        generated page projects a ``JourneyRecord``, and what
        ``read_more.page`` names for a journey is the *authored guide the
        catalog says covers it* — a document about the topic rather than a
        rendering of the record, and so not identity-stamped.

        That is a real §9.7 observation and it is left as one. Stamping
        authored guides would be a corpus-wide change to authored
        documents, which is Phase G's territory; asserting the identity on
        a page that has never carried it would only make this suite
        wrong.
        """
        page = tools.learn_s0ma_tool("journey:first-project")["read_more"]["page"]
        body = (REPO_ROOT / page.partition("#")[0]).read_text(encoding="utf-8")
        identity = resources.docs_snapshot_identity()

        assert (REPO_ROOT / page.partition("#")[0]).is_file()
        assert identity["snapshot_hash"] not in body, (
            f"{page} now carries the snapshot identity. If authored guides "
            f"became identity-stamped, add journeys to SWEEP_TOPICS and "
            f"delete this pin."
        )
        # The three channels a journey does have all agree, which is what
        # the residue comparison above already proves for its facts.
        assert tools.learn_s0ma_tool("journey:first-project")["ok"] is True

    def test_the_packaged_mirror_is_the_committed_snapshot(self) -> None:
        """A parity sweep over a stale mirror would prove nothing."""
        packaged = resources.load_docs_model()
        committed = (
            REPO_ROOT / "docs" / "_generated" / "s0ma-docs-model.json"
        ).read_text(encoding="utf-8")

        assert packaged == committed, (
            "s0ma_mcp/_docs/s0ma-docs-model.json has drifted from "
            "docs/_generated/s0ma-docs-model.json — refresh the mirror"
        )


# ---------------------------------------------------------------------------
# The contract is complete
# ---------------------------------------------------------------------------


def test_every_entry_point_of_the_contract_has_a_proof() -> None:
    here = globals()
    missing = [
        f"{route} -> {name}"
        for route, name in AGENT_ENTRY_POINTS.items()
        if name not in here
    ]

    assert missing == [], f"entry points with no proof: {missing}"
    assert len(AGENT_ENTRY_POINTS) == 7, "architecture §9.6 lists seven"


def test_this_suite_names_the_milestone_it_belongs_to() -> None:
    from pathlib import Path

    text = Path(__file__).read_text(encoding="utf-8")

    assert "Milestone F9" in text
    assert "§9.6" in text
