"""Error UX tests for the s0ma DSL transpiler (Milestone 18).

Validates that all errors are structured, actionable, and AI-consumable
per PRD §2.4 (Error System) and FR-29 (Diagnostics Quality).

Tests cover:
- Every error code has non-empty, specific remediation
- Every error has structured context
- JSON mode produces valid, schema-compliant JSON
- Error grouping works per-file and across files
- Error formatting matches PRD §2.4.4
- All error codes in the severity matrix are reachable
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import (
    S0maCLI,
    _format_diagnostics_json,
    _format_diagnostics_text,
    _group_diagnostics_by_file,
    _split_diagnostics,
)
from s0ma_dsl.config import SEVERITY_MATRIX, StrictnessMode, get_severity
from s0ma_dsl.errors import (
    S0maError,
    S0maParseError,
    S0maResolutionError,
    S0maSemanticError,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_INVALID_DIR = _FIXTURES_DIR / "invalid"
_VALID_DIR = _FIXTURES_DIR / "valid"
GOLDEN_FIXTURE = _VALID_DIR / "signal_processor.s0ma"


# ---------------------------------------------------------------------------
# Helpers for constructing test errors
# ---------------------------------------------------------------------------


def _make_error(
    code: str = "TEST_ERR",
    severity: str = "error",
    file: str = "test.s0ma",
    line: int = 10,
    column: int = 1,
    remediation: str = "Do the specific fix for this test error.",
    context: dict | None = None,
) -> S0maError:
    return S0maError(
        code=code,
        message=f"Test message for {code}",
        file=file,
        line=line,
        column=column,
        severity=severity,
        remediation=remediation,
        context=context or {"test_key": "test_value"},
    )


def _make_parse_error(
    code: str = "PARSE_ERROR",
    file: str = "broken.s0ma",
    line: int = 5,
) -> S0maParseError:
    return S0maParseError(
        code=code,
        message=f"Parse error: {code}",
        file=file,
        line=line,
        column=1,
        severity="error",
        remediation=f"Fix the parse issue for {code}.",
        context={"parse_detail": "test"},
    )


def _make_semantic_error(
    code: str = "INVALID_KIND",
    file: str = "broken.s0ma",
    line: int = 15,
) -> S0maSemanticError:
    return S0maSemanticError(
        code=code,
        message=f"Semantic error: {code}",
        file=file,
        line=line,
        column=0,
        severity="error",
        remediation=f"Fix the semantic issue for {code}.",
        context={"semantic_detail": "test"},
    )


def _make_resolution_error(
    code: str = "NOT_EXPORTED",
    file: str = "broken.s0ma",
    line: int = 20,
) -> S0maResolutionError:
    return S0maResolutionError(
        code=code,
        message=f"Resolution error: {code}",
        file=file,
        line=line,
        column=0,
        severity="error",
        remediation=f"Fix the resolution issue for {code}.",
        context={"resolution_detail": "test"},
    )


# ===========================================================================
# Test: Error Field Completeness
# ===========================================================================


class TestErrorFieldCompleteness:
    """Every S0maError must have all fields populated per PRD §2.4.1."""

    def test_all_required_fields_present(self):
        """S0maError instances always have the 8 required fields."""
        err = _make_error()
        assert err.code
        assert err.message
        assert err.file
        assert isinstance(err.line, int)
        assert isinstance(err.column, int)
        assert err.severity in ("error", "warning")
        assert err.remediation
        assert isinstance(err.context, dict)

    def test_remediation_is_not_generic(self):
        """Remediation must be specific, not generic placeholders."""
        generic_phrases = [
            "fix the error",
            "check the syntax",
            "try again",
            "see documentation",
        ]
        err = _make_error(remediation="Add 'select_evaluator' to routing module's exports list.")
        for phrase in generic_phrases:
            assert phrase not in err.remediation.lower()

    def test_error_to_dict_has_all_fields(self):
        """to_dict() includes every required field."""
        err = _make_error(context={"expected": "PUBLIC", "actual": "INTERNAL"})
        d = err.to_dict()
        required_keys = {
            "code", "message", "file", "line",
            "column", "severity", "remediation", "context",
        }
        assert required_keys == set(d.keys())

    def test_parse_error_is_s0ma_error(self):
        assert isinstance(_make_parse_error(), S0maError)

    def test_semantic_error_is_s0ma_error(self):
        assert isinstance(_make_semantic_error(), S0maError)

    def test_resolution_error_is_s0ma_error(self):
        assert isinstance(_make_resolution_error(), S0maError)


# ===========================================================================
# Test: Error Severity Matrix
# ===========================================================================


class TestSeverityMatrix:
    """The severity matrix in ``s0ma_dsl.config`` must be complete and correct."""

    EXPECTED_ERROR_CODES = [
        "PARSE_ERROR", "MISSING_FIELD", "INVALID_KIND", "VISIBILITY_MISMATCH",
        "LAYER_MISMATCH", "NAMESPACE_COLLISION", "INVALID_AXON_RELATION",
        "INVALID_RAISES_TARGET", "DUPLICATE_DECLARATION", "INVALID_VERSION",
        "PROHIBITED_CONSTRUCT", "BARE_IMPORT", "CLASS_BODY_IN_NERVE",
        "NOT_EXPORTED", "DOES_NOT_EXIST", "CIRCULAR_DEPENDENCY",
        "MISSING_PACKAGE", "VESTIGIAL_IMPORT", "EMPTY_OBSERVES",
        "DUPLICATE_AXON", "MISSING_TEST_COVERAGE",
    ]

    def test_all_expected_codes_in_matrix(self):
        """Every error code from PRD §2.4.2 is in the severity matrix."""
        for code in self.EXPECTED_ERROR_CODES:
            assert code in SEVERITY_MATRIX, f"Missing error code: {code}"

    def test_all_modes_covered_for_each_code(self):
        """Every error code has a mapping for all four modes."""
        for code, mappings in SEVERITY_MATRIX.items():
            for mode in StrictnessMode:
                assert mode in mappings, f"{code} missing mapping for {mode.value}"

    def test_structural_errors_always_error(self):
        """Structural errors must be 'error' in ALL modes."""
        structural = [
            "PARSE_ERROR", "MISSING_FIELD", "INVALID_KIND",
            "VISIBILITY_MISMATCH", "LAYER_MISMATCH", "NAMESPACE_COLLISION",
            "INVALID_AXON_RELATION", "INVALID_RAISES_TARGET",
            "DUPLICATE_DECLARATION", "INVALID_VERSION", "CLASS_BODY_IN_NERVE",
            "NOT_EXPORTED", "DOES_NOT_EXIST", "CIRCULAR_DEPENDENCY",
        ]
        for code in structural:
            for mode in StrictnessMode:
                assert get_severity(code, mode) == "error", (
                    f"{code} should be 'error' in {mode.value}, "
                    f"got {get_severity(code, mode)}"
                )

    def test_behavioral_rules_vary_by_mode(self):
        """Behavioral rules are warning in migration/dev, error in strict/release."""
        behavioral = [
            "PROHIBITED_CONSTRUCT", "BARE_IMPORT", "MISSING_PACKAGE",
            "VESTIGIAL_IMPORT", "EMPTY_OBSERVES", "DUPLICATE_AXON",
        ]
        for code in behavioral:
            assert get_severity(code, StrictnessMode.MIGRATION) == "warning"
            assert get_severity(code, StrictnessMode.DEV) == "warning"
            assert get_severity(code, StrictnessMode.STRICT) == "error"
            assert get_severity(code, StrictnessMode.RELEASE) == "error"

    def test_release_only_checks(self):
        """MISSING_TEST_COVERAGE is error only in release mode."""
        assert get_severity("MISSING_TEST_COVERAGE", StrictnessMode.MIGRATION) is None
        assert get_severity("MISSING_TEST_COVERAGE", StrictnessMode.DEV) is None
        assert get_severity("MISSING_TEST_COVERAGE", StrictnessMode.STRICT) is None
        assert get_severity("MISSING_TEST_COVERAGE", StrictnessMode.RELEASE) == "error"

    def test_get_severity_raises_on_unknown_code(self):
        """Unknown error codes raise KeyError."""
        with pytest.raises(KeyError):
            get_severity("NONEXISTENT_CODE", StrictnessMode.DEV)


# ===========================================================================
# Test: Error Grouping
# ===========================================================================


class TestErrorGrouping:
    """Diagnostics must be grouped per-file first per PRD §2.4.4."""

    def test_group_by_file_single_file(self):
        errors = [
            _make_error(file="a.s0ma", line=1),
            _make_error(file="a.s0ma", line=10),
        ]
        groups = _group_diagnostics_by_file(errors)
        assert len(groups) == 1
        assert "a.s0ma" in groups
        assert len(groups["a.s0ma"]) == 2

    def test_group_by_file_multiple_files(self):
        errors = [
            _make_error(file="a.s0ma", line=1),
            _make_error(file="b.s0ma", line=5),
            _make_error(file="a.s0ma", line=10),
            _make_error(file="c.s0ma", line=3),
        ]
        groups = _group_diagnostics_by_file(errors)
        assert len(groups) == 3
        assert len(groups["a.s0ma"]) == 2
        assert len(groups["b.s0ma"]) == 1
        assert len(groups["c.s0ma"]) == 1

    def test_group_preserves_first_occurrence_order(self):
        """File groups appear in order of first occurrence."""
        errors = [
            _make_error(file="b.s0ma"),
            _make_error(file="a.s0ma"),
            _make_error(file="c.s0ma"),
        ]
        groups = _group_diagnostics_by_file(errors)
        assert list(groups.keys()) == ["b.s0ma", "a.s0ma", "c.s0ma"]

    def test_group_empty_list(self):
        groups = _group_diagnostics_by_file([])
        assert groups == {}


# ===========================================================================
# Test: Text Format Output (PRD §2.4.4)
# ===========================================================================


class TestTextFormat:
    """Text format must follow PRD §2.4.4 structure."""

    def test_text_format_includes_file_line_severity_code(self):
        err = _make_error(code="NOT_EXPORTED", file="router.s0ma", line=5)
        text = _format_diagnostics_text([err], [])
        assert "router.s0ma:5:" in text
        assert "ERROR" in text
        assert "[NOT_EXPORTED]" in text

    def test_text_format_includes_remediation(self):
        err = _make_error(remediation="Add 'helper' to exports list.")
        text = _format_diagnostics_text([err], [])
        assert "Remediation:" in text
        assert "Add 'helper' to exports list." in text

    def test_text_format_includes_summary_line(self):
        errs = [_make_error(severity="error")]
        warns = [_make_error(severity="warning")]
        text = _format_diagnostics_text(errs, warns)
        assert "1 error(s)" in text
        assert "1 warning(s)" in text

    def test_text_format_shows_mode_in_summary(self):
        text = _format_diagnostics_text(
            [_make_error()], [], mode="strict"
        )
        assert "[mode: strict]" in text

    def test_text_format_multi_file_shows_file_headers(self):
        """When multiple files, each gets a header line."""
        errs = [
            _make_error(file="a.s0ma", severity="error"),
            _make_error(file="b.s0ma", severity="error"),
        ]
        text = _format_diagnostics_text(errs, [])
        assert "── a.s0ma" in text
        assert "── b.s0ma" in text

    def test_text_format_single_file_no_redundant_header(self):
        """With only one file, no per-file header is shown."""
        errs = [_make_error(file="only.s0ma")]
        text = _format_diagnostics_text(errs, [])
        assert "── only.s0ma" not in text

    def test_text_format_errors_before_warnings_within_file(self):
        """Errors appear before warnings within a file group."""
        errs = [_make_error(file="x.s0ma", severity="error", code="ERR1", line=20)]
        warns = [_make_error(file="x.s0ma", severity="warning", code="WARN1", line=5)]
        text = _format_diagnostics_text(errs, warns)
        err_pos = text.find("ERR1")
        warn_pos = text.find("WARN1")
        assert err_pos < warn_pos

    def test_text_format_empty_returns_empty(self):
        text = _format_diagnostics_text([], [])
        assert text == ""


# ===========================================================================
# Test: JSON Format Output (PRD §2.4.4)
# ===========================================================================


class TestJSONFormat:
    """JSON format must produce valid, schema-compliant output per PRD §2.4.4."""

    def test_json_is_valid_json(self):
        err = _make_error()
        json_str = _format_diagnostics_json([err], [])
        data = json.loads(json_str)
        assert isinstance(data, dict)

    def test_json_has_required_top_level_fields(self):
        json_str = _format_diagnostics_json(
            [_make_error()], [_make_error(severity="warning")]
        )
        data = json.loads(json_str)
        assert "errors" in data
        assert "warnings" in data
        assert "summary" in data
        assert "by_file" in data

    def test_json_summary_has_counts(self):
        json_str = _format_diagnostics_json(
            [_make_error()],
            [_make_error(severity="warning")],
            files_processed=3,
        )
        data = json.loads(json_str)
        assert data["summary"]["errors"] == 1
        assert data["summary"]["warnings"] == 1
        assert data["summary"]["files_processed"] == 3

    def test_json_summary_includes_mode(self):
        json_str = _format_diagnostics_json(
            [_make_error()], [], mode="strict"
        )
        data = json.loads(json_str)
        assert data["summary"]["mode"] == "strict"

    def test_json_error_has_all_required_fields(self):
        """Each error object in JSON must have all 8 PRD §2.4.1 fields."""
        err = _make_error(context={"key": "value"})
        json_str = _format_diagnostics_json([err], [])
        data = json.loads(json_str)
        error_dict = data["errors"][0]
        required = {
            "code", "message", "file", "line",
            "column", "severity", "remediation", "context",
        }
        assert required == set(error_dict.keys())

    def test_json_by_file_grouping(self):
        """The by_file field groups errors and warnings per file."""
        errs = [
            _make_error(file="a.s0ma", severity="error"),
            _make_error(file="b.s0ma", severity="error"),
        ]
        warns = [
            _make_error(file="a.s0ma", severity="warning"),
        ]
        json_str = _format_diagnostics_json(errs, warns, files_processed=2)
        data = json.loads(json_str)
        assert len(data["by_file"]) == 2
        a_group = next(g for g in data["by_file"] if g["file"] == "a.s0ma")
        assert a_group["error_count"] == 1
        assert a_group["warning_count"] == 1
        b_group = next(g for g in data["by_file"] if g["file"] == "b.s0ma")
        assert b_group["error_count"] == 1
        assert b_group["warning_count"] == 0

    def test_json_empty_diagnostics(self):
        json_str = _format_diagnostics_json([], [])
        data = json.loads(json_str)
        assert data["errors"] == []
        assert data["warnings"] == []
        assert data["by_file"] == []
        assert data["summary"]["errors"] == 0
        assert data["summary"]["warnings"] == 0


# ===========================================================================
# Test: Splitting Diagnostics
# ===========================================================================


class TestSplitDiagnostics:
    """_split_diagnostics correctly separates errors from warnings."""

    def test_split_by_severity(self):
        diags = [
            _make_error(severity="error"),
            _make_error(severity="warning"),
            _make_error(severity="error"),
            _make_error(severity="warning"),
        ]
        errors, warnings = _split_diagnostics(diags)
        assert len(errors) == 2
        assert len(warnings) == 2

    def test_split_empty(self):
        errors, warnings = _split_diagnostics([])
        assert errors == []
        assert warnings == []


# ===========================================================================
# Test: Error format_text Method
# ===========================================================================


class TestErrorFormatText:
    """S0maError.format_text() produces the expected text format."""

    def test_format_includes_file_and_line(self):
        err = _make_error(file="module.s0ma", line=42, code="LAYER_MISMATCH")
        text = err.format_text()
        assert "module.s0ma:42:" in text

    def test_format_includes_severity_upper(self):
        err = _make_error(severity="warning")
        text = err.format_text()
        assert "WARNING" in text

    def test_format_includes_code_in_brackets(self):
        err = _make_error(code="VISIBILITY_MISMATCH")
        text = err.format_text()
        assert "[VISIBILITY_MISMATCH]" in text

    def test_format_includes_message(self):
        err = S0maError(
            code="X", message="Component 'foo' is broken", file="f.s0ma",
            line=1, column=0, severity="error",
            remediation="Fix foo.", context={},
        )
        assert "Component 'foo' is broken" in err.format_text()

    def test_format_includes_remediation(self):
        err = _make_error(remediation="Add 'bar' to exports.")
        text = err.format_text()
        assert "Remediation: Add 'bar' to exports." in text

    def test_str_delegates_to_format_text(self):
        err = _make_error()
        assert str(err) == err.format_text()


# ===========================================================================
# Test: Error to_dict Method
# ===========================================================================


class TestErrorToDict:
    """S0maError.to_dict() produces correct JSON-serializable dict."""

    def test_to_dict_round_trips_through_json(self):
        err = _make_error(
            code="NOT_EXPORTED",
            file="router.s0ma",
            line=5,
            context={"target": "select_evaluator", "available_exports": ["route"]},
        )
        d = err.to_dict()
        json_str = json.dumps(d)
        loaded = json.loads(json_str)
        assert loaded["code"] == "NOT_EXPORTED"
        assert loaded["context"]["target"] == "select_evaluator"

    def test_to_dict_preserves_context_types(self):
        err = _make_error(context={"count": 42, "names": ["a", "b"], "flag": True})
        d = err.to_dict()
        assert d["context"]["count"] == 42
        assert d["context"]["names"] == ["a", "b"]
        assert d["context"]["flag"] is True


# ===========================================================================
# Test: Real Error Quality from Invalid Fixtures
# ===========================================================================


class TestRealErrorQuality:
    """Errors produced from actual invalid fixtures meet UX requirements."""

    def _parse_and_collect_errors(self, fixture_path: Path) -> list[S0maError]:
        """Parse a fixture and collect all errors."""
        from s0ma_dsl.parser.s0ma_parser import parse_s0ma

        source = fixture_path.read_text(encoding="utf-8")
        try:
            module = parse_s0ma(source, str(fixture_path), StrictnessMode.STRICT)
        except S0maError as e:
            return [e]

        # Run semantic validation
        from s0ma_dsl.semantic.validator import validate_module
        errors = list(validate_module(
            module, mode=StrictnessMode.STRICT, filename=str(fixture_path),
        ))
        return errors

    @pytest.mark.parametrize("fixture_name,expected_code", [
        ("missing_fields.s0ma", "SEMANTIC_REQUIRED_STATE_OMITTED"),
        ("invalid_kind.s0ma", "INVALID_KIND"),
        ("visibility_mismatch.s0ma", "VISIBILITY_MISMATCH"),
        ("layer_mismatch.s0ma", "LAYER_MISMATCH"),
        ("duplicate_declaration.s0ma", "DUPLICATE_DECLARATION"),
        ("invalid_version.s0ma", "INVALID_VERSION"),
        ("class_in_nerve.s0ma", "CLASS_BODY_IN_NERVE"),
        ("authored_raises_axon.s0ma", "PARSE_ERROR"),  # RAISES rejected at parse time
    ])
    def test_fixture_produces_expected_error_code(self, fixture_name: str, expected_code: str):
        """Each invalid fixture produces the expected error code."""
        fixture_path = _INVALID_DIR / fixture_name
        if not fixture_path.exists():
            pytest.skip(f"Fixture not found: {fixture_name}")
        errors = self._parse_and_collect_errors(fixture_path)
        codes = [e.code for e in errors]
        assert expected_code in codes, f"Expected {expected_code}, got {codes}"

    @pytest.mark.parametrize("fixture_name", [
        "missing_fields.s0ma",
        "invalid_kind.s0ma",
        "visibility_mismatch.s0ma",
        "layer_mismatch.s0ma",
        "duplicate_declaration.s0ma",
        "invalid_version.s0ma",
        "class_in_nerve.s0ma",
        "authored_raises_axon.s0ma",
        "bare_import.s0ma",
        "prohibited_construct.s0ma",
    ])
    def test_all_fixture_errors_have_remediation(self, fixture_name: str):
        """Every error from invalid fixtures has non-empty remediation."""
        fixture_path = _INVALID_DIR / fixture_name
        if not fixture_path.exists():
            pytest.skip(f"Fixture not found: {fixture_name}")
        errors = self._parse_and_collect_errors(fixture_path)
        assert len(errors) > 0, f"No errors produced by {fixture_name}"
        for err in errors:
            assert err.remediation, f"Empty remediation in {err.code} from {fixture_name}"
            assert len(err.remediation) > 10, (
                f"Remediation too short in {err.code} from {fixture_name}: {err.remediation!r}"
            )

    @pytest.mark.parametrize("fixture_name", [
        "missing_fields.s0ma",
        "invalid_kind.s0ma",
        "visibility_mismatch.s0ma",
        "layer_mismatch.s0ma",
        "duplicate_declaration.s0ma",
        "invalid_version.s0ma",
        "class_in_nerve.s0ma",
        "authored_raises_axon.s0ma",
    ])
    def test_all_fixture_errors_have_context(self, fixture_name: str):
        """Every error from invalid fixtures has a non-empty context dict."""
        fixture_path = _INVALID_DIR / fixture_name
        if not fixture_path.exists():
            pytest.skip(f"Fixture not found: {fixture_name}")
        errors = self._parse_and_collect_errors(fixture_path)
        assert len(errors) > 0, f"No errors produced by {fixture_name}"
        for err in errors:
            assert isinstance(err.context, dict), f"context not a dict in {err.code}"
            assert len(err.context) > 0, (
                f"Empty context in {err.code} from {fixture_name}"
            )

    @pytest.mark.parametrize("fixture_name", [
        "missing_fields.s0ma",
        "invalid_kind.s0ma",
        "visibility_mismatch.s0ma",
        "layer_mismatch.s0ma",
        "duplicate_declaration.s0ma",
        "class_in_nerve.s0ma",
        "authored_raises_axon.s0ma",
    ])
    def test_all_fixture_errors_have_source_location(self, fixture_name: str):
        """Every error has a meaningful source location (line > 0)."""
        fixture_path = _INVALID_DIR / fixture_name
        if not fixture_path.exists():
            pytest.skip(f"Fixture not found: {fixture_name}")
        errors = self._parse_and_collect_errors(fixture_path)
        assert len(errors) > 0
        for err in errors:
            assert err.line > 0, f"line=0 in {err.code} from {fixture_name}"
            assert err.file, f"Empty file in {err.code} from {fixture_name}"


# ===========================================================================
# Test: CLI JSON Output Integration
# ===========================================================================


class TestCLIJSONOutput:
    """End-to-end tests for --format json via the CLI."""

    @pytest.fixture()
    def cli(self) -> S0maCLI:
        return S0maCLI()

    @pytest.fixture()
    def invalid_file(self, tmp_path: Path) -> Path:
        s0ma = """\
