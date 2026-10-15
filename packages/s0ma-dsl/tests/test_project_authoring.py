"""Tests for ``[tool.s0ma].authoring`` parse + validation (STD-M4).

The usability plan's M4 adds a first-class on/off authoring switch to the
project model:

  - :class:`s0ma_dsl.project.S0maProject` gains an ``authoring`` field
    parsed from ``[tool.s0ma].authoring`` (validated against
    :data:`s0ma_dsl.project.SUPPORTED_AUTHORING`).
  - Unlike ``mode``, the key is NOT optional-as-``None``: an absent key
    takes the documented default ``"on"`` so every resolved project
    (including synthetic fallbacks) carries a definite posture.
  - An unrecognised value is a load-time ``ValueError`` naming the
    supported set — the same loud-error style as ``mode`` /
    ``test_layering``.

The MCP server's ``project_status`` tool and ``s0ma doctor`` both read
this posture back (tested in s0ma-mcp's ``test_project_status.py`` and
``test_doctor.py`` respectively); this module proves the loader half.
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl import S0maProject
from s0ma_dsl.project import DEFAULT_AUTHORING, SUPPORTED_AUTHORING

if TYPE_CHECKING:
    from pathlib import Path


def _write_pyproject(
    root: Path,
    *,
    project_name: str = "authproj",
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


# ---------------------------------------------------------------------------
# The supported set + default
# ---------------------------------------------------------------------------


def test_supported_set_is_exactly_on_off() -> None:
    assert frozenset({"on", "off"}) == SUPPORTED_AUTHORING


def test_default_is_on() -> None:
    assert DEFAULT_AUTHORING == "on"


# ---------------------------------------------------------------------------
# Loader: parse + validate [tool.s0ma].authoring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", sorted(SUPPORTED_AUTHORING))
def test_authoring_parsed_for_each_valid_value(
    tmp_path: Path, value: str
) -> None:
    """Both supported values round-trip onto ``S0maProject.authoring``."""
    _write_pyproject(tmp_path, tool_s0ma=f'authoring = "{value}"')
    project = S0maProject.discover(tmp_path)
    assert project.authoring == value


def test_authoring_absent_defaults_to_on(tmp_path: Path) -> None:
    """An omitted key takes the documented default ``"on"`` (not None)."""
    _write_pyproject(tmp_path, tool_s0ma='source_roots = ["src"]')
    project = S0maProject.discover(tmp_path)
    assert project.authoring == "on"


def test_authoring_empty_table_defaults_to_on(tmp_path: Path) -> None:
    """An empty ``[tool.s0ma]`` table still yields the default posture."""
    _write_pyproject(tmp_path, tool_s0ma="")
    project = S0maProject.discover(tmp_path)
    assert project.authoring == "on"


def test_authoring_invalid_value_raises_with_supported_set(
    tmp_path: Path,
) -> None:
    """An unrecognised value raises a load-time error naming the set."""
    _write_pyproject(tmp_path, tool_s0ma='authoring = "yes"')
    with pytest.raises(ValueError) as exc:
        S0maProject.discover(tmp_path)
    msg = str(exc.value)
    assert "[tool.s0ma].authoring" in msg
    assert "yes" in msg
    # Names the supported set so the author can self-correct.
    for valid in SUPPORTED_AUTHORING:
        assert valid in msg


def test_authoring_wrong_type_raises(tmp_path: Path) -> None:
    """A non-string value (e.g. a bool) is a load-time type error."""
    _write_pyproject(tmp_path, tool_s0ma="authoring = true")
    with pytest.raises(ValueError) as exc:
        S0maProject.discover(tmp_path)
    assert "authoring" in str(exc.value)


def test_synthetic_fallback_authoring_is_on(tmp_path: Path) -> None:
    """A synthetic-fallback project (no [tool.s0ma]) carries ``"on"``."""
    project = S0maProject.synthetic_fallback(tmp_path)
    assert project.synthetic is True
    assert project.authoring == "on"


def test_authoring_independent_of_mode(tmp_path: Path) -> None:
    """``authoring`` and ``mode`` parse independently on the same table."""
    _write_pyproject(
        tmp_path, tool_s0ma='mode = "strict"\nauthoring = "off"'
    )
    project = S0maProject.discover(tmp_path)
    assert project.mode == "strict"
    assert project.authoring == "off"
