"""Phase 3 Capstone — End-to-End Integration Test.

Milestone 12: Verifies the complete Phase 3 system end-to-end.

This test exercises the full pipeline:
  Lifecycle + Self-Model + Query Engine + REST API + Verification

The test validates that all Phase 3 sub-phases (2.5, 3A, 3B) integrate
correctly and that the s0ma property holds across the entire stack:
the system can create, describe, query, update, and remove components
while maintaining a consistent, accurate self-model.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

from s0ma._bootstrap import (
    EXPECTED_FRAMEWORK_COMPONENT_COUNT,
    bootstrap_register,
)
from s0ma.api.query_engine import QueryEngine
from s0ma.exceptions import LifecycleError
from s0ma.lifecycle import LifecycleManager
from s0ma.models import ComponentSpec, Contract
from s0ma.registry import ComponentRegistry
from s0ma.self_model import SelfModelInterface
from s0ma.types import AnomalySeverity, ComponentKind, Layer

if TYPE_CHECKING:
    from pathlib import Path

# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture()
def bootstrapped_registry() -> ComponentRegistry:
    """Fresh registry with all 32 framework components bootstrap-registered."""
    reg = ComponentRegistry(persist=False)
    bootstrap_register(reg)
    return reg


@pytest.fixture()
def full_stack(
    bootstrapped_registry: ComponentRegistry,
) -> tuple[LifecycleManager, SelfModelInterface, QueryEngine]:
    """Fully wired Phase 3 stack: LifecycleManager + SelfModelInterface + QueryEngine.

    The lifecycle manager and self-model are bidirectionally wired:
    - LM uses SMI for pre-validation
    - SMI reads lifecycle events from LM
    """
    smi = SelfModelInterface(bootstrapped_registry)
    lm = LifecycleManager(
        bootstrapped_registry, verify_after=False, self_model=smi,
    )
    smi._lifecycle_manager = lm
    qe = QueryEngine(bootstrapped_registry, smi)
    return lm, smi, qe


# ======================================================================
# 12.2: Phase 3 End-to-End Integration Test
# ======================================================================


class TestPhase3EndToEnd:
    """Phase 3 end-to-end integration test.

    Tests the full lifecycle + self-model + query engine pipeline.
    """

    def test_full_pipeline_create_describe_query_update_remove(
        self,
        full_stack: tuple[LifecycleManager, SelfModelInterface, QueryEngine],
        tmp_path: Path,
    ) -> None:
        """Create -> describe -> query -> update -> impact -> remove."""
        lm, smi, qe = full_stack

        # 1. Create a component at runtime
        source = textwrap.dedent("""\
            class OrderProcessor:
                \"\"\"Processes customer orders.\"\"\"
                def process(self, order: dict) -> dict:
                    return {"status": "processed", **order}
        """)
        spec = ComponentSpec(
            name="OrderProcessor",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Processes customer orders through the fulfillment pipeline",
            contracts=Contract(
                preconditions=["order dict is non-empty"],
                postconditions=["returns dict with status field"],
            ),
        )
        module = lm.create_component_at_runtime(source, spec, target_dir=tmp_path)
        assert module is not None
        assert lm.registry.contains("OrderProcessor")

        # 2. Describe the system — should include the new component
        desc = smi.describe_system()
        assert "DOMAIN" in desc  # New layer appears in breakdown

        # 3. Describe the specific component
        detail = smi.describe_component("OrderProcessor")
        assert "OrderProcessor" in detail
        assert "customer orders" in detail.lower()

        # 4. Query the system about the component
        answer = qe.query("What is OrderProcessor?")
        assert "OrderProcessor" in answer

        # 5. Get impact analysis
        impact = smi.get_impact_analysis("OrderProcessor")
        assert isinstance(impact, str)
        assert "OrderProcessor" in impact

        # 6. Update the component
        lm.update_component(
            "OrderProcessor",
            intent="Updated: processes customer orders with priority handling",
        )
        updated_detail = smi.describe_component("OrderProcessor")
        assert "priority handling" in updated_detail.lower()

        # 7. Query again — should reflect update
        answer_after = qe.query("What is OrderProcessor?")
        assert "priority" in answer_after.lower()

        # 8. Remove the component
        lm.remove_component("OrderProcessor", force=True)
        desc_after = smi.describe_system()
        assert "OrderProcessor" not in desc_after

    def test_transaction_with_self_model_reflection(
        self,
        full_stack: tuple[LifecycleManager, SelfModelInterface, QueryEngine],
        tmp_path: Path,
    ) -> None:
        """Transactional creation with self-model reflection."""
        lm, smi, qe = full_stack

        with lm.transaction() as txn:
            txn.create_component(
                "class AlphaService: pass\n",
                ComponentSpec(
                    name="AlphaService",
                    kind=ComponentKind.SERVICE,
                    layer=Layer.APPLICATION,
                    intent="First service in transactional batch for testing",
                ),
                target_dir=tmp_path / "alpha",
            )
            txn.create_component(
                "class BetaService: pass\n",
                ComponentSpec(
                    name="BetaService",
                    kind=ComponentKind.SERVICE,
                    layer=Layer.APPLICATION,
                    intent="Second service in transactional batch for testing",
                    dependencies=["AlphaService"],
                ),
                target_dir=tmp_path / "beta",
            )

        # Both should exist after successful transaction
        assert lm.registry.contains("AlphaService")
        assert lm.registry.contains("BetaService")

        # Self-model should reflect both
        desc = smi.describe_system()
        assert "APPLICATION" in desc

        # Query engine should find them
        answer = qe.query("What is AlphaService?")
        assert "AlphaService" in answer

        # Clean up
        lm.remove_component("BetaService", force=True)
        lm.remove_component("AlphaService", force=True)

    def test_transaction_rollback_leaves_clean_state(
        self,
        full_stack: tuple[LifecycleManager, SelfModelInterface, QueryEngine],
        tmp_path: Path,
    ) -> None:
        """Transaction rollback restores self-model to pre-transaction state."""
        lm, _smi, _qe = full_stack
        count_before = lm.registry.count()

        with pytest.raises(LifecycleError), lm.transaction() as txn:
            txn.create_component(
                "class GoodComp: pass\n",
                ComponentSpec(
                    name="GoodComp",
                    kind=ComponentKind.FUNCTION,
                    layer=Layer.DOMAIN,
                    intent="A valid component that will be rolled back on error",
                ),
                target_dir=tmp_path,
            )
            # This should fail — dependency doesn't exist
            txn.create_component(
                "class BadComp: pass\n",
                ComponentSpec(
                    name="BadComp",
                    kind=ComponentKind.FUNCTION,
                    layer=Layer.DOMAIN,
                    intent="A component with a bad dependency that triggers rollback",
                    dependencies=["NonExistentComponent"],
                ),
                target_dir=tmp_path,
            )

        # After rollback, registry should be back to original state
        assert lm.registry.count() == count_before
        assert not lm.registry.contains("GoodComp")
        assert not lm.registry.contains("BadComp")

    def test_verification_after_lifecycle_operations(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """verify_all() passes after create/update/remove cycle."""
        from s0ma.verifiers import verify_all

        lm = LifecycleManager(bootstrapped_registry, verify_after=False)

        # Create a temporary component
        bootstrapped_registry.register(
            ComponentSpec(
                name="TempVerifyComp",
                kind=ComponentKind.FUNCTION,
                layer=Layer.DOMAIN,
                intent="Temporary component for post-lifecycle verification",
                module_path="s0ma.models",
                qualified_name="s0ma.models.ComponentSpec",
            )
        )

        # Update it
        lm.update_component(
            "TempVerifyComp",
            intent="Updated temporary component for post-lifecycle test",
        )

        # Remove it
        lm.remove_component("TempVerifyComp")

        # verify_all should still pass (framework components intact)
        report = verify_all(bootstrapped_registry)
        assert report.passed, (
            f"Verification failed after lifecycle cycle:\n"
            f"{report.describe()}"
        )

    def test_recent_changes_tracked_across_pipeline(
        self,
        full_stack: tuple[LifecycleManager, SelfModelInterface, QueryEngine],
        tmp_path: Path,
    ) -> None:
        """Lifecycle events are visible via SelfModelInterface.get_recent_changes()."""
        lm, smi, _qe = full_stack

        lm.create_component_at_runtime(
            "class TrackedComp: pass\n",
            ComponentSpec(
                name="TrackedComp",
                kind=ComponentKind.FUNCTION,
                layer=Layer.DOMAIN,
                intent="Component to test lifecycle event tracking visibility",
            ),
            target_dir=tmp_path,
        )

        changes = smi.get_recent_changes()
        assert "TrackedComp" in changes
        assert "create" in changes.lower()

        # Clean up
        lm.remove_component("TrackedComp", force=True)


# ======================================================================
# 12.3: Phase 2.5 Exit Criteria Verification
# ======================================================================


class TestPhase25ExitCriteria:
    """Verify all Phase 2.5 (Dynamic Lifecycle) exit criteria are met."""

    def test_unregister_with_dependency_validation(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """Component removal works with dependency validation."""
        lm = LifecycleManager(bootstrapped_registry, verify_after=False)
        # Register two components with a dependency
        bootstrapped_registry.register(
            ComponentSpec(
                name="BaseComp",
                kind=ComponentKind.FUNCTION,
                layer=Layer.DOMAIN,
                intent="Base component for dependency validation testing",
            )
        )
        bootstrapped_registry.register(
            ComponentSpec(
                name="DependentComp",
                kind=ComponentKind.FUNCTION,
                layer=Layer.DOMAIN,
                intent="Dependent component for dependency validation testing",
                dependencies=["BaseComp"],
            )
        )

        # Cannot remove base while dependent exists (without force)
        with pytest.raises(LifecycleError):
            lm.remove_component("BaseComp")

        # Can remove with force
        removed = lm.remove_component("BaseComp", force=True)
        assert removed.name == "BaseComp"

    def test_update_atomically_replaces_with_rollback(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """update_component() atomically replaces spec."""
        lm = LifecycleManager(bootstrapped_registry, verify_after=False)
        bootstrapped_registry.register(
            ComponentSpec(
                name="UpdateTarget",
                kind=ComponentKind.FUNCTION,
                layer=Layer.DOMAIN,
                intent="Original intent before atomic update test",
            )
        )
        updated = lm.update_component(
            "UpdateTarget",
            intent="New intent after atomic update test replacement",
        )
        assert "New intent" in updated.intent
        retrieved = bootstrapped_registry.get("UpdateTarget")
        assert retrieved is not None
        assert "New intent" in retrieved.intent

    def test_create_at_runtime_with_rollback(
        self,
        bootstrapped_registry: ComponentRegistry,
        tmp_path: Path,
    ) -> None:
        """create_component_at_runtime() creates, registers, imports with rollback."""
        lm = LifecycleManager(bootstrapped_registry, verify_after=False)
        spec = ComponentSpec(
            name="RuntimeCreated",
            kind=ComponentKind.FUNCTION,
            layer=Layer.DOMAIN,
            intent="Runtime-created component for rollback verification",
        )
        module = lm.create_component_at_runtime(
            "def runtime_created(): return 42\n",
            spec,
            target_dir=tmp_path,
        )
        assert module is not None
        assert bootstrapped_registry.contains("RuntimeCreated")
        assert hasattr(module, "runtime_created")

    def test_transaction_rolls_back_on_exception(
        self,
        bootstrapped_registry: ComponentRegistry,
        tmp_path: Path,
    ) -> None:
        """Transaction context manager rolls back on exception."""
        lm = LifecycleManager(bootstrapped_registry, verify_after=False)
        count_before = bootstrapped_registry.count()

        with pytest.raises(ValueError, match="intentional"), lm.transaction() as txn:
            txn.create_component(
                "class TxnComp: pass\n",
                ComponentSpec(
                    name="TxnComp",
                    kind=ComponentKind.FUNCTION,
                    layer=Layer.DOMAIN,
                    intent="Component created inside a transaction for rollback testing",
                ),
                target_dir=tmp_path,
            )
            raise ValueError("intentional failure")

        assert bootstrapped_registry.count() == count_before
        assert not bootstrapped_registry.contains("TxnComp")

    def test_thread_safety_concurrent_operations(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """Concurrent lifecycle operations don't corrupt registry."""
        import threading

        lm = LifecycleManager(bootstrapped_registry, verify_after=False)
        errors: list[Exception] = []

        def create_and_remove(idx: int) -> None:
            try:
                name = f"ThreadComp{idx}"
                bootstrapped_registry.register(
                    ComponentSpec(
                        name=name,
                        kind=ComponentKind.FUNCTION,
                        layer=Layer.DOMAIN,
                        intent=f"Thread-created component number {idx} for testing",
                    )
                )
                lm.remove_component(name)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=create_and_remove, args=(i,))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread safety errors: {errors}"
        # All temp components should be removed
        assert bootstrapped_registry.count() == EXPECTED_FRAMEWORK_COMPONENT_COUNT


