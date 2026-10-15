"""Tests for the M7 ``s0ma docs`` and ``s0ma examples`` CLI subcommands.

Covers:
- ``docs render`` produces the declared output files.
- ``docs render`` reports doc-render errors as exit code 1.
- ``docs verify`` reports validation errors but does not write output.
- ``examples run`` informs cleanly when s0ma-core's runner is available
  (we just check dispatch — actual sandbox execution is exercised by
  s0ma-core).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import S0maCLI

FIXTURES = Path(__file__).parent / "fixtures" / "valid" / "docs" / "full_project"


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    """Copy the full doc-project fixture into a temp directory."""
    target = tmp_path / "project"
    shutil.copytree(FIXTURES, target)
    return target


# ---------------------------------------------------------------------------
# docs render
# ---------------------------------------------------------------------------


class TestDocsRender:
    def test_writes_declared_outputs(self, project_dir: Path, capsys) -> None:
        cli = S0maCLI()
        rc = cli.run(["docs", "render", str(project_dir)])
        assert rc == 0
        # Two outputs from the fixture's doc-ref + doc-guide.
        assert (project_dir / "docs" / "greetings_reference.md").is_file()
        assert (project_dir / "docs" / "greetings_walkthrough.md").is_file()
        out = capsys.readouterr().out
        assert "Rendered 2 doc output(s)" in out

    def test_render_then_modify_render_idempotent(self, project_dir: Path) -> None:
        cli = S0maCLI()
        cli.run(["docs", "render", str(project_dir)])
        first = (project_dir / "docs" / "greetings_reference.md").read_text(
            encoding="utf-8"
        )
        cli.run(["docs", "render", str(project_dir)])
        second = (project_dir / "docs" / "greetings_reference.md").read_text(
            encoding="utf-8"
        )
        # Determinism contract: re-rendering produces identical bytes.
        assert first == second

    def test_no_source_returns_usage_error(self, tmp_path: Path) -> None:
        cli = S0maCLI()
        empty = tmp_path / "empty"
        empty.mkdir()
        rc = cli.run(["docs", "render", str(empty)])
        assert rc == 2


# ---------------------------------------------------------------------------
# docs verify
# ---------------------------------------------------------------------------


class TestDocsVerify:
    def test_clean_project_passes(self, project_dir: Path) -> None:
        cli = S0maCLI()
        rc = cli.run(["docs", "verify", str(project_dir), "--mode", "strict"])
        assert rc == 0

    def test_invalid_reference_fails(self, project_dir: Path, capsys) -> None:
        # Mutate the doc-guide to reference a non-existent nerve.
        guide_path = project_dir / "greetings_docs.s0ma"
        text = guide_path.read_text(encoding="utf-8")
        text = text.replace("nerve::greet", "nerve::missing", 1)
        guide_path.write_text(text, encoding="utf-8")

        cli = S0maCLI()
        rc = cli.run(["docs", "verify", str(project_dir), "--mode", "strict"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "UNRESOLVED_REFERENCE" in out

    def test_does_not_write_output_files(self, project_dir: Path) -> None:
        # Wipe any pre-existing rendered output so we know `verify` is silent.
        docs_dir = project_dir / "docs"
        if docs_dir.exists():
            shutil.rmtree(docs_dir)
        cli = S0maCLI()
        cli.run(["docs", "verify", str(project_dir), "--mode", "strict"])
        assert not docs_dir.exists()


# ---------------------------------------------------------------------------
# examples run
# ---------------------------------------------------------------------------


class TestExamplesRun:
    def test_dispatch_no_examples_succeeds(self, tmp_path: Path) -> None:
        """Source with no example declarations exits cleanly."""
        # Create a no-examples project.
        no_ex = tmp_path / "noex"
        no_ex.mkdir()
        (no_ex / "m.s0ma").write_text(
            "module m\n"
            "    layer: DOMAIN\n"
            "    version: 1.0.0\n"
            "    intent: \"No examples here.\"\n"
            "    exports: []\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n",
            encoding="utf-8",
        )
        cli = S0maCLI()
        rc = cli.run(["examples", "run", str(no_ex)])
        # Either 0 (handler ran) or 3 (s0ma.examples missing); both are
        # acceptable per plan §10. Check we never silently fake a result.
        assert rc in (0, 3)

    def test_run_executes_example_and_reports_result(
        self, tmp_path: Path, capsys
    ) -> None:
        """A project with a real example registers, runs, and reports it."""
        src = tmp_path / "exproj"
        src.mkdir()
        (src / "hello_proj.s0ma").write_text(
            "module hello_proj\n"
            "    layer: DOMAIN\n"
            "    version: 1.0.0\n"
            "    intent: \"Hosts a runnable example for the CLI happy path.\"\n"
            "    exports: [hello]\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "\n"
            "nerve hello :: DOMAIN\n"
            "    kind: FUNCTION\n"
            "    visibility: PUBLIC\n"
            "    intent: \"Says hi.\"\n"
            "    expects: \"nothing\"\n"
            "    guarantees: \"prints a greeting\"\n"
            "    forbids: none\n"
            "    evaluates_at: FUNCTION_BOUNDARY\n"
            "    provides: none\n"
            "    returns: none\n"
            "    raises: none\n"
            "    interface: none\n"
            "    latency_ms: none\n"
            "    depends_on: none\n"
            "    internal: none\n"
            "    expected_exceptions: none\n"
            "    consumes_via_dict: none\n"
            "    declares_attributes: none\n"
            "    covered_by: none\n"
            "    ---\n"
            "    def hello():\n"
            "        print(\"hi\")\n"
            "\n"
            "example hello_example\n"
            "    intent: \"Demonstrates hello with a self-contained body.\"\n"
            "    demonstrates: [nerve::hello]\n"
            "    runs_in: standalone\n"
            "    ---\n"
            "    print(\"hi\")\n",
            encoding="utf-8",
        )
        cli = S0maCLI()
        rc = cli.run(["examples", "run", str(src), "--format", "json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert [r["name"] for r in payload] == ["hello_example"]
        assert payload[0]["passed"] is True
        assert payload[0]["stdout"].strip() == "hi"

    def test_blocking_errors_refuse_run(self, tmp_path: Path, capsys) -> None:
        """severity=error diagnostics print and exit 1 before any example runs.

        Mirrors the s0ma-mcp ``run_example`` gate: a project with
        blocking diagnostics must not execute even its valid examples.
        The example body writes a sentinel file, so execution (the
        regression) is directly observable.
        """
        src = tmp_path / "badproj"
        src.mkdir()
        sentinel = tmp_path / "example_ran.txt"
        (src / "broken.s0ma").write_text(
            "module broken\n"
            "    intent: \"Missing required layer and version fields.\"\n",
            encoding="utf-8",
        )
        (src / "good_proj.s0ma").write_text(
            "module good_proj\n"
            "    layer: DOMAIN\n"
            "    version: 1.0.0\n"
            "    intent: \"Valid module whose example must not run.\"\n"
            "    exports: [touch]\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "\n"
            "nerve touch :: DOMAIN\n"
            "    kind: FUNCTION\n"
            "    visibility: PUBLIC\n"
            "    intent: \"Touches a sentinel file.\"\n"
            "    expects: \"nothing\"\n"
            "    guarantees: \"writes a sentinel file\"\n"
            "    forbids: none\n"
            "    evaluates_at: FUNCTION_BOUNDARY\n"
            "    provides: none\n"
            "    returns: none\n"
            "    raises: none\n"
            "    interface: none\n"
            "    latency_ms: none\n"
            "    depends_on: none\n"
            "    internal: none\n"
            "    expected_exceptions: none\n"
            "    consumes_via_dict: none\n"
            "    declares_attributes: none\n"
            "    covered_by: none\n"
            "    ---\n"
            "    def touch():\n"
            "        pass\n"
            "\n"
            "example sentinel_example\n"
            "    intent: \"Writes a sentinel file if it ever executes.\"\n"
            "    demonstrates: [nerve::touch]\n"
            "    runs_in: standalone\n"
            "    ---\n"
            "    from pathlib import Path\n"
            f"    Path({str(sentinel)!r}).write_text(\"ran\", encoding=\"utf-8\")\n",
            encoding="utf-8",
        )
        cli = S0maCLI()
        rc = cli.run(["examples", "run", str(src)])
        assert rc == 1
        out = capsys.readouterr().out
        assert "SEMANTIC_REQUIRED_STATE_OMITTED" in out
        assert not sentinel.exists()


# ---------------------------------------------------------------------------
# W-3 / INV-5 (Windows plan M2): rendered doc outputs are LF on every OS.
# ---------------------------------------------------------------------------


class TestDocOutputsAreLFBytes:
    def test_rendered_docs_are_lf_bytes(self, project_dir: Path) -> None:
        """Asserted in BYTES space — on Windows an unpinned writer
        would emit CRLF and break the cross-OS byte-identity contract."""
        cli = S0maCLI()
        rc = cli.run(["docs", "render", str(project_dir)])
        assert rc == 0
        for name in ("greetings_reference.md", "greetings_walkthrough.md"):
            data = (project_dir / "docs" / name).read_bytes()
            assert b"\r" not in data, f"{name}: CR byte in rendered doc"
            assert data.endswith(b"\n")


# ---------------------------------------------------------------------------
# DSL-M4 (F-M5-4): doc output base-dir agreement.
#
# `s0ma build`, `s0ma docs render`, and `s0ma docs check-drift` must
# resolve declared `output:` paths against the SAME base directory for a
# `[tool.s0ma]` project — the configured build_dir — so the drift gate
# checks the directory the build actually writes to. Before the M4 fix,
# the docs commands resolved against the project root (ignoring build_dir),
# so a committed-build project wrote docs to `<build_dir>/docs/` while
# `check-drift` looked in `<root>/docs/` and reported spurious drift.
# ---------------------------------------------------------------------------


def _build_dir_project(tmp_path: Path) -> Path:
    """A `[tool.s0ma]` project with a non-default build_dir + one doc-ref."""
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "basedir-agreement"\n'
        'version = "0.1.0"\n'
        "[tool.s0ma]\n"
        'source_roots = ["src"]\n'
        'build_dir = "_built"\n',
        encoding="utf-8",
    )
    (root / "src" / "widgets.s0ma").write_text(
        "module widgets\n"
        "    layer: DOMAIN\n"
        "    version: 1.0.0\n"
        '    intent: "Widget module for the base-dir agreement test."\n'
        "    exports: [make]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "\n"
        "nerve make :: DOMAIN\n"
        "    kind: FUNCTION\n"
        "    visibility: PUBLIC\n"
        '    intent: "Produces a widget label for the supplied id."\n'
        '    expects: "wid is a non-empty string."\n'
        '    guarantees: "Returns a label string."\n'
        '    forbids: none\n'
        "    evaluates_at: FUNCTION_BOUNDARY\n"
        "    provides: none\n"
        "    returns: none\n"
        "    raises: none\n"
        "    interface: none\n"
        "    latency_ms: none\n"
        "    depends_on: none\n"
        "    internal: none\n"
        "    expected_exceptions: none\n"
        "    consumes_via_dict: none\n"
        "    declares_attributes: none\n"
        "    covered_by: none\n"
        "    ---\n"
        "    def make(wid: str) -> str:\n"
        '        return f"widget:{wid}"\n'
        "\n"
        "doc-ref widget_api\n"
        '    intent: "Generated reference for widgets public nerves."\n'
        "    format: markdown\n"
        "    output: docs/widget_api.md\n"
        "    covers: [nerve where module == widgets]\n"
        "    sections: [intent, expects, guarantees]\n",
        encoding="utf-8",
    )
    return root


class TestDocsBaseDirAgreement:
    def test_build_writes_docs_under_build_dir(self, tmp_path: Path) -> None:
        root = _build_dir_project(tmp_path)
        cli = S0maCLI()
        rc = cli.run(["--project-root", str(root), "build", str(root),
                      "--mode", "dev", "--quiet"])
        assert rc == 0
        # The build resolves output: against build_dir, not the project root.
        assert (root / "_built" / "docs" / "widget_api.md").is_file()
        assert not (root / "docs" / "widget_api.md").exists()

    def test_check_drift_agrees_with_build(self, tmp_path: Path) -> None:
        root = _build_dir_project(tmp_path)
        cli = S0maCLI()
        assert cli.run(["--project-root", str(root), "build", str(root),
                        "--mode", "dev", "--quiet"]) == 0
        # check-drift resolves the SAME base (build_dir) — the freshly built
        # doc is present and byte-current, so no drift (exit 0).
        rc = cli.run(["--project-root", str(root), "docs", "check-drift",
                      str(root), "--mode", "strict"])
        assert rc == 0

    def test_render_agrees_with_build(self, tmp_path: Path) -> None:
        root = _build_dir_project(tmp_path)
        cli = S0maCLI()
        assert cli.run(["--project-root", str(root), "build", str(root),
                        "--mode", "dev", "--quiet"]) == 0
        built = (root / "_built" / "docs" / "widget_api.md")
        from_build = built.read_bytes()
        built.unlink()
        # docs render targets the same build_dir base and re-emits the
        # byte-identical file the build produced.
        rc = cli.run(["--project-root", str(root), "docs", "render", str(root),
                      "--mode", "dev"])
        assert rc == 0
        assert built.is_file()
        assert built.read_bytes() == from_build
        assert not (root / "docs" / "widget_api.md").exists()

    def test_explicit_output_dir_still_wins(self, tmp_path: Path) -> None:
        # An explicit --output-dir overrides the project build_dir, matching
        # the build path's precedence (--output-dir > build_dir > source).
        root = _build_dir_project(tmp_path)
        out = tmp_path / "elsewhere"
        cli = S0maCLI()
        rc = cli.run(["--project-root", str(root), "docs", "render", str(root),
                      "--output-dir", str(out), "--mode", "dev"])
        assert rc == 0
        assert (out / "docs" / "widget_api.md").is_file()
        assert not (root / "_built" / "docs" / "widget_api.md").exists()
