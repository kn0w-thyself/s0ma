"""Tests for POST-12c + POST-12d (M-19, 0.16.0):

- **POST-12c — ``dataclass_invariants:`` block on MODEL cells.** Each
  entry is a Python boolean expression authored against the dataclass's
  fields (``"len(latency_samples) <= 100"``, ``"0.0 <= ratio <= 1.0"``).
  The validator syntax-checks each entry via
  ``ast.parse(expr, mode="eval")``; a parse failure raises
  ``INVALID_DATACLASS_INVARIANT`` in every strictness mode. The
  invariants are pure metadata for downstream introspection — they
  are NOT runtime-evaluated by s0ma. Declaring
  ``dataclass_invariants:`` on a non-MODEL cell is a ``PARSE_ERROR``.

- **POST-12d — ``consumes_via_dict:`` on nerves.** Each entry is a
  ``(contract, param)`` pair declaring a duck-typed coupling where the
  nerve body reads the contract via dict-key access rather than
  attribute access. The validator enforces that ``contract`` resolves
  to a known cell or ``uses:`` target and that ``param`` is a real
  parameter on the nerve body's outer function; mis-resolution raises
  ``CONSUMES_VIA_DICT_INVALID`` in every strictness mode.
"""

from __future__ import annotations

import textwrap

import pytest

from s0ma_dsl.ast_nodes.nodes import ConsumesViaDictEntry
from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.semantic.validator import IntraModuleValidator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model_with_invariants(invariants_block: str = "") -> str:
    """A minimal .s0ma source declaring a MODEL cell with optional invariants.

    ``invariants_block`` is the literal text inserted after the
    ``schema:`` field — must include leading 4-space indentation and a
    trailing newline when non-empty (e.g.
    ``'    dataclass_invariants: ["len(x) <= 10"]\\n'``).
    """
    head = textwrap.dedent(
        """\
module inv_module
    layer: DOMAIN
    version: 0.0.1
    intent: "Test module for dataclass_invariants."
    exports: [Stats]
    requires: [dataclasses, dataclasses.field]

    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell Stats :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "Holds running statistics."
    schema: "dataclass with samples + ratio."
    invariants: none
    covered_by: none
"""
    ).strip() + "\n"
    # Body must start with the class definition (decorator or
    # ``class`` keyword) — MODEL bodies cannot start with ``from``
    # imports per the cell-body classifier. ``dataclass`` / ``field``
    # are imported via the module-level ``requires:`` block above.
    body = (
        "    ---\n"
        "    @dataclass\n"
        "    class Stats:\n"
        "        samples: list = field(default_factory=list)\n"
        "        ratio: float = 0.5\n"
    )
    return head + invariants_block + body


def _nerve_with_consumes_via_dict(
    nerve_param: str,
    consumes_block: str,
    *,
    extra_cell: str = "",
    extra_uses: str = "",
) -> str:
    """A minimal .s0ma source declaring a SettingsDict cell + a consuming nerve.

    ``nerve_param`` is the parameter name on the nerve body's outer
    function (e.g. ``"config"``). ``consumes_block`` is the literal
    text inserted after ``evaluates_at:`` (must include 4-space
    indentation + trailing newline). ``extra_cell`` / ``extra_uses``
    let callers append additional declarations / uses entries.
    """
    uses_line = f"    uses: {extra_uses}\n" if extra_uses else "    uses: none\n"
    return textwrap.dedent(
        f"""
        module cvd_module
            layer: APPLICATION
            version: 0.0.1
            intent: "Test module for consumes_via_dict."
            exports: [foo]
            requires: none
            soft_requires: none
            runtime_only_requires: none
            deferred_requires: none
            exports_helpers: none
        {uses_line}
        cell SettingsDict :: APPLICATION
            kind: MODEL
            visibility: INTERNAL
            intent: "Settings dictionary contract."
            schema: "TypedDict-ish settings map."
            invariants: none
            covered_by: none
            ---
            class SettingsDict:
                pass
        {extra_cell}
        nerve foo :: APPLICATION
            kind: FUNCTION
            visibility: PUBLIC
            intent: "Reads settings via dict key."
            expects: "A settings dict."
            guarantees: "Returns the api key."
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
        """
    ).rstrip("\n") + "\n" + consumes_block + textwrap.dedent(
        f"""
            ---
            def foo({nerve_param}):
                return {nerve_param}["api_key"]
        """
    )


