"""The three generated references — commands, settings, and reports.

Milestone F3 of the docs-function plan (internal) §11. D6's two indexes list
what s0ma serves; these three pages say what each of those things takes,
what it does and what changes when you use it, and every one of them is
rendered from the composed snapshot rather than written.

So the assertions here are about **completeness, agreement and
determinism** rather than about prose:

* every command the parser serves, every key the project loader reads and
  every code the registries register has exactly one entry on its page,
  and the counts the pages state are the counts they carry;
* every entry's anchor resolves under the rules ``scripts/check_links.py``
  really applies, so the deep links F6 and F7 are given actually land —
  and two entries that would slug to one anchor are refused rather than
  silently disambiguated;
* the pages agree, fact for fact, with the two registered derived sources
  that cover the same ground (``cli_commands`` and ``error_codes``), so
  the corpus cannot end up with two accounts of one command or one code;
* three spot-checks per page go past the composed record to the live
  source of truth — ``config.py``'s matrix, ``project.py``'s constants,
  the parser's own choices — because a page that agrees with a record
  that agrees with nothing is a page nobody should trust;
* the bytes are stable across two renders and across three hash seeds in
  fresh processes.

**The wiring is proved rather than described.**
:class:`TestTheWiringNote` loads the catalog rows this milestone hands the
orchestrator through the real
:class:`~s0ma_dsl.docs_model.providers_catalog.CatalogProvider`, against a
fixture checkout, so a row that would be refused at the wave gate is
refused here first — where the milestone that wrote it can fix it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.docs_model.application import DOCS_ROOT, build
from s0ma_dsl.docs_model.providers_catalog import (
    CATALOG_FILE,
    CATALOG_SCHEMA,
    CatalogProvider,
)
from s0ma_dsl.docs_model.providers_cli import CliProvider
from s0ma_dsl.docs_model.providers_concepts import FORBIDDEN_IN_AUTHORED_PROSE
from s0ma_dsl.docs_model.providers_config import ConfigProvider
from s0ma_dsl.docs_model.providers_diagnostics import (
    NOT_APPLICABLE,
    DiagnosticsProvider,
    summary_line,
)
from s0ma_dsl.docs_model.records import (
    SCHEMA,
    BuildStamp,
    DocsBundle,
    Provenance,
    SurfaceRecord,
)
from s0ma_dsl.docs_model.reference_pages import (
    ABSENT,
    CLI_REFERENCE_OUTPUT,
    CONFIGURATION_REFERENCE_OUTPUT,
    DIAGNOSTICS_REFERENCE_OUTPUT,
    PAGE_BY_ID_CLASS,
    REFERENCE_OUTPUTS,
    DocsReferenceError,
    anchor,
    anchor_of,
    cli_reference,
    configuration_reference,
    deep_link,
    diagnostics_reference,
    heading_of,
)

if TYPE_CHECKING:
    from types import ModuleType

    from s0ma_dsl.docs_model.application import Build

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"

#: A version the composition is stamped with, so two builds of one tree
#: stay comparable across a release bump.
RELEASE = "0.0.0-f3"

#: The catalog rows this milestone hands the orchestrator, exactly as the
#: wiring note gives them. Written here rather than described, so the
#: shape check below is over the thing that will really be pasted in.
CATALOG_ROWS: tuple[dict[str, Any], ...] = (
    {
        "audiences": ["agent", "user"],
        "authority": "",
        "canonical_source": f"{DOCS_ROOT}/{CLI_REFERENCE_OUTPUT}",
        "covers": [],
        "governed_by": [],
        "id": "doc:generated/cli-reference",
        "kind": "reference",
        "prose_locator": f"{DOCS_ROOT}/{CLI_REFERENCE_OUTPUT}",
        "status": "generated",
        "title": "The s0ma command line",
    },
    {
        "audiences": ["agent", "user"],
        "authority": "",
        "canonical_source": f"{DOCS_ROOT}/{CONFIGURATION_REFERENCE_OUTPUT}",
        "covers": [],
        "governed_by": [],
        "id": "doc:generated/configuration-reference",
        "kind": "reference",
        "prose_locator": f"{DOCS_ROOT}/{CONFIGURATION_REFERENCE_OUTPUT}",
        "status": "generated",
        "title": "Project settings",
    },
    {
        "audiences": ["agent", "user"],
        "authority": "",
        "canonical_source": f"{DOCS_ROOT}/{DIAGNOSTICS_REFERENCE_OUTPUT}",
        "covers": [],
        "governed_by": [],
        "id": "doc:generated/diagnostics-reference",
        "kind": "reference",
        "prose_locator": f"{DOCS_ROOT}/{DIAGNOSTICS_REFERENCE_OUTPUT}",
        "status": "generated",
        "title": "Reports s0ma can make",
    },
)

#: One row of an overview table, whose first cell is a link to the entry's
#: own section: ``| [`name`](#anchor) | ...``.
_OVERVIEW_ROW = re.compile(r"^\| \[`(?P<name>[^`]+)`\]\(#(?P<anchor>[^)]+)\) \|")

#: An ATX heading, read the way ``scripts/check_links.py`` reads one.
_HEADING = re.compile(r"^ {0,3}(?P<hashes>#{1,6})\s+(?P<title>.*?)\s*#*\s*$")


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


@cache
def _script(name: str) -> ModuleType:
    """Import a ``scripts/`` guard so the pins below run its real rules.

    Registered in ``sys.modules`` before execution for the reason F2's
    suite gives: ``@dataclass`` resolves a class's module through it.
    """
    spec = importlib.util.spec_from_file_location(f"s0ma_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# One composition, three pages, read once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def composed() -> Build:
    """One composition of this checkout, stamped so a bump cannot move it."""
    return build(REPO_ROOT, version=RELEASE)


@pytest.fixture(scope="module")
def cli() -> CliProvider:
    """The live command-line reading — the parser this shell would meet."""
    return CliProvider()


@pytest.fixture(scope="module")
def settings() -> ConfigProvider:
    """The live ``[tool.s0ma]`` reading of this checkout."""
    return ConfigProvider(root=REPO_ROOT)


@pytest.fixture(scope="module")
def reports() -> DiagnosticsProvider:
    """The live diagnostic-registry reading of this checkout."""
    return DiagnosticsProvider(root=REPO_ROOT)


def _render(
    built: Build, provider: CliProvider, registries: DiagnosticsProvider
) -> dict[str, str]:
    """The three pages, rendered exactly as the wiring note wires them."""
    return {
        CLI_REFERENCE_OUTPUT: cli_reference(
            built.bundle, interfaces=provider.interface()
        ),
        CONFIGURATION_REFERENCE_OUTPUT: configuration_reference(built.bundle),
        DIAGNOSTICS_REFERENCE_OUTPUT: diagnostics_reference(
            built.bundle, modes=registries.modes()
        ),
    }


@pytest.fixture(scope="module")
def pages(
    composed: Build, cli: CliProvider, reports: DiagnosticsProvider
) -> dict[str, str]:
    """The three pages this milestone delivers, from the live composition."""
    return _render(composed, cli, reports)


def _headings(page: str) -> list[str]:
    """Every ATX heading's text, in document order."""
    return [
        match.group("title")
        for line in page.splitlines()
        if (match := _HEADING.match(line))
    ]


