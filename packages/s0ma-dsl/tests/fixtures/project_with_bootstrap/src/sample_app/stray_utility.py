"""A stray plain-Python file that is *not* declared as a bootstrap file.

This file exists to exercise the M11 ``UNKNOWN`` path: ``s0ma verify``
must surface it as ``UNKNOWN`` (not ``BOOTSTRAP``) because the project's
``[tool.s0ma].bootstrap_files`` list does not name it. The remediation
message points the author at either declaring it or transpiling a
``.s0ma`` source for it.
"""

from __future__ import annotations


def helper() -> str:
    return "stray"
