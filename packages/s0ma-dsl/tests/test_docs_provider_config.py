"""Gates for D2 — the ``[tool.s0ma]`` configuration provider.

Milestone D2 of the docs-function plan (internal) §9, over
``s0ma_dsl.docs_model.providers_config``. What these tests hold in place:

* **every key an author may write is addressed.** The record set is
  exactly the set of keys the project loader reads, cross-checked against
  the live :class:`~s0ma_dsl.project.S0maProject` so a key added to one
  and not the other turns this red.
* **the defaults are the product's.** Twelve of the nineteen keys have a
  default whose authored form and resolved form are the same value, and
  every one of them is compared against a project loaded from an empty
  table. The other seven are the keys whose authored form is a list of
  relative paths and whose resolved form is a tuple of absolute ones; the
  record documents what an author writes, and that split is pinned here
  rather than left to be discovered.
* **derived, not copied.** Proved against a copied tree: remove a key
  from the loader and its record goes; change a default constant and the
  fact follows it.
* **the citations cannot go stale quietly.** Both hand-written tables —
  which constant holds a key's accepted values, and which rule governs a
  key — refuse the build when what they cite has left ``project.py``, and
  a closed value set that no key cites refuses it too.
* **``docs_output_dir`` is still absent.** C8 ruled against adopting it;
  this is the second place that ruling is visible, and it fails if the key
  arrives without the documentation following.
* **the id form landed, and the local matcher is gone.** ``config:`` is
  in ``ids.ID_FORMS`` (D5a), so the proof below asserts the form is
  present and that this provider validates through it rather than
  through a regular expression of its own.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.docs_model import application
from s0ma_dsl.docs_model.compose import compose
from s0ma_dsl.docs_model.ids import ID_CLASSES, DocsIdError, id_form, validate_id
from s0ma_dsl.docs_model.providers import (
    ProviderRegistry,
    ProviderResult,
    record_key,
)
from s0ma_dsl.docs_model.providers_config import (
    CHANNEL,
    COMPUTED,
    CONFIG_FLOORS,
    LOADER,
    MODEL_CLASS,
    PROJECT_SOURCE,
    PROVIDER_ID,
    RULES,
    TABLE,
    UNBOUND_EXCEPTION,
    UNSTATED,
    VALUE_SETS,
    ConfigProvider,
    ConfigProviderError,
    config_id,
)
from s0ma_dsl.docs_model.providers_diagnostics import (
    DIAGNOSTIC_FLOORS,
    DiagnosticsProvider,
    fact_map,
)
from s0ma_dsl.docs_model.providers_diagnostics import PROVIDER_ID as DIAGNOSTICS_PROVIDER_ID
from s0ma_dsl.docs_model.records import SCHEMA, SurfaceRecord
from s0ma_dsl.docs_model.render_agent import check_budget, render_agent
from s0ma_dsl.docs_model.render_human import render_human
from s0ma_dsl.docs_model.resolve import check_coverage, facts_of
from s0ma_dsl.docs_model.serialize import serialize_bundle
from s0ma_dsl.docs_model.validate import check_floors, validate_bundle
from s0ma_dsl.project import (
    SUPPORTED_ATTRIBUTE_BUDGETS,
    SUPPORTED_AUTHORING,
    SUPPORTED_FIXTURE_FORMATS,
    SUPPORTED_PROJECT_MODES,
    SUPPORTED_TEST_LAYERINGS,
    SUPPORTED_TEST_RUNNERS,
    S0maProject,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "s0ma_dsl"
    / "docs_model"
    / "providers_config.py"
)

RELEASE = "0.18.1"

#: Fields of :class:`~s0ma_dsl.project.S0maProject` that are *not* keys an
#: author writes under ``[tool.s0ma]``. Written here rather than derived,
#: because this is the canary: the provider derives its key set from the
#: loader, and this list is the independent second opinion it is checked
#: against. A field that stops being a table key has to be added here, and
#: a field that starts being one has to be removed.
NOT_TABLE_KEYS = frozenset(
    {
        "root",  # discovery's answer, not an authored value
        "project_name",  # [project].name
        "requires_python",  # [project].requires-python, a PEP 621 field
        "synthetic",  # a fact about how the project was built
        "warnings",  # produced during discovery
    }
)

#: The keys whose authored default and whose resolved default are the same
#: value, so a record's ``default`` fact can be compared straight against a
#: project loaded from an empty table.
DIRECTLY_COMPARABLE = (
    "attribute_budgets",
    "authoring",
    "env",
    "fixtures_format",
    "health_command",
    "mode",
    "run_command",
    "runbook_notes",
    "test_layering",
    "test_module_name_prefix_by_dir",
    "test_runner",
    "venv_path",
)

#: The keys whose authored form differs from their resolved form: a TOML
#: list of relative paths becomes a tuple of absolute ones, and
#: ``build_dir`` is computed from the project name. The record documents
#: what an author writes, which is why these are not compared above.
RESOLVED_DIFFERENTLY = (
    "adoption_exempt",
    "bootstrap_files",
    "build_dir",
    "package_markers",
    "source_roots",
    "state_paths",
    "test_roots",
)

#: Every closed value set, live, keyed by the key that is validated against
#: it. The provider reads these out of the file; this is the independent
#: reading the records are checked against.
LIVE_VALUE_SETS: Mapping[str, frozenset[str]] = {
    "attribute_budgets": SUPPORTED_ATTRIBUTE_BUDGETS,
    "authoring": SUPPORTED_AUTHORING,
    "fixtures_format": SUPPORTED_FIXTURE_FORMATS,
    "mode": SUPPORTED_PROJECT_MODES,
    "test_layering": SUPPORTED_TEST_LAYERINGS,
    "test_runner": SUPPORTED_TEST_RUNNERS,
}


def _surfaces(result: ProviderResult) -> tuple[SurfaceRecord, ...]:
    """The result's records, typed. A configuration record is a surface."""
    found: list[SurfaceRecord] = []
    for item in result.records:
        assert isinstance(item.record, SurfaceRecord), (
            f"{item.record.id} is a {type(item.record).__name__}; this "
            f"provider emits served capabilities and nothing else"
        )
        found.append(item.record)
    return tuple(found)


