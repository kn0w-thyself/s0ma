"""Strictness mode tests for the s0ma DSL transpiler (Milestone 19).

Validates that the four strictness modes (MIGRATION, DEV, STRICT, RELEASE)
produce the correct severity for every rule, and that mode transitions
change error/warning classification as expected.

Tests cover:
- Severity matrix correctness for all 21 error codes across all 4 modes
- Behavioral rules: warning in MIGRATION/DEV, error in STRICT/RELEASE
- Release-only checks: MISSING_TEST_COVERAGE (PUBLIC nerves need tests)
- Release-only checks: non-zero version enforcement
- Mode transitions: upgrading mode escalates warnings to errors
- Integration: inline .s0ma parsing under different modes
"""

from __future__ import annotations

import pytest

from s0ma_dsl.ast_nodes.enums import (
    EvaluatesAt,
    Kind,
    Layer,
    Visibility,
)
from s0ma_dsl.ast_nodes.nodes import (
    CellDecl,
    ModuleDecl,
    NerveDecl,
    RequiresEntry,
    S0maModule,
    SourceLocation,
    StandaloneAxonDecl,
    TestDecl,
    UsesEntry,
)
from s0ma_dsl.config import StrictnessMode, get_severity
from s0ma_dsl.errors import S0maError
from s0ma_dsl.resolver.dependency import DependencyResolver, resolve_dependencies
from s0ma_dsl.semantic.validator import validate_module

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LOC = SourceLocation(start_line=1, start_column=0, end_line=1, end_column=0)


def _make_module(
    name: str = "test_mod",
    version: str = "1.0.0",
    layer: Layer = Layer.DOMAIN,
    exports: tuple[str, ...] = (),
    requires: tuple[RequiresEntry, ...] = (),
    uses: tuple[UsesEntry, ...] = (),
    nerves: tuple[NerveDecl, ...] = (),
    cells: tuple[CellDecl, ...] = (),
    tests: tuple[TestDecl, ...] = (),
    axons: tuple[StandaloneAxonDecl, ...] = (),
) -> S0maModule:
    """Build a S0maModule from parts."""
    return S0maModule(
        module=ModuleDecl(
            name=name,
            layer=layer,
            version=version,
            intent="Test module.",
            exports=exports,
            requires=requires,
            uses=uses,
            location=_LOC,
        ),
        nerves=nerves,
        cells=cells,
        tests=tests,
        axons=axons,
    )


def _make_nerve(
    name: str,
    visibility: Visibility = Visibility.INTERNAL,
    kind: Kind = Kind.FUNCTION,
    layer: Layer = Layer.DOMAIN,
    body: str | None = "def f(): pass",
) -> NerveDecl:
    return NerveDecl(
        name=name,
        layer=layer,
        kind=kind,
        visibility=visibility,
        intent="Test nerve.",
        expects="none",
        guarantees="none",
        evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
        body=body,
        location=_LOC,
    )


def _make_test(
    name: str,
    tests_targets: tuple[str, ...],
    layer: Layer = Layer.DOMAIN,
) -> TestDecl:
    return TestDecl(
        name=name,
        layer=layer,
        intent="Test decl.",
        tests=tests_targets,
        location=_LOC,
    )


def _parse_and_validate(
    source: str,
    mode: StrictnessMode,
    filename: str = "test.s0ma",
) -> list[S0maError]:
    """Parse source text and run semantic validation, returning all diagnostics.

    Uses ``parse_s0ma_with_warnings`` so body-validation warnings
    (PROHIBITED_CONSTRUCT, BARE_IMPORT in MIGRATION/DEV) are included.
    """
    from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings

    errors: list[S0maError] = []
    try:
        module, warnings = parse_s0ma_with_warnings(source, filename, mode)
        errors.extend(warnings)
    except S0maError as e:
        return [e]

    errors.extend(validate_module(module, mode=mode, filename=filename))
    return errors


# ===========================================================================
# Test: Severity Matrix Unit Tests
# ===========================================================================


