"""Tests for POST-3d (0.15.0): nerve ``internal:`` field — inner-helper
IR visibility.

SERVICE nerves frequently follow a factory-closure pattern where the
public ``provides:`` operations share small private helpers declared as
inner ``def`` statements inside the body. Those helpers stay invisible
to the registry (they live behind the factory's closure) and to
``s0ma inspect`` (which has no way to surface them).

POST-3d introduces an optional ``internal:`` field on nerves that lists
inner helper functions for introspection purposes only::

    nerve PromptAssembler :: APPLICATION
        kind: SERVICE
        intent: "..."
        expects: "..."
        guarantees: "..."
        forbids: none
        evaluates_at: FUNCTION_BOUNDARY
        returns: none
        raises: none
        interface: none
        latency_ms: none
        depends_on: none
        expected_exceptions: none
        consumes_via_dict: none
        declares_attributes: none
        covered_by: none
        provides: [assemble, validate]
        internal:
          - _normalize_topic: "Strip whitespace and lowercase the topic"
          - _escape_html: "Escape HTML-special chars in the rendered prompt"
        ---
        def assembler():
            def _normalize_topic(topic):
                return topic.strip().lower()
            def _escape_html(s):
                return s.replace("<", "&lt;")
            def assemble(topic):
                return _escape_html(_normalize_topic(topic))
            def validate(topic):
                return bool(_normalize_topic(topic))
            return {"assemble": assemble, "validate": validate}

Behavioural contract pinned here:

- ``internal:`` parses in inline form ``[_a, _b]`` (no intents) and
  block form ``- _a\\n  - _b: "intent"`` (intent optional per entry).
- Mixed bare / intent-carrying items in the same block list are
  allowed (the field's whole point is descriptive flexibility).
- Empty / absent ``internal:`` parses to ``internal_helpers=()``.
- IR JSON round-trips the structure under
  ``components[].fields.internal_helpers``.
- ``s0ma inspect`` text output renders a separate "Internal helpers"
  sub-section per nerve that has them.
- ``internal:`` has NO codegen effect — the emitted Python carries no
  new ``register_*()`` call, no new metadata key, and the body emits
  unchanged. Helpers stay module-private (they live inside the
  factory's closure) and never enter the registry.
- Inline / block-list entries are validated as Python identifiers;
  a non-identifier name raises ``PARSE_ERROR``.
- Duplicate names within the same ``internal:`` block raise
  ``PARSE_ERROR``.
"""

from __future__ import annotations

import json

import pytest

from s0ma_dsl.ast_nodes import InternalHelperEntry
from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.parser.s0ma_parser import parse_s0ma

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


_DEFAULT_BODY = (
    "    def assembler():\n"
    "        def _normalize_topic(topic):\n"
    "            return topic.strip().lower()\n"
    "        def _escape_html(s):\n"
    "            return s\n"
    "        def assemble(topic):\n"
    "            return _escape_html(_normalize_topic(topic))\n"
    "        def validate(topic):\n"
    "            return bool(_normalize_topic(topic))\n"
    "        return {'assemble': assemble, 'validate': validate}\n"
)


def _service_module(
    internal_block: str,
    *,
    body: str | None = None,
) -> str:
    """Return a minimal ``.s0ma`` source for a SERVICE nerve.

    ``internal_block`` is the literal text following the
    ``evaluates_at: FUNCTION_BOUNDARY`` line; the caller decides
    whether to include an ``internal:`` field, what form to use, and
    where to put it.
    """
    if body is None:
        body = _DEFAULT_BODY
    return (
        "module internal_demo\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "A demo module pinning the POST-3d internal helpers field."\n'
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
        '    intent: "A SERVICE nerve with private inner helpers."\n'
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
        "    provides: [assemble, validate]\n"
        + internal_block
        + "    ---\n"
        + body
    )


# ---------------------------------------------------------------------------
# Absence / default
# ---------------------------------------------------------------------------


class TestAbsentInternalField:
    """A nerve without ``internal:`` parses to the empty tuple."""

    def test_absent_internal_yields_empty_tuple(self) -> None:
        """No ``internal:`` field → ``internal_helpers=()``."""
        module = parse_s0ma(
            _service_module(""),  # empty -> no internal block in the source
            filename="absent_internal.s0ma",
        )
        nerve = module.nerves[0]
        assert nerve.internal_helpers == ()

    def test_absent_internal_omits_ir_surface(self) -> None:
        """No ``internal:`` → no ``internal_helpers`` key in IR fields."""
        src = _service_module("")
        module = parse_s0ma(src, filename="absent_internal_ir.s0ma")
        doc = build_ir(module, source_text=src)
        comp = doc.to_dict()["components"][0]
        assert comp["fields"]["internal_helpers"] == {"state": "none"}


# ---------------------------------------------------------------------------
# Parsing — inline form
# ---------------------------------------------------------------------------


