"""Teaching capability for the s0ma MCP server.

Helps coding agents learn s0ma by serving the teaching content that ships
inside this package, together with live examples read from the registry
that is actually running.

**What changed, and why it had to.** This module used to map a dozen topic
keywords onto section headings of a Markdown user guide, and to find that
guide by walking up from its own ``__file__`` to a repository checkout. No
wheel has ever contained the guide, so every pip-installed copy of s0ma
answered every teaching question with "documentation files are not
available in this installation". The framework whose whole claim is that
software should carry an accurate model of itself shipped unable to say
what it was.

**How it works now** (owner decision D-9). The documentation application
generates a *core teaching slice* — one JSON file holding every idea s0ma
is built out of, every capability this package serves, and the guided
paths through the product — and that file is mirrored into
``s0ma/_teaching/slice.json``, inside the packaged tree, so the wheel
carries it. This module reads it with :mod:`json` and
:mod:`importlib.resources` and nothing else. There is no import of
s0ma-dsl, s0ma-mcp or s0ma-studi0 here and there must never be one: the
documentation application knows about core, and core knows about a file.

**Resolution order, and what is left of the old path.** A question is
answered from the slice: an exact topic id, then an alternate name, then
the topic's own term, then a term the question *says* ("what is drift"
names drift), then the twelve keyword groups this module used to map onto
guide headings — each of them re-pointed, in the generator, at the topic
that answers it now — then a ranked search over titles and summaries.
Only if the slice is *missing* does the old guide-reading path run, and
then only if a checkout guide is actually there. That is the whole
degradation ladder, and on a wheel it stops at the first rung.

**Nothing here is a copy of anything.** Every sentence the slice carries
was written once, in the documentation model, and is reproduced word for
word; the section headings are the ones the same topic's page uses; the
live component template is read off the running registry. What this module
contributes is the ordering, the labels below, and the line that says
which release and which snapshot an answer came from.

Usage::

    from s0ma.api.teaching import TeachingProvider

    teacher = TeachingProvider(registry)
    lesson = teacher.learn_topic("nerve")
    lesson = teacher.learn_topic("creating components")
    template = teacher.get_component_template(kind="SERVICE")
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from s0ma.decorators import internal

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from s0ma.registry import ComponentRegistry

__all__ = ["TeachingProvider"]


# ---------------------------------------------------------------------------
# The packaged teaching slice
# ---------------------------------------------------------------------------

#: The slice format this reader understands. A file naming any other
#: version is refused rather than half-read: the house idiom from
#: ``s0ma_dsl.ir.schema`` — one constant, one error, one check a reader
#: makes before it trusts a byte.
SLICE_SCHEMA = "s0ma-core-teaching@1"

#: The channel word that means "this documentation describes a cut
#: release". Every other word this reader meets is a channel that has to be
#: *shown* to the reader, which is the whole of the rule below.
#:
#: The word is duplicated here rather than imported because D-9 forbids the
#: upward dependency that importing it would create, and a wrong copy is
#: not a silent failure: the slice generator writes the field, this reader
#: renders it, and ``scripts/wheel_smoke.py`` compares the rendered line
#: against the release manifest's own channel (H2). A copy that drifted
#: would fail that comparison rather than quietly relabel a release.
RELEASE_CHANNEL = "release"

#: What a slice that does not say is treated as. A build nobody told is a
#: release **is not one** (architecture §13.2), and the failure mode worth
#: designing against is preview documentation presenting itself as the
#: installed release — so the cautious word is the default, and a slice
#: written before H2 reads as preview rather than as released.
DEFAULT_BUILD_CHANNEL = "preview"

#: Where the packaged slice lives, as package data. Read through
#: :mod:`importlib.resources` for the reason ``s0ma_mcp`` reads its own
#: packaged documents that way: it is the one lookup that works from an
#: installed wheel, an editable install and a zip import alike, and none of
#: the three is allowed to be the only one that works.
SLICE_PACKAGE = "s0ma"
SLICE_RESOURCE = ("_teaching", "slice.json")

#: The same file where a repository checkout keeps it. Used only when the
#: packaged copy is missing — a state a healthy installation never reaches,
#: because the file ships inside the package and a drift gate in this
#: package's own suite holds the two byte-identical.
CHECKOUT_SLICE = ("docs", "_generated", "core-teaching-slice.json")

#: How many directories above this file to look for that checkout. Six is
#: how many it takes to get from ``packages/s0ma-core/src/s0ma/api/`` to
#: the repository root, counting the root itself. The walk is bounded so
#: that a package installed somewhere deep cannot wander up into an
#: unrelated directory that happens to have a ``docs/`` in it.
CHECKOUT_SEARCH_DEPTH = 6

#: The prefix the slice's navigation entries carry. They are lists rather
#: than topics — "glossary" is a request for one — and this module tells
#: them apart by the prefix so a list is rendered as a list.
INDEX_PREFIX = "index:"

#: The navigation entry a question that resolved to nothing falls back to.
ALL_INDEX = f"{INDEX_PREFIX}all"


@internal(reason="Private helper for TeachingProvider — locates docs on disk")
def resolve_docs_dir() -> Path | None:
    """Locate the docs/ directory relative to the s0ma package.

    The **fallback** path since the teaching slice arrived: it finds the
    repository's copy of the user guide, which is what this module reads
    when — and only when — no teaching slice is installed. It is kept
    because a source checkout really does have that guide and reading it
    is better than answering nothing; it is no longer the primary path,
    because a wheel never has it.

    The guide it finds is ``packages/s0ma-core/docs/s0ma_user_guide.md``,
    which since the G2 merge is the single canonical guide rather than one
    fork of three. Its heading set is the address space
    :data:`_TOPIC_TO_HEADING` writes into, and a test pins every one of
    those addresses to a real heading so a renumbering cannot silently
    turn this path back into "section not found".

    Resolution order:

    1. Development layout: ``s0ma/src/s0ma/`` → ``s0ma/docs/``
       (traverse up from package ``__file__`` to the project root)
    2. Editable install: ``site-packages/s0ma/`` → ``docs/`` alongside

    Returns:
        Absolute path to the ``docs/`` directory, or ``None`` if the
        user guide is not found (e.g., pip-installed without source).
    """
    # __file__ is s0ma/src/s0ma/api/teaching.py
    package_dir = Path(__file__).resolve().parent.parent  # s0ma/src/s0ma/
    # Development layout: s0ma/src/s0ma/ -> ../../ -> s0ma/ -> docs/
    candidate = package_dir.parent.parent / "docs"
    if (candidate / "s0ma_user_guide.md").is_file():
        return candidate

    # Alternate layout: s0ma/ directly contains docs/
    candidate = package_dir.parent / "docs"
    if (candidate / "s0ma_user_guide.md").is_file():
        return candidate

    return None


@internal(reason="Private helper for TeachingProvider — reads the packaged slice")
def packaged_slice() -> tuple[str, str] | None:
    """The teaching slice that ships inside this package: where, and its text.

    **This is the reading that matters**, and it is tried before anything
    else. The file is package data, so it is there in a wheel install, an
    editable install and a checkout alike — which is the whole difference
    between this and the guide reading it replaced, where development and
    release took different paths and only one of them was ever exercised.

    Read through :mod:`importlib.resources` rather than by building a path
    from ``__file__``, so a zip-imported installation works too.

    Returns:
        ``(where, text)``, or ``None`` if this installation carries no
        packaged slice — a packaging fault, not a supported state.
    """
    try:
        found = resources.files(SLICE_PACKAGE).joinpath(*SLICE_RESOURCE)
        if not found.is_file():
            return None
        return (f"{SLICE_PACKAGE}/{'/'.join(SLICE_RESOURCE)}", found.read_text(encoding="utf-8"))
    except (ModuleNotFoundError, FileNotFoundError, OSError):  # pragma: no cover
        return None


@internal(reason="Private helper for TeachingProvider — locates a checkout slice")
def resolve_slice_path() -> Path | None:
    """The repository's own copy of the slice, for a tree with no mirror yet.

    The recovery case, and only that: somebody deleted the packaged file,
    or is running from a tree where the documentation application has
    written the artifact and the mirror has not been refreshed. The walk is
    bounded so that a package installed somewhere deep cannot wander into
    an unrelated directory that happens to have a ``docs/`` in it.

    Returns:
        Path to a readable slice file, or ``None`` if there is none.
    """
    here = Path(__file__).resolve()
    for parent in list(here.parents)[:CHECKOUT_SEARCH_DEPTH]:
        candidate = parent.joinpath(*CHECKOUT_SLICE)
        if candidate.is_file():
            return candidate
    return None


class TeachingSliceError(ValueError):
    """The teaching slice is not a document this reader understands."""


@internal(reason="Private helper for TeachingProvider — word set for topic matching")
def _words(text: str) -> set[str]:
    """The words of ``text``, lowercased, one-letter and two-letter ones left out.

    Short words are dropped because they are the ones every sentence has:
    a question matching a summary on "the" is not a match, and counting it
    is how a search returns something confident and wrong.
    """
    return {word for word in re.findall(r"[\w-]+", text.lower()) if len(word) > 2}


@internal(reason="Private value type for TeachingProvider — the parsed teaching slice")
@dataclass(frozen=True)
class TeachingSlice:
    """The packaged teaching content, parsed once and read many times.

    Everything a question needs to be answered offline: the topics, the
    alternate names that reach them, the keyword vocabulary this module
    used to answer with, and the release, channel and snapshot every
    answer is stamped with.

    ``release_version`` is the bare version and ``build_channel`` is the
    channel that produced it; :meth:`version_line` is the one written form
    the two make together. They are kept apart for the reason the
    documentation application keeps them apart on its own stamp — a
    machine comparing versions wants the number, and a reader wants the
    sentence — and joining them in the field would leave nothing able to
    answer "which release is this?" without parsing prose back out.
    """

    where: str
    release_version: str
    snapshot_hash: str
    model_schema: str
    build_channel: str
    topics: Mapping[str, Mapping[str, Any]]
    indexes: Mapping[str, Mapping[str, Any]]
    aliases: Mapping[str, str]
    keywords: Mapping[str, str]
    live_example_topics: tuple[str, ...]

    @classmethod
    def load(cls, where: str, text: str) -> TeachingSlice:
        """Read and check ``text``, refusing anything this reader misreads.

        Malformed JSON, a missing key or a schema string from another
        version all raise: an answer assembled from a document nobody
        understood is worse than saying there is none, because the reader
        cannot tell the difference.
        """
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as error:
            raise TeachingSliceError(f"{where} could not be read: {error}") from error
        if not isinstance(raw, dict):
            raise TeachingSliceError(f"{where} is not a teaching slice document")
        schema = raw.get("schema")
        if schema != SLICE_SCHEMA:
            raise TeachingSliceError(
                f"this reader understands {SLICE_SCHEMA!r}; {where} names {schema!r}"
            )
        source = raw.get("source")
        if not isinstance(source, dict):
            raise TeachingSliceError(f"{where} carries no source identity")
        topics = {
            str(item["id"]): item
            for item in raw.get("topics", [])
            if isinstance(item, dict) and "id" in item
        }
        indexes = {
            str(item["id"]): item
            for item in raw.get("indexes", [])
            if isinstance(item, dict) and "id" in item
        }
        if not topics or not indexes:
            raise TeachingSliceError(f"{where} carries no topics to teach from")
        return cls(
            where=where,
            release_version=str(source.get("release_version", "")),
            snapshot_hash=str(source.get("snapshot_hash", "")),
            model_schema=str(source.get("model_schema", "")),
            # Absent means preview, never released: see
            # :data:`DEFAULT_BUILD_CHANNEL`. Read with a default rather
            # than required so that a slice written before H2 is still a
            # slice this reader understands — the additive-field rule the
            # model's ``@1`` schema is under — while still being labelled.
            build_channel=str(
                source.get("build_channel", "") or DEFAULT_BUILD_CHANNEL
            ),
            topics=topics,
            indexes=indexes,
            aliases={
                str(old): str(new) for old, new in raw.get("aliases", {}).items()
            },
            keywords={
                str(word): str(target)
                for word, target in raw.get("keywords", {}).items()
            },
            live_example_topics=tuple(
                str(item) for item in raw.get("live_example_topics", [])
            ),
        )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, question: str) -> str | None:
        """The id ``question`` asks for, or ``None`` if nothing answers it.

        Six readings, strongest first, and every one of them deterministic
        — a tie is broken by taking the lowest id, never by whichever
        happened to be visited first. An agent that asks the same question
        twice gets the same answer twice, on any machine.
        """
        asked = question.strip()
        if not asked:
            return None
        lowered = asked.lower()

        # 1. The id itself. Ids carry case — `rest:GET:/self/health` — so
        #    the exact spelling is tried before the folded one.
        if asked in self.topics or asked in self.indexes:
            return asked
        folded = {name.lower(): name for name in (*self.indexes, *self.topics)}
        if lowered in folded:
            return folded[lowered]

        # 2. An alternate name somebody arrives holding.
        for old, new in sorted(self.aliases.items()):
            if lowered in (old.lower(), old.partition(":")[2].replace("-", " ").lower()):
                return new

        # 3. The topic's own name, and every search term the slice records.
        for identifier in sorted(self.topics):
            terms = self.topics[identifier].get("search_terms", [])
            if isinstance(terms, list) and lowered in [str(t) for t in terms]:
                return identifier

        # 4. A name the question is asking *about*: "what is drift" names
        #    drift. Before the keyword table, because a question that says
        #    a topic's name is asking about that topic and not about
        #    whichever keyword happens to appear in it too.
        named = self._by_name(lowered)
        if named is not None:
            return named

        # 5. The keyword vocabulary this module used to answer with.
        keyword = self._by_keyword(lowered)
        if keyword is not None:
            return keyword

        # 6. A ranked search over what each topic is called and says it is.
        return self._by_search(lowered)

    #: Which group wins when two topics are equally good answers to a
    #: question asked in words. An idea first, then a path through the
    #: product, then a capability — because somebody typing a sentence is
    #: usually asking what something *is*, and somebody who wants the
    #: capability has its id or its name and reaches it before this.
    GROUP_RANK: ClassVar[Mapping[str, int]] = {
        "concepts": 2,
        "journeys": 1,
        "surfaces": 0,
    }

    #: The shortest name this reading will match on. Four characters, so
    #: that a name is a name rather than a fragment every question contains.
    NAME_FLOOR: ClassVar[int] = 4

    def _by_name(self, lowered: str) -> str | None:
        """The topic whose name the question actually says.

        Matched on whole words, so "drift" does not match "drifting" and a
        name is never found inside another word. The longest name wins —
        a question naming ".s0ma file" is about the file and not about
        files in general — and an equal-length tie goes to the group
        :data:`GROUP_RANK` ranks first, then to the lowest id.
        """
        asked = " " + " ".join(re.findall(r"[\w-]+", lowered)) + " "
        best: tuple[int, int, str] | None = None
        for identifier in sorted(self.topics):
            topic = self.topics[identifier]
            rank = self.GROUP_RANK.get(str(topic.get("group", "")), 0)
            for term in topic.get("search_terms", []):
                words = re.findall(r"[\w-]+", str(term).lower())
                if not words or len(str(term)) < self.NAME_FLOOR:
                    continue
                if f" {' '.join(words)} " not in asked:
                    continue
                ranked = (len(str(term)), rank, identifier)
                if best is None or ranked[:2] > best[:2]:
                    best = ranked
        return None if best is None else best[2]

    def _by_keyword(self, lowered: str) -> str | None:
        """The best of the legacy keyword groups, scored the old way.

        Whole-word matches and substring matches both count, which is how
        the table this replaced behaved — so a question that used to reach
        a section still reaches the topic that section became. Equal scores
        are broken by the *longer* keyword, which is what makes "api
        reference" resolve to the list of capabilities and a bare "api" to
        the self-model: the more of the question a keyword accounts for,
        the more likely it is the thing being asked about.
        """
        words = set(re.findall(r"[\w@-]+", lowered))
        best: tuple[int, int, str] | None = None
        for word in sorted(self.keywords):
            score = (1 if word in words else 0) + (1 if word in lowered else 0)
            if score == 0:
                continue
            ranked = (score, len(word), self.keywords[word])
            if best is None or ranked[:2] > best[:2]:
                best = ranked
        return None if best is None else best[2]

    #: How much a word shared with a topic's *name* is worth against a word
    #: shared with its summary, and the score a match has to reach.
    #:
    #: Three and one, floor of three: a question has to share at least one
    #: word with something's name before this reading will answer with it.
    #: Without the floor, "xyzzy nothing here" comes back with whichever
    #: topic happens to contain the word "nothing" — a confident wrong
    #: answer, which is worse for an agent than the list of what is
    #: actually here.
    NAME_WEIGHT: ClassVar[int] = 3
    SUMMARY_WEIGHT: ClassVar[int] = 1
    SEARCH_FLOOR: ClassVar[int] = 3

    def _by_search(self, lowered: str) -> str | None:
        """The topic whose name and summary share the most with the ask.

        A last reading rather than a clever one: no stemming, no ranking
        model, nothing that would answer differently on a different
        machine. A word shared with a name counts for more than a word
        shared with a sentence, because "what is drift" is a question about
        drift and not about every summary that says "what". Ties are broken
        by taking the lowest id, so the same question answers the same way
        twice.
        """
        asked = {word for word in re.findall(r"[\w-]+", lowered) if len(word) > 2}
        if not asked:
            return None
        best: tuple[int, str] | None = None
        for identifier in sorted(self.topics):
            topic = self.topics[identifier]
            named = _words(
                " ".join(
                    [
                        str(topic.get("title", "")),
                        *(str(term) for term in topic.get("search_terms", [])),
                    ]
                )
            )
            said = _words(str(topic.get("summary", "")))
            score = self.NAME_WEIGHT * len(asked & named) + self.SUMMARY_WEIGHT * len(
                asked & said
            )
            if score < self.SEARCH_FLOOR:
                continue
            if best is None or score > best[0]:
                best = (score, identifier)
        return None if best is None else best[1]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def version_line(self) -> str:
        """The release as a reader meets it, labelled unless it is released.

        ``0.18.1`` for a slice generated by a release build and
        ``0.18.1 (preview)`` for one generated from ``main`` — the same
        rule, and the same written form, the documentation application
        applies on its own side of the wall
        (``BuildStamp.version_line``). It is stated in two places because
        core may not import the toolchain (D-9); it cannot *drift* in two
        places because ``scripts/wheel_smoke.py`` compares this line
        against the release manifest's channel before a release is served.

        The label rides on the version rather than beside it because the
        unlabelled sentence is the false one: a wheel built from ``main``
        that says "this answer came from s0ma 0.18.1" is claiming to teach
        released 0.18.1, which is precisely what architecture §13.2 says
        preview documentation must never present itself as.
        """
        if self.build_channel == RELEASE_CHANNEL:
            return self.release_version
        return f"{self.release_version} ({self.build_channel})"

    def identity_line(self, identifier: str) -> str:
        """Which release, which snapshot, which topic — on every answer.

        The shared-output contract (architecture §9.7) asks every channel
        that serves a topic to say the same thing about where it came
        from. This is that sentence, and it is the reason an agent can
        tell a current answer from one served by a copy left behind three
        releases ago — or by a preview build that was never released.
        """
        return (
            f"This answer came from s0ma {self.version_line()}, teaching "
            f"snapshot {self.snapshot_hash}, topic {identifier}."
        )

    def render(self, identifier: str) -> str:
        """One topic, written out, or one navigation list."""
        if identifier in self.indexes:
            return self._render_index(self.indexes[identifier])
        topic = self.topics[identifier]
        # The title, then the facts. The short form is *not* repeated
        # above them: it is already the first section of every group that
        # has one, and a page that says the same sentence twice reads as a
        # rendering fault rather than as emphasis.
        lines: list[str] = [f"# {topic.get('title', identifier)}", ""]
        for section in topic.get("sections", []):
            lines.extend(self._render_section(section))
        availability = str(topic.get("availability", "")).strip()
        if availability:
            lines.extend(["## Where you can walk this", "", availability, ""])
        documents = topic.get("documents", [])
        if documents:
            lines.extend(["## Where this is written up at length", ""])
            lines.extend(
                f"- {document.get('title', '')} — {document.get('canonical_source', '')}"
                for document in documents
            )
            lines.append("")
        lines.extend(["---", "", self.identity_line(identifier)])
        return "\n".join(lines).rstrip() + "\n"

    def _render_section(self, section: Mapping[str, Any]) -> list[str]:
        """One labelled fact, as its heading and its body."""
        heading = str(section.get("heading", "")).strip()
        lines = [f"## {heading}", ""]
        if "text" in section:
            lines.extend([str(section["text"]), ""])
            return lines
        items = [str(item) for item in section.get("items", [])]
        if section.get("fact") == "syntax":
            lines.extend(["```", *items, "```", ""])
            return lines
        lines.extend([f"- {item}" for item in items])
        lines.append("")
        return lines

    def _render_index(self, index: Mapping[str, Any]) -> str:
        """One navigation list: what is here, and what to ask for next.

        The **other** lists are named from the slice's own set of them
        rather than written down, so a navigation entry added later is
        pointed at without this module hearing about it — and so a reader
        who landed on the whole-corpus map, which writes names only, is
        told where the descriptions are.
        """
        identifier = str(index.get("id", ""))
        lines: list[str] = [f"# {index.get('title', '')}", ""]
        summary = str(index.get("summary", "")).strip()
        if summary:
            lines.extend([summary, ""])
        described = index.get("lines") != "names"
        for group in index.get("groups", []):
            lines.extend([f"## {group.get('title', '')}", ""])
            for topic in group.get("topics", []):
                lines.append(f"- {self.one_line(str(topic), described)}")
            lines.append("")
        lines.append(
            "Ask for any of these by its plain name, or by the id in "
            "brackets after it."
        )
        others = sorted(name for name in self.indexes if name != identifier)
        if others:
            lines.append(
                f"The other lists here are {', '.join(others)} — each of "
                f"those describes every entry in a line."
            )
        lines.extend(["", "---", "", self.identity_line(identifier)])
        return "\n".join(lines).rstrip() + "\n"

    def one_line(self, identifier: str, described: bool = True) -> str:
        """One topic as a single line, for a list.

        ``described`` is the list's own declaration, not this method's
        opinion: the whole-corpus list is where a mistyped question lands,
        and a description of every topic there is is not a helpful answer
        to a typing mistake, so that one asks for names.
        """
        topic = self.topics.get(identifier)
        if topic is None:
            return identifier
        title = str(topic.get("title", identifier))
        summary = str(topic.get("summary", "")).strip()
        # A journey has no name a person would use, so its title *is* its
        # id — writing both would put the same string on the line twice.
        named = identifier if title == identifier else f"{title} ({identifier})"
        if described and summary:
            return f"{named} — {summary}"
        return named

    def lines_for(self, identifiers: Iterable[str]) -> list[str]:
        """Several topics as list lines, skipping any this slice lacks."""
        return [
            f"  - {self.one_line(identifier)}"
            for identifier in identifiers
            if identifier in self.topics
        ]


# ---------------------------------------------------------------------------
# Section heading patterns — the pre-slice fallback
# ---------------------------------------------------------------------------

# Map from topic keywords to user guide section headings.
#
# **This table is the fallback path only.** Since the teaching slice
# arrived it is consulted when — and only when — no slice is installed and
# a checkout guide is present, which on a wheel is never. The current
# vocabulary is the slice's own ``keywords`` map, where every one of these
# words is re-pointed at the topic that answers it now, and where a target
# nobody composed fails the documentation build instead of a user's query.
#
# Keys are lowercase keyword sets; values are the ## heading text to extract.
_TOPIC_TO_HEADING: list[tuple[frozenset[str], str]] = [
    (frozenset({"creating", "component", "decorator", "@component"}),
     "Section 2: Creating Components"),
    (frozenset({"modifying", "changing", "modify", "change"}),
     "Section 3: Modifying Components"),
    (frozenset({"removing", "deleting", "remove", "delete", "deletion"}),
     "Section 4: Removing Components"),
    (frozenset({"querying", "query", "self-model", "selfmodel", "api"}),
     "Section 5: Querying the Self-Model"),
    (frozenset({"anomalies", "anomaly", "verification", "verify", "health", "report"}),
     "Section 6: Understanding Anomaly Reports"),
    (frozenset({"best", "practices", "best practices"}),
     "Section 7: Best Practices"),
    # Section *9*, not 8. This entry named "Section 8: Troubleshooting" from
    # the day it was written and no guide has ever had that heading —
    # section 8 is "Testing s0ma Applications" and troubleshooting is 9 — so
    # every fallback answer for these five words was the 64-character
    # "section not found" string. Found and repaired at the G2 guide merge,
    # where the guide's heading set became something a gate reads.
    (frozenset({"troubleshooting", "errors", "error", "fix", "debug"}),
     "Section 9: Troubleshooting"),
    (frozenset({"setup", "initialize", "install", "init", "getting started"}),
     "Section 1: Project Setup"),
    (frozenset({"glossary", "terms", "definitions"}),
     "Appendix A: Glossary"),
    (frozenset({"reference", "api reference"}),
     "Appendix B: Python API Reference"),
    (frozenset({"compliance", "rules", "rule"}),
     "Appendix C: Compliance Rules"),
    (frozenset({"checklist", "pre-flight", "preflight"}),
     "C.11 Summary: Quick Compliance Checklist"),
]

#: What each guide-only document is called, and which topics answer the
#: same question from the slice when it is not on disk. A document that
#: lives in the repository is not in a wheel, and saying so while naming
#: what *is* here is a different thing from saying documentation is
#: unavailable: one routes the reader somewhere real and the other ends
#: the conversation.
_GUIDE_SUBSTITUTES: Mapping[str, tuple[str, tuple[str, ...]]] = {
    "compliance-rules": (
        "the compliance rules appendix of the user guide",
        ("concept:strictness-mode", "concept:drift-gate", "concept:contract"),
    ),
    "checklist": (
        "the quick compliance checklist from the user guide",
        ("concept:check-and-build-loop", "concept:drift-gate"),
    ),
    "architecture": (
        "the architecture document",
        ("concept:self-model", "concept:registry-snapshot"),
    ),
}


# ---------------------------------------------------------------------------
# TeachingProvider
# ---------------------------------------------------------------------------


class TeachingProvider:
    """Serves teaching content and live registry examples to agents.

    Reads the packaged teaching slice — the ideas s0ma is built out of,
    the capabilities this package serves, the guided paths through the
    product — and supplements it with templates read off the registry that
    is actually running. Both are current by construction: the slice is
    generated at release and stamped with the snapshot it describes, and a
    template is read at the moment it is asked for.

    When no slice is installed *and* a repository checkout is present, it
    falls back to reading that checkout's user guide, which is what this
    class used to do always. When neither is there it says so, and points
    at the self-model tools that need no documentation to work.

    Args:
        registry: The ComponentRegistry for live examples and templates.
        docs_dir: Explicit path to the ``docs/`` directory. If ``None``,
            auto-resolves using :func:`resolve_docs_dir`.
        slice_path: Explicit path to a teaching slice file. If ``None``,
            the packaged slice is read, and a checkout's copy only if this
            installation has none. An explicit path that is not readable
            leaves this provider with no slice, which is how a caller asks
            for the pre-slice behaviour on purpose.
    """

    def __init__(
        self,
        registry: ComponentRegistry,
        docs_dir: Path | None = None,
        slice_path: Path | None = None,
    ) -> None:
        self._registry = registry
        self._docs_dir = docs_dir if docs_dir is not None else resolve_docs_dir()
        self._slice_path = slice_path
        self._slice: TeachingSlice | None = None
        self._slice_read = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def docs_available(self) -> bool:
        """Whether the checkout's user guide is accessible on disk."""
        if self._docs_dir is None:
            return False
        return (self._docs_dir / "s0ma_user_guide.md").is_file()

    @property
    def slice_available(self) -> bool:
        """Whether the packaged teaching slice loaded.

        The property that should be ``True`` in every installation,
        including a bare ``pip install s0ma-core``: the slice ships inside
        the package.
        """
        return self.teaching_slice() is not None

    def teaching_slice(self) -> TeachingSlice | None:
        """The parsed slice, read once, or ``None`` if there is none.

        A slice that fails to parse is treated as absent rather than
        raised: a packaging accident should degrade a teaching answer, not
        break the MCP server that was only asked a question.
        """
        if self._slice_read:
            return self._slice
        self._slice_read = True
        source = self._slice_source()
        if source is not None:
            try:
                self._slice = TeachingSlice.load(*source)
            except TeachingSliceError:
                self._slice = None
        return self._slice

    def _slice_source(self) -> tuple[str, str] | None:
        """Where this provider reads its teaching content, and what it says.

        An explicit path wins and nothing falls back behind it — a caller
        naming a file and silently getting a different one is how a test
        proves the wrong thing. Otherwise the packaged slice, and only if
        this installation carries none, a checkout's copy.
        """
        if self._slice_path is not None:
            try:
                return (
                    str(self._slice_path),
                    self._slice_path.read_text(encoding="utf-8"),
                )
            except OSError:
                return None
        packaged = packaged_slice()
        if packaged is not None:
            return packaged
        found = resolve_slice_path()
        if found is None:
            return None
        try:
            return (str(found), found.read_text(encoding="utf-8"))
        except OSError:  # pragma: no cover - is_file() just said otherwise
            return None

    # ------------------------------------------------------------------
    # Documentation serving
    # ------------------------------------------------------------------

    def get_user_guide(self) -> str:
        """Return the guide a reader should start from.

        The checkout's user guide when this is a checkout, because it is
        the longer document and a person reading it wants all of it.
        Otherwise the teaching slice's own map of what is here — which is
        what an installed package can honestly offer, and is current
        rather than a copy of something.
        """
        content = self._read_doc_file("s0ma_user_guide.md")
        if content is not None:
            return content
        return self._from_slice(ALL_INDEX)

    def get_compliance_rules(self) -> str:
        """Return Appendix C (Compliance Rules) from the user guide.

        Extracts the compliance rules section by parsing the markdown
        at query time. This ensures the rules are always current.

        Returns:
            The compliance rules appendix, or — where the guide is not part
            of this installation — the topics that answer the same
            question from the packaged slice.
        """
        content = self._read_doc_file("s0ma_user_guide.md")
        if content is None:
            return self._substitute("compliance-rules")
        return self._extract_section(content, "Appendix C: Compliance Rules")

    def get_architecture(self) -> str:
        """Return the architecture note, read from disk.

        Returns:
            The content of ``architecture.md`` — the note naming the two
            documents that replaced the retired narrative — or, where it is
            not part of this installation, what the packaged slice and the
            live self-model can say instead.
        """
        content = self._read_doc_file("architecture.md")
        if content is None:
            return self._substitute("architecture")
        return content

    def get_section(self, heading: str) -> str:
        """Extract a specific section from the user guide by heading.

        Args:
            heading: The heading text (without ``##`` prefix) to find.
                Example: ``"Section 2: Creating Components"``.

        Returns:
            The extracted section content, or — where the guide is not part
            of this installation — a message saying so and naming what can
            be asked for instead.
        """
        content = self._read_doc_file("s0ma_user_guide.md")
        if content is None:
            return self._section_absent(heading)
        return self._extract_section(content, heading)

    def get_compliance_checklist(self) -> str:
        """Return the quick compliance checklist (Section C.11).

        This is the pre-flight checklist agents should run before
        submitting any s0ma component changes.

        Returns:
            The checklist content, or — where the guide is not part of this
            installation — the topics that answer the same question from
            the packaged slice.
        """
        content = self._read_doc_file("s0ma_user_guide.md")
        if content is None:
            return self._substitute("checklist")
        return self._extract_section(
            content, "C.11 Summary: Quick Compliance Checklist"
        )

    # ------------------------------------------------------------------
    # Live registry examples
    # ------------------------------------------------------------------

    def get_component_template(self, kind: str | None = None) -> str:
        """Return a real component formatted as a copyable template.

        Picks an actual registered component from the registry and
        formats it as a ``@component`` decorator invocation that an
        agent can copy and modify for new components.

        Prefers non-framework components when available, since they
        better demonstrate the developer-facing usage pattern.

        Args:
            kind: Optional ComponentKind filter (e.g., ``"SERVICE"``).
                If ``None``, picks a representative example.

        Returns:
            A copyable ``@component`` decorator template with comments.
        """
        from s0ma.types import ComponentKind

        all_specs = self._registry.get_all()

        # Prefer non-framework components (they show real usage)
        candidates = [
            s for s in all_specs.values() if not s.is_framework
        ]

        # Filter by kind if requested
        if kind:
            kind_upper = kind.upper()
            try:
                target_kind = ComponentKind[kind_upper]
            except KeyError:
                valid = ", ".join(k.name for k in ComponentKind)
                return (
                    f"Unknown ComponentKind: '{kind}'. "
                    f"Valid kinds are: {valid}"
                )
            kind_filtered = [
                s for s in candidates if s.kind == target_kind
            ]
            candidates = kind_filtered or [
                s for s in all_specs.values()
                if s.kind == target_kind
            ]

        # Fall back to framework components if no user components exist
        if not candidates:
            candidates = list(all_specs.values())

        if not candidates:
            return "No components registered. Initialize s0ma first."

        # Pick the first alphabetically for deterministic output
        spec = sorted(candidates, key=lambda s: s.name)[0]
        return self._format_as_template(spec)

    # ------------------------------------------------------------------
    # Topic-based learning
    # ------------------------------------------------------------------

    def learn_topic(self, topic: str) -> str:
        """Learn about a s0ma topic — returns teaching content + live examples.

        Resolves the question against the packaged teaching slice: a topic
        id, an alternate name, the topic's own term, the keyword
        vocabulary this module has always answered on, then a ranked
        search. A question nothing answers gets the list of everything
        that is here rather than an apology.

        Args:
            topic: What to learn about (e.g., ``"nerve"``,
                ``"creating components"``, ``"concept:drift"``).

        Returns:
            The topic, written out, ending with the release and snapshot it
            came from.
        """
        current = self.teaching_slice()
        if current is None:
            return self._learn_from_guide(topic)

        identifier = current.resolve(topic)
        if identifier is None:
            return current.render(ALL_INDEX)

        answer = current.render(identifier)
        if identifier in current.live_example_topics:
            answer += (
                "\n---\n\n"
                "## A real one, from this system\n\n"
                "Here is a component registered in the system you are "
                "talking to, written out so you can copy it:\n\n"
                + self.get_component_template()
                + "\n"
            )
        return answer

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _from_slice(self, identifier: str) -> str:
        """One slice topic, or the last-resort message if there is no slice."""
        current = self.teaching_slice()
        if current is None:
            return self._docs_unavailable_message()
        return current.render(identifier)

    def _section_absent(self, heading: str) -> str:
        """A guide section asked for where there is no guide.

        The one caller-facing path that can still be honestly answered
        "that document is not here": a heading is an address inside the
        user guide, and the slice has no heading of that name to offer
        instead. So it says which document is missing and names the two
        questions that *are* answerable, rather than falling through to
        the message that says nothing is.
        """
        current = self.teaching_slice()
        if current is None:
            return self._docs_unavailable_message()
        return (
            f"The user guide is not part of this installation, so there is "
            f"no section called {heading!r} to read from it. The guide lives "
            f"in the s0ma repository; an installed package carries the "
            f"teaching content instead.\n\n"
            f'Ask learn_about_s0ma("glossary") for every idea s0ma is built '
            f'out of, or learn_about_s0ma("api reference") for everything '
            f"this package serves.\n\n"
            f"---\n\n{current.identity_line(ALL_INDEX)}"
        )

    def _substitute(self, key: str) -> str:
        """What is here, when the document somebody asked for is not.

        Named rather than generic: the reader is told which document is
        missing, why an installed package does not carry it, and which
        topics answer the same question — each with its id, so the next
        question can be asked directly.
        """
        current = self.teaching_slice()
        what, topics = _GUIDE_SUBSTITUTES[key]
        if current is None:
            return self._docs_unavailable_message()
        lines = [
            f"{what.capitalize()} is not part of this installation — it lives "
            f"in the s0ma repository, and an installed package does not carry "
            f"it.",
            "",
            "What this installation can tell you instead:",
            "",
            *current.lines_for(topics),
            "",
            "Ask learn_about_s0ma() for any of those by name, or for "
            '"glossary" to see every idea s0ma is built out of. '
            "describe_system() and check_health() answer from the running "
            "system itself.",
            "",
            "---",
            "",
            current.identity_line(ALL_INDEX),
        ]
        return "\n".join(lines)

    def _learn_from_guide(self, topic: str) -> str:
        """The pre-slice path: keyword to guide heading, over a checkout.

        Unreachable in any installation that has a teaching slice, which is
        every installation that has the wheel. It is kept whole so that a
        tree without a composed slice still answers, and so the behaviour
        it had can be compared against the behaviour it has.
        """
        topic_lower = topic.lower()
        topic_words = set(re.findall(r'\b\w+\b', topic_lower))

        best_heading: str | None = None
        best_score = 0

        for keywords, heading in _TOPIC_TO_HEADING:
            score = len(topic_words & keywords)
            # Also check substring matches for multi-word keywords
            for kw in keywords:
                if kw in topic_lower:
                    score += 1
            if score > best_score:
                best_score = score
                best_heading = heading

        if best_heading is None or best_score == 0:
            return self._available_topics()

        result = self.get_section(best_heading)

        # For component creation topics, append a live template
        if "creating" in best_heading.lower() or "component" in best_heading.lower():
            template = self.get_component_template()
            result += (
                "\n\n---\n\n"
                "## Live Example from Registry\n\n"
                "Here is a real component currently registered in the system, "
                "formatted as a copyable template:\n\n"
                + template
            )

        return result

    def _read_doc_file(self, filename: str) -> str | None:
        """Read a documentation file from the docs directory.

        Args:
            filename: Name of the file (e.g., ``"s0ma_user_guide.md"``).

        Returns:
            File content as a string, or ``None`` if unavailable.
        """
        if self._docs_dir is None:
            return None
        path = self._docs_dir / filename
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def _extract_section(self, content: str, heading: str) -> str:
        """Extract a markdown section by its heading.

        Finds the line containing ``## {heading}`` (or ``### {heading}``)
        and includes all content up to the next heading at the same or
        higher level.

        Args:
            content: Full markdown content to search.
            heading: Heading text to find (without ``##`` prefix).

        Returns:
            The extracted section, or a not-found message.
        """
        lines = content.split("\n")
        start_idx: int | None = None
        start_level: int = 0
        end_idx = len(lines)

        for i, line in enumerate(lines):
            stripped = line.strip()
            # Match heading with any ## level
            if stripped.startswith("#"):
                # Count heading level
                level = 0
                for ch in stripped:
                    if ch == "#":
                        level += 1
                    else:
                        break
                heading_text = stripped[level:].strip()

                if start_idx is None:
                    # Looking for our target heading
                    if heading_text == heading:
                        start_idx = i
                        start_level = level
                else:
                    # We've found the start; look for the next heading
                    # at the same or higher (fewer #) level
                    if level <= start_level:
                        end_idx = i
                        # Walk backwards to exclude trailing blank lines/separators
                        while (
                            end_idx > start_idx
                            and lines[end_idx - 1].strip() in ("---", "")
                        ):
                            end_idx -= 1
                        break

        if start_idx is None:
            return f"Section '{heading}' not found in documentation."

        return "\n".join(lines[start_idx:end_idx]).strip()

    def _format_as_template(self, spec: Any) -> str:
        """Format a ComponentSpec as a copyable @component template.

        Args:
            spec: The ComponentSpec to format.

        Returns:
            A Python code block showing the @component invocation.
        """
        lines = [
            "```python",
            "from s0ma.decorators import component",
            "from s0ma.types import ComponentKind, Layer",
            "from s0ma.models import Contract",
            "",
            "@component(",
            f'    name="{spec.name}",',
            f"    kind=ComponentKind.{spec.kind.name},",
            f"    layer=Layer.{spec.layer.name},",
            f'    intent="{spec.intent}",',
        ]

        # Add contracts if non-empty
        contracts = spec.contracts
        has_contracts = (
            contracts.preconditions
            or contracts.postconditions
            or contracts.invariants
            or contracts.forbids
            or contracts.max_latency_ms is not None
            or contracts.error_rate_threshold is not None
            or contracts.input_type is not None
            or contracts.output_type is not None
        )
        if has_contracts:
            lines.append("    contracts=Contract(")
            if contracts.preconditions:
                lines.append(f"        preconditions={contracts.preconditions!r},")
            if contracts.postconditions:
                lines.append(f"        postconditions={contracts.postconditions!r},")
            if contracts.invariants:
                lines.append(f"        invariants={contracts.invariants!r},")
            if contracts.forbids:
                lines.append(f"        forbids={contracts.forbids!r},")
            if contracts.max_latency_ms is not None:
                lines.append(f"        max_latency_ms={contracts.max_latency_ms},")
            if contracts.error_rate_threshold is not None:
                lines.append(
                    f"        error_rate_threshold={contracts.error_rate_threshold},"
                )
            if contracts.input_type is not None:
                lines.append(f'        input_type="{contracts.input_type}",')
            if contracts.output_type is not None:
                lines.append(f'        output_type="{contracts.output_type}",')
            lines.append("    ),")

        # Add dependencies if non-empty
        if spec.dependencies:
            lines.append(f"    dependencies={spec.dependencies!r},")

        lines.extend([
            ")",
            f"class {spec.name}:",
            f'    """{spec.intent}."""',
            "    ...",
            "```",
        ])

        return "\n".join(lines)

    def _docs_unavailable_message(self) -> str:
        """The last resort: no teaching slice and no checkout guide either.

        Effectively unreachable in a released installation — the slice
        ships inside the package — and kept for the state that is left: a
        tree where the slice has never been composed and the guide is not
        beside it.
        """
        return (
            "Documentation files are not available in this installation.\n\n"
            "The s0ma teaching content ships inside the package and the user "
            "guide lives in the source repository; neither one is readable "
            "here, which is a packaging fault rather than something you did.\n\n"
            "You can still use these self-model tools to understand the system:\n"
            "  - describe_system() — system overview\n"
            "  - find_component(name) — component details\n"
            "  - check_health() — verification status\n"
            "  - get_extension_points() — where to add components\n"
            "  - get_component_example() — live component template\n\n"
            "For the full user guide, install from source or visit the "
            "project repository."
        )

    def _available_topics(self) -> str:
        """The pre-slice topic list, used only on the pre-slice path."""
        return (
            "Available topics for learn_about_s0ma():\n\n"
            "  - \"creating components\" — How to use @component\n"
            "  - \"compliance\" or \"rules\" — Compliance rules (Appendix C)\n"
            "  - \"checklist\" — Quick compliance checklist\n"
            "  - \"modifying\" — How to modify existing components\n"
            "  - \"removing\" — How to safely remove components\n"
            "  - \"querying\" or \"self-model\" — How to query the self-model\n"
            "  - \"anomalies\" or \"verification\" — Understanding anomaly reports\n"
            "  - \"best practices\" — Best practices for agents and humans\n"
            "  - \"troubleshooting\" — Common errors and fixes\n"
            "  - \"setup\" or \"initialize\" — Project setup and initialization\n"
            "  - \"glossary\" — Key terms and definitions\n"
            "  - \"api reference\" — Python API reference\n"
        )
