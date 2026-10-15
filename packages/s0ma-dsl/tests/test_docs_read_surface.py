"""The human read surface: navigation, list, show, search (F6).

Milestone F6 of the docs-function plan (internal) §11. What this suite is
for, in the order the milestone asks for it:

* **the four commands work offline and write nothing.** Proved in a
  process with the repository's own offline guard armed, not by reading
  the code and believing it;
* **they are deterministic.** Byte-equal twice in one process, and equal
  across three processes under three ``PYTHONHASHSEED`` values — the C7
  idiom, because dictionary order is exactly the thing that reaches bytes
  by accident;
* **the navigation screen stays inside B6's budget.** The three numbers
  are read out of B6's own ``budgets.json`` rather than restated here, so
  a suite that agreed with a budget nobody declared is impossible;
* **``show`` and the resolver say the same thing.** B5's residue over the
  terminal frame and over ``--format json``: every fact the record
  carries, verbatim, on both, and nothing in front of a reader that no
  declaration accounts for;
* **the three answers have three exit codes**, and the authoring family
  still dispatches exactly where it did.

**The staged wiring.** Three new subcommands are three new addressable
surfaces, and the D1 provider's dispatch table
(``providers_cli._HANDLERS``) is D1's file, not this milestone's. The
rows this milestone needs are therefore *staged* by
:func:`staged_cli_wiring` and proved against the live parser here; the
gate applies them. :class:`TestStagedWiring` is that proof, and it is
also the exact text of the wiring note.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.cli import docs_commands
from s0ma_dsl.cli.docs_commands import (
    CATEGORY_KEYS,
    CATEGORY_OF_CHANNEL,
    GROUP_ORDER,
    GROUP_TITLES,
    LISTED_GROUPS,
    NAV_BYTE_BUDGET,
    NAV_JOURNEY_LINES,
    NAV_MAX_COLUMNS,
    NAV_MAX_LINES,
    TERMINAL_CHANNEL,
    by_category,
    category_of_topic,
    envelope_of,
    identity_line,
    navigation,
    navigation_document,
    read_more,
    render_terminal,
    terminal_spec,
    topic_index,
    undeclared_lines,
)
from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.docs_model import bundle as bundle_module
from s0ma_dsl.docs_model import render_human, render_json
from s0ma_dsl.docs_model.bundle import (
    CHECKOUT,
    INSTALLED,
    PACKAGED_LOADER,
    PACKAGED_SNAPSHOT,
    DocsBundleUnavailableError,
    Snapshot,
    checkout_root,
    checkout_snapshot,
    installed_snapshot,
    load_snapshot,
    packaged_loader,
    packaged_snapshot_path,
    register_installed_loader,
    registered_names,
    snapshot_relative_path,
    unregister_installed_loader,
)
from s0ma_dsl.docs_model.resolve import (
    IDENTITY_FACTS,
    canonical_fact,
    resolve,
)
from s0ma_dsl.docs_model.validate import CHANNEL_EFFECTS

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from s0ma_dsl.docs_model.resolve import FactValue, TopicIndex, TopicView

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "check_docs_application.py"
B6_BUDGETS = (
    REPO_ROOT
    / "scripts"
    / "spikes"
    / "docs_model"
    / "spike_b6_discovery"
    / "fixtures"
    / "budgets.json"
)

#: The topic every cross-surface identity proof is run over, named by the
#: milestone itself: ``show concept:nerve`` carries the same identity
#: fields as the F7 tool.
NERVE = "concept:nerve"

#: One topic per bundle group the surface can show, so no proof below is
#: quietly about concepts only. Chosen for what they are rather than for
#: being convenient: a command on a generated reference page, a
#: configuration key, a diagnostic, a journey that a guide covers, a
#: served capability that no generated reference page carries, a
#: document, and a written authority.
SAMPLE_TOPICS: tuple[str, ...] = (
    "authority:spec/nerve-declaration",
    "cli:s0ma/check",
    "concept:nerve",
    "config:source_roots",
    "diagnostic:DRIFT_DETECTED",
    "doc:guide/first-project",
    "journey:first-project",
    "mcp:tool/check",
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def snapshot() -> Snapshot:
    """The checkout's committed snapshot, loaded once."""
    return load_snapshot(REPO_ROOT)


@pytest.fixture(scope="module")
def index(snapshot: Snapshot) -> TopicIndex:
    return topic_index(snapshot)


def _view(index: TopicIndex, identifier: str) -> TopicView:
    return index.view(identifier)


