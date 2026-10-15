"""Gates for D1 — the CLI provider, held against the live parser.

Milestone D1 of the docs-function plan (internal) §9. The provider reads
the constructed ``argparse`` tree in process, so almost every check here
can be made against the thing itself: the parser is built a second time,
independently, and asked what it serves. A fixture would only prove that
this file agrees with itself.

What these tests hold in place:

* **parity with the live boundary** — the record count equals the number
  of commands a second, independently built parser serves; every command
  it serves has a record and no record names a command it does not; the
  ``docs`` family includes C8's ``compose`` and ``check``; nested ids
  join with slashes, which is the form the B gate ratified;
* **the ``--help`` canary** (T2) — argparse's own rendered help for three
  commands names every option this provider derived, so an introspection
  that quietly stopped seeing a flag is caught by the surface a user
  actually reads. The help text is never the source: it is only ever
  asked whether it agrees;
* **binding** — three counted classes that partition the records, every
  bound id resolving to a registration that really exists, and nothing
  claiming a component this build cannot address;
* **side effects** — every served command classified, the vocabulary
  respected, the write-class commands carrying ``write`` and the
  read-class ones not, and an unclassified command refusing rather than
  defaulting;
* **the provider contract** — sorted, normalized, four-part provenance,
  a full sha256, and a source that is an import path rather than a file;
* **determinism** — two readings are the same bytes, in this process and
  in a fresh one under three hash seeds;
* **no machine paths** — nothing absolute reaches the serialized build;
* **anti-vacuity** — the shipped floor is met and a floor past the truth
  goes red;
* **composition** — the provider composes alone and beside the
  application's five with no findings at all.

One thing the milestone asked for and the model cannot carry is recorded
as a test rather than as prose, so that the day a field for it arrives
the test that says "there is nowhere to put this" fails and points at the
milestone that changed: :class:`TestOptionsHaveNoFieldInTheModel`.

Nothing under ``scripts/spikes`` is imported. B3 proved this reading and
is evidence, not a dependency; a test asserts that of the module too.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from s0ma_dsl.docs_model.application import (
    APPLICATION_FLOORS,
    SIDE_EFFECT_ALLOWANCES,
    registry,
)
from s0ma_dsl.docs_model.compose import Composition, compose
from s0ma_dsl.docs_model.ids import cli_id, id_form
from s0ma_dsl.docs_model.providers import ProviderRegistry, record_key
from s0ma_dsl.docs_model.providers_cli import (
    _HANDLERS,
    _SIDE_EFFECTS,
    BOUND_DIRECTLY,
    BOUND_TO_OWNING_CLASS,
    CHANNEL,
    FLOORS,
    PARSER_SOURCE,
    PROVIDER_ID,
    SIDE_EFFECT_WORDS,
    UNBOUND_MACHINERY,
    CliProvider,
    CliProviderError,
    CommandOption,
    _binding,
    _default_text,
    _digest,
    _effects,
    _resolve,
    _walk,
)
from s0ma_dsl.docs_model.records import SCHEMA, SurfaceRecord
from s0ma_dsl.docs_model.serialize import serialize_bundle
from s0ma_dsl.docs_model.validate import DOC_GATE_VACUOUS, check_floors, validate_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "s0ma_dsl"
    / "docs_model"
    / "providers_cli.py"
)

RELEASE = "0.18.1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

#: An absolute POSIX path, anywhere in the serialized build. The leading
#: context class keeps a served path inside a help string from reading as
#: one.
_POSIX_PATH = re.compile(r"""(?:^|[\s"(\[])/(?:Users|home|private|tmp|var|opt|usr|etc)/""")

#: A Windows drive letter, with the same lookbehind C3 uses.
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]")

#: The three commands the ``--help`` canary is run over: one top-level
#: command with many flags, one nested command under a group, and one
#: nested command whose only flag is its own. Three shapes, not three
#: samples of one shape.
HELP_CANARY = ("cli:s0ma/transpile", "cli:s0ma/docs/render", "cli:s0ma/feedback/enroll")


# ---------------------------------------------------------------------------
# The live boundary, read independently of the provider
# ---------------------------------------------------------------------------


def _live_parser() -> argparse.ArgumentParser:
    """A second parser, built here, so a comparison is not a restatement."""
    from s0ma_dsl.cli.main import S0maCLI

    return S0maCLI().build_parser()


def _live_command_paths(parser: argparse.ArgumentParser | None = None) -> set[tuple[str, ...]]:
    """Every command path the parser serves, walked here rather than asked for.

    Written independently of ``providers_cli._walk`` on purpose: a parity
    test that called the provider's own walker would compare the provider
    with itself.
    """
    found: set[tuple[str, ...]] = set()

    def walk(node: argparse.ArgumentParser, prefix: tuple[str, ...]) -> None:
        for action in node._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            for name, sub in action.choices.items():
                path = (*prefix, str(name))
                found.add(path)
                walk(sub, path)

    walk(parser if parser is not None else _live_parser(), ())
    return found


