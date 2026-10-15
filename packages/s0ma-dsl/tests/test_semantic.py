"""Tests for intra-module semantic validation (Milestone 7).

Covers:
  - Kind-to-declaration-type validation (7.1, spec §3.1)
  - Visibility/export consistency (7.2, R-27, FR-16)
  - Layer consistency (7.3, R-23, FR-17)
  - Inline axon validation (7.4, §1.12, R-22)
  - Standalone axon relation validation (7.4 continued, R-22)
  - Raises field validation (7.5, R-17, FR-15)
  - Version format validation (7.6, R-19)
  - Duplicate declaration detection (7.7)
  - Golden fixture passes all intra-module validations
  - Strictness modes correctly modulate severity
  - Error messages include remediation
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.ast_nodes.enums import (
    Coupling,
    EvaluatesAt,
    Kind,
    Layer,
    Relation,
    Visibility,
)
from s0ma_dsl.ast_nodes.nodes import (
    CellDecl,
    GanglionDecl,
    InlineAxon,
    ModuleDecl,
    NerveDecl,
    RequiresEntry,
    S0maModule,
    SourceLocation,
    StandaloneAxonDecl,
    TestDecl,
    UsesEntry,
)
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.semantic.validator import IntraModuleValidator, validate_module

if TYPE_CHECKING:
    from s0ma_dsl.errors import S0maSemanticError

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _loc(line: int = 1) -> SourceLocation:
    return SourceLocation(start_line=line, start_column=0, end_line=line, end_column=0)


def _make_module(
    name: str = "test_module",
    layer: Layer = Layer.APPLICATION,
    version: str = "1.0.0",
    intent: str = "Test module for semantic validation",
    exports: tuple[str, ...] = (),
    requires: tuple[RequiresEntry, ...] = (),
    uses: tuple[UsesEntry, ...] = (),
) -> ModuleDecl:
    return ModuleDecl(
        name=name,
        layer=layer,
        version=version,
        intent=intent,
        exports=exports,
        requires=requires,
        uses=uses,
        location=_loc(1),
    )


def _make_nerve(
    name: str,
    line: int = 10,
    layer: Layer = Layer.APPLICATION,
    kind: Kind = Kind.FUNCTION,
    visibility: Visibility = Visibility.INTERNAL,
    raises: tuple[str, ...] = (),
    depends_on: tuple[InlineAxon, ...] = (),
    version: str | None = None,
) -> NerveDecl:
    return NerveDecl(
        name=name,
        layer=layer,
        kind=kind,
        visibility=visibility,
        intent=f"Test nerve {name}",
        expects="None",
        guarantees="None",
        evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
        raises=raises,
        depends_on=depends_on,
        version=version,
        body=f"def {name}(): pass",
        location=_loc(line),
    )


def _make_cell(
    name: str,
    line: int = 20,
    layer: Layer = Layer.APPLICATION,
    kind: Kind = Kind.MODEL,
    visibility: Visibility = Visibility.INTERNAL,
    version: str | None = None,
) -> CellDecl:
    return CellDecl(
        name=name,
        layer=layer,
        kind=kind,
        visibility=visibility,
        intent=f"Test cell {name}",
        schema=f"{name} schema",
        body=f"class {name}: pass",
        location=_loc(line),
        version=version,
    )


def _make_ganglion(
    name: str,
    line: int = 30,
    layer: Layer = Layer.APPLICATION,
    visibility: Visibility = Visibility.INTERNAL,
    depends_on: tuple[InlineAxon, ...] = (),
) -> GanglionDecl:
    return GanglionDecl(
        name=name,
        layer=layer,
        visibility=visibility,
        intent=f"Test ganglion {name}",
        observes=("some_nerve",),
        scope=EvaluatesAt.SUBSYSTEM,
        priors="Expected normal signal patterns",
        on_anomaly="Log and alert",
        depends_on=depends_on,
        body=f"def {name}(): pass",
        location=_loc(line),
    )


def _make_test_decl(
    name: str,
    line: int = 40,
    layer: Layer = Layer.APPLICATION,
    tests: tuple[str, ...] = ("some_nerve",),
    depends_on: tuple[InlineAxon, ...] = (),
) -> TestDecl:
    return TestDecl(
        name=name,
        layer=layer,
        intent=f"Test declaration {name}",
        tests=tests,
        depends_on=depends_on,
        body=f"def {name}(): pass",
        location=_loc(line),
    )


def _make_standalone_axon(
    source: str,
    target: str,
    relation: Relation = Relation.CALLS,
    line: int = 50,
) -> StandaloneAxonDecl:
    return StandaloneAxonDecl(
        source=source,
        target=target,
        relation=relation,
        intent=f"{source} {relation.value} {target}",
        carries="data",
        coupling=Coupling.LOOSE,
        location=_loc(line),
    )


def _simple_module(
    exports: tuple[str, ...] = (),
    requires: tuple[RequiresEntry, ...] = (),
    uses: tuple[UsesEntry, ...] = (),
    nerves: tuple[NerveDecl, ...] = (),
    cells: tuple[CellDecl, ...] = (),
    ganglia: tuple[GanglionDecl, ...] = (),
    tests: tuple[TestDecl, ...] = (),
    axons: tuple[StandaloneAxonDecl, ...] = (),
    module_layer: Layer = Layer.APPLICATION,
    module_version: str = "1.0.0",
) -> S0maModule:
    return S0maModule(
        module=_make_module(
            exports=exports,
            requires=requires,
            uses=uses,
            layer=module_layer,
            version=module_version,
        ),
        nerves=nerves,
        cells=cells,
        ganglia=ganglia,
        tests=tests,
        axons=axons,
    )


def _error_codes(errors: list[S0maSemanticError]) -> list[str]:
    return [e.code for e in errors]


# ===========================================================================
# 7.7 — Duplicate declaration detection
# ===========================================================================


class TestDuplicateDeclarations:
    """Two declarations sharing a name within a module must fail."""

    def test_no_duplicates(self):
        mod = _simple_module(
            nerves=(_make_nerve("alpha"),),
            cells=(_make_cell("beta"),),
        )
        errors = validate_module(mod)
        assert "DUPLICATE_DECLARATION" not in _error_codes(errors)

    def test_duplicate_nerve_names(self):
        mod = _simple_module(
            nerves=(
                _make_nerve("foo", line=10),
                _make_nerve("foo", line=20),
            ),
        )
        errors = validate_module(mod)
        assert "DUPLICATE_DECLARATION" in _error_codes(errors)

    def test_duplicate_across_types(self):
        """A nerve and a cell sharing the same name must fail."""
        mod = _simple_module(
            nerves=(_make_nerve("shared_name", line=10),),
            cells=(_make_cell("shared_name", line=20),),
        )
        errors = validate_module(mod)
        assert "DUPLICATE_DECLARATION" in _error_codes(errors)

    def test_duplicate_error_has_remediation(self):
        mod = _simple_module(
            nerves=(
                _make_nerve("dup", line=5),
                _make_nerve("dup", line=15),
            ),
        )
        errors = validate_module(mod)
        dup_errors = [e for e in errors if e.code == "DUPLICATE_DECLARATION"]
        assert len(dup_errors) >= 1
        assert dup_errors[0].remediation
        assert "dup" in dup_errors[0].remediation

    def test_standalone_axons_not_counted(self):
        """Standalone axons don't introduce component names."""
        mod = _simple_module(
            nerves=(_make_nerve("sender"),),
            axons=(_make_standalone_axon("sender", "receiver"),),
        )
        errors = validate_module(mod)
        assert "DUPLICATE_DECLARATION" not in _error_codes(errors)


# ===========================================================================
# 7.6 — Version format validation (R-19)
# ===========================================================================


