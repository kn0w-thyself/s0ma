"""Re-export surface for the declared_layer package.

This __init__.py carries an ``__all__`` re-export and would
otherwise surface as UNKNOWN under `s0ma verify`. The author has
declared it under [tool.s0ma].package_markers to acknowledge it
as a package marker without forcing the file to be emptied.
"""

from sample_pkg.declared_layer import widget  # noqa: F401

__all__ = ["widget"]