def _live_subparser(path: tuple[str, ...]) -> argparse.ArgumentParser:
    """The parser argparse built for one command path."""
    node = _live_parser()
    for name in path:
        for action in node._actions:
            if isinstance(action, argparse._SubParsersAction) and name in action.choices:
                node = action.choices[name]
                break
        else:  # pragma: no cover - only reachable if a canary command is retired
            raise AssertionError(f"the live parser serves no command {path}")
    return node


def _composed() -> Composition:
    return compose(ProviderRegistry.of(CliProvider()), release_version=RELEASE)


def _composed_text() -> str:
    """The CLI build's canonical text. Read from a subprocess too."""
    return serialize_bundle(_composed().bundle)


@pytest.fixture(scope="module")
def provider() -> CliProvider:
    """One reading of the CLI, shared by every test that only inspects it."""
    return CliProvider()


@pytest.fixture(scope="module")
def composition() -> Composition:
    return _composed()


def _surfaces(provider: CliProvider) -> list[SurfaceRecord]:
    return sorted(
        (
            item.record
            for item in provider.provide().records
            if isinstance(item.record, SurfaceRecord)
        ),
        key=lambda record: record.id,
    )


def _fixture_parser(*commands: str) -> argparse.ArgumentParser:
    """A tiny parser serving exactly ``commands``, for the refusal proofs."""
    parser = argparse.ArgumentParser(prog="s0ma")
    subparsers = parser.add_subparsers(dest="command")
    for name in commands:
        subparsers.add_parser(name, help=f"the {name} command")
    return parser


# ---------------------------------------------------------------------------
# The command inventory
# ---------------------------------------------------------------------------


class TestCommandInventory:
    """Every command the program serves, and nothing else."""

    def test_the_record_count_equals_the_live_parsers_command_count(
        self, provider: CliProvider
    ) -> None:
        """Derived on both sides. No number is written down in this file."""
        assert len(provider.provide().records) == len(_live_command_paths())

    def test_every_command_the_parser_serves_has_a_record(
        self, provider: CliProvider
    ) -> None:
        served = {cli_id(*path) for path in _live_command_paths()}
        assert {record.id for record in _surfaces(provider)} == served

    def test_the_inventory_holds_both_depths(self, provider: CliProvider) -> None:
        """Top-level and nested, and enough of each to be worth reading.

        The plan's acceptance says twenty-two or more top-level commands;
        the count is asserted against the live parser rather than against
        that number, and the number is only the floor it has to clear.
        """
        depths = Counter(len(path) for path in _live_command_paths())
        assert depths[1] >= 22
        assert depths[2] >= 1
        assert sum(depths.values()) == len(_surfaces(provider))

    def test_a_nested_id_joins_its_path_with_slashes(
        self, provider: CliProvider
    ) -> None:
        """The B-gate-ratified form: ``cli:s0ma/docs/render``, not the last word."""
        record = provider.interface_of("cli:s0ma/docs/render")
        assert record.path == ("docs", "render")
        assert record.public_name == "s0ma docs render"

    def test_every_id_matches_the_frozen_cli_form(self, provider: CliProvider) -> None:
        for record in _surfaces(provider):
            assert id_form(record.id) == "cli", record.id

    def test_the_docs_family_includes_the_two_commands_c8_added(
        self, provider: CliProvider
    ) -> None:
        """``compose`` and ``check`` are the documentation application's own."""
        served = {record.id for record in _surfaces(provider)}
        for name in ("render", "verify", "check-drift", "compose", "check"):
            assert f"cli:s0ma/docs/{name}" in served, name

    def test_every_record_is_on_the_cli_channel(self, provider: CliProvider) -> None:
        assert {record.channel for record in _surfaces(provider)} == {CHANNEL}

    def test_the_public_name_is_what_a_person_types(
        self, provider: CliProvider
    ) -> None:
        for record in _surfaces(provider):
            interface = provider.interface_of(record.id)
            assert record.public_name == " ".join(("s0ma", *interface.path))

    def test_intent_quotes_the_help_the_author_wrote(
        self, provider: CliProvider
    ) -> None:
        """A quotation, never a rewording (the C7 residue rule).

        Every command's intent must appear, character for character, in
        the help argparse renders for its parent — which is the text a
        person reads when they run ``s0ma --help``. The comparison drops
        whitespace entirely rather than collapsing it, because argparse's
        own formatter re-wraps that help to the terminal width and will
        break a hyphenated word across two lines; every other character
        has to be there, in order.
        """
        for record in _surfaces(provider):
            interface = provider.interface_of(record.id)
            assert interface.intent, record.id
            parent = (
                _live_subparser(interface.path[:-1])
                if len(interface.path) > 1
                else _live_parser()
            )
            rendered = "".join(parent.format_help().split())
            assert "".join(interface.intent.split()) in rendered, record.id

    def test_a_parser_with_no_commands_is_a_failed_reading(self) -> None:
        empty = argparse.ArgumentParser(prog="s0ma")
        with pytest.raises(CliProviderError, match="served no commands"):
            CliProvider(empty)