class TestSeverityMatrixByMode:
    """Verify get_severity returns correct values for all codes and modes."""

    # --- Structural errors: ALWAYS error ---

    @pytest.mark.parametrize("code", [
        "PARSE_ERROR", "MISSING_FIELD", "INVALID_KIND",
        "VISIBILITY_MISMATCH", "LAYER_MISMATCH", "NAMESPACE_COLLISION",
        "INVALID_AXON_RELATION", "INVALID_RAISES_TARGET",
        "DUPLICATE_DECLARATION", "INVALID_VERSION", "CLASS_BODY_IN_NERVE",
        "NOT_EXPORTED", "DOES_NOT_EXIST", "CIRCULAR_DEPENDENCY",
    ])
    @pytest.mark.parametrize("mode", list(StrictnessMode))
    def test_structural_always_error(self, code: str, mode: StrictnessMode):
        assert get_severity(code, mode) == "error"

    # --- Behavioral rules: warning → error ---

    @pytest.mark.parametrize("code", [
        "PROHIBITED_CONSTRUCT", "BARE_IMPORT", "MISSING_PACKAGE",
        "VESTIGIAL_IMPORT", "EMPTY_OBSERVES", "DUPLICATE_AXON",
    ])
    def test_behavioral_warning_in_migration(self, code: str):
        assert get_severity(code, StrictnessMode.MIGRATION) == "warning"

    @pytest.mark.parametrize("code", [
        "PROHIBITED_CONSTRUCT", "BARE_IMPORT", "MISSING_PACKAGE",
        "VESTIGIAL_IMPORT", "EMPTY_OBSERVES", "DUPLICATE_AXON",
    ])
    def test_behavioral_warning_in_dev(self, code: str):
        assert get_severity(code, StrictnessMode.DEV) == "warning"

    @pytest.mark.parametrize("code", [
        "PROHIBITED_CONSTRUCT", "BARE_IMPORT", "MISSING_PACKAGE",
        "VESTIGIAL_IMPORT", "EMPTY_OBSERVES", "DUPLICATE_AXON",
    ])
    def test_behavioral_error_in_strict(self, code: str):
        assert get_severity(code, StrictnessMode.STRICT) == "error"

    @pytest.mark.parametrize("code", [
        "PROHIBITED_CONSTRUCT", "BARE_IMPORT", "MISSING_PACKAGE",
        "VESTIGIAL_IMPORT", "EMPTY_OBSERVES", "DUPLICATE_AXON",
    ])
    def test_behavioral_error_in_release(self, code: str):
        assert get_severity(code, StrictnessMode.RELEASE) == "error"

    # --- Release-only checks ---

    def test_missing_test_coverage_none_in_migration(self):
        assert get_severity("MISSING_TEST_COVERAGE", StrictnessMode.MIGRATION) is None

    def test_missing_test_coverage_none_in_dev(self):
        assert get_severity("MISSING_TEST_COVERAGE", StrictnessMode.DEV) is None

    def test_missing_test_coverage_none_in_strict(self):
        assert get_severity("MISSING_TEST_COVERAGE", StrictnessMode.STRICT) is None

    def test_missing_test_coverage_error_in_release(self):
        assert get_severity("MISSING_TEST_COVERAGE", StrictnessMode.RELEASE) == "error"


# ===========================================================================
# Test: Mode Transitions
# ===========================================================================


