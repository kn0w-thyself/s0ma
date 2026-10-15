"""Tests for the M4 documentation-subsystem reference resolver and assert evaluator.

Covers:
- ProjectIndex build from parsed S0maModule dict (entities, kinds, names).
- DocReferenceResolver on valid inputs produces zero diagnostics.
- Dangling references → UNRESOLVED_REFERENCE with accurate spans and hints.
- Kind mismatches → ENTITY_KIND_MISMATCH with "did you mean" guidance.
- Field-access failures → FIELD_NOT_FOUND with known-field list in context.
- Example embeds that do not resolve → UNREGISTERED_EXAMPLE.
- Filter predicate / ordered_by / group_by field validation.
- AssertEvaluator: true asserts pass, false asserts emit ASSERT_FAILED,
  unresolved-lhs asserts emit ASSERT_UNEVALUABLE.
- DocValidator end-to-end on a small multi-declaration project.
"""

from __future__ import annotations

from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser import parse_s0ma
from s0ma_dsl.resolver import (
    DocReferenceResolver,
    build_project_index,
)
from s0ma_dsl.resolver.doc_resolver import materialize_filter
from s0ma_dsl.semantic import validate_docs

# ---------------------------------------------------------------------------
# Fixture helpers — inline .s0ma sources for fast, self-contained tests
# ---------------------------------------------------------------------------


def _parse(source: str, module_name: str = "fixture") -> dict:
    """Parse a source string and return ``{module_name: S0maModule}``."""
    s0ma_module = parse_s0ma(source, filename=f"{module_name}.s0ma")
    return {s0ma_module.module.name: s0ma_module}


# A minimal module that exposes entities of every v1 doc-addressable kind
# so the resolver can be exercised against real AST nodes.
RICH_MODULE = """\
module chat
    layer: DOMAIN
    version: 1.0.0
    intent: "Chat domain module for doc-resolver tests."
    exports: [greet, Message, HelloFlow]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell Message :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "A simple chat message cell for testing the resolver."
    schema: "role: str; content: str."
    invariants: none
    covered_by: none
    ---
    class Message:
        role: str
        content: str

nerve greet :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Produces a greeting for the supplied username."
    expects: "username is a non-empty string."
    guarantees: "Returns a string beginning with 'Hello'."
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
    def greet(username: str) -> str:
        return f"Hello, {username}!"

nerve _helper :: DOMAIN
    kind: FUNCTION
    visibility: INTERNAL
    intent: "A private helper nerve that is not part of the public surface."
    expects: "x is an integer."
    guarantees: "Returns twice x."
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
    def _helper(x: int) -> int:
        return x * 2

ganglion HelloFlow :: DOMAIN
    visibility: PUBLIC
    intent: "Evaluator that observes the chat greeting nerve for anomalies."
    observes: [greet]
    scope: SUBSYSTEM
    priors: "Greet should succeed for all valid usernames."
    on_anomaly: "Log and continue."
    forbids: none
    depends_on: none
    covered_by: none
    ---
    def HelloFlow(signal):
        return None

example greet_example
    intent: "Demonstrates calling the greet nerve with a typical username."
    demonstrates: [nerve::greet]
    runs_in: standalone
    ---
    from chat import greet
    print(greet("Ada"))
"""


def _modules_with_rich_chat() -> dict:
    return _parse(RICH_MODULE, module_name="chat")


# ---------------------------------------------------------------------------
# ProjectIndex
# ---------------------------------------------------------------------------