def _by_key(result: ProviderResult) -> dict[str, SurfaceRecord]:
    """The records keyed by the ``[tool.s0ma]`` key each one addresses."""
    return {record.id.partition(":")[2]: record for record in _surfaces(result)}


def _live_keys() -> frozenset[str]:
    """Every table key, read off the resolved-project dataclass."""
    return frozenset(
        field.name
        for field in dataclasses.fields(S0maProject)
        if field.name not in NOT_TABLE_KEYS
    )


@pytest.fixture(scope="module")
def live() -> ProviderResult:
    """The provider's reading of this checkout, done once."""
    return ConfigProvider(root=REPO_ROOT).provide()


@pytest.fixture(scope="module")
def index(live: ProviderResult) -> dict[str, SurfaceRecord]:
    return _by_key(live)


@pytest.fixture(scope="module")
def defaults() -> S0maProject:
    """A project loaded from an empty table: every default, resolved."""
    return S0maProject._from_tool_s0ma(
        root=Path("/anywhere"), project_name="demo", table={}
    )


def _copy_project(destination: Path) -> Path:
    """A checkout holding only the file this provider reads."""
    root = destination / "checkout"
    target = root / PROJECT_SOURCE
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / PROJECT_SOURCE, target)
    return root


def _rewrite(root: Path, before: str, after: str) -> None:
    """Replace the first ``before`` with ``after`` in the copy's loader.

    The assertion is load-bearing: a rewrite whose target has moved would
    otherwise leave the file unchanged and the proof would pass by having
    changed nothing.
    """
    source = root / PROJECT_SOURCE
    text = source.read_text(encoding="utf-8")
    assert before in text, f"{before!r} is no longer in {PROJECT_SOURCE}"
    source.write_text(text.replace(before, after, 1), encoding="utf-8")


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

    def test_every_record_is_served_on_the_config_channel(
        self, live: ProviderResult
    ) -> None:
        assert {record.channel for record in _surfaces(live)} == {CHANNEL}

    def test_the_served_name_is_what_an_author_writes(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        for key, record in index.items():
            assert record.public_name == f"{TABLE}.{key}"

    def test_one_file_digest_is_shared_by_every_record(self, live: ProviderResult) -> None:
        digests = {item.provenance.source_sha256 for item in live.records}
        assert {item.provenance.source for item in live.records} == {PROJECT_SOURCE}
        text = (REPO_ROOT / PROJECT_SOURCE).read_text(encoding="utf-8")
        expected = hashlib.sha256(
            text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        ).hexdigest()
        assert digests == {expected}
        assert len(expected) == 64

    def test_calling_twice_gives_the_same_records(self) -> None:
        provider = ConfigProvider(root=REPO_ROOT)
        assert [item.record for item in provider.provide().records] == [
            item.record for item in provider.provide().records
        ]

    def test_no_record_carries_an_absolute_path(self, live: ProviderResult) -> None:
        """INV-5: no artifact embeds an absolute machine path."""
        machine = str(REPO_ROOT)
        for record in _surfaces(live):
            values = (
                record.id,
                record.public_name,
                record.intent,
                record.manual_exception,
                record.provenance.source,
                *record.errors,
            )
            for value in values:
                assert machine not in value
                assert not value.startswith("/")
            assert "\\" not in record.provenance.source

    def test_the_module_imports_nothing_it_should_not(self) -> None:
        """Stdlib and this model only, and never the module it describes."""
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
        assert "s0ma_dsl.project" not in imported


# ---------------------------------------------------------------------------
# The id form
# ---------------------------------------------------------------------------


class TestTheIdFormLanded:
    """D2's escalation, answered by D5a and pinned from the other side.

    This class used to assert that ``config:`` matched no form and that
    this provider matched it locally. D5a added the form to
    ``ids.ID_FORMS``, which is what D2's proof was waiting for, so the
    same three questions are now asked as presence: the form is in the
    table, the provider has no matcher of its own, and a key outside the
    form is refused by the *model's* error rather than by this adapter's.
    """

    def test_the_model_addresses_a_configuration_key(self) -> None:
        assert id_form("config:build_dir") == "config"
        assert "config" in ID_CLASSES

    def test_the_provider_validates_through_the_model_not_a_local_matcher(
        self,
    ) -> None:
        """The retirement, proved rather than promised.

        ``config_id`` produces exactly what ``validate_id`` accepts, and
        the module carries no compiled pattern that spells the form a
        second time — a local copy is what D2 escalated, and a local copy
        arriving again is what this would catch.
        """
        assert validate_id(config_id("build_dir")) == "config"
        source = MODULE.read_text(encoding="utf-8")
        assert "config:[a-z]" not in source, (
            "providers_config has minted the config: form locally again; "
            "ids.ID_FORMS is the one place the form is spelled"
        )

    def test_every_id_is_the_key_under_one_kind_word(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        for key, record in index.items():
            assert record.id == f"config:{key}"
            assert record.id == record.id.strip()
            assert id_form(record.id) == "config"

    @pytest.mark.parametrize("key", ["Build_Dir", "build-dir", "1st", "", "a b"])
    def test_a_key_outside_the_form_is_refused(self, key: str) -> None:
        """Refused by the model, which is the point of retiring the matcher."""
        with pytest.raises(DocsIdError):
            config_id(key)


# ---------------------------------------------------------------------------
# The key set
# ---------------------------------------------------------------------------


class TestTheKeySetIsTheLoaders:
    """Plan §9 D2 T2: every ``[tool.s0ma]`` key, and nothing else."""

    def test_the_records_are_exactly_the_keys_the_project_model_carries(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        """Two independent readings of one schema, required to agree."""
        assert set(index) == _live_keys()

    def test_the_keys_are_what_the_provider_says_they_are(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        assert ConfigProvider(root=REPO_ROOT).keys() == tuple(sorted(index))

    def test_the_two_split_lists_cover_every_key_once(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        assert not set(DIRECTLY_COMPARABLE) & set(RESOLVED_DIFFERENTLY)
        assert set(DIRECTLY_COMPARABLE) | set(RESOLVED_DIFFERENTLY) == set(index)

    def test_no_key_is_bound_and_every_one_says_why(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        for record in index.values():
            assert record.component_refs == ()
            assert record.manual_exception.startswith(UNBOUND_EXCEPTION)

    def test_a_configuration_key_changes_nothing_on_its_own(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        assert {record.side_effects for record in index.values()} == {("none",)}

    def test_every_record_carries_the_keys_documentation(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        """One sentence, quoted from where the key is declared."""
        for key, record in index.items():
            assert record.intent, key
            assert "\n" not in record.intent
            assert record.intent.endswith((".", "!", "?")), key

    def test_the_documentation_is_the_fields_own_first_sentence(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        assert index["build_dir"].intent == (
            "Absolute directory for transpiled build artifacts."
        )
        assert index["adoption_exempt"].intent == "Project-local adoption classifications."


class TestTheSchemaFacts:
    """Type, default, accepted values, and the rule where there is one."""

    def test_every_record_states_a_type_and_a_default(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        for key, record in index.items():
            facts = fact_map(record.errors)
            assert facts["type"], key
            assert facts["default"], key

    def test_only_the_keys_the_loader_types_by_hand_are_unstated(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        """Honest silence, and exactly where it belongs.

        Three keys are parsed by helpers that name no TOML type in the
        error they would raise, so the provider says so rather than
        transcribing a type by hand. A fourth appearing means a key lost
        its type check, which is worth finding out about.
        """
        unstated = sorted(
            key
            for key, record in index.items()
            if fact_map(record.errors)["type"] == UNSTATED
        )
        assert unstated == ["adoption_exempt", "env", "runbook_notes"]

    def test_the_stated_types_are_the_loaders_own_words(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        types = {key: fact_map(record.errors)["type"] for key, record in index.items()}
        assert types["source_roots"] == "list of strings"
        assert types["build_dir"] == "string"
        assert types["attribute_budgets"] == "table (mapping)"
        assert types["test_module_name_prefix_by_dir"] == "bool"
        assert types["run_command"] == "string"

    def test_a_directly_comparable_default_matches_the_loaded_project(
        self, index: Mapping[str, SurfaceRecord], defaults: S0maProject
    ) -> None:
        """The parity proof: the documented default is the product's."""
        for key in DIRECTLY_COMPARABLE:
            written = fact_map(index[key].errors)["default"]
            assert written == repr(getattr(defaults, key)), key

    def test_build_dir_is_the_one_computed_default(
        self, index: Mapping[str, SurfaceRecord], defaults: S0maProject
    ) -> None:
        assert fact_map(index["build_dir"].errors)["default"] == COMPUTED
        assert defaults.build_dir.name == "demo_build"

    def test_a_path_default_is_documented_as_an_author_writes_it(
        self, index: Mapping[str, SurfaceRecord], defaults: S0maProject
    ) -> None:
        """A TOML list of relative paths; the field holds absolute ones."""
        assert fact_map(index["source_roots"].errors)["default"] == "['src']"
        assert fact_map(index["test_roots"].errors)["default"] == "['tests']"
        # Derived exactly as the product does — ``(root / r).resolve()`` —
        # so the assertion holds on Windows too, where ``resolve()`` prefixes
        # a drive letter to the drive-less ``/anywhere``.
        assert defaults.source_roots == ((Path("/anywhere") / "src").resolve(),)

    def test_every_closed_value_set_is_the_live_one(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        for key, values in LIVE_VALUE_SETS.items():
            written = fact_map(index[key].errors)["values"]
            assert written == ",".join(sorted(values)), key

    def test_only_the_keys_with_a_closed_set_carry_values(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        carrying = sorted(
            key for key, record in index.items() if "values" in fact_map(record.errors)
        )
        assert carrying == sorted(VALUE_SETS)
        assert carrying == sorted(LIVE_VALUE_SETS)

    def test_every_rule_is_named_on_the_record_and_written_in_its_exception(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        for key, rule in RULES.items():
            record = index[key]
            assert fact_map(record.errors)["rule"] == rule.anchor
            assert record.manual_exception.endswith(" ".join(rule.note.split()))

    def test_build_dirs_identifier_rule_is_the_one_the_plan_names(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        """§1.2 fact 5: the last path component is the import token."""
        note = index["build_dir"].manual_exception
        assert "valid Python identifier" in note
        assert "import token" in note
        assert RULES["build_dir"].anchor == "INVALID_PROJECT_NAME_FOR_BUILD_DIR"


class TestTheKeyC8DeclinedToAdd:
    """C8 ruled against ``docs_output_dir``; here is the second witness."""

    def test_the_loader_still_does_not_read_it(
        self, index: Mapping[str, SurfaceRecord]
    ) -> None:
        assert "docs_output_dir" not in index
        assert "docs_output_dir" not in (REPO_ROOT / PROJECT_SOURCE).read_text(
            encoding="utf-8"
        )

    def test_the_project_model_carries_no_such_field(self) -> None:
        assert "docs_output_dir" not in {
            field.name for field in dataclasses.fields(S0maProject)
        }


# ---------------------------------------------------------------------------
# Derived, not copied
# ---------------------------------------------------------------------------


class TestTheSchemaIsDerivedNotCopied:
    """A loader edit flips the provider."""

    @pytest.fixture()
    def checkout(self, tmp_path: Path) -> Path:
        return _copy_project(tmp_path)

    def test_a_copy_reads_the_same_as_the_original(
        self, checkout: Path, live: ProviderResult
    ) -> None:
        assert _by_key(ConfigProvider(root=checkout).provide()) == _by_key(live)

    def test_a_key_the_loader_stops_reading_stops_being_documented(
        self, checkout: Path
    ) -> None:
        before = _by_key(ConfigProvider(root=checkout).provide())
        _rewrite(
            checkout,
            'state_paths_raw = table.get("state_paths", [])',
            "state_paths_raw: list[str] = []",
        )
        _rewrite(checkout, '_ensure_list_of_str("state_paths", state_paths_raw)', "")
        after = _by_key(ConfigProvider(root=checkout).provide())
        assert sorted(set(before) - set(after)) == ["state_paths"]

    def test_a_key_the_loader_starts_reading_starts_being_documented(
        self, checkout: Path
    ) -> None:
        before = _by_key(ConfigProvider(root=checkout).provide())
        _rewrite(
            checkout,
            'test_runner_raw = table.get("test_runner", DEFAULT_TEST_RUNNER)',
            'invented_raw = table.get("invented_key", "a default")\n'
            '        test_runner_raw = table.get("test_runner", DEFAULT_TEST_RUNNER)',
        )
        after = _by_key(ConfigProvider(root=checkout).provide())
        assert sorted(set(after) - set(before)) == ["invented_key"]
        assert fact_map(after["invented_key"].errors)["default"] == "'a default'"

    def test_changing_a_default_constant_changes_the_documented_default(
        self, checkout: Path
    ) -> None:
        before = _by_key(ConfigProvider(root=checkout).provide())
        assert fact_map(before["source_roots"].errors)["default"] == "['src']"
        _rewrite(
            checkout,
            'DEFAULT_SOURCE_ROOTS: tuple[str, ...] = ("src",)',
            'DEFAULT_SOURCE_ROOTS: tuple[str, ...] = ("lib",)',
        )
        after = _by_key(ConfigProvider(root=checkout).provide())
        assert fact_map(after["source_roots"].errors)["default"] == "['lib']"
        moved = sorted(key for key in before if before[key].errors != after[key].errors)
        assert moved == ["source_roots"]

    def test_widening_a_value_set_widens_the_documented_values(
        self, checkout: Path
    ) -> None:
        _rewrite(
            checkout,
            'SUPPORTED_TEST_LAYERINGS: frozenset[str] = frozenset({"strict", "permissive"})',
            'SUPPORTED_TEST_LAYERINGS: frozenset[str] = frozenset('
            '{"strict", "permissive", "audit"})',
        )
        after = _by_key(ConfigProvider(root=checkout).provide())
        assert fact_map(after["test_layering"].errors)["values"] == (
            "audit,permissive,strict"
        )


class TestCitationsCannotGoStaleQuietly:
    """The two hand-written tables, guarded in both directions."""

    @pytest.fixture()
    def checkout(self, tmp_path: Path) -> Path:
        return _copy_project(tmp_path)

    def test_a_value_set_no_key_cites_stops_the_build(self, checkout: Path) -> None:
        """A closed set nobody documents is a rule met only by breaking it."""
        _rewrite(
            checkout,
            'DEFAULT_TEST_RUNNER: str = "pytest"',
            'DEFAULT_TEST_RUNNER: str = "pytest"\n'
            'SUPPORTED_INVENTIONS: frozenset[str] = frozenset({"one"})',
        )
        with pytest.raises(ConfigProviderError, match="SUPPORTED_INVENTIONS"):
            ConfigProvider(root=checkout).provide()

    def test_a_cited_value_set_that_has_gone_stops_the_build(
        self, checkout: Path
    ) -> None:
        _rewrite(
            checkout,
            "SUPPORTED_AUTHORING: frozenset[str] = ",
            "SUPPORTED_AUTHORING_RENAMED: frozenset[str] = ",
        )
        with pytest.raises(ConfigProviderError, match="SUPPORTED_AUTHORING"):
            ConfigProvider(root=checkout).provide()

    def test_a_rules_anchor_that_has_gone_stops_the_build(
        self, checkout: Path
    ) -> None:
        source = checkout / PROJECT_SOURCE
        text = source.read_text(encoding="utf-8")
        assert "INVALID_PROJECT_NAME_FOR_BUILD_DIR" in text
        source.write_text(
            text.replace("INVALID_PROJECT_NAME_FOR_BUILD_DIR", "SOME_OTHER_CODE"),
            encoding="utf-8",
        )
        with pytest.raises(
            ConfigProviderError, match="INVALID_PROJECT_NAME_FOR_BUILD_DIR"
        ):
            ConfigProvider(root=checkout).provide()

    def test_a_cited_key_the_loader_no_longer_reads_stops_the_build(
        self, checkout: Path
    ) -> None:
        _rewrite(
            checkout,
            'package_markers_raw = table.get("package_markers", [])',
            "package_markers_raw: list[str] = []",
        )
        _rewrite(
            checkout, '_ensure_list_of_str("package_markers", package_markers_raw)', ""
        )
        with pytest.raises(ConfigProviderError, match="package_markers"):
            ConfigProvider(root=checkout).provide()


class TestRefusals:
    """What the provider will not read, said by name."""

    def test_a_tree_without_the_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigProviderError, match="not in this tree"):
            ConfigProvider(root=tmp_path).provide()

    def test_a_file_that_does_not_parse_is_refused(self, tmp_path: Path) -> None:
        target = tmp_path / PROJECT_SOURCE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("class (:\n", encoding="utf-8")
        with pytest.raises(ConfigProviderError, match="does not parse"):
            ConfigProvider(root=tmp_path).provide()

    def test_a_renamed_loader_is_refused_by_name(self, tmp_path: Path) -> None:
        checkout = _copy_project(tmp_path)
        _rewrite(checkout, f"def {LOADER}(", "def _from_somewhere_else(")
        with pytest.raises(ConfigProviderError, match=LOADER):
            ConfigProvider(root=checkout).provide()

    def test_a_renamed_project_model_is_refused_by_name(self, tmp_path: Path) -> None:
        checkout = _copy_project(tmp_path)
        _rewrite(checkout, f"class {MODEL_CLASS}:", "class SomethingElse:")
        with pytest.raises(ConfigProviderError, match=MODEL_CLASS):
            ConfigProvider(root=checkout).provide()

    def test_a_loader_that_reads_no_keys_is_refused(self, tmp_path: Path) -> None:
        """A schema that reads empty passes every count downstream of it."""
        target = tmp_path / PROJECT_SOURCE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "class S0maProject:\n"
            "    root: str\n"
            "\n"
            "    @classmethod\n"
            "    def _from_tool_s0ma(cls, table):\n"
            "        return cls()\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigProviderError, match="reads no keys"):
            ConfigProvider(root=tmp_path).provide()


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


class TestComposition:
    """Plan §9 D2 T4: it composes clean, byte-stable, on an honest floor."""

    def test_the_records_pass_every_gate_with_no_findings(self) -> None:
        composed = compose(
            ProviderRegistry.of(ConfigProvider(root=REPO_ROOT)), release_version=RELEASE
        )
        assert composed.findings == ()
        assert (
            validate_bundle(
                composed.bundle,
                results=composed.results,
                external_ids=(),
                floors=dict(CONFIG_FLOORS),
                claims=(),
            )
            == ()
        )

    def test_the_floor_this_module_publishes_is_met_and_is_not_a_pin(self) -> None:
        counted = ConfigProvider(root=REPO_ROOT).provide().counts()["surfaces"]
        floor = CONFIG_FLOORS[(PROVIDER_ID, "surfaces")]
        assert counted >= floor
        assert floor < counted

    def test_a_provider_that_stopped_seeing_its_source_trips_the_floor(
        self, tmp_path: Path
    ) -> None:
        checkout = _copy_project(tmp_path)
        # Five keys the loader stops reading from its table: enough to fall
        # under the floor, and none of them cited by the tables above, so
        # the failure this proves is vacuity rather than a stale citation.
        _rewrite(checkout, 'table.get("adoption_exempt", [])', '{}.get("adoption_exempt", [])')
        _rewrite(checkout, 'table.get("runbook_notes")', '{}.get("runbook_notes")')
        for key in ("run_command", "health_command", "venv_path"):
            _rewrite(
                checkout,
                f'_parse_optional_str(table, "{key}")',
                f'_parse_optional_str({{}}, "{key}")',
            )
        result = ConfigProvider(root=checkout).provide()
        assert result.counts()["surfaces"] < CONFIG_FLOORS[(PROVIDER_ID, "surfaces")]
        findings = check_floors([result], dict(CONFIG_FLOORS))
        assert [finding.code for finding in findings] == ["DOC_GATE_VACUOUS"]

    def test_the_bundle_is_byte_stable(self) -> None:
        first = compose(
            ProviderRegistry.of(ConfigProvider(root=REPO_ROOT)), release_version=RELEASE
        )
        second = compose(
            ProviderRegistry.of(ConfigProvider(root=REPO_ROOT)), release_version=RELEASE
        )
        assert serialize_bundle(first.bundle) == serialize_bundle(second.bundle)
        assert first.bundle.stamp.snapshot_hash == second.bundle.stamp.snapshot_hash

    def test_the_snapshot_moves_when_the_source_moves(self, tmp_path: Path) -> None:
        checkout = _copy_project(tmp_path)
        before = compose(
            ProviderRegistry.of(ConfigProvider(root=checkout)), release_version=RELEASE
        ).bundle.stamp.snapshot_hash
        _rewrite(
            checkout,
            'DEFAULT_TEST_ROOTS: tuple[str, ...] = ("tests",)',
            'DEFAULT_TEST_ROOTS: tuple[str, ...] = ("spec",)',
        )
        after = compose(
            ProviderRegistry.of(ConfigProvider(root=checkout)), release_version=RELEASE
        ).bundle.stamp.snapshot_hash
        assert before != after

    def test_every_key_can_be_asked_for_and_shown(self) -> None:
        composed = compose(
            ProviderRegistry.of(ConfigProvider(root=REPO_ROOT)), release_version=RELEASE
        )
        assert (
            check_coverage(
                composed.bundle,
                renderers={"human": render_human, "agent": render_agent},
            )
            == []
        )

    def test_every_key_fits_the_agent_channels_budget(self) -> None:
        """A key's page and a key's answer both fit; only prose could break it."""
        composed = compose(
            ProviderRegistry.of(ConfigProvider(root=REPO_ROOT)), release_version=RELEASE
        )
        for record in composed.bundle.surfaces:
            view = facts_of(composed.bundle, record)
            assert check_budget(view, render_agent(view)) == [], record.id

    def test_the_two_d2_providers_compose_together(self) -> None:
        """Both halves of this milestone in one bundle, gates green."""
        composed = compose(
            ProviderRegistry.of(
                DiagnosticsProvider(root=REPO_ROOT), ConfigProvider(root=REPO_ROOT)
            ),
            release_version=RELEASE,
        )
        assert composed.findings == ()
        assert (
            validate_bundle(
                composed.bundle,
                results=composed.results,
                external_ids=(),
                floors={**dict(DIAGNOSTIC_FLOORS), **dict(CONFIG_FLOORS)},
            )
            == ()
        )
        channels = {record.channel for record in composed.bundle.surfaces}
        assert channels == {"config", "diagnostic"}


class TestTheApplicationAcceptsIt:
    """Plan §9 D2 T4, now that D5b has wired both halves in.

    D2 registered its two providers beside the C phase's five and proved
    nothing got worse. D5b registered them for real, so these ask the
    same three questions of the composition the repository actually
    builds rather than of a hypothetical one.
    """

    def test_the_application_registers_both_halves_of_d2(self) -> None:
        registered = set(application.registry(REPO_ROOT).ids())
        assert {PROVIDER_ID, DIAGNOSTICS_PROVIDER_ID} <= registered

    def test_both_readings_reach_the_composed_bundle_whole(self) -> None:
        """Every key and every code, counted against the live readings.

        D2 asserted the *difference* two providers made to a build that
        did not have them. The same claim without a "before" is that the
        composed bundle holds one record per live key and one per live
        code — which is what the difference was measuring.
        """
        built = application.build(REPO_ROOT, version=RELEASE)
        keys = {
            record.id for record in built.bundle.surfaces if record.channel == CHANNEL
        }
        assert keys == {config_id(name) for name in _live_keys()}
        assert len(keys) == len(_live_keys())

        codes = {
            record.id
            for record in built.bundle.surfaces
            if record.id.startswith("diagnostic:")
        }
        assert len(codes) == len(DiagnosticsProvider(root=REPO_ROOT).codes())

    def test_this_provider_is_the_only_claimant_of_the_id_space(self) -> None:
        """The merge rule's precondition, asked the way D5b can ask it.

        D2 could only show the space was unoccupied. Now that it is, the
        question worth asking is whether anything else reaches into it —
        and every ``config:`` record in the build carries this adapter's
        provenance, so nothing does.
        """
        built = application.build(REPO_ROOT, version=RELEASE)
        claimed = [
            record
            for record in built.bundle.surfaces
            if record.id.startswith("config:")
        ]
        assert claimed
        assert {record.provenance.adapter_id for record in claimed} == {PROVIDER_ID}