class TestModeTransitions:
    """Verify that upgrading strictness mode escalates warnings to errors."""

    BEHAVIORAL_CODES = [
        "PROHIBITED_CONSTRUCT", "BARE_IMPORT", "MISSING_PACKAGE",
        "VESTIGIAL_IMPORT", "EMPTY_OBSERVES", "DUPLICATE_AXON",
    ]

    def test_migration_to_dev_no_change(self):
        """MIGRATION → DEV: behavioral rules stay as warnings."""
        for code in self.BEHAVIORAL_CODES:
            mig = get_severity(code, StrictnessMode.MIGRATION)
            dev = get_severity(code, StrictnessMode.DEV)
            assert mig == dev == "warning", f"{code}: migration={mig}, dev={dev}"

    def test_dev_to_strict_escalates_warnings(self):
        """DEV → STRICT: all behavioral rules escalate to error."""
        for code in self.BEHAVIORAL_CODES:
            dev = get_severity(code, StrictnessMode.DEV)
            strict = get_severity(code, StrictnessMode.STRICT)
            assert dev == "warning" and strict == "error", (
                f"{code}: dev={dev}, strict={strict}"
            )

    def test_strict_to_release_adds_test_coverage(self):
        """STRICT → RELEASE: MISSING_TEST_COVERAGE activates."""
        assert get_severity("MISSING_TEST_COVERAGE", StrictnessMode.STRICT) is None
        assert get_severity("MISSING_TEST_COVERAGE", StrictnessMode.RELEASE) == "error"

    def test_structural_unchanged_across_all_transitions(self):
        """Structural errors remain 'error' through all mode transitions."""
        structural = [
            "PARSE_ERROR", "MISSING_FIELD", "INVALID_KIND",
            "VISIBILITY_MISMATCH", "LAYER_MISMATCH",
        ]
        modes = list(StrictnessMode)
        for code in structural:
            severities = [get_severity(code, m) for m in modes]
            assert all(s == "error" for s in severities), (
                f"{code}: {dict(zip([m.value for m in modes], severities, strict=False))}"
            )


# ===========================================================================
# Test: Behavioral Rules Integration — PROHIBITED_CONSTRUCT
# ===========================================================================


class TestProhibitedConstructByMode:
    """PROHIBITED_CONSTRUCT: warning in migration/dev, error in strict/release.

    All four modes are tested through the full parse pipeline using
    ``parse_s0ma_with_warnings`` (via ``_parse_and_validate``), which
    surfaces body-validation warnings that ``parse_s0ma`` would discard.
    """

    PROHIBITED_S0MA = """\
module prohibited_mod
    layer: DOMAIN
    version: 1.0.0
    intent: "Module with eval()."
    exports: [evil_func]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve evil_func :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Uses eval()."
    expects: "expr: str"
    guarantees: "Returns result"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def evil_func(expr: str):
        return eval(expr)
"""

    def test_migration_produces_warning(self):
        errors = _parse_and_validate(self.PROHIBITED_S0MA, StrictnessMode.MIGRATION)
        prohibited = [e for e in errors if e.code == "PROHIBITED_CONSTRUCT"]
        assert len(prohibited) >= 1
        assert all(e.severity == "warning" for e in prohibited)

    def test_dev_produces_warning(self):
        errors = _parse_and_validate(self.PROHIBITED_S0MA, StrictnessMode.DEV)
        prohibited = [e for e in errors if e.code == "PROHIBITED_CONSTRUCT"]
        assert len(prohibited) >= 1
        assert all(e.severity == "warning" for e in prohibited)

    def test_strict_produces_error(self):
        errors = _parse_and_validate(self.PROHIBITED_S0MA, StrictnessMode.STRICT)
        prohibited = [e for e in errors if e.code == "PROHIBITED_CONSTRUCT"]
        assert len(prohibited) >= 1
        assert all(e.severity == "error" for e in prohibited)

    def test_release_produces_error(self):
        errors = _parse_and_validate(self.PROHIBITED_S0MA, StrictnessMode.RELEASE)
        prohibited = [e for e in errors if e.code == "PROHIBITED_CONSTRUCT"]
        assert len(prohibited) >= 1
        assert all(e.severity == "error" for e in prohibited)


# ===========================================================================
# Test: Behavioral Rules Integration — BARE_IMPORT
# ===========================================================================


