"""s0ma_dsl — The s0ma DSL transpiler toolchain.

Compiles .s0ma source files into Python + s0ma-decorated code,
normalized IR (.s0ma.json), and source maps (.s0ma.map).
"""

from s0ma_dsl.project import S0maProject

# Transpiler version. Surfaced in the M6b ``build.s0ma.json`` manifest
# (`transpiler_version` field) so downstream tooling can branch on the
# version that produced a given build artifact. Bump in lockstep with
# the version field in ``pyproject.toml``.
__version__ = "0.21.0"

__all__ = [
    "S0maProject",
    "__version__",
]
