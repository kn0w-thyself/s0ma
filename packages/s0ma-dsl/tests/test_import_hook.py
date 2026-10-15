"""Import hook integration tests per PRD §2.7.3.

Tests the complete path: .s0ma file → S0maFinder discovery → S0maDSLLoader
transpilation → caching → module loading → registry integration.

Also tests: cache invalidation on source change, syntax error handling,
mixed .s0ma/.py projects, and the S0maFinder .s0ma discovery logic.
"""

from __future__ import annotations

import contextlib
import hashlib
import sys
from typing import TYPE_CHECKING

import pytest
from s0ma.import_hook import (
    S0maDSLLoader,
    S0maFinder,
    install_import_hook,
    is_hook_installed,
    uninstall_import_hook,
)
from s0ma.registry import reset_registry

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_S0MA = '''\
module hello_world
    layer: DOMAIN
    version: 1.0.0
    intent: "A minimal test module for import hook validation"
    exports: [greet]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve greet :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Returns a greeting string for the given name"
    expects: "name: str"
    guarantees: "Returns a non-empty greeting string"
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
    def greet(name: str) -> str:
        return f"Hello, {name}!"
'''

MODIFIED_S0MA = '''\
module hello_world
    layer: DOMAIN
    version: 1.1.0
    intent: "A modified test module for import hook cache invalidation"
    exports: [greet]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve greet :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Returns a modified greeting string for the given name"
    expects: "name: str"
    guarantees: "Returns a non-empty greeting string"
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
    def greet(name: str) -> str:
        return f"Greetings, {name}!"
'''

INVALID_S0MA = '''\
module broken
    layer: DOMAIN
    version: 1.0.0
    intent: "This module is intentionally broken"
    exports: [some_nerve]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve some_nerve :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Intentionally missing required fields"
    expects: none
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
'''


@pytest.fixture()
def s0ma_project(tmp_path: Path):
    """Create a temporary project directory with a .s0ma file."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # Write the .s0ma file
    s0ma_file = project_dir / "hello_world.s0ma"
    s0ma_file.write_text(MINIMAL_S0MA, encoding="utf-8")

    yield project_dir

    # Cleanup: remove any cached modules
    for mod_name in list(sys.modules):
        if mod_name.startswith("hello_world"):
            del sys.modules[mod_name]


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset the global registry before and after each test.

    Transpiled .s0ma code calls @component() and register_module() which
    register into the global singleton registry. Without cleanup, these
    persist across tests and cause RegistrationError on re-import.
    """
    reset_registry()
    yield
    reset_registry()
    if is_hook_installed():
        uninstall_import_hook()
    # Evict any dynamically imported modules from sys.modules
    for mod_name in list(sys.modules):
        if mod_name in ("hello_world", "broken"):
            del sys.modules[mod_name]


# ---------------------------------------------------------------------------
# S0maFinder .s0ma discovery tests
# ---------------------------------------------------------------------------


class TestS0maFileDiscovery:
    """Tests for S0maFinder._find_s0ma_spec."""

    def test_finds_s0ma_file(self, s0ma_project: Path) -> None:
        """S0maFinder discovers a .s0ma file under project root."""
        finder = S0maFinder(s0ma_project, strict=False)
        spec = finder._find_s0ma_spec("hello_world", path=None)

        assert spec is not None
        assert spec.name == "hello_world"
        assert spec.origin is not None
        assert spec.origin.endswith(".s0ma")

    def test_ignores_s0ma_outside_project(self, tmp_path: Path) -> None:
        """S0maFinder does not discover .s0ma files outside project root."""
        # Create .s0ma file outside project root
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "rogue.s0ma").write_text(MINIMAL_S0MA, encoding="utf-8")

        project = tmp_path / "project"
        project.mkdir()

        finder = S0maFinder(project, strict=False)
        spec = finder._find_s0ma_spec("rogue", path=[str(outside)])

        assert spec is None

    def test_no_s0ma_file_returns_none(self, tmp_path: Path) -> None:
        """When no .s0ma file exists, returns None (falls back to .py)."""
        project = tmp_path / "project"
        project.mkdir()

        finder = S0maFinder(project, strict=False)
        spec = finder._find_s0ma_spec("nonexistent", path=None)

        assert spec is None

    def test_finds_s0ma_with_parent_path(self, s0ma_project: Path) -> None:
        """S0maFinder discovers .s0ma via parent package path."""
        finder = S0maFinder(s0ma_project, strict=False)
        spec = finder._find_s0ma_spec(
            "hello_world", path=[str(s0ma_project)]
        )

        assert spec is not None
        assert spec.name == "hello_world"


# ---------------------------------------------------------------------------
# S0maDSLLoader transpilation tests
# ---------------------------------------------------------------------------


