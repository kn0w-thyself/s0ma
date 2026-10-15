"""Tests for body extraction and validation (Milestone 5).

Covers:
- Simple function body extraction
- Class definition body extraction (cells)
- Function with decorators
- Complex type annotations
- exec() → error
- eval() → error
- __import__() → error
- importlib.import_module() → error
- setattr() → error (monkey-patching)
- Bare import → error
- Class in nerve → error
- Constant assignment (CONSTANT cells)
- Golden fixture bodies extract correctly
- Round-trip fidelity test (source text preserved)
- Cell kind-body compatibility
- Ganglion/test bodies must be functions
- Strictness mode modulates severity
"""

import pytest

from s0ma_dsl.ast_nodes.enums import Kind
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.errors import S0maParseError, S0maSemanticError
from s0ma_dsl.parser.body_extractor import (
    BodyInfo,
    BodyType,
    extract_body,
    validate_body,
)
from s0ma_dsl.parser.s0ma_parser import parse_s0ma

# =====================================================================
# extract_body — basic functionality
# =====================================================================


class TestExtractBody:
    """Tests for the extract_body function."""

    def test_simple_function(self):
        body = "    def greet(name: str) -> str:\n        return f'Hello, {name}!'"
        info = extract_body(body)
        assert info.body_type == BodyType.FUNCTION
        assert info.function_name == "greet"
        assert info.class_name is None
        assert info.ast_node is not None
        assert info.source_text == body  # Preserved exactly

    def test_simple_class(self):
        body = "    class MyModel:\n        x: int\n        y: str"
        info = extract_body(body)
        assert info.body_type == BodyType.CLASS
        assert info.class_name == "MyModel"
        assert info.function_name is None

    def test_function_with_decorator(self):
        body = (
            "    @staticmethod\n"
            "    def compute(x: int) -> int:\n"
            "        return x * 2"
        )
        info = extract_body(body)
        assert info.body_type == BodyType.FUNCTION
        assert info.function_name == "compute"

    def test_class_with_decorator(self):
        body = (
            "    @dataclass(frozen=True)\n"
            "    class SignalEnvelope:\n"
            "        source: str\n"
            "        timestamp: float"
        )
        info = extract_body(body)
        assert info.body_type == BodyType.CLASS
        assert info.class_name == "SignalEnvelope"

    def test_constant_assignment(self):
        body = "    MAX_STALENESS_SECONDS: int = 300"
        info = extract_body(body)
        assert info.body_type == BodyType.ASSIGNMENT
        assert info.function_name is None
        assert info.class_name is None

    def test_bare_assignment(self):
        body = "    DEFAULT_TIMEOUT = 30"
        info = extract_body(body)
        assert info.body_type == BodyType.ASSIGNMENT

    def test_complex_type_annotations(self):
        body = (
            "    def process(\n"
            "        items: list[dict[str, int]],\n"
            "        callback: Callable[[str], None] | None = None,\n"
            "    ) -> tuple[bool, list[str]]:\n"
            "        return True, []"
        )
        info = extract_body(body)
        assert info.body_type == BodyType.FUNCTION
        assert info.function_name == "process"

    def test_async_function(self):
        body = (
            "    async def fetch_data(url: str) -> bytes:\n"
            "        return b'data'"
        )
        info = extract_body(body)
        assert info.body_type == BodyType.FUNCTION
        assert info.function_name == "fetch_data"

    def test_multiline_signature(self):
        body = (
            "    def long_function(\n"
            "        arg1: str,\n"
            "        arg2: int,\n"
            "        arg3: float = 0.0,\n"
            "    ) -> dict[str, Any]:\n"
            "        return {}"
        )
        info = extract_body(body)
        assert info.body_type == BodyType.FUNCTION
        assert info.function_name == "long_function"

    def test_empty_body_raises(self):
        with pytest.raises(S0maParseError, match="Empty body"):
            extract_body("")

    def test_whitespace_only_body_raises(self):
        with pytest.raises(S0maParseError, match="Empty body"):
            extract_body("    \n    \n")

    def test_invalid_python_syntax_raises(self):
        with pytest.raises(S0maParseError, match="Invalid Python syntax"):
            extract_body("    def broken(:\n        pass")

    def test_source_text_preserved_exactly(self):
        """FR-07: Body source text must be preserved exactly as written."""
        original = "    def greet(name: str) -> str:\n        return f'Hello, {name}!'"
        info = extract_body(original)
        assert info.source_text == original
        # The dedented text should NOT be the same (it's dedented)
        assert info.dedented_text != original
        assert info.dedented_text.startswith("def greet")

    def test_dedented_text_parseable(self):
        body = "        def deeply_indented() -> None:\n            pass"
        info = extract_body(body)
        assert info.dedented_text.startswith("def deeply_indented")
        assert info.body_type == BodyType.FUNCTION

    def test_class_with_methods(self):
        body = (
            "    class Config:\n"
            "        debug: bool = False\n"
            "        port: int = 8080\n"
            "\n"
            "        def validate(self) -> bool:\n"
            "            return self.port > 0"
        )
        info = extract_body(body)
        assert info.body_type == BodyType.CLASS
        assert info.class_name == "Config"

    def test_enum_class(self):
        body = (
            "    class Priority(Enum):\n"
            "        LOW = 'low'\n"
            "        MEDIUM = 'medium'\n"
            "        HIGH = 'high'"
        )
        info = extract_body(body)
        assert info.body_type == BodyType.CLASS
        assert info.class_name == "Priority"

    def test_exception_class(self):
        body = (
            "    class SignalValidationError(Exception):\n"
            "        pass"
        )
        info = extract_body(body)
        assert info.body_type == BodyType.CLASS
        assert info.class_name == "SignalValidationError"


