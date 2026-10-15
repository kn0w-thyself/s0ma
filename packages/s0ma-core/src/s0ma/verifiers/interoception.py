"""Interoception monitor — runtime performance monitoring for components.

The interoception system captures per-component performance metrics
(latency, error rates, call frequency) plus app-reported physical gauges
(current draw, temperature, supply voltage; ADR-003 §4) and compares
them against declared ResourceProfile expectations. This is the
proprioceptive nervous system — the system sensing its own internal
state.

Architecture:
    1. Instrumentation layer: wraps component calls to capture timing/error data
    2. Aggregation layer: collects raw measurements into statistical summaries
    3. Comparison layer: compares aggregated metrics against ResourceProfile

Key design decisions:
    - Opt-in only: only components with non-None ResourceProfile are checked
    - Minimal overhead: uses time.perf_counter_ns() for nanosecond timing
    - Windowed aggregation: metrics over configurable time windows (default 60s)
    - Thread-safe: all metric collection uses threading.Lock

Components:
    ComponentMetrics: collected runtime metrics for a single component
    MetricsCollector: thread-safe collector of per-component metrics
    InteroceptionVerifier: implements the Verifier protocol
    DangerSignal: Aickelin's danger signal for adaptive monitoring
    instrument: decorator for automatic instrumentation
    monitor_call: context manager for ad-hoc instrumentation

Reference: Aickelin et al. (2003) danger theory for adaptive scheduling.
"""

from __future__ import annotations

import contextlib
import functools
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar

from s0ma.anomaly_stream import emit_runtime_anomaly
from s0ma.models import Anomaly, ResourceProfile, VerificationResult
from s0ma.types import AnomalyKind, AnomalySeverity, VerificationScope

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from s0ma.registry import ComponentRegistry
    from s0ma.verifiers.discovery import DiscoveredSurface

__all__ = [
    "ComponentMetrics",
    "MetricsCollector",
    "InteroceptionVerifier",
    "DangerSignal",
    "instrument",
    "monitor_call",
    "get_metrics_collector",
    "reset_metrics_collector",
]

_F = TypeVar("_F", bound="Callable[..., Any]")

# Default configuration
_DEFAULT_WINDOW_SECONDS = 60.0
_DEFAULT_MAX_SAMPLES = 10_000


# ======================================================================
# Metrics data structures
# ======================================================================


@dataclass
class ComponentMetrics:
    """Collected runtime metrics for a single component.

    Stores call counts, error counts, and a ring buffer of recent
    latency measurements. Provides computed properties for percentiles,
    error rates, and call frequency. Physical gauges (ADR-003 §4) hold
    the latest app-reported reading and stay None until reported.
    """

    component_name: str
    call_count: int = 0
    error_count: int = 0
    latencies_ns: deque[int] = field(default_factory=lambda: deque(maxlen=_DEFAULT_MAX_SAMPLES))
    last_call_at: datetime | None = None
    window_start: datetime = field(default_factory=lambda: datetime.now(UTC))
    current_ma: float | None = None
    temperature_c: float | None = None
    voltage_v: float | None = None

    @property
    def error_rate(self) -> float:
        """Fraction of calls that resulted in errors."""
        if self.call_count == 0:
            return 0.0
        return self.error_count / self.call_count

    @property
    def latency_p50_ms(self) -> float:
        """Median latency in milliseconds."""
        if not self.latencies_ns:
            return 0.0
        sorted_ns = sorted(self.latencies_ns)
        median_ns = statistics.median(sorted_ns)
        return median_ns / 1_000_000

    @property
    def latency_p95_ms(self) -> float:
        """95th percentile latency in milliseconds."""
        if not self.latencies_ns:
            return 0.0
        return _percentile(list(self.latencies_ns), 0.95) / 1_000_000

    @property
    def latency_p99_ms(self) -> float:
        """99th percentile latency in milliseconds."""
        if not self.latencies_ns:
            return 0.0
        return _percentile(list(self.latencies_ns), 0.99) / 1_000_000

    @property
    def calls_per_minute(self) -> float:
        """Estimated calls per minute based on window duration."""
        elapsed = (datetime.now(UTC) - self.window_start).total_seconds()
        if elapsed <= 0:
            return 0.0
        return (self.call_count / elapsed) * 60.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "component_name": self.component_name,
            "call_count": self.call_count,
            "error_count": self.error_count,
            "error_rate": self.error_rate,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_p99_ms": self.latency_p99_ms,
            "calls_per_minute": self.calls_per_minute,
            "current_ma": self.current_ma,
            "temperature_c": self.temperature_c,
            "voltage_v": self.voltage_v,
            "last_call_at": (
                self.last_call_at.isoformat() if self.last_call_at else None
            ),
            "window_start": self.window_start.isoformat(),
            "sample_count": len(self.latencies_ns),
        }