class TestDSLLoaderTranspilation:
    """Tests for S0maDSLLoader transpile + cache behavior."""

    def test_transpiles_s0ma_to_cache(self, s0ma_project: Path) -> None:
        """S0maDSLLoader transpiles a .s0ma file and writes cached .py."""
        s0ma_file = s0ma_project / "hello_world.s0ma"
        loader = S0maDSLLoader(
            s0ma_path=s0ma_file,
            project_root=s0ma_project,
            strict=False,
        )

        # Transpile by calling _transpile directly
        source_text = s0ma_file.read_text(encoding="utf-8")
        py_source = loader._transpile(source_text)

        assert "def greet" in py_source
        assert "@component" in py_source
        assert "register_module" in py_source

    def test_cache_directory_created(self, s0ma_project: Path) -> None:
        """After exec_module, __s0ma_cache__/ directory is created."""
        s0ma_file = s0ma_project / "hello_world.s0ma"
        loader = S0maDSLLoader(
            s0ma_path=s0ma_file,
            project_root=s0ma_project,
            strict=False,
        )

        # Create a module object and execute
        import types
        module = types.ModuleType("hello_world")
        module.__file__ = str(s0ma_file)

        # exec_module will fail on register_module call (no registry set up)
        # but the cache files should be created before that
        with contextlib.suppress(Exception):
            loader.exec_module(module)

        cache_dir = s0ma_project / "__s0ma_cache__"
        assert cache_dir.is_dir()
        assert (cache_dir / "hello_world.py").is_file()
        assert (cache_dir / "hello_world.hash").is_file()

    def test_cache_hit_skips_retranspile(self, s0ma_project: Path) -> None:
        """When cache hash matches source, transpilation is skipped."""
        s0ma_file = s0ma_project / "hello_world.s0ma"

        # Pre-populate cache
        cache_dir = s0ma_project / "__s0ma_cache__"
        cache_dir.mkdir()

        source_text = s0ma_file.read_text(encoding="utf-8")
        content_hash = hashlib.sha256(
            source_text.encode("utf-8")
        ).hexdigest()

        # Write a cache .py (doesn't need to be valid transpiler output)
        cached_py = "# Cached output\ndef greet(name): return f'Cached {name}'\n"
        (cache_dir / "hello_world.py").write_text(cached_py, encoding="utf-8")
        (cache_dir / "hello_world.hash").write_text(
            content_hash, encoding="utf-8"
        )

        loader = S0maDSLLoader(
            s0ma_path=s0ma_file,
            project_root=s0ma_project,
            strict=False,
        )

        import types
        module = types.ModuleType("hello_world")
        module.__file__ = str(s0ma_file)

        with contextlib.suppress(Exception):
            loader.exec_module(module)

        # Verify the cached version was used (not retranspiled)
        actual_py = (cache_dir / "hello_world.py").read_text(encoding="utf-8")
        assert actual_py == cached_py  # Not overwritten

    def test_cache_invalidation_on_change(self, s0ma_project: Path) -> None:
        """When source changes, the cache is invalidated and retranspiled."""
        s0ma_file = s0ma_project / "hello_world.s0ma"

        # Pre-populate cache with OLD content hash
        cache_dir = s0ma_project / "__s0ma_cache__"
        cache_dir.mkdir()

        old_hash = "0" * 64  # Definitely different from actual
        (cache_dir / "hello_world.py").write_text(
            "# Old cached output", encoding="utf-8"
        )
        (cache_dir / "hello_world.hash").write_text(
            old_hash, encoding="utf-8"
        )

        loader = S0maDSLLoader(
            s0ma_path=s0ma_file,
            project_root=s0ma_project,
            strict=False,
        )

        import types
        module = types.ModuleType("hello_world")
        module.__file__ = str(s0ma_file)

        with contextlib.suppress(Exception):
            loader.exec_module(module)

        # Verify the cache was refreshed (retranspiled)
        actual_py = (cache_dir / "hello_world.py").read_text(encoding="utf-8")
        assert "# Old cached output" not in actual_py
        assert "def greet" in actual_py


class TestDSLLoaderErrors:
    """Tests for S0maDSLLoader error handling."""

    def test_syntax_error_produces_import_error(self, tmp_path: Path) -> None:
        """A .s0ma file with parse errors raises ImportError at import time."""
        project = tmp_path / "project"
        project.mkdir()

        # Write invalid .s0ma file (nerve declared but no body)
        bad_s0ma = project / "broken.s0ma"
        bad_s0ma.write_text(INVALID_S0MA, encoding="utf-8")

        loader = S0maDSLLoader(
            s0ma_path=bad_s0ma,
            project_root=project,
            strict=False,
        )

        import types
        module = types.ModuleType("broken")
        module.__file__ = str(bad_s0ma)

        # Should raise ImportError wrapping the transpilation error
        with pytest.raises(ImportError, match="Transpilation failed"):
            loader.exec_module(module)


# ---------------------------------------------------------------------------
# Full integration: import hook + .s0ma file
# ---------------------------------------------------------------------------


