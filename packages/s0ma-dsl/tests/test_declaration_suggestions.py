"""Self-healing contract diagnostics — the M1 apply-then-green battery.

Batch-01c 0.13.0 M1. The cold-session anatomy measured 38/72 cold
``check`` calls failing on self-inflicted declaration mismatches
(``PROVIDES_KEY_MISMATCH`` / ``MISSING_PACKAGE``), each burning a 2–6-turn
guess-and-retry loop. The checker already computes the declared-vs-actual
sets it uses to name each mismatch; M1 hands the answer over as a
ready-to-paste ``suggested_declaration`` block.

The load-bearing property is **correct by construction**: for every
mismatch shape, pasting the suggested block over the named declaration and
re-checking clears that diagnostic class. These tests drive that property
end-to-end over the real parse → validate → resolve pipeline across the
battery the milestone names — extra key, missing key, renamed symbol
(typo), wrong module path, and multiple modules / entries at once — plus
the two ambiguity guards where the checker must decline to suggest rather
than fabricate a wrong block (a structured ``provides:`` triple; a
``requires:`` entry that actually names a s0ma module).
"""

from __future__ import annotations

from s0ma_dsl.ast_nodes.nodes import RequiresEntry
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.resolver.dependency import resolve_dependencies
from s0ma_dsl.semantic.validator import validate_module

# ---------------------------------------------------------------------------
# Pipeline helpers — run the real check over .s0ma source text
# ---------------------------------------------------------------------------


def _diagnostics(src: str, *, filename: str = "m.s0ma") -> list:
    """Parse *src* and run the validator + resolver (STRICT so the two
    contract mismatches surface as errors), returning every diagnostic."""
    module = parse_s0ma(src, filename=filename)
    errs = list(validate_module(module, filename=filename, mode=StrictnessMode.STRICT))
    errs += list(
        resolve_dependencies(
            {module.module.name: module},
            mode=StrictnessMode.STRICT,
            check_imports=True,
        )
    )
    return errs


def _codes(src: str) -> set[str]:
    return {e.code for e in _diagnostics(src)}


def _only(diags: list, code: str) -> list:
    return [e for e in diags if e.code == code]


def _apply(src: str, suggested: str) -> str:
    """Paste *suggested* over the single-line declaration it corrects.

    Replaces the first header/decl line whose stripped text starts with
    the suggested block's field keyword (``provides:`` / ``requires:``),
    preserving the original indentation — exactly the copy-paste an agent
    performs.
    """
    field = suggested.split(":", 1)[0]
    out: list[str] = []
    replaced = False
    for line in src.splitlines(keepends=True):
        stripped = line.lstrip()
        if not replaced and stripped.startswith(field + ":"):
            indent = line[: len(line) - len(stripped)]
            out.append(f"{indent}{suggested}\n")
            replaced = True
        else:
            out.append(line)
    assert replaced, f"no `{field}:` line found to replace in source"
    return "".join(out)


# ---------------------------------------------------------------------------
# Source fixtures
# ---------------------------------------------------------------------------


