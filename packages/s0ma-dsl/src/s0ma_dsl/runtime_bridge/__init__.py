"""Runtime Bridge — Adapter between the transpiler and the s0ma runtime registry.

Provides the registration functions that transpiled .s0ma modules call
at load time to register modules, constants, types, relationships, and
tests in the s0ma ComponentRegistry.

M6b (feedback 5–6, ADR-007) adds :func:`import_modules_from_manifest`,
the manifest-driven entry point that replaces filesystem traversal as
the runtime's source of truth for "what was built". See
``s0ma_dsl.codegen.build_manifest`` for the manifest schema.
"""

from s0ma_dsl.runtime_bridge.registration import (
    import_modules_from_manifest,
    register_constant,
    register_module,
    register_relationship,
    register_test,
    register_type,
)

__all__ = [
    "import_modules_from_manifest",
    "register_constant",
    "register_module",
    "register_relationship",
    "register_test",
    "register_type",
]
