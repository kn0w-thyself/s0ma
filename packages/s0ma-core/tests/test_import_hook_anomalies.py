"""Tests for ``ComponentRegistry.import_hook_anomalies`` and related API.

POST-1 / 0.4.0 surface — the import hook now appends an
``ImportHookAnomaly`` to the registry every time a foreign-code
surveillance pass detects a violation. Downstream consumers (notably
fr3d's Phase 2 B1 ``IMMUNE_RESPONSE`` detection) can poll the buffer
or subscribe to incremental detections without scraping log output.

The tests in this file cover four areas:

1. The ``ImportHookAnomaly`` dataclass itself (fields, freezing,
   ``to_dict`` shape).
2. The registry surface — ``import_hook_anomalies`` property,
   ``clear_import_hook_anomalies``, ``subscribe_import_hook_anomalies``.
3. The import-hook integration — anomalies are recorded when the
   loader runs in both strict and lenient mode, and the existing
   warning / exception behaviour is preserved (regression guard).
4. Thread safety — concurrent registrations and anomaly recording can
   interleave without losing records or deadlocking.
"""

from __future__ import annotations

import importlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma import ImportHookAnomaly
from s0ma.exceptions import UnregisteredComponentError
from s0ma.import_hook import (
    install_import_hook,
    uninstall_import_hook,
)
from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry, get_registry, set_registry
from s0ma.types import AnomalySeverity, ComponentKind, Layer

if TYPE_CHECKING:
    from collections.abc import Generator


SAMPLE_PROJECT_ROOT = Path(__file__).parent / "sample_project"

REGISTERED_MODULE = "tests.sample_project.registered_module"
UNREGISTERED_MODULE = "tests.sample_project.unregistered_module"
MIXED_MODULE = "tests.sample_project.mixed_module"
INTERNAL_MODULE = "tests.sample_project.internal_module"
PRIVATE_MODULE = "tests.sample_project.private_module"

ALL_SAMPLE_MODULES = [
    REGISTERED_MODULE,
    UNREGISTERED_MODULE,
    MIXED_MODULE,
    INTERNAL_MODULE,
    PRIVATE_MODULE,
    "tests.sample_project",
]


def _purge_modules(module_names: list[str]) -> None:
    """Remove modules from sys.modules to force re-import."""
    for name in module_names:
        sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def _clean_hook_and_modules() -> Generator[None, None, None]:
    """Ensure the import hook is uninstalled and sample modules are purged."""
    yield
    uninstall_import_hook()
    _purge_modules(ALL_SAMPLE_MODULES)


def _make_spec(name: str) -> ComponentSpec:
    """Build a minimal ComponentSpec for concurrent-registration tests."""
    return ComponentSpec(
        name=name,
        kind=ComponentKind.FUNCTION,
        layer=Layer.DOMAIN,
        intent=f"Test component {name} for anomaly concurrency tests.",
        module_path=f"myapp.test.{name}",
    )


# ======================================================================
# ImportHookAnomaly dataclass
# ======================================================================


class TestImportHookAnomaly:
    """The frozen dataclass that represents one hook detection."""

    def test_required_fields(self) -> None:
        """name, description, severity are required; layer/detected_at default."""
        anomaly = ImportHookAnomaly(
            name="myapp.foo",
            description="something is wrong",
            severity=AnomalySeverity.WARNING,
        )
        assert anomaly.name == "myapp.foo"
        assert anomaly.description == "something is wrong"
        assert anomaly.severity is AnomalySeverity.WARNING
        assert anomaly.layer is None
        assert anomaly.detected_at is not None

    def test_layer_defaults_to_none(self) -> None:
        anomaly = ImportHookAnomaly(
            name="m", description="d", severity=AnomalySeverity.INFO,
        )
        assert anomaly.layer is None

    def test_frozen_cannot_mutate(self) -> None:
        """Frozen dataclass prevents post-construction mutation."""
        anomaly = ImportHookAnomaly(
            name="m", description="d", severity=AnomalySeverity.ERROR,
        )
        # FrozenInstanceError is an AttributeError subclass; TypeError
        # covers alternative frozen-assignment surfaces.
        with pytest.raises((AttributeError, TypeError)):
            anomaly.name = "other"  # type: ignore[misc]

    def test_to_dict_round_trip(self) -> None:
        """to_dict produces a JSON-shape with enum names serialised."""
        anomaly = ImportHookAnomaly(
            name="myapp.bar",
            description="unregistered class 'Foo'",
            severity=AnomalySeverity.ERROR,
            layer=Layer.DOMAIN,
        )
        d = anomaly.to_dict()
        assert d["name"] == "myapp.bar"
        assert d["description"] == "unregistered class 'Foo'"
        assert d["severity"] == "ERROR"
        assert d["layer"] == "DOMAIN"
        assert "detected_at" in d
        # ISO8601 with timezone suffix
        assert d["detected_at"].endswith("+00:00") or "T" in d["detected_at"]

    def test_to_dict_layer_none(self) -> None:
        anomaly = ImportHookAnomaly(
            name="m", description="d", severity=AnomalySeverity.WARNING,
        )
        d = anomaly.to_dict()
        assert d["layer"] is None


