"""Tests for POST-3a (0.15.0): per-method ``returns:`` / ``expects:`` /
``guarantees:`` triples on SERVICE-nerve ``provides:`` entries.

The flat form of ``provides:`` has shipped since 0.x — a bare list of
operation names that the body must define as ``def`` statements::

    provides: [assemble, validate]

POST-3a extends the grammar with a structured form. Each entry is a
mapping whose key is the operation name and whose value is the
per-method contract triple::

    provides:
      - assemble:
          returns: "str — the assembled prompt"
          expects: "topic: str (non-empty)"
          guarantees: "result is non-empty; topic is escaped"
      - validate:
          returns: "bool — True iff topic is well-formed"

The structured form is *additive* — every triple slot is optional, and
the legacy flat form continues to parse unchanged. The motivating
consumer is fr3d's MS 11/12/17 SERVICE surface where settings tools,
budget tools, and the OAuth nerves carry many operations each, and
introspecting Python docstrings + type-hints to recover the per-method
contract is expensive enough to be worth declaring inline.

Behavioural contract pinned here:

- The flat form parses unchanged (regression).
- The structured form parses with any combination of the three triple
  slots; absent slots are ``None`` on the corresponding
  :class:`ProvidesEntry`.
- ``NerveDecl.provides`` (the canonical ordered tuple of operation
  names) is identical between the flat and structured forms — every
  downstream consumer that reads ``provides`` keeps working unchanged.
- ``NerveDecl.provides_entries`` exposes the per-method triples for
  consumers that need them.
- The IR carries the per-method triples under
  ``components[].fields.provides_contracts`` *only* when at least one
  entry declared a triple. Legacy flat-form nerves carry no new IR
  surface.
- The Python emitter weaves ``"provides_contracts": [...]`` into the
  ``metadata={...}`` dict on the emitted ``@component`` call so
  introspecting agents read the per-method contract at runtime without
  reaching for the IR.
- The validator's existing ``MISSING_PROVIDED_FUNCTION`` check (``def``
  names ⇄ provides names) applies to both forms. When the structured
  form is used AND the body terminates with a ``return { ... }``
  literal, the validator additionally checks the returned-dict keys
  against the structured provides names — closing the typo class the
  flat form misses (``"asemble"`` vs ``"assemble"``).
- Mixing flat and structured items in the same ``provides:`` block is
  a ``MIXED_PROVIDES_FORMS`` error.
- Unknown sub-fields (anything other than ``returns`` / ``expects`` /
  ``guarantees``) raise ``PARSE_ERROR`` with a remediation naming the
  valid alternatives.
- Duplicate item names raise ``DUPLICATE_PROVIDES_NAME``.
"""

from __future__ import annotations

import json

import pytest

from s0ma_dsl.ast_nodes import ProvidesEntry
from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.semantic.validator import validate_module

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _service_module(provides_block: str, *, body: str | None = None) -> str:
    """Return a minimal ``.s0ma`` source for a SERVICE nerve.

    ``provides_block`` is the literal text following ``provides:`` (the
    caller decides whether to use inline, flat-block, or structured-block
    form). ``body`` overrides the default factory body so tests can
    exercise the validator's return-dict-key check.
    """
    if body is None:
        body = (
            "    def assembler():\n"
            "        def assemble():\n"
            "            return 'hi'\n"
            "        def validate():\n"
            "            return True\n"
            "        return {'assemble': assemble, 'validate': validate}\n"
        )
    return (
        "module provides_demo\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "A demo module pinning the POST-3a structured provides form."\n'
        "    exports: [assembler]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "nerve assembler :: APPLICATION\n"
        "    kind: SERVICE\n"
        "    visibility: PUBLIC\n"
        '    intent: "A SERVICE nerve assembling and validating prompts."\n'
        '    expects: "no preconditions on the factory itself."\n'
        '    guarantees: "always returns a dict of operations."\n'
        '    forbids: none\n'
        "    evaluates_at: FUNCTION_BOUNDARY\n"
        "    returns: none\n"
        "    raises: none\n"
        "    interface: none\n"
        "    latency_ms: none\n"
        "    depends_on: none\n"
        "    internal: none\n"
        "    expected_exceptions: none\n"
        "    consumes_via_dict: none\n"
        "    declares_attributes: none\n"
        "    covered_by: none\n"
        + provides_block
        + "    ---\n"
        + body
    )


# ---------------------------------------------------------------------------
# Flat form — regression guard
# ---------------------------------------------------------------------------


