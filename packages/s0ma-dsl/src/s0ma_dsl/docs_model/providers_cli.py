"""The CLI provider: every command ``s0ma`` serves, read off the parser.

Milestone D1 of the docs-function plan (internal) §9, architecture plan
§7.3. One adapter over one reading:

``python:s0ma_dsl.cli.main.S0maCLI.build_parser``
    The **constructed** ``argparse`` tree. ``S0maCLI().build_parser()``
    is called and the resulting object walked, so what is inventoried is
    what a user's shell actually meets — nesting, defaults, choices and
    all. Reading ``cli/main.py`` as text would inventory the *source of*
    the parser instead, and the two are equal only by luck.

D-4 (strict) forbids new grammar and forbids touching the parser to make
it easier to read. Nothing here changes ``build_parser``: no
``set_defaults(func=...)`` is added, no command is renamed, no help
string is rewritten. Introspection only, and where introspection cannot
answer, the record says who answered instead.

**What argparse knows, and what it does not.** The tree carries every
command path, every option and positional, every default and every
choice list, and the one-line help a person wrote for each command. It
carries nothing at all about *what runs*: this parser records no handler
on any node, so the command-to-handler edge cannot be derived from it.
That edge is transcribed, once, in :data:`_HANDLERS`, and everything
downstream of it is derived again — whether the handler is a registered
component, which component, and under what name — by asking the resolved
callable for the ``__component__`` the ``@component`` decorator attaches
to it. The transcription is held to three structural checks, so it can
go stale loudly but not silently:

1. a live command with no entry stops the reading (the C3
   ``_HAND_CLASSIFIED`` precedent: refuse rather than guess);
2. an entry naming no live command stops it too, so a deleted command
   cannot leave a fossil behind;
3. an entry whose dotted path does not resolve to a real callable stops
   it, so a renamed handler is a failure and not an empty binding.

**Three binding classes, and why every record carries an exception.**
``manual_exception`` is this model's only place to say "a person, not a
reading, is why this field says what it says", and that is true of every
record here: the handler edge was transcribed. What differs is what the
transcription bought, so the exceptions come in three counted classes
and :meth:`CliProvider.exceptions` hands D5 the class of each surface as
data rather than as prose to parse:

:data:`BOUND_DIRECTLY`
    The handler is itself a registered component — the ``docs`` family
    and ``examples run`` are these.
:data:`BOUND_TO_OWNING_CLASS`
    The handler is a method of the registered ``S0maCLI`` service, and a
    method is not separately registered, so the binding names the class
    and the record says that is what it means. Every top-level command
    is one of these.
:data:`UNBOUND_MACHINERY`
    The handler is a module-level callable nothing registers, which is
    most of the dsl's own command machinery. These reach no component
    the model can address, and the exception names the callable so that
    D5 can either register it or ratify the exception.

How many fall in each class is deliberately not written down here:
``exceptions()`` answers that against the tree in front of it, and a
count in a docstring is a count that goes stale in silence.

**Side effects are classified by hand, and the table says so.** Nothing
about a command name promises anything — there is no analogue of HTTP's
safe methods here — so every command's effects were read off its handler
and written into :data:`_SIDE_EFFECTS` with the sentence a record can
quote. A command that reaches this provider without an entry is
*refused*, exactly as C3 refuses an unclassified mutating route:
recording a writing command as a read is the one mistake a documentation
build must never make quietly.

**What this provider does not emit, and why.** ``s0ma-docs-model@1``
gives :class:`~s0ma_dsl.docs_model.records.SurfaceRecord` no field for an
option, an argument or a default — B4 deferred ``input_schema`` and
``output_schema`` deliberately, as "a large derived blob a provider
copies verbatim". The interface is still read, in full, and handed to
the caller through :meth:`CliProvider.interface` the way C3 hands over
its component inventory: a thing the model *addresses* rather than a
thing it holds. It is not folded into ``intent``, which is a quotation
of the help line and would stop being one. The day the model grows a
field for it, this milestone's ``TestOptionsHaveNoFieldInTheModel``
fails and points here.

**Two honesty rules this module is held to.**

* A surface's ``intent`` is a quotation: the help line the author wrote
  for that command, whitespace-collapsed within the line and otherwise
  verbatim. Where a command declares none, the field is empty rather
  than invented.
* The source digest covers the whole interface — commands *and* their
  options, arguments and defaults — not only the facts the records
  carry. It is the honest analogue of a file hash for something that has
  no file, and covering more than the records means a renamed option
  moves the digest even though no record moved. Missing that would be
  the drift this provider exists to make visible.

**No side effects, and no registry.** The global
:func:`s0ma.registry.get_registry` singleton is never asked for: the
binding is read off the decorated object itself, which the ``@component``
decorator leaves attached as ``__component__`` and which is therefore
true of the code rather than of whatever else this process imported.
ADR-012 §5.4 names the singleton; this module has no reason to go near
it. Nothing here writes a file or opens a socket. Importing the CLI is
unavoidable — the parser is the thing being read — and the CLI's own
registrations ask for a non-persisting registry, so no ``.s0ma`` state
is created by the reading.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from s0ma_dsl.docs_model.ids import cli_id, validate_id
from s0ma_dsl.docs_model.providers import (
    DocsProviderError,
    ProviderResult,
    SourcedRecord,
    sort_records,
)
from s0ma_dsl.docs_model.records import SCHEMA, Provenance, SurfaceRecord
from s0ma_dsl.docs_model.serialize import canonical_json, to_plain

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "BOUND_DIRECTLY",
    "BOUND_TO_OWNING_CLASS",
    "CHANNEL",
    "FLOORS",
    "PARSER_SOURCE",
    "PROGRAM",
    "PROVIDER_ID",
    "SIDE_EFFECT_WORDS",
    "UNBOUND_MACHINERY",
    "CliProvider",
    "CliProviderError",
    "CommandArgument",
    "CommandInterface",
    "CommandOption",
]

#: This adapter's stable id, and the ``adapter_id`` stamped on every
#: record it emits. Plan §5 speaks of ``(provider_id, source)``; the
#: model's word for the first half is ``adapter_id``.
PROVIDER_ID = "cli"

#: The one source, named by import path. A code source has no file whose
#: bytes mean the same thing, and an installed package's file path is a
#: machine path — which the determinism invariant forbids outright.
PARSER_SOURCE = "python:s0ma_dsl.cli.main.S0maCLI.build_parser"

#: The program name every command id hangs under (plan §5's
#: ``cli:s0ma/<command-path>``). It is also the first word of every
#: ``public_name``, because that is how a person types the command.
PROGRAM = "s0ma"

#: The channel word, from the architecture plan's §6.3 list.
CHANNEL = "cli"

#: Anti-vacuity floor for this provider, in the shape
#: :func:`~s0ma_dsl.docs_model.validate.check_floors` reads. Thirty-five
#: commands are observed today — twenty-two top level and thirteen
#: nested. The floor is thirty: low enough that retiring a command or
#: two cannot trip it, high enough that losing a whole family must.
FLOORS: Mapping[tuple[str, str], int] = {
    (PROVIDER_ID, "surfaces"): 30,
}

#: The side-effect vocabulary (architecture §6.3, D5's completeness
#: check). Every entry in :data:`_SIDE_EFFECTS` is checked against it, so
#: a typo becomes a refusal rather than a word no gate will ever match.
#:
#: Two boundaries this module draws and states, because the words do not
#: draw them by themselves:
#:
#: * ``read`` covers project discovery. Every command but ``doctor``,
#:   ``feedback`` and ``new project`` resolves a ``[tool.s0ma]`` project
#:   before it dispatches, which walks the tree looking for
#:   ``pyproject.toml``; the three that self-manage resolution read the
#:   environment or ``~/.s0ma`` instead. No command here is ``none``, and
#:   a command recorded as ``none`` would be claiming something untrue.
#: * ``credential`` marks a command that *accepts or exchanges* a secret,
#:   which today is ``feedback enroll`` and nothing else. Reading the
#:   stored access token in order to authenticate a request is part of
#:   ``network``; marking every networked feedback command
#:   ``credential`` would make the word mean "talks to the service",
#:   which is what ``network`` already means.
SIDE_EFFECT_WORDS = frozenset(
    {
        "approval",
        "credential",
        "network",
        "none",
        "read",
        "subprocess",
        "write",
    }
)

#: The handler is itself a registered component: ``component_refs`` names
#: it, and the only hand-written part of the record is which callable the
#: dispatch reaches.
BOUND_DIRECTLY = "handler-registered"

#: The handler is a method of a registered class. ``component_refs``
#: names the class, which is the finest granularity the registration
#: offers, and the exception says so rather than letting the record read
#: as though the method itself were registered.
BOUND_TO_OWNING_CLASS = "class-granular"

#: The handler is a module-level callable nothing registers.
#: ``component_refs`` is empty and the exception names the callable, so
#: D5 has the import path it needs to either register it or ratify the
#: exception.
UNBOUND_MACHINERY = "handler-unregistered"


class CliProviderError(DocsProviderError):
    """The CLI provider cannot read what it was asked to read.

    A provider-contract failure, not a documentation finding. A command
    nobody has classified, a handler that no longer exists, a command id
    that does not match its frozen form — no author can fix any of them,
    and continuing would produce a build that describes a command set
    the product does not serve.
    """


# ---------------------------------------------------------------------------
# The transcribed edges: dispatch, and effects
# ---------------------------------------------------------------------------

#: Every command path mapped to the callable ``S0maCLI.run`` dispatches
#: to. **The one thing in this module a person wrote from reading the
#: code**, because argparse records no handler and inferring one from a
#: naming convention would be a guess wearing a derivation's clothes:
#: ``migrate/grammar`` alone would break any convention that fitted the
#: other twelve nested commands.
#:
#: Read from ``S0maCLI.run``'s dispatch table for the top-level commands
#: and from each group command's own dispatch for the nested ones. Held
#: to three checks by :class:`CliProvider`: complete against the live
#: parser, free of entries no live command claims, and every path
#: resolving to a real callable.
_HANDLERS: Mapping[str, str] = {
    # Top level — S0maCLI.run's dispatch table, in its order.
    "transpile": "s0ma_dsl.cli.main.S0maCLI._cmd_transpile",
    "check": "s0ma_dsl.cli.main.S0maCLI._cmd_check",
    "build": "s0ma_dsl.cli.main.S0maCLI._cmd_build",
    "migrate-layout": "s0ma_dsl.cli.main.S0maCLI._cmd_migrate_layout",
    "migrate-ext": "s0ma_dsl.cli.main.S0maCLI._cmd_migrate_ext",
    "migrate": "s0ma_dsl.cli.main.S0maCLI._cmd_migrate",
    "doctor": "s0ma_dsl.cli.main.S0maCLI._cmd_doctor",
    "inspect": "s0ma_dsl.cli.main.S0maCLI._cmd_inspect",
    "score": "s0ma_dsl.cli.main.S0maCLI._cmd_score",
    "graph": "s0ma_dsl.cli.main.S0maCLI._cmd_graph",
    "studi0": "s0ma_dsl.cli.main.S0maCLI._cmd_studi0",
    "topo": "s0ma_dsl.cli.main.S0maCLI._cmd_topo",
    "verify": "s0ma_dsl.cli.main.S0maCLI._cmd_verify",
    "verify-host": "s0ma_dsl.cli.main.S0maCLI._cmd_verify_host",
    "adopt": "s0ma_dsl.cli.main.S0maCLI._cmd_adopt",
    "new": "s0ma_dsl.cli.main.S0maCLI._cmd_new",
    "test": "s0ma_dsl.cli.main.S0maCLI._cmd_test",
    "test-conftest": "s0ma_dsl.cli.main.S0maCLI._cmd_test_conftest",
    "docs": "s0ma_dsl.cli.main.S0maCLI._cmd_docs",
    "docs/list": "s0ma_dsl.cli.docs_commands.cmd_docs_list",
    "docs/search": "s0ma_dsl.cli.docs_commands.cmd_docs_search",
    "docs/show": "s0ma_dsl.cli.docs_commands.cmd_docs_show",
    "examples": "s0ma_dsl.cli.main.S0maCLI._cmd_examples",
    "feedback": "s0ma_dsl.cli.main.S0maCLI._cmd_feedback",
    "deferred-surface": "s0ma_dsl.cli.main.S0maCLI._cmd_deferred_surface",
    # Nested — each group command's own dispatch.
    "adopt/file": "s0ma_dsl.cli.adopt_commands.cmd_adopt_file",
    # `adopt scan` is the one nested command whose dispatch reaches a
    # method rather than a module-level function. That is deliberate and
    # it is what this table records: `S0maCLI._cmd_adopt_scan` is a
    # one-line delegation to `adopt_commands.cmd_adopt_scan`, written so
    # the command binds to the registered `S0maCLI` at class granularity
    # instead of joining UNREGISTERED_HANDLERS. Pointing this entry at
    # the module-level function instead would be a truthful reading of a
    # different dispatch and would put the surface in the unbound ledger.
    "adopt/scan": "s0ma_dsl.cli.main.S0maCLI._cmd_adopt_scan",
    # `adopt init` is the second, for the same reason and by the same
    # construction (beta-prep-1-retrofit C1), `adopt draft` is the third
    # (D4), `adopt baseline` and `adopt verify-parity` are the fourth
    # and fifth (E2), and `adopt status` is the sixth and last of the
    # family (E3).
    "adopt/init": "s0ma_dsl.cli.main.S0maCLI._cmd_adopt_init",
    "adopt/draft": "s0ma_dsl.cli.main.S0maCLI._cmd_adopt_draft",
    "adopt/baseline": "s0ma_dsl.cli.main.S0maCLI._cmd_adopt_baseline",
    "adopt/verify-parity": "s0ma_dsl.cli.main.S0maCLI._cmd_adopt_verify_parity",
    "adopt/status": "s0ma_dsl.cli.main.S0maCLI._cmd_adopt_status",
    "docs/render": "s0ma_dsl.cli.docs_commands.cmd_docs_render",
    "docs/verify": "s0ma_dsl.cli.docs_commands.cmd_docs_verify",
    "docs/check-drift": "s0ma_dsl.cli.docs_commands.cmd_docs_check_drift",
    "docs/compose": "s0ma_dsl.cli.docs_commands.cmd_docs_compose",
    "docs/check": "s0ma_dsl.cli.docs_commands.cmd_docs_check",
    "examples/run": "s0ma_dsl.cli.examples_commands.cmd_examples_run",
    # `s0ma feedback` reaches run_feedback, which dispatches on the
    # subcommand; the record binds each command to the handler that
    # answers it rather than to the one-line router in between.
    "feedback/drafts": "s0ma_dsl.cli.feedback_commands.cmd_feedback_drafts",
    "feedback/submit": "s0ma_dsl.cli.feedback_commands.cmd_feedback_submit",
    "feedback/list": "s0ma_dsl.cli.feedback_commands.cmd_feedback_list",
    "feedback/delete": "s0ma_dsl.cli.feedback_commands.cmd_feedback_delete",
    "feedback/enroll": "s0ma_dsl.cli.feedback_commands.cmd_feedback_enroll",
    "migrate/grammar": "s0ma_dsl.cli.migrate_grammar.run_migrate_grammar",
}

#: What each command does to the world, and the sentence a record quotes
#: for having been told by a person rather than by a protocol.
#:
#: Every command needs an entry. There is no safe-method rule to fall
#: back on — a command's name promises nothing — so a command that
#: reaches this provider unclassified is refused, which is C3's rule for
#: a route whose method HTTP does not vouch for, applied to a channel
#: where *no* name vouches for anything.
#:
#: The five group commands (``adopt``, ``docs``, ``examples``,
#: ``migrate``, and ``feedback`` which is not one) are classified for
#: what they do when invoked bare. Three of them print usage and stop,
#: ``docs`` bare prints the learning map,
#: after the project resolution every command pays; ``feedback`` bare is
#: the interactive compose, which is the command people actually run.
_SIDE_EFFECTS: Mapping[str, tuple[tuple[str, ...], str]] = {
    "adopt": (
        ("read",),
        "Bare `s0ma adopt` resolves the project and prints the usage line "
        "for its subcommands; the project resolution is the read.",
    ),
    "adopt/file": (
        ("read", "write"),
        "It reads the named file to hash it and writes the adoption "
        "record into adopted.s0ma.json at the project root.",
    ),
    "adopt/baseline": (
        ("read", "write"),
        "It reads the Python files of the modules it was asked about and "
        "writes one file: adopt-baseline.s0ma.json at the project root, "
        "which records what each of those modules offers its callers "
        "today. The Python files are parsed and never imported, and are "
        "not changed; recording a module whose file has not changed "
        "rewrites the same bytes.",
    ),
    "adopt/verify-parity": (
        ("read",),
        "It reads the build manifest, the .py files the build emitted and "
        "the committed baselines, compares them, and prints what differs. "
        "It writes nothing anywhere, and the built module is parsed rather "
        "than imported — importing it would run the code the comparison is "
        "there to judge.",
    ),
    "adopt/draft": (
        ("read", "write"),
        "It reads the project's Python files to work out which module was "
        "asked for and what layer to propose, and writes exactly one new "
        "file: the .s0ma draft of that module. The Python file it read is "
        "parsed and never imported, and is not modified, moved or deleted; "
        "an existing draft is never written over without --force, and "
        "--dry-run writes nothing.",
    ),
    "adopt/init": (
        ("read", "write"),
        "It reads every Python file in the tree it is pointed at and then "
        "writes exactly two things: the [tool.s0ma] table appended to "
        "pyproject.toml, and one marked block in AGENTS.md. No "
        "application file is touched, and --dry-run writes nothing.",
    ),
    "adopt/scan": (
        ("read",),
        "It reads every Python file in the tree it is pointed at and "
        "prints what it found; it writes nothing at all — no report file, "
        "no cache, and nothing beside the sources, because it never "
        "imports or runs the code it is reading.",
    ),
    "adopt/status": (
        ("read",),
        "It reads the project's configuration, its Python files, the "
        ".s0ma drafts beside them, the committed baselines and whatever "
        "the build emitted, and prints where the retrofit stands. It "
        "writes nothing at all — no report file, no cache — and neither "
        "the Python nor the built modules are ever imported or run.",
    ),
    "build": (
        ("read", "write"),
        "It reads every source root and writes the generated .py, "
        ".s0ma.json and .s0ma.map files plus the build cache, which "
        "--clean removes first.",
    ),
    "check": (
        ("read", "write"),
        "It parses and validates the configured sources and generates no "
        "build output, which is the difference between it and build — but "
        "it does keep one bookkeeping note, updating "
        ".s0ma/check-baseline.json on every run (the [NEW]-marker "
        "baseline), which E3's evidence verified by mtime and content.",
    ),
    "deferred-surface": (
        ("read",),
        "It scans the project's sources for deferred: markers and prints "
        "what it found.",
    ),
    "docs": (
        ("read",),
        "Bare `s0ma docs` reads the composed documentation snapshot and "
        "prints the learning map; the snapshot read is the read.",
    ),
    "docs/list": (
        ("read",),
        "It reads the composed documentation snapshot and prints every "
        "topic of one part of it. It writes nothing and reaches no "
        "network.",
    ),
    "docs/search": (
        ("read",),
        "It reads the composed documentation snapshot and prints the "
        "topics a question could have meant. It writes nothing and "
        "reaches no network.",
    ),
    "docs/show": (
        ("read",),
        "It reads the composed documentation snapshot and prints one "
        "topic in full. It writes nothing and reaches no network.",
    ),
    "docs/check": (
        ("read",),
        "It composes the documentation snapshot and byte-compares it "
        "against the committed outputs, writing nothing — that is the "
        "whole difference between it and compose.",
    ),
    "docs/check-drift": (
        ("read",),
        "It re-renders every doc declaration in memory and byte-compares "
        "the result against the committed files without touching them.",
    ),
    "docs/compose": (
        ("read", "write"),
        "It composes the documentation snapshot from its providers and "
        "writes every declared output under the documentation root.",
    ),
    "docs/render": (
        ("read", "write"),
        "It renders every doc-ref and doc-guide to its declared output: "
        "path.",
    ),
    "docs/verify": (
        ("read",),
        "It runs the doc-subsystem validation layers over an in-memory "
        "render and writes nothing.",
    ),
    "doctor": (
        ("read",),
        "It reports on the environment and the project — installed "
        "versions, project detection, build freshness — and changes "
        "neither.",
    ),
    "examples": (
        ("read",),
        "Bare `s0ma examples` resolves the project and prints the usage "
        "line for its one subcommand; the project resolution is the read.",
    ),
    "examples/run": (
        ("read", "subprocess", "write"),
        "It parses the named sources and hands each registered example "
        "declaration to the example dispatcher, which writes the body to "
        "a throwaway directory and runs it in a child interpreter under "
        "the --timeout budget — the same act `s0ma test` and the "
        "`run_example` tool declare (G7 corrected the earlier "
        "in-this-process claim).",
    ),
    "feedback": (
        ("approval", "network", "read", "write"),
        "Bare `s0ma feedback` is the interactive compose: it reads the "
        "machine's stored enrolment, saves the report as a local draft, "
        "shows it, and sends it to the s0ma service only after you "
        "approve it.",
    ),
    "feedback/delete": (
        ("approval", "network", "read"),
        "It asks the service what you have on file and deletes; a report "
        "id is its own confirmation, and --all previews the whole list "
        "and asks before deleting any of it.",
    ),
    "feedback/drafts": (
        ("read", "write"),
        "It lists the unsent reports stored on this machine and removes "
        "the ones older than the draft retention window, which is the "
        "write.",
    ),
    "feedback/enroll": (
        ("credential", "network", "read", "write"),
        "It takes your license key — from --key or from S0MA_LICENSE_KEY "
        "— exchanges it with the service for an access code, and stores "
        "that code at ~/.s0ma/feedback-token.",
    ),
    "feedback/list": (
        ("network", "read"),
        "It reads the machine's stored enrolment and asks the service "
        "for the reports you have sent.",
    ),
    "feedback/submit": (
        ("approval", "network", "read", "write"),
        "It loads a saved draft, shows it again, sends it only if you "
        "approve, and removes the draft once it has been sent.",
    ),
    "graph": (
        ("read",),
        "It reads the project's build artifacts and prints the "
        "dependency graph in the requested format.",
    ),
    "inspect": (
        ("read",),
        "It reads a compiled module's self-model or the whole project's "
        "and prints what it asked for.",
    ),
    "migrate": (
        ("read",),
        "Bare `s0ma migrate` resolves the project and prints the usage "
        "line for its one subcommand; the project resolution is the read.",
    ),
    "migrate/grammar": (
        ("read", "write"),
        "It plans a whole-project grammar migration and prints the plan; "
        "with --apply it rewrites the sources the plan names.",
    ),
    "migrate-ext": (
        ("read", "write"),
        "It renames the pre-2.0.0 extension family across the project "
        "and rewrites what refers to it, unless --dry-run stops it at "
        "the plan.",
    ),
    "migrate-layout": (
        ("read", "write"),
        "It removes the legacy cache and per-layer subdirectories from "
        "the build directory and then runs a fresh build into it.",
    ),
    "new": (
        ("read", "write"),
        "It writes a scaffolded declaration file, or for `new project` a "
        "whole project tree including its pyproject.toml.",
    ),
    "score": (
        ("read",),
        "It reads the project and its policy input and prints the "
        "self-knowledge score; the gate flags change only the exit code.",
    ),
    "studi0": (
        ("network", "read", "subprocess"),
        "It serves the viewer over a loopback socket for as long as it "
        "runs, reading build artifacts only, and opens a browser process "
        "unless --no-open says not to.",
    ),
    "test": (
        ("read", "subprocess", "write"),
        "It builds every source and test root into the build directory "
        "and then runs pytest as a subprocess against it.",
    ),
    "test-conftest": (
        ("read", "write"),
        "It inspects the project's declarations and writes a conftest.py, "
        "refusing to overwrite an existing one without --force.",
    ),
    "topo": (
        ("read",),
        "It parses each module far enough to read its uses: edges and "
        "prints the import order.",
    ),
    "transpile": (
        ("read", "write"),
        "It writes the generated .py, .s0ma.json and .s0ma.map for every "
        "source it is given, except under --check, which compares "
        "against a temporary directory instead.",
    ),
    "verify": (
        ("read",),
        "It hashes the transpiled files and compares them against their "
        "sources without transpiling anything.",
    ),
    "verify-host": (
        ("read", "subprocess"),
        "It runs the host Python as a subprocess and has it import the "
        "built production modules, which executes the project's own "
        "code.",
    ),
}


# ---------------------------------------------------------------------------
# Small shared readings
# ---------------------------------------------------------------------------


def _summary_line(text: str | None) -> str:
    """The first non-empty line of ``text``, whitespace-collapsed.

    C3's rule, applied to a help string. A record carries the line the
    author wrote rather than a rewording of it: selecting the first line
    is not a paraphrase, and the collapse only touches runs of
    whitespace inside that one line. Where a command declares no help the
    answer is the empty string, which is an answer.
    """
    if not text:
        return ""
    for line in text.splitlines():
        collapsed = " ".join(line.split())
        if collapsed:
            return collapsed
    return ""


def _default_text(value: object) -> str:
    """One default, written the same way on every run.

    Only the shapes argparse actually holds in this parser are accepted —
    the absent default, a flag's boolean, a number, a string, and the
    empty list a repeatable option starts from. Anything else is refused
    rather than stringified: ``str()`` of an arbitrary object embeds a
    memory address, and a record carrying one would serialize differently
    on every run, which is the determinism invariant's plainest failure.
    """
    if value is None or value is argparse.SUPPRESS:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list | tuple) and not value:
        return "[]"
    raise CliProviderError(
        f"a command declares {value!r} as a default, which this provider "
        f"cannot write down deterministically. Add the shape to "
        f"_default_text with the text it should have, or give the option a "
        f"default the model can carry — a default rendered through str() "
        f"can embed a memory address and serialize differently every run."
    )


def _choice_text(choices: object) -> tuple[str, ...]:
    """One option's accepted values, in the order the parser declares them.

    Declared order, not sorted order: ``--mode`` runs from the most
    permissive to the strictest, and sorting it alphabetically would
    throw away the only thing that ordering says.
    """
    if choices is None:
        return ()
    if isinstance(choices, dict):  # a subparsers action; handled elsewhere
        return ()
    if not isinstance(choices, list | tuple):
        return ()
    return tuple(str(item) for item in choices)


def _provenance(digest: str) -> Provenance:
    """The one source's stamp, with all four parts the contract requires."""
    return Provenance(
        adapter_id=PROVIDER_ID,
        schema_version=SCHEMA,
        source=PARSER_SOURCE,
        source_sha256=digest,
    )