# =====================================================================
# validate_body — nerve body constraints (FR-19)
# =====================================================================


class TestNerveBodyValidation:
    """Nerve body constraints: function required, except SERVICE/ADAPTER allow class."""

    def test_valid_function_body(self):
        body = "    def process(x: int) -> int:\n        return x * 2"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "process", Kind.FUNCTION, "<test>", 1)
        assert errors == []

    def test_class_body_in_function_nerve_error(self):
        """FUNCTION nerves must not have class bodies."""
        body = "    class MyClass:\n        def run(self):\n            pass"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "my_func", Kind.FUNCTION, "<test>", 1)
        assert len(errors) == 1
        assert errors[0].code == "CLASS_BODY_IN_NERVE"
        assert errors[0].severity == "error"
        assert "SERVICE" in errors[0].remediation or "ADAPTER" in errors[0].remediation

    def test_class_body_in_orchestrator_nerve_error(self):
        """ORCHESTRATOR nerves must not have class bodies."""
        body = "    class Orchestrator:\n        pass"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "orch", Kind.ORCHESTRATOR, "<test>", 1)
        assert len(errors) == 1
        assert errors[0].code == "CLASS_BODY_IN_NERVE"

    def test_class_body_in_service_nerve_allowed(self):
        """SERVICE nerves may use class bodies (MS 8)."""
        body = "    class MyService:\n        def run(self):\n            pass"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "my_service", Kind.SERVICE, "<test>", 1)
        assert errors == []

    def test_class_body_in_adapter_nerve_allowed(self):
        """ADAPTER nerves may use class bodies (MS 8)."""
        body = "    class MyAdapter:\n        def connect(self):\n            pass"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "my_adapter", Kind.ADAPTER, "<test>", 1)
        assert errors == []

    def test_function_body_still_valid_for_service(self):
        """SERVICE nerves can still use function bodies."""
        body = "    def MyService():\n        return {}"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "MyService", Kind.SERVICE, "<test>", 1)
        assert errors == []

    def test_assignment_body_in_nerve_error(self):
        body = "    MY_CONST = 42"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "my_nerve", Kind.FUNCTION, "<test>", 1)
        assert len(errors) == 1
        assert errors[0].code == "PARSE_ERROR"
        msg = errors[0].message.lower()
        assert "function definition" in msg or "def" in msg


# =====================================================================
# PARSE_ERROR remediation teaches the body rules (pilot01)
# =====================================================================


