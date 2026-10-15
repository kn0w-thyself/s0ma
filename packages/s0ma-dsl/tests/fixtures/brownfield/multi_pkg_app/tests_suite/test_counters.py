"""The counting is right, including when there is nothing to count."""

from __future__ import annotations

import pytest

from metrics.counters import EMPTY_LABEL, Tally, mean, percentile, total


def test_an_empty_list_has_no_total_and_no_mean() -> None:
    assert total([]) == 0.0
    assert mean([]) == 0.0
    assert percentile([], 0.5) == 0.0


def test_the_mean_is_rounded_to_the_default_precision() -> None:
    assert mean([1.0, 2.0, 2.0]) == 1.667


def test_the_percentile_reads_a_sorted_copy() -> None:
    assert percentile([9.0, 1.0, 5.0], 0.0) == 1.0
    assert percentile([9.0, 1.0, 5.0], 1.0) == 9.0


def test_a_fraction_outside_the_range_is_refused() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        percentile([1.0], 1.5)


def test_a_tally_summarises_itself() -> None:
    tally = Tally(name="seconds")
    assert tally.summary()["label"] == EMPTY_LABEL
    tally.add(2.0)
    tally.add(4.0)
    assert tally.count == 2
    assert tally.summary()["mean"] == 3.0
