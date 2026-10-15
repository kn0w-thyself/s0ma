"""Tests for the O1 ops-runbook ``[tool.s0ma]`` keys (0.11.0, batch-01a).

M4: :class:`s0ma_dsl.project.S0maProject` gains five optional runbook
fields parsed from ``[tool.s0ma]`` — ``run_command`` / ``health_command``
(strings), ``state_paths`` (list of authored path strings, the runtime
state that must NEVER be reverted or regenerated), ``runbook_notes``
(string or list of strings), and ``env`` (``[tool.s0ma.env.<NAME>]``
subtables → :class:`RunbookEnvVar` contracts). All optional; every shape
error is a load-time ``ValueError`` in the existing ``[tool.s0ma]`` style.

These fields feed the ``s0ma://project/runbook`` MCP resource and the
``project_status`` runtime section; this module proves the loader half.
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl import S0maProject
from s0ma_dsl.project import RunbookEnvVar

if TYPE_CHECKING:
    from pathlib import Path


def _write(root: Path, tool_s0ma: str) -> Path:
    body = dedent(
        """
        [project]
        name = "runbookproj"
        version = "0.1.0"
        """
    ).lstrip()
    body += "\n[tool.s0ma]\nsource_roots = [\"src\"]\n" + tool_s0ma + "\n"
    pyproject = root / "pyproject.toml"
    pyproject.write_text(body, encoding="utf-8")
    return pyproject


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestRunbookFieldsParse:
    def test_all_keys(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            dedent(
                """
                run_command = "uv run opsdemo"
                health_command = "curl -fsS localhost:8080/health"
                state_paths = ["var/app.db", "var/uploads"]
                runbook_notes = ["a", "b"]

                [tool.s0ma.env.DATABASE_URL]
                required = true
                fail_fast = true
                default = "sqlite:///dev.db"

                [tool.s0ma.env.PORT]
                default = "8080"
                """
            ),
        )
        project = S0maProject.discover(tmp_path)
        assert project.run_command == "uv run opsdemo"
        assert project.health_command == "curl -fsS localhost:8080/health"
        assert project.state_paths == ("var/app.db", "var/uploads")
        assert project.runbook_notes == ("a", "b")
        assert project.env == {
            "DATABASE_URL": RunbookEnvVar(
                required=True, fail_fast=True, default="sqlite:///dev.db"
            ),
            "PORT": RunbookEnvVar(required=False, fail_fast=False, default="8080"),
        }

    def test_absent_keys_default_cleanly(self, tmp_path: Path) -> None:
        _write(tmp_path, "")
        project = S0maProject.discover(tmp_path)
        assert project.run_command is None
        assert project.health_command is None
        assert project.state_paths == ()
        assert project.runbook_notes == ()
        assert project.env == {}

    def test_runbook_notes_single_string(self, tmp_path: Path) -> None:
        _write(tmp_path, 'runbook_notes = "just one note"')
        project = S0maProject.discover(tmp_path)
        assert project.runbook_notes == ("just one note",)

    def test_runbook_notes_drops_blank_entries(self, tmp_path: Path) -> None:
        _write(tmp_path, 'runbook_notes = ["kept", "  ", "also"]')
        project = S0maProject.discover(tmp_path)
        assert project.runbook_notes == ("kept", "also")

    def test_env_defaults_when_flags_omitted(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            dedent(
                """
                [tool.s0ma.env.FEATURE_FLAG]
                """
            ),
        )
        project = S0maProject.discover(tmp_path)
        assert project.env == {
            "FEATURE_FLAG": RunbookEnvVar(
                required=False, fail_fast=False, default=None
            )
        }

    def test_synthetic_project_has_no_runbook(self, tmp_path: Path) -> None:
        project = S0maProject.synthetic_fallback(tmp_path)
        assert project.run_command is None
        assert project.env == {}
        assert project.state_paths == ()


# ---------------------------------------------------------------------------
# Shape validation (load-time ValueError, actionable message)
# ---------------------------------------------------------------------------


class TestRunbookShapeErrors:
    @pytest.mark.parametrize(
        ("body", "needle"),
        [
            ("run_command = 5", "run_command"),
            ("health_command = true", "health_command"),
            ('state_paths = "notalist"', "state_paths"),
            ("state_paths = [1, 2]", "state_paths"),
            ("runbook_notes = 42", "runbook_notes"),
            ("runbook_notes = [1]", "runbook_notes"),
            ('env = "notatable"', "env"),
        ],
    )
    def test_scalar_and_list_shape_errors(
        self, tmp_path: Path, body: str, needle: str
    ) -> None:
        _write(tmp_path, body)
        with pytest.raises(ValueError, match=needle):
            S0maProject.discover(tmp_path)

    def test_env_entry_must_be_table(self, tmp_path: Path) -> None:
        _write(tmp_path, "env = { DATABASE_URL = \"nope\" }")
        with pytest.raises(ValueError, match=r"env\.DATABASE_URL.*must be a table"):
            S0maProject.discover(tmp_path)

    def test_env_unknown_subkey_rejected(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            dedent(
                """
                [tool.s0ma.env.FOO]
                require = true
                """
            ),
        )
        with pytest.raises(ValueError, match="unsupported key"):
            S0maProject.discover(tmp_path)

    def test_env_required_must_be_bool(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            dedent(
                """
                [tool.s0ma.env.FOO]
                required = "yes"
                """
            ),
        )
        with pytest.raises(ValueError, match=r"env\.FOO\.required.*bool"):
            S0maProject.discover(tmp_path)

    def test_env_default_must_be_string(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            dedent(
                """
                [tool.s0ma.env.FOO]
                default = 8080
                """
            ),
        )
        with pytest.raises(ValueError, match=r"env\.FOO\.default.*string"):
            S0maProject.discover(tmp_path)
