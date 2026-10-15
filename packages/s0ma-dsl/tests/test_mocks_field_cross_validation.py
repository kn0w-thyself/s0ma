"""Tests for POST-3b + POST-3c (0.15.0): ``mocks:`` field on test
declarations + ``provides:`` ↔ ``return {...}`` strict-mode key check.

POST-3b adds a new optional field on ``test`` declarations::

    test some_factory_test :: APPLICATION
        intent: "Verify the assembler factory exposes the right ops."
        tests: [assembler]
        expects: none
        depends_on: none
        mocks: [assembler]
        ---
        def some_factory_test():
            mock_assembler = {
                "assemble": lambda parts: "".join(parts),
                "validate": lambda topic: True,
            }
            # ... test against the mock
            assert mock_assembler["assemble"](["a", "b"]) == "ab"

The validator cross-checks the dict literal assigned to a variable whose
name matches the lowercased mock target (optionally prefixed with
``mock_`` / ``fake_`` / ``stub_`` / ``dummy_`` / ``fixture_``) against
the target nerve's ``provides:`` set. Mismatches fire
``MOCK_KEY_MISMATCH`` (warning in dev/migration; error in strict/release).

POST-3c generalises M-4's structured-form ``return {...}`` key check to
cover the flat form too: a nerve with ``provides: [foo]`` whose body
returns ``{"fo": foo}`` fires ``PROVIDES_KEY_MISMATCH``. The check is
literal-keys-only (computed returns are silently skipped) and
mode-dependent (warning in migration/dev; error in strict/release).

Behavioural contract pinned here:

- ``mocks:`` parses in both inline and block forms (consistent with PRE-7).
- Cross-validation succeeds when test's mock dict keys match ``provides:``.
- ``MOCK_KEY_MISMATCH`` fires on missing key.
- ``MOCK_KEY_MISMATCH`` fires on extra key.
- ``MOCK_KEY_MISMATCH`` severity respects strictness mode.
- ``PROVIDES_KEY_MISMATCH`` fires on typo (``"asemble"`` vs ``"assemble"``).
- ``PROVIDES_KEY_MISMATCH`` does NOT fire when keys are computed.
- IR round-trips ``mocks:``.
- ``mocks:`` targeting an unknown nerve raises ``DOES_NOT_EXIST``.
"""

from __future__ import annotations

import json

from s0ma_dsl.cli.migrate_grammar import current_grammar_source
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.semantic.validator import validate_module

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _module_with_test(
    provides_block: str,
    test_block: str,
    *,
    nerve_body: str | None = None,
) -> str:
    """Return a minimal ``.s0ma`` source with one SERVICE nerve + one test.

    The nerve declares ``provides:`` per ``provides_block``; the test
    declares whatever mocks/body shape ``test_block`` carries.
    """
    if nerve_body is None:
        nerve_body = (
            "    def assembler():\n"
            "        def assemble():\n"
            "            return 'hi'\n"
            "        def validate():\n"
            "            return True\n"
            "        return {'assemble': assemble, 'validate': validate}\n"
        )
    source = (
        "module mocks_demo\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "A demo module pinning the POST-3b mocks field."\n'
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
        + nerve_body
        + "\n"
        + test_block
    )
    return current_grammar_source(source, filename="mocks_demo.s0ma")


def _basic_test_block(mocks_field: str, test_body: str) -> str:
    """Return a test declaration with the given ``mocks:`` field + body."""
    return (
        "test assembler_test :: APPLICATION\n"
        '    intent: "Verify the assembler exposes the right ops."\n'
        "    tests: [assembler]\n"
        "    depends_on: none\n"
        + mocks_field
        + "    ---\n"
        + test_body
    )


# ---------------------------------------------------------------------------
# mocks: field parsing
# ---------------------------------------------------------------------------


class TestMocksFieldParsing:
    """The ``mocks:`` field parses in both inline and block forms."""

    def test_inline_mocks_parses(self) -> None:
        src = _module_with_test(
            "    provides: [assemble, validate]\n",
            _basic_test_block(
                "    mocks: [assembler]\n",
                (
                    "    def assembler_test():\n"
                    "        mock_assembler = {\n"
                    "            'assemble': lambda parts: ''.join(parts),\n"
                    "            'validate': lambda topic: True,\n"
                    "        }\n"
                    "        assert mock_assembler['assemble'](['a']) == 'a'\n"
                ),
            ),
        )
        module = parse_s0ma(src, filename="mocks_inline.s0ma")
        (test,) = module.tests
        assert test.mocks == ("assembler",)

    def test_block_mocks_parses(self) -> None:
        """PRE-7 block-list form parses identically."""
        src = _module_with_test(
            "    provides: [assemble, validate]\n",
            _basic_test_block(
                "    mocks:\n      - assembler\n",
                (
                    "    def assembler_test():\n"
                    "        mock_assembler = {\n"
                    "            'assemble': lambda parts: ''.join(parts),\n"
                    "            'validate': lambda topic: True,\n"
                    "        }\n"
                    "        assert True\n"
                ),
            ),
        )
        module = parse_s0ma(src, filename="mocks_block.s0ma")
        (test,) = module.tests
        assert test.mocks == ("assembler",)

    def test_no_mocks_field_keeps_empty_tuple(self) -> None:
        """Legacy test declarations without ``mocks:`` parse unchanged."""
        src = _module_with_test(
            "    provides: [assemble, validate]\n",
            _basic_test_block(
                "",
                (
                    "    def assembler_test():\n"
                    "        assert True\n"
                ),
            ),
        )
        module = parse_s0ma(src, filename="mocks_absent.s0ma")
        (test,) = module.tests
        assert test.mocks == ()