def _entries(page: str) -> list[str]:
    """Every entry name in an overview table, in the order it is listed."""
    return [
        match.group("name")
        for line in page.splitlines()
        if (match := _OVERVIEW_ROW.match(line))
    ]


def _section(page: str, heading: str) -> str:
    """One entry's section: from its heading to the next one of any depth."""
    lines = page.splitlines()
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if match is None or match.group("title") != heading:
            continue
        for end in range(index + 1, len(lines)):
            if _HEADING.match(lines[end]):
                return "\n".join(lines[index:end])
        return "\n".join(lines[index:])
    raise AssertionError(f"no heading {heading!r} on this page")


# ---------------------------------------------------------------------------
# T1/T3 — completeness: every command, every key, every code, exactly once
# ---------------------------------------------------------------------------


@requires_checkout
class TestEveryThingServedHasOneEntry:
    """Derived both ways: the page is the reading, and nothing else."""

    def test_every_command_has_exactly_one_entry(
        self, pages: dict[str, str], cli: CliProvider
    ) -> None:
        """Equality, not containment.

        A subset test passes a page that lost half the command line and a
        superset test passes one that invented a command, so the two sets
        are compared as sets — and then counted, because a set comparison
        forgives a command listed twice.
        """
        page = pages[CLI_REFERENCE_OUTPUT]
        served = [item.public_name for item in cli.interface()]
        assert set(_entries(page)) == set(served)
        assert len(_entries(page)) == len(served)
        headings = _headings(page)
        for name in served:
            assert headings.count(name) == 1, name

    def test_every_configuration_key_has_exactly_one_entry(
        self, pages: dict[str, str], settings: ConfigProvider
    ) -> None:
        page = pages[CONFIGURATION_REFERENCE_OUTPUT]
        keys = list(settings.keys())
        assert set(_entries(page)) == set(keys)
        assert len(_entries(page)) == len(keys)
        headings = _headings(page)
        for key in keys:
            assert headings.count(key) == 1, key

    def test_every_diagnostic_code_has_exactly_one_entry(
        self, pages: dict[str, str], reports: DiagnosticsProvider
    ) -> None:
        page = pages[DIAGNOSTICS_REFERENCE_OUTPUT]
        codes = list(reports.codes())
        assert set(_entries(page)) == set(codes)
        assert len(_entries(page)) == len(codes)
        headings = _headings(page)
        for code in codes:
            assert headings.count(code) == 1, code

    def test_every_option_and_argument_the_parser_holds_is_listed(
        self, pages: dict[str, str], cli: CliProvider
    ) -> None:
        """The facts ``s0ma-docs-model@1`` has no field for, all of them.

        D1 reads the whole interface and hands it over rather than folding
        it into a record; this page is the first thing that renders it, so
        the count is asserted against the reading rather than against a
        number written here.
        """
        page = pages[CLI_REFERENCE_OUTPUT]
        # A flag row's first cell is a spelling that starts with a hyphen;
        # a positional's is the name the value arrives under, which never
        # does. Both are the only rows on this page whose first cell is a
        # bare code span — the overview's opens with a link.
        flags = [line for line in page.splitlines() if line.startswith("| `-")]
        positionals = [
            line
            for line in page.splitlines()
            if line.startswith("| `") and not line.startswith("| `-")
        ]
        arguments = sum(len(item.arguments) for item in cli.interface())
        options = sum(len(item.options) for item in cli.interface())
        assert len(flags) == options
        assert len(positionals) == arguments
        assert f"{options} options" in page
        assert f"{arguments} arguments" in page

    def test_the_counts_in_the_prose_are_the_counts_on_the_page(
        self, pages: dict[str, str], cli: CliProvider, reports: DiagnosticsProvider
    ) -> None:
        """A generated page that miscounts itself teaches nobody to trust it."""
        commands = pages[CLI_REFERENCE_OUTPUT]
        assert f"serves {len(cli.interface())} commands" in commands

        keys = pages[CONFIGURATION_REFERENCE_OUTPUT]
        assert f"reads {len(_entries(keys))} keys" in keys

        codes = pages[DIAGNOSTICS_REFERENCE_OUTPUT]
        laddered = len(_entries(codes)) - len(
            [code for code in reports.codes() if _out_of_matrix(code, reports)]
        )
        assert f"registers {len(reports.codes())} of them" in codes
        assert f"{laddered} get more serious" in codes

    def test_every_entry_carries_the_id_the_model_addresses_it_by(
        self, pages: dict[str, str], composed: Build
    ) -> None:
        """A page entry without its id is a deep link with no target."""
        for channel, relative in PAGE_BY_ID_CLASS.items():
            page = pages[relative]
            for record in composed.bundle.surfaces:
                if record.channel != channel:
                    continue
                assert f"`{record.id}`" in page, record.id


