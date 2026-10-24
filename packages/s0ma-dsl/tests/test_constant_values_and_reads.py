"""A constant carries its value and its readers.

``register_constant`` took a name, a layer, an intent and metadata and no
value; the IR for a constant cell had no literal; no derived edge
targeted a CONSTANT, so ``impact <constant>`` named nobody and
``dependencies <nerve>`` never mentioned the limit the nerve enforces.

These tests pin the four surfaces that now agree: the canonical IR
(``fields.value`` and derived ``READS`` edges), the emitted registration
(the ``value=`` argument), the self-context companion (``value`` and
``edges``) and the registry a transpiled module registers into.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from s0ma_dsl.ast_nodes.enums import Relation
from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.codegen.self_context import build_self_context_document
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.ir.constant_values import CONSTANT_VALUE_MAX_BYTES, constant_literal
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.semantic.derived_edges import analyze_derived_edges
from s0ma_dsl.semantic.validator import validate_module

if TYPE_CHECKING:
    from pathlib import Path

    from s0ma_dsl.ast_nodes.nodes import S0maModule


def _module_header(name: str, exports: str, uses: str = "none") -> str:
    return f"""\
module {name}
    layer: APPLICATION
    version: 0.1.0
    intent: "Fixture module for constant values and the edges that read them."
    exports: [{exports}]
    requires: none
    uses: {uses}

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""


def _constant(name: str, body: str, schema: str = "a constant") -> str:
    return f"""
cell {name} :: APPLICATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Fixture constant {name} for the value and reader tests."
    schema: "{schema}"
    invariants: none
    covered_by: none
    ---
    {body}
"""


def _nerve(name: str, body: str, depends_on: str = "none") -> str:
    return f"""
nerve {name} :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "Fixture nerve {name} that reads one or more constants."
    expects: none
    guarantees: "answers from the constants it reads"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: {depends_on}
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
{body}
"""


_LONG_TEXT = "x" * (CONSTANT_VALUE_MAX_BYTES + 10)

LIMITS_SOURCE = (
    _module_header(
        "limits",
        "MIN_INTERVAL_SECONDS, SUFFIXES, OPTIONAL, NEGATIVE, COMPUTED, LONG, "
        "SchedulerService, AuthoredReader, Shadowing",
    )
    + _constant("MIN_INTERVAL_SECONDS", "MIN_INTERVAL_SECONDS = 60", "integer seconds")
    + _constant("SUFFIXES", 'SUFFIXES: tuple[str, ...] = (".py", ".s0ma.json")')
    + _constant("OPTIONAL", "OPTIONAL = None")
    + _constant("NEGATIVE", "NEGATIVE = -1.5")
    + _constant("COMPUTED", 'COMPUTED = len("abc")')
    + _constant("LONG", f'LONG = "{_LONG_TEXT}"')
    + _nerve(
        "SchedulerService",
        "    def SchedulerService(tick: int = MIN_INTERVAL_SECONDS) -> dict:\n"
        "        floor = MIN_INTERVAL_SECONDS\n"
        "        return {\"floor\": floor, \"suffixes\": SUFFIXES, \"tick\": tick}",
    )
    + _nerve(
        "AuthoredReader",
        "    def AuthoredReader() -> int:\n"
        "        return MIN_INTERVAL_SECONDS",
        depends_on=(
            "\n        MIN_INTERVAL_SECONDS: {relation: READS, "
            'carries: "the floor", coupling: TIGHT}'
        ),
    )
    + _nerve(
        "Shadowing",
        "    def Shadowing(OPTIONAL) -> object:\n"
        "        NEGATIVE = 3\n"
        "        return (OPTIONAL, NEGATIVE)",
    )
)

CLIENT_SOURCE = (
    _module_header("client", "Planner", uses="[limits.MIN_INTERVAL_SECONDS, limits.SUFFIXES]")
    + _nerve(
        "Planner",
        "    def Planner() -> int:\n"
        "        return MIN_INTERVAL_SECONDS * 2",
    )
)


