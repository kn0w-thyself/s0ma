"""Gates for G7 — ``docs/trust-model.md``, the consolidated trust note.

Milestone G7 of the docs-function plan (internal) §12. This page is the one
a reader consults *before* deciding to run anything, which makes a stale
sentence in it worse than a stale sentence anywhere else in the corpus: a
person who checked the trust model and found it reassuring will not check
it twice.

Architecture §12 closes with the rule this suite exists to keep: the guide
"will explain these structural controls rather than substitute for them".
A page that explains a control it cannot point at has substituted for it,
so every promise on the page ends in a named enforcement point and every
one of those names is resolved here against the tree.

What is held:

* **the enforcement pointers resolve, in both directions** (T3) — every
  repository path and every ``file::name`` the page cites is a tracked
  file, and a named test or function really is defined in it. The reverse
  half matters as much: a pointer added to the page and not to
  :data:`POINTERS` fails, so the ledger cannot fall behind the prose it
  describes. A renamed test breaks the page's claim loudly, at the place
  the claim is made;
* **the vocabularies are the product's, not the page's** (T3) — the seven
  effect words the page defines are read out of its own table and compared
  with :data:`~s0ma_dsl.docs_model.validate.SIDE_EFFECT_WORDS`; the three
  example modes are compared with the parser's; the timeout the page
  states in words is compared with core's number; the one program a
  transcript may run is compared with the evidence format's closed set.
  Each is a sentence a reader would act on, pinned to the constant that
  makes it true;
* **the links resolve** (T3) — A5's rule, asked of this one file. The
  repository gate scans ``docs/`` and would catch these too; asking here
  as well is what makes the suite standalone and what reports the failure
  next to the claim rather than in a stage;
* **the voice battery** (T3) — this page is written for people deciding
  whether to trust the product, so it is held to the product's words:
  ``FORBIDDEN_IN_AUTHORED_PROSE``, the same three patterns every authored
  concept and journey is held to;
* **the filing** (T2) — the catalog row and the classification-ledger row
  say what the milestone decided they say, and the row's coverage names
  concepts this build really composes.

**Cost.** The documentation build is composed once for the module, and
only by the two tests that need the composed concepts.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from s0ma.examples.timeout import DEFAULT_TIMEOUT_SECONDS

from s0ma_dsl.cli.feedback_commands import (
    NON_INTERACTIVE_REFUSAL,
    NON_INTERACTIVE_REMEDIATION,
)
from s0ma_dsl.docs_model.application import build as build_documentation
from s0ma_dsl.docs_model.evidence import PROGRAMS
from s0ma_dsl.docs_model.ids import normalize_id
from s0ma_dsl.docs_model.providers_concepts import FORBIDDEN_IN_AUTHORED_PROSE
from s0ma_dsl.docs_model.validate import SIDE_EFFECT_WORDS
from s0ma_dsl.parser.s0ma_parser import VALID_EXAMPLE_RUNS_IN

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The page this suite is about, repository-relative.
GUIDE = "docs/trust-model.md"

#: Its catalog row, and the id the map of record files it under.
DOCUMENT_ID = "doc:guide/trust-model"

#: The catalog fields G7 decided, quoted here so a later edit to any of
#: them is a decision somebody takes rather than a drift nobody sees.
CATALOG_ROW: dict[str, Any] = {
    "audiences": ["contributor", "user"],
    "authority": "",
    "canonical_source": GUIDE,
    "covers": [
        "concept:authored-vs-generated-boundary",
        "concept:example",
        "concept:executable-evidence",
        "concept:feedback",
    ],
    "governed_by": [],
    "id": DOCUMENT_ID,
    "kind": "guide",
    "prose_locator": GUIDE,
    "status": "living",
    "title": "What s0ma trusts",
}

#: The A6 classification ledger, and the disposition this page carries.
#: An ordinary tracked gate input under ``docs/s0ma_src/`` since the
#: front-door move, so it is read directly here; the class below is
#: ``requires_checkout``, which is the only absence left to cover.
LEDGER = "docs/s0ma_src/doc-classification.json"
LEDGER_DISPOSITION = "living-authored"
LEDGER_AUDIENCE = "user"

#: Every enforcement point the page names, and what each one has to be.
#:
#: A bare repository path must be a tracked file. A ``path::name`` must be
#: a tracked Python file that really defines ``name`` — which is the half
#: that turns a renamed test into a failure here rather than into a
#: sentence nobody can check.
#:
#: This tuple is compared with what the page actually cites in **both**
#: directions (:class:`TestEveryEnforcementPointerResolves`), so it is a
#: ledger of the page's promises rather than a sample of them.
POINTERS: tuple[str, ...] = (
    "docs/_generated/inventory-surfaces.json",
    # The Claude route (beta-prep-2-claude D1). The launcher is the one part
    # of s0ma that contacts anything unasked, so the section about it ends in
    # the file that does it and in one test per promise.
    "integrations/launcher/s0ma_launch.py",
    # beta-prep-5 B3: the complete network table. Every row of it ends in the
    # test that proves that row, which is what makes "this list is complete"
    # a claim a reader can audit one line at a time rather than a promise.
    "integrations/launcher/tests/test_activate.py",
    "integrations/launcher/tests/test_activate.py"
    "::test_the_key_is_checked_exactly_once_and_only_in_a_header",
    "integrations/launcher/tests/test_install.py",
    "integrations/launcher/tests/test_install.py"
    "::test_a_wheel_already_downloaded_is_used_again",
    "integrations/launcher/tests/test_install.py"
    "::test_the_key_travels_in_the_header_and_nowhere_else",
    "integrations/launcher/tests/test_install.py::test_uv_is_never_handed_the_key",
    "integrations/launcher/tests/test_pin.py",
    "integrations/launcher/tests/test_pin.py::test_pin_asks_whether_the_version_exists",
    "integrations/launcher/tests/test_session_hint.py",
    "integrations/launcher/tests/test_session_hint.py::test_no_socket_is_opened",
    "integrations/launcher/tests/test_update.py",
    "integrations/launcher/tests/test_update.py"
    "::test_the_control_plane_is_asked_at_most_once_a_day",
    "packages/s0ma-core/src/s0ma/api/rest.py",
    "packages/s0ma-core/src/s0ma/examples/dispatcher.py",
    "packages/s0ma-core/src/s0ma/examples/timeout.py",
    "packages/s0ma-dsl/src/s0ma_dsl/cli/doctor.py",
    "packages/s0ma-dsl/src/s0ma_dsl/docs_model/evidence.py",
    "packages/s0ma-dsl/src/s0ma_dsl/docs_model/records.py",
    "packages/s0ma-dsl/src/s0ma_dsl/docs_model/validate.py",
    "packages/s0ma-dsl/tests/test_artifact_portability_sweep.py",
    "packages/s0ma-dsl/tests/test_docs_application_cli.py",
    "packages/s0ma-dsl/tests/test_docs_application_cli.py"
    "::test_no_artifact_carries_the_machine_that_built_it",
    "packages/s0ma-dsl/tests/test_docs_binding_policy.py",
    "packages/s0ma-dsl/tests/test_docs_evidence.py",
    "packages/s0ma-dsl/tests/test_docs_journey_studi0_feedback.py",
    "packages/s0ma-dsl/tests/test_docs_trust_model.py",
    "packages/s0ma-dsl/tests/test_example_runs_in_validation.py",
    "packages/s0ma-dsl/tests/test_feedback_client.py",
    "packages/s0ma-dsl/tests/test_feedback_client.py"
    "::test_a_deleted_report_is_absent_from_the_listing",
    "packages/s0ma-dsl/tests/test_feedback_client.py"
    "::test_enrolling_sends_the_license_key_and_stores_the_token",
    "packages/s0ma-dsl/tests/test_feedback_client.py"
    "::test_listing_returns_typed_rows_newest_first",
    "packages/s0ma-dsl/tests/test_feedback_client.py"
    "::test_the_license_key_never_travels_with_a_report",
    "packages/s0ma-dsl/tests/test_feedback_context.py",
    "packages/s0ma-dsl/tests/test_feedback_context.py"
    "::test_no_module_imports_anything_network_shaped",
    "packages/s0ma-mcp/src/s0ma_mcp/__init__.py",
    "packages/s0ma-mcp/tests/test_stdio_smoke.py",
    "packages/s0ma-mcp/tests/test_stdio_smoke.py::TestStdioTransport",
    "packages/s0ma-mcp/tests/test_telemetry_invisibility.py",
    "packages/s0ma-mcp/tests/test_telemetry_invisibility.py"
    "::test_sink_written_only_when_enabled",
    "packages/s0ma-studi0/tests/test_api.py",
    "packages/s0ma-studi0/tests/test_api.py"
    "::test_every_route_table_entry_has_the_declared_shape",
    "packages/s0ma-studi0/tests/test_launch.py",
    "packages/s0ma-studi0/tests/test_launch.py::test_binds_loopback_only",
    "scripts/check_docs_application.py",
    # A shell script, and the only one the page cites. ``cited`` recognises
    # ``.sh`` for exactly this reason: the keyed installer is one of the ways
    # a license key leaves this machine, and a row about it that resolved to
    # nothing would be the one unchecked promise in a table whose whole worth
    # is that every row is checked.
    "scripts/install.sh",
)

#: Names the page cites in prose as the gate behind a promise, with the
#: module each has to live in. Resolved by import, because a name that
#: moved to another module is exactly as broken a citation as a name that
#: was deleted.
NAMED_GATES: tuple[tuple[str, str], ...] = (
    ("s0ma_dsl.docs_model.records", "AUTHORITY_ORDER"),
    ("s0ma_dsl.docs_model.records", "FieldClass"),
    ("s0ma_dsl.docs_model.records", "Provenance"),
    ("s0ma_dsl.docs_model.validate", "check_authority_records"),
    ("s0ma_dsl.docs_model.validate", "check_journeys"),
    ("s0ma_dsl.docs_model.validate", "check_provenance"),
    ("s0ma_dsl.docs_model.validate", "check_side_effects"),
)

#: The page's sections, in the order it walks them. Authored here so a
#: section that quietly disappears — the one about what listens on a port,
#: say — fails rather than leaving a trust model with a hole in it.
SECTIONS: tuple[str, ...] = (
    "What s0ma trusts",
    "The one rule",
    "Every capability says what calling it does",
    "When s0ma runs code, and when it does not",
    "Executable evidence: the transcripts behind the guides",
    "What listens, and to whom",
    # beta-prep-5 B3. The complete table and the two things that have to sit
    # beside it: the "no" list, and the one local record a person can switch
    # on. A trust model that lists most of the connections is worth nothing,
    # so these three headings are pinned like the rest — a section removed
    # here is a hole a reader would have no way of noticing.
    "Every connection s0ma can make",
    "What never happens",
    "The one record you can switch on, and what it holds",
    "What s0ma sends when it is installed through Claude",
    "Feedback: nothing leaves without you",
    "What is never in what s0ma writes",
    "Observed is not declared",
    "Where each of these is held",
    "What this page is not",
)

#: The heading over the one table that claims to be complete. Named once,
#: here, because two tests and a fixture all have to find the same table.
NETWORK_TABLE_HEADING = "Every connection s0ma can make"

#: A number the page spells out in words, and the constant it is a
#: statement about. English rather than digits because the page is written
#: for people, which is exactly why it would rot unnoticed.
SPELLED_NUMBERS: tuple[tuple[str, int], ...] = (("thirty seconds", 30),)

_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*$")
_FENCE = re.compile(r"^```")
_CODE_SPAN = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\]\((?!https?:|mailto:)(?P<target>[^)#]*)(?:#(?P<anchor>[^)]*))?\)")
_TABLE_WORD = re.compile(r"^\|\s*`(?P<word>[a-z]+)`\s*\|")
_PUNCTUATION = re.compile(r"[^\w\- ]", re.UNICODE)


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


def _slugify(text: str) -> str:
    """The GitHub heading anchor for *text* — ``scripts/check_links.py``'s rule.

    Restated rather than imported: that file is a script and ships in no
    wheel, so importing it would make this suite depend on a checkout for
    a rule that is four lines long.
    """
    return _PUNCTUATION.sub("", text.strip().lower()).replace(" ", "-")


def _outside_fences(text: str) -> Iterator[str]:
    """Every line not inside a fenced block. A sample is not a citation."""
    inside = False
    for line in text.splitlines():
        if _FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            yield line


def _flowed(text: str) -> str:
    """*text* with every run of whitespace collapsed to one space.

    The page is hand-wrapped prose, so a sentence this suite pins can sit
    across two lines this week and one line next week. Searching the
    reflowed form asks about the sentence rather than about where the
    author happened to break the line — the alternative is a suite that
    fails on a rewrap, which teaches an author to stop rewrapping.
    """
    return " ".join(text.split())


def _defines(path: Path, name: str) -> bool:
    """Whether *path* really defines *name*, at any nesting depth."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wanted = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    return any(
        isinstance(node, wanted) and node.name == name for node in ast.walk(tree)
    )


