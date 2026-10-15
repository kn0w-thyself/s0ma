"""The three generated references: commands, settings, and reports.

Milestone F3 of the docs-function plan (internal) §11. D6 gave the corpus
two *indexes* — every concept in one line each, every served capability in
one row each — and said in its own docstring what they could not yet do:
the surfaces index lists a capability, so ``DOC_SURFACE_UNCOVERED`` is
satisfied by construction until "F3/F4 author per-family reference pages
and the index stops being the whole answer". These are three of those
pages. An index says a thing exists; a reference says what it takes, what
it does, and what changes when you use it.

**One page per family, and the families are the channels.** Architecture
§6.3's channel word is already the fact that decides which page a record
belongs on, and :data:`~s0ma_dsl.docs_model.inventories.CHANNEL_TITLES`
already names each channel for a reader. So there is no new
classification here and no table anybody has to keep up to date:
``cli`` goes to :data:`CLI_REFERENCE_OUTPUT`, ``config`` to
:data:`CONFIGURATION_REFERENCE_OUTPUT`, ``diagnostic`` to
:data:`DIAGNOSTICS_REFERENCE_OUTPUT`, and
:data:`PAGE_BY_ID_CLASS` is that same mapping said as the id classes
:mod:`~s0ma_dsl.docs_model.ids` addresses them by.

**The route.** Two were available and the plan permits either. The
doc-emitter route (ADR-013's derived-source registry, reached from a
``doc-ref`` declaration in ``docs/s0ma_src/``) renders one flat table of
positional cells per source: it is the right shape for
``packages/s0ma-dsl/docs/_generated/common_errors.md``, and it is the
wrong shape for a page with a section per entry, two nested tables per
command and a per-mode ladder per code — a record schema of flat values
has one cell to put each of those in. So these three take the
application-renderer route D6 and F2 established: a module here, wired
into ``application.STATIC_OUTPUTS``, byte-gated by the F1 stage.

That leaves ``cli_commands`` and ``error_codes`` — two registered derived
sources covering ground these pages also cover — and **neither is
forked**. Both read what this module reads: ``cli_commands`` calls the
same :class:`~s0ma_dsl.docs_model.providers_cli.CliProvider`, and
``error_codes`` reads the same three registries in ``config.py`` that
:class:`~s0ma_dsl.docs_model.providers_diagnostics.DiagnosticsProvider`
parses structurally. The F3 suite pins the diagnostics page against
``error_codes``'s records code for code, so a discrepancy is a red test
rather than two pages a reader has to choose between.

**Every count is computed here and none is written down.** The opening of
each page states how many commands, keys or codes it carries, and every
one of those numbers is taken from the records the page is rendering.
F2's reason, restated: a hand-written total is the first thing a
generated page gets wrong, and getting it wrong is how a reader learns
not to trust the page.

**The anchor convention, recorded for F6 and F7.** Every entry is an ATX
heading whose text is :func:`heading_of` of its id, so its GitHub anchor
is :func:`anchor_of` of that id and :func:`deep_link` is the whole
location a deep link needs:

* ``cli:s0ma/docs/render`` → ``docs/reference/cli.md#s0ma-docs-render``
* ``config:build_dir`` → ``docs/reference/configuration.md#build_dir``
* ``diagnostic:BARE_IMPORT`` →
  ``docs/reference/diagnostics.md#bare_import``

The renderers call :func:`heading_of` for the heading and
:func:`anchor_of` for the link, so a heading and its anchor cannot drift
apart; and :func:`_anchored` refuses a build in which two entries would
slug to one anchor, because github-slugger silently disambiguates a
repeated heading with a ``-1`` suffix and every deep link to the second
one would resolve to the first.

**What this module quotes, and the one cost of quoting.** A command's
help line, a key's documentation, a code's description and a record's
written exception are ``SOURCED`` fields: verbatim or absent, never
reworded (C1's classification, B4's finding 4). Only the framing —
headings, the opening, the legend under *How to read this page* — is
written here, and only that framing is subject to the voice rule.

The cost is that a source which writes Markdown by accident gets
Markdown. ``s0ma migrate-layout``'s help line contains
``__s0ma_cache__``, which a Markdown reader renders as bold; the fix is
the help line, not an escape here. The one escape this module does apply
is :func:`~s0ma_dsl.docs_model.inventories.cell`'s, in table cells only,
for the reason that helper exists: an unescaped vertical bar does not
look wrong, it silently shifts every column after it. Two renderers that
escaped a cell differently would disagree about one intent's bytes on two
committed pages, so nothing is escaped here that ``cell`` does not
escape.

**Determinism.** No clock, no network, no machine path. Every collection
is sorted before it is rendered — commands by their command path so a
family stays together, keys and codes by id — every count is computed,
and every page is UTF-8 with LF endings and exactly one trailing
newline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.inventories import GENERATED_NOTE, cell, list_cell
from s0ma_dsl.docs_model.providers_cli import CHANNEL as CLI_CHANNEL
from s0ma_dsl.docs_model.providers_config import CHANNEL as CONFIG_CHANNEL
from s0ma_dsl.docs_model.providers_config import (
    COMPUTED,
    TABLE,
    UNSTATED,
)
from s0ma_dsl.docs_model.providers_config import (
    UNBOUND_EXCEPTION as CONFIG_UNBOUND_EXCEPTION,
)
from s0ma_dsl.docs_model.providers_diagnostics import CHANNEL as DIAGNOSTIC_CHANNEL
from s0ma_dsl.docs_model.providers_diagnostics import (
    MATRIX_REGISTRY,
    NOT_APPLICABLE,
    OUT_OF_MATRIX_REGISTRY,
    REGISTRY_KEY,
    DiagnosticsProviderError,
    fact_map,
    summary_line,
)
from s0ma_dsl.docs_model.records import DocsModelError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from s0ma_dsl.docs_model.providers_cli import (
        CommandArgument,
        CommandInterface,
        CommandOption,
    )
    from s0ma_dsl.docs_model.records import DocsBundle, SurfaceRecord

__all__ = [
    "ABSENT",
    "CLI_REFERENCE_OUTPUT",
    "CONFIGURATION_REFERENCE_OUTPUT",
    "DIAGNOSTICS_REFERENCE_OUTPUT",
    "NARGS_WORDS",
    "PAGE_BY_ID_CLASS",
    "REFERENCE_OUTPUTS",
    "SEVERITY_WORDS",
    "DocsReferenceError",
    "anchor",
    "anchor_of",
    "cli_reference",
    "configuration_reference",
    "deep_link",
    "diagnostics_reference",
    "heading_of",
]


# ---------------------------------------------------------------------------
# Where the three pages go
# ---------------------------------------------------------------------------

#: The generated command-line reference, relative to the documentation
#: root. Under ``reference/`` rather than ``_generated/`` for ADR-012 §1's
#: reason, the one D6 gives for its two indexes: a page a person opens
#: lives where reader-facing pages live, and only its *provenance* makes
#: it generated.
CLI_REFERENCE_OUTPUT = "reference/cli.md"

#: The generated ``[tool.s0ma]`` reference, same directory and same rule.
CONFIGURATION_REFERENCE_OUTPUT = "reference/configuration.md"

#: The generated diagnostics reference, same directory and same rule.
DIAGNOSTICS_REFERENCE_OUTPUT = "reference/diagnostics.md"

#: The three, in the order the application declares them. The constants
#: live here rather than in the application module because
#: :func:`deep_link` has to name a page, and a second copy of a path is a
#: second thing that can be edited alone.
REFERENCE_OUTPUTS: tuple[str, ...] = (
    CLI_REFERENCE_OUTPUT,
    CONFIGURATION_REFERENCE_OUTPUT,
    DIAGNOSTICS_REFERENCE_OUTPUT,
)

#: Which page an addressable id is documented on, keyed by the id class
#: :func:`~s0ma_dsl.docs_model.ids.id_form` returns. The same mapping as
#: channel-to-page, said in the vocabulary a caller holding an id has:
#: F6's ``s0ma docs show`` and F7's ``learn_s0ma`` both start from an id
#: and neither has the record in hand.
PAGE_BY_ID_CLASS: Mapping[str, str] = {
    CLI_CHANNEL: CLI_REFERENCE_OUTPUT,
    CONFIG_CHANNEL: CONFIGURATION_REFERENCE_OUTPUT,
    DIAGNOSTIC_CHANNEL: DIAGNOSTICS_REFERENCE_OUTPUT,
}

#: The other two generated pages these link to, relative to a page inside
#: ``reference/``. Both are committed before these three and neither moves
#: with the documentation root's name, which is what lets these renderers
#: emit a link without being told where the documentation root is.
_SURFACES_INDEX_LINK = "surfaces-index.md"
_MAP_LINK = "../README.md"


class DocsReferenceError(DocsModelError):
    """A reference page cannot be rendered from what it was handed.

    Raised rather than reported, for
    :class:`~s0ma_dsl.docs_model.map_of_record.DocsMapError`'s reason: an
    author cannot fix any of these, and a page rendered anyway would be
    wrong rather than incomplete. There are two conditions — two entries
    that would slug to one anchor, and a fact list that is not in the
    grammar :func:`~s0ma_dsl.docs_model.providers_diagnostics.fact_entries`
    writes.
    """


# ---------------------------------------------------------------------------
# The anchor convention
# ---------------------------------------------------------------------------


def anchor(title: str) -> str:
    """A heading's GitHub anchor.

    The case of github-slugger's rules that every heading on these three
    pages stays inside: lowercase, drop anything that is not a letter, a
    digit, a space, a hyphen or an underscore, then spaces become
    hyphens.

    One character wider than
    :func:`~s0ma_dsl.docs_model.map_of_record.anchor`, and deliberately:
    the map's headings are authored section titles with no underscore in
    them, while a diagnostic code and a configuration key are *written*
    with underscores and github-slugger keeps them. The suite pins this
    against the rules ``scripts/check_links.py`` really applies, over
    every heading these pages render, so the widening is proved rather
    than assumed.
    """
    kept = [
        character
        for character in title.lower()
        if character.isalnum() or character in {" ", "-", "_"}
    ]
    return "".join(kept).strip().replace(" ", "-")


def heading_of(identifier: str) -> str:
    """The heading text the entry ``identifier`` gets on its page.

    One function for three id classes, because the heading and the anchor
    have to be derived from the same thing or they drift: the renderers
    below call this for the heading and :func:`anchor_of` for the link,
    and :func:`anchor_of` is this composed with :func:`anchor`.

    A command is headed by the way a person types it, which is what the
    id spells with slashes. A configuration key is headed by the key
    alone rather than by ``[tool.s0ma].key``: the table's name is on
    every heading of that page and in the page's title, and repeating it
    nineteen times would put it in nineteen anchors too. A diagnostic is
    headed by its code, exactly as it is registered.

    Raises:
        DocsReferenceError: for an id class no reference page carries.
    """
    kind, separator, rest = identifier.partition(":")
    if not separator or kind not in PAGE_BY_ID_CLASS:
        raise DocsReferenceError(
            f"{identifier!r} is not documented on a generated reference "
            f"page. These three carry {', '.join(sorted(PAGE_BY_ID_CLASS))}; "
            f"anything else is addressed somewhere the documentation model "
            f"knows about and this module does not."
        )
    if kind == CLI_CHANNEL:
        return rest.replace("/", " ")
    return rest


def anchor_of(identifier: str) -> str:
    """The in-page anchor of the entry ``identifier``."""
    return anchor(heading_of(identifier))


def deep_link(identifier: str, *, docs_root: str) -> str:
    """Where ``identifier`` is documented, as a repository-relative link.

    ``docs_root`` is the documentation root the caller wrote its pages
    under — the same parameter
    :func:`~s0ma_dsl.docs_model.map_of_record.map_of_record` takes, and
    for the same reason: this module renders relative paths and refuses
    to guess which tree they are relative to.

    This is the whole of what F6's ``s0ma docs show`` and F7's
    ``learn_s0ma`` need in order to point a reader at the canonical
    Markdown for a command, a setting or a report.
    """
    fragment = anchor_of(identifier)  # refuses an id no page carries
    return f"{docs_root}/{PAGE_BY_ID_CLASS[identifier.partition(':')[0]]}#{fragment}"


def _anchored(records: Sequence[SurfaceRecord]) -> dict[str, str]:
    """Every record's anchor, refusing two records that would share one.

    github-slugger disambiguates a repeated heading with a ``-1`` suffix,
    silently, and the second entry's deep link then resolves to the
    first. Nothing in the three id forms makes that impossible —
    ``cli:s0ma/migrate-ext`` and a nested ``cli:s0ma/migrate/ext`` would
    both slug to ``s0ma-migrate-ext`` — so the collision is refused here
    rather than left to be discovered by a reader following a link that
    lands on the wrong section.
    """
    found: dict[str, str] = {}
    claimed: dict[str, str] = {}
    for record in records:
        slug = anchor_of(record.id)
        held = claimed.get(slug)
        if held is not None:
            raise DocsReferenceError(
                f"{held} and {record.id} are both headed in a way that slugs "
                f"to #{slug}, so one of them would take the anchor and the "
                f"other would silently take #{slug}-1. Every deep link to "
                f"the second would land on the first. One of the two names "
                f"has to change in the product before this page can carry "
                f"both."
            )
        claimed[slug] = record.id
        found[record.id] = slug
    return found


# ---------------------------------------------------------------------------
# Shared readings and reader words
# ---------------------------------------------------------------------------

#: What a cell says when the fact it would carry is not there. An absent
#: fact is stated rather than left blank, for
#: :data:`~s0ma_dsl.docs_model.map_of_record.GUARD_ONLY_LISTED`'s reason:
#: an empty cell and a cell nobody filled in look the same.
ABSENT = "—"

#: How many values one positional takes, in the words argparse's ``nargs``
#: means. A form outside this table renders under its own name rather
#: than being dropped — the rule
#: :data:`~s0ma_dsl.docs_model.inventories.CHANNEL_TITLES` follows for a
#: channel nobody has titled.
NARGS_WORDS: Mapping[str, str] = {
    "": "one, required",
    "?": "one, optional",
    "*": "any number, optional",
    "+": "one or more",
}

#: What a severity value means to a reader, where the word alone does not
#: say it. ``error`` and ``warning`` are absent on purpose: they are the
#: product's own words for themselves and rendering them under any other
#: name would be this page inventing a vocabulary.
SEVERITY_WORDS: Mapping[str, str] = {NOT_APPLICABLE: "not checked"}

#: What a capability's effects say when it declares none. The word D5b's
#: gate reads an empty tuple as: an unanswered question, not a "no".
_UNDECLARED = "not declared"

#: What ``component_refs`` says when it is empty —
#: :func:`~s0ma_dsl.docs_model.inventories._binding_of`'s third state, in
#: a sentence rather than in one word, because a reader of a reference
#: page has not read that function.
_UNADDRESSABLE = "nothing the model can address"


def _spans(values: Sequence[str]) -> list[str]:
    """Each value in a code span, for a list a reader scans rather than reads."""
    return [f"`{cell(item)}`" for item in values]


def _effect_words(record: SurfaceRecord) -> str:
    """What running this capability touches, or the word for an unanswered one."""
    return list_cell(_spans(record.side_effects), absent=_UNDECLARED)


def _on_channel(bundle: DocsBundle, channel: str) -> tuple[SurfaceRecord, ...]:
    """Every composed capability on one channel, sorted by id."""
    return tuple(
        sorted(
            (record for record in bundle.surfaces if record.channel == channel),
            key=lambda record: record.id,
        )
    )


def _facts(record: SurfaceRecord) -> Mapping[str, str]:
    """One record's ``errors`` list read as the fact map D2 writes there.

    The refusal is re-raised as this module's error rather than passed
    through, so the failure is located at the page that could not be
    rendered: a fact list that is not in the grammar means a second
    writer has appeared, and the page is where somebody notices.
    """
    try:
        return fact_map(record.errors)
    except DiagnosticsProviderError as error:
        raise DocsReferenceError(
            f"{record.id} carries something in its errors list that is not a "
            f"<key>=<value> fact, so this page cannot say what it records: "
            f"{error}"
        ) from error


def _sources(records: Iterable[SurfaceRecord]) -> tuple[str, ...]:
    """The distinct sources the rendered records were read from, sorted."""
    return tuple(sorted({record.provenance.source for record in records}))


def _source_sentence(records: Sequence[SurfaceRecord]) -> str:
    """Where this page's facts were read from, named rather than linked.

    A provenance source is a file of code or an import path, not a
    document, so it is written in a code span. The map of record links
    its rows because its rows *are* documents; a link from here would
    have to know how deep under the checkout root this page sits, which
    is a fact about the documentation root's name and not about this
    page.
    """
    sources = _sources(records)
    if not sources:
        return "This build read nothing to make this page."
    named = ", ".join(f"`{cell(item)}`" for item in sources)
    return f"Read from {named} when the documentation was built."


def _page(lines: Sequence[str]) -> str:
    """One page's lines as canonical text: LF, one trailing newline."""
    return "\n".join(lines).rstrip("\n") + "\n"


