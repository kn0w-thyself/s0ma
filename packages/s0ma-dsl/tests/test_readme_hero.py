"""Tests for the root README's pictures.

The README's first picture is the anatomy of one real nerve, and it is drawn
by ``scripts/render_readme_hero.py`` from the project that
``s0ma new project shop --template service`` makes. Two things can go wrong
quietly, and each has a test here:

* The scaffold or the script changes and the committed pictures are left
  behind. The script is asked to draw them again and the result is compared
  with what is committed, so a picture cannot show a line the scaffold no
  longer writes.
* The README names a local image that is not in the repository. The link
  checker reads Markdown links and never looks inside an HTML ``<img>`` or
  ``<picture>``, which is where every image in the README lives, so those
  paths are checked here against ``git ls-files``. A file present only in a
  working tree is a file every other clone shows as broken. Terminal
  recordings are never committed, so the README has to reach them by URL.

Everything here needs the repository: the script, the README and the pictures
are not in any wheel.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "render_readme_hero.py"
README = REPO_ROOT / "README.md"
PICTURES = REPO_ROOT / "docs" / "media" / "readme"

_GIT = shutil.which("git")

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / ".git").exists() or not SCRIPT.is_file(),
    reason="not a git checkout (wheel-install context)",
)

#: Every ``src`` and ``srcset`` in the README's HTML.
_IMAGE_ATTRIBUTE = re.compile(r'\b(?:src|srcset)="([^"]+)"')

#: An HTML comment, which may run over several lines.
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@cache
def _hero() -> ModuleType:
    """Import ``scripts/render_readme_hero.py``."""
    spec = importlib.util.spec_from_file_location("s0ma_render_readme_hero", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@cache
def _drawn() -> dict[str, str]:
    """Both pictures, drawn once for the whole file: the scaffold takes a moment."""
    pictures: dict[str, str] = _hero().rendered()
    return pictures


def _local_images() -> list[str]:
    """Every image path the README shows that is not a URL.

    Comments are dropped first: a recording waits in one until it has a URL,
    and nothing in a comment is rendered.
    """
    text = _COMMENT.sub("", README.read_text(encoding="utf-8"))
    return sorted({ref for ref in _IMAGE_ATTRIBUTE.findall(text) if "://" not in ref})


class TestThePictureIsDrawnFromTheScaffold:
    def test_there_is_one_picture_for_each_palette(self) -> None:
        assert sorted(_drawn()) == ["nerve-anatomy-dark.svg", "nerve-anatomy-light.svg"]

    @pytest.mark.parametrize("name", ["nerve-anatomy-light.svg", "nerve-anatomy-dark.svg"])
    def test_the_committed_picture_is_what_the_scaffold_draws(self, name: str) -> None:
        committed = (PICTURES / name).read_text(encoding="utf-8")
        assert committed == _drawn()[name], (
            f"{name} is not what scripts/render_readme_hero.py draws from the service "
            "scaffold today. Run `python scripts/render_readme_hero.py --write` and "
            "review the difference."
        )

    @pytest.mark.parametrize("name", ["nerve-anatomy-light.svg", "nerve-anatomy-dark.svg"])
    def test_the_picture_is_well_formed(self, name: str) -> None:
        """A browser reads an SVG as XML and shows nothing at all when it is not."""
        root = ET.fromstring(_drawn()[name])
        assert root.tag.endswith("svg")

    def test_the_picture_shows_what_the_part_declares(self) -> None:
        """The four lines the README talks about, and the code under them."""
        picture = _drawn()["nerve-anatomy-light.svg"]
        for shown in ("intent", "guarantees", "forbids", "depends_on", "def handle_order_request"):
            assert shown in picture, shown

    def test_the_check_mode_agrees(self) -> None:
        """The script's own read-only mode is the same comparison, for a person to run."""
        assert _hero().main([]) == 0


class TestTheReadmeReachesItsImages:
    def test_the_readme_shows_the_picture_in_both_palettes(self) -> None:
        text = README.read_text(encoding="utf-8")
        assert 'srcset="docs/media/readme/nerve-anatomy-dark.svg"' in text
        assert 'src="docs/media/readme/nerve-anatomy-light.svg"' in text

    def test_the_readme_names_local_images(self) -> None:
        """Anti-vacuity: the next test has something to check."""
        assert len(_local_images()) >= 3

    @pytest.mark.skipif(_GIT is None, reason="git not available")
    def test_every_local_image_the_readme_names_is_tracked(self) -> None:
        assert _GIT is not None
        images = _local_images()
        listed = subprocess.run(
            [_GIT, "ls-files", "--", *images],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        missing = sorted(set(images) - set(listed))
        assert not missing, (
            f"the root README names images that are not in the repository: {missing}. "
            "A still image is committed under docs/media/readme/. A terminal recording "
            "is never committed, so the README reaches it by URL."
        )

    def test_no_recording_is_named_by_a_local_path(self) -> None:
        recordings = [ref for ref in _local_images() if ref.endswith((".gif", ".mp4", ".webm"))]
        assert not recordings, recordings