class TestFlatFormRegression:
    """The legacy flat form parses identically to before POST-3a."""

    def test_inline_flat_form_parses(self) -> None:
        """``provides: [assemble, validate]`` still parses."""
        module = parse_s0ma(
            _service_module("    provides: [assemble, validate]\n"),
            filename="flat_inline.s0ma",
        )
        nerve = module.nerves[0]
        assert nerve.provides == ("assemble", "validate")
        # ProvidesEntry tuple mirrors the names with empty triples.
        assert len(nerve.provides_entries) == 2
        assert all(not e.has_triple for e in nerve.provides_entries)
        assert nerve.provides_entries[0].name == "assemble"
        assert nerve.provides_entries[1].name == "validate"

    def test_block_flat_form_parses(self) -> None:
        """The PRE-7 block form (``- assemble``) still parses."""
        module = parse_s0ma(
            _service_module(
                "    provides:\n"
                "      - assemble\n"
                "      - validate\n"
            ),
            filename="flat_block.s0ma",
        )
        nerve = module.nerves[0]
        assert nerve.provides == ("assemble", "validate")
        assert all(not e.has_triple for e in nerve.provides_entries)

    def test_flat_form_omits_provides_contracts_from_ir(self) -> None:
        """No IR surface when every entry is bare."""
        src = _service_module("    provides: [assemble, validate]\n")
        module = parse_s0ma(src, filename="flat_no_contracts.s0ma")
        doc = build_ir(module, source_text=src)
        comps = doc.to_dict()["components"]
        assert "provides_contracts" not in comps[0]["fields"]

    def test_flat_form_omits_provides_contracts_from_emitted_metadata(self) -> None:
        """Emitted Python carries ``"provides"`` but no ``"provides_contracts"``."""
        src = _service_module("    provides: [assemble, validate]\n")
        module = parse_s0ma(src, filename="flat_no_emitter_contracts.s0ma")
        emitted = PythonEmitter().emit(module)
        # The ``provides`` list is present; the triples key is not.
        assert '"provides": ["assemble", "validate"]' in emitted
        assert "provides_contracts" not in emitted


# ---------------------------------------------------------------------------
# Structured form — full triple
# ---------------------------------------------------------------------------


class TestStructuredFormParsing:
    """Structured ``provides:`` populates the per-method triple."""

    def test_full_triple_parses(self) -> None:
        """All three sub-fields populate the entry's slots."""
        src = _service_module(
            "    provides:\n"
            "      - assemble:\n"
            '          returns: "str — the assembled prompt"\n'
            '          expects: "topic: str (non-empty)"\n'
            '          guarantees: "result is non-empty; topic is escaped"\n'
        )
        module = parse_s0ma(src, filename="struct_full.s0ma")
        nerve = module.nerves[0]
        assert nerve.provides == ("assemble",)
        (entry,) = nerve.provides_entries
        assert isinstance(entry, ProvidesEntry)
        assert entry.name == "assemble"
        assert entry.returns == "str — the assembled prompt"
        assert entry.expects == "topic: str (non-empty)"
        assert entry.guarantees == "result is non-empty; topic is escaped"
        assert entry.has_triple is True

    def test_subset_of_sub_fields_parses(self) -> None:
        """Only ``returns:`` is set — the other slots are ``None``."""
        src = _service_module(
            "    provides:\n"
            "      - validate:\n"
            '          returns: "bool — True iff topic is well-formed"\n',
            body=(
                "    def assembler():\n"
                "        def validate():\n"
                "            return True\n"
                "        return {'validate': validate}\n"
            ),
        )
        module = parse_s0ma(src, filename="struct_partial.s0ma")
        nerve = module.nerves[0]
        (entry,) = nerve.provides_entries
        assert entry.returns == "bool — True iff topic is well-formed"
        assert entry.expects is None
        assert entry.guarantees is None
        assert entry.has_triple is True

    def test_multiple_structured_entries_parse(self) -> None:
        """A SERVICE with two structured entries gets two populated triples."""
        src = _service_module(
            "    provides:\n"
            "      - assemble:\n"
            '          returns: "str"\n'
            '          expects: "topic"\n'
            "      - validate:\n"
            '          returns: "bool"\n'
            '          guarantees: "no side effects"\n'
        )
        module = parse_s0ma(src, filename="struct_multi.s0ma")
        nerve = module.nerves[0]
        assert nerve.provides == ("assemble", "validate")
        assert nerve.provides_entries[0].returns == "str"
        assert nerve.provides_entries[0].expects == "topic"
        assert nerve.provides_entries[0].guarantees is None
        assert nerve.provides_entries[1].returns == "bool"
        assert nerve.provides_entries[1].expects is None
        assert nerve.provides_entries[1].guarantees == "no side effects"


# ---------------------------------------------------------------------------
# IR — provides_contracts surfaces under components[].fields
# ---------------------------------------------------------------------------