class TestBareImportByMode:
    """BARE_IMPORT: warning in migration/dev, error in strict/release.

    All four modes tested through the full parse pipeline.
    """

    BARE_IMPORT_S0MA = """\
module bare_mod
    layer: DOMAIN
    version: 1.0.0
    intent: "Module with bare import in body."
    exports: [import_func]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve import_func :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Has bare import."
    expects: "nothing"
    guarantees: "Returns path"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def import_func():
        import os
        return os.getcwd()
"""

    def test_migration_produces_warning(self):
        errors = _parse_and_validate(self.BARE_IMPORT_S0MA, StrictnessMode.MIGRATION)
        bare = [e for e in errors if e.code == "BARE_IMPORT"]
        assert len(bare) >= 1
        assert all(e.severity == "warning" for e in bare)

    def test_dev_produces_warning(self):
        errors = _parse_and_validate(self.BARE_IMPORT_S0MA, StrictnessMode.DEV)
        bare = [e for e in errors if e.code == "BARE_IMPORT"]
        assert len(bare) >= 1
        assert all(e.severity == "warning" for e in bare)

    def test_strict_produces_error(self):
        errors = _parse_and_validate(self.BARE_IMPORT_S0MA, StrictnessMode.STRICT)
        bare = [e for e in errors if e.code == "BARE_IMPORT"]
        assert len(bare) >= 1
        assert all(e.severity == "error" for e in bare)

    def test_release_produces_error(self):
        errors = _parse_and_validate(self.BARE_IMPORT_S0MA, StrictnessMode.RELEASE)
        bare = [e for e in errors if e.code == "BARE_IMPORT"]
        assert len(bare) >= 1
        assert all(e.severity == "error" for e in bare)


# ===========================================================================
# Test: Release-Mode — MISSING_TEST_COVERAGE
# ===========================================================================


