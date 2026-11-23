"""Reading the one line ``session-hint`` prints, for the tests that need to.

The line has up to three parts: ``systemMessage`` for the person, and in
``hookSpecificOutput.additionalContext`` whatever the model must know about
this machine followed by the standing note. The note is told apart by the words
it opens with, written out here rather than read from the launcher, so a test
cannot pass by assembling the note the way the code does.
"""

from __future__ import annotations

import json
from typing import Any

#: How the standing note begins.
NOTE_OPENING = "s0ma is available in this session: "

#: The person's part of the line stays under this, as it always has.
VISIBLE_MAX_CHARS = 600

#: The standing note's own limit.
NOTE_MAX_CHARS = 1200

#: The off line, in full: the whole of what is said when s0ma is off here.
OFF_LINE = (
    "s0ma is turned off for this project. Do not use s0ma or its tools here, "
    "do not offer studi0, and do not bring s0ma up unless the person does; "
    "/s0ma:on turns it back on."
)


def parsed(out: str) -> dict[str, Any]:
    """The one line of JSON the hook printed, parsed, with its shape checked."""
    assert out, "the hook said nothing"
    assert out.endswith("\n"), "the hook's line must end in a newline"
    body = out[:-1]
    assert "\n" not in body, f"the hook printed more than one line:\n{out}"
    assert body.isascii(), "everything the hook prints is plain ASCII"
    data = json.loads(body)
    assert isinstance(data, dict)
    assert set(data) <= {"systemMessage", "hookSpecificOutput"}, sorted(data)
    extra = data.get("hookSpecificOutput")
    if extra is not None:
        assert sorted(extra) == ["additionalContext", "hookEventName"]
        assert extra["hookEventName"] == "SessionStart"
    return data


def parts(out: str) -> tuple[str | None, str | None, str | None]:
    """``(message, context, note)``: each ``None`` when it is not there.

    *context* is what the model is told besides the note.
    """
    data = parsed(out)
    message = data.get("systemMessage")
    extra = data.get("hookSpecificOutput")
    context: str | None = None
    note: str | None = None
    if extra is not None:
        whole = str(extra["additionalContext"])
        if whole.startswith(NOTE_OPENING):
            note = whole
        elif "\n\n" + NOTE_OPENING in whole:
            context, rest = whole.split("\n\n" + NOTE_OPENING, 1)
            note = NOTE_OPENING + rest
        else:
            context = whole
    visible: dict[str, Any] = {}
    if message is not None:
        visible["systemMessage"] = message
    if context is not None:
        visible["hookSpecificOutput"] = {
            "additionalContext": context,
            "hookEventName": "SessionStart",
        }
    assert len(json.dumps(visible, sort_keys=True)) < VISIBLE_MAX_CHARS
    if note is not None:
        assert len(note) <= NOTE_MAX_CHARS, f"the note is {len(note)} characters"
        assert note.isascii()
    return (None if message is None else str(message)), context, note


def quiet_for_the_person(result: tuple[int, str, str]) -> str:
    """Assert all is well: exit 0, nothing on stderr, nothing for the person, and
    the standing note for the model. Returns the note."""
    code, out, err = result
    assert (code, err) == (0, "")
    message, context, note = parts(out)
    assert message is None, f"the person was shown {message!r}"
    assert context is None, f"the model was told {context!r} besides the note"
    assert note is not None, "the model was not given the standing note"
    return note