def _nothing_here(what: str) -> list[str]:
    """What a page says when this build composed none of its subject.

    Not an empty page and not a raise. A composition that serves no
    command is a composition somebody built that way — the negative
    battery's planted providers are exactly that — and the honest answer
    is a page that says so and names where the answer would come from.
    The real build's page is held to its counts by the F3 suite instead.
    """
    return [
        f"This build composed no {what}. That is either a composition this "
        f"small or a reading that has stopped seeing its source — the "
        f"providers registered by the documentation application are where "
        f"to look.",
        "",
    ]


def _elsewhere() -> list[str]:
    """The two pages every reference points back at."""
    return [
        f"Every capability s0ma serves, on every channel, is listed in one "
        f"place: [what s0ma can do]({_SURFACES_INDEX_LINK}). Every document "
        f"this repository keeps is on [the documentation map]({_MAP_LINK}).",
        "",
    ]


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def _option_row(option: CommandOption) -> str:
    """One flag as a table row: how to write it, and what it takes."""
    return (
        f"| {list_cell(_spans(option.flags), absent=ABSENT)} "
        f"| {'a value' if option.takes_value else 'no value'} "
        f"| {f'`{cell(option.default)}`' if option.default else ABSENT} "
        f"| {list_cell(_spans(option.choices), absent=ABSENT)} |"
    )


