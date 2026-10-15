"""``s0ma adopt file`` — first-class adopted files (0.11.0, batch-01a D2).

Locks down the adoption primitive end-to-end:

- ``s0ma adopt file <path>`` records the project-root-relative POSIX
  path + content hash in the committed ``adopted.s0ma.json`` sidecar
  (deterministic bytes), idempotently (re-adopt refreshes the hash).
- Refusals: no ``[tool.s0ma]`` project, missing path, path outside the
  project root, transpiled artifacts (hash-headered), files declared
  under ``bootstrap_files``.
- ``s0ma verify`` classifies a hash-matching adopted file ``ADOPTED`` as
  byte-verified roster debt; an adopted-only tree is ``HOLLOW_MODEL`` and
  exits 4. An adopted-then-edited file is ``ADOPTED_DRIFT`` — an actionable
  FAILURE (exit 1) whose message names both ways out: re-adopt
  (``s0ma adopt file`` / MCP ``adopt_file``) or convert to ``.s0ma``.
- ``s0ma score`` splits componentized, roster-adopted, and unknown
  populations. Adoption changes classification but earns no gate credit.
- ``s0ma inspect --all`` lists adopted files with their hashes.

Pairs with ``tests/test_verify_bootstrap.py`` (the M11 classification
contract these tests extend) and ``tests/test_score.py`` (STD-M8).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from s0ma_dsl.adoption import (
    ADOPTED_FILENAME,
    ADOPTED_SCHEMA,
    AdoptedRecordError,
    compute_adopted_hash,
    load_adopted_files,
)
from s0ma_dsl.cli.main import (
    EXIT_NOTHING_VERIFIED,
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    EXIT_VALIDATION_ERROR,
    S0maCLI,
)


@pytest.fixture()
def cli() -> S0maCLI:
    return S0maCLI()


@pytest.fixture()
def project(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> Path:
    """A freshly scaffolded + built project with one stray ``_impl.py``.

    The stray file mirrors the bench hollow-model shape (P2_P_r02): a
    real, hand-written implementation file sitting beside generated
    code in the build dir, carrying no transpiler hash headers and no
    declaration — UNKNOWN to every surface until adopted.
    """
    target = tmp_path / "adoptproj"
    assert cli.run(["new", "project", str(target), "--quiet"]) == EXIT_SUCCESS
    (target / "build" / "legacy_impl.py").write_text(
        "def helper(x: int) -> int:\n    return x * 2\n",
        encoding="utf-8",
    )
    capsys.readouterr()  # drain scaffold output
    return target


def _adopt(
    cli: S0maCLI,
    root: Path,
    path: str,
    *extra: str,
) -> int:
    description_args = (
        () if "--description" in extra
        else ("--description", "Pre-existing legacy implementation.")
    )
    return cli.run([
        "--project-root", str(root),
        "adopt", "file", str(root / path),
        *description_args,
        *extra,
    ])


def _verify_json(
    cli: S0maCLI,
    capsys: pytest.CaptureFixture[str],
    root: Path,
    target: Path,
) -> tuple[int, list[dict[str, Any]]]:
    capsys.readouterr()
    rc = cli.run([
        "--project-root", str(root),
        "verify", str(target),
        "--format", "json",
    ])
    return rc, json.loads(capsys.readouterr().out)


def _score_registration(
    cli: S0maCLI,
    capsys: pytest.CaptureFixture[str],
    root: Path,
) -> dict[str, Any]:
    capsys.readouterr()
    rc = cli.run([
        "--project-root", str(root), "score", "--format", "json",
    ])
    assert rc == EXIT_SUCCESS
    report = json.loads(capsys.readouterr().out)
    metrics = report["faculties"]["proprioception"]["metrics"]
    reg: dict[str, Any] = metrics["registration"]
    return reg


# ---------------------------------------------------------------------------
# 1. The record: relative POSIX path + content hash, deterministic bytes
# ---------------------------------------------------------------------------


class TestAdoptFileCommand:
    def test_legacy_record_without_description_is_named_refusal(
        self, project: Path,
    ) -> None:
        (project / ADOPTED_FILENAME).write_text(json.dumps({
            "schema": ADOPTED_SCHEMA,
            "files": {
                "build/legacy_impl.py": {
                    "path": "build/legacy_impl.py",
                    "content_hash": "sha256:legacy",
                    "metadata": {},
                },
            },
        }), encoding="utf-8")
        with pytest.raises(AdoptedRecordError, match="description is required"):
            load_adopted_files(project)

    def test_adopt_records_relative_posix_path_and_hash(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = _adopt(cli, project, "build/legacy_impl.py")
        assert rc == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "Adopted build/legacy_impl.py" in out
        assert ADOPTED_FILENAME in out

        record_path = project / ADOPTED_FILENAME
        assert record_path.is_file()
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        assert payload["schema"] == ADOPTED_SCHEMA
        entry = payload["files"]["build/legacy_impl.py"]
        assert entry["path"] == "build/legacy_impl.py"
        assert entry["content_hash"] == compute_adopted_hash(
            project / "build" / "legacy_impl.py"
        )
        # Deterministic bytes: trailing newline; re-adoption updates only
        # advisory count while stable fields remain byte-identical.
        raw = record_path.read_text(encoding="utf-8")
        assert raw.endswith("\n")
        assert _adopt(cli, project, "build/legacy_impl.py") == EXIT_SUCCESS
        updated = json.loads(record_path.read_text(encoding="utf-8"))
        assert updated["files"]["build/legacy_impl.py"]["re_adopt_count"] == 1
        assert raw != record_path.read_text(encoding="utf-8")

    def test_the_record_is_lf_on_every_platform(
        self, cli: S0maCLI, project: Path,
    ) -> None:
        """``adopted.s0ma.json`` is committed, so its endings must not vary.

        Written in text mode without pinning the newline, this file is
        CRLF on Windows and LF everywhere else — so the same unchanged
        record diffs whole the first time a Windows machine touches it,
        and the hash-headed artifacts around it do not. Reading the
        bytes is the only way to see it from macOS (friction F-E1-1).
        """
        assert _adopt(cli, project, "build/legacy_impl.py") == EXIT_SUCCESS
        raw = (project / ADOPTED_FILENAME).read_bytes()
        assert b"\r" not in raw
        assert raw.endswith(b"}\n")

    def test_adopt_json_output_and_readopt_flag(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = _adopt(cli, project, "build/legacy_impl.py", "--format", "json")
        first = json.loads(capsys.readouterr().out)
        assert rc == EXIT_SUCCESS
        assert first["ok"] is True
        assert first["schema"] == "s0ma-tool-result@1"
        assert first["status"] == "interim"
        assert first["path"] == "build/legacy_impl.py"
        assert first["content_hash"].startswith("sha256:")
        assert first["re_adopted"] is False
        assert first["re_adopt_count"] == 0
        assert first["next_actions"][0]["tool"] == "author_module"
        assert first["counts"]["roster_adopted"] == 1

        # Edit, then re-adopt: the hash refreshes and the flag flips.
        impl = project / "build" / "legacy_impl.py"
        impl.write_text(
            impl.read_text(encoding="utf-8") + "\n# intentional edit\n",
            encoding="utf-8",
        )
        rc = _adopt(cli, project, "build/legacy_impl.py", "--format", "json")
        second = json.loads(capsys.readouterr().out)
        assert rc == EXIT_SUCCESS
        assert second["re_adopted"] is True
        assert second["re_adopt_count"] == 1
        assert second["content_hash"] != first["content_hash"]
        assert second["content_hash"] == compute_adopted_hash(impl)

    def test_fourth_adoption_emits_advisory_churn_without_gate_input(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        for index in range(4):
            assert _adopt(
                cli, project, "build/legacy_impl.py",
                "--description", "Legacy migration intake.",
                "--format", "json",
            ) == EXIT_SUCCESS
            payload = json.loads(capsys.readouterr().out)
            assert payload["re_adopt_count"] == index
        warning = payload["warnings"][0]
        assert warning["code"] == "ADOPTED_CHURN"
        assert warning["gate_relevant"] is False
        assert warning["next_action"]["tool"] == "author_module"

    def test_description_is_mandatory_and_recorded_on_readopt(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert _adopt(
            cli, project, "build/legacy_impl.py",
            "--description", "legacy helper adopted as-is",
        ) == EXIT_SUCCESS
        assert _adopt(
            cli, project, "build/legacy_impl.py",
            "--description", "legacy helper adopted as-is",
        ) == EXIT_SUCCESS
        records = load_adopted_files(project)
        assert (
            records["build/legacy_impl.py"].description
            == "legacy helper adopted as-is"
        )
        assert records["build/legacy_impl.py"].re_adopt_count == 1

        with pytest.raises(SystemExit) as exc_info:
            cli.run([
                "--project-root", str(project),
                "adopt", "file", str(project / "build/legacy_impl.py"),
            ])
        assert exc_info.value.code == EXIT_USAGE_ERROR
        assert "--description" in capsys.readouterr().err

    def test_refuses_without_project(
        self, cli: S0maCLI, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        stray = tmp_path / "stray.py"
        stray.write_text("x = 1\n", encoding="utf-8")
        rc = cli.run([
            "--project-root", str(tmp_path), "adopt", "file", str(stray),
            "--description", "Stray pre-existing file.",
        ])
        assert rc == EXIT_USAGE_ERROR
        err = capsys.readouterr().err
        assert "[tool.s0ma]" in err
        assert not (tmp_path / ADOPTED_FILENAME).exists()

    def test_refuses_missing_file(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = _adopt(cli, project, "build/nonexistent.py")
        assert rc == EXIT_USAGE_ERROR
        assert "not an existing regular file" in capsys.readouterr().err
        assert not (project / ADOPTED_FILENAME).exists()

    def test_refuses_file_outside_project_root(
        self, cli: S0maCLI, project: Path, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        outside = tmp_path / "outside.py"
        outside.write_text("x = 1\n", encoding="utf-8")
        rc = cli.run([
            "--project-root", str(project), "adopt", "file", str(outside),
            "--description", "Outside pre-existing file.",
        ])
        assert rc == EXIT_USAGE_ERROR
        assert "outside the project root" in capsys.readouterr().err
        assert not (project / ADOPTED_FILENAME).exists()

    def test_refuses_transpiled_artifact(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A hash-headered generated file is already registered — refuse."""
        generated = next(
            p for p in sorted((project / "build").glob("*.py"))
            if "s0ma-output-hash" in p.read_text(encoding="utf-8")
        )
        rc = cli.run([
            "--project-root", str(project), "adopt", "file", str(generated),
            "--description", "Generated file must be refused.",
        ])
        assert rc == EXIT_USAGE_ERROR
        err = capsys.readouterr().err
        assert "transpiled s0ma artifact" in err
        assert "already registered" in err
        assert not (project / ADOPTED_FILENAME).exists()

    def test_refuses_declared_bootstrap_file(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """One classification per file (the G1 conflict rule, extended)."""
        boot = project / "main.py"
        boot.write_text("print('boot')\n", encoding="utf-8")
        pyproject = project / "pyproject.toml"
        # [tool.s0ma] is the final table in the scaffolded pyproject, so
        # an appended key lands inside it.
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8")
            + 'bootstrap_files = ["main.py"]\n',
            encoding="utf-8",
        )
        rc = _adopt(cli, project, "main.py")
        assert rc == EXIT_USAGE_ERROR
        err = capsys.readouterr().err
        assert "bootstrap_files" in err
        assert "exactly one classification" in err
        assert not (project / ADOPTED_FILENAME).exists()