class TestInlineFormParsing:
    """Inline ``internal: [_a, _b]`` parses to bare entries (intent=None)."""

    def test_inline_form_parses(self) -> None:
        """``internal: [_normalize_topic, _escape_html]`` parses."""
        module = parse_s0ma(
            _service_module(
                "    internal: [_normalize_topic, _escape_html]\n",
            ),
            filename="inline_form.s0ma",
        )
        nerve = module.nerves[0]
        assert len(nerve.internal_helpers) == 2
        assert all(isinstance(e, InternalHelperEntry) for e in nerve.internal_helpers)
        assert nerve.internal_helpers[0].name == "_normalize_topic"
        assert nerve.internal_helpers[0].intent is None
        assert nerve.internal_helpers[1].name == "_escape_html"
        assert nerve.internal_helpers[1].intent is None

    def test_inline_form_single_entry_parses(self) -> None:
        """Single-entry inline form parses identically."""
        module = parse_s0ma(
            _service_module("    internal: [_helper]\n"),
            filename="inline_single.s0ma",
        )
        nerve = module.nerves[0]
        assert nerve.internal_helpers == (
            InternalHelperEntry(name="_helper", intent=None),
        )

    def test_inline_invalid_identifier_raises_parse_error(self) -> None:
        """A non-identifier inline name raises ``PARSE_ERROR``."""
        with pytest.raises(S0maParseError) as exc_info:
            parse_s0ma(
                _service_module("    internal: [123_bad]\n"),
                filename="inline_bad.s0ma",
            )
        # The Lark grammar may reject ``123_bad`` outright (parser-grammar
        # level) before the name validator fires, in which case the
        # raised error is still a ``S0maParseError`` with the structural
        # parse failure. Either path is acceptable — the milestone
        # contract is that the source does not silently produce a nerve
        # with the bad name.
        assert exc_info.value.code == "PARSE_ERROR"


# ---------------------------------------------------------------------------
# Parsing — block-list form (PRE-7 style)
# ---------------------------------------------------------------------------


class TestBlockFormParsing:
    """Block-list form ``internal:\\n  - _a\\n  - _b: "..."`` parses."""

    def test_block_form_bare_entries_parse(self) -> None:
        """``- _foo`` items (no intent) parse with ``intent=None``."""
        module = parse_s0ma(
            _service_module(
                "    internal:\n"
                "      - _normalize_topic\n"
                "      - _escape_html\n",
            ),
            filename="block_bare.s0ma",
        )
        nerve = module.nerves[0]
        assert nerve.internal_helpers == (
            InternalHelperEntry(name="_normalize_topic", intent=None),
            InternalHelperEntry(name="_escape_html", intent=None),
        )

    def test_block_form_with_intents_parses(self) -> None:
        """``- _foo: "..."`` items populate the ``intent`` slot."""
        module = parse_s0ma(
            _service_module(
                "    internal:\n"
                '      - _normalize_topic: "Strip whitespace and lowercase the topic"\n'
                '      - _escape_html: "Escape HTML-special chars"\n',
            ),
            filename="block_intent.s0ma",
        )
        nerve = module.nerves[0]
        assert len(nerve.internal_helpers) == 2
        assert nerve.internal_helpers[0].name == "_normalize_topic"
        assert (
            nerve.internal_helpers[0].intent
            == "Strip whitespace and lowercase the topic"
        )
        assert nerve.internal_helpers[1].name == "_escape_html"
        assert nerve.internal_helpers[1].intent == "Escape HTML-special chars"

    def test_block_form_mixed_bare_and_intent_parses(self) -> None:
        """Mixing bare and intent-carrying items in one block is allowed."""
        module = parse_s0ma(
            _service_module(
                "    internal:\n"
                "      - _normalize_topic\n"
                '      - _escape_html: "Escape HTML-special chars"\n',
            ),
            filename="block_mixed.s0ma",
        )
        nerve = module.nerves[0]
        assert nerve.internal_helpers == (
            InternalHelperEntry(name="_normalize_topic", intent=None),
            InternalHelperEntry(
                name="_escape_html",
                intent="Escape HTML-special chars",
            ),
        )

    def test_block_form_invalid_identifier_raises_parse_error(self) -> None:
        """A non-identifier block-list name raises ``PARSE_ERROR``."""
        with pytest.raises(S0maParseError) as exc_info:
            parse_s0ma(
                _service_module(
                    "    internal:\n"
                    "      - 123_bad\n",
                ),
                filename="block_bad.s0ma",
            )
        assert exc_info.value.code == "PARSE_ERROR"
        assert "internal" in str(exc_info.value).lower()

    def test_block_form_duplicate_name_raises_parse_error(self) -> None:
        """Two entries with the same name in one block raise ``PARSE_ERROR``."""
        with pytest.raises(S0maParseError) as exc_info:
            parse_s0ma(
                _service_module(
                    "    internal:\n"
                    "      - _helper\n"
                    "      - _helper\n",
                ),
                filename="block_dup.s0ma",
            )
        assert exc_info.value.code == "PARSE_ERROR"


# ---------------------------------------------------------------------------
# IR — internal_helpers round-trip through components[].fields
# ---------------------------------------------------------------------------