class TestProjectIndex:
    def test_build_indexes_all_kinds(self) -> None:
        modules = _modules_with_rich_chat()
        index = build_project_index(modules)

        # Module itself
        assert index.lookup("module", "chat") is not None
        # Nerves
        assert index.lookup("nerve", "greet") is not None
        assert index.lookup("nerve", "_helper") is not None
        # Cell
        assert index.lookup("cell", "Message") is not None
        # Ganglion
        assert index.lookup("ganglion", "HelloFlow") is not None
        # Example
        assert index.lookup("example", "greet_example") is not None

    def test_names_in_kind(self) -> None:
        index = build_project_index(_modules_with_rich_chat())
        assert index.names_in_kind("nerve") == {"greet", "_helper"}
        assert index.names_in_kind("example") == {"greet_example"}
        assert index.names_in_kind("cell") == {"Message"}

    def test_find_in_any_kind(self) -> None:
        index = build_project_index(_modules_with_rich_chat())
        found = index.find_in_any_kind("greet")
        assert [k for k, _ in found] == ["nerve"]

    def test_fields_normalise_enums(self) -> None:
        index = build_project_index(_modules_with_rich_chat())
        greet = index.lookup("nerve", "greet")
        assert greet is not None
        # Enums should be stored as their .value strings for comparison.
        assert greet.fields["visibility"] == "PUBLIC"
        assert greet.fields["kind"] == "FUNCTION"
        assert greet.fields["layer"] == "DOMAIN"


# ---------------------------------------------------------------------------
# DocReferenceResolver — positive cases
# ---------------------------------------------------------------------------


DOC_GUIDE_VALID = """\
module chat_guide
    layer: DOMAIN
    version: 1.0.0
    intent: "Module hosting a doc-guide that covers the chat greeting flow."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide getting_started
    intent: "Walk-through for the greet nerve and its example usage."
    format: markdown
    output: docs/getting_started.md
    covers: [nerve::greet]
    asserts: [nerve::greet.visibility == PUBLIC]
    examples: [example::greet_example]
    ---
    # Getting Started

    The {{nerve::greet}} nerve takes a username and returns a greeting.

    See the embedded example: {{example::greet_example}}.
"""


def _multi_project_chat_plus_guide() -> dict:
    """Return a 2-module project: chat + chat_guide (the guide references chat)."""
    chat = parse_s0ma(RICH_MODULE, filename="chat.s0ma")
    guide = parse_s0ma(DOC_GUIDE_VALID, filename="chat_guide.s0ma")
    return {
        chat.module.name: chat,
        guide.module.name: guide,
    }


class TestResolverPositive:
    def test_valid_doc_guide_has_no_errors(self) -> None:
        modules = _multi_project_chat_plus_guide()
        errors = validate_docs(modules)
        assert errors == [], "\n".join(e.format_text() for e in errors)

    def test_valid_example_has_no_errors(self) -> None:
        modules = _modules_with_rich_chat()
        index = build_project_index(modules)
        resolver = DocReferenceResolver(index=index)
        example = next(d for d in modules["chat"].examples)
        errors = resolver.resolve_example(example, filename="chat.s0ma")
        assert errors == []

    def test_valid_doc_ref_has_no_errors(self) -> None:
        source = """\
module chat_ref
    layer: DOMAIN
    version: 1.0.0
    intent: "Module hosting a doc-ref covering public nerves of chat."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-ref api_reference
    intent: "Generated reference for every public nerve."
    format: markdown
    output: docs/api_reference.md
    covers: [nerve where visibility == PUBLIC]
    sections: [intent, expects, guarantees]
"""
        modules = _parse(source, "chat_ref")
        modules.update(_parse(RICH_MODULE, "chat"))
        errors = validate_docs(modules)
        assert errors == [], "\n".join(e.format_text() for e in errors)


# ---------------------------------------------------------------------------
# DocReferenceResolver — negative cases
# ---------------------------------------------------------------------------


def _dangling_guide_source() -> str:
    return """\
module dangling_guide
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide that references a nerve which does not exist in the project."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide broken
    intent: "Guide that references a nerve which does not exist in the project."
    format: markdown
    output: docs/broken.md
    covers: [nerve::doesnotexist]
    asserts: [nerve::greet.visibility == PUBLIC]
    examples: [example::greet_example]
    ---
    Missing: {{nerve::doesnotexist}}.
"""


