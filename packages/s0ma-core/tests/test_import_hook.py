"""Comprehensive tests for the S0ma import hook enforcement mechanism.

The import hook is what makes the self-model load-bearing rather than advisory.
These tests verify that:
- Registered modules import successfully
- Unregistered public entities are caught in strict mode
- @internal-decorated entities are correctly exempted
- Private entities (starting with _) are ignored
- Third-party and standard library imports are unaffected
- S0ma's own modules are allowlisted
- The hook lifecycle (install/uninstall) works correctly
- Error messages are clear and actionable
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma.exceptions import UnregisteredComponentError
from s0ma.import_hook import (
    S0maDSLLoader,
    S0maFinder,
    S0maLoader,
    _format_violation_message,
    _get_unregistered_entities,
    _is_public_entity,
    install_import_hook,
    is_hook_installed,
    uninstall_import_hook,
)

if TYPE_CHECKING:
    from collections.abc import Generator


# Path to the sample_project used for import hook testing
SAMPLE_PROJECT_ROOT = Path(__file__).parent / "sample_project"

# Module names within sample_project
REGISTERED_MODULE = "tests.sample_project.registered_module"
UNREGISTERED_MODULE = "tests.sample_project.unregistered_module"
MIXED_MODULE = "tests.sample_project.mixed_module"
INTERNAL_MODULE = "tests.sample_project.internal_module"
PRIVATE_MODULE = "tests.sample_project.private_module"

# All sample modules for cleanup
ALL_SAMPLE_MODULES = [
    REGISTERED_MODULE,
    UNREGISTERED_MODULE,
    MIXED_MODULE,
    INTERNAL_MODULE,
    PRIVATE_MODULE,
    "tests.sample_project",
]


def _purge_modules(module_names: list[str]) -> None:
    """Remove modules from sys.modules to force re-import."""
    for name in module_names:
        sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def _clean_hook_and_modules() -> Generator[None, None, None]:
    """Ensure the import hook is uninstalled and sample modules are purged."""
    yield
    uninstall_import_hook()
    _purge_modules(ALL_SAMPLE_MODULES)


# ======================================================================
# Tests for _is_public_entity helper
# ======================================================================


class TestIsPublicEntity:
    """Tests for the _is_public_entity() helper function."""

    def test_public_class_is_detected(self) -> None:
        class MyClass:
            pass

        assert _is_public_entity("MyClass", MyClass) is True

    def test_public_function_is_detected(self) -> None:
        def my_func() -> None:
            pass

        assert _is_public_entity("my_func", my_func) is True

    def test_private_class_is_ignored(self) -> None:
        class _PrivateClass:
            pass

        assert _is_public_entity("_PrivateClass", _PrivateClass) is False

    def test_private_function_is_ignored(self) -> None:
        def _private_func() -> None:
            pass

        assert _is_public_entity("_private_func", _private_func) is False

    def test_dunder_is_ignored(self) -> None:
        # _is_public_entity inspects the name string, not the callable's
        # own __name__. Passing the dunder name as a string literal
        # keeps the test semantically accurate without forcing Python to
        # define a dunder-named function (which would be a code smell).
        def _dunder_stub() -> None:
            pass

        assert _is_public_entity("__special__", _dunder_stub) is False

    def test_string_constant_is_ignored(self) -> None:
        assert _is_public_entity("MY_CONSTANT", "some string") is False

    def test_integer_constant_is_ignored(self) -> None:
        assert _is_public_entity("MAX_RETRIES", 42) is False

    def test_none_is_ignored(self) -> None:
        assert _is_public_entity("nothing", None) is False

    def test_list_is_ignored(self) -> None:
        assert _is_public_entity("items", [1, 2, 3]) is False


# ======================================================================
# Tests for _get_unregistered_entities helper
# ======================================================================


class TestGetUnregisteredEntities:
    """Tests for the _get_unregistered_entities() scanner."""

    def test_finds_unregistered_class(self) -> None:
        """Import unregistered module without hook and scan it."""
        _purge_modules([UNREGISTERED_MODULE])
        module = importlib.import_module(UNREGISTERED_MODULE)
        unregistered = _get_unregistered_entities(module)
        names = [name for name, _ in unregistered]
        assert "UnregisteredService" in names
        assert "unregistered_function" in names

    def test_registered_entities_pass(self) -> None:
        """Registered entities should not appear in the scan results."""
        _purge_modules([REGISTERED_MODULE])
        module = importlib.import_module(REGISTERED_MODULE)
        unregistered = _get_unregistered_entities(module)
        assert len(unregistered) == 0

    def test_internal_entities_pass(self) -> None:
        """@internal entities should not appear in the scan results."""
        _purge_modules([INTERNAL_MODULE])
        module = importlib.import_module(INTERNAL_MODULE)
        unregistered = _get_unregistered_entities(module)
        assert len(unregistered) == 0

    def test_private_entities_pass(self) -> None:
        """Private entities should not appear in the scan results."""
        _purge_modules([PRIVATE_MODULE])
        module = importlib.import_module(PRIVATE_MODULE)
        unregistered = _get_unregistered_entities(module)
        assert len(unregistered) == 0

    def test_mixed_module_detects_violations(self) -> None:
        """Mixed module with some registered and some not."""
        _purge_modules([MIXED_MODULE])
        module = importlib.import_module(MIXED_MODULE)
        unregistered = _get_unregistered_entities(module)
        names = [name for name, _ in unregistered]
        assert "MixedUnregisteredClass" in names
        assert "MixedRegisteredClass" not in names


# ======================================================================
# Tests for _format_violation_message
# ======================================================================


class TestFormatViolationMessage:
    """Tests for the error message formatting."""

    def test_message_includes_module_name(self) -> None:
        msg = _format_violation_message(
            "myapp.services", None, [("MyService", type("MyService", (), {}))]
        )
        assert "myapp.services" in msg

    def test_message_includes_file_path(self) -> None:
        msg = _format_violation_message(
            "myapp.services",
            "/path/to/services.py",
            [("MyService", type("MyService", (), {}))],
        )
        assert "/path/to/services.py" in msg

    def test_message_includes_entity_names(self) -> None:
        msg = _format_violation_message(
            "myapp.services",
            None,
            [
                ("MyService", type("MyService", (), {})),
                ("helper_func", lambda: None),
            ],
        )
        assert "MyService" in msg
        assert "helper_func" in msg

    def test_message_distinguishes_class_and_function(self) -> None:
        msg = _format_violation_message(
            "myapp.services",
            None,
            [
                ("MyService", type("MyService", (), {})),
                ("helper_func", lambda: None),
            ],
        )
        assert "class 'MyService'" in msg
        assert "function 'helper_func'" in msg

    def test_message_includes_remediation_suggestions(self) -> None:
        msg = _format_violation_message(
            "myapp.services",
            None,
            [("MyService", type("MyService", (), {}))],
        )
        assert "@component" in msg
        assert "@internal" in msg
        assert "leading underscore" in msg


# ======================================================================
# Tests for the import hook lifecycle
# ======================================================================


class TestHookLifecycle:
    """Tests for install/uninstall/is_hook_installed."""

    def test_hook_not_installed_initially(self) -> None:
        assert is_hook_installed() is False

    def test_install_activates_hook(self) -> None:
        install_import_hook(SAMPLE_PROJECT_ROOT)
        assert is_hook_installed() is True

    def test_uninstall_deactivates_hook(self) -> None:
        install_import_hook(SAMPLE_PROJECT_ROOT)
        uninstall_import_hook()
        assert is_hook_installed() is False

    def test_uninstall_without_install_is_noop(self) -> None:
        """Uninstalling when nothing is installed should not raise."""
        uninstall_import_hook()  # Should not raise
        assert is_hook_installed() is False

    def test_install_returns_finder(self) -> None:
        finder = install_import_hook(SAMPLE_PROJECT_ROOT)
        assert isinstance(finder, S0maFinder)

    def test_finder_is_on_meta_path(self) -> None:
        finder = install_import_hook(SAMPLE_PROJECT_ROOT)
        assert finder in sys.meta_path

    def test_finder_removed_from_meta_path_on_uninstall(self) -> None:
        finder = install_import_hook(SAMPLE_PROJECT_ROOT)
        uninstall_import_hook()
        assert finder not in sys.meta_path

    def test_idempotent_install(self) -> None:
        """Installing twice should replace the first hook, not double-install."""
        finder1 = install_import_hook(SAMPLE_PROJECT_ROOT)
        finder2 = install_import_hook(SAMPLE_PROJECT_ROOT)
        assert finder1 is not finder2
        assert finder1 not in sys.meta_path
        assert finder2 in sys.meta_path
        # Only one S0maFinder should be in meta_path
        s0ma_finders = [f for f in sys.meta_path if isinstance(f, S0maFinder)]
        assert len(s0ma_finders) == 1

    def test_install_with_allowlist(self) -> None:
        finder = install_import_hook(
            SAMPLE_PROJECT_ROOT, allowlist={"myapp", "s0ma"}
        )
        assert "myapp" in finder.allowlist
        assert "s0ma" in finder.allowlist

    def test_install_strict_mode_default(self) -> None:
        finder = install_import_hook(SAMPLE_PROJECT_ROOT)
        assert finder.strict is True

    def test_install_lenient_mode(self) -> None:
        finder = install_import_hook(SAMPLE_PROJECT_ROOT, strict=False)
        assert finder.strict is False


# ======================================================================
# Tests for strict mode enforcement
# ======================================================================


class TestStrictModeEnforcement:
    """Tests for import hook in strict mode (default)."""

    def test_registered_module_imports_successfully(self) -> None:
        """Fully registered module should import without error."""
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        module = importlib.import_module(REGISTERED_MODULE)
        assert hasattr(module, "SampleService")
        assert hasattr(module, "sample_helper")

    def test_unregistered_module_raises_error(self) -> None:
        """Module with unregistered public entities should raise."""
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        with pytest.raises(UnregisteredComponentError) as exc_info:
            importlib.import_module(UNREGISTERED_MODULE)
        error_msg = str(exc_info.value)
        assert "UnregisteredService" in error_msg
        assert "unregistered_function" in error_msg

    def test_mixed_module_raises_error(self) -> None:
        """Module with at least one unregistered entity should raise."""
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        with pytest.raises(UnregisteredComponentError) as exc_info:
            importlib.import_module(MIXED_MODULE)
        error_msg = str(exc_info.value)
        assert "MixedUnregisteredClass" in error_msg
        # The registered class should not be in the error
        assert "MixedRegisteredClass" not in error_msg

    def test_internal_module_imports_successfully(self) -> None:
        """Module with @internal-decorated entities should pass."""
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        module = importlib.import_module(INTERNAL_MODULE)
        assert hasattr(module, "InternalModuleService")
        assert hasattr(module, "format_output")
        assert hasattr(module, "legacy_helper")

    def test_private_module_imports_successfully(self) -> None:
        """Module with only private names should pass."""
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        module = importlib.import_module(PRIVATE_MODULE)
        assert hasattr(module, "_PrivateHelper")
        assert hasattr(module, "_private_function")

    def test_error_message_is_actionable(self) -> None:
        """Error message should include module name and remediation."""
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        with pytest.raises(UnregisteredComponentError) as exc_info:
            importlib.import_module(UNREGISTERED_MODULE)
        error_msg = str(exc_info.value)
        assert "Unregistered public entities" in error_msg
        assert "@component" in error_msg
        assert "@internal" in error_msg

    def test_error_identifies_entity_types(self) -> None:
        """Error should distinguish classes from functions."""
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        with pytest.raises(UnregisteredComponentError) as exc_info:
            importlib.import_module(UNREGISTERED_MODULE)
        error_msg = str(exc_info.value)
        assert "class 'UnregisteredService'" in error_msg
        assert "function 'unregistered_function'" in error_msg


# ======================================================================
# Tests for lenient mode enforcement
# ======================================================================


class TestLenientModeEnforcement:
    """Tests for import hook in lenient mode (warn, don't raise)."""

    def test_unregistered_module_warns_but_loads(self) -> None:
        """In lenient mode, violations should warn but not raise."""
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT, strict=False)
        with pytest.warns(match="Unregistered public entities"):
            module = importlib.import_module(UNREGISTERED_MODULE)
        assert hasattr(module, "UnregisteredService")

    def test_registered_module_no_warning(self) -> None:
        """Registered modules should not produce warnings even in lenient mode."""
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT, strict=False)
        # No warning expected
        module = importlib.import_module(REGISTERED_MODULE)
        assert hasattr(module, "SampleService")


