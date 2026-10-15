"""One topic in the bytes an agent can afford: identity, a summary, pointers.

Milestone C7 of the docs-function plan (internal) §8, task T2. The bounded
channel. Everything difficult about it follows from one rule B5 proved and
this module inherits:

    **A channel carries a fact word for word or leaves it out entirely.**

There is no third option, so this channel gets smaller by *choosing which
facts to send*, never by rewriting them shorter. It sends the identity
core, one authored short form, and a pointer to where the rest is — and
when it still does not fit, the finding names the longest thing it carries
and says so plainly, because the renderer is forbidden from fixing it.

That is why :data:`AGENT_BYTE_BUDGET` is a limit on the *record* rather
than on the renderer, and why C1 added ``ConceptRecord.summary``: B5's
finding 1 said an author needs a short form to omit down to, and every
group names its own in
:data:`~s0ma_dsl.docs_model.resolve.AGENT_SHORT_FACT`.

The declaration:

* **labels** — one line each for the identity core, at the head; the short
  form under its own label, indented;
* **order** — identity first, then the short form. A reader who stops after
  the first five lines still knows what this is and what build it came
  from;
* **envelope** — the ``Read more`` pointer, which names where the omitted
  facts are and carries none of them;
* **transformations** — a list joined onto one line, the marker an empty
  list is written as, and prose wrapped at a **declared** width and
  indented two spaces.

The width is declared rather than measured. B6 finding 5 measured the
product's own ``--help`` at 5,256 bytes on a 40-column terminal and 3,436
on a 200-column one; a documentation build that renders differently on two
machines is not a build (plan §2.1).
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.providers import Finding
from s0ma_dsl.docs_model.resolve import (
    AGENT_SHORT_FACT,
    IDENTITY_FACTS,
    LIST_FACTS,
    DocsResolveError,
    FactValue,
    PresentationSpec,
    TopicView,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "AGENT_BYTE_BUDGET",
    "CHANNEL",
    "DOC_TOPIC_OVERSIZED",
    "EMPTY_MARKER",
    "ENVELOPE",
    "INDENT",
    "TRANSFORMATIONS",
    "WRAP_WIDTH",
    "check_budget",
    "extract",
    "render_agent",
    "spec_for",
    "undeclared_labels",
]

#: This channel's name.
CHANNEL = "agent"

#: How many bytes one topic answer may take on this channel.
#:
#: **Declared once, here.** A budget written in two places is a budget that
#: drifts, and B5 asserted the same property of its own constant.
#:
#: Where the number comes from, and why it is not B5's 1,400.
#:
#: The nearest real precedent in the product is the self-prompt card's
#: 2,600-byte ceiling (``packages/s0ma-mcp/tests/test_narration_rule.py``),
#: which bounds one artifact *pushed* once per session. A topic answer is
#: *pulled* many times in a session, so its budget has to sit below that.
#: B5 measured its own bounded channel at 1,004–1,159 bytes and set 1,400,
#: leaving about 240 bytes of headroom over its largest topic.
#:
#: This channel is smaller, and the reason is B5's own finding 1. B5's
#: bounded channel had to carry ``plain_definition`` in full, because the
#: model had no authored short form to fall back to and rule (b) forbids
#: making one at render time. C1 acted on that finding and added
#: ``ConceptRecord.summary``, so this channel carries the *summary* — 76 to
#: 136 bytes across the corpus — and omits the definition entirely.
#:
#: Re-measured on this tree rather than inherited: across all 398 topics
#: the largest answer this channel produces is 531 bytes. The number below
#: leaves 219 bytes of headroom, which is B5's proportion almost exactly,
#: and it is deliberately *less than the shortest ``plain_definition`` in
#: the corpus* (307 bytes; the median is 424). That is the property the
#: number exists for: the slack must have room for the envelope to grow a
#: line and no room to absorb a second teaching field unnoticed. B5's 1,400
#: here would have had room for two, and a proof holds the arithmetic.
AGENT_BYTE_BUDGET = 750

#: The column prose is wrapped at, and the indent it is written under.
WRAP_WIDTH = 72
INDENT = "  "

#: What a list with nothing in it is written as, matching the human page's
#: marker so a reader who meets both meets one convention.
EMPTY_MARKER = "none recorded"

#: The pointer line's label. Envelope: it says where the omitted facts are
#: and carries none of them.
_POINTER_LABEL = "Read more"

#: The blocks this answer adds that carry no fact.
ENVELOPE: tuple[str, ...] = (_POINTER_LABEL,)

#: The named transformations this channel applies (B5 clause 1).
TRANSFORMATIONS: tuple[str, ...] = (
    "identity is written at the head, one fact to a line",
    "a list is joined onto one line, items separated by a comma and a space",
    "an empty list is written as 'none recorded'",
    f"prose is wrapped at {WRAP_WIDTH} columns and indented two spaces",
    "prose is written under its label rather than beside it",
    "line endings: line feed, with exactly one at the end",
)

#: Architecture plan §11: a topic answer does not fit the channel it is
#: served on. Seeded by B5, which proved the finding has to name the field
#: to shorten because the renderer may not shorten it.
DOC_TOPIC_OVERSIZED = "DOC_TOPIC_OVERSIZED"

#: Where the identity core is written on this channel, in the order it is
#: written. Not :data:`~s0ma_dsl.docs_model.resolve.IDENTITY_FACTS`'s own
#: order, which is alphabetical: a reader who stops after the first line
#: should have the id, and a reader who stops after the third should know
#: what build this came from.
_IDENTITY_LABELS: Mapping[str, str] = {
    "topic_id": "Topic",
    "release_version": "Release",
    "snapshot_hash": "Snapshot",
    "example_ids": "Examples",
    "authority_refs": "Decided by",
}

#: What each group's short form is labelled. One label per group rather
#: than one per fact, because the same fact name means a different thing on
#: a surface and on a concept.
_SHORT_LABELS: Mapping[str, str] = {
    "concepts": "In short",
    "surfaces": "What it does",
    "journeys": "What this path is for",
    "sequences": "",
    "documents": "Title",
    "authorities": "Which document",
}


def spec_for(group: str) -> PresentationSpec:
    """This channel's declaration for one bundle group."""
    try:
        short = AGENT_SHORT_FACT[group]
    except KeyError:
        raise DocsResolveError(f"{group!r} is not a bundle group") from None
    labels = dict(_IDENTITY_LABELS)
    order = list(_IDENTITY_LABELS)
    if short:
        labels[short] = _SHORT_LABELS[group]
        order.append(short)
    return PresentationSpec(
        channel=CHANNEL,
        labels=labels,
        order=tuple(order),
        envelope=ENVELOPE,
        transformations=TRANSFORMATIONS,
        width=WRAP_WIDTH,
    )


