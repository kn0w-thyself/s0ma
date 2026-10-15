"""The conditional narration rule: one line, only while studi0 watches.

M11 mainlines the transport the M8 bench measured — the survival rules
(the channel that lands 36/36 sessions) carry ONE line asking the agent
to narrate its main movements into ``.s0ma/studi0/session.jsonl``. What
makes it a product feature rather than an instrumentation flag is the
condition (owner decision D-11: *if studi0 isn't active there is zero
need for narration — in fact we don't want it*):

* the condition is **presence, not configuration** — the file
  ``.s0ma/studi0/active.json`` under the project root the call names,
  parsing as a JSON object with ``port`` and ``pid``, whose ``pid`` is a
  process that is running right now;
* it is re-checked **per rules render**. studi0 can be started or
  stopped in the middle of a conversation and the next tool result must
  say so, so nothing is cached and no daemon is involved;
* every other reading — no file, unreadable bytes, malformed JSON, a
  missing key, a dead pid left by an unclean shutdown — is **absent**,
  and absent is never an error the tool result reports;
* while absent the rules are **byte-identical** to :data:`MAINLINE_RULES`
  — the canonical ``_SURVIVAL_RULES`` plus the one unconditional docs
  line F7 appends — which is the assertion that keeps this feature from
  costing a single token in the sessions that do not want it.

The rule text is frozen. The bench measured 44% session compliance at
100% line validity for exactly these bytes; a reworded line is an
unmeasured line, so it is pinned here character for character.

The line is also, by construction, dynamic — it exists only while the
marker does — so it can never reach a static artifact. The served tool
surface, the self-prompt card, and the survival-card guide resource are
all asserted unchanged.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")

from conftest import mainline_rules, make_project

from s0ma_mcp import create_server, resources, tools

#: studi0's presence marker, relative to the project root it watches.
PRESENCE_PARTS = (".s0ma", "studi0", "active.json")

#: The committed self-prompt card — a static build artifact.
SELF_PROMPT_CARD = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "s0ma_mcp"
    / "_built"
    / "self_prompt_card.md"
)

#: The exact line a watched session's rules end with. Frozen by the M8
#: bench measurement — kept here as one literal so a drift in the
#: authored concatenation reads as a diff, not as a passing test.
NARRATION_RULE = (
    "studi0 is watching this session: narrate each MAIN MOVEMENT "
    "(starting a task, moving to a different part of the system, "
    "completing a meaningful checkpoint — movements, not keystrokes) by "
    "appending ONE line to .s0ma/studi0/session.jsonl before or as you "
    'start it: {"type": "work.narrated", "movement": "<what you are '
    'doing>", "why": "<why>", "subjects": ["module::Name"], "phase": '
    '"orient|author|verify|move_on"}'
)

#: What a rules list looks like when NOTHING conditional applies (see
#: ``conftest.mainline_rules``): the canonical rules plus F7's
#: unconditional docs line, which sits below the conditional feedback
#: line and above this file's frozen narration line.
MAINLINE_RULES = mainline_rules()

#: Every tool the server serves. Narration is not among them and must not
#: become one — M11 deliberately did not build it (V4 stays in reserve).
MAINLINE_TOOLS = {
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
    "verify_host",
    # FD-5 (FB-M8): the feedback pair.
    "prepare_feedback",
    "submit_feedback",
    # F7: the documentation read surface.
    "learn_s0ma",
}


def arm(root: Path, *, pid: int | None = None, port: int = 51234) -> Path:
    """Write a studi0 presence marker under *root*; return its path."""
    return write_marker(root, json.dumps(
        {"pid": os.getpid() if pid is None else pid, "port": port},
        sort_keys=True,
    ))


def write_marker(root: Path, text: str) -> Path:
    """Write *text* as the presence marker under *root*; return its path."""
    marker = root.joinpath(*PRESENCE_PARTS)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(text, encoding="utf-8")
    return marker


def dead_pid() -> int:
    """A process id that has certainly exited by the time this returns."""
    with subprocess.Popen([sys.executable, "-c", ""]) as process:
        process.wait()
        return int(process.pid)


def rules_for(call: str, root: Path) -> list[str]:
    """The rules list one rules-bearing tool result carries for *root*."""
    results: dict[str, Any] = {
        "describe_server": lambda: tools.describe_server_tool(),
        "project_status": lambda: tools.project_status_tool(str(root)),
        "init_project": lambda: tools.init_project_tool(str(root)),
        "scaffold_module": lambda: tools.scaffold_module_tool(str(root), "probe"),
    }
    rules: list[str] = results[call]()["rules"]
    return rules


#: The three channels that take a project root, and so can be watched.
ROOTED_CHANNELS = ("project_status", "init_project", "scaffold_module")


@pytest.fixture()
def watched(tmp_path: Path) -> Path:
    """A real project with a live studi0 presence marker in it."""
    root = make_project(tmp_path / "proj", sources={})
    arm(root)
    return root


# ---------------------------------------------------------------------------
# Absent: byte-identical to mainline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("call", ROOTED_CHANNELS)
def test_no_studi0_means_byte_identical_rules(call: str, tmp_path: Path) -> None:
    """The feature costs nothing at all in a session with no viewer."""
    root = make_project(tmp_path / "proj", sources={})
    assert not root.joinpath(*PRESENCE_PARTS).exists()

    assert rules_for(call, root) == MAINLINE_RULES


def test_describe_server_carries_the_canonical_rules() -> None:
    """describe_server names no project, so it has no presence to read."""
    assert tools.describe_server_tool()["rules"] == MAINLINE_RULES


def test_describe_server_never_narrates_even_beside_a_live_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No root in scope is answered honestly — no root, no presence.

    describe_server answers about the SERVER, not about a project, so
    there is no project root to check a marker against. Nothing is
    guessed from the process's working directory: a live marker sitting
    right there changes nothing.
    """
    root = make_project(tmp_path / "proj", sources={})
    arm(root)
    monkeypatch.chdir(root)

    assert tools.describe_server_tool()["rules"] == MAINLINE_RULES