def _out_of_matrix(code: str, reports: DiagnosticsProvider) -> bool:
    """True when ``code`` never passes through the strictness ladder."""
    from s0ma_dsl.docs_model.providers_diagnostics import read_out_of_matrix

    return code in read_out_of_matrix(reports._source()[0])  # noqa: SLF001


# ---------------------------------------------------------------------------
# T1/T3 — the anchor convention F6 and F7 are handed
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheAnchorConvention:
    """A deep link is only as good as the heading it lands on."""

    def test_every_anchor_resolves_under_the_real_slugger(
        self, pages: dict[str, str], composed: Build
    ) -> None:
        """``anchor_of`` is checked against github-slugger's real rules.

        The module's own :func:`anchor` is a narrow case of those rules.
        This is what proves the case is wide enough: every heading these
        pages render is slugged by ``scripts/check_links.py`` and has to
        come out equal.
        """
        for channel, relative in PAGE_BY_ID_CLASS.items():
            anchors = _script("check_links").document_anchors(pages[relative])
            for record in composed.bundle.surfaces:
                if record.channel != channel:
                    continue
                assert anchor_of(record.id) in anchors, record.id

    def test_no_heading_takes_a_disambiguation_suffix(
        self, pages: dict[str, str]
    ) -> None:
        """github-slugger's ``-1`` is how a deep link lands on the wrong entry."""
        for relative in REFERENCE_OUTPUTS:
            page = pages[relative]
            slugger = _script("check_links")
            slugged = [
                slugger.slugify(title) for title in _headings(page) if slugger.slugify(title)
            ]
            assert len(slugged) == len(set(slugged)), relative

    def test_every_link_on_every_page_resolves(self, pages: dict[str, str]) -> None:
        """The unit form of the A5 gate, so a failure names the page.

        Both kinds: a same-document ``#anchor`` has to name a heading on
        that page, and a repository-relative link has to name a file this
        repository really tracks.
        """
        checker = _script("check_links")
        tracked = checker.tracked_files(REPO_ROOT)
        for relative in REFERENCE_OUTPUTS:
            page = pages[relative]
            here = f"{DOCS_ROOT}/{relative}"
            anchors = checker.document_anchors(page)
            for target in re.findall(r"\]\((?P<target>[^)\s]+)\)", page):
                path, _, fragment = target.partition("#")
                if not path:
                    assert fragment in anchors, (here, target)
                    continue
                resolved = checker._resolve(here, path)  # noqa: SLF001
                assert resolved in tracked, (here, target)

    def test_the_convention_is_the_one_the_read_surfaces_are_given(self) -> None:
        """The three worked examples the module docstring records for F6/F7."""
        assert deep_link("cli:s0ma/docs/render", docs_root=DOCS_ROOT) == (
            "docs/reference/cli.md#s0ma-docs-render"
        )
        assert deep_link("config:build_dir", docs_root=DOCS_ROOT) == (
            "docs/reference/configuration.md#build_dir"
        )
        assert deep_link("diagnostic:BARE_IMPORT", docs_root=DOCS_ROOT) == (
            "docs/reference/diagnostics.md#bare_import"
        )

    def test_the_heading_of_a_command_is_the_way_a_person_types_it(
        self, composed: Build
    ) -> None:
        """The heading is derived from the id and equals the served name.

        Both facts matter. Deriving from the id is what keeps a heading and
        its anchor from drifting; equalling ``public_name`` is what keeps
        the derivation honest, because a heading nobody could type would
        be a heading nobody searches for.
        """
        for record in composed.bundle.surfaces:
            if record.channel == "cli":
                assert heading_of(record.id) == record.public_name, record.id
            if record.channel == "config":
                assert record.public_name.endswith(f".{heading_of(record.id)}")
            if record.channel == "diagnostic":
                assert heading_of(record.id) == record.public_name, record.id

    def test_an_id_no_reference_page_carries_is_refused(self) -> None:
        for identifier in ("concept:nerve", "mcp:tool/build_project", "nonsense"):
            with pytest.raises(DocsReferenceError, match="generated reference"):
                heading_of(identifier)

    def test_the_slugger_keeps_the_underscore_the_map_drops(self) -> None:
        """Why this module has an ``anchor`` of its own at all.

        The map of record's narrow case drops every character but letters,
        digits, spaces and hyphens, which is right for its authored section
        titles and wrong for a code written with underscores.
        """
        from s0ma_dsl.docs_model.map_of_record import anchor as map_anchor

        assert anchor("BARE_IMPORT") == "bare_import"
        assert map_anchor("BARE_IMPORT") == "bareimport"
        assert anchor("BARE_IMPORT") == _script("check_links").slugify("BARE_IMPORT")


