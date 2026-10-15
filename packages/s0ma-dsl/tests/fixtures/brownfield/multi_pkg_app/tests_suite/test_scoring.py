"""Scores are between zero and one, and better suites sort first."""

from __future__ import annotations

from evallib.scoring import rank_suites, score_suite


def test_a_suite_that_all_passes_scores_above_one_that_does_not() -> None:
    good = score_suite("good", ["one", "two"])
    poor = score_suite("poor", ["one", ""])
    assert good.pass_rate == 1.0
    assert poor.pass_rate == 0.5
    assert good.overall > poor.overall


def test_an_empty_suite_scores_nothing_rather_than_failing() -> None:
    verdict = score_suite("empty", [])
    assert verdict.pass_rate == 0.0
    assert verdict.overall == 0.0


def test_ranking_puts_the_best_suite_first() -> None:
    ranked = rank_suites({"poor": ["one", ""], "good": ["one", "two"]})
    assert [verdict.suite for verdict in ranked] == ["good", "poor"]