class TestVersionFormat:
    """Version fields must follow semver MAJOR.MINOR.PATCH."""

    def test_valid_semver(self):
        mod = _simple_module(module_version="1.0.0")
        errors = validate_module(mod)
        assert "INVALID_VERSION" not in _error_codes(errors)

    def test_valid_semver_zero(self):
        mod = _simple_module(module_version="0.0.0")
        errors = validate_module(mod)
        assert "INVALID_VERSION" not in _error_codes(errors)

    def test_valid_semver_large(self):
        mod = _simple_module(module_version="12.345.6789")
        errors = validate_module(mod)
        assert "INVALID_VERSION" not in _error_codes(errors)

    def test_missing_patch(self):
        mod = _simple_module(module_version="1.0")
        errors = validate_module(mod)
        assert "INVALID_VERSION" in _error_codes(errors)

    def test_leading_zero(self):
        mod = _simple_module(module_version="01.0.0")
        errors = validate_module(mod)
        assert "INVALID_VERSION" in _error_codes(errors)

    def test_non_numeric(self):
        mod = _simple_module(module_version="1.0.0-beta")
        errors = validate_module(mod)
        assert "INVALID_VERSION" in _error_codes(errors)

    def test_empty_version(self):
        mod = _simple_module(module_version="")
        errors = validate_module(mod)
        assert "INVALID_VERSION" in _error_codes(errors)

    def test_component_version_valid(self):
        mod = _simple_module(
            nerves=(_make_nerve("foo", version="2.0.0"),),
        )
        errors = validate_module(mod)
        assert "INVALID_VERSION" not in _error_codes(errors)

    def test_component_version_invalid(self):
        mod = _simple_module(
            nerves=(_make_nerve("foo", version="bad"),),
        )
        errors = validate_module(mod)
        assert "INVALID_VERSION" in _error_codes(errors)

    def test_component_version_none_is_ok(self):
        """Optional version field — None means no version declared."""
        mod = _simple_module(
            nerves=(_make_nerve("foo", version=None),),
        )
        errors = validate_module(mod)
        assert "INVALID_VERSION" not in _error_codes(errors)

    def test_version_error_has_remediation(self):
        mod = _simple_module(module_version="nope")
        errors = validate_module(mod)
        ver_errors = [e for e in errors if e.code == "INVALID_VERSION"]
        assert len(ver_errors) >= 1
        rem = ver_errors[0].remediation
        assert "semver" in rem.lower() or "MAJOR.MINOR.PATCH" in rem


# ===========================================================================
# 7.1 — Kind-to-declaration-type validation (spec §3.1)
# ===========================================================================


class TestKindCompatibility:
    """Component kinds must match their declaration types."""

    def test_valid_nerve_kinds(self):
        """All valid nerve kinds should pass."""
        for k in (
            Kind.SERVICE, Kind.FUNCTION, Kind.ADAPTER,
            Kind.ORCHESTRATOR, Kind.FRAMEWORK,
        ):
            mod = _simple_module(nerves=(_make_nerve("n", kind=k),))
            errors = validate_module(mod)
            assert "INVALID_KIND" not in _error_codes(errors), (
                f"Kind {k} should be valid for nerve"
            )

    def test_valid_cell_kinds(self):
        """All valid cell kinds should pass."""
        for k in (
            Kind.MODEL, Kind.CONSTANT, Kind.CONFIG,
            Kind.ENUM, Kind.EXCEPTION, Kind.TYPE, Kind.FRAMEWORK,
        ):
            mod = _simple_module(cells=(_make_cell("c", kind=k),))
            errors = validate_module(mod)
            assert "INVALID_KIND" not in _error_codes(errors), (
                f"Kind {k} should be valid for cell"
            )

    def test_cell_kind_on_nerve_fails(self):
        """Using a cell-only kind on a nerve must fail."""
        mod = _simple_module(nerves=(_make_nerve("n", kind=Kind.MODEL),))
        errors = validate_module(mod)
        assert "INVALID_KIND" in _error_codes(errors)

    def test_nerve_kind_on_cell_fails(self):
        """Using a nerve-only kind on a cell must fail."""
        mod = _simple_module(cells=(_make_cell("c", kind=Kind.SERVICE),))
        errors = validate_module(mod)
        assert "INVALID_KIND" in _error_codes(errors)

    def test_invalid_kind_error_lists_valid_kinds(self):
        mod = _simple_module(nerves=(_make_nerve("n", kind=Kind.MODEL),))
        errors = validate_module(mod)
        kind_errors = [e for e in errors if e.code == "INVALID_KIND"]
        assert len(kind_errors) == 1
        # The error context should list the valid kinds
        assert "valid_kinds" in kind_errors[0].context

    def test_invalid_kind_has_remediation(self):
        mod = _simple_module(nerves=(_make_nerve("n", kind=Kind.CONSTANT),))
        errors = validate_module(mod)
        kind_errors = [e for e in errors if e.code == "INVALID_KIND"]
        assert kind_errors[0].remediation
        assert "n" in kind_errors[0].remediation


# ===========================================================================
# 7.3 — Layer consistency (R-23, FR-17)
# ===========================================================================


class TestLayerConsistency:
    """All components in a module must share the module's layer."""

    def test_matching_layers_pass(self):
        mod = _simple_module(
            module_layer=Layer.APPLICATION,
            nerves=(_make_nerve("n", layer=Layer.APPLICATION),),
            cells=(_make_cell("c", layer=Layer.APPLICATION),),
        )
        errors = validate_module(mod)
        assert "LAYER_MISMATCH" not in _error_codes(errors)

    def test_nerve_layer_mismatch(self):
        mod = _simple_module(
            module_layer=Layer.APPLICATION,
            nerves=(_make_nerve("n", layer=Layer.DOMAIN),),
        )
        errors = validate_module(mod)
        assert "LAYER_MISMATCH" in _error_codes(errors)

    def test_cell_layer_mismatch(self):
        mod = _simple_module(
            module_layer=Layer.INFRASTRUCTURE,
            cells=(_make_cell("c", layer=Layer.PRESENTATION),),
        )
        errors = validate_module(mod)
        assert "LAYER_MISMATCH" in _error_codes(errors)

    def test_ganglion_layer_mismatch(self):
        mod = _simple_module(
            module_layer=Layer.APPLICATION,
            ganglia=(_make_ganglion("g", layer=Layer.DOMAIN),),
        )
        errors = validate_module(mod)
        assert "LAYER_MISMATCH" in _error_codes(errors)

    def test_test_decl_layer_mismatch(self):
        mod = _simple_module(
            module_layer=Layer.APPLICATION,
            tests=(_make_test_decl("t", layer=Layer.DOMAIN),),
        )
        errors = validate_module(mod)
        assert "LAYER_MISMATCH" in _error_codes(errors)

    def test_multiple_mismatches_reported(self):
        mod = _simple_module(
            module_layer=Layer.APPLICATION,
            nerves=(
                _make_nerve("n1", layer=Layer.DOMAIN, line=10),
                _make_nerve("n2", layer=Layer.INFRASTRUCTURE, line=20),
            ),
        )
        errors = validate_module(mod)
        layer_errors = [e for e in errors if e.code == "LAYER_MISMATCH"]
        assert len(layer_errors) == 2

    def test_layer_error_has_remediation(self):
        mod = _simple_module(
            module_layer=Layer.APPLICATION,
            nerves=(_make_nerve("n", layer=Layer.DOMAIN),),
        )
        errors = validate_module(mod)
        layer_errors = [e for e in errors if e.code == "LAYER_MISMATCH"]
        assert layer_errors[0].remediation
        assert "APPLICATION" in layer_errors[0].remediation

    def test_standalone_axons_skipped(self):
        """Standalone axons don't have a layer field — should not trigger."""
        mod = _simple_module(
            module_layer=Layer.APPLICATION,
            nerves=(_make_nerve("sender"),),
            axons=(_make_standalone_axon("sender", "ext.receiver"),),
        )
        errors = validate_module(mod)
        assert "LAYER_MISMATCH" not in _error_codes(errors)


# ===========================================================================
# 7.2 — Visibility/export consistency (R-27, FR-16)
# ===========================================================================