# ---------------------------------------------------------------------------
# POST-12c — dataclass_invariants: parsing
# ---------------------------------------------------------------------------


class TestDataclassInvariantsParsing:
    """``dataclass_invariants:`` parses on MODEL cells in both forms."""

    def test_block_form_parses(self) -> None:
        """Block-list form parses into the tuple."""
        src = _model_with_invariants(
            "    dataclass_invariants:\n"
            '      - "len(samples) <= 100"\n'
            '      - "0.0 <= ratio <= 1.0"\n'
        )
        module = parse_s0ma(src, filename="inv_module.s0ma")
        assert module.cells[0].dataclass_invariants == (
            "len(samples) <= 100",
            "0.0 <= ratio <= 1.0",
        )

    def test_inline_form_parses(self) -> None:
        """Inline form parses identically."""
        src = _model_with_invariants(
            '    dataclass_invariants: ["len(samples) <= 100", "ratio > 0"]\n'
        )
        module = parse_s0ma(src, filename="inv_module.s0ma")
        assert module.cells[0].dataclass_invariants == (
            "len(samples) <= 100",
            "ratio > 0",
        )

    def test_omitted_field_leaves_tuple_empty(self) -> None:
        """No ``dataclass_invariants:`` → empty tuple."""
        src = _model_with_invariants("")
        module = parse_s0ma(src, filename="inv_module.s0ma")
        assert module.cells[0].dataclass_invariants == ()

    def test_dataclass_invariants_on_non_model_is_parse_error(self) -> None:
        """``dataclass_invariants:`` on a CONSTANT cell raises ``PARSE_ERROR``."""
        source = textwrap.dedent(
            """\
module bad_module
    layer: DOMAIN
    version: 0.0.1
    intent: "Test parse-error on non-MODEL invariants."
    exports: [SOME_CONST]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell SOME_CONST :: DOMAIN
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Constant with rejected invariants."
    schema: "string"
    dataclass_invariants: ["len(x) <= 10"]
    invariants: none
    covered_by: none
    ---
    SOME_CONST = "hello"
"""
        ).strip() + "\n"
        with pytest.raises(S0maParseError) as exc:
            parse_s0ma(source, filename="bad_module.s0ma")
        assert exc.value.code == "PARSE_ERROR"
        # The remediation should mention MODEL.
        assert "MODEL" in exc.value.message


# ---------------------------------------------------------------------------
# POST-12c — dataclass_invariants: validator
# ---------------------------------------------------------------------------


class TestDataclassInvariantsValidator:
    """The validator syntax-checks every entry as a Python boolean expression."""

    def test_syntactically_valid_invariants_pass(self) -> None:
        """Well-formed invariants produce zero diagnostics."""
        src = _model_with_invariants(
            "    dataclass_invariants:\n"
            '      - "len(samples) <= 100"\n'
            '      - "0.0 <= ratio <= 1.0"\n'
        )
        module = parse_s0ma(src, filename="inv_module.s0ma")
        validator = IntraModuleValidator(
            mode=StrictnessMode.DEV, filename="inv_module.s0ma",
        )
        errors = validator.validate(module)
        codes = [e.code for e in errors]
        assert "INVALID_DATACLASS_INVARIANT" not in codes

    def test_invalid_invariant_fires_error(self) -> None:
        """A syntactically-broken entry fires ``INVALID_DATACLASS_INVARIANT``."""
        src = _model_with_invariants(
            "    dataclass_invariants:\n"
            '      - "len(samples"\n'  # missing close paren
        )
        module = parse_s0ma(src, filename="inv_module.s0ma")
        validator = IntraModuleValidator(
            mode=StrictnessMode.DEV, filename="inv_module.s0ma",
        )
        errors = validator.validate(module)
        bad = [e for e in errors if e.code == "INVALID_DATACLASS_INVARIANT"]
        assert len(bad) == 1
        assert bad[0].severity == "error"
        # The bad expression should be cited in the message.
        assert "len(samples" in bad[0].message

    def test_invalid_invariant_is_error_in_every_mode(self) -> None:
        """``INVALID_DATACLASS_INVARIANT`` is error in every strictness mode."""
        src = _model_with_invariants(
            "    dataclass_invariants:\n"
            '      - "len(samples"\n'
        )
        module = parse_s0ma(src, filename="inv_module.s0ma")
        for mode in (
            StrictnessMode.MIGRATION,
            StrictnessMode.DEV,
            StrictnessMode.STRICT,
            StrictnessMode.RELEASE,
        ):
            validator = IntraModuleValidator(
                mode=mode, filename="inv_module.s0ma",
            )
            errors = validator.validate(module)
            bad = [
                e for e in errors
                if e.code == "INVALID_DATACLASS_INVARIANT"
            ]
            assert len(bad) == 1, (
                f"Expected one INVALID_DATACLASS_INVARIANT in mode "
                f"{mode}, got {[e.code for e in errors]}"
            )
            assert bad[0].severity == "error"


