"""End-to-end build-pipeline tests for the M6 doc emitter.

Covers:
* ``s0ma build`` writes Markdown / HTML / JSON outputs alongside the
  ``.py`` / ``.s0ma.json`` / ``.s0ma.map`` artifacts.
* Emitted ``register_doc_*`` calls carry the same content hash that is
  baked into the rendered front-matter.
* Re-running ``s0ma build`` against an unchanged source tree produces
  byte-identical rendered outputs (the determinism contract).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from s0ma_dsl.cli.main import S0maCLI

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "valid" / "docs" / "render_formats"


def _copy_fixture(src: Path, dst: Path) -> Path:
    """Copy the fixture tree into a writable scratch dir."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst


def _run_build(project_dir: Path, output_dir: Path) -> int:
    cli = S0maCLI()
    return cli.run(
        ["build", str(project_dir), "--output-dir", str(output_dir), "--quiet"]
    )


class TestBuildPipelineWritesRenderedOutputs:
    def test_markdown_html_json_files_emitted(self, tmp_path: Path) -> None:
        project_dir = _copy_fixture(FIXTURE_DIR, tmp_path / "project")
        output_dir = tmp_path / "out"
        rc = _run_build(project_dir, output_dir)
        assert rc == 0

        # Markdown / HTML / JSON output files exist with deterministic
        # paths matching the doc declarations' output: fields.
        assert (output_dir / "docs" / "greetings.md").is_file()
        assert (output_dir / "docs" / "greetings.html").is_file()
        assert (output_dir / "docs" / "greetings.json").is_file()
        assert (output_dir / "docs" / "walkthrough.md").is_file()

        # Sibling .py and .s0ma.json artifacts also land in out/.
        assert (output_dir / "render_targets.py").is_file()
        assert (output_dir / "render_targets.s0ma.json").is_file()


class TestEmittedHashMatchesRenderedHash:
    def test_register_doc_call_carries_rendered_hash(
        self, tmp_path: Path,
    ) -> None:
        project_dir = _copy_fixture(FIXTURE_DIR, tmp_path / "project")
        output_dir = tmp_path / "out"
        rc = _run_build(project_dir, output_dir)
        assert rc == 0

        py_text = (output_dir / "render_targets.py").read_text()
        md_text = (output_dir / "docs" / "greetings.md").read_text()

        # Pull the hash out of the markdown front-matter and confirm the
        # generated `register_doc_ref` call carries the same value.
        for line in md_text.splitlines():
            if line.startswith("content_hash:"):
                rendered_hash = line.split(":", 1)[1].strip().strip('"')
                break
        else:  # pragma: no cover — defensive
            raise AssertionError("front-matter content_hash missing")

        # The Python emitter writes the hash on a `content_hash="..."`
        # line inside the doc-ref's register call. Search by name to
        # avoid false positives if a future emitter adds more docs.
        assert "register_doc_ref(" in py_text
        assert f'content_hash="{rendered_hash}"' in py_text


class TestBuildPipelineDeterminism:
    def test_repeat_build_byte_equal(self, tmp_path: Path) -> None:
        project_dir = _copy_fixture(FIXTURE_DIR, tmp_path / "project")

        out_a = tmp_path / "out_a"
        out_b = tmp_path / "out_b"

        rc_a = _run_build(project_dir, out_a)
        rc_b = _run_build(project_dir, out_b)
        assert rc_a == rc_b == 0

        for relpath in (
            Path("docs/greetings.md"),
            Path("docs/greetings.html"),
            Path("docs/greetings.json"),
            Path("docs/walkthrough.md"),
        ):
            a = (out_a / relpath).read_text()
            b = (out_b / relpath).read_text()
            assert a == b, f"non-deterministic render for {relpath}"
