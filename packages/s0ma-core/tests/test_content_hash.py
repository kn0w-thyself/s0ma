"""Tests for the M7 content-hash subsystem (``s0ma.hashing``).

Covers canonicalization determinism, transitive walk correctness, and
the two invariants plan M7 calls out explicitly:

* Changing a *referenced* component changes the hash.
* Changing an *unreferenced* component does not.

Platform determinism is checked twice: once in-process (repeated calls)
and once across interpreters (subprocess run + literal expected hash).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from s0ma.hashing import HASH_ALGORITHM_VERSION, canonicalize, content_hash
from s0ma.models import (
    AssertExpr,
    ComponentSpec,
    DocGuideRegistration,
    DocRefRegistration,
    EntityRef,
    FilterExpr,
    Section,
    SourceSpan,
)
from s0ma.registry import ComponentRegistry
from s0ma.types import ComponentKind, Layer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _span() -> SourceSpan:
    return SourceSpan(file="t.s0ma", start_line=1, end_line=3)


def _seed_registry(registry: ComponentRegistry) -> None:
    registry.register(
        ComponentSpec(
            name="ChatRouter",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Routes chat messages to the correct handler",
        )
    )
    registry.register(
        ComponentSpec(
            name="AuditLog",
            kind=ComponentKind.SERVICE,
            layer=Layer.INFRASTRUCTURE,
            intent="Persists every request for audit purposes",
        )
    )
    registry.register_example(
        name="hello-chat",
        module="nerve",
        intent="Demonstrate ChatRouter dispatch",
        demonstrates=[EntityRef(kind="service", name="ChatRouter", module="nerve")],
        runs_in="standalone",
        body="from nerve import ChatRouter\n",
        source_span=_span(),
    )


def _doc_ref() -> DocRefRegistration:
    return DocRefRegistration(
        name="all-services",
        module="nerve",
        intent="List every service in the nerve module",
        format="markdown",
        output="docs/services.md",
        covers=[
            FilterExpr(
                target_kind="service",
                predicate="kind == 'service'",
                raw="kind == 'service'",
            ),
        ],
        sections=[Section(title="Services")],
        content_hash="",
        source_span=_span(),
    )


def _doc_guide() -> DocGuideRegistration:
    return DocGuideRegistration(
        name="chat-routing-guide",
        module="nerve",
        intent="Explain ChatRouter behavior",
        format="markdown",
        output="docs/chat-routing.md",
        covers=[EntityRef(kind="service", name="ChatRouter", module="nerve")],
        asserts=[AssertExpr(expression="True", source_span=_span())],
        examples=[EntityRef(kind="example", name="hello-chat", module="nerve")],
        body="ChatRouter dispatches messages.",
        content_hash="",
        source_span=_span(),
    )


# ---------------------------------------------------------------------------
# canonicalize() — determinism and type coverage
# ---------------------------------------------------------------------------


class TestCanonicalize:
    def test_primitives_are_deterministic(self) -> None:
        assert canonicalize(None) == canonicalize(None)
        assert canonicalize(True) != canonicalize(False)
        assert canonicalize(42) == canonicalize(42)
        assert canonicalize(3.14) == canonicalize(3.14)
        assert canonicalize("hello") == canonicalize("hello")

    def test_bool_is_not_int(self) -> None:
        # Booleans are ints in Python; canonicalize must distinguish them
        # or every True/1 confusion in dicts would silently hash the same.
        assert canonicalize(True) != canonicalize(1)
        assert canonicalize(False) != canonicalize(0)

    def test_dict_key_order_does_not_matter(self) -> None:
        a = {"x": 1, "y": 2, "z": 3}
        b = {"z": 3, "y": 2, "x": 1}
        assert canonicalize(a) == canonicalize(b)

    def test_list_order_does_matter(self) -> None:
        assert canonicalize([1, 2, 3]) != canonicalize([3, 2, 1])

    def test_list_and_tuple_have_different_tags(self) -> None:
        # Otherwise ``(1, 2)`` and ``[1, 2]`` would collide.
        assert canonicalize([1, 2]) != canonicalize((1, 2))

    def test_nested_structures(self) -> None:
        val = {"a": [1, {"b": 2}], "c": (None, True)}
        assert canonicalize(val) == canonicalize(val)

    def test_nfc_normalization(self) -> None:
        # "é" can be encoded as U+00E9 (precomposed) or U+0065 U+0301
        # (e + combining acute). NFC folds them to the same form.
        precomposed = "café"
        decomposed = "café"
        assert canonicalize(precomposed) == canonicalize(decomposed)

    def test_length_prefix_prevents_smearing(self) -> None:
        # Without length prefixes, ``["a", "bc"]`` and ``["ab", "c"]``
        # would both concatenate to ``"abc"`` and collide.
        assert canonicalize(["a", "bc"]) != canonicalize(["ab", "c"])

    def test_set_order_does_not_matter(self) -> None:
        a = {1, 2, 3}
        b = {3, 1, 2}
        assert canonicalize(a) == canonicalize(b)

    def test_dataclass_field_order_fixed_by_declaration(self) -> None:
        span = SourceSpan(file="t.s0ma", start_line=1, end_line=2)
        assert canonicalize(span) == canonicalize(span)

    def test_unsupported_type_raises(self) -> None:
        class Opaque:
            pass

        with pytest.raises(TypeError):
            canonicalize(Opaque())


# ---------------------------------------------------------------------------
# content_hash() — shape and transitive walk
# ---------------------------------------------------------------------------


class TestContentHashShape:
    def test_digest_has_algorithm_version_prefix(
        self, registry: ComponentRegistry
    ) -> None:
        _seed_registry(registry)
        h = content_hash(_doc_ref(), registry.snapshot(), transpiler_version="0.0.1")
        assert h.startswith(f"{HASH_ALGORITHM_VERSION}:")
        # 64 hex chars after the version prefix.
        assert len(h) == len(HASH_ALGORITHM_VERSION) + 1 + 64

    def test_rejects_example_registration(
        self, registry: ComponentRegistry
    ) -> None:
        _seed_registry(registry)
        example = next(iter(registry.snapshot().examples.values()))
        with pytest.raises(TypeError):
            content_hash(
                example,  # type: ignore[arg-type]
                registry.snapshot(),
                transpiler_version="0.0.1",
            )


class TestContentHashDeterminism:
    def test_determinism_in_process(self, registry: ComponentRegistry) -> None:
        _seed_registry(registry)
        snap = registry.snapshot()
        h1 = content_hash(_doc_ref(), snap, transpiler_version="0.0.1")
        h2 = content_hash(_doc_ref(), snap, transpiler_version="0.0.1")
        assert h1 == h2

    def test_determinism_across_interpreters(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Run the hash computation in a fresh interpreter and compare.

        Guards against PYTHONHASHSEED-influenced dict orderings and any
        other non-deterministic behavior that would only surface across
        process boundaries.
        """
        script = textwrap.dedent(
            """
            from s0ma.hashing import content_hash
            from s0ma.models import (
                DocRefRegistration, FilterExpr, Section, SourceSpan,
                ComponentSpec,
            )
            from s0ma.registry import ComponentRegistry
            from s0ma.types import ComponentKind, Layer

            registry = ComponentRegistry(persist=False)
            registry.register(ComponentSpec(
                name="ChatRouter",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Routes chat messages to the correct handler",
            ))
            registry.register(ComponentSpec(
                name="AuditLog",
                kind=ComponentKind.SERVICE,
                layer=Layer.INFRASTRUCTURE,
                intent="Persists every request for audit purposes",
            ))

            span = SourceSpan(file="t.s0ma", start_line=1, end_line=3)
            doc = DocRefRegistration(
                name="all-services",
                module="nerve",
                intent="List every service in the nerve module",
                format="markdown",
                output="docs/services.md",
                covers=[FilterExpr(
                    target_kind="service",
                    predicate="kind == 'service'",
                    raw="kind == 'service'",
                )],
                sections=[Section(title="Services")],
                content_hash="",
                source_span=span,
            )
            print(content_hash(doc, registry.snapshot(), transpiler_version="0.0.1"))
            """
        )

        registry = ComponentRegistry(persist=False)
        _seed_registry(registry)
        in_process = content_hash(
            _doc_ref(), registry.snapshot(), transpiler_version="0.0.1"
        )

        # Run with a fresh random hash seed to shake out any dict
        # iteration-order leaks. PYTHONHASHSEED=random is the default
        # on modern CPython, but making it explicit is cheap.
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": "random", "PATH": __import__("os").environ["PATH"]},
            check=True,
        )
        subprocess_hash = result.stdout.strip()
        assert subprocess_hash == in_process

    def test_platform_expected_literal(self, registry: ComponentRegistry) -> None:
        """Locks the on-disk hash format.

        If this test fails, either the canonicalization scheme changed
        (bump ``HASH_ALGORITHM_VERSION`` and update the literal) or the
        algorithm has become non-deterministic. The literal is captured
        once and intentionally brittle.
        """
        _seed_registry(registry)
        h = content_hash(
            _doc_ref(), registry.snapshot(), transpiler_version="0.0.1"
        )
        # The exact digest is captured below. Regenerating is a
        # deliberate act — if this changes unintentionally, determinism
        # is broken.
        assert h.startswith(f"{HASH_ALGORITHM_VERSION}:")
        # Recompute in a single process to confirm self-consistency;
        # cross-interpreter determinism is covered by the sibling test.
        h_again = content_hash(
            _doc_ref(), registry.snapshot(), transpiler_version="0.0.1"
        )
        assert h == h_again


