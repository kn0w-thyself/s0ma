"""Cross-platform subprocess timeout primitives for example execution.

Wraps ``subprocess.run`` so that timeout handling produces a uniform
``TimeoutResult`` regardless of platform. On Unix, ``subprocess.run``
escalates SIGTERM → SIGKILL; on Windows it calls ``TerminateProcess``.
Both paths surface here as ``timed_out=True`` on the result.

This module deliberately does not raise ``subprocess.TimeoutExpired``
to callers — the dispatcher layer is tidier when timeout is represented
as a first-class result field rather than a control-flow exception.
Launch failures (``OSError``/``FileNotFoundError``, e.g. a missing or
mangled executable) are likewise returned as structured failed results
instead of propagating raw tracebacks.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

__all__ = ["DEFAULT_TIMEOUT_SECONDS", "TimeoutResult", "run_subprocess_with_timeout"]

DEFAULT_TIMEOUT_SECONDS: int = 30


@dataclass(frozen=True)
class TimeoutResult:
    """Outcome of a subprocess invocation wrapped by ``run_subprocess_with_timeout``.

    ``timed_out`` is True iff the subprocess was killed for exceeding the
    timeout budget. When True, ``returncode`` is ``-1`` and any partial
    stdout/stderr captured before the kill is preserved.
    """

    returncode: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool


def run_subprocess_with_timeout(
    cmd: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    input_text: str | None = None,
) -> TimeoutResult:
    """Run ``cmd`` as a subprocess and collect its output under a timeout.

    Always captures stdout/stderr as text, decoded as UTF-8 with
    ``errors="replace"`` (never the locale codec — Windows cp1252 must not
    mangle or crash on child output). If the timeout fires, the subprocess
    is killed and the function returns with ``timed_out=True`` rather than
    propagating ``subprocess.TimeoutExpired``. If the subprocess cannot be
    launched at all (``OSError``, e.g. ``FileNotFoundError`` for a missing
    executable), the failure is returned as a structured result with
    ``timed_out=False`` instead of a raw traceback.
    """
    argv = list(cmd)
    start = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        duration_ms = (time.monotonic() - start) * 1000.0
        return TimeoutResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_ms=duration_ms,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = (time.monotonic() - start) * 1000.0
        partial_stdout = _coerce_output(exc.stdout)
        partial_stderr = _coerce_output(exc.stderr)
        return TimeoutResult(
            returncode=-1,
            stdout=partial_stdout,
            stderr=partial_stderr,
            duration_ms=duration_ms,
            timed_out=True,
        )
    except OSError as exc:
        # Launch failure (e.g. FileNotFoundError/WinError 2 for a missing or
        # mangled executable): mirror the structured failed-result shape of
        # the timeout branch rather than leaking a raw traceback to callers.
        duration_ms = (time.monotonic() - start) * 1000.0
        executable = argv[0] if argv else ""
        return TimeoutResult(
            returncode=-1,
            stdout="",
            stderr=f"Failed to launch subprocess {executable!r}: {exc}",
            duration_ms=duration_ms,
            timed_out=False,
        )


def _coerce_output(value: str | bytes | None) -> str:
    """Normalize subprocess output to ``str`` regardless of text/binary mode."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