# ---------------------------------------------------------------------------
# MOCK_KEY_MISMATCH — happy path + diagnostics
# ---------------------------------------------------------------------------


class TestMockKeyMismatch:
    """Cross-validation fires (or doesn't) per mock dict key set."""

    def _validate(
        self, src: str, mode: StrictnessMode = StrictnessMode.DEV,
    ) -> list:
        module = parse_s0ma(src, filename="mocks_check.s0ma")
        return validate_module(module, mode=mode, filename="mocks_check.s0ma")

    def test_matching_keys_pass_cleanly(self) -> None:
        """Mock dict keys equal to provides ⇒ no diagnostic."""
        src = _module_with_test(
            "    provides: [assemble, validate]\n",
            _basic_test_block(
                "    mocks: [assembler]\n",
                (
                    "    def assembler_test():\n"
                    "        mock_assembler = {\n"
                    "            'assemble': lambda parts: ''.join(parts),\n"
                    "            'validate': lambda topic: True,\n"
                    "        }\n"
                    "        assert True\n"
                ),
            ),
        )
        errors = self._validate(src)
        assert not [e for e in errors if e.code == "MOCK_KEY_MISMATCH"]

    def test_missing_key_fires_mock_key_mismatch(self) -> None:
        """Mock dict missing a provides key ⇒ MOCK_KEY_MISMATCH."""
        src = _module_with_test(
            "    provides: [assemble, validate]\n",
            _basic_test_block(
                "    mocks: [assembler]\n",
                (
                    "    def assembler_test():\n"
                    "        mock_assembler = {\n"
                    "            'assemble': lambda parts: ''.join(parts),\n"
                    "        }\n"
                    "        assert True\n"
                ),
            ),
        )
        errors = self._validate(src)
        mismatches = [e for e in errors if e.code == "MOCK_KEY_MISMATCH"]
        assert len(mismatches) == 1
        assert "validate" in mismatches[0].message
        assert mismatches[0].context["missing_keys"] == ["validate"]
        # In dev mode the finding is a warning.
        assert mismatches[0].severity == "warning"

    def test_extra_key_fires_mock_key_mismatch(self) -> None:
        """Mock dict carrying an undeclared key ⇒ MOCK_KEY_MISMATCH."""
        src = _module_with_test(
            "    provides: [assemble, validate]\n",
            _basic_test_block(
                "    mocks: [assembler]\n",
                (
                    "    def assembler_test():\n"
                    "        mock_assembler = {\n"
                    "            'assemble': lambda parts: ''.join(parts),\n"
                    "            'validate': lambda topic: True,\n"
                    "            'destroy': lambda: None,\n"
                    "        }\n"
                    "        assert True\n"
                ),
            ),
        )
        errors = self._validate(src)
        mismatches = [e for e in errors if e.code == "MOCK_KEY_MISMATCH"]
        assert len(mismatches) == 1
        assert "destroy" in mismatches[0].message
        assert mismatches[0].context["extra_keys"] == ["destroy"]

    def test_severity_respects_strictness_mode(self) -> None:
        """MOCK_KEY_MISMATCH ladders: warning in dev, error in strict."""
        src = _module_with_test(
            "    provides: [assemble, validate]\n",
            _basic_test_block(
                "    mocks: [assembler]\n",
                (
                    "    def assembler_test():\n"
                    "        mock_assembler = {\n"
                    "            'assemble': lambda parts: ''.join(parts),\n"
                    "        }\n"
                    "        assert True\n"
                ),
            ),
        )
        dev_errs = self._validate(src, mode=StrictnessMode.DEV)
        dev_mismatches = [
            e for e in dev_errs if e.code == "MOCK_KEY_MISMATCH"
        ]
        assert len(dev_mismatches) == 1
        assert dev_mismatches[0].severity == "warning"

        strict_errs = self._validate(src, mode=StrictnessMode.STRICT)
        strict_mismatches = [
            e for e in strict_errs if e.code == "MOCK_KEY_MISMATCH"
        ]
        assert len(strict_mismatches) == 1
        assert strict_mismatches[0].severity == "error"

    def test_no_mock_shape_dict_skips_silently(self) -> None:
        """A test with mocks: but no detectable mock dict ⇒ no diagnostic.

        Conservative-by-design: false positives are worse than false
        negatives. A body that builds its mock dynamically (or simply
        doesn't carry a recognisably-named mock literal) is silently
        skipped.
        """
        src = _module_with_test(
            "    provides: [assemble, validate]\n",
            _basic_test_block(
                "    mocks: [assembler]\n",
                (
                    "    def assembler_test():\n"
                    "        # Mock created via factory, not assignment.\n"
                    "        assert True\n"
                ),
            ),
        )
        errors = self._validate(src)
        assert not [e for e in errors if e.code == "MOCK_KEY_MISMATCH"]

    def test_unknown_mock_target_raises_does_not_exist(self) -> None:
        """``mocks: [unknown_nerve]`` raises DOES_NOT_EXIST."""
        src = _module_with_test(
            "    provides: [assemble, validate]\n",
            _basic_test_block(
                "    mocks: [no_such_nerve]\n",
                (
                    "    def assembler_test():\n"
                    "        assert True\n"
                ),
            ),
        )
        errors = self._validate(src)
        dne = [
            e for e in errors
            if e.code == "DOES_NOT_EXIST"
            and "no_such_nerve" in e.message
        ]
        assert len(dne) == 1