def _argument_row(argument: CommandArgument) -> str:
    """One positional as a table row, in the order it is typed."""
    how_many = NARGS_WORDS.get(argument.nargs, f"`{cell(argument.nargs)}`")
    return (
        f"| `{cell(argument.dest)}` "
        f"| {how_many} "
        f"| {f'`{cell(argument.default)}`' if argument.default else ABSENT} "
        f"| {list_cell(_spans(argument.choices), absent=ABSENT)} |"
    )


def _command_section(
    interface: CommandInterface | None, record: SurfaceRecord
) -> list[str]:
    """One command's whole entry: what it is, what it takes, what it does.

    ``interface`` is the parser reading of this command, and it is
    optional because it can honestly be absent: the interface comes from
    the provider that built the parser, and a caller that composed a
    command record without registering that provider has a record and no
    reading. Where it is absent the section says so instead of showing an
    empty options table, which would read as a command that takes no
    flags. The real build has one for every command, and the F3 suite is
    what holds it to that.
    """
    depth = record.id.count("/")
    lines = [f"{'#' * min(depth + 2, 6)} {heading_of(record.id)}", ""]
    if record.intent:
        lines.extend([record.intent, ""])
    lines.append(f"- **Addressed as** — `{record.id}`")
    lines.append(f"- **Running it touches** — {_effect_words(record)}")
    lines.append(
        f"- **Implemented by** — "
        f"{list_cell(_spans(record.component_refs), absent=_UNADDRESSABLE)}"
    )
    if interface is not None and interface.has_subcommands:
        lines.append(
            "- **Has subcommands** — the commands under it are the next "
            "headings below."
        )
    lines.append("")
    if record.manual_exception:
        lines.extend([record.manual_exception, ""])

    if interface is None:
        lines.extend(
            [
                "This build composed the command without the parser reading "
                "that carries its arguments and options, so they are not "
                "listed here.",
                "",
            ]
        )
        return lines

    if interface.arguments:
        lines.extend(
            [
                "| Argument | How many | Default | Accepted values |",
                "| --- | --- | --- | --- |",
                *(_argument_row(item) for item in interface.arguments),
                "",
            ]
        )
    if interface.options:
        lines.extend(
            [
                "| Option | Takes | Default | Accepted values |",
                "| --- | --- | --- | --- |",
                *(_option_row(item) for item in interface.options),
                "",
            ]
        )
    if not interface.arguments and not interface.options:
        lines.extend(["It takes no arguments and no options of its own.", ""])
    return lines


