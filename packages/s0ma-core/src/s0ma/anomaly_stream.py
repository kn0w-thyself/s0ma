"""Runtime anomaly stream — push-based delivery of live anomalies.

Poll-based verification (``s0ma.verify``, the interoception monitor)
answers "what is wrong right now?" when asked. Long-running and embodied
hosts also need the converse: to hear about a problem the moment a
detector sees it, without a polling timer. This module is that channel — a
process-wide subscription surface that runtime detectors publish into.

Publishers today:

- The ``precondition``/``postcondition`` decorators publish a NOCICEPTION
  anomaly at the moment a live call violates an executable contract,
  immediately before raising ``ContractViolationError`` — so subscribers
  hear the pain signal even when the caller swallows the exception.
- ``MetricsCollector.record_physical`` publishes INFLAMMATION anomalies
  when a reported physical reading crosses a declared ``ResourceProfile``
  bound (ADR-003 §4/§5).

The stream mirrors ``ComponentRegistry.subscribe_import_hook_anomalies``:
synchronous dispatch in registration order, subscriber exceptions logged
and swallowed so one bad callback cannot blackhole the rest, and
zero-argument unsubscribe closures. Dispatch happens on the detecting
call's thread, outside the internal lock — keep callbacks short and hand
heavy work to a queue or executor.

This module is dependency-free at runtime (annotations only), so any
layer may publish into it without import-cycle risk.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from s0ma.models import Anomaly

__all__ = [
    "subscribe_runtime_anomalies",
    "emit_runtime_anomaly",
    "reset_runtime_anomaly_subscribers",
]

logger = logging.getLogger(__name__)

_subscribers: list[Callable[[Anomaly], None]] = []
_lock = threading.Lock()


def subscribe_runtime_anomalies(
    callback: Callable[[Anomaly], None],
) -> Callable[[], None]:
    """Register a callback invoked on every runtime anomaly published.

    ``callback`` runs synchronously on the thread of whatever detector
    published the anomaly (a failing contract-decorated call, a physical
    reading crossing its bound). Subscribers run in registration order;
    an exception raised by one is logged and swallowed so the remaining
    subscribers are still notified.

    Args:
        callback: A callable receiving the freshly-detected
            :class:`~s0ma.models.Anomaly`. Keep the body short — it runs
            inside the failing call path. For heavier work, hand the
            anomaly off to a queue or executor.

    Returns:
        A zero-argument unsubscribe function. Calling it more than once
        is a no-op.
    """
    with _lock:
        _subscribers.append(callback)

    def _unsubscribe() -> None:
        # Suppressed ValueError means already unsubscribed — repeated
        # calls are a no-op so callers can hold the handle freely.
        with _lock, contextlib.suppress(ValueError):
            _subscribers.remove(callback)

    return _unsubscribe


def emit_runtime_anomaly(anomaly: Anomaly) -> None:
    """Publish an anomaly to every current subscriber.

    Detectors inside s0ma (contract decorators, physical-bound checks)
    call this at the moment of detection; applications may also publish
    their own runtime anomalies through it. The subscriber list is
    snapshotted under the lock, then dispatch happens outside it, so a
    subscriber may itself subscribe/unsubscribe without deadlocking.
    """
    with _lock:
        subscribers = list(_subscribers)
    for callback in subscribers:
        try:
            callback(anomaly)
        except Exception:  # noqa: BLE001 — subscriber isolation
            logger.exception(
                "Runtime anomaly subscriber %r raised; remaining "
                "subscribers will still be notified.",
                callback,
            )


def reset_runtime_anomaly_subscribers() -> None:
    """Remove every subscriber. Intended for test isolation."""
    with _lock:
        _subscribers.clear()
