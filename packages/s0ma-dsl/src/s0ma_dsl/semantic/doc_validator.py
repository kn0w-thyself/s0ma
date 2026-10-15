"""Orchestrator for the documentation-subsystem validation layers.

Runs validation layers 3 and 4 (design §§8.3–8.4) for every doc declaration
in a parsed project, collecting diagnostics from:

1. :class:`s0ma_dsl.resolver.doc_resolver.DocReferenceResolver` — walks every
   entity reference, field access, filter predicate, and example embed.
2. :class:`s0ma_dsl.resolver.assert_evaluator.AssertEvaluator` — evaluates
   every assert expression against the same project index.

The orchestrator operates at project scope: it takes the full dict of
parsed ``S0maModule`` objects, builds a :class:`ProjectIndex` once, and
fans out resolver/evaluator calls per declaration. Downstream milestones
(emitter, CLI) consume the returned diagnostics directly.

Earlier intra-module validation layers (syntax, field presence, grammar)
run in the parser and :class:`s0ma_dsl.semantic.validator.IntraModuleValidator`
and are not re-run here — this module focuses on the cross-declaration
and cross-module checks that require project-level context.

PRD references: FR-29, §2.3.3 (registry namespace).
Design references: §8.3 reference resolution, §8.4 assert evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.ast_nodes.enums import Visibility
from s0ma_dsl.ast_nodes.nodes import (
    DocGuideDecl,
    DocRefDecl,
    ExampleDecl,
    ExampleEmbedToken,
    S0maModule,
)
from s0ma_dsl.config import StrictnessMode, get_severity
from s0ma_dsl.errors import S0maResolutionError
from s0ma_dsl.resolver.assert_evaluator import AssertEvaluator
from s0ma_dsl.resolver.doc_resolver import (
    DocReferenceResolver,
    ProjectIndex,
    build_project_index,
    materialize_filter,
)

__all__ = [
    "DocValidator",
    "check_release_doc_coverage",
    "validate_docs",
]


@component(
    name="S0maDSL_DocValidator",
    kind=ComponentKind.SERVICE,
    layer=Layer.FRAMEWORK,
    intent=(
        "Orchestrates doc-subsystem reference resolution and assert evaluation across a parsed "
        "s0ma project."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class DocValidator:
    """Project-level doc-subsystem validator.

    Thin orchestrator over :class:`DocReferenceResolver` and
    :class:`AssertEvaluator`. Builds the project index once, walks every
    doc declaration in every module, and returns the aggregated diagnostic
    list in source-file-then-source-line order.
    """

    index: ProjectIndex = field(default_factory=ProjectIndex)

    @classmethod
    def from_modules(cls, modules: dict[str, S0maModule]) -> DocValidator:
        """Build a validator from a dict of parsed modules."""
        return cls(index=build_project_index(modules))

    def validate(
        self,
        modules: dict[str, S0maModule],
        *,
        filenames: dict[str, str] | None = None,
        mode: StrictnessMode = StrictnessMode.DEV,
    ) -> list[S0maResolutionError]:
        """Validate every doc declaration across a parsed project.

        Parameters
        ----------
        modules:
            Map of module name → parsed ``S0maModule``.
        filenames:
            Optional map of module name → source file path. Missing
            entries default to ``"<module>.s0ma"``.

        Returns
        -------
        list[S0maResolutionError]
            Every unresolved reference, kind mismatch, missing field,
            unregistered example, failed assert, and unevaluable assert
            discovered. Emitted in deterministic order: filenames sorted
            alphabetically, then declarations by source line within each
            file.
        """
        resolver = DocReferenceResolver(index=self.index, mode=mode)
        evaluator = AssertEvaluator(index=self.index)

        errors: list[S0maResolutionError] = []

        # Sort module names so diagnostic ordering is deterministic —
        # callers often assert against the first error in the list.
        for module_name in sorted(modules.keys()):
            s0ma_module = modules[module_name]
            filename = (
                filenames.get(module_name)
                if filenames is not None
                else f"{module_name}.s0ma"
            ) or f"{module_name}.s0ma"

            # Gather declarations in source-line order so diagnostics
            # within a file read top-to-bottom.
            for decl in s0ma_module.all_declarations:
                if isinstance(decl, DocRefDecl):
                    errors.extend(
                        resolver.resolve_doc_ref(decl, filename=filename)
                    )
                elif isinstance(decl, DocGuideDecl):
                    errors.extend(
                        resolver.resolve_doc_guide(decl, filename=filename)
                    )
                    errors.extend(
                        evaluator.evaluate_doc_guide(decl, filename=filename)
                    )
                elif isinstance(decl, ExampleDecl):
                    errors.extend(
                        resolver.resolve_example(decl, filename=filename)
                    )

        return errors


@component(
    name="S0maDSL_validate_docs",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Convenience entry point that builds a DocValidator from a module dict and runs it in "
        "one call."
    ),
    idempotent=True,
    is_framework=True,
)
def validate_docs(
    modules: dict[str, S0maModule],
    *,
    filenames: dict[str, str] | None = None,
    mode: StrictnessMode = StrictnessMode.DEV,
) -> list[S0maResolutionError]:
    """One-shot convenience wrapper over :class:`DocValidator`."""
    validator = DocValidator.from_modules(modules)
    return validator.validate(modules, filenames=filenames, mode=mode)


# ---------------------------------------------------------------------------
# Release-mode doc coverage (M7 subtask 4)
# ---------------------------------------------------------------------------


def _doc_ref_covers_nerves(
    decl: DocRefDecl, index: ProjectIndex,
) -> set[str]:
    """Return the set of nerve names a single doc-ref's covers: filters select."""
    matched: set[str] = set()
    for fexpr in decl.covers:
        if fexpr.kind != "nerve":
            continue
        for ent in materialize_filter(fexpr, index):
            matched.add(ent.name)
    return matched


