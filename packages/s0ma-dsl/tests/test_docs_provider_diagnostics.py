"""Gates for D2 — the DSL diagnostics provider.

Milestone D2 of the docs-function plan (internal) §9, over
``s0ma_dsl.docs_model.providers_diagnostics``. What these tests hold in
place:

* **every registered code is addressed.** The record set is exactly the
  union of ``SEVERITY_MATRIX`` and
  ``OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE``, asserted against
  the live module rather than against a number written here, so a code
  added by any milestone appears without an edit to this file.
* **derived, not copied.** The provider reads ``config.py`` structurally,
  and the proof is a copied tree: change a severity in the copy and the
  record changes with it; add a code and a record appears; remove one and
  its record goes. A provider that imported the module would pass a
  parity test by tautology and fail every one of these.
* **the release-only shape survives.** ``MISSING_PUBLIC_DOC_REF`` and
  ``MISSING_EMBEDDED_EXAMPLE`` are checks that do not run in three modes
  and are errors in the fourth, and "does not run" and "runs and warns"
  stay two different facts all the way to the record.
* **a shape this reader does not know stops the build.** Every refusal is
  proved against a synthetic registry, because a diagnostic that quietly
  failed to appear is a deep link that quietly stops resolving.
* **it composes clean.** The records pass every C2 gate with zero
  findings, and adding the provider to this repository's documentation
  application introduces no finding that was not there without it.

The live repository is the fixture for the counting tests on purpose: an
index of diagnostics that agreed with a synthetic tree and disagreed with
the product would be worthless. The floor is an honest minimum, set below
the live count so ordinary authoring never turns a green suite red.
"""

from __future__ import annotations

import ast
import hashlib
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.config import (
    ERROR_CODE_DESCRIPTIONS,
    OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE,
    SEVERITY_MATRIX,
    StrictnessMode,
)
from s0ma_dsl.docs_model import application
from s0ma_dsl.docs_model.compose import compose
from s0ma_dsl.docs_model.ids import id_form, validate_id
from s0ma_dsl.docs_model.providers import (
    ProviderRegistry,
    ProviderResult,
    record_key,
)
from s0ma_dsl.docs_model.providers_diagnostics import (
    CHANNEL,
    CONFIG_SOURCE,
    DESCRIPTIONS_NAME,
    DIAGNOSTIC_FLOORS,
    MATRIX_NAME,
    MATRIX_REGISTRY,
    MODE_ENUM,
    NOT_APPLICABLE,
    OUT_OF_MATRIX_NAME,
    OUT_OF_MATRIX_REGISTRY,
    PROVIDER_ID,
    REGISTRY_KEY,
    UNBOUND_EXCEPTION,
    DiagnosticsProvider,
    DiagnosticsProviderError,
    diagnostic_id,
    fact_entries,
    fact_map,
    severity_of,
    summary_line,
)
from s0ma_dsl.docs_model.records import SCHEMA, SurfaceRecord
from s0ma_dsl.docs_model.render_agent import (
    AGENT_BYTE_BUDGET,
    check_budget,
    render_agent,
)
from s0ma_dsl.docs_model.render_human import render_human
from s0ma_dsl.docs_model.resolve import TopicIndex, check_coverage, facts_of, resolve
from s0ma_dsl.docs_model.serialize import serialize_bundle
from s0ma_dsl.docs_model.validate import check_floors, validate_bundle

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "s0ma_dsl"
    / "docs_model"
    / "providers_diagnostics.py"
)

RELEASE = "0.20.0"

#: The four modes as the enum spells them, in ladder order. Read from the
#: live enum rather than written out, for the same reason the provider
#: reads them from the file: one definition.
MODES = tuple(mode.value for mode in StrictnessMode)

#: The codes whose ``config.py`` description is long enough to push an
#: agent answer past its byte budget. **Empty since D5a**, which shortened
#: the three that were on it — ``BARE_IMPORT``, ``MODULE_NAME_COLLISION``
#: and ``CONSUMES_VIA_DICT_INVALID`` — in ``config.py``, where the remedy
#: always belonged: the record quotes the description verbatim, the
#: channel rule is verbatim or absent, and a provider may not shorten one.
#: The set is still asserted exactly, so a description that grows past the
#: budget turns the suite red instead of quietly serving a truncated
#: answer.
OVERSIZED_TODAY: frozenset[str] = frozenset()


def _surfaces(result: ProviderResult) -> tuple[SurfaceRecord, ...]:
    """The result's records, typed. A diagnostic record is a surface."""
    found: list[SurfaceRecord] = []
    for item in result.records:
        assert isinstance(item.record, SurfaceRecord), (
            f"{item.record.id} is a {type(item.record).__name__}; this "
            f"provider emits served capabilities and nothing else"
        )
        found.append(item.record)
    return tuple(found)


