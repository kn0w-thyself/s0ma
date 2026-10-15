"""Tests for the ``ModuleManifestEntry.role`` field and the
``roles=`` kwarg on :func:`s0ma.bootstrap.bootstrap_imports` (0.14.0
pre-Phase-2 PRE-2).

Together these let a single ``build.s0ma.json`` carry both production
source modules and test modules, with the runtime helper defaulting to
the source slice. Pre-0.14.0 manifests load with ``role="source"`` for
every entry so consumer projects don't see a behaviour change unless
they opt in.
"""

from __future__ import annotations

import json
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest
from s0ma.bootstrap import bootstrap_imports

from s0ma_dsl.codegen.build_manifest import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA,
    VALID_ROLES,
    ModuleManifestEntry,
    build_manifest,
    emit_manifest,
    load_manifest,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


# ---------------------------------------------------------------------------
# ModuleManifestEntry — role field
# ---------------------------------------------------------------------------


class TestRoleField:
    """The ``role`` field defaults to ``"source"`` and validates input."""

    def test_default_role_is_source(self) -> None:
        entry = _make_entry("alpha")
        assert entry.role == "source"

    def test_explicit_test_role_accepted(self) -> None:
        entry = _make_entry("alpha", role="test")
        assert entry.role == "test"

    def test_unknown_role_rejected(self) -> None:
        with pytest.raises(ValueError, match="role must be one of"):
            _make_entry("alpha", role="benchmarks")

    def test_valid_roles_constant(self) -> None:
        assert frozenset({"source", "test"}) == VALID_ROLES


# ---------------------------------------------------------------------------
# Manifest emit / load round-trip
# ---------------------------------------------------------------------------


class TestManifestRoundTrip:
    def test_role_round_trip_through_emit_load(self, tmp_path: Path) -> None:
        manifest = build_manifest(
            project_name="round-trip",
            build_dir=tmp_path,
            modules=[
                _make_entry("source_a", role="source"),
                _make_entry("test_a", role="test"),
            ],
            transpiler_version="0.14.0",
            built_at="2026-05-10T12:00:00Z",
        )
        emit_manifest(manifest, tmp_path)
        loaded = load_manifest(tmp_path)
        roles_by_name = {entry.name: entry.role for entry in loaded.modules}
        assert roles_by_name == {"source_a": "source", "test_a": "test"}

    def test_legacy_manifest_without_role_loads_with_source_default(
        self, tmp_path: Path,
    ) -> None:
        """Pre-PRE-2 manifests carry no ``role`` key — load defaults it."""
        legacy = {
            "schema": MANIFEST_SCHEMA,
            "project": "legacy",
            "build_dir": str(tmp_path),
            "transpiler_version": "0.13.0",
            "built_at": "2026-04-29T12:00:00Z",
            "modules": [
                _make_entry_dict("legacy_module"),  # no ``role`` key
            ],
            "topological_import_order": ["legacy_module"],
        }
        (tmp_path / MANIFEST_FILENAME).write_text(json.dumps(legacy))
        loaded = load_manifest(tmp_path)
        assert len(loaded.modules) == 1
        assert loaded.modules[0].role == "source"


# ---------------------------------------------------------------------------
# bootstrap_imports — roles filter
# ---------------------------------------------------------------------------