def _command_overview(
    records: Sequence[SurfaceRecord], slugs: Mapping[str, str]
) -> list[str]:
    """Every command on one screen, each linked to its own entry.

    Three columns, and the middle one carries a whole help line rather
    than a shortened form of it. A long help line therefore makes a tall
    row and not a wide page, which is the trade this page takes: a table
    cell wraps, and a shortened quotation stops being one.
    """
    return [
        "| Command | What it does | Touches |",
        "| --- | --- | --- |",
        *(
            f"| [`{cell(heading_of(record.id))}`](#{slugs[record.id]}) "
            f"| {cell(record.intent) if record.intent else ABSENT} "
            f"| {_effect_words(record)} |"
            for record in records
        ),
        "",
    ]


def cli_reference(
    bundle: DocsBundle, *, interfaces: Sequence[CommandInterface] = ()
) -> str:
    """Every command ``s0ma`` serves, as Markdown.

    ``interfaces`` is
    :meth:`~s0ma_dsl.docs_model.providers_cli.CliProvider.interface` —
    the arguments, options, defaults and accepted values that
    ``s0ma-docs-model@1`` has no field for and that D1 hands to its
    caller instead. It arrives from the application rather than being
    read again here, for the reason
    :func:`~s0ma_dsl.docs_model.application._artifacts` takes the
    catalog's rows as a parameter: one reading of one source, and a
    renderer that read it again could describe a parser nobody composed.

    Commands are ordered by their command *path* rather than by id, which
    is what keeps a family together: ``s0ma migrate`` and
    ``s0ma migrate grammar`` are adjacent, and ``s0ma migrate-ext``
    follows them both instead of splitting them.
    """
    records = _on_channel(bundle, CLI_CHANNEL)
    slugs = _anchored(records)
    by_id = {item.id: item for item in interfaces}
    ordered = sorted(records, key=lambda record: tuple(heading_of(record.id).split(" ")))
    read = [by_id[record.id] for record in ordered if record.id in by_id]
    bound = sum(1 for record in ordered if record.component_refs)

    lines = [
        "# The s0ma command line",
        "",
        GENERATED_NOTE,
        "",
        f"Every command `s0ma` serves, read off the command-line parser your "
        f"shell actually meets rather than from a list somebody kept up to "
        f"date. This build serves {len(ordered)} commands with "
        f"{sum(len(item.options) for item in read)} options and "
        f"{sum(len(item.arguments) for item in read)} arguments between "
        f"them, and {bound} of the {len(ordered)} reach code the model can "
        f"point at.",
        "",
        "A line here is wrong? The place to fix it is the command — its "
        "help text, its flags, or what its handler does — and the next "
        "build writes this page again.",
        "",
        *_elsewhere(),
        "## How to read this page",
        "",
        "**What it does** is the command's own help line, quoted. **Touches** "
        "is what running it does to the world, in the vocabulary every "
        "capability s0ma serves is described with: `read`, `write`, "
        "`network`, `subprocess`, `credential`, `approval`, and `none` for "
        "one that genuinely does nothing. A command is listed with every "
        "word that is true of it.",
        "",
        "Under each command, **Default** is what the value is when you do "
        "not give one, and an option that takes no value is a switch that "
        "is off unless you write it. **Accepted values** is a closed set: "
        "anything else is refused. A dash means the fact is not there — no "
        "default, or no closed set — rather than that nobody filled it in.",
        "",
        "The sentence under each command's facts says two things the parser "
        "cannot: which code the command runs, and what that code does to "
        "your project. Both were read by a person and written down, which "
        "is why they are one paragraph rather than another table.",
        "",
        f"{_source_sentence(records)}",
        "",
        "## Every command",
        "",
    ]
    if not ordered:
        lines.extend(_nothing_here("commands"))
        return _page(lines)

    lines.extend(_command_overview(ordered, slugs))
    for record in ordered:
        lines.extend(_command_section(by_id.get(record.id), record))
    return _page(lines)


