"""Tests for PRE-6 (0.14.0): ``s0ma build`` prunes orphan artefacts.

After a build that renames or removes a ``.s0ma`` source, the prior
build's emitted ``.py`` / ``.s0ma.json`` / ``.s0ma.map`` triples
linger in ``<build_dir>``. ``s0ma verify`` / ``s0ma inspect`` then
report stale state, and ``bootstrap_imports`` may pick up the orphan
``.py`` if its module name happens to match something on
``sys.path``.

The prune helper at module scope (``_prune_orphan_artefacts``) walks
the build dir, identifies ``<name>.py`` files whose module is no
longer in the manifest's known names, and — only when sibling
``<name>.s0ma.json`` and ``<name>.s0ma.map`` are also present — deletes
the triple. Hand-written ``.py`` files without the sibling artefacts
are never pruned.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from s0ma_dsl.cli.main import _prune_orphan_artefacts

if TYPE_CHECKING:
    from pathlib import Path


def _write_triple(build_dir: Path, name: str) -> None:
    """Materialise the canonical s0ma-emitted triple for *name*."""
    (build_dir / f"{name}.py").write_text("# transpiled\n")
    (build_dir / f"{name}.s0ma.json").write_text("{}\n")
    (build_dir / f"{name}.s0ma.map").write_text("{}\n")


class TestOrphanTriplePrune:
    """Full triples whose name is not in the manifest are pruned."""

    def test_orphan_full_triple_pruned(self, tmp_path: Path) -> None:
        _write_triple(tmp_path, "stale")
        pruned = _prune_orphan_artefacts(tmp_path, known_module_names=set())
        assert [p.name for p in pruned] == ["stale.py"]
        assert not (tmp_path / "stale.py").exists()
        assert not (tmp_path / "stale.s0ma.json").exists()
        assert not (tmp_path / "stale.s0ma.map").exists()

    def test_known_triple_kept(self, tmp_path: Path) -> None:
        _write_triple(tmp_path, "alive")
        pruned = _prune_orphan_artefacts(
            tmp_path, known_module_names={"alive"},
        )
        assert pruned == []
        assert (tmp_path / "alive.py").exists()


class TestSafetyPredicate:
    """Hand-written ``.py`` without sibling artefacts is never pruned."""

    def test_orphan_py_without_ir_sibling_kept(self, tmp_path: Path) -> None:
        py = tmp_path / "manual.py"
        py.write_text("# hand-written\n")
        # Map exists but no IR — still not a complete triple.
        (tmp_path / "manual.s0ma.map").write_text("{}\n")
        pruned = _prune_orphan_artefacts(tmp_path, known_module_names=set())
        assert pruned == []
        assert py.exists()

    def test_orphan_py_without_map_sibling_kept(self, tmp_path: Path) -> None:
        py = tmp_path / "manual.py"
        py.write_text("# hand-written\n")
        (tmp_path / "manual.s0ma.json").write_text("{}\n")
        pruned = _prune_orphan_artefacts(tmp_path, known_module_names=set())
        assert pruned == []
        assert py.exists()

    def test_orphan_py_without_any_siblings_kept(self, tmp_path: Path) -> None:
        py = tmp_path / "standalone.py"
        py.write_text("# hand-written\n")
        pruned = _prune_orphan_artefacts(tmp_path, known_module_names=set())
        assert pruned == []
        assert py.exists()


class TestSpecialNames:
    """``__init__.py`` and the manifest file are never matched."""

    def test_init_py_never_pruned(self, tmp_path: Path) -> None:
        init_py = tmp_path / "__init__.py"
        init_py.write_text("")
        pruned = _prune_orphan_artefacts(tmp_path, known_module_names=set())
        assert pruned == []
        assert init_py.exists()

    def test_manifest_file_not_matched(self, tmp_path: Path) -> None:
        # ``build.s0ma.json`` exists but no ``.py`` of that name —
        # the manifest stays put even on an otherwise empty build.
        (tmp_path / "build.s0ma.json").write_text("{}\n")
        pruned = _prune_orphan_artefacts(tmp_path, known_module_names=set())
        assert pruned == []
        assert (tmp_path / "build.s0ma.json").exists()


class TestEdgeCases:
    """Empty / nonexistent build dirs are no-ops."""

    def test_nonexistent_build_dir(self, tmp_path: Path) -> None:
        pruned = _prune_orphan_artefacts(
            tmp_path / "does_not_exist", known_module_names=set(),
        )
        assert pruned == []

    def test_empty_build_dir(self, tmp_path: Path) -> None:
        pruned = _prune_orphan_artefacts(tmp_path, known_module_names=set())
        assert pruned == []


class TestMixedScenario:
    """Mix of orphans, kept modules, and hand-written ``.py``."""

    def test_only_orphan_triples_pruned(self, tmp_path: Path) -> None:
        _write_triple(tmp_path, "alpha")     # kept (in known)
        _write_triple(tmp_path, "beta")      # orphan triple (pruned)
        _write_triple(tmp_path, "gamma")     # orphan triple (pruned)
        # Hand-written file with no .py siblings.
        (tmp_path / "manual.py").write_text("# hand-written\n")
        # __init__.py
        (tmp_path / "__init__.py").write_text("")

        pruned = _prune_orphan_artefacts(
            tmp_path, known_module_names={"alpha"},
        )
        # Pruned exactly beta and gamma, in alphabetical order.
        assert sorted(p.name for p in pruned) == ["beta.py", "gamma.py"]
        # Kept: alpha triple, manual.py, __init__.py.
        assert (tmp_path / "alpha.py").exists()
        assert (tmp_path / "alpha.s0ma.json").exists()
        assert (tmp_path / "alpha.s0ma.map").exists()
        assert (tmp_path / "manual.py").exists()
        assert (tmp_path / "__init__.py").exists()
        # Pruned beta + gamma: triples gone.
        assert not (tmp_path / "beta.py").exists()
        assert not (tmp_path / "beta.s0ma.json").exists()
        assert not (tmp_path / "beta.s0ma.map").exists()
        assert not (tmp_path / "gamma.py").exists()
