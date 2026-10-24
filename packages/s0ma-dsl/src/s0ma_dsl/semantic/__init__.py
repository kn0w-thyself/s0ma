"""Semantic — Stages 3-4: Validation and derived edge analysis for the s0ma DSL.

Provides intra-module semantic validation: kind compatibility, visibility/export
consistency, layer consistency, inline axon validation, raises field validation,
version format validation, and duplicate declaration detection.

Also provides derived edge analysis: RAISES edge derivation from raises fields,
TYPE_USES edge derivation from function signature annotations, READS edge
derivation from the constants a body refers to, and conflict detection
between authored and derived edges (PRD §1.12).
"""

from s0ma_dsl.semantic.derived_edges import (
    DerivedEdge,
    DerivedEdgeAnalyzer,
    analyze_derived_edges,
)
from s0ma_dsl.semantic.doc_validator import DocValidator, validate_docs
from s0ma_dsl.semantic.validator import IntraModuleValidator, validate_module

__all__ = [
    "DerivedEdge",
    "DerivedEdgeAnalyzer",
    "DocValidator",
    "IntraModuleValidator",
    "analyze_derived_edges",
    "validate_docs",
    "validate_module",
]
