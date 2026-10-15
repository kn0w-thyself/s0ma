"""Smoke tests for Milestone 1 — verify toolchain, imports, and fixtures."""

from __future__ import annotations

from tests.conftest import VALID_FIXTURES_DIR

# ---------------------------------------------------------------------------
# Toolchain imports
# ---------------------------------------------------------------------------

def test_lark_importable():
    """Lark is installed and can parse a trivial grammar."""
    from lark import Lark

    grammar = r'''
    start: "hello" NAME
    NAME: /\w+/
    %ignore /\s+/
    '''
    parser = Lark(grammar, parser="lalr")
    tree = parser.parse("hello world")
    assert tree.data == "start"


def test_s0ma_dsl_package_importable():
    """The s0ma_dsl package is importable."""
    import s0ma_dsl
    assert s0ma_dsl.__doc__ is not None


def test_s0ma_dsl_errors_importable():
    """The errors module is importable and contains the expected types."""
    from s0ma_dsl.errors import (
        S0maError,
        S0maParseError,
        S0maResolutionError,
        S0maSemanticError,
    )
    assert issubclass(S0maParseError, S0maError)
    assert issubclass(S0maSemanticError, S0maError)
    assert issubclass(S0maResolutionError, S0maError)


def test_s0ma_dsl_config_importable():
    """The config module is importable and contains the expected types."""
    from s0ma_dsl.config import (
        SEVERITY_MATRIX,
        StrictnessMode,
    )
    assert len(StrictnessMode) == 4
    assert "PARSE_ERROR" in SEVERITY_MATRIX


def test_s0ma_framework_importable():
    """The s0ma framework is installed and core imports work."""
    from s0ma.decorators import component, internal
    from s0ma.types import ComponentKind, Layer

    assert component is not None
    assert internal is not None
    assert hasattr(ComponentKind, "SERVICE")
    assert hasattr(Layer, "FRAMEWORK")


# ---------------------------------------------------------------------------
# Error system
# ---------------------------------------------------------------------------

def test_s0ma_error_construction():
    """S0maError can be constructed with all required fields."""
    from s0ma_dsl.errors import S0maError

    err = S0maError(
        code="TEST_CODE",
        message="Something went wrong",
        file="example.s0ma",
        line=10,
        column=5,
        severity="error",
        remediation="Add the missing 'intent' field to the nerve declaration.",
    )
    assert err.code == "TEST_CODE"
    assert err.severity == "error"
    assert "intent" in err.remediation


def test_s0ma_error_format_text():
    """S0maError.format_text() produces human-readable output."""
    from s0ma_dsl.errors import S0maError

    err = S0maError(
        code="MISSING_FIELD",
        message="Required field 'intent' is missing.",
        file="mymodule.s0ma",
        line=3,
        column=0,
        severity="error",
        remediation="Add an 'intent' field with a description of the component's purpose.",
    )
    text = err.format_text()
    assert "mymodule.s0ma:3" in text
    assert "ERROR" in text
    assert "MISSING_FIELD" in text
    assert "Remediation:" in text


def test_s0ma_error_to_dict():
    """S0maError.to_dict() produces a JSON-compatible dictionary."""
    from s0ma_dsl.errors import S0maError

    err = S0maError(
        code="TEST",
        message="test",
        file="t.s0ma",
        line=1,
        column=0,
        severity="warning",
        remediation="Do something.",
        context={"expected": "PUBLIC", "actual": "INTERNAL"},
    )
    d = err.to_dict()
    assert d["code"] == "TEST"
    assert d["context"]["expected"] == "PUBLIC"


def test_s0ma_error_is_frozen():
    """S0maError instances are immutable (frozen dataclass)."""
    import pytest

    from s0ma_dsl.errors import S0maError

    err = S0maError(
        code="X", message="x", file="x.s0ma",
        line=1, column=0, severity="error", remediation="x",
    )
    with pytest.raises(AttributeError):
        err.code = "Y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Config system
# ---------------------------------------------------------------------------

def test_severity_matrix_structural_errors_always_error():
    """Structural errors are 'error' in all strictness modes."""
    from s0ma_dsl.config import StrictnessMode, get_severity

    structural_codes = [
        "PARSE_ERROR", "MISSING_FIELD", "INVALID_KIND",
        "VISIBILITY_MISMATCH", "LAYER_MISMATCH",
    ]
    for code in structural_codes:
        for mode in StrictnessMode:
            assert get_severity(code, mode) == "error", (
                f"{code} should be 'error' in {mode.value}"
            )


def test_severity_matrix_behavioral_rules_vary():
    """Behavioral rules are 'warning' in migration/dev, 'error' in strict/release."""
    from s0ma_dsl.config import StrictnessMode, get_severity

    behavioral_codes = [
        "PROHIBITED_CONSTRUCT", "BARE_IMPORT",
        "MISSING_PACKAGE", "VESTIGIAL_IMPORT",
    ]
    for code in behavioral_codes:
        assert get_severity(code, StrictnessMode.MIGRATION) == "warning"
        assert get_severity(code, StrictnessMode.DEV) == "warning"
        assert get_severity(code, StrictnessMode.STRICT) == "error"
        assert get_severity(code, StrictnessMode.RELEASE) == "error"


def test_severity_matrix_release_only():
    """MISSING_TEST_COVERAGE is only an error in release mode."""
    from s0ma_dsl.config import StrictnessMode, get_severity

    assert get_severity("MISSING_TEST_COVERAGE", StrictnessMode.MIGRATION) is None
    assert get_severity("MISSING_TEST_COVERAGE", StrictnessMode.DEV) is None
    assert get_severity("MISSING_TEST_COVERAGE", StrictnessMode.STRICT) is None
    assert get_severity("MISSING_TEST_COVERAGE", StrictnessMode.RELEASE) == "error"


def test_transpiler_config_defaults():
    """TranspilerConfig has sensible defaults."""
    from s0ma_dsl.config import StrictnessMode, TranspilerConfig

    cfg = TranspilerConfig()
    assert cfg.mode == StrictnessMode.DEV
    assert cfg.emit_ir is True
    assert cfg.emit_source_map is True
    assert cfg.output_format == "text"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def test_golden_fixture_exists():
    """The signal_processor.s0ma golden fixture exists."""
    fixture = VALID_FIXTURES_DIR / "signal_processor.s0ma"
    assert fixture.exists(), f"Golden fixture not found at {fixture}"
    content = fixture.read_text()
    assert "module signal_processor" in content
    assert "nerve process_signal" in content
    assert "cell SignalEnvelope" in content


# ---------------------------------------------------------------------------
# Dogfooding: @component decorators applied
# ---------------------------------------------------------------------------

def test_errors_module_has_component_decorators():
    """Error classes have __component__ attributes from @component."""
    from s0ma_dsl.errors import S0maError, S0maParseError

    assert hasattr(S0maError, "__component__"), (
        "S0maError should be decorated with @component"
    )
    assert hasattr(S0maParseError, "__component__"), (
        "S0maParseError should be decorated with @component"
    )


def test_config_module_has_component_decorators():
    """Config classes have __component__ attributes from @component."""
    from s0ma_dsl.config import StrictnessMode, TranspilerConfig

    assert hasattr(StrictnessMode, "__component__"), (
        "StrictnessMode should be decorated with @component"
    )
    assert hasattr(TranspilerConfig, "__component__"), (
        "TranspilerConfig should be decorated with @component"
    )