# ---------------------------------------------------------------------------
# T3 — three spot-checks per page, against the live source of truth
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheCommandPageAgreesWithTheParser:
    """Three facts checked past the record, at the parser itself."""

    def test_the_mode_flag_offers_the_modes_the_product_declares(
        self, pages: dict[str, str]
    ) -> None:
        from s0ma_dsl.config import StrictnessMode

        section = _section(pages[CLI_REFERENCE_OUTPUT], "s0ma build")
        written = ", ".join(f"`{mode.value}`" for mode in StrictnessMode)
        assert f"| `--mode` | a value | {ABSENT} | {written} |" in section

    def test_a_commands_lead_line_is_the_help_the_author_wrote(
        self, pages: dict[str, str], cli: CliProvider
    ) -> None:
        """Quoted, not reworded: the page's line is the parser's line."""
        served = cli.interface_of("cli:s0ma/docs/render")
        section = _section(pages[CLI_REFERENCE_OUTPUT], "s0ma docs render")
        assert f"\n\n{served.intent}\n" in section
        assert served.intent

    def test_an_unregistered_handler_says_it_reaches_nothing(
        self, pages: dict[str, str]
    ) -> None:
        """D5b's enumerated seven, over the page that shows them.

        The page must not read as though every command were bound: the
        exact list of commands that reach no registered component is a
        product decision somebody has to take, and it is only reviewable
        if the reference says so.
        """
        from s0ma_dsl.docs_model.application import UNREGISTERED_HANDLERS

        page = pages[CLI_REFERENCE_OUTPUT]
        for identifier in UNREGISTERED_HANDLERS:
            section = _section(page, heading_of(identifier))
            assert "**Implemented by** — nothing the model can address" in section
        assert page.count("**Implemented by** — nothing the model can address") == len(
            UNREGISTERED_HANDLERS
        )


