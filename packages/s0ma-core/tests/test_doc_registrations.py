"""Tests for the documentation subsystem data models and registry stores.

Milestone 1 of the documentation subsystem implementation plan introduces
the pure-data plumbing — dataclasses plus empty registry stores, without
any public registration API. Those read/write paths land in later
milestones, so this file exercises construction, ``to_dict`` /
``from_dict`` round-trips, the empty registry invariant, and thread-safe
direct insertion into the new stores.
"""

from __future__ import annotations

import threading

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_span(start: int = 1, end: int = 10) -> SourceSpan:
    """Build a sample SourceSpan."""
    return SourceSpan(file="src/module.s0ma", start_line=start, end_line=end)


def make_doc_ref(name: str = "api_reference") -> DocRefRegistration:
    """Build a sample DocRefRegistration covering nerves."""
    return DocRefRegistration(
        name=name,
        module="s0ma::api",
        intent="Reference for all public nerves",
        format="markdown",
        output="docs/api.md",
        covers=[FilterExpr(target_kind="nerve", predicate="public", raw="nerve[public]")],
        sections=[
            Section(
                title="Nerves",
                iterate="covers",
                group_by="module",
                render={"template": "heading"},
            ),
        ],
        content_hash="sha256:deadbeef",
        source_span=make_span(),
    )


def make_doc_guide(name: str = "getting_started") -> DocGuideRegistration:
    """Build a sample DocGuideRegistration."""
    return DocGuideRegistration(
        name=name,
        module="s0ma::guides",
        intent="Onboarding guide for new users",
        format="markdown",
        output="docs/getting_started.md",
        covers=[EntityRef(kind="nerve", name="initialize", module="s0ma")],
        asserts=[
            AssertExpr(
                expression="initialize is exported",
                source_span=make_span(5, 5),
            ),
        ],
        examples=[EntityRef(kind="example", name="hello_world", module="s0ma")],
        body="See {{example::hello_world}} to get started.",
        content_hash="sha256:cafebabe",
        source_span=make_span(),
    )


def make_example(name: str = "hello_world") -> ExampleRegistration:
    """Build a sample ExampleRegistration."""
    return ExampleRegistration(
        name=name,
        module="s0ma::examples",
        intent="Minimal hello-world example",
        demonstrates=[EntityRef(kind="nerve", name="initialize", module="s0ma")],
        runs_in="standalone",
        body="from s0ma import initialize\ninitialize()\n",
        source_span=make_span(),
    )


# ---------------------------------------------------------------------------
# Leaf dataclasses
# ---------------------------------------------------------------------------

class TestSourceSpan:
    """SourceSpan carries file + line range information."""

    def test_construction(self) -> None:
        span = SourceSpan(file="a.s0ma", start_line=1, end_line=4)
        assert span.file == "a.s0ma"
        assert span.start_line == 1
        assert span.end_line == 4

    def test_round_trip(self) -> None:
        span = SourceSpan(file="a.s0ma", start_line=1, end_line=4)
        assert SourceSpan.from_dict(span.to_dict()) == span


class TestEntityRef:
    """EntityRef is a typed cross-reference to a registered entity."""

    def test_module_is_optional(self) -> None:
        ref = EntityRef(kind="nerve", name="do_thing")
        assert ref.module is None
        assert "module" not in ref.to_dict()

    def test_round_trip_with_module(self) -> None:
        ref = EntityRef(kind="nerve", name="do_thing", module="pkg::mod")
        assert EntityRef.from_dict(ref.to_dict()) == ref


class TestFilterExpr:
    """FilterExpr keeps parsed + raw form of a cover filter."""

    def test_round_trip_without_predicate(self) -> None:
        expr = FilterExpr(target_kind="nerve", predicate=None, raw="nerve")
        assert FilterExpr.from_dict(expr.to_dict()) == expr

    def test_round_trip_with_predicate(self) -> None:
        expr = FilterExpr(
            target_kind="nerve",
            predicate="public",
            raw="nerve[public]",
        )
        assert FilterExpr.from_dict(expr.to_dict()) == expr


class TestSection:
    """Section describes one rendered block in a doc-ref."""

    def test_defaults(self) -> None:
        section = Section(title="Overview")
        assert section.iterate is None
        assert section.group_by is None
        assert section.render == {}

    def test_round_trip(self) -> None:
        section = Section(
            title="Nerves",
            iterate="covers",
            group_by="module",
            render={"template": "heading", "depth": 2},
        )
        assert Section.from_dict(section.to_dict()) == section


class TestAssertExpr:
    """AssertExpr couples an assertion with its source location."""

    def test_round_trip(self) -> None:
        span = make_span(3, 3)
        assertion = AssertExpr(expression="x > 0", source_span=span)
        assert AssertExpr.from_dict(assertion.to_dict()) == assertion


# ---------------------------------------------------------------------------
# Registration dataclasses
# ---------------------------------------------------------------------------