def _digest(*parts: object) -> str:
    """The sha256 of everything the parser was asked, as 64 hex characters.

    Not a file hash: an import path names no file whose bytes mean the
    same thing. This covers the whole interface — every command, option,
    argument and default — and not only the facts the records carry, so
    that renaming an option moves the digest even though ``@1`` gives the
    record nowhere to put an option. The canonical form is C1's, so the
    digest cannot disagree with the bytes a bundle serializes to.
    """
    return hashlib.sha256(canonical_json(to_plain(parts)).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# What one command's interface is
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class CommandOption:
    """One flag of one command, as the parser holds it.

    ``flags`` is sorted so ``--quiet`` and ``-q`` always appear in one
    order; ``dest`` is the name the value arrives under, which is not
    always derivable from the flags (``--format`` stores to
    ``output_format`` on most commands and that difference is a fact
    about the command, not a detail of this reading).
    """

    flags: tuple[str, ...]
    dest: str
    takes_value: bool
    default: str
    choices: tuple[str, ...]


@dataclass(frozen=True, order=True)
class CommandArgument:
    """One positional of one command.

    ``required`` is derived from ``nargs``: argparse's ``?`` and ``*``
    are the two forms a user may leave out, and everything else has to be
    given. ``nargs`` is carried as well, because "may be repeated" and
    "may be omitted" are different facts and one word carries both.
    """

    dest: str
    nargs: str
    required: bool
    default: str
    choices: tuple[str, ...]


@dataclass(frozen=True, order=True)
class CommandInterface:
    """Everything the parser knows about one command.

    The part of this reading the model has nowhere to hold. It is handed
    to the caller rather than minted into a record that would have to
    lie about what it is — the same seam C3 uses for its component
    inventory.
    """

    id: str
    path: tuple[str, ...]
    public_name: str
    intent: str
    has_subcommands: bool
    options: tuple[CommandOption, ...]
    arguments: tuple[CommandArgument, ...]


@dataclass(frozen=True)
class _SurfaceDraft:
    """A surface's facts before its provenance is known.

    The digest of a source covers what was read from it, and that has to
    exist before the stamp carrying the digest can be built. A draft is
    that intermediate state, and it is a dataclass so the same canonical
    serializer covers it.
    """

    id: str
    channel: str
    public_name: str
    intent: str
    component_refs: tuple[str, ...]
    manual_exception: str
    governed_by: tuple[str, ...]
    side_effects: tuple[str, ...]
    errors: tuple[str, ...]

    def record(self, provenance: Provenance) -> SurfaceRecord:
        """The real record, stamped."""
        return SurfaceRecord(
            id=self.id,
            channel=self.channel,
            public_name=self.public_name,
            intent=self.intent,
            component_refs=self.component_refs,
            manual_exception=self.manual_exception,
            governed_by=self.governed_by,
            side_effects=self.side_effects,
            errors=self.errors,
            provenance=provenance,
        )


# ---------------------------------------------------------------------------
# Walking the constructed parser
# ---------------------------------------------------------------------------


def _subparser_actions(parser: argparse.ArgumentParser) -> list[Any]:
    """Every ``add_subparsers`` action hanging off one parser."""
    return [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]


def _choice_help(action: Any, name: str) -> str:
    """The help string argparse recorded for one subcommand choice.

    This is what ``s0ma --help`` prints beside the command's name, and it
    is the sentence the author wrote to say what the command is for.
    """
    for pseudo in action._choices_actions:
        if pseudo.dest == name:
            return _summary_line(pseudo.help)
    return ""


def _option(action: argparse.Action) -> CommandOption:
    """One optional action as a fact.

    ``nargs == 0`` is argparse's own way of saying a flag stores a
    constant rather than taking a value, so ``takes_value`` is read from
    it rather than from the action's class name.
    """
    return CommandOption(
        flags=tuple(sorted(action.option_strings)),
        dest=action.dest,
        takes_value=action.nargs != 0,
        default=_default_text(action.default),
        choices=_choice_text(action.choices),
    )


def _argument(action: argparse.Action) -> CommandArgument:
    """One positional action as a fact."""
    nargs = action.nargs
    written = "" if nargs is None else str(nargs)
    return CommandArgument(
        dest=action.dest,
        nargs=written,
        required=written not in {"?", "*"},
        default=_default_text(action.default),
        choices=_choice_text(action.choices),
    )


def _interface(
    path: tuple[str, ...], parser: argparse.ArgumentParser, intent: str
) -> CommandInterface:
    """One command's whole interface, read off its own parser.

    ``-h/--help`` is excluded, and the exclusion is structural rather
    than a list of flag names that could rot: argparse's help action is
    its own class, present on every parser it builds, and it is the
    library's surface rather than the product's. C3 excludes FastAPI's
    four documentation routes the same way and for the same reason.
    """
    options: list[CommandOption] = []
    arguments: list[CommandArgument] = []
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction | argparse._SubParsersAction):
            continue
        if action.option_strings:
            options.append(_option(action))
        else:
            arguments.append(_argument(action))
    return CommandInterface(
        id=cli_id(*path),
        path=path,
        public_name=" ".join((PROGRAM, *path)),
        intent=intent,
        has_subcommands=bool(_subparser_actions(parser)),
        # Options are sorted: a flag list is a set a reader scans, and its
        # declaration order says nothing. Positionals are not: their order
        # is the order they are typed in, which is the whole fact.
        options=tuple(sorted(options)),
        arguments=tuple(arguments),
    )


