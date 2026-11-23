"""The launcher's copy of the default build folder is the compiler's own rule.

The Claude Code plugin refuses edits under a s0ma project's build folder, and
it reads that folder with the launcher, which imports nothing from s0ma. When
``[tool.s0ma].build_dir`` names no folder, the launcher works out the default
itself, with ``default_build_dir``. This test sits on the s0ma-lang-dsl side of
the boundary, where both rules can be read, and holds the two to one answer:
the same folder name for every project name, and no folder at all for a name
the compiler refuses.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.project import S0maProject, _default_build_dir

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER_PATH = REPO_ROOT / "integrations" / "launcher" / "s0ma_launch.py"

NAMES = (
    "demo",
    "shop",
    "my-app",
    "kn0wthyself-website-2",
    "a.b c",
    "_",
    "under_score",
    "MixedCase",
    "café",
    "x!y",
    "2fast",
    "-",
    "",
)


@pytest.fixture(scope="module")
def launcher() -> ModuleType:
    """``s0ma_launch.py``, loaded from its path, as the plugin runs it."""
    name = "s0ma_launch_for_build_dir_default"
    spec = importlib.util.spec_from_file_location(name, LAUNCHER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def compiler_default(name: str) -> str | None:
    try:
        return _default_build_dir(name)
    except ValueError as refused:
        assert str(refused).startswith("INVALID_PROJECT_NAME_FOR_BUILD_DIR")
        return None


@pytest.mark.parametrize("name", NAMES)
def test_the_launcher_names_the_same_default_build_folder(launcher: ModuleType, name: str) -> None:
    assert launcher.default_build_dir(name) == compiler_default(name)


def test_the_cases_cover_both_answers() -> None:
    """Anti-vacuity: some names have a default and some are refused."""
    answers = {compiler_default(name) is None for name in NAMES}
    assert answers == {True, False}


@pytest.mark.parametrize(
    ("project", "table"),
    [
        ('name = "my-app"\n', ""),
        ("", ""),
        ('name = "demo"\n', 'build_dir = "out/gen"\n'),
    ],
    ids=["from the name", "from the folder", "named"],
)
def test_the_launcher_finds_the_folder_a_project_builds_into(
    launcher: ModuleType, tmp_path: Path, project: str, table: str
) -> None:
    """The whole reading, against the project the compiler resolves."""
    root = tmp_path / "shop"
    root.mkdir()
    header = f"[project]\n{project}" if project else ""
    (root / "pyproject.toml").write_text(
        header + '[tool.s0ma]\nsource_roots = ["src"]\n' + table, encoding="utf-8"
    )
    resolved = S0maProject.discover(root)
    assert launcher.build_dir_of(root) == resolved.build_dir
