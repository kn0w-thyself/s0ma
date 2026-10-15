"""Tests for ``s0ma check`` multi-path / subdir support (M-11, POST-7).

The M-11 milestone makes ``s0ma check`` accept zero or more positional
paths. With no arguments, the command walks every configured
``source_roots`` + ``test_roots`` from the resolved
:class:`~s0ma_dsl.project.S0maProject`. With one or more arguments,
each path is processed in sequence and diagnostics are aggregated into
a single output. Subdir inputs resolve the project context by walking
upward for ``pyproject.toml`` rather than treating the subdir as the
project boundary.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.cli.main import (
    EXIT_SUCCESS,
    EXIT_VALIDATION_ERROR,
    S0maCLI,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cli() -> S0maCLI:
    return S0maCLI()


_VALID_SOURCE_S0MA = """\
module {name}
    layer: DOMAIN
    version: 0.1.0
    intent: "Multi-path check fixture — production-side module."
    exports: [do_{name}]
    uses: none
    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve do_{name} :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "A simple function for multi-path check coverage."
    expects: "none"
    guarantees: "Returns a string"
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
    def do_{name}() -> str:
        return "{name}"
"""


_VALID_TEST_S0MA = """\
module test_{name}
    layer: DOMAIN
    version: 0.1.0
    intent: "Multi-path check fixture — test-side module."
    uses: [{name}.do_{name}]
    exports: [test_do_{name}]
    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

test test_do_{name} :: DOMAIN
    intent: "Tests do_{name} from {name}."
    tests: [{name}.do_{name}]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_do_{name}():
        pass
"""


_BROKEN_S0MA = """\
module broken_mod
    layer: DOMAIN
    version: 0.1.0
    intent: "A module missing the exports field."
    exports: none
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""


def _write_pyproject(
    root: Path,
    *,
    project_name: str = "multi_path_proj",
    source_roots: list[str] | None = None,
    test_roots: list[str] | None = None,
) -> Path:
    """Write a minimal ``pyproject.toml`` carrying ``[tool.s0ma]``."""
    body = dedent(f"""
        [project]
        name = "{project_name}"
        version = "0.1.0"

        [tool.s0ma]
    """).lstrip()
    if source_roots is not None:
        body += f"source_roots = {source_roots!r}\n"
    if test_roots is not None:
        body += f"test_roots = {test_roots!r}\n"
    pyproject = root / "pyproject.toml"
    pyproject.write_text(body, encoding="utf-8")
    return pyproject


def _project_layout(
    tmp_path: Path,
    *,
    project_name: str = "multi_path_proj",
    extra_source: str | None = None,
    broken_in_tests: bool = False,
) -> tuple[Path, Path, Path]:
    """Stand up a minimal project with ``src/``, ``tests/``, and
    a ``pyproject.toml`` declaring both as roots."""
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "src"
    src.mkdir()
    tests = root / "tests"
    tests.mkdir()
    _write_pyproject(
        root,
        project_name=project_name,
        source_roots=["src"],
        test_roots=["tests"],
    )
    (src / "alpha.s0ma").write_text(
        _VALID_SOURCE_S0MA.format(name="alpha"), encoding="utf-8"
    )
    (tests / "test_alpha.s0ma").write_text(
        _VALID_TEST_S0MA.format(name="alpha"), encoding="utf-8"
    )
    if extra_source:
        (src / f"{extra_source}.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name=extra_source),
            encoding="utf-8",
        )
    if broken_in_tests:
        (tests / "broken.s0ma").write_text(_BROKEN_S0MA, encoding="utf-8")
    return root, src, tests


@contextmanager
def _chdir(target: Path) -> Iterator[None]:
    """Switch cwd for the duration of a test (and restore on exit)."""
    prev = Path.cwd()
    try:
        os.chdir(target)
        yield
    finally:
        os.chdir(prev)


# ---------------------------------------------------------------------------
# Multi-path positional arguments
# ---------------------------------------------------------------------------