def _percentile(sorted_values: list[int], pct: float) -> float:
    """Compute a percentile from a list of values using linear interpolation.

    Args:
        sorted_values: Values (will be sorted in place).
        pct: Percentile as a float between 0.0 and 1.0.

    Returns:
        The interpolated percentile value.
    """
    sorted_values.sort()
    n = len(sorted_values)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_values[0])
    # Linear interpolation
    idx = pct * (n - 1)
    lower = int(idx)
    upper = min(lower + 1, n - 1)
    frac = idx - lower
    return sorted_values[lower] + frac * (sorted_values[upper] - sorted_values[lower])


def _check_physical_bounds(
    component_name: str,
    profile: ResourceProfile,
    *,
    current_ma: float | None,
    temperature_c: float | None,
    voltage_v: float | None,
) -> tuple[int, list[Anomaly]]:
    """Check physical readings against declared profile bounds (ADR-003 §4).

    Returns ``(checks_declared, anomalies)``: ``checks_declared`` counts
    the profile bounds that exist (verifier bookkeeping); ``anomalies``
    holds one INFLAMMATION anomaly per crossed bound. Readings that were
    not reported (None) declare their check but cannot cross it.
    """
    checks = 0
    anomalies: list[Anomaly] = []
    for metric_key, label, actual, bound, direction, unit in (
        ("current_ma", "current draw", current_ma,
         profile.expected_max_current_ma, "max", "mA"),
        ("temperature_c", "temperature", temperature_c,
         profile.expected_max_temperature_c, "max", "°C"),
        ("voltage_v", "supply voltage", voltage_v,
         profile.expected_min_voltage_v, "min", "V"),
    ):
        if bound is None:
            continue
        checks += 1
        if actual is None:
            continue
        crossed = actual > bound if direction == "max" else actual < bound
        if not crossed:
            continue
        comparator = (
            "exceeds expected max"
            if direction == "max"
            else "is below expected min"
        )
        anomalies.append(Anomaly(
            kind=AnomalyKind.INFLAMMATION,
            severity=AnomalySeverity.WARNING,
            component_name=component_name,
            message=(
                f"Component '{component_name}' {label} "
                f"({actual:.1f} {unit}) {comparator} ({bound} {unit})"
            ),
            details={
                "metric": metric_key,
                "expected": bound,
                "actual": actual,
                "bound": direction,
            },
        ))
    return checks, anomalies


# ======================================================================
# Metrics Collector
# ======================================================================