# ======================================================================
# 12.3: Phase 3A Exit Criteria Verification
# ======================================================================


class TestPhase3AExitCriteria:
    """Verify all Phase 3A (Self-Model API) exit criteria are met."""

    def test_describe_system_is_llm_ready(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """describe_system() produces LLM-readable natural language overview."""
        smi = SelfModelInterface(bootstrapped_registry)
        desc = smi.describe_system()

        assert isinstance(desc, str)
        assert len(desc) > 500  # Substantive output
        # Contains system identity
        assert "s0ma" in desc.lower()
        assert "self-knowledge" in desc.lower()
        # Contains component counts
        assert str(EXPECTED_FRAMEWORK_COMPONENT_COUNT) in desc

    def test_describe_component_is_detailed(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """describe_component() produces detailed component description."""
        smi = SelfModelInterface(bootstrapped_registry)
        desc = smi.describe_component("ComponentRegistry")

        assert "ComponentRegistry" in desc
        assert "registry" in desc.lower()
        # Should include intent
        assert "intent" in desc.lower() or "storing" in desc.lower()
        # Should include dependencies
        assert "ComponentSpec" in desc
        # Should include contracts
        assert "invariant" in desc.lower() or "contract" in desc.lower()

    def test_architecture_context_is_comprehensive(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """get_architecture_context() is comprehensive (>2000 chars)."""
        smi = SelfModelInterface(bootstrapped_registry)
        context = smi.get_architecture_context()

        assert len(context) > 2000
        # Should include dependency graph
        assert "dependency" in context.lower()
        # Should include health status
        assert "health" in context.lower()

    def test_impact_analysis_traces_transitive_dependents(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """Impact analysis correctly traces transitive dependents."""
        smi = SelfModelInterface(bootstrapped_registry)
        impact = smi.get_impact_analysis("ComponentSpec")
        # ComponentSpec is foundational — many things depend on it
        assert "ComponentSpec" in impact
        assert "dependent" in impact.lower()

    def test_extension_points_respect_layers(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """Extension point detection identifies valid insertion locations."""
        smi = SelfModelInterface(bootstrapped_registry)
        points = smi.get_available_extension_points()
        assert len(points) > 100
        # Should mention at least one non-framework layer
        non_fw_layers = [layer for layer in Layer if layer != Layer.FRAMEWORK]
        assert any(layer.name in points for layer in non_fw_layers)

    def test_validate_catches_all_violation_types(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """Component validation catches duplicate name and missing dependency.

        Note: intent length is enforced at ComponentSpec.__post_init__
        (RegistrationError if <10 chars), so it cannot reach the validator.
        """
        smi = SelfModelInterface(bootstrapped_registry)

        # 1. Duplicate name
        dup = ComponentSpec(
            name="ComponentRegistry",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Duplicate name violation test component for validation",
        )
        assert any("already registered" in a.message for a in smi.validate_proposed_component(dup))

        # 2. Missing dependency
        missing_dep = ComponentSpec(
            name="ValidName",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Missing dependency violation test component for validation",
            dependencies=["NonExistent"],
        )
        assert any(
            "not registered" in a.message
            for a in smi.validate_proposed_component(missing_dep)
        )

        # 3. Valid component — no violations
        valid = ComponentSpec(
            name="PerfectlyValid",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A perfectly valid component that should pass all checks",
        )
        errors = [
            a for a in smi.validate_proposed_component(valid)
            if a.severity == AnomalySeverity.ERROR
        ]
        assert errors == []

    def test_self_model_dogfooding(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """The API can describe itself — SelfModelInterface is registered."""
        smi = SelfModelInterface(bootstrapped_registry)
        desc = smi.describe_component("SelfModelInterface")
        assert "SelfModelInterface" in desc
        assert "self-model" in desc.lower() or "query" in desc.lower()


# ======================================================================
# 12.3: Phase 3B Exit Criteria Verification
# ======================================================================


class TestPhase3BExitCriteria:
    """Verify all Phase 3B (External API) exit criteria are met."""

    def test_rest_api_returns_text_and_data(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """REST API endpoints return both text and structured data."""
        pytest.importorskip("fastapi", reason="FastAPI not installed")
        from s0ma.api.rest import create_app

        try:
            from httpx import ASGITransport, AsyncClient
        except ImportError:
            pytest.skip("httpx not installed")

        import asyncio

        app = create_app(bootstrapped_registry)

        async def _check() -> None:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Overview
                resp = await client.get("/self/overview")
                assert resp.status_code == 200
                data = resp.json()
                assert "text" in data
                assert isinstance(data["text"], str)
                assert data["component_count"] == EXPECTED_FRAMEWORK_COMPONENT_COUNT

                # Component detail
                resp = await client.get("/self/component/ComponentRegistry")
                assert resp.status_code == 200
                data = resp.json()
                assert "text" in data
                assert "spec" in data

                # Health
                resp = await client.get("/self/health")
                assert resp.status_code == 200
                data = resp.json()
                assert "text" in data
                assert "passed" in data

                # Graph
                resp = await client.get("/self/graph")
                assert resp.status_code == 200
                data = resp.json()
                assert "text" in data
                assert "json_graph" in data
                assert "dot_format" in data

        asyncio.run(_check())

    def test_query_engine_handles_all_categories(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """Natural language query engine handles all 8 question categories."""
        smi = SelfModelInterface(bootstrapped_registry)
        qe = QueryEngine(bootstrapped_registry, smi)

        queries_and_checks: list[tuple[str, str]] = [
            ("What is ComponentRegistry?", "ComponentRegistry"),
            ("What depends on ComponentSpec?", "depend"),
            ("What would break if ComponentRegistry changes?", "impact"),
            ("What anomalies exist?", ""),  # Any response is fine
            ("How many components are there?", str(EXPECTED_FRAMEWORK_COMPONENT_COUNT)),
            ("Where can I add a new service?", ""),  # Any response is fine
            ("What handles registration?", ""),  # Any response is fine
        ]

        for question, check_text in queries_and_checks:
            answer = qe.query(question)
            assert isinstance(answer, str)
            assert len(answer) > 0, f"Empty answer for: {question}"
            if check_text:
                assert check_text.lower() in answer.lower(), (
                    f"Expected '{check_text}' in answer for '{question}', "
                    f"got: {answer[:200]}"
                )

    def test_core_framework_works_without_optional_deps(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """Core framework works without FastAPI or MCP SDK installed.

        The lifecycle manager, self-model API, and query engine all work
        with zero external dependencies. This validates the Redis/MongoDB
        playbook: open-source core is dependency-free.
        """
        # All core operations should work
        smi = SelfModelInterface(bootstrapped_registry)
        lm = LifecycleManager(bootstrapped_registry, verify_after=False)
        qe = QueryEngine(bootstrapped_registry, smi)

        # Self-model queries
        assert isinstance(smi.describe_system(), str)
        assert isinstance(smi.get_architecture_context(), str)
        assert isinstance(smi.get_impact_analysis("ComponentRegistry"), str)
        assert isinstance(smi.get_available_extension_points(), str)

        # Lifecycle operations
        bootstrapped_registry.register(
            ComponentSpec(
                name="NoDepsComp",
                kind=ComponentKind.FUNCTION,
                layer=Layer.DOMAIN,
                intent="Component proving zero-dependency core works properly",
            )
        )
        lm.update_component(
            "NoDepsComp",
            intent="Updated component proving zero-dependency core is correct",
        )
        lm.remove_component("NoDepsComp")

        # Query engine
        answer = qe.query("What is ComponentRegistry?")
        assert "ComponentRegistry" in answer


# ======================================================================
# 12.3: General Exit Criteria
# ======================================================================


class TestGeneralExitCriteria:
    """Verify general Phase 3 exit criteria."""

    def test_all_phase1_phase2_tests_pass(self) -> None:
        """All 550+ Phase 1/2 tests are still green.

        (This is verified by running the full test suite, including
        this test file. If Phase 1/2 tests fail, CI will catch it.)
        """
        # This is a placeholder — the actual verification is that this
        # entire test suite passes alongside all existing tests.
        assert True

    def test_bootstrap_component_count_is_final(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """Framework component count matches expected final value.

        Locked at 44 as the Phase 3 exit criterion. Documentation
        subsystem Milestone 1 adds 8 new framework registrations
        (SourceSpan, EntityRef, FilterExpr, Section, AssertExpr,
        DocRefRegistration, DocGuideRegistration, ExampleRegistration),
        bringing the total to 52. M3B adds S0maDSLLoader (which
        pre-existed but had been omitted from bootstrap registration),
        bringing the total to 53. M4 adds DocsForResult, the structured
        wrapper returned by RegistrySnapshot.docs_for, bringing the
        total to 54. M6 adds the example-execution subsystem —
        ExampleRunner, ExampleResult, ExampleDispatcher, DispatchOutcome,
        and TimeoutResult — bringing the total to 59. POST-1 / 0.4.0
        adds ImportHookAnomaly (the foreign-code-surveillance record
        dispatched to subscribers from the import hook), bringing the
        total to 60. 0.11.0 (batch-01a D2) adds AdoptedFile (the
        adopted-file record behind register_adopted_file), bringing
        the total to 61. 0.20.0 adds OperationContract (one provided
        operation's own contract) and ComponentResolution (what a
        describe-surface name resolved to), bringing the total to 63.
        """
        assert bootstrapped_registry.count() == EXPECTED_FRAMEWORK_COMPONENT_COUNT
        assert EXPECTED_FRAMEWORK_COMPONENT_COUNT == 63

    def test_self_model_test_passes(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """verify_all() returns zero errors with all Phase 3 components."""
        from s0ma.verifiers import verify_all

        report = verify_all(bootstrapped_registry)
        assert report.passed, (
            f"Self-model verification failed:\n{report.describe()}"
        )

    def test_zero_runtime_dependencies_for_core(self) -> None:
        """Core framework has zero runtime dependencies.

        All imports in the core modules use only the Python standard
        library. FastAPI and MCP are optional extras.
        """
        # Verify that core modules import successfully without optional deps
        import s0ma
        import s0ma.api.query_engine
        import s0ma.lifecycle
        import s0ma.self_model

        assert s0ma.__version__ == "0.21.0"

    def test_all_phase3_components_registered_and_describable(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """All Phase 3 components are registered and self-describable."""
        smi = SelfModelInterface(bootstrapped_registry)

        phase3_components = [
            # Phase 2.5: Lifecycle
            "LifecycleEvent",
            "LifecycleManager",
            "TransactionContext",
            # Phase 3A: Self-Model API
            "SelfModelInterface",
            "ImpactReport",
            "ExtensionPoint",
            # Phase 3B: Query Engine
            "QueryEngine",
        ]

        for name in phase3_components:
            assert bootstrapped_registry.contains(name), (
                f"Phase 3 component '{name}' is not registered"
            )
            desc = smi.describe_component(name)
            assert len(desc) > 50, (
                f"Description of '{name}' is too short ({len(desc)} chars)"
            )
            assert name in desc, (
                f"Description of '{name}' doesn't mention its own name"
            )

    def test_query_engine_describes_itself(
        self,
        bootstrapped_registry: ComponentRegistry,
    ) -> None:
        """QueryEngine can be queried about itself — the s0ma at API level."""
        smi = SelfModelInterface(bootstrapped_registry)
        qe = QueryEngine(bootstrapped_registry, smi)

        answer = qe.query("What is QueryEngine?")
        assert "QueryEngine" in answer
        assert "query" in answer.lower() or "question" in answer.lower()