def _by_id(result: ProviderResult) -> dict[str, SurfaceRecord]:
    return {record.id: record for record in _surfaces(result)}


def _live_codes() -> frozenset[str]:
    """Every code the running module registers, from both registries."""
    return frozenset(SEVERITY_MATRIX) | frozenset(
        OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE
    )


@pytest.fixture(scope="module")
def live() -> ProviderResult:
    """The provider's reading of this checkout, done once."""
    return DiagnosticsProvider(root=REPO_ROOT).provide()


@pytest.fixture(scope="module")
def index(live: ProviderResult) -> dict[str, SurfaceRecord]:
    return _by_id(live)


# ---------------------------------------------------------------------------
# Copied and synthetic trees
# ---------------------------------------------------------------------------


def _copy_config(destination: Path) -> Path:
    """A checkout holding only the file this provider reads.

    Copied rather than edited in place, because the alternative is a test
    that mutates the repository it is testing.
    """
    root = destination / "checkout"
    target = root / CONFIG_SOURCE
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / CONFIG_SOURCE, target)
    return root


def _synthetic(destination: Path, body: str) -> Path:
    """A checkout whose ``config.py`` is exactly ``body``.

    The refusals are proved here rather than against a mutilated copy of
    the real file: a synthetic registry says in six lines what shape is
    being refused, and a reader of a failure can see it whole.
    """
    root = destination / "synthetic"
    target = root / CONFIG_SOURCE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return root


_ENUM = (
    "from enum import Enum\n"
    "\n"
    "\n"
    f"class {MODE_ENUM}(Enum):\n"
    '    MIGRATION = "migration"\n'
    '    DEV = "dev"\n'
    '    STRICT = "strict"\n'
    '    RELEASE = "release"\n'
    "\n"
    "\n"
)


def _registry(matrix: str, out_of_matrix: str = "()", descriptions: str = "{}") -> str:
    """A whole synthetic ``config.py``: the enum and the three registries."""
    return (
        _ENUM
        + f"{MATRIX_NAME} = {matrix}\n"
        + f"{OUT_OF_MATRIX_NAME} = {out_of_matrix}\n"
        + f"{DESCRIPTIONS_NAME} = {descriptions}\n"
    )


_ONE_CODE = _registry(
    matrix='{"PARSE_ERROR": dict.fromkeys(StrictnessMode, "error")}',
    descriptions='{"PARSE_ERROR": "It did not parse."}',
)


# ---------------------------------------------------------------------------
# The contract every provider is held to
# ---------------------------------------------------------------------------


class TestProviderContract:
    """Architecture plan §7.1, at the points it is checkable."""

    def test_the_result_is_stamped_with_this_provider(self, live: ProviderResult) -> None:
        assert live.provider_id == PROVIDER_ID
        assert all(item.provenance.adapter_id == PROVIDER_ID for item in live.records)

    def test_every_record_names_the_schema_it_was_emitted_against(
        self, live: ProviderResult
    ) -> None:
        assert {item.provenance.schema_version for item in live.records} == {SCHEMA}

    def test_the_records_come_back_sorted(self, live: ProviderResult) -> None:
        assert list(live.records) == sorted(live.records, key=record_key)

    def test_every_id_is_valid_and_claimed_once(self, live: ProviderResult) -> None:
        ids = [record.id for record in _surfaces(live)]
        for identifier in ids:
            assert validate_id(identifier) == "diagnostic"
        assert len(ids) == len(set(ids))

    def test_every_record_is_served_on_the_diagnostic_channel(
        self, live: ProviderResult
    ) -> None:
        assert {record.channel for record in _surfaces(live)} == {CHANNEL}

    def test_the_served_name_is_the_code_the_registry_spells(
        self, live: ProviderResult
    ) -> None:
        for record in _surfaces(live):
            assert record.id == f"diagnostic:{record.public_name}"

    def test_one_file_digest_is_shared_by_every_record(self, live: ProviderResult) -> None:
        """One file, read once, so no two records can disagree about it."""
        digests = {item.provenance.source_sha256 for item in live.records}
        sources = {item.provenance.source for item in live.records}
        assert sources == {CONFIG_SOURCE}
        assert len(digests) == 1
        text = (REPO_ROOT / CONFIG_SOURCE).read_text(encoding="utf-8")
        expected = hashlib.sha256(
            text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        ).hexdigest()
        assert digests == {expected}
        assert len(expected) == 64

    def test_calling_twice_gives_the_same_records(self) -> None:
        provider = DiagnosticsProvider(root=REPO_ROOT)
        assert [item.record for item in provider.provide().records] == [
            item.record for item in provider.provide().records
        ]

    def test_two_providers_on_one_root_agree(self, live: ProviderResult) -> None:
        second = DiagnosticsProvider(root=REPO_ROOT).provide()
        assert [item.record for item in second.records] == [
            item.record for item in live.records
        ]

    def test_no_record_carries_an_absolute_path(self, live: ProviderResult) -> None:
        """INV-5: no artifact embeds an absolute machine path."""
        machine = str(REPO_ROOT)
        for record in _surfaces(live):
            values = (
                record.id,
                record.channel,
                record.public_name,
                record.intent,
                record.manual_exception,
                record.provenance.source,
                *record.errors,
                *record.side_effects,
            )
            for value in values:
                assert machine not in value
                assert not value.startswith("/")
            assert "\\" not in record.provenance.source

    def test_the_module_imports_nothing_it_should_not(self) -> None:
        """Stdlib and this model only — no core, no mcp, no studi0, no spikes.

        The provider reads a file; it needs no runtime at all, and an
        import of the module it describes would make the parity proof a
        tautology.
        """
        forbidden = ("s0ma.", "s0ma_mcp", "s0ma_studi0", "spike_", "scripts.")
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.append(node.module)
        for name in imported:
            assert not name.startswith(forbidden), f"{name} is not this module's to import"
        assert "s0ma_dsl.config" not in imported


