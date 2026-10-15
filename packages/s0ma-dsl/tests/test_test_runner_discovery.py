"""M15 (feedback 5–6) — test-runner discovery: drop ``pytest`` from ``requires:``.

Pins the post-M15 contract:

* The runner identity is a project-level property declared once via
  ``[tool.s0ma].test_runner`` (default ``"pytest"``). The transpiler uses
  this to know what runner-specific stubs to emit; today pytest needs
  none — test functions are auto-discovered by name.
* A test module whose body has no ``pytest.<symbol>`` reference may omit
  ``pytest`` from ``requires:``. ``s0ma check --mode strict`` must stay
  clean for such a module — no ``VESTIGIAL_IMPORT`` papercut.
* A test module whose body uses ``pytest.raises`` (or any other
  ``pytest.<symbol>``) must still list ``pytest`` in ``requires:``. The
  current ``VESTIGIAL_IMPORT`` semantics are preserved: imported-but-unused
  fires; used-but-imported is clean.
* An unsupported runner value (``[tool.s0ma].test_runner = "nose"``)
  produces a friendly ``ValueError`` at project-discovery time naming
  the supported set and the remediation. No new error code is added —
  the project-discovery error path is the right home for runner-name
  validation.

These tests use the M15 fixture
``tests/fixtures/test_runner_pytest/`` — a minimal s0ma project with one
source module (``arithmetic``) and two test modules: ``arithmetic_tests``
(no body-level pytest reference, no ``pytest`` in ``requires:``) and
``divide_tests`` (uses ``pytest.raises``, lists ``pytest`` in
``requires:``).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from textwrap import dedent

import pytest

from s0ma_dsl import S0maProject
from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.project import (
    DEFAULT_TEST_RUNNER,
    SUPPORTED_TEST_RUNNERS,
)

FIXTURE = Path(__file__).parent / "fixtures" / "test_runner_pytest"


# ---------------------------------------------------------------------------
# Project-model: test_runner field
# ---------------------------------------------------------------------------


def test_test_runner_defaults_to_pytest(tmp_path: Path) -> None:
    """Omitting ``test_runner`` falls back to the canonical default.

    The default is the only runner supported in this version; an author
    who never types the key gets the same behaviour as one who explicitly
    pins ``test_runner = "pytest"``.
    """
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(dedent("""
        [project]
        name = "demo"
        version = "0.0.1"

        [tool.s0ma]
        source_roots = ["src"]
    """).lstrip())

    project = S0maProject.discover(tmp_path)

    assert project.test_runner == DEFAULT_TEST_RUNNER == "pytest"
    assert project.test_runner in SUPPORTED_TEST_RUNNERS


def test_test_runner_pytest_explicit_is_accepted(tmp_path: Path) -> None:
    """An explicit ``test_runner = "pytest"`` parses without warnings."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(dedent("""
        [project]
        name = "demo"
        version = "0.0.1"

        [tool.s0ma]
        source_roots = ["src"]
        test_runner = "pytest"
    """).lstrip())

    project = S0maProject.discover(tmp_path)

    assert project.test_runner == "pytest"
    assert project.warnings == ()


def test_synthetic_fallback_uses_default_runner(tmp_path: Path) -> None:
    """Legacy-mode (no [tool.s0ma]) projects get the default runner."""
    project = S0maProject.synthetic_fallback(tmp_path)

    assert project.test_runner == DEFAULT_TEST_RUNNER


# ---------------------------------------------------------------------------
# Validation: unsupported runner
# ---------------------------------------------------------------------------


def test_unknown_test_runner_errors(tmp_path: Path) -> None:
    """``test_runner = "nose"`` errors at project-discovery time.

    Acceptance criterion (M15): a friendly error names the supported set
    and the remediation; no new error code is introduced — the existing
    project-discovery error path handles runner-name validation. This
    pins both the message shape and the surface (``ValueError`` from
    ``S0maProject.discover``).
    """
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(dedent("""
        [project]
        name = "demo"
        version = "0.0.1"

        [tool.s0ma]
        source_roots = ["src"]
        test_runner = "nose"
    """).lstrip())

    with pytest.raises(ValueError) as excinfo:
        S0maProject.discover(tmp_path)

    msg = str(excinfo.value)
    assert "test_runner" in msg
    assert "'nose'" in msg
    assert "'pytest'" in msg
    # Remediation must point the author at the fix.
    assert "pyproject.toml" in msg


def test_test_runner_must_be_string(tmp_path: Path) -> None:
    """Non-string ``test_runner`` is a TOML-shape error, not a runner error."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(dedent("""
        [project]
        name = "demo"
        version = "0.0.1"

        [tool.s0ma]
        source_roots = ["src"]
        test_runner = 42
    """).lstrip())

    with pytest.raises(ValueError) as excinfo:
        S0maProject.discover(tmp_path)

    msg = str(excinfo.value)
    assert "test_runner" in msg
    assert "string" in msg


# ---------------------------------------------------------------------------
# End-to-end: build + run on the fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def staged_runner_project(tmp_path: Path) -> Path:
    """Stage the fixture into ``tmp_path`` so the build dir lands there.

    ``s0ma test`` writes to ``project.build_dir``. Staging keeps the
    test hermetic and survives parallel pytest workers; the in-tree
    fixture remains read-only.
    """
    dst = tmp_path / "test_runner_pytest"
    shutil.copytree(FIXTURE, dst)
    return dst


def test_test_module_without_pytest_requires_works(
    staged_runner_project: Path,
) -> None:
    """Test module that doesn't reference ``pytest.<symbol>`` and omits
    ``pytest`` from ``requires:`` builds clean and runs under ``s0ma test``.

    Acceptance criterion (M15): the recurring fr3d MS 16/18 papercut —
    "strip pytest from requires: to silence VESTIGIAL_IMPORT" — is gone.
    The runner-discovery semantics make the omission valid by default.
    """
    cli = S0maCLI()

    # Strict check must stay clean: no VESTIGIAL_IMPORT, no missing-import
    # cascade.
    rc_check = cli.run([
        "--project-root", str(staged_runner_project),
        "check", str(staged_runner_project),
        "--mode", "strict",
    ])
    assert rc_check == EXIT_SUCCESS, (
        "s0ma check --mode strict must stay clean on a test module "
        "that omits pytest from requires: when the body has no "
        "pytest.<symbol> reference."
    )

    # End-to-end: build + run. Pytest discovers test_* by name; no
    # import pytest is needed in the generated .py for this module.
    rc_test = cli.run([
        "--project-root", str(staged_runner_project),
        "test",
        "--",
        "-k", "test_add_returns_integer_sum",
    ])
    assert rc_test == EXIT_SUCCESS, (
        "s0ma test must run a test whose .s0ma module has no pytest.* "
        "references and no pytest in requires:."
    )


def test_test_module_using_pytest_raises_still_requires_it(
    staged_runner_project: Path,
) -> None:
    """A test body that uses ``pytest.raises`` still requires ``pytest``
    in ``requires:`` — the existing VESTIGIAL_IMPORT contract is preserved.

    Acceptance criterion (M15): "Body-level use of `pytest.<symbol>`
    requires `pytest` in `requires:`." This test pins both directions:

    1. The fixture's ``divide_tests.s0ma`` declares ``requires: [pytest]``
       and uses ``pytest.raises`` — strict check passes, s0ma test runs.
    2. Stripping ``requires: [pytest]`` while keeping the body usage
       reproduces a build-time failure (the generated .py has no
       ``import pytest`` so the test errors at collection / execution).
    """
    cli = S0maCLI()

    # Direction 1: as-shipped — clean check + green run.
    rc_check = cli.run([
        "--project-root", str(staged_runner_project),
        "check", str(staged_runner_project),
        "--mode", "strict",
    ])
    assert rc_check == EXIT_SUCCESS

    rc_test = cli.run([
        "--project-root", str(staged_runner_project),
        "test",
        "--",
        "-k", "test_divide_by_zero_raises",
    ])
    assert rc_test == EXIT_SUCCESS, (
        "s0ma test must run a test that uses pytest.raises when the "
        ".s0ma module declares requires: [pytest]."
    )

    # Direction 2: strip the requires entry but keep the pytest.raises
    # body usage — the runtime path must fail (the generated .py has no
    # `import pytest` so `pytest.raises(...)` resolves to NameError).
    divide_tests = staged_runner_project / "tests" / "divide_tests.s0ma"
    text = divide_tests.read_text()
    stripped = text.replace("    requires: [pytest]\n", "")
    assert stripped != text, "Sanity: the requires line must be present."
    divide_tests.write_text(stripped)

    rc_broken = cli.run([
        "--project-root", str(staged_runner_project),
        "test",
        "--",
        "-k", "test_divide_by_zero_raises",
    ])
    assert rc_broken != EXIT_SUCCESS, (
        "Stripping pytest from requires: while keeping pytest.raises in "
        "the body must produce a non-zero exit — the generated .py has "
        "no `import pytest` so the body cannot resolve `pytest`."
    )