# ---------------------------------------------------------------------------
# Project settings
# ---------------------------------------------------------------------------


def _rule_note(record: SurfaceRecord) -> str:
    """The structural rule written about one key, without the boilerplate.

    Every configuration record's ``manual_exception`` begins with the one
    sentence D2 writes about every key — that no registered component
    implements a configuration key — and a rule, where there is one, is
    appended to it. The shared opening is dropped here by matching the
    provider's own exported constant rather than by looking for a full
    stop, so this is a slice of the sourced text at a boundary the source
    defines and not a rewording of it. A record that does not start with
    the constant is carried whole, because the alternative is dropping a
    sentence nobody has read.
    """
    prefix = summary_line(CONFIG_UNBOUND_EXCEPTION)
    written = record.manual_exception
    if not written.startswith(prefix):
        return written
    return written[len(prefix) :].strip()


def _key_section(record: SurfaceRecord, facts: Mapping[str, str]) -> list[str]:
    """One key's entry: what it is for, what it takes, and what it refuses."""
    lines = [f"### {heading_of(record.id)}", ""]
    if record.intent:
        lines.extend([record.intent, ""])
    lines.append(f"- **Written as** — `{cell(record.public_name)}`")
    lines.append(f"- **Type** — {_type_words(facts.get('type', ''))}")
    lines.append(f"- **Default** — {_default_words(facts.get('default', ''))}")
    values = facts.get("values", "")
    if values:
        lines.append(
            f"- **Accepted values** — "
            f"{', '.join(f'`{cell(item)}`' for item in values.split(','))}"
        )
    rule = facts.get("rule", "")
    if rule:
        lines.append(f"- **Checked by** — `{cell(rule)}`")
    lines.append(f"- **Addressed as** — `{record.id}`")
    lines.append("")
    note = _rule_note(record)
    if note:
        lines.extend([note, ""])
    return lines