# ---------------------------------------------------------------------------
# T2 — the --help parity canary
# ---------------------------------------------------------------------------


class TestHelpParity:
    """argparse's own help agrees with what this provider derived.

    A canary against introspection gaps, never a source (architecture
    §7.3). The provider reads the action objects; a user reads the help
    text; if the two disagree, the record describes a command nobody can
    invoke the way it says.
    """

    @pytest.mark.parametrize("identifier", HELP_CANARY)
    def test_rendered_help_names_every_derived_option(
        self, provider: CliProvider, identifier: str
    ) -> None:
        interface = provider.interface_of(identifier)
        rendered = _live_subparser(interface.path).format_help()
        missing = sorted(
            flag
            for option in interface.options
            for flag in option.flags
            if flag not in rendered
        )
        assert missing == [], f"{identifier}: {missing}"

    @pytest.mark.parametrize("identifier", HELP_CANARY)
    def test_rendered_help_names_every_derived_positional(
        self, provider: CliProvider, identifier: str
    ) -> None:
        interface = provider.interface_of(identifier)
        rendered = _live_subparser(interface.path).format_help().lower()
        missing = sorted(
            argument.dest
            for argument in interface.arguments
            if argument.dest.lower() not in rendered
        )
        assert missing == [], f"{identifier}: {missing}"

    def test_the_canary_covers_a_command_with_several_options(
        self, provider: CliProvider
    ) -> None:
        """A canary over three flagless commands would pass by having nothing to check."""
        counted = sum(len(provider.interface_of(name).options) for name in HELP_CANARY)
        assert counted >= 10

    def test_the_canary_would_notice_an_option_the_help_does_not_name(self) -> None:
        """A guard nothing can trip is a guard nobody tested."""
        rendered = _live_subparser(("transpile",)).format_help()
        invented = CommandOption(
            flags=("--not-a-real-flag",),
            dest="invented",
            takes_value=True,
            default="",
            choices=(),
        )
        assert invented.flags[0] not in rendered


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------


