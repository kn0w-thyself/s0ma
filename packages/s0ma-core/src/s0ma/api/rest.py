"""FastAPI REST API for the s0ma self-model.

Wraps the SelfModelInterface for HTTP access by external tools,
monitoring dashboards, and Claude Code.

Usage::

    from s0ma import initialize
    from s0ma.api.rest import create_app

    registry = initialize(persist=False)
    app = create_app(registry)
    # Serve it with any ASGI server. This module exports no ``app``
    # attribute and starts nothing itself, so ``uvicorn s0ma.api.rest:app``
    # does not work — hand YOUR application object to the server, e.g.:
    #   uvicorn my_service:app          # where my_service.py holds the code above
    # Trust boundary: the routes carry no authentication and read the whole
    # self-model. Where it listens is the server's choice, not this
    # module's — bind loopback unless you have decided otherwise
    # (docs/trust-model.md, "What listens, and to whom").

All endpoints return JSON with both a ``text`` field (natural language
for LLM consumption) and structured ``data`` fields (for programmatic
access).

Requires: ``pip install s0ma-core[api]``
"""

from __future__ import annotations

from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except ImportError as _exc:
    raise ImportError(
        "The s0ma REST API requires FastAPI. "
        "Install it with: pip install s0ma-core[api]"
    ) from _exc

from s0ma import __version__
from s0ma.api.query_engine import QueryEngine
from s0ma.exceptions import RegistryIntegrityError
from s0ma.self_model.formatters import format_dependency_graph_dot
from s0ma.self_model.interface import SelfModelInterface

# Lazy imports to avoid circular dependencies at module load
# Registry and other types are imported inside functions.

__all__ = ["create_app"]


# ======================================================================
# Pydantic response models
# ======================================================================


class SelfOverviewResponse(BaseModel):
    """Response for GET /self/overview."""

    text: str
    component_count: int
    framework_component_count: int
    layers: dict[str, list[str]]


class ComponentListResponse(BaseModel):
    """Response for GET /self/components."""

    text: str
    components: list[dict[str, Any]]
    total: int


class ComponentDetailResponse(BaseModel):
    """Response for GET /self/component/{name}."""

    text: str
    spec: dict[str, Any]


class HealthResponse(BaseModel):
    """Response for GET /self/health."""

    text: str
    passed: bool
    anomaly_count: int
    erosion_coverage: dict[str, Any] | None = None


class AnomaliesResponse(BaseModel):
    """Response for GET /self/anomalies."""

    text: str
    anomalies: list[dict[str, Any]]
    total: int


class GraphResponse(BaseModel):
    """Response for GET /self/graph."""

    text: str
    json_graph: dict[str, list[str]]
    dot_format: str


class ImpactResponse(BaseModel):
    """Response for GET /self/impact/{name}."""

    text: str
    component_name: str
    risk_level: str
    direct_dependents: list[str]
    transitive_dependents: list[str]
    total_affected: int


class ExtensionsResponse(BaseModel):
    """Response for GET /self/extensions."""

    text: str
    extension_points: list[dict[str, Any]]
    total: int


class QueryRequest(BaseModel):
    """Request body for POST /self/query."""

    question: str


class QueryResponse(BaseModel):
    """Response for POST /self/query."""

    question: str
    answer: str


class DocListResponse(BaseModel):
    """Response for GET /self/docs."""

    text: str
    doc_refs: list[dict[str, Any]]
    doc_guides: list[dict[str, Any]]
    examples: list[dict[str, Any]]
    total_doc_refs: int
    total_doc_guides: int
    total_examples: int


class DocDetailResponse(BaseModel):
    """Response for GET /self/doc/{name}."""

    text: str
    kind: str
    spec: dict[str, Any]


class ExampleListResponse(BaseModel):
    """Response for GET /self/examples."""

    text: str
    examples: list[dict[str, Any]]
    total: int


class ExampleDetailResponse(BaseModel):
    """Response for GET /self/example/{name}."""

    text: str
    spec: dict[str, Any]


class DriftEntry(BaseModel):
    """A single drifted registration in the drift response."""

    kind: str
    name: str
    stored_hash: str
    recomputed_hash: str


class DriftResponse(BaseModel):
    """Response for GET /self/drift."""

    text: str
    total_doc_refs: int
    total_doc_guides: int
    doc_refs_hashed: int
    doc_guides_hashed: int
    drifted: list[DriftEntry]
    missing_hashes: list[str]


# ======================================================================
# Application factory
# ======================================================================