# ---------------------------------------------------------------------------
# Present: exactly one line, exactly these bytes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("call", ROOTED_CHANNELS)
def test_a_live_studi0_appends_the_frozen_line(call: str, watched: Path) -> None:
    """All three rooted channels ride one ``_survival_rules()``."""
    rules = rules_for(call, watched)

    assert rules[:-1] == MAINLINE_RULES
    assert rules[-1] == NARRATION_RULE
    assert len(rules) == len(MAINLINE_RULES) + 1


def test_the_line_is_one_line_carrying_the_whole_contract(watched: Path) -> None:
    """NFR-5 context economy: one rule, sink and record shape included."""
    rule = rules_for("project_status", watched)[-1]

    assert "\n" not in rule
    for marker in (
        "studi0 is watching this session:",
        "MAIN MOVEMENT",
        "movements, not keystrokes",
        ".s0ma/studi0/session.jsonl",
        '{"type": "work.narrated"',
        "orient|author|verify|move_on",
    ):
        assert marker in rule, marker


def test_the_narration_ask_is_valid_json_after_the_colon(watched: Path) -> None:
    """The shape the agent is asked to append parses as a JSON object."""
    rule = rules_for("project_status", watched)[-1]
    record = json.loads(rule[rule.index("{") :])

    assert set(record) == {"type", "movement", "why", "subjects", "phase"}
    assert record["type"] == "work.narrated"
    assert record["phase"] == "orient|author|verify|move_on"


def test_an_already_initialized_project_narrates_too(watched: Path) -> None:
    """init_project's idempotent branch carries the rules, so it carries this."""
    first = tools.init_project_tool(str(watched))
    again = tools.init_project_tool(str(watched))

    assert again["changed"] is False
    assert first["rules"] == again["rules"]
    assert again["rules"][-1] == NARRATION_RULE


def test_a_directory_that_is_not_a_project_narrates(tmp_path: Path) -> None:
    """The bootstrap moment is watched like any other (project_status F3)."""
    root = tmp_path / "bare"
    root.mkdir()
    arm(root)

    result = tools.project_status_tool(str(root))
    assert result["is_project"] is False
    assert result["rules"][-1] == NARRATION_RULE


# ---------------------------------------------------------------------------
# Absent by evidence: dead, malformed, unreadable
# ---------------------------------------------------------------------------


def test_a_dead_pid_is_a_stale_marker(tmp_path: Path) -> None:
    """An unclean shutdown leaves the file; the pid is what tells the truth."""
    root = make_project(tmp_path / "proj", sources={})
    arm(root, pid=dead_pid())

    assert tools.project_status_tool(str(root))["rules"] == MAINLINE_RULES


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("empty", ""),
        ("not json", "studi0 was here"),
        ("truncated", '{"pid": 1, "por'),
        ("json but not an object", '[{"pid": 1, "port": 2}]'),
        ("json scalar", '"running"'),
        ("no pid", '{"port": 51234}'),
        ("no port", '{"pid": 1}'),
        ("string pid", '{"pid": "1", "port": 51234}'),
        ("string port", '{"pid": 1, "port": "51234"}'),
        ("boolean pid", '{"pid": true, "port": 51234}'),
        ("negative pid", '{"pid": -1, "port": 51234}'),
        ("zero pid", '{"pid": 0, "port": 51234}'),
    ],
)
def test_a_malformed_marker_is_absent_not_an_error(
    label: str, text: str, tmp_path: Path
) -> None:
    """Nothing about the marker can turn a tool result into a failure."""
    root = make_project(tmp_path / "proj", sources={})
    write_marker(root, text)

    result = tools.project_status_tool(str(root))
    assert result["ok"] is True, label
    assert result["rules"] == MAINLINE_RULES, label
    assert "error" not in result, label