class TestBinding:
    """Three counted classes, and what each one is allowed to claim."""

    def test_the_classes_partition_the_records(self, provider: CliProvider) -> None:
        ledger = dict(provider.exceptions())
        assert set(ledger) == {record.id for record in _surfaces(provider)}
        assert set(ledger.values()) <= {
            BOUND_DIRECTLY,
            BOUND_TO_OWNING_CLASS,
            UNBOUND_MACHINERY,
        }

    def test_every_class_is_populated(self, provider: CliProvider) -> None:
        """All three exist in this tree, so all three are exercised."""
        counted = Counter(binding for _, binding in provider.exceptions())
        assert counted[BOUND_DIRECTLY] >= 1
        assert counted[BOUND_TO_OWNING_CLASS] >= 1
        assert counted[UNBOUND_MACHINERY] >= 1

    def test_a_bound_record_names_components_and_an_unbound_one_does_not(
        self, provider: CliProvider
    ) -> None:
        ledger = dict(provider.exceptions())
        for record in _surfaces(provider):
            if ledger[record.id] == UNBOUND_MACHINERY:
                assert record.component_refs == (), record.id
            else:
                assert len(record.component_refs) == 1, record.id

    def test_every_record_says_how_its_binding_was_arrived_at(
        self, provider: CliProvider
    ) -> None:
        """The handler edge is transcribed, and every record says so.

        argparse records no handler on any node, so the one fact this
        provider could not derive is named on every record rather than
        left to a module docstring nobody reads at the point of use.
        """
        for record in _surfaces(provider):
            assert "transcribed from the dispatch" in record.manual_exception, record.id

    def test_an_unbound_record_names_the_callable_d5_has_to_deal_with(
        self, provider: CliProvider
    ) -> None:
        """A reason D5 can consume, not a placeholder."""
        ledger = dict(provider.exceptions())
        unbound = [
            record for record in _surfaces(provider) if ledger[record.id] == UNBOUND_MACHINERY
        ]
        assert unbound
        for record in unbound:
            interface = provider.interface_of(record.id)
            dotted = _HANDLERS["/".join(interface.path)]
            assert dotted in record.manual_exception, record.id
            assert "nothing registers" in record.manual_exception, record.id

    def test_a_class_granular_binding_says_it_is_class_granular(
        self, provider: CliProvider
    ) -> None:
        ledger = dict(provider.exceptions())
        granular = [
            record
            for record in _surfaces(provider)
            if ledger[record.id] == BOUND_TO_OWNING_CLASS
        ]
        assert granular
        for record in granular:
            assert "a method is not separately registered" in record.manual_exception

    def test_every_named_component_really_carries_a_registration(
        self, provider: CliProvider
    ) -> None:
        """Derived, not written down: the id is read off the object itself."""
        for identifier in provider.component_ids():
            dotted = identifier.removeprefix("component:")
            target, _ = _resolve(dotted, "this test")
            spec = getattr(target, "__dict__", {}).get("__component__")
            assert spec is not None, identifier
            assert spec.qualified_name == dotted

    def test_every_component_id_is_package_qualified(
        self, provider: CliProvider
    ) -> None:
        for identifier in provider.component_ids():
            assert id_form(identifier) == "component", identifier
            assert len(identifier.removeprefix("component:").split(".")) >= 3

    def test_the_external_ids_cover_every_reference_the_records_make(
        self, provider: CliProvider
    ) -> None:
        """Nothing this provider names is left for somebody else to vouch for."""
        referenced = {
            item for record in _surfaces(provider) for item in record.component_refs
        }
        assert referenced <= set(provider.external_ids())

    def test_the_handler_table_matches_the_parser_in_both_directions(self) -> None:
        served = {"/".join(path) for path in _live_command_paths()}
        assert set(_HANDLERS) == served

    def test_a_command_the_table_does_not_know_stops_the_reading(self) -> None:
        with pytest.raises(CliProviderError, match="says nothing about them"):
            CliProvider(_fixture_parser("not-a-real-command"))

    def test_a_table_entry_no_command_claims_stops_the_reading(self) -> None:
        """A fossil entry keeps a handler in review that nothing reaches."""
        with pytest.raises(CliProviderError, match="which this parser does not serve"):
            CliProvider(_fixture_parser("doctor"))

    def test_a_handler_that_cannot_be_reached_stops_the_reading(self) -> None:
        with pytest.raises(CliProviderError, match="importable module"):
            _resolve("not_a_module_anybody_has.handler", "doctor")

    def test_a_handler_whose_attribute_is_gone_stops_the_reading(self) -> None:
        with pytest.raises(CliProviderError, match="does not exist"):
            _resolve("s0ma_dsl.cli.main.S0maCLI._cmd_no_such_command", "doctor")

    def test_binding_is_the_same_answer_every_time(self) -> None:
        assert _binding("docs/render") == _binding("docs/render")


# ---------------------------------------------------------------------------
# T3 — side effects
# ---------------------------------------------------------------------------


class TestSideEffectClassification:
    """Read by a person, written down, and refused when nobody has read it."""

    def test_every_served_command_is_classified(self) -> None:
        assert set(_SIDE_EFFECTS) == {"/".join(path) for path in _live_command_paths()}

    def test_every_classification_uses_the_frozen_vocabulary(self) -> None:
        for command, (effects, _) in _SIDE_EFFECTS.items():
            assert set(effects) <= SIDE_EFFECT_WORDS, command
            assert effects, command

    def test_every_classification_carries_a_sentence_a_record_can_quote(self) -> None:
        for command, (_, reason) in _SIDE_EFFECTS.items():
            assert reason.strip(), command
            assert "\n\n" not in reason, command

    def test_every_record_quotes_its_own_classification(
        self, provider: CliProvider
    ) -> None:
        for record in _surfaces(provider):
            interface = provider.interface_of(record.id)
            effects, reason = _SIDE_EFFECTS["/".join(interface.path)]
            assert record.side_effects == tuple(sorted(effects)), record.id
            assert reason in record.manual_exception, record.id

    @pytest.mark.parametrize(
        "command",
        [
            "transpile",
            "build",
            "new",
            "test-conftest",
            "docs/render",
            "docs/compose",
            "adopt/file",
            "migrate-ext",
            "migrate-layout",
            "migrate/grammar",
        ],
    )
    def test_a_writing_command_says_it_writes(self, command: str) -> None:
        assert "write" in _SIDE_EFFECTS[command][0], command

    # "check" left this list at the E gate: E3's evidence proved it updates
    # .s0ma/check-baseline.json on every run (the [NEW]-marker baseline), so
    # its record now declares the write it always performed.
    @pytest.mark.parametrize(
        "command",
        [
            "verify",
            "inspect",
            "graph",
            "topo",
            "score",
            "doctor",
            "deferred-surface",
            "docs/verify",
            "docs/check-drift",
            "docs/check",
        ],
    )
    def test_a_reading_command_does_not_claim_to_write(self, command: str) -> None:
        effects = _SIDE_EFFECTS[command][0]
        assert "read" in effects, command
        assert "write" not in effects, command

    def test_the_two_docs_commands_that_look_alike_do_not_read_alike(self) -> None:
        """``compose`` writes and ``check`` does not; that is the whole difference."""
        assert "write" in _SIDE_EFFECTS["docs/compose"][0]
        assert "write" not in _SIDE_EFFECTS["docs/check"][0]

    def test_every_feedback_command_that_reaches_the_service_says_network(self) -> None:
        for command in ("feedback", "feedback/submit", "feedback/list", "feedback/delete"):
            assert "network" in _SIDE_EFFECTS[command][0], command

    def test_the_commands_that_send_ask_first(self) -> None:
        """The frozen feedback contract: nothing is sent without approval."""
        for command in ("feedback", "feedback/submit"):
            assert "approval" in _SIDE_EFFECTS[command][0], command

    def test_the_one_command_that_takes_a_key_says_credential(self) -> None:
        credentialed = sorted(
            command for command, (effects, _) in _SIDE_EFFECTS.items() if "credential" in effects
        )
        assert credentialed == ["feedback/enroll"]

    def test_the_commands_that_start_a_process_say_subprocess(self) -> None:
        starts = sorted(
            command for command, (effects, _) in _SIDE_EFFECTS.items() if "subprocess" in effects
        )
        # examples/run joined at G7: the trust-model sweep caught it
        # declaring read-only while delegating to the dispatcher's child
        # interpreter — the same act its siblings already declared.
        assert starts == ["examples/run", "studi0", "test", "verify-host"]

    def test_no_command_claims_to_do_nothing(self) -> None:
        """Every command resolves a project or reads the environment first."""
        for command, (effects, _) in _SIDE_EFFECTS.items():
            assert "none" not in effects, command

    def test_an_unclassified_command_stops_the_reading(self) -> None:
        with pytest.raises(CliProviderError, match="nobody has said what it does"):
            _effects("a-command-nobody-classified")

    def test_the_refusal_lists_the_vocabulary_it_expects(self) -> None:
        with pytest.raises(CliProviderError) as caught:
            _effects("a-command-nobody-classified")
        for word in ("read", "write", "network", "subprocess", "credential", "approval"):
            assert word in str(caught.value), word


