"""One topic as a page a person can read.

Milestone C7 of the docs-function plan (internal) §8, task T2. Markdown,
written for the reader the product writes for: someone intelligent who
does not program, and who wants to know what a thing is, why it is there,
when to reach for it and when not to.

**The renderer writes headings; it never writes facts.** Every sentence on
the page is authored prose from a record, reproduced word for word. The
only words this module contributes are the section headings, the identity
labels and the marker an empty list is written as — and all of them are
declared, so a gate can tell the difference between a heading and a claim.
That is B5's residue clause 1 applied to a page: anything in front of a
reader that is neither declared presentation nor the carrier of a declared
fact is a violation.

The declaration:

* **labels** — the label's own prefix decides the layout, so the
  declaration *is* the design rather than a description of it. ``#`` is the
  page title, ``##`` is a section heading, ``-`` is a bullet in the
  identity block at the foot;
* **order** — title, then sections in :data:`SECTION_FACTS`, then the
  identity block. Deliberately not the record's field order, and a proof
  asserts the two are permutations of each other so a fact cannot fall out
  of the page by being left off one table;
* **envelope** — the identity block's heading and the rule above it, which
  carry no fact;
* **transformations** — heading wording and level, section order, bullet
  markers, the fenced block a written form goes in, the backticks around
  an identifier, and the marker an empty list is written as.

Prose is **not** wrapped here. A Markdown paragraph is one line, and the
bounded channel is the one that wraps — which is exactly the asymmetry the
residue comparison has to survive, and does, because whitespace collapses
on the way back in.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.resolve import (
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
    "CHANNEL",
    "EMPTY_MARKER",
    "ENVELOPE",
    "IDENTITY_HEADING",
    "SECTION_FACTS",
    "TITLE_FACT",
    "TRANSFORMATIONS",
    "extract",
    "render_human",
    "spec_for",
    "undeclared_headings",
]

#: This channel's name.
CHANNEL = "human"

#: What a list with nothing in it is written as. One marker for the whole
#: channel, so a reader meets the same words wherever a list runs out, and
#: a proof asserts no fact in the corpus is spelled this way — an encoding
#: a real value could collide with is an encoding that loses data.
EMPTY_MARKER = "none recorded"

#: The heading over the identity block at the foot of every page.
IDENTITY_HEADING = "## Identity"

#: The blocks this page adds that carry no fact.
ENVELOPE: tuple[str, ...] = (IDENTITY_HEADING, "---")

#: The named transformations this channel applies (B5 clause 1).
TRANSFORMATIONS: tuple[str, ...] = (
    "heading wording: a plain-language phrase per fact, not the field name",
    "heading level: one '#' for the title, two for every section",
    "section order: as declared, which is not the record's field order",
    "a list is written one item to a line after a hyphen",
    "an identifier in a list is written between backticks",
    "a written form is written inside a fenced block, one line to a line",
    "an empty list is written as one item reading 'none recorded'",
    "a fact whose value is empty and is not identity has its section left out",
    "the identity block is written at the foot, its values between backticks",
    "prose is written unwrapped, one paragraph to a line",
    "line endings: line feed, with exactly one at the end",
)

#: The list facts whose items are identifiers, and so are written between
#: backticks. The prose-shaped lists — a step's purpose, a recovery path —
#: are not, because a sentence in a monospaced box reads as a mistake.
_BACKTICKED: frozenset[str] = frozenset(
    {
        "authority_refs",
        "authority_sources",
        "component_refs",
        "concepts_required",
        "concepts_taught",
        "covers",
        "delegations",
        "errors",
        "example_ids",
        "related_concepts",
        "side_effects",
        "step_surfaces",
        "step_topics",
    }
)

#: The fact each group's page is titled with. Three groups carry a name a
#: person would use; the other three do not, so their page is titled with
#: the id — which is identity, and is therefore left out of the block at
#: the foot rather than written twice.
TITLE_FACT: Mapping[str, str] = {
    "concepts": "term",
    "surfaces": "public_name",
    "documents": "title",
    "journeys": "topic_id",
    "sequences": "topic_id",
    "authorities": "topic_id",
}

#: The sections of each group's page, in the order a reader meets them.
#: Written out rather than derived, because the order is a design decision
#: about a page and not a property of a record — a concept page answers
#: "what is it" before "what decides it", and the record's field order has
#: no opinion about that. What keeps the two honest is the proof that each
#: row here is a permutation of that group's facts minus its title.
SECTION_FACTS: Mapping[str, tuple[str, ...]] = {
    "concepts": (
        "summary",
        "plain_definition",
        "purpose",
        "use_when",
        "do_not_use_when",
        "syntax",
        "related_concepts",
        "example_ids",
        "authority_refs",
        "authority_sources",
    ),
    "surfaces": (
        "intent",
        "channel",
        "component_refs",
        "manual_exception",
        "side_effects",
        "errors",
        "read_from",
        "example_ids",
        "authority_refs",
        "authority_sources",
    ),
    "journeys": (
        "intent",
        "concepts_required",
        "step_surfaces",
        "step_purposes",
        "step_outcomes",
        "approval_boundaries",
        "recovery_paths",
        "concepts_taught",
        "example_ids",
        "authority_refs",
    ),
    "sequences": ("step_topics", "step_purposes", "example_ids", "authority_refs"),
    "documents": (
        "canonical_source",
        "prose_locator",
        "authority",
        "covers",
        "example_ids",
        "authority_refs",
        "authority_sources",
    ),
    "authorities": (
        "authority_class",
        "written_in",
        "section",
        "status",
        "content_sha256",
        "delegations",
        "example_ids",
        "authority_refs",
    ),
}

#: Every section heading, per fact. A plain-language phrase rather than a
#: field name: the reader is not reading a schema.
_HEADINGS: Mapping[str, str] = {
    "example_ids": "Worked examples",
    "authority_refs": "What decides this",
    "authority_sources": "Where to read the decision",
    # Concepts.
    "summary": "In short",
    "plain_definition": "What it is",
    "purpose": "Why it exists",
    "use_when": "When to use it",
    "do_not_use_when": "When not to use it",
    "syntax": "How it is written",
    "related_concepts": "Related ideas",
    # Served capabilities.
    "channel": "Where it is served",
    "intent": "What it does",
    "component_refs": "What implements it",
    "manual_exception": "Why some of this was written by hand",
    "side_effects": "What it changes",
    "errors": "What can go wrong",
    "read_from": "Where these facts were read",
    # Journeys and teaching orders.
    "step_surfaces": "The steps, in order",
    "step_purposes": "Why each step",
    "step_outcomes": "What you should see",
    "approval_boundaries": "Where you are asked first",
    "recovery_paths": "If something goes wrong",
    "concepts_required": "What to know before you start",
    "concepts_taught": "What you learn on the way",
    "step_topics": "What is taught, in order",
    # Catalog rows.
    "canonical_source": "Where the file is",
    "prose_locator": "Where the words are",
    "authority": "The authority this document is",
    "covers": "What it covers",
    # Written authorities.
    "authority_class": "What kind of authority",
    "written_in": "Which document",
    "section": "Which section",
    "status": "Standing",
    "content_sha256": "Fingerprint of the source",
    "delegations": "What it hands to someone else",
}

#: The few headings that have to change with the group, because one fact
#: name means two things. ``intent`` on a served capability is what it
#: does; on a journey it is what the whole path is for, and a page that
#: called them the same thing would be reading a field name aloud.
_GROUP_HEADINGS: Mapping[tuple[str, str], str] = {
    ("journeys", "intent"): "What this path is for",
}

#: The identity facts written as bullets in the block at the foot.
_FOOTER: Mapping[str, str] = {
    "topic_id": "Topic id",
    "release_version": "Release",
    "snapshot_hash": "Documentation snapshot",
}

_HEADING_LINE = re.compile(r"^(#{1,6})\s+(.*)$")
_FOOTER_LINE = re.compile(r"^- ([^:]+): `(.*)`$")
_BACKTICKED_ITEM = re.compile(r"^`(.*)`$", re.DOTALL)

#: The fence a written form is written inside, and the word that opens it.
#: Matched by prefix everywhere, because the opening fence carries the word
#: and the closing one does not — and because a syntax skeleton legitimately
#: contains a line that would otherwise read as a heading or as the rule
#: above the identity block (``nerve``'s own skeleton contains ``---``).
_FENCE = "```"
_OPEN_FENCE = "```text"
_RULE = "---"


def spec_for(group: str) -> PresentationSpec:
    """This channel's declaration for one bundle group."""
    try:
        sections = SECTION_FACTS[group]
    except KeyError:
        raise DocsResolveError(f"{group!r} is not a bundle group") from None
    title = TITLE_FACT[group]
    footer = tuple(fact for fact in _FOOTER if fact != title)
    labels = {title: "# "}
    for fact in sections:
        heading = _GROUP_HEADINGS.get((group, fact), _HEADINGS[fact])
        labels[fact] = f"## {heading}"
    for fact in footer:
        labels[fact] = f"- {_FOOTER[fact]}"
    return PresentationSpec(
        channel=CHANNEL,
        labels=labels,
        order=(title, *sections, *footer),
        envelope=ENVELOPE,
        transformations=TRANSFORMATIONS,
    )


