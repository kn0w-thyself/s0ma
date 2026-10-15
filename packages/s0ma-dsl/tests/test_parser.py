"""Comprehensive parser tests for the s0ma DSL.

Tests cover:
- Minimal module declarations
- Module with requires/uses/exports
- Nerve with all fields
- Nerve with optional fields
- Cell (MODEL, CONSTANT, EXCEPTION)
- Ganglion with observes
- Test with tests field
- Standalone axon
- Multi-line strings
- depends_on blocks
- Aliasing syntax
- Missing mandatory fields → S0maParseError
- Golden fixture parses without errors
- Empty file and bad top-level content errors
- Multiple module declarations error
"""

from __future__ import annotations

from pathlib import Path

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
    S0maModule,
)
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.parser import parse_s0ma

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GOLDEN_FIXTURE = Path(__file__).parent / "fixtures" / "valid" / "signal_processor.s0ma"


# ---------------------------------------------------------------------------
# Minimal module
# ---------------------------------------------------------------------------


class TestMinimalModule:
    """Tests for the simplest valid module declarations."""

    def test_minimal_module(self) -> None:
        source = """\
module my_module
    layer: DOMAIN
    version: 1.0.0
    intent: "A minimal test module."
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source, "minimal.s0ma")
        assert isinstance(result, S0maModule)
        assert result.module.name == "my_module"
        assert result.module.layer == Layer.DOMAIN
        assert result.module.version == "1.0.0"
        assert result.module.intent == "A minimal test module."
        assert result.module.exports == ()
        assert result.module.requires == ()
        assert result.module.uses == ()

    def test_module_with_exports(self) -> None:
        source = """\
