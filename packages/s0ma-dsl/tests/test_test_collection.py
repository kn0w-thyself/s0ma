"""A test the runner would never run is reported (spec §4.8.2).

``TEST_NOT_COLLECTED``. The emitter writes a test's code out as it was
authored and registers the declaration as coverage for the parts it names.
Whether anything runs is pytest's decision, taken on the function's name
alone — so a body that defines only ``def check_dates()`` is emitted,
counted as coverage, and never executed.

The names pytest collects are read from the project's own runner settings,
so a project that has told pytest to collect other names is not told its
tests will not run. ``TestTheProjectsOwnRunnerSettings`` pins that, for each
of the four files pytest reads settings from.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.config import SEVERITY_MATRIX, StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.semantic import validator
from s0ma_dsl.semantic.validator import validate_module

HEADER = """\
module probe_tests
    layer: DOMAIN
    version: 0.1.0
    intent: "Checks written to be collected, or not."
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""

TEST = """
test {name} :: DOMAIN
    intent: "Two and two make four."
    tests: [probe.add]
    expects: none
    depends_on: none
    mocks: none
    ---
{body}
"""


def module_with(body: str, name: str = "sums_are_right") -> str:
    indented = "\n".join("    " + line if line else line for line in body.split("\n"))
    return HEADER + TEST.format(name=name, body=indented)


def reports(
    source: str,
    *,
    mode: StrictnessMode = StrictnessMode.DEV,
    filename: str = "probe_tests.s0ma",
) -> list:
    module = parse_s0ma(source, filename, mode=mode)
    return [
        item
        for item in validate_module(module, mode=mode, filename=filename)
        if item.code == "TEST_NOT_COLLECTED"
    ]


@pytest.fixture(autouse=True)
def fresh_runner_settings():
    """The settings reading is cached per directory; each test starts clean."""
    validator._runner_settings_above.cache_clear()
    yield
    validator._runner_settings_above.cache_clear()


FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "invalid" / "test_not_collected.s0ma"
)
"""The deliberately failing fixture, named after the code it trips — the
repository's convention for a DSL diagnostic."""


class TestTheNegativeFixture:
    """What a person at a terminal sees: the real command, over a real file."""

    def check(self, mode: str, capsys) -> dict[str, list[dict]]:
        S0maCLI().run(["check", str(FIXTURE), "--mode", mode, "--format", "json"])
        return json.loads(capsys.readouterr().out)

    def test_the_fixture_trips_its_code_and_nothing_else(self, capsys):
        report = self.check("dev", capsys)
        assert report["errors"] == []
        assert [item["code"] for item in report["warnings"]] == ["TEST_NOT_COLLECTED"]
        found = report["warnings"][0]
        assert found["line"] == 14
        assert found["remediation"].startswith("Name the function `test_sums_are_right`.")

    def test_before_shipping_it_is_refused(self, capsys):
        report = self.check("release", capsys)
        assert "TEST_NOT_COLLECTED" in [item["code"] for item in report["errors"]]


class TestWhatTheRunnerCollects:
    def test_a_function_named_test_is_not_reported(self):
        assert reports(module_with("def test_sums() -> None:\n    assert 2 + 2 == 4")) == []

    def test_an_async_function_named_test_is_not_reported(self):
        body = "async def test_sums() -> None:\n    assert 2 + 2 == 4"
        assert reports(module_with(body)) == []

    def test_one_collected_function_among_helpers_is_enough(self):
        body = (
            "def make_pair() -> tuple[int, int]:\n"
            "    return 2, 2\n"
            "\n"
            "def test_sums() -> None:\n"
            "    left, right = make_pair()\n"
            "    assert left + right == 4"
        )
        assert reports(module_with(body)) == []

    def test_a_function_named_anything_else_is_reported(self):
        found = reports(module_with("def sums_are_right() -> None:\n    assert 2 + 2 == 4"))
        assert len(found) == 1
        report = found[0]
        assert report.severity == "warning"
        assert report.message == (
            "Test 'sums_are_right' defines `sums_are_right`, and the test runner "
            "only runs functions whose names start with `test`. This test would "
            "never run, and it would still count as coverage for the parts it "
            "names."
        )
        assert report.remediation.startswith("Name the function `test_sums_are_right`.")
        assert report.context == {
            "test": "sums_are_right",
            "defined": ["sums_are_right"],
            "collected_patterns": ["test"],
            "suggestion": "test_sums_are_right",
        }

    def test_the_declarations_own_name_does_not_make_it_run(self):
        body = "def sums() -> None:\n    assert 2 + 2 == 4"
        found = reports(module_with(body, name="test_sums_are_right"))
        assert len(found) == 1
        # The declaration is already named the way the runner wants, so
        # that is the name to give the function.
        assert found[0].context["suggestion"] == "test_sums_are_right"

    def test_every_uncollected_declaration_is_reported(self):
        source = module_with("def first() -> None:\n    assert True", name="first") + TEST.format(
            name="second", body="    def second() -> None:\n        assert True",
        )
        assert [item.context["test"] for item in reports(source)] == ["first", "second"]


