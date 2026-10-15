"""Tests for POST-2 (0.15.0): the optional ``category:`` field on cell
declarations.

The s0ma DSL has historically modelled cells as opaque structural
artefacts — the kind (CONSTANT / MODEL / CONFIG / ENUM / EXCEPTION /
TYPE) distinguished the shape of the body, but no field captured the
*role* the cell plays in the surrounding system. fr3d's MS 19 ConfigDiff
classifier has been carrying a static rule table to derive
"capability vs behaviour" from cell name patterns; this batch adds a
first-class ``category:`` field so classification can come from the
registry instead.

Behavioural contract pinned here:

- ``category: capability`` and ``category: behaviour`` parse to
  ``CellDecl.category`` populated with the lower-case string value.
- Omitting the field leaves ``CellDecl.category == None``.
- Any other value raises :class:`S0maParseError` with
  ``code == "PARSE_ERROR"`` and a remediation that names the valid
  alternatives.
- The IR carries the category in the cell component's ``fields`` dict
  under the ``"category"`` key — absent → key omitted.
- The Python emitter weaves ``"category"`` into the ``metadata={...}``
  dict on the ``@component``-decorator / ``register_constant`` /
  ``register_type`` call so downstream consumers see the role at
  runtime.
- ``s0ma inspect`` text output surfaces the value in the bracket label
  of the cell row (``[PUBLIC MODEL cell, category=capability]``).

Tests use small, self-contained ``.s0ma`` snippets and read the IR
through ``build_ir(...).to_dict()`` so the assertions exercise the same
JSON shape ``s0ma inspect`` reads from disk.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest

from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.parser.s0ma_parser import VALID_CELL_CATEGORIES, parse_s0ma

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _cell_module(extra_cell_fields: str, *, cell_kind: str = "MODEL") -> str:
    """Return a minimal ``.s0ma`` source defining one cell.

    The cell name is ``DemoCell``; the module exports it. ``cell_kind``
    selects between MODEL / CONSTANT / TYPE so the same helper can
    cover all three emitter branches.
    """
    if cell_kind == "MODEL":
        body = "    class DemoCell:\n        pass\n"
    elif cell_kind == "CONSTANT":
        body = "    DemoCell: int = 42\n"
    elif cell_kind == "TYPE":
        body = "    DemoCell = list[int]\n"
    else:  # pragma: no cover — guard against future kind additions
        raise AssertionError(f"unhandled cell kind: {cell_kind}")
    return (
        "module category_demo\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "A demo module pinning the POST-2 category field."\n'
        "    exports: [DemoCell]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "cell DemoCell :: APPLICATION\n"
        f"    kind: {cell_kind}\n"
        "    visibility: PUBLIC\n"
        '    intent: "Demo cell exercising the category field."\n'
        '    schema: "demo schema describing the cell shape."\n'
        '    invariants: none\n'
        '    covered_by: none\n'
        + extra_cell_fields
        + "    ---\n"
        + body
    )


# ---------------------------------------------------------------------------
# Constant / valid-values contract
# ---------------------------------------------------------------------------


class TestValidCellCategoriesConstant:
    """The valid-values constant is the contract surface exported."""

    def test_valid_values_constant(self) -> None:
        assert frozenset({"capability", "behaviour"}) == VALID_CELL_CATEGORIES


# ---------------------------------------------------------------------------
# Parser — category field on CellDecl
# ---------------------------------------------------------------------------


class TestCategoryFieldParsing:
    """``category:`` parses to ``CellDecl.category`` with the right value."""

    def test_category_capability_parses_to_ast(self) -> None:
        module = parse_s0ma(
            _cell_module("    category: capability\n"),
            filename="category_capability.s0ma",
        )
        assert len(module.cells) == 1
        assert module.cells[0].category == "capability"

    def test_category_behaviour_parses_to_ast(self) -> None:
        module = parse_s0ma(
            _cell_module("    category: behaviour\n"),
            filename="category_behaviour.s0ma",
        )
        assert module.cells[0].category == "behaviour"

    def test_category_omitted_leaves_field_none(self) -> None:
        """A cell with no ``category:`` line parses with ``category=None``."""
        module = parse_s0ma(
            _cell_module(""), filename="category_absent.s0ma",
        )
        assert module.cells[0].category is None

    def test_category_invalid_value_raises_parse_error(self) -> None:
        """``category: invalid`` raises PARSE_ERROR naming the valid options."""
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(
                _cell_module("    category: invalid\n"),
                filename="category_invalid.s0ma",
            )
        err = excinfo.value
        assert err.code == "PARSE_ERROR"
        # Message names the offending value and lists the alternatives.
        assert "invalid" in err.message
        assert "behaviour" in err.message
        assert "capability" in err.message
        # Remediation tells the author how to fix it.
        assert err.remediation is not None
        assert "category" in err.remediation.lower()

    def test_category_blank_value_treated_as_absent(self) -> None:
        """An empty ``category:`` line is the same as omitting the field.

        This mirrors how ``version:`` and ``tags:`` behave — a blank
        line carries no semantic content.
        """
        module = parse_s0ma(
            _cell_module("    category: \n"),
            filename="category_blank.s0ma",
        )
        assert module.cells[0].category is None

    def test_category_case_sensitive(self) -> None:
        """``CATEGORY: Capability`` is rejected — values are lower-case.

        The DSL uses upper-case for enum-style fields (``kind:``,
        ``layer:``, ``visibility:``) and lower-case for label-style
        fields (``coupling:`` on edges, ``role:`` on manifest
        entries). ``category:`` belongs in the second group.
        """
        with pytest.raises(S0maParseError):
            parse_s0ma(
                _cell_module("    category: Capability\n"),
                filename="category_uppercase.s0ma",
            )

    def test_category_with_other_optional_fields(self) -> None:
        """The category field coexists with ``tags:`` / ``version:`` / ``invariants:``."""
        module = parse_s0ma(
            _cell_module(
                "    category: behaviour\n"
                "    version: 0.3.1\n"
                '    invariants: "no field may be None."\n'
                "    tags: [domain_model, audit]\n"
            ),
            filename="category_with_others.s0ma",
        )
        cell = module.cells[0]
        assert cell.category == "behaviour"
        assert cell.version == "0.3.1"
        assert cell.invariants == "no field may be None."
        assert cell.tags == ("domain_model", "audit")


# ---------------------------------------------------------------------------
# IR — category round-trips through the JSON shape
# ---------------------------------------------------------------------------


class TestCategoryIRRoundTrip:
    """The category rides through the IR builder and ``to_dict``."""

    def test_capability_appears_in_ir_fields(self) -> None:
        src = _cell_module("    category: capability\n")
        module = parse_s0ma(src, filename="ir_capability.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = doc.to_dict()
        comps = ir_dict["components"]
        assert len(comps) == 1
        assert comps[0]["fields"]["category"] == {
            "state": "value",
            "value": "capability",
        }

    def test_behaviour_appears_in_ir_fields(self) -> None:
        src = _cell_module("    category: behaviour\n")
        module = parse_s0ma(src, filename="ir_behaviour.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = doc.to_dict()
        assert ir_dict["components"][0]["fields"]["category"] == {
            "state": "value",
            "value": "behaviour",
        }

    def test_absent_category_omitted_from_ir_fields(self) -> None:
        """When the field is absent, the IR omits the key entirely."""
        src = _cell_module("")
        module = parse_s0ma(src, filename="ir_absent.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = doc.to_dict()
        assert "category" not in ir_dict["components"][0]["fields"]

    def test_ir_round_trips_through_json(self) -> None:
        """``json.dumps(ir.to_dict())`` → ``json.loads`` round-trips the value."""
        src = _cell_module("    category: capability\n")
        module = parse_s0ma(src, filename="ir_json_round_trip.s0ma")
        doc = build_ir(module, source_text=src)
        rehydrated = json.loads(json.dumps(doc.to_dict()))
        assert rehydrated["components"][0]["fields"]["category"] == {
            "state": "value",
            "value": "capability",
        }


# ---------------------------------------------------------------------------
# Python emitter — category appears in the registered metadata dict
# ---------------------------------------------------------------------------


class TestCategoryEmittedInMetadata:
    """Emitted Python includes ``"category": "..."`` in the metadata dict."""

    @pytest.mark.parametrize(
        "kind, category",
        [
            ("MODEL", "capability"),
            ("MODEL", "behaviour"),
            ("CONSTANT", "capability"),
            ("CONSTANT", "behaviour"),
            ("TYPE", "capability"),
        ],
    )
    def test_category_in_metadata(self, kind: str, category: str) -> None:
        src = _cell_module(f"    category: {category}\n", cell_kind=kind)
        module = parse_s0ma(src, filename=f"emit_{kind}_{category}.s0ma")
        emitter = PythonEmitter(module_name="category_demo")
        py_source = emitter.emit(module)
        # Every kind embeds the category as a single-line entry in the
        # metadata dict — quoting is consistent across the three
        # emitter branches.
        assert f'"category": "{category}"' in py_source

    def test_absent_category_omitted_from_metadata(self) -> None:
        """A cell without ``category:`` emits no ``category`` metadata key."""
        src = _cell_module("")
        module = parse_s0ma(src, filename="emit_absent.s0ma")
        emitter = PythonEmitter(module_name="category_demo")
        py_source = emitter.emit(module)
        assert '"category"' not in py_source


# ---------------------------------------------------------------------------
# s0ma inspect — category appears in the bracket label
# ---------------------------------------------------------------------------


class TestInspectShowsCategory:
    """``s0ma inspect`` text output surfaces the category in the label."""

    def test_capability_appears_in_inspect_label(self) -> None:
        src = _cell_module("    category: capability\n")
        module = parse_s0ma(src, filename="inspect_capability.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = json.loads(json.dumps(doc.to_dict()))

        cli = S0maCLI()
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._print_inspect_text(ir_dict)
        output = buf.getvalue()

        # The cell row's bracket label must mention the category.
        assert "category=capability" in output, (
            f"Expected 'category=capability' in inspect output; got:\n"
            f"{output}"
        )
        # The label is appended after the existing kind/visibility
        # triplet — the triplet must still be present.
        assert "PUBLIC MODEL cell" in output

    def test_behaviour_appears_in_inspect_label(self) -> None:
        src = _cell_module("    category: behaviour\n")
        module = parse_s0ma(src, filename="inspect_behaviour.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = json.loads(json.dumps(doc.to_dict()))

        cli = S0maCLI()
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._print_inspect_text(ir_dict)
        output = buf.getvalue()

        assert "category=behaviour" in output

    def test_absent_category_lacks_label_entry(self) -> None:
        """No ``category=...`` in the bracket label when the field is absent."""
        src = _cell_module("")
        module = parse_s0ma(src, filename="inspect_absent.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = json.loads(json.dumps(doc.to_dict()))

        cli = S0maCLI()
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._print_inspect_text(ir_dict)
        output = buf.getvalue()

        assert "category=" not in output
