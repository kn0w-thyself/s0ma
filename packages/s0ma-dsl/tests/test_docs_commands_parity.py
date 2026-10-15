"""Base-directory parity across the three ``s0ma docs`` subcommands (A8 T1).

``render``, ``verify`` and ``check-drift`` all render through the same M6
pipeline, so they must agree on the base directory that declared
``output:`` paths resolve against. Before A8 they did not: ``verify``
computed its base from the source path directly and its subparser had no
``--output-dir``, so a project-form invocation had ``render`` writing
under ``<build_dir>/`` while ``verify`` validated against the project
root — a clean ``verify`` could sit next to a drifting ``check-drift``.

These tests pin the parity in two independent ways:

1. structurally — :func:`_resolve_docs_base_dir` returns the identical
   path for namespaces parsed from all three subcommands, and
2. behaviourally — the ``base_dir`` each handler actually hands to
   ``_run_doc_pipeline`` is identical, captured through the real
   ``S0maCLI.run`` argv path.

Each is checked for all three invocation forms: project-form (a
``[tool.s0ma]`` table with a ``build_dir``), explicit ``--output-dir``,
and bare-source (no project reachable).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.cli import docs_commands
from s0ma_dsl.cli.docs_commands import _resolve_docs_base_dir
from s0ma_dsl.cli.main import S0maCLI, _resolve_project

if TYPE_CHECKING:
    import argparse

FIXTURES = Path(__file__).parent / "fixtures" / "valid" / "docs" / "full_project"

# The three subcommands under parity. ``render`` is the reference
# implementation; the other two must match it.
_SUBCOMMANDS = ("render", "verify", "check-drift")


def _make_project(root: Path, *, build_dir: str = "build_out") -> Path:
    """Materialise a ``[tool.s0ma]`` project holding the docs fixture.

    Returns the project root. Sources live under ``src/`` so the declared
    ``source_roots`` entry points at a directory that exists.
    """
    root.mkdir(parents=True, exist_ok=True)
    src = root / "src"
    shutil.copytree(FIXTURES, src)
    (root / "pyproject.toml").write_text(
        dedent(f"""
            [project]
            name = "parityproj"
            version = "0.1.0"

            [tool.s0ma]
            source_roots = ["src"]
            build_dir = "{build_dir}"
        """).lstrip(),
        encoding="utf-8",
    )
    return root


def _make_bare_source(root: Path) -> Path:
    """Materialise a source directory with no ``[tool.s0ma]`` anywhere above."""
    src = root / "bare"
    shutil.copytree(FIXTURES, src)
    return src


def _namespace(argv: list[str]) -> argparse.Namespace:
    """Parse *argv* the way ``S0maCLI.run`` does, project resolution included."""
    args = S0maCLI().build_parser().parse_args(argv)
    args.s0ma_project = _resolve_project(args)
    return args


def _argv_for(sub: str, *, project_root: Path, source: Path,
              output_dir: Path | None = None) -> list[str]:
    argv = ["--project-root", str(project_root), "docs", sub, str(source)]
    if output_dir is not None:
        argv += ["--output-dir", str(output_dir)]
    return argv


# ---------------------------------------------------------------------------
# 1. Structural parity — the resolver agrees across subcommands
# ---------------------------------------------------------------------------


class TestResolvedBaseParity:
    def test_project_form_resolves_build_dir_for_all_three(
        self, tmp_path: Path,
    ) -> None:
        project = _make_project(tmp_path / "proj")
        bases = {
            sub: _resolve_docs_base_dir(_namespace(
                _argv_for(sub, project_root=project, source=project / "src"),
            ))
            for sub in _SUBCOMMANDS
        }
        assert len(set(bases.values())) == 1, bases
        # ...and the one base is the project's build_dir, not the source dir.
        assert bases["verify"] == (project / "build_out").resolve()

    def test_output_dir_form_resolves_explicit_dir_for_all_three(
        self, tmp_path: Path,
    ) -> None:
        project = _make_project(tmp_path / "proj")
        explicit = tmp_path / "elsewhere"
        bases = {
            sub: _resolve_docs_base_dir(_namespace(_argv_for(
                sub,
                project_root=project,
                source=project / "src",
                output_dir=explicit,
            )))
            for sub in _SUBCOMMANDS
        }
        assert len(set(bases.values())) == 1, bases
        # An explicit override wins over the project's build_dir.
        assert bases["verify"] == explicit

    def test_bare_source_form_resolves_source_dir_for_all_three(
        self, tmp_path: Path,
    ) -> None:
        bare_root = tmp_path / "noproject"
        source = _make_bare_source(bare_root)
        bases = {
            sub: _resolve_docs_base_dir(_namespace(
                _argv_for(sub, project_root=bare_root, source=source),
            ))
            for sub in _SUBCOMMANDS
        }
        assert len(set(bases.values())) == 1, bases
        assert bases["verify"] == source

    def test_bare_single_file_form_resolves_parent_for_all_three(
        self, tmp_path: Path,
    ) -> None:
        bare_root = tmp_path / "noproject"
        source_dir = _make_bare_source(bare_root)
        one_file = source_dir / "greetings_docs.s0ma"
        assert one_file.is_file()
        bases = {
            sub: _resolve_docs_base_dir(_namespace(
                _argv_for(sub, project_root=bare_root, source=one_file),
            ))
            for sub in _SUBCOMMANDS
        }
        assert len(set(bases.values())) == 1, bases
        assert bases["verify"] == source_dir


# ---------------------------------------------------------------------------
# 2. Behavioural parity — the handlers pass that base to the pipeline
# ---------------------------------------------------------------------------


class _PipelineProbe:
    """Records the ``base_dir`` each handler hands to ``_run_doc_pipeline``.

    The pipeline is stubbed so nothing is parsed or written: the point is
    the argument, not the render. ``modules`` comes back non-empty so the
    handlers take their normal path instead of the "no .s0ma files"
    usage-error path.
    """

    def __init__(self) -> None:
        self.bases: dict[str, Path] = {}
        self._running: str = ""

    def __call__(
        self, source: str, mode: Any, *, base_dir: Path,
    ) -> tuple[Any, ...]:
        self.bases[self._running] = base_dir
        return ({"stub_module": None}, {}, None, None, {}, [])

    def run_all_three(
        self,
        *,
        project_root: Path,
        source: Path,
        output_dir: Path | None = None,
    ) -> dict[str, Path]:
        cli = S0maCLI()
        for sub in _SUBCOMMANDS:
            self._running = sub
            rc = cli.run(_argv_for(
                sub,
                project_root=project_root,
                source=source,
                output_dir=output_dir,
            ))
            assert rc == 0, f"{sub} exited {rc}"
        assert set(self.bases) == set(_SUBCOMMANDS)
        return dict(self.bases)


@pytest.fixture()
def probe(monkeypatch) -> _PipelineProbe:
    p = _PipelineProbe()
    monkeypatch.setattr(docs_commands, "_run_doc_pipeline", p)
    return p


class TestHandlerBaseParity:
    def test_project_form(self, tmp_path: Path, probe: _PipelineProbe) -> None:
        project = _make_project(tmp_path / "proj")
        bases = probe.run_all_three(
            project_root=project, source=project / "src",
        )
        assert len(set(bases.values())) == 1, bases
        assert bases["verify"] == (project / "build_out").resolve()

    def test_output_dir_form(self, tmp_path: Path, probe: _PipelineProbe) -> None:
        project = _make_project(tmp_path / "proj")
        explicit = tmp_path / "elsewhere"
        bases = probe.run_all_three(
            project_root=project,
            source=project / "src",
            output_dir=explicit,
        )
        assert len(set(bases.values())) == 1, bases
        assert bases["verify"] == explicit

    def test_bare_source_form(self, tmp_path: Path, probe: _PipelineProbe) -> None:
        bare_root = tmp_path / "noproject"
        source = _make_bare_source(bare_root)
        bases = probe.run_all_three(project_root=bare_root, source=source)
        assert len(set(bases.values())) == 1, bases
        assert bases["verify"] == source


# ---------------------------------------------------------------------------
# 3. The flag itself, and verify's preserved semantics
# ---------------------------------------------------------------------------


class TestVerifyOutputDirFlag:
    @pytest.mark.parametrize("flag", ["--output-dir", "-o"])
    def test_verify_accepts_the_flag_in_both_spellings(
        self, tmp_path: Path, flag: str,
    ) -> None:
        args = S0maCLI().build_parser().parse_args(
            ["docs", "verify", str(tmp_path), flag, str(tmp_path / "out")],
        )
        assert args.output_dir == str(tmp_path / "out")

    def test_verify_default_output_dir_is_none(self, tmp_path: Path) -> None:
        args = S0maCLI().build_parser().parse_args(
            ["docs", "verify", str(tmp_path)],
        )
        assert args.output_dir is None


class TestVerifySemanticsPreserved:
    """A8 T1 is a base-resolution fix — verify's contract is unchanged."""

    def test_clean_project_still_passes(self, tmp_path: Path) -> None:
        source = _make_bare_source(tmp_path / "noproject")
        rc = S0maCLI().run([
            "--project-root", str(tmp_path / "noproject"),
            "docs", "verify", str(source), "--mode", "strict",
        ])
        assert rc == 0

    def test_broken_reference_still_fails(self, tmp_path: Path) -> None:
        source = _make_bare_source(tmp_path / "noproject")
        guide = source / "greetings_docs.s0ma"
        text = guide.read_text(encoding="utf-8")
        guide.write_text(text.replace("nerve::greet", "nerve::missing", 1),
                         encoding="utf-8")
        rc = S0maCLI().run([
            "--project-root", str(tmp_path / "noproject"),
            "docs", "verify", str(source), "--mode", "strict",
        ])
        assert rc == 1

    def test_empty_source_still_usage_error(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        rc = S0maCLI().run([
            "--project-root", str(tmp_path), "docs", "verify", str(empty),
        ])
        assert rc == 2

    def test_verify_writes_no_output_files(self, tmp_path: Path) -> None:
        """Verify renders in memory only — even with an --output-dir."""
        project = _make_project(tmp_path / "proj")
        out = project / "build_out"
        rc = S0maCLI().run([
            "--project-root", str(project),
            "docs", "verify", str(project / "src"), "--mode", "strict",
            "--output-dir", str(out),
        ])
        assert rc == 0
        assert not out.exists()