class TestMultiPathSources:
    """Test ``s0ma check src/ tests/`` and other multi-path forms."""

    def test_two_directories_checked_in_one_command(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ):
        """``s0ma check src/ tests/`` runs against both as one command."""
        root, src, tests = _project_layout(tmp_path)
        with _chdir(root):
            exit_code = cli.run([
                "check", str(src), str(tests),
                "--mode", "dev",
            ])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        # Both files reported in the no-errors summary.
        assert "2 file(s) checked" in captured.out

    def test_single_file_invocation_still_works(
        self, cli: S0maCLI, tmp_path: Path,
    ):
        """``s0ma check src/module.s0ma`` remains a valid form."""
        root, src, _ = _project_layout(tmp_path)
        target = src / "alpha.s0ma"
        with _chdir(root):
            exit_code = cli.run([
                "check", str(target), "--mode", "dev",
            ])
        assert exit_code == EXIT_SUCCESS

    def test_two_files_aggregated_into_one_output(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ):
        """Two single-file paths are aggregated and report together."""
        root, src, _ = _project_layout(
            tmp_path, extra_source="beta",
        )
        with _chdir(root):
            exit_code = cli.run([
                "check",
                str(src / "alpha.s0ma"),
                str(src / "beta.s0ma"),
                "--mode", "dev",
            ])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "2 file(s) checked" in captured.out

    def test_failure_in_any_path_causes_nonzero_exit(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ):
        """Exit code aggregates: any failing path produces non-zero exit."""
        root, src, tests = _project_layout(
            tmp_path, broken_in_tests=True,
        )
        with _chdir(root):
            exit_code = cli.run([
                "check", str(src), str(tests),
                "--mode", "dev",
            ])
        assert exit_code == EXIT_VALIDATION_ERROR
        captured = capsys.readouterr()
        # Diagnostic includes the path of the failing file.
        assert "broken_mod" in captured.out or "broken.s0ma" in captured.out

    def test_overlapping_inputs_dedupe_files(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ):
        """Listing the same dir and a file inside it must not double-count."""
        root, src, _ = _project_layout(tmp_path)
        target = src / "alpha.s0ma"
        with _chdir(root):
            exit_code = cli.run([
                "check", str(src), str(target),
                "--mode", "dev",
            ])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        # The file is parsed once, not twice — no MODULE_NAME_COLLISION
        # should fire against the module colliding with itself.
        assert "MODULE_NAME_COLLISION" not in captured.out
        assert "1 file(s) checked" in captured.out

    def test_diagnostics_do_not_interleave_in_json_output(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ):
        """JSON output keys one ``errors`` list across all input paths."""
        root, src, tests = _project_layout(
            tmp_path, broken_in_tests=True,
        )
        with _chdir(root):
            cli.run([
                "check", str(src), str(tests),
                "--mode", "dev",
                "--format", "json",
            ])
        captured = capsys.readouterr()
        # A single JSON document — not two concatenated ones — must
        # parse cleanly.
        payload = json.loads(captured.out)
        assert "errors" in payload
        assert isinstance(payload["errors"], list)


# ---------------------------------------------------------------------------
# No-args invocation: walks configured roots
# ---------------------------------------------------------------------------


class TestNoArgsWalksConfiguredRoots:
    """``s0ma check`` (no positional args) sweeps every configured root."""

    def test_no_args_checks_every_configured_root(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ):
        """``s0ma check`` with no args runs against
        ``source_roots`` + ``test_roots`` from ``[tool.s0ma]``."""
        root, _, _ = _project_layout(tmp_path)
        with _chdir(root):
            exit_code = cli.run(["check", "--mode", "dev"])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        # ``src/alpha.s0ma`` + ``tests/test_alpha.s0ma`` = 2 files.
        assert "2 file(s) checked" in captured.out

    def test_no_args_empty_roots_emits_friendly_message(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ):
        """Empty configured roots → no-op message with exit 0."""
        root = tmp_path / "blank"
        root.mkdir()
        _write_pyproject(
            root,
            project_name="blankproj",
            source_roots=[],
            test_roots=[],
        )
        with _chdir(root):
            exit_code = cli.run(["check", "--mode", "dev"])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        # Friendly no-op message lives on stderr.
        assert "nothing to check" in captured.err.lower()

    def test_no_args_missing_root_paths_emits_message(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ):
        """Configured roots that don't exist on disk yield a no-op."""
        root = tmp_path / "scaffold"
        root.mkdir()
        _write_pyproject(
            root,
            project_name="scaffold_proj",
            source_roots=["src"],
            test_roots=["tests"],
        )
        # Intentionally do not create src/ or tests/.
        with _chdir(root):
            exit_code = cli.run(["check", "--mode", "dev"])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "nothing to check" in captured.err.lower()