class TestStructuredFormIRRoundTrip:
    """The per-method triple rides through the IR builder."""

    def test_provides_contracts_appear_in_ir_fields(self) -> None:
        src = _service_module(
            "    provides:\n"
            "      - assemble:\n"
            '          returns: "str"\n'
            '          expects: "topic: str"\n'
            '          guarantees: "non-empty"\n'
            "      - validate:\n"
            '          returns: "bool"\n'
        )
        module = parse_s0ma(src, filename="ir_struct.s0ma")
        doc = build_ir(module, source_text=src)
        comp = doc.to_dict()["components"][0]
        contracts = comp["fields"]["provides_contracts"]
        assert contracts == [
            {
                "name": "assemble",
                "returns": "str",
                "expects": "topic: str",
                "guarantees": "non-empty",
            },
            {"name": "validate", "returns": "bool"},
        ]
        # The flat ``provides`` list is also present — the structured
        # form is additive, not a replacement.
        assert comp["fields"]["provides"] == {
            "state": "value",
            "value": ["assemble", "validate"],
        }

    def test_ir_round_trips_through_json(self) -> None:
        """``json.dumps`` → ``json.loads`` round-trips the triple."""
        src = _service_module(
            "    provides:\n"
            "      - assemble:\n"
            '          returns: "str — assembled prompt"\n'
        )
        module = parse_s0ma(src, filename="ir_json_struct.s0ma")
        doc = build_ir(module, source_text=src)
        rehydrated = json.loads(json.dumps(doc.to_dict()))
        assert rehydrated["components"][0]["fields"]["provides_contracts"] == [
            {"name": "assemble", "returns": "str — assembled prompt"},
        ]


# ---------------------------------------------------------------------------
# Python emitter — provides_contracts appears in registered metadata
# ---------------------------------------------------------------------------


class TestStructuredFormEmitted:
    """The per-method triple appears in the emitted ``metadata`` dict."""

    def test_metadata_carries_provides_contracts(self) -> None:
        src = _service_module(
            "    provides:\n"
            "      - assemble:\n"
            '          returns: "str"\n'
            '          expects: "topic"\n'
            '          guarantees: "non-empty"\n'
            "      - validate:\n"
            '          returns: "bool"\n'
        )
        module = parse_s0ma(src, filename="emit_struct.s0ma")
        emitted = PythonEmitter().emit(module)
        # Both keys appear; the contracts list mirrors the structured form.
        assert '"provides": ["assemble", "validate"]' in emitted
        assert '"provides_contracts"' in emitted
        assert '"name": "assemble"' in emitted
        assert '"returns": "str"' in emitted
        assert '"expects": "topic"' in emitted
        assert '"guarantees": "non-empty"' in emitted

    def test_emitted_python_is_valid_syntax(self) -> None:
        """The emitted module parses with ``ast.parse`` — no syntax bugs."""
        import ast

        src = _service_module(
            "    provides:\n"
            "      - assemble:\n"
            '          returns: "str"\n'
            '          expects: "topic"\n'
            '          guarantees: "non-empty"\n'
        )
        module = parse_s0ma(src, filename="emit_valid.s0ma")
        emitted = PythonEmitter().emit(module)
        ast.parse(emitted)

    def test_emitted_metadata_is_executable(self) -> None:
        """The emitted ``metadata`` dict literal evaluates to the expected shape."""
        src = _service_module(
            "    provides:\n"
            "      - assemble:\n"
            '          returns: "str"\n'
            '          guarantees: "non-empty"\n'
        )
        module = parse_s0ma(src, filename="emit_exec.s0ma")
        emitted = PythonEmitter().emit(module)
        # Pluck out the metadata literal — the @component() call's
        # ``metadata={"...": ...}`` keyword arg.
        marker = "metadata="
        idx = emitted.find(marker)
        assert idx != -1
        # Find the balanced ``{...}`` after the marker.
        start = emitted.index("{", idx)
        depth = 0
        for end in range(start, len(emitted)):
            if emitted[end] == "{":
                depth += 1
            elif emitted[end] == "}":
                depth -= 1
                if depth == 0:
                    break
        literal = emitted[start : end + 1]
        evaluated = eval(literal)  # noqa: S307 — emitted code under test
        assert evaluated["provides_contracts"] == [
            {
                "name": "assemble",
                "returns": "str",
                "guarantees": "non-empty",
            },
        ]


# ---------------------------------------------------------------------------
# Validator — return-dict-key check on structured form
# ---------------------------------------------------------------------------


