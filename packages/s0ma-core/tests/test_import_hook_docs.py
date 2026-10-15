"""Tests for import-hook integration of the documentation subsystem (plan M3).

Verifies that:
    * Modules carrying a ``__s0ma_doc_ref__`` / ``__s0ma_doc_guide__`` /
      ``__s0ma_example__`` marker paired with a matching registration
      import cleanly through the hook.
    * Modules carrying such a marker *without* a matching registration
      raise ``UnregisteredComponentError`` in strict mode.
    * The verification runs against the three registration kinds
      independently.
    * Non-documentation modules still import under the same hook
      (regression guard).
    * Lenient mode warns but does not raise.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma.exceptions import UnregisteredComponentError
from s0ma.import_hook import (
    DOC_GUIDE_MARKER_ATTR,
    DOC_REF_MARKER_ATTR,
    EXAMPLE_MARKER_ATTR,
    _format_doc_violation_message,
    _get_unregistered_doc_declarations,
    install_import_hook,
    uninstall_import_hook,
)
from s0ma.registry import ComponentRegistry, reset_registry, set_registry

if TYPE_CHECKING:
    from collections.abc import Generator


FIXTURES_ROOT = Path(__file__).parent / "test_fixtures" / "docs"

REGISTERED_DOC_REF_MODULE = (
    "tests.test_fixtures.docs.registered_doc_ref_module"
)
REGISTERED_DOC_GUIDE_MODULE = (
    "tests.test_fixtures.docs.registered_doc_guide_module"
)
REGISTERED_EXAMPLE_MODULE = (
    "tests.test_fixtures.docs.registered_example_module"
)
DANGLING_DOC_REF_MODULE = (
    "tests.test_fixtures.docs.dangling_doc_ref_module"
)
DANGLING_DOC_GUIDE_MODULE = (
    "tests.test_fixtures.docs.dangling_doc_guide_module"
)
DANGLING_EXAMPLE_MODULE = (
    "tests.test_fixtures.docs.dangling_example_module"
)
PLAIN_MODULE = "tests.test_fixtures.docs.plain_module"

ALL_FIXTURE_MODULES = [
    REGISTERED_DOC_REF_MODULE,
    REGISTERED_DOC_GUIDE_MODULE,
    REGISTERED_EXAMPLE_MODULE,
    DANGLING_DOC_REF_MODULE,
    DANGLING_DOC_GUIDE_MODULE,
    DANGLING_EXAMPLE_MODULE,
    PLAIN_MODULE,
    "tests.test_fixtures.docs",
]


def _purge_modules(names: list[str]) -> None:
    for name in names:
        sys.modules.pop(name, None)


@pytest.fixture()
def isolated_registry() -> Generator[ComponentRegistry, None, None]:
    """Install a fresh registry as the global singleton for the test.

    Keeps fixture state from bleeding across tests, and lets us assert on
    what was actually registered during a given import.
    """
    fresh = ComponentRegistry(persist=False)
    set_registry(fresh)
    try:
        yield fresh
    finally:
        reset_registry()


@pytest.fixture(autouse=True)
def _clean_hook_and_modules() -> Generator[None, None, None]:
    """Uninstall the hook and purge fixture modules between tests."""
    yield
    uninstall_import_hook()
    _purge_modules(ALL_FIXTURE_MODULES)


# ======================================================================
# _get_unregistered_doc_declarations — unit tests
# ======================================================================


class TestGetUnregisteredDocDeclarations:
    """Unit tests for the marker scanner."""

    def test_module_without_markers_is_clean(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        import types
        module = types.ModuleType("no_markers")
        assert _get_unregistered_doc_declarations(module) == []

    def test_doc_ref_marker_with_registration_is_clean(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        import types
        module = types.ModuleType("with_doc_ref")
        module.__s0ma_doc_ref__ = ("registered_ref",)  # type: ignore[attr-defined]
        isolated_registry.register_doc_ref(
            name="registered_ref",
            module="m",
            intent="i",
            format="markdown",
            output="docs/x.md",
        )
        assert _get_unregistered_doc_declarations(module) == []

    def test_doc_ref_marker_without_registration_is_missing(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        import types
        module = types.ModuleType("missing_doc_ref")
        module.__s0ma_doc_ref__ = ("nope",)  # type: ignore[attr-defined]
        assert _get_unregistered_doc_declarations(module) == [
            ("doc-ref", "nope"),
        ]

    def test_doc_guide_marker_without_registration_is_missing(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        import types
        module = types.ModuleType("missing_doc_guide")
        module.__s0ma_doc_guide__ = ("nope",)  # type: ignore[attr-defined]
        assert _get_unregistered_doc_declarations(module) == [
            ("doc-guide", "nope"),
        ]

    def test_example_marker_without_registration_is_missing(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        import types
        module = types.ModuleType("missing_example")
        module.__s0ma_example__ = ("nope",)  # type: ignore[attr-defined]
        assert _get_unregistered_doc_declarations(module) == [
            ("example", "nope"),
        ]

    def test_string_marker_is_treated_as_singleton(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        import types
        module = types.ModuleType("string_marker")
        # A bare string is a common accidental shorthand; treat as one
        # name, not as a sequence of characters.
        module.__s0ma_doc_ref__ = "solo"  # type: ignore[attr-defined]
        assert _get_unregistered_doc_declarations(module) == [
            ("doc-ref", "solo"),
        ]

    def test_multiple_names_all_reported(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        import types
        module = types.ModuleType("many")
        module.__s0ma_doc_ref__ = ("a", "b")  # type: ignore[attr-defined]
        module.__s0ma_example__ = ("c",)  # type: ignore[attr-defined]
        missing = _get_unregistered_doc_declarations(module)
        assert ("doc-ref", "a") in missing
        assert ("doc-ref", "b") in missing
        assert ("example", "c") in missing
        assert len(missing) == 3


# ======================================================================
# _format_doc_violation_message — unit tests
# ======================================================================


class TestFormatDocViolationMessage:
    def test_message_includes_module_and_declaration(self) -> None:
        msg = _format_doc_violation_message(
            "tests.fixtures.stale",
            "/path/to/stale.py",
            [("doc-ref", "api_reference")],
        )
        assert "tests.fixtures.stale" in msg
        assert "/path/to/stale.py" in msg
        assert "doc-ref 'api_reference'" in msg

    def test_message_mentions_remediation(self) -> None:
        msg = _format_doc_violation_message(
            "m", None, [("example", "hello")],
        )
        assert "Regenerate" in msg or "regenerate" in msg
        assert "register_doc_ref" in msg
        assert "register_example" in msg

    def test_message_lists_all_missing(self) -> None:
        msg = _format_doc_violation_message(
            "m",
            None,
            [
                ("doc-ref", "a"),
                ("doc-guide", "b"),
                ("example", "c"),
            ],
        )
        assert "doc-ref 'a'" in msg
        assert "doc-guide 'b'" in msg
        assert "example 'c'" in msg


# ======================================================================
# Marker-attribute constants exposed for DSL emitter coordination
# ======================================================================


class TestMarkerAttrConstants:
    """The marker names are the public contract with the DSL emitter."""

    def test_constants_are_stable_dunder_names(self) -> None:
        assert DOC_REF_MARKER_ATTR == "__s0ma_doc_ref__"
        assert DOC_GUIDE_MARKER_ATTR == "__s0ma_doc_guide__"
        assert EXAMPLE_MARKER_ATTR == "__s0ma_example__"


# ======================================================================
# End-to-end hook behavior on fixture modules
# ======================================================================


class TestFixtureImportsUnderHook:
    """Strict-mode hook installed over the fixtures directory."""

    def test_registered_doc_ref_module_imports_cleanly(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        _purge_modules(ALL_FIXTURE_MODULES)
        install_import_hook(FIXTURES_ROOT)
        importlib.import_module(REGISTERED_DOC_REF_MODULE)
        assert isolated_registry.get_doc_ref("fixture_api_ref") is not None

    def test_registered_doc_guide_module_imports_cleanly(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        _purge_modules(ALL_FIXTURE_MODULES)
        install_import_hook(FIXTURES_ROOT)
        importlib.import_module(REGISTERED_DOC_GUIDE_MODULE)
        assert isolated_registry.get_doc_guide("fixture_guide") is not None

    def test_registered_example_module_imports_cleanly(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        _purge_modules(ALL_FIXTURE_MODULES)
        install_import_hook(FIXTURES_ROOT)
        importlib.import_module(REGISTERED_EXAMPLE_MODULE)
        assert isolated_registry.get_example("fixture_example") is not None

    def test_dangling_doc_ref_raises(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        _purge_modules(ALL_FIXTURE_MODULES)
        install_import_hook(FIXTURES_ROOT)
        with pytest.raises(UnregisteredComponentError) as exc_info:
            importlib.import_module(DANGLING_DOC_REF_MODULE)
        msg = str(exc_info.value)
        assert "doc-ref 'fixture_missing_ref'" in msg

    def test_dangling_doc_guide_raises(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        _purge_modules(ALL_FIXTURE_MODULES)
        install_import_hook(FIXTURES_ROOT)
        with pytest.raises(UnregisteredComponentError) as exc_info:
            importlib.import_module(DANGLING_DOC_GUIDE_MODULE)
        msg = str(exc_info.value)
        assert "doc-guide 'fixture_missing_guide'" in msg

    def test_dangling_example_raises(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        _purge_modules(ALL_FIXTURE_MODULES)
        install_import_hook(FIXTURES_ROOT)
        with pytest.raises(UnregisteredComponentError) as exc_info:
            importlib.import_module(DANGLING_EXAMPLE_MODULE)
        msg = str(exc_info.value)
        assert "example 'fixture_missing_example'" in msg

    def test_plain_module_still_imports(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        """Regression: non-doc modules under the same hook still work."""
        _purge_modules(ALL_FIXTURE_MODULES)
        install_import_hook(FIXTURES_ROOT)
        mod = importlib.import_module(PLAIN_MODULE)
        assert mod.FixtureDocsPlainService().ping() == "pong"


class TestLenientMode:
    """In lenient mode, dangling markers warn but do not raise."""

    def test_dangling_doc_ref_warns_but_loads(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        _purge_modules(ALL_FIXTURE_MODULES)
        install_import_hook(FIXTURES_ROOT, strict=False)
        with pytest.warns(match="doc-ref 'fixture_missing_ref'"):
            module = importlib.import_module(DANGLING_DOC_REF_MODULE)
        assert module.__s0ma_doc_ref__ == ("fixture_missing_ref",)

    def test_registered_module_no_warning(
        self, isolated_registry: ComponentRegistry,
    ) -> None:
        _purge_modules(ALL_FIXTURE_MODULES)
        install_import_hook(FIXTURES_ROOT, strict=False)
        # No warning expected — registration matches marker.
        importlib.import_module(REGISTERED_DOC_REF_MODULE)
