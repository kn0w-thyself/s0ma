"""Small summaries over a run's measurements — numbers in, numbers out."""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_PRECISION = 3
EMPTY_LABEL = "no measurements"


def total(values: list[float]) -> float:
    """The sum of ``values``, or zero when there are none."""
    return float(sum(values))


def mean(values: list[float]) -> float:
    """The arithmetic mean of ``values``, or zero when there are none."""
    if not values:
        return 0.0
    return round(total(values) / len(values), DEFAULT_PRECISION)


def percentile(values: list[float], fraction: float) -> float:
    """The value at ``fraction`` through a sorted copy of ``values``."""
    if not values:
        return 0.0
    if not 0.0 <= fraction <= 1.0:
        raise ValueError(f"fraction must be between 0 and 1, not {fraction}")
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return ordered[position]


def _label(count: int) -> str:
    """How a tally describes its own size, in plain words."""
    if count == 0:
        return EMPTY_LABEL
    return f"{count} measurement" if count == 1 else f"{count} measurements"


@dataclass
class Tally:
    """Measurements collected under one name."""

    name: str
    values: list[float] = field(default_factory=list)

    def add(self, value: float) -> None:
        """Record one more measurement."""
        self.values.append(float(value))

    @property
    def count(self) -> int:
        """How many measurements have been recorded."""
        return len(self.values)

    def summary(self) -> dict[str, float | str]:
        """The tally as the report wants it: three numbers and a label."""
        return {
            "name": self.name,
            "label": _label(self.count),
            "mean": mean(self.values),
            "total": total(self.values),
            "p90": percentile(self.values, 0.9),
        }