# ---------------------------------------------------------------------------
# Subdir input → project-context walk-up
# ---------------------------------------------------------------------------


class TestSubdirProjectContextWalkUp:
    """Subdir inputs resolve the project context by walking upward
    for ``pyproject.toml`` rather than treating the subdir as the
    project boundary."""

    def test_subdir_input_finds_pyproject_via_walk_up(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ):
        """``s0ma check src/nested/`` from outside the project resolves
        the right ``S0maProject`` via the pyproject walk-up."""
        root, src, _ = _project_layout(tmp_path)
        nested = src / "nested"
        nested.mkdir()
        # Move alpha.s0ma deeper so the input path is genuinely a
        # subdir of src/.
        (nested / "alpha.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="alpha"), encoding="utf-8"
        )
        (src / "alpha.s0ma").unlink()

        outside = tmp_path / "elsewhere"
        outside.mkdir()
        with _chdir(outside):
            exit_code = cli.run([
                "check", str(nested), "--mode", "dev",
            ])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "1 file(s) checked" in captured.out

    def test_subdir_input_uses_project_attribute_budgets(
        self, cli: S0maCLI, tmp_path: Path,
    ):
        """The re-resolved project's attribute_budgets reach the
        resolver pass — proves we picked up the real ``[tool.s0ma]``
        rather than a synthetic fallback."""
        root = tmp_path / "proj"
        root.mkdir()
        src = root / "src"
        src.mkdir()
        # A pyproject with a deliberately mis-configured budget so
        # the wrong project resolution would silently miss the error
        # and the right resolution would surface it.
        pyproject = root / "pyproject.toml"
        pyproject.write_text(
            dedent("""
                [project]
                name = "budget_proj"
                version = "0.1.0"

                [tool.s0ma]
                source_roots = ["src"]
                test_roots = []

                [tool.s0ma.attribute_budgets]
                landmark = "exactly_one_per_page"
            """).strip() + "\n",
            encoding="utf-8",
        )
        # A valid module with no ``is_page_composer: true`` nerve
        # triggers NO_PAGE_COMPOSER_DECLARED at check time when the
        # budget is configured.
        (src / "alpha.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="alpha"), encoding="utf-8"
        )
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        with _chdir(outside):
            exit_code = cli.run([
                "check", str(src), "--mode", "dev",
            ])
        # Budget pass fired ⇒ the re-resolution found the right
        # project ⇒ exit code reflects the budget error.
        assert exit_code == EXIT_VALIDATION_ERROR

    def test_explicit_project_root_overrides_subdir_walkup(
        self, cli: S0maCLI, tmp_path: Path,
    ):
        """``--project-root`` always wins over the input-path walk-up."""
        root, src, _ = _project_layout(tmp_path)
        # An empty directory with no pyproject.toml — used as
        # ``--project-root`` to force synthetic resolution even
        # though src/ would otherwise resolve to the real project.
        bare = tmp_path / "bare"
        bare.mkdir()
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        with _chdir(outside):
            exit_code = cli.run([
                "--project-root", str(bare),
                "check", str(src), "--mode", "dev",
            ])
        # The synthetic-mode fallback still validates the .s0ma
        # files; this test just asserts the explicit override
        # leaves the command runnable (i.e. our re-resolution
        # carve-out does NOT clobber an explicit override).
        assert exit_code == EXIT_SUCCESS


# ---------------------------------------------------------------------------
# Argparse surface
# ---------------------------------------------------------------------------


class TestCheckParserAcceptsMultiplePositionals:
    """The argparse parser accepts the new ``nargs="*"`` shape."""

    def test_check_accepts_zero_positional(self, cli: S0maCLI):
        parser = cli.build_parser()
        args = parser.parse_args(["check"])
        assert args.command == "check"
        assert args.source == []

    def test_check_accepts_two_positionals(self, cli: S0maCLI):
        parser = cli.build_parser()
        args = parser.parse_args(["check", "src/", "tests/"])
        assert args.source == ["src/", "tests/"]