def _walk(parser: argparse.ArgumentParser) -> tuple[CommandInterface, ...]:
    """Every command and nested subcommand of one constructed parser.

    Depth-first over the real object. Nothing is read from source text,
    and no command list is written down anywhere: the tree is the
    inventory.
    """
    found: list[CommandInterface] = []

    def walk(node: argparse.ArgumentParser, prefix: tuple[str, ...]) -> None:
        for action in _subparser_actions(node):
            choices = action.choices
            if not isinstance(choices, dict):  # pragma: no cover - argparse's shape
                continue
            for name, sub in sorted(choices.items()):
                if not isinstance(sub, argparse.ArgumentParser):  # pragma: no cover
                    continue
                path = (*prefix, str(name))
                intent = _choice_help(action, str(name)) or _summary_line(sub.description)
                found.append(_interface(path, sub, intent))
                walk(sub, path)

    walk(parser, ())
    return tuple(sorted(found, key=lambda item: item.id))


# ---------------------------------------------------------------------------
# The transcribed edges, resolved
# ---------------------------------------------------------------------------

_MISSING = object()


def _resolve(dotted: str, command: str) -> tuple[Any, Any]:
    """The callable ``dotted`` names, and the object it is defined on.

    The dotted path mixes a module with an attribute walk, so the longest
    importable prefix is found first and the rest is walked with
    ``getattr``. A path that resolves to nothing is a failure and not an
    empty binding: a renamed handler must stop the reading rather than
    quietly turn a bound surface into an unbound one.
    """
    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        try:
            module = importlib.import_module(".".join(parts[:split]))
        except ImportError:
            continue
        target: Any = module
        owner: Any = None
        for attribute in parts[split:]:
            owner = target
            target = getattr(target, attribute, _MISSING)
            if target is _MISSING:
                raise CliProviderError(
                    f"the handler {dotted!r} recorded for {command!r} does not "
                    f"exist: {attribute!r} is not there. Either the handler was "
                    f"renamed and _HANDLERS still names the old one, or the "
                    f"entry was wrong when it was written."
                )
        return target, owner
    raise CliProviderError(
        f"no part of {dotted!r} — the handler recorded for {command!r} — is an "
        f"importable module. A handler this provider cannot reach is a binding "
        f"it cannot check, so the reading stops here rather than guessing."
    )