def test_an_unreadable_marker_is_absent(tmp_path: Path) -> None:
    """A directory where the file should be reads as no marker at all."""
    root = make_project(tmp_path / "proj", sources={})
    root.joinpath(*PRESENCE_PARTS).mkdir(parents=True)

    result = tools.project_status_tool(str(root))
    assert result["ok"] is True
    assert result["rules"] == MAINLINE_RULES


def test_a_marker_in_a_neighbouring_project_is_not_this_project(
    tmp_path: Path,
) -> None:
    """Presence is per project root, never ambient."""
    watched_root = make_project(tmp_path / "watched", sources={})
    other_root = make_project(tmp_path / "other", sources={})
    arm(watched_root)

    assert tools.project_status_tool(str(other_root))["rules"] == MAINLINE_RULES
    assert tools.project_status_tool(str(watched_root))["rules"][-1] == (
        NARRATION_RULE
    )


# ---------------------------------------------------------------------------
# Per render, never cached
# ---------------------------------------------------------------------------


def test_starting_and_stopping_studi0_mid_session_is_noticed(
    tmp_path: Path,
) -> None:
    """The check is a stat per render — no caching, no daemon, no restart.

    This is the whole reason the condition is a file rather than an
    environment variable read at boot: the same server process, in the
    same conversation, answers differently as the viewer comes and goes.
    """
    root = make_project(tmp_path / "proj", sources={})
    canonical = MAINLINE_RULES

    assert tools.project_status_tool(str(root))["rules"] == canonical

    marker = arm(root)
    assert tools.project_status_tool(str(root))["rules"][-1] == NARRATION_RULE

    marker.unlink()
    assert tools.project_status_tool(str(root))["rules"] == canonical

    arm(root)
    assert tools.project_status_tool(str(root))["rules"][-1] == NARRATION_RULE


def test_the_helper_reads_the_marker_on_every_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Counted, so "no caching" is observed rather than assumed."""
    root = make_project(tmp_path / "proj", sources={})
    arm(root)
    probes: list[int] = []
    real_alive = tools._process_alive

    def _counting_alive(pid: int) -> bool:
        probes.append(pid)
        return bool(real_alive(pid))

    monkeypatch.setattr(tools, "_process_alive", _counting_alive)
    for _ in range(3):
        tools.project_status_tool(str(root))

    assert probes == [os.getpid()] * 3


# ---------------------------------------------------------------------------
# The line stays dynamic: no static artifact carries it
# ---------------------------------------------------------------------------


def test_the_served_surface_carries_no_narration_tool(watched: Path) -> None:
    """Narration is result content, not surface — no narrate tool (V4 reserve).

    The count moved from twelve to fourteen at FB-M8 (the FD-5 feedback
    pair) and to fifteen at F7 (learn_s0ma); the invariant this test
    guards is not the number but that narration never became a tool of
    its own.
    """
    served = {tool.name for tool in asyncio.run(create_server().list_tools())}

    assert served == MAINLINE_TOOLS
    assert len(served) == 15
    assert not [name for name in served if "narrat" in name]


def test_the_static_survival_card_never_carries_the_line(watched: Path) -> None:
    """The guide resource is a static document; the ask is per call."""
    assert "studi0 is watching" not in resources.survival_card_resource()


def test_the_self_prompt_card_never_carries_the_line(watched: Path) -> None:
    """The bounded build artifact is authored text only — nothing dynamic."""
    card = SELF_PROMPT_CARD.read_text(encoding="utf-8")

    assert "studi0 is watching" not in card
    assert len(card.encode("utf-8")) <= 2_600


# ---------------------------------------------------------------------------
# The liveness probe itself
# ---------------------------------------------------------------------------


def test_this_process_is_alive() -> None:
    assert tools._process_alive(os.getpid()) is True


def test_an_exited_process_is_not_alive() -> None:
    assert tools._process_alive(dead_pid()) is False


@pytest.mark.parametrize("pid", [0, -1, -12345])
def test_a_nonsense_pid_is_not_alive(pid: int) -> None:
    assert tools._process_alive(pid) is False


def test_the_probe_never_signals_the_process_it_asks_about() -> None:
    """The probe must observe, never disturb — on every platform.

    On Windows ``os.kill(pid, 0)`` routes to ``TerminateProcess`` and
    would kill the studi0 it was asked about, which is why the Win32
    branch opens the process for query instead. Here the guarantee is
    checked the only way it can be from inside one process: a live child
    is probed repeatedly and is still running afterwards.
    """
    with subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"],
        stdin=subprocess.PIPE,
    ) as process:
        try:
            for _ in range(5):
                assert tools._process_alive(process.pid) is True
            assert process.poll() is None
        finally:
            if process.stdin is not None:
                process.stdin.close()
            process.wait()

    assert tools._process_alive(process.pid) is False
