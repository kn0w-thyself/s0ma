"""Scoring a run: how much passed, and how quickly, through ``harnesslib``."""

from __future__ import annotations

from dataclasses import dataclass

from harnesslib.runner import run_suite
from metrics.counters import percentile

PASS_WEIGHT = 0.8
SPEED_WEIGHT = 0.2
SLOW_SECONDS = 2.0


@dataclass(frozen=True)
class Verdict:
    """One suite's score, and the two halves it was made of."""

    suite: str
    pass_rate: float
    speed: float

    @property
    def overall(self) -> float:
        """The weighted score, between zero and one."""
        return round(PASS_WEIGHT * self.pass_rate + SPEED_WEIGHT * self.speed, 3)


def _speed(seconds: list[float]) -> float:
    """How fast a run was, as a number between zero and one."""
    if not seconds:
        return 0.0
    slowest = percentile(seconds, 0.9)
    if slowest <= 0:
        return 1.0
    return round(max(0.0, min(1.0, SLOW_SECONDS / slowest)), 3)


def score_suite(name: str, cases: list[str]) -> Verdict:
    """Run a suite and score what came back."""
    report = run_suite(name, cases)
    results = report["results"]
    pass_rate = round(report["passed"] / len(results), 3) if results else 0.0
    return Verdict(
        suite=name,
        pass_rate=pass_rate,
        speed=_speed([result.seconds for result in results]),
    )


def rank_suites(suites: dict[str, list[str]]) -> list[Verdict]:
    """Score every suite and return them best first."""
    verdicts = [score_suite(name, cases) for name, cases in sorted(suites.items())]
    return sorted(verdicts, key=lambda verdict: (-verdict.overall, verdict.suite))