def _launcher() -> Any:
    """The launcher module, loaded from its file.

    It ships in no wheel and sits outside every package, so there is no
    import path to it; this is the same by-path load its own conftest
    uses, registration in ``sys.modules`` included — ``dataclasses``
    resolves a frozen class's own module while building it, and a module
    that is not registered fails there rather than at the import. Loaded
    rather than re-typed because the point of reading it here is to
    compare the page against the constants, not against a copy of them
    made when this was written.
    """
    import importlib.util
    import sys

    name = "s0ma_launch_for_docs"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = REPO_ROOT / "integrations" / "launcher" / "s0ma_launch.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def _table_under(text: str, heading: str) -> tuple[tuple[str, ...], ...]:
    """Every body row of the first table under *heading*, cell by cell.

    The header row and its separator are dropped, so what comes back is
    the claims and nothing else. A heading with no table under it returns
    nothing, which the floor above then reports as the failure it is.
    """
    lines = list(_outside_fences(text))
    start = None
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if match and match.group("text") == heading:
            start = index + 1
            break
    if start is None:
        return ()

    table: list[str] = []
    for line in lines[start:]:
        if line.startswith("|"):
            table.append(line)
            continue
        if table:
            break
    if len(table) < 3:  # a header, a separator, and at least one claim
        return ()

    rows: list[tuple[str, ...]] = []
    for line in table[2:]:
        rows.append(tuple(cell.strip() for cell in line.strip().strip("|").split("|")))
    return tuple(rows)


