"""The built-in stub server: what Claude hears when there is no s0ma to start.

The stub is the launcher's answer to the thirty-second rule (plan section 4.4).
It never installs, never waits for a network, and never leaves the host looking
at a server that would not start: it completes the handshake at once and says,
in words a model can pass on to a person, that s0ma is not installed yet and
that ``/s0ma:setup`` fixes it.

The tests come at it from two directions, because both can break on their own:

* **In process**, through :func:`s0ma_launch.serve_stub`, which takes a pair of
  text streams. That is where the protocol logic is examined message by message.
* **Through real pipes**, by running the launcher file as a whole program with
  ``serve`` and writing to its standard input. That is where the wiring is
  proved: that ``serve`` reaches the stub at all, that nothing but protocol
  messages ever lands on standard output, and that the end of the input ends the
  run with a zero.

Two house rules are tested here rather than assumed: nothing is ever written
into ``S0MA_HOME`` by a ``serve`` that had nothing to serve, and a license key
is never shown in full - only whether there is one and its last four characters,
exactly as ``status`` does it.
"""

from __future__ import annotations

import io
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

#: Anything that could be a real key, in any output. Nothing may match.
KEY_SHAPED = re.compile(r"s0ma_(?:live|test)_[A-Za-z0-9_-]{4,}")

#: How long a stub run through real pipes may take before the test gives up.
#: The stub does no work at all, so this is generous by a wide margin.
SUBPROCESS_TIMEOUT_SECONDS = 60


# ---------------------------------------------------------------------------
# Driving the stub.
# ---------------------------------------------------------------------------


def initialize(version: str = "2025-11-25", message_id: Any = 1) -> dict[str, Any]:
    """The `initialize` a well-behaved client opens with."""
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": "initialize",
        "params": {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": {"name": "the test client", "version": "1.0.0"},
        },
    }


def request(method: str, message_id: Any, **params: Any) -> dict[str, Any]:
    """A plain JSON-RPC request."""
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params:
        message["params"] = params
    return message


def drive_lines(
    launcher: ModuleType, lines: list[str], **kwargs: Any
) -> tuple[int, list[dict[str, Any]], str]:
    """Feed *lines* to the stub in process; return the code, the replies, the text."""
    source = io.StringIO("".join(line + "\n" for line in lines))
    sink = io.StringIO()
    code = int(launcher.serve_stub(source, sink, **kwargs))
    written = sink.getvalue()
    replies = [json.loads(one) for one in written.splitlines() if one.strip()]
    return code, replies, written


def drive(
    launcher: ModuleType, messages: list[dict[str, Any]], **kwargs: Any
) -> tuple[int, list[dict[str, Any]], str]:
    """The same, for messages that are already well-formed objects."""
    return drive_lines(launcher, [json.dumps(one) for one in messages], **kwargs)


def _clean_env(launcher: ModuleType) -> dict[str, str]:
    """A copy of this process's environment with every s0ma variable removed.

    The names come from the launcher itself, so a variable that is renamed there
    cannot quietly stop being cleared here.
    """
    ours = {
        launcher.ENV_HOME,
        launcher.ENV_LICENSE_KEY,
        launcher.ENV_UPDATE,
        launcher.ENV_TOOLCHAIN,
        launcher.ENV_CP_HOST,
        launcher.ENV_PROJECT_DIR,
        launcher.ENV_PLUGIN_DATA,
    }
    return {name: value for name, value in os.environ.items() if name not in ours}