# ---------------------------------------------------------------------------
# The interface the model has nowhere to hold
# ---------------------------------------------------------------------------


class TestCommandInterfaces:
    """Options, arguments, defaults and choices, read in full."""

    def test_every_command_has_an_interface(self, provider: CliProvider) -> None:
        assert {item.id for item in provider.interface()} == {
            record.id for record in _surfaces(provider)
        }

    def test_the_interfaces_are_sorted_by_id(self, provider: CliProvider) -> None:
        ids = [item.id for item in provider.interface()]
        assert ids == sorted(ids)

    def test_argparses_own_help_flag_is_not_the_products_surface(
        self, provider: CliProvider
    ) -> None:
        """Excluded structurally, by action class, not by a list of names."""
        for item in provider.interface():
            flags = {flag for option in item.options for flag in option.flags}
            assert "-h" not in flags, item.id
            assert "--help" not in flags, item.id

    def test_a_known_option_is_read_with_its_default_and_its_choices(
        self, provider: CliProvider
    ) -> None:
        transpile = provider.interface_of("cli:s0ma/transpile")
        mode = next(item for item in transpile.options if "--mode" in item.flags)
        assert mode.choices == ("migration", "dev", "strict", "release")
        assert mode.takes_value is True
        quiet = next(item for item in transpile.options if "--quiet" in item.flags)
        assert quiet.flags == ("--quiet", "-q")
        assert quiet.takes_value is False
        assert quiet.default == "false"

    def test_an_options_dest_is_carried_because_it_is_not_always_the_flag(
        self, provider: CliProvider
    ) -> None:
        """``--format`` stores to ``output_format``, and that is a fact."""
        transpile = provider.interface_of("cli:s0ma/transpile")
        fmt = next(item for item in transpile.options if "--format" in item.flags)
        assert fmt.dest == "output_format"

    def test_a_positional_keeps_the_order_it_is_typed_in(
        self, provider: CliProvider
    ) -> None:
        run = provider.interface_of("cli:s0ma/examples/run")
        assert [item.dest for item in run.arguments] == ["source", "name"]
        assert run.arguments[0].required is True
        assert run.arguments[1].required is False

    def test_a_choice_list_keeps_its_declared_order(
        self, provider: CliProvider
    ) -> None:
        """``--mode`` runs permissive to strict; sorting it would lose that."""
        new = provider.interface_of("cli:s0ma/new")
        mode = next(item for item in new.options if "--mode" in item.flags)
        assert mode.choices == ("migration", "dev", "strict", "release")
        assert mode.choices != tuple(sorted(mode.choices))

    def test_a_group_command_says_it_has_subcommands(
        self, provider: CliProvider
    ) -> None:
        assert provider.interface_of("cli:s0ma/docs").has_subcommands is True
        assert provider.interface_of("cli:s0ma/docs/render").has_subcommands is False

    def test_asking_for_a_command_that_is_not_served_is_refused(
        self, provider: CliProvider
    ) -> None:
        with pytest.raises(CliProviderError, match="not a command this reading found"):
            provider.interface_of("cli:s0ma/no-such-command")

    def test_a_default_the_model_cannot_write_down_is_refused(self) -> None:
        """``str()`` of an arbitrary object embeds a memory address."""
        with pytest.raises(CliProviderError, match="deterministically"):
            _default_text(object())

    def test_the_defaults_that_are_written_down_are_written_stably(self) -> None:
        assert _default_text(None) == ""
        assert _default_text(argparse.SUPPRESS) == ""
        assert _default_text(False) == "false"
        assert _default_text(True) == "true"
        assert _default_text(30) == "30"
        assert _default_text(".") == "."
        assert _default_text([]) == "[]"

    def test_the_interface_moves_the_source_digest(self) -> None:
        """An option rename must be visible even though no record carries one.

        Two parsers serving one command with one help line and one
        differently-named flag. The facts a record could carry are
        identical; the digest is not, which is what makes an option
        change drift rather than silence. Asked of the walk and the
        digest directly, because a full provider over a fixture parser
        would be refused by the handler table long before the digest
        was reached — which is itself the right behaviour.
        """
        def parser(flag: str) -> argparse.ArgumentParser:
            built = argparse.ArgumentParser(prog="s0ma")
            subparsers = built.add_subparsers(dest="command")
            doctor = subparsers.add_parser("doctor", help="Health report")
            doctor.add_argument(flag, dest="output_format", default="text")
            return built

        left = _walk(parser("--format"))
        right = _walk(parser("--output-format"))
        assert [item.id for item in left] == [item.id for item in right]
        assert [item.intent for item in left] == [item.intent for item in right]
        assert left != right
        assert _digest(left) != _digest(right)
        assert _digest(left) == _digest(_walk(parser("--format")))


