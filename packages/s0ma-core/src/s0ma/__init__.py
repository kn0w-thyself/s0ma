"""s0ma — A Python framework for software self-knowledge.

Software that cannot exist without understanding itself. Self-knowledge
spans three faculties: proprioception (structure), interoception
(runtime state), and metacognition (reasoning over the model). Every
component must register in a hierarchical self-model as a condition of
existing. The self-model is not documentation *about* the code; it is a
structural dependency *of* the code.

Usage:
    from s0ma import initialize
    registry = initialize(project_root="./my_project")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from s0ma._bootstrap import bootstrap_register
from s0ma.import_hook import install_import_hook
from s0ma.registry import get_registry

if TYPE_CHECKING:
    from pathlib import Path

    from s0ma.models import VerificationReport
    from s0ma.registry import ComponentRegistry

__version__ = "0.20.0"

# Re-export LifecycleManager and SelfModelInterface at the top level
# for convenience. TransactionContext is available via s0ma.lifecycle.
# The documentation subsystem data types (M1) and the public
# registration functions (M2) are re-exported alongside.
from s0ma.hashing import HASH_ALGORITHM_VERSION, canonicalize, content_hash
from s0ma.lifecycle import LifecycleManager
from s0ma.models import (
    AssertExpr,
    DocGuideRegistration,
    DocRefRegistration,
    DocsForResult,
    EntityRef,
    ExampleRegistration,
    FilterExpr,
    ImportHookAnomaly,
    Section,
    SourceSpan,
)
from s0ma.self_model import SelfModelInterface

__all__ = [
    "__version__",
    "initialize",
    "verify",
    "LifecycleManager",
    "SelfModelInterface",
    # Import-hook anomaly surface (POST-1 / 0.4.0)
    "ImportHookAnomaly",
    # Documentation — data types (M1)
    "SourceSpan",
    "EntityRef",
    "FilterExpr",
    "Section",
    "AssertExpr",
    "DocRefRegistration",
    "DocGuideRegistration",
    "ExampleRegistration",
    # Documentation — snapshot reverse-index result (M4)
    "DocsForResult",
    # Documentation — registration functions (M2)
    "register_doc_ref",
    "register_doc_guide",
    "register_example",
    # Documentation — content-hash subsystem (M7)
    "HASH_ALGORITHM_VERSION",
    "canonicalize",
    "content_hash",
]

logger = logging.getLogger("s0ma")


def initialize(
    project_root: str | Path | None = None,
    *,
    persist: bool = True,
    strict: bool = True,
) -> ComponentRegistry:
    """Initialize the s0ma framework.

    Performs the three-step startup sequence:
    1. Creates or connects to the component registry
    2. Performs bootstrap self-registration (registers s0ma's own
       components using direct construction, bypassing @component).
       ``get_registry()`` already does this when it creates the
       singleton, so a registry obtained before ``initialize()`` knows
       the framework too; the call here is a no-op in that case.
    3. Optionally installs the import hook for the specified project root

    Args:
        project_root: Root directory of the user's project. If provided,
            the import hook is installed to enforce registration for all
            modules under this directory. If None, no import hook is
            installed (useful for testing or library-only usage).
        persist: If True (default), enable SQLite persistence so the
            registry survives process restarts.
        strict: If True (default), the import hook raises
            UnregisteredComponentError for violations. If False, it
            issues warnings only (lenient mode).

    Returns:
        The initialized ComponentRegistry with all framework components
        registered.

    Example::

        from s0ma import initialize

        # Full initialization with import hook enforcement
        registry = initialize(project_root="./src")

        # Library-only mode (no hook, no persistence)
        registry = initialize(persist=False)
    """
    registry = get_registry(persist=persist)
    bootstrap_register(registry)

    logger.info(
        "s0ma framework initialized (v%s). "
        "%d framework components registered.",
        __version__,
        registry.count(),
    )

    if project_root is not None:
        install_import_hook(
            project_root=project_root,
            allowlist={"s0ma"},
            strict=strict,
        )

    return registry


def verify(
    registry: ComponentRegistry | None = None,
    **kwargs: Any,
) -> VerificationReport:
    """Run the full verification suite.

    Convenience wrapper around ``verifiers.verify_all()``.
    Uses the global registry if none is provided.

    This is the Phase 2 equivalent of the Phase 1 bootstrap test.
    If this returns errors, the system's self-model has drifted.

    Args:
        registry: The registry to verify. If None, uses the global
            registry obtained via ``get_registry()``.
        **kwargs: Additional arguments passed through to
            ``verify_all()`` (e.g., ``metrics_collector``,
            ``coverage_data_path``, ``include_scopes``).

    Returns:
        VerificationReport aggregating results from all verifiers.

    Example::

        from s0ma import initialize, verify

        registry = initialize(persist=False)
        report = verify(registry)
        assert report.passed, report.describe()
    """
    from s0ma.verifiers import verify_all

    if registry is None:
        registry = get_registry(persist=False)
        bootstrap_register(registry)

    return verify_all(registry, **kwargs)


# ----------------------------------------------------------------------
# Documentation subsystem — public registration functions (M2)
# ----------------------------------------------------------------------
#
# Thin wrappers over the global registry's ComponentRegistry methods.
# DSL-generated modules invoke these at module import time to register
# doc-ref / doc-guide / example declarations.


def register_doc_ref(
    *,
    name: str,
    module: str,
    intent: str,
    format: str,  # noqa: A002 — field name mandated by design §6 / plan M2
    output: str,
    covers: list[FilterExpr] | None = None,
    sections: list[Section] | None = None,
    content_hash: str = "",
    source_span: SourceSpan | None = None,
    idempotent: bool = False,
) -> DocRefRegistration:
    """Register a ``doc-ref`` declaration in the global registry.

    See :meth:`ComponentRegistry.register_doc_ref` for parameter semantics.
    """
    return get_registry().register_doc_ref(
        name=name,
        module=module,
        intent=intent,
        format=format,
        output=output,
        covers=covers,
        sections=sections,
        content_hash=content_hash,
        source_span=source_span,
        idempotent=idempotent,
    )


def register_doc_guide(
    *,
    name: str,
    module: str,
    intent: str,
    format: str,  # noqa: A002 — field name mandated by design §6 / plan M2
    output: str,
    covers: list[EntityRef] | None = None,
    asserts: list[AssertExpr] | None = None,
    examples: list[EntityRef] | None = None,
    body: str = "",
    content_hash: str = "",
    source_span: SourceSpan | None = None,
    idempotent: bool = False,
) -> DocGuideRegistration:
    """Register a ``doc-guide`` declaration in the global registry.

    See :meth:`ComponentRegistry.register_doc_guide` for parameter semantics.
    """
    return get_registry().register_doc_guide(
        name=name,
        module=module,
        intent=intent,
        format=format,
        output=output,
        covers=covers,
        asserts=asserts,
        examples=examples,
        body=body,
        content_hash=content_hash,
        source_span=source_span,
        idempotent=idempotent,
    )


def register_example(
    *,
    name: str,
    module: str,
    intent: str,
    demonstrates: list[EntityRef],
    runs_in: Literal["standalone", "pytest", "integration"] = "standalone",
    body: str = "",
    source_span: SourceSpan | None = None,
    idempotent: bool = False,
) -> ExampleRegistration:
    """Register an ``example`` declaration in the global registry.

    See :meth:`ComponentRegistry.register_example` for parameter semantics.
    """
    return get_registry().register_example(
        name=name,
        module=module,
        intent=intent,
        demonstrates=demonstrates,
        runs_in=runs_in,
        body=body,
        source_span=source_span,
        idempotent=idempotent,
    )
