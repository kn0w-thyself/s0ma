"""Tests for qualified in-project ``depends_on:`` targets (DSL-M2, 0.8.0).

ADR-011 §(d) / design rule L-4: a ``depends_on:`` entry target accepts
the qualified in-project form ``module.declaration`` — exactly one dot
(module names are flat per ADR-006; deeper dotting is a parse error).
The dot is the established s0ma-component-space qualifier (``uses:``,
cross-module ``tests:`` targets, standalone axon targets); the colon
stays the Python-import override marker on the ``requires:`` side.

Behavioural contract pinned here:

- Grammar: ``module.declaration`` parses; ``a.b.c`` is a PARSE_ERROR;
  bare targets parse exactly as before.
- Resolution (resolver, project module set): target module must exist
  (``DOES_NOT_EXIST`` naming the qualified form; the single-module arm
  says qualified targets need a project build), the declaration must
  exist in the target module (``DOES_NOT_EXIST``), and cross-module
  targets must be exported (``NOT_EXPORTED``). Self-module-qualified
  targets resolve as the local declaration (idempotent, permitted, no
  export demand).
- Qualified edges join Phase-1 module-graph construction (fatal
  ``CIRCULAR_DEPENDENCY``) and the cross-layer reachability matrix
  (``CROSS_LAYER_DEPENDENCY``).
- Evidence rules are target-location-agnostic: Phase 4c checks the LEAF
  name for dotted targets.
- Emitted ``dependencies=[...]`` carries canonical
  ``module::declaration`` for qualified targets; bare local targets
  stay byte-identical (L-7). The IR's authored-edge records
  canonicalize the same way.
"""

from __future__ import annotations

import re

import pytest

from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.resolver.dependency import DependencyResolver

# ---------------------------------------------------------------------------
# Source builders — a two-module project (tools ← prompts)
# ---------------------------------------------------------------------------

_TOOLS_SRC = '''\
module tools
    layer: PRESENTATION
    version: 0.1.0
    intent: "Tool surface module for the qualified depends_on fixture."
    exports: [check_tool]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
    ---

nerve check_tool :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Checks things."
    expects: "nothing"
    guarantees: "a dict"
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
    def check_tool():
        return {"ok": True}
'''

_PROMPTS_SRC = '''\
module prompts
    layer: PRESENTATION
    version: 0.1.0
    intent: "Prompt surface module for the qualified depends_on fixture."
    uses: [tools.check_tool]
    exports: [author_prompt]
    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
    ---

nerve author_prompt :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Renders a prompt naming the tool the agent should call."
    expects: "nothing"
    guarantees: "a string"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    depends_on:
        tools.check_tool: {relation: CALLS, carries: "referential journey edge", coupling: LOOSE}
        LOCAL_TEMPLATE: {relation: READS, carries: "prompt copy", coupling: TIGHT}
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
    def author_prompt():
        return LOCAL_TEMPLATE + " then call " + str(check_tool())

cell LOCAL_TEMPLATE :: PRESENTATION
    kind: CONSTANT
    visibility: INTERNAL
    intent: "Prompt template."
    schema: "str"
    invariants: none
    covered_by: none
    ---
    LOCAL_TEMPLATE = "the copy"
'''


def _parse(src: str, name: str):
    return parse_s0ma(src, filename=f"{name}.s0ma")


def _resolve(modules: dict, mode: StrictnessMode = StrictnessMode.DEV):
    resolver = DependencyResolver(mode=mode)
    return resolver.resolve(modules, check_imports=False)


def _two_module_project():
    return {
        "tools": _parse(_TOOLS_SRC, "tools"),
        "prompts": _parse(_PROMPTS_SRC, "prompts"),
    }


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


class TestQualifiedTargetGrammar:
    def test_one_dot_parses_and_bare_unchanged(self) -> None:
        prompts = _parse(_PROMPTS_SRC, "prompts")
        targets = [a.target for a in prompts.nerves[0].depends_on]
        assert targets == ["tools.check_tool", "LOCAL_TEMPLATE"]

    def test_two_dots_is_a_parse_error(self) -> None:
        src = _PROMPTS_SRC.replace(
            "tools.check_tool: {", "tools.sub.check_tool: {",
        )
        with pytest.raises(S0maParseError) as excinfo:
            _parse(src, "prompts")
        assert excinfo.value.code == "PARSE_ERROR"
        assert "module.declaration" in (excinfo.value.remediation or "")


# ---------------------------------------------------------------------------
# Resolution — the ADR §(d) rule set
# ---------------------------------------------------------------------------


