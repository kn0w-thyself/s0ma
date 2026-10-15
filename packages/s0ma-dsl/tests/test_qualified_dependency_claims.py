"""Regression: generated cross-module dependency claims must not warn.

The emitter writes ``dependencies=["<module>::<Name>"]`` (DSL-M2 canonical
form, ADR-011 §(d)) while registering every generated component under its
bare name — ``module_scoped`` stays False. s0ma-core's
``ComponentRegistry._resolve_key`` used to short-circuit any qualified
identifier that was not a direct key hit, so importing two generated
modules joined by one cross-module ``depends_on`` edge logged a false
``declares dependency '<module>::<Name>' which is not yet registered``
warning per edge (0.15.1, observed on every cross-module edge of the
s0ma-cpx pilot).

This file transpiles a two-module project — a producer model and a
consumer nerve — imports both generated modules, and pins: the emitter
still writes the qualified claim, importing produces zero dependency
warnings, and the dependency edge actually resolves.
"""

from __future__ import annotations

import logging
import sys
import types
from typing import TYPE_CHECKING

from s0ma.registry import ComponentRegistry, reset_registry, set_registry

from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.parser.s0ma_parser import parse_s0ma

if TYPE_CHECKING:
    import pytest

PRODUCER_SRC = '''module reading_models
    layer: DOMAIN
    version: 0.1.0
    intent: "Reading models for the qualified-dependency regression test project."
    exports: [LightReading]
    requires: [dataclasses:dataclass]
    uses: []

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

cell LightReading :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "One ambient-light sample carried across the module boundary."
    schema: "counts: int relative light level"
    invariants: "counts is non-negative"
    dataclass_invariants: ["counts >= 0"]
    covered_by: none
    ---
    @dataclass
    class LightReading:
        counts: int
'''

CONSUMER_SRC = '''module senses
    layer: APPLICATION
    version: 0.1.0
    intent: "Consumer module declaring one qualified cross-module dependency."
    exports: [read_light]
    requires: []
    uses: [reading_models.LightReading]

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve read_light :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Sense ambient light by constructing the producer module's model."
    expects: "counts is a non-negative int"
    guarantees: "returns a LightReading carrying counts"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on:
        reading_models.LightReading: {relation: CONSTRUCTS, carries: "light", coupling: TIGHT}
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def read_light(counts):
        return LightReading(counts=counts)
'''


def _emit(module_name: str, src: str) -> str:
    """Parse and emit one module, filling the build-time hash placeholders."""
    mod = parse_s0ma(src, filename=f"{module_name}.s0ma")
    py = PythonEmitter(module_name=module_name).emit(mod)
    return py.replace("__S0MA_SOURCE_HASH__", "x").replace(
        "__S0MA_OUTPUT_HASH__", "y"
    )


def _import_generated(module_name: str, code: str) -> types.ModuleType:
    """Execute emitted code as a real module in ``sys.modules``.

    The consumer's ``uses:`` import (``from reading_models import ...``)
    needs the producer resolvable through ``sys.modules``, and
    ``@component`` derives ``module_path`` from ``__module__`` — so the
    generated code must run inside a genuine module namespace, exactly as
    an import executes it.
    """
    mod = types.ModuleType(module_name)
    sys.modules[module_name] = mod
    exec(compile(code, f"<{module_name}>", "exec"), mod.__dict__)  # noqa: S102
    return mod


class TestQualifiedCrossModuleDependencyClaims:
    """Two generated modules, one qualified dependency edge, no warnings."""

    def test_importing_generated_modules_warns_nothing_and_resolves(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        registry = ComponentRegistry(persist=False)
        set_registry(registry)
        try:
            producer_py = _emit("reading_models", PRODUCER_SRC)
            consumer_py = _emit("senses", CONSUMER_SRC)

            # The emitter half of the regression: the cross-module claim is
            # written in canonical qualified form, not as a bare name.
            assert 'dependencies=["reading_models::LightReading"],' in consumer_py

            with caplog.at_level(logging.WARNING, logger="s0ma"):
                _import_generated("reading_models", producer_py)
                _import_generated("senses", consumer_py)

            dependency_warnings = [
                record.getMessage()
                for record in caplog.records
                if "declares dependency" in record.getMessage()
            ]
            assert dependency_warnings == []

            # The registry half: the qualified claim resolves to the
            # bare-keyed generated registration.
            spec = registry.get("reading_models::LightReading")
            assert spec is not None
            assert spec.name == "LightReading"
            assert spec.module_path == "reading_models"

            deps = registry.get_dependencies("read_light")
            assert [d.name for d in deps] == ["LightReading"]
        finally:
            sys.modules.pop("reading_models", None)
            sys.modules.pop("senses", None)
            reset_registry()