@contextmanager
def _in(directory: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run with the working directory set, so the loader walks from there."""
    monkeypatch.chdir(directory)
    yield


def _run(argv: list[str]) -> int:
    """One CLI invocation, through the real parser and dispatch."""
    return S0maCLI().run(argv)


def _residue(
    channel: Any, view: TopicView, artifact: str
) -> dict[str, FactValue]:
    """The facts left in ``artifact`` once the declared presentation is off.

    B5 clause 3, the same reimplementation ``test_docs_resolve_render``
    uses. The artifact is passed in rather than rendered here so a proof
    can hand this an artifact it has edited — which is the whole
    difference between proving a renderer agrees with itself and proving
    it agrees with the record.
    """
    spec = channel.spec_for(view.group)
    return {
        name: canonical_fact(name, value)
        for name, value in channel.extract(artifact, spec).items()
    }


def staged_cli_wiring() -> tuple[
    Mapping[str, str], Mapping[str, tuple[tuple[str, ...], str]]
]:
    """The rows ``providers_cli`` needs for the three new subcommands.

    **This function is the wiring note.** F6 owns the commands and D1 owns
    the dispatch transcription; these are the exact entries, and
    :class:`TestStagedWiring` proves they are the right ones against the
    live parser rather than asserting they look plausible.
    """
    handlers = {
        "docs/list": "s0ma_dsl.cli.docs_commands.cmd_docs_list",
        "docs/search": "s0ma_dsl.cli.docs_commands.cmd_docs_search",
        "docs/show": "s0ma_dsl.cli.docs_commands.cmd_docs_show",
    }
    effects: dict[str, tuple[tuple[str, ...], str]] = {
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
    }
    return handlers, effects


@contextmanager
def _staged_wiring(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The D1 dispatch table with F6's rows in it, for one proof."""
    from s0ma_dsl.docs_model import providers_cli

    handlers, effects = staged_cli_wiring()
    monkeypatch.setattr(
        providers_cli, "_HANDLERS", {**providers_cli._HANDLERS, **handlers}
    )
    monkeypatch.setattr(
        providers_cli, "_SIDE_EFFECTS", {**providers_cli._SIDE_EFFECTS, **effects}
    )
    yield


# ---------------------------------------------------------------------------
# The bundle loader (the checkout-vs-installed seam)
# ---------------------------------------------------------------------------


class TestBundleLoader:
    """One snapshot, found in one of two places, and neither guessed at."""

    def test_the_checkout_answers_and_says_so(self, snapshot: Snapshot) -> None:
        assert snapshot.origin == CHECKOUT
        assert snapshot.location.endswith(snapshot_relative_path().split("/")[-1])
        assert snapshot.release_version()
        assert snapshot.snapshot_hash().startswith("sha256:")

    def test_the_snapshot_path_is_the_applications_own(self) -> None:
        """One path, composed from the constants that own its two halves."""
        from s0ma_dsl.docs_model.application import DOCS_ROOT, SNAPSHOT_OUTPUT

        assert snapshot_relative_path() == f"{DOCS_ROOT}/{SNAPSHOT_OUTPUT}"
        assert (REPO_ROOT / snapshot_relative_path()).is_file()

    def test_the_walk_finds_the_root_from_anywhere_inside_it(self) -> None:
        deep = REPO_ROOT / "packages" / "s0ma-dsl" / "src" / "s0ma_dsl" / "cli"
        assert checkout_root(deep) == REPO_ROOT
        assert checkout_root(REPO_ROOT) == REPO_ROOT

    def test_a_directory_outside_any_checkout_has_none(self, tmp_path: Path) -> None:
        assert checkout_root(tmp_path) is None
        assert checkout_snapshot(tmp_path) is None

    def test_the_checkout_still_wins_now_that_both_arms_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The order is the whole point, and both arms now have content.

        While the installed arm was empty this was untestable in the only
        way that mattered: "checkout first" cannot be proved against a
        second place that has nothing in it. The packaged copy gives it
        something to win against. A contributor is asking about *this
        tree*, and answering them out of a package directory — which in an
        editable install is a copy refreshed by a ``cp`` they may not have
        run yet — is the failure a version-stamped read surface exists to
        prevent.
        """
        assert packaged_loader() is not None, "the second arm has nothing to lose to"
        with _in(REPO_ROOT, monkeypatch):
            assert load_snapshot().origin == CHECKOUT

    def test_outside_a_checkout_the_packaged_snapshot_answers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing staged: the committed copy, through the real loader.

        The in-process form of what ``scripts/wheel_smoke.py`` proves on a
        cold install. Both are needed — this one fails in a second when a
        loader stops being registered, and the smoke is the only thing that
        can tell you the *wheel* carries the file.
        """
        assert checkout_root(tmp_path) is None
        with _in(tmp_path, monkeypatch):
            found = load_snapshot()
        assert found.origin == INSTALLED
        assert found.snapshot_hash() == load_snapshot(REPO_ROOT).snapshot_hash()

    def test_the_installed_arm_is_registered_and_answers(self) -> None:
        """The seam is a code path, and now it is a *filled* one.

        This assertion used to read ``packaged_loader() is None``, with the
        docstring "the seam is a code path, not a promise about one". The
        premise was true when it was written and stopped being true without
        anybody noticing: the packaging milestone shipped the snapshot into
        the ``s0ma-mcp`` wheel and the teaching slice into ``s0ma-core``,
        and left the place this loader looks empty — so every ``s0ma docs``
        command from an installed wheel answered "no documentation snapshot
        was found", and this test passed the whole time, because a loader
        that finds nothing is exactly what it asked for.

        The intent is kept and the premise is corrected: the arm is still
        proved to be a real code path, by requiring it to produce a real
        snapshot from the committed copy inside the package directory.
        """
        assert PACKAGED_LOADER in registered_names()

        found = packaged_loader()
        assert found is not None, (
            f"the s0ma_dsl package carries no {PACKAGED_SNAPSHOT}, so an "
            f"installed toolchain has no documentation to read. Refresh it: "
            f"cp docs/_generated/s0ma-docs-model.json "
            f"packages/s0ma-dsl/src/s0ma_dsl/{PACKAGED_SNAPSHOT}"
        )
        assert found.origin == INSTALLED
        assert found.snapshot_hash().startswith("sha256:")

    def test_a_staged_packaged_snapshot_is_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What F8 will do, done here, so the arm is proved rather than described.

        The last assertion is flipped from F6, knowingly. It used to read
        ``found.aliases.entries == ()`` — the honest record of a real gap:
        the alternate terms lived only in the authored concept files, so an
        installed origin had nowhere to read them and the ALIAS match class
        was dead on every served channel. F9 put the pairs in the snapshot,
        so a packaged copy now carries exactly what the checkout carries.
        """
        staged = tmp_path / "s0ma-docs-model.json"
        staged.write_text(
            (REPO_ROOT / snapshot_relative_path()).read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )
        monkeypatch.setattr(
            bundle_module, "packaged_snapshot_path", lambda: staged
        )
        found = packaged_loader()
        assert found is not None
        assert found.origin == INSTALLED
        assert found.aliases.entries
        assert found.aliases.entries == load_snapshot(REPO_ROOT).aliases.entries

    def test_a_registered_loader_answers_when_no_checkout_does(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        made = Snapshot(
            origin=INSTALLED,
            location="staged",
            bundle=load_snapshot(REPO_ROOT).bundle,
        )
        register_installed_loader("staged-for-a-test", lambda: made)
        try:
            assert installed_snapshot() is not None
            with _in(tmp_path, monkeypatch):
                assert load_snapshot().origin == INSTALLED
        finally:
            unregister_installed_loader("staged-for-a-test")
        assert "staged-for-a-test" not in registered_names()

    def test_loaders_are_tried_in_a_declared_order(self) -> None:
        """Sorted by name, so import order cannot decide which one answers."""
        register_installed_loader("zzz-last", lambda: None)
        register_installed_loader("aaa-first", lambda: None)
        try:
            names = registered_names()
            assert names == tuple(sorted(names))
            assert names[0] == "aaa-first"
        finally:
            unregister_installed_loader("zzz-last")
            unregister_installed_loader("aaa-first")

    def test_unregistering_a_name_nothing_registered_is_refused(self) -> None:
        with pytest.raises(DocsBundleUnavailableError, match="registered"):
            unregister_installed_loader("never-registered")

    def test_no_snapshot_anywhere_names_both_places(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """And says what the remaining case actually is.

        The message used to end "Neither had one", because at the time
        *nothing* filled the installed place and a reader could not act on
        the difference. Now that a release wheel carries the snapshot,
        reaching this message means one of two specific things, and the
        message has to name both of them or it sends an installed person
        looking for a checkout they never had.
        """
        monkeypatch.setattr(bundle_module, "installed_snapshot", lambda: None)
        with _in(tmp_path, monkeypatch), pytest.raises(
            DocsBundleUnavailableError
        ) as caught:
            load_snapshot()
        message = str(caught.value)
        assert snapshot_relative_path() in message
        assert f"s0ma_dsl/{PACKAGED_SNAPSHOT}" in message
        assert "development install being run outside its own checkout" in message
        assert "package files are incomplete" in message
        assert "docs compose" in message
        assert "reinstall from the release wheels" in message

    def test_a_checkout_supplies_the_alternate_terms(
        self, snapshot: Snapshot
    ) -> None:
        """Aliases are the seam's one asymmetry, and it is a real one."""
        assert snapshot.aliases.entries
        for old, new in snapshot.aliases.entries:
            assert old.startswith("concept:")
            assert new.startswith("concept:")


class TestPackagedMirrorDrift:
    """``s0ma_dsl/_docs_snapshot/s0ma-docs-model.json`` mirrors the build.

    The third copy of the composed snapshot, and the one the *command
    line* reads when there is no checkout. If this fails, the
    documentation application recomposed and the packaged copy is behind:
    refresh it with

        cp docs/_generated/s0ma-docs-model.json \\
           packages/s0ma-dsl/src/s0ma_dsl/_docs_snapshot/s0ma-docs-model.json

    and commit the two together — the same drift gate the ``s0ma-mcp``
    ``_docs`` snapshot and the ``s0ma-core`` teaching slice each have, in
    the same words, because it is the same loop
    (``docs/operations/docs-maintenance.md``, step 3).

    The copy exists because a wheel install has no checkout to read.
    Without it, ``s0ma docs``, ``docs list``, ``docs show`` and ``docs
    search`` answered an installed person "no documentation snapshot was
    found" while answering a contributor perfectly — which is how the gap
    survived four milestones: every gate ran in a checkout.
    """

    def test_the_packaged_file_is_there_and_parses(self) -> None:
        """Runs everywhere, including where the comparison below cannot.

        The companion that keeps the skip honest: outside a checkout there
        is no generated artifact to compare against, and a class whose only
        test skips reports nothing at all. This one asserts what can still
        be asserted — the file ships, it parses, and it has topics in it.
        """
        found = packaged_loader()
        assert found is not None, (
            f"no packaged snapshot in this installation, at "
            f"s0ma_dsl/{PACKAGED_SNAPSHOT}"
        )
        assert found.bundle.documents
        assert found.bundle.concepts
        assert found.snapshot_hash().startswith("sha256:")

    def test_the_mirror_matches_the_generated_artifact(self) -> None:
        artifact = REPO_ROOT / snapshot_relative_path()
        if not artifact.is_file():  # pragma: no cover - wheel-install context
            pytest.skip(
                "not a repository checkout: no generated snapshot to compare"
            )
        mirror = (
            REPO_ROOT
            / "packages"
            / "s0ma-dsl"
            / "src"
            / "s0ma_dsl"
            / PACKAGED_SNAPSHOT
        )
        assert mirror.read_bytes() == artifact.read_bytes(), (
            f"s0ma_dsl/{PACKAGED_SNAPSHOT} has drifted from "
            f"{snapshot_relative_path()} — refresh the mirror:\n"
            f"  cp {snapshot_relative_path()} "
            f"packages/s0ma-dsl/src/s0ma_dsl/{PACKAGED_SNAPSHOT}"
        )

    def test_the_mirror_is_what_the_loader_reads(self) -> None:
        """No fourth copy: the file compared above is the file served."""
        assert packaged_snapshot_path() == (
            PACKAGE_ROOT / "src" / "s0ma_dsl" / PACKAGED_SNAPSHOT
        ).resolve()


# ---------------------------------------------------------------------------
# The five parts
# ---------------------------------------------------------------------------


class TestCategories:
    """Every topic lands in exactly one part, and nothing lands by default."""

    def test_every_classified_channel_has_a_part(self) -> None:
        assert set(CATEGORY_OF_CHANNEL) == set(CHANNEL_EFFECTS)
        assert set(CATEGORY_OF_CHANNEL.values()) <= set(CATEGORY_KEYS)

    def test_the_five_keys_are_the_maps_five(self) -> None:
        from s0ma_dsl.docs_model.map_of_record import CATEGORIES

        assert tuple(section.key for section in CATEGORIES) == CATEGORY_KEYS

    def test_every_listed_topic_is_in_exactly_one_part(
        self, index: TopicIndex
    ) -> None:
        grouped = by_category(index)
        seen: list[str] = []
        for key in CATEGORY_KEYS:
            seen.extend(grouped[key])
        assert len(seen) == len(set(seen))
        listed = {
            identifier
            for identifier, view in index.views.items()
            if view.group in LISTED_GROUPS
        }
        assert set(seen) == listed

    def test_documents_are_addressable_and_not_listed(
        self, index: TopicIndex
    ) -> None:
        """The structural decision, asserted where somebody will read it."""
        documents = index.group("documents")
        assert documents, "the corpus has documents"
        assert "documents" not in LISTED_GROUPS
        for identifier in documents:
            assert category_of_topic(index.views[identifier]) is None
        # Still fully addressable: the map navigates them, the resolver
        # still answers for them.
        assert resolve(index, documents[0]).topic is not None

    def test_no_part_is_empty(self, index: TopicIndex) -> None:
        """A part with nothing in it is a heading that teaches nothing."""
        grouped = by_category(index)
        for key in CATEGORY_KEYS:
            assert grouped[key], key

    def test_an_unclassified_channel_is_refused_rather_than_defaulted(
        self, index: TopicIndex, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from s0ma_dsl.docs_model.resolve import DocsResolveError

        monkeypatch.setattr(
            docs_commands, "CATEGORY_OF_CHANNEL", {"cli": "toolchain"}
        )
        surface = index.view("config:source_roots")
        with pytest.raises(DocsResolveError, match="no part for that channel"):
            category_of_topic(surface)


# ---------------------------------------------------------------------------
# The navigation screen (T1)
# ---------------------------------------------------------------------------


def _b6_budget() -> dict[str, Any]:
    document = json.loads(B6_BUDGETS.read_text(encoding="utf-8"))
    for entry in document["budgets"]:
        if entry["artifact"] == "docs_navigation_stub":
            return dict(entry)
    raise AssertionError("B6 declared no navigation-stub budget")


class TestNavigation:
    """One screen, inside the budget B6 measured for it."""

    def test_the_budget_is_b6s_and_not_a_second_opinion(self) -> None:
        declared = _b6_budget()
        assert declared["budget_bytes"] == NAV_BYTE_BUDGET
        assert declared["max_lines"] == NAV_MAX_LINES
        assert declared["max_columns"] == NAV_MAX_COLUMNS

    def test_the_screen_fits_all_three_ceilings(self, snapshot: Snapshot) -> None:
        text = navigation(snapshot)
        payload = text[:-1] if text.endswith("\n") else text
        lines = payload.split("\n")
        assert len(payload.encode("utf-8")) <= NAV_BYTE_BUDGET
        assert len(lines) <= NAV_MAX_LINES
        assert max(len(line) for line in lines) <= NAV_MAX_COLUMNS

    def test_the_identity_line_is_first(self, snapshot: Snapshot) -> None:
        assert navigation(snapshot).split("\n")[0] == identity_line(snapshot)
        assert snapshot.release_version() in identity_line(snapshot)
        assert snapshot.snapshot_hash() in identity_line(snapshot)

    def test_no_absolute_path_reaches_the_screen(self, snapshot: Snapshot) -> None:
        """Rule 4: a machine path in an emitted frame is a frame that moved."""
        assert str(REPO_ROOT) not in navigation(snapshot)
        assert snapshot.location not in navigation(snapshot)

    def test_the_counts_are_the_listings_lengths(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        grouped = by_category(index)
        document = navigation_document(snapshot)
        for entry in document["categories"]:
            assert entry["topics"] == len(grouped[entry["key"]])

    def test_every_next_command_is_one_the_parser_serves(
        self, snapshot: Snapshot
    ) -> None:
        """A map that names a command nobody can run is a map that lies."""
        text = navigation(snapshot)
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped.startswith("s0ma docs "):
                continue
            argv = stripped.split()[1:]
            if argv[-1].startswith("<"):
                continue
            assert _run(argv) in {0, 5}, stripped

    def test_the_journey_block_never_outgrows_its_lines(
        self, snapshot: Snapshot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """More journeys than fit gets an overflow line, not a longer screen."""
        real = docs_commands._journey_order
        many = tuple(f"journey:made-up-{number}" for number in range(20))
        monkeypatch.setattr(
            docs_commands,
            "_journey_order",
            lambda index: (*real(index), *many)[:26],
        )
        lines = navigation(snapshot).split("\n")
        block = [line for line in lines if "s0ma docs show journey:" in line]
        assert len(block) == NAV_JOURNEY_LINES - 1
        assert any("... and" in line and "docs list build" in line for line in lines)
        assert len(navigation(snapshot).rstrip("\n").split("\n")) <= NAV_MAX_LINES

    def test_the_journeys_are_ordered_by_what_they_assume(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        ordered = navigation_document(snapshot)["journeys"]
        keys = [
            (len(index.view(identifier).items("concepts_required")), identifier)
            for identifier in ordered
        ]
        assert keys == sorted(keys)

    def test_the_document_map_is_named(self, snapshot: Snapshot) -> None:
        """Where the surface hands the document question over."""
        from s0ma_dsl.docs_model.application import DOCS_ROOT, MAP_OUTPUT

        target = f"{DOCS_ROOT}/{MAP_OUTPUT}"
        assert target in navigation(snapshot)
        assert (REPO_ROOT / target).is_file()


# ---------------------------------------------------------------------------
# The terminal channel and the residue (T2, T4)
# ---------------------------------------------------------------------------


class TestTerminalChannel:
    """``show`` says exactly what the record says, and declares the rest."""

    def test_the_spec_inherits_the_pages_facts(self, index: TopicIndex) -> None:
        for group in ("concepts", "surfaces", "journeys", "documents", "authorities"):
            page = render_human.spec_for(group)
            terminal = terminal_spec(group)
            assert terminal.channel == TERMINAL_CHANNEL
            assert terminal.order == page.order
            assert terminal.labels == page.labels
            assert terminal.width == 0
            assert set(page.envelope) <= set(terminal.envelope)

    def test_the_spec_refuses_to_drop_identity(self, index: TopicIndex) -> None:
        spec = terminal_spec("concepts")
        assert set(IDENTITY_FACTS) <= spec.carries()
        spec.check(_view(index, NERVE))

    @pytest.mark.parametrize("identifier", SAMPLE_TOPICS)
    def test_the_frame_carries_every_fact_verbatim(
        self, snapshot: Snapshot, index: TopicIndex, identifier: str
    ) -> None:
        """B5 rules (a) and (b) over the frame a person actually sees."""
        view = _view(index, identifier)
        frame = render_terminal(snapshot, view)
        residue = _residue(render_human, view, frame)
        truth = {
            name: canonical_fact(name, value) for name, value in view.facts.items()
        }
        for fact in IDENTITY_FACTS:
            assert fact in residue, fact
            assert residue[fact] == truth[fact], fact
        for fact, value in residue.items():
            assert value == truth[fact], fact

    @pytest.mark.parametrize("identifier", SAMPLE_TOPICS)
    def test_nothing_undeclared_reaches_the_reader(
        self, snapshot: Snapshot, index: TopicIndex, identifier: str
    ) -> None:
        """B5 clause 1, for a channel whose envelope is two lines."""
        view = _view(index, identifier)
        frame = render_terminal(snapshot, view)
        page = render_human.render_human(view)
        assert undeclared_lines(frame, page, envelope_of(snapshot, view)) == ()
        assert (
            render_human.undeclared_headings(
                frame, render_human.spec_for(view.group)
            )
            == ()
        )

    def test_an_edited_frame_is_caught(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        """Clause 2: the residue reads the artifact, not the renderer."""
        view = _view(index, NERVE)
        frame = render_terminal(snapshot, view)
        page = render_human.render_human(view)
        tampered = frame.replace(
            "## Why it exists", "## Why it exists\n\nSomebody added this."
        )
        assert "Somebody added this." in undeclared_lines(
            tampered, page, envelope_of(snapshot, view)
        )
        residue = _residue(render_human, view, tampered)
        assert residue["purpose"] != canonical_fact("purpose", view.text("purpose"))

    def test_the_frame_does_not_wrap(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        """The bytes cannot depend on a terminal's width if nothing wraps.

        The concept pages carry paragraphs far past any terminal width, so
        a renderer that wrapped would be visible here immediately.
        """
        frame = render_terminal(snapshot, _view(index, NERVE))
        assert max(len(line) for line in frame.split("\n")) > NAV_MAX_COLUMNS

    def test_the_frame_ends_with_exactly_one_newline(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        for identifier in SAMPLE_TOPICS:
            frame = render_terminal(snapshot, _view(index, identifier))
            assert frame.endswith("\n")
            assert not frame.endswith("\n\n")

    @pytest.mark.parametrize("identifier", SAMPLE_TOPICS)
    def test_the_terminal_and_the_json_agree(
        self, snapshot: Snapshot, index: TopicIndex, identifier: str
    ) -> None:
        """The cross-surface residue: one topic, two of this milestone's outputs."""
        view = _view(index, identifier)
        terminal = _residue(
            render_human, view, render_terminal(snapshot, view)
        )
        structured = _residue(render_json, view, render_json.render_json(view))
        shared = set(terminal) & set(structured)
        assert set(IDENTITY_FACTS) <= shared
        for fact in sorted(shared):
            assert terminal[fact] == structured[fact], fact


# ---------------------------------------------------------------------------
# Deep links (T3)
# ---------------------------------------------------------------------------


class TestDeepLinks:
    """Where a topic is written, derived every time and written down never."""

    def test_a_concept_points_at_its_learn_page(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        from s0ma_dsl.docs_model.learn_pages import page_path

        for identifier in index.group("concepts"):
            view = _view(index, identifier)
            pages = read_more(snapshot, view)
            assert pages == (f"docs/{page_path(identifier)}",)
            assert (REPO_ROOT / pages[0]).is_file(), identifier

    def test_a_command_setting_or_report_points_through_f3s_deep_link(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        from s0ma_dsl.docs_model.reference_pages import PAGE_BY_ID_CLASS, deep_link

        checked = 0
        for identifier in index.group("surfaces"):
            if identifier.partition(":")[0] not in PAGE_BY_ID_CLASS:
                continue
            view = _view(index, identifier)
            expected = deep_link(identifier, docs_root="docs")
            assert read_more(snapshot, view) == (expected,)
            page, _, anchor = expected.partition("#")
            body = (REPO_ROOT / page).read_text(encoding="utf-8")
            assert f"({anchor})" in body or anchor in body, identifier
            checked += 1
        assert checked > 100, "the three generated references carry most surfaces"

    def test_every_other_capability_points_at_the_index_that_lists_it(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        from s0ma_dsl.docs_model.application import SURFACES_INDEX_OUTPUT
        from s0ma_dsl.docs_model.reference_pages import PAGE_BY_ID_CLASS

        target = f"docs/{SURFACES_INDEX_OUTPUT}"
        body = (REPO_ROOT / target).read_text(encoding="utf-8")
        for identifier in index.group("surfaces"):
            if identifier.partition(":")[0] in PAGE_BY_ID_CLASS:
                continue
            assert read_more(snapshot, _view(index, identifier)) == (target,)
            assert identifier in body, identifier

    def test_a_journey_points_at_the_guide_the_catalog_says_covers_it(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        covered = 0
        for identifier in index.group("journeys"):
            pages = read_more(snapshot, _view(index, identifier))
            expected = sorted(
                {
                    document.canonical_source
                    for document in snapshot.bundle.documents
                    if identifier in document.covers
                }
            )
            assert list(pages) == expected, identifier
            for page in pages:
                assert (REPO_ROOT / page).is_file()
            covered += bool(pages)
        assert covered, "at least one journey is covered by a guide"

    def test_the_journey_pointer_moves_when_the_catalog_does(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        """Derived, and the proof is that editing the covers moves it."""
        from dataclasses import replace

        journeys = [
            identifier
            for identifier in index.group("journeys")
            if read_more(snapshot, _view(index, identifier))
        ]
        target = journeys[0]
        documents = tuple(
            replace(document, covers=())
            if target in document.covers
            else document
            for document in snapshot.bundle.documents
        )
        stripped = Snapshot(
            origin=snapshot.origin,
            location=snapshot.location,
            bundle=replace(snapshot.bundle, documents=documents),
            aliases=snapshot.aliases,
        )
        assert read_more(stripped, _view(index, target)) == ()

    def test_a_document_points_at_itself_and_an_authority_at_nothing(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        document = _view(index, "doc:guide/first-project")
        assert read_more(snapshot, document) == (
            document.text("canonical_source"),
        )
        authority = _view(index, "authority:spec/nerve-declaration")
        assert read_more(snapshot, authority) == ()
        # Not a silence: the page already carries where it is written.
        assert authority.text("written_in")


# ---------------------------------------------------------------------------
# The commands, end to end (T2)
# ---------------------------------------------------------------------------


class TestCommands:
    """Four commands, their outputs, and their exit codes."""

    def test_bare_docs_shows_navigation_and_exits_zero(
        self, capsys: pytest.CaptureFixture[str], snapshot: Snapshot
    ) -> None:
        """The exit-2 era ends here (arch §9.3 row 3)."""
        assert _run(["docs"]) == 0
        out = capsys.readouterr().out
        assert out == navigation(snapshot)

    def test_bare_docs_json_is_canonical(
        self, capsys: pytest.CaptureFixture[str], snapshot: Snapshot
    ) -> None:
        assert _run(["docs", "--format", "json"]) == 0
        document = json.loads(capsys.readouterr().out)
        assert document == json.loads(
            json.dumps(navigation_document(snapshot))
        )
        assert document["release_version"] == snapshot.release_version()
        assert document["snapshot_hash"] == snapshot.snapshot_hash()

    def test_list_of_one_part_opens_with_identity(
        self, capsys: pytest.CaptureFixture[str], snapshot: Snapshot
    ) -> None:
        assert _run(["docs", "list", "build"]) == 0
        out = capsys.readouterr().out
        assert out.split("\n")[0] == identity_line(snapshot)
        assert "journey:first-project" in out

    def test_list_of_everything_covers_every_part(
        self, capsys: pytest.CaptureFixture[str], index: TopicIndex
    ) -> None:
        assert _run(["docs", "list"]) == 0
        out = capsys.readouterr().out
        listed = {line.strip() for line in out.split("\n") if line.startswith("    ")}
        grouped = by_category(index)
        for key in CATEGORY_KEYS:
            for identifier in grouped[key]:
                assert identifier in listed, identifier

    def test_a_part_is_sub_headed_by_group_with_its_own_count(
        self, capsys: pytest.CaptureFixture[str], index: TopicIndex
    ) -> None:
        """A part read as one alphabet buries its teaching under its anchors."""
        assert _run(["docs", "list", "understand"]) == 0
        out = capsys.readouterr().out
        held: dict[str, int] = {}
        for identifier in by_category(index)["understand"]:
            group = index.views[identifier].group
            held[group] = held.get(group, 0) + 1
        for group, count in held.items():
            assert f"  {GROUP_TITLES[group]} — {count}\n" in out, group
        # And the teaching comes first, whatever the alphabet says.
        assert out.index(GROUP_TITLES["concepts"]) < out.index(
            GROUP_TITLES["authorities"]
        )

    def test_list_json_carries_every_entry_with_its_summary(
        self, capsys: pytest.CaptureFixture[str], index: TopicIndex
    ) -> None:
        assert _run(["docs", "list", "build", "--format", "json"]) == 0
        document = json.loads(capsys.readouterr().out)
        entries = document["categories"][0]["topics"]
        assert [entry["id"] for entry in entries] == list(
            by_category(index)["build"]
        )
        for entry in entries:
            assert entry["summary"] == index.view(entry["id"]).text("intent")

    def test_a_part_that_is_not_one_of_the_five_is_a_usage_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(["docs", "list", "kitchen"]) == 2
        err = capsys.readouterr().err
        for key in CATEGORY_KEYS:
            assert key in err

    def test_show_renders_the_terminal_frame(
        self, capsys: pytest.CaptureFixture[str], snapshot: Snapshot, index: TopicIndex
    ) -> None:
        assert _run(["docs", "show", NERVE]) == 0
        assert capsys.readouterr().out == render_terminal(
            snapshot, _view(index, NERVE)
        )

    def test_show_json_is_the_json_channels_own_rendering(
        self, capsys: pytest.CaptureFixture[str], index: TopicIndex
    ) -> None:
        """No extra keys: the residue over ``--format json`` is exact."""
        assert _run(["docs", "show", NERVE, "--format", "json"]) == 0
        out = capsys.readouterr().out
        assert out == render_json.render_json(_view(index, NERVE))
        assert render_json.undeclared_keys(
            out, render_json.spec_for("concepts")
        ) == ()

    def test_show_resolves_an_alias(
        self, capsys: pytest.CaptureFixture[str], snapshot: Snapshot
    ) -> None:
        old, new = snapshot.aliases.entries[0]
        assert _run(["docs", "show", old]) == 0
        assert f"Topic id: `{new}`" in capsys.readouterr().out

    def test_show_resolves_a_name(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(["docs", "show", "s0ma check"]) == 0
        assert "Topic id: `cli:s0ma/check`" in capsys.readouterr().out

    def test_an_ambiguous_question_lists_the_candidates_with_reasons(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(["docs", "show", "nerv"]) == 5
        out = capsys.readouterr().out
        assert "match 'nerv' equally well" in out
        assert "concept:nerve — what you asked for appears in its name" in out

    def test_an_ambiguous_question_in_json_names_its_state(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(["docs", "show", "nerv", "--format", "json"]) == 5
        document = json.loads(capsys.readouterr().out)
        assert document["state"] == "ambiguous"
        assert {entry["rank"] for entry in document["candidates"]} == {3}
        assert all(entry["reason"] for entry in document["candidates"])

    def test_a_miss_prints_the_nearest_forms(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(["docs", "show", "nervz"]) == 1
        err = capsys.readouterr().err
        assert "names no topic this build addresses" in err
        assert "concept:nerve" in err

    def test_a_miss_with_no_near_form_names_the_kinds(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(["docs", "show", "qqzz"]) == 1
        err = capsys.readouterr().err
        assert "Every topic is addressed by a kind and a colon" in err

    def test_search_ranks_and_says_why(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(["docs", "search", "drift"]) == 0
        out = capsys.readouterr().out
        assert "strongest match first" in out
        assert "concept:drift — its name is exactly what you asked for" in out

    def test_search_is_the_resolvers_own_ranking(
        self, capsys: pytest.CaptureFixture[str], index: TopicIndex
    ) -> None:
        """One ranking, not two: ``show`` and ``search`` ask the same question."""
        assert _run(["docs", "search", "drift", "--format", "json"]) == 0
        document = json.loads(capsys.readouterr().out)
        assert [entry["id"] for entry in document["matches"]] == [
            candidate.id for candidate in resolve(index, "drift").candidates
        ]

    def test_search_takes_a_phrase(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Several words are one question, joined by one space."""
        assert _run(["docs", "search", "s0ma", "docs", "render"]) == 0
        assert "cli:s0ma/docs/render" in capsys.readouterr().out

    def test_search_that_matches_nothing_reports_the_miss(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(["docs", "search", "qqzz"]) == 1
        assert "names no topic" in capsys.readouterr().err

    def test_every_read_command_states_the_version_and_snapshot(
        self, capsys: pytest.CaptureFixture[str], snapshot: Snapshot
    ) -> None:
        """Arch §9.2's closing rule, over all four."""
        line = identity_line(snapshot)
        for argv in (
            ["docs"],
            ["docs", "list", "build"],
            ["docs", "show", NERVE],
            ["docs", "search", "drift"],
        ):
            _run(argv)
            captured = capsys.readouterr()
            assert line in captured.out + captured.err, argv

    def test_a_missing_snapshot_is_reported_not_crashed(
        self,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(bundle_module, "installed_snapshot", lambda: None)
        with _in(tmp_path, monkeypatch):
            assert _run(["docs"]) == 1
        assert "no documentation snapshot was found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The authoring family, untouched (A8 parity)
# ---------------------------------------------------------------------------


class TestAuthoringFamilyUnchanged:
    """The five authoring subcommands still go exactly where they went."""

    def test_the_dispatch_is_unchanged_for_all_five(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import argparse

        called: list[str] = []
        for name in (
            "cmd_docs_render",
            "cmd_docs_verify",
            "cmd_docs_check_drift",
            "cmd_docs_compose",
            "cmd_docs_check",
        ):
            monkeypatch.setattr(
                docs_commands,
                name,
                lambda _args, _name=name: (called.append(_name), 0)[1],
            )
        cli = S0maCLI()
        for sub, expected in (
            ("render", "cmd_docs_render"),
            ("verify", "cmd_docs_verify"),
            ("check-drift", "cmd_docs_check_drift"),
            ("compose", "cmd_docs_compose"),
            ("check", "cmd_docs_check"),
        ):
            called.clear()
            args = argparse.Namespace(docs_command=sub)
            assert cli._cmd_docs(args) == 0
            assert called == [expected], sub

    def test_the_authoring_subcommands_keep_their_options(self) -> None:
        """Their interfaces are not disturbed by three new siblings."""
        parser = S0maCLI().build_parser()
        docs = _subparsers(parser)["docs"]
        subs = _subparsers(docs)
        assert set(subs) == {
            "render",
            "verify",
            "check-drift",
            "compose",
            "check",
            "list",
            "show",
            "search",
        }
        for name in ("render", "verify", "check-drift"):
            options = {
                option
                for action in subs[name]._actions
                for option in action.option_strings
            }
            assert {"--output-dir", "--mode", "--format"} <= options, name

    def test_the_read_subcommands_take_no_project_or_mode(self) -> None:
        parser = S0maCLI().build_parser()
        subs = _subparsers(_subparsers(parser)["docs"])
        for name in ("list", "show", "search"):
            options = {
                option
                for action in subs[name]._actions
                for option in action.option_strings
            }
            assert "--mode" not in options, name
            assert "--output-dir" not in options, name


def _subparsers(parser: Any) -> dict[str, Any]:
    import argparse

    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


# ---------------------------------------------------------------------------
# Discovery: `s0ma --help` advertises learning (arch §9.3 row 2)
# ---------------------------------------------------------------------------


class TestHelpAdvertisesLearning:
    """The help line beside ``docs`` is a discovery guarantee, so it is pinned."""

    def test_the_help_line_offers_learning_before_maintenance(self) -> None:
        line = _docs_help_line()
        assert "Learn how s0ma works" in line
        assert "s0ma docs" in line
        for word in ("list", "show", "search"):
            assert word in line
        # The authoring family is still advertised, after the read one.
        assert line.index("learning map") < line.index("render")

    def test_the_help_line_is_what_a_person_running_help_sees(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The pin is on the text `s0ma --help` really prints, not on a field."""
        with pytest.raises(SystemExit):
            S0maCLI().run(["--help"])
        printed = capsys.readouterr().out
        assert "Learn how s0ma works" in printed

    def test_the_help_line_fits_the_bounded_channel(self) -> None:
        """It is also ``cli:s0ma/docs``'s intent, and that has a budget."""
        from s0ma_dsl.docs_model.render_agent import AGENT_BYTE_BUDGET

        assert len(_docs_help_line().encode("utf-8")) < AGENT_BYTE_BUDGET

    def test_the_three_new_commands_advertise_themselves(self) -> None:
        parser = S0maCLI().build_parser()
        subs = _subparsers(_subparsers(parser)["docs"])
        helps = {
            name: _help_of(_subparsers(_subparsers(parser)["docs"]), name)
            for name in ("list", "show", "search")
        }
        assert subs
        assert "part of the documentation" in helps["list"]
        assert "one topic in full" in helps["show"]
        assert "strongest match first" in helps["search"]


def _docs_help_line() -> str:
    parser = S0maCLI().build_parser()
    for action in parser._actions:
        if getattr(action, "dest", None) == "command":
            for choice in action._get_subactions():
                if choice.dest == "docs":
                    return str(choice.help)
    raise AssertionError("the parser serves no `docs` command")


def _help_of(subs: Mapping[str, Any], name: str) -> str:
    parser = S0maCLI().build_parser()
    for action in parser._actions:
        if getattr(action, "dest", None) != "command":
            continue
        for choice in action.choices["docs"]._actions:
            if not hasattr(choice, "_get_subactions"):
                continue
            for entry in choice._get_subactions():
                if entry.dest == name:
                    return str(entry.help)
    raise AssertionError(f"the docs family serves no {name!r}")


# ---------------------------------------------------------------------------
# Determinism and offline (T4)
# ---------------------------------------------------------------------------


_PROBE = """\
import io, sys
sys.path.insert(0, sys.argv[1])
import importlib.util
spec = importlib.util.spec_from_file_location('gate', sys.argv[2])
gate = importlib.util.module_from_spec(spec)
sys.modules['gate'] = gate
spec.loader.exec_module(gate)
gate.arm_offline_guard()
from s0ma_dsl.cli.main import S0maCLI
codes = []
for argv in (
    ['docs'],
    ['docs', 'list', 'build'],
    ['docs', 'show', 'concept:nerve'],
    ['docs', 'search', 'drift'],
):
    codes.append(S0maCLI().run(argv))
print('CODES', codes, file=sys.stderr)
"""


def _package_src() -> str:
    return str(PACKAGE_ROOT / "src")


class TestOfflineAndDeterministic:
    """No network, no clock, no hash seed, no machine path."""

    def test_all_four_run_with_the_offline_guard_armed(
        self, tmp_path: Path
    ) -> None:
        script = tmp_path / "offline_probe.py"
        script.write_text(_PROBE, encoding="utf-8", newline="\n")
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, str(script), _package_src(), str(GATE)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(REPO_ROOT),
            check=False,
        )
        assert done.returncode == 0, done.stderr
        assert "CODES [0, 0, 0, 0]" in done.stderr
        assert "NetworkAttempted" not in done.stderr

    def test_the_offline_guard_used_here_really_refuses(
        self, tmp_path: Path
    ) -> None:
        """A guard that permits everything would make the proof above empty."""
        script = tmp_path / "guard_probe.py"
        script.write_text(
            "import sys, importlib.util, socket\n"
            "spec = importlib.util.spec_from_file_location('gate', sys.argv[1])\n"
            "gate = importlib.util.module_from_spec(spec)\n"
            "sys.modules['gate'] = gate\n"
            "spec.loader.exec_module(gate)\n"
            "gate.arm_offline_guard()\n"
            "try:\n"
            "    socket.create_connection(('kn0wthyself.ai', 443), timeout=1)\n"
            "except Exception as exc:\n"
            "    print(type(exc).__name__)\n",
            encoding="utf-8",
            newline="\n",
        )
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, str(script), str(GATE)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert done.stdout.strip() == "NetworkAttempted", done.stderr

    def test_two_runs_in_one_process_are_byte_equal(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        first = navigation(snapshot)
        assert navigation(load_snapshot(REPO_ROOT)) == first
        view = _view(index, NERVE)
        frame = render_terminal(snapshot, view)
        assert render_terminal(load_snapshot(REPO_ROOT), view) == frame

    def test_three_hash_seeds_in_three_processes_agree(
        self, tmp_path: Path
    ) -> None:
        script = tmp_path / "render_once.py"
        script.write_text(
            "import hashlib, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from pathlib import Path\n"
            "from s0ma_dsl.cli.docs_commands import (\n"
            "    navigation, render_terminal, topic_index,\n"
            ")\n"
            "from s0ma_dsl.docs_model.bundle import load_snapshot\n"
            "snapshot = load_snapshot(Path(sys.argv[2]))\n"
            "index = topic_index(snapshot)\n"
            "digest = hashlib.sha256()\n"
            "digest.update(navigation(snapshot).encode('utf-8'))\n"
            "for identifier in index.ids():\n"
            "    digest.update(identifier.encode('utf-8'))\n"
            "    digest.update(\n"
            "        render_terminal(snapshot, index.view(identifier)).encode('utf-8')\n"
            "    )\n"
            "print(digest.hexdigest())\n",
            encoding="utf-8",
            newline="\n",
        )
        digests = set()
        for seed in ("0", "1", "4242"):
            done = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [sys.executable, str(script), _package_src(), str(REPO_ROOT)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(tmp_path),
                # Inherit the real environment (as the sibling determinism
                # tests do) and vary only the hash seed. A hand-built minimal
                # env dropped SystemRoot, which Winsock needs to initialize —
                # importing asyncio then dies with WinError 10106 on Windows,
                # a failure that has nothing to do with what this test checks.
                env={**os.environ, "PYTHONHASHSEED": seed},
                check=False,
            )
            assert done.returncode == 0, done.stderr
            digests.add(done.stdout.strip())
        assert len(digests) == 1, "the bytes moved between hash seeds"

    def test_every_topic_renders_and_none_leaks_a_machine_path(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        """Total over the whole build, not over the eight sampled above."""
        root = str(REPO_ROOT)
        for identifier in index.ids():
            frame = render_terminal(snapshot, index.view(identifier))
            assert frame.strip(), identifier
            assert identifier in frame, identifier
            assert root not in frame, identifier

    def test_the_read_surface_writes_nothing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """SDA-INV-9's read half: a read command that wrote would be a build.

        Run from the checkout, so all four actually answer, and checked
        against the committed generated tree rather than only against an
        empty temporary directory — the files a documentation command
        could plausibly overwrite are the ones a build writes.
        """
        generated = REPO_ROOT / "docs" / "_generated"

        def fingerprint() -> dict[str, str]:
            return {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(generated.iterdir())
                if path.is_file()
            }

        before = fingerprint()
        assert before, "the checkout has committed generated artifacts"
        empty = tmp_path / "empty"
        empty.mkdir()
        with _in(REPO_ROOT, monkeypatch):
            for argv in (
                ["docs"],
                ["docs", "list"],
                ["docs", "show", NERVE],
                ["docs", "search", "drift"],
            ):
                assert _run(argv) == 0, argv
                capsys.readouterr()
        assert fingerprint() == before
        assert list(empty.iterdir()) == []


# ---------------------------------------------------------------------------
# The staged wiring (the note the gate applies)
# ---------------------------------------------------------------------------


def _rows_applied() -> bool:
    """Has the gate written F6's rows into D1's dispatch table yet?"""
    from s0ma_dsl.docs_model import providers_cli

    handlers, _effects = staged_cli_wiring()
    return bool(set(handlers) & set(providers_cli._HANDLERS))


class TestStagedWiring:
    """Three commands are three surfaces, and D1's table has to say so.

    **These proofs are written to survive their own resolution.** Until
    the gate applies the note, they prove the provider refuses by name and
    that the staged rows are what fixes it. Once it has, the same proofs
    check that what was applied is what was asked for, character for
    character. Neither state needs an edit here, which is what stops a
    staging test from becoming the thing that goes red when the wiring
    finally lands.
    """

    def test_the_live_parser_serves_exactly_the_three_staged_paths(self) -> None:
        handlers, effects = staged_cli_wiring()
        assert set(handlers) == set(effects)
        subs = _subparsers(_subparsers(S0maCLI().build_parser())["docs"])
        for path in handlers:
            assert path.split("/", 1)[1] in subs, path

    def test_every_staged_handler_resolves_to_a_real_callable(self) -> None:
        handlers, _effects = staged_cli_wiring()
        for path, dotted in handlers.items():
            module_name, _, attribute = dotted.rpartition(".")
            spec = importlib.util.find_spec(module_name)
            assert spec is not None, dotted
            module = sys.modules.get(module_name) or importlib.import_module(
                module_name
            )
            assert callable(getattr(module, attribute)), path

    def test_the_provider_composes_with_the_rows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole content of the wiring note, proved rather than asserted."""
        from s0ma_dsl.docs_model.providers_cli import CliProvider

        with _staged_wiring(monkeypatch):
            provider = CliProvider()
            ids = {record.record.id for record in provider.provide().records}
        for path in staged_cli_wiring()[0]:
            assert f"cli:s0ma/{path}" in ids, path

    def test_the_provider_refuses_by_name_until_the_rows_are_applied(
        self,
    ) -> None:
        """The failure the gate sees, or the applied rows that ended it."""
        from s0ma_dsl.docs_model import providers_cli
        from s0ma_dsl.docs_model.providers_cli import CliProvider, CliProviderError

        handlers, effects = staged_cli_wiring()
        if _rows_applied():
            # Applied. What was applied has to be what was asked for: a
            # note half-taken is a binding pointing at the wrong callable.
            for path, dotted in handlers.items():
                assert providers_cli._HANDLERS[path] == dotted, path
            for path, classified in effects.items():
                assert providers_cli._SIDE_EFFECTS[path] == classified, path
            CliProvider()
            return
        with pytest.raises(CliProviderError) as caught:
            CliProvider()
        message = str(caught.value)
        for path in handlers:
            assert path in message, path

    def test_the_staged_reasons_are_long_enough_to_have_been_written(
        self,
    ) -> None:
        _handlers, effects = staged_cli_wiring()
        for path, (kinds, reason) in effects.items():
            assert kinds == ("read",), path
            assert len(reason) > 60, path
            assert "writes nothing" in reason, path

    def test_the_docs_group_command_still_only_reads(self) -> None:
        """Bare ``s0ma docs`` changed what it prints, not what it touches.

        D1 classified the group command as a read because it resolved the
        project and printed usage. It still only reads — a snapshot, now,
        instead of nothing — so the classification is unchanged and the
        note does not have to ask for an edit to it.
        """
        from s0ma_dsl.docs_model.providers_cli import _SIDE_EFFECTS

        kinds, _reason = _SIDE_EFFECTS["docs"]
        assert kinds == ("read",)


def test_this_suite_names_the_milestone_it_belongs_to() -> None:
    """A cheap guard that the module docstring survives an edit."""
    assert "F6" in (sys.modules[__name__].__doc__ or "")
    assert hashlib.sha256  # the import is used by the seed proof above


def test_the_group_tables_cover_exactly_the_listed_groups() -> None:
    """A group with no title would list under nothing and be lost."""
    assert set(GROUP_ORDER) == set(LISTED_GROUPS)
    assert set(GROUP_TITLES) == set(LISTED_GROUPS)
