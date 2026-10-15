"""Example discovery + execution subsystem (plan M6).

Registered ``example`` declarations describe runnable code that
demonstrates one or more components. This subpackage discovers those
registrations via ``RegistrySnapshot.examples`` and executes each body
in an isolated subprocess, with per-example timeout enforcement and
structured result reporting.

Typical usage::

    from s0ma.examples import ExampleRunner

    runner = ExampleRunner(registry, timeout_seconds=30)
    for result in runner.run_all():
        print(result.summary())

The pytest plugin (activated by ``--s0ma-examples``) plugs the same
runner into the host project's test session so that ``pytest`` on the
s0ma-core repo can exercise registered examples alongside its regular
test suite.
"""

from s0ma.examples.dispatcher import (
    INTEGRATION_CMD_ENV_VAR,
    DispatchOutcome,
    ExampleDispatcher,
)
from s0ma.examples.runner import ExampleResult, ExampleRunner, run_all_examples
from s0ma.examples.timeout import (
    DEFAULT_TIMEOUT_SECONDS,
    TimeoutResult,
    run_subprocess_with_timeout,
)

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "INTEGRATION_CMD_ENV_VAR",
    "DispatchOutcome",
    "ExampleDispatcher",
    "ExampleResult",
    "ExampleRunner",
    "TimeoutResult",
    "run_all_examples",
    "run_subprocess_with_timeout",
]
