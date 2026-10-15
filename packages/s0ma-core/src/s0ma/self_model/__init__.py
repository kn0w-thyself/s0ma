"""Self-model query API for s0ma.

Provides a Python-native interface for querying the self-model,
producing natural language text optimized for LLM consumption.

The primary class is ``SelfModelInterface``, which wraps the
``ComponentRegistry`` and optional verification data to produce
text suitable for injecting into LLM system prompts or context
windows.

All methods return ``str`` (not data structures) because the
primary consumer is an LLM that needs natural language context.
"""

from s0ma.self_model.diff import (
    ComponentChange,
    StructuredDiff,
    compute_registry_diff,
)
from s0ma.self_model.interface import SelfModelInterface

__all__ = [
    "ComponentChange",
    "SelfModelInterface",
    "StructuredDiff",
    "compute_registry_diff",
]