# ======================================================================
# Tests for scope and allowlist
# ======================================================================


class TestScopeAndAllowlist:
    """Tests for module scope detection and allowlist behavior."""

    def test_standard_library_unaffected(self) -> None:
        """Importing standard library modules should work normally."""
        install_import_hook(SAMPLE_PROJECT_ROOT)
        import json  # noqa: F811

        assert json.dumps({"key": "value"}) == '{"key": "value"}'

    def test_third_party_unaffected(self) -> None:
        """Importing third-party packages should work normally."""
        install_import_hook(SAMPLE_PROJECT_ROOT)
        import pytest as pt

        assert pt is not None

    def test_s0ma_allowlisted(self) -> None:
        """S0ma's own modules should be skippable via allowlist."""
        install_import_hook(
            SAMPLE_PROJECT_ROOT, allowlist={"s0ma"}
        )
        # This should not raise, even though s0ma modules are under
        # the project root (they're allowlisted)
        from s0ma.types import ComponentKind

        assert ComponentKind.SERVICE is not None

    def test_allowlist_prefix_matching(self) -> None:
        """Allowlist should match dotted module name prefixes."""
        finder = S0maFinder(
            SAMPLE_PROJECT_ROOT,
            allowlist={"tests.sample_project"},
        )
        # The allowlisted prefix should cause find_spec to return None
        # because "tests.sample_project.unregistered_module" starts with
        # "tests.sample_project."
        result = finder.find_spec(
            "tests.sample_project.unregistered_module"
        )
        assert result is None

    def test_allowlist_exact_match(self) -> None:
        """Allowlist should match exact module names too."""
        finder = S0maFinder(
            SAMPLE_PROJECT_ROOT,
            allowlist={"tests.sample_project.unregistered_module"},
        )
        result = finder.find_spec(
            "tests.sample_project.unregistered_module"
        )
        assert result is None

    def test_allowlist_does_not_match_partial_names(self) -> None:
        """Allowlist prefix should not match partial dotted segments."""
        finder = S0maFinder(
            SAMPLE_PROJECT_ROOT,
            allowlist={"tests.sample_project.unregistered"},
        )
        # "tests.sample_project.unregistered_module" does NOT start with
        # "tests.sample_project.unregistered." — the next char is "_" not "."
        # So this should NOT be allowlisted
        result = finder.find_spec(
            "tests.sample_project.unregistered_module"
        )
        # Should return a spec (not None) because it's not allowlisted
        assert result is not None

    def test_out_of_scope_module_unaffected(self) -> None:
        """Modules outside project_root should not be intercepted."""
        # Point to a non-existent directory that doesn't contain our tests
        install_import_hook(Path(__file__).parent / "nonexistent_dir")
        # Sample modules should import normally (no enforcement)
        _purge_modules(ALL_SAMPLE_MODULES)
        module = importlib.import_module(UNREGISTERED_MODULE)
        assert hasattr(module, "UnregisteredService")


