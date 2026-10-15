"""One topic as canonical JSON: the machine's copy of the same facts.

Milestone C7 of the docs-function plan (internal) §8, task T2. The channel
with the least presentation of the three, which is what makes it the
useful one to read the other two against: it carries every fact the topic
has, at a declared key path, in the model's own canonical text form.

The declaration, per B5's residue clause 1
(``scripts/spikes/docs_model/spike_b5_channels/README.md``):

* **labels** — a dotted key path per fact, two levels deep: the identity
  core under ``identity``, everything else under ``topic``;
* **order** — the order the facts are read back in. The written order is
  sorted, because
  :func:`~s0ma_dsl.docs_model.serialize.canonical_json` sorts keys; the
  declared order is what an extractor walks;
* **envelope** — ``schema``, which names the model version this document
  is written against and carries no fact about the topic;
* **transformations** — key naming, two-level nesting, sorted keys,
  two-space indentation, and one trailing line feed.

Nothing here formats numbers, dates or floats: the model carries none, and
:func:`~s0ma_dsl.docs_model.serialize.to_plain` refuses one. That is why
this channel can promise the same bytes on every platform without doing
anything special to keep the promise.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from s0ma_dsl.docs_model.records import SCHEMA
from s0ma_dsl.docs_model.resolve import (
    FACT_ORDER,
    IDENTITY_FACTS,
    LIST_FACTS,
    DocsResolveError,
    FactValue,
    PresentationSpec,
    TopicView,
)
from s0ma_dsl.docs_model.serialize import canonical_json

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "CHANNEL",
    "ENVELOPE",
    "TRANSFORMATIONS",
    "extract",
    "render_json",
    "spec_for",
    "undeclared_keys",
]

#: This channel's name, used in every finding it takes part in.
CHANNEL = "json"

#: The keys this document adds that carry no fact about the topic.
ENVELOPE: tuple[str, ...] = ("schema",)

#: The named transformations this channel applies (B5 clause 1).
TRANSFORMATIONS: tuple[str, ...] = (
    "key naming: a reader-facing name per fact, not the record's field name",
    "key nesting: two levels — identity under 'identity', the rest under 'topic'",
    "key order: sorted, so the written order carries nothing",
    "indentation: two spaces",
    "line endings: line feed, with exactly one at the end",
    "an empty list is written as an empty array",
)

#: Where the identity core is written. Reader-facing names rather than the
#: record's field names, so that renaming a field in the model does not
#: rename a key somebody's tooling reads — and so that the declaration is
#: doing real work rather than repeating the record.
_IDENTITY_KEYS: Mapping[str, str] = {
    "topic_id": "identity.topic",
    "example_ids": "identity.examples",
    "authority_refs": "identity.authorities",
    "release_version": "identity.release",
    "snapshot_hash": "identity.snapshot",
}

#: Where each topical fact is written. One entry per fact name in
#: :data:`~s0ma_dsl.docs_model.resolve.FACT_ORDER`; a proof asserts the two
#: tables cover each other, so a fact added to the model without a key here
#: fails the suite rather than vanishing from this channel.
_TOPIC_KEYS: Mapping[str, str] = {
    "term": "topic.term",
    "summary": "topic.summary",
    "plain_definition": "topic.definition",
    "purpose": "topic.purpose",
    "use_when": "topic.use_when",
    "do_not_use_when": "topic.do_not_use_when",
    "syntax": "topic.syntax",
    "related_concepts": "topic.related",
    "authority_sources": "topic.decided_in",
    "public_name": "topic.served_as",
    "channel": "topic.channel",
    "intent": "topic.intent",
    "component_refs": "topic.implemented_by",
    "manual_exception": "topic.manual_exception",
    "side_effects": "topic.side_effects",
    "errors": "topic.errors",
    "read_from": "topic.read_from",
    "step_surfaces": "topic.step_surfaces",
    "step_purposes": "topic.step_purposes",
    "step_outcomes": "topic.step_outcomes",
    "approval_boundaries": "topic.approval_boundaries",
    "recovery_paths": "topic.recovery_paths",
    "concepts_required": "topic.concepts_required",
    "concepts_taught": "topic.concepts_taught",
    "step_topics": "topic.step_topics",
    "title": "topic.title",
    "canonical_source": "topic.canonical_source",
    "prose_locator": "topic.prose_locator",
    "authority": "topic.is_authority",
    "covers": "topic.covers",
    "authority_class": "topic.authority_class",
    "written_in": "topic.written_in",
    "section": "topic.section",
    "status": "topic.status",
    "content_sha256": "topic.content_sha256",
    "delegations": "topic.delegations",
}


def spec_for(group: str) -> PresentationSpec:
    """This channel's declaration for one bundle group.

    One spec per group rather than one for everything, because a spec that
    named facts a topic does not carry would put empty keys on a document
    and call them an answer.
    """
    try:
        topical = FACT_ORDER[group]
    except KeyError:
        raise DocsResolveError(f"{group!r} is not a bundle group") from None
    labels = {**_IDENTITY_KEYS, **{fact: _TOPIC_KEYS[fact] for fact in topical}}
    return PresentationSpec(
        channel=CHANNEL,
        labels=labels,
        order=(*IDENTITY_FACTS, *topical),
        envelope=ENVELOPE,
        transformations=TRANSFORMATIONS,
    )


def _plant(document: dict[str, Any], path: str, value: Any) -> None:
    """Write ``value`` at a dotted ``path``, making the branch as it goes."""
    head, _, tail = path.partition(".")
    if not tail:
        document[head] = value
        return
    branch = document.setdefault(head, {})
    if not isinstance(branch, dict):  # pragma: no cover - the tables forbid it
        raise DocsResolveError(f"{head!r} is both a value and a branch")
    _plant(branch, tail, value)


def _pick(document: Mapping[str, Any], path: str) -> Any:
    """Read whatever is at a dotted ``path``, or ``None`` for nothing."""
    head, _, tail = path.partition(".")
    held = document.get(head)
    if not tail:
        return held
    if not isinstance(held, dict):
        return None
    return _pick(held, tail)


def render_json(view: TopicView, spec: PresentationSpec | None = None) -> str:
    """One topic as this channel's canonical text.

    Every fact the topic carries is written, because this channel has no
    budget to keep and nothing to gain from omitting. That makes it the
    channel the other two are read against in practice, though the residue
    comparison does not privilege it: all three are compared against
    :func:`~s0ma_dsl.docs_model.resolve.facts_of`, never against each
    other's output.
    """
    declared = spec if spec is not None else spec_for(view.group)
    declared.check(view)
    document: dict[str, Any] = {"schema": SCHEMA}
    for fact in declared.order:
        value = view.value(fact)
        _plant(
            document,
            declared.label_of(fact),
            list(value) if isinstance(value, tuple) else value,
        )
    return canonical_json(document)


def extract(text: str, spec: PresentationSpec) -> dict[str, FactValue]:
    """Read the facts back out of a rendered document, declaration in hand.

    The comparison runs on what this found, never on the record the
    renderer started from (B5 clause 2). Editing a value in an already
    written document therefore changes what this reports, which is the
    property that stops the residue test comparing a renderer with itself.
    """
    document = json.loads(text)
    if not isinstance(document, dict):
        raise DocsResolveError("a rendered topic is an object; this text is not one")
    found: dict[str, FactValue] = {}
    for fact in spec.order:
        held = _pick(document, spec.label_of(fact))
        if held is None:
            continue
        if fact in LIST_FACTS:
            if not isinstance(held, list):
                raise DocsResolveError(f"{fact} is a list fact and was written as text")
            found[fact] = tuple(str(item) for item in held)
        else:
            if not isinstance(held, str):
                raise DocsResolveError(f"{fact} is a prose fact and was written as a list")
            found[fact] = held
    return found


def _paths(value: Any, prefix: str = "") -> set[str]:
    """Every leaf path in a document, dotted."""
    if not isinstance(value, dict):
        return {prefix}
    if not value:
        return {prefix}
    found: set[str] = set()
    for key, held in value.items():
        found |= _paths(held, f"{prefix}.{key}" if prefix else str(key))
    return found


def undeclared_keys(text: str, spec: PresentationSpec) -> tuple[str, ...]:
    """Key paths in the document that no declaration accounts for.

    B5 clause 1's enforcement, and B5 finding 6 recommended it survive
    promotion: everything else the residue compares is a fact that *is*
    there, so this is the only check that can see a claim added to a
    rendering that no fact backs.
    """
    declared = {spec.label_of(fact) for fact in spec.order} | set(spec.envelope)
    return tuple(sorted(_paths(json.loads(text)) - declared))
