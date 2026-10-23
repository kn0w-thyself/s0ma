"""MCP server implementation for the s0ma self-model.

Makes the system natively queryable from Claude Code, Claude Desktop,
or any MCP client via the Model Context Protocol.

Usage::

    from s0ma import initialize
    from s0ma.api.mcp_server import create_mcp_server

    registry = initialize(persist=False)
    server = create_mcp_server(registry)
    server.run()  # stdio transport

All tools return natural language text suitable for LLM consumption.
Teaching resources and tools are also available — use them to learn
how to build applications with s0ma. Documentation is served from
the actual source files (never cached copies), so it is always current.

Requires: ``pip install s0ma-core[mcp]``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as _exc:
    raise ImportError(
        "The s0ma MCP server requires the MCP SDK. "
        "Install it with: pip install s0ma-core[mcp]"
    ) from _exc

from s0ma.api.query_engine import QueryEngine
from s0ma.api.teaching import TeachingProvider
from s0ma.exceptions import RegistryIntegrityError
from s0ma.self_model.analyzers import explain_dependency_chain
from s0ma.self_model.formatters import format_health_summary
from s0ma.self_model.interface import SelfModelInterface

__all__ = ["create_mcp_server"]


def create_mcp_server(
    registry: Any,
    *,
    metrics_collector: Any | None = None,
    lifecycle_manager: Any | None = None,
    docs_dir: str | Path | None = None,
) -> FastMCP:
    """Create an MCP server with self-model and teaching tools.

    Args:
        registry: The ComponentRegistry to expose via MCP.
        metrics_collector: Optional MetricsCollector for runtime data.
        lifecycle_manager: Optional LifecycleManager for lifecycle events.
        docs_dir: Optional path to the docs/ directory for teaching
            resources. If ``None``, auto-resolves from the s0ma
            package location.

    Returns:
        A configured FastMCP server instance.
    """
    smi = SelfModelInterface(
        registry,
        metrics_collector=metrics_collector,
        lifecycle_manager=lifecycle_manager,
    )

    docs_path = Path(docs_dir) if docs_dir is not None else None
    teacher = TeachingProvider(registry, docs_dir=docs_path)

    mcp = FastMCP(
        "s0ma-self-model",
        instructions=(
            "This server exposes the s0ma self-model — a load-bearing "
            "self-description of the software system. Use these tools to "
            "understand the system's architecture, components, health, "
            "and dependency relationships. Use the teaching tools "
            "(learn_about_s0ma, get_component_example, get_compliance_checklist) "
            "and resources (s0ma://docs/*) to learn how to use the framework."
        ),
    )

    @mcp.tool()
    def describe_system() -> str:
        """Get a natural language overview of the system architecture.

        Returns a comprehensive description including component counts,
        architectural layers, key patterns, and current health status.
        The layer and kind breakdowns list the application's own
        components; s0ma's framework components are counted but not
        listed. Use this to understand what the system is before making
        changes.
        """
        return smi.describe_system()

    @mcp.tool()
    def find_component(name: str) -> str:
        """Get detailed information about a specific component.

        Args:
            name: The name of the component to look up, or the name of an
                operation a component provides; that answers for the
                providing component and says so.

        Returns the component's identity, purpose, contracts, the
        operations it provides with each operation's own expects,
        guarantees and returns, dependencies, dependents, and source
        location.
        """
        try:
            return smi.describe_component(name)
        except RegistryIntegrityError as exc:
            return str(exc)

    @mcp.tool()
    def check_health() -> str:
        """Get the system's current health status and anomalies.

        Runs verification against the self-model and reports any
        discrepancies between the registry and the actual codebase.
        """
        report = smi._try_verify()
        if report is None:
            return "Health status: No verification data available."
        return format_health_summary(report)

    @mcp.tool()
    def explain_dependency(source: str, target: str) -> str:
        """Explain why component 'source' depends on component 'target'.

        Traces the dependency chain and explains the architectural
        reason for the relationship. Reports whether the dependency
        is direct or transitive.

        Args:
            source: Name of the component that depends on target, or of an
                operation it provides.
            target: Name of the component being depended upon, or of an
                operation it provides.
        """
        try:
            return explain_dependency_chain(registry, source, target)
        except RegistryIntegrityError as exc:
            return str(exc)

    @mcp.tool()
    def suggest_fix(anomaly_description: str) -> str:
        """Given an anomaly description, suggest how to fix it.

        Analyzes the anomaly type and provides actionable remediation
        steps based on the biological pathology taxonomy.

        Args:
            anomaly_description: A description of the anomaly to fix.
        """
        return _suggest_fix_for_anomaly(anomaly_description, registry)

    @mcp.tool()
    def get_impact(component: str) -> str:
        """Analyze what would be affected if a component changes.

        Returns direct and transitive dependents, affected architectural
        layers, and a risk assessment (low/medium/high).

        Args:
            component: Name of the component to analyze, or of an operation
                it provides; the analysis is then the providing component's.
        """
        try:
            return smi.get_impact_analysis(component)
        except RegistryIntegrityError as exc:
            return str(exc)

    @mcp.tool()
    def get_extension_points() -> str:
        """Find where new components can be added safely.

        Identifies valid extension locations organized by architectural
        layer, with suggestions for component kinds and potential
        dependency targets.
        """
        return smi.get_available_extension_points()

    query_engine = QueryEngine(
        registry,
        smi,
        metrics_collector=metrics_collector,
    )

    @mcp.tool()
    def query_system(question: str) -> str:
        """Ask a natural language question about the system.

        Supports questions like:
        - "What is ComponentRegistry?"
        - "What depends on ComponentSpec?"
        - "What would break if I changed ComponentRegistry?"
        - "Are there any anomalies?"
        - "How many components are there?"
        - "Where can I add a new service?"
        - "What handles registration?"
        - "How do I create a component?"

        Args:
            question: A natural language question about the system.
        """
        return query_engine.query(question)

    # ------------------------------------------------------------------
    # Teaching resources — serve docs from disk (never cached copies)
    # ------------------------------------------------------------------

    @mcp.resource("s0ma://docs/user-guide")
    def user_guide_resource() -> str:
        """The complete s0ma user guide — how to build applications with s0ma.

        Read from the guide itself when this is a checkout: setup,
        creating/modifying/removing components, querying the self-model,
        anomaly reports, best practices, and compliance rules. From an
        installed package the packaged teaching content answers instead,
        with its own map of what it holds.
        """
        return teacher.get_user_guide()

    @mcp.resource("s0ma://docs/compliance-rules")
    def compliance_rules_resource() -> str:
        """Compliance rules (Appendix C) — every rule for s0ma-compliant code.

        Contains all enforcement levels (ENFORCED, VERIFIED, CONVENTION),
        organized by category: initialization, registration, modification,
        removal, self-model integrity, contracts, verification, and
        agent-specific rules. Includes a quick compliance checklist.
        """
        return teacher.get_compliance_rules()

    @mcp.resource("s0ma://docs/architecture")
    def architecture_resource() -> str:
        """How s0ma's own architecture is documented, and where to read it.

        The hand-maintained architecture narrative was retired: what s0ma
        contains is now the generated component index, and what s0ma
        promises is core's current spec. This serves the note that says so
        and names both. From an installed package, where neither document
        is on disk, the packaged teaching content answers instead.
        """
        return teacher.get_architecture()

    @mcp.resource("s0ma://model/component-template")
    def component_template_resource() -> str:
        """A real component from the registry formatted as a copyable template.

        Shows the correct @component decorator invocation with all fields
        populated. Copy and modify this for new components.
        """
        return teacher.get_component_template()

    @mcp.resource("s0ma://model/registry-summary")
    def registry_summary_resource() -> str:
        """Live system overview from the self-model.

        Current component counts, architectural layers, patterns,
        and health status — generated from the live registry.
        """
        return smi.describe_system()

    # ------------------------------------------------------------------
    # Documentation-subsystem resources (M8)
    # ------------------------------------------------------------------

    @mcp.resource("s0ma://docs/registered-docs")
    def registered_docs_resource() -> str:
        """Every registered doc-ref, doc-guide, and example.

        Generated from the live registry via ``SelfModelInterface.describe_docs()``.
        Shows each registration's intent, output target, and the entities it
        covers or demonstrates. Useful when an agent wants to know what
        documentation the system already declares before authoring more.
        """
        return smi.describe_docs()

    @mcp.resource("s0ma://model/examples-for/{component}")
    def examples_for_component_resource(component: str) -> str:
        """Canonical examples demonstrating ``component``.

        Resolves through ``RegistrySnapshot.examples_for`` — accepts a bare
        component name or a ``module::name`` shortcut. Returns an
        informative "no canonical examples" message when nothing matches.
        """
        return smi.get_examples_for_component(component)

    @mcp.resource("s0ma://model/docs-for/{component}")
    def docs_for_component_resource(component: str) -> str:
        """Doc-refs and doc-guides covering ``component``.

        Resolves through ``RegistrySnapshot.docs_for`` — accepts a bare
        component name or a ``module::name`` shortcut. Returns an
        informative "no documentation" message when nothing matches.
        """
        return smi.get_docs_for_component(component)

    # ------------------------------------------------------------------
    # Teaching tools — help agents learn the framework
    # ------------------------------------------------------------------

    @mcp.tool()
    def learn_about_s0ma(topic: str) -> str:
        """Learn how to use the s0ma framework.

        Returns relevant documentation sections and live examples for
        the given topic. Reads from the actual user guide (not cached
        copies), so the information is always current.

        Supported topics: creating components, compliance/rules,
        checklist, modifying, removing, querying, anomalies/verification,
        best practices, troubleshooting, glossary, api reference,
        setup/initialize.

        Args:
            topic: What you want to learn about (e.g., "creating components",
                   "compliance rules", "troubleshooting").
        """
        return teacher.learn_topic(topic)

    @mcp.tool()
    def get_component_example(kind: str = "") -> str:
        """Get a real component from the registry as a copyable template.

        Returns an actual registered component formatted as a @component
        decorator invocation that you can copy and modify for new
        components. The template includes all required and relevant
        optional fields.

        Args:
            kind: Optional ComponentKind filter (SERVICE, FUNCTION, MODEL,
                  ADAPTER, ORCHESTRATOR). If empty, returns a representative
                  example.
        """
        return teacher.get_component_template(kind or None)

    @mcp.tool()
    def get_compliance_checklist() -> str:
        """Get the quick compliance checklist for creating/modifying components.

        Returns the pre-flight checklist from Appendix C of the user guide.
        Run through this before submitting any s0ma component changes.
        """
        return teacher.get_compliance_checklist()

    @mcp.tool()
    def get_examples_for(component: str) -> str:
        """List canonical examples demonstrating a component.

        Surfaces every registered ``example`` whose ``demonstrates`` list
        includes the given component. Accepts a bare component name or a
        ``module::name`` shortcut. Returns an informative message when
        nothing matches — no exception.

        Agents should use this before modifying a component (agent rule
        A-8) to understand which examples they must keep in sync.

        Args:
            component: Component name or ``module::name`` shortcut.
        """
        return smi.get_examples_for_component(component)

    return mcp


def _suggest_fix_for_anomaly(
    anomaly_description: str,
    registry: Any,
) -> str:
    """Generate a fix suggestion for an anomaly based on its description.

    Uses keyword matching against the biological pathology taxonomy
    to identify the anomaly type and suggest appropriate remediation.
    """
    desc_lower = anomaly_description.lower()

    # Phantom limb: registry entry with no corresponding code
    if "phantom" in desc_lower or "no corresponding code" in desc_lower:
        return (
            "Phantom Limb Detected\n"
            "The registry contains an entry that has no matching code.\n\n"
            "Suggested fixes:\n"
            "  1. Remove the orphaned registry entry using "
            "registry.unregister(name)\n"
            "  2. Implement the missing code to match the registry entry\n"
            "  3. If the component was renamed, update the registry entry's "
            "qualified_name and module_path"
        )

    # Vestigial organ: code exists but is never used
    if "vestigial" in desc_lower or "never used" in desc_lower or "dead code" in desc_lower:
        return (
            "Vestigial Organ Detected\n"
            "Code exists but serves no active purpose.\n\n"
            "Suggested fixes:\n"
            "  1. Remove the unused code and its registry entry\n"
            "  2. If it will be needed soon, add a deprecation marker\n"
            "  3. Verify no runtime paths depend on it via coverage analysis"
        )

    # Immune response: unregistered code detected
    if "immune" in desc_lower or "unregistered" in desc_lower or "blind spot" in desc_lower:
        return (
            "Immune Response Detected\n"
            "Code exists that is not registered in the self-model.\n\n"
            "Suggested fixes:\n"
            "  1. Add @component decorator to register the entity\n"
            "  2. Add @internal decorator if it's a private helper\n"
            "  3. Add to _KNOWN_UNREGISTERED_UTILITIES if it's a utility "
            "function that can't use decorators"
        )

    # Inflammation: component exceeding resource profile
    if "inflam" in desc_lower or "exceeding" in desc_lower or "resource" in desc_lower:
        return (
            "Inflammation Detected\n"
            "A component is exceeding its declared resource profile.\n\n"
            "Suggested fixes:\n"
            "  1. Update the ResourceProfile to match actual usage\n"
            "  2. Optimize the component to meet its declared profile\n"
            "  3. Check for memory leaks or unintended recursive calls"
        )

    # Atrophied muscle: deprecated API still receiving traffic
    if "atroph" in desc_lower or "deprecated" in desc_lower:
        return (
            "Atrophied Muscle Detected\n"
            "A deprecated API is still receiving traffic.\n\n"
            "Suggested fixes:\n"
            "  1. Migrate callers to the replacement API\n"
            "  2. Add deprecation warnings to guide callers\n"
            "  3. Set a removal deadline and track migration progress"
        )

    # Layer violation
    if "layer" in desc_lower and "violation" in desc_lower:
        return (
            "Layer Violation Detected\n"
            "A component has a dependency that crosses layer boundaries.\n\n"
            "Suggested fixes:\n"
            "  1. Introduce an interface/adapter to invert the dependency\n"
            "  2. Move the component to the correct layer\n"
            "  3. Re-evaluate whether the layer assignment is correct"
        )

    # Generic / unknown anomaly
    return (
        "Anomaly Analysis\n"
        f"Description: {anomaly_description}\n\n"
        "General remediation steps:\n"
        "  1. Run verify_all() to get detailed diagnostics\n"
        "  2. Check the component's registration metadata matches its "
        "actual implementation\n"
        "  3. Review the dependency graph for unexpected relationships\n"
        "  4. Use get_impact_analysis() to understand the blast radius "
        "before making changes"
    )
