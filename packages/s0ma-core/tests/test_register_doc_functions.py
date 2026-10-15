"""Tests for the documentation subsystem registration functions (M2).

Covers:
    * Happy-path registration of doc-ref, doc-guide, and example through
      both the ComponentRegistry methods and the top-level wrappers
      exported from ``s0ma``.
    * Duplicate protection and idempotent upsert.
    * Input validation at the registration boundary (format, output path,
      runs_in, demonstrates).
    * SQLite persistence round-trip across registry restarts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import s0ma
from s0ma.exceptions import RegistrationError
from s0ma.models import (
    AssertExpr,
    DocGuideRegistration,
    DocRefRegistration,
    EntityRef,
    ExampleRegistration,
    FilterExpr,
    Section,
    SourceSpan,
)
from s0ma.registry import ComponentRegistry

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def registry() -> ComponentRegistry:
    """Return a fresh in-memory registry for each test."""
    return ComponentRegistry(persist=False)


@pytest.fixture()
def disk_registry(tmp_path: Path) -> ComponentRegistry:
    """Return a fresh SQLite-backed registry rooted at tmp_path."""
    return ComponentRegistry(persist=True, db_path=tmp_path / "reg.db")


def make_span() -> SourceSpan:
    return SourceSpan(file="src/module.s0ma", start_line=1, end_line=10)


def make_entity_ref(name: str = "initialize") -> EntityRef:
    return EntityRef(kind="nerve", name=name, module="s0ma")


# ---------------------------------------------------------------------------
# register_doc_ref — happy path & persistence
# ---------------------------------------------------------------------------

class TestRegisterDocRef:
    """ComponentRegistry.register_doc_ref stores doc-ref declarations."""

    def test_happy_path(self, registry: ComponentRegistry) -> None:
        reg = registry.register_doc_ref(
            name="api_reference",
            module="s0ma::api",
            intent="Reference for all public nerves",
            format="markdown",
            output="docs/api.md",
            covers=[FilterExpr(target_kind="nerve", predicate="public", raw="nerve[public]")],
            sections=[Section(title="Nerves")],
            content_hash="sha256:deadbeef",
            source_span=make_span(),
        )
        assert isinstance(reg, DocRefRegistration)
        assert registry.get_doc_ref("api_reference") is reg
        assert registry._doc_refs["api_reference"] is reg

    def test_duplicate_raises_by_default(self, registry: ComponentRegistry) -> None:
        registry.register_doc_ref(
            name="api_reference", module="m", intent="x",
            format="markdown", output="docs/api.md",
        )
        with pytest.raises(RegistrationError, match="already registered"):
            registry.register_doc_ref(
                name="api_reference", module="m", intent="x",
                format="markdown", output="docs/api.md",
            )

    def test_idempotent_upsert_replaces(self, registry: ComponentRegistry) -> None:
        registry.register_doc_ref(
            name="ref", module="m", intent="first",
            format="markdown", output="docs/x.md",
        )
        registry.register_doc_ref(
            name="ref", module="m", intent="second",
            format="markdown", output="docs/x.md",
            idempotent=True,
        )
        stored = registry.get_doc_ref("ref")
        assert stored is not None
        assert stored.intent == "second"

    def test_format_validated(self, registry: ComponentRegistry) -> None:
        with pytest.raises(ValueError, match="Unsupported doc format"):
            registry.register_doc_ref(
                name="x", module="m", intent="i",
                format="pdf", output="docs/x.md",
            )

    def test_output_rejects_absolute(self, registry: ComponentRegistry) -> None:
        with pytest.raises(ValueError, match="absolute"):
            registry.register_doc_ref(
                name="x", module="m", intent="i",
                format="markdown", output="/etc/passwd",
            )

    def test_output_rejects_parent_escape(self, registry: ComponentRegistry) -> None:
        with pytest.raises(ValueError, match=r"\.\.|must not contain"):
            registry.register_doc_ref(
                name="x", module="m", intent="i",
                format="markdown", output="../escape.md",
            )

    def test_output_rejects_empty(self, registry: ComponentRegistry) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            registry.register_doc_ref(
                name="x", module="m", intent="i",
                format="markdown", output="",
            )


# ---------------------------------------------------------------------------
# register_doc_guide
# ---------------------------------------------------------------------------

class TestRegisterDocGuide:
    """ComponentRegistry.register_doc_guide stores doc-guide declarations."""

    def test_happy_path(self, registry: ComponentRegistry) -> None:
        reg = registry.register_doc_guide(
            name="getting_started",
            module="s0ma::guides",
            intent="Onboarding",
            format="markdown",
            output="docs/getting_started.md",
            covers=[make_entity_ref()],
            asserts=[AssertExpr(expression="initialize is exported", source_span=make_span())],
            examples=[EntityRef(kind="example", name="hello_world", module="s0ma")],
            body="See {{example::hello_world}} to start.",
            content_hash="sha256:cafebabe",
            source_span=make_span(),
        )
        assert isinstance(reg, DocGuideRegistration)
        assert registry.get_doc_guide("getting_started") is reg
        assert len(reg.asserts) == 1

    def test_duplicate_raises(self, registry: ComponentRegistry) -> None:
        registry.register_doc_guide(
            name="g", module="m", intent="i",
            format="markdown", output="g.md",
        )
        with pytest.raises(RegistrationError):
            registry.register_doc_guide(
                name="g", module="m", intent="i",
                format="markdown", output="g.md",
            )

    def test_idempotent_replaces(self, registry: ComponentRegistry) -> None:
        registry.register_doc_guide(
            name="g", module="m", intent="first",
            format="markdown", output="g.md",
        )
        registry.register_doc_guide(
            name="g", module="m", intent="second",
            format="markdown", output="g.md",
            idempotent=True,
        )
        stored = registry.get_doc_guide("g")
        assert stored is not None
        assert stored.intent == "second"

    def test_format_validated(self, registry: ComponentRegistry) -> None:
        with pytest.raises(ValueError, match="Unsupported doc format"):
            registry.register_doc_guide(
                name="g", module="m", intent="i",
                format="pdf", output="g.md",
            )


# ---------------------------------------------------------------------------
# register_example
# ---------------------------------------------------------------------------

class TestRegisterExample:
    """ComponentRegistry.register_example stores example declarations."""

    def test_happy_path(self, registry: ComponentRegistry) -> None:
        reg = registry.register_example(
            name="hello_world",
            module="s0ma::examples",
            intent="Minimal hello",
            demonstrates=[make_entity_ref()],
            runs_in="standalone",
            body="print('hi')\n",
            source_span=make_span(),
        )
        assert isinstance(reg, ExampleRegistration)
        assert registry.get_example("hello_world") is reg

    def test_duplicate_raises(self, registry: ComponentRegistry) -> None:
        registry.register_example(
            name="ex", module="m", intent="i",
            demonstrates=[make_entity_ref()],
        )
        with pytest.raises(RegistrationError):
            registry.register_example(
                name="ex", module="m", intent="i",
                demonstrates=[make_entity_ref()],
            )

    def test_idempotent_replaces(self, registry: ComponentRegistry) -> None:
        registry.register_example(
            name="ex", module="m", intent="first",
            demonstrates=[make_entity_ref()],
        )
        registry.register_example(
            name="ex", module="m", intent="second",
            demonstrates=[make_entity_ref()],
            idempotent=True,
        )
        stored = registry.get_example("ex")
        assert stored is not None
        assert stored.intent == "second"

    def test_empty_demonstrates_rejected(self, registry: ComponentRegistry) -> None:
        with pytest.raises(ValueError, match="demonstrates"):
            registry.register_example(
                name="bad", module="m", intent="i",
                demonstrates=[],
            )

    def test_unknown_runs_in_rejected(self, registry: ComponentRegistry) -> None:
        with pytest.raises(ValueError, match="Unknown runs_in"):
            registry.register_example(
                name="bad", module="m", intent="i",
                demonstrates=[make_entity_ref()],
                runs_in="bogus",  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize("mode", ["standalone", "pytest", "integration"])
    def test_all_runs_in_modes_accepted(
        self, registry: ComponentRegistry, mode: str,
    ) -> None:
        reg = registry.register_example(
            name=f"ex_{mode}", module="m", intent="i",
            demonstrates=[make_entity_ref()],
            runs_in=mode,  # type: ignore[arg-type]
        )
        assert reg.runs_in == mode


# ---------------------------------------------------------------------------
# Top-level wrappers exported from s0ma
# ---------------------------------------------------------------------------

class TestTopLevelExports:
    """The three public functions are importable from ``s0ma``."""

    def test_exports_exist(self) -> None:
        assert hasattr(s0ma, "register_doc_ref")
        assert hasattr(s0ma, "register_doc_guide")
        assert hasattr(s0ma, "register_example")
        assert "register_doc_ref" in s0ma.__all__
        assert "register_doc_guide" in s0ma.__all__
        assert "register_example" in s0ma.__all__

    def test_wrappers_forward_to_global_registry(self, tmp_path: Path) -> None:
        """The module-level wrappers write to the process-global registry."""
        from s0ma.registry import (
            ComponentRegistry,
            reset_registry,
            set_registry,
        )

        # Swap in a fresh, isolated registry so this test does not
        # pollute — or get polluted by — the global singleton.
        fresh = ComponentRegistry(persist=False)
        set_registry(fresh)
        try:
            reg = s0ma.register_doc_ref(
                name="wrap_ref",
                module="m",
                intent="via wrapper",
                format="markdown",
                output="docs/wrap.md",
            )
            assert isinstance(reg, DocRefRegistration)
            assert fresh.get_doc_ref("wrap_ref") is reg

            ex = s0ma.register_example(
                name="wrap_ex",
                module="m",
                intent="via wrapper",
                demonstrates=[make_entity_ref()],
            )
            assert fresh.get_example("wrap_ex") is ex

            guide = s0ma.register_doc_guide(
                name="wrap_guide",
                module="m",
                intent="via wrapper",
                format="markdown",
                output="docs/wrap_guide.md",
            )
            assert fresh.get_doc_guide("wrap_guide") is guide
        finally:
            reset_registry()


# ---------------------------------------------------------------------------
# SQLite persistence round-trip
# ---------------------------------------------------------------------------

class TestPersistenceRoundTrip:
    """Registrations survive a close/reopen of the SQLite-backed registry."""

    def test_doc_ref_round_trip(self, tmp_path: Path) -> None:
        db_path = tmp_path / "reg.db"
        first = ComponentRegistry(persist=True, db_path=db_path)
        try:
            first.register_doc_ref(
                name="api_reference",
                module="s0ma::api",
                intent="Reference",
                format="markdown",
                output="docs/api.md",
                covers=[FilterExpr(target_kind="nerve", predicate=None, raw="nerve")],
                sections=[Section(title="Nerves")],
                content_hash="sha256:abcd",
                source_span=make_span(),
            )
        finally:
            first.close()

        second = ComponentRegistry(persist=True, db_path=db_path)
        try:
            stored = second.get_doc_ref("api_reference")
            assert stored is not None
            assert stored.module == "s0ma::api"
            assert stored.content_hash == "sha256:abcd"
            assert stored.covers[0].target_kind == "nerve"
            assert stored.sections[0].title == "Nerves"
        finally:
            second.close()

    def test_doc_guide_round_trip(self, tmp_path: Path) -> None:
        db_path = tmp_path / "reg.db"
        first = ComponentRegistry(persist=True, db_path=db_path)
        try:
            first.register_doc_guide(
                name="guide",
                module="m",
                intent="i",
                format="markdown",
                output="g.md",
                covers=[make_entity_ref()],
                asserts=[AssertExpr(expression="x", source_span=make_span())],
                examples=[EntityRef(kind="example", name="e", module="m")],
                body="body",
                content_hash="sha256:0",
                source_span=make_span(),
            )
        finally:
            first.close()

        second = ComponentRegistry(persist=True, db_path=db_path)
        try:
            stored = second.get_doc_guide("guide")
            assert stored is not None
            assert stored.body == "body"
            assert len(stored.asserts) == 1
            assert stored.asserts[0].expression == "x"
        finally:
            second.close()

    def test_example_round_trip(self, tmp_path: Path) -> None:
        db_path = tmp_path / "reg.db"
        first = ComponentRegistry(persist=True, db_path=db_path)
        try:
            first.register_example(
                name="ex",
                module="m",
                intent="i",
                demonstrates=[make_entity_ref()],
                runs_in="pytest",
                body="assert True\n",
                source_span=make_span(),
            )
        finally:
            first.close()

        second = ComponentRegistry(persist=True, db_path=db_path)
        try:
            stored = second.get_example("ex")
            assert stored is not None
            assert stored.runs_in == "pytest"
            assert stored.body == "assert True\n"
            assert stored.demonstrates[0].name == "initialize"
        finally:
            second.close()