class TestIRRoundTrip:
    """The ``internal_helpers`` field rides through the IR builder."""

    def test_internal_helpers_appear_in_ir_fields(self) -> None:
        """IR carries one record per ``internal:`` entry."""
        src = _service_module(
            "    internal:\n"
            '      - _normalize_topic: "Strip whitespace"\n'
            "      - _escape_html\n",
        )
        module = parse_s0ma(src, filename="ir_round_trip.s0ma")
        doc = build_ir(module, source_text=src)
        comp = doc.to_dict()["components"][0]
        assert comp["fields"]["internal_helpers"] == {
            "state": "value",
            "value": [
                {"name": "_normalize_topic", "intent": "Strip whitespace"},
                {"name": "_escape_html"},
            ],
        }

    def test_ir_round_trips_through_json(self) -> None:
        """``json.dumps`` → ``json.loads`` preserves the structure."""
        src = _service_module(
            "    internal:\n"
            '      - _helper: "Some intent"\n'
            "      - _other\n",
        )
        module = parse_s0ma(src, filename="ir_json.s0ma")
        doc = build_ir(module, source_text=src)
        rehydrated = json.loads(json.dumps(doc.to_dict()))
        assert rehydrated["components"][0]["fields"]["internal_helpers"] == {
            "state": "value",
            "value": [
                {"name": "_helper", "intent": "Some intent"},
                {"name": "_other"},
            ],
        }


# ---------------------------------------------------------------------------
# s0ma inspect — "Internal helpers" sub-section
# ---------------------------------------------------------------------------


class TestS0maInspectRendering:
    """``_print_inspect_text`` surfaces the Internal helpers sub-section."""

    def test_inspect_text_contains_internal_helpers_section(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The text renderer prints a separate "Internal helpers" header."""
        from s0ma_dsl.cli.main import S0maCLI

        src = _service_module(
            "    internal:\n"
            '      - _normalize_topic: "Strip whitespace and lowercase"\n'
            "      - _escape_html\n",
        )
        module = parse_s0ma(src, filename="inspect_demo.s0ma")
        doc = build_ir(module, source_text=src)
        cli = S0maCLI()
        cli._print_inspect_text(doc.to_dict())
        captured = capsys.readouterr().out
        assert "Internal helpers (2)" in captured
        # Bare entry — name only.
        assert "- _escape_html" in captured
        # Entry with intent — name + intent on the same line.
        assert "_normalize_topic: Strip whitespace and lowercase" in captured

    def test_inspect_text_omits_section_when_no_internal_helpers(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No ``internal:`` → no "Internal helpers" sub-section."""
        from s0ma_dsl.cli.main import S0maCLI

        src = _service_module("")
        module = parse_s0ma(src, filename="inspect_no_internal.s0ma")
        doc = build_ir(module, source_text=src)
        cli = S0maCLI()
        cli._print_inspect_text(doc.to_dict())
        captured = capsys.readouterr().out
        assert "Internal helpers" not in captured


# ---------------------------------------------------------------------------
# Codegen — no registry side effect
# ---------------------------------------------------------------------------


class TestNoRegistrySideEffect:
    """``internal:`` does not promote helpers to components.

    The emitted Python must not gain any new ``register_*()`` call for
    a ``_helper`` named in ``internal:``, nor a new metadata key on
    the ``@component`` decorator. The helpers live behind the
    factory's closure and stay module-private.
    """

    def test_emitter_does_not_emit_register_for_internal_helpers(self) -> None:
        """No ``register_<Name>`` line for any ``internal:`` entry."""
        src = _service_module(
            "    internal:\n"
            '      - _normalize_topic: "Strip whitespace"\n'
            "      - _escape_html\n",
        )
        module = parse_s0ma(src, filename="no_register.s0ma")
        emitted = PythonEmitter().emit(module)
        # No register_* line names either inner helper. (We search
        # specifically for ``"_normalize_topic"`` and ``"_escape_html"``
        # as a register-call argument; the helper itself still appears
        # inside the body as a ``def`` statement, which is exactly the
        # point — they live inside the factory closure, not in the
        # registry.)
        for line in emitted.split("\n"):
            if "register_" in line:
                assert "_normalize_topic" not in line
                assert "_escape_html" not in line

    def test_emitter_does_not_add_internal_metadata_key(self) -> None:
        """No ``"internal_helpers"`` key in the emitted ``metadata=`` dict.

        The IR surfaces ``internal_helpers`` (so ``s0ma inspect`` can
        render it), but the Python emitter intentionally drops the
        field — runtime introspection of the registered ``@component``
        does not need the inner-helper list, and including it would
        make the helpers look like a public surface to consumers of
        the emitted code.
        """
        src = _service_module(
            "    internal:\n"
            '      - _normalize_topic: "Strip whitespace"\n'
            "      - _escape_html\n",
        )
        module = parse_s0ma(src, filename="no_metadata.s0ma")
        emitted = PythonEmitter().emit(module)
        assert "internal_helpers" not in emitted
