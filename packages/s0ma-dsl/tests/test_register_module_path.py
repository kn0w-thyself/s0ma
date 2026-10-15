"""Tests for PRE-8 (0.14.0): the DSL emitter threads ``module_path``
into :func:`register_constant` and :func:`register_type` calls so the
registry knows which module owns each cell.

Pre-PRE-8 the runtime helpers accepted only ``name``, ``layer``,
``intent``, ``metadata``. The emitter dropped ``module_path`` on the
floor — fr3d's ``WebViewRegistry`` walker had to derive it from the
spec's ``source_file`` path with a fragile fallback. Post-PRE-8 the
emitter passes the transpiler's ``module_name`` straight through, the
runtime bridge introspects the framework's signature so older
s0ma-core builds (pre-0.3.0, then distributed as ``s0ma-framework``)
keep working, and the spec carries
``module_path`` end-to-end.
"""

from __future__ import annotations

import inspect

from s0ma_dsl.runtime_bridge import registration


def test_register_constant_accepts_module_path_kwarg() -> None:
    sig = inspect.signature(registration.register_constant)
    assert "module_path" in sig.parameters
    assert sig.parameters["module_path"].default is None


def test_register_type_accepts_module_path_kwarg() -> None:
    sig = inspect.signature(registration.register_type)
    assert "module_path" in sig.parameters
    assert sig.parameters["module_path"].default is None


def test_register_constant_propagates_module_path_to_registry() -> None:
    """End-to-end: bridge call → registry → spec carries ``module_path``."""
    from s0ma.registry import ComponentRegistry, set_registry
    from s0ma.types import Layer

    registry = ComponentRegistry(persist=False)
    set_registry(registry)
    try:
        registration.register_constant(
            name="DEMO_CONST",
            layer=Layer.APPLICATION,
            intent="A demo constant for module_path propagation testing",
            metadata={"visibility": "public"},
            module_path="presentation.web.shell_view",
        )
        spec = registry.get("DEMO_CONST")
        assert spec is not None
        assert spec.module_path == "presentation.web.shell_view"
    finally:
        from s0ma.registry import reset_registry

        reset_registry()


def test_register_constant_omitting_module_path_is_backward_compatible() -> None:
    """Pre-PRE-8 emitted code (no ``module_path``) keeps working."""
    from s0ma.registry import ComponentRegistry, reset_registry, set_registry
    from s0ma.types import Layer

    registry = ComponentRegistry(persist=False)
    set_registry(registry)
    try:
        # No ``module_path`` argument — simulates a pre-0.14.0 emitted
        # ``.py`` file calling the bridge.
        registration.register_constant(
            name="LEGACY_CONST",
            layer=Layer.APPLICATION,
            intent="A legacy constant registered without module_path",
            metadata={"visibility": "public"},
        )
        spec = registry.get("LEGACY_CONST")
        assert spec is not None
        assert spec.module_path == ""  # back-compat default
    finally:
        reset_registry()


def test_emitter_includes_module_path_in_register_constant_call(
    tmp_path,
) -> None:
    """The transpiled ``.py`` carries ``module_path=...`` in the
    ``register_constant(...)`` call.

    Compile a tiny ``.s0ma`` module containing a CONSTANT cell, then
    grep the generated Python for the threading.
    """
    from s0ma_dsl.codegen.python_emitter import PythonEmitter
    from s0ma_dsl.parser.s0ma_parser import parse_s0ma

    source = """\
module demo_module
    layer: APPLICATION
    version: 0.1.0
    intent: "Demo module exercising the PRE-8 module_path emission."
    exports: [DEMO_VALUE]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
    ---

cell DEMO_VALUE :: APPLICATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Demo CONSTANT cell that should carry module_path on register."
    schema: "string"
    invariants: none
    covered_by: none
    ---
    DEMO_VALUE = "hello"
"""
    module = parse_s0ma(source, filename="demo_module.s0ma")
    emitter = PythonEmitter()
    emitted = emitter.emit(module)
    assert "register_constant(" in emitted
    assert 'module_path="demo_module"' in emitted


def test_emitter_includes_module_path_in_register_type_call(tmp_path) -> None:
    """The transpiled ``.py`` carries ``module_path=...`` in the
    ``register_type(...)`` call.
    """
    from s0ma_dsl.codegen.python_emitter import PythonEmitter
    from s0ma_dsl.parser.s0ma_parser import parse_s0ma

    source = """\
module type_demo
    layer: DOMAIN
    version: 0.1.0
    intent: "Demo module exercising the PRE-8 module_path emission for TYPE cells."
    exports: [UserId]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
    ---

cell UserId :: DOMAIN
    kind: TYPE
    visibility: PUBLIC
    intent: "Type alias for user identifier in the domain layer."
    schema: "int"
    invariants: none
    covered_by: none
    ---
    UserId = int
"""
    module = parse_s0ma(source, filename="type_demo.s0ma")
    emitter = PythonEmitter()
    emitted = emitter.emit(module)
    assert "register_type(" in emitted
    assert 'module_path="type_demo"' in emitted