class TestFullImportIntegration:
    """End-to-end tests using the installed import hook to import .s0ma files."""

    def test_s0ma_import_via_hook(self, s0ma_project: Path) -> None:
        """Install the hook, add project to sys.path, import a .s0ma module."""
        # Add project to sys.path so Python can find it
        sys.path.insert(0, str(s0ma_project))

        try:
            # Install the hook with the project root
            install_import_hook(
                s0ma_project,
                allowlist={"s0ma", "s0ma_dsl"},
                strict=False,
            )

            # Import should discover the .s0ma file and transpile it
            # Remove from sys.modules if previously cached
            sys.modules.pop("hello_world", None)

            import hello_world  # type: ignore[import-not-found]

            # The module should be loaded and functional
            assert hasattr(hello_world, "greet")
            result = hello_world.greet("World")
            assert result == "Hello, World!"

        finally:
            sys.path.remove(str(s0ma_project))
            sys.modules.pop("hello_world", None)

    def test_modification_triggers_retranspile(
        self, s0ma_project: Path
    ) -> None:
        """Modifying a .s0ma file and re-importing triggers retranspilation."""
        s0ma_file = s0ma_project / "hello_world.s0ma"
        sys.path.insert(0, str(s0ma_project))

        try:
            install_import_hook(
                s0ma_project,
                allowlist={"s0ma", "s0ma_dsl"},
                strict=False,
            )

            # First import
            sys.modules.pop("hello_world", None)
            import hello_world  # type: ignore[import-not-found]
            assert hello_world.greet("X") == "Hello, X!"

            # Modify the source
            s0ma_file.write_text(MODIFIED_S0MA, encoding="utf-8")

            # Re-import (need to clear module cache AND registry)
            sys.modules.pop("hello_world", None)
            reset_registry()
            import hello_world  # type: ignore[import-not-found]
            assert hello_world.greet("X") == "Greetings, X!"

        finally:
            sys.path.remove(str(s0ma_project))
            sys.modules.pop("hello_world", None)

    def test_syntax_error_at_import_time(self, tmp_path: Path) -> None:
        """A broken .s0ma file produces a clear error at import time."""
        project = tmp_path / "bad_project"
        project.mkdir()
        (project / "broken.s0ma").write_text(INVALID_S0MA, encoding="utf-8")

        sys.path.insert(0, str(project))

        try:
            install_import_hook(
                project,
                allowlist={"s0ma", "s0ma_dsl"},
                strict=False,
            )

            sys.modules.pop("broken", None)

            with pytest.raises(ImportError, match="Transpilation failed"):
                import broken  # type: ignore[import-not-found]  # noqa: F401

        finally:
            sys.path.remove(str(project))
            sys.modules.pop("broken", None)


class TestS0maPreferredOverPy:
    """When both .s0ma and .py exist, .s0ma is authoritative."""

    def test_s0ma_preferred_over_py(self, s0ma_project: Path) -> None:
        """When both hello_world.s0ma and hello_world.py exist,
        the .s0ma version is used."""
        # Write a .py file that would conflict
        py_file = s0ma_project / "hello_world.py"
        py_file.write_text(
            "def greet(name): return f'PY: {name}'\n",
            encoding="utf-8",
        )

        sys.path.insert(0, str(s0ma_project))

        try:
            install_import_hook(
                s0ma_project,
                allowlist={"s0ma", "s0ma_dsl"},
                strict=False,
            )

            sys.modules.pop("hello_world", None)
            import hello_world  # type: ignore[import-not-found]

            # Should use the .s0ma version, not the .py version
            result = hello_world.greet("Test")
            assert result == "Hello, Test!"
            assert "PY:" not in result

        finally:
            sys.path.remove(str(s0ma_project))
            sys.modules.pop("hello_world", None)


class TestCacheArtifacts:
    """Verify cache directory structure and content."""

    def test_cache_contains_py_and_hash(self, s0ma_project: Path) -> None:
        """After importing a .s0ma module, the cache contains .py and .hash."""
        sys.path.insert(0, str(s0ma_project))

        try:
            install_import_hook(
                s0ma_project,
                allowlist={"s0ma", "s0ma_dsl"},
                strict=False,
            )

            sys.modules.pop("hello_world", None)
            import hello_world  # type: ignore[import-not-found]  # noqa: F401

            cache_dir = s0ma_project / "__s0ma_cache__"
            assert cache_dir.is_dir()
            assert (cache_dir / "hello_world.py").is_file()
            assert (cache_dir / "hello_world.hash").is_file()

            # Verify hash content
            source = (s0ma_project / "hello_world.s0ma").read_text(
                encoding="utf-8"
            )
            expected_hash = hashlib.sha256(
                source.encode("utf-8")
            ).hexdigest()
            actual_hash = (cache_dir / "hello_world.hash").read_text(
                encoding="utf-8"
            ).strip()
            assert actual_hash == expected_hash

        finally:
            sys.path.remove(str(s0ma_project))
            sys.modules.pop("hello_world", None)