class TestDocRefRegistration:
    """DocRefRegistration holds the full payload of a doc-ref declaration."""

    def test_construction(self) -> None:
        ref = make_doc_ref()
        assert ref.name == "api_reference"
        assert ref.format == "markdown"
        assert len(ref.covers) == 1
        assert ref.covers[0].target_kind == "nerve"
        assert len(ref.sections) == 1
        assert ref.sections[0].title == "Nerves"
        assert ref.source_span is not None

    def test_round_trip(self) -> None:
        ref = make_doc_ref()
        assert DocRefRegistration.from_dict(ref.to_dict()) == ref

    def test_round_trip_without_source_span(self) -> None:
        ref = DocRefRegistration(
            name="bare",
            module="m",
            intent="intent",
            format="markdown",
            output="out.md",
        )
        round_tripped = DocRefRegistration.from_dict(ref.to_dict())
        assert round_tripped == ref
        assert round_tripped.source_span is None

    def test_frozen(self) -> None:
        ref = make_doc_ref()
        try:
            ref.name = "other"  # type: ignore[misc]
        except Exception:
            return
        raise AssertionError("DocRefRegistration should be frozen")


class TestDocGuideRegistration:
    """DocGuideRegistration stores an authored doc-guide's body + refs."""

    def test_construction(self) -> None:
        guide = make_doc_guide()
        assert guide.name == "getting_started"
        assert "hello_world" in guide.body
        assert len(guide.covers) == 1
        assert len(guide.asserts) == 1
        assert len(guide.examples) == 1

    def test_round_trip(self) -> None:
        guide = make_doc_guide()
        assert DocGuideRegistration.from_dict(guide.to_dict()) == guide


class TestExampleRegistration:
    """ExampleRegistration carries runnable example bodies."""

    def test_construction(self) -> None:
        example = make_example()
        assert example.runs_in == "standalone"
        assert "initialize" in example.body
        assert len(example.demonstrates) == 1

    def test_round_trip(self) -> None:
        example = make_example()
        assert ExampleRegistration.from_dict(example.to_dict()) == example

    def test_runs_in_variants_round_trip(self) -> None:
        for mode in ("standalone", "pytest", "integration"):
            example = make_example(name=f"ex_{mode}")
            example = ExampleRegistration(
                name=example.name,
                module=example.module,
                intent=example.intent,
                demonstrates=example.demonstrates,
                runs_in=mode,  # type: ignore[arg-type]
                body=example.body,
                source_span=example.source_span,
            )
            assert ExampleRegistration.from_dict(example.to_dict()) == example


# ---------------------------------------------------------------------------
# Registry stores
# ---------------------------------------------------------------------------

class TestRegistryStores:
    """A fresh registry exposes empty doc/example stores."""

    def test_stores_are_empty(self) -> None:
        registry = ComponentRegistry(persist=False)
        assert registry._doc_refs == {}
        assert registry._doc_guides == {}
        assert registry._examples == {}

    def test_reset_clears_new_stores(self) -> None:
        registry = ComponentRegistry(persist=False)
        # Direct insertion — public register_* functions land in M2.
        registry._doc_refs["api_reference"] = make_doc_ref()
        registry._doc_guides["getting_started"] = make_doc_guide()
        registry._examples["hello_world"] = make_example()

        registry.reset()

        assert registry._doc_refs == {}
        assert registry._doc_guides == {}
        assert registry._examples == {}

    def test_threaded_writes_serialize(self) -> None:
        """Two threads inserting into _doc_refs under the registry lock
        must not lose writes (mirrors the thread-safety style used by
        existing registry tests).
        """
        registry = ComponentRegistry(persist=False)

        def insert(start: int, count: int) -> None:
            for i in range(start, start + count):
                ref = make_doc_ref(name=f"ref_{i}")
                with registry._lock:
                    registry._doc_refs[ref.name] = ref

        t1 = threading.Thread(target=insert, args=(0, 50))
        t2 = threading.Thread(target=insert, args=(50, 50))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(registry._doc_refs) == 100
        assert all(f"ref_{i}" in registry._doc_refs for i in range(100))


class TestPersistenceSchema:
    """The SQLite persistence layer must create the new tables on init.

    Milestone 1 only guarantees that the schema exists — actual persist
    paths are wired up in Milestone 2 alongside the register_* functions.
    """

    def test_tables_exist_after_init(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        db_path = tmp_path / "reg.db"
        registry = ComponentRegistry(persist=True, db_path=db_path)
        try:
            assert registry._connection is not None
            cursor = registry._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}
            assert {"doc_refs", "doc_guides", "examples"} <= tables
        finally:
            registry.close()

    def test_reset_recreates_new_tables(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        db_path = tmp_path / "reg.db"
        registry = ComponentRegistry(persist=True, db_path=db_path)
        try:
            registry.reset()
            assert registry._connection is not None
            cursor = registry._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}
            assert {"doc_refs", "doc_guides", "examples"} <= tables
        finally:
            registry.close()

    def test_load_tolerates_missing_new_tables(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """An older DB without the doc tables must still load cleanly.

        Exercises the try/except OperationalError fallback in _load_all
        for the three new stores.
        """
        import sqlite3

        db_path = tmp_path / "old.db"
        # Build a pre-docs DB with only the components table.
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE components (
                name TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                layer TEXT NOT NULL,
                intent TEXT NOT NULL,
                contracts_json TEXT,
                dependencies_json TEXT,
                resource_profile_json TEXT,
                version TEXT,
                metadata_json TEXT,
                module_path TEXT,
                qualified_name TEXT,
                source_file TEXT,
                registered_at TEXT,
                is_framework INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()
        conn.close()

        registry = ComponentRegistry(persist=True, db_path=db_path)
        try:
            assert registry._doc_refs == {}
            assert registry._doc_guides == {}
            assert registry._examples == {}
        finally:
            registry.close()