def _type_words(stated: str) -> str:
    """A key's authored type, or the honest word for one nobody states."""
    if not stated or stated == UNSTATED:
        return "not stated by the loader"
    return f"`{cell(stated)}`"


def _default_words(stated: str) -> str:
    """A key's default, or the honest word for one that is worked out."""
    if not stated:
        return ABSENT
    if stated == COMPUTED:
        return "worked out from the project"
    return f"`{cell(stated)}`"


def configuration_reference(bundle: DocsBundle) -> str:
    """Every key a project may set under ``[tool.s0ma]``, as Markdown.

    The key set is the set of keys the project loader really reads —
    D2's reading of ``project.py``, composed into this bundle — so a key
    the product stops reading leaves this page by itself, and one it
    starts reading arrives by itself.
    """
    records = _on_channel(bundle, CONFIG_CHANNEL)
    slugs = _anchored(records)
    facts = {record.id: _facts(record) for record in records}
    with_values = sum(1 for record in records if facts[record.id].get("values"))
    with_rules = sum(1 for record in records if facts[record.id].get("rule"))

    lines = [
        "# Project settings",
        "",
        GENERATED_NOTE,
        "",
        f"Everything a project can say about itself in its "
        f"`pyproject.toml`, under the `{TABLE}` table. This build reads "
        f"{len(records)} keys; {with_values} of them accept a closed set of "
        f"values and nothing else, and {with_rules} carry a structural rule "
        f"the loader enforces when your project is opened.",
        "",
        "The keys are what the project loader actually reads, so this page "
        "cannot describe a setting the product has stopped honouring, and a "
        "setting it starts honouring appears here at the next build.",
        "",
        *_elsewhere(),
        "## How to read this page",
        "",
        "**Type** is the type you write in TOML — a string, a list of "
        "strings, a table — taken from the words the loader itself uses "
        "when it refuses the wrong one. Three keys are validated through "
        "helpers that name no type, and those say so rather than carrying a "
        "type somebody guessed.",
        "",
        "**Default** is what you get when you leave the key out. `None` "
        "means the key is simply unset and nothing stands in for it; one "
        "key's default is worked out from the project's own name and says "
        "so.",
        "",
        "**Accepted values** is the closed set the loader validates "
        "against: writing anything else is refused when the project is "
        "opened. **Checked by** names the rule in the loader that governs "
        "the key, and the paragraph under a key with one says what that "
        "rule is.",
        "",
        f"{_source_sentence(records)}",
        "",
        "## Every setting",
        "",
    ]
    if not records:
        lines.extend(_nothing_here("project settings"))
        return _page(lines)

    lines.extend(
        [
            "| Setting | What it is for | Type | Default |",
            "| --- | --- | --- | --- |",
            *(
                f"| [`{cell(heading_of(record.id))}`](#{slugs[record.id]}) "
                f"| {cell(record.intent) if record.intent else ABSENT} "
                f"| {_type_words(facts[record.id].get('type', ''))} "
                f"| {_default_words(facts[record.id].get('default', ''))} |"
                for record in records
            ),
            "",
        ]
    )
    for record in records:
        lines.extend(_key_section(record, facts[record.id]))
    return _page(lines)