class TestParseErrorRemediationTeachesBodyRules:
    """Pilot01 (b): the must-be-a-def PARSE_ERROR remediation teaches
    the two rules that kill first-time users — exactly ONE def in the
    body, and imports go in the module header's ``requires:`` list —
    and, when the body detectably mixes imports with a def (normal
    Python pasted in), leads with that state-aware diagnosis."""

    IMPORTS_BEFORE_DEF = (
        "    import json\n"
        "    import sys\n"
        "\n"
        "    def do_work(x):\n"
        "        return json.dumps(x)\n"
    )

    def test_imports_before_def_nerve_body_gets_state_aware_remediation(self):
        info = extract_body(self.IMPORTS_BEFORE_DEF)
        assert info.body_type == BodyType.UNKNOWN
        errors = validate_body(info, "nerve", "do_work", Kind.FUNCTION, "<test>", 1)
        parse_errors = [e for e in errors if e.code == "PARSE_ERROR"]
        assert len(parse_errors) == 1
        err = parse_errors[0]
        # Message is pinned in transcripts/analytics — unchanged shape.
        assert err.message == (
            "Nerve 'do_work' body must be a function definition (def), "
            "found unknown."
        )
        remediation = err.remediation
        # State-aware diagnosis leads.
        assert "The body contains import statements outside the def." in remediation
        # The two rules.
        assert "`requires:` list" in remediation
        assert "exactly ONE `def do_work(...)`" in remediation
        # Compact valid example.
        assert "A valid nerve body looks like:" in remediation
        assert "def do_work(arg):" in remediation
        assert "requires: [json, mypkg:helper]" in remediation
        # Detected shape rides the context payload.
        assert err.context["imports_in_body"] is True

    def test_generic_unknown_body_remediation_still_teaches_both_rules(self):
        """An unknown body WITHOUT the imports+def shape still gets the
        single-def rule, the requires: rule, and the example."""
        body = "    x = 1\n    y = 2\n"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "do_work", Kind.FUNCTION, "<test>", 1)
        parse_errors = [e for e in errors if e.code == "PARSE_ERROR"]
        assert len(parse_errors) == 1
        remediation = parse_errors[0].remediation
        assert "exactly ONE" in remediation
        assert "`def do_work(...)`" in remediation
        assert "`requires:` list" in remediation
        assert "A valid nerve body looks like:" in remediation
        assert parse_errors[0].context["imports_in_body"] is False

    def test_ganglion_and_test_bodies_get_same_treatment(self):
        for decl_type in ("ganglion", "test"):
            info = extract_body(self.IMPORTS_BEFORE_DEF)
            errors = validate_body(info, decl_type, "do_work", None, "<test>", 1)
            parse_errors = [e for e in errors if e.code == "PARSE_ERROR"]
            assert len(parse_errors) == 1
            remediation = parse_errors[0].remediation
            assert "The body contains import statements outside the def." in remediation
            assert f"A valid {decl_type} body looks like:" in remediation

    def test_full_file_parse_surfaces_teaching_remediation(self):
        """End-to-end via the parser API: normal Python pasted into a
        .s0ma nerve body raises PARSE_ERROR whose remediation names the
        actual rules instead of a bare 'wrap it in a def'."""
        source = (
            """\
module foo
    layer: DOMAIN
    version: 0.1.0
    intent: "Pilot01 fixture."
    exports: [do_foo]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_foo :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Normal Python pasted in."
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
    import json

    def do_foo(x):
        return json.dumps(x)
"""
        )
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(source, "foo.s0ma", mode=StrictnessMode.DEV)
        err = excinfo.value
        assert err.code == "PARSE_ERROR"
        assert "The body contains import statements outside the def." in err.remediation
        assert "`requires:` list" in err.remediation
        assert "exactly ONE `def do_foo(...)`" in err.remediation


# =====================================================================
# validate_body — cell body constraints
# =====================================================================


