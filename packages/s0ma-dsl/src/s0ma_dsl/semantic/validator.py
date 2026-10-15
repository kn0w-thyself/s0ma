"""Intra-module semantic validation for the s0ma DSL.

Implements all validation rules that apply within a single .s0ma file:
kind-to-declaration-type compatibility, visibility/export consistency,
layer consistency, inline axon validation, raises field validation,
version format validation, and duplicate declaration detection.

PRD references: FR-05, FR-14 through FR-19, §1.12, §2.4.3
Spec references: §7.1 rules R-04, R-05, R-09, R-10, R-16, R-17,
                  R-19, R-22, R-23, R-27
"""

from __future__ import annotations

import ast
import configparser
import dataclasses
import fnmatch
import functools
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from s0ma.decorators import component
from s0ma.types import ComponentKind
from s0ma.types import Layer as S0maLayer

# D3 (beta-prep-1-retrofit): the retrofit draft's two markers and the
# quarantine-cell name prefix are part of the ``@1`` draft contract — the
# emitter writes them and this validator matches them, so they are
# imported from the one place that defines them and never re-typed here.
from s0ma_dsl.adopt.draft_emit import PLACEHOLDERS
from s0ma_dsl.adopt.harvest import UNPLACED_CELL_PREFIX
from s0ma_dsl.adopt.model import DRAFT_INTENT_MARKER, DRAFT_UNPLACED_MARKER
from s0ma_dsl.ast_nodes.enums import (
    VALID_KINDS_FOR_DECLARATION,
    DeclarationType,
    Kind,
    Layer,
    Relation,
    Visibility,
)
from s0ma_dsl.ast_nodes.nodes import (
    METADATA_INVALID_VALUE_MARKER,
    CellDecl,
    DocGuideDecl,
    DocRefDecl,
    ExampleDecl,
    GanglionDecl,
    HelperDecl,
    InlineAxon,
    IntegrationDecl,
    ModuleDecl,
    NerveDecl,
    S0maModule,
    SourceLocation,
    StandaloneAxonDecl,
    TestDecl,
)
from s0ma_dsl.config import StrictnessMode, get_severity
from s0ma_dsl.errors import S0maSemanticError
from s0ma_dsl.ir.schema import RESERVED_COMPONENT_METADATA_KEYS
from s0ma_dsl.resolver.namespaces import NamespaceService, build_namespaces
from s0ma_dsl.suggestions import render_provides_block

__all__ = [
    "IntraModuleValidator",
    "validate_module",
]


# ---------------------------------------------------------------------------
# Semver regex — MAJOR.MINOR.PATCH, all non-negative integers, no leading zeros
# ---------------------------------------------------------------------------

_SEMVER_RE = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$"
)


# ---------------------------------------------------------------------------
# B3 (0.11.0) — Python standard-library top-level module names
# ---------------------------------------------------------------------------
#
# A s0ma module whose declared name is one of these cannot be imported by
# its bare name at runtime: the stdlib module is already resident in
# ``sys.modules`` at interpreter start, so ``importlib.import_module`` (the
# engine behind ``bootstrap_imports`` and every cross-module ``uses:``
# resolution) returns the stdlib module rather than the built ``.py``.
# ``sys.stdlib_module_names`` is a frozenset of the top-level names for the
# running interpreter (Python 3.10+); it is stable across 3.11–3.13, the
# supported range.

_STDLIB_MODULE_NAMES: frozenset[str] = frozenset(
    getattr(sys, "stdlib_module_names", set())
)


def _authored_bodies(
    module: S0maModule,
) -> list[tuple[str, str, int]]:
    """Every authored inline body in *module* as ``(decl_name, body, line)``.

    Mirrors the whole-body inventory in
    :meth:`IntraModuleValidator._check_duplicate_inner_function`: nerve,
    cell (excluding ``content: @file()`` embeds), ganglion, and helper
    bodies. Test bodies are intentionally excluded — the B1 module-object
    subscript hazard is a production-code confusion.
    """
    bodies: list[tuple[str, str, int]] = []
    for nerve in module.nerves:
        if nerve.body:
            line = nerve.location.start_line if nerve.location else 0
            bodies.append((nerve.name, nerve.body, line))
    for cell in module.cells:
        if cell.body and cell.embedded_file_path is None:
            line = cell.location.start_line if cell.location else 0
            bodies.append((cell.name, cell.body, line))
    for ganglion in module.ganglia:
        if ganglion.body:
            line = ganglion.location.start_line if ganglion.location else 0
            bodies.append((ganglion.name, ganglion.body, line))
    for helper in module.helpers:
        if helper.body:
            line = helper.location.start_line if helper.location else 0
            bodies.append((helper.name, helper.body, line))
    return bodies