def _wrapped(text: str) -> list[str]:
    """Prose at the declared width, indented, never breaking an identifier."""
    return textwrap.wrap(
        text,
        width=WRAP_WIDTH,
        initial_indent=INDENT,
        subsequent_indent=INDENT,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [INDENT + EMPTY_MARKER]


def _pointer(view: TopicView, omitted: bool) -> list[str]:
    """The line that says where the facts this answer left out are.

    A bounded channel omits and points; it never paraphrases. The pointer
    names the topic by its id and stops there — the id is what every other
    channel answers to, and a per-channel spelling is how one topic becomes
    two (B6 finding 4). It deliberately does not enumerate what was left
    out: the list would cost more bytes than it saves a reader, and the
    page it points at is where the answer actually is.
    """
    if not omitted:
        return []
    return [
        "",
        f"{_POINTER_LABEL}:",
        *_wrapped(
            f"the full page for {view.id} carries every fact left out here, "
            f"word for word."
        ),
    ]


def render_agent(view: TopicView, spec: PresentationSpec | None = None) -> str:
    """One topic in the bytes an agent can afford.

    Rendering never fails on size. :func:`check_budget` reports it, because
    an over-budget answer is a fact about the writing that an author has to
    act on, and refusing to render would hide the thing they need to read.
    """
    declared = spec if spec is not None else spec_for(view.group)
    declared.check(view)
    carried = declared.carries()
    lines: list[str] = []
    prose: list[str] = []
    for fact in declared.order:
        label = declared.label_of(fact)
        value = view.value(fact)
        if fact in IDENTITY_FACTS:
            written = ", ".join(value) if isinstance(value, tuple) else value
            lines.append(f"{label}: {written or EMPTY_MARKER}")
        elif isinstance(value, tuple):
            lines.append(f"{label}: {', '.join(value) or EMPTY_MARKER}")
        else:
            prose.extend(["", f"{label}:", *_wrapped(value)])
    omitted = any(name not in carried for name in view.facts)
    return "\n".join([*lines, *prose, *_pointer(view, omitted)]) + "\n"


def _longest(view: TopicView, carried: frozenset[str]) -> tuple[str, int]:
    """The biggest thing this answer carries, and how big it is in bytes."""
    sized = {
        name: len(
            (", ".join(value) if isinstance(value, tuple) else value).encode("utf-8")
        )
        for name, value in view.facts.items()
        if name in carried
    }
    # Sorted by size then by name, so a tie names the same field every run.
    name = max(sorted(sized), key=lambda item: sized[item])
    return name, sized[name]


def check_budget(view: TopicView, text: str) -> list[Finding]:
    """Is this answer small enough for the channel it is served on?

    ``DOC_TOPIC_OVERSIZED``.
    The finding names the longest field the answer carries and tells the
    author to shorten it *in the topic*, because rule (b) leaves the
    renderer no way to send a smaller version of the same fact. B5 proved
    the remediation has to say that out loud, or an author reads
    "over budget" and goes looking for a renderer setting that does not
    exist.
    """
    size = len(text.encode("utf-8"))
    if size <= AGENT_BYTE_BUDGET:
        return []
    field, field_size = _longest(view, spec_for(view.group).carries())
    return [
        Finding(
            code=DOC_TOPIC_OVERSIZED,
            location="",
            message=(
                f"{view.id} comes to {size} bytes as an agent answer, "
                f"{size - AGENT_BYTE_BUDGET} over the "
                f"{AGENT_BYTE_BUDGET}-byte limit. The longest thing it "
                f"carries is {field}, at {field_size} bytes."
            ),
            remediation=(
                f"shorten {field} in the topic itself. This channel repeats it "
                f"word for word — it has no shorter version to send — so the "
                f"answer only gets smaller when the writing does."
            ),
        )
    ]


def extract(text: str, spec: PresentationSpec) -> dict[str, FactValue]:
    """Read the facts back out of a rendered answer, declaration in hand.

    The wrapping and the indent are undone here, which is what lets a
    wrapped terminal block and an unwrapped page paragraph compare equal.
    """
    single: dict[str, str] = {}
    blocks: dict[str, list[str]] = {}
    current = ""
    for line in text.split("\n"):
        if line.startswith(INDENT):
            if current:
                blocks[current].append(line.strip())
            continue
        label, separator, rest = line.partition(":")
        if not separator:
            current = ""
            continue
        current = ""
        if rest.strip():
            single[label] = rest.strip()
        else:
            current = label
            blocks[label] = []

    found: dict[str, FactValue] = {}
    for fact in spec.order:
        label = spec.label_of(fact)
        if label in single:
            written = single[label]
        elif label in blocks:
            written = " ".join(blocks[label])
        else:
            continue
        if fact in LIST_FACTS:
            found[fact] = () if written == EMPTY_MARKER else tuple(written.split(", "))
        else:
            found[fact] = "" if written == EMPTY_MARKER else written
    return found


def undeclared_labels(text: str, spec: PresentationSpec) -> tuple[str, ...]:
    """Labels in the answer that no declaration accounts for.

    B5 clause 1's enforcement for this channel. A line that reads like a
    label and names nothing declared is a claim nobody can check.
    """
    declared = {spec.label_of(fact) for fact in spec.order} | set(spec.envelope)
    found: list[str] = []
    for line in text.split("\n"):
        if line.startswith(INDENT) or not line.strip():
            continue
        label = line.partition(":")[0]
        if label != line and label not in declared:
            found.append(label)
    return tuple(sorted(set(found)))