# ---------------------------------------------------------------------------
# Reports s0ma can make
# ---------------------------------------------------------------------------


def _mode_order(
    records: Sequence[SurfaceRecord],
    facts: Mapping[str, Mapping[str, str]],
    declared: Sequence[str],
) -> tuple[str, ...]:
    """The modes to show, in the order the product ramps through them.

    ``declared`` is the strictness ladder as the product declares it —
    migration to release — which is the whole content of that ordering
    and is thrown away by sorting. A mode that appears on a record and
    not in ``declared`` is still shown, sorted, after the declared ones:
    the rule :func:`~s0ma_dsl.docs_model.inventories._channel_order`
    follows, for the same reason. An index that quietly dropped a column
    would hide exactly the thing a severity table exists to show.
    """
    present = {
        key for record in records for key in facts[record.id] if key != REGISTRY_KEY
    }
    known: list[str] = []
    for mode in declared:
        if mode in present and mode not in known:
            known.append(mode)
    return (*known, *sorted(present - set(known)))


def _severity_words(value: str | None) -> str:
    """One severity cell: the product's word, a reader's word, or absent."""
    if value is None:
        return ABSENT
    return SEVERITY_WORDS.get(value, f"`{cell(value)}`")


def _code_section(
    record: SurfaceRecord, facts: Mapping[str, str], modes: Sequence[str]
) -> list[str]:
    """One code's entry: what it means, and how strictness changes it."""
    lines = [f"### {heading_of(record.id)}", ""]
    if record.intent:
        lines.extend([record.intent, ""])
    ladder = [(mode, facts.get(mode)) for mode in modes]
    stated = [(mode, value) for mode, value in ladder if value is not None]
    if stated:
        written = ", ".join(
            f"{mode} {_severity_words(value)}" for mode, value in stated
        )
        lines.append(f"- **Severity by mode** — {written}")
    elif facts.get(REGISTRY_KEY) == OUT_OF_MATRIX_REGISTRY:
        lines.append(
            "- **Severity by mode** — not in the table. The strictness mode "
            "a project is in does not change how this one is reported."
        )
    else:
        lines.append(f"- **Severity by mode** — {ABSENT}")
    lines.append(f"- **Addressed as** — `{record.id}`")
    lines.append("")
    return lines


