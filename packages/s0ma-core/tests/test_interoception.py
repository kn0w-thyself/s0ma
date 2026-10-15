"""Tests for the interoception monitor — Milestone 4 of Phase 2.

Validates the runtime monitoring layer that captures per-component
performance metrics and compares them against declared ResourceProfile
expectations. Tests cover:

- MetricsCollector: recording, thread safety, percentiles, windowing
- Instrumentation: decorator and context manager
- InteroceptionVerifier: threshold comparison, anomaly production
- DangerSignal: criticality scoring
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import pytest

from s0ma.anomaly_stream import (
    reset_runtime_anomaly_subscribers,
    subscribe_runtime_anomalies,
)
from s0ma.models import Anomaly, ComponentSpec, ResourceProfile
from s0ma.registry import ComponentRegistry
from s0ma.types import (
    AnomalyKind,
    AnomalySeverity,
    ComponentKind,
    Layer,
    VerificationScope,
)
from s0ma.verifiers.interoception import (
    ComponentMetrics,
    DangerSignal,
    InteroceptionVerifier,
    MetricsCollector,
    compute_danger_signals,
    instrument,
    monitor_call,
    reset_metrics_collector,
)

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def _reset_interoception() -> Generator[None, None, None]:
    """Reset the global metrics collector after each test."""
    yield
    reset_metrics_collector()


@pytest.fixture()
def collector() -> MetricsCollector:
    """Fresh MetricsCollector for testing."""
    return MetricsCollector()


@pytest.fixture()
def registry_with_profiles() -> ComponentRegistry:
    """Registry with components that have ResourceProfiles."""
    reg = ComponentRegistry(persist=False)
    reg.register(ComponentSpec(
        name="FastService",
        kind=ComponentKind.SERVICE,
        layer=Layer.DOMAIN,
        intent="A fast service that processes requests quickly",
        resource_profile=ResourceProfile(
            expected_latency_p50_ms=10.0,
            expected_latency_p99_ms=50.0,
            expected_error_rate=0.01,
            expected_call_frequency_per_min=100.0,
        ),
        module_path="test.fast",
        qualified_name="test.fast.FastService",
    ))
    reg.register(ComponentSpec(
        name="SlowService",
        kind=ComponentKind.SERVICE,
        layer=Layer.DOMAIN,
        intent="A service that is allowed to be slow",
        resource_profile=ResourceProfile(
            expected_latency_p50_ms=500.0,
            expected_latency_p99_ms=2000.0,
            expected_error_rate=0.05,
        ),
        module_path="test.slow",
        qualified_name="test.slow.SlowService",
    ))
    reg.register(ComponentSpec(
        name="UnmonitoredService",
        kind=ComponentKind.SERVICE,
        layer=Layer.DOMAIN,
        intent="A service with no resource profile",
        module_path="test.unmon",
        qualified_name="test.unmon.UnmonitoredService",
    ))
    return reg


# ======================================================================
# MetricsCollector tests
# ======================================================================


class TestMetricsCollector:
    """Tests for the MetricsCollector class."""

    def test_record_call_creates_entry(self, collector: MetricsCollector) -> None:
        """Recording a call creates a metrics entry for the component."""
        collector.record_call("TestComp", latency_ns=1_000_000)
        metrics = collector.get_metrics("TestComp")
        assert metrics is not None
        assert metrics.call_count == 1
        assert metrics.error_count == 0
        assert len(metrics.latencies_ns) == 1

    def test_record_multiple_calls(self, collector: MetricsCollector) -> None:
        """Multiple calls increment counts correctly."""
        collector.record_call("TestComp", latency_ns=1_000_000)
        collector.record_call("TestComp", latency_ns=2_000_000)
        collector.record_call("TestComp", latency_ns=3_000_000, error=True)
        metrics = collector.get_metrics("TestComp")
        assert metrics is not None
        assert metrics.call_count == 3
        assert metrics.error_count == 1
        assert len(metrics.latencies_ns) == 3

    def test_error_recording(self, collector: MetricsCollector) -> None:
        """Error flag increments error_count."""
        collector.record_call("TestComp", latency_ns=1_000_000, error=True)
        collector.record_call("TestComp", latency_ns=1_000_000, error=True)
        collector.record_call("TestComp", latency_ns=1_000_000, error=False)
        metrics = collector.get_metrics("TestComp")
        assert metrics is not None
        assert metrics.error_count == 2
        assert metrics.error_rate == pytest.approx(2 / 3)

    def test_get_metrics_unknown_component(self, collector: MetricsCollector) -> None:
        """Getting metrics for unknown component returns None."""
        assert collector.get_metrics("Unknown") is None

    def test_get_all_metrics(self, collector: MetricsCollector) -> None:
        """get_all_metrics returns all tracked components."""
        collector.record_call("A", latency_ns=1_000_000)
        collector.record_call("B", latency_ns=2_000_000)
        all_metrics = collector.get_all_metrics()
        assert len(all_metrics) == 2
        assert "A" in all_metrics
        assert "B" in all_metrics

    def test_reset_clears_all(self, collector: MetricsCollector) -> None:
        """Reset clears all metrics."""
        collector.record_call("A", latency_ns=1_000_000)
        collector.record_call("B", latency_ns=2_000_000)
        collector.reset()
        assert collector.get_all_metrics() == {}
        assert collector.get_metrics("A") is None

    def test_reset_component(self, collector: MetricsCollector) -> None:
        """Resetting a single component clears only that component."""
        collector.record_call("A", latency_ns=1_000_000)
        collector.record_call("B", latency_ns=2_000_000)
        collector.reset_component("A")
        assert collector.get_metrics("A") is None
        assert collector.get_metrics("B") is not None

    def test_thread_safety(self, collector: MetricsCollector) -> None:
        """Concurrent recordings across 10 threads are thread-safe."""
        n_threads = 10
        calls_per_thread = 100
        barrier = threading.Barrier(n_threads)

        def record_calls() -> None:
            barrier.wait()
            for i in range(calls_per_thread):
                collector.record_call(
                    "ConcurrentComp",
                    latency_ns=i * 1000,
                    error=(i % 10 == 0),
                )

        threads = [threading.Thread(target=record_calls) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        metrics = collector.get_metrics("ConcurrentComp")
        assert metrics is not None
        assert metrics.call_count == n_threads * calls_per_thread
        # Each thread produces calls_per_thread / 10 errors
        expected_errors = n_threads * (calls_per_thread // 10)
        assert metrics.error_count == expected_errors

    def test_last_call_timestamp(self, collector: MetricsCollector) -> None:
        """Recording a call sets last_call_at."""
        collector.record_call("TestComp", latency_ns=1_000_000)
        metrics = collector.get_metrics("TestComp")
        assert metrics is not None
        assert metrics.last_call_at is not None


# ======================================================================
# ComponentMetrics tests
# ======================================================================


class TestComponentMetrics:
    """Tests for ComponentMetrics computed properties."""

    def test_error_rate_zero_calls(self) -> None:
        """Error rate is 0.0 when no calls recorded."""
        metrics = ComponentMetrics(component_name="Test")
        assert metrics.error_rate == 0.0

    def test_latency_p50_known_distribution(self) -> None:
        """P50 matches expected value for a known distribution."""
        metrics = ComponentMetrics(component_name="Test")
        # Add 100 values: 1ms to 100ms (in nanoseconds)
        for i in range(1, 101):
            metrics.latencies_ns.append(i * 1_000_000)
        # Median of 1..100 should be ~50.5ms
        assert 50.0 <= metrics.latency_p50_ms <= 51.0

    def test_latency_p99_known_distribution(self) -> None:
        """P99 matches expected value for a known distribution."""
        metrics = ComponentMetrics(component_name="Test")
        for i in range(1, 101):
            metrics.latencies_ns.append(i * 1_000_000)
        # P99 of 1..100 should be ~99.01ms
        assert metrics.latency_p99_ms >= 99.0

    def test_latency_empty(self) -> None:
        """Latency percentiles are 0.0 when no data."""
        metrics = ComponentMetrics(component_name="Test")
        assert metrics.latency_p50_ms == 0.0
        assert metrics.latency_p99_ms == 0.0
        assert metrics.latency_p95_ms == 0.0

    def test_latency_single_value(self) -> None:
        """Single latency value returns that value for all percentiles."""
        metrics = ComponentMetrics(component_name="Test")
        metrics.latencies_ns.append(5_000_000)  # 5ms
        assert metrics.latency_p50_ms == pytest.approx(5.0)
        assert metrics.latency_p99_ms == pytest.approx(5.0)

    def test_to_dict_serialization(self) -> None:
        """ComponentMetrics.to_dict() produces all expected keys."""
        metrics = ComponentMetrics(component_name="Test")
        metrics.latencies_ns.append(1_000_000)
        metrics.call_count = 1
        d = metrics.to_dict()
        assert d["component_name"] == "Test"
        assert "call_count" in d
        assert "error_rate" in d
        assert "latency_p50_ms" in d
        assert "latency_p99_ms" in d
        assert "sample_count" in d


# ======================================================================
# Instrumentation tests
# ======================================================================


class TestInstrumentDecorator:
    """Tests for the @instrument decorator."""

    def test_captures_timing(self, collector: MetricsCollector) -> None:
        """Instrumented function records call timing."""

        @instrument("test.func", collector)
        def slow_func() -> str:
            time.sleep(0.01)  # 10ms
            return "done"

        result = slow_func()
        assert result == "done"
        metrics = collector.get_metrics("test.func")
        assert metrics is not None
        assert metrics.call_count == 1
        assert metrics.latencies_ns[0] >= 9_000_000  # At least ~9ms

    def test_captures_errors(self, collector: MetricsCollector) -> None:
        """Instrumented function records errors."""

        @instrument("test.error_func", collector)
        def failing_func() -> None:
            msg = "intentional"
            raise ValueError(msg)

        with pytest.raises(ValueError, match="intentional"):
            failing_func()

        metrics = collector.get_metrics("test.error_func")
        assert metrics is not None
        assert metrics.call_count == 1
        assert metrics.error_count == 1

    def test_preserves_function_identity(self, collector: MetricsCollector) -> None:
        """Instrumented function preserves __name__ and __doc__."""

        @instrument("test.named_func", collector)
        def my_function() -> None:
            """My docstring."""

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."


class TestMonitorCall:
    """Tests for the monitor_call context manager."""

    def test_captures_timing(self, collector: MetricsCollector) -> None:
        """Context manager records call timing."""
        with monitor_call("test.ctx", collector) as ctx:
            time.sleep(0.01)  # 10ms

        assert ctx.latency_ns >= 9_000_000  # At least ~9ms
        metrics = collector.get_metrics("test.ctx")
        assert metrics is not None
        assert metrics.call_count == 1

    def test_captures_errors(self, collector: MetricsCollector) -> None:
        """Context manager records errors from exceptions."""
        with pytest.raises(ValueError, match="ctx_error"), monitor_call("test.ctx_err", collector):
            msg = "ctx_error"
            raise ValueError(msg)

        metrics = collector.get_metrics("test.ctx_err")
        assert metrics is not None
        assert metrics.error_count == 1

    def test_latency_available_on_context(self, collector: MetricsCollector) -> None:
        """Context object exposes latency_ns after exit."""
        with monitor_call("test.ctx_lat", collector) as ctx:
            pass
        assert ctx.latency_ns > 0


# ======================================================================
# Physical gauges (ADR-003 §4) — record_physical + verifier coverage
# ======================================================================


class TestPhysicalGauges:
    """Physical gauge ingestion, bound checks, and stream emission."""

    @pytest.fixture(autouse=True)
    def _reset_stream(self) -> None:
        """Isolate runtime-anomaly subscribers between tests."""
        yield  # type: ignore[misc]
        reset_runtime_anomaly_subscribers()

    def test_record_physical_stores_gauges(
        self, collector: MetricsCollector
    ) -> None:
        """Reported readings land as latest-value gauges."""
        collector.record_physical(
            "Servo", current_ma=120.0, temperature_c=41.5, voltage_v=5.1
        )
        metrics = collector.get_metrics("Servo")
        assert metrics is not None
        assert metrics.current_ma == 120.0
        assert metrics.temperature_c == 41.5
        assert metrics.voltage_v == 5.1

    def test_record_physical_partial_update_keeps_other_gauges(
        self, collector: MetricsCollector
    ) -> None:
        """Partial reports update only the reported gauges."""
        collector.record_physical("Servo", current_ma=120.0, voltage_v=5.1)
        collector.record_physical("Servo", temperature_c=39.0)
        metrics = collector.get_metrics("Servo")
        assert metrics is not None
        assert metrics.current_ma == 120.0
        assert metrics.temperature_c == 39.0
        assert metrics.voltage_v == 5.1

    def test_to_dict_includes_physical_gauges(
        self, collector: MetricsCollector
    ) -> None:
        """Serialized metrics carry the gauge fields."""
        collector.record_physical("Servo", current_ma=120.0)
        metrics = collector.get_metrics("Servo")
        assert metrics is not None
        data = metrics.to_dict()
        assert data["current_ma"] == 120.0
        assert data["temperature_c"] is None
        assert data["voltage_v"] is None

    def test_record_physical_without_profile_returns_no_anomalies(
        self, collector: MetricsCollector
    ) -> None:
        """No profile means storage only — no checks, no anomalies."""
        assert collector.record_physical("Servo", current_ma=999.0) == []

    def test_record_physical_checks_bounds_and_emits(
        self, collector: MetricsCollector
    ) -> None:
        """Crossed bounds return INFLAMMATION and publish on the stream."""
        received: list[Anomaly] = []
        subscribe_runtime_anomalies(received.append)

        profile = ResourceProfile(
            expected_max_current_ma=350.0,
            expected_min_voltage_v=4.8,
        )
        anomalies = collector.record_physical(
            "Servo", current_ma=520.0, voltage_v=4.5, profile=profile
        )

        assert {a.details["metric"] for a in anomalies} == {
            "current_ma",
            "voltage_v",
        }
        assert all(a.kind is AnomalyKind.INFLAMMATION for a in anomalies)
        assert all(a.severity is AnomalySeverity.WARNING for a in anomalies)
        assert received == anomalies

    def test_record_physical_within_bounds_is_quiet(
        self, collector: MetricsCollector
    ) -> None:
        """Readings inside every declared bound produce nothing."""
        profile = ResourceProfile(
            expected_max_current_ma=350.0,
            expected_max_temperature_c=75.0,
            expected_min_voltage_v=4.8,
        )
        anomalies = collector.record_physical(
            "Servo",
            current_ma=200.0,
            temperature_c=44.0,
            voltage_v=5.1,
            profile=profile,
        )
        assert anomalies == []

    def test_record_physical_only_checks_reported_readings(
        self, collector: MetricsCollector
    ) -> None:
        """A stored older gauge is not re-checked by a later partial report."""
        profile = ResourceProfile(expected_max_current_ma=350.0)
        collector.record_physical("Servo", current_ma=520.0)
        anomalies = collector.record_physical(
            "Servo", voltage_v=5.0, profile=profile
        )
        assert anomalies == []

    def _door_servo_registry(self) -> ComponentRegistry:
        reg = ComponentRegistry(persist=False)
        reg.register(ComponentSpec(
            name="DoorServo",
            kind=ComponentKind.SERVICE,
            layer=Layer.INFRASTRUCTURE,
            intent="Drives a cargo-door hinge servo within physical bounds",
            resource_profile=ResourceProfile(
                expected_max_current_ma=350.0,
                expected_max_temperature_c=75.0,
                expected_min_voltage_v=4.8,
            ),
            module_path="test.door",
            qualified_name="test.door.DoorServo",
        ))
        return reg

    def test_verifier_flags_physical_bound_breaches(self) -> None:
        """verify() reports crossed physical bounds as INFLAMMATION."""
        reg = self._door_servo_registry()
        collector = MetricsCollector()
        collector.record_call("DoorServo", latency_ns=1_000_000)
        collector.record_physical(
            "DoorServo", current_ma=520.0, temperature_c=60.0, voltage_v=4.5
        )

        verifier = InteroceptionVerifier(collector=collector)
        result = verifier.verify(reg)

        physical = [
            a for a in result.anomalies
            if a.details.get("metric")
            in {"current_ma", "temperature_c", "voltage_v"}
        ]
        assert {a.details["metric"] for a in physical} == {
            "current_ma",
            "voltage_v",
        }
        assert all(a.kind is AnomalyKind.INFLAMMATION for a in physical)

    def test_verifier_checks_gauges_only_component(self) -> None:
        """A component that only reports gauges is checked, not flagged idle."""
        reg = self._door_servo_registry()
        collector = MetricsCollector()
        collector.record_physical("DoorServo", voltage_v=4.5)

        verifier = InteroceptionVerifier(collector=collector)
        result = verifier.verify(reg)

        vestigial = [
            a for a in result.anomalies
            if a.kind is AnomalyKind.VESTIGIAL_ORGAN
        ]
        assert vestigial == []
        breaches = [
            a for a in result.anomalies
            if a.details.get("metric") == "voltage_v"
        ]
        assert len(breaches) == 1

    def test_verify_incremental_covers_physical_bounds(self) -> None:
        """Incremental verification runs the same physical checks."""
        reg = self._door_servo_registry()
        collector = MetricsCollector()
        collector.record_physical("DoorServo", current_ma=520.0)

        verifier = InteroceptionVerifier(collector=collector)
        result = verifier.verify_incremental(reg, "DoorServo")

        breaches = [
            a for a in result.anomalies
            if a.details.get("metric") == "current_ma"
        ]
        assert len(breaches) == 1
        assert breaches[0].kind is AnomalyKind.INFLAMMATION


# ======================================================================
# InteroceptionVerifier tests
# ======================================================================


class TestInteroceptionVerifier:
    """Tests for the InteroceptionVerifier class."""

    def test_scope_is_interoception(self, collector: MetricsCollector) -> None:
        """Verifier scope is INTEROCEPTION."""
        verifier = InteroceptionVerifier(collector=collector)
        assert verifier.scope == VerificationScope.INTEROCEPTION
        assert verifier.name == "Interoception Monitor"

    def test_skips_components_without_profile(
        self,
        collector: MetricsCollector,
    ) -> None:
        """Components without ResourceProfile produce no anomalies."""
        reg = ComponentRegistry(persist=False)
        reg.register(ComponentSpec(
            name="NoProfile",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A service with no resource profile at all",
            module_path="test.no",
            qualified_name="test.no.NoProfile",
        ))
        verifier = InteroceptionVerifier(collector=collector)
        result = verifier.verify(reg)
        assert result.passed
        assert result.components_checked == 0
        assert len(result.anomalies) == 0

    def test_reports_info_for_profiled_no_metrics(
        self,
        collector: MetricsCollector,
        registry_with_profiles: ComponentRegistry,
    ) -> None:
        """Profiled component with no metrics gets INFO anomaly."""
        verifier = InteroceptionVerifier(collector=collector)
        result = verifier.verify(registry_with_profiles)
        # FastService and SlowService have profiles but no metrics
        info_anomalies = [
            a for a in result.anomalies
            if a.severity == AnomalySeverity.INFO
            and a.kind == AnomalyKind.VESTIGIAL_ORGAN
        ]
        assert len(info_anomalies) == 2  # FastService + SlowService

    def test_detects_latency_p50_exceeded(
        self,
        collector: MetricsCollector,
        registry_with_profiles: ComponentRegistry,
    ) -> None:
        """Detects when latency p50 exceeds expected threshold."""
        # FastService expects p50 <= 10ms, simulate 20ms calls
        for _ in range(10):
            collector.record_call("FastService", latency_ns=20_000_000)

        verifier = InteroceptionVerifier(collector=collector)
        result = verifier.verify(registry_with_profiles)
        inflammation = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.INFLAMMATION
            and a.component_name == "FastService"
            and "p50" in a.message
        ]
        assert len(inflammation) >= 1

    def test_detects_latency_p99_exceeded(
        self,
        collector: MetricsCollector,
        registry_with_profiles: ComponentRegistry,
    ) -> None:
        """Detects when latency p99 exceeds expected threshold."""
        # FastService expects p99 <= 50ms, simulate mostly fast with spikes
        for _ in range(90):
            collector.record_call("FastService", latency_ns=5_000_000)  # 5ms
        for _ in range(10):
            collector.record_call("FastService", latency_ns=100_000_000)  # 100ms

        verifier = InteroceptionVerifier(collector=collector)
        result = verifier.verify(registry_with_profiles)
        inflammation = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.INFLAMMATION
            and a.component_name == "FastService"
            and "p99" in a.message
        ]
        assert len(inflammation) >= 1

    def test_detects_error_rate_exceeded(
        self,
        collector: MetricsCollector,
        registry_with_profiles: ComponentRegistry,
    ) -> None:
        """Detects when error rate exceeds expected threshold."""
        # FastService expects error rate <= 1%, simulate 10%
        for _ in range(90):
            collector.record_call("FastService", latency_ns=5_000_000)
        for _ in range(10):
            collector.record_call("FastService", latency_ns=5_000_000, error=True)

        verifier = InteroceptionVerifier(collector=collector)
        result = verifier.verify(registry_with_profiles)
        inflammation = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.INFLAMMATION
            and a.component_name == "FastService"
            and "error rate" in a.message
        ]
        assert len(inflammation) == 1

    def test_passes_for_healthy_component(
        self,
        collector: MetricsCollector,
        registry_with_profiles: ComponentRegistry,
    ) -> None:
        """No WARNING/ERROR anomalies for a component within thresholds."""
        # FastService within all limits: p50 < 10ms, p99 < 50ms, errors < 1%
        for _ in range(100):
            collector.record_call("FastService", latency_ns=5_000_000)  # 5ms

        verifier = InteroceptionVerifier(collector=collector)
        result = verifier.verify(registry_with_profiles)
        # Only check WARNING/ERROR severity — rapid test calls will
        # naturally produce an anomalous calls_per_minute (INFO)
        fast_anomalies = [
            a for a in result.anomalies
            if a.component_name == "FastService"
            and a.kind == AnomalyKind.INFLAMMATION
            and a.severity in (AnomalySeverity.WARNING, AnomalySeverity.ERROR)
        ]
        assert len(fast_anomalies) == 0

    def test_verify_incremental_known_component(
        self,
        collector: MetricsCollector,
        registry_with_profiles: ComponentRegistry,
    ) -> None:
        """Incremental verification checks a single component."""
        for _ in range(10):
            collector.record_call("FastService", latency_ns=20_000_000)  # 20ms

        verifier = InteroceptionVerifier(collector=collector)
        result = verifier.verify_incremental(registry_with_profiles, "FastService")
        assert result.components_checked == 1
        # Should detect p50 exceeded
        assert any(
            a.kind == AnomalyKind.INFLAMMATION for a in result.anomalies
        )

    def test_verify_incremental_unknown_component(
        self,
        collector: MetricsCollector,
        registry_with_profiles: ComponentRegistry,
    ) -> None:
        """Incremental verification for unknown component returns error."""
        verifier = InteroceptionVerifier(collector=collector)
        result = verifier.verify_incremental(registry_with_profiles, "Unknown")
        assert not result.passed
        assert any(a.kind == AnomalyKind.PHANTOM_LIMB for a in result.anomalies)

    def test_verify_incremental_no_profile(
        self,
        collector: MetricsCollector,
        registry_with_profiles: ComponentRegistry,
    ) -> None:
        """Incremental verification for component without profile is clean."""
        verifier = InteroceptionVerifier(collector=collector)
        result = verifier.verify_incremental(
            registry_with_profiles, "UnmonitoredService"
        )
        assert result.passed
        assert result.components_checked == 1
        assert len(result.anomalies) == 0

    def test_empty_registry(self, collector: MetricsCollector) -> None:
        """Verifier handles empty registry gracefully."""
        reg = ComponentRegistry(persist=False)
        verifier = InteroceptionVerifier(collector=collector)
        result = verifier.verify(reg)
        assert result.passed
        assert result.components_checked == 0

    def test_danger_signals_in_details(
        self,
        collector: MetricsCollector,
        registry_with_profiles: ComponentRegistry,
    ) -> None:
        """Verify result includes danger signals in details."""
        for _ in range(10):
            collector.record_call("FastService", latency_ns=5_000_000)

        verifier = InteroceptionVerifier(collector=collector)
        result = verifier.verify(registry_with_profiles)
        assert "danger_signals" in result.details


# ======================================================================
# DangerSignal tests
# ======================================================================


class TestDangerSignal:
    """Tests for the DangerSignal computation."""

    def test_computation_produces_signals(
        self,
        collector: MetricsCollector,
        registry_with_profiles: ComponentRegistry,
    ) -> None:
        """compute_danger_signals returns signals for profiled components."""
        collector.record_call("FastService", latency_ns=5_000_000)
        signals = compute_danger_signals(registry_with_profiles, collector)
        # Should have signals for FastService and SlowService (both have profiles)
        assert len(signals) == 2
        names = {s.component_name for s in signals}
        assert "FastService" in names
        assert "SlowService" in names

    def test_signals_sorted_by_criticality(
        self,
        collector: MetricsCollector,
        registry_with_profiles: ComponentRegistry,
    ) -> None:
        """Signals are sorted by criticality_score descending."""
        # Give FastService many error calls to increase its criticality
        for _ in range(100):
            collector.record_call("FastService", latency_ns=5_000_000, error=True)

        signals = compute_danger_signals(registry_with_profiles, collector)
        for i in range(len(signals) - 1):
            assert signals[i].criticality_score >= signals[i + 1].criticality_score

    def test_signal_to_dict(self) -> None:
        """DangerSignal serializes to dict correctly."""
        signal = DangerSignal(
            component_name="Test",
            dependency_count=3,
            error_rate_recent=0.05,
            call_count_recent=100,
            criticality_score=6.5,
        )
        d = signal.to_dict()
        assert d["component_name"] == "Test"
        assert d["dependency_count"] == 3
        assert d["criticality_score"] == 6.5

    def test_no_signals_for_unmonitored(
        self,
        collector: MetricsCollector,
    ) -> None:
        """Components without ResourceProfile don't get danger signals."""
        reg = ComponentRegistry(persist=False)
        reg.register(ComponentSpec(
            name="NoProfile",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A service with no resource profile at all",
            module_path="test.no",
            qualified_name="test.no.NoProfile",
        ))
        signals = compute_danger_signals(reg, collector)
        assert len(signals) == 0


# ======================================================================
# Metrics window / overflow tests
# ======================================================================


class TestMetricsWindow:
    """Tests for metrics windowing and ring buffer behavior."""

    def test_ring_buffer_overflow(self) -> None:
        """Ring buffer discards oldest entries when full."""
        collector = MetricsCollector(max_samples=5)
        for i in range(10):
            collector.record_call("Test", latency_ns=(i + 1) * 1_000_000)

        metrics = collector.get_metrics("Test")
        assert metrics is not None
        assert metrics.call_count == 10  # Count not capped
        assert len(metrics.latencies_ns) == 5  # Buffer is capped
        # Should contain the last 5 values: 6ms, 7ms, 8ms, 9ms, 10ms
        latencies_ms = [ns / 1_000_000 for ns in metrics.latencies_ns]
        assert latencies_ms == [6.0, 7.0, 8.0, 9.0, 10.0]