class TestVisibilityExportConsistency:
    """Visibility and exports must agree: exported=PUBLIC, non-exported=INTERNAL."""

    def test_exported_public_passes(self):
        mod = _simple_module(
            exports=("pub_nerve",),
            nerves=(_make_nerve("pub_nerve", visibility=Visibility.PUBLIC),),
        )
        errors = validate_module(mod)
        assert "VISIBILITY_MISMATCH" not in _error_codes(errors)

    def test_non_exported_internal_passes(self):
        mod = _simple_module(
            exports=(),
            nerves=(_make_nerve("int_nerve", visibility=Visibility.INTERNAL),),
        )
        errors = validate_module(mod)
        assert "VISIBILITY_MISMATCH" not in _error_codes(errors)

    def test_exported_internal_fails(self):
        """Exported component must be PUBLIC, not INTERNAL."""
        mod = _simple_module(
            exports=("n",),
            nerves=(_make_nerve("n", visibility=Visibility.INTERNAL),),
        )
        errors = validate_module(mod)
        assert "VISIBILITY_MISMATCH" in _error_codes(errors)
        vis_errors = [e for e in errors if e.code == "VISIBILITY_MISMATCH"]
        assert "PUBLIC" in vis_errors[0].remediation

    def test_non_exported_public_fails(self):
        """PUBLIC component must be exported."""
        mod = _simple_module(
            exports=(),
            nerves=(_make_nerve("n", visibility=Visibility.PUBLIC),),
        )
        errors = validate_module(mod)
        assert "VISIBILITY_MISMATCH" in _error_codes(errors)
        vis_errors = [e for e in errors if e.code == "VISIBILITY_MISMATCH"]
        assert "exports" in vis_errors[0].remediation.lower()

    def test_mixed_correct_visibility(self):
        """Module with both PUBLIC exported and INTERNAL non-exported."""
        mod = _simple_module(
            exports=("pub",),
            nerves=(
                _make_nerve("pub", visibility=Visibility.PUBLIC, line=10),
                _make_nerve("priv", visibility=Visibility.INTERNAL, line=20),
            ),
        )
        errors = validate_module(mod)
        assert "VISIBILITY_MISMATCH" not in _error_codes(errors)

    def test_cell_visibility_checked(self):
        mod = _simple_module(
            exports=("MyModel",),
            cells=(_make_cell("MyModel", visibility=Visibility.INTERNAL),),
        )
        errors = validate_module(mod)
        assert "VISIBILITY_MISMATCH" in _error_codes(errors)

    def test_ganglion_visibility_checked(self):
        mod = _simple_module(
            exports=(),
            ganglia=(_make_ganglion("g", visibility=Visibility.PUBLIC),),
        )
        errors = validate_module(mod)
        assert "VISIBILITY_MISMATCH" in _error_codes(errors)

    def test_visibility_error_in_all_modes(self):
        """VISIBILITY_MISMATCH is always an error regardless of strictness mode."""
        mod = _simple_module(
            exports=("n",),
            nerves=(_make_nerve("n", visibility=Visibility.INTERNAL),),
        )
        for mode in StrictnessMode:
            errors = validate_module(mod, mode=mode)
            vis_errors = [e for e in errors if e.code == "VISIBILITY_MISMATCH"]
            assert len(vis_errors) >= 1, f"Expected VISIBILITY_MISMATCH in {mode.value} mode"
            assert vis_errors[0].severity == "error"


# ===========================================================================
# 7.4 — Inline axon validation
# ===========================================================================


class TestInlineAxonValidation:
    """Inline depends_on entries must have valid targets and authored relations."""

    def test_valid_inline_axon_local_target(self):
        """depends_on targeting a local declaration should pass."""
        cell = _make_cell("MyConstant", kind=Kind.CONSTANT, line=10)
        nerve = _make_nerve(
            "reader",
            line=20,
            depends_on=(
                InlineAxon(
                    target="MyConstant",
                    relation=Relation.READS,
                    carries="config value",
                    coupling=Coupling.TIGHT,
                    location=_loc(25),
                ),
            ),
        )
        mod = _simple_module(cells=(cell,), nerves=(nerve,))
        errors = validate_module(mod)
        assert "INVALID_AXON_RELATION" not in _error_codes(errors)
        assert "DOES_NOT_EXIST" not in _error_codes(errors)

    def test_valid_inline_axon_uses_target(self):
        """depends_on targeting a uses import should pass."""
        nerve = _make_nerve(
            "processor",
            line=20,
            depends_on=(
                InlineAxon(
                    target="select_evaluator",
                    relation=Relation.CALLS,
                    carries="data",
                    coupling=Coupling.LOOSE,
                    location=_loc(25),
                ),
            ),
        )
        mod = _simple_module(
            uses=(UsesEntry(qualified_name="routing.select_evaluator", location=_loc(5)),),
            nerves=(nerve,),
        )
        errors = validate_module(mod)
        axon_errors = [e for e in errors if e.code in ("DOES_NOT_EXIST", "INVALID_RAISES_TARGET")]
        assert len(axon_errors) == 0

    def test_inline_axon_derived_relation_fails(self):
        """Using RAISES as an inline axon relation must fail (R-22)."""
        cell = _make_cell("MyError", kind=Kind.EXCEPTION, line=10)
        nerve = _make_nerve(
            "thrower",
            line=20,
            depends_on=(
                InlineAxon(
                    target="MyError",
                    relation=Relation.RAISES,
                    carries="exception",
                    coupling=Coupling.TIGHT,
                    location=_loc(25),
                ),
            ),
        )
        mod = _simple_module(cells=(cell,), nerves=(nerve,))
        errors = validate_module(mod)
        assert "INVALID_AXON_RELATION" in _error_codes(errors)

    def test_inline_axon_type_uses_relation_fails(self):
        """Using TYPE_USES as an inline axon relation must fail (R-22)."""
        cell = _make_cell("MyType", kind=Kind.TYPE, line=10)
        nerve = _make_nerve(
            "user",
            line=20,
            depends_on=(
                InlineAxon(
                    target="MyType",
                    relation=Relation.TYPE_USES,
                    carries="type info",
                    coupling=Coupling.LOOSE,
                    location=_loc(25),
                ),
            ),
        )
        mod = _simple_module(cells=(cell,), nerves=(nerve,))
        errors = validate_module(mod)
        assert "INVALID_AXON_RELATION" in _error_codes(errors)

    def test_inline_axon_target_not_found(self):
        """depends_on targeting a non-existent name must fail."""
        nerve = _make_nerve(
            "caller",
            line=20,
            depends_on=(
                InlineAxon(
                    target="nonexistent",
                    relation=Relation.CALLS,
                    carries="data",
                    coupling=Coupling.TIGHT,
                    location=_loc(25),
                ),
            ),
        )
        mod = _simple_module(nerves=(nerve,))
        errors = validate_module(mod)
        assert "DOES_NOT_EXIST" in _error_codes(errors)

    def test_inline_axon_requires_target_fails(self):
        """depends_on targeting a requires name must fail (not a s0ma component)."""
        nerve = _make_nerve(
            "caller",
            line=20,
            depends_on=(
                InlineAxon(
                    target="time",
                    relation=Relation.CALLS,
                    carries="timestamp",
                    coupling=Coupling.LOOSE,
                    location=_loc(25),
                ),
            ),
        )
        mod = _simple_module(
            requires=(RequiresEntry(module_path="time", location=_loc(3)),),
            nerves=(nerve,),
        )
        errors = validate_module(mod)
        assert "INVALID_RAISES_TARGET" in _error_codes(errors)

    def test_ganglion_inline_axon_validated(self):
        """Inline axons on ganglia should also be validated."""
        ganglion = _make_ganglion(
            "monitor",
            line=30,
            depends_on=(
                InlineAxon(
                    target="ghost",
                    relation=Relation.READS,
                    carries="data",
                    coupling=Coupling.LOOSE,
                    location=_loc(35),
                ),
            ),
        )
        mod = _simple_module(ganglia=(ganglion,))
        errors = validate_module(mod)
        assert "DOES_NOT_EXIST" in _error_codes(errors)

    def test_test_decl_inline_axon_validated(self):
        """Inline axons on test declarations should also be validated."""
        test = _make_test_decl(
            "test_something",
            line=40,
            depends_on=(
                InlineAxon(
                    target="missing",
                    relation=Relation.CALLS,
                    carries="data",
                    coupling=Coupling.LOOSE,
                    location=_loc(45),
                ),
            ),
        )
        mod = _simple_module(tests=(test,))
        errors = validate_module(mod)
        assert "DOES_NOT_EXIST" in _error_codes(errors)

    def test_all_authored_relations_accepted(self):
        """All authored relations should be valid in depends_on."""
        cell = _make_cell("Target", line=10)
        for rel in (
            Relation.CALLS, Relation.CONSTRUCTS, Relation.READS,
            Relation.CONFIGURES, Relation.PRODUCES, Relation.CONSUMES,
        ):
            nerve = _make_nerve(
                "source",
                line=20,
                depends_on=(
                    InlineAxon(
                        target="Target",
                        relation=rel,
                        carries="data",
                        coupling=Coupling.LOOSE,
                        location=_loc(25),
                    ),
                ),
            )
            mod = _simple_module(cells=(cell,), nerves=(nerve,))
            errors = validate_module(mod)
            assert "INVALID_AXON_RELATION" not in _error_codes(errors), (
                f"Authored relation {rel.value} should be accepted"
            )