def _service_module(provides_block: str, body: str) -> str:
    return (
        "module provides_demo\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "demo"\n'
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
        '    intent: "svc"\n'
        '    expects: "none"\n'
        '    guarantees: "returns a dict of ops"\n'
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


def _flat_body(return_keys: tuple[str, ...]) -> str:
    """A factory body whose terminal return dict has exactly *return_keys*
    (each mapped to a locally-defined ``def`` so the flat def-name checks
    stay quiet and PROVIDES_KEY_MISMATCH is the only contract finding)."""
    defs = "".join(
        f"        def {k}():\n            return 1\n" for k in return_keys
    )
    ret = ", ".join(f"'{k}': {k}" for k in return_keys)
    return "    def assembler():\n" + defs + f"        return {{{ret}}}\n"


def _module_with_requires(name: str, requires_line: str) -> str:
    """A minimal module whose header carries *requires_line* verbatim."""
    requires_default = (
        "" if requires_line.startswith("requires:") else "    requires: none\n"
    )
    deferred_default = (
        ""
        if requires_line.startswith("deferred_requires:")
        else "    deferred_requires: none\n"
    )
    return (
        f"module {name}\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "demo"\n'
        f"    {requires_line}\n"
        "    exports: [noop]\n"
        + requires_default
        + "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        + deferred_default
        +
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "nerve noop :: APPLICATION\n"
        "    kind: FUNCTION\n"
        "    visibility: PUBLIC\n"
        '    intent: "noop"\n'
        '    expects: "none"\n'
        '    guarantees: "none"\n'
        '    forbids: none\n'
        "    evaluates_at: FUNCTION_BOUNDARY\n"
        "    provides: none\n"
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
        "    ---\n"
        "    def noop():\n"
        "        return 1\n"
    )


# ===========================================================================
# PROVIDES_KEY_MISMATCH (flat form) — apply-then-green across the battery
# ===========================================================================


class TestProvidesKeyMismatchSuggestions:
    def _run_battery(self, provides_names: str, return_keys: tuple[str, ...]) -> None:
        src = _service_module(
            f"    provides: [{provides_names}]\n", _flat_body(return_keys)
        )
        diags = _diagnostics(src)
        pk = _only(diags, "PROVIDES_KEY_MISMATCH")
        assert len(pk) == 1, "the mismatch must fire in the fixture"
        suggested = pk[0].suggested_declaration
        assert suggested is not None
        # The suggested block is the flat provides in canonical style.
        assert suggested.startswith("provides: [")
        # Correct by construction: apply → re-check → the class is gone.
        healed = _apply(src, suggested)
        assert "PROVIDES_KEY_MISMATCH" not in _codes(healed)

    def test_extra_key(self) -> None:
        # body returns an undeclared key.
        self._run_battery("assemble", ("assemble", "extra"))

    def test_missing_key(self) -> None:
        # provides declares a key the body never returns.
        self._run_battery("assemble, validate", ("assemble",))

    def test_renamed_symbol_typo(self) -> None:
        # the classic 'asemble' typo — declared vs returned diverge by one.
        self._run_battery("assemble, validate", ("asemble", "validate"))

    def test_suggested_block_renders_sorted_actual_keys(self) -> None:
        src = _service_module(
            "    provides: [assemble, validate]\n",
            _flat_body(("validate", "asemble")),
        )
        pk = _only(_diagnostics(src), "PROVIDES_KEY_MISMATCH")
        # Deterministic, sorted, from the body's actual return keys.
        assert pk[0].suggested_declaration == "provides: [asemble, validate]"

    def test_suggestion_rides_format_text_after_remediation(self) -> None:
        src = _service_module(
            "    provides: [assemble]\n", _flat_body(("assemble", "extra"))
        )
        pk = _only(_diagnostics(src), "PROVIDES_KEY_MISMATCH")
        text = pk[0].format_text()
        # Lead-with-cause ordering intact: message, then Remediation, then
        # the suggested block last.
        assert text.index("Remediation:") < text.index("Suggested fix")
        assert "provides: [assemble, extra]" in text

    def test_suggestion_rides_to_dict_only_when_present(self) -> None:
        src = _service_module(
            "    provides: [assemble]\n", _flat_body(("assemble", "extra"))
        )
        pk = _only(_diagnostics(src), "PROVIDES_KEY_MISMATCH")
        assert pk[0].to_dict()["suggested_declaration"] == "provides: [assemble, extra]"


class TestProvidesStructuredAmbiguityGuard:
    """A structured ``provides:`` triple cannot be synthesised for a new
    key, so the checker declines to suggest and says so."""

    def test_structured_extra_key_is_guarded(self) -> None:
        provides_block = (
            "    provides:\n"
            "      - assemble:\n"
            '          returns: "str"\n'
        )
        body = _flat_body(("assemble", "extra"))
        src = _service_module(provides_block, body)
        pk = _only(_diagnostics(src), "PROVIDES_KEY_MISMATCH")
        assert len(pk) == 1
        # No verbatim block; the remediation explains the structured-form
        # limitation explicitly.
        assert pk[0].suggested_declaration is None
        assert "suggested_declaration" not in pk[0].to_dict()
        assert "structured" in pk[0].remediation
        # format_text carries no "Suggested fix" line for a guarded finding.
        assert "Suggested fix" not in pk[0].format_text()


# ===========================================================================
# MISSING_PACKAGE — apply-then-green + consolidation + ambiguity guard
# ===========================================================================


class TestMissingPackageSuggestions:
    def test_wrong_module_path_single(self) -> None:
        # 'zzz_not_a_pkg' is unresolvable and is not a s0ma module → removable.
        src = _module_with_requires("a", "requires: [os, zzz_not_a_pkg]")
        diags = _diagnostics(src)
        mp = _only(diags, "MISSING_PACKAGE")
        assert len(mp) == 1
        suggested = mp[0].suggested_declaration
        assert suggested == "requires: [os]"
        healed = _apply(src, suggested)
        assert "MISSING_PACKAGE" not in _codes(healed)

    def test_multiple_bad_entries_consolidate_to_one_block(self) -> None:
        src = _module_with_requires(
            "a", "requires: [os, zzz_bad_one, zzz_bad_two]"
        )
        diags = _diagnostics(src)
        mp = _only(diags, "MISSING_PACKAGE")
        assert len(mp) == 2
        # One consolidated block per module: BOTH findings carry the same
        # remainder (all removables dropped at once), not one-per-error.
        blocks = {e.suggested_declaration for e in mp}
        assert blocks == {"requires: [os]"}
        # And it heals both in a single paste.
        healed = _apply(src, "requires: [os]")
        assert "MISSING_PACKAGE" not in _codes(healed)

    def test_from_import_survivors_round_trip(self) -> None:
        # Survivors span every requires form: colon-only from-import,
        # known-from-import, plain dotted import. All must render so the
        # pasted block re-parses to importable entries.
        src = _module_with_requires(
            "a",
            "requires: [uuid:uuid4, dataclasses.dataclass, os.path, zzz_bad]",
        )
        mp = _only(_diagnostics(src), "MISSING_PACKAGE")
        assert len(mp) == 1
        suggested = mp[0].suggested_declaration
        assert suggested is not None
        assert "zzz_bad" not in suggested
        healed = _apply(src, suggested)
        assert "MISSING_PACKAGE" not in _codes(healed)

    def test_multiple_modules_at_once(self) -> None:
        # Each module consolidates independently; the resolver runs over
        # the whole set at once (the "multiple modules" battery shape).
        mod_a = parse_s0ma(
            _module_with_requires("a", "requires: [os, zzz_bad_a]"),
            filename="a.s0ma",
        )
        mod_b = parse_s0ma(
            _module_with_requires("b", "requires: [json, zzz_bad_b]"),
            filename="b.s0ma",
        )
        diags = resolve_dependencies(
            {"a": mod_a, "b": mod_b},
            mode=StrictnessMode.STRICT,
            check_imports=True,
        )
        mp = _only(diags, "MISSING_PACKAGE")
        assert len(mp) == 2
        by_entry = {e.context["requires"]: e.suggested_declaration for e in mp}
        assert by_entry["zzz_bad_a"] == "requires: [os]"
        assert by_entry["zzz_bad_b"] == "requires: [json]"

    def test_s0ma_module_confusion_is_guarded(self) -> None:
        # 'store' is a real module in the set → the agent meant `uses:`,
        # not `requires:`. Removal would drop a real dependency, so the
        # checker declines a verbatim block and names the cross-decl fix.
        store = parse_s0ma(
            _module_with_requires("store", "requires: [os]"), filename="store.s0ma"
        )
        consumer = parse_s0ma(
            _module_with_requires("consumer", "requires: [store.open]"),
            filename="consumer.s0ma",
        )
        diags = resolve_dependencies(
            {"store": store, "consumer": consumer},
            mode=StrictnessMode.STRICT,
            check_imports=True,
        )
        mp = [e for e in _only(diags, "MISSING_PACKAGE") if e.context["import_path"] == "store"]
        assert len(mp) == 1
        assert mp[0].suggested_declaration is None
        assert "suggested_declaration" not in mp[0].to_dict()
        assert "uses:" in mp[0].remediation
        assert "Suggested fix" not in mp[0].format_text()

    def test_deferred_requires_names_its_own_field(self) -> None:
        src = _module_with_requires("a", "deferred_requires: [os, zzz_bad]")
        mp = _only(_diagnostics(src), "MISSING_PACKAGE")
        assert len(mp) == 1
        # The block names the field it corrects (not a blanket `requires:`).
        assert mp[0].suggested_declaration == "deferred_requires: [os]"
        healed = _apply(src, mp[0].suggested_declaration)
        assert "MISSING_PACKAGE" not in _codes(healed)


class TestRendererRoundTrip:
    """The requires-entry renderer round-trips every form back to the same
    RequiresEntry semantics (module_path / alias / is_from_import)."""

    def _round_trip(self, entry: RequiresEntry) -> None:
        from s0ma_dsl.parser.s0ma_parser import _build_requires
        from s0ma_dsl.suggestions import render_requires_entry

        rendered = render_requires_entry(entry)
        # ``_build_requires`` consumes the raw bracketed list form (the
        # value after ``requires:``), so wrap the single rendered entry.
        (reparsed,) = _build_requires(f"[{rendered}]", "m.s0ma", 1)
        assert reparsed.module_path == entry.module_path
        assert reparsed.alias == entry.alias
        assert reparsed.is_from_import == entry.is_from_import

    def test_plain_import(self) -> None:
        self._round_trip(RequiresEntry(module_path="os"))

    def test_dotted_plain_import(self) -> None:
        self._round_trip(RequiresEntry(module_path="os.path"))

    def test_capitalised_from_import(self) -> None:
        self._round_trip(RequiresEntry(module_path="uuid.UUID", is_from_import=True))

    def test_lowercase_colon_from_import(self) -> None:
        self._round_trip(RequiresEntry(module_path="uuid.uuid4", is_from_import=True))

    def test_known_from_import(self) -> None:
        self._round_trip(
            RequiresEntry(module_path="dataclasses.dataclass", is_from_import=True)
        )

    def test_aliased_plain_import(self) -> None:
        self._round_trip(RequiresEntry(module_path="numpy", alias="np"))
