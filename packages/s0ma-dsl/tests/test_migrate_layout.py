"""M6b (feedback 5–6, ADR-007) — `s0ma migrate-layout` invariants.

The plan's migration command brings legacy build trees forward in one
shot:

- legacy ``__s0ma_cache__/`` directories under the build dir or
  project dir are deleted;
- per-layer subdirectories (``presentation/``, ``application/``,
  ``domain/``, ``infrastructure/``) under the build dir are deleted;
- a fresh ``s0ma build`` runs, emitting the M6a flat layout and the
  M6b ``build.s0ma.json`` manifest;
- the command is *idempotent*: running it twice in a row produces the
  same result.

These tests stage the legacy artifacts in a copy of the
``legacy_layout_project`` fixture under ``tmp_path`` so the fixture
tree stays clean across test runs.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.codegen.build_manifest import MANIFEST_FILENAME, load_manifest

if TYPE_CHECKING:
    import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "legacy_layout_project"


def _stage_legacy_layout(tmp_path: Path) -> tuple[Path, Path]:
    """Copy the fixture and seed it with legacy artifacts.

    Returns ``(project_dir, build_dir)``. ``build_dir`` is the same
    location ``S0maProject.synthetic_fallback`` resolves to for a
    project rooted at ``project_dir`` — `<project_dir>/<name>_build`.
    """
    project_dir = tmp_path / "legacy_layout_project"
    shutil.copytree(FIXTURE, project_dir)
    build_dir = project_dir / f"{project_dir.name}_build"
    build_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1: a legacy __s0ma_cache__ under the build dir.
    cache_under_build = build_dir / "__s0ma_cache__"
    cache_under_build.mkdir(parents=True, exist_ok=True)
    (cache_under_build / "stale.py").write_text(
        "# legacy stale cached output\n", encoding="utf-8"
    )
    (cache_under_build / "stale.s0ma.json").write_text(
        '{"module": {"name": "stale"}}\n', encoding="utf-8"
    )

    # Stage 2: legacy per-layer subdirs with stale .py shadows.
    for layer in ("presentation", "application", "domain", "infrastructure"):
        layer_dir = build_dir / layer
        layer_dir.mkdir(parents=True, exist_ok=True)
        (layer_dir / "ghost.py").write_text(
            f"# legacy {layer}-layer shadow\n", encoding="utf-8"
        )

    # Stage 3: a __s0ma_cache__ under the project dir as well — pre-M6a
    # could anchor either place depending on how `s0ma build` was
    # invoked.
    cache_under_project = project_dir / "__s0ma_cache__"
    cache_under_project.mkdir(parents=True, exist_ok=True)
    (cache_under_project / "stale_src.py").write_text(
        "# legacy project-anchored cache\n", encoding="utf-8"
    )

    return project_dir, build_dir


# ---------------------------------------------------------------------------
# Acceptance — cleans legacy state
# ---------------------------------------------------------------------------


def test_migrate_layout_cleans_legacy_dirs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """``s0ma migrate-layout`` deletes legacy paths and rebuilds flat.

    Acceptance criterion (M6b): after a single invocation, no
    ``__s0ma_cache__/`` directories remain anywhere in the project or
    build tree, no legacy layer subdirectories remain under the build
    dir, and the build dir contains the M6a flat layout + M6b
    manifest.
    """
    project_dir, build_dir = _stage_legacy_layout(tmp_path)

    cli = S0maCLI()
    rc = cli.run([
        "migrate-layout", str(project_dir),
        "--mode", "dev",
    ])
    assert rc == EXIT_SUCCESS, "migrate-layout did not exit clean"

    # Legacy state is gone everywhere.
    assert not (build_dir / "__s0ma_cache__").exists()
    assert not (project_dir / "__s0ma_cache__").exists()
    for layer in ("presentation", "application", "domain", "infrastructure"):
        assert not (build_dir / layer).exists(), (
            f"legacy {layer}/ subdir was not cleaned"
        )

    # Flat layout regenerated, with the manifest.
    assert (build_dir / "__init__.py").is_file()
    assert (build_dir / MANIFEST_FILENAME).is_file()
    manifest = load_manifest(build_dir)
    assert {m.name for m in manifest.modules} == {"farewell", "greeter"}
    for entry in manifest.modules:
        assert (build_dir / entry.output).is_file()
        assert (build_dir / entry.ir).is_file()
        assert (build_dir / entry.source_map).is_file()

    # Summary line shape per the plan.
    out = capsys.readouterr().out
    assert "Migrated legacy_layout_project:" in out
    assert "removed" in out
    assert "emitted 2 module(s)" in out


def test_migrate_layout_idempotent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Running migrate-layout twice produces the same result.

    Acceptance criterion (M6b): the second pass finds nothing to clean
    and reports the no-op summary (`nothing to clean`). The build
    output content is byte-stable across the two runs (the manifest's
    ``built_at`` timestamp is allowed to differ — it is the only
    intentionally non-stable field).
    """
    project_dir, build_dir = _stage_legacy_layout(tmp_path)

    cli = S0maCLI()

    # Pass 1: cleans legacy artifacts.
    rc1 = cli.run(["migrate-layout", str(project_dir), "--mode", "dev"])
    assert rc1 == EXIT_SUCCESS
    out1 = capsys.readouterr().out
    assert "removed" in out1

    # Capture the manifest contents that resulted from pass 1.
    manifest1 = load_manifest(build_dir)
    py_bytes_1 = {
        entry.name: (build_dir / entry.output).read_bytes()
        for entry in manifest1.modules
    }

    # Pass 2: idempotent. No legacy paths exist, so the summary
    # reports the no-op shape.
    rc2 = cli.run(["migrate-layout", str(project_dir), "--mode", "dev"])
    assert rc2 == EXIT_SUCCESS
    out2 = capsys.readouterr().out
    assert "nothing to clean" in out2, (
        f"second pass should report no-op; got stdout: {out2!r}"
    )

    # The flat layout is unchanged on disk: every .py emitted by pass
    # 1 has byte-identical content after pass 2. (Only built_at on
    # the manifest is allowed to differ.)
    manifest2 = load_manifest(build_dir)
    assert {m.name for m in manifest2.modules} == {
        m.name for m in manifest1.modules
    }
    for entry in manifest2.modules:
        py_now = (build_dir / entry.output).read_bytes()
        assert py_now == py_bytes_1[entry.name], (
            f"{entry.name}.py drifted across idempotent migrate-layout passes"
        )