# ======================================================================
# Registry surface — property / clear / subscribe
# ======================================================================


class TestRegistryAnomalyProperty:
    """``ComponentRegistry.import_hook_anomalies`` semantics."""

    def test_empty_on_fresh_registry(self, registry: ComponentRegistry) -> None:
        assert registry.import_hook_anomalies == []

    def test_appends_in_detection_order(
        self, registry: ComponentRegistry,
    ) -> None:
        a1 = ImportHookAnomaly(
            name="m1", description="first",
            severity=AnomalySeverity.WARNING,
        )
        a2 = ImportHookAnomaly(
            name="m2", description="second",
            severity=AnomalySeverity.ERROR,
        )
        registry.record_import_hook_anomaly(a1)
        registry.record_import_hook_anomaly(a2)

        anomalies = registry.import_hook_anomalies
        assert len(anomalies) == 2
        assert anomalies[0] is a1
        assert anomalies[1] is a2

    def test_property_returns_defensive_copy(
        self, registry: ComponentRegistry,
    ) -> None:
        """Mutating the returned list does not affect the buffer."""
        registry.record_import_hook_anomaly(
            ImportHookAnomaly(
                name="m", description="d", severity=AnomalySeverity.INFO,
            ),
        )
        snapshot = registry.import_hook_anomalies
        snapshot.clear()
        # The buffer should still hold the one record
        assert len(registry.import_hook_anomalies) == 1

    def test_clear_empties_buffer(self, registry: ComponentRegistry) -> None:
        registry.record_import_hook_anomaly(
            ImportHookAnomaly(
                name="m", description="d", severity=AnomalySeverity.WARNING,
            ),
        )
        assert len(registry.import_hook_anomalies) == 1
        registry.clear_import_hook_anomalies()
        assert registry.import_hook_anomalies == []

    def test_reset_clears_anomalies(self, registry: ComponentRegistry) -> None:
        registry.record_import_hook_anomaly(
            ImportHookAnomaly(
                name="m", description="d", severity=AnomalySeverity.INFO,
            ),
        )
        registry.reset()
        assert registry.import_hook_anomalies == []


