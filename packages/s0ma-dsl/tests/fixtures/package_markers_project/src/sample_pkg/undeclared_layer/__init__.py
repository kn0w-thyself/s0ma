"""Undeclared layer with executable content.

This __init__.py carries an ``__all__`` re-export but is left
undeclared on purpose. `s0ma verify` should classify it as
UNKNOWN with a remediation pointing the author at either
[tool.s0ma].bootstrap_files or [tool.s0ma].package_markers.
"""

from sample_pkg.undeclared_layer import widget  # noqa: F401

__all__ = ["widget"]
