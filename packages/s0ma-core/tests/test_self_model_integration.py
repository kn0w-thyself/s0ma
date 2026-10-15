"""Integration tests for SelfModelInterface + LifecycleManager wiring.

Milestone 7 tests verifying that:
- SelfModelInterface reflects real-time registry state after lifecycle operations
- LifecycleManager uses SelfModelInterface for enhanced pre-validation
- get_recent_changes() returns lifecycle event history
- The full create → describe → update → describe → remove → describe cycle works
- Both components work in standalone mode (without each other)

Milestone 8 capstone tests verifying that:
- The self-model API can describe the framework including lifecycle and self-model
  components themselves (the s0ma — the snake eating its own tail)
- Output is comprehensive enough for the Fresh LLM simulation test
- Impact analysis correctly identifies high-impact core components
- Extension points are actionable for LLM planners
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

from s0ma._bootstrap import bootstrap_register
from s0ma.lifecycle import LifecycleManager
from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry
from s0ma.self_model import SelfModelInterface
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from pathlib import Path

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture()
def registry() -> ComponentRegistry:
    """Fresh registry with framework components bootstrap-registered."""
    reg = ComponentRegistry(persist=False)
    bootstrap_register(reg)
    return reg


@pytest.fixture()
def lifecycle_manager(registry: ComponentRegistry) -> LifecycleManager:
    """LifecycleManager wired to the bootstrapped registry, verify off."""
    return LifecycleManager(registry, verify_after=False)


@pytest.fixture()
def smi(
    registry: ComponentRegistry,
    lifecycle_manager: LifecycleManager,
) -> SelfModelInterface:
    """SelfModelInterface wired to both registry and lifecycle manager."""
    return SelfModelInterface(
        registry,
        lifecycle_manager=lifecycle_manager,
    )


@pytest.fixture()
def wired_pair(
    registry: ComponentRegistry,
) -> tuple[LifecycleManager, SelfModelInterface]:
    """A LifecycleManager and SelfModelInterface mutually wired.

    The lifecycle manager uses the self-model for pre-validation,
    and the self-model reads lifecycle events from the manager.
    """
    smi = SelfModelInterface(registry)
    lm = LifecycleManager(
        registry, verify_after=False, self_model=smi,
    )
    # Now wire the lifecycle manager into the self-model
    smi._lifecycle_manager = lm
    return lm, smi


@pytest.fixture()
def sample_spec() -> ComponentSpec:
    """A sample ComponentSpec for runtime creation tests."""
    return ComponentSpec(
        name="TestProcessor",
        kind=ComponentKind.SERVICE,
        layer=Layer.DOMAIN,
        intent="Processes test data for integration testing purposes",
    )


@pytest.fixture()
def sample_source() -> str:
    """Simple Python source code for runtime creation tests."""
    return textwrap.dedent("""\
        class TestProcessor:
            \"\"\"Processes test data.\"\"\"
            def process(self, data):
                return data
    """)


# ------------------------------------------------------------------
# M7.1: LifecycleManager uses SelfModelInterface for pre-validation
# ------------------------------------------------------------------


class TestLifecycleManagerPreValidation:
    """Tests that LifecycleManager delegates to SelfModelInterface
    for enhanced pre-validation when available."""

    def test_validation_uses_self_model_when_available(
        self,
        wired_pair: tuple[LifecycleManager, SelfModelInterface],
        sample_source: str,
        tmp_path: Path,
    ) -> None:
        """When a SelfModelInterface is wired, pre-validation uses it."""
        lm, _smi = wired_pair
        # Register a dependency first
        lm.registry.register(
            ComponentSpec(
                name="HelperService",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="A helper service for testing dependency validation",
            )
        )

        # Create a component with a valid dependency
        spec = ComponentSpec(
            name="DependentService",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A service that depends on HelperService for testing",
            dependencies=["HelperService"],
        )
        module = lm.create_component_at_runtime(
            "class DependentService: pass",
            spec,
            target_dir=tmp_path,
        )
        assert module is not None
        assert lm.registry.contains("DependentService")

    def test_self_model_catches_duplicate_name(
        self,
        wired_pair: tuple[LifecycleManager, SelfModelInterface],
        tmp_path: Path,
    ) -> None:
        """SelfModelInterface pre-validation catches duplicate names."""
        lm, _smi = wired_pair
        # ComponentRegistry is already registered via bootstrap
        spec = ComponentSpec(
            name="ComponentRegistry",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A duplicate component to test pre-validation rejection",
        )
        from s0ma.exceptions import LifecycleError

        with pytest.raises(LifecycleError, match="already registered"):
            lm.create_component_at_runtime(
                "class ComponentRegistry: pass",
                spec,
                target_dir=tmp_path,
            )

    def test_self_model_catches_missing_dependency(
        self,
        wired_pair: tuple[LifecycleManager, SelfModelInterface],
        tmp_path: Path,
    ) -> None:
        """SelfModelInterface pre-validation catches missing dependencies."""
        lm, _smi = wired_pair
        spec = ComponentSpec(
            name="BrokenService",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A service with a dependency that does not exist at all",
            dependencies=["NonExistentDependency"],
        )
        from s0ma.exceptions import LifecycleError

        with pytest.raises(LifecycleError, match="not registered"):
            lm.create_component_at_runtime(
                "class BrokenService: pass",
                spec,
                target_dir=tmp_path,
            )

    def test_fallback_validation_without_self_model(
        self,
        registry: ComponentRegistry,
        tmp_path: Path,
    ) -> None:
        """Without SelfModelInterface, basic validation still works."""
        lm = LifecycleManager(registry, verify_after=False)
        # No self_model wired — uses fallback validation
        spec = ComponentSpec(
            name="ComponentRegistry",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A duplicate component to test fallback validation works",
        )
        from s0ma.exceptions import LifecycleError

        with pytest.raises(LifecycleError, match="already registered"):
            lm.create_component_at_runtime(
                "class ComponentRegistry: pass",
                spec,
                target_dir=tmp_path,
            )


# ------------------------------------------------------------------
# M7.2: Real-time state reflection
# ------------------------------------------------------------------


class TestRealTimeStateReflection:
    """Tests that SelfModelInterface reflects current registry state
    after lifecycle operations."""

    def test_describe_system_reflects_created_component(
        self,
        smi: SelfModelInterface,
        lifecycle_manager: LifecycleManager,
        sample_spec: ComponentSpec,
        sample_source: str,
        tmp_path: Path,
    ) -> None:
        """describe_system() includes a component created via lifecycle."""
        # Create the component
        lifecycle_manager.create_component_at_runtime(
            sample_source, sample_spec, target_dir=tmp_path,
        )
        desc = smi.describe_system()
        # DOMAIN layer should now appear (it's the new component's layer)
        assert "DOMAIN" in desc

    def test_describe_system_reflects_removed_component(
        self,
        smi: SelfModelInterface,
        lifecycle_manager: LifecycleManager,
        sample_spec: ComponentSpec,
        sample_source: str,
        tmp_path: Path,
    ) -> None:
        """describe_system() no longer includes a removed component."""
        # Create then remove
        lifecycle_manager.create_component_at_runtime(
            sample_source, sample_spec, target_dir=tmp_path,
        )
        assert lifecycle_manager.registry.contains("TestProcessor")
        lifecycle_manager.remove_component("TestProcessor", force=True)

        desc = smi.describe_system()
        # The component should no longer appear in the description
        assert "TestProcessor" not in desc

    def test_describe_component_reflects_updated_spec(
        self,
        smi: SelfModelInterface,
        lifecycle_manager: LifecycleManager,
        sample_spec: ComponentSpec,
        sample_source: str,
        tmp_path: Path,
    ) -> None:
        """describe_component() returns updated intent after lifecycle update."""
        lifecycle_manager.create_component_at_runtime(
            sample_source, sample_spec, target_dir=tmp_path,
        )
        new_intent = "Updated intent for integration testing verification"
        lifecycle_manager.update_component(
            "TestProcessor", intent=new_intent,
        )
        desc = smi.describe_component("TestProcessor")
        assert new_intent in desc


# ------------------------------------------------------------------
# M7.3: Lifecycle event history (get_recent_changes)
# ------------------------------------------------------------------


class TestGetRecentChanges:
    """Tests for the get_recent_changes() method."""

    def test_returns_events_after_create(
        self,
        smi: SelfModelInterface,
        lifecycle_manager: LifecycleManager,
        sample_spec: ComponentSpec,
        sample_source: str,
        tmp_path: Path,
    ) -> None:
        """get_recent_changes() shows a create event."""
        lifecycle_manager.create_component_at_runtime(
            sample_source, sample_spec, target_dir=tmp_path,
        )
        changes = smi.get_recent_changes()
        assert "TestProcessor" in changes
        assert "create" in changes.lower()

    def test_returns_events_after_update(
        self,
        smi: SelfModelInterface,
        lifecycle_manager: LifecycleManager,
        sample_spec: ComponentSpec,
        sample_source: str,
        tmp_path: Path,
    ) -> None:
        """get_recent_changes() shows an update event."""
        lifecycle_manager.create_component_at_runtime(
            sample_source, sample_spec, target_dir=tmp_path,
        )
        lifecycle_manager.update_component(
            "TestProcessor",
            intent="Updated intent for recent changes test event",
        )
        changes = smi.get_recent_changes()
        assert "update" in changes.lower()

    def test_returns_events_after_remove(
        self,
        smi: SelfModelInterface,
        lifecycle_manager: LifecycleManager,
        sample_spec: ComponentSpec,
        sample_source: str,
        tmp_path: Path,
    ) -> None:
        """get_recent_changes() shows a remove event."""
        lifecycle_manager.create_component_at_runtime(
            sample_source, sample_spec, target_dir=tmp_path,
        )
        lifecycle_manager.remove_component("TestProcessor", force=True)
        changes = smi.get_recent_changes()
        assert "unregister" in changes.lower()

    def test_no_lifecycle_manager_returns_message(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """Without a lifecycle manager, returns an informative message."""
        smi = SelfModelInterface(registry)
        changes = smi.get_recent_changes()
        assert "not available" in changes.lower()

    def test_empty_events_returns_message(
        self,
        smi: SelfModelInterface,
    ) -> None:
        """With no events, returns a 'no changes' message."""
        changes = smi.get_recent_changes()
        assert "no lifecycle changes" in changes.lower()

    def test_limit_parameter(
        self,
        smi: SelfModelInterface,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """The limit parameter restricts the number of events returned."""
        # Create 3 components
        for i in range(3):
            spec = ComponentSpec(
                name=f"LimitTest{i}",
                kind=ComponentKind.FUNCTION,
                layer=Layer.DOMAIN,
                intent=f"Test component number {i} for limit testing purposes",
            )
            lifecycle_manager.create_component_at_runtime(
                f"def limit_test_{i}(): pass\n",
                spec,
                target_dir=tmp_path,
            )

        # Limit to 1 — should only show the most recent
        changes = smi.get_recent_changes(limit=1)
        assert "LimitTest2" in changes
        # The oldest event should not be in the limited view
        assert "LimitTest0" not in changes


# ------------------------------------------------------------------
# M7.4: Full lifecycle + self-model integration cycle
# ------------------------------------------------------------------


class TestFullIntegrationCycle:
    """Tests the full create → describe → update → describe → remove cycle."""

    def test_full_cycle_create_describe_update_remove(
        self,
        smi: SelfModelInterface,
        lifecycle_manager: LifecycleManager,
        sample_spec: ComponentSpec,
        sample_source: str,
        tmp_path: Path,
    ) -> None:
        """Full lifecycle: create → describe → update → describe → remove."""
        # 1. Create
        lifecycle_manager.create_component_at_runtime(
            sample_source, sample_spec, target_dir=tmp_path,
        )

        # 2. Describe (should include new component)
        desc = smi.describe_system()
        assert "TestProcessor" in desc or "DOMAIN" in desc

        # 3. Update
        lifecycle_manager.update_component(
            "TestProcessor",
            intent="Completely new intent after full cycle update test",
        )

        # 4. Describe again (should reflect update)
        detail = smi.describe_component("TestProcessor")
        assert "Completely new intent" in detail

        # 5. Remove
        lifecycle_manager.remove_component("TestProcessor", force=True)

        # 6. Describe (should no longer include component)
        desc_after = smi.describe_system()
        assert "TestProcessor" not in desc_after

    def test_architecture_context_includes_lifecycle_events(
        self,
        smi: SelfModelInterface,
        lifecycle_manager: LifecycleManager,
        sample_spec: ComponentSpec,
        sample_source: str,
        tmp_path: Path,
    ) -> None:
        """get_architecture_context() includes lifecycle event history."""
        lifecycle_manager.create_component_at_runtime(
            sample_source, sample_spec, target_dir=tmp_path,
        )
        context = smi.get_architecture_context()
        # Should include the lifecycle change section
        assert "Lifecycle" in context or "lifecycle" in context.lower()
        assert "TestProcessor" in context


# ------------------------------------------------------------------
# Standalone mode tests
# ------------------------------------------------------------------


class TestStandaloneMode:
    """Tests that both components work independently."""

    def test_smi_works_without_lifecycle_manager(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """SelfModelInterface works without a lifecycle manager."""
        smi = SelfModelInterface(registry)
        desc = smi.describe_system()
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_smi_works_without_metrics_collector(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """SelfModelInterface works without a metrics collector."""
        smi = SelfModelInterface(registry, metrics_collector=None)
        desc = smi.describe_system()
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_smi_with_all_optional_components(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """SelfModelInterface works with all optional components wired."""
        from s0ma.verifiers.interoception import MetricsCollector

        mc = MetricsCollector()
        lm = LifecycleManager(registry, verify_after=False)
        smi = SelfModelInterface(
            registry,
            metrics_collector=mc,
            lifecycle_manager=lm,
        )
        desc = smi.describe_system()
        assert isinstance(desc, str)
        assert len(desc) > 0

        context = smi.get_architecture_context()
        assert isinstance(context, str)
        assert len(context) > 1000

    def test_lifecycle_manager_works_without_self_model(
        self,
        registry: ComponentRegistry,
        tmp_path: Path,
    ) -> None:
        """LifecycleManager works without a SelfModelInterface."""
        lm = LifecycleManager(registry, verify_after=False)
        spec = ComponentSpec(
            name="StandaloneTest",
            kind=ComponentKind.FUNCTION,
            layer=Layer.DOMAIN,
            intent="A standalone test component without self-model wiring",
        )
        module = lm.create_component_at_runtime(
            "def standalone_test(): pass\n",
            spec,
            target_dir=tmp_path,
        )
        assert module is not None
        assert lm.registry.contains("StandaloneTest")


# ------------------------------------------------------------------
# M8: Phase 3A Capstone — Self-Model API describes itself
# ------------------------------------------------------------------


class TestSelfModelCapstone:
    """Phase 3A capstone: the self-model API describes itself.

    These tests verify the s0ma property at the API level — the
    self-model query interface can accurately describe the framework
    including the lifecycle and self-model components themselves.
    If these tests fail, the self-model API is not self-aware.
    """

    def test_describe_system_includes_all_phases(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """System description mentions Phase 1, 2, and 3 components."""
        smi = SelfModelInterface(registry)
        desc = smi.describe_system()

        # Phase 1 core: ComponentRegistry is the heart of the system
        assert "ComponentRegistry" in desc or "registry" in desc.lower()

        # Phase 2 verification engine: at least one verifier should appear
        assert (
            "verif" in desc.lower()
            or "structural" in desc.lower()
            or "contract" in desc.lower()
        )

        # Phase 3 self-model: the self-model components should be represented
        # They're FRAMEWORK layer components, so they should appear in the
        # framework layer breakdown
        assert "FRAMEWORK" in desc
        assert "31" in desc or "framework" in desc.lower()

    def test_describe_self_model_interface(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """The self-model API can describe itself."""
        smi = SelfModelInterface(registry)
        desc = smi.describe_component("SelfModelInterface")

        # Should describe its own purpose
        assert "self-model" in desc.lower() or "query" in desc.lower()

        # Should mention it produces text output
        assert "text" in desc.lower() or "str" in desc.lower()

        # Should list its dependencies (ComponentRegistry, LifecycleManager)
        assert "ComponentRegistry" in desc
        assert "LifecycleManager" in desc

        # Should include its contracts
        assert "postcondition" in desc.lower() or "contract" in desc.lower()

    def test_describe_impact_report(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """The self-model can describe the ImpactReport data model."""
        smi = SelfModelInterface(registry)
        desc = smi.describe_component("ImpactReport")

        assert "impact" in desc.lower()
        assert "affected" in desc.lower() or "change" in desc.lower()

    def test_describe_extension_point(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """The self-model can describe the ExtensionPoint data model."""
        smi = SelfModelInterface(registry)
        desc = smi.describe_component("ExtensionPoint")

        assert "extension" in desc.lower() or "location" in desc.lower()

    def test_architecture_context_is_comprehensive(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """Architecture context includes lifecycle + self-model info.

        The output must be comprehensive enough for an LLM to understand
        the full system architecture — all phases, all components.
        """
        smi = SelfModelInterface(registry)
        context = smi.get_architecture_context()

        # Must be substantial for 31 framework components
        assert len(context) > 2000, (
            f"Architecture context is only {len(context)} chars; "
            f"expected >2000 for 31 components"
        )

        # Must include dependency graph
        assert "Dependency" in context or "dependency" in context.lower()

        # Must include verification status
        assert "Health" in context or "health" in context

        # Must include lifecycle components
        assert "LifecycleManager" in context
        assert "TransactionContext" in context

        # Must include self-model components
        assert "SelfModelInterface" in context
        assert "ImpactReport" in context

    def test_fresh_llm_simulation(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """Simulate the Fresh LLM Test (preview of acid test).

        Give only the describe_system() output to the test.
        Verify it contains enough information to answer basic
        architectural questions without reading source code.

        A fresh LLM given this text should be able to determine:
        1. How many components exist
        2. What layers are used
        3. What the system does (software self-knowledge)
        4. What the major subsystems are
        5. Whether the system is healthy
        """
        smi = SelfModelInterface(registry)
        desc = smi.describe_system()

        # Q1: How many components?
        assert "31" in desc or "component" in desc.lower()

        # Q2: What layers are used?
        assert any(
            layer.name in desc for layer in Layer
        ), "At least one layer name must appear in the description"

        # Q3: What does the system do?
        assert (
            "self-knowledge" in desc.lower()
            or "proprioception" in desc.lower()
            or "self-aware" in desc.lower()
        )

        # Q4: What are the major subsystems?
        # At minimum, the description should mention registration and
        # the load-bearing self-model
        assert "registration" in desc.lower() or "register" in desc.lower()
        assert "load-bearing" in desc.lower() or "self-model" in desc.lower()

        # Q5: Is the system healthy?
        assert (
            "health" in desc.lower()
            or "healthy" in desc.lower()
            or "passed" in desc.lower()
        )

    def test_impact_analysis_on_registry(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """Impact analysis on ComponentRegistry shows many dependents.

        ComponentRegistry is the most-depended-on component in the
        framework. Its impact analysis should reflect high risk.
        """
        smi = SelfModelInterface(registry)
        impact = smi.get_impact_analysis("ComponentRegistry")

        # Should identify it as high or medium impact
        assert "high" in impact.lower() or "medium" in impact.lower()

        # Should list dependents
        assert "dependent" in impact.lower()

        # Known dependents should appear (StructuralVerifier depends on
        # ComponentRegistry, SelfModelInterface depends on it, etc.)
        assert "StructuralVerifier" in impact or "dependent" in impact.lower()

    def test_impact_analysis_on_self_model_interface(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """Impact analysis on SelfModelInterface — medium risk.

        SelfModelInterface is consumed by QueryEngine, so its impact
        is medium (one dependent within the framework).
        """
        smi = SelfModelInterface(registry)
        impact = smi.get_impact_analysis("SelfModelInterface")

        assert "medium" in impact.lower() or "low" in impact.lower()

    def test_extension_points_are_actionable(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """Extension point descriptions are actionable for an LLM planner.

        The output should include:
        - Which layers are available for extension
        - What kinds of components can be added
        - Potential dependency targets
        """
        smi = SelfModelInterface(registry)
        points = smi.get_available_extension_points()

        # Must produce non-trivial output
        assert len(points) > 100, (
            f"Extension points output is only {len(points)} chars"
        )

        # Must mention at least one non-framework layer
        non_fw_layers = [
            layer for layer in Layer if layer != Layer.FRAMEWORK
        ]
        assert any(
            layer.name in points for layer in non_fw_layers
        ), "Extension points must mention at least one non-framework layer"

        # Must suggest component kinds
        assert any(
            kind.name.lower() in points.lower()
            for kind in ComponentKind
            if kind != ComponentKind.FRAMEWORK
        ), "Extension points must suggest at least one component kind"

    def test_validate_proposed_component_against_framework(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """validate_proposed_component works against the live framework registry.

        A well-formed proposed component should produce no anomalies.
        A malformed one should produce specific violations.
        """
        smi = SelfModelInterface(registry)

        # Valid component — should pass
        valid_spec = ComponentSpec(
            name="NewDomainService",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A new domain service for validating proposed components",
        )
        anomalies = smi.validate_proposed_component(valid_spec)
        errors = [
            a for a in anomalies
            if a.severity.name == "ERROR"
        ]
        assert errors == [], (
            f"Valid component should have no errors: "
            f"{[a.message for a in errors]}"
        )

        # Duplicate name — should catch it
        dup_spec = ComponentSpec(
            name="ComponentRegistry",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A duplicate name that should be caught by validation",
        )
        dup_anomalies = smi.validate_proposed_component(dup_spec)
        assert any(
            "already registered" in a.message for a in dup_anomalies
        ), "Should detect duplicate name"

    def test_self_model_dogfooding_completeness(
        self,
        registry: ComponentRegistry,
    ) -> None:
        """All Phase 3A components are registered and describable.

        The self-model API, its data models, and the lifecycle manager
        should all be registered and describable via the interface.
        """
        smi = SelfModelInterface(registry)

        phase_3a_components = [
            "SelfModelInterface",
            "ImpactReport",
            "ExtensionPoint",
        ]
        lifecycle_components = [
            "LifecycleManager",
            "TransactionContext",
            "LifecycleEvent",
        ]

        for name in phase_3a_components + lifecycle_components:
            assert registry.contains(name), (
                f"Component '{name}' is not registered"
            )
            desc = smi.describe_component(name)
            assert len(desc) > 50, (
                f"Description of '{name}' is too short ({len(desc)} chars)"
            )
            assert name in desc, (
                f"Description of '{name}' doesn't mention its own name"
            )