class MetricsCollector:
    """Thread-safe collector of per-component runtime metrics.

    Records call latencies and errors for components, providing
    aggregated views for the InteroceptionVerifier to compare
    against declared ResourceProfile expectations.
    """

    def __init__(
        self,
        window_seconds: float = _DEFAULT_WINDOW_SECONDS,
        max_samples: int = _DEFAULT_MAX_SAMPLES,
    ) -> None:
        self._metrics: dict[str, ComponentMetrics] = {}
        self._lock = threading.Lock()
        self._window_seconds = window_seconds
        self._max_samples = max_samples

    def record_call(
        self,
        component_name: str,
        latency_ns: int,
        error: bool = False,
    ) -> None:
        """Record a single call to a component.

        Args:
            component_name: Name of the component.
            latency_ns: Call latency in nanoseconds.
            error: Whether the call resulted in an error.
        """
        with self._lock:
            metrics = self._get_or_create(component_name)
            metrics.call_count += 1
            metrics.latencies_ns.append(latency_ns)
            if error:
                metrics.error_count += 1
            metrics.last_call_at = datetime.now(UTC)

    def record_physical(
        self,
        component_name: str,
        *,
        current_ma: float | None = None,
        temperature_c: float | None = None,
        voltage_v: float | None = None,
        profile: ResourceProfile | None = None,
    ) -> list[Anomaly]:
        """Record physical readings (gauges) for a component.

        Stores the latest reported current draw, temperature, and supply
        voltage. Interoception stays app-driven: s0ma never samples
        hardware itself — the application reads its own instruments and
        reports here at whatever cadence it chooses.

        When ``profile`` is provided, each reading reported *in this
        call* is immediately checked against the declared physical
        bounds; every crossing produces an INFLAMMATION anomaly that is
        published on the runtime anomaly stream and returned — so a
        subscriber hears about a stall spike or rail sag at ingestion
        time instead of at the next poll.

        Args:
            component_name: Name of the component the readings belong to.
            current_ma: Latest current draw in milliamps, if sampled.
            temperature_c: Latest temperature in °C, if sampled.
            voltage_v: Latest supply voltage in volts, if sampled.
            profile: The component's declared ResourceProfile; enables
                the immediate bound check when provided.

        Returns:
            Anomalies for crossed bounds (empty when within bounds or
            when no profile was given).
        """
        with self._lock:
            metrics = self._get_or_create(component_name)
            if current_ma is not None:
                metrics.current_ma = current_ma
            if temperature_c is not None:
                metrics.temperature_c = temperature_c
            if voltage_v is not None:
                metrics.voltage_v = voltage_v

        if profile is None:
            return []
        _, anomalies = _check_physical_bounds(
            component_name,
            profile,
            current_ma=current_ma,
            temperature_c=temperature_c,
            voltage_v=voltage_v,
        )
        for anomaly in anomalies:
            emit_runtime_anomaly(anomaly)
        return anomalies

    def get_metrics(self, component_name: str) -> ComponentMetrics | None:
        """Get current metrics for a component, or None."""
        return self._metrics.get(component_name)

    def get_all_metrics(self) -> dict[str, ComponentMetrics]:
        """Get a copy of metrics for all instrumented components."""
        return dict(self._metrics)

    def reset(self) -> None:
        """Clear all collected metrics."""
        with self._lock:
            self._metrics.clear()

    def reset_component(self, component_name: str) -> None:
        """Clear metrics for a single component."""
        with self._lock:
            self._metrics.pop(component_name, None)

    def _get_or_create(self, component_name: str) -> ComponentMetrics:
        """Get or create a ComponentMetrics entry (must hold lock)."""
        if component_name not in self._metrics:
            self._metrics[component_name] = ComponentMetrics(
                component_name=component_name,
                latencies_ns=deque(maxlen=self._max_samples),
            )
        return self._metrics[component_name]


# ======================================================================
# Global metrics collector singleton
# ======================================================================

_global_metrics_collector: MetricsCollector | None = None
_global_metrics_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """Get or create the global MetricsCollector singleton."""
    global _global_metrics_collector  # noqa: PLW0603
    if _global_metrics_collector is None:
        with _global_metrics_lock:
            if _global_metrics_collector is None:
                _global_metrics_collector = MetricsCollector()
    return _global_metrics_collector


def reset_metrics_collector() -> None:
    """Reset the global MetricsCollector singleton."""
    global _global_metrics_collector  # noqa: PLW0603
    with _global_metrics_lock:
        if _global_metrics_collector is not None:
            _global_metrics_collector.reset()
        _global_metrics_collector = None


# ======================================================================
# Instrumentation: decorator and context manager
# ======================================================================