class TestResolverNegative:
    def test_dangling_reference_emits_unresolved(self) -> None:
        modules = {
            "chat": parse_s0ma(RICH_MODULE, filename="chat.s0ma"),
            "dangling_guide": parse_s0ma(
                _dangling_guide_source(), filename="dangling_guide.s0ma"
            ),
        }
        errors = validate_docs(modules)
        codes = [e.code for e in errors]
        # Both covers and the prose {{...}} reference the dangling nerve.
        assert codes.count("UNRESOLVED_REFERENCE") >= 2
        # Diagnostic carries source location info.
        dangling = next(e for e in errors if e.code == "UNRESOLVED_REFERENCE")
        assert dangling.line > 0
        assert "doesnotexist" in dangling.message

    def test_kind_mismatch_points_at_correct_kind(self) -> None:
        # Reference cell::greet — but 'greet' is actually a nerve.
        source = """\
module mismatch_guide
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide that refers to the greet nerve using the wrong kind."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide wrong_kind
    intent: "Guide that uses cell::greet instead of nerve::greet."
    format: markdown
    output: docs/wrong_kind.md
    covers: [cell::greet]
    asserts: [nerve::greet.visibility == PUBLIC]
    examples: [example::greet_example]
    ---
    Oops: {{cell::greet}}.
"""
        modules = {
            "chat": parse_s0ma(RICH_MODULE, filename="chat.s0ma"),
            "mismatch_guide": parse_s0ma(source, filename="mismatch_guide.s0ma"),
        }
        errors = validate_docs(modules)
        mismatches = [e for e in errors if e.code == "ENTITY_KIND_MISMATCH"]
        assert len(mismatches) >= 2  # covers + prose
        assert any("nerve::greet" in e.remediation for e in mismatches)

    def test_unregistered_example_embed(self) -> None:
        source = """\
module bad_example_guide
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide that embeds an example which was never declared."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide ghost_example
    intent: "Guide that embeds a non-existent example."
    format: markdown
    output: docs/ghost.md
    covers: [nerve::greet]
    asserts: [nerve::greet.visibility == PUBLIC]
    examples: [example::not_a_real_example]
    ---
    See: {{example::not_a_real_example}}.
"""
        modules = {
            "chat": parse_s0ma(RICH_MODULE, filename="chat.s0ma"),
            "bad_example_guide": parse_s0ma(source, filename="bad.s0ma"),
        }
        errors = validate_docs(modules)
        unregistered = [e for e in errors if e.code == "UNREGISTERED_EXAMPLE"]
        assert len(unregistered) >= 2
        assert any("not_a_real_example" in e.message for e in unregistered)

    def test_field_not_found_in_doc_ref_section(self) -> None:
        # 'bogus_field' is not a known field on 'nerve'.
        source = """\
module bad_ref
    layer: DOMAIN
    version: 1.0.0
    intent: "Doc-ref that asks for a section field no nerve exposes."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-ref bad
    intent: "Doc-ref with a non-existent section field reference."
    format: markdown
    output: docs/bad.md
    covers: [nerve where visibility == PUBLIC]
    sections: [bogus_field]
"""
        modules = {
            "chat": parse_s0ma(RICH_MODULE, filename="chat.s0ma"),
            "bad_ref": parse_s0ma(source, filename="bad_ref.s0ma"),
        }
        errors = validate_docs(modules)
        field_errs = [e for e in errors if e.code == "FIELD_NOT_FOUND"]
        assert field_errs
        assert any("bogus_field" in e.message for e in field_errs)

    def test_field_not_found_in_prose_reference(self) -> None:
        source = """\
module bad_prose_guide
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide whose prose references a non-existent nerve field."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide bad
    intent: "Guide that reaches for a field that nerves do not expose."
    format: markdown
    output: docs/bad.md
    covers: [nerve::greet]
    asserts: [nerve::greet.visibility == PUBLIC]
    examples: [example::greet_example]
    ---
    The intent field: {{nerve::greet.not_a_field}}.
"""
        modules = {
            "chat": parse_s0ma(RICH_MODULE, filename="chat.s0ma"),
            "bad_prose_guide": parse_s0ma(source, filename="bad_prose.s0ma"),
        }
        errors = validate_docs(modules)
        field_errs = [e for e in errors if e.code == "FIELD_NOT_FOUND"]
        assert field_errs
        assert any("not_a_field" in e.message for e in field_errs)

    def test_filter_predicate_field_validated(self) -> None:
        # where clause references a field 'color' that does not exist on nerve.
        source = """\
module filter_check
    layer: DOMAIN
    version: 1.0.0
    intent: "Doc-ref whose filter predicate references an unknown field."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-ref bad_where
    intent: "Generated reference whose where predicate uses an unknown field."
    format: markdown
    output: docs/bad_where.md
    covers: [nerve where color == red]
    sections: [intent]
"""
        modules = {
            "chat": parse_s0ma(RICH_MODULE, filename="chat.s0ma"),
            "filter_check": parse_s0ma(source, filename="filter_check.s0ma"),
        }
        errors = validate_docs(modules)
        codes = [e.code for e in errors]
        assert "FIELD_NOT_FOUND" in codes
        # The diagnostic context records the offending clause.
        ff = next(e for e in errors if e.code == "FIELD_NOT_FOUND")
        assert ff.context.get("clause") == "where"