@requires_checkout
class TestTheSettingsPageAgreesWithTheLoader:
    """Three facts checked past the record, at ``project.py``'s constants."""

    def test_the_source_roots_default_is_the_loaders_own_constant(
        self, pages: dict[str, str]
    ) -> None:
        from s0ma_dsl.project import DEFAULT_SOURCE_ROOTS

        section = _section(pages[CONFIGURATION_REFERENCE_OUTPUT], "source_roots")
        assert f"- **Default** — `{list(DEFAULT_SOURCE_ROOTS)!r}`" in section

    def test_the_mode_key_accepts_the_modes_the_loader_validates_against(
        self, pages: dict[str, str]
    ) -> None:
        from s0ma_dsl.project import SUPPORTED_PROJECT_MODES

        section = _section(pages[CONFIGURATION_REFERENCE_OUTPUT], "mode")
        written = ", ".join(f"`{value}`" for value in sorted(SUPPORTED_PROJECT_MODES))
        assert f"- **Accepted values** — {written}" in section

    def test_the_computed_default_says_so_and_carries_its_rule(
        self, pages: dict[str, str]
    ) -> None:
        """``build_dir`` is the key §1.2 fact 5 names: no written default.

        Its default is worked out from the project's name, and the rule
        that governs the result is named on the page and still written in
        the loader.
        """
        section = _section(pages[CONFIGURATION_REFERENCE_OUTPUT], "build_dir")
        assert "- **Default** — worked out from the project" in section
        assert "- **Checked by** — `INVALID_PROJECT_NAME_FOR_BUILD_DIR`" in section
        loader = (REPO_ROOT / "packages/s0ma-dsl/src/s0ma_dsl/project.py").read_text(
            encoding="utf-8"
        )
        assert "INVALID_PROJECT_NAME_FOR_BUILD_DIR" in loader


@requires_checkout
class TestTheReportsPageAgreesWithTheRegistries:
    """Three facts checked past the record, at ``config.py`` itself."""

    def test_a_laddered_codes_severities_are_the_matrix_row(
        self, pages: dict[str, str]
    ) -> None:
        from s0ma_dsl.config import SEVERITY_MATRIX, StrictnessMode

        ladder = SEVERITY_MATRIX["BARE_IMPORT"]
        written = ", ".join(
            f"{mode.value} `{ladder[mode]}`" for mode in StrictnessMode
        )
        section = _section(pages[DIAGNOSTICS_REFERENCE_OUTPUT], "BARE_IMPORT")
        assert f"- **Severity by mode** — {written}" in section

    def test_a_release_only_code_reads_as_not_checked_in_the_other_modes(
        self, pages: dict[str, str]
    ) -> None:
        """The shape ``None`` in the matrix exists to carry.

        "The check does not run in this mode" and "it runs and warns" are
        different facts, and a page that rendered both as a blank would
        lose the one the release-only checks are built around.
        """
        from s0ma_dsl.config import SEVERITY_MATRIX, StrictnessMode

        code = next(
            name
            for name, ladder in sorted(SEVERITY_MATRIX.items())
            if any(ladder[mode] is None for mode in StrictnessMode)
        )
        section = _section(pages[DIAGNOSTICS_REFERENCE_OUTPUT], code)
        assert "not checked" in section
        assert NOT_APPLICABLE not in section

    def test_an_out_of_matrix_code_says_the_mode_does_not_change_it(
        self, pages: dict[str, str]
    ) -> None:
        from s0ma_dsl.config import (
            ERROR_CODE_DESCRIPTIONS,
            OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE,
        )

        code = sorted(OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE)[0]
        section = _section(pages[DIAGNOSTICS_REFERENCE_OUTPUT], code)
        assert "not in the table" in section
        assert summary_line(ERROR_CODE_DESCRIPTIONS[code]) in section