# ---------------------------------------------------------------------------
# 2. Verify: ADOPTED is a verified state; drift is an actionable failure
# ---------------------------------------------------------------------------


class TestVerifyAdopted:
    def test_verify_classifies_adopted_by_content_hash(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert _adopt(cli, project, "build/legacy_impl.py") == EXIT_SUCCESS
        rc, rows = _verify_json(cli, capsys, project, project / "build")
        assert rc == EXIT_SUCCESS
        by_status = {r["status"] for r in rows}
        assert "ADOPTED" in by_status
        assert "UNKNOWN" not in by_status
        adopted_row = next(r for r in rows if r["status"] == "ADOPTED")
        assert adopted_row["file"].endswith("legacy_impl.py")
        assert "registered by adoption" in adopted_row["detail"]
        assert "sha256:" in adopted_row["detail"]

    def test_adopted_then_edited_fails_verify_with_readopt_message(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """THE D2 acceptance case: drift is a failure naming both ways out."""
        assert _adopt(cli, project, "build/legacy_impl.py") == EXIT_SUCCESS
        impl = project / "build" / "legacy_impl.py"
        impl.write_text(
            impl.read_text(encoding="utf-8") + "\n# hand edit after adopt\n",
            encoding="utf-8",
        )
        rc, rows = _verify_json(cli, capsys, project, project / "build")
        assert rc == EXIT_VALIDATION_ERROR
        drifted = next(r for r in rows if r["status"] == "ADOPTED_DRIFT")
        detail = drifted["detail"]
        assert "changed since adoption" in detail
        # Both remediation options, and the exact re-adopt command:
        assert "s0ma adopt file build/legacy_impl.py" in detail
        assert "adopt_file" in detail  # the MCP spelling
        assert "convert it to a .s0ma source" in detail

    def test_verify_text_output_adopted_rows_and_coverage(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert _adopt(cli, project, "build/legacy_impl.py") == EXIT_SUCCESS
        capsys.readouterr()
        rc = cli.run([
            "--project-root", str(project),
            "verify", str(project / "build"),
        ])
        assert rc == EXIT_SUCCESS
        out = capsys.readouterr().out
        # The ADOPTED row is always shown (a verified state, like CLEAN).
        assert any(
            line.lstrip().startswith("ADOPTED ")
            and "legacy_impl.py" in line
            for line in out.splitlines()
        )
        assert "1 adopted file(s) verified." in out
        coverage_line = next(
            line for line in out.splitlines() if line.startswith("Coverage:")
        )
        assert "modeled s0ma module(s)" in coverage_line
        assert "1 roster-adopted file(s)" in coverage_line
        assert "0 unknown plain-Python file(s)" in coverage_line

    def test_verify_summary_unchanged_when_no_adoption(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The frozen coverage triple always includes a zero roster count."""
        capsys.readouterr()
        cli.run([
            "--project-root", str(project),
            "verify", str(project / "build"),
        ])
        out = capsys.readouterr().out
        assert "adopted file(s) verified" not in out
        assert "0 roster-adopted file(s)" in out

    def test_adopted_only_tree_is_hollow_model(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Adoption verifies bytes but cannot create a semantic model."""
        tools_dir = project / "toolscripts"
        tools_dir.mkdir()
        helper = tools_dir / "helper.py"
        helper.write_text("VALUE = 42\n", encoding="utf-8")
        assert _adopt(cli, project, "toolscripts/helper.py") == EXIT_SUCCESS
        rc, rows = _verify_json(cli, capsys, project, tools_dir)
        assert rc == EXIT_NOTHING_VERIFIED
        assert [r["status"] for r in rows] == ["ADOPTED", "HOLLOW_MODEL"]
        assert rows[-1]["code"] == "HOLLOW_MODEL"

    def test_corrupt_record_fails_verify_loudly(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (project / ADOPTED_FILENAME).write_text(
            "not json at all\n", encoding="utf-8",
        )
        capsys.readouterr()
        rc = cli.run([
            "--project-root", str(project),
            "verify", str(project / "build"),
        ])
        assert rc == EXIT_VALIDATION_ERROR
        assert "not readable JSON" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 3. Score: the hollow-model fix, end-to-end (bench P2_P_r02 shape)
# ---------------------------------------------------------------------------


class TestScoreCountsAdopted:
    def test_adoption_changes_roster_classification_not_gate_credit(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Adoption makes debt explicit without raising componentized credit."""
        before = _score_registration(cli, capsys, project)
        assert before["unknown"] == 1
        assert before["roster_adopted"] == 0
        assert before["componentized_pct"] is not None

        assert _adopt(cli, project, "build/legacy_impl.py") == EXIT_SUCCESS

        after = _score_registration(cli, capsys, project)
        assert after["unknown"] == 0
        assert after["roster_adopted"] == 1
        assert after["componentized"] == before["componentized"]
        assert after["componentized_pct"] == before["componentized_pct"]
        assert after["combined_pct"] == 100.0
        assert "1 roster-adopted" in after["detail"]


# ---------------------------------------------------------------------------
# 4. Inspect: adopted files listed with their hashes
# ---------------------------------------------------------------------------


class TestInspectAdopted:
    def test_inspect_all_lists_adopted_files_with_hashes(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert _adopt(cli, project, "build/legacy_impl.py") == EXIT_SUCCESS
        expected_hash = compute_adopted_hash(
            project / "build" / "legacy_impl.py"
        )
        capsys.readouterr()
        rc = cli.run(["--project-root", str(project), "inspect", "--all"])
        assert rc == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "Adopted files (1):" in out
        assert f"build/legacy_impl.py  {expected_hash}" in out

    def test_inspect_all_marks_missing_adopted_file(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert _adopt(cli, project, "build/legacy_impl.py") == EXIT_SUCCESS
        (project / "build" / "legacy_impl.py").unlink()
        capsys.readouterr()
        rc = cli.run(["--project-root", str(project), "inspect", "--all"])
        assert rc == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "(missing on disk)" in out

    def test_inspect_all_silent_when_nothing_adopted(
        self, cli: S0maCLI, project: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        capsys.readouterr()
        rc = cli.run(["--project-root", str(project), "inspect", "--all"])
        assert rc == EXIT_SUCCESS
        assert "Adopted files" not in capsys.readouterr().out