class TestMissingTestCoverage:
    """MISSING_TEST_COVERAGE fires only in release mode for uncovered PUBLIC nerves."""

    def _make_project_with_uncovered_nerve(self) -> dict[str, S0maModule]:
        """Create a project with a PUBLIC nerve that has no test."""
        nerve = _make_nerve("public_func", visibility=Visibility.PUBLIC)
        mod = _make_module(
            name="mymod",
            exports=("public_func",),
            nerves=(nerve,),
        )
        return {"mymod": mod}

    def _make_project_with_covered_nerve(self) -> dict[str, S0maModule]:
        """Create a project with a PUBLIC nerve that has test coverage."""
        nerve = _make_nerve("public_func", visibility=Visibility.PUBLIC)
        test = _make_test("test_public_func", tests_targets=("public_func",))
        mod = _make_module(
            name="mymod",
            exports=("public_func",),
            nerves=(nerve,),
            tests=(test,),
        )
        return {"mymod": mod}

    def _make_project_with_cross_module_coverage(self) -> dict[str, S0maModule]:
        """A's PUBLIC nerve is covered by B's test."""
        nerve_a = _make_nerve("api_endpoint", visibility=Visibility.PUBLIC)
        mod_a = _make_module(
            name="api",
            exports=("api_endpoint",),
            nerves=(nerve_a,),
        )
        test_b = _make_test("test_api", tests_targets=("api_endpoint",))
        mod_b = _make_module(
            name="api_tests",
            tests=(test_b,),
            uses=(UsesEntry(qualified_name="api.api_endpoint", location=_LOC),),
        )
        return {"api": mod_a, "api_tests": mod_b}

    def test_uncovered_nerve_error_in_release(self):
        modules = self._make_project_with_uncovered_nerve()
        resolver = DependencyResolver(mode=StrictnessMode.RELEASE)
        errors = resolver.resolve(modules, check_imports=False)
        coverage_errors = [e for e in errors if e.code == "MISSING_TEST_COVERAGE"]
        assert len(coverage_errors) == 1
        assert coverage_errors[0].severity == "error"
        assert "public_func" in coverage_errors[0].message

    def test_uncovered_nerve_silent_in_strict(self):
        modules = self._make_project_with_uncovered_nerve()
        resolver = DependencyResolver(mode=StrictnessMode.STRICT)
        errors = resolver.resolve(modules, check_imports=False)
        coverage_errors = [e for e in errors if e.code == "MISSING_TEST_COVERAGE"]
        assert len(coverage_errors) == 0

    def test_uncovered_nerve_silent_in_dev(self):
        modules = self._make_project_with_uncovered_nerve()
        resolver = DependencyResolver(mode=StrictnessMode.DEV)
        errors = resolver.resolve(modules, check_imports=False)
        coverage_errors = [e for e in errors if e.code == "MISSING_TEST_COVERAGE"]
        assert len(coverage_errors) == 0

    def test_uncovered_nerve_silent_in_migration(self):
        modules = self._make_project_with_uncovered_nerve()
        resolver = DependencyResolver(mode=StrictnessMode.MIGRATION)
        errors = resolver.resolve(modules, check_imports=False)
        coverage_errors = [e for e in errors if e.code == "MISSING_TEST_COVERAGE"]
        assert len(coverage_errors) == 0

    def test_covered_nerve_no_error_in_release(self):
        modules = self._make_project_with_covered_nerve()
        resolver = DependencyResolver(mode=StrictnessMode.RELEASE)
        errors = resolver.resolve(modules, check_imports=False)
        coverage_errors = [e for e in errors if e.code == "MISSING_TEST_COVERAGE"]
        assert len(coverage_errors) == 0

    def test_internal_nerve_not_checked(self):
        """INTERNAL nerves are exempt from test coverage requirements."""
        nerve = _make_nerve("helper", visibility=Visibility.INTERNAL)
        mod = _make_module(name="mymod", nerves=(nerve,))
        modules = {"mymod": mod}
        resolver = DependencyResolver(mode=StrictnessMode.RELEASE)
        errors = resolver.resolve(modules, check_imports=False)
        coverage_errors = [e for e in errors if e.code == "MISSING_TEST_COVERAGE"]
        assert len(coverage_errors) == 0

    def test_cross_module_coverage_accepted(self):
        """A test in module B covers a PUBLIC nerve in module A."""
        modules = self._make_project_with_cross_module_coverage()
        resolver = DependencyResolver(mode=StrictnessMode.RELEASE)
        errors = resolver.resolve(modules, check_imports=False)
        coverage_errors = [e for e in errors if e.code == "MISSING_TEST_COVERAGE"]
        assert len(coverage_errors) == 0

    def test_multiple_uncovered_nerves(self):
        """All uncovered PUBLIC nerves produce individual errors."""
        n1 = _make_nerve("func_a", visibility=Visibility.PUBLIC)
        n2 = _make_nerve("func_b", visibility=Visibility.PUBLIC)
        n3 = _make_nerve("helper", visibility=Visibility.INTERNAL)
        mod = _make_module(
            name="mymod",
            exports=("func_a", "func_b"),
            nerves=(n1, n2, n3),
        )
        modules = {"mymod": mod}
        resolver = DependencyResolver(mode=StrictnessMode.RELEASE)
        errors = resolver.resolve(modules, check_imports=False)
        coverage_errors = [e for e in errors if e.code == "MISSING_TEST_COVERAGE"]
        assert len(coverage_errors) == 2
        names = {e.context["nerve"] for e in coverage_errors}
        assert names == {"func_a", "func_b"}

    def test_error_has_actionable_remediation(self):
        modules = self._make_project_with_uncovered_nerve()
        resolver = DependencyResolver(mode=StrictnessMode.RELEASE)
        errors = resolver.resolve(modules, check_imports=False)
        coverage_errors = [e for e in errors if e.code == "MISSING_TEST_COVERAGE"]
        assert len(coverage_errors) == 1
        assert "test declaration" in coverage_errors[0].remediation.lower()
        assert "public_func" in coverage_errors[0].remediation


# ===========================================================================
# Test: Release-Mode — Non-Zero Version
# ===========================================================================