class TestOptionsHaveNoFieldInTheModel:
    """``s0ma-docs-model@1`` has nowhere to put an option, and says so here.

    B4 deferred ``input_schema`` and ``output_schema`` deliberately, so a
    command's flags, positionals and defaults are read in full and handed
    to the caller rather than folded into a field that means something
    else. When a field for them arrives — D6 is the point of need — these
    tests fail, and that failure is the signal to emit them as facts.
    """

    def test_no_record_field_holds_an_option(self) -> None:
        names = set(SurfaceRecord.__dataclass_fields__)
        assert "options" not in names
        assert "arguments" not in names
        assert "input_schema" not in names

    def test_the_derived_options_reach_a_caller_through_the_accessor(
        self, provider: CliProvider
    ) -> None:
        """Ninety flags today; the floor is low enough to survive a retirement."""
        counted = sum(len(item.options) for item in provider.interface())
        assert counted >= 80

    def test_no_record_smuggles_the_interface_into_its_intent(
        self, provider: CliProvider
    ) -> None:
        """``intent`` is a quotation of the help line and stays one."""
        for record in _surfaces(provider):
            interface = provider.interface_of(record.id)
            for option in interface.options:
                for flag in option.flags:
                    assert flag not in record.intent or flag in interface.intent, record.id


# ---------------------------------------------------------------------------
# The provider contract
# ---------------------------------------------------------------------------