# ---------------------------------------------------------------------------
# What every test reads, read once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def guide_text() -> str:
    return (REPO_ROOT / GUIDE).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def guide_prose(guide_text: str) -> str:
    """The page as one flowed string — what a sentence-level pin searches."""
    return _flowed(guide_text)


@pytest.fixture(scope="module")
def cited(guide_text: str) -> tuple[str, ...]:
    """Every code span on the page that reads as a repository pointer.

    A span qualifies when it names a file (a slash and a known extension)
    or names something inside one (``::``). Everything else in backticks
    on this page is product vocabulary — an effect word, an address, a
    command — and is checked by the tests that own those.

    ``sh`` joined the extensions with B3's network table: the keyed
    installer is one of the ways a license key leaves a machine, and until
    it was recognised here a citation of it resolved to nothing at all —
    a row that looked checked and was not.
    """
    found: set[str] = set()
    for line in _outside_fences(guide_text):
        for span in _CODE_SPAN.findall(line):
            if "::" in span or (
                "/" in span and span.rsplit(".", 1)[-1] in {"py", "json", "md", "sh"}
            ):
                found.add(span)
    return tuple(sorted(found))


@pytest.fixture(scope="module")
def table_rows(guide_text: str) -> tuple[tuple[str, ...], ...]:
    """The body rows of the complete network table (beta-prep-5 B3)."""
    return _table_under(guide_text, NETWORK_TABLE_HEADING)