class TestCellBodyValidation:
    """Cell bodies must match their kind."""

    def test_model_with_class_body(self):
        body = "    class MyModel:\n        x: int"
        info = extract_body(body)
        errors = validate_body(info, "cell", "MyModel", Kind.MODEL, "<test>", 1)
        assert errors == []

    def test_model_with_function_body_error(self):
        body = "    def not_a_model() -> None:\n        pass"
        info = extract_body(body)
        errors = validate_body(info, "cell", "MyModel", Kind.MODEL, "<test>", 1)
        assert len(errors) == 1
        assert errors[0].code == "PARSE_ERROR"
        msg = errors[0].message.lower()
        rem = errors[0].remediation.lower()
        assert "class definition" in msg or "class" in rem

    def test_constant_with_assignment_body(self):
        body = "    MAX_RETRIES: int = 3"
        info = extract_body(body)
        errors = validate_body(info, "cell", "MAX_RETRIES", Kind.CONSTANT, "<test>", 1)
        assert errors == []

    def test_constant_with_class_body_error(self):
        body = "    class NotAConstant:\n        pass"
        info = extract_body(body)
        errors = validate_body(info, "cell", "MAX_RETRIES", Kind.CONSTANT, "<test>", 1)
        assert len(errors) == 1
        assert "assignment" in errors[0].message.lower()

    def test_exception_with_class_body(self):
        body = "    class MyError(Exception):\n        pass"
        info = extract_body(body)
        errors = validate_body(info, "cell", "MyError", Kind.EXCEPTION, "<test>", 1)
        assert errors == []

    def test_enum_with_class_body(self):
        body = "    class Status(Enum):\n        ACTIVE = 'active'\n        INACTIVE = 'inactive'"
        info = extract_body(body)
        errors = validate_body(info, "cell", "Status", Kind.ENUM, "<test>", 1)
        assert errors == []

    def test_config_with_class_body(self):
        body = "    class AppConfig:\n        debug: bool = False"
        info = extract_body(body)
        errors = validate_body(info, "cell", "AppConfig", Kind.CONFIG, "<test>", 1)
        assert errors == []

    def test_type_with_assignment_body(self):
        """TYPE cells can use assignment-style type aliases."""
        body = "    UserID = str"
        info = extract_body(body)
        errors = validate_body(info, "cell", "UserID", Kind.TYPE, "<test>", 1)
        assert errors == []

    def test_type_with_function_body_error(self):
        body = "    def not_a_type() -> None:\n        pass"
        info = extract_body(body)
        errors = validate_body(info, "cell", "UserID", Kind.TYPE, "<test>", 1)
        assert len(errors) == 1
        assert "type alias" in errors[0].message.lower()


# =====================================================================
# validate_body — ganglion and test body constraints
# =====================================================================


class TestGanglionTestBodyValidation:
    """Ganglion and test bodies must be function definitions."""

    def test_ganglion_with_function_body(self):
        body = "    def evaluate(signals: list) -> dict:\n        return {}"
        info = extract_body(body)
        errors = validate_body(info, "ganglion", "my_ganglion", None, "<test>", 1)
        assert errors == []

    def test_ganglion_with_class_body_error(self):
        body = "    class NotAFunction:\n        pass"
        info = extract_body(body)
        errors = validate_body(info, "ganglion", "my_ganglion", None, "<test>", 1)
        assert len(errors) == 1
        assert "function definition" in errors[0].message.lower()

    def test_test_with_function_body(self):
        body = "    def test_something() -> None:\n        assert True"
        info = extract_body(body)
        errors = validate_body(info, "test", "test_something", None, "<test>", 1)
        assert errors == []

    def test_test_with_class_body_error(self):
        body = "    class TestSomething:\n        pass"
        info = extract_body(body)
        errors = validate_body(info, "test", "test_something", None, "<test>", 1)
        assert len(errors) == 1
        assert "function definition" in errors[0].message.lower()


# =====================================================================
# validate_body — prohibited constructs (FR-18)
# =====================================================================