# ===========================================================================
# 7.4 (continued) — Standalone axon validation
# ===========================================================================


class TestStandaloneAxonValidation:
    """Standalone axon declarations must use authored relations and valid sources."""

    def test_valid_standalone_axon(self):
        nerve = _make_nerve("sender", line=10)
        axon = _make_standalone_axon("sender", "ext.receiver", Relation.CALLS, line=50)
        mod = _simple_module(nerves=(nerve,), axons=(axon,))
        errors = validate_module(mod)
        assert "INVALID_AXON_RELATION" not in _error_codes(errors)
        assert "DOES_NOT_EXIST" not in _error_codes(errors)

    def test_standalone_axon_raises_relation_fails(self):
        nerve = _make_nerve("sender", line=10)
        axon = _make_standalone_axon("sender", "ext.target", Relation.RAISES, line=50)
        mod = _simple_module(nerves=(nerve,), axons=(axon,))
        errors = validate_module(mod)
        assert "INVALID_AXON_RELATION" in _error_codes(errors)

    def test_standalone_axon_type_uses_relation_fails(self):
        nerve = _make_nerve("sender", line=10)
        axon = _make_standalone_axon("sender", "ext.target", Relation.TYPE_USES, line=50)
        mod = _simple_module(nerves=(nerve,), axons=(axon,))
        errors = validate_module(mod)
        assert "INVALID_AXON_RELATION" in _error_codes(errors)

    def test_standalone_axon_source_not_found(self):
        axon = _make_standalone_axon("nonexistent", "ext.target", line=50)
        mod = _simple_module(axons=(axon,))
        errors = validate_module(mod)
        assert "DOES_NOT_EXIST" in _error_codes(errors)
        does_not_exist = [e for e in errors if e.code == "DOES_NOT_EXIST"]
        assert "nonexistent" in does_not_exist[0].message

    def test_standalone_axon_source_exists(self):
        """Source matching a local declaration should pass."""
        nerve = _make_nerve("my_func", line=10)
        axon = _make_standalone_axon("my_func", "other_module.target", line=50)
        mod = _simple_module(nerves=(nerve,), axons=(axon,))
        errors = validate_module(mod)
        source_errors = [
            e for e in errors
            if e.code == "DOES_NOT_EXIST" and "source" in e.message.lower()
        ]
        assert len(source_errors) == 0


# ===========================================================================
# 7.5 — Raises field validation (R-17, FR-15)
# ===========================================================================


class TestRaisesFieldValidation:
    """raises entries must reference valid exception cells in component-ref namespace."""

    def test_raises_local_exception_passes(self):
        """Raises referencing a local exception cell should pass."""
        exc_cell = _make_cell("MyError", kind=Kind.EXCEPTION, line=10)
        nerve = _make_nerve("thrower", raises=("MyError",), line=20)
        mod = _simple_module(cells=(exc_cell,), nerves=(nerve,))
        errors = validate_module(mod)
        raises_errors = [
            e for e in errors
            if e.code in ("INVALID_RAISES_TARGET", "DOES_NOT_EXIST")
            and "raises" in e.message.lower()
        ]
        assert len(raises_errors) == 0

    def test_raises_uses_exception_passes(self):
        """Raises referencing a uses import should pass."""
        nerve = _make_nerve("thrower", raises=("SignalValidationError",), line=20)
        mod = _simple_module(
            uses=(UsesEntry(qualified_name="errors.SignalValidationError", location=_loc(5)),),
            nerves=(nerve,),
        )
        errors = validate_module(mod)
        raises_errors = [
            e for e in errors
            if e.code in ("INVALID_RAISES_TARGET", "DOES_NOT_EXIST")
        ]
        assert len(raises_errors) == 0

    def test_raises_requires_name_fails(self):
        """Raises referencing a requires name must fail (FR-15)."""
        nerve = _make_nerve("thrower", raises=("ValueError",), line=20)
        mod = _simple_module(
            requires=(RequiresEntry(
                module_path="builtins.ValueError",
                is_from_import=True,
                location=_loc(3),
            ),),
            nerves=(nerve,),
        )
        errors = validate_module(mod)
        assert "INVALID_RAISES_TARGET" in _error_codes(errors)
        target_errors = [e for e in errors if e.code == "INVALID_RAISES_TARGET"]
        assert "requires" in target_errors[0].message.lower()
        assert "adapter" in target_errors[0].remediation.lower()

    def test_raises_nonexistent_name_fails(self):
        """Raises referencing an unknown name must fail."""
        nerve = _make_nerve("thrower", raises=("GhostError",), line=20)
        mod = _simple_module(nerves=(nerve,))
        errors = validate_module(mod)
        assert "DOES_NOT_EXIST" in _error_codes(errors)

    def test_multiple_raises_checked(self):
        """All entries in the raises tuple should be validated."""
        exc = _make_cell("RealError", kind=Kind.EXCEPTION, line=10)
        nerve = _make_nerve("thrower", raises=("RealError", "FakeError"), line=20)
        mod = _simple_module(cells=(exc,), nerves=(nerve,))
        errors = validate_module(mod)
        # RealError should pass, FakeError should fail
        raises_errors = [
            e for e in errors
            if e.code == "DOES_NOT_EXIST" and "FakeError" in e.message
        ]
        assert len(raises_errors) == 1


# ===========================================================================
# Golden fixture — full pipeline test
# ===========================================================================


