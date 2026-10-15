"""F7: the agent read surface — ``learn_s0ma``, ``s0ma://docs/*``, discovery.

(Named for the *agent* surface on purpose: F6's ``s0ma docs`` suite is the
human half and lives in the dsl package under its own name. Two files
with one basename in one collection is an import mismatch waiting to
happen.)

Four things are proved here, and they are four because the plan's §1.2
fact 15 says arrival is *necessary and not sufficient*: content that
reaches an agent still has to be small enough to read and has to point
somewhere that exists.

* **discovery** — the server's instructions, the rules every tool result
  carries, and the docs index all name the topic query, and everything
  any of them names is really served. A pointer at a surface nobody
  serves is the ``DOC_DISCOVERY_BROKEN`` shape, so it is asserted from
  the live server rather than from a list written here;
* **budgets** — the instructions paragraph (527 bytes), the one-line
  footer (319 bytes), the index resource (4 KB, the survival card's
  ceiling) and every topic answer (750 bytes, the model's own
  ``AGENT_BYTE_BUDGET``). Every one is measured against the constant
  that declares it, never against a copy of the number;
* **compatibility** — the twelve resources and fourteen tools that were
  served before F7 are all still served, byte-for-byte the same
  descriptions. F7 adds; it changes nothing a client already holds;
* **the packaged snapshot** — the copy under ``s0ma_mcp/_docs/`` is
  byte-identical to the in-repo snapshot it mirrors, the same drift gate
  the nine guide documents have had since M2. When the documentation
  application recomposes, this is the test that says "refresh the copy".

Everything runs in-process against ``create_server()``. A resource that
exists and a resource that *answers* are different facts, and only the
second one is worth anything to an agent.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("mcp", reason="MCP SDK not installed")

from conftest import REPO_ROOT, mainline_rules, make_project

from s0ma_mcp import create_server, resources, tools

#: The docs paragraph's budget (B6). The instructions are one string, so
#: the paragraph is located by its opening and closing sentences rather
#: than stored twice.
INSTRUCTIONS_DOCS_BUDGET = 527
INSTRUCTIONS_DOCS_OPENING = "This server documents itself:"
INSTRUCTIONS_DOCS_CLOSING = "Ask rather than guess what a s0ma word means. "

#: The footer line's budget (B6): one line, riding every rules-bearing
#: tool result.
DOCS_RULE_BUDGET = 319

#: The index is the first thing an agent reads about s0ma itself, so it
#: is held to the survival card's context-economy ceiling.
DOCS_INDEX_BUDGET = 4_096

#: What the server served before F7 — every one of which must still be
#: served, with the same description. Zero client breakage, asserted
#: rather than asserted-about.
PRE_F7_RESOURCES = {
    "s0ma://guide/errors",
    "s0ma://guide/getting-started",
    "s0ma://guide/patterns",
    "s0ma://guide/quick-reference",
    "s0ma://guide/self-prompting",
    "s0ma://guide/survival-card",
    "s0ma://guide/system-prompt",
    "s0ma://meta/changelog",
    "s0ma://meta/version",
    "s0ma://project/runbook",
    "s0ma://self/model",
    "s0ma://spec/current",
}

#: The three F7 adds. Deliberately NOT one per topic: 37 concepts and 6
#: journeys as concrete resources would quadruple every client's resource
#: listing to say what one bounded tool call already says, and each would
#: need its own registered component — a hand-kept copy of the snapshot's
#: own id list, which is the exact defect this initiative removes.
DOCS_RESOURCES = {
    "s0ma://docs/index",
    "s0ma://docs/concepts",
    "s0ma://docs/journeys",
}

#: Core's runtime server serves these three, and this server does not.
#: Same scheme, different server, no collision at the protocol level —
#: and the index says so out loud rather than leaving a reader to find
#: out by asking.
CORE_DOCS_RESOURCES = {
    "s0ma://docs/user-guide",
    "s0ma://docs/compliance-rules",
    "s0ma://docs/architecture",
}


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def server() -> Any:
    return create_server()


@pytest.fixture(scope="module")
def served(server: Any) -> dict[str, Any]:
    """Everything the server lists, by kind — read once."""
    return {
        "tools": {str(t.name): t for t in _run(server.list_tools())},
        "resources": {str(r.uri): r for r in _run(server.list_resources())},
        "prompts": {str(p.name): p for p in _run(server.list_prompts())},
    }


def _read(server: Any, uri: str) -> str:
    contents = list(_run(server.read_resource(uri)))
    assert len(contents) == 1, uri
    return str(contents[0].content)


def _docs_paragraph(server: Any) -> str:
    instructions = server.instructions or ""
    assert INSTRUCTIONS_DOCS_OPENING in instructions
    start = instructions.index(INSTRUCTIONS_DOCS_OPENING)
    end = instructions.index(INSTRUCTIONS_DOCS_CLOSING) + len(
        INSTRUCTIONS_DOCS_CLOSING
    )
    return instructions[start:end]


# ---------------------------------------------------------------------------
# T3 — discovery: three channels name the surface, and it is really there
# ---------------------------------------------------------------------------


class TestDiscovery:
    """Every route to the documentation ends somewhere that answers."""

    def test_instructions_name_the_topic_query_and_the_index(
        self, server: Any, served: dict[str, Any]
    ) -> None:
        paragraph = _docs_paragraph(server)

        assert "learn_s0ma(topic)" in paragraph
        for uri in DOCS_RESOURCES:
            assert uri in paragraph, uri
        # DOC_DISCOVERY_BROKEN: everything the paragraph names is served.
        assert "learn_s0ma" in served["tools"]
        assert set(served["resources"]) >= DOCS_RESOURCES

    def test_the_rules_footer_rides_every_rules_bearing_result(
        self, tmp_path: Path
    ) -> None:
        """The B6 seam: one line, on the channel that lands 36/36.

        All six call sites take it from ``_survival_rules``, so proving
        the four reachable ones plus the helper's own output proves the
        seam rather than each site's copy of it.
        """
        root = make_project(tmp_path / "proj", sources={})
        carriers = [
            tools.describe_server_tool(),
            tools.project_status_tool(str(root)),
            tools.init_project_tool(str(root)),
            tools.scaffold_module_tool(str(root), "probe"),
        ]
        for result in carriers:
            assert tools._DOCS_RULE in result["rules"]

    def test_the_footer_is_one_line_naming_the_tool_and_the_index(self) -> None:
        rule = tools._DOCS_RULE

        assert "\n" not in rule
        assert "learn_s0ma" in rule
        assert "s0ma://docs/index" in rule

    def test_the_footer_sits_above_the_measured_narration_line(
        self, tmp_path: Path
    ) -> None:
        """The M8 bench measured the narration line LAST; it stays last."""
        from test_narration_rule import NARRATION_RULE, arm

        root = make_project(tmp_path / "proj", sources={})
        arm(root)
        rules = tools.project_status_tool(str(root))["rules"]

        assert rules[-1] == NARRATION_RULE
        assert rules[-2] == tools._DOCS_RULE

    def test_the_index_only_points_at_things_that_answer(
        self, server: Any, served: dict[str, Any]
    ) -> None:
        """DOC_DISCOVERY_BROKEN, over the index's own text.

        Every ``s0ma://`` address the index names is either served by
        this server or explicitly named as another server's — and every
        tool it names is served here.
        """
        index = _read(server, "s0ma://docs/index")

        named = {
            word.strip(".,;:()`")
            for word in index.split()
            if word.startswith("s0ma://")
        }
        assert named, "the index names no addresses at all"
        for uri in named:
            assert uri in served["resources"] or uri in CORE_DOCS_RESOURCES, uri
        assert "learn_s0ma" in index
        assert "learn_s0ma" in served["tools"]

    def test_the_index_says_which_server_the_other_docs_family_is(
        self, server: Any, served: dict[str, Any]
    ) -> None:
        """Core's three are not aliased here; they are explained here.

        The two families share a scheme and never collide: a client is
        talking to one server or the other, and the index removes the
        only ambiguity that leaves — a reader who has seen both.
        """
        index = _read(server, "s0ma://docs/index")

        for uri in CORE_DOCS_RESOURCES:
            assert uri in index, uri
            assert uri not in served["resources"], uri
        assert "different server" in index


# ---------------------------------------------------------------------------
# T1 — the topic query
# ---------------------------------------------------------------------------


class TestLearnS0ma:
    """One question, one bounded answer, through the real MCP boundary."""

    def _call(self, server: Any, topic: str) -> dict[str, Any]:
        outcome = _run(server.call_tool("learn_s0ma", {"topic": topic}))
        structured = outcome[1] if isinstance(outcome, tuple) else outcome
        assert isinstance(structured, dict)
        return structured

    def test_an_exact_id_resolves_through_the_server(self, server: Any) -> None:
        """The B6 idiom: a real call, not a call to the body behind it."""
        result = self._call(server, "concept:ganglion")

        assert result["ok"] is True
        assert result["topic_id"] == "concept:ganglion"
        assert result["state"] == "resolved"
        assert "watcher" in result["answer"]
        assert result["read_more"]["page"] == "docs/learn/ganglion.md"
        assert result["read_more"]["resource"] == "s0ma://docs/concepts"

    def test_the_answer_carries_its_own_build_identity(self, server: Any) -> None:
        """B5's residue rule: an answer says which build it came from."""
        result = self._call(server, "concept:ganglion")
        identity = resources.docs_snapshot_identity()

        assert result["release_version"] == identity["release_version"]
        assert result["snapshot_hash"] == identity["snapshot_hash"]
        # In the text too, so a pasted answer keeps saying it.
        assert f"Release: {identity['release_version']}" in result["answer"]
        assert f"Snapshot: {identity['snapshot_hash']}" in result["answer"]

    def test_it_is_deterministic_and_reaches_no_network(
        self, server: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Offline by construction: a socket in the tool path fails here."""
        import socket

        # Refuse a socket that reaches *another host*, not one the process
        # opens to talk to itself. Windows' ProactorEventLoop builds its
        # asyncio self-pipe from a loopback socket pair, so a bare "any
        # connect fails" guard reports a network reach that never happened —
        # the same distinction scripts/check_docs_application.py draws.
        _loopback = frozenset({"", "localhost", "127.0.0.1", "::1", "0.0.0.0", "::"})
        real_connect = socket.socket.connect
        real_create_connection = socket.create_connection

        def _is_local(address: Any) -> bool:
            if isinstance(address, str | bytes):
                return True  # an AF_UNIX path never leaves the machine
            if isinstance(address, tuple) and address:
                host = address[0]
                if isinstance(host, bytes):
                    host = host.decode("utf-8", "replace")
                return str(host) in _loopback
            return False

        def _refuse(self: Any, address: Any, *args: Any, **kwargs: Any) -> Any:
            if _is_local(address):
                return real_connect(self, address, *args, **kwargs)
            raise AssertionError("learn_s0ma opened a socket")

        def _refuse_create(address: Any, *args: Any, **kwargs: Any) -> Any:
            if _is_local(address):
                return real_create_connection(address, *args, **kwargs)
            raise AssertionError("learn_s0ma opened a socket")

        monkeypatch.setattr(socket.socket, "connect", _refuse)
        monkeypatch.setattr(socket, "create_connection", _refuse_create)

        first = self._call(server, "ganglion")
        second = self._call(server, "ganglion")
        assert first == second

    def test_every_topic_this_build_addresses_fits_the_channel(self) -> None:
        """The 750-byte budget, over all 683 topics rather than one.

        Asserted against the model's own constant: a budget written down
        twice is a budget that drifts.
        """
        from s0ma_dsl.docs_model.render_agent import AGENT_BYTE_BUDGET

        index = resources.docs_topic_index()
        oversized: list[tuple[str, int]] = []
        for identifier in index.ids():
            answered = tools.learn_s0ma_tool(identifier)
            assert answered["ok"] is True, identifier
            assert answered["answer_budget_bytes"] == AGENT_BYTE_BUDGET
            if answered["answer_bytes"] > AGENT_BYTE_BUDGET:
                oversized.append((identifier, answered["answer_bytes"]))
                assert answered["budget_findings"], identifier
        assert not oversized, oversized

    def test_every_answer_points_at_a_page_that_exists(self) -> None:
        """A pointer to a file nobody committed is worse than none."""
        index = resources.docs_topic_index()
        for identifier in index.ids():
            page = tools.learn_s0ma_tool(identifier)["read_more"]["page"]
            assert (REPO_ROOT / page.partition("#")[0]).is_file(), identifier

    def test_a_bare_term_and_its_id_are_one_question(self, server: Any) -> None:
        assert self._call(server, "ganglion")["answer"] == (
            self._call(server, "concept:ganglion")["answer"]
        )

    def test_a_miss_returns_the_nearest_forms_not_a_guess(
        self, server: Any
    ) -> None:
        result = self._call(server, "gangleon")

        assert result["ok"] is False
        assert result["state"] == "unresolved"
        assert result["code"] == "DOC_TOPIC_UNRESOLVED"
        assert result["nearest"]
        assert result["next_actions"][0]["arguments"]["topic"] == (
            result["nearest"][0]
        )
        # A miss still says which build could not place the question.
        assert result["snapshot_hash"].startswith("sha256:")

    def test_related_topics_are_all_addressable(self, server: Any) -> None:
        """The next-step pointers are topics, not decoration."""
        index = resources.docs_topic_index()
        result = self._call(server, "journey:mcp-authoring-loop")

        assert result["related_topics"]
        for identifier in result["related_topics"]:
            assert identifier in index.views, identifier

    def test_it_is_annotated_honestly(self, served: dict[str, Any]) -> None:
        annotations = served["tools"]["learn_s0ma"].annotations

        assert annotations is not None
        assert annotations.readOnlyHint is True
        assert annotations.idempotentHint is True
        assert annotations.openWorldHint is False


# ---------------------------------------------------------------------------
# T2 — the resource family
# ---------------------------------------------------------------------------


class TestDocsResources:
    """Three resources, each answering from the packaged snapshot."""

    def test_the_family_is_exactly_three(self, served: dict[str, Any]) -> None:
        assert {
            uri for uri in served["resources"] if uri.startswith("s0ma://docs/")
        } == DOCS_RESOURCES

    def test_each_one_answers(self, server: Any) -> None:
        for uri in sorted(DOCS_RESOURCES):
            assert len(_read(server, uri)) > 500, uri

    def test_the_index_stays_inside_the_context_economy_ceiling(
        self, server: Any
    ) -> None:
        index = _read(server, "s0ma://docs/index")

        assert len(index.encode("utf-8")) <= DOCS_INDEX_BUDGET

    def test_the_index_grows_by_category_and_not_by_topic(
        self, server: Any
    ) -> None:
        """The bound is structural, not a number somebody watches.

        One line per id prefix, so a build that grew a hundred
        diagnostics grows this page by nothing at all.
        """
        index = _read(server, "s0ma://docs/index")
        prefixes = {
            identifier.partition(":")[0]
            for identifier in resources.docs_topic_index().ids()
        }
        bullets = [line for line in index.splitlines() if line.startswith("- ")]

        assert len(bullets) == len(prefixes) + 2  # + the two other resources
        for prefix in prefixes:
            assert f"- {prefix}: " in index, prefix

    def test_the_concepts_resource_carries_every_concept_verbatim(
        self, server: Any
    ) -> None:
        text = _read(server, "s0ma://docs/concepts")
        concepts = resources.docs_bundle().concepts

        assert len(concepts) == 39
        for record in concepts:
            assert record.summary in text, record.id

    def test_the_journeys_resource_walks_the_recorded_steps(
        self, server: Any
    ) -> None:
        text = _read(server, "s0ma://docs/journeys")
        for journey in resources.docs_bundle().journeys:
            position = -1
            for step in journey.steps:
                found = text.index(step.purpose)
                assert found > position, f"{journey.id}: steps out of order"
                position = found

    def test_the_family_is_served_as_markdown(
        self, served: dict[str, Any]
    ) -> None:
        for uri in sorted(DOCS_RESOURCES):
            assert served["resources"][uri].mimeType == "text/markdown", uri


# ---------------------------------------------------------------------------
# Compatibility — F7 adds and changes nothing a client already held
# ---------------------------------------------------------------------------


class TestNoClientBreakage:
    """The pre-F7 surface is untouched, proved against the served server."""

    def test_every_pre_f7_resource_is_still_served_and_still_answers(
        self, server: Any, served: dict[str, Any]
    ) -> None:
        assert set(served["resources"]) >= PRE_F7_RESOURCES
        for uri in sorted(PRE_F7_RESOURCES):
            assert _read(server, uri), uri

    def test_the_packaged_guides_are_untouched(self, server: Any) -> None:
        """The mirrors F7 did not change, still byte-identical.

        Every packaged document, whatever the count of them is today: the
        set is read from ``GUIDE_DOCS`` rather than written here.
        """
        for doc in resources.GUIDE_DOCS.values():
            source = REPO_ROOT / doc.source
            assert source.is_file(), doc.source
            assert resources.load_doc(doc.key) == source.read_text(
                encoding="utf-8"
            ), doc.key
            assert _read(server, doc.uri) == resources.load_doc(doc.key), doc.key

    def test_the_docs_family_does_not_shadow_any_guide_address(
        self, served: dict[str, Any]
    ) -> None:
        assert not (DOCS_RESOURCES & PRE_F7_RESOURCES)
        assert not (DOCS_RESOURCES & CORE_DOCS_RESOURCES)

    def test_the_rules_are_the_canonical_block_plus_one_line(self) -> None:
        """F7 spent exactly one line of the rules budget (NFR-5)."""
        assert mainline_rules() == [*tools._SURVIVAL_RULES, tools._DOCS_RULE]
        assert tools.describe_server_tool()["rules"] == mainline_rules()


# ---------------------------------------------------------------------------
# Budgets — each measured against the constant that declares it
# ---------------------------------------------------------------------------


class TestBudgets:
    def test_the_instructions_paragraph_fits(self, server: Any) -> None:
        paragraph = _docs_paragraph(server)

        assert len(paragraph.encode("utf-8")) <= INSTRUCTIONS_DOCS_BUDGET

    def test_the_footer_line_fits(self) -> None:
        assert len(tools._DOCS_RULE.encode("utf-8")) <= DOCS_RULE_BUDGET

    def test_the_instructions_say_the_docs_paragraph_once(
        self, server: Any
    ) -> None:
        """NFR-5: served text repeated is served cost repeated."""
        instructions = server.instructions or ""

        assert instructions.count(INSTRUCTIONS_DOCS_OPENING) == 1
        # Twice, and both earn their place: once in the paragraph that
        # says what it answers, and once in the live situation-to-tool
        # map, which is the machine-readable half of the same fact.
        assert instructions.count("learn_s0ma") == 2
        assert "look up a s0ma concept, command or diagnostic" in instructions


# ---------------------------------------------------------------------------
# The packaged snapshot — the same drift gate the packaged guides have
# ---------------------------------------------------------------------------


class TestDocsModelMirrorDrift:
    """``s0ma_mcp/_docs/s0ma-docs-model.json`` mirrors the built snapshot.

    If this fails, the documentation application recomposed and the
    packaged copy is behind: refresh it with

        cp docs/_generated/s0ma-docs-model.json \\
           packages/s0ma-mcp/src/s0ma_mcp/_docs/s0ma-docs-model.json

    and commit the two together, exactly as the packaged guide documents are
    refreshed. The copy exists because a wheel install has no checkout to
    read: without it the authoring server could answer documentation
    questions only from a repository, which is the degradation F8 is
    removing from core for the same reason.
    """

    @pytest.fixture(autouse=True)
    def _require_repo_checkout(self) -> None:
        if not (REPO_ROOT / resources.DOCS_MODEL_SOURCE).is_file():
            pytest.skip("documentation snapshot not available (not a checkout)")

    def test_the_packaged_copy_matches_the_built_snapshot(self) -> None:
        source = REPO_ROOT / resources.DOCS_MODEL_SOURCE
        assert resources.load_docs_model() == source.read_text(
            encoding="utf-8"
        ), (
            f"s0ma_mcp/_docs/{resources.DOCS_MODEL_FILENAME} has drifted from "
            f"{resources.DOCS_MODEL_SOURCE}; refresh the committed copy (see "
            "this test's docstring)"
        )

    def test_the_packaged_copy_is_the_schema_this_build_reads(self) -> None:
        """The identity a served blurb quotes is the packaged stamp's.

        Three keys since H2, and the third is the one a reader meets:
        ``release_version`` is the bare number a caller compares and
        ``version_line`` is the written form, which carries the channel
        label whenever this build is not a released one. The equality is
        exact, so a fourth key — or a blurb quietly served the bare
        version again — is a failure here rather than a wrong sentence in
        production.
        """
        stamp = json.loads(resources.load_docs_model())["stamp"]

        assert stamp["schema"] == "s0ma-docs-model@1"
        channel = stamp["build_channel"]
        labelled = (
            stamp["release_version"]
            if channel == "release"
            else f"{stamp['release_version']} ({channel})"
        )
        assert resources.docs_snapshot_identity() == {
            "release_version": stamp["release_version"],
            "version_line": labelled,
            "snapshot_hash": stamp["snapshot_hash"],
        }

    def test_the_mirror_is_not_a_guide_document(self) -> None:
        """It is package data, not a served resource: half a megabyte.

        The packaged guides are all served; this one is read from and never
        handed over whole, which is why it is registered nowhere in
        ``GUIDE_DOCS`` and has a drift gate of its own.
        """
        assert resources.DOCS_MODEL_FILENAME not in {
            doc.filename for doc in resources.GUIDE_DOCS.values()
        }
        assert len(resources.load_docs_model().encode("utf-8")) > 100_000


# ---------------------------------------------------------------------------
# T3 — the prompt binding, proved from the record
# ---------------------------------------------------------------------------


class TestPromptJourneyBinding:
    """A journey step edited in the model reaches the served prompt."""

    def _render(self, server: Any) -> str:
        from s0ma_mcp import prompts

        assert prompts.PROMPT_JOURNEYS["author_module"] == (
            "journey:mcp-authoring-loop"
        )
        result = _run(
            server.get_prompt(
                "author_module",
                {"project_root": "/tmp/demo", "module_name": "Billing"},
            )
        )
        return "\n".join(
            str(message.content.text) for message in result.messages
        )

    def test_the_served_prompt_carries_the_recorded_ladder(
        self, server: Any
    ) -> None:
        from s0ma_mcp import prompts

        text = self._render(server)
        ladder = prompts.journey_ladder("journey:mcp-authoring-loop")

        assert ladder in text, "the served prompt does not carry the ladder"

    def test_changing_a_recorded_step_changes_the_served_prompt(
        self, server: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The binding, demonstrated rather than described.

        The journey record is replaced with one whose steps differ; the
        prompt the server renders differs in exactly that way. Without
        the binding this passes only by coincidence, and it does not.
        """
        before = self._render(server)
        recorded = resources.docs_journey_steps("journey:mcp-authoring-loop")
        edited = [dict(step) for step in recorded]
        edited[0]["purpose"] = "Ask the tree what it is, in a different way."

        # Patched where the record is READ, not where the prompt is
        # written: the ladder reaches the model through this one
        # function, so this stands in for editing the journey source.
        monkeypatch.setattr(
            resources,
            "docs_journey_steps",
            lambda journey_id: edited if journey_id else [],
        )
        after = self._render(server)

        assert after != before
        assert "Ask the tree what it is, in a different way." in after
        assert recorded[0]["purpose"] not in after

    def test_every_prompt_is_bound_or_says_why_not(self, served: dict[str, Any]) -> None:
        from s0ma_mcp import prompts

        accounted = set(prompts.PROMPT_JOURNEYS) | set(
            prompts.PROMPT_WITHOUT_JOURNEY
        )
        assert accounted == set(served["prompts"])
        recorded = {
            journey.id for journey in resources.docs_bundle().journeys
        }
        for journey_id in prompts.PROMPT_JOURNEYS.values():
            assert journey_id in recorded, journey_id
        for name, reason in prompts.PROMPT_WITHOUT_JOURNEY.items():
            assert len(reason) > 80, name
