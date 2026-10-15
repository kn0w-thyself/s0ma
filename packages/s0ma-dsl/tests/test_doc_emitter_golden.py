"""Golden snapshot tests for the M6 doc emitter.

Each rendered output is compared byte-for-byte against a checked-in
golden file. If a future change is intentional, regenerate the goldens
in a single commit and explain why in the commit message — the tests
are deliberately strict so that accidental drift surfaces immediately.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import S0maCLI

FIXTURE_SOURCE = (
    Path(__file__).parent / "fixtures" / "valid" / "docs" / "render_formats"
)
GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "docs"


def _build(project_dir: Path, output_dir: Path) -> int:
    cli = S0maCLI()
    return cli.run(
        ["build", str(project_dir), "--output-dir", str(output_dir), "--quiet"]
    )


@pytest.mark.parametrize(
    "relpath",
    [
        Path("docs/greetings.md"),
        Path("docs/greetings.json"),
        Path("docs/greetings.html"),
        Path("docs/walkthrough.md"),
    ],
)
def test_rendered_output_matches_golden(
    tmp_path: Path, relpath: Path,
) -> None:
    project_dir = tmp_path / "project"
    shutil.copytree(FIXTURE_SOURCE, project_dir)
    output_dir = tmp_path / "out"

    rc = _build(project_dir, output_dir)
    assert rc == 0

    actual = (output_dir / relpath).read_text()
    golden = (GOLDEN_DIR / relpath.name).read_text()
    assert actual == golden, (
        f"Rendered {relpath.name} drifted from golden snapshot.\n"
        f"--- golden ---\n{golden}\n--- actual ---\n{actual}"
    )