class TestGoldenFixture:
    """The signal_processor.s0ma golden fixture must pass all intra-module validations."""

    def test_golden_fixture_parses_and_validates(self):
        """Parse the golden fixture and validate it — should produce no errors."""
        from pathlib import Path

        from s0ma_dsl.parser import parse_s0ma

        fixture_path = Path(__file__).parent / "fixtures" / "valid" / "signal_processor.s0ma"
        source = fixture_path.read_text()
        module = parse_s0ma(source, str(fixture_path))

        errors = validate_module(module, filename=str(fixture_path))
        # Filter to only semantic errors (not namespace collisions which are
        # separate from what we're testing here). Golden fixture should be clean.
        semantic_codes = {
            "DUPLICATE_DECLARATION", "INVALID_VERSION", "INVALID_KIND",
            "LAYER_MISMATCH", "VISIBILITY_MISMATCH", "INVALID_AXON_RELATION",
            "INVALID_RAISES_TARGET",
        }
        real_errors = [e for e in errors if e.code in semantic_codes and e.severity == "error"]
        if real_errors:
            msgs = "\n".join(e.format_text() for e in real_errors)
            pytest.fail(f"Golden fixture should pass validation but got:\n{msgs}")

    def test_golden_fixture_all_modes(self):
        """Golden fixture should pass in all strictness modes."""
        from pathlib import Path

        from s0ma_dsl.parser import parse_s0ma

        fixture_path = Path(__file__).parent / "fixtures" / "valid" / "signal_processor.s0ma"
        source = fixture_path.read_text()
        module = parse_s0ma(source, str(fixture_path))

        semantic_codes = {
            "DUPLICATE_DECLARATION", "INVALID_VERSION", "INVALID_KIND",
            "LAYER_MISMATCH", "VISIBILITY_MISMATCH", "INVALID_AXON_RELATION",
            "INVALID_RAISES_TARGET",
        }
        for mode in StrictnessMode:
            errors = validate_module(module, mode=mode, filename=str(fixture_path))
            real_errors = [e for e in errors if e.code in semantic_codes and e.severity == "error"]
            if real_errors:
                msgs = "\n".join(e.format_text() for e in real_errors)
                pytest.fail(f"Golden fixture failed in {mode.value} mode:\n{msgs}")


# ===========================================================================
# Strictness mode severity differences
# ===========================================================================


class TestStrictnessModes:
    """Structural errors are always errors; behavioral rules vary by mode."""

    def test_structural_errors_always_error(self):
        """INVALID_KIND, LAYER_MISMATCH, VISIBILITY_MISMATCH are errors in all modes."""
        # Create a module with a layer mismatch
        mod = _simple_module(
            module_layer=Layer.APPLICATION,
            nerves=(_make_nerve("n", layer=Layer.DOMAIN),),
        )
        for mode in StrictnessMode:
            errors = validate_module(mod, mode=mode)
            layer_errors = [e for e in errors if e.code == "LAYER_MISMATCH"]
            assert len(layer_errors) >= 1, f"Expected LAYER_MISMATCH in {mode.value}"
            assert layer_errors[0].severity == "error"

    def test_duplicate_declaration_always_error(self):
        mod = _simple_module(
            nerves=(
                _make_nerve("x", line=10),
                _make_nerve("x", line=20),
            ),
        )
        for mode in StrictnessMode:
            errors = validate_module(mod, mode=mode)
            dup_errors = [e for e in errors if e.code == "DUPLICATE_DECLARATION"]
            assert len(dup_errors) >= 1
            assert dup_errors[0].severity == "error"

    def test_invalid_version_always_error(self):
        mod = _simple_module(module_version="bad")
        for mode in StrictnessMode:
            errors = validate_module(mod, mode=mode)
            ver_errors = [e for e in errors if e.code == "INVALID_VERSION"]
            assert len(ver_errors) >= 1
            assert ver_errors[0].severity == "error"


# ===========================================================================
# Error message quality
# ===========================================================================


class TestErrorQuality:
    """All errors must have non-empty remediation and structured context."""

    def test_all_error_codes_have_remediation(self):
        """Every error produced by the validator must have a non-empty remediation."""
        # Construct a module with multiple deliberate violations
        mod = S0maModule(
            module=ModuleDecl(
                name="broken",
                layer=Layer.APPLICATION,
                version="nope",  # INVALID_VERSION
                intent="Deliberately broken",
                exports=("pub_nerve",),
                location=_loc(1),
            ),
            nerves=(
                # VISIBILITY_MISMATCH:
                _make_nerve("pub_nerve", visibility=Visibility.INTERNAL, line=10),
                _make_nerve("dup", line=20),
                _make_nerve("dup", line=30),  # DUPLICATE_DECLARATION
                _make_nerve("bad_kind", kind=Kind.MODEL, line=40),  # INVALID_KIND
                _make_nerve("wrong_layer", layer=Layer.DOMAIN, line=50),  # LAYER_MISMATCH
            ),
        )
        errors = validate_module(mod)
        for err in errors:
            assert err.remediation, f"Error {err.code} at line {err.line} has empty remediation"
            assert len(err.remediation) > 10, (
                f"Error {err.code} remediation is too short: {err.remediation!r}"
            )

    def test_all_errors_have_context(self):
        """Every error should have structured context data."""
        mod = _simple_module(
            module_layer=Layer.APPLICATION,
            nerves=(_make_nerve("n", layer=Layer.DOMAIN),),
        )
        errors = validate_module(mod)
        layer_errors = [e for e in errors if e.code == "LAYER_MISMATCH"]
        assert layer_errors[0].context
        assert "component_layer" in layer_errors[0].context

    def test_errors_include_file_and_line(self):
        mod = _simple_module(
            nerves=(
                _make_nerve("dup", line=10),
                _make_nerve("dup", line=20),
            ),
        )
        errors = validate_module(mod, filename="test.s0ma")
        dup_errors = [e for e in errors if e.code == "DUPLICATE_DECLARATION"]
        assert dup_errors[0].file == "test.s0ma"
        assert dup_errors[0].line == 20  # second occurrence


# ===========================================================================
# Convenience function
# ===========================================================================


class TestValidateModuleFunction:
    """validate_module() convenience function works correctly."""

    def test_returns_empty_for_valid_module(self):
        mod = _simple_module(
            exports=("pub",),
            nerves=(_make_nerve("pub", visibility=Visibility.PUBLIC),),
        )
        errors = validate_module(mod)
        # Filter only semantic errors (not namespace collisions)
        semantic_errors = [
            e for e in errors
            if e.code != "NAMESPACE_COLLISION"
        ]
        assert len(semantic_errors) == 0

    def test_accepts_mode_parameter(self):
        mod = _simple_module()
        errors = validate_module(mod, mode=StrictnessMode.STRICT)
        assert isinstance(errors, list)

    def test_accepts_filename_parameter(self):
        mod = _simple_module(
            module_layer=Layer.APPLICATION,
            nerves=(_make_nerve("n", layer=Layer.DOMAIN),),
        )
        errors = validate_module(mod, filename="myfile.s0ma")
        layer_errors = [e for e in errors if e.code == "LAYER_MISMATCH"]
        assert layer_errors[0].file == "myfile.s0ma"


# ===========================================================================
# Provides field validation
# ===========================================================================


class TestProvidesValidation:
    """Tests for MISSING_PROVIDED_FUNCTION validation."""

    def test_provides_all_present_passes(self):
        nerve = NerveDecl(
            name="svc",
            layer=Layer.APPLICATION,
            kind=Kind.SERVICE,
            visibility=Visibility.INTERNAL,
            intent="Service nerve",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            provides=("read", "write"),
            body="    def read():\n        pass\n    def write():\n        pass",
            location=_loc(5),
        )
        mod = S0maModule(
            module=_make_module(exports=()),
            nerves=(nerve,),
        )
        errors = validate_module(mod)
        provides_errors = [e for e in errors if e.code == "MISSING_PROVIDED_FUNCTION"]
        assert len(provides_errors) == 0

    def test_provides_missing_function_errors(self):
        nerve = NerveDecl(
            name="svc",
            layer=Layer.APPLICATION,
            kind=Kind.SERVICE,
            visibility=Visibility.INTERNAL,
            intent="Service nerve",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            provides=("read", "write"),
            body="    def read():\n        pass",
            location=_loc(5),
        )
        mod = S0maModule(
            module=_make_module(exports=()),
            nerves=(nerve,),
        )
        errors = validate_module(mod)
        provides_errors = [e for e in errors if e.code == "MISSING_PROVIDED_FUNCTION"]
        assert len(provides_errors) == 1
        assert "write" in provides_errors[0].message

    def test_provides_no_body_no_error(self):
        nerve = NerveDecl(
            name="svc",
            layer=Layer.APPLICATION,
            kind=Kind.SERVICE,
            visibility=Visibility.INTERNAL,
            intent="Service nerve",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            provides=("read",),
            body=None,
            location=_loc(5),
        )
        mod = S0maModule(
            module=_make_module(exports=()),
            nerves=(nerve,),
        )
        errors = validate_module(mod)
        provides_errors = [e for e in errors if e.code == "MISSING_PROVIDED_FUNCTION"]
        assert len(provides_errors) == 0

    def test_provides_error_has_remediation(self):
        nerve = NerveDecl(
            name="svc",
            layer=Layer.APPLICATION,
            kind=Kind.SERVICE,
            visibility=Visibility.INTERNAL,
            intent="Service nerve",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            provides=("missing_op",),
            body="    def other_op():\n        pass",
            location=_loc(5),
        )
        mod = S0maModule(
            module=_make_module(exports=()),
            nerves=(nerve,),
        )
        errors = validate_module(mod)
        provides_errors = [e for e in errors if e.code == "MISSING_PROVIDED_FUNCTION"]
        assert len(provides_errors) == 1
        assert "def missing_op" in provides_errors[0].remediation

    def test_provides_empty_list_no_errors(self):
        nerve = NerveDecl(
            name="svc",
            layer=Layer.APPLICATION,
            kind=Kind.SERVICE,
            visibility=Visibility.INTERNAL,
            intent="Service nerve",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            provides=(),
            body="    def svc():\n        pass",
            location=_loc(5),
        )
        mod = S0maModule(
            module=_make_module(exports=()),
            nerves=(nerve,),
        )
        errors = validate_module(mod)
        provides_errors = [e for e in errors if e.code == "MISSING_PROVIDED_FUNCTION"]
        assert len(provides_errors) == 0


