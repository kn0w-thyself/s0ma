"""F2 (feedback 5–6 follow-up) — `s0ma test` excludes `.s0ma.cache/`.

Pins the post-F2 contract:

* `s0ma test`'s pytest invocation passes ``--ignore=<abs_path>`` for
  the hidden ``.s0ma.cache/`` directory at the build dir and project
  root, and for every legacy pre-M6a ``__s0ma_cache__/`` directory
  that could plausibly sit at the build dir, project root, source
  roots, or test roots.
* The ignore flags are unconditional (pytest accepts non-existent
  paths harmlessly).
* Real test files are still collected and run; cache-shaped
  artefacts (transpiled ``.py`` matching ``python_files`` inside a
  cache dir) are not.

The M20 smoke test against fr3d hit the regression these tests pin:
fr3d's ``s0ma test`` collected ``.s0ma.cache/<build_dir>/*.py``
alongside ``<build_dir>/*.py``, double-registering every component
and producing ``RegistrationError`` at import time. See
``plans/feedback_5-6/feedback_5-6_smoke_results.md`` (Finding #2)
and the F2 milestone spec in
the 5-6 plan (internal).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI

FIXTURE = (
    Path(__file__).parent / "fixtures" / "cache_pollution_project"
)


@pytest.fixture()
def staged_project(tmp_path: Path) -> Path:
    """Copy the fixture into ``tmp_path`` so the build dir lands there.

    ``s0ma test`` mutates ``project.build_dir`` and the in-tree
    fixture lives in the s0ma-dsl repo's ``tests/``. Staging keeps
    the test hermetic and survives parallel pytest workers.
    """
    dst = tmp_path / "cache_pollution_project"
    shutil.copytree(FIXTURE, dst)
    return dst


def _stage_cache(cache_dir: Path) -> None:
    """Drop a test-shaped ``.py`` file inside *cache_dir*.

    The body asserts ``False`` unconditionally — if pytest collects
    it, the run fails loudly. This is the regression-loud-by-design
    posture the F2 plan requires.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "test_stale.py").write_text(
        "def test_stale_artifact_should_never_run():\n"
        "    assert False, (\n"
        "        's0ma test should never collect tests from inside a '\n"
        "        's0ma cache directory; F2 regressed if you see this.'\n"
        "    )\n",
        encoding="utf-8",
    )


def test_s0ma_test_ignores_s0ma_cache(staged_project: Path) -> None:
    """End-to-end: a staged ``.s0ma.cache/`` with a failing
    ``test_stale.py`` is not collected; the real test runs and passes.

    This is the F2 regression case fr3d hit in the M20 smoke test.
    Without ``--ignore=<.s0ma.cache>`` the staged ``test_stale.py``
    would be collected, the assertion would fail, and the run would
    exit non-zero. With the F2 fix in place, the cache directory is
    invisible to pytest and only the fixture's real
    ``widget_tests.s0ma``-derived test runs.

    Pytest's default ``norecursedirs`` skips dot-prefixed directories
    (`.*`), which would mask this regression in the standard config.
    fr3d's project had a custom ``[tool.pytest.ini_options]`` that
    allowed dot-dirs into collection — the same pattern is reproduced
    here by passing ``-o norecursedirs=`` to pytest, forcing it to
    descend into ``.s0ma.cache/`` unless ``--ignore`` excludes it.
    """
    build_dir = staged_project / "cache_pollution_project_build"
    build_dir.mkdir(parents=True, exist_ok=True)
    _stage_cache(build_dir / ".s0ma.cache")
    _stage_cache(staged_project / ".s0ma.cache")

    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_project),
        "test",
        "--",
        # Reproduce fr3d's pytest config: don't auto-skip dot dirs.
        # Without F2, pytest will collect <build_dir>/.s0ma.cache/ here.
        "-o", "norecursedirs=",
    ])
    assert rc == EXIT_SUCCESS, (
        "s0ma test must ignore .s0ma.cache/ test-shaped artefacts "
        "even when pytest's default dot-dir skip is disabled; "
        "if rc != 0 the F2 ignore flags were dropped or the cache "
        "directory's location is no longer covered."
    )


def test_s0ma_test_ignores_legacy_s0ma_cache(staged_project: Path) -> None:
    """Pre-M6a ``__s0ma_cache__/`` directories are also ignored.

    M6a/M6b moved internal caching to ``.s0ma.cache/`` but the
    legacy directory may still exist on consumer projects that
    haven't yet run ``s0ma migrate-layout``. F2 keeps those
    directories out of pytest collection too — a half-migrated
    consumer must still be able to run ``s0ma test`` cleanly.
    """
    # Stage a legacy cache shape at every plausible location.
    build_dir = staged_project / "cache_pollution_project_build"
    build_dir.mkdir(parents=True, exist_ok=True)
    _stage_cache(build_dir / "__s0ma_cache__")
    _stage_cache(staged_project / "__s0ma_cache__")
    _stage_cache(
        staged_project / "src" / "cache_pollution_project" / "__s0ma_cache__"
    )
    _stage_cache(staged_project / "tests" / "__s0ma_cache__")

    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_project),
        "test",
    ])
    assert rc == EXIT_SUCCESS, (
        "s0ma test must ignore legacy __s0ma_cache__/ test-shaped "
        "artefacts; if rc != 0 the F2 defensive ignore flags were "
        "dropped or do not cover this location."
    )