@pytest.fixture(scope="module")
def catalog() -> dict[str, Any]:
    raw = (REPO_ROOT / "docs" / "s0ma_src" / "catalog.json").read_text(encoding="utf-8")
    return json.loads(raw)


@pytest.fixture(scope="module")
def live() -> Any:
    """The whole documentation build, composed once for this module."""
    return build_documentation(REPO_ROOT)


# ---------------------------------------------------------------------------
# The file itself (T1)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheGuideIsThere:
    """The page exists, in the encoding every emitted file in this repo uses."""

    def test_the_file_is_utf8_with_line_feeds_and_one_trailing_newline(self) -> None:
        raw = (REPO_ROOT / GUIDE).read_bytes()
        assert b"\r" not in raw
        assert raw.endswith(b"\n")
        assert not raw.endswith(b"\n\n")
        raw.decode("utf-8")

    def test_the_sections_are_the_ones_this_milestone_authored(
        self, guide_text: str
    ) -> None:
        headings = [
            match.group("text")
            for line in _outside_fences(guide_text)
            if (match := _HEADING.match(line))
        ]
        assert tuple(headings) == SECTIONS


# ---------------------------------------------------------------------------
# The enforcement pointers (T3)
# ---------------------------------------------------------------------------


@requires_checkout
class TestEveryEnforcementPointerResolves:
    """A promise that cannot be checked is the failure this class prevents."""

    def test_the_page_cites_exactly_the_ledgers_pointers(
        self, cited: tuple[str, ...]
    ) -> None:
        """Both directions, because each catches a different rot.

        A pointer in the ledger and not on the page is a promise that was
        edited away. A pointer on the page and not in the ledger is a
        promise nothing resolved — which is the whole failure this suite
        exists to make impossible.
        """
        assert cited == tuple(sorted(POINTERS))

    @pytest.mark.parametrize("pointer", sorted(POINTERS))
    def test_the_pointer_names_something_that_is_really_there(
        self, pointer: str
    ) -> None:
        relative, _, name = pointer.partition("::")
        target = REPO_ROOT / relative
        assert target.is_file(), relative
        if name:
            assert _defines(target, name), pointer

    @pytest.mark.parametrize(("module", "name"), NAMED_GATES)
    def test_the_named_gate_is_in_the_module_the_page_puts_it_in(
        self, module: str, name: str, guide_text: str
    ) -> None:
        imported = __import__(module, fromlist=[name])
        assert hasattr(imported, name), f"{module}.{name}"
        assert f"`{name}`" in guide_text, name

    def test_the_ledger_is_not_a_sample(self) -> None:
        """An anti-vacuity floor: a page with two pointers proves nothing.

        Raised from twelve when B3's network table landed. The page cites
        far more than this; the floor sits well below the real count so
        ordinary rewording never trips it, and well above zero so a
        truncated ledger cannot pass.
        """
        assert len(POINTERS) >= 30
        assert len(NAMED_GATES) >= 5