# ===========================================================================
# Dogfooding — validator uses @component
# ===========================================================================


class TestHelperNameCollision:
    """Test that duplicate helper function names across test declarations emit a warning."""

    def test_no_collision_single_test(self):
        """A single test declaration should not trigger a warning."""
        mod = _make_module(exports=())
        test = TestDecl(
            name="test_a",
            layer=Layer.APPLICATION,
            intent="Test A",
            tests=("some_nerve",),
            body="def _setup(): pass",
            location=_loc(10),
        )
        module = S0maModule(module=mod, tests=(test,))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        collision_errors = [e for e in errors if e.code == "HELPER_NAME_COLLISION"]
        assert len(collision_errors) == 0

    def test_collision_detected(self):
        """Two test declarations defining the same helper should warn."""
        mod = _make_module(exports=())
        test_a = TestDecl(
            name="test_a",
            layer=Layer.APPLICATION,
            intent="Test A",
            tests=("some_nerve",),
            body="def _setup_env(): pass\ndef _helper(): pass",
            location=_loc(10),
        )
        test_b = TestDecl(
            name="test_b",
            layer=Layer.APPLICATION,
            intent="Test B",
            tests=("other_nerve",),
            body="def _setup_env(): pass",
            location=_loc(20),
        )
        module = S0maModule(module=mod, tests=(test_a, test_b))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        collision_errors = [e for e in errors if e.code == "HELPER_NAME_COLLISION"]
        assert len(collision_errors) == 1
        assert "_setup_env" in collision_errors[0].message
        assert "test_a" in collision_errors[0].message
        assert "test_b" in collision_errors[0].message

    def test_no_collision_different_helpers(self):
        """Different helper names in different tests should not warn."""
        mod = _make_module(exports=())
        test_a = TestDecl(
            name="test_a",
            layer=Layer.APPLICATION,
            intent="Test A",
            tests=("some_nerve",),
            body="def _setup_a(): pass",
            location=_loc(10),
        )
        test_b = TestDecl(
            name="test_b",
            layer=Layer.APPLICATION,
            intent="Test B",
            tests=("other_nerve",),
            body="def _setup_b(): pass",
            location=_loc(20),
        )
        module = S0maModule(module=mod, tests=(test_a, test_b))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        collision_errors = [e for e in errors if e.code == "HELPER_NAME_COLLISION"]
        assert len(collision_errors) == 0

    def test_collision_is_warning_not_error(self):
        """HELPER_NAME_COLLISION should be a warning, not an error."""
        mod = _make_module(exports=())
        test_a = TestDecl(
            name="test_a",
            layer=Layer.APPLICATION,
            intent="Test A",
            tests=("some_nerve",),
            body="def _dup(): pass",
            location=_loc(10),
        )
        test_b = TestDecl(
            name="test_b",
            layer=Layer.APPLICATION,
            intent="Test B",
            tests=("other_nerve",),
            body="def _dup(): pass",
            location=_loc(20),
        )
        module = S0maModule(module=mod, tests=(test_a, test_b))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        collision_errors = [e for e in errors if e.code == "HELPER_NAME_COLLISION"]
        assert len(collision_errors) == 1
        assert collision_errors[0].severity == "warning"

    def test_collision_has_remediation(self):
        """HELPER_NAME_COLLISION warning should include remediation."""
        mod = _make_module(exports=())
        test_a = TestDecl(
            name="test_a",
            layer=Layer.APPLICATION,
            intent="Test A",
            tests=("some_nerve",),
            body="def _dup(): pass",
            location=_loc(10),
        )
        test_b = TestDecl(
            name="test_b",
            layer=Layer.APPLICATION,
            intent="Test B",
            tests=("other_nerve",),
            body="def _dup(): pass",
            location=_loc(20),
        )
        module = S0maModule(module=mod, tests=(test_a, test_b))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        collision_errors = [e for e in errors if e.code == "HELPER_NAME_COLLISION"]
        assert collision_errors[0].remediation
        assert "_dup" in collision_errors[0].remediation

    def test_no_body_no_collision(self):
        """Tests without bodies should not trigger collision checks."""
        mod = _make_module(exports=())
        test_a = TestDecl(
            name="test_a",
            layer=Layer.APPLICATION,
            intent="Test A",
            tests=("some_nerve",),
            body=None,
            location=_loc(10),
        )
        test_b = TestDecl(
            name="test_b",
            layer=Layer.APPLICATION,
            intent="Test B",
            tests=("other_nerve",),
            body=None,
            location=_loc(20),
        )
        module = S0maModule(module=mod, tests=(test_a, test_b))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        collision_errors = [e for e in errors if e.code == "HELPER_NAME_COLLISION"]
        assert len(collision_errors) == 0

    def test_class_methods_do_not_collide(self):
        """def methods inside class bodies must NOT trigger HELPER_NAME_COLLISION.

        Regression for feedback-6 CRIT-1: every HTTP-mocking integration
        defines `class _Recorder` with `__init__`, `__aenter__`, `__aexit__`,
        `request` etc. The pre-M3 regex-based detector treated these as
        module-scope helpers and false-positively warned.
        """
        mod = _make_module(exports=())
        recorder_body = (
            "def test_block_one():\n"
            "    class _Recorder:\n"
            "        def __init__(self, name): self.name = name\n"
            "        async def __aenter__(self): return self\n"
            "        async def __aexit__(self, *exc): return None\n"
            "        def request(self, *args, **kwargs): return None\n"
            "    r = _Recorder('a')\n"
            "    assert r.name == 'a'\n"
        )
        recorder_body_two = recorder_body.replace(
            "test_block_one", "test_block_two"
        ).replace("'a'", "'b'")
        test_a = TestDecl(
            name="test_block_one",
            layer=Layer.APPLICATION,
            intent="first block defines a class with __init__",
            tests=("some_nerve",),
            body=recorder_body,
            location=_loc(10),
        )
        test_b = TestDecl(
            name="test_block_two",
            layer=Layer.APPLICATION,
            intent="second block defines another class with __init__",
            tests=("other_nerve",),
            body=recorder_body_two,
            location=_loc(20),
        )
        module = S0maModule(module=mod, tests=(test_a, test_b))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        collision_errors = [e for e in errors if e.code == "HELPER_NAME_COLLISION"]
        assert len(collision_errors) == 0, (
            f"class methods (__init__, __aenter__, __aexit__, request) "
            f"must not trigger HELPER_NAME_COLLISION, got: "
            f"{[e.message for e in collision_errors]}"
        )

    def test_inner_function_defs_do_not_collide(self):
        """def functions inside other defs must NOT trigger collisions.

        Inner-function closures (factory patterns: `def inner()` inside
        `def factory()`) are scope-isolated and cannot collide across test
        bodies.
        """
        mod = _make_module(exports=())
        factory_body = (
            "def test_block_one():\n"
            "    def _make_adapter():\n"
            "        def prepare_request(req): return req\n"
            "        def send(req): return None\n"
            "        return prepare_request, send\n"
            "    p, s = _make_adapter()\n"
            "    assert p is not None\n"
        )
        factory_body_two = (
            "def test_block_two():\n"
            "    def _make_adapter():\n"
            "        def prepare_request(req): return req\n"
            "        def send(req): return None\n"
            "        return prepare_request, send\n"
            "    p, s = _make_adapter()\n"
            "    assert s is None\n"
        )
        test_a = TestDecl(
            name="test_block_one",
            layer=Layer.APPLICATION,
            intent="first block uses a factory",
            tests=("some_nerve",),
            body=factory_body,
            location=_loc(10),
        )
        test_b = TestDecl(
            name="test_block_two",
            layer=Layer.APPLICATION,
            intent="second block uses the same factory pattern",
            tests=("other_nerve",),
            body=factory_body_two,
            location=_loc(20),
        )
        module = S0maModule(module=mod, tests=(test_a, test_b))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        collision_errors = [e for e in errors if e.code == "HELPER_NAME_COLLISION"]
        # The outer test functions (`test_block_one` / `test_block_two`)
        # are top-level and have distinct names, so they don't collide.
        # The inner `_make_adapter`, `prepare_request`, `send` are scoped
        # inside the outer def and must NOT be flagged.
        assert len(collision_errors) == 0, (
            f"inner-function defs must not trigger HELPER_NAME_COLLISION, "
            f"got: {[e.message for e in collision_errors]}"
        )

    def test_real_top_level_collision_still_fires(self):
        """A genuine top-level def collision must still fire exactly once."""
        mod = _make_module(exports=())
        body_a = (
            "def _setup():\n"
            "    return 1\n"
            "def test_block_one():\n"
            "    assert _setup() == 1\n"
        )
        body_b = (
            "def _setup():\n"
            "    return 2\n"
            "def test_block_two():\n"
            "    assert _setup() == 2\n"
        )
        test_a = TestDecl(
            name="test_block_one",
            layer=Layer.APPLICATION,
            intent="first block defines _setup at top level",
            tests=("some_nerve",),
            body=body_a,
            location=_loc(10),
        )
        test_b = TestDecl(
            name="test_block_two",
            layer=Layer.APPLICATION,
            intent="second block redefines _setup at top level",
            tests=("other_nerve",),
            body=body_b,
            location=_loc(20),
        )
        module = S0maModule(module=mod, tests=(test_a, test_b))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        collision_errors = [
            e for e in errors if e.code == "HELPER_NAME_COLLISION"
        ]
        # Exactly one warning for the colliding name `_setup`.
        # (`test_block_one` and `test_block_two` are distinct, so they
        # don't collide.)
        assert len(collision_errors) == 1
        assert "_setup" in collision_errors[0].message
        assert "module-scope" in collision_errors[0].message

    def test_class_helpers_fixture_validates_clean(self):
        """The class-helpers regression fixture validates with 0 collision warnings.

        This is the end-to-end version of `test_class_methods_do_not_collide`:
        it loads `tests/fixtures/test_with_class_helpers.s0ma` through the
        full parse + validate pipeline (rather than constructing TestDecl
        directly) and asserts zero HELPER_NAME_COLLISION warnings.
        """
        from pathlib import Path

        from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings

        fixture = Path(__file__).parent / "fixtures" / "test_with_class_helpers.s0ma"
        source = fixture.read_text()
        module, warnings = parse_s0ma_with_warnings(
            source, filename=str(fixture), mode=StrictnessMode.STRICT
        )
        errors = validate_module(module, mode=StrictnessMode.STRICT)
        all_diags = list(warnings) + list(errors)
        collision_diags = [d for d in all_diags if d.code == "HELPER_NAME_COLLISION"]
        assert len(collision_diags) == 0, (
            f"fixture must validate with no HELPER_NAME_COLLISION warnings, "
            f"got: {[d.message for d in collision_diags]}"
        )

    def test_async_def_at_top_level_is_flagged(self):
        """async def helpers at top level must be flagged like sync defs."""
        mod = _make_module(exports=())
        body_a = (
            "async def _helper():\n"
            "    return 1\n"
            "def test_block_one():\n"
            "    pass\n"
        )
        body_b = (
            "async def _helper():\n"
            "    return 2\n"
            "def test_block_two():\n"
            "    pass\n"
        )
        test_a = TestDecl(
            name="test_block_one",
            layer=Layer.APPLICATION,
            intent="first block defines async _helper at top level",
            tests=("some_nerve",),
            body=body_a,
            location=_loc(10),
        )
        test_b = TestDecl(
            name="test_block_two",
            layer=Layer.APPLICATION,
            intent="second block redefines async _helper at top level",
            tests=("other_nerve",),
            body=body_b,
            location=_loc(20),
        )
        module = S0maModule(module=mod, tests=(test_a, test_b))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        collision_errors = [
            e for e in errors if e.code == "HELPER_NAME_COLLISION"
        ]
        assert len(collision_errors) == 1
        assert "_helper" in collision_errors[0].message