def _doc_guide_embedded_examples(decl: DocGuideDecl) -> set[str]:
    """Return the set of example names a single doc-guide embeds.

    Embeds come from two surfaces: the structured ``examples:`` field and
    ``{{example::X}}`` tokens in the prose body. Both must register as
    coverage; either one is sufficient for an example to count as
    embedded for release-mode purposes.
    """
    embedded: set[str] = set()
    for ref in decl.examples:
        if ref.kind == "example":
            embedded.add(ref.name)
    for tok in decl.prose_tokens:
        if isinstance(tok, ExampleEmbedToken) and tok.entity_ref.kind == "example":
            embedded.add(tok.entity_ref.name)
    return embedded


@component(
    name="S0maDSL_check_release_doc_coverage",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Release-mode coverage pass: every PUBLIC nerve must be covered by "
        "at least one doc-ref, and every registered example must be embedded "
        "in at least one doc-guide. Emits MISSING_PUBLIC_DOC_REF and "
        "MISSING_EMBEDDED_EXAMPLE diagnostics (only active in release mode)."
    ),
    idempotent=True,
    is_framework=True,
)
def check_release_doc_coverage(
    modules: dict[str, S0maModule],
    *,
    mode: StrictnessMode,
    filenames: dict[str, str] | None = None,
) -> list[S0maResolutionError]:
    """Run the release-mode doc-subsystem coverage checks (plan §11.11).

    Returns an empty list outside :class:`StrictnessMode.RELEASE` so
    callers can wire this into the pipeline unconditionally without
    paying the project-walk cost.
    """
    errors: list[S0maResolutionError] = []

    public_doc_severity = get_severity("MISSING_PUBLIC_DOC_REF", mode)
    example_doc_severity = get_severity("MISSING_EMBEDDED_EXAMPLE", mode)
    if public_doc_severity is None and example_doc_severity is None:
        return errors

    filenames = filenames or {}
    index = build_project_index(modules)

    # --- Build coverage sets across the whole project --------------------
    covered_public_nerves: set[str] = set()
    embedded_examples: set[str] = set()
    for s0ma_module in modules.values():
        for ref in s0ma_module.doc_refs:
            covered_public_nerves.update(_doc_ref_covers_nerves(ref, index))
        for guide in s0ma_module.doc_guides:
            embedded_examples.update(_doc_guide_embedded_examples(guide))

    # --- MISSING_PUBLIC_DOC_REF ------------------------------------------
    if public_doc_severity is not None:
        for module_name in sorted(modules.keys()):
            s0ma_module = modules[module_name]
            filename = filenames.get(module_name) or f"{module_name}.s0ma"
            for nerve in s0ma_module.nerves:
                if nerve.visibility != Visibility.PUBLIC:
                    continue
                if nerve.name in covered_public_nerves:
                    continue
                loc = nerve.location
                line = loc.start_line if loc else 0
                col = loc.start_column if loc else 0
                errors.append(S0maResolutionError(
                    code="MISSING_PUBLIC_DOC_REF",
                    message=(
                        f"PUBLIC nerve '{nerve.name}' is not covered by any "
                        f"doc-ref in the project."
                    ),
                    file=filename,
                    line=line,
                    column=col,
                    severity=public_doc_severity,
                    remediation=(
                        f"Add a doc-ref whose covers: filter selects "
                        f"nerve::{nerve.name}, or downgrade the nerve to "
                        f"INTERNAL visibility."
                    ),
                    context={
                        "nerve": nerve.name,
                        "module": module_name,
                    },
                ))

    # --- MISSING_EMBEDDED_EXAMPLE ----------------------------------------
    if example_doc_severity is not None:
        for module_name in sorted(modules.keys()):
            s0ma_module = modules[module_name]
            filename = filenames.get(module_name) or f"{module_name}.s0ma"
            for ex in s0ma_module.examples:
                if ex.name in embedded_examples:
                    continue
                loc = ex.location
                line = loc.start_line if loc else 0
                col = loc.start_column if loc else 0
                errors.append(S0maResolutionError(
                    code="MISSING_EMBEDDED_EXAMPLE",
                    message=(
                        f"Example '{ex.name}' is not embedded in any "
                        f"doc-guide in the project."
                    ),
                    file=filename,
                    line=line,
                    column=col,
                    severity=example_doc_severity,
                    remediation=(
                        f"Add example::{ex.name} to a doc-guide's examples: "
                        f"list, or embed it in prose with "
                        f"{{{{example::{ex.name}}}}}, or remove the example."
                    ),
                    context={
                        "example": ex.name,
                        "module": module_name,
                    },
                ))

    return errors