# ---------------------------------------------------------------------------
# T3 — no fork: the pages agree with the registered derived sources
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheDerivedSourcesAreNotForked:
    """Two readings of one truth have to say one thing.

    ``error_codes`` and ``cli_commands`` are registered derived sources
    (ADR-013) rendering the same registries and the same parser into
    ``packages/s0ma-dsl/docs/_generated/common_errors.md`` and into any
    ``doc-ref`` that names them. These pages are a second rendering, not a
    second source, and this is what holds them to that.
    """

    def test_every_code_and_description_matches_the_error_codes_source(
        self, pages: dict[str, str]
    ) -> None:
        from s0ma_dsl.codegen.doc_emitter.derived_sources import error_codes_provider

        page = pages[DIAGNOSTICS_REFERENCE_OUTPUT]
        records = error_codes_provider()
        rows = records.as_mappings()
        assert {row["code"] for row in rows} == set(_entries(page))
        for row in rows:
            code = row["code"]
            assert code is not None
            section = _section(page, code)
            description = row["description"]
            assert description is not None
            assert summary_line(description) in section

    def test_every_stated_severity_matches_the_error_codes_source(
        self, pages: dict[str, str]
    ) -> None:
        """Agreement where the other source can speak, and one place it cannot.

        The derived source writes ``None`` both for a code outside the
        ladder and for a mode the matrix marks as not checked, so it
        renders the two as one em dash. This page distinguishes them,
        which is a finer rendering of the same facts and not a
        disagreement — so the assertion is one-directional exactly there.
        """
        from s0ma_dsl.codegen.doc_emitter.derived_sources import error_codes_provider

        page = pages[DIAGNOSTICS_REFERENCE_OUTPUT]
        for row in error_codes_provider().as_mappings():
            code = row["code"]
            assert code is not None
            section = _section(page, code)
            for mode in ("migration", "dev", "strict", "release"):
                stated = row[mode]
                if stated is None:
                    assert f"{mode} `" not in section, (code, mode)
                    continue
                assert f"{mode} `{stated}`" in section, (code, mode)

    def test_every_command_and_help_line_matches_the_cli_commands_source(
        self, pages: dict[str, str]
    ) -> None:
        from s0ma_dsl.codegen.doc_emitter.derived_sources import cli_commands_provider

        page = pages[CLI_REFERENCE_OUTPUT]
        rows = cli_commands_provider().as_mappings()
        assert {row["command"] for row in rows} == set(_entries(page))
        for row in rows:
            command = row["command"]
            assert command is not None
            section = _section(page, command)
            intent = row["intent"]
            if intent:
                assert intent in section, command
            effects = row["effects"]
            if effects:
                written = ", ".join(f"`{word}`" for word in effects.split(", "))
                assert f"- **Running it touches** — {written}" in section


# ---------------------------------------------------------------------------
# T2/T3 — determinism, canonical text, and the voice rule
# ---------------------------------------------------------------------------


def _page_text() -> str:
    """The three pages of this checkout, concatenated. Used by the seed test."""
    built = build(REPO_ROOT, version=RELEASE)
    rendered = _render(built, CliProvider(), DiagnosticsProvider(root=REPO_ROOT))
    return "".join(rendered[relative] for relative in REFERENCE_OUTPUTS)


@requires_checkout
class TestDeterminism:
    """The same composition is the same bytes, here and in a fresh process."""

    def test_rendering_twice_from_one_composition_is_byte_identical(
        self, composed: Build, cli: CliProvider, reports: DiagnosticsProvider
    ) -> None:
        assert _render(composed, cli, reports) == _render(composed, cli, reports)

    def test_a_second_composition_renders_the_same_bytes(
        self, pages: dict[str, str]
    ) -> None:
        again = build(REPO_ROOT, version=RELEASE)
        assert _render(again, CliProvider(), DiagnosticsProvider(root=REPO_ROOT)) == pages

    def test_the_pages_are_the_same_under_any_hash_seed(self) -> None:
        """Dictionary iteration is how a hash seed reaches output.

        The parser's subparser choices and the registries' fact maps are
        both dictionaries, so this can only be proved in a fresh process
        with the seed set.
        """
        script = (
            "from tests.test_docs_reference_pages import _page_text;"
            "print(_page_text(), end='')"
        )
        root = Path(__file__).resolve().parents[1]
        outputs = []
        for seed in ("0", "1", "524287"):
            # PYTHONUTF8 so the child renders its em-dash-bearing pages to a
            # utf-8 stdout — a Windows console defaults to cp1252, where
            # printing them raises UnicodeEncodeError and the child exits 1 —
            # and encoding= so the parent decodes the same bytes. check=False
            # with the assert surfaces the child's own traceback on failure.
            environment = {
                **os.environ,
                "PYTHONHASHSEED": seed,
                "PYTHONPATH": str(root),
                "PYTHONUTF8": "1",
            }
            result = subprocess.run(
                [sys.executable, "-c", script],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=root,
                env=environment,
            )
            assert result.returncode == 0, result.stderr
            outputs.append(result.stdout)
        assert outputs[0] == outputs[1] == outputs[2]
        assert outputs[0] == _page_text()

    def test_the_pages_are_canonical_text(self, pages: dict[str, str]) -> None:
        for relative, page in pages.items():
            assert "\r" not in page, relative
            assert page.endswith("\n"), relative
            assert not page.endswith("\n\n"), relative
            assert str(REPO_ROOT) not in page, relative
            assert str(Path.home()) not in page, relative