class TestStructuredFormReturnDictKeyCheck:
    """Structured ``provides:`` triggers the return-dict-key check."""

    def test_return_dict_key_match_passes(self) -> None:
        """All structured names appear as keys in the return dict."""
        src = _service_module(
            "    provides:\n"
            "      - assemble:\n"
            '          returns: "str"\n'
            "      - validate:\n"
            '          returns: "bool"\n'
        )
        module = parse_s0ma(src, filename="return_match.s0ma")
        errors = validate_module(module, filename="return_match.s0ma")
        # No MISSING_PROVIDED_FUNCTION or MISSING_RETURN_KEY for the
        # structured form — body's ``return {...}`` keys match.
        relevant = [
            e for e in errors
            if e.code in {"MISSING_PROVIDED_FUNCTION", "MISSING_RETURN_KEY"}
        ]
        assert relevant == []

    def test_return_dict_key_typo_fires_missing_return_key(self) -> None:
        """Typo in the returned dict surfaces as ``MISSING_RETURN_KEY``.

        This is the headline POST-3a improvement: the flat ``provides:``
        form misses the ``"asemble"`` vs ``"assemble"`` typo because
        ``provides_entries`` only validates ``def`` names. With the
        structured form, the validator additionally checks the returned
        dict keys against the structured names.
        """
        body = (
            "    def assembler():\n"
            "        def assemble():\n"
            "            return 'hi'\n"
            "        def validate():\n"
            "            return True\n"
            # Typo in the returned-dict key — note 'asemble' (single 's').
            "        return {'asemble': assemble, 'validate': validate}\n"
        )
        src = _service_module(
            "    provides:\n"
            "      - assemble:\n"
            '          returns: "str"\n'
            "      - validate:\n"
            '          returns: "bool"\n',
            body=body,
        )
        module = parse_s0ma(src, filename="return_typo.s0ma")
        errors = validate_module(module, filename="return_typo.s0ma")
        codes = {e.code for e in errors}
        assert "MISSING_RETURN_KEY" in codes
        missing = [e for e in errors if e.code == "MISSING_RETURN_KEY"]
        # The error names the missing key (``assemble``) so the author
        # can find the typo without guessing.
        assert any("assemble" in e.message for e in missing)

    def test_class_bodied_service_skips_return_dict_check(self) -> None:
        """Class-bodied SERVICE (no terminal return-dict) skips the check.

        For a class-bodied SERVICE, the structural contract is satisfied
        by the ``def`` names directly — there is no ``return {...}`` to
        compare against. The validator silently skips the
        returned-dict-key pass in this case (the flat ``def``-name check
        still applies).
        """
        body = (
            "    class Assembler:\n"
            "        def assemble(self):\n"
            "            return 'hi'\n"
            "        def validate(self):\n"
            "            return True\n"
        )
        src = _service_module(
            "    provides:\n"
            "      - assemble:\n"
            '          returns: "str"\n'
            "      - validate:\n"
            '          returns: "bool"\n',
            body=body,
        )
        module = parse_s0ma(src, filename="class_body.s0ma")
        errors = validate_module(module, filename="class_body.s0ma")
        # No MISSING_RETURN_KEY because no ``return {...}`` literal
        # appears in a class body.
        codes = {e.code for e in errors}
        assert "MISSING_RETURN_KEY" not in codes


# ---------------------------------------------------------------------------
# Error paths — invalid sub-fields, mixed forms, duplicates
# ---------------------------------------------------------------------------


class TestStructuredFormErrors:
    """Authoring mistakes raise precise errors."""

    def test_unknown_sub_field_raises_parse_error(self) -> None:
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(
                _service_module(
                    "    provides:\n"
                    "      - assemble:\n"
                    '          surprise: "value"\n'
                ),
                filename="unknown_sub.s0ma",
            )
        err = excinfo.value
        assert err.code == "PARSE_ERROR"
        assert "surprise" in err.message
        # The error lists the valid sub-field names.
        assert "returns" in err.message
        assert "expects" in err.message
        assert "guarantees" in err.message

    def test_mixed_flat_and_structured_raises_mixed_provides_forms(self) -> None:
        """Mixing ``- foo:`` and ``- bar`` in one block is an error.

        The parser cannot blend the two flavours into a single
        ``provides_entries`` tuple — the structured consumer rejects
        bare items so the author picks one form per block.
        """
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(
                _service_module(
                    "    provides:\n"
                    "      - assemble:\n"
                    '          returns: "str"\n'
                    "      - validate\n"
                ),
                filename="mixed.s0ma",
            )
        err = excinfo.value
        assert err.code == "MIXED_PROVIDES_FORMS"
        # Remediation tells the author how to pick one form.
        assert err.remediation is not None
        assert "flat" in err.remediation.lower()
        assert "structured" in err.remediation.lower()

    def test_duplicate_structured_entry_name_raises(self) -> None:
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(
                _service_module(
                    "    provides:\n"
                    "      - assemble:\n"
                    '          returns: "str"\n'
                    "      - assemble:\n"
                    '          returns: "bool"\n'
                ),
                filename="dup.s0ma",
            )
        err = excinfo.value
        assert err.code == "DUPLICATE_PROVIDES_NAME"
        assert "assemble" in err.message
