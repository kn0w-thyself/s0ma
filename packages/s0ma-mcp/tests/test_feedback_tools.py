"""The feedback pair: ``prepare_feedback`` (pure) and ``submit_feedback``.

Plan FB-M8 acceptance. The approval interaction is the point of these
tools, so almost everything here runs over a **real in-process client
session** (``create_connected_server_and_client_session``) with a fake
elicitation callback standing in for the human: a session is the only
place where ``ctx.elicit`` and the client's declared elicitation
capability exist at all.

What is held here:

* purity — ``prepare_feedback`` writes nothing under ``~/.s0ma`` and
  cannot open a socket (both enforced, not asserted by inspection);
* the approval outcomes — accept, "no" inside the form, decline, cancel,
  and a client that declared no elicitation capability (the FD-6 refusal
  path), each with the draft/receipt consequence the plan names;
* hash continuity — approved == transmitted == receipt, and any drift
  between the report and its fingerprint is refused before anyone is
  asked to approve anything;
* transport failure — the draft survives and the result stays structured;
* the served surface — the frozen annotations, the always-ask ``_meta``
  hint, and the fact that the injected approval parameter is NOT
  reachable from a client.

The network is faked at ``s0ma_dsl.feedback.client.request_json`` — the
single function that opens a socket — so the whole engine above it runs
for real.
"""

from __future__ import annotations

import asyncio
import json
import socket
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")

import mcp.types as types
from mcp.shared.memory import create_connected_server_and_client_session
from s0ma_dsl.feedback import client as feedback_client
from s0ma_dsl.feedback import model as feedback_model

from s0ma_mcp import create_server, tools

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

TOOL_RESULT_SCHEMA = "s0ma-tool-result@1"

#: A syntactically valid feedback token, so the token gate is satisfied
#: without a control plane. Never a real credential.
FAKE_TOKEN = "s0ma_fb_" + "A" * 43

REPORT: dict[str, Any] = {
    "summary": "The BARE_IMPORT remediation did not say where to move the import",
    "category": "diagnostic_quality",
    "impact": "minor",
    "actual": "It told me to declare it but my home is /Users/ada/work/app.s0ma",
    "reproduction": ["Author a nerve body with an import", "Run check"],
    "surface_kind": "tool",
    "surface_name": "check",
    "diagnostic_codes": ["BARE_IMPORT"],
}


@pytest.fixture()
def state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private ``$HOME`` so no test can touch the developer's ~/.s0ma."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("S0MA_FEEDBACK_TOKEN", raising=False)
    return home


@pytest.fixture()
def enrolled(state_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A machine that holds a feedback token (the environment override)."""
    monkeypatch.setenv("S0MA_FEEDBACK_TOKEN", FAKE_TOKEN)
    return state_home


@pytest.fixture()
def sent() -> Iterator[list[dict[str, Any]]]:
    """Capture every submission body; answer with a matching receipt."""
    bodies: list[dict[str, Any]] = []

    def fake_request_json(
        method: str,
        url: str,
        *,
        bearer: str,
        body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> feedback_client.FeedbackResult:
        assert body is not None
        bodies.append({"body": body, "headers": dict(extra_headers or {})})
        return feedback_client.FeedbackResult(
            ok=True,
            status_code=200,
            data={
                "schema": "s0ma-feedback-receipt@1",
                "ok": True,
                "feedback_id": "fb_00000000000000000000000000000001",
                "received_ts": 1787850000000,
                "payload_sha256": feedback_model.payload_sha256(body["envelope"]),
                "status": "received",
            },
        )

    original = feedback_client.request_json
    feedback_client.request_json = fake_request_json  # type: ignore[assignment]
    try:
        yield bodies
    finally:
        feedback_client.request_json = original  # type: ignore[assignment]


def _elicitation(answer: types.ElicitResult) -> Callable[..., Any]:
    """A client-side elicitation callback that always answers *answer*."""
    seen: list[types.ElicitRequestParams] = []

    async def callback(
        context: Any, params: types.ElicitRequestParams
    ) -> types.ElicitResult:
        seen.append(params)
        return answer

    callback.seen = seen  # type: ignore[attr-defined]
    return callback


def _journey(
    *,
    elicitation: Callable[..., Any] | None,
    arguments: dict[str, Any] | None = None,
    submit_with: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run prepare → submit over one in-process client session."""

    async def run() -> tuple[dict[str, Any], dict[str, Any]]:
        options: dict[str, Any] = {}
        if elicitation is not None:
            options["elicitation_callback"] = elicitation
        server = create_server()
        async with create_connected_server_and_client_session(
            server._mcp_server,  # noqa: SLF001 - the SDK's own in-process helper
            **options,
        ) as session:
            prepared = await session.call_tool(
                "prepare_feedback", arguments if arguments is not None else REPORT
            )
            prepare_result = prepared.structuredContent
            assert isinstance(prepare_result, dict)
            submit_arguments = (
                submit_with(prepare_result)
                if submit_with is not None
                else {
                    "envelope": prepare_result["envelope"],
                    "payload_sha256": prepare_result["payload_sha256"],
                }
            )
            submitted = await session.call_tool("submit_feedback", submit_arguments)
            submit_result = submitted.structuredContent
            assert isinstance(submit_result, dict)
            return prepare_result, submit_result

    return asyncio.run(run())


def _drafts(home: Path) -> list[dict[str, Any]]:
    directory = home / ".s0ma" / "feedback-drafts"
    if not directory.is_dir():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("fbd_*.json"))
    ]