# ---------------------------------------------------------------------------
# The vocabularies are the product's (T3)
# ---------------------------------------------------------------------------


@requires_checkout
class TestThePageQuotesTheProductsOwnVocabulary:
    """Every list and number the page teaches, against the thing that owns it."""

    def test_the_effect_words_are_the_models_effect_words(
        self, guide_text: str
    ) -> None:
        """The page's table read back as data, compared with the frozen set.

        The reader is being taught seven words and told the list is
        closed. If the model ever gains an eighth, this is where the page
        finds out.
        """
        found = {
            match.group("word")
            for line in _outside_fences(guide_text)
            if (match := _TABLE_WORD.match(line))
        }
        assert found == set(SIDE_EFFECT_WORDS)

    def test_the_page_says_the_word_list_is_closed(self, guide_prose: str) -> None:
        assert "The list is closed." in guide_prose

    def test_the_run_modes_are_the_parsers_run_modes(self, guide_prose: str) -> None:
        for mode in VALID_EXAMPLE_RUNS_IN:
            assert f"`{mode}`" in guide_prose, mode
        assert "three modes" in guide_prose

    @pytest.mark.parametrize(("spelled", "value"), SPELLED_NUMBERS)
    def test_a_number_the_page_spells_out_is_the_number_in_the_code(
        self, spelled: str, value: int, guide_prose: str
    ) -> None:
        assert spelled in guide_prose
        assert value == DEFAULT_TIMEOUT_SECONDS

    def test_the_only_program_a_transcript_may_run_is_the_one_named(
        self, guide_prose: str
    ) -> None:
        assert PROGRAMS == ("s0ma",)
        assert "the only program a transcript may name is `s0ma`" in guide_prose

    def test_the_refusal_the_page_describes_is_the_one_the_product_prints(
        self, guide_prose: str
    ) -> None:
        """Two claims a reader would act on, against the strings themselves."""
        assert "Nothing was sent." in NON_INTERACTIVE_REFUSAL
        assert "No flag skips the approval step" in _flowed(
            NON_INTERACTIVE_REMEDIATION
        )
        assert "No flag skips the approval step" in guide_prose
        assert "Silence is no." in guide_prose