def _body_bound_names(tree: ast.AST) -> set[str]:
    """Names bound (assigned) anywhere in a parsed body.

    Used to suppress ``MODULE_SUBSCRIPT`` on a name a body rebinds locally
    (``registry = registry_factory()``): after the rebind the name is a
    value, not the module object, so subscripting it is legitimate. This
    conservative, control-flow-insensitive over-approximation favours
    false negatives over false positives.
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            for arg in (
                list(args.posonlyargs)
                + list(args.args)
                + list(args.kwonlyargs)
            ):
                bound.add(arg.arg)
            if args.vararg is not None:
                bound.add(args.vararg.arg)
            if args.kwarg is not None:
                bound.add(args.kwarg.arg)
    return bound


# ---------------------------------------------------------------------------
# POST-12b (0.16.0) — placeholder marker pattern
#
# Magic-string placeholders inside an embedded file (referenced by a
# CONSTANT cell's ``content: @file("...")``) follow the dunder-uppercase
# convention: two underscores + an uppercase letter + zero-or-more
# uppercase letters / digits / underscores + two underscores. Examples:
# ``__SYSTEM_NAME__``, ``__GRAPH_DATA_JSON__``, ``__A__``. The pattern
# is deliberately conservative: lowercase or mixed-case dunders (e.g.
# ``__a__``, ``__Foo__``) do NOT match — they are common in Python
# (``__init__``, ``__name__``) and would produce false positives across
# every embedded code template.
# ---------------------------------------------------------------------------

_PLACEHOLDER_PATTERN = re.compile(r"__[A-Z][A-Z0-9_]*__")


# ---------------------------------------------------------------------------
# DSL-M1 (0.8.0) — authored ``metadata:`` shape validation (ADR-011 §(a))
# ---------------------------------------------------------------------------

_METADATA_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Reserved metadata keys whose fact is owned by a same-named (or
#: closely-named) declaration field — the ``METADATA_RESERVED_KEY``
#: remediation points the author at the field instead of the metadata
#: map. Keys absent from this mapping get the generic emitter-derived
#: wording.
_RESERVED_KEY_FIELD_HINTS: dict[str, str] = {
    "abstract": "abstract:",
    "category": "category:",
    "consumes_via_dict": "consumes_via_dict:",
    # "covered_by" joins this mapping at M2 when the field lands; until
    # then the generic reserved-key wording applies.
    "dataclass_invariants": "dataclass_invariants:",
    "deferred": "deferred:",
    "evaluates_at": "evaluates_at:",
    "expected_exceptions": "expected_exceptions:",
    "interface": "interface:",
    "invariants": "invariants:",
    "kind_detail": "kind:",
    "observes": "observes:",
    "observes_patterns": "observes:",
    "on_anomaly": "on_anomaly:",
    "priors": "priors:",
    "provides": "provides:",
    "provides_contracts": "provides:",
    "raises": "raises:",
    "resolved_observes": "observes:",
    "returns": "returns:",
    "schema": "schema:",
    "scope": "scope:",
    "serves_as": "serves_as:",
    "visibility": "visibility:",
}

#: Human wording for the parser's invalid-value marker reasons (see
#: ``parser/s0ma_parser.py::_parse_metadata_scalar`` /
#: ``_consume_metadata_block``).
_METADATA_INVALID_REASONS: dict[str, str] = {
    "null": (
        "has no value — every metadata entry needs an explicit value "
        "(null entries are not part of the shape set)"
    ),
    "bare-token": (
        "is an unquoted bare token — scalar strings must be quoted "
        "(booleans are the lower-case literals true/false)"
    ),
    "nested-map": (
        "is a nested map — metadata values are flat (string | int | "
        "float | bool | list of strings); nested maps are not supported"
    ),
    "list-entry": (
        "contains a malformed list entry — list entries must be quoted "
        "strings or bare identifiers"
    ),
    "inline-form": (
        "is not a block map — author 'metadata:' as an indented block "
        "(one 'key: value' line per entry); there is no inline form"
    ),
}


# ---------------------------------------------------------------------------
# IntraModuleValidator — orchestrates all intra-module checks
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_IntraModuleValidator",
    kind=ComponentKind.SERVICE,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Orchestrates all intra-module semantic validation rules for a single parsed .s0ma file."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class IntraModuleValidator:
    """Validates a single ``S0maModule`` for internal semantic consistency.

    Runs all intra-module checks defined by the spec's universal rules
    and the PRD's functional requirements. Cross-module resolution is
    handled separately by the dependency resolver (M8).

    Attributes
    ----------
    mode:
        Active strictness mode controlling severity of certain rules.
    filename:
        Source file path for diagnostics.
    """

    mode: StrictnessMode = StrictnessMode.DEV
    filename: str = "<unknown>"
    requires_python: tuple[str, ...] | None = None
    """M-12 (POST-8, 0.16.0): the project's
    ``[project].requires-python`` range as a tuple of PEP 440 clauses
    (e.g. ``(">=3.11",)``, ``(">=3.11", "<3.13")``), or ``None`` if
    the project does not declare the field. The forward-compat
    grammar pass fires only when the range explicitly admits Python
    3.11 (see ``s0ma_dsl.semantic.python_compat.requires_python_includes_311``).
    A ``None`` value (no declared floor) suppresses the pass under
    the conservative default."""

    def validate(self, module: S0maModule) -> list[S0maSemanticError]:
        """Run all intra-module validation checks.

        Parameters
        ----------
        module:
            A fully parsed ``S0maModule`` from the parser.

        Returns
        -------
        list[S0maSemanticError]
            All errors and warnings found. Empty list means the module
            is internally consistent.
        """
        errors: list[S0maSemanticError] = []

        # Build namespaces (also detects collisions — R-25)
        ns, ns_errors = build_namespaces(module, self.filename)
        errors.extend(ns_errors)

        # Run each validation pass
        errors.extend(self._check_module_name_matches_filename(module))
        errors.extend(self._check_semantic_pending_debt(module))
        errors.extend(self._check_duplicate_declarations(module))
        errors.extend(self._check_version_format(module))
        errors.extend(self._check_kind_compatibility(module))
        errors.extend(self._check_layer_consistency(module))
        errors.extend(self._check_visibility_export_consistency(module))
        errors.extend(self._check_inline_axons(module, ns))
        errors.extend(self._check_metadata_fields(module))
        errors.extend(self._check_serves_as_fields(module))
        errors.extend(self._check_covered_by_fields(module))
        errors.extend(self._check_standalone_axon_relations(module))
        errors.extend(self._check_raises_fields(module, ns))
        errors.extend(self._check_provides_fields(module))
        errors.extend(self._check_abstract_fields(module))
        errors.extend(self._check_returns_fields(module))
        errors.extend(self._check_test_helper_collisions(module))
        errors.extend(self._check_test_collection(module))
        errors.extend(self._check_constant_cell_body_assigns_cell_name(module))
        errors.extend(self._check_placeholders(module))
        errors.extend(self._check_mocks_key_mismatch(module))
        errors.extend(self._check_provides_key_mismatch(module))
        errors.extend(self._check_exports_helpers_resolve(module))
        errors.extend(self._check_integrations(module))
        errors.extend(self._check_python_grammar_compat(module))
        errors.extend(self._check_uuid_pattern_hint(module))
        errors.extend(self._check_mutable_dataclass_default(module))
        errors.extend(self._check_duplicate_inner_function(module))
        errors.extend(self._check_cross_module_uses_asymmetry(module))
        errors.extend(self._check_dataclass_invariants(module))
        errors.extend(self._check_consumes_via_dict(module))
        errors.extend(self._check_module_object_subscript(module))
        errors.extend(self._check_module_shadows_stdlib(module))
        errors.extend(self._check_adopt_placeholder_intent(module))
        errors.extend(self._check_adopt_unplaced_code(module))

        return errors

    def _check_semantic_pending_debt(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Report every explicit ``pending(reason)`` semantic field.

        Pending is acknowledged work, never completion: warning in
        migration/dev, error in strict/release.  The stable declaration +
        field context gives the check-baseline delta machinery a durable key,
        so newly introduced debt is attributable without line-number churn.
        """

        severity = get_severity("SEMANTIC_PENDING_DEBT", self.mode)
        if severity is None:
            return []
        diagnostics: list[S0maSemanticError] = []
        declarations = [module.module, *module.all_declarations]
        for declaration in declarations:
            owner_name = getattr(declaration, "name", module.module.name)
            owner = f"{module.module.name}::{owner_name}"
            line = declaration.location.start_line if declaration.location else 0
            for field, state in declaration.semantic_states:
                if state.state != "pending":
                    continue
                diagnostics.append(S0maSemanticError(
                    code="SEMANTIC_PENDING_DEBT",
                    message=(
                        f"Semantic field '{field}' on '{owner}' is pending: "
                        f"{state.reason}. Pending earns zero completeness credit"
                        " and blocks release."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity=severity,
                    remediation=(
                        f"Resolve '{field}' to an authored value, or use `none` only "
                        "if the normative field matrix permits non-applicability."
                    ),
                    context={
                        "declaration": owner,
                        "owner": owner,
                        "field": field,
                        "reason": state.reason,
                        "completeness_credit": 0,
                    },
                ))
        return diagnostics

    # -------------------------------------------------------------------
    # 4.1 — Module name canonical-identity check (M4, feedback 5–6)
    # -------------------------------------------------------------------

    def _check_module_name_matches_filename(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate that the source filename's stem equals the declared
        module name.

        The ``module <name>`` declaration is the canonical identity in
        s0ma's IR — it is the cache key, the import name resolved by
        ``uses:`` references, and the basis for the emitted ``.py`` /
        ``.s0ma.json`` / ``.s0ma.map`` filenames. The source filename's
        stem must mirror that identity so the filesystem and the IR
        agree on what each module is called.

        Severity: **error in dev, strict, and release modes** — this is
        a hard correctness invariant. Without it, a file named
        ``integration.s0ma`` declaring ``module google_calendar_integration``
        would write its outputs to ``google_calendar_integration.py`` while
        consumers searching by file stem (``integration.s0ma``) would fail
        silently to resolve the import.
        """
        errors: list[S0maSemanticError] = []
        if not self.filename or self.filename in ("<unknown>", "<string>"):
            # No filesystem context to compare against — most often this
            # is a unit test that constructs a S0maModule directly. The
            # check is meaningless without a real path.
            return errors

        stem = Path(self.filename).stem
        # Drop trailing ".s0ma" if Path.stem doesn't strip it (it does
        # for ``foo.s0ma`` → ``foo``, but be defensive about future
        # extension changes like ``foo.s0ma.json``).
        if stem.endswith(".s0ma"):
            stem = stem[: -len(".s0ma")]

        if stem == module.module.name:
            return errors

        line = (
            module.module.location.start_line
            if module.module.location is not None
            else 1
        )
        errors.append(S0maSemanticError(
            code="MODULE_NAME_STEM_MISMATCH",
            message=(
                f"Module is declared as '{module.module.name}' but the "
                f"source file is named '{stem}.s0ma'. The source filename "
                f"must match the declared module name so the source tree "
                f"mirrors the canonical IR identity (cache keys and "
                f"`uses:` import paths derive from the module name)."
            ),
            file=self.filename,
            line=line,
            column=0,
            severity="error",  # error in dev, strict, release
            remediation=(
                f"Rename the source file to '{module.module.name}.s0ma', "
                f"or change the module declaration to "
                f"'module {stem} :: ...'."
            ),
            context={
                "declared_module_name": module.module.name,
                "actual_file_stem": stem,
            },
        ))
        return errors

    # -------------------------------------------------------------------
    # 7.7 — Duplicate declaration detection
    # -------------------------------------------------------------------

    def _check_duplicate_declarations(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Detect declarations that share the same name within a module."""
        errors: list[S0maSemanticError] = []
        seen: dict[str, int] = {}  # name → first occurrence line

        for decl in module.all_declarations:
            if isinstance(decl, StandaloneAxonDecl):
                continue  # axons don't introduce component names
            name = decl.name
            line = decl.location.start_line if decl.location else 0

            if name in seen:
                errors.append(S0maSemanticError(
                    code="DUPLICATE_DECLARATION",
                    message=(
                        f"Declaration '{name}' is defined multiple times. "
                        f"First defined at line {seen[name]}."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        f"Rename one of the declarations of '{name}' to a "
                        f"unique name within this module."
                    ),
                    context={
                        "name": name,
                        "first_line": seen[name],
                        "duplicate_line": line,
                    },
                ))
            else:
                seen[name] = line

        return errors

    # -------------------------------------------------------------------
    # 7.6 — Version format validation (R-19)
    # -------------------------------------------------------------------

    def _check_version_format(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate that all version fields follow semver MAJOR.MINOR.PATCH."""
        errors: list[S0maSemanticError] = []

        # Module version (mandatory)
        mod = module.module
        if not _SEMVER_RE.match(mod.version):
            line = mod.location.start_line if mod.location else 0
            errors.append(S0maSemanticError(
                code="INVALID_VERSION",
                message=(
                    f"Module version '{mod.version}' is not valid semver. "
                    f"Expected MAJOR.MINOR.PATCH (e.g. '1.0.0')."
                ),
                file=self.filename,
                line=line,
                column=0,
                severity="error",
                remediation=(
                    "Change the version field to a valid semver string "
                    "(e.g. '1.0.0', '0.1.0')."
                ),
                context={"version": mod.version, "field": "module.version"},
            ))
        elif self.mode == StrictnessMode.RELEASE and mod.version == "0.0.0":
            line = mod.location.start_line if mod.location else 0
            errors.append(S0maSemanticError(
                code="INVALID_VERSION",
                message=(
                    "Module version '0.0.0' is not allowed in release "
                    "mode. All modules must have a non-zero version."
                ),
                file=self.filename,
                line=line,
                column=0,
                severity="error",
                remediation=(
                    "Set the module version to a non-zero semver string "
                    "(e.g. '1.0.0', '0.1.0')."
                ),
                context={"version": mod.version, "field": "module.version"},
            ))

        # Component-level versions (optional — only validated if present)
        for decl in module.all_declarations:
            version = getattr(decl, "version", None)
            if version is not None and not _SEMVER_RE.match(version):
                line = decl.location.start_line if decl.location else 0
                name = getattr(decl, "name", "<unknown>")
                errors.append(S0maSemanticError(
                    code="INVALID_VERSION",
                    message=(
                        f"Version '{version}' on '{name}' is not valid semver. "
                        f"Expected MAJOR.MINOR.PATCH (e.g. '1.0.0')."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        f"Change the version field on '{name}' to a valid "
                        f"semver string (e.g. '1.0.0', '0.1.0'), or remove "
                        f"the version field if not needed."
                    ),
                    context={"version": version, "component": name},
                ))

        return errors

    # -------------------------------------------------------------------
    # 7.1 — Kind-to-declaration-type validation (spec §3.1)
    # -------------------------------------------------------------------

    def _check_kind_compatibility(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate that component kinds match their declaration types."""
        errors: list[S0maSemanticError] = []

        for nerve in module.nerves:
            if nerve.kind not in VALID_KINDS_FOR_DECLARATION[DeclarationType.NERVE]:
                line = nerve.location.start_line if nerve.location else 0
                valid = ", ".join(
                    k.value for k in sorted(
                        VALID_KINDS_FOR_DECLARATION[DeclarationType.NERVE],
                        key=lambda k: k.value,
                    )
                )
                errors.append(S0maSemanticError(
                    code="INVALID_KIND",
                    message=(
                        f"Nerve '{nerve.name}' has kind '{nerve.kind.value}', "
                        f"which is not valid for nerve declarations."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        f"Change the kind of '{nerve.name}' to one of the "
                        f"valid nerve kinds: {valid}."
                    ),
                    context={
                        "component": nerve.name,
                        "declaration_type": "nerve",
                        "actual_kind": nerve.kind.value,
                        "valid_kinds": valid,
                    },
                ))

        for cell in module.cells:
            if cell.kind not in VALID_KINDS_FOR_DECLARATION[DeclarationType.CELL]:
                line = cell.location.start_line if cell.location else 0
                valid = ", ".join(
                    k.value for k in sorted(
                        VALID_KINDS_FOR_DECLARATION[DeclarationType.CELL],
                        key=lambda k: k.value,
                    )
                )
                errors.append(S0maSemanticError(
                    code="INVALID_KIND",
                    message=(
                        f"Cell '{cell.name}' has kind '{cell.kind.value}', "
                        f"which is not valid for cell declarations."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        f"Change the kind of '{cell.name}' to one of the "
                        f"valid cell kinds: {valid}."
                    ),
                    context={
                        "component": cell.name,
                        "declaration_type": "cell",
                        "actual_kind": cell.kind.value,
                        "valid_kinds": valid,
                    },
                ))

        return errors

    # -------------------------------------------------------------------
    # 7.3 — Layer consistency (R-23, FR-17)
    # -------------------------------------------------------------------

    def _check_layer_consistency(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate that all components share the module's layer."""
        errors: list[S0maSemanticError] = []
        module_layer = module.module.layer

        for decl in module.all_declarations:
            decl_layer = getattr(decl, "layer", None)
            if decl_layer is None:
                continue  # standalone axons don't have a layer field
            if decl_layer != module_layer:
                name = getattr(decl, "name", "<unknown>")
                line = decl.location.start_line if decl.location else 0
                errors.append(S0maSemanticError(
                    code="LAYER_MISMATCH",
                    message=(
                        f"Component '{name}' has layer '{decl_layer.value}' "
                        f"but module '{module.module.name}' declares layer "
                        f"'{module_layer.value}'. All components must share "
                        f"the module's layer in v1."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        f"Change the layer on '{name}' to "
                        f"'{module_layer.value}' to match the module's layer, "
                        f"or move '{name}' to a module with layer "
                        f"'{decl_layer.value}'."
                    ),
                    context={
                        "component": name,
                        "component_layer": decl_layer.value,
                        "module_layer": module_layer.value,
                    },
                ))

        return errors

    # -------------------------------------------------------------------
    # 7.2 — Visibility/export consistency (R-27, FR-16)
    # -------------------------------------------------------------------

    def _check_visibility_export_consistency(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate that visibility and exports agree.

        - Exported components must be PUBLIC.
        - Non-exported components must be INTERNAL.
        Error in ALL strictness modes.
        """
        errors: list[S0maSemanticError] = []
        exports = set(module.module.exports)

        for decl in module.all_declarations:
            visibility = getattr(decl, "visibility", None)
            if visibility is None:
                continue  # standalone axons, tests without visibility
            name = getattr(decl, "name", "<unknown>")
            line = decl.location.start_line if decl.location else 0
            is_exported = name in exports

            if is_exported and visibility != Visibility.PUBLIC:
                errors.append(S0maSemanticError(
                    code="VISIBILITY_MISMATCH",
                    message=(
                        f"Component '{name}' is in the exports list but has "
                        f"visibility '{visibility.value}'. Exported components "
                        f"must be PUBLIC."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        f"Change the visibility of '{name}' to PUBLIC, or "
                        f"remove '{name}' from the module's exports list."
                    ),
                    context={
                        "component": name,
                        "visibility": visibility.value,
                        "exported": True,
                        "expected_visibility": "PUBLIC",
                    },
                ))
            elif not is_exported and visibility == Visibility.PUBLIC:
                errors.append(S0maSemanticError(
                    code="VISIBILITY_MISMATCH",
                    message=(
                        f"Component '{name}' has visibility PUBLIC but is "
                        f"not in the module's exports list. PUBLIC components "
                        f"must be exported."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        f"Add '{name}' to the module's exports list, or "
                        f"change its visibility to INTERNAL."
                    ),
                    context={
                        "component": name,
                        "visibility": visibility.value,
                        "exported": False,
                        "expected_visibility": "INTERNAL",
                    },
                ))

        return errors

    # -------------------------------------------------------------------
    # 7.4 — Inline axon validation
    # -------------------------------------------------------------------

    def _check_inline_axons(
        self, module: S0maModule, ns: NamespaceService,
    ) -> list[S0maSemanticError]:
        """Validate inline depends_on entries.

        Checks:
        - Target exists in the component-reference namespace
        - Relation is an authored type (never RAISES or TYPE_USES per §1.12)
        - Source declaration exists locally (implicit — it's the parent decl)
        """
        errors: list[S0maSemanticError] = []

        for decl in module.all_declarations:
            depends_on: tuple[InlineAxon, ...] = getattr(decl, "depends_on", ())
            parent_name = getattr(decl, "name", "<unknown>")
            parent_line = decl.location.start_line if decl.location else 0

            for axon in depends_on:
                axon_line = axon.location.start_line if axon.location else parent_line

                # Check relation is authored type (R-22 / §1.12)
                if axon.relation.is_derived():
                    errors.append(S0maSemanticError(
                        code="INVALID_AXON_RELATION",
                        message=(
                            f"Inline dependency on '{axon.target}' in "
                            f"'{parent_name}' uses derived relation "
                            f"'{axon.relation.value}'. Derived relations "
                            f"(RAISES, TYPE_USES) must never be authored "
                            f"manually — they are inferred by the transpiler."
                        ),
                        file=self.filename,
                        line=axon_line,
                        column=0,
                        severity="error",
                        remediation=(
                            "Change the relation to an authored type "
                            "(CALLS, CONSTRUCTS, READS, CONFIGURES, "
                            "PRODUCES, or CONSUMES). "
                            "RAISES edges are derived from the 'raises' "
                            "field; TYPE_USES edges are derived from "
                            "function signature annotations."
                        ),
                        context={
                            "source": parent_name,
                            "target": axon.target,
                            "relation": axon.relation.value,
                            "allowed_relations": (
                                "CALLS, CONSTRUCTS, READS, CONFIGURES, PRODUCES, CONSUMES"
                            ),
                        },
                    ))

                # DSL-M2 (0.8.0, ADR-011 §(d)): qualified in-project
                # targets (``module.declaration``) are resolved against
                # the PROJECT module set by the dependency resolver
                # (``_check_qualified_depends_on``) — the module-local
                # namespace below cannot see other modules, so the
                # dotted form skips it entirely (the relation check
                # above still applied).
                if "." in axon.target:
                    continue

                # Check target exists in component-reference namespace
                if not ns.is_in_component_ref_namespace(axon.target):
                    # Check if it's a requires name (common mistake)
                    if ns.is_requires_name(axon.target):
                        errors.append(S0maSemanticError(
                            code="INVALID_RAISES_TARGET",
                            message=(
                                f"Inline dependency target '{axon.target}' in "
                                f"'{parent_name}' is a requires name (external "
                                f"Python dependency), not a s0ma component. "
                                f"DSL metadata fields can only reference s0ma "
                                f"components."
                            ),
                            file=self.filename,
                            line=axon_line,
                            column=0,
                            severity="error",
                            remediation=(
                                f"Move '{axon.target}' from requires to uses "
                                f"if it is a s0ma component, or remove it from "
                                f"the depends_on block if it is a plain Python "
                                f"dependency."
                            ),
                            context={
                                "source": parent_name,
                                "target": axon.target,
                                "target_origin": "requires",
                            },
                        ))
                    else:
                        errors.append(S0maSemanticError(
                            code="DOES_NOT_EXIST",
                            message=(
                                f"Inline dependency target '{axon.target}' in "
                                f"'{parent_name}' does not exist in the "
                                f"component-reference namespace (local "
                                f"declarations and uses imports)."
                            ),
                            file=self.filename,
                            line=axon_line,
                            column=0,
                            severity="error",
                            remediation=(
                                f"Ensure '{axon.target}' is declared in this "
                                f"module or imported via a uses entry. Check "
                                f"spelling and ensure the target is a s0ma "
                                f"component, not an external Python dependency."
                            ),
                            context={
                                "source": parent_name,
                                "target": axon.target,
                            },
                        ))

        return errors

    # -------------------------------------------------------------------
    # 7.5 — serves_as validation, module scope (DSL-M1, ADR-011 §(b))
    # -------------------------------------------------------------------

    def _check_serves_as_fields(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate ``serves_as:`` values within one module.

        - ``SERVES_AS_INVALID``: value not identifier-shaped. Served
          names that are NOT identifiers (resource URIs) belong in
          ``metadata:`` — ``serves_as`` is identifier-only because its
          emitted form must be a legal ``__name__``.
        - ``SERVES_AS_COLLISION`` (module scope): two declarations in
          this module carry the same ``serves_as`` value — one flat
          served-name namespace (L-2). Equality with the declaration's
          OWN identifier is permitted (harmless idempotent rename);
          the cross-module scope is validated by the dependency
          resolver on project builds.
        """
        errors: list[S0maSemanticError] = []
        carriers: dict[str, list[NerveDecl]] = {}

        for nerve in module.nerves:
            served = nerve.serves_as
            if served is None:
                continue
            line = nerve.location.start_line if nerve.location else 0
            if not _METADATA_KEY_RE.match(served):
                errors.append(S0maSemanticError(
                    code="SERVES_AS_INVALID",
                    message=(
                        f"serves_as value {served!r} on '{nerve.name}' is "
                        f"not identifier-shaped. The served name becomes "
                        f"the emitted callable's __name__, so it must "
                        f"match [A-Za-z_][A-Za-z0-9_]*."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        "Use a bare identifier (e.g. 'serves_as: check'). "
                        "Non-identifier served names (resource URIs, "
                        "catalog paths) belong in 'metadata:' instead."
                    ),
                    context={"declaration": nerve.name, "serves_as": served},
                ))
                continue
            carriers.setdefault(served, []).append(nerve)

        for served, nerves in sorted(carriers.items()):
            if len(nerves) < 2:
                continue
            names = ", ".join(f"'{n.name}'" for n in nerves)
            first_line = (
                nerves[0].location.start_line if nerves[0].location else 0
            )
            errors.append(S0maSemanticError(
                code="SERVES_AS_COLLISION",
                message=(
                    f"serves_as '{served}' is carried by more than one "
                    f"declaration in this module: {names}. Served names "
                    f"form one flat namespace and must be unique."
                ),
                file=self.filename,
                line=first_line,
                column=0,
                severity="error",
                remediation=(
                    f"Rename the serves_as value on all but one of "
                    f"{names} (or drop the field where the declaration "
                    f"name itself is the served name)."
                ),
                context={
                    "serves_as": served,
                    "declarations": [n.name for n in nerves],
                },
            ))

        return errors

    # -------------------------------------------------------------------
    # 7.6 — Authored metadata shape validation (DSL-M1, ADR-011 §(a))
    # -------------------------------------------------------------------

    def _check_metadata_fields(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate authored ``metadata:`` maps on nerve/cell/ganglion.

        Shape-only validation per design rule L-1 — the language never
        interprets values (P-2). Three checks, all error in every mode:

        - ``METADATA_INVALID_KEY``: key not identifier-shaped, or the
          same key authored twice in one map (the AST carries ordered
          pairs precisely so duplicates survive parsing).
        - ``METADATA_INVALID_VALUE``: value outside the L-1 shape set
          (string | int | float | bool | list-of-strings) — nested
          maps, null entries, unquoted bare tokens, malformed list
          entries, and the unsupported inline ``metadata: {...}`` form
          all land here via the parser's invalid-value markers.
        - ``METADATA_RESERVED_KEY``: key collides with
          ``RESERVED_COMPONENT_METADATA_KEYS`` (the emitter writes
          those keys into the same registration dict the authored map
          merges into); the remediation points at the declaration
          field that owns the fact where one exists.
        """
        errors: list[S0maSemanticError] = []

        for decl in module.all_declarations:
            entries = getattr(decl, "metadata", ())
            if not entries:
                continue
            decl_name = getattr(decl, "name", "<unknown>")
            decl_line = decl.location.start_line if decl.location else 0
            seen_keys: set[str] = set()

            for key, value in entries:
                is_marker = isinstance(value, str) and value.startswith(
                    METADATA_INVALID_VALUE_MARKER,
                )
                if is_marker:
                    reason, _, raw_display = value[
                        len(METADATA_INVALID_VALUE_MARKER):
                    ].partition("\x00")
                    described = _METADATA_INVALID_REASONS.get(
                        reason, "is not in the metadata value shape set",
                    )
                    subject = (
                        f"The 'metadata:' field on '{decl_name}'"
                        if not key
                        else f"Metadata entry '{key}' on '{decl_name}'"
                    )
                    errors.append(S0maSemanticError(
                        code="METADATA_INVALID_VALUE",
                        message=(
                            f"{subject} {described}."
                            + (f" Got: {raw_display!r}." if raw_display else "")
                        ),
                        file=self.filename,
                        line=decl_line,
                        column=0,
                        severity="error",
                        remediation=(
                            "Author 'metadata:' as an indented block map "
                            "whose values are a quoted string, an integer, "
                            "a float, true/false, or a bracketed list of "
                            "strings (entries quoted, or bare when "
                            "identifier-shaped)."
                        ),
                        context={
                            "declaration": decl_name,
                            "key": key,
                            "reason": reason,
                        },
                    ))
                    if not key:
                        continue
                elif not isinstance(
                    value, (str, int, float, bool, tuple),
                ) or (
                    isinstance(value, tuple)
                    and not all(isinstance(item, str) for item in value)
                ):  # pragma: no cover — parser only produces L-1 shapes
                    errors.append(S0maSemanticError(
                        code="METADATA_INVALID_VALUE",
                        message=(
                            f"Metadata entry '{key}' on '{decl_name}' has a "
                            f"value outside the shape set (string | int | "
                            f"float | bool | list of strings)."
                        ),
                        file=self.filename,
                        line=decl_line,
                        column=0,
                        severity="error",
                        remediation=(
                            "Use a quoted string, an integer, a float, "
                            "true/false, or a bracketed list of strings."
                        ),
                        context={"declaration": decl_name, "key": key},
                    ))

                if not key:
                    continue

                if not _METADATA_KEY_RE.match(key):
                    errors.append(S0maSemanticError(
                        code="METADATA_INVALID_KEY",
                        message=(
                            f"Metadata key {key!r} on '{decl_name}' is not "
                            f"identifier-shaped. Keys must match "
                            f"[A-Za-z_][A-Za-z0-9_]*."
                        ),
                        file=self.filename,
                        line=decl_line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Rename the {key!r} entry to an identifier "
                            f"(letters, digits, underscores; not starting "
                            f"with a digit)."
                        ),
                        context={"declaration": decl_name, "key": key},
                    ))
                elif key in seen_keys:
                    errors.append(S0maSemanticError(
                        code="METADATA_INVALID_KEY",
                        message=(
                            f"Metadata key '{key}' on '{decl_name}' is "
                            f"authored more than once. Each key in a "
                            f"'metadata:' map must be unique."
                        ),
                        file=self.filename,
                        line=decl_line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Remove or rename the duplicate '{key}:' "
                            f"entry (to carry several values under one "
                            f"key, use a single list value)."
                        ),
                        context={"declaration": decl_name, "key": key},
                    ))
                elif key in RESERVED_COMPONENT_METADATA_KEYS:
                    field_hint = _RESERVED_KEY_FIELD_HINTS.get(key)
                    if field_hint is not None:
                        remediation = (
                            f"Set the declaration's '{field_hint}' field "
                            f"instead — the emitter derives the "
                            f"'{key}' registration-metadata key from it."
                        )
                    else:
                        remediation = (
                            f"Choose a different key: '{key}' is written "
                            f"by the emitter from declaration structure "
                            f"and cannot be authored."
                        )
                    errors.append(S0maSemanticError(
                        code="METADATA_RESERVED_KEY",
                        message=(
                            f"Metadata key '{key}' on '{decl_name}' "
                            f"collides with a reserved registration-"
                            f"metadata key (the emitter writes '{key}' "
                            f"into the same metadata dict)."
                        ),
                        file=self.filename,
                        line=decl_line,
                        column=0,
                        severity="error",
                        remediation=remediation,
                        context={
                            "declaration": decl_name,
                            "key": key,
                            "reserved": True,
                        },
                    ))
                seen_keys.add(key)

        return errors

    # -------------------------------------------------------------------
    # 7.7 — covered_by validation (DSL-M2, ADR-011 §(e))
    # -------------------------------------------------------------------

    def _check_covered_by_fields(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate ``covered_by:`` shape on nerve / cell / ganglion.

        DSL-M2 (0.8.0, ADR-011 §(e)): the field is a non-empty list of
        non-empty strings — suite paths or rationale prose, authored-
        opaque (the language never resolves them). ``COVERED_BY_EMPTY``
        (error in every mode) fires when the field is present with an
        empty list (the parser encodes that as one empty-string marker)
        or when any entry is empty/whitespace: an empty coverage claim
        would credit the release gate with no auditable evidence.
        """
        errors: list[S0maSemanticError] = []
        severity = get_severity("COVERED_BY_EMPTY", self.mode)
        if severity is None:
            return errors

        declarations = (
            list(module.nerves) + list(module.cells) + list(module.ganglia)
        )
        for decl in declarations:
            state = dict(decl.semantic_states).get("covered_by")
            if state is not None and state.state in {"none", "pending"}:
                # The empty primitive is only the parser's internal
                # projection of an explicit tagged state. ``none`` is a
                # truthful no-evidence assertion and pending debt is
                # reported by SEMANTIC_PENDING_DEBT; neither is a malformed
                # list claim.
                continue
            covered_by = getattr(decl, "covered_by", ())
            if not covered_by:
                continue
            if all(entry.strip() for entry in covered_by):
                continue
            line = decl.location.start_line if decl.location else 0
            errors.append(S0maSemanticError(
                code="COVERED_BY_EMPTY",
                message=(
                    f"covered_by on '{decl.name}' is empty or contains "
                    f"an empty entry. The field is the release gate's "
                    f"external test-evidence credit — an empty claim "
                    f"credits coverage with no auditable evidence."
                ),
                file=self.filename,
                line=line,
                column=0,
                severity=severity,
                remediation=(
                    "List the external suite paths (or a rationale) "
                    "that cover this declaration, e.g. covered_by: "
                    '["tests/test_tools.py — boundary-contract '
                    'suite"], or remove the field.'
                ),
                context={
                    "declaration": decl.name,
                    "covered_by": list(covered_by),
                },
            ))

        return errors

    # -------------------------------------------------------------------
    # 7.4 (continued) — Standalone axon relation validation (R-22)
    # -------------------------------------------------------------------

    def _check_standalone_axon_relations(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate that standalone axons use authored relation types only.

        Also validates that the source exists as a local declaration.
        Target validation (cross-module) is deferred to M8.
        """
        errors: list[S0maSemanticError] = []
        local_names = set()
        for decl in module.all_declarations:
            if not isinstance(decl, StandaloneAxonDecl):
                name = getattr(decl, "name", None)
                if name:
                    local_names.add(name)

        for axon in module.axons:
            line = axon.location.start_line if axon.location else 0

            # Check relation is authored type (R-22 / §1.12)
            if axon.relation.is_derived():
                errors.append(S0maSemanticError(
                    code="INVALID_AXON_RELATION",
                    message=(
                        f"Standalone axon '{axon.source} -> {axon.target}' "
                        f"uses derived relation '{axon.relation.value}'. "
                        f"Derived relations (RAISES, TYPE_USES) must never "
                        f"be authored manually."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        "Change the relation to an authored type "
                        "(CALLS, CONSTRUCTS, READS, CONFIGURES, "
                        "PRODUCES, or CONSUMES). "
                        "RAISES edges are derived from 'raises' fields; "
                        "TYPE_USES edges are derived from function "
                        "signature annotations."
                    ),
                    context={
                        "source": axon.source,
                        "target": axon.target,
                        "relation": axon.relation.value,
                        "allowed_relations": (
                            "CALLS, CONSTRUCTS, READS, CONFIGURES, PRODUCES, CONSUMES"
                        ),
                    },
                ))

            # Check source exists locally
            if axon.source not in local_names:
                errors.append(S0maSemanticError(
                    code="DOES_NOT_EXIST",
                    message=(
                        f"Standalone axon source '{axon.source}' does not "
                        f"exist as a declaration in this module."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        f"Ensure '{axon.source}' is declared in this module "
                        f"(as a nerve, cell, ganglion, or test). Standalone "
                        f"axon sources must be local declarations."
                    ),
                    context={
                        "source": axon.source,
                        "target": axon.target,
                        "available_locals": sorted(local_names),
                    },
                ))

        return errors

    # -------------------------------------------------------------------
    # 7.5 — Raises field validation (R-17, FR-15)
    # -------------------------------------------------------------------

    def _check_raises_fields(
        self, module: S0maModule, ns: NamespaceService,
    ) -> list[S0maSemanticError]:
        """Validate that raises entries reference valid exception cells.

        Each entry must:
        - Exist in the component-reference namespace
        - NOT be a requires name (external exceptions must be wrapped)
        """
        errors: list[S0maSemanticError] = []

        for nerve in module.nerves:
            if not nerve.raises:
                continue
            line = nerve.location.start_line if nerve.location else 0

            for exc_name in nerve.raises:
                if ns.is_requires_name(exc_name):
                    errors.append(S0maSemanticError(
                        code="INVALID_RAISES_TARGET",
                        message=(
                            f"Nerve '{nerve.name}' raises '{exc_name}', "
                            f"which is a requires name (external Python "
                            f"dependency). The raises field must only "
                            f"reference exception cells visible in the "
                            f"component-reference namespace."
                        ),
                        file=self.filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Create a s0ma exception cell wrapping "
                            f"'{exc_name}' in this module or another s0ma "
                            f"module, import it via uses, and reference the "
                            f"wrapper in the raises field instead. External "
                            f"exceptions should be normalized at adapter "
                            f"boundaries."
                        ),
                        context={
                            "nerve": nerve.name,
                            "exception": exc_name,
                            "origin": "requires",
                        },
                    ))
                elif not ns.is_in_component_ref_namespace(exc_name):
                    errors.append(S0maSemanticError(
                        code="DOES_NOT_EXIST",
                        message=(
                            f"Nerve '{nerve.name}' raises '{exc_name}', "
                            f"which does not exist in the component-reference "
                            f"namespace."
                        ),
                        file=self.filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Ensure '{exc_name}' is declared as an exception "
                            f"cell in this module or imported via a uses entry. "
                            f"Check spelling and ensure the target is a s0ma "
                            f"component."
                        ),
                        context={
                            "nerve": nerve.name,
                            "exception": exc_name,
                        },
                    ))

        return errors

    # -------------------------------------------------------------------
    # 7.8 — Provides field validation
    # -------------------------------------------------------------------

    def _check_provides_fields(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate that provides entries match def names in the body.

        If a nerve declares ``provides: [op_a, op_b]`` and has a body,
        each name in provides must appear as a ``def`` in the body.

        POST-3a (0.15.0): when the structured ``provides:`` form is in
        use (any entry carries a per-method ``returns:`` / ``expects:`` /
        ``guarantees:`` triple), we additionally validate the body's
        terminal ``return {...}`` dict keys against the same set of
        provides names — mirroring the existing ``MISSING_RETURN_KEY``
        check on the standalone ``returns:`` field. The structured form
        is most useful for factory-pattern SERVICE bodies where the
        returned dict literally maps each provides name to the inner
        ``def``; catching the typo (``"asemble"`` vs ``"assemble"``) at
        check time is the whole point of writing the triple inline. The
        check is silently skipped when the body has no ``return { ... }``
        literal (class-bodied SERVICE pattern), preserving the existing
        flat-form behaviour.
        """
        errors: list[S0maSemanticError] = []

        for nerve in module.nerves:
            if not nerve.provides:
                continue
            line = nerve.location.start_line if nerve.location else 0

            if not nerve.body:
                # No body to check against — skip silently
                # (body-less nerves get a stub ``pass`` body from the emitter)
                continue

            body_def_names = _extract_def_names(nerve.body)

            for provided in nerve.provides:
                if provided not in body_def_names:
                    errors.append(S0maSemanticError(
                        code="MISSING_PROVIDED_FUNCTION",
                        message=(
                            f"Nerve '{nerve.name}' declares "
                            f"provides: [{', '.join(nerve.provides)}], "
                            f"but '{provided}' is not defined in the body."
                        ),
                        file=self.filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Add 'def {provided}(...)' to the body of "
                            f"'{nerve.name}', or remove '{provided}' from "
                            f"the provides list."
                        ),
                        context={
                            "nerve": nerve.name,
                            "missing_function": provided,
                            "declared_provides": list(nerve.provides),
                            "body_functions": sorted(body_def_names),
                        },
                    ))

            # POST-3a: structured-form returned-dict-key check.
            structured = any(
                entry.has_triple for entry in nerve.provides_entries
            )
            if not structured:
                continue
            return_keys = _extract_return_dict_keys(nerve.body)
            if return_keys is None:
                # No return-dict pattern (class-bodied or no terminal
                # return dict) — skip silently. The flat ``def`` check
                # above already covers the structural contract.
                continue

            for provided in nerve.provides:
                if provided not in return_keys:
                    errors.append(S0maSemanticError(
                        code="MISSING_RETURN_KEY",
                        message=(
                            f"Nerve '{nerve.name}' declares a "
                            f"structured 'provides:' entry for "
                            f"'{provided}' (with a per-method "
                            f"returns:/expects:/guarantees: triple), "
                            f"but '{provided}' is not a key in the "
                            f"body's returned dict."
                        ),
                        file=self.filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Add '{provided}' as a key in the return "
                            f"dict of '{nerve.name}', or remove the "
                            f"structured 'provides:' entry for "
                            f"'{provided}'."
                        ),
                        context={
                            "nerve": nerve.name,
                            "missing_key": provided,
                            "declared_provides": list(nerve.provides),
                            "body_return_keys": sorted(return_keys),
                        },
                    ))

        return errors

    # -------------------------------------------------------------------
    # 11.1 — Abstract nerve validation
    # -------------------------------------------------------------------

    def _check_abstract_fields(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate abstract nerve declarations.

        Rules:
        - ``interface`` may only be declared on abstract nerves.
        - If a non-abstract nerve has a CONSTRUCTS dependency targeting an
          abstract nerve in the same module, validate that the concrete
          nerve's body defines all methods listed in the abstract's interface.
        """
        errors: list[S0maSemanticError] = []

        # Index abstract nerves by name
        abstract_nerves: dict[str, NerveDecl] = {}
        for nerve in module.nerves:
            if nerve.abstract:
                abstract_nerves[nerve.name] = nerve

        for nerve in module.nerves:
            line = nerve.location.start_line if nerve.location else 0

            # interface may only appear on abstract nerves
            if nerve.interface and not nerve.abstract:
                errors.append(S0maSemanticError(
                    code="INTERFACE_ON_NON_ABSTRACT",
                    message=(
                        f"Nerve '{nerve.name}' declares 'interface' but is "
                        f"not marked 'abstract: true'."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        f"Either add 'abstract: true' to '{nerve.name}', "
                        f"or remove the 'interface' field."
                    ),
                    context={
                        "nerve": nerve.name,
                        "interface": list(nerve.interface),
                    },
                ))

            # Check concrete nerves that CONSTRUCTS an abstract nerve
            if nerve.abstract:
                continue

            for axon in nerve.depends_on:
                if axon.relation != Relation.CONSTRUCTS:
                    continue
                target = abstract_nerves.get(axon.target)
                if target is None or not target.interface:
                    continue

                # Concrete nerve must define all interface methods
                if not nerve.body:
                    errors.append(S0maSemanticError(
                        code="MISSING_INTERFACE_METHODS",
                        message=(
                            f"Nerve '{nerve.name}' CONSTRUCTS abstract "
                            f"nerve '{target.name}' but has no body to "
                            f"implement the required interface."
                        ),
                        file=self.filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Add a body to '{nerve.name}' with definitions "
                            f"for: {', '.join(target.interface)}."
                        ),
                        context={
                            "nerve": nerve.name,
                            "abstract_nerve": target.name,
                            "required_methods": list(target.interface),
                        },
                    ))
                    continue

                body_defs = _extract_def_names(nerve.body)
                missing = [m for m in target.interface if m not in body_defs]
                if missing:
                    errors.append(S0maSemanticError(
                        code="MISSING_INTERFACE_METHODS",
                        message=(
                            f"Nerve '{nerve.name}' CONSTRUCTS abstract "
                            f"nerve '{target.name}' but is missing "
                            f"interface methods: {', '.join(missing)}."
                        ),
                        file=self.filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Add the following definitions to "
                            f"'{nerve.name}': "
                            + ", ".join(f"def {m}(...)" for m in missing)
                            + "."
                        ),
                        context={
                            "nerve": nerve.name,
                            "abstract_nerve": target.name,
                            "required_methods": list(target.interface),
                            "missing_methods": missing,
                            "body_functions": sorted(body_defs),
                        },
                    ))

        return errors

    # -------------------------------------------------------------------
    # 11.2 — Returns field validation
    # -------------------------------------------------------------------

    def _check_returns_fields(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate that ``returns`` entries match return-dict keys in the body.

        If a nerve declares ``returns: [op_a, op_b]`` and has a function body,
        check that the body contains a ``return {`` dict with matching keys.
        """
        errors: list[S0maSemanticError] = []

        for nerve in module.nerves:
            if not nerve.returns:
                continue
            line = nerve.location.start_line if nerve.location else 0

            if not nerve.body:
                continue

            # Extract dict keys from return statements in the body
            return_keys = _extract_return_dict_keys(nerve.body)
            if return_keys is None:
                # Could not find a return-dict pattern — skip validation
                continue

            for key in nerve.returns:
                if key not in return_keys:
                    errors.append(S0maSemanticError(
                        code="MISSING_RETURN_KEY",
                        message=(
                            f"Nerve '{nerve.name}' declares "
                            f"returns: [{', '.join(nerve.returns)}], "
                            f"but '{key}' is not a key in the returned dict."
                        ),
                        file=self.filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Add '{key}' as a key in the return dict of "
                            f"'{nerve.name}', or remove '{key}' from the "
                            f"returns list."
                        ),
                        context={
                            "nerve": nerve.name,
                            "missing_key": key,
                            "declared_returns": list(nerve.returns),
                            "body_return_keys": sorted(return_keys),
                        },
                    ))

        return errors

    # -------------------------------------------------------------------
    # 10.3 — Test helper name collision detection
    # -------------------------------------------------------------------

    def _check_test_helper_collisions(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Warn when multiple test declarations define helpers with the same name.

        If two test bodies both define ``def _setup_env(...)``, the second
        definition will silently overwrite the first at module scope. This
        check detects that situation and emits a warning.
        """
        errors: list[S0maSemanticError] = []

        if len(module.tests) < 2:
            return errors

        # {function_name: [declaring_test_names]}
        helper_sources: dict[str, list[str]] = {}

        for test_decl in module.tests:
            if not test_decl.body:
                continue
            func_names = _extract_top_level_def_names(test_decl.body)
            for fn in func_names:
                helper_sources.setdefault(fn, []).append(test_decl.name)

        for fn_name, test_names in sorted(helper_sources.items()):
            if len(test_names) >= 2:
                line = module.tests[0].location.start_line if module.tests[0].location else 0
                errors.append(S0maSemanticError(
                    code="HELPER_NAME_COLLISION",
                    message=(
                        f"Helper function '{fn_name}' is defined at "
                        f"module-scope in both test '{test_names[0]}' and "
                        f"test '{test_names[1]}'. The second definition will "
                        f"overwrite the first at module scope."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="warning",
                    remediation=(
                        f"Either rename '{fn_name}' in one of the test "
                        f"declarations, or — if these are class methods or "
                        f"inner-function closures — wrap them in a `class` "
                        f"or outer `def` so they are not at top-level."
                    ),
                    context={
                        "helper_name": fn_name,
                        "declaring_tests": test_names,
                    },
                ))

        return errors

    # -------------------------------------------------------------------
    # 10.4 — A test the runner would never run
    # -------------------------------------------------------------------

    def _check_test_collection(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Report a ``test`` declaration whose code the runner will not run.

        ``TEST_NOT_COLLECTED``. The emitter writes a test's code out as it
        was authored and registers the declaration as coverage for the
        parts it names; whether anything *runs* is then pytest's decision,
        taken on the function's name alone. A body that defines only
        ``def check_dates()`` is therefore emitted, counted as coverage —
        release-mode ``MISSING_TEST_COVERAGE`` is satisfied by it — and
        never executed, which is a verification claim nothing stands
        behind.

        The names pytest collects are read from the project's own runner
        settings (:func:`_runner_name_patterns`) rather than assumed, so a
        project that has told pytest to collect ``check_*`` is not told its
        tests will not run. A body that does not parse is left to the body
        validator, which reports it.
        """
        severity = get_severity("TEST_NOT_COLLECTED", self.mode)
        if severity is None or not module.tests:
            return []

        functions, classes = _runner_name_patterns(self.filename)
        errors: list[S0maSemanticError] = []
        for test_decl in module.tests:
            if not test_decl.body:
                continue
            defined = _top_level_definitions(test_decl.body)
            if defined is None:
                continue
            function_names, class_methods = defined
            if any(_runner_collects(name, functions) for name in function_names):
                continue
            if any(
                _runner_collects(class_name, classes)
                and any(_runner_collects(method, functions) for method in methods)
                for class_name, methods in class_methods.items()
            ):
                continue

            wanted = " or ".join(f"`{pattern}`" for pattern in functions)
            found = ", ".join(f"`{name}`" for name in function_names) or "no function"
            suggested = (
                test_decl.name
                if _runner_collects(test_decl.name, functions)
                else f"test_{(function_names or [test_decl.name])[0].lstrip('_')}"
            )
            line = test_decl.location.start_line if test_decl.location else 0
            errors.append(S0maSemanticError(
                code="TEST_NOT_COLLECTED",
                message=(
                    f"Test '{test_decl.name}' defines {found}, and the test "
                    f"runner only runs functions whose names start with "
                    f"{wanted}. This test would never run, and it would "
                    f"still count as coverage for the parts it names."
                ),
                file=self.filename,
                line=line,
                column=0,
                severity=severity,
                remediation=(
                    f"Name the function `{suggested}`. The declaration's own "
                    f"name does not decide what runs; the function's does."
                ),
                context={
                    "test": test_decl.name,
                    "defined": list(function_names),
                    "collected_patterns": list(functions),
                    "suggestion": suggested,
                },
            ))

        return errors

    # -------------------------------------------------------------------
    # 11 — CONSTANT cell name vs. body identifier (M17, feedback 5–6)
    # -------------------------------------------------------------------

    def _check_constant_cell_body_assigns_cell_name(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate that every CONSTANT cell's body assigns to the cell name.

        For ``kind: CONSTANT`` cells, the transpiler emits
        ``from <module> import <cell_name>`` so the cell name is what
        consumers reach for via ``uses:``. The body must therefore
        contain a top-level assignment to that exact identifier — if the
        author writes ``cell VizTemplate :: ...`` with body
        ``VIZ_TEMPLATE = '''...'''`` the import resolves to a ``NameError``
        at runtime (feedback-5 MS 2 was exactly this).

        Severity: **error in every mode** — the cell declaration name
        IS the canonical IR identity, the same as for module names
        (M4) and test targets (M5). A mismatch is a hard correctness
        violation, not a strictness preference.

        Cells whose body is supplied via ``content: @file("...")``
        (M12) are exempt from this check: the codegen synthesises the
        ``<cell_name> = <literal>`` assignment from the embedded file's
        contents, so the cell name and the assigned identifier are
        guaranteed equal by construction.
        """
        errors: list[S0maSemanticError] = []
        for cell in module.cells:
            if cell.kind != Kind.CONSTANT:
                continue
            # M12 ``content: @file()`` cells: the codegen synthesises
            # the assignment from the cell name itself, so there is no
            # author-written body to check against. Skip.
            if cell.embedded_file_path is not None:
                continue
            if not cell.body:
                # No body and no embed — a separate check
                # (kind/declaration-shape) reports the missing body.
                continue
            assigned = _body_top_level_assigned_names(cell.body)
            if cell.name in assigned:
                continue
            line = cell.location.start_line if cell.location else 0
            errors.append(S0maSemanticError(
                code="CONSTANT_NAME_MISMATCH",
                message=(
                    f"CONSTANT cell '{cell.name}' declares its name as "
                    f"'{cell.name}' but the body does not assign to that "
                    f"identifier at top level (assigns to: "
                    f"{sorted(assigned) if assigned else '[]'}). The "
                    f"transpiler emits `from <module> import {cell.name}`; "
                    f"a mismatch would produce a runtime ImportError."
                ),
                file=self.filename,
                line=line,
                column=0,
                severity="error",
                remediation=(
                    f"Rename the cell declaration "
                    f"`cell <body_name> :: ...` to match the body's "
                    f"top-level assignment, or change the body assignment "
                    f"to `{cell.name} = ...`."
                ),
                context={
                    "cell_name": cell.name,
                    "assigned_names": sorted(assigned),
                },
            ))
        return errors

    # -------------------------------------------------------------------
    # 11.1 — POST-12b: placeholders: ↔ @file() content cross-validation
    # -------------------------------------------------------------------

    def _check_placeholders(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate ``placeholders:`` declarations on CONSTANT cells with ``@file()``.

        POST-12b (0.16.0): a CONSTANT cell whose body comes from an
        embedded file (``content: @file("path.html")``) can declare
        ``placeholders: [__SYSTEM_NAME__, __GRAPH_DATA_JSON__]`` to
        assert which magic-string markers the file's content carries.
        The check enforces both directions of the contract:

        * **Declared → present.** Every entry in ``placeholders:`` MUST
          appear at least once in the embedded file's content. A
          declared placeholder that is absent fires
          :data:`PLACEHOLDER_NOT_FOUND` at error severity in every
          strictness mode — the build would emit a constant string
          missing the marker a downstream renderer expects, producing
          a silent rendering bug. Same load-bearing-correctness
          precedent as ``CONSTANT_NAME_MISMATCH`` (declared shape must
          match actual shape).

        * **Present → declared.** Any placeholder-shaped string in the
          file (matching ``__[A-Z][A-Z0-9_]*__``) that is NOT listed
          in the cell's ``placeholders:`` field fires
          :data:`UNDECLARED_PLACEHOLDER` (warning in migration/dev,
          error in strict/release). The lint catches the silent-drift
          class where a marker is added to the file without updating
          the cell declaration — the renderer would either ignore it
          (silent rendering bug) or substitute an unexpected value
          (security or correctness drift).

        Cells without ``content: @file(...)`` are skipped — the
        ``placeholders:`` field is only meaningful for embedded content
        (the parser enforces this with a ``PARSE_ERROR``). Cells with
        ``@file()`` but no declared placeholders still get the
        present-but-undeclared lint so authors are nudged toward the
        explicit declaration once they introduce markers.
        """
        errors: list[S0maSemanticError] = []
        for cell in module.cells:
            # Only CONSTANT cells with embedded @file content participate
            # — the parser rejects ``placeholders:`` on any other shape,
            # but we double-check defensively.
            if cell.kind != Kind.CONSTANT:
                continue
            if cell.embedded_content is None:
                continue
            content = cell.embedded_content
            declared = set(cell.placeholders)
            line = cell.location.start_line if cell.location else 0

            # Pass 1: declared → present. Each declared placeholder must
            # appear in the file at least once. Missing entries are
            # always an error.
            for placeholder in cell.placeholders:
                if placeholder not in content:
                    errors.append(S0maSemanticError(
                        code="PLACEHOLDER_NOT_FOUND",
                        message=(
                            f"CONSTANT cell '{cell.name}' declares "
                            f"placeholder '{placeholder}' but the "
                            f"embedded file "
                            f"'{cell.embedded_file_path}' does not "
                            f"contain that marker."
                        ),
                        file=self.filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Either add the marker '{placeholder}' "
                            f"to the embedded file at "
                            f"'{cell.embedded_file_path}', or remove "
                            f"the entry from cell '{cell.name}'s "
                            f"'placeholders:' list."
                        ),
                        context={
                            "cell_name": cell.name,
                            "placeholder": placeholder,
                            "embedded_file_path": cell.embedded_file_path,
                        },
                    ))

            # Pass 2: present → declared. Scan the file for
            # placeholder-shaped substrings; any that are NOT in the
            # declared set fire the undeclared lint.
            found_in_file = set(_PLACEHOLDER_PATTERN.findall(content))
            undeclared = sorted(found_in_file - declared)
            if undeclared:
                severity = get_severity("UNDECLARED_PLACEHOLDER", self.mode)
                if severity is not None:
                    for marker in undeclared:
                        errors.append(S0maSemanticError(
                            code="UNDECLARED_PLACEHOLDER",
                            message=(
                                f"CONSTANT cell '{cell.name}': the "
                                f"embedded file "
                                f"'{cell.embedded_file_path}' contains "
                                f"placeholder-shaped marker "
                                f"'{marker}' that is not listed in "
                                f"the cell's 'placeholders:' field."
                            ),
                            file=self.filename,
                            line=line,
                            column=0,
                            severity=severity,
                            remediation=(
                                f"Add '{marker}' to cell '{cell.name}'s "
                                f"'placeholders:' list so the declared "
                                f"marker set matches the file's actual "
                                f"content, or remove the marker from "
                                f"the embedded file if it is not "
                                f"intended to be substituted by a "
                                f"downstream renderer."
                            ),
                            context={
                                "cell_name": cell.name,
                                "placeholder": marker,
                                "embedded_file_path": cell.embedded_file_path,
                            },
                        ))
        return errors

    # -------------------------------------------------------------------
    # 12 — POST-3b: mocks: ↔ target provides: cross-validation
    # -------------------------------------------------------------------

    def _check_mocks_key_mismatch(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Cross-check ``mocks:`` targets against mock-shape dicts in the body.

        POST-3b (0.15.0): when a ``test`` declaration carries
        ``mocks: [<NerveName>, ...]`` and the body assigns a dict
        literal to a variable whose name matches the lowercased mock
        target (optionally prefixed with ``mock_`` / ``fake_`` /
        ``stub_``), cross-check the dict's literal-string keys against
        the target nerve's ``provides:`` set. Mismatches fire
        :data:`MOCK_KEY_MISMATCH` (warning in dev/migration; error in
        strict/release).

        Conservative by design: false positives are worse than false
        negatives. The check only fires when (a) the target is a local
        nerve with a non-empty ``provides:``, (b) the body contains
        an assignment ``<name> = { ... }`` whose ``<name>`` matches
        the convention, and (c) every dict key the body declares is a
        literal string. Dynamic mock construction (``mock = dict(...)``,
        comprehensions, str-formatted keys) is intentionally skipped.

        Unresolved targets (not a local nerve and not in ``uses:``)
        fire :data:`DOES_NOT_EXIST` per the existing axon-target
        resolution pattern; cross-module targets (resolved via
        ``uses:``) are accepted without dict-key check at this layer
        — only the local-module check has access to the target's
        ``provides:`` set without a full cross-module resolution pass.
        """
        errors: list[S0maSemanticError] = []
        if not module.tests:
            return errors

        # Local nerve index keyed by declared name. Cross-module
        # references go through ``uses:`` (handled below).
        local_nerves: dict[str, NerveDecl] = {
            n.name: n for n in module.nerves
        }
        # Names imported via ``uses:`` (aliases resolved). Targets in
        # this set are accepted as known (the cross-module resolver
        # validates them in dependency.py) but we do not have access
        # to their ``provides:`` set here, so we skip the dict-key
        # cross-check for them.
        uses_local_names: set[str] = set()
        for use in module.module.uses:
            uses_local_names.add(use.alias or use.qualified_name.split(".")[-1])

        severity = get_severity("MOCK_KEY_MISMATCH", self.mode)

        for test in module.tests:
            if not test.mocks:
                continue
            test_line = (
                test.location.start_line if test.location else 0
            )

            # Pre-extract every assignment ``<name> = {...literal-string keys}``
            # from the body once per test. Bodies without parseable
            # AST or without dict-shaped literal assignments produce
            # an empty map (the check skips silently — see _extract_mock_dict_assignments).
            assignments: dict[str, _MockDictLiteral] = (
                _extract_mock_dict_assignments(test.body or "")
            )

            for mock_target in test.mocks:
                # First: resolve the target. Local nerves are
                # checked in full; cross-module (``uses:``) targets
                # are accepted as known but skipped at this layer;
                # everything else raises DOES_NOT_EXIST.
                local_target = local_nerves.get(mock_target)
                if local_target is None:
                    if mock_target in uses_local_names:
                        # Cross-module mock target; skip the dict-key
                        # check at this layer (the cross-module
                        # resolver validates the target's existence
                        # and visibility separately).
                        continue
                    errors.append(S0maSemanticError(
                        code="DOES_NOT_EXIST",
                        message=(
                            f"Test '{test.name}' lists "
                            f"'{mock_target}' in mocks: but the name "
                            f"does not resolve to a local nerve or a "
                            f"`uses:` entry in this module."
                        ),
                        file=self.filename,
                        line=test_line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Either declare '{mock_target}' as a "
                            f"nerve in this module, add it to "
                            f"`uses: [...]` so it resolves cross-"
                            f"module, or remove it from the test's "
                            f"`mocks:` list."
                        ),
                        context={
                            "test": test.name,
                            "mock_target": mock_target,
                        },
                    ))
                    continue

                if severity is None:
                    # Severity disabled in this mode — the
                    # DOES_NOT_EXIST check above still runs (it
                    # uses fixed-severity "error"), but the
                    # dict-key cross-check is silent.
                    continue

                if not local_target.provides:
                    # Target has no public surface to mock against;
                    # nothing to compare. Skip.
                    continue

                # Find a mock-shape assignment matching the target
                # by lowercased-convention name.
                literal = _match_mock_assignment(
                    mock_target, assignments,
                )
                if literal is None:
                    # No detectable mock dict — be conservative.
                    continue

                target_keys = set(local_target.provides)
                mock_keys = literal.keys
                missing = sorted(target_keys - mock_keys)
                extra = sorted(mock_keys - target_keys)
                if not missing and not extra:
                    continue

                diff_parts: list[str] = []
                if missing:
                    diff_parts.append(
                        f"missing keys: {', '.join(missing)}"
                    )
                if extra:
                    diff_parts.append(
                        f"unexpected keys: {', '.join(extra)}"
                    )
                diff_text = "; ".join(diff_parts)
                errors.append(S0maSemanticError(
                    code="MOCK_KEY_MISMATCH",
                    message=(
                        f"Test '{test.name}' mocks nerve "
                        f"'{mock_target}' via "
                        f"'{literal.assigned_name} = {{...}}', but the "
                        f"mock dict's keys do not match the target's "
                        f"`provides:` set: {diff_text}."
                    ),
                    file=self.filename,
                    line=test_line,
                    column=0,
                    severity=severity,
                    remediation=(
                        f"Align the mock dict's keys with "
                        f"'{mock_target}'.provides: "
                        f"{sorted(target_keys)}; or remove "
                        f"'{mock_target}' from the test's `mocks:` "
                        f"list if the mock intentionally covers a "
                        f"different surface."
                    ),
                    context={
                        "test": test.name,
                        "mock_target": mock_target,
                        "mock_assigned_name": literal.assigned_name,
                        "target_provides": sorted(target_keys),
                        "mock_keys": sorted(mock_keys),
                        "missing_keys": missing,
                        "extra_keys": extra,
                    },
                ))

        return errors

    # -------------------------------------------------------------------
    # 13 — POST-3c: provides: ↔ return-dict literal-key strict-mode pass
    # -------------------------------------------------------------------

    def _check_provides_key_mismatch(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Generalised ``provides:`` ↔ ``return {...}`` literal-key check.

        POST-3c (0.15.0): when a nerve declares ``provides:`` (flat or
        structured) AND its body's terminal ``return {...}`` literal
        carries literal-string keys, the literal keys must equal the
        ``provides:`` set. Both directions matter:

        - A ``provides:`` name absent from the return dict signals a
          missing implementation — for the structured form M-4's
          ``MISSING_RETURN_KEY`` already covers this exact case, so
          we skip ``missing`` keys when the structured form is in
          use to avoid duplicate diagnostics.
        - A return-dict key absent from ``provides:`` signals a typo
          (``"asemble"`` instead of ``"assemble"``) or a stray
          undeclared key. This is the typo class that the structured
          form's M-4 check does *not* catch; POST-3c surfaces it.

        Severity: warning in migration/dev, error in strict/release
        (per :data:`PROVIDES_KEY_MISMATCH`'s severity matrix entry).
        Bodies without a literal ``return {...}`` (computed via
        ``dict(...)`` or a comprehension) are intentionally skipped
        — false positives on legitimate dynamic returns would erode
        author trust in the check.
        """
        errors: list[S0maSemanticError] = []

        severity = get_severity("PROVIDES_KEY_MISMATCH", self.mode)
        if severity is None:
            return errors

        for nerve in module.nerves:
            if not nerve.provides:
                continue
            if not nerve.body:
                continue
            return_keys = _extract_return_dict_keys(nerve.body)
            if return_keys is None:
                # No literal ``return {...}`` — class-bodied SERVICE
                # pattern, computed returns, or generator bodies. The
                # POST-3c check intentionally does not fire on
                # non-literal returns; document the limitation in the
                # spec rather than guess at the author's intent.
                continue

            provides_set = set(nerve.provides)
            structured = any(
                entry.has_triple for entry in nerve.provides_entries
            )

            # ``missing`` is what ``MISSING_RETURN_KEY`` (M-4 structured
            # form) already covers; skip it for structured nerves to
            # avoid duplicate diagnostics on the same author error.
            missing = sorted(provides_set - return_keys) if not structured else []
            extra = sorted(return_keys - provides_set)

            if not missing and not extra:
                continue

            line = nerve.location.start_line if nerve.location else 0
            diff_parts: list[str] = []
            if missing:
                diff_parts.append(
                    f"missing keys: {', '.join(missing)}"
                )
            if extra:
                diff_parts.append(
                    f"unexpected keys: {', '.join(extra)}"
                )
            diff_text = "; ".join(diff_parts)
            # M1 (0.13.0, batch-01c): hand the corrected declaration over.
            # The body's literal return keys ARE the actual public surface,
            # so a flat `provides:` block matching them clears the mismatch
            # by construction. The structured form (a per-method
            # returns/expects/guarantees triple) is the ambiguity guard:
            # aligning provides to a new key would need a contract triple
            # the checker cannot synthesise, so it explains rather than
            # fabricates a verbatim block (spec (e)).
            if structured:
                suggested = None
                remediation = (
                    f"Align the return dict's keys with "
                    f"`provides:` ({sorted(provides_set)}); or "
                    f"update `provides:` to reflect the actual "
                    f"public surface. This nerve uses the structured "
                    f"`provides:` form, so the checker does not emit a "
                    f"verbatim corrected block — a newly-declared key "
                    f"would need a returns/expects/guarantees triple it "
                    f"cannot infer. The check fires on literal-"
                    f"string keys only — computed returns are "
                    f"silently skipped."
                )
            else:
                suggested = render_provides_block(sorted(return_keys))
                remediation = (
                    f"Update `provides:` to match the body's actual "
                    f"return keys (the suggested block below); or "
                    f"change the return dict to match `provides:` "
                    f"({sorted(provides_set)}). The check fires on "
                    f"literal-string keys only — computed returns are "
                    f"silently skipped."
                )
            errors.append(S0maSemanticError(
                code="PROVIDES_KEY_MISMATCH",
                message=(
                    f"Nerve '{nerve.name}' declares "
                    f"`provides: [{', '.join(nerve.provides)}]` but "
                    f"its body's `return {{...}}` literal-string keys "
                    f"do not match: {diff_text}."
                ),
                file=self.filename,
                line=line,
                column=0,
                severity=severity,
                remediation=remediation,
                context={
                    "nerve": nerve.name,
                    "declared_provides": list(nerve.provides),
                    "return_keys": sorted(return_keys),
                    "missing_keys": missing,
                    "extra_keys": extra,
                },
                suggested_declaration=suggested,
            ))

        return errors

    # -------------------------------------------------------------------
    # POST-4c (0.15.0) — exports_helpers: must resolve to actual helpers
    # -------------------------------------------------------------------

    def _check_exports_helpers_resolve(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """POST-4c: every ``exports_helpers:`` entry must name a helper.

        The ``exports_helpers:`` field widens cross-module reachability
        for the named helpers (still gated by the M13 test-context
        access-control rule on the consumer side). If an entry doesn't
        resolve to an actual ``helper`` declaration in this module, the
        re-export surface is mis-configured — there is no helper to
        reach, so the consumer side will fail with a confusing
        ``DOES_NOT_EXIST``. Surfacing the mis-configuration on the
        producer side gives the author a precise pointer at the
        offending line.

        Severity: error in every mode. ``exports_helpers:`` is a
        deliberate publication act; a typo silently no-ops without
        this check.
        """
        errors: list[S0maSemanticError] = []

        exports_helpers = module.module.exports_helpers
        if not exports_helpers:
            return errors

        helper_names = {h.name for h in module.helpers}
        line = (
            module.module.location.start_line
            if module.module.location is not None
            else 1
        )

        for entry in exports_helpers:
            if entry in helper_names:
                continue
            errors.append(S0maSemanticError(
                code="EXPORTED_HELPER_NOT_FOUND",
                message=(
                    f"Module '{module.module.name}' lists "
                    f"'{entry}' in `exports_helpers:`, but no "
                    f"`helper {entry} :: <layer>` declaration "
                    f"exists in this module."
                ),
                file=self.filename,
                line=line,
                column=0,
                severity="error",
                remediation=(
                    f"Either (a) add a `helper {entry} :: <layer>` "
                    f"declaration to this module, (b) remove "
                    f"'{entry}' from the `exports_helpers:` list, or "
                    f"(c) correct a typo in the helper name. "
                    f"`exports_helpers:` only widens reachability for "
                    f"helpers declared in *this* module — names from "
                    f"other modules cannot be re-exported."
                ),
                context={
                    "module": module.module.name,
                    "missing_helper": entry,
                    "available_helpers": sorted(helper_names),
                },
            ))

        return errors

    # -------------------------------------------------------------------
    # POST-5 (0.16.0) — integration declaration cross-checks
    # -------------------------------------------------------------------

    def _check_integrations(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate every integration declaration in the module (POST-5).

        Each integration is checked against four invariants:

        1. ``layer == INFRASTRUCTURE``. External-system adapters are by
           definition an infrastructure concern; a non-INFRASTRUCTURE
           layer would let an APPLICATION or DOMAIN-layered "integration"
           skirt the cross-layer guardrails. Surfaces ``LAYER_MISMATCH``.
        2. The ``factory:`` field names a nerve declared in this module.
           Surfaces ``INTEGRATION_FACTORY_NOT_FOUND``.
        3. The named factory is ``kind: SERVICE``. The auto-emitted
           ``get_factory()`` wraps the factory call expecting a dict
           return shape — pointing at a FUNCTION / ADAPTER / etc. nerve
           breaks that contract. Surfaces
           ``INTEGRATION_FACTORY_NOT_SERVICE``.
        4. The ``smoke_test_primary:`` field names either a nerve in
           this module or a reachable ``uses:`` entry. Surfaces
           ``INTEGRATION_SMOKE_TEST_NOT_FOUND``.

        A fifth, lighter check validates the ``manifest:`` map's keys
        (Python identifiers) and values (JSON-serialisable primitives)
        via ``INTEGRATION_INVALID_MANIFEST_KEY`` — basic shape only; no
        semantic interpretation of ``required_env`` etc.
        """
        errors: list[S0maSemanticError] = []
        if not module.integrations:
            return errors

        # Lookup tables for the cross-check.
        nerve_by_name: dict[str, NerveDecl] = {n.name: n for n in module.nerves}
        uses_targets: set[str] = set()
        for u in module.module.uses:
            qn = u.qualified_name
            # The local name is the last segment of ``module.name``.
            if "." in qn:
                uses_targets.add(qn.rsplit(".", 1)[-1])
            else:
                uses_targets.add(qn)

        ident_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

        for integ in module.integrations:
            line = integ.location.start_line if integ.location else 0

            # 1. Layer must be INFRASTRUCTURE.
            if integ.layer != Layer.INFRASTRUCTURE:
                errors.append(S0maSemanticError(
                    code="LAYER_MISMATCH",
                    message=(
                        f"integration '{integ.name}' is declared "
                        f"with layer {integ.layer.value}, but "
                        f"integration declarations must be "
                        f"INFRASTRUCTURE-layered."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        f"Change the header to "
                        f"'integration {integ.name} :: INFRASTRUCTURE'. "
                        f"External-system adapters are an "
                        f"infrastructure concern by definition."
                    ),
                    context={
                        "declaration": integ.name,
                        "declared_layer": integ.layer.value,
                        "expected_layer": "INFRASTRUCTURE",
                    },
                ))

            # 2 + 3. Factory cross-check.
            factory_nerve = nerve_by_name.get(integ.factory)
            if factory_nerve is None:
                errors.append(S0maSemanticError(
                    code="INTEGRATION_FACTORY_NOT_FOUND",
                    message=(
                        f"integration '{integ.name}' names "
                        f"'{integ.factory}' as its factory, but no "
                        f"nerve with that name exists in module "
                        f"'{module.module.name}'."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        f"Either (a) declare a SERVICE nerve named "
                        f"'{integ.factory}' in this module, or (b) "
                        f"correct the factory name on the integration "
                        f"declaration to point at an existing SERVICE "
                        f"nerve."
                    ),
                    context={
                        "integration": integ.name,
                        "missing_factory": integ.factory,
                        "available_nerves": sorted(nerve_by_name.keys()),
                    },
                ))
            else:
                if factory_nerve.kind != Kind.SERVICE:
                    errors.append(S0maSemanticError(
                        code="INTEGRATION_FACTORY_NOT_SERVICE",
                        message=(
                            f"integration '{integ.name}' names "
                            f"'{integ.factory}' as its factory, but "
                            f"that nerve has kind "
                            f"'{factory_nerve.kind.value}'. The "
                            f"factory nerve of an integration must be "
                            f"`kind: SERVICE` (the auto-emitted "
                            f"`get_factory()` helper expects a "
                            f"SERVICE return shape)."
                        ),
                        file=self.filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Either (a) change '{integ.factory}' to "
                            f"`kind: SERVICE`, or (b) point the "
                            f"integration's `factory:` field at a "
                            f"different nerve that already has "
                            f"`kind: SERVICE`."
                        ),
                        context={
                            "integration": integ.name,
                            "factory": integ.factory,
                            "actual_kind": factory_nerve.kind.value,
                            "expected_kind": "SERVICE",
                        },
                    ))

            # 4. Smoke-test primary cross-check. Accept a same-module
            # nerve OR a name that appears in the module's ``uses:``
            # list (cross-module factories are sometimes the canonical
            # smoke-test target — they're already validated by the
            # cross-module resolver).
            if (
                integ.smoke_test_primary not in nerve_by_name
                and integ.smoke_test_primary not in uses_targets
            ):
                errors.append(S0maSemanticError(
                    code="INTEGRATION_SMOKE_TEST_NOT_FOUND",
                    message=(
                        f"integration '{integ.name}' names "
                        f"'{integ.smoke_test_primary}' as its "
                        f"smoke_test_primary, but no nerve or "
                        f"`uses:` entry with that name resolves in "
                        f"module '{module.module.name}'."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        f"Either (a) declare a nerve named "
                        f"'{integ.smoke_test_primary}' in this "
                        f"module, (b) import it via `uses:` from a "
                        f"sibling module, or (c) correct the "
                        f"`smoke_test_primary:` field to point at an "
                        f"existing target."
                    ),
                    context={
                        "integration": integ.name,
                        "missing_target": integ.smoke_test_primary,
                        "available_nerves": sorted(nerve_by_name.keys()),
                    },
                ))

            # 5. Manifest shape — basic validation only.
            for key, value in integ.manifest.items():
                if not ident_re.match(key):
                    errors.append(S0maSemanticError(
                        code="INTEGRATION_INVALID_MANIFEST_KEY",
                        message=(
                            f"integration '{integ.name}': manifest "
                            f"key {key!r} is not a valid Python "
                            f"identifier."
                        ),
                        file=self.filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            "Rename the manifest key to a Python "
                            "identifier (letters, digits, "
                            "underscores; must not start with a "
                            "digit)."
                        ),
                        context={
                            "integration": integ.name,
                            "invalid_key": key,
                        },
                    ))
                if not _is_jsonable(value):
                    errors.append(S0maSemanticError(
                        code="INTEGRATION_INVALID_MANIFEST_KEY",
                        message=(
                            f"integration '{integ.name}': manifest "
                            f"key '{key}' carries a value of type "
                            f"{type(value).__name__} which is not "
                            f"JSON-serialisable."
                        ),
                        file=self.filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            "Manifest values must be one of: str, "
                            "int, float, bool, list, dict, or None. "
                            "Convert the value to one of these types."
                        ),
                        context={
                            "integration": integ.name,
                            "invalid_value_key": key,
                            "value_type": type(value).__name__,
                        },
                    ))

        return errors

    # -------------------------------------------------------------------
    # M-12 (POST-8, 0.16.0) — forward-compat grammar pass
    # -------------------------------------------------------------------

    def _check_python_grammar_compat(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Flag Python 3.12-only grammar when ``requires-python`` admits 3.11.

        M-12 (POST-8, 0.16.0). When the project's
        ``[project].requires-python`` range explicitly admits 3.11
        (the conservative trigger: every clause must be satisfied
        by 3.11), walk every nerve / cell / ganglion / test body and
        flag the three known 3.12-only construct families:

        1. **PEP 701 nested-quote f-strings** —
           ``f"outer {f"inner"}"`` (same-quote nesting). Detected
           via a text-level scan because the AST does not preserve
           quote-style.
        2. **Walrus operator inside a comprehension** —
           ``[(y := x) for x in xs]``. 3.10 / 3.11 tightened the
           rules; 3.12 reopened them. Detected via the AST walk in
           ``s0ma_dsl.semantic.python_compat._scan_ast``.
        3. **PEP 695 type-parameter / type-alias syntax** —
           ``def foo[T](x: T) -> T: ...``, ``class Foo[T]: ...``,
           ``type Vector = list[T]``. Detected via the ``type_params``
           slot on FunctionDef / AsyncFunctionDef / ClassDef and the
           ``ast.TypeAlias`` node.

        The pass stays silent when:

        * The validator was constructed without
          ``requires_python`` (the default — most call sites do not
          forward the project's range, and synthetic projects have
          no declared floor).
        * ``requires_python`` is ``None`` (no
          ``[project].requires-python`` declared).
        * Every clause excludes 3.11 (e.g. ``>=3.12``,
          ``>=3.13``) — the project has opted in to the newer
          grammar and a 3.11 portability check would be noise.

        Body sources that cannot be parsed by ``ast.parse`` fall
        back gracefully: the text-based nested-quote scan still
        runs (it never raises), and the AST walk silently returns
        no findings. The outer ``PARSE_ERROR`` pass owns the
        syntax-error diagnostic; this pass intentionally never
        emits ``PARSE_GRAMMAR_FORWARD_INCOMPAT`` for a body that
        already produces ``PARSE_ERROR``.
        """
        # Local import to keep the top-of-module imports stable; the
        # python_compat module is purely a detection helper.
        from s0ma_dsl.semantic.python_compat import (
            Python312OnlyFinding,
            flag_python_312_only,
            requires_python_includes_311,
        )

        errors: list[S0maSemanticError] = []
        if not requires_python_includes_311(self.requires_python):
            return errors

        # Walk every declaration that carries an authored body. Helpers
        # are out of scope: they are emitted verbatim as module-level
        # defs / classes and the same grammar would fail at import
        # whether they live in a helper or a nerve, but the M-12
        # decision is to focus on the four canonical body-bearing
        # declaration kinds (nerve / cell / ganglion / test). Cells
        # supplying their body via ``content: @file()`` are exempt
        # by construction — the embedded content is verbatim text
        # the codegen writes to a string literal, not Python source
        # for ``ast.parse``.
        body_targets: list[tuple[str, str, str, SourceLocation | None]] = []
        for nerve in module.nerves:
            if nerve.body:
                body_targets.append(("nerve", nerve.name, nerve.body, nerve.location))
        for cell in module.cells:
            # Skip ``content: @file()`` cells — the embedded content
            # is not authored Python; the codegen synthesises the
            # assignment.
            if cell.embedded_file_path is not None:
                continue
            if cell.body:
                body_targets.append(("cell", cell.name, cell.body, cell.location))
        for ganglion in module.ganglia:
            if ganglion.body:
                body_targets.append((
                    "ganglion", ganglion.name, ganglion.body, ganglion.location,
                ))
        for test in module.tests:
            if test.body:
                body_targets.append(("test", test.name, test.body, test.location))

        for kind, name, body, location in body_targets:
            findings: list[Python312OnlyFinding] = flag_python_312_only(body)
            if not findings:
                continue
            base_line = (
                location.start_line if location is not None else 0
            )
            for finding in findings:
                # Compute the canonical line number. Body line is
                # 1-based; the declaration's location.start_line is
                # the header line, so the body's line numbers are
                # offset from there. We approximate by adding the
                # finding line minus 1; tests assert on the
                # declaration-relative line so callers can pin
                # locations even when the exact offset shifts with
                # parser-internal formatting.
                line = base_line + max(0, finding.line - 1)
                errors.append(S0maSemanticError(
                    code="PARSE_GRAMMAR_FORWARD_INCOMPAT",
                    message=(
                        f"{kind} '{name}' body contains a Python "
                        f"3.12-only grammar construct: "
                        f"{finding.description} The project's "
                        f"[project].requires-python admits Python 3.11; "
                        f"this body would compile on 3.12 but raise "
                        f"SyntaxError at import on 3.11."
                    ),
                    file=self.filename,
                    line=line,
                    column=finding.column,
                    severity="error",
                    remediation=(
                        "Either (a) rewrite the body using grammar "
                        "available in Python 3.11 (e.g. nested "
                        "f-strings with mismatched quotes, walrus "
                        "assignment outside the comprehension, or "
                        "`TypeVar` from `typing` instead of PEP 695 "
                        "`[T]` syntax), or (b) tighten "
                        "`[project].requires-python` to `>=3.12` to "
                        "declare the 3.12 floor explicitly."
                    ),
                    context={
                        "declaration_kind": kind,
                        "declaration_name": name,
                        "construct_kind": finding.kind,
                        "body_line": finding.line,
                        "body_column": finding.column,
                    },
                ))

        return errors


    # -------------------------------------------------------------------
    # POST-10g — uuid.uuid4 colon-override hint
    # -------------------------------------------------------------------

    def _check_uuid_pattern_hint(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Emit an info-level hint when a ``requires:`` entry like
        ``uuid.uuid4`` shadows a lowercase-callable shape that the
        ``from-import`` heuristic does not pick up.

        Background: the parser's ``_build_requires`` heuristic decides
        whether a dotted ``requires:`` entry is a from-import by
        inspecting the last segment's first character — UPPER_CASE
        last segments (``uuid.UUID``) become ``from uuid import UUID``;
        lowercase last segments (``uuid.uuid4``) fall through and
        emit a plain ``import uuid.uuid4``, which (a) does not bind
        the ``uuid4`` name in the module's namespace, and (b) makes
        the local name ``uuid`` (the first segment). A body that
        calls bare ``uuid4()`` therefore looks vestigial to the
        Phase 4 detector, and the import name ``uuid`` is not
        actually consumed.

        The colon-override form ``requires: [uuid:uuid4]`` is the
        explicit, deterministic shape the author wants here: the
        parser unambiguously emits ``from uuid import uuid4`` and
        binds the lowercase callable. This validator pass identifies
        the heuristic-confused pattern and emits a soft hint at the
        ``requires:`` declaration line so the author has the fix in
        hand rather than chasing the resulting ``VESTIGIAL_IMPORT``
        and ``NameError`` ladder. Severity: warning in every mode —
        the existing code path keeps working (or fails loudly with
        a separate diagnostic); this is a steering hint.

        Trigger conditions (all must hold for the hint to fire on
        an entry):

        1. The ``requires:`` entry has a dotted ``module_path``
           (i.e. ``"uuid.uuid4"``, not ``"uuid"``).
        2. The entry is NOT a from-import (the heuristic missed it).
        3. The entry was not authored in colon-override form (the
           author already chose ``uuid:uuid4``).
        4. The last segment starts with a lowercase letter (the
           heuristic's trigger).
        5. At least one authored body in the module references the
           lowercase last segment as a bare identifier.

        Returns the list of synthesized ``REQUIRES_DOTTED_LOWERCASE_HINT``
        warnings.
        """
        errors: list[S0maSemanticError] = []

        # Collect every dotted requires entry the heuristic might have
        # mis-classified. ``soft_requires``, ``runtime_only_requires``,
        # and ``deferred_requires`` (DSL-M2) participate in the same
        # heuristic so we scan all four.
        candidates: list[tuple[str, str, str, SourceLocation | None]] = []
        sources = (
            ("requires", module.module.requires),
            ("soft_requires", module.module.soft_requires),
            ("runtime_only_requires", module.module.runtime_only_requires),
            ("deferred_requires", module.module.deferred_requires),
        )
        for source, entries in sources:
            for entry in entries:
                path = entry.module_path
                if "." not in path:
                    continue
                if entry.is_from_import:
                    continue
                # Authored colon-override (``uuid:uuid4``) is captured
                # on the entry as ``is_from_import=True`` per the
                # parser's ``colon_form`` branch — so reaching here
                # implies the author wrote ``uuid.uuid4`` (dot form).
                last = path.rsplit(".", 1)[-1]
                if not last or not last[0].islower():
                    continue
                candidates.append((source, path, last, entry.location))

        if not candidates:
            return errors

        # Build the set of bare identifiers found across every authored
        # body in the module. We only need the names — we are not
        # tracking declaration-level context (a hint fires once per
        # mis-classified requires entry, not once per body).
        body_identifiers: set[str] = set()
        body_sources = []
        for nerve in module.nerves:
            if nerve.body:
                body_sources.append(nerve.body)
        for cell in module.cells:
            if cell.body and cell.embedded_file_path is None:
                body_sources.append(cell.body)
        for ganglion in module.ganglia:
            if ganglion.body:
                body_sources.append(ganglion.body)
        for test in module.tests:
            if test.body:
                body_sources.append(test.body)
        for helper in module.helpers:
            if helper.body:
                body_sources.append(helper.body)

        for body in body_sources:
            try:
                tree = ast.parse(body)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    body_identifiers.add(node.id)
                elif isinstance(node, ast.Attribute):
                    # Capture the leftmost identifier in
                    # ``module.attr.attr`` chains so dotted references
                    # don't escape detection.
                    cur: ast.expr = node
                    while isinstance(cur, ast.Attribute):
                        cur = cur.value
                    if isinstance(cur, ast.Name):
                        body_identifiers.add(cur.id)

        # Emit one hint per heuristic-confused entry whose lowercase
        # last segment shows up bare in a body.
        for source, path, last_segment, location in candidates:
            if last_segment not in body_identifiers:
                continue
            line = (
                location.start_line if location is not None else 0
            )
            colon_form = path.replace(".", ":", 1)
            errors.append(S0maSemanticError(
                code="REQUIRES_DOTTED_LOWERCASE_HINT",
                message=(
                    f"`{source}: [{path}]` looks like a from-import but "
                    f"its last segment '{last_segment}' is lowercase, so "
                    f"the parser's UPPER_CASE heuristic treats it as a "
                    f"plain `import {path}` (binding only `{path.split('.')[0]}` "
                    f"in the namespace). The body references `{last_segment}` "
                    f"as a bare identifier, which suggests the intended "
                    f"shape is `from {path.rsplit('.', 1)[0]} import "
                    f"{last_segment}`."
                ),
                file=self.filename,
                line=line,
                column=0,
                severity="warning",
                remediation=(
                    f"Replace the dotted form with the explicit "
                    f"colon-override `{colon_form}` so the parser emits "
                    f"`from {path.rsplit('.', 1)[0]} import "
                    f"{last_segment}` deterministically (and the "
                    f"vestigial-import / NameError ladder disappears)."
                ),
                context={
                    "module": module.module.name,
                    "source": source,
                    "requires_entry": path,
                    "colon_form": colon_form,
                    "lowercase_last_segment": last_segment,
                },
            ))

        return errors

    # -------------------------------------------------------------------
    # POST-10h — Mutable-default lint
    # -------------------------------------------------------------------

    def _check_mutable_dataclass_default(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Flag ``dataclasses.field(default=[...])`` / ``default={...}`` calls.

        POST-10h (0.16.0): supplying a mutable collection literal as the
        ``default=`` argument to ``dataclasses.field`` is the canonical
        shared-mutable-default bug. Python evaluates ``default`` once at
        class-body time, so every instance ends up sharing the same
        list/dict/set object — mutating one mutates them all. The
        correct shape is ``default_factory=list`` (or ``=dict`` /
        ``=set``) so each instance gets a fresh collection.

        The check walks every authored body (nerves, cells, ganglia,
        tests, helpers) and looks for ``ast.Call`` nodes whose function
        is ``field`` or ``dataclasses.field`` (qualified or aliased) and
        whose ``default=`` keyword argument is a ``List``, ``Dict``, or
        ``Set`` literal. Severity ladders with mode: warning in
        migration/dev so authors see the finding while iterating, error
        in strict and release where shipping a known-buggy default is
        unacceptable. Body locations carry no per-line offsets at this
        layer, so the diagnostic references the declaration's start
        line.
        """
        errors: list[S0maSemanticError] = []
        severity = get_severity("MUTABLE_DEFAULT", self.mode)
        if severity is None:
            return errors

        # (label, body, location_line) tuples for every authored body
        # in the module. The label is the declaration's name for the
        # diagnostic context.
        body_sources: list[tuple[str, str, str, int]] = []
        for nerve in module.nerves:
            if nerve.body:
                line = nerve.location.start_line if nerve.location else 0
                body_sources.append(("nerve", nerve.name, nerve.body, line))
        for cell in module.cells:
            if cell.body and cell.embedded_file_path is None:
                line = cell.location.start_line if cell.location else 0
                body_sources.append(("cell", cell.name, cell.body, line))
        for ganglion in module.ganglia:
            if ganglion.body:
                line = ganglion.location.start_line if ganglion.location else 0
                body_sources.append(("ganglion", ganglion.name, ganglion.body, line))
        for test in module.tests:
            if test.body:
                line = test.location.start_line if test.location else 0
                body_sources.append(("test", test.name, test.body, line))
        for helper in module.helpers:
            if helper.body:
                line = helper.location.start_line if helper.location else 0
                body_sources.append(("helper", helper.name, helper.body, line))

        for kind, decl_name, body, decl_line in body_sources:
            try:
                tree = ast.parse(body)
            except SyntaxError:
                # A separate pass surfaces body syntax errors; skip the
                # mutable-default check rather than double-reporting.
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not _is_dataclasses_field_call(node.func):
                    continue
                for kw in node.keywords:
                    if kw.arg != "default":
                        continue
                    literal = _classify_mutable_literal(kw.value)
                    if literal is None:
                        continue
                    errors.append(S0maSemanticError(
                        code="MUTABLE_DEFAULT",
                        message=(
                            f"`dataclasses.field(default={literal}(...))` in "
                            f"{kind} '{decl_name}' supplies a mutable "
                            f"{literal} literal as the default value. Python "
                            f"shares the same {literal} across every instance "
                            f"of the dataclass, so mutations in one instance "
                            f"leak into all others (the classic "
                            f"shared-mutable-default bug)."
                        ),
                        file=self.filename,
                        line=decl_line,
                        column=0,
                        severity=severity,
                        remediation=(
                            f"Replace `default={literal}(...)` with "
                            f"`default_factory={literal}` so each instance "
                            f"gets a fresh collection. For non-empty defaults, "
                            f"use a `lambda: [...]` / `lambda: {{...}}` factory."
                        ),
                        context={
                            "module": module.module.name,
                            "declaration_kind": kind,
                            "declaration_name": decl_name,
                            "literal_kind": literal,
                        },
                    ))
        return errors

    # -------------------------------------------------------------------
    # POST-10i — Duplicate inner-function lint
    # -------------------------------------------------------------------

    def _check_duplicate_inner_function(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Flag two ``def`` declarations with the same name in one outer scope.

        POST-10i (0.16.0): inside one enclosing function scope (most
        commonly a SERVICE nerve factory body where the author meant
        the second ``def`` to be a sibling but accidentally re-typed
        the first name), Python silently accepts the second
        definition and the second binding shadows the first.
        Downstream this manifests as the factory's returned dict
        being keyed to a function the author did not intend.

        The detector walks every authored body and, for each
        ``ast.FunctionDef`` / ``ast.AsyncFunctionDef`` node, scans its
        direct ``ast.FunctionDef`` / ``ast.AsyncFunctionDef`` children
        for name collisions. Class bodies and methods inside classes
        are intentionally excluded: Python allows ``def foo`` once per
        method-name in a class body, and the parallel collision
        detector for nerves is ``CLASS_BODY_IN_NERVE``. Always an
        error in every strictness mode — this is a structural authoring
        bug, not a strictness preference.
        """
        errors: list[S0maSemanticError] = []

        body_sources: list[tuple[str, str, str, int]] = []
        for nerve in module.nerves:
            if nerve.body:
                line = nerve.location.start_line if nerve.location else 0
                body_sources.append(("nerve", nerve.name, nerve.body, line))
        for cell in module.cells:
            if cell.body and cell.embedded_file_path is None:
                line = cell.location.start_line if cell.location else 0
                body_sources.append(("cell", cell.name, cell.body, line))
        for ganglion in module.ganglia:
            if ganglion.body:
                line = ganglion.location.start_line if ganglion.location else 0
                body_sources.append(("ganglion", ganglion.name, ganglion.body, line))
        for test in module.tests:
            if test.body:
                line = test.location.start_line if test.location else 0
                body_sources.append(("test", test.name, test.body, line))
        for helper in module.helpers:
            if helper.body:
                line = helper.location.start_line if helper.location else 0
                body_sources.append(("helper", helper.name, helper.body, line))

        for kind, decl_name, body, decl_line in body_sources:
            try:
                tree = ast.parse(body)
            except SyntaxError:
                continue
            # For each outer function scope, scan the direct children
            # for duplicate ``def`` / ``async def`` names. The outer
            # scope itself may be a module-level FunctionDef OR a
            # nested FunctionDef inside another function.
            for outer in ast.walk(tree):
                if not isinstance(outer, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                seen: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
                for child in outer.body:
                    if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    first = seen.get(child.name)
                    if first is None:
                        seen[child.name] = child
                        continue
                    # Duplicate inside this scope — emit the diagnostic
                    # once per duplicate (not once per first definition).
                    errors.append(S0maSemanticError(
                        code="DUPLICATE_INNER_FUNCTION",
                        message=(
                            f"In {kind} '{decl_name}', function "
                            f"'{outer.name}' contains two inner "
                            f"definitions named '{child.name}' (first at "
                            f"body-line {first.lineno}, second at body-line "
                            f"{child.lineno}). Python shadows the first "
                            f"binding with the second; the surface the "
                            f"outer function returns ends up referring to "
                            f"the second definition only."
                        ),
                        file=self.filename,
                        line=decl_line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Rename one of the two inner '{child.name}' "
                            f"definitions inside '{outer.name}' so each "
                            f"sibling binding has a distinct name. If the "
                            f"second definition was meant to replace the "
                            f"first, delete the first one explicitly."
                        ),
                        context={
                            "module": module.module.name,
                            "declaration_kind": kind,
                            "declaration_name": decl_name,
                            "outer_function": outer.name,
                            "duplicate_name": child.name,
                            "first_body_line": first.lineno,
                            "second_body_line": child.lineno,
                        },
                    ))
        return errors

    # -------------------------------------------------------------------
    # POST-10k — Cross-module ``uses:`` symmetry lint
    # -------------------------------------------------------------------

    def _check_cross_module_uses_asymmetry(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Flag two or more siblings from the same parent module where
        only a subset is referenced in the bodies.

        POST-10k (0.16.0): when ``uses: [other.A, other.B]`` declares
        two entries from the same parent module ``other`` but the
        module's bodies only reference ``A``, the author probably
        over-imported (perhaps copy-pasted the symmetric pair from a
        sibling module) and the unused entry should be trimmed.
        Narrower than ``VESTIGIAL_IMPORT``: only fires when ≥2 siblings
        from the same parent module are declared together. Severity
        ladders with mode: warning in migration/dev so authors see the
        finding while iterating, error in strict and release where
        the silent-symmetry-asymmetry pattern signals real drift.
        """
        errors: list[S0maSemanticError] = []
        severity = get_severity("CROSS_MODULE_USES_ASYMMETRY", self.mode)
        if severity is None:
            return errors

        # Group uses-entries by parent module path. ``other.A`` and
        # ``other.B`` share parent ``other``; ``a.b.X`` and ``a.b.Y``
        # share parent ``a.b``. Bare ``uses: [singleton]`` entries
        # without a dot are skipped (no parent to share).
        groups: dict[str, list[tuple[str, str, SourceLocation | None]]] = {}
        for use in module.module.uses:
            qn = use.qualified_name
            if "." not in qn:
                continue
            parent, name = qn.rsplit(".", 1)
            local_name = use.alias or name
            groups.setdefault(parent, []).append((local_name, qn, use.location))

        # Only parent modules with ≥2 sibling entries participate.
        relevant_groups = {
            parent: entries
            for parent, entries in groups.items()
            if len(entries) >= 2
        }
        if not relevant_groups:
            return errors

        # Collect every bare identifier reference across every authored
        # body. The check fires when an entry's local_name is NOT in
        # ``body_identifiers`` but at least one of its siblings IS.
        body_identifiers: set[str] = set()
        body_sources: list[str] = []
        for nerve in module.nerves:
            if nerve.body:
                body_sources.append(nerve.body)
        for cell in module.cells:
            if cell.body and cell.embedded_file_path is None:
                body_sources.append(cell.body)
        for ganglion in module.ganglia:
            if ganglion.body:
                body_sources.append(ganglion.body)
        for test in module.tests:
            if test.body:
                body_sources.append(test.body)
        for helper in module.helpers:
            if helper.body:
                body_sources.append(helper.body)

        for body in body_sources:
            try:
                tree = ast.parse(body)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    body_identifiers.add(node.id)
                elif isinstance(node, ast.Attribute):
                    cur: ast.expr = node
                    while isinstance(cur, ast.Attribute):
                        cur = cur.value
                    if isinstance(cur, ast.Name):
                        body_identifiers.add(cur.id)

        # Emit one diagnostic per unreferenced sibling whose group has
        # at least one referenced sibling. If NO sibling is referenced,
        # the existing ``VESTIGIAL_IMPORT`` ladder handles the full
        # group — POST-10k's narrow purpose is the asymmetry case.
        for parent, entries in relevant_groups.items():
            referenced = [
                (local, qn, loc)
                for (local, qn, loc) in entries
                if local in body_identifiers
            ]
            unreferenced = [
                (local, qn, loc)
                for (local, qn, loc) in entries
                if local not in body_identifiers
            ]
            if not referenced or not unreferenced:
                continue
            for local, qn, loc in unreferenced:
                line = loc.start_line if loc is not None else 0
                referenced_names = sorted(r[0] for r in referenced)
                errors.append(S0maSemanticError(
                    code="CROSS_MODULE_USES_ASYMMETRY",
                    message=(
                        f"`uses:` imports '{qn}' from parent module "
                        f"'{parent}' alongside referenced sibling(s) "
                        f"{referenced_names}, but no body in this module "
                        f"references '{local}'. The asymmetry suggests the "
                        f"entry was over-imported (perhaps copy-pasted "
                        f"alongside the referenced sibling) and can be "
                        f"trimmed."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity=severity,
                    remediation=(
                        f"Remove '{qn}' from `uses:` if the bodies do not "
                        f"intend to reference it. If the entry IS needed, "
                        f"ensure at least one body references '{local}' "
                        f"directly so the asymmetry resolves."
                    ),
                    context={
                        "module": module.module.name,
                        "parent_module": parent,
                        "unreferenced_entry": qn,
                        "unreferenced_local_name": local,
                        "referenced_siblings": referenced_names,
                    },
                ))
        return errors

    # -------------------------------------------------------------------
    # POST-12c — dataclass_invariants: syntax check
    # -------------------------------------------------------------------

    def _check_dataclass_invariants(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate that ``dataclass_invariants:`` entries are syntactically valid Python.

        POST-12c (0.16.0): each entry under a MODEL cell's
        ``dataclass_invariants:`` list is a Python boolean expression
        authored against the dataclass's fields. The invariants are
        *not* runtime-evaluated by s0ma — they are pure metadata for
        downstream introspection — but the validator runs each entry
        through ``ast.parse(expr, mode="eval")`` so syntactically
        malformed expressions are caught at check time rather than
        crashing a downstream consumer that *does* try to evaluate
        them. The motivating failure mode: an author writes
        ``"len(latency_samples <= 100"`` (missing close paren); the
        entry rides through the IR and emitted metadata uncaught, and
        a future contract-enforcing tool crashes opaquely. Severity
        is always ``error`` — see
        :data:`INVALID_DATACLASS_INVARIANT`.
        """
        errors: list[S0maSemanticError] = []
        for cell in module.cells:
            if not cell.dataclass_invariants:
                continue
            # The parser already rejects ``dataclass_invariants:`` on
            # non-MODEL cells, but defend defensively here too.
            if cell.kind != Kind.MODEL:
                continue
            line = cell.location.start_line if cell.location else 0
            for invariant in cell.dataclass_invariants:
                try:
                    ast.parse(invariant, mode="eval")
                except SyntaxError as exc:
                    errors.append(S0maSemanticError(
                        code="INVALID_DATACLASS_INVARIANT",
                        message=(
                            f"MODEL cell '{cell.name}' declares "
                            f"dataclass_invariant {invariant!r} which "
                            f"is not a syntactically valid Python "
                            f"expression: {exc.msg}."
                        ),
                        file=self.filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Edit the entry under cell '{cell.name}'s "
                            f"'dataclass_invariants:' list so the "
                            f"expression parses cleanly via "
                            f"`ast.parse(expr, mode=\"eval\")`. "
                            f"Invariants are descriptive metadata, "
                            f"not runtime-enforced, but the syntax "
                            f"check exists so the declared expression "
                            f"is always machine-readable."
                        ),
                        context={
                            "cell_name": cell.name,
                            "invariant": invariant,
                            "syntax_error": exc.msg,
                        },
                    ))
        return errors

    # -------------------------------------------------------------------
    # POST-12d — consumes_via_dict: contract + param resolution
    # -------------------------------------------------------------------

    def _check_consumes_via_dict(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Validate ``consumes_via_dict:`` entries on nerves.

        POST-12d (0.16.0): each entry declares a
        ``(contract, param)`` pair. ``contract`` must resolve to
        either a known cell in the current module or a ``uses:``
        target. ``param`` must be a parameter on the nerve body's
        outer function (closure-scoped params do not count). The
        validator fires :data:`CONSUMES_VIA_DICT_INVALID` when
        either side fails to resolve — same load-bearing-correctness
        precedent as ``INTERFACE_ON_NON_ABSTRACT`` (the named
        relationship must point at real entities, otherwise the
        declaration is meaningless).
        """
        errors: list[S0maSemanticError] = []

        # Build the set of resolvable contract names. Local cells are
        # named directly; ``uses:`` entries register the bare last
        # segment OR the alias if one was set.
        local_cell_names = {c.name for c in module.cells}
        uses_names: set[str] = set()
        for use in module.module.uses:
            qn = use.qualified_name
            local = use.alias or (
                qn.rsplit(".", 1)[-1] if "." in qn else qn
            )
            uses_names.add(local)
        resolvable_contracts = local_cell_names | uses_names

        for nerve in module.nerves:
            if not nerve.consumes_via_dict:
                continue
            # Resolve the body's outer-function parameters. The body
            # is the canonical (column-0) form; parse and look at the
            # first top-level ``FunctionDef`` / ``AsyncFunctionDef``.
            body_params: set[str] = set()
            if nerve.body:
                try:
                    tree = ast.parse(nerve.body)
                except SyntaxError:
                    tree = None
                if tree is not None:
                    for stmt in tree.body:
                        if isinstance(
                            stmt, (ast.FunctionDef, ast.AsyncFunctionDef),
                        ):
                            args = stmt.args
                            # Standard positional + keyword-only +
                            # varargs / kwargs all count.
                            for arg in (
                                list(args.posonlyargs)
                                + list(args.args)
                                + list(args.kwonlyargs)
                            ):
                                body_params.add(arg.arg)
                            if args.vararg is not None:
                                body_params.add(args.vararg.arg)
                            if args.kwarg is not None:
                                body_params.add(args.kwarg.arg)
                            break

            line = nerve.location.start_line if nerve.location else 0
            for entry in nerve.consumes_via_dict:
                contract = entry.contract
                param = entry.param
                contract_ok = contract in resolvable_contracts
                param_ok = param in body_params
                if contract_ok and param_ok:
                    continue
                reasons: list[str] = []
                if not contract_ok:
                    reasons.append(
                        f"contract {contract!r} is not a known cell "
                        f"in this module and is not listed in "
                        f"`uses:`"
                    )
                if not param_ok:
                    reasons.append(
                        f"param {param!r} is not a parameter on "
                        f"nerve '{nerve.name}''s outer function"
                    )
                joined = "; ".join(reasons)
                errors.append(S0maSemanticError(
                    code="CONSUMES_VIA_DICT_INVALID",
                    message=(
                        f"Nerve '{nerve.name}': consumes_via_dict "
                        f"entry (contract={contract!r}, "
                        f"param={param!r}) is invalid — {joined}."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity="error",
                    remediation=(
                        "Both `contract` and `param` must resolve. "
                        "For `contract`: declare it as a cell in "
                        "this module, or add it to `uses:` if it "
                        "lives in another module. For `param`: "
                        "ensure the nerve body's outer function "
                        "takes a parameter with the named identifier."
                    ),
                    context={
                        "nerve_name": nerve.name,
                        "contract": contract,
                        "param": param,
                        "contract_resolves": contract_ok,
                        "param_resolves": param_ok,
                    },
                ))
        return errors

    # -------------------------------------------------------------------
    # B1 (0.11.0, batch-01a) — subscripting a bare ``uses:`` module object
    # -------------------------------------------------------------------

    def _check_module_object_subscript(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Flag subscripting a bare ``uses:`` module object (``MODULE_SUBSCRIPT``).

        A bare ``uses: [registry]`` entry (no dot) emits ``import
        registry`` — the local name binds a *module object*, not a
        component. Nerve bodies are emitted verbatim
        (``parser/body_extractor``), so an author-written
        ``registry["get_op"]`` compiles cleanly and detonates at
        runtime as ``TypeError: 'module' object is not subscriptable``.
        This is the batch-01a factory-dict confusion (run
        ``P1_P_r02``): the author expects ``registry`` to be the dict a
        ``registry()`` nerve returns, but the bare ``uses:`` entry bound
        the *module*.

        The guard keys on bare-``uses:`` module-object resolution only —
        dotted ``uses: [mod.symbol]`` from-imports a component (not a
        module) and is never flagged, and a body-local rebind of the
        name (``registry = registry_factory()``) suppresses the finding
        so legitimate dict subscripts are never rejected (the
        "do NOT reject legitimate dict subscripts" contract).
        """
        # Bare uses entries (no dot in qualified_name) bind a whole
        # module object; dotted entries from-import a component. Only
        # the former can be the ``'module' object is not subscriptable``
        # hazard. The emitted binding for a bare entry is the module
        # name itself; an alias (rare for bare uses) is added defensively.
        module_object_names: set[str] = set()
        for use in module.module.uses:
            if "." not in use.qualified_name:
                module_object_names.add(use.qualified_name)
                if use.alias:
                    module_object_names.add(use.alias)
        if not module_object_names:
            return []

        errors: list[S0maSemanticError] = []
        for decl_name, body, decl_line in _authored_bodies(module):
            try:
                tree = ast.parse(body)
            except SyntaxError:
                continue
            # A name assigned anywhere in the body is a local rebind
            # (``registry = registry()``) — after it the name is a value,
            # not the module object, so its subscripts are legitimate.
            # This conservative, control-flow-insensitive over-
            # approximation favours false negatives over false positives.
            shadowed = _body_bound_names(tree)
            seen_here: set[tuple[str, int]] = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Subscript):
                    continue
                target = node.value
                if not isinstance(target, ast.Name):
                    continue
                name = target.id
                if name not in module_object_names or name in shadowed:
                    continue
                key = (name, node.lineno)
                if key in seen_here:
                    continue
                seen_here.add(key)
                errors.append(S0maSemanticError(
                    code="MODULE_SUBSCRIPT",
                    message=(
                        f"'{decl_name}' subscripts '{name}', but "
                        f"'{name}' is a bare `uses: [{name}]` module "
                        f"object, not a dict — `{name}[...]` raises "
                        f"`TypeError: 'module' object is not "
                        f"subscriptable` at runtime."
                    ),
                    file=self.filename,
                    line=decl_line,
                    column=0,
                    severity="error",
                    remediation=(
                        f"You are treating the module '{name}' as the "
                        f"value one of its nerves returns. Import the "
                        f"symbol itself: `uses: [{name}.<symbol>]` emits "
                        f"`from {name} import <symbol>`, then call it "
                        f"(e.g. `result = <symbol>(...)`). For a shared "
                        f"factory, declare a module-level `helper` in "
                        f"'{name}', list it under that module's "
                        f"`exports_helpers:`, and consume it via "
                        f"`uses: [{name}.<helper>]`."
                    ),
                    context={
                        "declaration": decl_name,
                        "module_object": name,
                        "body_line": node.lineno,
                    },
                ))
        return errors

    # -------------------------------------------------------------------
    # B3 (0.11.0, batch-01a) — module name shadows a Python stdlib module
    # -------------------------------------------------------------------

    def _check_module_shadows_stdlib(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Warn when a module's name shadows a stdlib module (``MODULE_SHADOWS_STDLIB``).

        A s0ma module named after a stdlib module (``io``, ``json``,
        ``csv`` …) cannot be reliably imported by its bare name: the
        stdlib module is already cached in ``sys.modules`` at
        interpreter start, so ``bootstrap_imports`` /
        ``importlib.import_module("io")`` returns the *stdlib* module
        and a consumer's ``from io import read_data`` raises
        ``ImportError``. This detonated batch-01a run ``P1_P_r02`` (a
        module named ``io`` forced the agent into a hand-written
        ``importlib`` shim). Severity ladders with mode
        (warning in migration/dev, error in strict/release): the
        project simply will not bootstrap, so it must not ship.
        """
        name = module.module.name
        if name not in _STDLIB_MODULE_NAMES:
            return []
        severity = get_severity("MODULE_SHADOWS_STDLIB", self.mode)
        if severity is None:
            return []
        line = (
            module.module.location.start_line
            if module.module.location
            else 1
        )
        return [S0maSemanticError(
            code="MODULE_SHADOWS_STDLIB",
            message=(
                f"Module '{name}' shadows the Python standard-library "
                f"module '{name}'. A s0ma module with a stdlib name "
                f"cannot be imported by its bare name — the stdlib "
                f"module is already loaded, so bootstrap_imports and "
                f"cross-module `uses: [{name}...]` resolve to the "
                f"stdlib module and fail at runtime."
            ),
            file=self.filename,
            line=line,
            column=0,
            severity=severity,
            remediation=(
                f"Rename the module (and its file) to a non-stdlib "
                f"name — e.g. '{name}_io', 'app_{name}', or a "
                f"domain-specific noun. Keep the filename stem equal to "
                f"the declared `module <name>`."
            ),
            context={"module_name": name, "shadows": "stdlib"},
        )]

    # -------------------------------------------------------------------
    # D3 (beta-prep-1-retrofit) — a draft must never build as though it
    # were finished
    #
    # ``s0ma adopt draft`` turns a Python module into a DRAFT ``.s0ma``
    # file. A draft carries two kinds of unfinished business, and both
    # are refused here, in every strictness mode (retrofit ruling R-5):
    #
    #   * meaning nobody has written yet — a field still holding the
    #     :data:`~s0ma_dsl.adopt.model.DRAFT_INTENT_MARKER` placeholder;
    #   * source text the harvester could not place in any declaration —
    #     a quarantine cell, named and marked per the D1 carrier
    #     contract (see :mod:`s0ma_dsl.adopt.harvest`'s module
    #     docstring, which is where both keys are decided).
    #
    # Both passes live here, in the intra-module validator, because this
    # is the one pass that is handed the whole parsed module — the header
    # declaration and every other declaration, through
    # ``all_declarations`` — and already carries the strictness mode. A
    # separate file would be a second walk over the same declarations
    # and a second place to remember when a declaration form is added.
    # -------------------------------------------------------------------

    def _check_adopt_placeholder_intent(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Refuse every un-authored field a draft left behind.

        One finding per offending field, so a person sees the whole list
        of what is still theirs to write rather than one at a time.

        **The rule is "contains", not "starts with", and it covers every
        authored text field — not only ``intent:``.** Two reasons, both
        learned from what the emitter actually writes. First, the
        emitter puts the marker on ``expects:``, ``guarantees:`` and
        ``schema:`` as well, and appends explanatory sentences *after*
        the instruction, so a placeholder is not always the whole value.
        Second, no finished field has any reason to contain
        ``FIXME(adopt):`` — it is the draft tool's own marker, not a
        word of English — so a finished module cannot trip this by
        accident, and a half-edit that leaves the marker in the middle
        of a sentence is exactly the case worth catching.

        Bodies are never read. A body is code, carried across verbatim,
        and the quarantine carrier's body holds arbitrary Python
        *as a string* — a file that happened to contain the marker in a
        comment would otherwise be refused for its own source text
        rather than for anything unwritten.

        **The closing advice is the field's own**
        (:func:`_placeholder_advice`), because a message that covers
        every field cannot end with the answer to one of them.
        """
        severity = get_severity("ADOPT_PLACEHOLDER_INTENT", self.mode)
        if severity is None:  # pragma: no cover — error in every mode
            return []

        errors: list[S0maSemanticError] = []
        for form, declaration in _adopt_declarations(module):
            label = _adopt_label(form, declaration, module)
            line = declaration.location.start_line if declaration.location else 0
            for field_name, text in _authored_text_fields(declaration):
                if DRAFT_INTENT_MARKER not in text:
                    continue
                errors.append(S0maSemanticError(
                    code="ADOPT_PLACEHOLDER_INTENT",
                    message=(
                        f"{_adopt_sentence_start(label)} has not had its "
                        f"`{field_name}:` written yet: the value still carries "
                        f"`{DRAFT_INTENT_MARKER}`, the marker "
                        f"`s0ma adopt draft` leaves on every field it "
                        f"could not write for you. A draft derives "
                        f"structure from your Python and never invents "
                        f"meaning, so this sentence is the part only a "
                        f"person can write — {_placeholder_advice(form, field_name)}."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity=severity,
                    remediation=(
                        f"Replace the whole `{field_name}:` value on "
                        f"{label} — marker and all — with one plain "
                        f"sentence of your own; the placeholder text "
                        f"says what belongs there. Then run "
                        f"`s0ma check` again. This is refused in every "
                        f"mode, migration included, so that a "
                        f"half-finished draft cannot build or score as "
                        f"though somebody had written its meaning."
                    ),
                    context={
                        "declaration_type": form,
                        "declaration_name": getattr(
                            declaration, "name", module.module.name
                        ),
                        "field": field_name,
                        "marker": DRAFT_INTENT_MARKER,
                    },
                ))
        return errors

    def _check_adopt_unplaced_code(
        self, module: S0maModule,
    ) -> list[S0maSemanticError]:
        """Refuse every quarantine of un-placed source text.

        **Two independent keys, either of which is enough** — the
        contract D1 wrote down and the emitter honours: the declaration's
        *name* starts with ``ADOPT_UNPLACED_``, or one of its authored
        text fields carries the ``adopt: unplaced`` marker (the emitter
        writes it into the carrier's ``schema:``).

        Why both, and why neither alone. The marker alone could be
        dodged by deleting one word from ``schema:`` while the quarantine
        — and the un-placed code inside it — stayed exactly where it was.
        The name alone could be dodged by renaming the cell. Requiring
        *both* would mean either edit silences the refusal, which is the
        opposite of what a quarantine is for; so the rule is ``or``, and
        the only way out is the honest one: place the text and delete the
        declaration.

        It cannot be fooled by an ordinary constant either. The whole
        reserved prefix is matched — ``ADOPT_UNPLACED_``, which
        ``s0ma adopt draft`` mints and uses for nothing else, not the
        ``ADOPT_`` a real name might plausibly begin with — and
        ``adopt: unplaced`` is not a phrase that occurs in authored
        prose. In the one-in-a-million case where somebody did name a
        real constant into the prefix, the fix the message asks for
        (the declaration goes) is still the right conversation to be
        having, because the name is lying about what it holds.

        One finding per declaration, never two, however many keys matched.
        """
        severity = get_severity("ADOPT_UNPLACED_CODE", self.mode)
        if severity is None:  # pragma: no cover — error in every mode
            return []

        errors: list[S0maSemanticError] = []
        for form, declaration in _adopt_declarations(module):
            name = getattr(declaration, "name", "")
            by_name = bool(name) and name.startswith(UNPLACED_CELL_PREFIX)
            marked_field = next(
                (
                    field_name
                    for field_name, text in _authored_text_fields(declaration)
                    if DRAFT_UNPLACED_MARKER in text
                ),
                None,
            )
            if not by_name and marked_field is None:
                continue

            label = _adopt_label(form, declaration, module)
            line = declaration.location.start_line if declaration.location else 0
            span = _unplaced_span(name) if by_name else None
            if span is not None:
                holds = (
                    f"it holds {span} of the Python file this module was "
                    f"drafted from"
                )
            elif by_name:
                holds = (
                    f"its name opens with `{UNPLACED_CELL_PREFIX}`, which "
                    f"`s0ma adopt draft` uses for nothing else"
                )
            else:
                holds = (
                    f"its `{marked_field}:` is marked "
                    f"`{DRAFT_UNPLACED_MARKER}`"
                )
            errors.append(S0maSemanticError(
                code="ADOPT_UNPLACED_CODE",
                message=(
                    f"{_adopt_sentence_start(label)} is a quarantine rather "
                    f"than a part of your system: {holds}. It is source text "
                    f"`s0ma adopt draft` could not place in any "
                    f"declaration, kept word for word — as a string, so "
                    f"nothing was lost and nothing of it runs."
                ),
                file=self.filename,
                line=line,
                column=0,
                severity=severity,
                remediation=(
                    f"Read the text, then take one of the two ways out: "
                    f"move it into the declaration it belongs to — most "
                    f"often the module header's `requires:` or `uses:` "
                    f"list, an existing declaration's body, or a new "
                    f"declaration of its own — or delete it, if it is "
                    f"code nothing needs any more. Either way the "
                    f"{label} goes with it: the module cannot build "
                    f"while a quarantine is still in it, in any mode."
                ),
                context={
                    "declaration_type": form,
                    "declaration_name": name,
                    "matched_name_prefix": by_name,
                    "matched_marker_field": marked_field,
                },
            ))
        return errors


# ---------------------------------------------------------------------------
# D3 helpers — reading a declaration's authored text
# ---------------------------------------------------------------------------

#: Every declaration form of the language: the module header plus the ten
#: members of ``S0maModule.all_declarations``. Spelled out rather than
#: widened to ``object`` so that a form added to the language turns this
#: alias red at the one place that would otherwise start silently
#: skipping it.
_AdoptDeclaration = (
    ModuleDecl
    | NerveDecl
    | CellDecl
    | GanglionDecl
    | TestDecl
    | StandaloneAxonDecl
    | HelperDecl
    | IntegrationDecl
    | DocRefDecl
    | DocGuideDecl
    | ExampleDecl
)

#: Fields that hold code or a derived twin of it, never authored prose.
#: Excluded from every marker scan: a body is carried into a draft
#: verbatim, and the quarantine carrier's body is arbitrary source text
#: held as a string, so reading either would refuse a module for what its
#: own Python says rather than for anything left unwritten. ``name`` is
#: out because it is the declaration's identity, read on its own by
#: :meth:`IntraModuleValidator._check_adopt_unplaced_code`, and because
#: no identifier can contain either marker.
_NON_PROSE_FIELDS: frozenset[str] = frozenset({
    "body",
    "raw_body",
    "name",
    "embedded_content",
    "embedded_file_hash",
    "embedded_file_path",
    "embedded_file_resolved",
})

#: ``ADOPT_UNPLACED_<start>_<end>`` — the carrier name D1 mints, whose
#: two numbers are the line range of the source text it holds.
_UNPLACED_SPAN_RE = re.compile(r"_(\d+)_(\d+)$")


def _adopt_declarations(
    module: S0maModule,
) -> list[tuple[str, _AdoptDeclaration]]:
    """Every declaration of *module* as ``(form, declaration)``.

    The module header first, then every other declaration in source
    order (``all_declarations`` sorts by start line), so the findings of
    one file come out in one deterministic order on every platform.
    The form is read from the class name rather than from a list of
    types, so a declaration form added to the language arrives here by
    existing instead of by somebody remembering.
    """
    declarations: list[tuple[str, _AdoptDeclaration]] = [("module", module.module)]
    for declaration in module.all_declarations:
        form = type(declaration).__name__.removesuffix("Decl")
        declarations.append((_DECL_FORM_WORDS.get(form, form.lower()), declaration))
    return declarations


#: Class-name stem → the word a person would use for that declaration.
#: Only the stems that do not simply lower-case cleanly need a row.
_DECL_FORM_WORDS: dict[str, str] = {
    "StandaloneAxon": "axon",
    "DocRef": "doc-ref",
    "DocGuide": "doc-guide",
}


def _adopt_label(
    form: str, declaration: _AdoptDeclaration, module: S0maModule
) -> str:
    """How a finding names the declaration it is about, in plain words.

    Lower case, because the phrase reads mid-sentence more often than it
    opens one; :func:`_adopt_sentence_start` is the other form.
    """
    if form == "module":
        return f"module '{module.module.name}'"
    name = getattr(declaration, "name", None)
    if name is None:  # an axon names its two ends rather than itself
        source = getattr(declaration, "source", "?")
        target = getattr(declaration, "target", "?")
        return f"axon '{source} -> {target}'"
    return f"{form} '{name}'"


def _adopt_sentence_start(label: str) -> str:
    """The same label with its first letter capitalised, and nothing else.

    ``str.capitalize`` would lower-case the declaration's own name along
    with it, and a name is quoted from the source exactly as written.
    """
    return label[:1].upper() + label[1:]


def _authored_text_fields(declaration: _AdoptDeclaration) -> list[tuple[str, str]]:
    """Every authored text field of *declaration*, in declared order.

    A field counts when its value is a string and its name is not in
    :data:`_NON_PROSE_FIELDS`. Reading the dataclass rather than a list
    of field names is what makes the two D3 passes cover a field the
    language grows later without anybody adding it here — and the
    ordering is the dataclass's own, which is fixed at class-definition
    time and therefore identical on every platform.
    """
    if not dataclasses.is_dataclass(declaration):  # pragma: no cover
        return []
    found: list[tuple[str, str]] = []
    for field_info in dataclasses.fields(declaration):
        if field_info.name in _NON_PROSE_FIELDS:
            continue
        value = getattr(declaration, field_info.name, None)
        if isinstance(value, str):
            found.append((field_info.name, value))
    return found


#: Said when a field has no instruction of its own. True of every
#: placeholder the emitter writes, and it points at the one place that
#: always knows: the value still sitting in the file.
_GENERIC_PLACEHOLDER_ADVICE = "the placeholder text says what belongs there"


def _placeholder_advice(form: str, field: str) -> str:
    """What this field is for, in the emitter's own words.

    The refusal used to end with advice written for an ``intent:`` —
    "why this part exists and what would break without it" — whatever
    field it was about, so a ``schema:`` was answered with the wrong
    question (G3c). The sentences that say what belongs in each field
    already exist and are already read by the person being refused:
    ``s0ma adopt draft`` writes them into the file
    (:data:`~s0ma_dsl.adopt.draft_emit.PLACEHOLDERS`). Reading them from
    there is what stops the refusal and the placeholder it is about ever
    saying two different things.

    A field with no sentence of its own — one the draft tool does not
    write, reached because the rule covers every authored text field —
    gets the one thing that is true of all of them.
    """
    return PLACEHOLDERS.get((form, field), _GENERIC_PLACEHOLDER_ADVICE)


def _unplaced_span(name: str) -> str | None:
    """``lines 10-13`` / ``line 10`` from a carrier's name, or ``None``.

    The two numbers a carrier name ends in are the line range of the
    source text it holds (``harvest.unplaced_cell_name``). A name that
    opens with the prefix but does not end in that shape has been
    hand-edited; the finding then says what it can rather than inventing
    a range.
    """
    match = _UNPLACED_SPAN_RE.search(name)
    if match is None:
        return None
    start, end = int(match.group(1)), int(match.group(2))
    return f"line {start}" if start == end else f"lines {start}-{end}"


# ---------------------------------------------------------------------------
# POST-10h helpers — recognise ``dataclasses.field`` calls with mutable defaults
# ---------------------------------------------------------------------------


def _is_dataclasses_field_call(func: ast.expr) -> bool:
    """Return True iff ``func`` is a call target naming the
    ``dataclasses.field`` function.

    Recognises both ``field(...)`` (when ``field`` is imported from
    ``dataclasses`` via ``requires: [dataclasses.field]`` or
    ``requires: [dataclasses:field]``) and ``dataclasses.field(...)``
    (when only the top-level module is imported). Aliased imports
    (``from dataclasses import field as df``; ``df(...)``) are not
    recognised — the lint is intentionally conservative there to
    avoid false positives on unrelated single-name ``field(...)``
    calls in unrelated APIs.
    """
    if isinstance(func, ast.Name):
        return func.id == "field"
    if isinstance(func, ast.Attribute):
        # ``dataclasses.field`` — match the rightmost attribute and
        # the leftmost root identifier.
        if func.attr != "field":
            return False
        cur: ast.expr = func.value
        while isinstance(cur, ast.Attribute):
            cur = cur.value
        return isinstance(cur, ast.Name) and cur.id == "dataclasses"
    return False


def _classify_mutable_literal(value: ast.expr) -> str | None:
    """Classify ``value`` as ``list``/``dict``/``set`` if it is a
    mutable-collection literal; otherwise return None.

    Matches:
    - ``[...]``                              → ``"list"``
    - ``list(...)``                           → ``"list"`` (only when args empty)
    - ``{...}`` / ``{k: v, ...}`` / ``set()`` → ``"dict"`` or ``"set"``
    - ``dict(...)``                           → ``"dict"`` (only when args empty)
    - ``set(...)``                            → ``"set"`` (only when args empty)

    Comprehensions are NOT recognised — they're an unusual choice for a
    ``default=`` argument and the false-positive cost is non-trivial.
    The lint's value is catching the canonical
    ``default=[]`` / ``default={}`` cases.
    """
    if isinstance(value, ast.List):
        return "list"
    if isinstance(value, ast.Dict):
        return "dict"
    if isinstance(value, ast.Set):
        return "set"
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and not value.args
        and not value.keywords
    ):
        if value.func.id == "list":
            return "list"
        if value.func.id == "dict":
            return "dict"
        if value.func.id == "set":
            return "set"
    return None


def _is_jsonable(value: object) -> bool:
    """Return True iff ``value`` is a JSON-serialisable primitive (POST-5)."""
    if value is None:
        return True
    if isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_jsonable(v) for v in value)
    if isinstance(value, dict):
        return all(
            isinstance(k, str) and _is_jsonable(v) for k, v in value.items()
        )
    return False


# ---------------------------------------------------------------------------
# Mock-dict extraction helpers (POST-3b)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _MockDictLiteral:
    """A literal dict assigned at the test body's top level.

    Used by :func:`_extract_mock_dict_assignments` and the POST-3b
    cross-check. ``keys`` is the set of literal-string keys the dict
    carries; entries with non-literal keys are intentionally not
    represented (the check skips ambiguous mocks).
    """

    assigned_name: str
    keys: frozenset[str]


def _extract_mock_dict_assignments(body: str) -> dict[str, _MockDictLiteral]:
    """Return every assignment ``<name> = {...literal-string keys}`` in ``body``.

    Walks the body's AST (and the AST of every nested function in the
    body) and collects identifier-targeted assignments to dict
    literals whose keys are all literal strings. Returns a dict
    keyed by the assignment's identifier name. Bodies that fail to
    parse return ``{}``; the dedicated body-syntax check elsewhere
    reports the parse failure.

    Mock dicts often live inside the test function rather than at the
    declaration's module scope, so the walk descends into ``def`` /
    ``async def`` bodies — the test framework runs each test as a
    function, and the mock fixture is typically constructed there.
    Dicts whose keys mix literal strings with other key shapes are
    skipped: the check requires every key be a literal string so the
    cross-check's key-set comparison is well-defined.
    """
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return {}

    assignments: dict[str, _MockDictLiteral] = {}

    def _record_dict_assignments(stmts: list[ast.stmt]) -> None:
        for node in stmts:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                keys = _literal_string_keys(node.value)
                if keys is None:
                    continue
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        # Last-write-wins is fine — duplicate names
                        # inside one test body are rare and the
                        # cross-check would surface the issue either
                        # way.
                        assignments[tgt.id] = _MockDictLiteral(
                            assigned_name=tgt.id,
                            keys=frozenset(keys),
                        )
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and isinstance(node.value, ast.Dict)
            ):
                keys = _literal_string_keys(node.value)
                if keys is None:
                    continue
                assignments[node.target.id] = _MockDictLiteral(
                    assigned_name=node.target.id,
                    keys=frozenset(keys),
                )

    # Top-level assignments + every nested function / async function
    # body. Class bodies are excluded — class-bodied tests are rare
    # and the mock-shape convention applies to fixture dicts, not
    # methods.
    _record_dict_assignments(tree.body)
    for outer in tree.body:
        if isinstance(outer, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _record_dict_assignments(outer.body)
            # One more level of nesting (a factory inside the test
            # function is the canonical Phase 2 frontend shape).
            for inner in outer.body:
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _record_dict_assignments(inner.body)
    return assignments


def _literal_string_keys(node: ast.Dict) -> set[str] | None:
    """Return the set of literal-string keys in ``node``, or ``None`` if any key is non-literal.

    A key is "literal-string" iff it is an ``ast.Constant`` whose
    value is a ``str``. The POST-3b cross-check refuses to fire on
    dicts that mix literal and non-literal keys: the comparison
    needs a well-defined key set, and silently dropping the
    non-literal keys would either hide a real mismatch or surface a
    spurious one. Returning ``None`` causes the caller to skip the
    assignment entirely.
    """
    keys: set[str] = set()
    for key in node.keys:
        if key is None:
            # ``{**other}`` spread; treat as non-literal.
            return None
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            keys.add(key.value)
            continue
        return None
    return keys


# Common author-convention prefixes the POST-3b cross-check strips
# before comparing the assignment name to the mock target name.
_MOCK_VARIABLE_PREFIXES: tuple[str, ...] = (
    "mock_",
    "fake_",
    "stub_",
    "dummy_",
    "fixture_",
)


def _match_mock_assignment(
    mock_target: str,
    assignments: dict[str, _MockDictLiteral],
) -> _MockDictLiteral | None:
    """Pick the assignment whose name matches ``mock_target`` by convention.

    The convention: an assignment name matches when, after lowercasing
    and stripping a leading mock/fake/stub prefix, it equals the
    target's lowercased name. Returns the first matching literal in a
    deterministic order, or ``None`` when no assignment matches.
    """
    target_lower = mock_target.lower()
    # Sort by assignment name so deterministic order is preserved
    # when more than one candidate matches (rare; choosing
    # alphabetically keeps tests stable).
    for assigned_name in sorted(assignments):
        candidate = assigned_name.lower()
        if candidate == target_lower:
            return assignments[assigned_name]
        for prefix in _MOCK_VARIABLE_PREFIXES:
            if (
                candidate.startswith(prefix)
                and candidate[len(prefix):] == target_lower
            ):
                return assignments[assigned_name]
    return None


def _body_top_level_assigned_names(body: str) -> set[str]:
    """Return names assigned at the top level of a Python body.

    Walks the AST and collects identifiers that are the LHS of either
    a plain ``Assign`` (``FOO = 1``) or an ``AnnAssign``
    (``FOO: int = 1``) at the body's top level. Tuple/starred targets,
    attribute targets, and assignments inside nested ``def`` / ``class``
    bodies are intentionally excluded — only top-level identifier
    assignments correspond to the import surface the codegen emits
    for a CONSTANT cell.

    Returns an empty set if the body fails to parse; the dedicated
    body-syntax check elsewhere reports the parse failure, so this
    helper avoids double-reporting.
    """
    # F1 (feedback 5–6 follow-up): ``body`` is the canonical, already
    # dedented form produced by ``parser.body_extractor.extract_body``.
    # Calling ``textwrap.dedent`` here used to silently fail on
    # multi-line CONSTANT bodies whose strings carry column-0 lines
    # (e.g. ``BIG_TEMPLATE = """\n<html>...``) — that broke the common
    # leading prefix and produced a spurious ``IndentationError`` from
    # ``ast.parse``, which this helper swallowed via ``return set()``.
    # The result was an M17 false-positive ``CONSTANT_NAME_MISMATCH``.
    # Reading the canonical body directly eliminates that failure mode.
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return set()

    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _extract_def_names(body: str) -> set[str]:
    """Extract all function names defined in a body via ``def name(...)``.

    Note: this is a *non-scope-aware* helper used by ``provides`` and abstract
    interface checks, where any matching ``def`` in the body satisfies the
    contract regardless of nesting. For module-scope helper-collision
    detection, see :func:`_extract_top_level_def_names`.
    """
    names: set[str] = set()
    for match in re.finditer(r"\bdef\s+(\w+)\s*\(", body):
        names.add(match.group(1))
    return names


def _extract_top_level_def_names(body: str) -> set[str]:
    """Return names of ``def`` / ``async def`` declarations at the body's
    top level only.

    Methods inside ``class`` bodies and functions inside other functions are
    intentionally excluded — they are not module-scope helpers and cannot
    collide across test blocks. This is the correct semantics for
    ``HELPER_NAME_COLLISION``: only top-level helpers risk silent overwrite
    when two test bodies are concatenated into the same emitted module.

    POST-10c (0.16.0) — D-27 closure: only siblings of the test root
    function (and the test root function itself) are at risk of
    silent overwrite at module emit time. Class-bodied helpers carry
    their own method namespace; nested closures live inside an outer
    ``def`` scope. Neither escapes into the module namespace and so
    neither participates in the collision detector. The single-pass
    ``ast.walk`` over ``tree.body`` here encodes that rule exactly:
    we look at ``ast.FunctionDef`` / ``ast.AsyncFunctionDef`` nodes
    whose parent is the module-root, full stop.
    """
    # F1 (feedback 5–6 follow-up): ``body`` is the canonical (column-0)
    # form produced by ``parser.body_extractor.extract_body``. No
    # secondary dedent is needed here — see
    # :func:`_body_top_level_assigned_names` for the rationale.
    try:
        tree = ast.parse(body)
    except SyntaxError:
        # Body has a syntax error; the dedicated body-syntax check will
        # surface it. Skip collision analysis for this body to avoid
        # double-reporting.
        return set()

    names: set[str] = set()
    # POST-10c: iterate ``tree.body`` — i.e. module-root statements —
    # *only*. ``ast.ClassDef`` nodes and any nested ``ast.FunctionDef``
    # inside another ``def`` are ignored by design. The exhaustive
    # regression cases live in tests/test_semantic.py
    # (``test_class_methods_do_not_collide``,
    # ``test_inner_function_defs_do_not_collide``) and the round-1
    # regression pins live in tests/test_validator_round_1_fixes.py.
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def _top_level_definitions(
    body: str,
) -> tuple[list[str], dict[str, list[str]]] | None:
    """What a body defines at its top level, in the order it defines it.

    Returns the top-level function names and, for each top-level class,
    the names of the functions directly inside it — the two shapes pytest
    can collect. ``None`` for a body that does not parse, which is the
    body validator's finding and not this caller's.
    """
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return None
    functions: list[str] = []
    classes: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes[node.name] = [
                item.name
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
    return functions, classes


# pytest's own defaults for ``python_functions`` and ``python_classes``.
_DEFAULT_RUNNER_FUNCTIONS: tuple[str, ...] = ("test",)
_DEFAULT_RUNNER_CLASSES: tuple[str, ...] = ("Test",)

# The ini-style files pytest falls back to after ``pytest.ini`` and
# ``pyproject.toml``, in the order it prefers them, each with the section
# that holds its settings.
_RUNNER_FALLBACK_FILES: tuple[tuple[str, str], ...] = (
    ("tox.ini", "pytest"),
    ("setup.cfg", "tool:pytest"),
)


def _runner_collects(name: str, patterns: tuple[str, ...]) -> bool:
    """Would pytest collect ``name`` under ``patterns``?

    pytest's own rule, restated: an entry is a prefix, and an entry that
    contains a glob character is also tried as a glob.
    """
    return any(
        name.startswith(pattern)
        or (
            any(char in pattern for char in "*?[")
            and fnmatch.fnmatch(name, pattern)
        )
        for pattern in patterns
    )


def _runner_patterns_of(raw: object, default: tuple[str, ...]) -> tuple[str, ...]:
    """One runner setting as a tuple of patterns, or ``default`` if unset."""
    if isinstance(raw, str):
        found = tuple(raw.split())
    elif isinstance(raw, list):
        found = tuple(str(item) for item in raw if str(item).strip())
    else:
        found = ()
    return found or default


def _runner_name_patterns(filename: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The function and class names pytest collects for ``filename``'s project.

    Read from the nearest directory at or above the source file that
    holds runner settings, which is where pytest itself finds them when
    ``s0ma test`` runs it from the project root. A source with no file
    behind it, and a project that sets neither name, get pytest's
    defaults.
    """
    source = Path(filename)
    if not source.is_file():
        return _DEFAULT_RUNNER_FUNCTIONS, _DEFAULT_RUNNER_CLASSES
    return _runner_settings_above(str(source.resolve().parent))


@functools.lru_cache(maxsize=128)
def _runner_settings_above(
    directory: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Walk up from ``directory`` to the first runner settings; read them."""
    start = Path(directory)
    for candidate in (start, *start.parents):
        settings = _runner_settings_in(candidate)
        if settings is not None:
            return (
                _runner_patterns_of(
                    settings.get("python_functions"), _DEFAULT_RUNNER_FUNCTIONS,
                ),
                _runner_patterns_of(
                    settings.get("python_classes"), _DEFAULT_RUNNER_CLASSES,
                ),
            )
    return _DEFAULT_RUNNER_FUNCTIONS, _DEFAULT_RUNNER_CLASSES


def _runner_settings_in(directory: Path) -> dict[str, object] | None:
    """The runner settings ``directory`` holds, or ``None`` if it holds none.

    An unreadable or malformed settings file is treated as holding none:
    this reading exists to avoid a false report, and the file's own
    problems are the runner's to report when it is run.
    """
    ini = directory / "pytest.ini"
    if ini.is_file():
        return _runner_ini_section(ini, "pytest") or {}

    pyproject = directory / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            data = {}
        options = data.get("tool", {}).get("pytest", {}).get("ini_options")
        if isinstance(options, dict):
            return options

    for name, section in _RUNNER_FALLBACK_FILES:
        found = _runner_ini_section(directory / name, section)
        if found is not None:
            return found
    return None


def _runner_ini_section(path: Path, section: str) -> dict[str, object] | None:
    """One section of an ini-style settings file, or ``None`` if it is absent."""
    if not path.is_file():
        return None
    parser = configparser.ConfigParser()
    try:
        parser.read_string(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, configparser.Error):
        return None
    if not parser.has_section(section):
        return None
    return dict(parser.items(section))


def _extract_return_dict_keys(body: str) -> set[str] | None:
    """Extract string keys from ``return {"key": ...}`` patterns in a body.

    Looks for ``return {`` followed by quoted string keys. Returns ``None``
    if no return-dict pattern is found (indicating the body doesn't use
    the dict-of-functions pattern and validation should be skipped).
    """
    # Match return { ... } blocks — look for "key": patterns inside
    match = re.search(r"\breturn\s*\{", body)
    if match is None:
        return None

    # Extract everything from the return { to the end of the body
    rest = body[match.end():]

    keys: set[str] = set()
    # Match both "key": and 'key': patterns
    for key_match in re.finditer(r'["\'](\w+)["\']\s*:', rest):
        keys.add(key_match.group(1))

    return keys


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_validate_module",
    kind=ComponentKind.FUNCTION,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Convenience function to run all intra-module semantic validations on a parsed "
        "S0maModule."
    ),
    idempotent=True,
    is_framework=True,
)
def validate_module(
    module: S0maModule,
    *,
    mode: StrictnessMode = StrictnessMode.DEV,
    filename: str = "<unknown>",
    requires_python: tuple[str, ...] | None = None,
) -> list[S0maSemanticError]:
    """Run all intra-module semantic validations.

    Parameters
    ----------
    module:
        A fully parsed ``S0maModule`` from the parser.
    mode:
        Active strictness mode.
    filename:
        Source file path for diagnostics.
    requires_python:
        M-12 (POST-8, 0.16.0) — the project's
        ``[project].requires-python`` range as a tuple of PEP 440
        specifier clauses. When supplied and the range admits
        Python 3.11, the validator runs the
        ``PARSE_GRAMMAR_FORWARD_INCOMPAT`` pass and flags 3.12-only
        grammar in every body. When ``None`` (default), the pass is
        a no-op — consistent with the conservative
        "no declared floor → no check" rule.

    Returns
    -------
    list[S0maSemanticError]
        All errors and warnings found.
    """
    validator = IntraModuleValidator(
        mode=mode,
        filename=filename,
        requires_python=requires_python,
    )
    return validator.validate(module)
