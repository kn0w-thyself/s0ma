"""Dispatcher that executes ``ExampleRegistration`` bodies in isolated subprocesses.

Three dispatch modes mirror the ``runs_in`` field on ``ExampleRegistration``:

* ``standalone`` — execute the body as a plain Python script in a fresh
  interpreter subprocess. Uncaught exceptions mark the example as failed.
* ``pytest`` — write the body to a ``test_<name>.py`` file in a temp dir
  and invoke ``pytest`` against it via ``python -m pytest``.
* ``integration`` — honor ``S0MA_INTEGRATION_CMD`` for a user-configurable
  integration runner; falls back to the standalone dispatcher when the
  env var is unset.

All three paths go through ``run_subprocess_with_timeout`` to guarantee
consistent timeout + capture semantics.
"""

from __future__ import annotations

import os
import shlex
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma.examples.timeout import (
    DEFAULT_TIMEOUT_SECONDS,
    TimeoutResult,
    run_subprocess_with_timeout,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from s0ma.models import ExampleRegistration

__all__ = [
    "INTEGRATION_CMD_ENV_VAR",
    "DispatchOutcome",
    "ExampleDispatcher",
]

INTEGRATION_CMD_ENV_VAR: str = "S0MA_INTEGRATION_CMD"


class DispatchOutcome:
    """Raw outcome of dispatching an example body to a subprocess.

    Thin value object consumed by ``ExampleRunner`` to build the
    user-facing ``ExampleResult``. Kept distinct so that ``ExampleResult``
    can carry registry-level fields (name, runs_in) without the dispatcher
    needing to know about them.
    """

    __slots__ = ("timeout_result", "mode")

    def __init__(self, timeout_result: TimeoutResult, mode: str) -> None:
        self.timeout_result = timeout_result
        self.mode = mode


class ExampleDispatcher:
    """Dispatches an ``ExampleRegistration`` to the appropriate subprocess runner.

    One dispatcher instance is safe to reuse across many examples. All
    state is scoped per-call; no registry or filesystem resources are
    held between invocations.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        python_executable: str | None = None,
        integration_cmd: str | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._python_executable = python_executable or sys.executable
        self._integration_cmd = integration_cmd

    def dispatch(self, example: ExampleRegistration) -> DispatchOutcome:
        """Dispatch an example by its ``runs_in`` mode."""
        mode = example.runs_in
        if mode == "standalone":
            return self._dispatch_standalone(example)
        if mode == "pytest":
            return self._dispatch_pytest(example)
        if mode == "integration":
            return self._dispatch_integration(example)
        raise ValueError(
            f"Example '{example.name}' has unknown runs_in value: {mode!r}"
        )

    def _dispatch_standalone(self, example: ExampleRegistration) -> DispatchOutcome:
        # ignore_cleanup_errors: on Windows a timed-out grandchild can briefly
        # hold the directory open, turning teardown into a PermissionError.
        with tempfile.TemporaryDirectory(
            prefix="s0ma-example-", ignore_cleanup_errors=True,
        ) as tmpdir:
            body_path = Path(tmpdir) / f"{_safe_filename(example.name)}.py"
            body_path.write_text(example.body, encoding="utf-8")
            result = run_subprocess_with_timeout(
                [self._python_executable, str(body_path)],
                cwd=tmpdir,
                env=_child_env(),
                timeout_seconds=self._timeout_seconds,
            )
        return DispatchOutcome(result, mode="standalone")

    def _dispatch_pytest(self, example: ExampleRegistration) -> DispatchOutcome:
        # ignore_cleanup_errors: see _dispatch_standalone.
        with tempfile.TemporaryDirectory(
            prefix="s0ma-example-pytest-", ignore_cleanup_errors=True,
        ) as tmpdir:
            test_file = Path(tmpdir) / f"test_{_safe_filename(example.name)}.py"
            test_file.write_text(example.body, encoding="utf-8")
            result = run_subprocess_with_timeout(
                [
                    self._python_executable,
                    "-m",
                    "pytest",
                    str(test_file),
                    "-q",
                    "--tb=short",
                    "-p",
                    "no:cacheprovider",
                ],
                cwd=tmpdir,
                env=_child_env(),
                timeout_seconds=self._timeout_seconds,
            )
        return DispatchOutcome(result, mode="pytest")

    def _dispatch_integration(self, example: ExampleRegistration) -> DispatchOutcome:
        cmd_template = self._integration_cmd or os.environ.get(INTEGRATION_CMD_ENV_VAR)
        if not cmd_template:
            outcome = self._dispatch_standalone(example)
            return DispatchOutcome(outcome.timeout_result, mode="integration")

        # ignore_cleanup_errors: see _dispatch_standalone.
        with tempfile.TemporaryDirectory(
            prefix="s0ma-example-integration-", ignore_cleanup_errors=True,
        ) as tmpdir:
            body_path = Path(tmpdir) / f"{_safe_filename(example.name)}.py"
            body_path.write_text(example.body, encoding="utf-8")

            env = _child_env()
            env["S0MA_EXAMPLE_BODY_PATH"] = str(body_path)
            env["S0MA_EXAMPLE_NAME"] = example.name

            cmd_parts = _split_command_template(cmd_template)
            substituted = [_substitute_body_token(part, str(body_path)) for part in cmd_parts]

            result = run_subprocess_with_timeout(
                substituted,
                cwd=tmpdir,
                env=env,
                timeout_seconds=self._timeout_seconds,
            )
        return DispatchOutcome(result, mode="integration")


def _safe_filename(name: str) -> str:
    """Produce a filesystem-safe identifier derived from an example name."""
    cleaned = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in name)
    return cleaned or "example"


def _split_command_template(cmd_template: str, *, posix: bool | None = None) -> list[str]:
    r"""Split an integration command template into argv tokens.

    ``posix=None`` (the default) selects the mode for the current platform;
    tests pass an explicit mode to exercise both behaviors everywhere.

    POSIX-mode ``shlex.split`` treats ``\`` as an escape character, eating
    Windows path backslashes (``C:\Tools\python.exe`` becomes
    ``C:Toolspython.exe``), so on Windows we split with ``posix=False``
    (W-4: the semantics genuinely differ per-OS). Non-POSIX mode keeps quote
    characters on quoted tokens (``"a b"`` stays ``'"a b"'``), which
    subprocess argv entries must not carry, so one layer of matching outer
    quotes is stripped from each fully-quoted token. Known non-POSIX shlex
    limit: a quote that does not start its token does not group (e.g.
    ``--flag="a b"`` splits at the space) — quote whole tokens instead.
    """
    if posix is None:
        # Windows command strings carry backslashed paths; POSIX shlex
        # would destroy them (see docstring).
        posix = os.name != "nt"
    parts = shlex.split(cmd_template, posix=posix)
    if not posix:
        parts = [_strip_outer_quotes(part) for part in parts]
    return parts


def _strip_outer_quotes(token: str) -> str:
    """Remove one layer of matching surrounding quotes from a shlex token.

    Only used for non-POSIX ``shlex.split`` output, which preserves the
    quote characters that grouped a token.
    """
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1]
    return token


def _substitute_body_token(part: str, body_path: str) -> str:
    """Replace the ``{body}`` placeholder in an integration command template."""
    return part.replace("{body}", body_path)


def _child_env() -> dict[str, str]:
    """Copy of the current environment safe to mutate for a child process.

    Pins ``PYTHONIOENCODING=utf-8`` so child interpreters emit UTF-8 on
    stdout/stderr regardless of the platform locale — the parent decodes
    subprocess output as UTF-8 (see ``run_subprocess_with_timeout``), and
    both sides must agree (Windows would otherwise write cp1252).
    """
    env: Mapping[str, str] = os.environ
    child = dict(env)
    child["PYTHONIOENCODING"] = "utf-8"
    return child