def diagnostics_reference(bundle: DocsBundle, *, modes: Sequence[str] = ()) -> str:
    """Every report s0ma can make about a project, as Markdown.

    ``modes`` is
    :meth:`~s0ma_dsl.docs_model.providers_diagnostics.DiagnosticsProvider.modes`
    — the strictness ladder in the order the enum declares it. It arrives
    from the application for :func:`cli_reference`'s reason: the order is
    a fact of ``config.py`` that the composed records carry no field for,
    and re-reading the file here would let this page describe a ladder
    nobody composed.

    Every code is a section of its own with a stable anchor, because the
    point of this page is that a build which failed on ``BARE_IMPORT``
    can hand a reader the entry about ``BARE_IMPORT``.
    """
    records = _on_channel(bundle, DIAGNOSTIC_CHANNEL)
    slugs = _anchored(records)
    facts = {record.id: _facts(record) for record in records}
    order = _mode_order(records, facts, modes)
    laddered = sum(
        1 for record in records if facts[record.id].get(REGISTRY_KEY) == MATRIX_REGISTRY
    )

    lines = [
        "# Reports s0ma can make",
        "",
        GENERATED_NOTE,
        "",
        f"Every report s0ma can make about a project, with what it means "
        f"and how seriously it is taken. This build registers "
        f"{len(records)} of them: {laddered} get more serious as a project "
        f"tightens its strictness, and {len(records) - laddered} are the "
        f"same whatever mode the project is in.",
        "",
        "Each report has an entry of its own further down, so a build that "
        "stopped on one can send you straight to it.",
        "",
        "A report's code is its permanent name: once a code has shipped it is "
        "never renamed and never given to a different report, so a script or "
        "an agent can match on it safely. The sentence beside it is written "
        "for a person and is improved between releases. "
        "[What can change, and how you will know](../stability.md) says so in "
        "full.",
        "",
        *_elsewhere(),
        "## How to read this page",
        "",
        "s0ma reads a project in one of four **modes**, each stricter than "
        "the last, and a project chooses which. The same finding can be "
        "worth mentioning in the first and worth stopping for in the "
        "fourth, so most reports have a severity per mode rather than one "
        "severity.",
        "",
        "A mode column says `warning` when the report is made and the work "
        "goes on, `error` when the work stops, and *not checked* when the "
        "report is not made at all in that mode. A dash means the report "
        "does not pass through the modes: it is raised the same way in all "
        "of them.",
        "",
        f"{_source_sentence(records)}",
        "",
        "## Severity by mode",
        "",
    ]
    if not records:
        lines.extend(_nothing_here("reports"))
        return _page(lines)

    header = " | ".join(("Report", *order))
    lines.extend(
        [
            f"| {header} |",
            f"| {' | '.join(['---'] * (len(order) + 1))} |",
            *(
                "| "
                + " | ".join(
                    (
                        f"[`{cell(heading_of(record.id))}`](#{slugs[record.id]})",
                        *(
                            _severity_words(facts[record.id].get(mode))
                            for mode in order
                        ),
                    )
                )
                + " |"
                for record in records
            ),
            "",
            "## Every report",
            "",
        ]
    )
    for record in records:
        lines.extend(_code_section(record, facts[record.id], order))
    return _page(lines)