class TestProhibitedConstructs:
    """FR-18: exec, eval, __import__, importlib.import_module, monkey-patching."""

    def test_exec_detected(self):
        body = "    def evil() -> None:\n        exec('print(1)')"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "evil", Kind.FUNCTION, "<test>", 1)
        assert any(e.code == "PROHIBITED_CONSTRUCT" for e in errors)
        assert any("exec" in e.message for e in errors)

    def test_eval_detected(self):
        body = "    def evil() -> None:\n        x = eval('1 + 1')"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "evil", Kind.FUNCTION, "<test>", 1)
        assert any(e.code == "PROHIBITED_CONSTRUCT" for e in errors)
        assert any("eval" in e.message for e in errors)

    def test_dunder_import_detected(self):
        body = "    def evil() -> None:\n        mod = __import__('os')"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "evil", Kind.FUNCTION, "<test>", 1)
        assert any(e.code == "PROHIBITED_CONSTRUCT" for e in errors)
        assert any("__import__" in e.message for e in errors)

    def test_importlib_import_module_detected(self):
        body = "    def evil() -> None:\n        mod = importlib.import_module('os')"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "evil", Kind.FUNCTION, "<test>", 1)
        assert any(e.code == "PROHIBITED_CONSTRUCT" for e in errors)
        assert any("importlib.import_module" in e.message for e in errors)

    def test_setattr_detected(self):
        body = "    def evil(obj) -> None:\n        setattr(obj, 'x', 42)"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "evil", Kind.FUNCTION, "<test>", 1)
        assert any(e.code == "PROHIBITED_CONSTRUCT" for e in errors)
        assert any("setattr" in e.message for e in errors)

    def test_clean_body_no_prohibited_constructs(self):
        body = "    def clean(x: int) -> int:\n        return x * 2"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "clean", Kind.FUNCTION, "<test>", 1)
        assert errors == []

    def test_multiple_prohibited_constructs(self):
        body = (
            "    def very_evil() -> None:\n"
            "        exec('code')\n"
            "        eval('expr')\n"
            "        __import__('os')"
        )
        info = extract_body(body)
        errors = validate_body(info, "nerve", "very_evil", Kind.FUNCTION, "<test>", 1)
        prohibited = [e for e in errors if e.code == "PROHIBITED_CONSTRUCT"]
        assert len(prohibited) == 3


# =====================================================================
# validate_body — bare imports (FR-18)
# =====================================================================


class TestBareImports:
    """FR-18: Bare import statements in bodies are rejected."""

    def test_bare_import_detected(self):
        body = "    def sneaky() -> None:\n        import os\n        os.listdir('.')"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "sneaky", Kind.FUNCTION, "<test>", 1)
        assert any(e.code == "BARE_IMPORT" for e in errors)
        assert any("import os" in e.message for e in errors)

    def test_bare_from_import_detected(self):
        body = (
            "    def sneaky() -> None:\n"
            "        from pathlib import Path\n"
            "        Path('.').resolve()"
        )
        info = extract_body(body)
        errors = validate_body(info, "nerve", "sneaky", Kind.FUNCTION, "<test>", 1)
        assert any(e.code == "BARE_IMPORT" for e in errors)
        assert any("from pathlib import Path" in e.message for e in errors)

    def test_no_bare_imports_clean(self):
        body = "    def clean() -> None:\n        x = 42"
        info = extract_body(body)
        errors = validate_body(info, "nerve", "clean", Kind.FUNCTION, "<test>", 1)
        assert not any(e.code == "BARE_IMPORT" for e in errors)


# =====================================================================
# Strictness mode modulation
# =====================================================================


class TestStrictnessModes:
    """Prohibited construct and bare import severity varies by strictness mode."""

    def _body_with_exec(self):
        return extract_body("    def f() -> None:\n        exec('x')")

    def _body_with_import(self):
        return extract_body("    def f() -> None:\n        import os")

    def test_migration_mode_prohibited_construct_is_warning(self):
        info = self._body_with_exec()
        errors = validate_body(
            info, "nerve", "f", Kind.FUNCTION, "<test>", 1,
            mode=StrictnessMode.MIGRATION,
        )
        prohibited = [e for e in errors if e.code == "PROHIBITED_CONSTRUCT"]
        assert len(prohibited) == 1
        assert prohibited[0].severity == "warning"

    def test_dev_mode_prohibited_construct_is_warning(self):
        info = self._body_with_exec()
        errors = validate_body(
            info, "nerve", "f", Kind.FUNCTION, "<test>", 1,
            mode=StrictnessMode.DEV,
        )
        prohibited = [e for e in errors if e.code == "PROHIBITED_CONSTRUCT"]
        assert len(prohibited) == 1
        assert prohibited[0].severity == "warning"

    def test_strict_mode_prohibited_construct_is_error(self):
        info = self._body_with_exec()
        errors = validate_body(
            info, "nerve", "f", Kind.FUNCTION, "<test>", 1,
            mode=StrictnessMode.STRICT,
        )
        prohibited = [e for e in errors if e.code == "PROHIBITED_CONSTRUCT"]
        assert len(prohibited) == 1
        assert prohibited[0].severity == "error"

    def test_release_mode_prohibited_construct_is_error(self):
        info = self._body_with_exec()
        errors = validate_body(
            info, "nerve", "f", Kind.FUNCTION, "<test>", 1,
            mode=StrictnessMode.RELEASE,
        )
        prohibited = [e for e in errors if e.code == "PROHIBITED_CONSTRUCT"]
        assert len(prohibited) == 1
        assert prohibited[0].severity == "error"

    def test_migration_mode_bare_import_is_warning(self):
        info = self._body_with_import()
        errors = validate_body(
            info, "nerve", "f", Kind.FUNCTION, "<test>", 1,
            mode=StrictnessMode.MIGRATION,
        )
        bare = [e for e in errors if e.code == "BARE_IMPORT"]
        assert len(bare) == 1
        assert bare[0].severity == "warning"

    def test_strict_mode_bare_import_is_error(self):
        info = self._body_with_import()
        errors = validate_body(
            info, "nerve", "f", Kind.FUNCTION, "<test>", 1,
            mode=StrictnessMode.STRICT,
        )
        bare = [e for e in errors if e.code == "BARE_IMPORT"]
        assert len(bare) == 1
        assert bare[0].severity == "error"