def serve_through_pipes(
    launcher: ModuleType,
    home: Path,
    project: Path,
    lines: list[str],
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the launcher file as a whole program and talk to it over real pipes.

    ``uv run --script`` is how a host starts it and is proved by hand at the
    gate; running the same file with this interpreter exercises the identical
    code and is fast enough to do in every test.
    """
    env = _clean_env(launcher)
    env[launcher.ENV_HOME] = str(home)
    env[launcher.ENV_PROJECT_DIR] = str(project)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(Path(launcher.__file__)), "serve"],
        input="".join(line + "\n" for line in lines),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(project),
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
        check=False,
    )


def replies_of(completed: subprocess.CompletedProcess[str]) -> list[dict[str, Any]]:
    """Every protocol message a piped run wrote, parsed."""
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# The handshake.
# ---------------------------------------------------------------------------


def test_the_handshake_is_answered_at_once(launcher: ModuleType) -> None:
    code, replies, _ = drive(launcher, [initialize()])

    assert code == 0
    assert len(replies) == 1
    answer = replies[0]
    assert answer["jsonrpc"] == "2.0"
    assert answer["id"] == 1
    result = answer["result"]
    assert result["protocolVersion"] == "2025-11-25"
    assert result["serverInfo"]["name"] == "s0ma"
    assert result["instructions"]


def test_only_tools_are_offered(launcher: ModuleType) -> None:
    """A capability this server does not declare is one Claude will not ask for."""
    _, replies, _ = drive(launcher, [initialize()])
    assert replies[0]["result"]["capabilities"] == {"tools": {}}


def test_the_server_says_plainly_that_it_is_the_setup_stub(launcher: ModuleType) -> None:
    _, replies, _ = drive(launcher, [initialize()])
    info = replies[0]["result"]["serverInfo"]
    assert "stub" in info["version"]
    assert "setup" in info["title"].lower()


def test_a_version_the_stub_knows_is_answered_with_that_same_version(
    launcher: ModuleType,
) -> None:
    """The specification's rule: support it, and you must answer with it."""
    for version in launcher.STUB_PROTOCOL_VERSIONS:
        _, replies, _ = drive(launcher, [initialize(version)])
        assert replies[0]["result"]["protocolVersion"] == version


def test_a_version_the_stub_does_not_know_gets_the_newest_one_it_has(
    launcher: ModuleType,
) -> None:
    """Otherwise the server must answer with another version it supports."""
    for asked in ("1999-01-01", "2099-12-31", "not-a-version", ""):
        _, replies, _ = drive(launcher, [initialize(asked)])
        assert replies[0]["result"]["protocolVersion"] == launcher.STUB_LATEST_PROTOCOL_VERSION


def test_an_initialize_with_no_version_at_all_still_gets_an_answer(
    launcher: ModuleType,
) -> None:
    _, replies, _ = drive(launcher, [request("initialize", 1)])
    assert replies[0]["result"]["protocolVersion"] == launcher.STUB_LATEST_PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# What the instructions say, which is the first thing Claude reads.
# ---------------------------------------------------------------------------


def test_the_instructions_say_what_is_missing_and_what_fixes_it(
    launcher: ModuleType, isolated_home: Path, project: Path
) -> None:
    _, replies, _ = drive(launcher, [initialize()], home=isolated_home, project=project)
    instructions = replies[0]["result"]["instructions"]

    assert "not installed on this machine yet" in instructions
    assert "/s0ma:setup" in instructions
    assert "restart" in instructions
    assert instructions.count(". ") == 1, "two sentences, no more"
    assert instructions.endswith(".")


def test_a_pin_that_is_not_installed_is_named_in_the_instructions(
    launcher: ModuleType, isolated_home: Path, project: Path
) -> None:
    """A project asking for a version it has not got is a different problem, and
    the model has to be able to tell the person which one they have."""
    (project / launcher.PIN_FILENAME).write_text("0.19.0\n", encoding="utf-8")

    _, replies, _ = drive(launcher, [initialize()], home=isolated_home, project=project)
    instructions = replies[0]["result"]["instructions"]

    assert "0.19.0" in instructions
    assert launcher.PIN_FILENAME in instructions
    assert "/s0ma:setup" in instructions
    assert instructions.count(". ") == 1


def test_the_instructions_are_built_from_the_launchers_own_reason(
    launcher: ModuleType,
) -> None:
    """One wording, in one place: whatever ``status`` says is what Claude hears."""
    resolution = launcher.Resolution(
        kind=launcher.KIND_NONE,
        path=None,
        version=None,
        reason="S0MA_TOOLCHAIN points at /somewhere, but there is no s0ma program there.",
    )
    instructions = launcher.stub_instructions(resolution)

    assert instructions.startswith("S0MA_TOOLCHAIN points at /somewhere")
    assert "/s0ma:setup" in instructions
    # The reason's own full stop is not left sitting in the middle of a sentence.
    assert "there., so" not in instructions


# ---------------------------------------------------------------------------
# The one tool.
# ---------------------------------------------------------------------------


def test_exactly_one_tool_is_listed(launcher: ModuleType) -> None:
    _, replies, _ = drive(launcher, [initialize(), request("tools/list", 2)])

    tools = replies[1]["result"]["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "s0ma_setup_status"


def test_the_tool_is_titled_described_and_takes_nothing(launcher: ModuleType) -> None:
    """Anthropic's directory rejects a tool without a title or a behaviour hint."""
    _, replies, _ = drive(launcher, [request("tools/list", 1)])
    tool = replies[0]["result"]["tools"][0]

    assert tool["title"]
    assert tool["description"]
    assert tool["inputSchema"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def test_the_tool_is_marked_read_only_and_closed_world(launcher: ModuleType) -> None:
    _, replies, _ = drive(launcher, [request("tools/list", 1)])
    annotations = replies[0]["result"]["tools"][0]["annotations"]

    assert annotations["readOnlyHint"] is True
    assert annotations["destructiveHint"] is False
    assert annotations["idempotentHint"] is True
    assert annotations["openWorldHint"] is False
    assert annotations["title"]


def test_calling_the_tool_reports_the_same_facts_as_status(
    launcher: ModuleType, isolated_home: Path, project: Path
) -> None:
    _, replies, _ = drive(
        launcher,
        [request("tools/call", 1, name="s0ma_setup_status", arguments={})],
        home=isolated_home,
        project=project,
    )
    result = replies[0]["result"]

    assert result["isError"] is False
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    text = result["content"][0]["text"]
    for expected in ("Runs here:", "Why:", "Installed:", "License key:", "Next step:"):
        assert expected in text
    assert "/s0ma:setup" in text


def test_the_tool_works_without_an_arguments_field_at_all(launcher: ModuleType) -> None:
    _, replies, _ = drive(
        launcher, [request("tools/call", 1, name="s0ma_setup_status")]
    )
    assert replies[0]["result"]["isError"] is False


def test_the_tool_notices_when_s0ma_has_arrived_mid_session(
    launcher: ModuleType, isolated_home: Path, project: Path, make_toolchain: Any
) -> None:
    """Someone runs /s0ma:setup in a terminal while the session is open. Asking
    again should say so, not repeat that nothing is installed."""
    make_toolchain("0.18.0")

    _, replies, _ = drive(
        launcher,
        [request("tools/call", 1, name="s0ma_setup_status")],
        home=isolated_home,
        project=project,
    )
    text = replies[0]["result"]["content"][0]["text"]

    assert "installed on this machine now" in text
    assert "0.18.0" in text


def test_a_tool_this_server_does_not_have_is_an_error_result_not_a_crash(
    launcher: ModuleType,
) -> None:
    code, replies, _ = drive(
        launcher, [request("tools/call", 1, name="s0ma_build_everything")]
    )

    assert code == 0
    result = replies[0]["result"]
    assert result["isError"] is True
    assert "s0ma_build_everything" in result["content"][0]["text"]
    assert "/s0ma:setup" in result["content"][0]["text"]


def test_a_tool_call_with_no_name_is_a_protocol_error(launcher: ModuleType) -> None:
    _, replies, _ = drive(launcher, [request("tools/call", 1, arguments={})])
    assert replies[0]["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# The rest of the protocol.
# ---------------------------------------------------------------------------


def test_ping_is_answered_with_an_empty_result(launcher: ModuleType) -> None:
    _, replies, _ = drive(launcher, [request("ping", 7)])
    assert replies == [{"jsonrpc": "2.0", "id": 7, "result": {}}]


def test_a_notification_is_never_answered(launcher: ModuleType) -> None:
    code, replies, written = drive_lines(
        launcher,
        [
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled"}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/who/knows"}),
        ],
    )

    assert code == 0
    assert replies == []
    assert written == ""


def test_an_unknown_method_gets_the_proper_error(launcher: ModuleType) -> None:
    _, replies, _ = drive(launcher, [request("resources/list", 3)])

    failure = replies[0]["error"]
    assert failure["code"] == -32601
    assert "resources/list" in failure["message"]
    assert replies[0]["id"] == 3


def test_a_modern_clients_probe_is_answered_the_way_it_expects(
    launcher: ModuleType,
) -> None:
    """The 2026-07-28 revision has clients probe with ``server/discover`` and
    fall back to ``initialize`` on any error that is not a modern one. A plain
    method-not-found is exactly that, so this stub is reached the old way."""
    _, replies, _ = drive(launcher, [request("server/discover", 1)])
    assert replies[0]["error"]["code"] == -32601


def test_a_line_that_is_not_json_gets_a_parse_error_and_the_run_carries_on(
    launcher: ModuleType,
) -> None:
    code, replies, _ = drive_lines(
        launcher,
        ["{not json at all", json.dumps(request("ping", 2))],
    )

    assert code == 0
    assert len(replies) == 2
    assert replies[0]["error"]["code"] == -32700
    assert replies[0]["id"] is None, "a line too broken to find an id in answers null"
    assert replies[1] == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_blank_lines_are_passed_over_in_silence(launcher: ModuleType) -> None:
    code, replies, _ = drive_lines(launcher, ["", "   ", json.dumps(request("ping", 1))])
    assert code == 0
    assert len(replies) == 1


def test_a_message_that_is_not_an_object_is_refused(launcher: ModuleType) -> None:
    _, replies, _ = drive_lines(launcher, ['"hello"', "42"])
    assert [one["error"]["code"] for one in replies] == [-32600, -32600]


def test_a_batch_is_refused_rather_than_half_understood(launcher: ModuleType) -> None:
    """JSON-RPC batching left MCP in revision 2025-06-18."""
    _, replies, _ = drive_lines(launcher, [json.dumps([request("ping", 1)])])
    assert replies[0]["error"]["code"] == -32600
    assert replies[0]["id"] is None


def test_a_response_to_a_request_this_server_never_sent_is_ignored(
    launcher: ModuleType,
) -> None:
    code, replies, _ = drive_lines(
        launcher, [json.dumps({"jsonrpc": "2.0", "id": 9, "result": {}})]
    )
    assert code == 0
    assert replies == []


def test_a_request_with_an_unusable_id_is_refused(launcher: ModuleType) -> None:
    """The protocol forbids a null id on a request, and a list is not an id."""
    _, replies, _ = drive_lines(
        launcher,
        [
            json.dumps({"jsonrpc": "2.0", "id": None, "method": "ping"}),
            json.dumps({"jsonrpc": "2.0", "id": [1], "method": "ping"}),
        ],
    )
    assert [one["error"]["code"] for one in replies] == [-32600, -32600]


def test_params_that_are_not_an_object_are_refused(launcher: ModuleType) -> None:
    _, replies, _ = drive_lines(
        launcher,
        [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": []})],
    )
    assert replies[0]["error"]["code"] == -32602


def test_a_string_id_comes_back_exactly_as_it_was_sent(launcher: ModuleType) -> None:
    _, replies, _ = drive(launcher, [request("ping", "abc-123")])
    assert replies[0]["id"] == "abc-123"


def test_several_requests_in_one_burst_are_all_answered_in_order(
    launcher: ModuleType,
) -> None:
    """A host may write everything it has and then wait. Nothing may be dropped."""
    messages: list[dict[str, Any]] = [
        initialize(message_id=1),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        request("tools/list", 2),
        request("tools/call", 3, name="s0ma_setup_status", arguments={}),
        request("ping", 4),
        request("nothing/at/all", 5),
    ]

    code, replies, _ = drive(launcher, messages)

    assert code == 0
    assert [one["id"] for one in replies] == [1, 2, 3, 4, 5]


def test_the_end_of_the_input_ends_the_run_with_a_zero(launcher: ModuleType) -> None:
    """Closing the input is how a host asks a stdio server to stop. Not a failure."""
    code, replies, _ = drive_lines(launcher, [])
    assert code == 0
    assert replies == []


def test_a_closed_output_ends_the_run_quietly(launcher: ModuleType) -> None:
    """The host went away mid-answer. There is nobody left to complain to."""
    source = io.StringIO(json.dumps(request("ping", 1)) + "\n")
    sink = io.StringIO()
    sink.close()
    assert launcher.serve_stub(source, sink) == 0


def test_an_input_that_cannot_be_read_is_the_same_as_no_input(
    launcher: ModuleType,
) -> None:
    """A stdin the host has taken away is not an error; there is simply nothing
    to serve."""

    class Unreadable:
        def readline(self) -> str:
            raise OSError("the input has gone")

    assert launcher.serve_stub(Unreadable(), io.StringIO()) == 0


# ---------------------------------------------------------------------------
# What the stub will not do.
# ---------------------------------------------------------------------------


def test_the_stub_opens_no_socket(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """Nothing on this path asks anybody anything. An MCP server has thirty
    seconds to answer, and a network is how you lose them."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the stub server opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    code, replies, _ = drive(
        launcher,
        [
            initialize(),
            request("tools/list", 2),
            request("tools/call", 3, name="s0ma_setup_status", arguments={}),
        ],
        home=isolated_home,
    )

    assert code == 0
    assert len(replies) == 3


def test_the_stub_installs_nothing_and_leaves_a_clean_machine_clean(
    launcher: ModuleType, isolated_home: Path, project: Path
) -> None:
    drive(
        launcher,
        [
            initialize(),
            request("tools/list", 2),
            request("tools/call", 3, name="s0ma_setup_status", arguments={}),
        ],
        home=isolated_home,
        project=project,
    )

    assert list(isolated_home.iterdir()) == []


def test_a_license_key_is_never_shown_in_full(
    launcher: ModuleType, isolated_home: Path, project: Path, fake_key: str
) -> None:
    (isolated_home / launcher.LICENSE_FILENAME).write_text(fake_key, encoding="utf-8")

    _, replies, written = drive(
        launcher,
        [initialize(), request("tools/call", 2, name="s0ma_setup_status")],
        home=isolated_home,
        project=project,
    )

    assert fake_key not in written
    assert KEY_SHAPED.search(written) is None
    text = replies[1]["result"]["content"][0]["text"]
    assert "s0ma_..." + fake_key[-4:] in text


def test_everything_the_stub_writes_is_plain_ascii(
    launcher: ModuleType, isolated_home: Path, project: Path
) -> None:
    """A Windows console outside UTF-8 mode has to be able to show every line a
    person may end up reading (L1 gate ruling 6)."""
    _, _, written = drive(
        launcher,
        [
            initialize(),
            request("tools/list", 2),
            request("tools/call", 3, name="s0ma_setup_status"),
            request("mystery", 4),
        ],
        home=isolated_home,
        project=project,
    )

    written.encode("ascii")


def test_no_message_carries_a_newline_inside_it(launcher: ModuleType) -> None:
    """The transport delimits messages by newlines and forbids embedded ones -
    and the tool's answer is a report with line breaks all through it."""
    _, replies, written = drive(
        launcher, [request("tools/call", 1, name="s0ma_setup_status")]
    )

    assert written.count("\n") == 1
    assert "\n" in replies[0]["result"]["content"][0]["text"]


# The house rule about words a programmer would use and a person would not is
# checked over the whole launcher file, the stub included, by
# ``test_no_message_the_launcher_prints_is_addressed_to_a_programmer`` in
# ``test_status.py``. It is not repeated here.


# ---------------------------------------------------------------------------
# The wiring: `serve` really does reach the stub, through real pipes.
# ---------------------------------------------------------------------------


def test_serve_hands_the_session_to_the_stub(
    launcher: ModuleType, run_cli: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seam itself: nothing installed means the stub takes the conversation."""
    seen: list[tuple[Any, Any, Any]] = []

    def record(source: Any, sink: Any, **kwargs: Any) -> int:
        seen.append((source, sink, kwargs.get("resolution")))
        return 0

    monkeypatch.setattr(launcher, "serve_stub", record)

    code, out, err = run_cli("serve")

    assert code == 0
    assert out == "", "stdout belongs to the protocol"
    assert len(seen) == 1
    source, sink, resolution = seen[0]
    assert source is sys.stdin
    assert sink is sys.stdout
    assert resolution.kind == launcher.KIND_NONE
    assert "not installed on this machine yet" in err
    assert "/s0ma:setup" in err


def test_a_real_run_answers_the_handshake_over_pipes(
    launcher: ModuleType, isolated_home: Path, project: Path
) -> None:
    completed = serve_through_pipes(
        launcher,
        isolated_home,
        project,
        [
            json.dumps(initialize()),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps(request("tools/list", 2)),
            json.dumps(request("tools/call", 3, name="s0ma_setup_status", arguments={})),
        ],
    )

    assert completed.returncode == 0
    replies = replies_of(completed)
    assert [one["id"] for one in replies] == [1, 2, 3]
    assert replies[0]["result"]["serverInfo"]["name"] == "s0ma"
    assert replies[1]["result"]["tools"][0]["name"] == "s0ma_setup_status"
    assert replies[2]["result"]["isError"] is False


def test_a_real_run_puts_nothing_but_protocol_messages_on_stdout(
    launcher: ModuleType, isolated_home: Path, project: Path
) -> None:
    """The reason s0ma is missing is worth saying - on stderr, where a person
    reading the host's log will find it and the protocol will not."""
    completed = serve_through_pipes(
        launcher,
        isolated_home,
        project,
        ["{ broken", json.dumps(initialize()), json.dumps(request("ping", 2))],
    )

    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        assert json.loads(line)["jsonrpc"] == "2.0"
    assert "not installed on this machine yet" in completed.stderr
    assert "/s0ma:setup" in completed.stderr


def test_a_real_run_ends_with_a_zero_when_the_input_closes(
    launcher: ModuleType, isolated_home: Path, project: Path
) -> None:
    completed = serve_through_pipes(launcher, isolated_home, project, [])

    assert completed.returncode == 0
    assert completed.stdout == ""


def test_a_real_run_installs_nothing(
    launcher: ModuleType, isolated_home: Path, project: Path
) -> None:
    serve_through_pipes(launcher, isolated_home, project, [json.dumps(initialize())])
    assert list(isolated_home.iterdir()) == []


def test_a_real_run_with_a_pin_it_has_not_got_says_which_version_is_wanted(
    launcher: ModuleType, isolated_home: Path, project: Path
) -> None:
    (project / launcher.PIN_FILENAME).write_text("0.19.0\n", encoding="utf-8")

    completed = serve_through_pipes(
        launcher, isolated_home, project, [json.dumps(initialize())]
    )

    instructions = replies_of(completed)[0]["result"]["instructions"]
    assert "0.19.0" in instructions
    assert launcher.PIN_FILENAME in instructions
    assert "0.19.0" in completed.stderr


def test_a_real_run_never_prints_the_key(
    launcher: ModuleType, isolated_home: Path, project: Path, fake_key: str
) -> None:
    completed = serve_through_pipes(
        launcher,
        isolated_home,
        project,
        [json.dumps(request("tools/call", 1, name="s0ma_setup_status"))],
        extra_env={launcher.ENV_LICENSE_KEY: fake_key},
    )

    assert fake_key not in completed.stdout
    assert fake_key not in completed.stderr
    assert KEY_SHAPED.search(completed.stdout) is None
    text = replies_of(completed)[0]["result"]["content"][0]["text"]
    assert "s0ma_..." + fake_key[-4:] in text
