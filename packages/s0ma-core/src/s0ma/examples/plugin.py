"""Opt-in pytest plugin that runs registered examples as test items.

Activated by ``--s0ma-examples``. When the flag is absent the plugin is
a no-op so that installing ``s0ma-core`` never surprises an
unrelated pytest run. This matches the v1 design in
the docs-subsystem plan (internal) M6 and the
resolution recorded for §11's open-question on opt-in vs. opt-out.

Each registered example becomes one pytest item named
``s0ma-example::<example-name>`` and is attached to the session root.
A failing example's captured stdout, stderr, and error summary are
routed through ``pytest.fail`` so they render in the standard report.

``s0ma.examples.plugin`` imports ``pytest`` at module load time.
s0ma-core declares pytest only as a dev extra; the plugin module is
loaded exclusively through pytest's ``pytest11`` entry-point discovery,
so by the time this import runs, pytest is already available.
"""

from __future__ import annotations

import pytest

from s0ma.examples.runner import ExampleRunner
from s0ma.examples.timeout import DEFAULT_TIMEOUT_SECONDS
from s0ma.registry import get_registry

__all__ = [
    "pytest_addoption",
    "pytest_collection_modifyitems",
]

_FLAG_NAME: str = "--s0ma-examples"
_INI_KEY: str = "s0ma_example_timeout"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--s0ma-examples`` flag and its timeout ini key."""
    group = parser.getgroup("s0ma", "s0ma example-execution plugin")
    group.addoption(
        _FLAG_NAME,
        action="store_true",
        default=False,
        help=(
            "Discover and execute s0ma registered examples as part of "
            "the test session (opt-in)."
        ),
    )
    parser.addini(
        _INI_KEY,
        type="string",
        default=str(DEFAULT_TIMEOUT_SECONDS),
        help="Per-example timeout in seconds when --s0ma-examples is enabled.",
    )


def pytest_collection_modifyitems(
    session: pytest.Session,
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Append one synthetic item per registered example when opted-in."""
    if not config.getoption(_FLAG_NAME, default=False):
        return

    timeout_seconds = _coerce_timeout(config.getini(_INI_KEY))
    registry = get_registry(persist=False)
    runner = ExampleRunner(registry, timeout_seconds=timeout_seconds)

    for example in runner.discover():
        item = _S0maExampleItem.from_parent(
            session,
            name=f"s0ma-example::{example.name}",
            runner=runner,
            example_name=example.name,
        )
        items.append(item)


class _S0maExampleItem(pytest.Item):
    """pytest item that delegates execution to :class:`ExampleRunner`."""

    def __init__(
        self,
        *,
        name: str,
        parent: pytest.Session | pytest.Collector,
        runner: ExampleRunner,
        example_name: str,
    ) -> None:
        super().__init__(name, parent)
        self._runner = runner
        self._example_name = example_name

    def runtest(self) -> None:
        example = self._runner.registry.get_example(self._example_name)
        if example is None:
            pytest.fail(f"Example '{self._example_name}' is not registered")
            return
        result = self._runner.run(example)
        if not result.passed:
            pytest.fail(
                f"{result.summary()}\n"
                f"--- stdout ---\n{result.stdout}\n"
                f"--- stderr ---\n{result.stderr}\n"
                f"--- error ---\n{result.error or ''}"
            )

    def reportinfo(self) -> tuple[str, int, str]:
        return (self._example_name, 0, self.name)


def _coerce_timeout(raw: object) -> float:
    try:
        return float(str(raw))
    except (TypeError, ValueError):
        return float(DEFAULT_TIMEOUT_SECONDS)