# ---------------------------------------------------------------------------
# AssertEvaluator
# ---------------------------------------------------------------------------


class TestAssertEvaluator:
    def test_true_equality_passes(self) -> None:
        # nerve::greet.visibility == PUBLIC is true for the RICH_MODULE fixture.
        modules = _multi_project_chat_plus_guide()
        errors = validate_docs(modules)
        # No ASSERT_FAILED should appear.
        assert not any(e.code == "ASSERT_FAILED" for e in errors)

    def test_false_equality_fails(self) -> None:
        source = """\
module failing_asserts
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide with an assertion that contradicts the self-model."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide wrong_claim
    intent: "Guide that claims greet is INTERNAL even though it is PUBLIC."
    format: markdown
    output: docs/wrong_claim.md
    covers: [nerve::greet]
    asserts: [nerve::greet.visibility == INTERNAL]
    examples: [example::greet_example]
    ---
    Claim: greet is internal.
"""
        modules = {
            "chat": parse_s0ma(RICH_MODULE, filename="chat.s0ma"),
            "failing_asserts": parse_s0ma(source, filename="failing.s0ma"),
        }
        errors = validate_docs(modules)
        failed = [e for e in errors if e.code == "ASSERT_FAILED"]
        assert len(failed) == 1
        # Context includes expected/actual.
        assert failed[0].context["expected"] == "INTERNAL"
        assert failed[0].context["actual"] == "PUBLIC"

    def test_in_list_pass(self) -> None:
        source = """\
module in_list_asserts
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide whose assert uses the in operator to check kind membership."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide check
    intent: "Guide whose assert uses membership to check kind."
    format: markdown
    output: docs/check.md
    covers: [nerve::greet]
    asserts: [nerve::greet.kind in [SERVICE, FUNCTION]]
    examples: [example::greet_example]
    ---
    Checking kind via membership.
"""
        modules = {
            "chat": parse_s0ma(RICH_MODULE, filename="chat.s0ma"),
            "in_list_asserts": parse_s0ma(source, filename="in.s0ma"),
        }
        errors = validate_docs(modules)
        assert not any(e.code == "ASSERT_FAILED" for e in errors)

    def test_in_list_fail(self) -> None:
        source = """\
module in_list_bad
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide whose assert membership check does not include the actual kind."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide check
    intent: "Guide whose membership check excludes the actual kind."
    format: markdown
    output: docs/check.md
    covers: [nerve::greet]
    asserts: [nerve::greet.kind in [SERVICE, ADAPTER]]
    examples: [example::greet_example]
    ---
    Checking kind via membership.
"""
        modules = {
            "chat": parse_s0ma(RICH_MODULE, filename="chat.s0ma"),
            "in_list_bad": parse_s0ma(source, filename="in_bad.s0ma"),
        }
        errors = validate_docs(modules)
        failed = [e for e in errors if e.code == "ASSERT_FAILED"]
        assert failed

    def test_boolean_and_short_circuits_on_failure(self) -> None:
        source = """\
module bool_asserts
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide with a boolean AND assert that fails on the first operand."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide combo
    intent: "Guide whose AND assertion fails the first operand."
    format: markdown
    output: docs/combo.md
    covers: [nerve::greet]
    asserts: [nerve::greet.visibility == INTERNAL and nerve::greet.kind == FUNCTION]
    examples: [example::greet_example]
    ---
    Checking combined assert.
"""
        modules = {
            "chat": parse_s0ma(RICH_MODULE, filename="chat.s0ma"),
            "bool_asserts": parse_s0ma(source, filename="bool.s0ma"),
        }
        errors = validate_docs(modules)
        failed = [e for e in errors if e.code == "ASSERT_FAILED"]
        assert len(failed) == 1
        # The failure points at the FIRST operand (visibility), not kind.
        assert failed[0].context["lhs_field_path"] == ["visibility"]

    def test_not_inverts_result(self) -> None:
        source = """\
module not_asserts
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide whose assert wraps a true comparison in NOT; should fail."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide neg
    intent: "Guide whose NOT wraps a true comparison and should therefore fail."
    format: markdown
    output: docs/neg.md
    covers: [nerve::greet]
    asserts: [not nerve::greet.visibility == PUBLIC]
    examples: [example::greet_example]
    ---
    Checking negation.
"""
        modules = {
            "chat": parse_s0ma(RICH_MODULE, filename="chat.s0ma"),
            "not_asserts": parse_s0ma(source, filename="not.s0ma"),
        }
        errors = validate_docs(modules)
        assert any(e.code == "ASSERT_FAILED" for e in errors)

    def test_unresolved_entity_in_assert_is_unevaluable(self) -> None:
        source = """\
module unevaluable_asserts
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide whose assert targets a missing entity and is unevaluable."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide floating
    intent: "Guide whose assert targets an entity that does not exist."
    format: markdown
    output: docs/floating.md
    covers: [nerve::greet]
    asserts: [nerve::ghost.visibility == PUBLIC]
    examples: [example::greet_example]
    ---
    Floating reference.
"""
        modules = {
            "chat": parse_s0ma(RICH_MODULE, filename="chat.s0ma"),
            "unevaluable_asserts": parse_s0ma(source, filename="unev.s0ma"),
        }
        errors = validate_docs(modules)
        assert any(e.code == "ASSERT_UNEVALUABLE" for e in errors)


