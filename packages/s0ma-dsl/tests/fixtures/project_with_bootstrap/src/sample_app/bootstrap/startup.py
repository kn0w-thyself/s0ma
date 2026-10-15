"""Startup helper for the project_with_bootstrap fixture.

Declared under ``[tool.s0ma].bootstrap_files`` — the conventional
second bootstrap file in a s0ma project layout. Plain Python; no
s0ma-source-hash comments because no ``.s0ma`` source produces it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


def startup(build_dir: Path) -> dict[str, Any]:
    """Return a stub dict so the test fixture is exercise-friendly."""
    return {"build_dir": build_dir}