class TestBootstrapRolesFilter:
    """The ``roles=`` kwarg filters which entries get imported."""

    def test_default_roles_imports_source_only(
        self, build_dir_with_source_and_test: Path,
    ) -> None:
        imported = bootstrap_imports(build_dir_with_source_and_test)
        assert sorted(imported.keys()) == ["source_a"]

    def test_roles_test_only_imports_tests(
        self, build_dir_with_source_and_test: Path,
    ) -> None:
        imported = bootstrap_imports(
            build_dir_with_source_and_test, roles=("test",),
        )
        assert sorted(imported.keys()) == ["test_a"]

    def test_roles_source_and_test_imports_all(
        self, build_dir_with_source_and_test: Path,
    ) -> None:
        imported = bootstrap_imports(
            build_dir_with_source_and_test, roles=("source", "test"),
        )
        assert sorted(imported.keys()) == ["source_a", "test_a"]

    def test_empty_roles_imports_nothing(
        self, build_dir_with_source_and_test: Path,
    ) -> None:
        imported = bootstrap_imports(
            build_dir_with_source_and_test, roles=(),
        )
        assert imported == {}

    def test_unknown_role_raises_value_error(
        self, build_dir_with_source_and_test: Path,
    ) -> None:
        with pytest.raises(ValueError, match="must be a subset of"):
            bootstrap_imports(
                build_dir_with_source_and_test, roles=("source", "tool"),
            )

    def test_topological_order_preserved_after_role_filter(
        self, tmp_path: Path,
    ) -> None:
        """Filtering by role must preserve dependency-first ordering."""
        # Two source modules where source_b depends on source_a, plus
        # one test module that depends on both. Topological order is
        # therefore source_a, source_b, test_one. Filtering for
        # ``("source",)`` keeps source_a, source_b in that order.
        _write_module(tmp_path, "source_a", body='X = "alpha"\n')
        _write_module(
            tmp_path,
            "source_b",
            body='import source_a\nY = source_a.X + "_beta"\n',
        )
        _write_module(
            tmp_path,
            "test_one",
            body='import source_a\nimport source_b\nZ = source_b.Y\n',
        )
        manifest = build_manifest(
            project_name="topo-filter",
            build_dir=tmp_path,
            modules=[
                _make_entry("source_a", role="source"),
                _make_entry("source_b", role="source"),
                _make_entry("test_one", role="test"),
            ],
            transpiler_version="0.14.0",
            built_at="2026-05-10T12:00:00Z",
            topological_import_order=("source_a", "source_b", "test_one"),
        )
        emit_manifest(manifest, tmp_path)
        # Reset sys.modules pollution from prior tests in this file
        # (the helper test modules are imported by name; collisions
        # across sub-tests are an issue otherwise).
        for name in ("source_a", "source_b", "test_one"):
            sys.modules.pop(name, None)
        imported = bootstrap_imports(tmp_path, roles=("source",))
        assert list(imported.keys()) == ["source_a", "source_b"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def build_dir_with_source_and_test(tmp_path: Path) -> Generator[Path, None, None]:
    """Materialise a build directory holding one source and one test module."""
    _write_module(tmp_path, "source_a", body='VALUE = 42\n')
    _write_module(tmp_path, "test_a", body='RESULT = "ok"\n')
    manifest = build_manifest(
        project_name="role-filter",
        build_dir=tmp_path,
        modules=[
            _make_entry("source_a", role="source"),
            _make_entry("test_a", role="test"),
        ],
        transpiler_version="0.14.0",
        built_at="2026-05-10T12:00:00Z",
        topological_import_order=("source_a", "test_a"),
    )
    emit_manifest(manifest, tmp_path)

    # Make sure the modules we are about to import are not in sys.modules
    # already (a prior test might have imported them under a different
    # build dir and left a stale reference).
    for name in ("source_a", "test_a"):
        sys.modules.pop(name, None)

    yield tmp_path

    # Teardown: drop the imported modules so subsequent tests don't see
    # the wrong file backing them.
    for name in ("source_a", "test_a"):
        sys.modules.pop(name, None)
    # Drop the inserted sys.path entry so other tests don't accidentally
    # resolve modules of the same name to this temp dir.
    build_str = str(tmp_path)
    while build_str in sys.path:
        sys.path.remove(build_str)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(name: str, *, role: str = "source") -> ModuleManifestEntry:
    """Construct a ``ModuleManifestEntry`` with sensible test defaults."""
    return ModuleManifestEntry(
        name=name,
        source=f"/abs/path/{name}.s0ma",
        output=f"{name}.py",
        ir=f"{name}.s0ma.json",
        source_map=f"{name}.s0ma.map",
        source_hash=f"sha256:{'0' * 64}",
        output_hash=f"sha256:{'1' * 64}",
        role=role,
    )


def _make_entry_dict(name: str) -> dict[str, str]:
    """Pre-PRE-2 dict shape — no ``role`` key — for legacy load tests."""
    return {
        "name": name,
        "source": f"/abs/path/{name}.s0ma",
        "output": f"{name}.py",
        "ir": f"{name}.s0ma.json",
        "source_map": f"{name}.s0ma.map",
        "source_hash": f"sha256:{'0' * 64}",
        "output_hash": f"sha256:{'1' * 64}",
    }


def _write_module(build_dir: Path, name: str, *, body: str) -> None:
    """Write a stand-in transpiled module so ``importlib`` can load it."""
    (build_dir / f"{name}.py").write_text(textwrap.dedent(body))
    # The minimal flat-layout build dir needs an __init__ for ``import``
    # to find modules at the build dir root.
    init_path = build_dir / "__init__.py"
    if not init_path.exists():
        init_path.write_text("")