# ---------------------------------------------------------------------------
# DocValidator — deterministic ordering
# ---------------------------------------------------------------------------


class TestDocValidatorOrdering:
    def test_errors_are_sorted_by_module_name(self) -> None:
        # Two modules, both with dangling references; confirm module order.
        chat = parse_s0ma(RICH_MODULE, filename="chat.s0ma")
        zz_source = """\
module zz_guide
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide last in alphabetical order that references a ghost nerve."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide last
    intent: "Ghost reference in the alphabetically last module."
    format: markdown
    output: docs/last.md
    covers: [nerve::ghostA]
    asserts: [nerve::greet.visibility == PUBLIC]
    examples: [example::greet_example]
    ---
    {{nerve::ghostA}}
"""
        aa_source = """\
module aa_guide
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide first in alphabetical order that references a ghost nerve."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide first
    intent: "Ghost reference in the alphabetically first module."
    format: markdown
    output: docs/first.md
    covers: [nerve::ghostB]
    asserts: [nerve::greet.visibility == PUBLIC]
    examples: [example::greet_example]
    ---
    {{nerve::ghostB}}
"""
        modules = {
            chat.module.name: chat,
            "zz_guide": parse_s0ma(zz_source, filename="zz.s0ma"),
            "aa_guide": parse_s0ma(aa_source, filename="aa.s0ma"),
        }
        errors = validate_docs(modules)
        unresolved = [e for e in errors if e.code == "UNRESOLVED_REFERENCE"]
        assert unresolved
        # aa_guide errors come before zz_guide errors.
        files = [e.file for e in unresolved]
        aa_index = next(i for i, f in enumerate(files) if f == "aa_guide.s0ma")
        zz_index = next(i for i, f in enumerate(files) if f == "zz_guide.s0ma")
        assert aa_index < zz_index


