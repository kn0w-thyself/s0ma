"""Tests for ``_discover_raw_python_tests`` (PRE-9, 0.14.0).

``s0ma test`` discovers raw ``.py`` test files under
``[tool.s0ma].test_roots`` when those files have no ``.s0ma`` sibling.
This lets Phase 2's integration smoke tests and lint linters — which
shell out to ``docker compose`` and walk file trees, neither of which
fit a ``.s0ma`` body — participate in the canonical ``s0ma test``
flow instead of needing a separate ``pytest`` invocation.

These tests pin the discovery rules:
- raw ``.py`` test files (matching pytest's default prefix/suffix) are
  discovered when no ``.s0ma`` sibling exists,
- ``.py`` files with a same-stem ``.s0ma`` sibling are NOT discovered
  (the .s0ma is the source of truth; the build emits the canonical
  .py into ``build_dir`` instead),
- helper files (no ``test_`` prefix), ``conftest.py``, and
  ``__init__.py`` are skipped,
- ``.s0ma.cache`` / ``__s0ma_cache__`` subtrees are excluded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from s0ma_dsl.cli.main import _discover_raw_python_tests

if TYPE_CHECKING:
    from pathlib import Path


class TestRawPyDiscovery:
    """The happy path: raw ``.py`` test files are discovered."""

    def test_raw_py_test_without_s0ma_sibling_discovered(
        self, tmp_path: Path,
    ) -> None:
        test_root = tmp_path / "tests"
        test_root.mkdir()
        raw_test = test_root / "test_raw_smoke.py"
        raw_test.write_text("def test_smoke():\n    assert True\n")

        discovered = _discover_raw_python_tests([test_root])

        assert raw_test.resolve() in discovered

    def test_underscore_test_suffix_discovered(self, tmp_path: Path) -> None:
        test_root = tmp_path / "tests"
        test_root.mkdir()
        raw_test = test_root / "smoke_test.py"
        raw_test.write_text("def test_smoke():\n    assert True\n")

        discovered = _discover_raw_python_tests([test_root])

        assert raw_test.resolve() in discovered

    def test_underscore_tests_suffix_discovered(self, tmp_path: Path) -> None:
        test_root = tmp_path / "tests"
        test_root.mkdir()
        raw_test = test_root / "smoke_tests.py"
        raw_test.write_text("def test_smoke():\n    assert True\n")

        discovered = _discover_raw_python_tests([test_root])

        assert raw_test.resolve() in discovered

    def test_nested_raw_py_test_discovered(self, tmp_path: Path) -> None:
        test_root = tmp_path / "tests"
        nested = test_root / "integration"
        nested.mkdir(parents=True)
        raw_test = nested / "test_local_smoke.py"
        raw_test.write_text("def test_smoke():\n    assert True\n")

        discovered = _discover_raw_python_tests([test_root])

        assert raw_test.resolve() in discovered


class TestS0maSiblingExcludes:
    """``.py`` files with a same-stem ``.s0ma`` sibling are not double-collected."""

    def test_py_with_s0ma_sibling_not_collected(self, tmp_path: Path) -> None:
        test_root = tmp_path / "tests"
        test_root.mkdir()
        # Simulate the unusual layout: a .py file living next to a
        # .s0ma source. The build emits to build_dir/, so this .py is
        # something the user (or a stale build) put here directly.
        # Either way, the .s0ma's existence means "do not raw-collect".
        py_path = test_root / "test_compiled.py"
        s0ma_path = test_root / "test_compiled.s0ma"
        py_path.write_text("def test_compiled():\n    assert True\n")
        s0ma_path.write_text("module test_compiled\n    layer: APPLICATION\n")

        discovered = _discover_raw_python_tests([test_root])

        assert py_path.resolve() not in discovered


class TestNonTestFilesSkipped:
    """Helper modules, conftests, and __init__ are not discovered."""

    def test_helper_without_test_prefix_skipped(self, tmp_path: Path) -> None:
        test_root = tmp_path / "tests"
        test_root.mkdir()
        helper = test_root / "helpers.py"
        helper.write_text("def make_fixture():\n    return 42\n")

        discovered = _discover_raw_python_tests([test_root])

        assert helper.resolve() not in discovered

    def test_conftest_skipped(self, tmp_path: Path) -> None:
        test_root = tmp_path / "tests"
        test_root.mkdir()
        conftest = test_root / "conftest.py"
        conftest.write_text("import pytest\n")

        discovered = _discover_raw_python_tests([test_root])

        assert conftest.resolve() not in discovered

    def test_init_py_skipped(self, tmp_path: Path) -> None:
        test_root = tmp_path / "tests"
        test_root.mkdir()
        init = test_root / "__init__.py"
        init.write_text("")

        discovered = _discover_raw_python_tests([test_root])

        assert init.resolve() not in discovered


class TestCacheSubtreesExcluded:
    """``.s0ma.cache`` and ``__s0ma_cache__`` subtrees are not walked."""

    def test_dotted_cache_subtree_excluded(self, tmp_path: Path) -> None:
        test_root = tmp_path / "tests"
        cache = test_root / ".s0ma.cache"
        cache.mkdir(parents=True)
        cached_py = cache / "test_cached.py"
        cached_py.write_text("def test_cached():\n    assert True\n")

        discovered = _discover_raw_python_tests([test_root])

        assert cached_py.resolve() not in discovered

    def test_underscore_cache_subtree_excluded(self, tmp_path: Path) -> None:
        test_root = tmp_path / "tests"
        cache = test_root / "__s0ma_cache__"
        cache.mkdir(parents=True)
        cached_py = cache / "test_cached.py"
        cached_py.write_text("def test_cached():\n    assert True\n")

        discovered = _discover_raw_python_tests([test_root])

        assert cached_py.resolve() not in discovered


class TestMultipleRoots:
    """Multiple roots all contribute discovered files."""

    def test_two_roots_both_searched(self, tmp_path: Path) -> None:
        root_a = tmp_path / "tests_a"
        root_b = tmp_path / "tests_b"
        root_a.mkdir()
        root_b.mkdir()
        test_a = root_a / "test_smoke_a.py"
        test_b = root_b / "test_smoke_b.py"
        test_a.write_text("def test_a():\n    assert True\n")
        test_b.write_text("def test_b():\n    assert True\n")

        discovered = _discover_raw_python_tests([root_a, root_b])

        assert test_a.resolve() in discovered
        assert test_b.resolve() in discovered

    def test_nonexistent_root_silently_skipped(self, tmp_path: Path) -> None:
        existing = tmp_path / "tests"
        existing.mkdir()
        test = existing / "test_smoke.py"
        test.write_text("def test_smoke():\n    assert True\n")
        missing = tmp_path / "does_not_exist"

        discovered = _discover_raw_python_tests([missing, existing])

        assert test.resolve() in discovered
        assert len(discovered) == 1

    def test_empty_root_list_returns_empty(self) -> None:
        assert _discover_raw_python_tests([]) == []