# ---------------------------------------------------------------------------
# The network table (beta-prep-5 B3)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheNetworkTableIsComplete:
    """The one table, held to the only standard that makes it worth reading.

    "Every connection s0ma can make" is a completeness claim, and a
    completeness claim is either audited or decorative. Three things are
    asked of it here: every row ends in a citation the ledger above
    resolves, so no row is an assertion; the table does not shrink without
    somebody deciding it should; and the facts a reader would act on — the
    host, the once-a-day rule, the size cap on a report, the name of the
    switch that turns the local call log on — are compared with the
    constants that make them true rather than re-typed.
    """

    def test_every_row_of_the_table_ends_in_a_citation(
        self, table_rows: tuple[tuple[str, ...], ...]
    ) -> None:
        """The last cell of every row is a pointer this suite resolved."""
        for row in table_rows:
            citation = row[-1].strip()
            found = _CODE_SPAN.fullmatch(citation)
            assert found is not None, f"row not cited: {row[0]}"
            assert found.group(1) in POINTERS, found.group(1)

    def test_the_table_still_covers_the_whole_product(
        self, table_rows: tuple[tuple[str, ...], ...]
    ) -> None:
        """An anti-vacuity floor for the table itself.

        Fifteen rows is what the product needed when this was written: the
        launcher's four requests, uv, the keyed installer, four feedback
        requests, the viewer, the authoring server, the optional HTTP view,
        the plugin, and everything else. A row deleted is a connection a
        reader can no longer find, which is exactly the failure a nearly
        complete table produces.
        """
        assert len(table_rows) >= 15

    def test_every_row_says_which_way_it_goes(
        self, table_rows: tuple[tuple[str, ...], ...]
    ) -> None:
        """A closed vocabulary, so "which way" is never left to the reader."""
        allowed = ("outbound request", "listener", "neither", "no socket")
        for row in table_rows:
            direction = row[1].lower()
            assert any(word in direction for word in allowed), row[1]

    def test_the_host_is_the_launchers_own_default(self, guide_prose: str) -> None:
        launcher = _launcher()
        assert launcher.DEFAULT_CP_HOST in guide_prose
        assert f"`{launcher.DEFAULT_CP_HOST}`" in guide_prose

    def test_once_a_day_is_the_interval_the_launcher_keeps(
        self, guide_prose: str
    ) -> None:
        assert _launcher().UPDATE_CHECK_INTERVAL_SECONDS == 24 * 60 * 60
        assert "once a day" in guide_prose

    def test_the_size_the_page_states_is_the_contracts_cap(
        self, guide_prose: str
    ) -> None:
        from s0ma_dsl.feedback.model import BODY_MAX_BYTES

        assert BODY_MAX_BYTES == 32 * 1024
        assert "at most 32 KB of it" in guide_prose

    def test_the_local_call_log_is_named_as_the_server_names_it(
        self, guide_prose: str
    ) -> None:
        """The switch, the sink and the off-words, from the server itself."""
        from s0ma_mcp import _TELEMETRY_OFF_VALUES

        assert "`S0MA_MCP_TELEMETRY`" in guide_prose
        assert "`S0MA_MCP_TELEMETRY_SINK`" in guide_prose
        for word in sorted(_TELEMETRY_OFF_VALUES - {""}):
            assert f"`{word}`" in guide_prose, word

    def test_the_http_view_row_counts_the_routes_this_build_composes(
        self, live: Any, guide_prose: str
    ) -> None:
        """Fourteen routes, thirteen of them ``GET`` — counted, not recalled."""
        routes = [record for record in live.bundle.surfaces if record.channel == "rest"]
        gets = [item for item in routes if item.public_name.startswith("GET ")]
        posts = [item for item in routes if item.public_name.startswith("POST ")]
        assert len(routes) == 14
        assert (len(gets), len(posts)) == (13, 1)
        assert "14 read-only routes" in guide_prose
        assert "Thirteen answer `GET`" in guide_prose


