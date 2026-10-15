"""Tests for ``[tool.s0ma].mode`` read-side + CLI precedence (DSL-M3).

F-M1-2: until 0.8.0 the ``[tool.s0ma].mode`` key was declarative-only —
``s0ma new project`` wrote it but nothing read it back, so a project
declaring ``mode = "strict"`` still checked/built in the CLI's built-in
default unless every invocation passed ``--mode``. DSL-M3 makes the key
load-bearing:

  - :class:`s0ma_dsl.project.S0maProject` gains a ``mode`` field parsed
    from ``[tool.s0ma].mode`` (validated against the four
    :class:`s0ma_dsl.config.StrictnessMode` values; absent => ``None``).
  - The CLI resolves the effective mode as
    ``--mode flag > [tool.s0ma].mode > the command's built-in default``
    (``s0ma_dsl.cli.main._resolve_mode``), preserving the pre-0.8.0
    per-command built-in defaults EXACTLY (``check`` strict, every other
    project-resolving command dev) for table-less and synthetic
    invocations.

This module proves the loader half (parse + validate) and the full
precedence matrix on both ``check`` (built-in strict) and ``build``
(built-in dev), plus the synthetic-invariance guarantee.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from textwrap import dedent

import pytest

from s0ma_dsl import S0maProject
from s0ma_dsl.cli.main import _BUILTIN_MODE_DEFAULTS, _resolve_mode
from s0ma_dsl.project import SUPPORTED_PROJECT_MODES

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_pyproject(
    root: Path,
    *,
    project_name: str = "modeproj",
    tool_s0ma: str | None = "",
) -> Path:
    """Write a minimal pyproject.toml at *root*.

    *tool_s0ma* is the body of the ``[tool.s0ma]`` table. ``""`` writes
    an empty table; ``None`` omits the table entirely.
    """
    body = dedent(f"""
        [project]
        name = "{project_name}"
        version = "0.1.0"
    """).lstrip()
    if tool_s0ma is not None:
        body += "\n[tool.s0ma]\n" + tool_s0ma + "\n"
    pyproject = root / "pyproject.toml"
    pyproject.write_text(body, encoding="utf-8")
    return pyproject


def _mk_project(
    mode: str | None, *, synthetic: bool = False
) -> S0maProject:
    """Construct a minimal :class:`S0maProject` carrying *mode*."""
    return S0maProject(
        root=Path("/x"),
        project_name="p",
        source_roots=(),
        test_roots=(),
        build_dir=Path("/x/build"),
        bootstrap_files=(),
        mode=mode,  # type: ignore[arg-type]
        synthetic=synthetic,
    )


def _resolve(
    command: str, flag: str | None, project: S0maProject | None
) -> str | None:
    """Run :func:`_resolve_mode` and return the resolved ``args.mode``."""
    ns = argparse.Namespace(command=command, mode=flag)
    _resolve_mode(ns, project)
    return ns.mode


# ---------------------------------------------------------------------------
# Loader: parse + validate [tool.s0ma].mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", sorted(SUPPORTED_PROJECT_MODES))
def test_mode_key_parsed_for_each_valid_value(
    tmp_path: Path, mode: str
) -> None:
    """Every supported mode value round-trips onto ``S0maProject.mode``."""
    _write_pyproject(tmp_path, tool_s0ma=f'mode = "{mode}"')
    project = S0maProject.discover(tmp_path)
    assert project.mode == mode


def test_mode_absent_is_none(tmp_path: Path) -> None:
    """An omitted ``mode`` key leaves ``S0maProject.mode`` as ``None``.

    ``None`` is the signal the CLI uses to fall through to each command's
    built-in default — the pre-0.8.0 behaviour.
    """
    _write_pyproject(tmp_path, tool_s0ma='source_roots = ["src"]')
    project = S0maProject.discover(tmp_path)
    assert project.mode is None


def test_mode_invalid_value_raises_with_supported_set(
    tmp_path: Path,
) -> None:
    """An unrecognised ``mode`` raises a load-time error naming the set."""
    _write_pyproject(tmp_path, tool_s0ma='mode = "ultra"')
    with pytest.raises(ValueError) as exc:
        S0maProject.discover(tmp_path)
    msg = str(exc.value)
    assert "[tool.s0ma].mode" in msg
    assert "ultra" in msg
    # Names the supported set so the author can self-correct.
    for valid in SUPPORTED_PROJECT_MODES:
        assert valid in msg


def test_mode_wrong_type_raises(tmp_path: Path) -> None:
    """A non-string ``mode`` (e.g. an int) is a load-time type error."""
    _write_pyproject(tmp_path, tool_s0ma="mode = 3")
    with pytest.raises(ValueError) as exc:
        S0maProject.discover(tmp_path)
    assert "mode" in str(exc.value)


def test_synthetic_fallback_mode_is_none(tmp_path: Path) -> None:
    """A synthetic-fallback project (no [tool.s0ma]) carries ``mode=None``."""
    project = S0maProject.synthetic_fallback(tmp_path)
    assert project.synthetic is True
    assert project.mode is None


# ---------------------------------------------------------------------------
# CLI precedence matrix — check (built-in default: strict)
# ---------------------------------------------------------------------------


class TestCheckPrecedence:
    """``check``'s built-in default is ``strict`` (NOT unified with build)."""

    def test_flag_wins_over_table(self) -> None:
        # Explicit --mode overrides the project table.
        assert _resolve("check", "release", _mk_project("dev")) == "release"

    def test_table_used_when_flag_omitted(self) -> None:
        assert _resolve("check", None, _mk_project("release")) == "release"

    def test_builtin_when_no_flag_no_table(self) -> None:
        assert _resolve("check", None, _mk_project(None)) == "strict"

    def test_synthetic_ignores_table_uses_builtin(self) -> None:
        # Synthetic projects must keep today's behaviour exactly: the
        # table value (even if somehow present) is ignored.
        resolved = _resolve("check", None, _mk_project("release", synthetic=True))
        assert resolved == "strict"

    def test_no_project_uses_builtin(self) -> None:
        assert _resolve("check", None, None) == "strict"

    def test_flag_wins_even_with_synthetic(self) -> None:
        resolved = _resolve("check", "dev", _mk_project("release", synthetic=True))
        assert resolved == "dev"