class TestNonZeroVersionRelease:
    """Version 0.0.0 is rejected in release mode only."""

    def test_zero_version_error_in_release(self):
        mod = _make_module(name="mymod", version="0.0.0")
        errors = validate_module(mod, mode=StrictnessMode.RELEASE, filename="test.s0ma")
        version_errors = [e for e in errors if e.code == "INVALID_VERSION"]
        assert len(version_errors) == 1
        assert "0.0.0" in version_errors[0].message
        assert "release" in version_errors[0].message.lower()

    def test_zero_version_ok_in_strict(self):
        mod = _make_module(name="mymod", version="0.0.0")
        errors = validate_module(mod, mode=StrictnessMode.STRICT, filename="test.s0ma")
        version_errors = [e for e in errors if e.code == "INVALID_VERSION"]
        assert len(version_errors) == 0

    def test_zero_version_ok_in_dev(self):
        mod = _make_module(name="mymod", version="0.0.0")
        errors = validate_module(mod, mode=StrictnessMode.DEV, filename="test.s0ma")
        version_errors = [e for e in errors if e.code == "INVALID_VERSION"]
        assert len(version_errors) == 0

    def test_zero_version_ok_in_migration(self):
        mod = _make_module(name="mymod", version="0.0.0")
        errors = validate_module(mod, mode=StrictnessMode.MIGRATION, filename="test.s0ma")
        version_errors = [e for e in errors if e.code == "INVALID_VERSION"]
        assert len(version_errors) == 0

    def test_nonzero_version_ok_in_release(self):
        mod = _make_module(name="mymod", version="1.0.0")
        errors = validate_module(mod, mode=StrictnessMode.RELEASE, filename="test.s0ma")
        version_errors = [e for e in errors if e.code == "INVALID_VERSION"]
        assert len(version_errors) == 0

    def test_nonzero_minor_ok_in_release(self):
        """0.1.0 is valid — only 0.0.0 is blocked."""
        mod = _make_module(name="mymod", version="0.1.0")
        errors = validate_module(mod, mode=StrictnessMode.RELEASE, filename="test.s0ma")
        version_errors = [e for e in errors if e.code == "INVALID_VERSION"]
        assert len(version_errors) == 0

    def test_error_has_actionable_remediation(self):
        mod = _make_module(name="mymod", version="0.0.0")
        errors = validate_module(mod, mode=StrictnessMode.RELEASE, filename="test.s0ma")
        version_errors = [e for e in errors if e.code == "INVALID_VERSION"]
        assert len(version_errors) == 1
        assert "non-zero" in version_errors[0].remediation.lower()


# ===========================================================================
# Test: Structural Errors Unchanged Across Modes
# ===========================================================================


class TestStructuralErrorsAcrossModes:
    """Structural errors are always 'error' regardless of strictness mode."""

    INVALID_KIND_S0MA = """\
module struct_mod
    layer: DOMAIN
    version: 1.0.0
    intent: "Module with wrong kind."
    exports: [bad_nerve]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve bad_nerve :: DOMAIN
    kind: EXCEPTION
    visibility: PUBLIC
    intent: "EXCEPTION is not valid for nerves."
    expects: "none"
    guarantees: "none"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def bad_nerve():
        pass
"""

    @pytest.mark.parametrize("mode", list(StrictnessMode))
    def test_invalid_kind_always_error(self, mode: StrictnessMode):
        errors = _parse_and_validate(self.INVALID_KIND_S0MA, mode)
        kind_errors = [e for e in errors if e.code == "INVALID_KIND"]
        assert len(kind_errors) >= 1
        assert all(e.severity == "error" for e in kind_errors)

    DUPLICATE_S0MA = """\
module dup_mod
    layer: DOMAIN
    version: 1.0.0
    intent: "Module with duplicate names."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve helper :: DOMAIN
    kind: FUNCTION
    visibility: INTERNAL
    intent: "First."
    expects: "none"
    guarantees: "none"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def helper():
        pass

nerve helper :: DOMAIN
    kind: FUNCTION
    visibility: INTERNAL
    intent: "Duplicate."
    expects: "none"
    guarantees: "none"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def helper():
        pass
"""

    @pytest.mark.parametrize("mode", list(StrictnessMode))
    def test_duplicate_declaration_always_error(self, mode: StrictnessMode):
        errors = _parse_and_validate(self.DUPLICATE_S0MA, mode)
        dup_errors = [e for e in errors if e.code == "DUPLICATE_DECLARATION"]
        assert len(dup_errors) >= 1
        assert all(e.severity == "error" for e in dup_errors)