def _registration(value: object) -> Any:
    """The ``@component`` spec attached to ``value``, or ``None``.

    The decorator returns what it decorated, unmodified, with the spec
    attached as ``__component__``. Reading it off the object is what
    makes the binding derived: it is true of the code, not of whatever
    else this process happened to import into a global registry.
    ``__dict__`` is consulted rather than ``getattr`` so a subclass does
    not inherit its parent's registration and claim to be it.
    """
    own = getattr(value, "__dict__", None)
    if own is None:
        return None
    return own.get("__component__")


def _component_id(spec: Any, dotted: str) -> str:
    """The package-qualified id of one registered component.

    The registration's own ``qualified_name`` is the id. Where it is
    absent the id is built from the module path and the name — the two
    fields the qualified name is itself built from — and where neither
    can produce a package-qualified name the binding is refused rather
    than written flat: four packages register into one registry and a
    flat name can mean two different components (plan §5).
    """
    qualified = getattr(spec, "qualified_name", "") or ""
    if not qualified:
        module_path = getattr(spec, "module_path", "") or ""
        name = getattr(spec, "name", "") or ""
        qualified = f"{module_path}.{name}" if module_path else ""
    if not qualified:
        raise CliProviderError(
            f"the component registered for {dotted!r} names no module, so it "
            f"cannot be addressed as component:<package>.<module>.<name>. "
            f"There is no honest id to bind this command to."
        )
    identifier = f"component:{qualified}"
    validate_id(identifier)
    return identifier


