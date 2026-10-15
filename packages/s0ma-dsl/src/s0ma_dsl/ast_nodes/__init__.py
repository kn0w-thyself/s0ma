"""AST Nodes — Stage 2: Typed AST node definitions for the s0ma DSL.

Re-exports all enums and node dataclasses so downstream code can import
from ``s0ma_dsl.ast_nodes`` directly.
"""

from s0ma_dsl.ast_nodes.enums import (
    VALID_KINDS_FOR_DECLARATION,
    Coupling,
    DeclarationType,
    EvaluatesAt,
    Kind,
    Layer,
    Relation,
    Visibility,
)
from s0ma_dsl.ast_nodes.nodes import (
    CellDecl,
    DocGuideDecl,
    DocRefDecl,
    EntityRefAst,
    ExampleDecl,
    FilterExprAst,
    GanglionDecl,
    HelperDecl,
    InlineAxon,
    IntegrationDecl,
    InternalHelperEntry,
    ModuleDecl,
    NerveDecl,
    ProvidesEntry,
    RequiresEntry,
    S0maModule,
    SectionAst,
    SourceLocation,
    StandaloneAxonDecl,
    TestDecl,
    UsesEntry,
)
from s0ma_dsl.semantic_state import (
    FIELD_CLASSIFICATIONS,
    FieldClassification,
    SemanticState,
)

__all__ = [
    # Enums
    "Coupling",
    "DeclarationType",
    "EvaluatesAt",
    "Kind",
    "Layer",
    "Relation",
    "Visibility",
    "VALID_KINDS_FOR_DECLARATION",
    # Nodes
    "CellDecl",
    "DocGuideDecl",
    "DocRefDecl",
    "EntityRefAst",
    "ExampleDecl",
    "FilterExprAst",
    "GanglionDecl",
    "HelperDecl",
    "InlineAxon",
    "IntegrationDecl",
    "InternalHelperEntry",
    "ModuleDecl",
    "NerveDecl",
    "ProvidesEntry",
    "RequiresEntry",
    "SectionAst",
    "S0maModule",
    "SourceLocation",
    "StandaloneAxonDecl",
    "TestDecl",
    "UsesEntry",
    "SemanticState",
    "FieldClassification",
    "FIELD_CLASSIFICATIONS",
]