# ---------------------------------------------------------------------------
# DSL-M4 (F-M5-2): the ``module`` predicate field
#
# ``module`` is the owning module's name, addressable on every entity kind
# so a multi-module project can render per-module references
# (``covers: [nerve where module == tools]``). The data rides every
# ``_IndexedEntity`` as ``module_name``; M4 exposes it in the ``fields``
# dict at index-build time and adds it to ``_FIELDS_BY_KIND``.
# ---------------------------------------------------------------------------


# A second module so module-scoped filters have something to discriminate.
BILLING_MODULE = """\
module billing
    layer: DOMAIN
    version: 1.0.0
    intent: "Billing domain module for module-predicate tests."
    exports: [invoice]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve invoice :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Produces an invoice total for the supplied line items."
    expects: "items is a non-empty list of positive numbers."
    guarantees: "Returns the summed total as a float."
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
    def invoice(items: list[float]) -> float:
        return sum(items)
"""


def _two_module_project() -> dict:
    """``chat`` (RICH_MODULE) + ``billing`` in a single project index input."""
    modules = _parse(RICH_MODULE, "chat")
    modules.update(_parse(BILLING_MODULE, "billing"))
    return modules


class TestModulePredicate:
    def test_module_is_addressable_field_on_every_kind(self) -> None:
        # Every indexed entity exposes its owning module under ``module``.
        index = build_project_index(_two_module_project())
        greet = index.lookup("nerve", "greet")
        message = index.lookup("cell", "Message")
        flow = index.lookup("ganglion", "HelloFlow")
        example = index.lookup("example", "greet_example")
        invoice = index.lookup("nerve", "invoice")
        chat_mod = index.lookup("module", "chat")
        assert greet is not None and greet.fields["module"] == "chat"
        assert message is not None and message.fields["module"] == "chat"
        assert flow is not None and flow.fields["module"] == "chat"
        assert example is not None and example.fields["module"] == "chat"
        assert invoice is not None and invoice.fields["module"] == "billing"
        # A module entity's ``module`` resolves to its own name.
        assert chat_mod is not None and chat_mod.fields["module"] == "chat"

    def test_filter_by_module_renders_only_that_module(self) -> None:
        # ``covers: [nerve where module == chat]`` selects only chat's nerves,
        # not billing's — the core F-M5-2 capability.
        source = """\
module chat_ref
    layer: DOMAIN
    version: 1.0.0
    intent: "Doc-ref scoped to the chat module's nerves only."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-ref chat_nerves
    intent: "Generated reference for chat's nerves."
    format: markdown
    output: docs/chat_nerves.md
    covers: [nerve where module == chat]
    sections: [intent]
"""
        modules = _two_module_project()
        modules.update(_parse(source, "chat_ref"))
        index = build_project_index(modules)
        fexpr = next(
            d for d in modules["chat_ref"].doc_refs
        ).covers[0]
        matched = materialize_filter(fexpr, index)
        matched_names = sorted(e.name for e in matched)
        # chat owns greet + _helper; billing's invoice is excluded.
        assert matched_names == ["_helper", "greet"]
        assert all(e.module_name == "chat" for e in matched)

    def test_module_filtered_doc_ref_validates_clean(self) -> None:
        # The whole doc-ref resolves without diagnostics — the predicate
        # field is accepted by validation and materialises to >0 entities.
        source = """\
module billing_ref
    layer: DOMAIN
    version: 1.0.0
    intent: "Doc-ref scoped to the billing module's nerves only."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-ref billing_nerves
    intent: "Generated reference for billing's nerves."
    format: markdown
    output: docs/billing_nerves.md
    covers: [nerve where module == billing]
    sections: [intent, expects, guarantees]
"""
        modules = _two_module_project()
        modules.update(_parse(source, "billing_ref"))
        errors = validate_docs(modules)
        assert errors == [], "\n".join(e.format_text() for e in errors)

    def test_module_field_access_resolves(self) -> None:
        # ``{{nerve::greet.module}}`` field-access resolves (no FIELD_NOT_FOUND)
        # because ``module`` is now a known, populated field.
        source = """\
module chat_guide
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide naming the owning module of the greet nerve."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide greet_origin
    intent: "Names the module that hosts the greet nerve."
    format: markdown
    output: docs/greet_origin.md
    covers: [nerve::greet]
    asserts: [nerve::greet.module == chat]
    examples: [example::greet_example]
    ---
    greet lives in the {{nerve::greet.module}} module.
"""
        modules = _two_module_project()
        modules.update(_parse(source, "chat_guide"))
        errors = validate_docs(modules)
        assert errors == [], "\n".join(e.format_text() for e in errors)

    def test_unknown_module_value_materialises_empty(self) -> None:
        # Unknown-VALUE semantics (the resolver's existing behavior): an
        # unrecognised module name matches nothing — there is no special
        # "unknown module" diagnostic; the filter simply materialises empty.
        source = """\
module ghost_ref
    layer: DOMAIN
    version: 1.0.0
    intent: "Doc-ref filtering on a module name that does not exist."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-ref ghost_nerves
    intent: "Reference for a non-existent module's nerves."
    format: markdown
    output: docs/ghost_nerves.md
    covers: [nerve where module == nonexistent]
    sections: [intent]
"""
        modules = _two_module_project()
        modules.update(_parse(source, "ghost_ref"))
        index = build_project_index(modules)
        fexpr = next(d for d in modules["ghost_ref"].doc_refs).covers[0]
        assert materialize_filter(fexpr, index) == []

    def test_unknown_module_value_is_empty_filter_warning_in_dev(self) -> None:
        # The empty materialisation surfaces through EMPTY_DOC_FILTER, which
        # is a WARNING in dev/migration and an ERROR in strict/release —
        # identical to any other predicate that matches no entity.
        source = """\
module ghost_ref
    layer: DOMAIN
    version: 1.0.0
    intent: "Doc-ref filtering on a module name that does not exist."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-ref ghost_nerves
    intent: "Reference for a non-existent module's nerves."
    format: markdown
    output: docs/ghost_nerves.md
    covers: [nerve where module == nonexistent]
    sections: [intent]
"""
        modules = _two_module_project()
        modules.update(_parse(source, "ghost_ref"))
        dev_errors = validate_docs(modules, mode=StrictnessMode.DEV)
        dev_empty = [e for e in dev_errors if e.code == "EMPTY_DOC_FILTER"]
        assert dev_empty and all(e.severity == "warning" for e in dev_empty)

        strict_errors = validate_docs(modules, mode=StrictnessMode.STRICT)
        strict_empty = [e for e in strict_errors if e.code == "EMPTY_DOC_FILTER"]
        assert strict_empty and all(e.severity == "error" for e in strict_empty)