def _binding(command: str) -> tuple[tuple[str, ...], str, str]:
    """One command's components, its binding class, and the exception text.

    Three answers in one place because they are one decision. The
    handler is resolved, asked for its own registration, and — where it
    has none — asked what it is defined on: a method of a registered
    service is bound to that service and says so, and a module-level
    callable nothing registers is bound to nothing and says that.
    """
    dotted = _HANDLERS[command]
    handler, owner = _resolve(dotted, command)

    spec = _registration(handler)
    if spec is not None:
        identifier = _component_id(spec, dotted)
        return (
            (identifier,),
            BOUND_DIRECTLY,
            (
                f"The handler this command reaches was transcribed from the "
                f"dispatch — argparse records none — and is {dotted}, which is "
                f"itself a registered component."
            ),
        )

    if isinstance(owner, type):
        spec = _registration(owner)
        if spec is not None:
            identifier = _component_id(spec, dotted)
            return (
                (identifier,),
                BOUND_TO_OWNING_CLASS,
                (
                    f"The handler this command reaches was transcribed from the "
                    f"dispatch — argparse records none — and is {dotted}, a "
                    f"method of a registered component; the binding names the "
                    f"class because a method is not separately registered."
                ),
            )

    return (
        (),
        UNBOUND_MACHINERY,
        (
            f"The handler this command reaches was transcribed from the "
            f"dispatch — argparse records none — and is {dotted}, which nothing "
            f"registers, so this command reaches no component the model can "
            f"address."
        ),
    )


