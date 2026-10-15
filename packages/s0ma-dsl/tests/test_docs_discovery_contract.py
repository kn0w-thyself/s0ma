"""The human discovery contract, as executable tests (F9).

Milestone F9 of the docs-function plan (internal) §11, closing Phase F.
Architecture §9.3 lists seven guaranteed ways a *person* finds out that
this product documents itself, and SDA-INV-17 says discovery is
contextual rather than optional browsing. Until this file existed, those
seven were prose. Here each one is a proof, and :data:`HUMAN_ENTRY_POINTS`
is checked against the classes below, so an entry point cannot be quietly
dropped by deleting its test.

**What "closing" means, and what it does not.** The B7 re-measured
baseline was three sentences long: ``s0ma --help`` named the docs family
as build maintenance, bare ``s0ma docs`` was a 160-byte usage error, and
neither the served MCP instructions nor ``project_status`` contained the
word "docs". Six of the seven routes were real when F9 landed and are
proved here against the running product. The seventh — the root README's
"start here" route — did not exist, and rather than test something
adjacent and call it done, :class:`TestRootReadmeRoute` pinned its
absence so the day it arrived would fail loudly. Milestone G4 repointed
the README's Documentation section at the map of record, and that pin is
flipped below: all seven routes are now asserted as present.

**Budgets are read, never restated.** Every ceiling asserted here comes
out of B6's ``fixtures/budgets.json``. A suite that agreed with a number
nobody declared would be agreeing with itself.

**The agent half lives elsewhere.** ``s0ma-mcp``'s
``tests/test_docs_discovery_mcp.py`` holds architecture §9.6's seven and
the four-channel parity sweep, because those need a running server and
this package may not depend on one (SDA-INV-5). The two halves meet at
one place — the composed snapshot — and each proves its own side of it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.cli import new_project as new_project_module
from s0ma_dsl.cli.docs_commands import (
    NAV_BYTE_BUDGET,
    NAV_MAX_COLUMNS,
    NAV_MAX_LINES,
    envelope_of,
    navigation,
    render_terminal,
    topic_index,
)
from s0ma_dsl.cli.doctor import LEARN_HINT as DOCTOR_LEARN_HINT
from s0ma_dsl.cli.doctor import LEARN_JOURNEY as DOCTOR_LEARN_JOURNEY
from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.cli.new_project import LEARN_HINT, LEARN_JOURNEY
from s0ma_dsl.docs_model import bundle as bundle_module
from s0ma_dsl.docs_model import render_human
from s0ma_dsl.docs_model.application import DOCS_ROOT, MAP_OUTPUT
from s0ma_dsl.docs_model.bundle import (
    INSTALLED,
    Snapshot,
    checkout_root,
    load_snapshot,
    packaged_loader,
    snapshot_relative_path,
)
from s0ma_dsl.docs_model.learn_pages import page_path
from s0ma_dsl.docs_model.reference_pages import PAGE_BY_ID_CLASS, deep_link
from s0ma_dsl.docs_model.resolve import resolve
from tests.test_docs_resolve_render import DOC_CHANNEL_DIVERGENCE, divergences

if TYPE_CHECKING:
    from s0ma_dsl.docs_model.resolve import TopicIndex

REPO_ROOT = Path(__file__).resolve().parents[3]
ROOT_README = REPO_ROOT / "README.md"
MAP_OF_RECORD = f"{DOCS_ROOT}/{MAP_OUTPUT}"

B6_BUDGETS = (
    REPO_ROOT
    / "scripts"
    / "spikes"
    / "docs_model"
    / "spike_b6_discovery"
    / "fixtures"
    / "budgets.json"
)

#: The name a discovery failure is reported under. Milestone-local, the
#: same way ``test_docs_resolve_render`` holds
#: :data:`DOC_CHANNEL_DIVERGENCE`: neither code has a home in
#: ``docs_model.validate`` because neither gate reads a *record* — they
#: read the running product's own output, which no build-time validator
#: has in front of it. The precedent is deliberate and F9's owns-list
#: names it.
DOC_DISCOVERY_BROKEN = "DOC_DISCOVERY_BROKEN"

#: Architecture §9.3's seven, in its order, each mapped to the class that
#: proves it. The mapping is asserted at the bottom of this file, so a
#: deleted class fails loudly rather than silently reducing the contract.
HUMAN_ENTRY_POINTS: dict[str, str] = {
    "1-root-readme-start-here": "TestRootReadmeRoute",
    "2-help-advertises-learning": "TestHelpAdvertisesLearning",
    "3-bare-docs-navigates": "TestBareDocsNavigates",
    "4-setup-results-name-a-next-step": "TestSetupResultsNameANextStep",
    "5-diagnostics-point-at-their-topic": "TestDiagnosticsPointAtTheirTopic",
    "6-generated-instructions-name-both-routes": "TestGeneratedInstructions",
    "7-installed-bundles-need-no-checkout": "TestInstalledBundlesNeedNoCheckout",
}

#: Three topics for the parity sweep, one per shape of record the human
#: page collection actually holds a file for: a concept with a written
#: syntax form, a concept with none, and a journey. Chosen for what they
#: are, not for being convenient.
PARITY_TOPICS: tuple[str, ...] = (
    "concept:nerve",
    "concept:self-knowledge",
    "journey:first-project",
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def snapshot() -> Snapshot:
    return load_snapshot(REPO_ROOT)


@pytest.fixture(scope="module")
def index(snapshot: Snapshot) -> TopicIndex:
    return topic_index(snapshot)


def _budget(artifact: str) -> dict[str, Any]:
    """One artifact's declared budget, from B6's own fixture."""
    document = json.loads(B6_BUDGETS.read_text(encoding="utf-8"))
    for entry in document["budgets"]:
        if entry["artifact"] == artifact:
            return dict(entry)
    raise AssertionError(f"B6 declared no budget for {artifact!r}")


def _run(argv: list[str]) -> int:
    return S0maCLI().run(argv)


def _resolves(index: TopicIndex, identifier: str) -> None:
    """``identifier`` is a question this build can actually answer.

    The whole of ``DOC_DISCOVERY_BROKEN``: a route that names a topic no
    build addresses is worse than a route that names nothing, because a
    person following it spends their attention before finding out.
    """
    outcome = resolve(index, identifier)
    assert outcome.topic is not None, (
        f"{DOC_DISCOVERY_BROKEN}: a discovery route names {identifier!r}, "
        f"which this build does not address"
    )


# ---------------------------------------------------------------------------
# Entry point 1 — the root README's "start here" route
# ---------------------------------------------------------------------------


class TestRootReadmeRoute:
    """§9.3.1: "The root README has one 'Start here' route to docs/README.md."

    **This entry point was the pinned deferral, and G4 T2 closed it.** F9
    found the root README's Documentation section listing per-package
    READMEs, the PRD and the changelog, and never naming the map of
    record; the repoint belonged to milestone **G4 T2** by name, which
    owned the file. So F9 pinned the absence instead of reaching into it,
    and this class now asserts the route in the positive form the pin's
    failure message asked for.

    Three things are proved together, because a route is only worth
    following if all three hold: the map exists and is composed by the
    application rather than kept by hand, the README sends a reader to it
    from one place, and the CLI sends them to the same page (entry point 3
    no longer carries this one's weight alone).
    """

    def test_the_map_of_record_exists_and_is_the_one_the_route_names(
        self,
    ) -> None:
        page = REPO_ROOT / MAP_OF_RECORD
        assert page.is_file(), MAP_OF_RECORD
        # Composed by the application, not hand-kept: a route to a page
        # somebody maintains by hand would rot at a different rate than
        # the corpus it describes.
        assert MAP_OUTPUT in _generated_relatives()

    def test_the_root_readme_routes_to_it(self) -> None:
        """Entry point 1, in the positive form the pin asked for.

        The section is the route and nothing else. A Documentation section
        that also enumerates documents is a second index, which is the
        shape G4 removed: two lists of the same corpus rot apart, and the
        hand-kept one always wins the race.
        """
        text = ROOT_README.read_text(encoding="utf-8")

        assert "## Documentation" in text, (
            f"{DOC_DISCOVERY_BROKEN}: the root README has no Documentation "
            f"section, so entry point 1 has nowhere to live"
        )
        section = text.split("## Documentation", 1)[1].split("\n## ", 1)[0]
        assert MAP_OF_RECORD in section, (
            f"{DOC_DISCOVERY_BROKEN}: the root README's Documentation section "
            f"no longer routes to {MAP_OF_RECORD} (G4 T2 put it there)"
        )
        assert "Start here" in section, (
            f"{DOC_DISCOVERY_BROKEN}: the route is present but unlabelled — "
            f"architecture §9.3.1 asks for a 'Start here' route, not a mention"
        )
        assert text.count(MAP_OF_RECORD) == 1, (
            f"{DOC_DISCOVERY_BROKEN}: the root README names {MAP_OF_RECORD} "
            f"{text.count(MAP_OF_RECORD)} times. §9.3.1 asks for ONE route; a "
            f"reader who meets the index twice has to decide which one is it"
        )

    def test_the_cli_route_names_the_same_page(self, snapshot: Snapshot) -> None:
        """Both routes land on one page, asserted rather than assumed."""
        screen = navigation(snapshot)

        assert MAP_OF_RECORD in screen
        assert (REPO_ROOT / MAP_OF_RECORD).is_file()


def _generated_relatives() -> tuple[str, ...]:
    """Every artifact path the application declares it always writes."""
    from s0ma_dsl.docs_model.application import STATIC_OUTPUTS

    return tuple(STATIC_OUTPUTS)


# ---------------------------------------------------------------------------
# Entry point 2 — `s0ma --help`
# ---------------------------------------------------------------------------


class TestHelpAdvertisesLearning:
    """§9.3.2: help advertises learning, not only subsystem maintenance.

    F6 proved the wording and its budget. What is added here is the
    contract half: everything the line offers is a command the parser
    really serves, and it is reachable from the top-level help a person
    with no prior knowledge runs first.
    """

    def test_the_help_line_offers_learning(self) -> None:
        line = _subcommand_help(S0maCLI().build_parser(), "docs")

        assert "Learn how s0ma works" in line
        # The learning half comes first: a person skimming twenty command
        # descriptions reads the opening clause of each.
        assert line.index("Learn") < line.index("renders")

    def test_every_command_the_line_offers_is_served(self) -> None:
        line = _subcommand_help(S0maCLI().build_parser(), "docs")
        offered = set(re.findall(r"\b(list|show|search|compose|check)\b", line))
        served = _docs_subcommands()

        assert offered, f"{DOC_DISCOVERY_BROKEN}: the help line offers nothing"
        for word in sorted(offered):
            assert word in served, (
                f"{DOC_DISCOVERY_BROKEN}: `s0ma --help` offers `s0ma docs "
                f"{word}` and the parser does not serve it"
            )

    def test_it_reaches_a_person_who_runs_help_and_nothing_else(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exited:
            _run(["--help"])
        printed = capsys.readouterr().out

        assert exited.value.code == 0
        assert "Learn how s0ma works" in " ".join(printed.split())


def _subparsers(parser: Any) -> dict[str, Any]:
    """One parser's subcommands, by name. F6's idiom, unchanged.

    Anchored on ``argparse._SubParsersAction`` rather than on "an action
    with choices", because ``--format`` has choices too and a helper that
    could not tell them apart would answer ``{"json", "text"}`` to the
    question "what does ``docs`` serve".
    """
    import argparse

    for action in parser._actions:  # noqa: SLF001 — the parser is the truth
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return dict(action.choices)
    return {}


def _subcommand_help(parser: Any, name: str) -> str:
    """One subcommand's help text, as argparse holds it."""
    import argparse

    for action in parser._actions:  # noqa: SLF001
        if not isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            continue
        for entry in action._choices_actions:  # noqa: SLF001
            if entry.dest == name:
                return " ".join(str(entry.help or "").split())
    raise AssertionError(f"the parser serves no {name!r} command")


def _docs_subcommands() -> frozenset[str]:
    """Every subcommand the live parser serves under ``docs``."""
    served = _subparsers(_subparsers(S0maCLI().build_parser())["docs"])

    assert served, "the docs command serves no subcommands"
    return frozenset(served)


# ---------------------------------------------------------------------------
# Entry point 3 — bare `s0ma docs`
# ---------------------------------------------------------------------------


class TestBareDocsNavigates:
    """§9.3.3: bare ``s0ma docs`` shows navigation, not a usage error.

    The B7 baseline measured this at exit 2 and 160 bytes. Both halves of
    that are asserted against here — the exit code and the size — because
    a screen that navigates and exits 2 would still break every script
    that reads the code, and a "screen" of 160 bytes would navigate
    nowhere.
    """

    def test_it_exits_zero_and_prints_a_screen(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run(["docs"])
        printed = capsys.readouterr().out

        assert code == 0, "bare `s0ma docs` is no longer a usage error (B7)"
        assert len(printed.encode("utf-8")) > 160
        assert "usage:" not in printed

    def test_every_command_it_offers_is_one_the_parser_serves(
        self, snapshot: Snapshot
    ) -> None:
        served = _docs_subcommands()
        offered = {
            match.group(1)
            for match in re.finditer(r"^\s*s0ma docs (\w+)", navigation(snapshot), re.M)
        }

        assert offered
        for word in sorted(offered):
            assert word in served, (
                f"{DOC_DISCOVERY_BROKEN}: the navigation screen offers "
                f"`s0ma docs {word}` and the parser does not serve it"
            )

    def test_every_topic_it_names_is_one_this_build_answers(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        named = re.findall(r"s0ma docs show ([a-z0-9_]+:\S+)", navigation(snapshot))

        assert named, "the navigation screen names no topic at all"
        for identifier in named:
            _resolves(index, identifier)


# ---------------------------------------------------------------------------
# Entry point 4 — `new project` and `doctor`
# ---------------------------------------------------------------------------


class TestSetupResultsNameANextStep:
    """§9.3.4: setup results name the next relevant journey.

    Wired at F9. Both surfaces already printed next steps and both named
    only agent-side routes — ``s0ma://guide/getting-started`` and the MCP
    registration hint — which a person without an MCP client cannot
    follow. One line each, at the place each surface already prints next
    steps, and the id it names is resolved here against the composed
    snapshot rather than trusted.
    """

    def test_new_project_names_a_journey_this_build_answers(
        self, index: TopicIndex
    ) -> None:
        _resolves(index, LEARN_JOURNEY)
        assert LEARN_JOURNEY in LEARN_HINT

    def test_new_project_prints_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run(["new", "project", str(tmp_path / "app")])
        printed = capsys.readouterr().out

        assert code == 0
        assert LEARN_HINT in printed
        # Beside the agent route rather than instead of it: §9.3.4 and
        # §9.6.3 are two readerships, not two versions of one.
        assert new_project_module.GETTING_STARTED_URI in printed

    def test_new_project_says_it_on_the_structured_channel_too(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run(
            ["new", "project", str(tmp_path / "app"), "--format", "json"]
        )
        report = json.loads(capsys.readouterr().out)

        assert code == 0
        assert report["next_steps"]["learn"] == LEARN_HINT

    def test_doctor_names_a_journey_this_build_answers(
        self, index: TopicIndex
    ) -> None:
        _resolves(index, DOCTOR_LEARN_JOURNEY)
        assert DOCTOR_LEARN_JOURNEY in DOCTOR_LEARN_HINT
        assert "s0ma docs" in DOCTOR_LEARN_HINT

    def test_doctor_prints_it_on_both_channels(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(["--project-root", str(tmp_path), "doctor"]) == 0
        assert f"learn         {DOCTOR_LEARN_HINT}" in capsys.readouterr().out

        assert (
            _run(["--project-root", str(tmp_path), "doctor", "--format", "json"])
            == 0
        )
        assert json.loads(capsys.readouterr().out)["learn"] == DOCTOR_LEARN_HINT

    def test_the_two_surfaces_name_the_same_journey(self) -> None:
        """One next step, not two opinions about where a person goes."""
        assert LEARN_JOURNEY == DOCTOR_LEARN_JOURNEY


# ---------------------------------------------------------------------------
# Entry point 5 — diagnostics
# ---------------------------------------------------------------------------


class TestDiagnosticsPointAtTheirTopic:
    """§9.3.5: a diagnostic points at an exact topic id and command.

    The chain a person actually walks, end to end: a real ``s0ma check``
    reports a code, the code is an id this build addresses, ``s0ma docs
    show`` answers it, and the deep link the answer carries lands on a
    committed page at an anchor that is really in the file.
    """

    def _broken(self, tmp_path: Path) -> Path:
        source = tmp_path / "broken.s0ma"
        source.write_text("module broken\n    layer: DOMAIN\n", encoding="utf-8")
        return source

    def test_a_failing_check_reports_a_code_this_build_addresses(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], index: TopicIndex
    ) -> None:
        code = _run(["check", "--format", "json", str(self._broken(tmp_path))])
        report = json.loads(capsys.readouterr().out)

        assert code != 0
        reported = {finding["code"] for finding in report["errors"]}
        assert reported, "a failing check reported no diagnostic code"
        for name in sorted(reported):
            _resolves(index, f"diagnostic:{name}")

    def test_the_reported_code_is_answerable_from_the_terminal(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(["check", "--format", "json", str(self._broken(tmp_path))])
        report = json.loads(capsys.readouterr().out)
        first = sorted(finding["code"] for finding in report["errors"])[0]

        assert _run(["docs", "show", f"diagnostic:{first}"]) == 0
        answer = capsys.readouterr().out
        assert first in answer

    def test_every_diagnostic_deep_links_into_a_committed_page(
        self, index: TopicIndex
    ) -> None:
        """The convention, over all 109 rather than over a chosen one."""
        codes = index.group("surfaces")
        diagnostics = [item for item in codes if item.startswith("diagnostic:")]

        assert diagnostics, "this build addresses no diagnostics at all"
        pages: dict[str, frozenset[str]] = {}
        for identifier in diagnostics:
            link = deep_link(identifier, docs_root=DOCS_ROOT)
            page, _, anchor = link.partition("#")
            assert anchor, identifier
            anchors = pages.setdefault(
                page, _anchors_of((REPO_ROOT / page).read_text(encoding="utf-8"))
            )
            assert anchor in anchors, (
                f"{DOC_DISCOVERY_BROKEN}: {identifier} deep-links to "
                f"{link} and {page} carries no heading that slugs to it"
            )

    def test_the_page_the_convention_names_is_the_committed_one(self) -> None:
        for id_class, relative in sorted(PAGE_BY_ID_CLASS.items()):
            assert (REPO_ROOT / DOCS_ROOT / relative).is_file(), id_class


def _anchors_of(markdown: str) -> frozenset[str]:
    """Every heading anchor a Markdown body offers, github-slugger style.

    Lowercase, drop what is neither alphanumeric nor underscore nor
    hyphen nor space, then spaces to hyphens. The underscore is kept on
    purpose and it is the whole reason this helper is written out: every
    diagnostic anchor *is* an underscored code, and a slugger that
    dropped underscores would answer "no such anchor" to every one of the
    109 links this file checks.
    """
    found = set()
    for line in markdown.splitlines():
        if not line.startswith("#"):
            continue
        heading = line.lstrip("#").strip().strip("`")
        slug = re.sub(r"[^a-z0-9_\s-]", "", heading.lower())
        found.add(re.sub(r"\s+", "-", slug).strip("-"))
    return frozenset(found)


# ---------------------------------------------------------------------------
# Entry point 6 — generated project instructions
# ---------------------------------------------------------------------------


class TestGeneratedInstructions:
    """§9.3.6 and §9.6.6: the generated AGENTS.md names *both* routes.

    F7 added the agent route. The human one was missing, which mattered
    exactly where the file is read by a person rather than by a client
    with an MCP server attached — and it is one file read by both. F9
    added the terminal half to the same bullet, inside B6's
    ``agents_snippet`` budget, which is asserted here from the fixture.
    """

    @pytest.fixture(scope="class")
    def agents_md(self, tmp_path_factory: pytest.TempPathFactory) -> str:
        target = tmp_path_factory.mktemp("generated") / "app"
        assert S0maCLI().run(["new", "project", str(target), "--quiet"]) == 0
        return (target / "AGENTS.md").read_text(encoding="utf-8")

    def _docs_bullet(self, agents_md: str) -> str:
        bullets = re.findall(r"(?ms)^- .*?(?=\n(?:- |\n|#)|\Z)", agents_md)
        found = [item for item in bullets if "Ask s0ma about s0ma" in item]
        assert len(found) == 1, "the docs bullet is not exactly one bullet"
        return found[0]

    def test_it_names_the_agent_route(self, agents_md: str) -> None:
        bullet = self._docs_bullet(agents_md)

        assert "learn_s0ma(topic=...)" in bullet
        assert "s0ma://docs/index" in bullet

    def test_it_names_the_human_route(self, agents_md: str) -> None:
        bullet = self._docs_bullet(agents_md)

        assert "s0ma docs show" in bullet
        assert "s0ma docs" in bullet

    def test_the_human_route_is_a_command_the_parser_serves(
        self, agents_md: str
    ) -> None:
        offered = set(
            re.findall(r"`s0ma docs (\w+)[^`]*`", self._docs_bullet(agents_md))
        )
        served = _docs_subcommands()

        assert offered
        for word in sorted(offered):
            assert word in served, (
                f"{DOC_DISCOVERY_BROKEN}: the generated AGENTS.md offers "
                f"`s0ma docs {word}` and the parser does not serve it"
            )

    def test_the_bullet_stays_inside_b6s_budget(self, agents_md: str) -> None:
        """B6's rule: not the longest bullet in the file it joins."""
        declared = _budget("agents_snippet")
        bullets = re.findall(r"(?ms)^- .*?(?=\n(?:- |\n|#)|\Z)", agents_md)
        longest = max(len(item.encode("utf-8")) for item in bullets)
        size = len(self._docs_bullet(agents_md).encode("utf-8"))

        assert declared["budget_bytes"] == longest, (
            "B6 derived this budget from the longest bullet in the generated "
            "file; the file has moved, so re-derive the budget rather than "
            "quietly permitting a longer bullet"
        )
        assert size <= declared["budget_bytes"], (
            f"the documentation bullet is {size} bytes against a "
            f"{declared['budget_bytes']}-byte budget ({declared['rule']})"
        )


# ---------------------------------------------------------------------------
# Entry point 7 — installed bundles
# ---------------------------------------------------------------------------


class TestInstalledBundlesNeedNoCheckout:
    """§9.3.7: installed bundles answer with no checkout and no network.

    F8 shipped the core teaching slice and proved a pip-installed core
    answers cold; that proof is ``packages/s0ma-core/tests/
    test_teaching_slice.py`` and is cited rather than re-run here. What
    this class adds is the *seam*: a packaged snapshot answers when no
    checkout is reachable, and it answers with the same alternate terms a
    checkout does — which was not true before F9, and is the one gap that
    milestone was authorized to close.

    **Every proof below but the first stages its snapshot**, and for four
    years of milestones that was the only kind available: nothing filled
    the place the loader looks, so the contract could be stated only about
    a file a test had put there. It cost the product the whole command
    line — ``s0ma docs`` answered "no documentation snapshot was found" on
    every installed toolchain while this class was green. The first test
    is the unstaged one: the committed copy inside the package directory,
    through the real loader, with the working directory outside any
    checkout. Staging is still right for the rest, which ask what happens
    to snapshots this tree does not carry (one with ``aliases`` deleted,
    one standing alone with no concept sources beside it).
    """

    def test_the_committed_packaged_copy_answers_unstaged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Snapshot
    ) -> None:
        """Nothing staged, nothing patched: what an installed person gets."""
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        assert checkout_root(outside) is None

        monkeypatch.chdir(outside)
        found = load_snapshot()
        assert found.origin == INSTALLED
        assert found.snapshot_hash() == snapshot.snapshot_hash()
        assert found.aliases.entries == snapshot.aliases.entries

    def test_a_packaged_snapshot_answers_with_no_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Snapshot
    ) -> None:
        staged = tmp_path / "s0ma-docs-model.json"
        staged.write_text(
            (REPO_ROOT / snapshot_relative_path()).read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )
        monkeypatch.setattr(bundle_module, "packaged_snapshot_path", lambda: staged)

        outside = tmp_path / "elsewhere"
        outside.mkdir()
        assert checkout_root(outside) is None

        found = packaged_loader()
        assert found is not None
        assert found.origin == INSTALLED
        assert found.release_version() == snapshot.release_version()
        assert found.snapshot_hash() == snapshot.snapshot_hash()

    def test_the_alternate_terms_travel_with_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Snapshot
    ) -> None:
        """The F7 flag, closed: the ALIAS match class was dead when served.

        Before F9 the pairs lived only in the authored concept files, so
        an installed origin had nowhere to read them: every earlier name
        missed on a wheel and on the MCP server's packaged copy while
        resolving fine in a checkout. They are in the snapshot now, so
        both origins answer the same questions.
        """
        staged = tmp_path / "s0ma-docs-model.json"
        staged.write_text(
            (REPO_ROOT / snapshot_relative_path()).read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )
        monkeypatch.setattr(bundle_module, "packaged_snapshot_path", lambda: staged)
        found = packaged_loader()
        assert found is not None

        assert found.aliases.entries == snapshot.aliases.entries
        assert found.aliases.entries, "this build declares no alternate terms"

        old, current = found.aliases.entries[0]
        installed = topic_index(found)
        outcome = resolve(installed, old)
        assert outcome.topic is not None, old
        assert outcome.topic.id == current

    def test_the_core_slice_proof_is_where_f8_left_it(self) -> None:
        """Cited, not re-run: this package does not import core's suite."""
        proof = REPO_ROOT / "packages" / "s0ma-core" / "tests" / "test_teaching_slice.py"
        mirror = (
            REPO_ROOT / "packages" / "s0ma-core" / "src" / "s0ma" / "_teaching" / "slice.json"
        )

        assert proof.is_file()
        assert mirror.is_file()

    def test_reading_a_snapshot_takes_no_concept_sources(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Snapshot
    ) -> None:
        """A wheel has the snapshot and nothing else it used to need.

        The checkout loader used to re-read ``docs/s0ma_src/concepts/``
        for the alias table. If anything still did, a snapshot copied
        somewhere with no such directory beside it would come back with
        fewer ways of asking — so the staged copy is put where no concept
        source exists and asked for all of them.
        """
        staged = tmp_path / "alone" / "s0ma-docs-model.json"
        staged.parent.mkdir()
        staged.write_text(
            (REPO_ROOT / snapshot_relative_path()).read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )
        monkeypatch.setattr(bundle_module, "packaged_snapshot_path", lambda: staged)

        found = packaged_loader()
        assert found is not None
        assert len(found.aliases.entries) == len(snapshot.aliases.entries)

    def test_a_snapshot_written_before_f9_is_still_readable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The additive rule, proved on a document with the field removed.

        ``@1`` is additive-only, which is a promise about *old documents*
        and is therefore worth nothing unless a reader keeps it. The
        committed snapshot with its ``aliases`` key deleted is exactly an
        older snapshot: it must still read, and it must read as carrying
        no alternate terms rather than as an error or as a guess.
        """
        from s0ma_dsl.docs_model.serialize import deserialize_bundle, serialize_bundle

        document = json.loads(
            (REPO_ROOT / snapshot_relative_path()).read_text(encoding="utf-8")
        )
        del document["aliases"]
        older = tmp_path / "s0ma-docs-model.json"
        older.write_text(json.dumps(document), encoding="utf-8", newline="\n")
        monkeypatch.setattr(bundle_module, "packaged_snapshot_path", lambda: older)

        found = packaged_loader()
        assert found is not None
        assert found.bundle.aliases == ()
        assert found.aliases.entries == ()
        # Every id still answers; only the earlier names are gone.
        assert topic_index(found).ids()
        # And writing it back puts the key in, so an old document is
        # normalized rather than left half-shaped.
        assert '"aliases"' in serialize_bundle(deserialize_bundle(older.read_text()))


# ---------------------------------------------------------------------------
# T3 — budgets, read from B6 rather than restated
# ---------------------------------------------------------------------------


class TestBudgets:
    """Every first-pointed human artifact, against its declared ceiling."""

    def test_the_navigation_screen_fits_all_three_ceilings(
        self, snapshot: Snapshot
    ) -> None:
        declared = _budget("docs_navigation_stub")
        screen = navigation(snapshot)
        lines = screen.splitlines()

        assert len(screen.encode("utf-8")) <= declared["budget_bytes"]
        assert len(lines) <= declared["max_lines"]
        assert max(len(line) for line in lines) <= declared["max_columns"]

    def test_the_products_own_constants_are_b6s_numbers(self) -> None:
        """One budget, not a copy of one. Three constants, one fixture."""
        declared = _budget("docs_navigation_stub")

        assert declared["budget_bytes"] == NAV_BYTE_BUDGET
        assert declared["max_lines"] == NAV_MAX_LINES
        assert declared["max_columns"] == NAV_MAX_COLUMNS

    def test_the_two_human_budgets_are_the_two_b6_declared(self) -> None:
        """The human channels B6 measured, and no invented third one."""
        document = json.loads(B6_BUDGETS.read_text(encoding="utf-8"))
        declared = {entry["artifact"] for entry in document["budgets"]}

        assert {"docs_navigation_stub", "agents_snippet"} <= declared


# ---------------------------------------------------------------------------
# T4 — channel parity, the human half
# ---------------------------------------------------------------------------


class TestChannelParityHumanHalf:
    """The committed page and the terminal say the same things (§9.7).

    The four-channel sweep needs a running MCP server for its other two
    channels and lives in ``s0ma-mcp``'s F9 suite. What is provable here
    without one is the pair that share a renderer but not a frame: the
    page a reader opens in the repository, and the frame ``s0ma docs
    show`` puts around the same rendering.
    """

    def test_the_terminal_frame_is_the_page_plus_declared_envelope(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        for identifier in PARITY_TOPICS:
            view = index.view(identifier)
            frame = render_terminal(snapshot, view)
            page = render_human.render_human(view)
            envelope = envelope_of(snapshot, view)

            assert page in frame, identifier
            leftover = [
                line
                for line in frame.splitlines()
                if line not in page.splitlines() and line not in envelope
            ]
            assert leftover == [], (
                f"{DOC_CHANNEL_DIVERGENCE}: the terminal frame for "
                f"{identifier} carries {leftover}, which is neither the page "
                f"nor declared envelope"
            )

    def test_the_committed_page_carries_the_builds_identity(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        """A file a person opens says which build wrote it (§9.7)."""
        for identifier in PARITY_TOPICS:
            if not identifier.startswith("concept:"):
                continue
            page = REPO_ROOT / DOCS_ROOT / page_path(identifier)
            body = page.read_text(encoding="utf-8")

            assert snapshot.release_version() in body, identifier
            assert snapshot.snapshot_hash() in body, identifier
            assert identifier in body, identifier

    def test_the_residue_agrees_across_the_three_renderers(
        self, index: TopicIndex
    ) -> None:
        """B5's comparison, over the real composition rather than a golden.

        ``divergences`` is the utility ``test_docs_resolve_render``
        declared for F9 to adopt, and adopting it here rather than writing
        a second one is what keeps one definition of "the channels agree".
        """
        from s0ma_dsl.docs_model import render_agent, render_json

        for identifier in PARITY_TOPICS:
            view = index.view(identifier)
            found = divergences(
                view,
                {
                    "json": render_json.render_json(view),
                    "human": render_human.render_human(view),
                    "agent": render_agent.render_agent(view),
                },
            )
            assert found == [], f"{identifier}: {found}"


# ---------------------------------------------------------------------------
# The contract is complete
# ---------------------------------------------------------------------------


def test_every_entry_point_of_the_contract_has_a_proof() -> None:
    """Seven routes, seven classes, and the mapping is checked.

    Deleting a class or renaming one without updating
    :data:`HUMAN_ENTRY_POINTS` fails here, which is the only thing that
    stops a contract shrinking quietly.
    """
    here = globals()
    missing = [
        f"{route} -> {name}"
        for route, name in HUMAN_ENTRY_POINTS.items()
        if name not in here
    ]

    assert missing == [], f"entry points with no proof: {missing}"
    assert len(HUMAN_ENTRY_POINTS) == 7, "architecture §9.3 lists seven"


def test_this_suite_names_the_milestone_it_belongs_to() -> None:
    text = Path(__file__).read_text(encoding="utf-8")

    assert "Milestone F9" in text
    assert "architecture §9.3" in text or "§9.3" in text
