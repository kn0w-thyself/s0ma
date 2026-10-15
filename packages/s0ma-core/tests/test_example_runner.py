"""Tests for the plan-M6 example execution subsystem.

Covers the three ``runs_in`` dispatch modes, the subprocess-level
timeout guarantee, the reverse-reporting on failure, and the contract
that ``ExampleRunner.run_all`` never raises even when individual
examples fail or hang.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import pytest

from s0ma.examples import (
    DEFAULT_TIMEOUT_SECONDS,
    INTEGRATION_CMD_ENV_VAR,
    DispatchOutcome,
    ExampleDispatcher,
    ExampleResult,
    ExampleRunner,
    TimeoutResult,
    run_all_examples,
    run_subprocess_with_timeout,
)
from s0ma.examples.dispatcher import _split_command_template
from s0ma.exceptions import ExampleTimeoutError
from s0ma.models import EntityRef, ExampleRegistration

if TYPE_CHECKING:
    from s0ma.registry import ComponentRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _passing_standalone(name: str = "pass_example") -> ExampleRegistration:
    return ExampleRegistration(
        name=name,
        module="tests.fixtures.examples",
        intent="Prints a single line and exits zero",
        demonstrates=[EntityRef(kind="component", name="SampleTarget", module=None)],
        runs_in="standalone",
        body="print('hello from example')\n",
    )


def _failing_standalone(name: str = "fail_example") -> ExampleRegistration:
    return ExampleRegistration(
        name=name,
        module="tests.fixtures.examples",
        intent="Raises an exception to demonstrate failure",
        demonstrates=[EntityRef(kind="component", name="SampleTarget", module=None)],
        runs_in="standalone",
        body='raise RuntimeError("deliberate failure from example")\n',
    )


def _slow_standalone(name: str = "slow_example", seconds: float = 5.0) -> ExampleRegistration:
    return ExampleRegistration(
        name=name,
        module="tests.fixtures.examples",
        intent="Sleeps long enough to trigger the runner timeout",
        demonstrates=[EntityRef(kind="component", name="SampleTarget", module=None)],
        runs_in="standalone",
        body=f"import time\ntime.sleep({seconds})\n",
    )


def _passing_pytest(name: str = "pytest_example") -> ExampleRegistration:
    return ExampleRegistration(
        name=name,
        module="tests.fixtures.examples",
        intent="A minimal pytest body that exercises a passing assertion",
        demonstrates=[EntityRef(kind="component", name="SampleTarget", module=None)],
        runs_in="pytest",
        body="def test_ok():\n    assert 1 + 1 == 2\n",
    )


def _failing_pytest(name: str = "failing_pytest") -> ExampleRegistration:
    return ExampleRegistration(
        name=name,
        module="tests.fixtures.examples",
        intent="A pytest body that deliberately fails an assertion",
        demonstrates=[EntityRef(kind="component", name="SampleTarget", module=None)],
        runs_in="pytest",
        body="def test_fails():\n    assert 1 == 2\n",
    )


# ---------------------------------------------------------------------------
# timeout.py
# ---------------------------------------------------------------------------


class TestRunSubprocessWithTimeout:
    def test_success_captures_stdout(self) -> None:
        result = run_subprocess_with_timeout(
            [sys.executable, "-c", "print('ok')"],
            timeout_seconds=5,
        )
        assert isinstance(result, TimeoutResult)
        assert result.returncode == 0
        assert "ok" in result.stdout
        assert result.timed_out is False
        assert result.duration_ms >= 0

    def test_nonzero_exit_is_not_a_timeout(self) -> None:
        result = run_subprocess_with_timeout(
            [sys.executable, "-c", "import sys; sys.exit(7)"],
            timeout_seconds=5,
        )
        assert result.returncode == 7
        assert result.timed_out is False

    def test_timeout_marks_result(self) -> None:
        result = run_subprocess_with_timeout(
            [sys.executable, "-c", "import time; time.sleep(3)"],
            timeout_seconds=0.2,
        )
        assert result.timed_out is True
        assert result.returncode == -1

    def test_stderr_captured_on_failure(self) -> None:
        result = run_subprocess_with_timeout(
            [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(1)"],
            timeout_seconds=5,
        )
        assert result.returncode == 1
        assert "boom" in result.stderr

    def test_missing_executable_is_structured_failure(self) -> None:
        # Launch failure (FileNotFoundError on every OS; WinError 2 on
        # Windows) must come back as a structured result, never a raw
        # traceback — the §1.2 Windows core-failure mode.
        result = run_subprocess_with_timeout(
            ["s0ma-test-binary-that-exists-nowhere"],
            timeout_seconds=5,
        )
        assert result.returncode == -1
        assert result.timed_out is False
        assert result.stdout == ""
        assert "Failed to launch subprocess" in result.stderr
        assert "s0ma-test-binary-that-exists-nowhere" in result.stderr
        assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# ExampleTimeoutError
# ---------------------------------------------------------------------------


def test_example_timeout_error_is_structured() -> None:
    err = ExampleTimeoutError("foo", 1.5)
    assert err.example_name == "foo"
    assert err.timeout_seconds == 1.5
    assert "foo" in str(err)
    assert "1.5" in str(err)


# ---------------------------------------------------------------------------
# _split_command_template (the Windows dispatcher regression)
# ---------------------------------------------------------------------------


class TestSplitCommandTemplate:
    """Regression coverage for the S0MA_INTEGRATION_CMD splitting fix.

    Parameterized over both ``posix=`` modes so the Windows-shaped cases
    run (simulated) on POSIX CI too — the posix=True rows document the
    backslash-eating bug that broke the dispatcher on Windows.
    """

    # The real test pattern from test_integration_honors_s0ma_integration_cmd,
    # with a Windows-shaped interpreter path substituted for sys.executable.
    WINDOWS_CMD = (
        'C:\\Tools\\Python313\\python.exe -c "import sys;print(\'integration-ran\')"'
    )

    @pytest.mark.parametrize(
        ("posix", "expected"),
        [
            pytest.param(
                False,
                [
                    "C:\\Tools\\Python313\\python.exe",
                    "-c",
                    "import sys;print('integration-ran')",
                ],
                id="non-posix-preserves-backslashes-and-strips-outer-quotes",
            ),
            pytest.param(
                True,
                [
                    "C:ToolsPython313python.exe",
                    "-c",
                    "import sys;print('integration-ran')",
                ],
                id="posix-eats-backslashes-the-windows-bug",
            ),
        ],
    )
    def test_windows_shaped_command(self, posix: bool, expected: list[str]) -> None:
        assert _split_command_template(self.WINDOWS_CMD, posix=posix) == expected

    @pytest.mark.parametrize("posix", [True, False])
    def test_quoted_body_placeholder_loses_quotes_in_both_modes(
        self, posix: bool
    ) -> None:
        # {body} substitution happens after splitting; a quoted placeholder
        # must come out bare in both modes or the child sees literal quotes.
        parts = _split_command_template('runner "{body}" --flag', posix=posix)
        assert parts == ["runner", "{body}", "--flag"]

    def test_non_posix_strips_single_quotes_too(self) -> None:
        parts = _split_command_template("tool 'a b' c", posix=False)
        assert parts == ["tool", "a b", "c"]

    def test_non_posix_mid_token_quotes_do_not_group(self) -> None:
        # Documented limit (a non-POSIX shlex property): a quote that does
        # not start its token does not group, so the token splits at the
        # space and keeps its quote characters — only fully-quoted tokens
        # lose their quotes.
        parts = _split_command_template('tool --flag="a b"', posix=False)
        assert parts == ["tool", '--flag="a', 'b"']

    def test_default_mode_matches_platform(self) -> None:
        cmd = 'x -c "y z"'
        assert _split_command_template(cmd) == _split_command_template(
            cmd, posix=(os.name != "nt")
        )


# ---------------------------------------------------------------------------
# ExampleDispatcher
# ---------------------------------------------------------------------------


class TestExampleDispatcher:
    def test_standalone_pass(self) -> None:
        dispatcher = ExampleDispatcher(timeout_seconds=10)
        outcome = dispatcher.dispatch(_passing_standalone())
        assert isinstance(outcome, DispatchOutcome)
        assert outcome.mode == "standalone"
        assert outcome.timeout_result.returncode == 0
        assert "hello" in outcome.timeout_result.stdout

    def test_standalone_failure_captures_traceback(self) -> None:
        dispatcher = ExampleDispatcher(timeout_seconds=10)
        outcome = dispatcher.dispatch(_failing_standalone())
        assert outcome.timeout_result.returncode != 0
        assert "deliberate failure" in outcome.timeout_result.stderr

    def test_pytest_mode_passes(self) -> None:
        dispatcher = ExampleDispatcher(timeout_seconds=30)
        outcome = dispatcher.dispatch(_passing_pytest())
        assert outcome.mode == "pytest"
        # pytest returns 0 on all-pass sessions.
        assert outcome.timeout_result.returncode == 0

    def test_pytest_mode_surfaces_failure(self) -> None:
        dispatcher = ExampleDispatcher(timeout_seconds=30)
        outcome = dispatcher.dispatch(_failing_pytest())
        # pytest returns non-zero when any test fails.
        assert outcome.timeout_result.returncode != 0
        assert outcome.timeout_result.timed_out is False

    def test_integration_falls_back_to_standalone_without_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv(INTEGRATION_CMD_ENV_VAR, raising=False)
        dispatcher = ExampleDispatcher(timeout_seconds=10)
        example = _passing_standalone("integration_fallback")
        example_obj = ExampleRegistration(
            name=example.name,
            module=example.module,
            intent=example.intent,
            demonstrates=example.demonstrates,
            runs_in="integration",
            body=example.body,
        )
        outcome = dispatcher.dispatch(example_obj)
        assert outcome.mode == "integration"
        assert outcome.timeout_result.returncode == 0

    def test_integration_honors_s0ma_integration_cmd(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Use a simple command that echoes the body path so we can assert it ran.
        cmd = f'{sys.executable} -c "import sys;print(\'integration-ran\')"'
        monkeypatch.setenv(INTEGRATION_CMD_ENV_VAR, cmd)
        dispatcher = ExampleDispatcher(timeout_seconds=10)
        example = ExampleRegistration(
            name="integration_cmd",
            module="tests.fixtures.examples",
            intent="Uses S0MA_INTEGRATION_CMD to run a custom runner",
            demonstrates=[EntityRef(kind="component", name="SampleTarget", module=None)],
            runs_in="integration",
            body="# unused — integration cmd replaces execution\n",
        )
        outcome = dispatcher.dispatch(example)
        assert outcome.mode == "integration"
        assert outcome.timeout_result.returncode == 0
        assert "integration-ran" in outcome.timeout_result.stdout

    def test_integration_cmd_missing_binary_is_structured_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A Windows-shaped path to a binary that exists on no OS: however the
        # platform's shlex mode renders it, the launch fails — and that must
        # surface as a structured failed result, never an uncaught OSError
        # (the §1.2 Windows core failure was an uncaught FileNotFoundError).
        monkeypatch.setenv(
            INTEGRATION_CMD_ENV_VAR,
            "C:\\definitely\\missing\\s0ma-runner.exe {body}",
        )
        dispatcher = ExampleDispatcher(timeout_seconds=10)
        example = ExampleRegistration(
            name="integration_missing_binary",
            module="tests.fixtures.examples",
            intent="Integration command pointing at a nonexistent runner",
            demonstrates=[EntityRef(kind="component", name="SampleTarget", module=None)],
            runs_in="integration",
            body="# unused — integration cmd replaces execution\n",
        )
        outcome = dispatcher.dispatch(example)
        assert outcome.mode == "integration"
        assert outcome.timeout_result.returncode == -1
        assert outcome.timeout_result.timed_out is False
        assert "Failed to launch subprocess" in outcome.timeout_result.stderr

    def test_unknown_runs_in_raises(self) -> None:
        dispatcher = ExampleDispatcher()
        # ExampleRegistration's Literal typing means we construct an
        # object with an invalid value to exercise the dispatcher's
        # fallthrough check.
        example = ExampleRegistration(
            name="bogus",
            module="tests",
            intent="Bogus runs_in for negative test",
            demonstrates=[EntityRef(kind="component", name="X", module=None)],
            runs_in="standalone",
            body="pass\n",
        )
        object.__setattr__(example, "runs_in", "unknown-mode")
        with pytest.raises(ValueError, match="unknown runs_in"):
            dispatcher.dispatch(example)


# ---------------------------------------------------------------------------
# ExampleRunner
# ---------------------------------------------------------------------------


class TestExampleRunner:
    def test_default_timeout_matches_constant(
        self,
        registry: ComponentRegistry,
    ) -> None:
        runner = ExampleRunner(registry)
        assert runner.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
        assert runner.registry is registry

    def test_discover_empty_registry(
        self,
        registry: ComponentRegistry,
    ) -> None:
        runner = ExampleRunner(registry)
        assert runner.discover() == []

    def test_run_all_empty_registry_returns_empty_list(
        self,
        registry: ComponentRegistry,
    ) -> None:
        runner = ExampleRunner(registry)
        assert runner.run_all() == []

    def test_run_success_returns_passed_result(
        self,
        registry: ComponentRegistry,
    ) -> None:
        example = registry.register_example(
            name="run_pass",
            module="tests.fixtures.examples",
            intent="Happy-path standalone example",
            demonstrates=[
                EntityRef(kind="component", name="SampleTarget", module=None)
            ],
            runs_in="standalone",
            body="print('runner pass')\n",
        )
        runner = ExampleRunner(registry, timeout_seconds=10)
        result = runner.run(example)
        assert isinstance(result, ExampleResult)
        assert result.example_name == "run_pass"
        assert result.runs_in == "standalone"
        assert result.passed is True
        assert result.timed_out is False
        assert result.error is None
        assert "runner pass" in result.stdout
        assert result.duration_ms >= 0
        assert result.summary().startswith("[PASS]")

    def test_run_failure_populates_error(
        self,
        registry: ComponentRegistry,
    ) -> None:
        example = registry.register_example(
            name="run_fail",
            module="tests.fixtures.examples",
            intent="Raises inside a standalone body",
            demonstrates=[
                EntityRef(kind="component", name="SampleTarget", module=None)
            ],
            runs_in="standalone",
            body='raise RuntimeError("nope")\n',
        )
        runner = ExampleRunner(registry, timeout_seconds=10)
        result = runner.run(example)
        assert result.passed is False
        assert result.timed_out is False
        assert result.error is not None
        assert "nope" in result.error or "nope" in result.stderr

    def test_run_timeout_sets_timed_out_and_error(
        self,
        registry: ComponentRegistry,
    ) -> None:
        registry.register_example(
            name="run_timeout",
            module="tests.fixtures.examples",
            intent="Sleeps longer than the configured timeout",
            demonstrates=[
                EntityRef(kind="component", name="SampleTarget", module=None)
            ],
            runs_in="standalone",
            body="import time\ntime.sleep(3)\n",
        )
        runner = ExampleRunner(registry, timeout_seconds=0.25)
        results = runner.run_all()
        assert len(results) == 1
        result = results[0]
        assert result.timed_out is True
        assert result.passed is False
        assert result.error is not None
        assert "run_timeout" in result.error
        assert result.summary().startswith("[TIMEOUT]")

    def test_run_all_aggregates_mixed_outcomes(
        self,
        registry: ComponentRegistry,
    ) -> None:
        registry.register_example(
            name="mix_pass",
            module="tests.fixtures.examples",
            intent="Passing standalone example in a mixed batch",
            demonstrates=[
                EntityRef(kind="component", name="SampleTarget", module=None)
            ],
            runs_in="standalone",
            body="print('ok')\n",
        )
        registry.register_example(
            name="mix_fail",
            module="tests.fixtures.examples",
            intent="Failing standalone example in a mixed batch",
            demonstrates=[
                EntityRef(kind="component", name="SampleTarget", module=None)
            ],
            runs_in="standalone",
            body='raise SystemExit(3)\n',
        )
        results = run_all_examples(registry, timeout_seconds=10)
        by_name = {r.example_name: r for r in results}
        assert set(by_name) == {"mix_pass", "mix_fail"}
        assert by_name["mix_pass"].passed is True
        assert by_name["mix_fail"].passed is False


# ---------------------------------------------------------------------------
# Module re-exports are intact
# ---------------------------------------------------------------------------


def test_s0ma_examples_public_api_surface() -> None:
    import s0ma.examples as m

    for symbol in (
        "ExampleRunner",
        "ExampleResult",
        "ExampleDispatcher",
        "DispatchOutcome",
        "TimeoutResult",
        "run_all_examples",
        "run_subprocess_with_timeout",
        "DEFAULT_TIMEOUT_SECONDS",
        "INTEGRATION_CMD_ENV_VAR",
    ):
        assert hasattr(m, symbol), f"s0ma.examples missing {symbol}"