def _parse(source: str, filename: str) -> S0maModule:
    return parse_s0ma(source, filename=filename)


def _cell(module: S0maModule, name: str):  # type: ignore[no-untyped-def]
    return next(cell for cell in module.cells if cell.name == name)


class TestConstantLiteral:
    def test_simple_literals_are_read(self) -> None:
        module = _parse(LIMITS_SOURCE, "limits.s0ma")
        assert constant_literal(_cell(module, "MIN_INTERVAL_SECONDS")) == (True, 60)
        assert constant_literal(_cell(module, "SUFFIXES")) == (True, [".py", ".s0ma.json"])
        assert constant_literal(_cell(module, "OPTIONAL")) == (True, None)
        assert constant_literal(_cell(module, "NEGATIVE")) == (True, -1.5)

    def test_expressions_and_oversized_literals_carry_nothing(self) -> None:
        module = _parse(LIMITS_SOURCE, "limits.s0ma")
        assert constant_literal(_cell(module, "COMPUTED")) == (False, None)
        assert constant_literal(_cell(module, "LONG")) == (False, None)

    def test_non_constant_cells_carry_nothing(self) -> None:
        source = _module_header("models", "Shape") + """
cell Shape :: APPLICATION
    kind: MODEL
    visibility: PUBLIC
    intent: "A model cell, which never carries a value."
    schema: "one field"
    invariants: none
    covered_by: none
    ---
    class Shape:
        sides: int = 4
"""
        module = _parse(source, "models.s0ma")
        assert constant_literal(_cell(module, "Shape")) == (False, None)