# ===========================================================================
# Test: Convenience Function resolve_dependencies
# ===========================================================================


class TestResolveDependenciesConvenience:
    """The resolve_dependencies function respects strictness mode."""

    def test_release_mode_detects_missing_coverage(self):
        nerve = _make_nerve("pub", visibility=Visibility.PUBLIC)
        mod = _make_module(name="m", exports=("pub",), nerves=(nerve,))
        errors = resolve_dependencies(
            {"m": mod}, mode=StrictnessMode.RELEASE, check_imports=False,
        )
        coverage = [e for e in errors if e.code == "MISSING_TEST_COVERAGE"]
        assert len(coverage) == 1

    def test_dev_mode_skips_coverage_check(self):
        nerve = _make_nerve("pub", visibility=Visibility.PUBLIC)
        mod = _make_module(name="m", exports=("pub",), nerves=(nerve,))
        errors = resolve_dependencies(
            {"m": mod}, mode=StrictnessMode.DEV, check_imports=False,
        )
        coverage = [e for e in errors if e.code == "MISSING_TEST_COVERAGE"]
        assert len(coverage) == 0


# ===========================================================================
# Test: Complete Mode Spectrum for a Single Rule
# ===========================================================================


class TestVestigialImportSpectrum:
    """End-to-end test of VESTIGIAL_IMPORT across all four modes."""

    def _make_module_with_vestigial_uses(self) -> tuple[dict[str, S0maModule], dict[str, str]]:
        """Create two modules where one has a vestigial uses entry."""
        nerve_a = _make_nerve("api_func", visibility=Visibility.PUBLIC)
        mod_a = _make_module(
            name="provider",
            exports=("api_func",),
            nerves=(nerve_a,),
        )
        # mod_b uses provider.api_func but never references it
        nerve_b = _make_nerve("unrelated", body="def unrelated(): return 42")
        mod_b = _make_module(
            name="consumer",
            nerves=(nerve_b,),
            uses=(UsesEntry(qualified_name="provider.api_func", location=_LOC),),
        )
        modules = {"provider": mod_a, "consumer": mod_b}
        filenames = {"provider": "provider.s0ma", "consumer": "consumer.s0ma"}
        return modules, filenames

    def test_migration_produces_warning(self):
        modules, filenames = self._make_module_with_vestigial_uses()
        resolver = DependencyResolver(mode=StrictnessMode.MIGRATION)
        errors = resolver.resolve(modules, filenames, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"]
        assert len(vestigial) >= 1
        assert all(e.severity == "warning" for e in vestigial)

    def test_dev_produces_warning(self):
        modules, filenames = self._make_module_with_vestigial_uses()
        resolver = DependencyResolver(mode=StrictnessMode.DEV)
        errors = resolver.resolve(modules, filenames, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"]
        assert len(vestigial) >= 1
        assert all(e.severity == "warning" for e in vestigial)

    def test_strict_produces_error(self):
        modules, filenames = self._make_module_with_vestigial_uses()
        resolver = DependencyResolver(mode=StrictnessMode.STRICT)
        errors = resolver.resolve(modules, filenames, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"]
        assert len(vestigial) >= 1
        assert all(e.severity == "error" for e in vestigial)

    def test_release_produces_error(self):
        modules, filenames = self._make_module_with_vestigial_uses()
        resolver = DependencyResolver(mode=StrictnessMode.RELEASE)
        errors = resolver.resolve(modules, filenames, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"]
        assert len(vestigial) >= 1
        assert all(e.severity == "error" for e in vestigial)
