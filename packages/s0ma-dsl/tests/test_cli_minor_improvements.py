"""M-16 (POST-11a/b/c, 0.16.0) — CLI / build minor improvements.

Three independent regression surfaces, bundled into one test module so
the M-16 commit body stays auditable:

- **POST-11a — `--output-dir` vs. `[tool.s0ma].build_dir` conflict.**
  When the user passes ``--output-dir`` to ``s0ma build`` and the
  resolved path disagrees with ``[tool.s0ma].build_dir``, the default
  behaviour refuses the override with ``BUILD_DIR_OVERRIDE_CONFLICT``
  (exit ``EXIT_USAGE_ERROR``). The ``--force-output-dir`` flag is the
  escape hatch — it suppresses the refusal and emits a one-line stderr
  notice so the override remains visible in logs.

- **POST-11b — ``s0ma test --quiet``.** ``--quiet`` suppresses every
  driver-side print path so only pytest's own output stream reaches
  stdout. Without ``--quiet`` the driver banner is present (the build
  helper's ``Running: ...`` line plus any one-liner notices).

- **POST-11c — ``s0ma build`` exit-code semantics.** Warnings never
  block the build absent ``--mode strict`` (or higher). Hard errors
  always exit non-zero. Zero issues exits zero. These tests pin the
  current contract so future refactors cannot silently flip it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import (
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    EXIT_VALIDATION_ERROR,
    S0maCLI,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CROSS_MODULE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "cross_module_test_project"
)

# A minimal one-module .s0ma source for a self-contained per-test project.
_MINIMAL_MODULE = """\
module sample_mod
    layer: DOMAIN
    version: 0.1.0
    intent: "A minimal module for CLI minor-improvements tests."
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
    intent: "Return a greeting; trivial for build-pass smoke tests."
    expects: "name: str"
    guarantees: "Returns a non-empty greeting string."
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
"""


def _scaffold_project(
    root: Path,
    *,
    build_dir_value: str = "build",
    extra_pyproject_lines: str = "",
) -> None:
    """Lay down a minimal s0ma project at *root* with a [tool.s0ma] table.

    The project carries one ``.s0ma`` module under ``src/`` and a
    ``[tool.s0ma].build_dir`` of ``build_dir_value`` so the M-16
    BUILD_DIR_OVERRIDE_CONFLICT pre-flight has something to disagree
    with.
    """
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "sample_mod.s0ma").write_text(_MINIMAL_MODULE, encoding="utf-8")
    pyproject = (
        '[project]\n'
        'name = "sample_project"\n'
        'version = "0.0.1"\n'
        '\n'
        '[tool.s0ma]\n'
        'source_roots = ["src"]\n'
        'test_roots = ["tests"]\n'
        f'build_dir = "{build_dir_value}"\n'
        'bootstrap_files = []\n'
        f'{extra_pyproject_lines}'
    )
    (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")


@pytest.fixture()
def synthetic_project_dir(tmp_path: Path) -> Path:
    """A project root with no ``[tool.s0ma]`` table (synthetic fallback path)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "sample_mod.s0ma").write_text(_MINIMAL_MODULE, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def configured_project_dir(tmp_path: Path) -> Path:
    """A project root with a ``[tool.s0ma].build_dir = "build"`` table."""
    _scaffold_project(tmp_path, build_dir_value="build")
    return tmp_path


@pytest.fixture()
def staged_test_runner_project(tmp_path: Path) -> Path:
    """Copy the cross-module test fixture into ``tmp_path`` for hermetic runs.

    Mirrors ``tests/test_s0ma_test_runner.py`` — the in-tree fixture
    must be staged because ``s0ma test`` writes a ``build_dir`` next to
    the pyproject.toml.
    """
    dst = tmp_path / "cross_module_test_project"
    shutil.copytree(CROSS_MODULE_FIXTURE, dst)
    return dst


# ===========================================================================
# POST-11a — `--output-dir` vs `[tool.s0ma].build_dir` conflict
# ===========================================================================


class TestPOST11aOutputDirConflict:
    """``--output-dir`` against a configured project triggers the refusal."""

    def test_conflicting_output_dir_refused_without_force(
        self,
        configured_project_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A different --output-dir refuses with BUILD_DIR_OVERRIDE_CONFLICT.

        Acceptance: exit ``EXIT_USAGE_ERROR``, a stderr message naming
        the error code + both paths + the ``--force-output-dir`` escape
        hatch, and the supplied ``--output-dir`` is NOT materialised
        (the pre-flight refusal fires before any ``.s0ma`` parsing).
        """
        override = tmp_path / "throwaway_build"
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(configured_project_dir),
            "build", str(configured_project_dir / "src"),
            "--output-dir", str(override),
            "--mode", "dev",
            "--no-cache",
        ])
        assert rc == EXIT_USAGE_ERROR
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "BUILD_DIR_OVERRIDE_CONFLICT" in combined
        assert str(override) in combined
        assert "--force-output-dir" in combined
        # No build artefacts at the override path — the refusal aborts
        # before any transpile step runs.
        assert not override.exists() or not any(override.iterdir())

    def test_force_output_dir_suppresses_refusal(
        self,
        configured_project_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--force-output-dir`` proceeds and lands the build at the override.

        Acceptance: exit ``EXIT_SUCCESS``; a one-line stderr notice
        announces the override (so log readers see what happened); the
        build artefacts land at the override path.
        """
        override = tmp_path / "throwaway_build"
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(configured_project_dir),
            "build", str(configured_project_dir / "src"),
            "--output-dir", str(override),
            "--force-output-dir",
            "--mode", "dev",
            "--no-cache",
        ])
        assert rc == EXIT_SUCCESS
        captured = capsys.readouterr()
        # The override notice on stderr (not stdout) carries both paths.
        assert "overrides" in captured.err or "--force-output-dir" in captured.err
        assert str(override) in captured.err
        # The build landed at the override path.
        assert (override / "sample_mod.py").is_file()

    def test_synthetic_project_no_conflict(
        self,
        synthetic_project_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Synthetic-fallback projects never raise BUILD_DIR_OVERRIDE_CONFLICT.

        Acceptance: a project with no ``[tool.s0ma]`` table has no
        canonical ``build_dir`` to disagree with; the override applies
        silently (modulo the synthetic-mode warning which is unrelated
        to POST-11a).
        """
        override = tmp_path / "synthetic_out"
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(synthetic_project_dir),
            "build", str(synthetic_project_dir / "src"),
            "--output-dir", str(override),
            "--mode", "dev",
            "--no-cache",
        ])
        assert rc == EXIT_SUCCESS
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "BUILD_DIR_OVERRIDE_CONFLICT" not in combined
        assert (override / "sample_mod.py").is_file()

    def test_no_override_no_warning(
        self,
        configured_project_dir: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``s0ma build`` with no ``--output-dir`` is the common case — no warning.

        Acceptance: the project model's resolved ``build_dir`` is the
        target by default; no BUILD_DIR_OVERRIDE_CONFLICT diagnostic
        fires because no override was supplied.
        """
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(configured_project_dir),
            "build", str(configured_project_dir / "src"),
            "--mode", "dev",
            "--no-cache",
        ])
        assert rc == EXIT_SUCCESS
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "BUILD_DIR_OVERRIDE_CONFLICT" not in combined
        # The build landed at the project's configured ``build_dir``.
        assert (configured_project_dir / "build" / "sample_mod.py").is_file()

    def test_override_matching_build_dir_is_silent(
        self,
        configured_project_dir: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--output-dir`` pointing at the SAME path as ``build_dir`` is silent.

        Acceptance: a redundant ``--output-dir`` (the user typed
        ``--output-dir=build`` for a project that already declares
        ``[tool.s0ma].build_dir = "build"``) does NOT fire the
        conflict — the two paths resolve to the same absolute path so
        there is nothing to disagree with.
        """
        same_path = configured_project_dir / "build"
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(configured_project_dir),
            "build", str(configured_project_dir / "src"),
            "--output-dir", str(same_path),
            "--mode", "dev",
            "--no-cache",
        ])
        assert rc == EXIT_SUCCESS
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "BUILD_DIR_OVERRIDE_CONFLICT" not in combined


# ===========================================================================
# POST-11b — ``s0ma test --quiet`` mode
# ===========================================================================


class TestPOST11bS0maTestQuiet:
    """``s0ma test --quiet`` suppresses every driver-side stdout print."""

    def test_quiet_suppresses_driver_banner(
        self,
        staged_test_runner_project: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``s0ma test --quiet`` does not emit the ``Running: pytest …`` banner.

        Acceptance: with ``--quiet`` set, no driver-side print path
        reaches stdout. ``subprocess.run`` is monkeypatched to a no-op
        so the test does not depend on a real pytest invocation; the
        test asserts on what the driver itself would have printed to
        stdout BEFORE handing control to pytest.
        """
        class _DummyResult:
            returncode = 0

        def _fake_run(*args: object, **kwargs: object) -> _DummyResult:
            return _DummyResult()

        monkeypatch.setattr("subprocess.run", _fake_run)
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(staged_test_runner_project),
            "test",
            "--quiet",
        ])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Running:" not in captured.out
        # ``Built N module(s).`` is the legacy --quiet one-liner from
        # the build helper. POST-11b suppresses it for test-runner
        # builds so the only thing on stdout is pytest's stream.
        assert "Built " not in captured.out
        assert "Build complete" not in captured.out
        assert "Output directory" not in captured.out

    def test_default_emits_driver_banner(
        self,
        staged_test_runner_project: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without ``--quiet`` the driver banner is visible on stdout.

        Acceptance: the user explicitly opted into visible per-step
        output; the ``Running: …`` line plus the build summary
        ``Build complete: …`` line reach stdout as the regression-pin
        contract for the non-quiet path.
        """
        class _DummyResult:
            returncode = 0

        def _fake_run(*args: object, **kwargs: object) -> _DummyResult:
            return _DummyResult()

        monkeypatch.setattr("subprocess.run", _fake_run)
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(staged_test_runner_project),
            "test",
        ])
        assert rc == 0
        captured = capsys.readouterr()
        # The driver's ``Running: ...`` banner reaches stdout.
        assert "Running:" in captured.out
        # The build helper's "Build complete: ..." line is also on stdout.
        assert "Build complete:" in captured.out


# ===========================================================================
# POST-11c — ``s0ma build`` exit-code semantics
# ===========================================================================


_WARNING_PRODUCING_MODULE = """\
module sample_mod
    layer: DOMAIN
    version: 0.1.0
    intent: "Module that produces a warning-only finding in dev mode."
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
    intent: "Return a greeting; bare-imports json (BARE_IMPORT warning in dev)."
    expects: "name: str"
    guarantees: "Returns a non-empty greeting string."
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
        import json
        return json.dumps({"hi": name})
"""

_HARD_ERROR_MODULE = """\
module sample_mod
    layer: DOMAIN
    version: 0.1.0
    intent: "Module that triggers a parse-time hard error (missing exports)."
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""


def _project_with_module(tmp_path: Path, source: str) -> Path:
    """Lay down a minimal project with a single ``.s0ma`` module containing *source*."""
    proj = tmp_path / "exit_codes_project"
    proj.mkdir()
    (proj / "src").mkdir()
    (proj / "src" / "sample_mod.s0ma").write_text(source, encoding="utf-8")
    (proj / "pyproject.toml").write_text(
        '[project]\n'
        'name = "exit_codes_project"\n'
        'version = "0.0.1"\n'
        '\n'
        '[tool.s0ma]\n'
        'source_roots = ["src"]\n'
        'test_roots = ["tests"]\n'
        'build_dir = "build"\n'
        'bootstrap_files = []\n',
        encoding="utf-8",
    )
    return proj


class TestPOST11cBuildExitCodeSemantics:
    """Regression pins on the ``s0ma build`` exit-code contract.

    The contract: warnings alone never block the build (exit 0); hard
    errors always exit non-zero; ``--mode strict`` (and higher) escalate
    qualifying warnings to errors via ``SEVERITY_MATRIX``.
    """

    def test_clean_build_exits_zero(self, configured_project_dir: Path) -> None:
        """Zero diagnostics → ``EXIT_SUCCESS``.

        Acceptance: the happy-path baseline. A clean ``.s0ma`` source
        with no warnings exits zero unconditionally.
        """
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(configured_project_dir),
            "build", str(configured_project_dir / "src"),
            "--mode", "dev",
            "--no-cache",
        ])
        assert rc == EXIT_SUCCESS

    def test_warning_only_dev_mode_exits_zero(self, tmp_path: Path) -> None:
        """A warning-only finding (VESTIGIAL_IMPORT in dev) exits zero.

        Acceptance: dev mode promotes the unused ``requires: [json]``
        entry to a warning; ``s0ma build`` continues to emit the
        artefact and exits ``EXIT_SUCCESS``. The contract is "warnings
        never block absent --mode strict".
        """
        proj = _project_with_module(tmp_path, _WARNING_PRODUCING_MODULE)
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(proj),
            "build", str(proj / "src"),
            "--mode", "dev",
            "--no-cache",
        ])
        assert rc == EXIT_SUCCESS

    def test_strict_mode_promotes_same_warning_to_error(
        self, tmp_path: Path
    ) -> None:
        """Strict mode promotes the dev warning to an error → non-zero.

        Acceptance: the SAME source that exited zero in dev mode exits
        ``EXIT_VALIDATION_ERROR`` in strict mode. The strictness ladder
        is the only knob that flips warning-only findings to blockers;
        no other CLI input does.
        """
        proj = _project_with_module(tmp_path, _WARNING_PRODUCING_MODULE)
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(proj),
            "build", str(proj / "src"),
            "--mode", "strict",
            "--no-cache",
        ])
        assert rc == EXIT_VALIDATION_ERROR

    def test_hard_error_always_exits_non_zero(self, tmp_path: Path) -> None:
        """A required-state omission exits ``EXIT_VALIDATION_ERROR``.

        Acceptance: a missing ``exports:`` field is a hard error in
        every strictness mode. Even the most permissive mode
        (``migration``) cannot make this pass — the build must exit
        non-zero so the failing module is visible to CI.
        """
        proj = _project_with_module(tmp_path, _HARD_ERROR_MODULE)
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(proj),
            "build", str(proj / "src"),
            "--mode", "migration",
            "--no-cache",
        ])
        assert rc == EXIT_VALIDATION_ERROR