# ---------------------------------------------------------------------------
# PROVIDES_KEY_MISMATCH — POST-3c flat-form + typo case
# ---------------------------------------------------------------------------


class TestProvidesKeyMismatch:
    """``provides:`` ↔ return-dict literal-key cross-check (POST-3c)."""

    def _validate(
        self, src: str, mode: StrictnessMode = StrictnessMode.DEV,
    ) -> list:
        module = parse_s0ma(src, filename="provides_check.s0ma")
        return validate_module(
            module, mode=mode, filename="provides_check.s0ma",
        )

    def test_typo_fires_provides_key_mismatch(self) -> None:
        """``return {"asemble": assemble}`` vs ``provides: [assemble]`` ⇒ MISMATCH."""
        # Body has the typo "asemble" instead of "assemble". The
        # provides field carries the correct spelling.
        src = _module_with_test(
            "    provides: [assemble]\n",
            _basic_test_block(
                "",
                (
                    "    def assembler_test():\n"
                    "        assert True\n"
                ),
            ),
            nerve_body=(
                "    def assembler():\n"
                "        def assemble():\n"
                "            return 'hi'\n"
                "        return {'asemble': assemble}\n"
            ),
        )
        errors = self._validate(src)
        mismatches = [
            e for e in errors if e.code == "PROVIDES_KEY_MISMATCH"
        ]
        assert len(mismatches) == 1
        # 'asemble' is an extra key; 'assemble' is missing.
        assert "asemble" in mismatches[0].context["extra_keys"]
        assert "assemble" in mismatches[0].context["missing_keys"]
        # Dev-mode severity is warning.
        assert mismatches[0].severity == "warning"

    def test_matching_keys_pass_cleanly(self) -> None:
        """Provides keys equal to return dict keys ⇒ no diagnostic."""
        src = _module_with_test(
            "    provides: [assemble, validate]\n",
            _basic_test_block(
                "",
                (
                    "    def assembler_test():\n"
                    "        assert True\n"
                ),
            ),
        )
        errors = self._validate(src)
        assert not [
            e for e in errors if e.code == "PROVIDES_KEY_MISMATCH"
        ]

    def test_computed_return_is_silently_skipped(self) -> None:
        """A return built by ``dict(...)`` is silently skipped.

        The POST-3c check is literal-keys-only by design — computed
        returns produce false positives we cannot recover from without
        running the body, so the validator skips them.
        """
        src = _module_with_test(
            "    provides: [assemble, validate]\n",
            _basic_test_block(
                "",
                (
                    "    def assembler_test():\n"
                    "        assert True\n"
                ),
            ),
            nerve_body=(
                "    def assembler():\n"
                "        def assemble():\n"
                "            return 'hi'\n"
                "        def validate():\n"
                "            return True\n"
                "        ops = dict(assemble=assemble, validate=validate)\n"
                "        return ops\n"
            ),
        )
        errors = self._validate(src)
        assert not [
            e for e in errors if e.code == "PROVIDES_KEY_MISMATCH"
        ]

    def test_severity_respects_strictness_mode(self) -> None:
        """Warning in dev, error in strict/release per the severity matrix."""
        src = _module_with_test(
            "    provides: [assemble]\n",
            _basic_test_block(
                "",
                (
                    "    def assembler_test():\n"
                    "        assert True\n"
                ),
            ),
            nerve_body=(
                "    def assembler():\n"
                "        def assemble():\n"
                "            return 'hi'\n"
                "        return {'asemble': assemble}\n"
            ),
        )
        dev_errs = self._validate(src, mode=StrictnessMode.DEV)
        dev_mismatches = [
            e for e in dev_errs if e.code == "PROVIDES_KEY_MISMATCH"
        ]
        assert len(dev_mismatches) == 1
        assert dev_mismatches[0].severity == "warning"

        strict_errs = self._validate(src, mode=StrictnessMode.STRICT)
        strict_mismatches = [
            e for e in strict_errs if e.code == "PROVIDES_KEY_MISMATCH"
        ]
        assert len(strict_mismatches) == 1
        assert strict_mismatches[0].severity == "error"

    def test_structured_form_skips_missing_to_avoid_duplicate(self) -> None:
        """Structured-form ``MISSING_RETURN_KEY`` is not duplicated by POST-3c.

        M-4's ``MISSING_RETURN_KEY`` already covers structured-form
        missing-from-return diagnostics; POST-3c only adds the typo
        (extra key) direction so the same author error never produces
        two error codes.
        """
        src = _module_with_test(
            "    provides:\n"
            "      - assemble:\n"
            '          returns: "str"\n',
            _basic_test_block(
                "",
                (
                    "    def assembler_test():\n"
                    "        assert True\n"
                ),
            ),
            nerve_body=(
                "    def assembler():\n"
                "        def assemble():\n"
                "            return 'hi'\n"
                # Note: missing "assemble" key + extra "asemble" key.
                "        return {'asemble': assemble}\n"
            ),
        )
        errors = parse_s0ma(src, filename="dup_check.s0ma")
        diag = validate_module(
            errors, mode=StrictnessMode.STRICT, filename="dup_check.s0ma",
        )
        mismatches = [
            e for e in diag if e.code == "PROVIDES_KEY_MISMATCH"
        ]
        # The structured form already fires MISSING_RETURN_KEY for
        # the missing key; POST-3c only adds the extra-key direction.
        assert len(mismatches) == 1
        assert mismatches[0].context["missing_keys"] == []
        assert "asemble" in mismatches[0].context["extra_keys"]
        # And the M-4 ``MISSING_RETURN_KEY`` is still surfaced.
        missing = [e for e in diag if e.code == "MISSING_RETURN_KEY"]
        assert len(missing) == 1