module my_module
    layer: APPLICATION
    version: 0.1.0
    intent: "Module with exports."
    exports: [foo, bar]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert result.module.exports == ("foo", "bar")

    def test_module_all_layers(self) -> None:
        for layer_name in ("DOMAIN", "APPLICATION", "INFRASTRUCTURE", "PRESENTATION", "FRAMEWORK"):
            source = f"""\
module m
    layer: {layer_name}
    version: 1.0.0
    intent: "Testing layer {layer_name}."
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
            result = parse_s0ma(source)
            assert result.module.layer == Layer[layer_name]


# ---------------------------------------------------------------------------
# Module with imports
# ---------------------------------------------------------------------------


class TestModuleImports:
    """Tests for requires, uses, and aliasing."""

    def test_requires_simple(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Has requires."
    requires: [time, json]
    exports: []
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert len(result.module.requires) == 2
        assert result.module.requires[0].module_path == "time"
        assert result.module.requires[0].is_from_import is False
        assert result.module.requires[1].module_path == "json"

    def test_requires_qualified(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Has qualified requires."
    requires: [uuid.UUID, os.path]
    exports: []
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert result.module.requires[0].module_path == "uuid.UUID"
        assert result.module.requires[0].is_from_import is True  # UUID is capitalized
        assert result.module.requires[1].module_path == "os.path"
        assert result.module.requires[1].is_from_import is False  # path is lowercase

    def test_requires_with_alias(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Has aliased requires."
    requires: [collections.OrderedDict as OD]
    exports: []
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert result.module.requires[0].module_path == "collections.OrderedDict"
        assert result.module.requires[0].alias == "OD"

    def test_uses(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Has uses."
    uses: [routing.select_evaluator, errors.SignalValidationError]
    exports: []
    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert len(result.module.uses) == 2
        assert result.module.uses[0].qualified_name == "routing.select_evaluator"
        assert result.module.uses[1].qualified_name == "errors.SignalValidationError"

    def test_uses_with_alias(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Has aliased uses."
    uses: [auth.validate_token as verify_token]
    exports: []
    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert result.module.uses[0].qualified_name == "auth.validate_token"
        assert result.module.uses[0].alias == "verify_token"

    def test_requires_colon_syntax(self) -> None:
        """Colon syntax forces from-import regardless of capitalization."""
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Has colon-form requires."
    requires: [unittest.mock:patch, dataclasses:dataclass]
    exports: []
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert len(result.module.requires) == 2
        # unittest.mock:patch → from unittest.mock import patch
        assert result.module.requires[0].module_path == "unittest.mock.patch"
        assert result.module.requires[0].is_from_import is True
        # dataclasses:dataclass → from dataclasses import dataclass
        assert result.module.requires[1].module_path == "dataclasses.dataclass"
        assert result.module.requires[1].is_from_import is True

    def test_requires_colon_syntax_with_alias(self) -> None:
        """Colon syntax with alias."""
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Has aliased colon-form requires."
    requires: [unittest.mock:patch as p]
    exports: []
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert result.module.requires[0].module_path == "unittest.mock.patch"
        assert result.module.requires[0].alias == "p"
        assert result.module.requires[0].is_from_import is True

    def test_requires_known_exceptions(self) -> None:
        """Known stdlib patterns are treated as from-imports despite lowercase."""
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Has known-exception requires."
    requires: [datetime.datetime, functools.wraps, dataclasses.dataclass]
    exports: []
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        # datetime.datetime → from datetime import datetime (known exception)
        assert result.module.requires[0].module_path == "datetime.datetime"
        assert result.module.requires[0].is_from_import is True
        # functools.wraps → from functools import wraps (known exception)
        assert result.module.requires[1].module_path == "functools.wraps"
        assert result.module.requires[1].is_from_import is True
        # dataclasses.dataclass → from dataclasses import dataclass (known exception)
        assert result.module.requires[2].module_path == "dataclasses.dataclass"
        assert result.module.requires[2].is_from_import is True

    def test_requires_heuristic_still_works(self) -> None:
        """Capitalization heuristic still works for non-exception cases."""
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Standard heuristic requires."
    requires: [pathlib.Path, os.path]
    exports: []
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        # pathlib.Path → from pathlib import Path (uppercase → from-import)
        assert result.module.requires[0].module_path == "pathlib.Path"
        assert result.module.requires[0].is_from_import is True
        # os.path → import os.path (lowercase, not in known-exceptions)
        assert result.module.requires[1].module_path == "os.path"
        assert result.module.requires[1].is_from_import is False

    def test_requires_mixed_forms(self) -> None:
        """Colon syntax, known-exceptions, and heuristic work together."""
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Mixed import forms."
    requires: [unittest.mock:patch, datetime.datetime, pathlib.Path, json]
    exports: []
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert len(result.module.requires) == 4
        # Colon form
        assert result.module.requires[0].module_path == "unittest.mock.patch"
        assert result.module.requires[0].is_from_import is True
        # Known exception
        assert result.module.requires[1].module_path == "datetime.datetime"
        assert result.module.requires[1].is_from_import is True
        # Capitalization heuristic
        assert result.module.requires[2].module_path == "pathlib.Path"
        assert result.module.requires[2].is_from_import is True
        # Simple import (no dots)
        assert result.module.requires[3].module_path == "json"
        assert result.module.requires[3].is_from_import is False

    def test_empty_requires_and_uses(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Empty import lists."
    requires: []
    uses: []
    exports: []
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert result.module.requires == ()
        assert result.module.uses == ()

    def test_tags(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Has tags."
    exports: []
    tags: [core, signals]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert result.module.tags == ("core", "signals")


# ---------------------------------------------------------------------------
# Nerve declarations
# ---------------------------------------------------------------------------


class TestNerveDeclaration:
    """Tests for nerve parsing."""

    def test_nerve_all_mandatory_fields(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
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
    intent: "Does a thing."
    expects: "input is not None"
    guarantees: "returns a value"
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
        return x + 1
"""
        result = parse_s0ma(source)
        assert len(result.nerves) == 1
        n = result.nerves[0]
        assert n.name == "do_thing"
        assert n.layer == Layer.DOMAIN
        assert n.kind == Kind.FUNCTION
        assert n.visibility == Visibility.PUBLIC
        assert n.intent == "Does a thing."
        assert n.expects == "input is not None"
        assert n.guarantees == "returns a value"
        assert n.evaluates_at == EvaluatesAt.FUNCTION_BOUNDARY
        assert n.body is not None
        assert "def do_thing" in n.body

    def test_nerve_with_optional_fields(self) -> None:
        source = """\
module m
    layer: APPLICATION
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve validate :: APPLICATION
    kind: FUNCTION
    visibility: INTERNAL
    intent: "Validates input."
    expects: "data is not empty"
    guarantees: "returns True if valid"
    forbids: none
    raises: [ValidationError]
    latency_ms: 10
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    interface: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def validate(data: str) -> bool:
        return len(data) > 0
"""
        result = parse_s0ma(source)
        n = result.nerves[0]
        assert n.raises == ("ValidationError",)
        assert n.latency_ms == 10

    def test_nerve_all_kinds(self) -> None:
        for kind in ("SERVICE", "FUNCTION", "ADAPTER", "ORCHESTRATOR"):
            source = f"""\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve n :: DOMAIN
    kind: {kind}
    visibility: INTERNAL
    intent: "A nerve."
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
    def n():
        pass
"""
            result = parse_s0ma(source)
            assert result.nerves[0].kind == Kind[kind]

    def test_nerve_with_depends_on(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve process :: DOMAIN
    kind: ORCHESTRATOR
    visibility: INTERNAL
    intent: "Processes data."
    expects: "input valid"
    guarantees: "output valid"
    forbids: none
    evaluates_at: SUBSYSTEM
    depends_on:
        helper: {relation: CALLS, carries: "data", coupling: TIGHT}
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def process(x):
        return helper(x)
"""
        result = parse_s0ma(source)
        n = result.nerves[0]
        assert len(n.depends_on) == 1
        dep = n.depends_on[0]
        assert dep.target == "helper"
        assert dep.relation == Relation.CALLS
        assert dep.carries == "data"
        assert dep.coupling == Coupling.TIGHT

    def test_nerve_evaluates_at_values(self) -> None:
        for ea in ("FUNCTION_BOUNDARY", "SUBSYSTEM", "SYSTEM"):
            source = f"""\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve n :: DOMAIN
    kind: FUNCTION
    visibility: INTERNAL
    intent: "A nerve."
    expects: "none"
    guarantees: "none"
    forbids: none
    evaluates_at: {ea}
    declares_attributes: none
    covered_by: none
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    ---
    def n():
        pass
"""
            result = parse_s0ma(source)
            assert result.nerves[0].evaluates_at == EvaluatesAt[ea]


# ---------------------------------------------------------------------------
# Cell declarations
# ---------------------------------------------------------------------------


class TestCellDeclaration:
    """Tests for cell parsing."""

    def test_model_cell(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: [MyModel]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell MyModel :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "A data model."
    schema: "Dataclass with name: str, value: int."
    invariants: none
    covered_by: none
    ---
    @dataclass
    class MyModel:
        name: str
        value: int
"""
        result = parse_s0ma(source)
        assert len(result.cells) == 1
        c = result.cells[0]
        assert c.name == "MyModel"
        assert c.kind == Kind.MODEL
        assert c.visibility == Visibility.PUBLIC
        assert c.body is not None
        assert "class MyModel" in c.body

    def test_constant_cell(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell MAX_RETRIES :: DOMAIN
    kind: CONSTANT
    visibility: INTERNAL
    intent: "Maximum retry count."
    schema: "int constant. Value: 3."
    invariants: none
    covered_by: none
    ---
    MAX_RETRIES: int = 3
"""
        result = parse_s0ma(source)
        c = result.cells[0]
        assert c.name == "MAX_RETRIES"
        assert c.kind == Kind.CONSTANT

    def test_exception_cell(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: [MyError]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell MyError :: DOMAIN
    kind: EXCEPTION
    visibility: PUBLIC
    intent: "Custom error for validation."
    schema: "Exception subclass. message: str."
    invariants: "message is non-empty."
    covered_by: none
    ---
    class MyError(Exception):
        def __init__(self, message: str):
            self.message = message
            super().__init__(message)
"""
        result = parse_s0ma(source)
        c = result.cells[0]
        assert c.kind == Kind.EXCEPTION
        assert c.invariants == "message is non-empty."

    def test_enum_cell(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell Color :: DOMAIN
    kind: ENUM
    visibility: INTERNAL
    intent: "Color enumeration."
    schema: "Enum with RED, GREEN, BLUE."
    invariants: none
    covered_by: none
    ---
    class Color(Enum):
        RED = 'red'
        GREEN = 'green'
        BLUE = 'blue'
"""
        result = parse_s0ma(source)
        assert result.cells[0].kind == Kind.ENUM

    def test_all_cell_kinds(self) -> None:
        # Each kind requires an appropriate body type:
        # CLASS kinds need class definitions, CONSTANT needs assignment,
        # TYPE needs assignment or type alias.
        kind_bodies = {
            "MODEL": "    class c:\n        pass",
            "CONSTANT": "    c: int = 42",
            "CONFIG": "    class c:\n        debug: bool = False",
            "ENUM": "    class c:\n        X = 'x'",
            "EXCEPTION": "    class c(Exception):\n        pass",
            "TYPE": "    c = str",
        }
        for kind, body in kind_bodies.items():
            source = f"""\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

cell c :: DOMAIN
    kind: {kind}
    visibility: INTERNAL
    intent: "A cell."
    schema: "Description."
    invariants: none
    covered_by: none
    ---
{body}
"""
            result = parse_s0ma(source)
            assert result.cells[0].kind == Kind[kind]


# ---------------------------------------------------------------------------
# Ganglion declarations
# ---------------------------------------------------------------------------


class TestGanglionDeclaration:
    """Tests for ganglion parsing."""

    def test_ganglion_basic(self) -> None:
        source = """\
module m
    layer: APPLICATION
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
ganglion health_check :: APPLICATION
    visibility: INTERNAL
    intent: "Monitors system health."
    observes: [process_signal, validate_envelope]
    scope: SUBSYSTEM
    priors: "Signals should complete within latency bounds."
    on_anomaly: "Log and alert if latency exceeds threshold."
    forbids: none
    depends_on: none
    covered_by: none
    ---
    def health_check(signal):
        pass
"""
        result = parse_s0ma(source)
        assert len(result.ganglia) == 1
        g = result.ganglia[0]
        assert g.name == "health_check"
        assert g.visibility == Visibility.INTERNAL
        assert g.observes == ("process_signal", "validate_envelope")
        assert g.scope == EvaluatesAt.SUBSYSTEM
        assert "latency" in g.priors
        assert g.body is not None


# ---------------------------------------------------------------------------
# Test declarations
# ---------------------------------------------------------------------------


class TestTestDeclaration:
    """Tests for test declaration parsing."""

    def test_basic_test(self) -> None:
        source = """\
module m
    layer: APPLICATION
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
test test_process_signal :: APPLICATION
    intent: "Verifies signal processing works correctly."
    tests: [process_signal]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_process_signal():
        assert True
"""
        result = parse_s0ma(source)
        assert len(result.tests) == 1
        t = result.tests[0]
        assert t.name == "test_process_signal"
        assert t.tests == ("process_signal",)
        assert t.body is not None

    def test_test_with_optional_fields(self) -> None:
        source = """\
module m
    layer: APPLICATION
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
test test_validation :: APPLICATION
    intent: "Verifies validation logic."
    tests: [validate_envelope, process_signal]
    expects: "Valid envelopes are available"
    tags: [unit, fast]
    depends_on: none
    mocks: none
    ---
    def test_validation():
        pass
"""
        result = parse_s0ma(source)
        t = result.tests[0]
        assert t.tests == ("validate_envelope", "process_signal")
        assert t.expects == "Valid envelopes are available"
        assert t.tags == ("unit", "fast")


# ---------------------------------------------------------------------------
# Standalone axon declarations
# ---------------------------------------------------------------------------


class TestAxonDeclaration:
    """Tests for standalone axon parsing."""

    def test_basic_axon(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
axon caller -> target
    relation: CALLS
    intent: "Caller invokes target."
    carries: "request data"
    coupling: LOOSE
"""
        result = parse_s0ma(source)
        assert len(result.axons) == 1
        a = result.axons[0]
        assert a.source == "caller"
        assert a.target == "target"
        assert a.relation == Relation.CALLS
        assert a.intent == "Caller invokes target."
        assert a.carries == "request data"
        assert a.coupling == Coupling.LOOSE

    def test_axon_all_relation_types(self) -> None:
        for rel in ("CALLS", "CONSTRUCTS", "READS", "CONFIGURES", "PRODUCES", "CONSUMES"):
            source = f"""\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

axon a -> b
    relation: {rel}
    intent: "Dependency."
    carries: "data"
    coupling: TIGHT
"""
            result = parse_s0ma(source)
            assert result.axons[0].relation == Relation[rel]


# ---------------------------------------------------------------------------
# Multi-line strings
# ---------------------------------------------------------------------------


class TestMultiLineStrings:
    """Tests for multi-line quoted string fields."""

    def test_multi_line_intent(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "This is a multi-line
        intent that spans two lines."
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert "multi-line" in result.module.intent
        assert "two lines" in result.module.intent

    def test_multi_line_in_nerve(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_thing :: DOMAIN
    kind: FUNCTION
    visibility: INTERNAL
    intent: "Does something important
        that requires a longer description."
    expects: "input is valid and non-empty"
    guarantees: "output is always correct
        even in edge cases"
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
    def do_thing():
        pass
"""
        result = parse_s0ma(source)
        n = result.nerves[0]
        assert "longer description" in n.intent
        assert "edge cases" in n.guarantees


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestParseErrors:
    """Tests for error handling."""

    def test_empty_file(self) -> None:
        with pytest.raises(S0maParseError, match="Empty .s0ma file"):
            parse_s0ma("")

    def test_no_module_first(self) -> None:
        source = """\
nerve do_thing :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "A nerve."
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
    def do_thing():
        pass
"""
        with pytest.raises(S0maParseError, match="must begin with a module"):
            parse_s0ma(source)

    def test_multiple_modules(self) -> None:
        source = """\
module first
    layer: DOMAIN
    version: 1.0.0
    intent: "First module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
module second
    layer: DOMAIN
    version: 1.0.0
    intent: "Second module."
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        with pytest.raises(S0maParseError, match="Multiple module"):
            parse_s0ma(source)

    def test_missing_required_field_module_layer(self) -> None:
        source = """\
module m
    version: 1.0.0
    intent: "Missing layer."
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        with pytest.raises(S0maParseError) as exc_info:
            parse_s0ma(source)
        assert exc_info.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert "layer" in exc_info.value.message

    def test_missing_required_field_module_version(self) -> None:
        source = """\
module m
    layer: DOMAIN
    intent: "Missing version."
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        with pytest.raises(S0maParseError) as exc_info:
            parse_s0ma(source)
        assert exc_info.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert "version" in exc_info.value.message

    def test_missing_required_field_module_intent(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        with pytest.raises(S0maParseError) as exc_info:
            parse_s0ma(source)
        assert exc_info.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert "intent" in exc_info.value.message

    def test_missing_required_field_module_exports(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Missing exports."
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        with pytest.raises(S0maParseError) as exc_info:
            parse_s0ma(source)
        assert exc_info.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert "exports" in exc_info.value.message

    def test_missing_nerve_kind(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve n :: DOMAIN
    visibility: INTERNAL
    intent: "Missing kind."
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
    def n():
        pass
"""
        with pytest.raises(S0maParseError) as exc_info:
            parse_s0ma(source)
        assert exc_info.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert "kind" in exc_info.value.message

    def test_missing_nerve_evaluates_at(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve n :: DOMAIN
    kind: FUNCTION
    visibility: INTERNAL
    intent: "Missing evaluates_at."
    expects: "none"
    guarantees: "none"
    forbids: none
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
    def n():
        pass
"""
        with pytest.raises(S0maParseError) as exc_info:
            parse_s0ma(source)
        assert exc_info.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert "evaluates_at" in exc_info.value.message

    def test_missing_cell_schema(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell c :: DOMAIN
    kind: MODEL
    visibility: INTERNAL
    intent: "Missing schema."
    invariants: none
    covered_by: none
    ---
    class c:
        pass
"""
        with pytest.raises(S0maParseError) as exc_info:
            parse_s0ma(source)
        assert exc_info.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert "schema" in exc_info.value.message

    def test_missing_axon_relation(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
axon a -> b
    intent: "Missing relation."
    carries: "data"
    coupling: TIGHT
"""
        with pytest.raises(S0maParseError) as exc_info:
            parse_s0ma(source)
        assert exc_info.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert "relation" in exc_info.value.message

    def test_invalid_layer(self) -> None:
        source = """\
module m
    layer: INVALID_LAYER
    version: 1.0.0
    intent: "Bad layer."
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        with pytest.raises(S0maParseError, match="Invalid layer"):
            parse_s0ma(source)

    def test_invalid_kind(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve n :: DOMAIN
    kind: INVALID_KIND
    visibility: INTERNAL
    intent: "Bad kind."
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
    def n():
        pass
"""
        with pytest.raises(S0maParseError, match="Invalid kind"):
            parse_s0ma(source)

    def test_invalid_visibility(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve n :: DOMAIN
    kind: FUNCTION
    visibility: PRIVATE
    intent: "Bad visibility."
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
    def n():
        pass
"""
        with pytest.raises(S0maParseError, match="Invalid visibility"):
            parse_s0ma(source)

    def test_error_has_remediation(self) -> None:
        """Every parse error must include actionable remediation."""
        with pytest.raises(S0maParseError) as exc_info:
            parse_s0ma("")
        assert exc_info.value.remediation
        assert len(exc_info.value.remediation) > 10

    def test_bare_top_level_code(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []

x = 42
"""
        with pytest.raises(S0maParseError, match="Unexpected content"):
            parse_s0ma(source)


# ---------------------------------------------------------------------------
# Source locations
# ---------------------------------------------------------------------------


class TestSourceLocations:
    """Tests for SourceLocation on AST nodes."""

    def test_module_location(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source, "test.s0ma")
        loc = result.module.location
        assert loc is not None
        assert loc.start_line == 1
        assert loc.file == "test.s0ma"

    def test_nerve_location(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve n :: DOMAIN
    kind: FUNCTION
    visibility: INTERNAL
    intent: "A nerve."
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
    def n():
        pass
"""
        result = parse_s0ma(source, "test.s0ma")
        loc = result.nerves[0].location
        assert loc is not None
        assert loc.start_line == 13
        assert loc.file == "test.s0ma"

    # ``end_line`` is the declaration's last non-blank line. It used to be
    # the line before the next header — the blank line between two
    # declarations — and, for the last declaration of a file ending in a
    # newline, one line past the end of the file. The source map's
    # ``body_source`` and the ``# s0ma:`` pointers inherited the error.

    _MODULE = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: [first, second]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""

    @staticmethod
    def _nerve(name: str) -> str:
        return f"""\
nerve {name} :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "A nerve."
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
    def {name}():
        return 1
"""

    @staticmethod
    def _line_of(source: str, text: str) -> int:
        """1-indexed number of the only line whose stripped text is *text*."""
        (number,) = [
            i
            for i, line in enumerate(source.split("\n"), start=1)
            if line.strip() == text
        ]
        return number

    @pytest.mark.parametrize("blank_lines", [0, 1, 2, 3])
    def test_end_line_stops_before_the_blank_lines_after_a_declaration(
        self, blank_lines: int
    ) -> None:
        gap = "\n" * blank_lines
        source = self._MODULE + gap + self._nerve("first") + gap + self._nerve("second")
        result = parse_s0ma(source, "test.s0ma")
        assert result.module.location is not None
        assert result.module.location.end_line == self._line_of(
            source, "exports_helpers: none"
        )
        first = result.nerves[0].location
        assert first is not None
        # The last line of ``first`` is its last body line, however many
        # blank lines stand between it and ``second``.
        assert first.end_line == self._line_of(source, "def first():") + 1

    @pytest.mark.parametrize("ending", ["", "\n", "\n\n\n"])
    def test_end_line_never_passes_the_end_of_the_file(self, ending: str) -> None:
        source = self._MODULE + "\n" + self._nerve("first").rstrip("\n") + ending
        result = parse_s0ma(source, "test.s0ma")
        loc = result.nerves[0].location
        assert loc is not None
        last_line = self._line_of(source, "return 1")
        assert loc.end_line == last_line
        assert loc.end_line <= len(source.splitlines())

    def test_body_less_declaration_ends_on_its_last_field(self) -> None:
        source = (
            self._MODULE
            + "\n"
            + """\
axon first -> second
    relation: CALLS
    intent: "Caller invokes target."
    carries: "request data"
    coupling: LOOSE


"""
            + self._nerve("first")
        )
        result = parse_s0ma(source, "test.s0ma")
        loc = result.axons[0].location
        assert loc is not None
        assert loc.end_line == self._line_of(source, "coupling: LOOSE")


# ---------------------------------------------------------------------------
# Golden fixture
# ---------------------------------------------------------------------------


class TestGoldenFixture:
    """The golden test file must parse completely."""

    def test_golden_fixture_parses(self) -> None:
        source = GOLDEN_FIXTURE.read_text()
        result = parse_s0ma(source, "signal_processor.s0ma")
        assert isinstance(result, S0maModule)

    def test_golden_module(self) -> None:
        source = GOLDEN_FIXTURE.read_text()
        result = parse_s0ma(source, "signal_processor.s0ma")
        m = result.module
        assert m.name == "signal_processor"
        assert m.layer == Layer.APPLICATION
        assert m.version == "1.0.0"
        assert m.exports == ("process_signal", "SignalEnvelope")
        assert len(m.requires) == 3
        assert len(m.uses) == 2

    def test_golden_cells(self) -> None:
        source = GOLDEN_FIXTURE.read_text()
        result = parse_s0ma(source, "signal_processor.s0ma")
        assert len(result.cells) == 2
        envelope = result.cells[0]
        assert envelope.name == "SignalEnvelope"
        assert envelope.kind == Kind.MODEL
        assert envelope.visibility == Visibility.PUBLIC
        constant = result.cells[1]
        assert constant.name == "MAX_STALENESS_SECONDS"
        assert constant.kind == Kind.CONSTANT
        assert constant.visibility == Visibility.INTERNAL

    def test_golden_nerves(self) -> None:
        source = GOLDEN_FIXTURE.read_text()
        result = parse_s0ma(source, "signal_processor.s0ma")
        assert len(result.nerves) == 2
        validate = result.nerves[0]
        assert validate.name == "validate_envelope"
        assert validate.kind == Kind.FUNCTION
        assert validate.visibility == Visibility.INTERNAL
        assert validate.raises == ("SignalValidationError",)
        assert validate.latency_ms == 5
        assert len(validate.depends_on) == 1
        assert validate.depends_on[0].target == "MAX_STALENESS_SECONDS"
        assert validate.depends_on[0].relation == Relation.READS

        process = result.nerves[1]
        assert process.name == "process_signal"
        assert process.kind == Kind.ORCHESTRATOR
        assert process.visibility == Visibility.PUBLIC
        assert process.latency_ms == 50
        assert len(process.depends_on) == 1
        assert process.depends_on[0].target == "validate_envelope"
        assert process.depends_on[0].relation == Relation.CALLS

    def test_golden_axon(self) -> None:
        source = GOLDEN_FIXTURE.read_text()
        result = parse_s0ma(source, "signal_processor.s0ma")
        assert len(result.axons) == 1
        a = result.axons[0]
        assert a.source == "process_signal"
        assert a.target == "select_evaluator"
        assert a.relation == Relation.CALLS
        assert a.coupling == Coupling.LOOSE
        assert "evaluator selection" in a.intent

    def test_golden_bodies_preserved(self) -> None:
        source = GOLDEN_FIXTURE.read_text()
        result = parse_s0ma(source, "signal_processor.s0ma")
        # Cell bodies
        assert result.cells[0].body is not None
        assert "class SignalEnvelope" in result.cells[0].body
        assert result.cells[1].body is not None
        assert "300" in result.cells[1].body
        # Nerve bodies
        assert result.nerves[0].body is not None
        assert "def validate_envelope" in result.nerves[0].body
        assert result.nerves[1].body is not None
        assert "def process_signal" in result.nerves[1].body


# ---------------------------------------------------------------------------
# Mixed declarations
# ---------------------------------------------------------------------------


class TestMixedDeclarations:
    """Tests for files with multiple declaration types."""

    def test_all_declaration_types(self) -> None:
        source = """\
module m
    layer: APPLICATION
    version: 1.0.0
    intent: "Module with all types."
    exports: [do_thing, MyModel]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell MyModel :: APPLICATION
    kind: MODEL
    visibility: PUBLIC
    intent: "A model."
    schema: "Dataclass."
    invariants: none
    covered_by: none
    ---
    class MyModel:
        pass

nerve do_thing :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Does a thing."
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
    def do_thing():
        pass

ganglion monitor :: APPLICATION
    visibility: INTERNAL
    intent: "Monitors things."
    observes: [do_thing]
    scope: SUBSYSTEM
    priors: "Things should work."
    on_anomaly: "Alert."
    forbids: none
    depends_on: none
    covered_by: none
    ---
    def monitor(signal):
        pass

test test_thing :: APPLICATION
    intent: "Tests do_thing."
    tests: [do_thing]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_thing():
        assert True

axon do_thing -> some_external
    relation: CALLS
    intent: "Calls external."
    carries: "data"
    coupling: LOOSE
"""
        result = parse_s0ma(source)
        assert len(result.cells) == 1
        assert len(result.nerves) == 1
        assert len(result.ganglia) == 1
        assert len(result.tests) == 1
        assert len(result.axons) == 1


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


class TestComments:
    """Comments should be ignored."""

    def test_comments_between_declarations(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: []

# This is a comment between declarations
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve n :: DOMAIN
    kind: FUNCTION
    visibility: INTERNAL
    intent: "A nerve."
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
    def n():
        pass
"""
        result = parse_s0ma(source)
        assert len(result.nerves) == 1


# ---------------------------------------------------------------------------
# Provides field
# ---------------------------------------------------------------------------


class TestProvidesField:
    """Tests for the provides field on nerve declarations."""

    def test_provides_parsed_on_nerve(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module with provides."
    exports: [svc]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve svc :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    intent: "A service nerve with provides."
    expects: "none"
    guarantees: "returns results"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: [read_file, write_file]
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
    def read_file():
        pass
    def write_file():
        pass
"""
        result = parse_s0ma(source)
        assert len(result.nerves) == 1
        assert result.nerves[0].provides == ("read_file", "write_file")

    def test_provides_empty_list(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module with empty provides."
    exports: [svc]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve svc :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    intent: "A service nerve."
    expects: "none"
    guarantees: "returns results"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: []
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
    def svc():
        pass
"""
        result = parse_s0ma(source)
        assert result.nerves[0].provides == ()

    def test_provides_absent(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module without provides."
    exports: [svc]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve svc :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    intent: "A service nerve."
    expects: "none"
    guarantees: "returns results"
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
    def svc():
        pass
"""
        result = parse_s0ma(source)
        assert result.nerves[0].provides == ()


# ---------------------------------------------------------------------------
# Soft requires field
# ---------------------------------------------------------------------------


class TestSoftRequires:
    """Tests for the soft_requires field on module declarations."""

    def test_soft_requires_parsed(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module with soft requires."
    soft_requires: [anthropic, prompt_toolkit]
    exports: []
    requires: none
    uses: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert len(result.module.soft_requires) == 2
        assert result.module.soft_requires[0].module_path == "anthropic"
        assert result.module.soft_requires[1].module_path == "prompt_toolkit"

    def test_soft_requires_with_alias(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module with aliased soft requires."
    soft_requires: [anthropic as ant]
    exports: []
    requires: none
    uses: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert len(result.module.soft_requires) == 1
        assert result.module.soft_requires[0].module_path == "anthropic"
        assert result.module.soft_requires[0].alias == "ant"

    def test_soft_requires_absent(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module without soft requires."
    exports: []
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert result.module.soft_requires == ()

    def test_soft_requires_colon_form(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module with colon-form soft requires."
    soft_requires: [unittest.mock:patch]
    exports: []
    requires: none
    uses: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        result = parse_s0ma(source)
        assert len(result.module.soft_requires) == 1
        assert result.module.soft_requires[0].module_path == "unittest.mock.patch"
        assert result.module.soft_requires[0].is_from_import is True


# ---------------------------------------------------------------------------
# MS 11: Abstract, interface, and returns fields
# ---------------------------------------------------------------------------


class TestAbstractField:
    """Test parsing of the abstract: true/false field on nerves."""

    def test_abstract_true(self) -> None:
        source = """\
module m
    layer: INFRASTRUCTURE
    version: 1.0.0
    intent: "Module with abstract nerve."
    exports: [LLMAdapter]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve LLMAdapter :: INFRASTRUCTURE
    kind: ADAPTER
    visibility: PUBLIC
    intent: "Abstract LLM adapter interface."
    expects: "None"
    guarantees: "Subclasses implement chat and chat_stream."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    abstract: true
    interface: [chat, chat_stream]
    provides: none
    returns: none
    raises: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
"""
        result = parse_s0ma(source)
        assert len(result.nerves) == 1
        nerve = result.nerves[0]
        assert nerve.abstract is True
        assert nerve.interface == ("chat", "chat_stream")

    def test_abstract_false_explicit(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module with explicit non-abstract nerve."
    exports: [Foo]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve Foo :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "A concrete nerve."
    expects: "None"
    guarantees: "Returns result."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    abstract: false
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
    def Foo():
        return 42
"""
        result = parse_s0ma(source)
        assert result.nerves[0].abstract is False
        assert result.nerves[0].interface == ()

    def test_abstract_absent_defaults_false(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module without abstract field."
    exports: [Bar]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve Bar :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "A regular nerve."
    expects: "None"
    guarantees: "Returns result."
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
    def Bar():
        return 42
"""
        result = parse_s0ma(source)
        assert result.nerves[0].abstract is False

    def test_abstract_invalid_value(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module with bad abstract value."
    exports: [Bad]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve Bad :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Bad nerve."
    expects: "None"
    guarantees: "None."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    abstract: yes
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
"""
        with pytest.raises(S0maParseError, match="must be true or false"):
            parse_s0ma(source)

    def test_interface_without_abstract(self) -> None:
        """interface field parses even without abstract — validation catches it."""
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: [X]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve X :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Nerve."
    expects: "None"
    guarantees: "None."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    interface: [method_a, method_b]
    provides: none
    returns: none
    raises: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def X():
        pass
"""
        result = parse_s0ma(source)
        assert result.nerves[0].interface == ("method_a", "method_b")
        assert result.nerves[0].abstract is False


class TestReturnsField:
    """Test parsing of the returns: [...] field on nerves."""

    def test_returns_parsed(self) -> None:
        source = """\
module m
    layer: PRESENTATION
    version: 1.0.0
    intent: "Module with returns field."
    exports: [CLIGateway]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve CLIGateway :: PRESENTATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "CLI entry point."
    expects: "None"
    guarantees: "Provides dict of operations."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    returns: [receive_message, send_response, start, stop]
    provides: none
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
    def CLIGateway():
        def receive_message(): pass
        def send_response(): pass
        def start(): pass
        def stop(): pass
        return {
            "receive_message": receive_message,
            "send_response": send_response,
            "start": start,
            "stop": stop,
        }
"""
        result = parse_s0ma(source)
        nerve = result.nerves[0]
        assert nerve.returns == ("receive_message", "send_response", "start", "stop")

    def test_returns_absent_defaults_empty(self) -> None:
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: [X]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve X :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Nerve."
    expects: "None"
    guarantees: "None."
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
    def X():
        pass
"""
        result = parse_s0ma(source)
        assert result.nerves[0].returns == ()

    def test_returns_with_provides(self) -> None:
        """A nerve may have both provides and returns."""
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Module."
    exports: [Svc]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve Svc :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    intent: "Service with both fields."
    expects: "None"
    guarantees: "Returns dict."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: [op_a, op_b]
    returns: [op_a, op_b]
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
    def Svc():
        def op_a(): pass
        def op_b(): pass
        return {"op_a": op_a, "op_b": op_b}
"""
        result = parse_s0ma(source)
        nerve = result.nerves[0]
        assert nerve.provides == ("op_a", "op_b")
        assert nerve.returns == ("op_a", "op_b")


# ---------------------------------------------------------------------------
# Dogfooding: parser uses @component
# ---------------------------------------------------------------------------


class TestDogfooding:
    """Verify parser components are registered with s0ma."""

    def test_parser_class_has_component(self) -> None:
        from s0ma_dsl.parser.s0ma_parser import S0maParser

        assert hasattr(S0maParser, "__component__")