class TestTheLadder:
    def test_warning_while_working_and_error_before_shipping(self):
        assert SEVERITY_MATRIX["TEST_NOT_COLLECTED"] == {
            StrictnessMode.MIGRATION: "warning",
            StrictnessMode.DEV: "warning",
            StrictnessMode.STRICT: "error",
            StrictnessMode.RELEASE: "error",
        }

    @pytest.mark.parametrize(
        "mode, severity",
        [
            (StrictnessMode.MIGRATION, "warning"),
            (StrictnessMode.DEV, "warning"),
            (StrictnessMode.STRICT, "error"),
            (StrictnessMode.RELEASE, "error"),
        ],
    )
    def test_the_report_carries_the_modes_severity(self, mode, severity):
        found = reports(module_with("def sums() -> None:\n    assert True"), mode=mode)
        assert [item.severity for item in found] == [severity]


class TestTheProjectsOwnRunnerSettings:
    """pytest reads its settings from the first of four files it finds, and
    a project may have told it to collect other names."""

    BODY = "def check_sums() -> None:\n    assert 2 + 2 == 4"

    def source_in(self, project: Path) -> str:
        tests = project / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        path = tests / "probe_tests.s0ma"
        path.write_text(module_with(self.BODY), encoding="utf-8")
        return str(path)

    def found_in(self, project: Path) -> list:
        filename = self.source_in(project)
        return reports(Path(filename).read_text(encoding="utf-8"), filename=filename)

    def test_with_no_settings_the_default_names_apply(self, tmp_path):
        assert len(self.found_in(tmp_path)) == 1

    def test_pyproject_may_name_other_functions(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\npython_functions = ["test_*", "check_*"]\n',
            encoding="utf-8",
        )
        assert self.found_in(tmp_path) == []

    def test_pyproject_may_name_them_as_one_string(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\npython_functions = "test check"\n',
            encoding="utf-8",
        )
        assert self.found_in(tmp_path) == []

    @pytest.mark.parametrize(
        "name, section",
        [("pytest.ini", "pytest"), ("tox.ini", "pytest"), ("setup.cfg", "tool:pytest")],
    )
    def test_an_ini_file_may_name_other_functions(self, tmp_path, name, section):
        (tmp_path / name).write_text(
            f"[{section}]\npython_functions = test_* check_*\n", encoding="utf-8",
        )
        assert self.found_in(tmp_path) == []

    def test_settings_that_name_no_functions_leave_the_default(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\naddopts = "-q"\n', encoding="utf-8",
        )
        assert len(self.found_in(tmp_path)) == 1

    def test_the_report_names_the_patterns_the_project_configured(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\npython_functions = ["should_*"]\n',
            encoding="utf-8",
        )
        found = self.found_in(tmp_path)
        assert len(found) == 1
        assert found[0].context["collected_patterns"] == ["should_*"]

    def test_pytest_ini_wins_over_pyproject_in_the_same_directory(self, tmp_path):
        (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\npython_functions = ["check_*"]\n',
            encoding="utf-8",
        )
        # pytest.ini is the file pytest reads, and it names no functions,
        # so the default applies and the pyproject setting is never seen.
        assert len(self.found_in(tmp_path)) == 1

    def test_a_settings_file_that_cannot_be_read_is_treated_as_absent(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("this is [not toml\n", encoding="utf-8")
        assert len(self.found_in(tmp_path)) == 1

    def test_a_source_with_no_file_behind_it_uses_the_default(self):
        assert validator._runner_name_patterns("<string>") == (("test",), ("Test",))


class TestPytestsOwnMatchingRule:
    @pytest.mark.parametrize(
        "name, patterns, collected",
        [
            ("test_sums", ("test",), True),
            ("testsums", ("test",), True),
            ("sums_test", ("test",), False),
            ("check_sums", ("test", "check"), True),
            ("check_sums", ("check_*",), True),
            ("it_checks_sums", ("*_sums",), True),
            ("it_checks_sums", ("check_*",), False),
        ],
    )
    def test_a_prefix_or_a_glob(self, name, patterns, collected):
        assert validator._runner_collects(name, patterns) is collected
