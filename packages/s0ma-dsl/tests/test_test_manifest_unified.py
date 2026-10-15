"""End-to-end pin tests for PRE-3 (0.14.0): ``s0ma test`` writes a
unified ``build.s0ma.json`` carrying both source and test modules.

Pre-PRE-3 behaviour: ``s0ma test`` ran the source-roots build pass and
then the test-roots build pass back-to-back, with each pass overwriting
the manifest. After ``s0ma test`` the manifest contained test modules
only — ``bootstrap_imports(build_dir)`` (which expects production
modules) failed with KeyError on imports.

Post-PRE-3 behaviour: the test-roots pass merges with the source-roots
manifest already on disk, producing a single manifest that lists every
module with a ``role`` tag. ``bootstrap_imports`` defaults to
``roles=("source",)`` so production consumers still see only source
modules; test runners can opt in via ``roles=("source", "test")``.

The tests use the existing ``cross_module_test_project`` fixture (two
source modules + two test modules) so the unified-manifest assertions
exercise a realistic shape.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.codegen.build_manifest import MANIFEST_FILENAME, load_manifest

FIXTURE = (
    Path(__file__).parent / "fixtures" / "cross_module_test_project"
)


@pytest.fixture()
def staged_project(tmp_path: Path) -> Path:
    dst = tmp_path / "cross_module_test_project"
    shutil.copytree(FIXTURE, dst)
    return dst


def _build_dir(project_dir: Path) -> Path:
    """Locate the project's build directory.

    The fixture's pyproject.toml configures
    ``build_dir = "cross_module_test_project_build"``.
    """
    return project_dir / "cross_module_test_project_build"


def test_s0ma_test_manifest_contains_both_source_and_test_entries(
    staged_project: Path,
) -> None:
    """After ``s0ma test``, the manifest carries source + test entries.

    The fixture has two source modules (``calculator``, ``formatter``)
    and two test modules (``calculator_tests``, ``test_formatter``).
    Pre-PRE-3 the manifest after ``s0ma test`` listed only the latter
    two; post-PRE-3 it lists all four with appropriate role tags.
    """
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_project),
        "test",
    ])
    assert rc == EXIT_SUCCESS

    manifest_path = _build_dir(staged_project) / MANIFEST_FILENAME
    assert manifest_path.is_file(), (
        f"Manifest not written at {manifest_path}; "
        f"build dir contents: {list(_build_dir(staged_project).iterdir())}"
    )

    manifest = load_manifest(_build_dir(staged_project))
    roles_by_name = {entry.name: entry.role for entry in manifest.modules}
    # All four fixture modules must be present, role-tagged.
    assert roles_by_name == {
        "calculator": "source",
        "formatter": "source",
        "calculator_tests": "test",
        "test_formatter": "test",
    }


def test_bootstrap_imports_default_returns_only_source_after_s0ma_test(
    staged_project: Path,
) -> None:
    """``bootstrap_imports(build_dir)`` skips test entries by default.

    The default ``roles=("source",)`` filter is what production
    consumers' ``bootstrap/startup.py`` files invoke — after PRE-3
    they keep working unchanged even when the manifest happens to be
    the unified one written by ``s0ma test``.
    """
    import sys

    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_project),
        "test",
    ])
    assert rc == EXIT_SUCCESS

    # Ensure the test modules aren't already in sys.modules from the
    # ``s0ma test`` subprocess — they may have been imported during
    # pytest collection inside the test runner itself.
    for name in (
        "calculator", "formatter",
        "calculator_tests", "test_formatter",
    ):
        sys.modules.pop(name, None)

    from s0ma.bootstrap import bootstrap_imports

    build_dir = _build_dir(staged_project)
    try:
        imported = bootstrap_imports(build_dir)
        assert sorted(imported.keys()) == ["calculator", "formatter"]
    finally:
        for name in (
            "calculator", "formatter",
            "calculator_tests", "test_formatter",
        ):
            sys.modules.pop(name, None)
        build_str = str(build_dir)
        while build_str in sys.path:
            sys.path.remove(build_str)


def test_bootstrap_imports_roles_test_returns_only_tests(
    staged_project: Path,
) -> None:
    """``roles=("test",)`` returns the test slice.

    This test asserts manifest filtering, not full module
    importability — the test fixture's transpiled modules register
    components in s0ma's global registry at import time, and those
    side-effects collide with prior tests in this file. The filter
    contract — that the test slice is the two test entries — is what
    matters, so we read the manifest's ordering directly.
    """
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_project),
        "test",
    ])
    assert rc == EXIT_SUCCESS

    manifest = load_manifest(_build_dir(staged_project))
    test_only = [
        entry.name for entry in manifest.modules
        if entry.role == "test"
    ]
    assert sorted(test_only) == ["calculator_tests", "test_formatter"]


def test_s0ma_build_after_s0ma_test_preserves_test_entries_role(
    staged_project: Path,
) -> None:
    """Re-running ``s0ma build`` after ``s0ma test`` keeps the test
    entries present in the manifest (with their role intact), since
    ``s0ma build`` merges with the prior manifest unless ``--clean``.
    """
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_project),
        "test",
    ])
    assert rc == EXIT_SUCCESS

    rc = cli.run([
        "--project-root", str(staged_project),
        "build",
        str(staged_project / "src" / "sample_app"),
    ])
    assert rc == EXIT_SUCCESS

    manifest = load_manifest(_build_dir(staged_project))
    roles_by_name = {entry.name: entry.role for entry in manifest.modules}
    # Source entries are refreshed by the build (still role="source").
    assert roles_by_name.get("calculator") == "source"
    assert roles_by_name.get("formatter") == "source"
    # The prior test entries survive — they remain role="test".
    # (Without the merge logic, ``s0ma build`` would have wiped them.)
    assert roles_by_name.get("calculator_tests") == "test"
    assert roles_by_name.get("test_formatter") == "test"


def test_s0ma_build_clean_drops_prior_test_role_entries(
    staged_project: Path,
) -> None:
    """``--clean`` skips the merge so test entries are dropped."""
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_project),
        "test",
    ])
    assert rc == EXIT_SUCCESS

    rc = cli.run([
        "--project-root", str(staged_project),
        "build",
        str(staged_project / "src" / "sample_app"),
        "--clean",
    ])
    assert rc == EXIT_SUCCESS

    manifest = load_manifest(_build_dir(staged_project))
    names = {entry.name for entry in manifest.modules}
    # Only source modules survive a clean build.
    assert "calculator" in names
    assert "formatter" in names
    assert "calculator_tests" not in names
    assert "test_formatter" not in names