class TestProviderContract:
    """What every provider is held to (plan §5, architecture §7.1)."""

    def test_the_provider_satisfies_the_protocol(self, provider: CliProvider) -> None:
        assert provider.provider_id == PROVIDER_ID
        assert provider.provide().provider_id == PROVIDER_ID

    def test_the_records_arrive_sorted(self, provider: CliProvider) -> None:
        records = provider.provide().records
        assert list(records) == sorted(records, key=record_key)

    def test_reading_twice_returns_the_same_records(
        self, provider: CliProvider
    ) -> None:
        assert provider.provide() == provider.provide()

    def test_every_record_carries_all_four_parts_of_its_provenance(
        self, provider: CliProvider
    ) -> None:
        for record in _surfaces(provider):
            stamp = record.provenance
            assert stamp.adapter_id == PROVIDER_ID
            assert stamp.schema_version == SCHEMA
            assert stamp.source == PARSER_SOURCE
            assert _SHA256.match(stamp.source_sha256), record.id

    def test_the_source_is_an_import_path_and_not_a_file(
        self, provider: CliProvider
    ) -> None:
        """A code source has no file whose bytes mean the same thing."""
        sources = [source for source, _ in provider.provide().sources()]
        assert sources == [PARSER_SOURCE]
        assert sources[0].startswith("python:")

    def test_a_surface_agrees_with_the_provenance_it_was_stamped_with(
        self, provider: CliProvider
    ) -> None:
        for item in provider.provide().records:
            record = item.record
            assert isinstance(record, SurfaceRecord)
            assert record.provenance == item.provenance

    def test_the_ids_are_already_their_comparable_form(
        self, provider: CliProvider
    ) -> None:
        from s0ma_dsl.docs_model.ids import normalize_id

        for record in _surfaces(provider):
            assert normalize_id(record.id) == record.id


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """The same reading is the same bytes, here and in a fresh process."""

    def test_two_readings_are_byte_identical(self) -> None:
        assert _composed_text() == _composed_text()

    def test_two_providers_produce_equal_results(self) -> None:
        assert CliProvider().provide() == CliProvider().provide()

    def test_the_build_is_the_same_under_any_hash_seed(self) -> None:
        """Dictionary iteration is how a hash seed reaches output.

        The subparser choice map is a dictionary, so this can only be
        proved in a fresh process with the seed set.
        """
        script = (
            "from tests.test_docs_provider_cli import _composed_text;"
            "print(_composed_text(), end='')"
        )
        root = Path(__file__).resolve().parents[1]
        outputs = []
        for seed in ("0", "1", "524287"):
            environment = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(root)}
            result = subprocess.run(
                [sys.executable, "-c", script],
                check=True,
                capture_output=True,
                text=True,
                cwd=root,
                env=environment,
            )
            outputs.append(result.stdout)
        assert outputs[0] == outputs[1] == outputs[2]
        assert outputs[0] == _composed_text()


class TestNoMachinePaths:
    """The determinism invariant's hardest edge: nothing absolute, anywhere."""

    def test_no_absolute_path_reaches_the_serialized_build(self) -> None:
        text = _composed_text()
        assert not _POSIX_PATH.search(text), "an absolute POSIX path reached a record"
        assert not _WINDOWS_PATH.search(text), "a Windows path reached a record"

    def test_this_checkout_is_not_in_the_build(self) -> None:
        text = _composed_text()
        for path in (REPO_ROOT, Path.home()):
            assert str(path) not in text, path

    def test_the_pattern_would_notice_a_machine_path(self) -> None:
        assert _POSIX_PATH.search('  "source": "/Users/somebody/s0ma/cli/main.py"')
        assert _WINDOWS_PATH.search('  "source": "C:\\\\s0ma\\\\main.py"')
        assert not _POSIX_PATH.search('  "id": "cli:s0ma/docs/render"')
        assert not _WINDOWS_PATH.search('  "id": "cli:s0ma/docs/render"')


# ---------------------------------------------------------------------------
# Composition and the floors
# ---------------------------------------------------------------------------


