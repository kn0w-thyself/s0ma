"""Every served tool carries a human-readable title (surface contract R3).

Directories that list MCP servers require a title a person can read on
every tool. The surface snapshot pins the fifteen wordings; this module
pins the *rule* behind them, so a sixteenth tool cannot arrive without
one and the two places a client may read a title cannot drift apart:

* every tool in the live surface has a title;
* the tool's own ``title`` and its ``annotations.title`` are the same
  string, because both are served from one authored value;
* the bridge refuses a malformed authored title loudly, the same way it
  refuses a malformed hint.
"""

from __future__ import annotations

import asyncio

import pytest

import s0ma_mcp
from s0ma_mcp import _TOOL_TITLE_MAX_CHARS, _parse_tool_title


def _live_tools() -> list[object]:
    server = s0ma_mcp.create_server()
    return list(asyncio.run(server.list_tools()))


def test_every_served_tool_has_a_title() -> None:
    """No tool reaches a client without a label a person can read."""
    tools = _live_tools()
    assert tools, "the live surface served no tools"
    untitled = [tool.name for tool in tools if not getattr(tool, "title", None)]  # type: ignore[attr-defined]
    assert untitled == []


def test_the_two_places_a_client_reads_a_title_agree() -> None:
    """``title`` and ``annotations.title`` come from one authored value."""
    for tool in _live_tools():
        annotations = getattr(tool, "annotations", None)
        assert annotations is not None, getattr(tool, "name", tool)
        assert annotations.title == tool.title  # type: ignore[attr-defined]


def test_every_title_is_one_short_plain_line() -> None:
    """A title is a label, not a description."""
    for tool in _live_tools():
        title = tool.title  # type: ignore[attr-defined]
        assert title == title.strip()
        assert "\n" not in title
        assert 1 <= len(title) <= _TOOL_TITLE_MAX_CHARS


@pytest.mark.parametrize(
    "bad",
    [
        "",
        " Leading space",
        "Trailing space ",
        "Two\nlines",
        "x" * (_TOOL_TITLE_MAX_CHARS + 1),
        None,
        ["Not", "a", "string"],
    ],
)
def test_a_malformed_authored_title_is_refused(bad: object) -> None:
    """The bridge fails loudly rather than serving a broken label."""
    with pytest.raises(ValueError, match="malformed mcp_tool_title"):
        _parse_tool_title("some_tool", bad)


def test_a_well_formed_title_passes_through_unchanged() -> None:
    assert _parse_tool_title("check_tool", "Check s0ma source") == "Check s0ma source"
