"""Resolver — Stage 3: Dependency resolution for the s0ma DSL.

Public API:
    NamespaceEntry — a resolved name within a namespace
    NamespaceService — holds and queries the four namespaces for a module
    build_namespaces(s0ma_module, filename) -> (NamespaceService, errors)
    DependencyResolver — four-phase cross-module dependency resolution
    resolve_dependencies(modules, ...) -> errors
    layer_reachability_matrix() -> {layer: [reachable layers]}, the enforced table as data

Documentation subsystem (M4):
    ProjectIndex — kind-indexed view of every doc-addressable entity
    build_project_index(modules) -> ProjectIndex
    DocReferenceResolver — walks doc-ref/doc-guide/example references
    AssertEvaluator — evaluates doc-guide assert expressions
    AssertResult — per-assert evaluation outcome
"""

from s0ma_dsl.resolver.assert_evaluator import AssertEvaluator, AssertResult
from s0ma_dsl.resolver.dependency import (
    DependencyResolver,
    layer_reachability_matrix,
    resolve_dependencies,
)
from s0ma_dsl.resolver.doc_resolver import (
    DocReferenceResolver,
    ProjectIndex,
    build_project_index,
)
from s0ma_dsl.resolver.namespaces import (
    NamespaceEntry,
    NamespaceService,
    build_namespaces,
)
from s0ma_dsl.resolver.topological import (
    ModuleDependencyCycleError,
    compute_topological_order,
)

__all__ = [
    "AssertEvaluator",
    "AssertResult",
    "DependencyResolver",
    "DocReferenceResolver",
    "ModuleDependencyCycleError",
    "NamespaceEntry",
    "NamespaceService",
    "ProjectIndex",
    "build_namespaces",
    "build_project_index",
    "compute_topological_order",
    "layer_reachability_matrix",
    "resolve_dependencies",
]