# =====================================================================
# Golden fixture body extraction
# =====================================================================


class TestGoldenFixtureBodies:
    """Golden fixture (signal_processor.s0ma) bodies extract correctly."""

    @pytest.fixture
    def golden_source(self, valid_fixtures_dir):
        path = valid_fixtures_dir / "signal_processor.s0ma"
        return path.read_text()

    def test_golden_parses_with_body_validation(self, golden_source):
        """The golden fixture should parse without body errors in dev mode."""
        # parse_s0ma now includes body validation; should not raise
        result = parse_s0ma(golden_source, "signal_processor.s0ma")
        assert result is not None

    def test_signal_envelope_body(self, golden_source):
        result = parse_s0ma(golden_source, "signal_processor.s0ma")
        cell = result.cells[0]
        assert cell.name == "SignalEnvelope"
        assert cell.body is not None
        info = extract_body(cell.body)
        assert info.body_type == BodyType.CLASS
        assert info.class_name == "SignalEnvelope"

    def test_constant_body(self, golden_source):
        result = parse_s0ma(golden_source, "signal_processor.s0ma")
        cell = result.cells[1]
        assert cell.name == "MAX_STALENESS_SECONDS"
        assert cell.body is not None
        info = extract_body(cell.body)
        assert info.body_type == BodyType.ASSIGNMENT

    def test_validate_envelope_body(self, golden_source):
        result = parse_s0ma(golden_source, "signal_processor.s0ma")
        nerve = result.nerves[0]
        assert nerve.name == "validate_envelope"
        assert nerve.body is not None
        info = extract_body(nerve.body)
        assert info.body_type == BodyType.FUNCTION
        assert info.function_name == "validate_envelope"

    def test_process_signal_body(self, golden_source):
        result = parse_s0ma(golden_source, "signal_processor.s0ma")
        nerve = result.nerves[1]
        assert nerve.name == "process_signal"
        assert nerve.body is not None
        info = extract_body(nerve.body)
        assert info.body_type == BodyType.FUNCTION
        assert info.function_name == "process_signal"

    def test_golden_body_round_trip_fidelity(self, golden_source):
        """FR-07: Body source text must be preserved exactly."""
        result = parse_s0ma(golden_source, "signal_processor.s0ma")
        for nerve in result.nerves:
            if nerve.body is not None:
                info = extract_body(nerve.body)
                assert info.source_text == nerve.body
        for cell in result.cells:
            if cell.body is not None:
                info = extract_body(cell.body)
                assert info.source_text == cell.body

    def test_golden_bodies_have_no_prohibited_constructs(self, golden_source):
        """The golden fixture should have clean bodies."""
        result = parse_s0ma(golden_source, "signal_processor.s0ma")
        for nerve in result.nerves:
            if nerve.body is not None:
                info = extract_body(nerve.body)
                errors = validate_body(
                    info, "nerve", nerve.name, nerve.kind, "signal_processor.s0ma", 1,
                )
                assert errors == [], f"Unexpected errors in {nerve.name}: {errors}"