def _receipts(home: Path) -> list[dict[str, Any]]:
    path = home / ".s0ma" / "feedback-receipts.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class TestPrepareIsPure:
    """``readOnlyHint=true`` is a claim about behavior, so behavior holds it."""

    def test_it_writes_no_state_and_opens_no_socket(
        self, state_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("prepare_feedback opened a socket")

        monkeypatch.setattr(socket, "create_connection", refuse)
        monkeypatch.setattr(socket.socket, "connect", refuse)

        result = tools.prepare_feedback_tool(**REPORT)

        assert result["ok"] is True
        assert not (state_home / ".s0ma" / "feedback-drafts").exists()
        assert not (state_home / ".s0ma" / "feedback-receipts.jsonl").exists()
        # Not even the installation pseudonym: minting it would be a write,
        # and readOnlyHint=true is a literal claim (0.14 budget §10.3).
        assert not (state_home / ".s0ma" / "installation_id").exists()
        assert "pseudonym" not in result["envelope"]["context"]

    def test_a_submission_establishes_the_pseudonym_prepare_would_not_mint(
        self, enrolled: Path, sent: list[dict[str, Any]]
    ) -> None:
        """So the report after this one carries a stable installation id."""
        assert not (enrolled / ".s0ma" / "installation_id").exists()

        first, result = _journey(
            elicitation=_elicitation(
                types.ElicitResult(action="accept", content={"send": True})
            )
        )
        assert result["ok"] is True
        assert "pseudonym" not in first["envelope"]["context"]
        assert (enrolled / ".s0ma" / "installation_id").is_file()

        second = tools.prepare_feedback_tool(**REPORT)
        assert second["envelope"]["context"]["pseudonym"] == (
            (enrolled / ".s0ma" / "installation_id").read_text(encoding="utf-8").strip()
        )

    def test_it_redacts_before_anything_is_shown_and_reports_what_it_removed(
        self, state_home: Path
    ) -> None:
        result = tools.prepare_feedback_tool(**REPORT)

        assert "/Users/ada" not in json.dumps(result["envelope"])
        assert "<PATH_1>" in result["envelope"]["actual"]
        assert result["redaction_report"]["profile"] == "v1"
        assert result["redaction_report"]["redacted"]["paths"] >= 1
        assert result["envelope"]["privacy"]["redacted"] == (
            result["redaction_report"]["redacted"]
        )
        assert any("replaced" in warning for warning in result["warnings"])

    def test_its_fingerprint_is_the_contract_hash_of_what_it_returned(
        self, state_home: Path
    ) -> None:
        result = tools.prepare_feedback_tool(**REPORT)

        assert result["payload_sha256"] == feedback_model.payload_sha256(
            result["envelope"]
        )

    def test_an_unenrolled_machine_is_warned_before_anyone_composes_more(
        self, state_home: Path
    ) -> None:
        result = tools.prepare_feedback_tool(**REPORT)

        assert any("s0ma feedback enroll" in w for w in result["warnings"])

    def test_the_context_carries_the_calling_client_over_a_session(
        self, state_home: Path
    ) -> None:
        prepared, _ = _journey(
            elicitation=_elicitation(types.ElicitResult(action="decline"))
        )
        context = prepared["envelope"]["context"]

        assert context["client"]["name"]
        assert context["mcp_protocol_version"]
        assert context["surface"] == {"kind": "tool", "name": "check"}
        assert set(context) <= set(feedback_model.CONTEXT_ALLOWED_KEYS)

    def test_it_refuses_a_report_no_service_could_accept(
        self, state_home: Path
    ) -> None:
        result = tools.prepare_feedback_tool(
            summary="x" * 401, category="bug", impact="minor"
        )

        assert result["ok"] is False
        assert result["code"] == "SCHEMA_INVALID"
        assert result["problems"]


class TestApprovalOutcomes:
    """One elicitation round, five honest endings."""

    def test_accept_sends_and_relays_a_matching_receipt(
        self, enrolled: Path, sent: list[dict[str, Any]]
    ) -> None:
        prepared, result = _journey(
            elicitation=_elicitation(
                types.ElicitResult(
                    action="accept", content={"send": True, "contact_ok": True}
                )
            )
        )

        assert result["ok"] is True
        assert result["receipt"]["feedback_id"].startswith("fb_")
        assert result["receipt"]["payload_sha256"] == prepared["payload_sha256"]
        assert result["contact_ok"] is True
        assert len(sent) == 1
        wrapper = sent[0]["body"]
        assert wrapper["schema"] == "s0ma-feedback-submission@1"
        assert wrapper["channel"] == "mcp"
        assert wrapper["approval_method"] == "mcp_elicitation"
        assert wrapper["contact_ok"] is True
        assert sent[0]["headers"]["Idempotency-Key"]

    def test_accept_leaves_a_receipt_in_the_log_and_no_unsent_draft(
        self, enrolled: Path, sent: list[dict[str, Any]]
    ) -> None:
        _, result = _journey(
            elicitation=_elicitation(
                types.ElicitResult(action="accept", content={"send": True})
            )
        )

        assert result["ok"] is True
        assert _drafts(enrolled) == []
        logged = _receipts(enrolled)
        assert len(logged) == 1
        assert logged[0]["feedback_id"] == result["receipt"]["feedback_id"]
        assert logged[0]["payload_sha256"] == result["receipt"]["payload_sha256"]

    def test_answering_no_inside_the_form_is_a_decline_not_a_send(
        self, enrolled: Path, sent: list[dict[str, Any]]
    ) -> None:
        _, result = _journey(
            elicitation=_elicitation(
                types.ElicitResult(action="accept", content={"send": False})
            )
        )

        assert result["ok"] is False
        assert result["code"] == "APPROVAL_DECLINED"
        assert sent == []
        assert len(_drafts(enrolled)) == 1

    @pytest.mark.parametrize(
        ("action", "code"),
        [("decline", "APPROVAL_DECLINED"), ("cancel", "APPROVAL_CANCELLED")],
    )
    def test_decline_and_cancel_save_the_draft_and_send_nothing(
        self,
        enrolled: Path,
        sent: list[dict[str, Any]],
        action: str,
        code: str,
    ) -> None:
        _, result = _journey(
            elicitation=_elicitation(types.ElicitResult(action=action))
        )

        assert result["ok"] is False
        assert result["code"] == code
        assert sent == []
        drafts = _drafts(enrolled)
        assert len(drafts) == 1
        assert drafts[0]["draft_id"] == result["draft_id"]
        assert result["draft_id"] in result["remediation"]

    def test_a_client_without_elicitation_gets_the_refusal_path(
        self, enrolled: Path, sent: list[dict[str, Any]]
    ) -> None:
        """FD-6: no trustworthy approval interaction, no MCP submission."""
        _, result = _journey(elicitation=None)

        assert result["ok"] is False
        assert result["code"] == "APPROVAL_UNAVAILABLE"
        assert result["remediation"] == "run: s0ma feedback"
        assert sent == []
        assert len(_drafts(enrolled)) == 1
        assert _drafts(enrolled)[0]["draft_id"] == result["draft_id"]

    def test_the_user_reads_the_exact_report_before_approving(
        self, enrolled: Path, sent: list[dict[str, Any]]
    ) -> None:
        """Trust rule 3: the approval question carries the real data."""
        callback = _elicitation(types.ElicitResult(action="decline"))
        prepared, _ = _journey(elicitation=callback)

        asked = callback.seen[0]  # type: ignore[attr-defined]
        message = str(asked.message)
        envelope = prepared["envelope"]
        assert "Send exactly this feedback data" in message
        assert envelope["summary"] in message
        assert envelope["actual"] in message
        for step in envelope["reproduction"]:
            assert step in message
        assert "payload" not in message.lower()
        schema = asked.requestedSchema
        assert set(schema["properties"]) == {"send", "contact_ok"}
        assert schema["properties"]["contact_ok"]["description"] == (
            "May kn0wthyself contact you about this report?"
        )
        assert schema["properties"]["contact_ok"]["default"] is False


class TestTheDataIsTheApprovedData:
    """Approved == transmitted == stored == receipt, or nothing happens."""

    def test_hash_continuity_holds_from_prepare_to_receipt(
        self, enrolled: Path, sent: list[dict[str, Any]]
    ) -> None:
        prepared, result = _journey(
            elicitation=_elicitation(
                types.ElicitResult(action="accept", content={"send": True})
            )
        )

        transmitted = sent[0]["body"]["envelope"]
        assert transmitted == prepared["envelope"]
        assert feedback_model.payload_sha256(transmitted) == (
            prepared["payload_sha256"]
        )
        assert result["receipt"]["payload_sha256"] == prepared["payload_sha256"]

    def test_an_edited_report_is_refused_before_anyone_is_asked(
        self, enrolled: Path, sent: list[dict[str, Any]]
    ) -> None:
        callback = _elicitation(
            types.ElicitResult(action="accept", content={"send": True})
        )

        def tamper(prepared: dict[str, Any]) -> dict[str, Any]:
            edited = dict(prepared["envelope"])
            edited["summary"] = "Something the user never wrote"
            return {
                "envelope": edited,
                "payload_sha256": prepared["payload_sha256"],
            }

        _, result = _journey(elicitation=callback, submit_with=tamper)

        assert result["ok"] is False
        assert result["code"] == "HASH_MISMATCH"
        assert "prepare_feedback" in result["remediation"]
        assert callback.seen == []  # type: ignore[attr-defined]
        assert sent == []
        assert _drafts(enrolled) == []

    def test_an_unknown_field_cannot_ride_along_under_a_stale_fingerprint(
        self, enrolled: Path, sent: list[dict[str, Any]]
    ) -> None:
        def smuggle(prepared: dict[str, Any]) -> dict[str, Any]:
            edited = dict(prepared["envelope"])
            edited["transcript"] = "everything the user said today"
            return {
                "envelope": edited,
                "payload_sha256": prepared["payload_sha256"],
            }

        _, result = _journey(
            elicitation=_elicitation(
                types.ElicitResult(action="accept", content={"send": True})
            ),
            submit_with=smuggle,
        )

        assert result["ok"] is False
        assert result["code"] == "HASH_MISMATCH"
        assert sent == []

    def test_a_wrong_fingerprint_names_the_right_one(
        self, enrolled: Path, sent: list[dict[str, Any]]
    ) -> None:
        def restamp(prepared: dict[str, Any]) -> dict[str, Any]:
            return {
                "envelope": prepared["envelope"],
                "payload_sha256": "sha256:" + "0" * 64,
            }

        _, result = _journey(
            elicitation=_elicitation(
                types.ElicitResult(action="accept", content={"send": True})
            ),
            submit_with=restamp,
        )

        assert result["ok"] is False
        assert result["code"] == "HASH_MISMATCH"
        assert result["expected_payload_sha256"].startswith("sha256:")
        assert sent == []


class TestFailuresKeepTheUsersWords:
    """Feedback is never load-bearing, and never silently lost."""

    def test_a_transport_failure_preserves_the_draft_and_stays_structured(
        self, enrolled: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def unreachable(*args: Any, **kwargs: Any) -> feedback_client.FeedbackResult:
            return feedback_client.FeedbackResult(
                ok=False,
                code=feedback_client.CODE_UNREACHABLE,
                message="The s0ma feedback service could not be reached.",
                remediation="Try again when the machine is back online.",
            )

        monkeypatch.setattr(feedback_client, "request_json", unreachable)

        _, result = _journey(
            elicitation=_elicitation(
                types.ElicitResult(action="accept", content={"send": True})
            )
        )

        assert result["ok"] is False
        assert result["code"] == "NETWORK_UNREACHABLE"
        assert result["error"]
        assert result["remediation"]
        drafts = _drafts(enrolled)
        assert len(drafts) == 1
        assert drafts[0]["draft_id"] == result["draft_id"]
        assert _receipts(enrolled) == []

    def test_an_unenrolled_machine_refuses_before_asking_for_approval(
        self, state_home: Path
    ) -> None:
        callback = _elicitation(
            types.ElicitResult(action="accept", content={"send": True})
        )

        _, result = _journey(elicitation=callback)

        assert result["ok"] is False
        assert result["code"] == "INVALID_TOKEN"
        assert callback.seen == []  # type: ignore[attr-defined]
        assert _drafts(state_home) == []

    def test_a_direct_python_call_never_sends_without_an_approval(
        self, enrolled: Path, sent: list[dict[str, Any]]
    ) -> None:
        """The injected approval defaults to absent, and absent means no."""
        prepared = tools.prepare_feedback_tool(**REPORT)

        result = tools.submit_feedback_tool(
            envelope=prepared["envelope"],
            payload_sha256=prepared["payload_sha256"],
        )

        assert result["ok"] is False
        assert result["code"] == "APPROVAL_UNAVAILABLE"
        assert sent == []


class TestTheServedSurface:
    """The client-visible contract: FD-5 annotations and no forged approval."""

    def test_annotations_match_the_authored_attributes(self) -> None:
        served = {
            tool.name: tool
            for tool in asyncio.run(create_server().list_tools())
            if tool.name in {"prepare_feedback", "submit_feedback"}
        }
        assert set(served) == {"prepare_feedback", "submit_feedback"}

        prepare = served["prepare_feedback"].annotations
        assert prepare is not None
        assert (
            prepare.readOnlyHint,
            prepare.destructiveHint,
            prepare.idempotentHint,
            prepare.openWorldHint,
        ) == (True, None, None, False)

        submit = served["submit_feedback"].annotations
        assert submit is not None
        assert (
            submit.readOnlyHint,
            submit.destructiveHint,
            submit.idempotentHint,
            submit.openWorldHint,
        ) == (False, False, True, True)

    def test_the_authored_attributes_are_the_only_source_of_those_hints(
        self,
    ) -> None:
        """F-M3-4 parity: the .s0ma source, not the factory, decides."""
        authored = {
            "prepare_feedback": ["readOnlyHint=true", "openWorldHint=false"],
            "submit_feedback": [
                "readOnlyHint=false",
                "destructiveHint=false",
                "idempotentHint=true",
                "openWorldHint=true",
            ],
        }
        for served_name, entries in authored.items():
            declaration = getattr(tools, f"{served_name}_tool")
            assert declaration.__component__.metadata[
                "mcp_tool_annotations"
            ] == entries

    def test_submit_carries_the_always_ask_hint_and_prepare_does_not(
        self,
    ) -> None:
        served = {tool.name: tool for tool in asyncio.run(create_server().list_tools())}

        assert served["submit_feedback"].meta == {
            "anthropic/requiresUserInteraction": True
        }
        assert served["prepare_feedback"].meta is None

    def test_a_client_cannot_reach_the_injected_interaction_parameters(
        self,
    ) -> None:
        """An agent that could pass mcp_approval could skip the user."""
        served = {tool.name: tool for tool in asyncio.run(create_server().list_tools())}

        assert set(served["submit_feedback"].inputSchema["properties"]) == {
            "envelope",
            "payload_sha256",
            "contact_ok",
        }
        properties = set(served["prepare_feedback"].inputSchema["properties"])
        assert "mcp_client" not in properties
        assert "mcp_approval" not in properties
        assert served["prepare_feedback"].inputSchema["required"] == [
            "summary",
            "category",
            "impact",
        ]

    def test_the_served_vocabulary_is_the_contract_vocabulary(self) -> None:
        """The Literal enums mirror §4; drift here is a contract change."""
        served = {tool.name: tool for tool in asyncio.run(create_server().list_tools())}
        properties = served["prepare_feedback"].inputSchema["properties"]

        assert properties["category"]["enum"] == list(feedback_model.CATEGORIES)
        assert properties["impact"]["enum"] == list(feedback_model.IMPACTS)

    def test_every_feedback_result_is_common_envelope_data(
        self, enrolled: Path, sent: list[dict[str, Any]]
    ) -> None:
        prepared, result = _journey(
            elicitation=_elicitation(types.ElicitResult(action="decline"))
        )

        for document in (prepared, result):
            assert document["schema"] == TOOL_RESULT_SCHEMA
            assert isinstance(document["ok"], bool)
            assert isinstance(document["next_actions"], list)
        assert prepared["next_actions"][0]["tool"] == "submit_feedback"
        assert prepared["next_actions"][0]["arguments"] == {
            "envelope": prepared["envelope"],
            "payload_sha256": prepared["payload_sha256"],
        }
        assert result["next_actions"] == []

    def test_the_tool_descriptions_stay_inside_the_four_line_budget(
        self,
    ) -> None:
        """0.14 surface budget §10.4: tool descriptions are ≤ 4 lines."""
        served = {tool.name: tool for tool in asyncio.run(create_server().list_tools())}

        for name in ("prepare_feedback", "submit_feedback"):
            description = served[name].description or ""
            lines = [line for line in description.splitlines() if line.strip()]
            assert len(lines) <= 4, f"{name} description is {len(lines)} lines"
            assert "payload" not in description.lower().replace(
                "payload_sha256", ""
            )
