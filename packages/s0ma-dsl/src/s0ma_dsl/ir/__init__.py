"""IR — Stage 4: Normalized intermediate representation (.s0ma.json) generation.

This package implements the IR builder and schema types that produce
the ``.s0ma.json`` artifact per PRD §2.5. The IR is the primary
machine interface for AI tools.
"""

from s0ma_dsl.ir.builder import IRBuilder, build_ir, compute_content_hash
from s0ma_dsl.ir.schema import (
    SCHEMA_VERSION,
    TRANSPILER_VERSION,
    IRAuthoredEdge,
    IRComponent,
    IRComponentLocation,
    IRDerivedEdge,
    IRDocument,
    IREdges,
    IRImports,
    IRModule,
    IRPrivilegedImport,
    IRRequiresImport,
    IRSchemaVersionError,
    IRUsesImport,
    IRVerificationEdge,
    validate_ir_schema_version,
)

__all__ = [
    "SCHEMA_VERSION",
    "TRANSPILER_VERSION",
    "IRAuthoredEdge",
    "IRBuilder",
    "IRComponent",
    "IRComponentLocation",
    "IRDerivedEdge",
    "IRDocument",
    "IREdges",
    "IRImports",
    "IRModule",
    "IRPrivilegedImport",
    "IRRequiresImport",
    "IRUsesImport",
    "IRVerificationEdge",
    "IRSchemaVersionError",
    "validate_ir_schema_version",
    "build_ir",
    "compute_content_hash",
]
