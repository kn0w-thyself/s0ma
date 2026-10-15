"""Example discovery + execution — the public entry point of ``s0ma.examples``.

``ExampleRunner`` wraps ``ExampleDispatcher`` with registry-aware
discovery and structured result reporting. Consumers typically call
``run_all()`` to execute every registered example in the current
registry snapshot.

Design notes
------------
* Each example runs in its own subprocess (see :mod:`s0ma.examples.dispatcher`)
  so that registry mutations, ``sys.modules`` state, and timeouts stay
  isolated from the parent test run.
* Timeouts are reported on the ``ExampleResult`` (``timed_out=True``,
  ``error`` populated), never raised to ``run_all``'s caller — bulk runs
  must surface all failures instead of short-circuiting on the first.
* ``run()`` (single-example) also returns the result rather than raising,
  matching plan M6's fixture-based tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from s0ma.examples.dispatcher import ExampleDispatcher
from s0ma.examples.timeout import DEFAULT_TIMEOUT_SECONDS, TimeoutResult
from s0ma.exceptions import ExampleTimeoutError

if TYPE_CHECKING:
    from s0ma.models import ExampleRegistration
    from s0ma.registry import ComponentRegistry

__all__ = [
    "ExampleResult",
    "ExampleRunner",
    "run_all_examples",
]


@dataclass(frozen=True)
class ExampleResult:
    """Structured outcome of running a single registered example.

    ``passed`` is the summary bit: True iff the subprocess returned zero
    and did not time out. ``error`` carries the most actionable failure
    hint — a timeout marker, a captured traceback fragment, or the first
    lines of stderr.
    """

    example_name: str
    runs_in: str
    passed: bool
    duration_ms: float
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        """One-line human summary suitable for a CLI report."""
        status = "PASS" if self.passed else ("TIMEOUT" if self.timed_out else "FAIL")
        return (
            f"[{status}] {self.example_name} ({self.runs_in}) "
            f"— {self.duration_ms:.0f}ms"
        )


class ExampleRunner:
    """Discovers and executes registered examples with per-result reporting.

    Reads examples from the registry snapshot at call time, so any
    registrations that land after the runner is constructed are still
    picked up by the next ``discover()`` / ``run_all()`` call.
    """

    def __init__(
        self,
        registry: ComponentRegistry,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        dispatcher: ExampleDispatcher | None = None,
    ) -> None:
        self._registry = registry
        self._timeout_seconds = timeout_seconds
        self._dispatcher = dispatcher or ExampleDispatcher(
            timeout_seconds=timeout_seconds
        )

    @property
    def registry(self) -> ComponentRegistry:
        """The registry this runner reads examples from."""
        return self._registry

    @property
    def timeout_seconds(self) -> float:
        """Effective per-example timeout budget, in seconds."""
        return self._timeout_seconds

    def discover(self) -> list[ExampleRegistration]:
        """Return every ``ExampleRegistration`` in the current registry snapshot."""
        snapshot = self._registry.snapshot()
        return list(snapshot.examples.values())

    def run(self, example: ExampleRegistration) -> ExampleResult:
        """Execute one example and return the structured result."""
        outcome = self._dispatcher.dispatch(example)
        timeout_result = outcome.timeout_result
        passed = (not timeout_result.timed_out) and timeout_result.returncode == 0
        error = self._build_error_summary(example, timeout_result)
        return ExampleResult(
            example_name=example.name,
            runs_in=outcome.mode,
            passed=passed,
            duration_ms=timeout_result.duration_ms,
            stdout=timeout_result.stdout,
            stderr=timeout_result.stderr,
            returncode=timeout_result.returncode,
            timed_out=timeout_result.timed_out,
            error=error,
        )

    def run_all(self) -> list[ExampleResult]:
        """Execute every discovered example. Always returns — never raises."""
        results: list[ExampleResult] = []
        for example in self.discover():
            results.append(self.run(example))
        return results

    def _build_error_summary(
        self,
        example: ExampleRegistration,
        timeout_result: TimeoutResult,
    ) -> str | None:
        if timeout_result.timed_out:
            timeout_err = ExampleTimeoutError(example.name, self._timeout_seconds)
            return str(timeout_err)
        if timeout_result.returncode == 0:
            return None
        stderr_tail = (timeout_result.stderr or "").strip()
        if stderr_tail:
            return _tail_lines(stderr_tail, max_lines=10)
        return f"Example exited with returncode {timeout_result.returncode}"


def run_all_examples(
    registry: ComponentRegistry,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[ExampleResult]:
    """Module-level convenience — construct a runner and execute everything.

    Equivalent to ``ExampleRunner(registry, timeout_seconds=...).run_all()``.
    Exists because most test-pipeline integrations want a single call.
    """
    runner = ExampleRunner(registry, timeout_seconds=timeout_seconds)
    return runner.run_all()


def _tail_lines(text: str, *, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[-max_lines:])