# =====================================================================
# Parser integration — body validation in parse_s0ma
# =====================================================================


class TestParserIntegration:
    """Test that parse_s0ma integrates body validation."""

    def test_nerve_with_class_body_fails_for_function_kind(self):
        """A FUNCTION nerve with a class body should fail during parsing."""
        source = """\
module test_mod
    layer: APPLICATION
    version: 1.0.0
    intent: "Test module"
    exports: [my_nerve]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve my_nerve :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "A nerve with wrong body"
    expects: "nothing"
    guarantees: "nothing"
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
    class MyService:
        def run(self):
            pass
"""
        with pytest.raises(S0maSemanticError, match="CLASS_BODY_IN_NERVE"):
            parse_s0ma(source, "<test>")

    def test_service_nerve_with_class_body_succeeds(self):
        """A SERVICE nerve with a class body should parse successfully (MS 8)."""
        source = """\
module test_mod
    layer: APPLICATION
    version: 1.0.0
    intent: "Test module"
    exports: [my_service]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve my_service :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "A service with class body"
    expects: "nothing"
    guarantees: "nothing"
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
    class MyService:
        def __init__(self, dep):
            self.dep = dep
        def run(self):
            return self.dep
"""
        result = parse_s0ma(source, "<test>")
        assert result is not None
        assert len(result.nerves) == 1
        assert "class MyService" in result.nerves[0].body

    def test_nerve_with_exec_in_strict_mode_fails(self):
        """exec() in strict mode should fail at parse time."""
        source = """\
module test_mod
    layer: APPLICATION
    version: 1.0.0
    intent: "Test module"
    exports: [evil_nerve]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve evil_nerve :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "A nerve with prohibited construct"
    expects: "nothing"
    guarantees: "nothing"
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
    def evil_nerve() -> None:
        exec('print(1)')
"""
        with pytest.raises(S0maSemanticError, match="PROHIBITED_CONSTRUCT"):
            parse_s0ma(source, "<test>", mode=StrictnessMode.STRICT)

    def test_nerve_with_exec_in_dev_mode_succeeds(self):
        """exec() in dev mode is a warning, not a blocking error."""
        source = """\
module test_mod
    layer: APPLICATION
    version: 1.0.0
    intent: "Test module"
    exports: [warning_nerve]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve warning_nerve :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "A nerve with prohibited construct"
    expects: "nothing"
    guarantees: "nothing"
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
    def warning_nerve() -> None:
        exec('print(1)')
"""
        # Should NOT raise in dev mode (exec is a warning)
        result = parse_s0ma(source, "<test>", mode=StrictnessMode.DEV)
        assert result is not None

    def test_nerve_with_bare_import_in_strict_mode_fails(self):
        source = """\
module test_mod
    layer: APPLICATION
    version: 1.0.0
    intent: "Test module"
    exports: [sneaky]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve sneaky :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "A nerve with bare import"
    expects: "nothing"
    guarantees: "nothing"
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
    def sneaky() -> None:
        import os
        os.listdir('.')
"""
        with pytest.raises(S0maSemanticError, match="BARE_IMPORT"):
            parse_s0ma(source, "<test>", mode=StrictnessMode.STRICT)

    def test_valid_module_parses_with_body_validation(self):
        """A well-formed module with valid bodies should parse fine."""
        source = """\
module good_mod
    layer: DOMAIN
    version: 0.1.0
    intent: "A well-formed module"
    exports: [do_thing]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_thing :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Does a thing"
    expects: "x is positive"
    guarantees: "returns x doubled"
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
    def do_thing(x: int) -> int:
        return x * 2
"""
        result = parse_s0ma(source, "<test>")
        assert result is not None
        assert len(result.nerves) == 1
        assert result.nerves[0].body is not None


# =====================================================================
# Dogfooding — @component decorators on body extractor
# =====================================================================


class TestDogfooding:
    """Verify body extractor components are registered with s0ma."""

    def test_body_type_has_component(self):
        assert hasattr(BodyType, "__component__")

    def test_body_info_has_component(self):
        assert hasattr(BodyInfo, "__component__")

    def test_extract_body_has_component(self):
        assert hasattr(extract_body, "__component__")

    def test_validate_body_has_component(self):
        assert hasattr(validate_body, "__component__")