def _effects(command: str) -> tuple[tuple[str, ...], str]:
    """One command's side effects and the sentence that explains them.

    Refuses an unclassified command. There is no protocol here to fall
    back on the way HTTP's safe methods let C3 derive a route's read
    fact, so an unclassified command is an unanswered question and not a
    default.
    """
    classified = _SIDE_EFFECTS.get(command)
    if classified is None:
        raise CliProviderError(
            f"the command {command!r} is served and nobody has said what it "
            f"does. Read its handler and add it to _SIDE_EFFECTS with its "
            f"effects — none, read, write, network, subprocess, credential or "
            f"approval — and the sentence a record can quote. A command name "
            f"promises nothing, so there is no safe answer to fall back on, "
            f"and recording a writing command as a read is the one mistake a "
            f"documentation build must never make quietly."
        )
    effects, reason = classified
    unknown = sorted(set(effects) - SIDE_EFFECT_WORDS)
    if unknown:
        raise CliProviderError(
            f"{command!r} is classified with {unknown}, which is not in the "
            f"side-effect vocabulary. The words are: "
            f"{', '.join(sorted(SIDE_EFFECT_WORDS))}."
        )
    if not effects:
        raise CliProviderError(
            f"{command!r} is classified with no side effects at all. A command "
            f"that genuinely does nothing to the world is written as ('none',) "
            f"— an empty tuple reads as an unanswered question."
        )
    return tuple(sorted(effects)), reason


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


