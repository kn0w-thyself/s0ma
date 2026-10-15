"""Tests for the runtime anomaly stream — hw-foundation M1.

Validates the push-based anomaly channel itself: subscription, dispatch
order, subscriber isolation, idempotent unsubscribe, self-unsubscribe
during dispatch, and reset. Publisher-side integration is covered in
test_contract_verifier.py (NOCICEPTION on contract violations) and
test_interoception.py (INFLAMMATION on physical bound crossings).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from s0ma.anomaly_stream import (
    emit_runtime_anomaly,
    reset_runtime_anomaly_subscribers,
    subscribe_runtime_anomalies,
)
from s0ma.models import Anomaly
from s0ma.types import AnomalyKind, AnomalySeverity

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture(autouse=True)
def _reset_stream() -> None:
    """Isolate subscribers between tests."""
    yield  # type: ignore[misc]
    reset_runtime_anomaly_subscribers()


def _make_anomaly(message: str = "test anomaly") -> Anomaly:
    """Build a minimal anomaly for stream tests."""
    return Anomaly(
        kind=AnomalyKind.NOCICEPTION,
        severity=AnomalySeverity.ERROR,
        component_name="TestComponent",
        message=message,
    )


class TestRuntimeAnomalyStream:
    """Behavior of subscribe/emit/reset on the process-wide stream."""

    def test_subscriber_receives_emitted_anomaly(self) -> None:
        """A subscriber sees exactly the emitted anomaly object."""
        received: list[Anomaly] = []
        subscribe_runtime_anomalies(received.append)

        anomaly = _make_anomaly()
        emit_runtime_anomaly(anomaly)

        assert received == [anomaly]

    def test_subscribers_dispatch_in_registration_order(self) -> None:
        """Dispatch preserves registration order."""
        order: list[str] = []
        subscribe_runtime_anomalies(lambda _a: order.append("first"))
        subscribe_runtime_anomalies(lambda _a: order.append("second"))

        emit_runtime_anomaly(_make_anomaly())

        assert order == ["first", "second"]

    def test_unsubscribe_stops_delivery(self) -> None:
        """After unsubscribing, no further anomalies are delivered."""
        received: list[Anomaly] = []
        unsubscribe = subscribe_runtime_anomalies(received.append)

        unsubscribe()
        emit_runtime_anomaly(_make_anomaly())

        assert received == []

    def test_unsubscribe_is_idempotent(self) -> None:
        """Calling the unsubscribe handle twice is a no-op."""
        unsubscribe = subscribe_runtime_anomalies(lambda _a: None)
        unsubscribe()
        unsubscribe()

    def test_emit_without_subscribers_is_noop(self) -> None:
        """Emitting into an empty stream must not raise."""
        emit_runtime_anomaly(_make_anomaly())

    def test_bad_subscriber_does_not_block_others(self) -> None:
        """A raising subscriber is isolated; later subscribers still run."""
        received: list[Anomaly] = []

        def _explode(_anomaly: Anomaly) -> None:
            raise RuntimeError("subscriber bug")

        subscribe_runtime_anomalies(_explode)
        subscribe_runtime_anomalies(received.append)

        emit_runtime_anomaly(_make_anomaly())

        assert len(received) == 1

    def test_subscriber_may_unsubscribe_itself_during_dispatch(self) -> None:
        """Dispatch happens outside the lock — self-removal is safe."""
        received: list[Anomaly] = []
        handles: list[Callable[[], None]] = []

        def _once(anomaly: Anomaly) -> None:
            received.append(anomaly)
            handles[0]()

        handles.append(subscribe_runtime_anomalies(_once))

        emit_runtime_anomaly(_make_anomaly("first"))
        emit_runtime_anomaly(_make_anomaly("second"))

        assert [a.message for a in received] == ["first"]

    def test_reset_clears_all_subscribers(self) -> None:
        """reset_runtime_anomaly_subscribers removes every subscriber."""
        received: list[Anomaly] = []
        subscribe_runtime_anomalies(received.append)

        reset_runtime_anomaly_subscribers()
        emit_runtime_anomaly(_make_anomaly())

        assert received == []