# ======================================================================
# Tests for S0maFinder internals
# ======================================================================


class TestS0maFinder:
    """Tests for S0maFinder behavior."""

    def test_project_root_is_resolved(self) -> None:
        finder = S0maFinder(".")
        assert finder.project_root.is_absolute()

    def test_default_allowlist_is_empty(self) -> None:
        finder = S0maFinder(".")
        assert finder.allowlist == set()

    def test_find_spec_returns_none_for_nonexistent(self) -> None:
        finder = S0maFinder(SAMPLE_PROJECT_ROOT)
        result = finder.find_spec("this.module.does.not.exist")
        assert result is None

    def test_find_spec_returns_none_when_inactive(self) -> None:
        finder = S0maFinder(SAMPLE_PROJECT_ROOT)
        finder._active = False
        result = finder.find_spec(REGISTERED_MODULE)
        assert result is None


# ======================================================================
# Tests for S0maLoader internals
# ======================================================================


class TestS0maLoader:
    """Tests for S0maLoader behavior."""

    def test_loader_stores_strict_flag(self) -> None:
        class FakeLoader:
            pass

        loader = S0maLoader(FakeLoader(), strict=True)  # type: ignore[arg-type]
        assert loader._strict is True

    def test_loader_stores_lenient_flag(self) -> None:
        class FakeLoader:
            pass

        loader = S0maLoader(FakeLoader(), strict=False)  # type: ignore[arg-type]
        assert loader._strict is False