# ===========================================================================
# MS 11: Abstract nerve validation
# ===========================================================================


class TestAbstractValidation:
    """Validate abstract nerve and interface field rules."""

    def test_interface_on_non_abstract_errors(self):
        """interface field on a non-abstract nerve should error."""
        mod = _make_module(exports=())
        nerve = NerveDecl(
            name="BadNerve",
            layer=Layer.DOMAIN,
            kind=Kind.ADAPTER,
            visibility=Visibility.PUBLIC,
            intent="Nerve with interface but not abstract",
            expects="None",
            guarantees="None",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            interface=("method_a", "method_b"),
            abstract=False,
            body="def BadNerve(): pass",
            location=_loc(10),
        )
        module = S0maModule(module=mod, nerves=(nerve,))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        iface_errors = [e for e in errors if e.code == "INTERFACE_ON_NON_ABSTRACT"]
        assert len(iface_errors) == 1
        assert "BadNerve" in iface_errors[0].message

    def test_abstract_with_interface_no_error(self):
        """An abstract nerve with interface is fine."""
        mod = _make_module(exports=())
        nerve = NerveDecl(
            name="LLMAdapter",
            layer=Layer.INFRASTRUCTURE,
            kind=Kind.ADAPTER,
            visibility=Visibility.PUBLIC,
            intent="Abstract LLM adapter",
            expects="None",
            guarantees="Subclasses implement methods",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            abstract=True,
            interface=("chat", "chat_stream"),
            body=None,
            location=_loc(10),
        )
        module = S0maModule(module=mod, nerves=(nerve,))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        iface_errors = [e for e in errors if e.code == "INTERFACE_ON_NON_ABSTRACT"]
        assert len(iface_errors) == 0

    def test_constructs_missing_interface_methods(self):
        """Concrete nerve CONSTRUCTS abstract but missing methods should error."""
        mod = _make_module(exports=())
        abstract_nerve = NerveDecl(
            name="LLMAdapter",
            layer=Layer.INFRASTRUCTURE,
            kind=Kind.ADAPTER,
            visibility=Visibility.PUBLIC,
            intent="Abstract adapter",
            expects="None",
            guarantees="Interface methods",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            abstract=True,
            interface=("chat", "chat_stream"),
            body=None,
            location=_loc(10),
        )
        concrete_nerve = NerveDecl(
            name="OpenAIAdapter",
            layer=Layer.INFRASTRUCTURE,
            kind=Kind.ADAPTER,
            visibility=Visibility.PUBLIC,
            intent="OpenAI LLM adapter",
            expects="API key",
            guarantees="Implements chat",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            depends_on=(
                InlineAxon(
                    target="LLMAdapter",
                    relation=Relation.CONSTRUCTS,
                    carries="implementation",
                    coupling=Coupling.TIGHT,
                    location=_loc(25),
                ),
            ),
            body="def OpenAIAdapter():\n    def chat(): pass\n    return {\"chat\": chat}",
            location=_loc(20),
        )
        module = S0maModule(module=mod, nerves=(abstract_nerve, concrete_nerve))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        missing_errors = [e for e in errors if e.code == "MISSING_INTERFACE_METHODS"]
        assert len(missing_errors) == 1
        assert "chat_stream" in missing_errors[0].message

    def test_constructs_all_interface_methods_present(self):
        """Concrete nerve implementing all interface methods should pass."""
        mod = _make_module(exports=())
        abstract_nerve = NerveDecl(
            name="LLMAdapter",
            layer=Layer.INFRASTRUCTURE,
            kind=Kind.ADAPTER,
            visibility=Visibility.PUBLIC,
            intent="Abstract adapter",
            expects="None",
            guarantees="Interface methods",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            abstract=True,
            interface=("chat", "chat_stream"),
            body=None,
            location=_loc(10),
        )
        concrete_nerve = NerveDecl(
            name="OpenAIAdapter",
            layer=Layer.INFRASTRUCTURE,
            kind=Kind.ADAPTER,
            visibility=Visibility.PUBLIC,
            intent="OpenAI LLM adapter",
            expects="API key",
            guarantees="Implements both methods",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            depends_on=(
                InlineAxon(
                    target="LLMAdapter",
                    relation=Relation.CONSTRUCTS,
                    carries="implementation",
                    coupling=Coupling.TIGHT,
                    location=_loc(25),
                ),
            ),
            body=(
                "def OpenAIAdapter():\n"
                "    def chat(): pass\n"
                "    def chat_stream(): pass\n"
                "    return {\"chat\": chat, \"chat_stream\": chat_stream}"
            ),
            location=_loc(20),
        )
        module = S0maModule(module=mod, nerves=(abstract_nerve, concrete_nerve))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        missing_errors = [e for e in errors if e.code == "MISSING_INTERFACE_METHODS"]
        assert len(missing_errors) == 0

    def test_constructs_no_body_errors(self):
        """Concrete nerve CONSTRUCTS abstract but has no body at all."""
        mod = _make_module(exports=())
        abstract_nerve = NerveDecl(
            name="Gateway",
            layer=Layer.PRESENTATION,
            kind=Kind.ADAPTER,
            visibility=Visibility.PUBLIC,
            intent="Abstract gateway",
            expects="None",
            guarantees="Interface methods",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            abstract=True,
            interface=("start", "stop"),
            body=None,
            location=_loc(10),
        )
        concrete_nerve = NerveDecl(
            name="CLIGateway",
            layer=Layer.PRESENTATION,
            kind=Kind.ADAPTER,
            visibility=Visibility.PUBLIC,
            intent="CLI gateway",
            expects="None",
            guarantees="Implements gateway",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            depends_on=(
                InlineAxon(
                    target="Gateway",
                    relation=Relation.CONSTRUCTS,
                    carries="implementation",
                    coupling=Coupling.TIGHT,
                    location=_loc(25),
                ),
            ),
            body=None,
            location=_loc(20),
        )
        module = S0maModule(module=mod, nerves=(abstract_nerve, concrete_nerve))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        missing_errors = [e for e in errors if e.code == "MISSING_INTERFACE_METHODS"]
        assert len(missing_errors) == 1
        assert "no body" in missing_errors[0].message


