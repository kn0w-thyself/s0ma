"""The run loop reports what it ran, and refuses what it cannot run."""

from __future__ import annotations

import pytest

from harnesslib.runner import CASE_FAILED, Runner, run_case, run_suite


def test_a_named_case_passes_and_is_timed() -> None:
    result = run_case("open-the-shop")
    assert result.passed
    assert result.seconds > 0


def test_a_blank_case_fails_without_being_run() -> None:
    result = run_case("   ")
    assert not result.passed
    assert result.outcome == CASE_FAILED
    assert result.seconds == 0.0


def test_a_run_of_no_attempts_is_refused() -> None:
    with pytest.raises(ValueError, match="at least once"):
        run_case("anything", attempts=0)


def test_a_runner_keeps_its_own_timings() -> None:
    runner = Runner("morning")
    runner.run(["one", "two"])
    assert runner.tally.count == 2
    assert runner.average_seconds() > 0


def test_a_suite_reports_how_many_passed() -> None:
    report = run_suite("morning", ["one", "", "three"])
    assert report["suite"] == "morning"
    assert report["passed"] == 2