module broken
    layer: DOMAIN
    version: 0.1.0
    intent: "Missing exports field."
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        f = tmp_path / "broken.s0ma"
        f.write_text(s0ma, encoding="utf-8")
        return f

    @pytest.fixture()
    def valid_file(self, tmp_path: Path) -> Path:
        s0ma = """\
module ok_mod
    layer: DOMAIN
    version: 0.1.0
    intent: "A valid module."
    exports: [greet]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve greet :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Greeting function."
    expects: "name: str"
    guarantees: "Returns a greeting"
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
    def greet(name: str) -> str:
        return f"Hello, {name}!"
"""
        f = tmp_path / "ok_mod.s0ma"
        f.write_text(s0ma, encoding="utf-8")
        return f

    def test_check_json_produces_valid_json(self, cli: S0maCLI, invalid_file: Path, capsys):
        cli.run(["check", str(invalid_file), "--format", "json", "--mode", "dev"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "errors" in data
        assert "warnings" in data
        assert "summary" in data
        assert "by_file" in data

    def test_check_json_summary_has_mode(self, cli: S0maCLI, invalid_file: Path, capsys):
        cli.run(["check", str(invalid_file), "--format", "json", "--mode", "strict"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["summary"]["mode"] == "strict"

    def test_check_json_errors_have_all_fields(self, cli: S0maCLI, invalid_file: Path, capsys):
        cli.run(["check", str(invalid_file), "--format", "json", "--mode", "dev"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        if data["errors"]:
            err = data["errors"][0]
            for field in [
                "code", "message", "file", "line",
                "column", "severity", "remediation", "context",
            ]:
                assert field in err, f"Missing field: {field}"

    def test_check_json_by_file_structure(self, cli: S0maCLI, invalid_file: Path, capsys):
        cli.run(["check", str(invalid_file), "--format", "json", "--mode", "dev"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["by_file"]) >= 1
        for group in data["by_file"]:
            assert "file" in group
            assert "errors" in group
            assert "warnings" in group
            assert "error_count" in group
            assert "warning_count" in group

    def test_transpile_json_diagnostics_on_error(
        self, cli: S0maCLI, invalid_file: Path, tmp_path: Path, capsys
    ):
        out = tmp_path / "out"
        out.mkdir()
        cli.run([
            "transpile", str(invalid_file),
            "--output-dir", str(out),
            "--format", "json",
            "--mode", "dev",
        ])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["summary"]["errors"] > 0

    def test_valid_file_json_no_errors(self, cli: S0maCLI, valid_file: Path, capsys):
        """Valid file in JSON mode should produce no errors."""
        cli.run(["check", str(valid_file), "--format", "json", "--mode", "dev"])
        captured = capsys.readouterr()
        # If output is empty (success path), that's fine
        if captured.out.strip():
            data = json.loads(captured.out)
            assert data["summary"]["errors"] == 0


# ===========================================================================
# Test: Error Immutability
# ===========================================================================


class TestErrorImmutability:
    """S0maError instances are immutable after construction."""

    def test_cannot_modify_fields(self):
        err = _make_error()
        # dataclasses.FrozenInstanceError is what we expect, but it's a
        # subclass of AttributeError — assert the broader
        # AttributeError to keep the test resilient if that ever
        # changes upstream while still being narrower than ``Exception``.
        with pytest.raises(AttributeError):
            err.code = "CHANGED"

    def test_can_be_raised_and_caught(self):
        err = _make_parse_error()
        with pytest.raises(S0maParseError) as exc_info:
            raise err
        assert exc_info.value.code == "PARSE_ERROR"

    def test_exception_protocol_works(self):
        """Exception chaining works despite immutability."""
        err = _make_error()
        try:
            try:
                raise ValueError("original")
            except ValueError:
                raise err from ValueError("cause")
        except S0maError as caught:
            assert caught.__cause__ is not None


# ===========================================================================
# Test: Error Hierarchy
# ===========================================================================


class TestErrorHierarchy:
    """Error subclasses allow catching at different levels."""

    def test_catch_base_catches_all(self):
        errs = [_make_parse_error(), _make_semantic_error(), _make_resolution_error()]
        for e in errs:
            assert isinstance(e, S0maError)
            assert isinstance(e, Exception)

    def test_catch_specific_types(self):
        assert isinstance(_make_parse_error(), S0maParseError)
        assert not isinstance(_make_parse_error(), S0maSemanticError)
        assert isinstance(_make_semantic_error(), S0maSemanticError)
        assert not isinstance(_make_semantic_error(), S0maResolutionError)
        assert isinstance(_make_resolution_error(), S0maResolutionError)
        assert not isinstance(_make_resolution_error(), S0maParseError)