def create_app(
    registry: Any,
    *,
    metrics_collector: Any | None = None,
    lifecycle_manager: Any | None = None,
) -> FastAPI:
    """Create a FastAPI application with self-model endpoints.

    Args:
        registry: The ComponentRegistry to expose via REST.
        metrics_collector: Optional MetricsCollector for runtime data.
        lifecycle_manager: Optional LifecycleManager for lifecycle events.

    Returns:
        A configured FastAPI application.
    """
    app = FastAPI(
        title="s0ma Self-Model API",
        description=(
            "REST API for querying the s0ma self-model. "
            "Provides both natural language text (for LLM consumption) "
            "and structured data (for programmatic access)."
        ),
        version=__version__,
    )

    smi = SelfModelInterface(
        registry,
        metrics_collector=metrics_collector,
        lifecycle_manager=lifecycle_manager,
    )

    # ------------------------------------------------------------------
    # GET /self/overview
    # ------------------------------------------------------------------
    @app.get(
        "/self/overview",
        response_model=SelfOverviewResponse,
        summary="System overview",
        description="Get a natural language overview of the system architecture.",
    )
    def get_overview() -> SelfOverviewResponse:
        text = smi.describe_system()
        snapshot = registry.snapshot()
        return SelfOverviewResponse(
            text=text,
            component_count=snapshot.component_count,
            framework_component_count=snapshot.framework_component_count,
            layers=snapshot.layers,
        )

    # ------------------------------------------------------------------
    # GET /self/components
    # ------------------------------------------------------------------
    @app.get(
        "/self/components",
        response_model=ComponentListResponse,
        summary="All components",
        description="List all registered components with their metadata.",
    )
    def get_components() -> ComponentListResponse:
        snapshot = registry.snapshot()
        components_data = [
            spec.to_dict() for spec in sorted(
                snapshot.components.values(), key=lambda s: s.name
            )
        ]
        # Build a text summary
        text_lines = [
            f"Registered components ({snapshot.component_count} total):",
        ]
        for spec in sorted(snapshot.components.values(), key=lambda s: s.name):
            text_lines.append(
                f"  - {spec.name} ({spec.kind.name.lower()}, "
                f"{spec.layer.name.lower()})"
            )
        text = "\n".join(text_lines)

        return ComponentListResponse(
            text=text,
            components=components_data,
            total=snapshot.component_count,
        )

    # ------------------------------------------------------------------
    # GET /self/component/{name}
    # ------------------------------------------------------------------
    @app.get(
        "/self/component/{name}",
        response_model=ComponentDetailResponse,
        summary="Component detail",
        description="Get detailed information about a specific component.",
    )
    def get_component(name: str) -> ComponentDetailResponse:
        try:
            text = smi.describe_component(name)
        except RegistryIntegrityError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Component '{name}' is not registered.",
            ) from exc

        spec = registry.get(name)
        if spec is None:
            raise HTTPException(
                status_code=404,
                detail=f"Component '{name}' is not registered.",
            )

        return ComponentDetailResponse(
            text=text,
            spec=spec.to_dict(),
        )

    # ------------------------------------------------------------------
    # GET /self/health
    # ------------------------------------------------------------------
    @app.get(
        "/self/health",
        response_model=HealthResponse,
        summary="System health",
        description="Get the system's current health status and verification results.",
    )
    def get_health() -> HealthResponse:
        report = smi._try_verify()

        if report is None:
            return HealthResponse(
                text="Health status: No verification data available.",
                passed=True,
                anomaly_count=0,
                erosion_coverage=None,
            )

        from s0ma.self_model.formatters import format_health_summary

        text = format_health_summary(report)

        # Extract erosion coverage if available
        erosion_coverage: dict[str, Any] | None = None
        for result in report.results:
            erosion = result.details.get("erosion_coverage")
            if erosion and isinstance(erosion, dict):
                erosion_coverage = erosion
                break

        return HealthResponse(
            text=text,
            passed=report.passed,
            anomaly_count=report.total_anomalies,
            erosion_coverage=erosion_coverage,
        )

    # ------------------------------------------------------------------
    # GET /self/anomalies
    # ------------------------------------------------------------------
    @app.get(
        "/self/anomalies",
        response_model=AnomaliesResponse,
        summary="Current anomalies",
        description="Get current verification anomalies (code-model discrepancies).",
    )
    def get_anomalies() -> AnomaliesResponse:
        report = smi._try_verify()

        if report is None:
            return AnomaliesResponse(
                text="No verification data available.",
                anomalies=[],
                total=0,
            )

        all_anomalies: list[dict[str, Any]] = []
        for result in report.results:
            for anomaly in result.anomalies:
                all_anomalies.append(anomaly.to_dict())

        if not all_anomalies:
            text = "No anomalies detected. The self-model is consistent with the codebase."
        else:
            text = report.explain_for_llm()

        return AnomaliesResponse(
            text=text,
            anomalies=all_anomalies,
            total=len(all_anomalies),
        )

    # ------------------------------------------------------------------
    # GET /self/graph
    # ------------------------------------------------------------------
    @app.get(
        "/self/graph",
        response_model=GraphResponse,
        summary="Dependency graph",
        description=(
            "Get the full dependency graph in both JSON adjacency "
            "list and Graphviz DOT format."
        ),
    )
    def get_graph() -> GraphResponse:
        snapshot = registry.snapshot()
        graph = snapshot.dependency_graph

        from s0ma.self_model.formatters import format_dependency_graph_text

        text = format_dependency_graph_text(graph)
        dot = format_dependency_graph_dot(graph, snapshot.components)

        return GraphResponse(
            text=text,
            json_graph=graph,
            dot_format=dot,
        )

    # ------------------------------------------------------------------
    # GET /self/impact/{name}
    # ------------------------------------------------------------------
    @app.get(
        "/self/impact/{name}",
        response_model=ImpactResponse,
        summary="Impact analysis",
        description="Analyze what would be affected if a component changes.",
    )
    def get_impact(name: str) -> ImpactResponse:
        from s0ma.self_model.analyzers import compute_impact_analysis

        try:
            report = compute_impact_analysis(
                registry, name,
                metrics_collector=metrics_collector,
            )
        except RegistryIntegrityError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Component '{name}' is not registered.",
            ) from exc

        text = smi.get_impact_analysis(name)

        return ImpactResponse(
            text=text,
            component_name=report.component_name,
            risk_level=report.risk_level,
            direct_dependents=report.direct_dependents,
            transitive_dependents=report.transitive_dependents,
            total_affected=report.total_affected_count,
        )

    # ------------------------------------------------------------------
    # GET /self/extensions
    # ------------------------------------------------------------------
    @app.get(
        "/self/extensions",
        response_model=ExtensionsResponse,
        summary="Extension points",
        description="Find where new components can be added safely.",
    )
    def get_extensions() -> ExtensionsResponse:
        from s0ma.self_model.analyzers import find_extension_points

        points = find_extension_points(registry)
        text = smi.get_available_extension_points()

        extension_data: list[dict[str, Any]] = []
        for point in points:
            extension_data.append({
                "layer": point.layer.name,
                "suggested_kinds": [k.name for k in point.suggested_kinds],
                "potential_dependencies": point.potential_dependencies,
                "rationale": point.rationale,
            })

        return ExtensionsResponse(
            text=text,
            extension_points=extension_data,
            total=len(points),
        )

    # ------------------------------------------------------------------
    # GET /self/docs
    # ------------------------------------------------------------------
    @app.get(
        "/self/docs",
        response_model=DocListResponse,
        summary="Registered documentation",
        description=(
            "List every registered doc-ref, doc-guide, and example. "
            "Combines the three documentation-subsystem stores into a "
            "single natural-language overview plus structured data."
        ),
    )
    def get_docs() -> DocListResponse:
        snapshot = registry.snapshot()
        text = smi.describe_docs()
        refs = [
            snapshot.doc_refs[name].to_dict()
            for name in sorted(snapshot.doc_refs)
        ]
        guides = [
            snapshot.doc_guides[name].to_dict()
            for name in sorted(snapshot.doc_guides)
        ]
        examples = [
            snapshot.examples[name].to_dict()
            for name in sorted(snapshot.examples)
        ]
        return DocListResponse(
            text=text,
            doc_refs=refs,
            doc_guides=guides,
            examples=examples,
            total_doc_refs=len(refs),
            total_doc_guides=len(guides),
            total_examples=len(examples),
        )

    # ------------------------------------------------------------------
    # GET /self/doc/{name}
    # ------------------------------------------------------------------
    @app.get(
        "/self/doc/{name}",
        response_model=DocDetailResponse,
        summary="Documentation detail",
        description=(
            "Detailed view of a single doc-ref or doc-guide. Looks up "
            "``name`` first in the doc-ref store, then in the doc-guide "
            "store. Returns 404 if the name is not registered as "
            "either."
        ),
    )
    def get_doc(name: str) -> DocDetailResponse:
        snapshot = registry.snapshot()
        ref = snapshot.doc_refs.get(name)
        if ref is not None:
            return DocDetailResponse(
                text=smi.describe_doc(name),
                kind="doc-ref",
                spec=ref.to_dict(),
            )
        guide = snapshot.doc_guides.get(name)
        if guide is not None:
            return DocDetailResponse(
                text=smi.describe_doc(name),
                kind="doc-guide",
                spec=guide.to_dict(),
            )
        raise HTTPException(
            status_code=404,
            detail=f"Documentation '{name}' is not registered.",
        )

    # ------------------------------------------------------------------
    # GET /self/examples
    # ------------------------------------------------------------------
    @app.get(
        "/self/examples",
        response_model=ExampleListResponse,
        summary="Registered examples",
        description=(
            "List every registered example with its ``runs_in`` mode "
            "and the entities it demonstrates."
        ),
    )
    def get_examples() -> ExampleListResponse:
        snapshot = registry.snapshot()
        examples = [
            snapshot.examples[name].to_dict()
            for name in sorted(snapshot.examples)
        ]
        if not examples:
            text = (
                "No examples registered. Add an ``example`` "
                "declaration to surface canonical runnable code here."
            )
        else:
            lines = [
                f"Registered examples ({len(examples)} total):",
            ]
            for ex_name in sorted(snapshot.examples):
                ex = snapshot.examples[ex_name]
                demos = ", ".join(
                    f"{d.kind}:{d.name}" for d in ex.demonstrates
                )
                lines.append(
                    f"  - {ex_name} (runs_in={ex.runs_in}): {demos}"
                )
            text = "\n".join(lines)
        return ExampleListResponse(
            text=text,
            examples=examples,
            total=len(examples),
        )

    # ------------------------------------------------------------------
    # GET /self/example/{name}
    # ------------------------------------------------------------------
    @app.get(
        "/self/example/{name}",
        response_model=ExampleDetailResponse,
        summary="Example detail",
        description=(
            "Detailed view of a single example registration, including "
            "its body and the entities it demonstrates. Returns 404 if "
            "the name is not a registered example."
        ),
    )
    def get_example(name: str) -> ExampleDetailResponse:
        from s0ma.self_model.formatters import format_example_detail

        snapshot = registry.snapshot()
        example = snapshot.examples.get(name)
        if example is None:
            raise HTTPException(
                status_code=404,
                detail=f"Example '{name}' is not registered.",
            )
        return ExampleDetailResponse(
            text=format_example_detail(example),
            spec=example.to_dict(),
        )

    # ------------------------------------------------------------------
    # GET /self/drift
    # ------------------------------------------------------------------
    @app.get(
        "/self/drift",
        response_model=DriftResponse,
        summary="Documentation drift status",
        description=(
            "Recompute the transitive content hash for every registered "
            "doc-ref and doc-guide, compare it against the stored hash, "
            "and report divergence as drift. Degrades to a hash-presence "
            "report when nothing is hashed yet."
        ),
    )
    def get_drift(transpiler_version: str = "unknown") -> DriftResponse:
        from s0ma.hashing import content_hash

        snapshot = registry.snapshot()
        text = smi.get_drift_status(transpiler_version=transpiler_version)

        drifted: list[DriftEntry] = []
        missing: list[str] = []
        refs_hashed = 0
        guides_hashed = 0

        for name, ref in snapshot.doc_refs.items():
            if not ref.content_hash:
                missing.append(f"doc-ref:{name}")
                continue
            refs_hashed += 1
            recomputed = content_hash(
                ref, snapshot, transpiler_version=transpiler_version
            )
            if recomputed != ref.content_hash:
                drifted.append(DriftEntry(
                    kind="doc-ref",
                    name=name,
                    stored_hash=ref.content_hash,
                    recomputed_hash=recomputed,
                ))

        for name, guide in snapshot.doc_guides.items():
            if not guide.content_hash:
                missing.append(f"doc-guide:{name}")
                continue
            guides_hashed += 1
            recomputed = content_hash(
                guide, snapshot, transpiler_version=transpiler_version
            )
            if recomputed != guide.content_hash:
                drifted.append(DriftEntry(
                    kind="doc-guide",
                    name=name,
                    stored_hash=guide.content_hash,
                    recomputed_hash=recomputed,
                ))

        return DriftResponse(
            text=text,
            total_doc_refs=len(snapshot.doc_refs),
            total_doc_guides=len(snapshot.doc_guides),
            doc_refs_hashed=refs_hashed,
            doc_guides_hashed=guides_hashed,
            drifted=sorted(drifted, key=lambda d: (d.kind, d.name)),
            missing_hashes=sorted(missing),
        )

    # ------------------------------------------------------------------
    # POST /self/query
    # ------------------------------------------------------------------
    query_engine = QueryEngine(
        registry,
        smi,
        metrics_collector=metrics_collector,
    )

    @app.post(
        "/self/query",
        response_model=QueryResponse,
        summary="Natural language query",
        description=(
            "Ask a natural language question about the system. "
            "Supports questions about components, dependencies, "
            "health, impact, extension points, and more."
        ),
    )
    def query_self_model(request: QueryRequest) -> QueryResponse:
        answer = query_engine.query(request.question)
        return QueryResponse(
            question=request.question,
            answer=answer,
        )

    return app