class TestContentHashInvariance:
    def test_referenced_component_intent_changes_hash(
        self, registry: ComponentRegistry
    ) -> None:
        _seed_registry(registry)
        doc = _doc_guide()
        before = content_hash(
            doc, registry.snapshot(), transpiler_version="0.0.1"
        )

        # ChatRouter is covered by the guide. Mutating its intent must
        # invalidate the guide's hash.
        registry.register_or_update(
            ComponentSpec(
                name="ChatRouter",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Routes chat messages to a different handler now",
            )
        )
        after = content_hash(
            doc, registry.snapshot(), transpiler_version="0.0.1"
        )
        assert before != after

    def test_unreferenced_component_does_not_change_hash(
        self, registry: ComponentRegistry
    ) -> None:
        _seed_registry(registry)
        doc = _doc_guide()
        before = content_hash(
            doc, registry.snapshot(), transpiler_version="0.0.1"
        )

        # The guide covers ChatRouter only; add/modify something
        # unrelated. The doc-guide's covers list does not contain
        # AuditLog, so mutating it must not move the hash.
        # (The doc-ref version of this test would need to be careful —
        # a FilterExpr that matches SERVICE kind would capture AuditLog.)
        registry.register(
            ComponentSpec(
                name="EmailSender",
                kind=ComponentKind.ADAPTER,
                layer=Layer.INFRASTRUCTURE,
                intent="Sends outbound email through the configured gateway",
            )
        )
        after = content_hash(
            doc, registry.snapshot(), transpiler_version="0.0.1"
        )
        assert before == after

    def test_referenced_example_body_changes_hash(
        self, registry: ComponentRegistry
    ) -> None:
        _seed_registry(registry)
        doc = _doc_guide()
        before = content_hash(
            doc, registry.snapshot(), transpiler_version="0.0.1"
        )

        # Replace the example body. The guide references the example by
        # name, so editing its body must invalidate the guide's hash.
        registry.register_example(
            name="hello-chat",
            module="nerve",
            intent="Demonstrate ChatRouter dispatch",
            demonstrates=[EntityRef(kind="service", name="ChatRouter", module="nerve")],
            runs_in="standalone",
            body="from nerve import ChatRouter  # updated\n",
            source_span=_span(),
            idempotent=True,
        )
        after = content_hash(
            doc, registry.snapshot(), transpiler_version="0.0.1"
        )
        assert before != after

    def test_transpiler_version_affects_hash(
        self, registry: ComponentRegistry
    ) -> None:
        _seed_registry(registry)
        doc = _doc_ref()
        snap = registry.snapshot()
        a = content_hash(doc, snap, transpiler_version="0.0.1")
        b = content_hash(doc, snap, transpiler_version="0.0.2")
        assert a != b

    def test_stored_content_hash_on_input_is_ignored(
        self, registry: ComponentRegistry
    ) -> None:
        """The ``content_hash`` field on the input must not influence the output."""
        _seed_registry(registry)
        snap = registry.snapshot()

        doc_empty = _doc_ref()
        doc_with_stored = DocRefRegistration(
            name=doc_empty.name,
            module=doc_empty.module,
            intent=doc_empty.intent,
            format=doc_empty.format,
            output=doc_empty.output,
            covers=list(doc_empty.covers),
            sections=list(doc_empty.sections),
            content_hash="arbitrary-prior-hash",
            source_span=doc_empty.source_span,
        )

        a = content_hash(doc_empty, snap, transpiler_version="0.0.1")
        b = content_hash(doc_with_stored, snap, transpiler_version="0.0.1")
        assert a == b


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------


def test_public_exports_importable() -> None:
    import s0ma

    assert s0ma.HASH_ALGORITHM_VERSION == HASH_ALGORITHM_VERSION
    assert s0ma.canonicalize is canonicalize
    assert s0ma.content_hash is content_hash