# ---------------------------------------------------------------------------
# The fact grammar
# ---------------------------------------------------------------------------


class TestFactGrammar:
    """``<key>=<value>`` entries, written and read only through the pair."""

    def test_facts_are_written_in_sorted_order(self) -> None:
        one = fact_entries({"strict": "error", "dev": "warning"})
        two = fact_entries({"dev": "warning", "strict": "error"})
        assert one == two == ("dev=warning", "strict=error")

    def test_the_facts_read_back(self) -> None:
        written = fact_entries({"registry": MATRIX_REGISTRY, "release": "error"})
        assert fact_map(written) == {
            REGISTRY_KEY: MATRIX_REGISTRY,
            "release": "error",
        }

    def test_a_value_may_be_empty_and_still_read_back(self) -> None:
        assert fact_map(fact_entries({"note": ""})) == {"note": ""}

    @pytest.mark.parametrize("key", ["Registry", "1st", "with space", ""])
    def test_a_key_outside_the_grammar_is_refused(self, key: str) -> None:
        with pytest.raises(DiagnosticsProviderError):
            fact_entries({key: "error"})

    def test_a_value_that_spans_lines_is_refused(self) -> None:
        """A fact is one line so a channel can write it beside its neighbours."""
        with pytest.raises(DiagnosticsProviderError, match="spans lines"):
            fact_entries({"note": "one\ntwo"})

    @pytest.mark.parametrize("entry", ["no-equals-sign", "=orphan", "Registry=matrix"])
    def test_reading_something_that_is_not_a_fact_is_refused(self, entry: str) -> None:
        with pytest.raises(DiagnosticsProviderError):
            fact_map([entry])

    def test_severity_of_answers_none_for_a_mode_the_record_does_not_record(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        """``None`` is not the same fact as ``not_applicable``."""
        out_of_matrix = index[f"diagnostic:{OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE[0]}"]
        assert severity_of(out_of_matrix, "release") is None
        release_only = index["diagnostic:MISSING_PUBLIC_DOC_REF"]
        assert severity_of(release_only, "strict") == NOT_APPLICABLE
        assert severity_of(release_only, "release") == "error"

    @pytest.mark.parametrize("code", ["parse_error", "1_BAD", "PARSE-ERROR", ""])
    def test_a_code_that_is_not_a_code_is_refused(self, code: str) -> None:
        with pytest.raises(DiagnosticsProviderError):
            diagnostic_id(code)

    def test_summary_line_collapses_the_layout_of_the_source(self) -> None:
        assert summary_line("one\n  two   three\n") == "one two three"


# ---------------------------------------------------------------------------
# Parity with the live registries
# ---------------------------------------------------------------------------


class TestTheRegistriesAreReadWhole:
    """Plan §9 D2 T1: every code, its severities, its description."""

    def test_the_record_set_is_exactly_the_two_registries(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        assert set(index) == {f"diagnostic:{code}" for code in _live_codes()}

    def test_the_severity_of_every_matrix_code_matches_the_matrix(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        """The parity proof, run mode by mode over every registered code."""
        for code, ladder in SEVERITY_MATRIX.items():
            record = index[f"diagnostic:{code}"]
            facts = fact_map(record.errors)
            assert facts[REGISTRY_KEY] == MATRIX_REGISTRY
            for mode in StrictnessMode:
                expected = ladder[mode]
                written = NOT_APPLICABLE if expected is None else expected
                assert facts[mode.value] == written, code
            assert set(facts) == {*MODES, REGISTRY_KEY}

    def test_an_out_of_matrix_code_records_no_ladder_and_says_why(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        for code in OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE:
            facts = fact_map(index[f"diagnostic:{code}"].errors)
            assert facts == {REGISTRY_KEY: OUT_OF_MATRIX_REGISTRY}

    def test_the_two_registries_partition_the_codes(self) -> None:
        """What the provider refuses to see; asserted of the live file too."""
        assert not set(SEVERITY_MATRIX) & set(
            OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE
        )

    def test_every_intent_is_the_registered_description(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        for code in _live_codes():
            record = index[f"diagnostic:{code}"]
            assert record.intent == summary_line(ERROR_CODE_DESCRIPTIONS[code])
            assert record.intent

    def test_the_mode_vocabulary_comes_from_the_enum(self) -> None:
        assert DiagnosticsProvider(root=REPO_ROOT).modes() == MODES

    def test_every_code_is_bound_or_says_why_it_is_not(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        """C2's binding rule, and the reason is the same one for all of them."""
        for record in index.values():
            assert record.component_refs == ()
            assert record.manual_exception == UNBOUND_EXCEPTION
        assert "milestone that completes every surface's binding" in UNBOUND_EXCEPTION

    def test_a_diagnostic_changes_nothing(self, index: Mapping[str, SurfaceRecord]) -> None:
        assert {record.side_effects for record in index.values()} == {("none",)}

    def test_no_authority_is_cited_and_that_is_deliberate(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        """A section is not an addressable authority id in this model."""
        assert {record.governed_by for record in index.values()} == {()}


# ---------------------------------------------------------------------------
# Derived, not copied
# ---------------------------------------------------------------------------


class TestSeverityIsDerivedNotCopied:
    """Plan §9 D2 acceptance: a matrix edit flips the provider."""

    @pytest.fixture()
    def checkout(self, tmp_path: Path) -> Path:
        return _copy_config(tmp_path)

    def test_a_copy_reads_the_same_as_the_original(
        self, checkout: Path, live: ProviderResult
    ) -> None:
        """The control. Without it, the flip below could pass for other reasons."""
        assert _by_id(DiagnosticsProvider(root=checkout).provide()) == _by_id(live)

    def test_changing_one_severity_changes_exactly_that_record(
        self, checkout: Path
    ) -> None:
        before = _by_id(DiagnosticsProvider(root=checkout).provide())
        source = checkout / CONFIG_SOURCE
        text = source.read_text(encoding="utf-8")
        target = '"BARE_IMPORT": {\n        StrictnessMode.MIGRATION: "warning",'
        assert target in text
        source.write_text(
            text.replace(
                target, '"BARE_IMPORT": {\n        StrictnessMode.MIGRATION: "error",', 1
            ),
            encoding="utf-8",
        )
        after = _by_id(DiagnosticsProvider(root=checkout).provide())

        assert before.keys() == after.keys()
        moved = sorted(
            key for key in before if before[key].errors != after[key].errors
        )
        assert moved == ["diagnostic:BARE_IMPORT"]
        assert severity_of(before["diagnostic:BARE_IMPORT"], "migration") == "warning"
        assert severity_of(after["diagnostic:BARE_IMPORT"], "migration") == "error"

    def test_adding_a_code_adds_a_record(self, checkout: Path) -> None:
        before = _by_id(DiagnosticsProvider(root=checkout).provide())
        source = checkout / CONFIG_SOURCE
        text = source.read_text(encoding="utf-8")
        source.write_text(
            text.replace(
                '    "PARSE_ERROR":          dict.fromkeys(StrictnessMode, "error"),',
                '    "PARSE_ERROR":          dict.fromkeys(StrictnessMode, "error"),\n'
                '    "INVENTED_CODE": dict.fromkeys(StrictnessMode, "warning"),',
                1,
            ).replace(
                '    "PARSE_ERROR": "Source file failed to parse as a valid .s0ma module.",',
                '    "PARSE_ERROR": "Source file failed to parse as a valid .s0ma module.",\n'
                '    "INVENTED_CODE": "Something this tree invented.",',
                1,
            ),
            encoding="utf-8",
        )
        after = _by_id(DiagnosticsProvider(root=checkout).provide())

        assert sorted(set(after) - set(before)) == ["diagnostic:INVENTED_CODE"]
        record = after["diagnostic:INVENTED_CODE"]
        assert record.intent == "Something this tree invented."
        assert severity_of(record, "release") == "warning"

    def test_removing_a_code_removes_its_record(self, checkout: Path) -> None:
        before = _by_id(DiagnosticsProvider(root=checkout).provide())
        source = checkout / CONFIG_SOURCE
        text = source.read_text(encoding="utf-8")
        assert '    "ADOPTED_CHURN",\n' in text
        source.write_text(text.replace('    "ADOPTED_CHURN",\n', "", 1), encoding="utf-8")
        after = _by_id(DiagnosticsProvider(root=checkout).provide())

        assert sorted(set(before) - set(after)) == ["diagnostic:ADOPTED_CHURN"]

    def test_a_new_mode_arrives_without_an_edit_here(self, tmp_path: Path) -> None:
        """The ladder's vocabulary is the enum's, not this module's."""
        body = _ENUM.replace(
            '    RELEASE = "release"\n', '    RELEASE = "release"\n    AUDIT = "audit"\n'
        ) + (
            f'{MATRIX_NAME} = {{"PARSE_ERROR": dict.fromkeys(StrictnessMode, "error")}}\n'
            f"{OUT_OF_MATRIX_NAME} = ()\n"
            f'{DESCRIPTIONS_NAME} = {{"PARSE_ERROR": "It did not parse."}}\n'
        )
        root = _synthetic(tmp_path, body)
        provider = DiagnosticsProvider(root=root)
        assert provider.modes() == ("migration", "dev", "strict", "release", "audit")
        record = _by_id(provider.provide())["diagnostic:PARSE_ERROR"]
        assert severity_of(record, "audit") == "error"

    def test_a_comment_restamps_every_record_and_changes_no_fact(
        self, checkout: Path
    ) -> None:
        """One file, one digest: an edit anywhere re-stamps all of them.

        The honest unit is the file, not a byte range around one entry, so
        an unrelated comment moves every record's provenance and none of
        their facts. That is the intended behaviour, and asserting it here
        is what makes the flip tests above mean something narrower.
        """
        before = DiagnosticsProvider(root=checkout).provide()
        source = checkout / CONFIG_SOURCE
        source.write_text(
            source.read_text(encoding="utf-8") + "\n# A later edit.\n", encoding="utf-8"
        )
        after = DiagnosticsProvider(root=checkout).provide()

        assert before.sources() != after.sources()
        assert len({item.provenance.source_sha256 for item in after.records}) == 1
        stripped_before = {
            item.record.id: item.record.errors for item in before.records
        }
        stripped_after = {item.record.id: item.record.errors for item in after.records}
        assert stripped_before == stripped_after


# ---------------------------------------------------------------------------
# The codes the milestone names
# ---------------------------------------------------------------------------


class TestNamedDiagnostics:
    """Plan §9 D2 acceptance: the release-only shape, and A8's validation."""

    @pytest.mark.parametrize(
        "code", ["MISSING_PUBLIC_DOC_REF", "MISSING_EMBEDDED_EXAMPLE"]
    )
    def test_a_release_only_check_says_it_does_not_run_in_the_other_three(
        self, index: Mapping[str, SurfaceRecord], code: str
    ) -> None:
        record = index[f"diagnostic:{code}"]
        assert severity_of(record, "release") == "error"
        for mode in ("migration", "dev", "strict"):
            assert severity_of(record, mode) == NOT_APPLICABLE

    def test_the_release_only_shape_is_not_confused_with_a_warning(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        """``not_applicable`` and ``warning`` are different answers."""
        laddered = index["diagnostic:CROSS_LAYER_DEPENDENCY"]
        assert severity_of(laddered, "migration") == "warning"
        assert severity_of(laddered, "release") == "error"
        assert NOT_APPLICABLE not in laddered.errors

    def test_a8s_runs_in_validation_is_addressed(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        """A8's parse-time ``runs_in`` check fires ``PARSE_ERROR``.

        A8.T2 validated an existing field's value against the dispatcher's
        real mode set and reused the code the parser already raises rather
        than minting a new one, so the deep link a bad ``runs_in`` produces
        lands on this record. Asserted against the parser's own emit site
        so a future milestone that mints a dedicated code turns this red
        rather than leaving the link pointing at the wrong page.
        """
        record = index["diagnostic:PARSE_ERROR"]
        for mode in MODES:
            assert severity_of(record, mode) == "error"

        parser = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "s0ma_dsl"
            / "parser"
            / "s0ma_parser.py"
        )
        text = parser.read_text(encoding="utf-8")
        modes = '("standalone", "pytest", "integration")'
        assert f"VALID_EXAMPLE_RUNS_IN: tuple[str, ...] = {modes}" in text
        assert "has invalid runs_in" in text
        marker = text.index("has invalid runs_in")
        opening = text.rindex("raise S0maParseError(", 0, marker)
        assert 'code="PARSE_ERROR"' in text[opening:marker]

    def test_every_code_the_parser_and_validator_raise_is_addressed(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        """The completeness claim, checked against the live registries.

        ``config.py``'s own meta-test pins every code literal in the
        package to one of the two registries; this asserts the other half
        — that the documentation addresses every code those registries
        hold, so no registered code is a topic nobody can ask for.
        """
        assert {record.public_name for record in index.values()} == _live_codes()


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


class TestRefusals:
    """A shape this reader does not know stops the build, by name."""

    def test_a_tree_without_the_file_is_refused(self, tmp_path: Path) -> None:
        """Absence is not empty here: this package owns that file."""
        with pytest.raises(DiagnosticsProviderError, match="not in this tree"):
            DiagnosticsProvider(root=tmp_path).provide()

    def test_a_file_that_does_not_parse_is_refused(self, tmp_path: Path) -> None:
        root = _synthetic(tmp_path, "def (:\n")
        with pytest.raises(DiagnosticsProviderError, match="does not parse"):
            DiagnosticsProvider(root=root).provide()

    @pytest.mark.parametrize(
        "name", [MATRIX_NAME, OUT_OF_MATRIX_NAME, DESCRIPTIONS_NAME]
    )
    def test_a_renamed_registry_is_refused_by_name(
        self, tmp_path: Path, name: str
    ) -> None:
        body = _ONE_CODE.replace(f"{name} = ", f"{name}_RENAMED = ", 1)
        root = _synthetic(tmp_path, body)
        with pytest.raises(DiagnosticsProviderError, match=name):
            DiagnosticsProvider(root=root).provide()

    def test_a_missing_mode_enum_is_refused(self, tmp_path: Path) -> None:
        body = _ONE_CODE.replace(f"class {MODE_ENUM}(Enum):", "class Other(Enum):", 1)
        root = _synthetic(tmp_path, body)
        with pytest.raises(DiagnosticsProviderError, match=MODE_ENUM):
            DiagnosticsProvider(root=root).provide()

    def test_a_value_shape_this_reader_does_not_know_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The failure the refusal exists for: a code that would vanish."""
        root = _synthetic(
            tmp_path,
            _registry(
                matrix='{"PARSE_ERROR": severities_for("PARSE_ERROR")}',
                descriptions='{"PARSE_ERROR": "It did not parse."}',
            ),
        )
        with pytest.raises(DiagnosticsProviderError, match="PARSE_ERROR"):
            DiagnosticsProvider(root=root).provide()

    def test_a_ladder_over_some_other_set_is_refused(self, tmp_path: Path) -> None:
        root = _synthetic(
            tmp_path,
            _registry(
                matrix='{"PARSE_ERROR": dict.fromkeys(SomethingElse, "error")}',
                descriptions='{"PARSE_ERROR": "It did not parse."}',
            ),
        )
        with pytest.raises(DiagnosticsProviderError, match="SomethingElse"):
            DiagnosticsProvider(root=root).provide()

    def test_a_ladder_missing_a_mode_is_refused(self, tmp_path: Path) -> None:
        root = _synthetic(
            tmp_path,
            _registry(
                matrix=(
                    '{"PARSE_ERROR": {StrictnessMode.MIGRATION: "warning", '
                    'StrictnessMode.DEV: "warning"}}'
                ),
                descriptions='{"PARSE_ERROR": "It did not parse."}',
            ),
        )
        with pytest.raises(DiagnosticsProviderError, match="strict"):
            DiagnosticsProvider(root=root).provide()

    def test_a_ladder_keyed_on_something_that_is_not_a_mode_is_refused(
        self, tmp_path: Path
    ) -> None:
        root = _synthetic(
            tmp_path,
            _registry(
                matrix='{"PARSE_ERROR": {StrictnessMode.NOWHERE: "error"}}',
                descriptions='{"PARSE_ERROR": "It did not parse."}',
            ),
        )
        with pytest.raises(DiagnosticsProviderError, match="NOWHERE"):
            DiagnosticsProvider(root=root).provide()

    def test_a_code_in_both_registries_is_refused(self, tmp_path: Path) -> None:
        root = _synthetic(
            tmp_path,
            _registry(
                matrix='{"PARSE_ERROR": dict.fromkeys(StrictnessMode, "error")}',
                out_of_matrix='("PARSE_ERROR",)',
                descriptions='{"PARSE_ERROR": "It did not parse."}',
            ),
        )
        with pytest.raises(DiagnosticsProviderError, match="both"):
            DiagnosticsProvider(root=root).provide()

    def test_a_code_with_no_description_is_refused(self, tmp_path: Path) -> None:
        root = _synthetic(
            tmp_path,
            _registry(matrix='{"PARSE_ERROR": dict.fromkeys(StrictnessMode, "error")}'),
        )
        with pytest.raises(DiagnosticsProviderError, match="PARSE_ERROR"):
            DiagnosticsProvider(root=root).provide()

    def test_an_empty_matrix_is_refused(self, tmp_path: Path) -> None:
        """A registry that reads empty passes every count downstream of it."""
        root = _synthetic(tmp_path, _registry(matrix="{}"))
        with pytest.raises(DiagnosticsProviderError, match="empty"):
            DiagnosticsProvider(root=root).provide()

    def test_a_computed_registry_entry_is_refused(self, tmp_path: Path) -> None:
        root = _synthetic(
            tmp_path,
            _registry(
                matrix='{**INHERITED, "PARSE_ERROR": dict.fromkeys(StrictnessMode, "error")}',
                descriptions='{"PARSE_ERROR": "It did not parse."}',
            ),
        )
        with pytest.raises(DiagnosticsProviderError, match="unpacks"):
            DiagnosticsProvider(root=root).provide()

    def test_a_code_registered_twice_is_refused(self, tmp_path: Path) -> None:
        root = _synthetic(
            tmp_path,
            _registry(
                matrix=(
                    '{"PARSE_ERROR": dict.fromkeys(StrictnessMode, "error"), '
                    '"PARSE_ERROR": dict.fromkeys(StrictnessMode, "warning")}'
                ),
                descriptions='{"PARSE_ERROR": "It did not parse."}',
            ),
        )
        with pytest.raises(DiagnosticsProviderError, match="twice"):
            DiagnosticsProvider(root=root).provide()


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


class TestComposition:
    """Plan §9 D2 T4: it composes clean, byte-stable, on an honest floor."""

    def test_the_records_pass_every_gate_with_no_findings(self) -> None:
        composed = compose(
            ProviderRegistry.of(DiagnosticsProvider(root=REPO_ROOT)),
            release_version=RELEASE,
        )
        assert composed.findings == ()
        assert (
            validate_bundle(
                composed.bundle,
                results=composed.results,
                external_ids=(),
                floors=dict(DIAGNOSTIC_FLOORS),
                claims=(),
            )
            == ()
        )

    def test_the_floor_this_module_publishes_is_met_and_is_not_a_pin(self) -> None:
        counted = DiagnosticsProvider(root=REPO_ROOT).provide().counts()["surfaces"]
        floor = DIAGNOSTIC_FLOORS[(PROVIDER_ID, "surfaces")]
        assert counted >= floor
        assert floor < counted

    def test_a_provider_that_stopped_seeing_its_source_trips_the_floor(
        self, tmp_path: Path
    ) -> None:
        """The failure the floor exists for, made to happen."""
        root = _synthetic(tmp_path, _ONE_CODE)
        result = DiagnosticsProvider(root=root).provide()
        findings = check_floors([result], dict(DIAGNOSTIC_FLOORS))
        assert [finding.code for finding in findings] == ["DOC_GATE_VACUOUS"]

    def test_the_bundle_is_byte_stable(self) -> None:
        first = compose(
            ProviderRegistry.of(DiagnosticsProvider(root=REPO_ROOT)),
            release_version=RELEASE,
        )
        second = compose(
            ProviderRegistry.of(DiagnosticsProvider(root=REPO_ROOT)),
            release_version=RELEASE,
        )
        assert serialize_bundle(first.bundle) == serialize_bundle(second.bundle)
        assert first.bundle.stamp.snapshot_hash == second.bundle.stamp.snapshot_hash

    def test_the_snapshot_moves_when_the_source_moves(self, tmp_path: Path) -> None:
        checkout = _copy_config(tmp_path)
        before = compose(
            ProviderRegistry.of(DiagnosticsProvider(root=checkout)),
            release_version=RELEASE,
        ).bundle.stamp.snapshot_hash
        source = checkout / CONFIG_SOURCE
        source.write_text(
            source.read_text(encoding="utf-8").replace(
                '"PARSE_ERROR":          dict.fromkeys(StrictnessMode, "error")',
                '"PARSE_ERROR":          dict.fromkeys(StrictnessMode, "warning")',
                1,
            ),
            encoding="utf-8",
        )
        after = compose(
            ProviderRegistry.of(DiagnosticsProvider(root=checkout)),
            release_version=RELEASE,
        ).bundle.stamp.snapshot_hash
        assert before != after

    def test_every_diagnostic_can_be_asked_for_and_shown(self) -> None:
        """The coverage question, over the real reader channels."""
        composed = compose(
            ProviderRegistry.of(DiagnosticsProvider(root=REPO_ROOT)),
            release_version=RELEASE,
        )
        assert (
            check_coverage(
                composed.bundle,
                renderers={"human": render_human, "agent": render_agent},
            )
            == []
        )

    def test_a_diagnostic_resolves_by_its_code_as_well_as_by_its_id(self) -> None:
        """What a failing build hands a reader: the code it just printed."""
        composed = compose(
            ProviderRegistry.of(DiagnosticsProvider(root=REPO_ROOT)),
            release_version=RELEASE,
        )
        served = TopicIndex.of(composed.bundle)
        assert resolve(served, "diagnostic:BARE_IMPORT").topic is not None
        by_name = resolve(served, "BARE_IMPORT")
        assert by_name.topic is not None
        assert by_name.topic.id == "diagnostic:BARE_IMPORT"

    def test_no_description_exceeds_the_agent_budget(self) -> None:
        """A fact about ``config.py``'s prose, pinned rather than papered over.

        The record quotes the description word for word — a bounded channel
        gets smaller by omitting, never by paraphrasing — so a description
        that does not fit is a description to shorten in ``config.py``, not
        something this provider may trim. D2 found three that did not fit
        and could not shorten them; D5a shortened them at the source, so
        this set is empty. It is still asserted exactly: a description that
        grows past the budget turns this red, which is the signal to
        shorten it rather than to widen the channel.
        """
        composed = compose(
            ProviderRegistry.of(DiagnosticsProvider(root=REPO_ROOT)),
            release_version=RELEASE,
        )
        oversized = set()
        for record in composed.bundle.surfaces:
            view = facts_of(composed.bundle, record)
            if check_budget(view, render_agent(view)):
                oversized.add(record.id)
        assert oversized == set(OVERSIZED_TODAY)
        assert AGENT_BYTE_BUDGET > 0

    def test_the_three_shortened_descriptions_still_say_what_fires_them(self) -> None:
        """D5a shortened for the budget, not for brevity's own sake.

        Each of the three keeps the two things a person reading a failing
        build needs: what tripped it, and what to write instead. Asserted
        on the live descriptions so a later trim that drops the remedy is
        caught here rather than in a support thread.
        """
        from s0ma_dsl.config import ERROR_CODE_DESCRIPTIONS

        expected = {
            "BARE_IMPORT": ("bare `import` statement", "delete the import line"),
            "MODULE_NAME_COLLISION": ("declare the same `module <name>`", "Rename one"),
            "CONSUMES_VIA_DICT_INVALID": (
                "resolves to no known",
                "declare the contract",
            ),
        }
        for code, (trigger, remedy) in expected.items():
            description = ERROR_CODE_DESCRIPTIONS[code]
            assert trigger in description, code
            assert remedy in description, code
            assert len(description.encode("utf-8")) <= 400, code


class TestTheApplicationAcceptsIt:
    """Plan §9 D2 T4, now that D5b has wired it in.

    D2 wrote this class to prove its provider *would* fit the application:
    it registered one beside the C phase's five and asserted nothing got
    worse. D5b registered it for real, so the conditional is gone and the
    claims are made directly of the composition the repository builds.
    That is a stronger form of the same three claims, not a weaker one —
    "it would compose clean" has become "it does".
    """

    def test_the_application_registers_it(self) -> None:
        assert PROVIDER_ID in set(application.registry(REPO_ROOT).ids())

    def test_the_composed_build_reports_no_finding(self) -> None:
        built = application.build(REPO_ROOT, version=RELEASE)
        assert [finding.rendered() for finding in built.findings] == []

    def test_the_diagnostics_reach_the_composed_bundle(self) -> None:
        built = application.build(REPO_ROOT, version=RELEASE)
        served = {
            record.id for record in built.bundle.surfaces if record.channel == CHANNEL
        }
        assert served == {f"diagnostic:{code}" for code in _live_codes()}

    def test_this_provider_is_the_only_claimant_of_the_id_space(self) -> None:
        """The merge rule's precondition, asked the way D5b can ask it.

        D2 could only show the space was unoccupied. Now that it is
        occupied, the useful question is whether anything *else* reaches
        into it: two providers emitting one id with different facts is a
        build error, and one emitting identical facts merges silently.
        Reading the provenance of every ``diagnostic:`` record answers
        both — every one of them was stamped by this adapter.
        """
        built = application.build(REPO_ROOT, version=RELEASE)
        claimed = [
            record
            for record in built.bundle.surfaces
            if id_form(record.id) == "diagnostic"
        ]
        assert claimed
        assert {record.provenance.adapter_id for record in claimed} == {PROVIDER_ID}