# ---------------------------------------------------------------------------
# IR round-trip
# ---------------------------------------------------------------------------


class TestMocksIRRoundTrip:
    """``mocks:`` rides through the IR builder."""

    def test_ir_carries_mocks_field(self) -> None:
        """``components[].fields.mocks`` exists when ``mocks:`` is declared."""
        src = _module_with_test(
            "    provides: [assemble, validate]\n",
            _basic_test_block(
                "    mocks: [assembler]\n",
                (
                    "    def assembler_test():\n"
                    "        mock_assembler = {\n"
                    "            'assemble': lambda parts: ''.join(parts),\n"
                    "            'validate': lambda topic: True,\n"
                    "        }\n"
                    "        assert True\n"
                ),
            ),
        )
        module = parse_s0ma(src, filename="mocks_ir.s0ma")
        doc = build_ir(module, source_text=src)
        test_comp = next(
            c for c in doc.to_dict()["components"]
            if c["declaration_type"] == "test"
        )
        assert test_comp["fields"]["mocks"] == {
            "state": "value",
            "value": ["assembler"],
        }
        # Round-trip through JSON.
        rehydrated = json.loads(json.dumps(doc.to_dict()))
        test_comp2 = next(
            c for c in rehydrated["components"]
            if c["declaration_type"] == "test"
        )
        assert test_comp2["fields"]["mocks"] == {
            "state": "value",
            "value": ["assembler"],
        }

    def test_ir_omits_mocks_when_absent(self) -> None:
        """No ``mocks:`` ⇒ no ``mocks`` key in the IR fields dict."""
        src = _module_with_test(
            "    provides: [assemble, validate]\n",
            _basic_test_block(
                "",
                (
                    "    def assembler_test():\n"
                    "        assert True\n"
                ),
            ),
        )
        module = parse_s0ma(src, filename="mocks_absent_ir.s0ma")
        doc = build_ir(module, source_text=src)
        test_comp = next(
            c for c in doc.to_dict()["components"]
            if c["declaration_type"] == "test"
        )
        assert test_comp["fields"]["mocks"] == {"state": "none"}