def test_migrate_layout_refuses_unknown_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Defensive: refuses to operate on a build dir lacking s0ma artifacts.

    The plan's constraint: ``s0ma migrate-layout`` must not delete a
    build dir that doesn't look like a s0ma build. Stage a
    *non-empty* build dir whose contents are decidedly not s0ma —
    no IR, no auto-emitted ``__init__.py`` marker, no legacy layer
    subdirs, no cache. The command should bail out with a
    remediation rather than blow it away.
    """
    project_dir = tmp_path / "legacy_layout_project"
    shutil.copytree(FIXTURE, project_dir)
    build_dir = project_dir / f"{project_dir.name}_build"
    build_dir.mkdir(parents=True, exist_ok=True)

    # A non-s0ma file the migration must not touch.
    sentinel = build_dir / "important_user_file.txt"
    sentinel.write_text("DO NOT DELETE", encoding="utf-8")
    sentinel_mtime = sentinel.stat().st_mtime_ns

    cli = S0maCLI()
    rc = cli.run(["migrate-layout", str(project_dir), "--mode", "dev"])

    # Refuses with a usage error.
    assert rc != EXIT_SUCCESS
    assert sentinel.read_text(encoding="utf-8") == "DO NOT DELETE"
    assert sentinel.stat().st_mtime_ns == sentinel_mtime
    err = capsys.readouterr().err
    assert "refusing to operate" in err