# ---------------------------------------------------------------------------
# Links (T3)
# ---------------------------------------------------------------------------


@requires_checkout
class TestEveryLinkResolves:
    """A5's rule, asked of this one file, next to the claim it carries."""

    def test_every_intra_repo_link_names_a_file_that_is_there(
        self, guide_text: str
    ) -> None:
        here = (REPO_ROOT / GUIDE).parent
        for match in _LINK.finditer(guide_text):
            target = match.group("target")
            if not target:
                continue
            assert (here / target).resolve().is_file(), target

    def test_every_anchor_names_a_heading_that_is_there(self, guide_text: str) -> None:
        here = (REPO_ROOT / GUIDE).parent
        checked = 0
        for match in _LINK.finditer(guide_text):
            anchor = match.group("anchor")
            target = match.group("target")
            if not anchor or not target or not target.endswith(".md"):
                continue
            page = (here / target).resolve()
            slugs = {
                _slugify(found.group("text"))
                for line in _outside_fences(page.read_text(encoding="utf-8"))
                if (found := _HEADING.match(line))
            }
            assert anchor in slugs, f"{target}#{anchor}"
            checked += 1
        assert checked >= 3, "the page has stopped deep-linking anything"


# ---------------------------------------------------------------------------
# The voice rule (T3)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheVoice:
    """Written for people deciding whether to trust s0ma, in this product's words."""

    def test_the_prose_never_uses_a_word_this_product_does_not(
        self, guide_text: str
    ) -> None:
        for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE:
            found = pattern.search(guide_text)
            assert found is None, f"{label}: {found.group(0) if found else ''}"


# ---------------------------------------------------------------------------
# The filing (T2)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheFiling:
    """One catalog row, one ledger row, and both say what G7 decided."""

    def test_the_catalog_row_is_the_row_this_milestone_wrote(
        self, catalog: dict[str, Any]
    ) -> None:
        rows = [item for item in catalog["documents"] if item["id"] == DOCUMENT_ID]
        assert len(rows) == 1
        assert rows[0] == CATALOG_ROW

    def test_no_second_row_claims_this_file(self, catalog: dict[str, Any]) -> None:
        owners = [
            item["id"]
            for item in catalog["documents"]
            if item["canonical_source"] == GUIDE
        ]
        assert owners == [DOCUMENT_ID]

    def test_every_concept_the_row_covers_is_one_this_build_composes(
        self, live: Any
    ) -> None:
        known = {normalize_id(record.id) for record in live.bundle.concepts}
        for covered in CATALOG_ROW["covers"]:
            assert normalize_id(covered) in known, covered

    def test_the_page_teaches_the_concepts_the_row_claims(
        self, live: Any, guide_prose: str
    ) -> None:
        concepts = {normalize_id(record.id): record for record in live.bundle.concepts}
        lowered = guide_prose.lower()
        for covered in CATALOG_ROW["covers"]:
            assert concepts[normalize_id(covered)].term in lowered, covered

    def test_the_classification_ledger_carries_this_page(self) -> None:
        raw = (REPO_ROOT / LEDGER).read_text(encoding="utf-8")
        rows = [item for item in json.loads(raw)["entries"] if item["path"] == GUIDE]
        assert len(rows) == 1
        assert rows[0]["disposition"] == LEDGER_DISPOSITION
        assert rows[0]["audience"] == LEDGER_AUDIENCE
        assert len(rows[0]["note"].split()) >= 20
