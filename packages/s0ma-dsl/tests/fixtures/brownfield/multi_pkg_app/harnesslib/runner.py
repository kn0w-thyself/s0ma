"""The run loop: one case at a time, timings tallied through ``metrics``."""

from __future__ import annotations

from dataclasses import dataclass

from metrics.counters import Tally, mean

DEFAULT_ATTEMPTS = 2
CASE_PASSED = "passed"
CASE_FAILED = "failed"


@dataclass(frozen=True)
class CaseResult:
    """What one case did, once."""

    case: str
    outcome: str
    seconds: float

    @property
    def passed(self) -> bool:
        """True when the case reached the end without an error."""
        return self.outcome == CASE_PASSED


def _cost(case: str, attempt: int) -> float:
    """A stand-in for a real clock, so a run is reproducible."""
    return round(len(case) / 10 + attempt / 4, 3)


def run_case(case: str, attempts: int = DEFAULT_ATTEMPTS) -> CaseResult:
    """Run one case ``attempts`` times; a blank name fails without running."""
    if attempts < 1:
        raise ValueError("a case has to be attempted at least once")
    if not case.strip():
        return CaseResult(case=case, outcome=CASE_FAILED, seconds=0.0)
    spent = 0.0
    for attempt in range(1, attempts + 1):
        spent += _cost(case, attempt)
    return CaseResult(case=case, outcome=CASE_PASSED, seconds=round(spent, 3))


class Runner:
    """A run over a list of cases, with its timings kept as it goes."""

    def __init__(self, name: str, attempts: int = DEFAULT_ATTEMPTS) -> None:
        self.name = name
        self.attempts = attempts
        self.tally = Tally(name=f"{name}-seconds")

    def run(self, cases: list[str]) -> list[CaseResult]:
        """Run every case in order and record how long each one took."""
        results = []
        for case in cases:
            result = run_case(case, self.attempts)
            self.tally.add(result.seconds)
            results.append(result)
        return results

    def average_seconds(self) -> float:
        """The mean time of everything run so far."""
        return mean(self.tally.values)


def run_suite(name: str, cases: list[str]) -> dict[str, object]:
    """Run a whole suite and return the report the scorer reads."""
    runner = Runner(name)
    results = runner.run(cases)
    return {
        "suite": name,
        "results": results,
        "passed": sum(1 for result in results if result.passed),
        "average_seconds": runner.average_seconds(),
    }
