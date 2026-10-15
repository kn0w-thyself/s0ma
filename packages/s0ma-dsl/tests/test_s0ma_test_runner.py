"""M7 (feedback 5–6, CRIT-3) — `s0ma test` project-aware runner.

Pins the post-M7 contract:

* ``s0ma test`` discovers the project, builds source + test roots to
  ``project.build_dir`` (M6a flat layout), and invokes pytest with
  ``PYTHONPATH=<build_dir>`` plus a ``-o python_files=...`` override
  that recognises both ``test_*.py`` and ``*_tests.py`` naming.
* Args after ``--`` reach pytest verbatim; argparse cannot consume
  them (the ``-o`` foot-gun documented in feedback-5.5 M01 is gone).
* The runner emits a friendly remediation when pytest is not
  importable in the active environment.

These tests use the ``tests/fixtures/cross_module_test_project/``
fixture: a minimal s0ma project with two source modules
(``calculator``, ``formatter``) and two test modules
(``calculator_tests`` — ``*_tests.s0ma`` naming convention,
``test_formatter`` — cross-module imports from ``calculator`` and
``formatter``). Both naming conventions and the cross-module import
path are exercised end-to-end.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, EXIT_USAGE_ERROR, S0maCLI

FIXTURE = (
    Path(__file__).parent / "fixtures" / "cross_module_test_project"
)


@pytest.fixture()
def staged_project(tmp_path: Path) -> Path:
    """Copy the fixture into ``tmp_path`` so the build dir lands there.

    ``s0ma test`` mutates ``project.build_dir`` and the in-tree fixture
    lives in the s0ma-dsl repo's tests/. Staging keeps the test
    hermetic and survives parallel pytest workers.
    """
    dst = tmp_path / "cross_module_test_project"
    shutil.copytree(FIXTURE, dst)
    return dst


def test_s0ma_test_runs_cross_module_tests(staged_project: Path) -> None:
    """End-to-end: cross-module imports resolve, all 4 tests pass.

    Acceptance criterion (M7): ``s0ma test`` discovers the project,
    builds ``src/sample_app`` (calculator + formatter) and ``tests``
    (calculator_tests + test_formatter) into the flat build dir, and
    pytest collects + runs every test against the build_dir on
    ``PYTHONPATH``. The CRIT-3 case — a test importing across
    modules (``test_formatter`` uses ``calculator.add`` and
    ``formatter.format_sum``) — must succeed without any
    per-project conftest hack.
    """
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_project),
        "test",
    ])
    assert rc == EXIT_SUCCESS, (
        "s0ma test should pass on the cross-module fixture; "
        "if this fails the CRIT-3 cross-module import path is broken."
    )


def test_s0ma_test_passes_args_through(staged_project: Path) -> None:
    """``s0ma test ... -- -k <filter>`` reaches pytest verbatim.

    Acceptance criterion (M7): args after ``--`` are not parsed by
    argparse — the ``-o``/``--output-dir`` foot-gun documented in
    feedback-5.5 M01 is gone. Filtering on a substring narrows the
    test selection to exactly the matching tests.
    """
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_project),
        "test",
        "--",
        "-k", "test_add_returns_integer_sum",
    ])
    # The single matching test passes — pytest exit 0 means the
    # filter actually narrowed collection (otherwise we'd see exit 5,
    # "no tests collected", or 0 with all four tests run).
    assert rc == EXIT_SUCCESS

    # Now confirm a definitely-non-matching filter produces exit 5
    # (no tests collected) — proof that pytest received the filter.
    rc_empty = cli.run([
        "--project-root", str(staged_project),
        "test",
        "--",
        "-k", "definitely_no_test_matches_this_string",
    ])
    # pytest's exit code 5 means "no tests collected" — the filter
    # made it through. Argparse would not have produced this code.
    assert rc_empty == 5


def test_s0ma_test_recognizes_tests_py_naming(staged_project: Path) -> None:
    """``*_tests.py`` files are picked up alongside ``test_*.py``.

    Acceptance criterion (M7, feedback-5.5 M01): pre-M7 pytest's
    default ``python_files = test_*.py`` glob silently ignored every
    file emitted by ``test_*.s0ma`` under the ``*_tests.py`` naming
    convention. M7 sets ``-o python_files=test_*.py *_tests.py`` so
    both conventions are collected.

    The fixture's ``calculator_tests.s0ma`` exercises this — it must
    produce ``calculator_tests.py`` in the build dir and pytest must
    run it. We verify by running with a ``-k`` filter that only
    matches a test inside ``calculator_tests.py``; if the file were
    not collected, pytest would exit with code 5
    ("no tests collected").
    """
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_project),
        "test",
        "--",
        "-k", "test_multiply_returns_integer_product",
    ])
    assert rc == EXIT_SUCCESS, (
        "tests in *_tests.py files must be collected and run "
        "(M7 python_files glob extension)."
    )

    # Verify the build dir actually contains a *_tests.py file —
    # structural check on the flat layout.
    build_dir = staged_project / "cross_module_test_project_build"
    tests_files = list(build_dir.glob("*_tests.py"))
    assert tests_files, (
        f"expected at least one *_tests.py under {build_dir}; "
        f"found: {[p.name for p in build_dir.iterdir()]}"
    )


def test_s0ma_test_emits_friendly_error_when_pytest_missing(
    staged_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Friendly preflight when pytest is not importable.

    Acceptance criterion (M7): exit 2 with a remediation pointing the
    user at ``pip install pytest``. Stubbed by patching
    ``importlib.util.find_spec`` so the runner sees pytest as
    unavailable without actually uninstalling it.
    """
    cli = S0maCLI()

    real_find_spec = __import__("importlib.util").util.find_spec

    def _no_pytest(name: str, *args: object, **kwargs: object) -> object:
        if name == "pytest":
            return None
        return real_find_spec(name, *args, **kwargs)

    with patch("importlib.util.find_spec", side_effect=_no_pytest):
        rc = cli.run([
            "--project-root", str(staged_project),
            "test",
        ])

    assert rc == EXIT_USAGE_ERROR
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "pytest" in combined.lower()
    assert "pip install pytest" in combined