class TestRegistrySubscribe:
    """``subscribe_import_hook_anomalies`` semantics."""

    def test_callback_fires_on_record(
        self, registry: ComponentRegistry,
    ) -> None:
        received: list[ImportHookAnomaly] = []
        registry.subscribe_import_hook_anomalies(received.append)
        a = ImportHookAnomaly(
            name="m", description="d", severity=AnomalySeverity.ERROR,
        )
        registry.record_import_hook_anomaly(a)
        assert received == [a]

    def test_multiple_callbacks_fire_in_registration_order(
        self, registry: ComponentRegistry,
    ) -> None:
        order: list[str] = []
        registry.subscribe_import_hook_anomalies(lambda _: order.append("a"))
        registry.subscribe_import_hook_anomalies(lambda _: order.append("b"))
        registry.subscribe_import_hook_anomalies(lambda _: order.append("c"))
        registry.record_import_hook_anomaly(
            ImportHookAnomaly(
                name="m", description="d", severity=AnomalySeverity.INFO,
            ),
        )
        assert order == ["a", "b", "c"]

    def test_unsubscribe_stops_dispatch(
        self, registry: ComponentRegistry,
    ) -> None:
        received: list[ImportHookAnomaly] = []
        unsub = registry.subscribe_import_hook_anomalies(received.append)
        registry.record_import_hook_anomaly(
            ImportHookAnomaly(
                name="m1", description="d1", severity=AnomalySeverity.WARNING,
            ),
        )
        unsub()
        registry.record_import_hook_anomaly(
            ImportHookAnomaly(
                name="m2", description="d2", severity=AnomalySeverity.WARNING,
            ),
        )
        assert len(received) == 1
        assert received[0].name == "m1"

    def test_unsubscribe_twice_is_noop(
        self, registry: ComponentRegistry,
    ) -> None:
        """Repeated unsubscribe calls do not raise — callers can hold handles."""
        unsub = registry.subscribe_import_hook_anomalies(lambda _: None)
        unsub()
        unsub()  # Must not raise

    def test_subscriber_exceptions_isolated(
        self,
        registry: ComponentRegistry,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A broken subscriber must not block the others."""
        good: list[ImportHookAnomaly] = []

        def bad(_a: ImportHookAnomaly) -> None:
            raise RuntimeError("subscriber boom")

        registry.subscribe_import_hook_anomalies(bad)
        registry.subscribe_import_hook_anomalies(good.append)

        anomaly = ImportHookAnomaly(
            name="m", description="d", severity=AnomalySeverity.ERROR,
        )
        registry.record_import_hook_anomaly(anomaly)

        # The good subscriber still fired; the bad one's error was logged.
        assert good == [anomaly]
        assert any(
            "subscriber" in record.getMessage().lower()
            for record in caplog.records
        )


# ======================================================================
# Import-hook integration — strict mode
# ======================================================================


class TestImportHookStrictModeRecording:
    """Anomalies appear after the hook detects strict-mode violations."""

    def test_anomaly_recorded_when_strict_raises(self) -> None:
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        registry = get_registry(persist=False)
        registry.clear_import_hook_anomalies()

        with pytest.raises(UnregisteredComponentError):
            importlib.import_module(UNREGISTERED_MODULE)

        anomalies = registry.import_hook_anomalies
        # Two unregistered entities → two anomalies.
        assert len(anomalies) == 2
        names = {a.description for a in anomalies}
        assert any("UnregisteredService" in d for d in names)
        assert any("unregistered_function" in d for d in names)
        # All strict-mode anomalies carry ERROR severity.
        assert all(a.severity is AnomalySeverity.ERROR for a in anomalies)
        # Module name is set on every record.
        assert all(a.name == UNREGISTERED_MODULE for a in anomalies)

    def test_strict_mode_subscriber_fires_before_raise(self) -> None:
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        registry = get_registry(persist=False)
        registry.clear_import_hook_anomalies()

        received: list[ImportHookAnomaly] = []
        registry.subscribe_import_hook_anomalies(received.append)

        with pytest.raises(UnregisteredComponentError):
            importlib.import_module(UNREGISTERED_MODULE)

        # The subscriber saw the records even though the import raised.
        assert len(received) >= 2
        assert all(a.severity is AnomalySeverity.ERROR for a in received)


# ======================================================================
# Import-hook integration — lenient mode
# ======================================================================


class TestImportHookLenientModeRecording:
    """Anomalies are recorded when the hook is in lenient mode too."""

    def test_anomaly_recorded_in_lenient_mode(self) -> None:
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT, strict=False)
        registry = get_registry(persist=False)
        registry.clear_import_hook_anomalies()

        with pytest.warns(match="Unregistered public entities"):
            importlib.import_module(UNREGISTERED_MODULE)

        anomalies = registry.import_hook_anomalies
        assert len(anomalies) == 2
        # Lenient mode uses WARNING severity.
        assert all(a.severity is AnomalySeverity.WARNING for a in anomalies)
        assert all(a.name == UNREGISTERED_MODULE for a in anomalies)

    def test_no_anomalies_on_clean_import(self) -> None:
        """Registered modules import without any anomaly being recorded."""
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        registry = get_registry(persist=False)
        registry.clear_import_hook_anomalies()

        importlib.import_module(REGISTERED_MODULE)

        assert registry.import_hook_anomalies == []


# ======================================================================
# Concurrency
# ======================================================================


class TestConcurrentRecording:
    """Lock prevents races between registration and anomaly recording."""

    def test_concurrent_anomaly_recording_no_loss(
        self, registry: ComponentRegistry,
    ) -> None:
        """Many threads concurrently recording anomalies do not lose records."""
        num_anomalies = 200

        def record_one(i: int) -> None:
            registry.record_import_hook_anomaly(
                ImportHookAnomaly(
                    name=f"mod_{i}",
                    description=f"anomaly {i}",
                    severity=AnomalySeverity.WARNING,
                ),
            )

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(record_one, i) for i in range(num_anomalies)
            ]
            for future in as_completed(futures):
                future.result()

        anomalies = registry.import_hook_anomalies
        assert len(anomalies) == num_anomalies
        # Every record's name landed in the buffer.
        names = {a.name for a in anomalies}
        assert names == {f"mod_{i}" for i in range(num_anomalies)}

    def test_concurrent_register_and_record(
        self, registry: ComponentRegistry,
    ) -> None:
        """Concurrent component registration + anomaly recording works."""
        num = 50

        def register(i: int) -> None:
            registry.register(_make_spec(f"Comp_{i}"))

        def record(i: int) -> None:
            registry.record_import_hook_anomaly(
                ImportHookAnomaly(
                    name=f"mod_{i}",
                    description=f"d{i}",
                    severity=AnomalySeverity.WARNING,
                ),
            )

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for i in range(num):
                futures.append(executor.submit(register, i))
                futures.append(executor.submit(record, i))
            for f in futures:
                f.result()

        assert registry.count() == num
        assert len(registry.import_hook_anomalies) == num

    def test_subscriber_invoked_under_lock(
        self, registry: ComponentRegistry,
    ) -> None:
        """Subscribers see every record across concurrent dispatches."""
        received: list[ImportHookAnomaly] = []
        registry.subscribe_import_hook_anomalies(received.append)
        num = 100

        def record(i: int) -> None:
            registry.record_import_hook_anomaly(
                ImportHookAnomaly(
                    name=f"mod_{i}",
                    description=f"d{i}",
                    severity=AnomalySeverity.INFO,
                ),
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            for f in [executor.submit(record, i) for i in range(num)]:
                f.result()

        # Subscriber dispatch is under the registry lock — every record
        # appears exactly once in ``received``.
        assert len(received) == num


# ======================================================================
# Regression guard — existing import_hook behaviour preserved
# ======================================================================


class TestImportHookRegression:
    """Pre-existing import-hook tests continue to pass alongside POST-1."""

    def test_strict_mode_still_raises(self) -> None:
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        with pytest.raises(UnregisteredComponentError):
            importlib.import_module(UNREGISTERED_MODULE)

    def test_lenient_mode_still_warns(self) -> None:
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT, strict=False)
        with pytest.warns(match="Unregistered public entities"):
            importlib.import_module(UNREGISTERED_MODULE)

    def test_internal_module_records_no_anomaly(self) -> None:
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        registry = get_registry(persist=False)
        registry.clear_import_hook_anomalies()
        importlib.import_module(INTERNAL_MODULE)
        assert registry.import_hook_anomalies == []


# ======================================================================
# Fresh-registry coexistence — set_registry round-trip
# ======================================================================


class TestSetRegistryCoexistence:
    """Anomaly state lives on the registry instance, not module-level."""

    def test_state_per_registry_instance(self) -> None:
        r1 = ComponentRegistry(persist=False)
        r2 = ComponentRegistry(persist=False)
        r1.record_import_hook_anomaly(
            ImportHookAnomaly(
                name="m", description="d", severity=AnomalySeverity.ERROR,
            ),
        )
        assert len(r1.import_hook_anomalies) == 1
        assert r2.import_hook_anomalies == []

    def test_set_registry_swaps_anomaly_surface(self) -> None:
        original = get_registry(persist=False)
        replacement = ComponentRegistry(persist=False)
        try:
            replacement.record_import_hook_anomaly(
                ImportHookAnomaly(
                    name="m", description="d",
                    severity=AnomalySeverity.WARNING,
                ),
            )
            set_registry(replacement)
            # After set_registry, get_registry returns the replacement.
            assert get_registry(persist=False) is replacement
            assert len(get_registry(persist=False).import_hook_anomalies) == 1
        finally:
            # Restore the original global for the autouse fixture's reset.
            set_registry(original)
