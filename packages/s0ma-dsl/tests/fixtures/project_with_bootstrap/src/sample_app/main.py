"""Plain-Python application entry point for the project_with_bootstrap fixture.

This file is declared under ``[tool.s0ma].bootstrap_files`` in
pyproject.toml so ``s0ma verify`` recognises it as ``BOOTSTRAP`` rather
than ``UNKNOWN``. It carries no s0ma-source-hash comments because there
is no ``.s0ma`` source for it to derive from — it is the framework
bootstrap by definition.
"""

from __future__ import annotations


def main() -> int:
    print("hello from the bootstrap entry point")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