def instrument(
    component_name: str,
    collector: MetricsCollector | None = None,
) -> Callable[[_F], _F]:
    """Decorator that instruments a callable for interoception monitoring.

    Captures timing and error data for each invocation and records
    it in the metrics collector.

    Args:
        component_name: Name of the component being instrumented.
        collector: MetricsCollector to record into. Uses the global
            singleton if None.

    Returns:
        A decorator that wraps the callable with timing instrumentation.

    Example::

        @instrument("PaymentProcessor.process")
        def process(self, request):
            ...
    """

    def decorator(func: _F) -> _F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            actual_collector = collector or get_metrics_collector()
            start_ns = time.perf_counter_ns()
            error_occurred = False
            try:
                return func(*args, **kwargs)
            except Exception:
                error_occurred = True
                raise
            finally:
                elapsed_ns = time.perf_counter_ns() - start_ns
                actual_collector.record_call(
                    component_name, elapsed_ns, error=error_occurred
                )

        return wrapper  # type: ignore[return-value]

    return decorator


@contextlib.contextmanager
def monitor_call(
    component_name: str,
    collector: MetricsCollector | None = None,
) -> Generator[_MonitorContext, None, None]:
    """Context manager for ad-hoc interoception instrumentation.

    Captures timing and error data for the code block and records
    it in the metrics collector.

    Args:
        component_name: Name of the component being monitored.
        collector: MetricsCollector to record into. Uses the global
            singleton if None.

    Example::

        with monitor_call("PaymentProcessor.process") as ctx:
            result = processor.process(request)
        print(f"Latency: {ctx.latency_ns}ns")
    """
    actual_collector = collector or get_metrics_collector()
    ctx = _MonitorContext()
    start_ns = time.perf_counter_ns()
    error_occurred = False
    try:
        yield ctx
    except Exception:
        error_occurred = True
        raise
    finally:
        ctx.latency_ns = time.perf_counter_ns() - start_ns
        actual_collector.record_call(
            component_name, ctx.latency_ns, error=error_occurred
        )


class _MonitorContext:
    """Context object for monitor_call, exposing measured latency."""

    __slots__ = ("latency_ns",)

    def __init__(self) -> None:
        self.latency_ns: int = 0


# ======================================================================
# Danger Signal (Aickelin 2003)
# ======================================================================


@dataclass(frozen=True)
class DangerSignal:
    """Aickelin's danger signal for adaptive monitoring.

    Components with high danger signals should be monitored more
    frequently. This implements the homunculus-weighted verification
    concept from the LOA2 plan.

    The criticality_score is a composite measure that combines
    dependency count (how many components depend on this one),
    recent error rate, and call volume.

    Reference: Aickelin, Bentley, Cayzer, Kim & McLeod (2003).
    """

    component_name: str
    dependency_count: int = 0
    error_rate_recent: float = 0.0
    call_count_recent: int = 0
    criticality_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "component_name": self.component_name,
            "dependency_count": self.dependency_count,
            "error_rate_recent": self.error_rate_recent,
            "call_count_recent": self.call_count_recent,
            "criticality_score": self.criticality_score,
        }


def compute_danger_signals(
    registry: ComponentRegistry,
    collector: MetricsCollector,
) -> list[DangerSignal]:
    """Compute danger signals for all components with ResourceProfile.

    Components with high danger signals should be monitored more
    frequently. This implements the homunculus-weighted verification
    concept from the LOA2 plan.

    The criticality score is a weighted sum:
        score = (dependency_count * 2.0)
              + (error_rate_recent * 10.0)
              + min(call_count_recent / 100.0, 5.0)

    Args:
        registry: The component registry.
        collector: The metrics collector with runtime data.

    Returns:
        List of DangerSignal objects sorted by criticality (highest first).
    """
    signals: list[DangerSignal] = []
    all_specs = registry.get_all()

    for comp_name, spec in all_specs.items():
        if spec.resource_profile is None:
            continue

        # Dependency count: how many components depend on this one
        try:
            dependents = registry.get_dependents(comp_name)
            dep_count = len(dependents)
        except Exception:  # noqa: BLE001
            dep_count = 0

        # Recent metrics
        metrics = collector.get_metrics(comp_name)
        error_rate = metrics.error_rate if metrics else 0.0
        call_count = metrics.call_count if metrics else 0

        # Composite criticality score
        score = (
            (dep_count * 2.0)
            + (error_rate * 10.0)
            + min(call_count / 100.0, 5.0)
        )

        signals.append(DangerSignal(
            component_name=comp_name,
            dependency_count=dep_count,
            error_rate_recent=error_rate,
            call_count_recent=call_count,
            criticality_score=score,
        ))

    return sorted(signals, key=lambda s: s.criticality_score, reverse=True)