# ======================================================================
# Tests for S0maDSLLoader cache artifacts
# ======================================================================


class TestS0maDSLLoaderCacheArtifacts:
    """The runtime-cache IR references its outputs by basename (INV-5)."""

    MINIMAL_S0MA_SOURCE = (
        "module cache_probe\n"
        "    layer: APPLICATION\n"
        "    version: 1.0.0\n"
        '    intent: "Minimal module exercising the runtime-cache IR'
        ' artifact."\n'
        "    exports: []\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "\n"
        "cell ANSWER :: APPLICATION\n"
        "    kind: CONSTANT\n"
        "    visibility: INTERNAL\n"
        '    intent: "A constant used only to make the module'
        ' non-empty."\n'
        '    schema: "int constant. Value: 42."\n'
        "    invariants: none\n"
        "    covered_by: none\n"
        "    ---\n"
        "    ANSWER: int = 42\n"
    )

    def test_cache_ir_references_cached_py_by_basename(
        self, tmp_path: Path
    ) -> None:
        """The cache IR's ``transpiled_file`` is the cached .py's basename.

        Same policy as the s0ma-dsl build artifacts (WIN-M3): the IR is
        always written next to the cached ``.py`` it describes, so the
        basename is a complete, directory-independent reference — and
        emitted artifacts must not embed absolute machine paths (INV-5).
        Also guards against the cache directory's path leaking into the
        artifact bytes in either its raw or its JSON-escaped rendering
        (the two differ on Windows, where escaping hid the WIN-M3 leak).
        """
        pytest.importorskip("s0ma_dsl", reason="s0ma-dsl not installed")

        s0ma_path = tmp_path / "cache_probe.s0ma"
        s0ma_path.write_text(self.MINIMAL_S0MA_SOURCE, encoding="utf-8")

        loader = S0maDSLLoader(s0ma_path, tmp_path)
        loader._cache_dir.mkdir()
        loader._write_ir_and_map(self.MINIMAL_S0MA_SOURCE)

        ir_path = loader._cache_dir / "cache_probe.s0ma.json"
        raw_ir = ir_path.read_text(encoding="utf-8")
        ir = json.loads(raw_ir)

        assert ir["module"]["transpiled_file"] == "cache_probe.py"

        cache_dir = str(loader._cache_dir)
        for needle in {cache_dir, json.dumps(cache_dir)[1:-1]}:
            assert needle not in raw_ir


# ======================================================================
# Tests for registered component functionality after hook import
# ======================================================================


class TestFunctionalityAfterHookImport:
    """Verify that components imported through the hook still work."""

    def test_registered_class_is_functional(self) -> None:
        """A class imported through the hook should be fully functional."""
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        module = importlib.import_module(REGISTERED_MODULE)
        service = module.SampleService()
        assert service.process() == "processed"

    def test_registered_function_is_callable(self) -> None:
        """A function imported through the hook should be callable."""
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        module = importlib.import_module(REGISTERED_MODULE)
        assert module.sample_helper() == "helped"

    def test_internal_function_is_callable(self) -> None:
        """An @internal function imported through the hook should work."""
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        module = importlib.import_module(INTERNAL_MODULE)
        assert module.format_output("test") == "[test]"

    def test_component_spec_attached_after_hook(self) -> None:
        """@component spec should be accessible after hook import."""
        _purge_modules(ALL_SAMPLE_MODULES)
        install_import_hook(SAMPLE_PROJECT_ROOT)
        module = importlib.import_module(REGISTERED_MODULE)
        assert hasattr(module.SampleService, "__component__")
        assert module.SampleService.__component__.name == "SampleService"