@requires_checkout
class TestTheAuthoredFramingIsInTheProductsVoice:
    """Rule 10, over the half of each page a person wrote.

    Everything these pages quote is a ``SOURCED`` field, and the voice
    rule deliberately does not reach a quotation (B4 finding 4). So the
    quotations are *removed* — by value, taken from the records the page
    was rendered from — and what is left is the framing: the headings, the
    opening, the legend, and every sentence composed at render time.
    """

    def test_no_forbidden_word_survives_in_the_framing(
        self, pages: dict[str, str], composed: Build
    ) -> None:
        quoted = sorted(
            {
                value
                for record in composed.bundle.surfaces
                for value in (record.intent, record.manual_exception, record.public_name)
                if value
            },
            key=len,
            reverse=True,
        )
        for relative, page in pages.items():
            framing = page
            for value in quoted:
                framing = framing.replace(value, " ")
            for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE:
                found = pattern.search(framing)
                assert found is None, f"{relative}: {label}: {found}"

    def test_the_removal_would_notice_a_forbidden_word(
        self, composed: Build
    ) -> None:
        """The subtraction above must not be able to hide a real violation.

        A test that removes text before searching it passes trivially if
        the removal takes too much, so the same subtraction is run over a
        page with a planted violation in its framing.
        """
        planted = "This sentence is about a payload.\n"
        quoted = [record.intent for record in composed.bundle.surfaces if record.intent]
        framing = planted
        for value in quoted:
            framing = framing.replace(value, " ")
        assert any(
            pattern.search(framing) for _label, pattern in FORBIDDEN_IN_AUTHORED_PROSE
        )


# ---------------------------------------------------------------------------
# T2 — what the renderers refuse, and what they state instead
# ---------------------------------------------------------------------------


_PROVENANCE = Provenance(
    adapter_id="fixture",
    schema_version=SCHEMA,
    source="fixture",
    source_sha256="0" * 64,
)


def _surface(identifier: str, *, channel: str, errors: tuple[str, ...] = ()) -> SurfaceRecord:
    """One planted capability, ready to be broken in exactly one place."""
    return SurfaceRecord(
        id=identifier,
        channel=channel,
        public_name=identifier.partition(":")[2],
        intent="Answer one question about the project being described.",
        component_refs=(),
        manual_exception="Written by hand for the fixture page it belongs to.",
        governed_by=(),
        side_effects=("read",),
        errors=errors,
        provenance=_PROVENANCE,
    )


def _bundle(*surfaces: SurfaceRecord) -> DocsBundle:
    """A bundle of nothing but the planted capabilities."""
    return DocsBundle(
        stamp=BuildStamp(schema=SCHEMA, release_version=RELEASE, snapshot_hash="0" * 64),
        authorities=(),
        concepts=(),
        surfaces=tuple(sorted(surfaces, key=lambda record: record.id)),
        journeys=(),
        sequences=(),
        documents=(),
    )


class TestTheRenderersRefuseAHole:
    """Two conditions, both of which would make a page quietly wrong."""

    def test_two_entries_that_would_share_an_anchor_are_refused(self) -> None:
        """A nested command and a hyphenated one can slug to one thing.

        Nothing in the id form forbids it, github-slugger would resolve it
        by silently suffixing the second, and every deep link to the
        second would then land on the first.
        """
        planted = _bundle(
            _surface("cli:s0ma/migrate-ext", channel="cli"),
            _surface("cli:s0ma/migrate/ext", channel="cli"),
        )
        with pytest.raises(DocsReferenceError, match="s0ma-migrate-ext"):
            cli_reference(planted)

    def test_a_fact_list_outside_the_grammar_is_refused(self) -> None:
        """``errors`` on these two channels is written by ``fact_entries``.

        An entry that is not a ``<key>=<value>`` fact means a second
        writer has appeared, and a page that skipped it would be the place
        that hid it.
        """
        planted = _bundle(
            _surface("diagnostic:PARSE_ERROR", channel="diagnostic", errors=("oops",))
        )
        with pytest.raises(DocsReferenceError, match="not a <key>=<value> fact"):
            diagnostics_reference(planted)


