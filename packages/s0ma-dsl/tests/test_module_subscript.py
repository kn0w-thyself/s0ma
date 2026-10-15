"""B1 (s0ma 0.11.0, batch-01a) — the ``MODULE_SUBSCRIPT`` guard.

A bare ``uses: [registry]`` entry emits ``import registry`` — the name
binds a *module object*, not a component. Nerve bodies are emitted
verbatim, so an author-written ``registry["get_op"]`` compiles cleanly
and crashes at runtime as ``TypeError: 'module' object is not
subscriptable``. This is the factory-dict confusion that detonated the
bench workspace ``batch-01a-20260713_P1_P_haiku45_r02`` (acceptance
1/24). The guard flags it at check time.

The guard must key on module-object resolution only: dotted
``uses: [mod.symbol]`` from-imports a component, and a body-local rebind
of the name turns it into a value — neither is flagged, so legitimate
dict subscripts are never rejected.
"""

from __future__ import annotations

from pathlib import Path

from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.config import ERROR_CODE_DESCRIPTIONS, StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.semantic.validator import validate_module

_FIXTURE_PROJECT = (
    Path(__file__).parent / "fixtures" / "module_subscript_regression"
)


def _validate(source: str, *, mode: StrictnessMode = StrictnessMode.STRICT):
    module, warnings = parse_s0ma_with_warnings(source, "<test>.s0ma", mode=mode)
    errors = validate_module(module, mode=mode, filename="<test>.s0ma")
    return list(warnings) + list(errors)


_CONSUMER_HEADER = """\
module consumer
    layer: DOMAIN
    version: 0.1.0
    intent: "Consumer of the registry module."
    exports: [consumer]
    requires: []
    uses: {uses}

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve consumer :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    intent: "Consume"
    expects: "None"
    guarantees: "Runs"
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
{body}
"""


def _consumer(uses: str, body: str) -> str:
    return _CONSUMER_HEADER.format(uses=uses, body=body)


class TestModuleSubscriptFires:
    def test_bare_uses_module_subscript_is_flagged(self) -> None:
        """``registry["x"]`` on a bare ``uses: [registry]`` module fires."""
        src = _consumer(
            "[registry]",
            "    def consumer():\n"
            "        return registry[\"get_op\"]\n",
        )
        diags = _validate(src)
        subs = [d for d in diags if d.code == "MODULE_SUBSCRIPT"]
        assert len(subs) == 1, [d.message for d in diags]
        err = subs[0]
        assert err.severity == "error"
        assert err.context["module_object"] == "registry"
        # Remediation teaches the dotted-uses + helper/exports_helpers fix.
        assert "uses: [registry.<symbol>]" in err.remediation
        assert "exports_helpers:" in err.remediation

    def test_module_subscript_is_error_in_every_mode(self) -> None:
        """MODULE_SUBSCRIPT is a guaranteed runtime crash — error in all modes."""
        src = _consumer(
            "[registry]",
            "    def consumer():\n"
            "        return registry[0]\n",
        )
        for mode in StrictnessMode:
            diags = _validate(src, mode=mode)
            subs = [d for d in diags if d.code == "MODULE_SUBSCRIPT"]
            assert len(subs) == 1 and subs[0].severity == "error", (
                f"mode {mode} did not error"
            )

    def test_aliased_bare_uses_module_subscript_is_flagged(self) -> None:
        """A bare ``uses: [registry as reg]`` subscripted as ``reg[...]`` fires."""
        src = _consumer(
            "[registry as reg]",
            "    def consumer():\n"
            "        return reg[\"get_op\"]\n",
        )
        subs = [d for d in _validate(src) if d.code == "MODULE_SUBSCRIPT"]
        assert len(subs) == 1


class TestModuleSubscriptNoFalsePositives:
    def test_dotted_uses_then_local_dict_subscript_is_clean(self) -> None:
        """Dotted ``uses: [registry.registry]`` + local-dict subscript: no fire."""
        src = _consumer(
            "[registry.registry]",
            "    def consumer():\n"
            "        funcs = registry()\n"
            "        return funcs[\"get_op\"]\n",
        )
        assert not [d for d in _validate(src) if d.code == "MODULE_SUBSCRIPT"]

    def test_local_rebind_of_module_name_is_clean(self) -> None:
        """Rebinding the bare-uses name to a local dict suppresses the guard."""
        src = _consumer(
            "[registry]",
            "    def consumer():\n"
            "        registry = {\"get_op\": 1}\n"
            "        return registry[\"get_op\"]\n",
        )
        assert not [d for d in _validate(src) if d.code == "MODULE_SUBSCRIPT"]

    def test_getattr_on_module_is_clean(self) -> None:
        """``getattr(registry, ...)`` (the bench op_rename shape) is not a subscript."""
        src = _consumer(
            "[registry]",
            "    def consumer():\n"
            "        fn = getattr(registry, \"registry\")\n"
            "        funcs = fn()\n"
            "        return funcs[\"get_op\"]\n",
        )
        assert not [d for d in _validate(src) if d.code == "MODULE_SUBSCRIPT"]


class TestModuleSubscriptRegressionFixture:
    """The r02-shaped regression fixture — a factory-dict registry plus a
    cli consumer that fatally subscripts the bare module object."""

    def test_project_check_flags_the_cli_consumer(self, capsys) -> None:
        rc = S0maCLI().run([
            "--project-root", str(_FIXTURE_PROJECT),
            "check", "--mode", "strict",
        ])
        out = capsys.readouterr().out
        assert rc != 0
        assert "MODULE_SUBSCRIPT" in out
        assert "cli.s0ma" in out
        # The correctly-authored op_rename and the registry factory stay clean.
        assert "op_rename.s0ma" not in out
        assert "registry.s0ma" not in out


def test_module_subscript_code_is_cataloged() -> None:
    assert "MODULE_SUBSCRIPT" in ERROR_CODE_DESCRIPTIONS