def _is_empty(value: FactValue) -> bool:
    return not value if isinstance(value, tuple) else not value.strip()


def _section_body(fact: str, value: FactValue) -> list[str]:
    """One section's lines, below its heading."""
    if isinstance(value, str):
        return [value]
    if fact == "syntax":
        return [_OPEN_FENCE, *(value or (EMPTY_MARKER,)), _FENCE]
    if not value:
        return [f"- {EMPTY_MARKER}"]
    if fact in _BACKTICKED:
        return [f"- `{item}`" for item in value]
    return [f"- {item}" for item in value]


def render_human(view: TopicView, spec: PresentationSpec | None = None) -> str:
    """One topic as a readable page.

    A section whose fact is empty is left out, unless the fact is part of
    the identity core — those five are carried on every channel whatever
    their value, because rule (a) says presentation cannot drop identity,
    and an empty list that is *stated* to be empty is a fact where a
    missing section is a silence.
    """
    declared = spec if spec is not None else spec_for(view.group)
    declared.check(view)
    lines: list[str] = []
    footer: list[str] = []
    for fact in declared.order:
        label = declared.label_of(fact)
        value = view.value(fact)
        if label.startswith("- "):
            written = ", ".join(value) if isinstance(value, tuple) else value
            footer.append(f"{label}: `{written or EMPTY_MARKER}`")
        elif label.startswith("# "):
            lines.extend([f"# {value}", ""])
        elif _is_empty(value) and fact not in IDENTITY_FACTS:
            continue
        else:
            lines.extend([label, "", *_section_body(fact, value), ""])
    lines.extend([_RULE, "", IDENTITY_HEADING, "", *footer])
    return "\n".join(lines) + "\n"


