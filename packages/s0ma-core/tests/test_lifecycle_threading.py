"""Thread safety tests for lifecycle operations.

Milestone 6 (Phase 2.5): Verifies that concurrent create, update, and
remove operations don't corrupt the registry, and that transactions
are properly serialized.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from s0ma.exceptions import LifecycleError, RegistryIntegrityError
from s0ma.lifecycle import LifecycleManager
from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from pathlib import Path


# -- Helpers ---------------------------------------------------------------

def _make_spec(name: str, **overrides: object) -> ComponentSpec:
    """Create a minimal ComponentSpec for threading tests."""
    defaults = {
        "name": name,
        "kind": ComponentKind.FUNCTION,
        "layer": Layer.DOMAIN,
        "intent": f"Thread safety test component {name}",
        "module_path": f"test_module.{name.lower()}",
        "qualified_name": f"test_module.{name.lower()}.{name}",
    }
    defaults.update(overrides)
    return ComponentSpec(**defaults)  # type: ignore[arg-type]


def _make_source(class_name: str) -> str:
    """Create minimal Python source for a runtime component."""
    return f'class {class_name}:\n    """Test class."""\n    pass\n'


# -- Fixtures --------------------------------------------------------------

@pytest.fixture()
def registry() -> ComponentRegistry:
    return ComponentRegistry(persist=False)


@pytest.fixture()
def lm(registry: ComponentRegistry) -> LifecycleManager:
    return LifecycleManager(registry, verify_after=False)


# -- Tests: Concurrent Create ----------------------------------------------

class TestConcurrentCreate:
    """Concurrent component creation."""

    def test_concurrent_create_different_names(
        self, lm: LifecycleManager, tmp_path: Path,
    ) -> None:
        """10 threads each create a unique component. All 10 are registered."""
        errors: list[Exception] = []
        count = 10

        def _create(idx: int) -> None:
            try:
                name = f"ConcCreate{idx}"
                target = tmp_path / f"create_{idx}"
                spec = _make_spec(name)
                lm.create_component_at_runtime(
                    _make_source(name), spec, target_dir=target,
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_create, args=(i,)) for i in range(count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected errors: {errors}"
        assert lm.registry.count() == count

    def test_concurrent_create_same_name(
        self, lm: LifecycleManager, tmp_path: Path,
    ) -> None:
        """5 threads try to create the same component. Exactly 1 succeeds."""
        successes: list[int] = []
        failures: list[int] = []
        count = 5

        def _create(idx: int) -> None:
            try:
                name = "SameName"
                target = tmp_path / f"same_{idx}"
                spec = _make_spec(name)
                lm.create_component_at_runtime(
                    _make_source(name), spec, target_dir=target,
                )
                successes.append(idx)
            except (LifecycleError, RegistryIntegrityError):
                failures.append(idx)

        threads = [threading.Thread(target=_create, args=(i,)) for i in range(count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successes) == 1
        assert len(failures) == count - 1
        assert lm.registry.contains("SameName")


# -- Tests: Concurrent Update -----------------------------------------------

class TestConcurrentUpdate:
    """Concurrent component updates."""

    def test_concurrent_update_different_components(
        self, lm: LifecycleManager,
    ) -> None:
        """10 threads each update a different component. All updates apply."""
        count = 10
        for i in range(count):
            lm.registry.register(_make_spec(f"UpdComp{i}"))

        errors: list[Exception] = []

        def _update(idx: int) -> None:
            try:
                lm.update_component(
                    f"UpdComp{idx}",
                    intent=f"Updated intent for component {idx} in thread",
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_update, args=(i,)) for i in range(count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected errors: {errors}"
        for i in range(count):
            spec = lm.registry.get(f"UpdComp{i}")
            assert spec is not None
            assert "Updated intent" in spec.intent

    def test_concurrent_update_same_component(
        self, lm: LifecycleManager,
    ) -> None:
        """5 threads update the same component. Final state is one of the updates."""
        lm.registry.register(_make_spec("SharedComp"))
        errors: list[Exception] = []
        count = 5

        def _update(idx: int) -> None:
            try:
                lm.update_component(
                    "SharedComp",
                    intent=f"Thread {idx} updated intent for this component",
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_update, args=(i,)) for i in range(count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected errors: {errors}"
        spec = lm.registry.get("SharedComp")
        assert spec is not None
        assert "Thread" in spec.intent


# -- Tests: Concurrent Remove -----------------------------------------------

class TestConcurrentRemove:
    """Concurrent component removal."""

    def test_concurrent_remove_different_components(
        self, lm: LifecycleManager,
    ) -> None:
        """10 threads each remove a different component. All removals succeed."""
        count = 10
        for i in range(count):
            lm.registry.register(_make_spec(f"RemComp{i}"))

        errors: list[Exception] = []

        def _remove(idx: int) -> None:
            try:
                lm.remove_component(f"RemComp{idx}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_remove, args=(i,)) for i in range(count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected errors: {errors}"
        assert lm.registry.count() == 0

    def test_concurrent_remove_same_component(
        self, lm: LifecycleManager,
    ) -> None:
        """5 threads try to remove the same component. Exactly 1 succeeds."""
        lm.registry.register(_make_spec("OnlyOne"))
        successes: list[int] = []
        failures: list[int] = []
        count = 5

        def _remove(idx: int) -> None:
            try:
                lm.remove_component("OnlyOne")
                successes.append(idx)
            except (RegistryIntegrityError, LifecycleError):
                failures.append(idx)

        threads = [threading.Thread(target=_remove, args=(i,)) for i in range(count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successes) == 1
        assert len(failures) == count - 1
        assert not lm.registry.contains("OnlyOne")


# -- Tests: Concurrent Mixed ------------------------------------------------

class TestConcurrentMixed:
    """Mixed concurrent operations."""

    def test_concurrent_mixed_operations(
        self, lm: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Mix of create, update, and remove across 10 threads. Registry consistent."""
        # Pre-register some components for update and remove
        for i in range(5):
            lm.registry.register(_make_spec(f"MixUpd{i}"))
        for i in range(5):
            lm.registry.register(_make_spec(f"MixRem{i}"))

        errors: list[Exception] = []

        def _create(idx: int) -> None:
            try:
                name = f"MixNew{idx}"
                target = tmp_path / f"mix_create_{idx}"
                spec = _make_spec(name)
                lm.create_component_at_runtime(
                    _make_source(name), spec, target_dir=target,
                )
            except Exception as e:
                errors.append(e)

        def _update(idx: int) -> None:
            try:
                lm.update_component(
                    f"MixUpd{idx}",
                    intent=f"Mixed update intent for component number {idx}",
                )
            except Exception as e:
                errors.append(e)

        def _remove(idx: int) -> None:
            try:
                lm.remove_component(f"MixRem{idx}")
            except Exception as e:
                errors.append(e)

        threads: list[threading.Thread] = []
        for i in range(3):
            threads.append(threading.Thread(target=_create, args=(i,)))
        for i in range(5):
            threads.append(threading.Thread(target=_update, args=(i,)))
        for i in range(5):
            threads.append(threading.Thread(target=_remove, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected errors: {errors}"
        # 5 pre-registered updates + 3 created - 5 removed = 8
        # But the update targets still exist (updated, not removed)
        assert lm.registry.count() == 8

    def test_registry_state_consistent_after_concurrent_ops(
        self, lm: LifecycleManager, tmp_path: Path,
    ) -> None:
        """snapshot() after concurrent operations produces a valid snapshot."""
        for i in range(5):
            lm.registry.register(_make_spec(f"SnapComp{i}"))

        errors: list[Exception] = []

        def _update(idx: int) -> None:
            try:
                lm.update_component(
                    f"SnapComp{idx}",
                    intent=f"Snapshot test update intent for comp {idx}",
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_update, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        snapshot = lm.registry.snapshot()
        assert snapshot.component_count == 5
        assert len(snapshot.components) == 5


# -- Tests: Transaction Serialization ----------------------------------------

class TestTransactionSerialization:
    """Transactions are serialized (no interleaving)."""

    def test_concurrent_transactions_serialized(
        self, lm: LifecycleManager,
    ) -> None:
        """Two concurrent transactions don't interleave operations."""
        # Pre-register components for each transaction
        for i in range(5):
            lm.registry.register(_make_spec(f"TxnA{i}"))
        for i in range(5):
            lm.registry.register(_make_spec(f"TxnB{i}"))

        order: list[str] = []
        errors: list[Exception] = []

        def _txn_a() -> None:
            try:
                with lm.transaction() as txn:
                    for i in range(5):
                        txn.update_component(
                            f"TxnA{i}",
                            intent=f"Transaction A update for component {i}",
                        )
                        order.append(f"A{i}")
            except Exception as e:
                errors.append(e)

        def _txn_b() -> None:
            try:
                with lm.transaction() as txn:
                    for i in range(5):
                        txn.update_component(
                            f"TxnB{i}",
                            intent=f"Transaction B update for component {i}",
                        )
                        order.append(f"B{i}")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=_txn_a)
        t2 = threading.Thread(target=_txn_b)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Unexpected errors: {errors}"

        # Because transactions hold the lock, all A's should come before all B's
        # or all B's before all A's. No interleaving.
        a_indices = [i for i, x in enumerate(order) if x.startswith("A")]
        b_indices = [i for i, x in enumerate(order) if x.startswith("B")]

        if a_indices and b_indices:
            # Either all A's come first, or all B's come first
            a_block = max(a_indices) < min(b_indices)
            b_block = max(b_indices) < min(a_indices)
            assert a_block or b_block, (
                f"Transactions interleaved: {order}"
            )
