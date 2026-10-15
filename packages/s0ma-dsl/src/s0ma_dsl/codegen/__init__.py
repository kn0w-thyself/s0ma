"""Codegen — Stage 5: Code generation (.py and .s0ma.map output).

Public API:
    PythonEmitter             — Generates Python from S0maModule ASTs
    emit_python               — Convenience function for single-module emission
    ObservesResolver          — Resolves ganglion observes patterns
    ProjectContext            — Project-level context for cross-module resolution
    resolve_observes          — Convenience function for observes resolution
    SourceMapGenerator        — Generates .s0ma.map source maps
    generate_source_map       — Convenience function for source map generation
    validate_emitted_python   — Post-emission ``ast.parse()`` build invariant (M2)
    BuildManifest             — Build manifest dataclass (M6b)
    ModuleManifestEntry       — Per-module entry in the manifest (M6b)
    emit_manifest             — Write ``build.s0ma.json`` (M6b)
    load_manifest             — Read ``build.s0ma.json`` with schema validation (M6b)
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from s0ma_dsl.codegen.build_manifest import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA,
    ArtifactReference,
    BuildManifest,
    ExternalContentFileEntry,
    ManifestSchemaError,
    ModuleManifestEntry,
    SelfContextReferences,
    build_manifest,
    compute_file_hash,
    emit_manifest,
    load_manifest,
)
from s0ma_dsl.codegen.observes_resolver import (
    ObservesResolver,
    PrivilegedImportInfo,
    ProjectContext,
    ResolvedObserves,
    determine_privileged_imports,
    resolve_observes,
)
from s0ma_dsl.codegen.python_emitter import PythonEmitter, emit_python
from s0ma_dsl.codegen.source_map import (
    DeclarationMapping,
    LineRange,
    ModuleHeaderMapping,
    ResolvedLocation,
    SourceMap,
    SourceMapGenerator,
    annotate_source_pointers,
    generate_source_map,
    load_source_map,
    resolve_output_line,
)
from s0ma_dsl.errors import TranspilerInternalError

if TYPE_CHECKING:
    from pathlib import Path


def validate_emitted_python(path: Path | str, source: str) -> None:
    """Validate emitted Python source by round-tripping through ``ast.parse``.

    Build invariant introduced in feedback-5/6 M2: every ``.py`` file the
    transpiler is about to write must be syntactically valid Python.
    Failure indicates a transpiler bug — historically, mishandled escape
    sequences in metadata strings — and is raised loudly so the issue is
    caught at build time, not at handoff.

    Parameters
    ----------
    path:
        Filesystem path the emitted source will be written to. Used for
        diagnostics only.
    source:
        The emitted Python source as a string.

    Raises
    ------
    TranspilerInternalError
        If ``ast.parse`` rejects ``source``. The exception message names
        ``path`` and the underlying ``SyntaxError`` and instructs the
        user to file a transpiler-bug report.
    """
    try:
        ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise TranspilerInternalError(
            f"Emitted Python at {path} is syntactically invalid: {exc}. "
            f"This is a transpiler bug — please file an issue at "
            f"https://github.com/kn0wthyself/s0ma-dsl/issues with the "
            f"offending .s0ma source attached."
        ) from exc


__all__ = [
    "BuildManifest",
    "ArtifactReference",
    "DeclarationMapping",
    "ExternalContentFileEntry",
    "LineRange",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA",
    "ManifestSchemaError",
    "ModuleHeaderMapping",
    "ModuleManifestEntry",
    "SelfContextReferences",
    "ObservesResolver",
    "PrivilegedImportInfo",
    "ProjectContext",
    "PythonEmitter",
    "ResolvedLocation",
    "ResolvedObserves",
    "SourceMap",
    "SourceMapGenerator",
    "annotate_source_pointers",
    "build_manifest",
    "compute_file_hash",
    "determine_privileged_imports",
    "emit_manifest",
    "emit_python",
    "generate_source_map",
    "load_manifest",
    "load_source_map",
    "resolve_observes",
    "resolve_output_line",
    "validate_emitted_python",
]