def _sections(text: str) -> dict[str, list[str]]:
    """Every heading in the page, with the lines under it.

    Fence-aware, because a written form may legitimately contain a line
    that begins with a hash, and a horizontal rule ends the section above
    it so the envelope's own lines are never read as somebody's prose.
    """
    found: dict[str, list[str]] = {}
    current = ""
    fenced = False
    for line in text.split("\n"):
        if line.strip().startswith(_FENCE):
            fenced = not fenced
        elif not fenced:
            if line.strip() == _RULE:
                current = ""
                continue
            match = _HEADING_LINE.match(line)
            if match is not None:
                current = f"{match.group(1)} {match.group(2)}"
                found[current] = []
                continue
        if current:
            found[current].append(line)
    return found


def _read_body(fact: str, lines: list[str]) -> FactValue:
    """One section's lines back into the fact they carry."""
    body = [line for line in lines if line.strip()]
    if fact not in LIST_FACTS:
        return " ".join(body)
    if fact == "syntax":
        inside = [line for line in lines if not line.strip().startswith(_FENCE)]
        while inside and not inside[0].strip():
            inside.pop(0)
        while inside and not inside[-1].strip():
            inside.pop()
        return () if inside == [EMPTY_MARKER] else tuple(inside)
    if body == [f"- {EMPTY_MARKER}"]:
        return ()
    items = [line[2:] for line in body if line.startswith("- ")]
    if fact not in _BACKTICKED:
        return tuple(items)
    # Only the delimiters come off, matched at both ends at once. Stripping
    # backticks would be lossy for an item that legitimately ends in one —
    # a PRD section anchor quotes a package name that way — and a lossy
    # read-back is a residue that agrees with a page it has corrupted.
    read: list[str] = []
    for item in items:
        matched = _BACKTICKED_ITEM.match(item)
        read.append(matched.group(1) if matched is not None else item)
    return tuple(read)


def extract(text: str, spec: PresentationSpec) -> dict[str, FactValue]:
    """Read the facts back out of a rendered page, declaration in hand.

    Only the declaration is used: a heading this spec does not name is not
    consulted, and a section this spec names but the page does not carry is
    reported as absent rather than guessed at. That is what makes an edit
    to an already-rendered page change what this returns — B5 clause 2, and
    the reason the residue test is not a renderer talking to itself.
    """
    sections = _sections(text)
    footer_lines = sections.get(IDENTITY_HEADING, [])
    title_heading = next((key for key in sections if key.startswith("# ")), None)
    found: dict[str, FactValue] = {}
    for fact in spec.order:
        label = spec.label_of(fact)
        if label.startswith("# "):
            if title_heading is not None:
                found[fact] = title_heading[2:]
        elif label.startswith("- "):
            for line in footer_lines:
                match = _FOOTER_LINE.match(line)
                if match is not None and match.group(1) == label[2:]:
                    written = match.group(2)
                    found[fact] = "" if written == EMPTY_MARKER else written
        elif label in sections:
            found[fact] = _read_body(fact, sections[label])
    return found


def undeclared_headings(text: str, spec: PresentationSpec) -> tuple[str, ...]:
    """Headings on the page that no declaration accounts for.

    B5 clause 1's enforcement for a text channel, recommended for promotion
    by its finding 6. The residue can only compare facts that are there;
    this is what sees a section somebody added that no fact backs.
    """
    declared = set(spec.envelope)
    titled = False
    for fact in spec.order:
        label = spec.label_of(fact)
        if label.startswith("# "):
            titled = True
        elif label.startswith("## "):
            declared.add(label)
    found = [
        heading
        for heading in _sections(text)
        if heading not in declared and not (titled and heading.startswith("# "))
    ]
    return tuple(sorted(found))