class TestComposition:
    """The provider in a build, with every gate C2 owns run over it."""

    def test_it_registers_and_composes_with_nothing_wrong(
        self, composition: Composition
    ) -> None:
        assert composition.ok
        assert composition.findings == ()

    def test_every_gate_over_the_composed_bundle_is_silent(
        self, provider: CliProvider, composition: Composition
    ) -> None:
        findings = validate_bundle(
            composition.bundle,
            results=composition.results,
            floors=FLOORS,
            external_ids=provider.external_ids(),
        )
        assert findings == (), [finding.rendered() for finding in findings]

    def test_the_surfaces_are_the_only_group_this_provider_fills(
        self, provider: CliProvider
    ) -> None:
        counts = provider.provide().counts()
        assert counts["surfaces"] > 0
        for group in ("authorities", "concepts", "journeys", "sequences", "documents"):
            assert counts[group] == 0, group

    def test_the_shipped_floor_is_met(self, composition: Composition) -> None:
        assert check_floors(composition.results, FLOORS) == []

    def test_the_floor_sits_under_the_truth_with_room_to_move(
        self, provider: CliProvider
    ) -> None:
        """A floor at the count fails the day somebody adds a command."""
        served = len(provider.provide().records)
        floor = FLOORS[(PROVIDER_ID, "surfaces")]
        assert floor < served

    def test_a_floor_past_the_truth_reports_a_vacuous_gate(
        self, composition: Composition
    ) -> None:
        findings = check_floors(composition.results, {(PROVIDER_ID, "surfaces"): 10_000})
        assert [finding.code for finding in findings] == [DOC_GATE_VACUOUS]

    def test_a_floor_naming_a_provider_that_did_not_run_is_a_finding(self) -> None:
        assert [finding.code for finding in check_floors((), FLOORS)] == [DOC_GATE_VACUOUS]

    def test_every_surface_is_bound_or_says_why_it_is_not(
        self, provider: CliProvider
    ) -> None:
        for record in _surfaces(provider):
            assert record.component_refs or record.manual_exception.strip(), record.id

    def test_it_composes_inside_the_application_with_no_findings(self) -> None:
        """The whole composition, every gate run over the result.

        D1 registered this provider beside the application's five and
        proved the six composed clean. D5b registered it for real, so the
        claim is now made of ``registry`` itself: the application's ten,
        with the component ids each provider that knows any hands over.
        An empty ``external_ids`` would report every ``component:``
        reference unresolved, which is the truthful answer when nobody
        has said what components exist.

        E2 added the second source of ids the model addresses and does
        not hold: a transcript fixture is registered runnable evidence
        and lives outside the bundle exactly as a registered component
        does, so the library is asked here for the same reason the
        providers are.
        """
        from s0ma_dsl.docs_model.evidence import EvidenceLibrary

        known = registry(REPO_ROOT)
        assert PROVIDER_ID in set(known.ids())
        composed = compose(known, release_version=RELEASE)
        assert composed.findings == (), [
            finding.rendered() for finding in composed.findings
        ]

        external: set[str] = set(EvidenceLibrary.load(REPO_ROOT).ids())
        for item in known.providers():
            harvest = getattr(item, "external_ids", None)
            if harvest is not None:
                external.update(harvest())
        findings = validate_bundle(
            composed.bundle,
            results=composed.results,
            external_ids=sorted(external),
            floors={**dict(APPLICATION_FLOORS), **dict(FLOORS)},
            allowances=SIDE_EFFECT_ALLOWANCES,
        )
        assert findings == (), [finding.rendered() for finding in findings]

    def test_the_whole_application_build_is_byte_stable(self) -> None:
        def text() -> str:
            return serialize_bundle(
                compose(registry(REPO_ROOT), release_version=RELEASE).bundle
            )

        assert text() == text()

    def test_no_command_id_collides_with_another_providers_record(self) -> None:
        """The merge rule's hard case, asked of the real application build.

        Two providers emitting one id with different facts is a build
        error and would never reach here; identical facts merge silently,
        and the survivor's provenance is the first-sorting one. So the
        question is whether any ``cli:`` record in the composition was
        stamped by somebody else — which is what a silent merge would
        look like from outside.
        """
        known = registry(REPO_ROOT)
        cli = next(
            item for item in known.providers() if item.provider_id == PROVIDER_ID
        )
        composed = compose(known, release_version=RELEASE)
        mine = {record.id for record in _surfaces(cli)}
        assert mine
        theirs = [
            record.id
            for record in composed.bundle.surfaces
            if record.id in mine and record.provenance.adapter_id != PROVIDER_ID
        ]
        assert theirs == []


# ---------------------------------------------------------------------------
# What the module is allowed to depend on
# ---------------------------------------------------------------------------


class TestDependencies:
    """ADR-012's placement rules, checked against the source."""

    def test_the_module_imports_nothing_it_should_not(self) -> None:
        """This package and the standard library. Nothing else.

        The other three packages have providers of their own, and the
        spikes are evidence rather than dependencies, so nothing under
        ``scripts/`` may be imported either. ``s0ma`` itself is not
        needed: the binding is read off the ``__component__`` the
        decorator leaves on the object, so this provider never asks the
        global registry anything.
        """
        forbidden = ("s0ma_mcp", "s0ma_studi0", "spike_", "scripts.")
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        offenders = [name for name in imported if name.startswith(forbidden)]
        assert offenders == [], f"providers_cli.py imports {offenders}"

    def test_the_global_registry_is_never_asked_for(self) -> None:
        """ADR-012 §5.4. The binding comes off the object, not off a singleton.

        Asked of the syntax tree rather than of the text: the module
        docstring names the singleton in order to say it is not used, and
        a substring check could not tell that apart from using it.
        """
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        called: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else ""
            )
            if name in {"get_registry", "ComponentRegistry", "set_registry"}:
                called.append(name)
        assert called == [], f"providers_cli.py calls {called}"

    def test_the_cli_import_is_deferred_to_the_function_that_needs_it(self) -> None:
        """A module-level CLI import would make every reader of the model pay it."""
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        top_level: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level.append(node.module)
        for name in top_level:
            assert not name.startswith("s0ma_dsl.cli"), name

    def test_the_parser_is_never_read_as_text(self) -> None:
        """The constructed object is the source; ``cli/main.py`` is not."""
        source = MODULE_PATH.read_text(encoding="utf-8")
        for reader in ("read_text", "open(", "Path("):
            assert reader not in source, reader

    def test_the_source_is_utf8_with_line_feeds(self) -> None:
        raw = MODULE_PATH.read_bytes()
        raw.decode("utf-8")
        assert b"\r\n" not in raw


def test_no_spike_is_imported_to_make_this_reading_work() -> None:
    """B3 proved this reading and is evidence, not a dependency.

    Asked of the interpreter as well as of the source: importing the
    provider and running this suite must not have pulled a spike module
    in behind it.
    """
    loaded = sorted(name for name in sys.modules if name.startswith("spike_"))
    assert loaded == [], loaded