# ======================================================================
# Interoception Verifier
# ======================================================================


class InteroceptionVerifier:
    """Runtime monitoring verifier comparing metrics against ResourceProfile.

    For each component with a declared ResourceProfile, retrieves
    current ComponentMetrics from the collector and compares against
    expectations. Produces INFLAMMATION anomalies when thresholds
    are exceeded.

    Components without ResourceProfile are skipped (opt-in monitoring).
    Components with ResourceProfile but no collected metrics produce
    an INFO anomaly suggesting they may not be called.
    """

    def __init__(
        self,
        collector: MetricsCollector | None = None,
    ) -> None:
        self._collector = collector

    @property
    def name(self) -> str:
        """Human-readable name for this verifier."""
        return "Interoception Monitor"

    @property
    def scope(self) -> VerificationScope:
        """This verifier performs interoception checks."""
        return VerificationScope.INTEROCEPTION

    def _get_collector(self) -> MetricsCollector:
        """Get the metrics collector, falling back to global singleton."""
        if self._collector is not None:
            return self._collector
        return get_metrics_collector()

    def verify(
        self,
        registry: ComponentRegistry,
        *,
        discovered_surface: DiscoveredSurface | None = None,
    ) -> VerificationResult:
        """Run interoception verification against all registered components.

        For each component with a ResourceProfile:
        1. Retrieves current metrics from the collector
        2. Compares latency p50/p99 against expectations
        3. Compares error rate against expectations
        4. Checks call frequency for significant deviation
        5. Reports INFLAMMATION anomalies for threshold violations

        Args:
            registry: The ComponentRegistry to verify against.

        Returns:
            VerificationResult with interoception anomalies and
            danger signal data in details.
        """
        start_ns = time.perf_counter_ns()
        anomalies: list[Anomaly] = []
        components_checked = 0
        checks_performed = 0
        collector = self._get_collector()

        all_specs = registry.get_all()

        from s0ma.verifiers.discovery import (
            registered_surface_identifiers,
            unregistered_surface_anomaly,
        )

        registered_surface = registered_surface_identifiers(registry)
        discovery_anomaly = unregistered_surface_anomaly(
            discovered_surface, registered_surface,
        )
        if discovery_anomaly is not None:
            anomalies.append(discovery_anomaly)
            checks_performed += 1

        for comp_name, spec in all_specs.items():
            if spec.resource_profile is None:
                continue

            components_checked += 1
            profile = spec.resource_profile
            metrics = collector.get_metrics(comp_name)

            has_gauges = metrics is not None and (
                metrics.current_ma is not None
                or metrics.temperature_c is not None
                or metrics.voltage_v is not None
            )
            if metrics is None or (metrics.call_count == 0 and not has_gauges):
                checks_performed += 1
                anomalies.append(Anomaly(
                    kind=AnomalyKind.VESTIGIAL_ORGAN,
                    severity=AnomalySeverity.INFO,
                    component_name=comp_name,
                    message=(
                        f"Component '{comp_name}' has a ResourceProfile "
                        f"but no metrics collected — is it being called?"
                    ),
                ))
                continue

            # Check latency p50
            if profile.expected_latency_p50_ms is not None:
                checks_performed += 1
                actual_p50 = metrics.latency_p50_ms
                if actual_p50 > profile.expected_latency_p50_ms:
                    anomalies.append(Anomaly(
                        kind=AnomalyKind.INFLAMMATION,
                        severity=AnomalySeverity.WARNING,
                        component_name=comp_name,
                        message=(
                            f"Component '{comp_name}' latency p50 "
                            f"({actual_p50:.1f}ms) exceeds expected "
                            f"({profile.expected_latency_p50_ms}ms)"
                        ),
                        details={
                            "metric": "latency_p50_ms",
                            "expected": profile.expected_latency_p50_ms,
                            "actual": actual_p50,
                        },
                    ))

            # Check latency p99
            if profile.expected_latency_p99_ms is not None:
                checks_performed += 1
                actual_p99 = metrics.latency_p99_ms
                if actual_p99 > profile.expected_latency_p99_ms:
                    anomalies.append(Anomaly(
                        kind=AnomalyKind.INFLAMMATION,
                        severity=AnomalySeverity.WARNING,
                        component_name=comp_name,
                        message=(
                            f"Component '{comp_name}' latency p99 "
                            f"({actual_p99:.1f}ms) exceeds expected "
                            f"({profile.expected_latency_p99_ms}ms)"
                        ),
                        details={
                            "metric": "latency_p99_ms",
                            "expected": profile.expected_latency_p99_ms,
                            "actual": actual_p99,
                        },
                    ))

            # Check error rate
            if profile.expected_error_rate is not None:
                checks_performed += 1
                actual_error_rate = metrics.error_rate
                if actual_error_rate > profile.expected_error_rate:
                    anomalies.append(Anomaly(
                        kind=AnomalyKind.INFLAMMATION,
                        severity=AnomalySeverity.WARNING,
                        component_name=comp_name,
                        message=(
                            f"Component '{comp_name}' error rate "
                            f"({actual_error_rate:.2%}) exceeds expected "
                            f"({profile.expected_error_rate:.2%})"
                        ),
                        details={
                            "metric": "error_rate",
                            "expected": profile.expected_error_rate,
                            "actual": actual_error_rate,
                        },
                    ))

            # Check call frequency (INFO only — significant deviation).
            # Skipped for gauges-only components: zero calls is not a
            # frequency deviation for a component that reports readings.
            if (
                profile.expected_call_frequency_per_min is not None
                and metrics.call_count > 0
            ):
                checks_performed += 1
                actual_cpm = metrics.calls_per_minute
                expected_cpm = profile.expected_call_frequency_per_min
                if expected_cpm > 0:
                    ratio = actual_cpm / expected_cpm
                    if ratio > 2.0 or ratio < 0.5:
                        anomalies.append(Anomaly(
                            kind=AnomalyKind.INFLAMMATION,
                            severity=AnomalySeverity.INFO,
                            component_name=comp_name,
                            message=(
                                f"Component '{comp_name}' call frequency "
                                f"({actual_cpm:.1f}/min) differs significantly "
                                f"from expected ({expected_cpm}/min)"
                            ),
                            details={
                                "metric": "call_frequency_per_min",
                                "expected": expected_cpm,
                                "actual": actual_cpm,
                                "ratio": ratio,
                            },
                        ))

            # Check physical gauges against declared bounds (ADR-003 §4)
            physical_checks, physical_anomalies = _check_physical_bounds(
                comp_name,
                profile,
                current_ma=metrics.current_ma,
                temperature_c=metrics.temperature_c,
                voltage_v=metrics.voltage_v,
            )
            checks_performed += physical_checks
            anomalies.extend(physical_anomalies)

        # Compute danger signals for details
        danger_signals = compute_danger_signals(registry, collector)

        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

        return VerificationResult(
            verifier_name=self.name,
            scope=self.scope,
            anomalies=anomalies,
            components_checked=components_checked,
            checks_performed=checks_performed,
            duration_ms=elapsed_ms,
            details={
                "danger_signals": [s.to_dict() for s in danger_signals],
            },
        )

    def verify_incremental(
        self,
        registry: ComponentRegistry,
        component_name: str,
    ) -> VerificationResult:
        """Verify interoception for a single component.

        Args:
            registry: The ComponentRegistry to verify against.
            component_name: Name of the component to verify.

        Returns:
            VerificationResult scoped to the named component.
        """
        start_ns = time.perf_counter_ns()
        anomalies: list[Anomaly] = []
        checks_performed = 0
        collector = self._get_collector()

        spec = registry.get(component_name)
        if spec is None:
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            return VerificationResult(
                verifier_name=self.name,
                scope=self.scope,
                anomalies=[
                    Anomaly(
                        kind=AnomalyKind.PHANTOM_LIMB,
                        severity=AnomalySeverity.ERROR,
                        component_name=component_name,
                        message=(
                            f"Component '{component_name}' "
                            f"is not registered"
                        ),
                    )
                ],
                components_checked=0,
                checks_performed=1,
                duration_ms=elapsed_ms,
            )

        if spec.resource_profile is None:
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            return VerificationResult(
                verifier_name=self.name,
                scope=self.scope,
                anomalies=[],
                components_checked=1,
                checks_performed=0,
                duration_ms=elapsed_ms,
            )

        profile = spec.resource_profile
        metrics = collector.get_metrics(component_name)

        has_gauges = metrics is not None and (
            metrics.current_ma is not None
            or metrics.temperature_c is not None
            or metrics.voltage_v is not None
        )
        if metrics is None or (metrics.call_count == 0 and not has_gauges):
            checks_performed += 1
            anomalies.append(Anomaly(
                kind=AnomalyKind.VESTIGIAL_ORGAN,
                severity=AnomalySeverity.INFO,
                component_name=component_name,
                message=(
                    f"Component '{component_name}' has a ResourceProfile "
                    f"but no metrics collected — is it being called?"
                ),
            ))
        else:
            if profile.expected_latency_p50_ms is not None:
                checks_performed += 1
                if metrics.latency_p50_ms > profile.expected_latency_p50_ms:
                    anomalies.append(Anomaly(
                        kind=AnomalyKind.INFLAMMATION,
                        severity=AnomalySeverity.WARNING,
                        component_name=component_name,
                        message=(
                            f"Component '{component_name}' latency p50 "
                            f"({metrics.latency_p50_ms:.1f}ms) exceeds "
                            f"expected ({profile.expected_latency_p50_ms}ms)"
                        ),
                    ))

            if profile.expected_latency_p99_ms is not None:
                checks_performed += 1
                if metrics.latency_p99_ms > profile.expected_latency_p99_ms:
                    anomalies.append(Anomaly(
                        kind=AnomalyKind.INFLAMMATION,
                        severity=AnomalySeverity.WARNING,
                        component_name=component_name,
                        message=(
                            f"Component '{component_name}' latency p99 "
                            f"({metrics.latency_p99_ms:.1f}ms) exceeds "
                            f"expected ({profile.expected_latency_p99_ms}ms)"
                        ),
                    ))

            if profile.expected_error_rate is not None:
                checks_performed += 1
                if metrics.error_rate > profile.expected_error_rate:
                    anomalies.append(Anomaly(
                        kind=AnomalyKind.INFLAMMATION,
                        severity=AnomalySeverity.WARNING,
                        component_name=component_name,
                        message=(
                            f"Component '{component_name}' error rate "
                            f"({metrics.error_rate:.2%}) exceeds expected "
                            f"({profile.expected_error_rate:.2%})"
                        ),
                    ))

            physical_checks, physical_anomalies = _check_physical_bounds(
                component_name,
                profile,
                current_ma=metrics.current_ma,
                temperature_c=metrics.temperature_c,
                voltage_v=metrics.voltage_v,
            )
            checks_performed += physical_checks
            anomalies.extend(physical_anomalies)

        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
        return VerificationResult(
            verifier_name=self.name,
            scope=self.scope,
            anomalies=anomalies,
            components_checked=1,
            checks_performed=checks_performed,
            duration_ms=elapsed_ms,
        )