class TestCanonicalIr:
    def test_value_rides_fields_only_where_a_literal_exists(self) -> None:
        module = _parse(LIMITS_SOURCE, "limits.s0ma")
        ir = build_ir(module, source_text=LIMITS_SOURCE).to_dict()
        fields = {
            component["canonical_id"]: component["fields"]
            for component in ir["components"]
        }
        assert fields["limits::MIN_INTERVAL_SECONDS"]["value"] == 60
        assert fields["limits::SUFFIXES"]["value"] == [".py", ".s0ma.json"]
        assert fields["limits::NEGATIVE"]["value"] == -1.5
        assert "value" in fields["limits::OPTIONAL"]
        assert fields["limits::OPTIONAL"]["value"] is None
        assert "value" not in fields["limits::COMPUTED"]
        assert "value" not in fields["limits::LONG"]
        assert "value" not in fields["limits::SchedulerService"]
        # The IR stays plain JSON for the value: no state tag around it.
        assert json.loads(json.dumps(ir))["components"]

    def test_reads_edges_are_derived_from_bodies(self) -> None:
        module = _parse(LIMITS_SOURCE, "limits.s0ma")
        derived, errors = analyze_derived_edges(
            module, mode=StrictnessMode.STRICT, filename="limits.s0ma"
        )
        assert errors == []
        reads = sorted(
            (edge.source, edge.target_canonical)
            for edge in derived
            if edge.relation is Relation.READS
        )
        assert reads == [
            ("SchedulerService", "limits::MIN_INTERVAL_SECONDS"),
            ("SchedulerService", "limits::SUFFIXES"),
        ]
        assert {edge.origin for edge in derived if edge.relation is Relation.READS} == {
            "constant_reference"
        }
        ir = build_ir(module, derived_edges=derived, source_text=LIMITS_SOURCE).to_dict()
        ir_reads = [
            edge for edge in ir["edges"]["derived"] if edge["relation"] == "READS"
        ]
        assert ir_reads == [
            {
                "origin": "constant_reference",
                "relation": "READS",
                "source": "limits::SchedulerService",
                "target": "limits::MIN_INTERVAL_SECONDS",
            },
            {
                "origin": "constant_reference",
                "relation": "READS",
                "source": "limits::SchedulerService",
                "target": "limits::SUFFIXES",
            },
        ]

    def test_an_authored_edge_wins_and_raises_no_duplicate(self) -> None:
        module = _parse(LIMITS_SOURCE, "limits.s0ma")
        semantic_errors = validate_module(
            module, mode=StrictnessMode.STRICT, filename="limits.s0ma"
        )
        assert [e.code for e in semantic_errors if e.code == "DUPLICATE_AXON"] == []
        derived, errors = analyze_derived_edges(
            module, mode=StrictnessMode.STRICT, filename="limits.s0ma"
        )
        assert [e.code for e in errors] == []
        assert not [
            edge for edge in derived if edge.source == "AuthoredReader"
        ], "the authored READS edge is the one record of that dependency"
        ir = build_ir(module, derived_edges=derived, source_text=LIMITS_SOURCE).to_dict()
        authored = [
            edge for edge in ir["edges"]["authored"]
            if edge["source"] == "limits::AuthoredReader"
        ]
        assert [edge["target"] for edge in authored] == ["limits::MIN_INTERVAL_SECONDS"]

    def test_a_name_the_body_binds_is_not_read_as_the_constant(self) -> None:
        module = _parse(LIMITS_SOURCE, "limits.s0ma")
        derived, _ = analyze_derived_edges(module, filename="limits.s0ma")
        assert not [edge for edge in derived if edge.source == "Shadowing"]

    def test_an_imported_constant_is_read_when_the_project_is_known(self) -> None:
        client = _parse(CLIENT_SOURCE, "client.s0ma")
        alone, _ = analyze_derived_edges(client, filename="client.s0ma")
        assert not [edge for edge in alone if edge.relation is Relation.READS]

        known = frozenset({"limits::MIN_INTERVAL_SECONDS", "limits::SUFFIXES"})
        derived, errors = analyze_derived_edges(
            client, filename="client.s0ma", constant_targets=known
        )
        assert errors == []
        reads = [
            (edge.source, edge.target, edge.target_canonical)
            for edge in derived
            if edge.relation is Relation.READS
        ]
        # SUFFIXES is imported but never read, so only the floor is an edge.
        assert reads == [("Planner", "MIN_INTERVAL_SECONDS", "limits::MIN_INTERVAL_SECONDS")]


class TestEmittedRegistration:
    def test_register_constant_carries_the_literal(self) -> None:
        module = _parse(LIMITS_SOURCE, "limits.s0ma")
        output = PythonEmitter(mode=StrictnessMode.DEV).emit(module)
        compile(output, "limits.py", "exec")
        assert 'name="MIN_INTERVAL_SECONDS",' in output
        assert "    value=60,\n" in output
        assert '    value=[".py", ".s0ma.json"],\n' in output
        assert "    value=None,\n" in output
        assert "    value=-1.5,\n" in output

    def test_no_value_argument_without_a_literal(self) -> None:
        module = _parse(LIMITS_SOURCE, "limits.s0ma")
        output = PythonEmitter(mode=StrictnessMode.DEV).emit(module)
        computed = output[output.index('name="COMPUTED"'):]
        computed = computed[: computed.index(")")]
        assert "value=" not in computed
        long = output[output.index('name="LONG"'):]
        long = long[: long.index(")")]
        assert "value=" not in long

    def test_the_literal_reaches_the_registry(self) -> None:
        from s0ma.registry import ComponentRegistry, set_registry

        module = _parse(LIMITS_SOURCE, "limits.s0ma")
        output = PythonEmitter(mode=StrictnessMode.DEV).emit(module)
        registry = ComponentRegistry(persist=False)
        set_registry(registry)
        try:
            namespace: dict[str, object] = {"__name__": "limits_fixture"}
            exec(compile(output, "limits.py", "exec"), namespace)  # noqa: S102
            floor = registry.get("MIN_INTERVAL_SECONDS")
            assert floor is not None
            assert floor.metadata["value"] == 60
            assert floor.metadata["kind_detail"] == "CONSTANT"
            suffixes = registry.get("SUFFIXES")
            assert suffixes is not None
            assert suffixes.metadata["value"] == [".py", ".s0ma.json"]
            optional = registry.get("OPTIONAL")
            assert optional is not None
            assert "value" in optional.metadata and optional.metadata["value"] is None
            computed = registry.get("COMPUTED")
            assert computed is not None
            assert "value" not in computed.metadata
            snapshot = registry.snapshot().to_dict()
            assert snapshot["components"]["MIN_INTERVAL_SECONDS"]["metadata"]["value"] == 60
        finally:
            from s0ma.registry import reset_registry

            reset_registry()