# ---------------------------------------------------------------------------
# POST-12c — dataclass_invariants: IR + emitter
# ---------------------------------------------------------------------------


class TestDataclassInvariantsIRAndEmitter:
    """The declared invariants ride through the IR and emitted metadata."""

    def test_ir_round_trips_invariants(self) -> None:
        """The IR carries ``components[].fields.dataclass_invariants``."""
        src = _model_with_invariants(
            "    dataclass_invariants:\n"
            '      - "len(samples) <= 100"\n'
            '      - "0.0 <= ratio <= 1.0"\n'
        )
        module = parse_s0ma(src, filename="inv_module.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = doc.to_dict()
        cell_ir = next(
            c for c in ir_dict["components"]
            if c["declaration_type"] == "cell"
        )
        assert cell_ir["fields"]["dataclass_invariants"] == {
            "state": "value",
            "value": [
                "len(samples) <= 100",
                "0.0 <= ratio <= 1.0",
            ],
        }

    def test_ir_omits_invariants_key_when_empty(self) -> None:
        """Empty / absent → key omitted entirely from the IR."""
        src = _model_with_invariants("")
        module = parse_s0ma(src, filename="inv_module.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = doc.to_dict()
        cell_ir = next(
            c for c in ir_dict["components"]
            if c["declaration_type"] == "cell"
        )
        assert "dataclass_invariants" not in cell_ir["fields"]

    def test_emitted_metadata_contains_invariants(self) -> None:
        """The emitted ``metadata={...}`` dict carries the invariants list."""
        src = _model_with_invariants(
            "    dataclass_invariants:\n"
            '      - "len(samples) <= 100"\n'
        )
        module = parse_s0ma(src, filename="inv_module.s0ma")
        emitted = PythonEmitter().emit(module)
        assert '"dataclass_invariants"' in emitted
        assert '"len(samples) <= 100"' in emitted


# ---------------------------------------------------------------------------
# POST-12d — consumes_via_dict: parsing
# ---------------------------------------------------------------------------


class TestConsumesViaDictParsing:
    """``consumes_via_dict:`` parses into the entry tuple."""

    def test_single_entry_parses(self) -> None:
        """One entry parses into ``ConsumesViaDictEntry``."""
        src = _nerve_with_consumes_via_dict(
            "config",
            "    consumes_via_dict:\n"
            "      - contract: SettingsDict\n"
            "        param: config\n",
        )
        module = parse_s0ma(src, filename="cvd_module.s0ma")
        assert len(module.nerves[0].consumes_via_dict) == 1
        entry = module.nerves[0].consumes_via_dict[0]
        assert entry == ConsumesViaDictEntry(
            contract="SettingsDict", param="config",
        )

    def test_multiple_entries_parse(self) -> None:
        """Multiple entries preserve order."""
        # Add another cell so the second entry has a real target.
        src = textwrap.dedent(
            """\
module cvd_module
    layer: APPLICATION
    version: 0.0.1
    intent: "Test."
    exports: [foo]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell SettingsDict :: APPLICATION
    kind: MODEL
    visibility: INTERNAL
    intent: "Settings."
    schema: "Map."
    invariants: none
    covered_by: none
    ---
    class SettingsDict:
        pass

cell FeatureFlags :: APPLICATION
    kind: MODEL
    visibility: INTERNAL
    intent: "Feature flags."
    schema: "Map."
    invariants: none
    covered_by: none
    ---
    class FeatureFlags:
        pass

nerve foo :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Reads settings + flags."
    expects: "Both maps."
    guarantees: "An api key."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    consumes_via_dict:
      - contract: SettingsDict
        param: config
      - contract: FeatureFlags
        param: flags
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    declares_attributes: none
    covered_by: none
    ---
    def foo(config, flags):
        return config["api_key"] + flags["region"]
"""
        ).strip() + "\n"
        module = parse_s0ma(src, filename="cvd_module.s0ma")
        entries = module.nerves[0].consumes_via_dict
        assert len(entries) == 2
        assert entries[0].contract == "SettingsDict"
        assert entries[0].param == "config"
        assert entries[1].contract == "FeatureFlags"
        assert entries[1].param == "flags"

    def test_omitted_field_leaves_tuple_empty(self) -> None:
        """No ``consumes_via_dict:`` → empty tuple."""
        src = _nerve_with_consumes_via_dict("config", "")
        module = parse_s0ma(src, filename="cvd_module.s0ma")
        assert module.nerves[0].consumes_via_dict == ()


# ---------------------------------------------------------------------------
# POST-12d — consumes_via_dict: validator
# ---------------------------------------------------------------------------


class TestConsumesViaDictValidator:
    """The validator enforces contract + param resolution."""

    def test_well_formed_entry_passes(self) -> None:
        """A resolvable contract + a real param → zero diagnostics."""
        src = _nerve_with_consumes_via_dict(
            "config",
            "    consumes_via_dict:\n"
            "      - contract: SettingsDict\n"
            "        param: config\n",
        )
        module = parse_s0ma(src, filename="cvd_module.s0ma")
        validator = IntraModuleValidator(
            mode=StrictnessMode.DEV, filename="cvd_module.s0ma",
        )
        errors = validator.validate(module)
        bad = [
            e for e in errors
            if e.code == "CONSUMES_VIA_DICT_INVALID"
        ]
        assert bad == []

    def test_unknown_contract_fires_error(self) -> None:
        """An unknown contract → ``CONSUMES_VIA_DICT_INVALID``."""
        src = _nerve_with_consumes_via_dict(
            "config",
            "    consumes_via_dict:\n"
            "      - contract: UnknownContract\n"
            "        param: config\n",
        )
        module = parse_s0ma(src, filename="cvd_module.s0ma")
        validator = IntraModuleValidator(
            mode=StrictnessMode.DEV, filename="cvd_module.s0ma",
        )
        errors = validator.validate(module)
        bad = [
            e for e in errors
            if e.code == "CONSUMES_VIA_DICT_INVALID"
        ]
        assert len(bad) == 1
        assert bad[0].severity == "error"
        assert "UnknownContract" in bad[0].message

    def test_unknown_param_fires_error(self) -> None:
        """A param not on the nerve body's outer fn → ``CONSUMES_VIA_DICT_INVALID``."""
        # The nerve body takes ``config`` but the entry names ``settings``.
        src = _nerve_with_consumes_via_dict(
            "config",
            "    consumes_via_dict:\n"
            "      - contract: SettingsDict\n"
            "        param: settings\n",
        )
        module = parse_s0ma(src, filename="cvd_module.s0ma")
        validator = IntraModuleValidator(
            mode=StrictnessMode.DEV, filename="cvd_module.s0ma",
        )
        errors = validator.validate(module)
        bad = [
            e for e in errors
            if e.code == "CONSUMES_VIA_DICT_INVALID"
        ]
        assert len(bad) == 1
        assert bad[0].severity == "error"
        assert "settings" in bad[0].message

    def test_consumes_via_dict_is_error_in_every_mode(self) -> None:
        """The diagnostic is error severity in every strictness mode."""
        src = _nerve_with_consumes_via_dict(
            "config",
            "    consumes_via_dict:\n"
            "      - contract: UnknownContract\n"
            "        param: config\n",
        )
        module = parse_s0ma(src, filename="cvd_module.s0ma")
        for mode in (
            StrictnessMode.MIGRATION,
            StrictnessMode.DEV,
            StrictnessMode.STRICT,
            StrictnessMode.RELEASE,
        ):
            validator = IntraModuleValidator(
                mode=mode, filename="cvd_module.s0ma",
            )
            errors = validator.validate(module)
            bad = [
                e for e in errors
                if e.code == "CONSUMES_VIA_DICT_INVALID"
            ]
            assert len(bad) == 1, (
                f"Expected one CONSUMES_VIA_DICT_INVALID in mode "
                f"{mode}, got {[e.code for e in errors]}"
            )
            assert bad[0].severity == "error"


# ---------------------------------------------------------------------------
# POST-12d — consumes_via_dict: IR + emitter
# ---------------------------------------------------------------------------


class TestConsumesViaDictIRAndEmitter:
    """The entries ride through the IR and the emitted metadata."""

    def test_ir_round_trips_consumes_via_dict(self) -> None:
        """The IR carries ``components[].fields.consumes_via_dict``."""
        src = _nerve_with_consumes_via_dict(
            "config",
            "    consumes_via_dict:\n"
            "      - contract: SettingsDict\n"
            "        param: config\n",
        )
        module = parse_s0ma(src, filename="cvd_module.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = doc.to_dict()
        nerve_ir = next(
            c for c in ir_dict["components"]
            if c["declaration_type"] == "nerve"
        )
        assert nerve_ir["fields"]["consumes_via_dict"] == {
            "state": "value",
            "value": [{"contract": "SettingsDict", "param": "config"}],
        }

    def test_ir_omits_key_when_empty(self) -> None:
        """Empty / absent → key omitted from the IR."""
        src = _nerve_with_consumes_via_dict("config", "")
        module = parse_s0ma(src, filename="cvd_module.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = doc.to_dict()
        nerve_ir = next(
            c for c in ir_dict["components"]
            if c["declaration_type"] == "nerve"
        )
        assert nerve_ir["fields"]["consumes_via_dict"] == {
            "state": "none",
        }

    def test_emitted_metadata_contains_entries(self) -> None:
        """The emitted ``metadata={...}`` dict carries the dict-keyed entries."""
        src = _nerve_with_consumes_via_dict(
            "config",
            "    consumes_via_dict:\n"
            "      - contract: SettingsDict\n"
            "        param: config\n",
        )
        module = parse_s0ma(src, filename="cvd_module.s0ma")
        emitted = PythonEmitter().emit(module)
        assert '"consumes_via_dict"' in emitted
        assert '"contract": "SettingsDict"' in emitted
        assert '"param": "config"' in emitted


# ---------------------------------------------------------------------------
# s0ma inspect — text rendering
# ---------------------------------------------------------------------------


class TestS0maInspectRendering:
    """Both fields surface in ``s0ma inspect`` text output."""

    def test_dataclass_invariants_render_in_inspect(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The text renderer prints a "Dataclass invariants" header."""
        from s0ma_dsl.cli.main import S0maCLI

        src = _model_with_invariants(
            "    dataclass_invariants:\n"
            '      - "len(samples) <= 100"\n'
            '      - "0.0 <= ratio <= 1.0"\n'
        )
        module = parse_s0ma(src, filename="inv_module.s0ma")
        doc = build_ir(module, source_text=src)
        S0maCLI()._print_inspect_text(doc.to_dict())
        captured = capsys.readouterr().out
        assert "Dataclass invariants (2)" in captured
        assert "- len(samples) <= 100" in captured
        assert "- 0.0 <= ratio <= 1.0" in captured

    def test_consumes_via_dict_renders_in_inspect(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The text renderer prints a "Consumes via dict" header."""
        from s0ma_dsl.cli.main import S0maCLI

        src = _nerve_with_consumes_via_dict(
            "config",
            "    consumes_via_dict:\n"
            "      - contract: SettingsDict\n"
            "        param: config\n",
        )
        module = parse_s0ma(src, filename="cvd_module.s0ma")
        doc = build_ir(module, source_text=src)
        S0maCLI()._print_inspect_text(doc.to_dict())
        captured = capsys.readouterr().out
        assert "Consumes via dict (1)" in captured
        assert "SettingsDict via param 'config'" in captured