class TestWhatAPageSaysWhenAFactIsAbsent:
    """Absent is stated, never guessed and never quietly empty."""

    def test_a_command_with_no_parser_reading_says_so(self) -> None:
        """The honest answer for a composition with a record and no reading.

        An empty options table would read as a command that takes no
        flags, which is a different claim and a false one.
        """
        page = cli_reference(_bundle(_surface("cli:s0ma/planted", channel="cli")))
        assert "without the parser reading" in page
        assert "| Option |" not in page

    def test_a_composition_with_nothing_on_a_channel_says_that_too(self) -> None:
        """The negative battery composes builds like this on purpose."""
        empty = _bundle()
        assert "This build composed no commands" in cli_reference(empty)
        assert "This build composed no project settings" in configuration_reference(empty)
        assert "This build composed no reports" in diagnostics_reference(empty)

    def test_a_mode_nobody_declared_is_shown_rather_than_dropped(self) -> None:
        """A severity column this build has never heard of still renders.

        The rule ``inventories`` follows for an untitled channel. A table
        that silently dropped a mode would hide the one thing a severity
        ladder exists to show.
        """
        planted = _bundle(
            _surface(
                "diagnostic:PLANTED_CODE",
                channel="diagnostic",
                errors=("paranoid=error", "registry=severity_matrix"),
            )
        )
        page = diagnostics_reference(planted, modes=())
        assert "| Report | paranoid |" in page
        assert "paranoid `error`" in page


# ---------------------------------------------------------------------------
# T3 — the wiring note's catalog rows, loaded by the real reader
# ---------------------------------------------------------------------------


def _fixture_catalog(root: Path) -> None:
    """A checkout holding nothing but this milestone's three rows.

    The three files are written because the catalog refuses a row naming a
    file that is not there, which is one of the shape rules being proved:
    a row whose ``canonical_source`` does not match the declared output
    would be caught here rather than at the wave gate.
    """
    (root / DOCS_ROOT / "s0ma_src").mkdir(parents=True)
    for relative in REFERENCE_OUTPUTS:
        target = root.joinpath(DOCS_ROOT, *relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Placeholder\n", encoding="utf-8", newline="\n")
    (root / CATALOG_FILE).write_text(
        json.dumps(
            {
                "documents": list(CATALOG_ROWS),
                "excluded": [],
                "schema": CATALOG_SCHEMA,
                "self": {
                    "audiences": ["agent", "contributor"],
                    "id": "doc:catalog/document-catalog",
                    "kind": "reference",
                    "status": "living",
                    "title": "The document catalog",
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


class TestTheWiringNote:
    """The rows this milestone hands over are rows the build can read."""

    def test_the_rows_load_through_the_real_catalog_reader(
        self, tmp_path: Path
    ) -> None:
        _fixture_catalog(tmp_path)
        provider = CatalogProvider(root=tmp_path)
        rows = {row.id: row for row in provider.rows()}
        for written in CATALOG_ROWS:
            row = rows[str(written["id"])]
            assert row.status == "generated"
            assert row.kind == "reference"
            assert row.audiences == tuple(written["audiences"])
        assert not provider.findings()

    def test_each_row_names_the_output_its_renderer_declares(self) -> None:
        """The row and the declared output are one path, written once.

        A catalog row pointing at a file the application never writes is
        the drift this milestone would otherwise introduce, so the rows
        are built from the output constants rather than from a string.
        """
        sources = {str(row["canonical_source"]) for row in CATALOG_ROWS}
        assert sources == {f"{DOCS_ROOT}/{relative}" for relative in REFERENCE_OUTPUTS}
        for row in CATALOG_ROWS:
            assert row["prose_locator"] == row["canonical_source"]

    @requires_checkout
    def test_each_rows_title_is_the_pages_own_heading(
        self, pages: dict[str, str]
    ) -> None:
        """A catalog title that is not the page's title is two names for one page."""
        titles = {
            str(row["canonical_source"]): str(row["title"]) for row in CATALOG_ROWS
        }
        for relative, page in pages.items():
            assert _headings(page)[0] == titles[f"{DOCS_ROOT}/{relative}"]

    def test_the_three_outputs_are_declared_in_one_place(self) -> None:
        """``REFERENCE_OUTPUTS`` is what the application appends, in order."""
        assert REFERENCE_OUTPUTS == (
            CLI_REFERENCE_OUTPUT,
            CONFIGURATION_REFERENCE_OUTPUT,
            DIAGNOSTICS_REFERENCE_OUTPUT,
        )
        assert set(PAGE_BY_ID_CLASS.values()) == set(REFERENCE_OUTPUTS)