class TestSelfContext:
    def _document(self, tmp_path: Path) -> dict[str, object]:
        limits = _parse(LIMITS_SOURCE, "limits.s0ma")
        client = _parse(CLIENT_SOURCE, "client.s0ma")
        known = frozenset({"limits::MIN_INTERVAL_SECONDS", "limits::SUFFIXES"})
        build_dir = tmp_path / "build"
        build_dir.mkdir(exist_ok=True)
        entries = []
        for parsed, source, name in (
            (limits, LIMITS_SOURCE, "limits"),
            (client, CLIENT_SOURCE, "client"),
        ):
            derived, _ = analyze_derived_edges(
                parsed, filename=f"{name}.s0ma", constant_targets=known
            )
            ir = build_ir(parsed, derived_edges=derived, source_text=source).to_dict()
            (build_dir / f"{name}.s0ma.json").write_text(
                json.dumps(ir, sort_keys=True), encoding="utf-8"
            )
            from s0ma_dsl.codegen.build_manifest import ModuleManifestEntry

            entries.append(ModuleManifestEntry(
                name=name,
                source=f"src/{name}.s0ma",
                output=f"{name}.py",
                ir=f"{name}.s0ma.json",
                source_map=f"{name}.s0ma.map",
                source_hash="sha256:0",
                output_hash="sha256:0",
            ))
        return build_self_context_document(build_dir, entries)

    @staticmethod
    def _component(document: dict[str, object], component_id: str) -> dict[str, object]:
        components = document["components"]
        assert isinstance(components, list)
        matched = [item for item in components if item["id"] == component_id]
        assert len(matched) == 1
        return matched[0]

    def test_value_and_edges_reach_the_companion(self, tmp_path: Path) -> None:
        document = self._document(tmp_path)
        floor = self._component(document, "limits::MIN_INTERVAL_SECONDS")
        assert floor["value"] == 60
        assert "edges" not in floor
        optional = self._component(document, "limits::OPTIONAL")
        assert "value" in optional and optional["value"] is None
        assert "value" not in self._component(document, "limits::COMPUTED")

        service = self._component(document, "limits::SchedulerService")
        assert service["dependencies"] == []
        assert service["edges"] == [
            {
                "target": "limits::MIN_INTERVAL_SECONDS",
                "relation": "READS",
                "authored": False,
                "origin": "constant_reference",
            },
            {
                "target": "limits::SUFFIXES",
                "relation": "READS",
                "authored": False,
                "origin": "constant_reference",
            },
        ]
        authored = self._component(document, "limits::AuthoredReader")
        assert authored["dependencies"] == ["limits::MIN_INTERVAL_SECONDS"]
        assert authored["edges"] == [
            {
                "target": "limits::MIN_INTERVAL_SECONDS",
                "relation": "READS",
                "authored": True,
                "origin": "inline_depends_on",
                "carries": "the floor",
            },
        ]
        planner = self._component(document, "client::Planner")
        assert planner["edges"] == [
            {
                "target": "limits::MIN_INTERVAL_SECONDS",
                "relation": "READS",
                "authored": False,
                "origin": "constant_reference",
            },
        ]
        assert document == self._document(tmp_path)