class TestQualifiedResolution:
    def test_two_module_project_resolves_clean_in_strict(self) -> None:
        errors = _resolve(_two_module_project(), StrictnessMode.STRICT)
        assert [e for e in errors if e.severity == "error"] == []

    def test_missing_target_module_names_qualified_form(self) -> None:
        modules = _two_module_project()
        del modules["tools"]
        # Drop the uses entry so the depends_on arm is isolated.
        prompts_src = _PROMPTS_SRC.replace(
            "    uses: [tools.check_tool]\n", "    uses: none\n",
        ).replace(" + str(check_tool())", "")
        modules["prompts"] = _parse(prompts_src, "prompts")
        modules2 = {"prompts": modules["prompts"], "other": _parse(
            _TOOLS_SRC.replace("module tools", "module other"), "other",
        )}
        errors = _resolve(modules2)
        missing = [e for e in errors if e.code == "DOES_NOT_EXIST"]
        assert len(missing) == 1
        assert "'tools.check_tool'" in missing[0].message
        assert "other" in missing[0].remediation  # lists project modules

    def test_single_module_arm_says_project_build_required(self) -> None:
        prompts_src = _PROMPTS_SRC.replace(
            "    uses: [tools.check_tool]\n", "    uses: none\n",
        ).replace(" + str(check_tool())", "")
        errors = _resolve({"prompts": _parse(prompts_src, "prompts")})
        missing = [e for e in errors if e.code == "DOES_NOT_EXIST"]
        assert len(missing) == 1
        assert "[tool.s0ma] project" in missing[0].remediation

    def test_missing_declaration_in_target_module(self) -> None:
        prompts_src = _PROMPTS_SRC.replace(
            "tools.check_tool: {", "tools.nope_tool: {",
        )
        modules = {
            "tools": _parse(_TOOLS_SRC, "tools"),
            "prompts": _parse(prompts_src, "prompts"),
        }
        errors = _resolve(modules)
        missing = [e for e in errors if e.code == "DOES_NOT_EXIST"]
        assert len(missing) == 1
        assert "'tools.nope_tool'" in missing[0].message
        assert "no declaration named 'nope_tool'" in missing[0].message

    def test_unexported_target_is_not_exported(self) -> None:
        tools_src = _TOOLS_SRC.replace(
            "exports: [check_tool]", "exports: []",
        ).replace("visibility: PUBLIC", "visibility: INTERNAL")
        modules = {
            "tools": _parse(tools_src, "tools"),
            "prompts": _parse(_PROMPTS_SRC, "prompts"),
        }
        errors = _resolve(modules)
        not_exported = [
            e for e in errors
            if e.code == "NOT_EXPORTED"
            and e.context.get("source") == "author_prompt"
        ]
        assert len(not_exported) == 1
        assert "'tools.check_tool'" in not_exported[0].message

    def test_self_module_qualified_target_is_permitted(self) -> None:
        src = _PROMPTS_SRC.replace(
            "LOCAL_TEMPLATE: {relation: READS",
            "prompts.LOCAL_TEMPLATE: {relation: READS",
        )
        modules = {
            "tools": _parse(_TOOLS_SRC, "tools"),
            "prompts": _parse(src, "prompts"),
        }
        errors = _resolve(modules, StrictnessMode.STRICT)
        assert [e for e in errors if e.severity == "error"] == []

    def test_qualified_cycle_is_fatal(self) -> None:
        tools_cyclic = _TOOLS_SRC.replace(
            "    ---\n    def check_tool():",
            "    depends_on:\n"
            "        prompts.author_prompt: "
            "{relation: CALLS, carries: \"cycle edge\", coupling: LOOSE}\n"
            "    ---\n    def check_tool():",
        ).replace(
            'return {"ok": True}', 'return {"ok": bool(author_prompt())}',
        )
        modules = {
            "tools": _parse(tools_cyclic, "tools"),
            "prompts": _parse(_PROMPTS_SRC, "prompts"),
        }
        errors = _resolve(modules)
        cycles = [e for e in errors if e.code == "CIRCULAR_DEPENDENCY"]
        assert len(cycles) >= 1
        assert "prompts" in cycles[0].message and "tools" in cycles[0].message

    def test_cross_layer_matrix_applies_to_qualified_edges(self) -> None:
        tools_infra = _TOOLS_SRC.replace(
            ":: PRESENTATION", ":: INFRASTRUCTURE",
        ).replace("layer: PRESENTATION", "layer: INFRASTRUCTURE")
        modules = {
            "tools": _parse(tools_infra, "tools"),
            "prompts": _parse(_PROMPTS_SRC, "prompts"),
        }
        errors = _resolve(modules, StrictnessMode.STRICT)
        layer = [
            e for e in errors
            if e.code == "CROSS_LAYER_DEPENDENCY"
            and e.context.get("qualified_name") == "tools.check_tool"
        ]
        assert layer, "qualified depends_on edge must hit the layer matrix"
        assert all(e.severity == "error" for e in layer)

    def test_leaf_name_evidence_for_qualified_targets(self) -> None:
        # Remove the body's call to the leaf — the CALLS edge loses its
        # evidence and Phase 4c flags it (leaf-name evidence rule).
        prompts_src = _PROMPTS_SRC.replace(
            "        return LOCAL_TEMPLATE + \" then call \" + str(check_tool())\n",
            "        return LOCAL_TEMPLATE\n",
        ).replace("    uses: [tools.check_tool]\n", "    uses: none\n")
        modules = {
            "tools": _parse(_TOOLS_SRC, "tools"),
            "prompts": _parse(prompts_src, "prompts"),
        }
        errors = _resolve(modules)
        vestigial = [
            e for e in errors
            if e.code == "VESTIGIAL_IMPORT"
            and e.context.get("target") == "tools.check_tool"
        ]
        assert len(vestigial) == 1


# ---------------------------------------------------------------------------
# Emitted and IR forms
# ---------------------------------------------------------------------------


class TestQualifiedEmission:
    def test_dependencies_carry_canonical_form_bare_stays_bare(self) -> None:
        prompts = _parse(_PROMPTS_SRC, "prompts")
        emitted = PythonEmitter(module_name="prompts").emit(prompts)
        match = re.search(r"dependencies=\[.*?\]", emitted)
        assert match is not None
        assert match.group(0) == (
            'dependencies=["tools::check_tool", "LOCAL_TEMPLATE"]'
        )

    def test_ir_authored_edges_canonicalize_qualified_targets(self) -> None:
        prompts = _parse(_PROMPTS_SRC, "prompts")
        doc = build_ir(prompts, source_text=_PROMPTS_SRC).to_dict()
        targets = {
            e["target"] for e in doc["edges"]["authored"]
            if e["source"] == "prompts::author_prompt"
        }
        assert targets == {"tools::check_tool", "prompts::LOCAL_TEMPLATE"}