class CliProvider:
    """One deterministic reading of the ``s0ma`` command-line interface.

    Everything is read when the provider is built, and :meth:`provide`
    hands over what was read. That is what the contract means by "reads
    nothing at call time": calling it twice in one process returns the
    same records because it returns the same object.

    A parser may be supplied, which is how a test describes a command
    tree this repository does not ship — a fixture parser proves the
    refusals fire without anyone having to add a real command to prove
    them. When none is supplied the live one is built, which is the only
    reading the documentation application ever wants.
    """

    def __init__(self, parser: argparse.ArgumentParser | None = None) -> None:
        live = self._live_parser() if parser is None else parser
        interfaces = _walk(live)
        if not interfaces:
            raise CliProviderError(
                "the parser served no commands. A command-line interface with "
                "no commands is not a smaller product than the one that ships, "
                "it is a reading that failed — an anti-vacuity floor cannot "
                "tell the two apart once the records are gone."
            )

        self._check_handlers({"/".join(item.path) for item in interfaces})

        drafts: list[_SurfaceDraft] = []
        exceptions: list[tuple[str, str]] = []
        for interface in interfaces:
            command = "/".join(interface.path)
            component_refs, binding_class, binding_note = _binding(command)
            side_effects, effects_note = _effects(command)
            drafts.append(
                _SurfaceDraft(
                    id=interface.id,
                    channel=CHANNEL,
                    public_name=interface.public_name,
                    intent=interface.intent,
                    component_refs=component_refs,
                    manual_exception=f"{binding_note} {effects_note}",
                    # No authority is cited. The repository provider emits the
                    # authority records, and a citation invented here would
                    # either resolve to nothing or claim a section nobody
                    # checked; D5 binds these where a section really governs.
                    governed_by=(),
                    side_effects=side_effects,
                    # argparse records no error contract. The exit-code
                    # families the product does have — the feedback family's
                    # five codes, the shared usage/validation codes — are
                    # written down in prose the parser cannot see, so the
                    # honest answer here is nothing rather than a guess.
                    errors=(),
                )
            )
            exceptions.append((interface.id, binding_class))

        provenance = _provenance(_digest(interfaces, tuple(drafts)))
        self._interfaces = interfaces
        self._exceptions = tuple(sorted(exceptions))
        self._component_ids = tuple(
            sorted({item for draft in drafts for item in draft.component_refs})
        )
        self._result = ProviderResult(
            provider_id=PROVIDER_ID,
            records=sort_records(
                SourcedRecord.of(draft.record(provenance)) for draft in drafts
            ),
        )

    @staticmethod
    def _live_parser() -> argparse.ArgumentParser:
        """The constructed parser, built the way the program builds it.

        The import is deferred to here rather than taken at module level
        for the reason C3 defers ``fastapi``: importing the whole CLI is
        a cost every reader of ``docs_model`` would otherwise pay, and
        this is the one function that needs it.
        """
        from s0ma_dsl.cli.main import S0maCLI

        return S0maCLI().build_parser()

    @staticmethod
    def _check_handlers(commands: set[str]) -> None:
        """The transcribed dispatch still describes the parser it was read from.

        Both directions. A live command with no entry would silently lose
        its binding, and an entry naming no live command is a fossil that
        would keep a deleted command's handler alive in review. Neither
        is reported as a finding: an author cannot fix either, and the
        records that would come out are wrong rather than incomplete.
        """
        unmapped = sorted(commands - set(_HANDLERS))
        if unmapped:
            raise CliProviderError(
                f"the parser serves {unmapped} and _HANDLERS says nothing about "
                f"them. argparse records no handler, so the dispatch has to be "
                f"read and written down before a record can claim what "
                f"implements a command — add each one with the callable "
                f"S0maCLI.run (or its group command) dispatches to."
            )
        stray = sorted(set(_HANDLERS) - commands)
        if stray:
            raise CliProviderError(
                f"_HANDLERS names {stray}, which this parser does not serve. "
                f"Either the command was removed and its entry should go with "
                f"it, or the entry's command path is misspelled — a fossil here "
                f"keeps a handler in review that nothing reaches."
            )

    @property
    def provider_id(self) -> str:
        """This adapter's stable id, unique across the registry."""
        return PROVIDER_ID

    def provide(self) -> ProviderResult:
        """The records read at construction, sorted, stamped, unchanged."""
        return self._result

    def interface(self) -> tuple[CommandInterface, ...]:
        """Every command's options, arguments and defaults, sorted by id.

        What ``s0ma-docs-model@1`` has nowhere to hold. It is handed over
        here rather than minted into a record type that would have to
        lie about what it is — the same seam
        :meth:`~s0ma_dsl.docs_model.providers_core.CoreProvider.external_ids`
        uses for the component inventory. D6's generated references are
        the point of need; when a field for it arrives, this is what
        fills it.
        """
        return self._interfaces

    def interface_of(self, identifier: str) -> CommandInterface:
        """One command's interface, refusing an id this reading has no command for."""
        for item in self._interfaces:
            if item.id == identifier:
                return item
        raise CliProviderError(
            f"{identifier!r} is not a command this reading found. The commands "
            f"are addressed as cli:s0ma/<command-path>, with nested commands "
            f"joined by slashes."
        )

    def component_ids(self) -> tuple[str, ...]:
        """Every registered component a command of this reading reaches, sorted.

        The dsl's own commands bind to dsl components, and the core
        provider vouches only for core's, so without this the reference
        resolver would report every one of these bindings unresolved —
        which would be the truthful answer if nobody had said what
        components exist. This provider has said: each id here was read
        off a registration attached to the callable the dispatch reaches,
        not written down anywhere.
        """
        return self._component_ids

    def external_ids(self) -> tuple[str, ...]:
        """Everything this provider vouches for but does not hold.

        Hand this to ``ReferenceIndex`` or ``validate_bundle`` alongside
        the core provider's. Components are the only class of addressed
        id this reading produces — the CLI registers no runnable
        examples — so the two answers are the same tuple today, and the
        second name exists because it is the seam C2 built and the one
        every provider is asked for.
        """
        return self._component_ids

    def exceptions(self) -> tuple[tuple[str, str], ...]:
        """Every surface paired with its binding class, sorted.

        The exception ledger as data. D5 counts these against its stated
        ceiling and decides which classes to close; parsing the prose out
        of ``manual_exception`` to do it would make the ledger depend on
        the wording rather than on the decision behind it.
        """
        return self._exceptions
