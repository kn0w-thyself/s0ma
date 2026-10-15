"""Tests for ``s0ma doctor`` (FR-DSL-5 v1.1, UX-M3).

Covers (per the UX phase-1 plan, M3 step 4): doctor on (a) the
monorepo itself, (b) a temp project across the fresh → stale → unbuilt
→ orphaned arc, and (c) a bare directory — plus the malformed
``[tool.s0ma]`` finding (never a crash), the exact FR-COM placeholder
strings (D-2), and the diagnose-don't-gate exit-code contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.cli.doctor import (
    LICENSE_PLACEHOLDER,
    MCP_HINT,
    STUDI0_HINT,
    UPDATE_CHECK_PLACEHOLDER,
)
from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI

#: The monorepo root (tests run with cwd = packages/s0ma-dsl under
#: check.py — every doctor invocation passes --project-root explicitly).
REPO_ROOT = Path(__file__).resolve().parents[3]

SECTION_KEYS = {"ok", "versions", "project", "mcp", "license", "update_check", "findings"}


@pytest.fixture
def cli() -> S0maCLI:
    return S0maCLI()


def _doctor_json(
    cli: S0maCLI, capsys: pytest.CaptureFixture[str], root: Path
) -> tuple[int, dict[str, Any]]:
    rc = cli.run(["--project-root", str(root), "doctor", "--format", "json"])
    return rc, json.loads(capsys.readouterr().out)


@pytest.fixture
def temp_project(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> Path:
    """A freshly initialized + built project (via ``s0ma new project``)."""
    target = tmp_path / "docproj"
    assert cli.run(["new", "project", str(target), "--quiet"]) == EXIT_SUCCESS
    capsys.readouterr()  # drain the summary line before the test reads JSON
    return target


# ---------------------------------------------------------------------------
# (a) The monorepo itself
# ---------------------------------------------------------------------------


class TestDoctorOnTheMonorepo:
    def test_exits_zero_with_every_section_present(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc, report = _doctor_json(cli, capsys, REPO_ROOT)

        assert rc == EXIT_SUCCESS
        assert set(report) >= SECTION_KEYS
        assert report["ok"] is True
        versions = report["versions"]
        # core + dsl resolve from the workspace; s0ma-mcp/s0ma-studi0/
        # mcp_sdk are tolerated as None (core+dsl-only installs
        # supported, INV-6 — both packages are optional add-ons).
        assert versions["python"]
        assert versions["s0ma_core"]
        assert versions["s0ma_dsl"]
        assert "s0ma_mcp" in versions
        assert "s0ma_studi0" in versions
        assert "mcp_sdk" in versions

    def test_placeholders_are_labeled_exactly(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The FR-COM placeholders ship with these exact strings (D-2)."""
        _, report = _doctor_json(cli, capsys, REPO_ROOT)

        assert report["license"] == "not required in this version"
        assert report["update_check"] == (
            "offline in this version — see PRD §7.5 (FR-COM-4)"
        )
        # The module constants the CLI renders from match, too.
        assert report["license"] == LICENSE_PLACEHOLDER
        assert report["update_check"] == UPDATE_CHECK_PLACEHOLDER

    def test_mcp_section_is_consistent_and_carries_the_hint(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _, report = _doctor_json(cli, capsys, REPO_ROOT)

        mcp = report["mcp"]
        assert mcp["registration_hint"] == MCP_HINT == (
            "claude mcp add s0ma -- s0ma-mcp"
        )
        assert mcp["found"] == (mcp["server_executable"] is not None)


class TestOptionalDistributions:
    """s0ma-studi0 is an add-on: absence is diagnosed, never failed (INV-6).

    The same contract s0ma-mcp has had since FR-DSL-5 v1.1 — the viewer
    joined the versions block at studi0-v1 M7.
    """

    @staticmethod
    def _without_studi0(monkeypatch: pytest.MonkeyPatch) -> None:
        """Report s0ma-studi0 as absent, leaving every other lookup real."""
        from s0ma_dsl.cli import doctor

        installed = doctor._dist_version
        monkeypatch.setattr(
            doctor,
            "_dist_version",
            lambda name: None if name == "s0ma-studi0" else installed(name),
        )

    def test_absence_is_an_info_finding_and_still_exits_zero(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._without_studi0(monkeypatch)

        rc, report = _doctor_json(cli, capsys, tmp_path)

        assert rc == EXIT_SUCCESS
        assert report["ok"] is True
        assert report["versions"]["s0ma_studi0"] is None
        studi0 = [
            f
            for f in report["findings"]
            if f["section"] == "versions" and "s0ma-studi0" in f["message"]
        ]
        assert len(studi0) == 1, studi0
        assert studi0[0]["severity"] == "info", studi0[0]
        assert STUDI0_HINT in studi0[0]["remediation"]

    def test_absence_renders_as_not_installed(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._without_studi0(monkeypatch)

        rc = cli.run(["--project-root", str(tmp_path), "doctor"])

        assert rc == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "s0ma-studi0 not installed" in out


# ---------------------------------------------------------------------------
# (b) A temp project: fresh → stale → unbuilt → orphaned
# ---------------------------------------------------------------------------


class TestDoctorOnATempProject:
    def test_fresh_project(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        temp_project: Path,
    ) -> None:
        rc, report = _doctor_json(cli, capsys, temp_project)

        assert rc == EXIT_SUCCESS
        project = report["project"]
        assert project["is_project"] is True
        assert project["root"] == str(temp_project)
        assert project["mode"] == "dev"
        # STD-M4: a fresh `new project` defaults to authoring-on.
        assert project["authoring"] == "on"
        # STD-M6: a fresh feature-first project ships three built modules —
        # the starter feature module, the project-wide app map, and the
        # mirrored starter test (the first build builds src + tests, so the
        # project is fully built and doctor-clean out of the box).
        assert project["module_count"] == 3
        assert {m["name"] for m in project["modules"]} == {
            "core_domain",
            "app_map",
            "core_domain_tests",
        }
        assert all(m["status"] == "fresh" for m in project["modules"])
        assert project["build"]["built"] is True
        assert project["build"]["status"] == "fresh"
        assert project["build"]["stale_modules"] == []
        assert project["build"]["transpiler_version"]
        assert project["suggested_next_action"] == "run `s0ma check`"

    def test_authoring_off_is_reported_in_json(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        temp_project: Path,
    ) -> None:
        """STD-M4: ``[tool.s0ma].authoring = "off"`` surfaces verbatim."""
        # ``new project`` already wrote ``authoring = "on"`` — flip it in
        # place (appending a second key would be a duplicate-key TOML
        # error, not the off posture).
        pyproject = temp_project / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8").replace(
                'authoring = "on"', 'authoring = "off"'
            ),
            encoding="utf-8",
        )
        _, report = _doctor_json(cli, capsys, temp_project)
        assert report["project"]["authoring"] == "off"

    def test_authoring_renders_in_text(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        temp_project: Path,
    ) -> None:
        """STD-M4: the posture renders in the human ``project`` section."""
        rc = cli.run(["--project-root", str(temp_project), "doctor"])
        assert rc == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "authoring   on" in out

    def test_stale_after_a_source_edit(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        temp_project: Path,
    ) -> None:
        # STD-M6 feature-first: the starter module lives in its feature dir.
        source = temp_project / "src" / "core" / "core_domain.s0ma"
        source.write_text(
            source.read_text(encoding="utf-8") + "\n", encoding="utf-8"
        )

        rc, report = _doctor_json(cli, capsys, temp_project)

        assert rc == EXIT_SUCCESS, "stale is a finding, not a gate"
        project = report["project"]
        assert project["build"]["status"] == "stale"
        assert project["build"]["stale_modules"] == ["core_domain"]
        stale = {
            m["name"]: m["status"] for m in project["modules"]
        }
        assert stale["core_domain"] == "stale"
        assert stale["app_map"] == "fresh"
        assert stale["core_domain_tests"] == "fresh"
        assert project["suggested_next_action"] == (
            "run `s0ma build` — 1 module stale"
        )
        assert any(
            f["severity"] == "warning" and f["section"] == "project"
            for f in report["findings"]
        )

    def test_unbuilt_second_module(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        temp_project: Path,
    ) -> None:
        assert (
            cli.run(
                [
                    "new",
                    "module",
                    "Extra",
                    "-o",
                    str(temp_project / "src"),
                ]
            )
            == EXIT_SUCCESS
        )
        capsys.readouterr()  # drop the scaffold chatter

        rc, report = _doctor_json(cli, capsys, temp_project)

        assert rc == EXIT_SUCCESS
        statuses = {
            m["name"]: m["status"] for m in report["project"]["modules"]
        }
        # STD-M6: the fresh feature-first trio plus the new unbuilt module.
        assert statuses == {
            "core_domain": "fresh",
            "app_map": "fresh",
            "core_domain_tests": "fresh",
            "extra": "unbuilt",
        }
        assert report["project"]["build"]["status"] == "stale"

    def test_orphaned_after_source_removal(
        self,
        cli: S0maCLI,
        capsys: pytest.CaptureFixture[str],
        temp_project: Path,
    ) -> None:
        # STD-M6 feature-first: remove the starter module from its feature
        # dir; the app map's built artifact remains, so the removed module
        # is the orphan.
        (temp_project / "src" / "core" / "core_domain.s0ma").unlink()

        rc, report = _doctor_json(cli, capsys, temp_project)

        assert rc == EXIT_SUCCESS
        modules = {m["name"]: m["status"] for m in report["project"]["modules"]}
        assert modules["core_domain"] == "orphaned"
        assert modules["app_map"] == "fresh"
        assert modules["core_domain_tests"] == "fresh"

    def test_unbuilt_project(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """A configured project that was never built."""
        target = tmp_path / "neverbuilt"
        src = target / "src"
        src.mkdir(parents=True)
        (target / "pyproject.toml").write_text(
            '[project]\nname = "neverbuilt"\n\n'
            '[tool.s0ma]\nsource_roots = ["src"]\nbuild_dir = "build"\n',
            encoding="utf-8",
        )
        (src / "thing.s0ma").write_text("module thing\n", encoding="utf-8")

        rc, report = _doctor_json(cli, capsys, target)

        assert rc == EXIT_SUCCESS
        project = report["project"]
        assert project["build"]["built"] is False
        assert project["build"]["status"] == "unbuilt"
        assert project["modules"][0]["status"] == "unbuilt"
        assert project["suggested_next_action"] == (
            "run `s0ma build` — project not built yet"
        )

    def test_malformed_table_is_a_finding_not_a_crash(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        target = tmp_path / "malformed"
        target.mkdir()
        (target / "pyproject.toml").write_text(
            '[project]\nname = "malformed"\n\n'
            '[tool.s0ma]\ntest_runner = "unittest"\n',
            encoding="utf-8",
        )

        rc, report = _doctor_json(cli, capsys, target)

        assert rc == EXIT_SUCCESS, "doctor diagnoses, it does not gate"
        project = report["project"]
        assert project["is_project"] is False
        assert "test_runner" in project["config_error"]
        assert any(
            f["severity"] == "error"
            and f["section"] == "project"
            and "[tool.s0ma] is malformed" in f["message"]
            for f in report["findings"]
        )


# ---------------------------------------------------------------------------
# (c) A bare directory
# ---------------------------------------------------------------------------


class TestDoctorOnABareDir:
    def test_bare_dir_reports_no_project_and_exits_zero(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        rc, report = _doctor_json(cli, capsys, tmp_path)

        assert rc == EXIT_SUCCESS
        assert set(report) >= SECTION_KEYS
        project = report["project"]
        assert project["is_project"] is False
        assert project["searched_from"] == str(tmp_path)
        assert any(
            f["section"] == "project" and "s0ma new project" in f["remediation"]
            for f in report["findings"]
        ), "the remediation must point at `s0ma new project`"


# ---------------------------------------------------------------------------
# Text rendering (derived from the same structured report, P-5)
# ---------------------------------------------------------------------------


class TestDoctorTextRendering:
    def test_sections_and_placeholders_render(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        rc = cli.run(["--project-root", str(tmp_path), "doctor"])

        assert rc == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert out.startswith("s0ma doctor")
        for heading in ("versions", "project", "mcp", "findings"):
            assert f"\n{heading}\n" in out
        # Every distribution the versions block enumerates gets a row,
        # installed or not (the optional add-ons render "not installed"),
        # so this holds in any environment the suite runs in.
        for label in (
            "python",
            "s0ma-core",
            "s0ma-dsl",
            "s0ma-mcp",
            "s0ma-studi0",
            "mcp SDK",
        ):
            assert f"\n  {label:<12}" in out
        assert "license       not required in this version" in out
        assert (
            "update check  offline in this version — see PRD §7.5 (FR-COM-4)"
            in out
        )
        assert "register    claude mcp add s0ma -- s0ma-mcp" in out
        assert "\nok — " in out

    def test_findings_carry_remediations_in_text(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        rc = cli.run(["--project-root", str(tmp_path), "doctor"])

        assert rc == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "[info] project:" in out
        assert "-> Run `s0ma new project <dir>`" in out


# ---------------------------------------------------------------------------
# (e) Mid-retrofit: the greenfield advice is the wrong advice (G3b)
# ---------------------------------------------------------------------------


_BROWNFIELD = Path(__file__).parent / "fixtures" / "brownfield"


def _retrofitting(cli: S0maCLI, tmp_path: Path, name: str, *roots: str) -> Path:
    """A brownfield fixture copied and taken through rung 1 for real."""
    import shutil

    root = tmp_path / name
    shutil.copytree(
        _BROWNFIELD / name, root, ignore=shutil.ignore_patterns("__pycache__")
    )
    argv = ["--project-root", str(root), "adopt", "init"]
    for named in roots:
        argv += ["--source-root", named]
    assert cli.run(argv) == EXIT_SUCCESS
    return root


class TestDoctorMidRetrofit:
    """G1's H-2 and the pilot's G2-13: doctor defers to the ladder.

    Seconds after ``adopt init``, ``s0ma doctor`` said the next step was
    ``s0ma new module <Name> -o src`` while ``s0ma adopt status`` said
    ``s0ma adopt baseline bookshelf.config``. The trial's agent trusted
    the one the card names — and recorded the contradiction as the kind
    of thing that costs a tool its user's trust.
    """

    def test_it_points_at_the_ladder_rather_than_the_greenfield_command(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        root = _retrofitting(cli, tmp_path, "layered_app")
        capsys.readouterr()

        rc, report = _doctor_json(cli, capsys, root)

        assert rc == EXIT_SUCCESS
        suggested = report["project"]["suggested_next_action"]
        assert suggested == "mid-retrofit — `s0ma adopt status` has the next command"
        assert "new module" not in json.dumps(report)

    def test_it_never_names_a_directory_the_project_does_not_have(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """The pilot's four flat packages have no ``src`` to be pointed at."""
        root = _retrofitting(
            cli, tmp_path, "multi_pkg_app",
            "harnesslib", "evallib", "metrics",
        )
        capsys.readouterr()

        _, report = _doctor_json(cli, capsys, root)

        assert not (root / "src").exists()
        assert " src" not in report["project"]["suggested_next_action"]

    def test_a_greenfield_project_still_gets_the_greenfield_advice(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Nothing converted, nothing to convert: the first module is the step."""
        target = tmp_path / "greenfield"
        target.mkdir()
        (target / "pyproject.toml").write_text(
            '[project]\nname = "greenfield"\nversion = "0.1.0"\n\n'
            '[tool.s0ma]\nsource_roots = ["src"]\n',
            encoding="utf-8",
        )
        (target / "src").mkdir()

        _, report = _doctor_json(cli, capsys, target)

        assert report["project"]["suggested_next_action"] == (
            "run `s0ma new module <Name> -o src` to create the first module"
        )