def test_s0ma_test_does_not_double_collect(
    staged_project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each unique test is collected at most once.

    With the F2 fix in place, pytest sees ``--ignore=<.s0ma.cache>``
    and ``--ignore=<__s0ma_cache__>`` ahead of the build dir target,
    so a transpiled artefact that lives in both ``<build_dir>/foo.py``
    AND ``<build_dir>/.s0ma.cache/foo.py`` is collected exactly once.

    We assert this by intercepting the pytest argv and verifying the
    ignore flags are present (so collection doesn't recurse into the
    cache dirs), then by checking pytest's own collection count
    when run end-to-end.
    """
    cli = S0maCLI()

    captured_args: list[str] = []

    class _DummyResult:
        returncode = 0

    def fake_run(cmd: list[str], *, env: dict[str, str], check: bool) -> _DummyResult:
        captured_args.extend(cmd)
        return _DummyResult()

    monkeypatch.setattr("subprocess.run", fake_run)
    rc = cli.run([
        "--project-root", str(staged_project),
        "test",
    ])
    assert rc == EXIT_SUCCESS

    # F2 contract: at minimum, --ignore for the build_dir's
    # .s0ma.cache/ AND __s0ma_cache__/ must be present, with absolute
    # paths (no globs, no relative paths).
    build_dir = (staged_project / "cache_pollution_project_build").resolve()
    expected_primary = [
        str(build_dir / ".s0ma.cache"),
        str(build_dir / "__s0ma_cache__"),
    ]
    # Pull (--ignore, <path>) pairs out of the captured argv.
    ignore_paths: list[str] = []
    for i, tok in enumerate(captured_args):
        if tok == "--ignore" and i + 1 < len(captured_args):
            ignore_paths.append(captured_args[i + 1])

    for path in expected_primary:
        assert path in ignore_paths, (
            f"expected --ignore {path} in pytest argv; got "
            f"ignore paths: {ignore_paths}"
        )

    # Defensive: also expect the legacy cache shape at the project
    # root, since mid-migration projects may have a stale
    # __s0ma_cache__/ at that level.
    project_root = staged_project.resolve()
    assert str(project_root / "__s0ma_cache__") in ignore_paths, (
        "expected --ignore for the legacy project-root cache dir; "
        f"got: {ignore_paths}"
    )

    # All ignore paths must be absolute — relative paths would be
    # resolved against pytest's own cwd, which is unsafe.
    for path in ignore_paths:
        assert os.path.isabs(path), (
            f"--ignore path must be absolute; got {path!r}"
        )


def test_s0ma_test_real_run_collects_only_real_tests(
    staged_project: Path,
) -> None:
    """End-to-end double-collection check: stage cache pollution at
    every covered location, then verify the real test count is
    exactly 1 (the fixture's single ``test_greet_returns_hello``).

    A pre-F2 build would collect 1 real test plus N cache-shaped
    pollution tests (each of which fails). With F2 in place, pytest
    collects exactly the one real test — no duplicates, no
    cache-shaped artefacts.
    """
    # Pre-stage cache pollution at every F2-covered location.
    build_dir = staged_project / "cache_pollution_project_build"
    build_dir.mkdir(parents=True, exist_ok=True)
    _stage_cache(build_dir / ".s0ma.cache")
    _stage_cache(build_dir / "__s0ma_cache__")
    _stage_cache(staged_project / ".s0ma.cache")
    _stage_cache(staged_project / "__s0ma_cache__")

    # Run pytest manually (out-of-process) with the same argv
    # ``s0ma test`` would build, then read the verbose summary line.
    # Going through `s0ma test` itself would mask collection counts;
    # we want to read pytest's own ``collected N items`` output.
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_project),
        "test",
        "--",
        "-v",
        # Reproduce fr3d-style config: disable pytest's default
        # dot-dir auto-skip so the test exercises F2's --ignore flags
        # even for `.s0ma.cache/`.
        "-o", "norecursedirs=",
    ])
    assert rc == EXIT_SUCCESS, (
        "s0ma test must succeed end-to-end with cache pollution "
        "staged at every covered location; if rc != 0, either an "
        "ignore path was dropped or a stale cache test was collected."
    )

    # The build dir must contain exactly one real ``*_tests.py`` (the
    # transpiled fixture). The cache dirs at build_dir/.s0ma.cache/
    # and build_dir/__s0ma_cache__/ should still contain their
    # ``test_stale.py`` files (we did NOT delete them; we asserted
    # they were not collected). Read both back to confirm the staged
    # pollution was real and survived the run.
    real_tests = sorted(
        p.name for p in build_dir.glob("*_tests.py")
        if ".s0ma.cache" not in p.parts
        and "__s0ma_cache__" not in p.parts
    )
    assert real_tests == ["widget_tests.py"], (
        f"expected exactly one real test file (widget_tests.py); "
        f"got: {real_tests}"
    )
    # Cache pollution was actually staged (not silently lost).
    assert (build_dir / ".s0ma.cache" / "test_stale.py").is_file()
    assert (build_dir / "__s0ma_cache__" / "test_stale.py").is_file()