# ---------------------------------------------------------------------------
# CLI precedence matrix — build (built-in default: dev)
# ---------------------------------------------------------------------------


class TestBuildPrecedence:
    """``build``'s built-in default is ``dev`` (preserved, NOT unified)."""

    def test_flag_wins_over_table(self) -> None:
        assert _resolve("build", "strict", _mk_project("release")) == "strict"

    def test_table_used_when_flag_omitted(self) -> None:
        assert _resolve("build", None, _mk_project("release")) == "release"

    def test_builtin_when_no_flag_no_table(self) -> None:
        assert _resolve("build", None, _mk_project(None)) == "dev"

    def test_synthetic_ignores_table_uses_builtin(self) -> None:
        resolved = _resolve("build", None, _mk_project("release", synthetic=True))
        assert resolved == "dev"

    def test_no_project_uses_builtin(self) -> None:
        assert _resolve("build", None, None) == "dev"


# ---------------------------------------------------------------------------
# CLI precedence matrix — the other project-resolving commands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command", ["transpile", "migrate-layout", "topo", "test"]
)
class TestOtherCommandsPrecedence:
    """transpile/migrate-layout/topo/test all share the dev built-in."""

    def test_builtin_is_dev(self, command: str) -> None:
        assert _BUILTIN_MODE_DEFAULTS[command] == "dev"
        assert _resolve(command, None, _mk_project(None)) == "dev"

    def test_table_wins_over_builtin(self, command: str) -> None:
        assert _resolve(command, None, _mk_project("strict")) == "strict"

    def test_flag_wins_over_table(self, command: str) -> None:
        assert _resolve(command, "release", _mk_project("strict")) == "release"

    def test_synthetic_falls_back_to_builtin(self, command: str) -> None:
        resolved = _resolve(command, None, _mk_project("release", synthetic=True))
        assert resolved == "dev"


# ---------------------------------------------------------------------------
# new project: the one command that WRITES the table — must NOT read it
# ---------------------------------------------------------------------------


def test_new_command_not_table_aware() -> None:
    """``new`` is absent from the mode map: it self-manages resolution.

    ``s0ma new project`` writes ``[tool.s0ma].mode`` for a directory that
    is not a project yet, so there is no project to read from. Its
    argparse ``--mode`` default must survive ``_resolve_mode`` untouched.
    """
    assert "new" not in _BUILTIN_MODE_DEFAULTS
    ns = argparse.Namespace(command="new", mode="dev")
    _resolve_mode(ns, _mk_project("release"))
    assert ns.mode == "dev"  # untouched


def test_command_without_mode_is_noop() -> None:
    """A command outside the map with no ``mode`` attribute is a no-op."""
    ns = argparse.Namespace(command="doctor")
    # Must not raise even though there is no ``mode`` attribute.
    _resolve_mode(ns, _mk_project("release"))
    assert not hasattr(ns, "mode")


# ---------------------------------------------------------------------------
# End-to-end: table value flows through discover() into resolution
# ---------------------------------------------------------------------------


def test_table_release_flows_into_check_resolution(tmp_path: Path) -> None:
    """A real project declaring ``mode = "release"`` resolves check=release.

    This is the F-M1-2 acceptance shape: ``s0ma check <project>`` (no
    --mode) runs in the table-declared mode rather than the built-in
    strict default.
    """
    _write_pyproject(tmp_path, tool_s0ma='mode = "release"')
    project = S0maProject.discover(tmp_path)
    assert _resolve("check", None, project) == "release"
    # And the explicit flag still wins.
    assert _resolve("check", "dev", project) == "dev"