# ===========================================================================
# MS 11: Returns field validation
# ===========================================================================


class TestReturnsValidation:
    """Validate returns field against return-dict keys in the body."""

    def test_missing_return_key_errors(self):
        """Declared returns key not in return dict should error."""
        mod = _make_module(exports=())
        nerve = NerveDecl(
            name="MySvc",
            layer=Layer.DOMAIN,
            kind=Kind.SERVICE,
            visibility=Visibility.PUBLIC,
            intent="Service with returns",
            expects="None",
            guarantees="Returns dict",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            returns=("op_a", "op_b", "op_c"),
            body=(
                'def MySvc():\n'
                '    def op_a(): pass\n'
                '    def op_b(): pass\n'
                '    return {"op_a": op_a, "op_b": op_b}'
            ),
            location=_loc(10),
        )
        module = S0maModule(module=mod, nerves=(nerve,))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        return_errors = [e for e in errors if e.code == "MISSING_RETURN_KEY"]
        assert len(return_errors) == 1
        assert "op_c" in return_errors[0].message

    def test_all_return_keys_present(self):
        """All declared returns keys found in return dict — no error."""
        mod = _make_module(exports=())
        nerve = NerveDecl(
            name="MySvc",
            layer=Layer.DOMAIN,
            kind=Kind.SERVICE,
            visibility=Visibility.PUBLIC,
            intent="Service with returns",
            expects="None",
            guarantees="Returns dict",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            returns=("op_a", "op_b"),
            body=(
                'def MySvc():\n'
                '    def op_a(): pass\n'
                '    def op_b(): pass\n'
                '    return {"op_a": op_a, "op_b": op_b}'
            ),
            location=_loc(10),
        )
        module = S0maModule(module=mod, nerves=(nerve,))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        return_errors = [e for e in errors if e.code == "MISSING_RETURN_KEY"]
        assert len(return_errors) == 0

    def test_no_return_dict_skips_validation(self):
        """Body without return dict pattern — skip validation, no error."""
        mod = _make_module(exports=())
        nerve = NerveDecl(
            name="MySvc",
            layer=Layer.DOMAIN,
            kind=Kind.SERVICE,
            visibility=Visibility.PUBLIC,
            intent="Service with returns but no dict",
            expects="None",
            guarantees="Returns something",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            returns=("op_a",),
            body="def MySvc():\n    return 42",
            location=_loc(10),
        )
        module = S0maModule(module=mod, nerves=(nerve,))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        return_errors = [e for e in errors if e.code == "MISSING_RETURN_KEY"]
        assert len(return_errors) == 0

    def test_empty_returns_no_validation(self):
        """Empty returns field — skip validation."""
        mod = _make_module(exports=())
        nerve = NerveDecl(
            name="MySvc",
            layer=Layer.DOMAIN,
            kind=Kind.SERVICE,
            visibility=Visibility.PUBLIC,
            intent="Service without returns",
            expects="None",
            guarantees="Returns dict",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            returns=(),
            body='def MySvc():\n    return {"op_a": 1}',
            location=_loc(10),
        )
        module = S0maModule(module=mod, nerves=(nerve,))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        return_errors = [e for e in errors if e.code == "MISSING_RETURN_KEY"]
        assert len(return_errors) == 0

    def test_no_body_skips_validation(self):
        """No body — skip returns validation."""
        mod = _make_module(exports=())
        nerve = NerveDecl(
            name="MySvc",
            layer=Layer.DOMAIN,
            kind=Kind.SERVICE,
            visibility=Visibility.PUBLIC,
            intent="Service with returns but no body",
            expects="None",
            guarantees="Returns dict",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            returns=("op_a",),
            body=None,
            location=_loc(10),
        )
        module = S0maModule(module=mod, nerves=(nerve,))
        errors = validate_module(module, mode=StrictnessMode.DEV)
        return_errors = [e for e in errors if e.code == "MISSING_RETURN_KEY"]
        assert len(return_errors) == 0


# ===========================================================================
# Dogfooding — validator uses @component
# ===========================================================================


class TestDogfooding:
    """The validator module itself should be registered as s0ma components."""

    def test_validator_is_registered(self):
        assert hasattr(IntraModuleValidator, "__component__")

    def test_validate_module_is_registered(self):
        from s0ma_dsl.semantic.validator import validate_module
        assert hasattr(validate_module, "__component__")