def test_s0ma_test_pythonpath_contains_build_dir(
    staged_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pytest subprocess inherits ``PYTHONPATH`` rooted at build_dir.

    M7 contract: cross-module imports work because the build dir is
    on ``PYTHONPATH`` — without it, ``from calculator import add``
    inside a test body would fail with ImportError. We verify by
    intercepting ``subprocess.run`` and asserting on its env.
    """
    cli = S0maCLI()

    captured_env: dict[str, str] = {}
    captured_args: list[str] = []

    class _DummyResult:
        returncode = 0

    def fake_run(cmd: list[str], *, env: dict[str, str], check: bool) -> _DummyResult:
        captured_env.update(env)
        captured_args.extend(cmd)
        return _DummyResult()

    monkeypatch.setattr("subprocess.run", fake_run)

    rc = cli.run([
        "--project-root", str(staged_project),
        "test",
    ])
    assert rc == 0

    # PYTHONPATH must lead with build_dir
    pythonpath = captured_env.get("PYTHONPATH", "")
    build_dir = (staged_project / "cross_module_test_project_build").resolve()
    assert pythonpath.split(os.pathsep)[0] == str(build_dir), (
        f"expected PYTHONPATH to lead with {build_dir}; "
        f"got {pythonpath!r}"
    )

    # The python_files override must be in the pytest args.
    assert "-o" in captured_args
    o_idx = captured_args.index("-o")
    assert captured_args[o_idx + 1] == "python_files=test_*.py *_tests.py"

    # The pytest target is the build_dir.
    assert str(build_dir) in captured_args


def test_s0ma_test_no_source_tree_pollution(staged_project: Path) -> None:
    """No ``.py`` files appear in the source/test trees after a run.

    Acceptance criterion (M7): the build dir is the only output.
    The legacy ``--output-dir <test_dir>`` mode that wrote .py files
    next to .s0ma sources is gone.
    """
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_project),
        "test",
    ])
    assert rc == EXIT_SUCCESS

    # Source tree must contain no .py files.
    src_root = staged_project / "src"
    src_py_files = list(src_root.rglob("*.py"))
    assert src_py_files == [], (
        f"source tree must not be polluted; found: {src_py_files}"
    )

    # Test tree must contain no .py files either.
    test_root = staged_project / "tests"
    test_py_files = list(test_root.rglob("*.py"))
    assert test_py_files == [], (
        f"test tree must not be polluted; found: {test_py_files}"
    )


def test_s0ma_test_friendly_notice_when_no_test_roots(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When ``test_roots`` is empty, s0ma test prints a remediation.

    Acceptance criterion (M7): friendly preflight message guiding
    the user to add ``test_roots = ["tests"]`` to ``[tool.s0ma]``.
    """
    proj = tmp_path / "no_test_roots"
    proj.mkdir()
    (proj / "pyproject.toml").write_text(
        "[project]\nname = \"no_test_roots\"\n\n"
        "[tool.s0ma]\n"
        "source_roots = [\"src\"]\n"
        "test_roots = []\n"
        "build_dir = \"build\"\n"
        "bootstrap_files = []\n",
        encoding="utf-8",
    )

    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(proj),
        "test",
    ])
    assert rc == EXIT_USAGE_ERROR
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "test_roots" in combined
    assert "[tool.s0ma]" in combined
