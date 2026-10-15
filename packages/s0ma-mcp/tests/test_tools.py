"""Round-trip tests for the s0ma-mcp tool implementations.

Each tool is exercised against a real temporary project assembled from
s0ma-dsl's own fixtures (consolidation plan M5 step 5): scaffold →
check → transpile, full builds, IR inspection, example execution, the
migrate-ext dry-run contract, structured diagnostics for invalid
source, and the NFR-6 write fence.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")
# ^ tools.py imports mcp.types for the FR-MCP-8 annotation matrix.

from conftest import BROKEN_S0MA, make_project

from s0ma_mcp import tools


class TestVerifyHost:
    """M2: explicit, dangerous host-reality tool and release pairing."""

    def test_declared_installed_project_passes_and_teaches_static_pair(
        self, project: Path
    ) -> None:
        pyproject = project / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8").replace(
                'version = "0.1.0"',
                'version = "0.1.0"\ndependencies = ["s0ma-core", "s0ma-dsl"]',
            ),
            encoding="utf-8",
        )
        built = tools.build_project_tool(project_root=str(project), mode="dev")
        assert built["ok"] is True
        result = tools.verify_host_tool(
            project_root=str(project),
            python=sys.executable,
            gate_mode="release",
        )
        assert result["schema"] == "s0ma-tool-result@1"
        assert result["ok"] is True
        report = result["host_verification"]
        assert report["schema"] == "s0ma-host-verification@1"
        assert report["gate"]["passes"] is True
        assert result["next_actions"] == [{
            "tool": "check",
            "arguments": {
                "project_root": str(project.resolve()),
                "gate_mode": "release",
            },
            "reason": (
                "Run or confirm the static half under the same caller-pinned "
                "policy; host verification alone is not release readiness."
            ),
        }]

    def test_side_effect_proves_annotation_trust_boundary(
        self, tmp_path: Path
    ) -> None:
        marker = tmp_path / "host-side-effect.txt"
        project = make_project(tmp_path / "project")
        pyproject = project / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8").replace(
                'version = "0.1.0"',
                'version = "0.1.0"\ndependencies = ["s0ma-core", "s0ma-dsl"]',
            ),
            encoding="utf-8",
        )
        built = tools.build_project_tool(project_root=str(project), mode="dev")
        assert built["ok"] is True
        manifest = json.loads(
            (project / "build" / "build.s0ma.json").read_text(encoding="utf-8")
        )
        first_module = project / "build" / manifest["modules"][0]["output"]
        with first_module.open("a", encoding="utf-8") as stream:
            stream.write(
                "\nfrom pathlib import Path as _M2Path\n"
                f"_M2Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n"
            )
        result = tools.verify_host_tool(
            project_root=str(project), python=sys.executable
        )
        assert marker.read_text(encoding="utf-8") == "ran"
        assert result["schema"] == "s0ma-tool-result@1"
        assert result["host_verification"]["schema"] == (
            "s0ma-host-verification@1"
        )


class TestScaffoldCheckTranspileLoop:
    """The acceptance-criterion loop: scaffold → check (ok) → transpile."""

    def test_scaffold_module_creates_valid_file(self, project: Path) -> None:
        result = tools.scaffold_module_tool(
            project_root=str(project), module_name="GreeterService"
        )
        assert result["ok"] is True
        path = Path(result["path"])
        assert path.is_file()
        assert path.name == "greeter_service.s0ma"
        assert path.parent == project / "src"
        assert "module greeter_service" in result["content"]
        assert "nerve GreeterService" in result["content"]

    def test_scaffold_is_check_clean_in_strict_mode(self, project: Path) -> None:
        result = tools.scaffold_module_tool(
            project_root=str(project), module_name="GreeterService"
        )
        assert result["check"]["ok"] is True
        assert result["check"]["exit_code"] == 0

    def test_scaffold_then_transpile_emits_artifacts(self, project: Path) -> None:
        scaffolded = tools.scaffold_module_tool(
            project_root=str(project), module_name="GreeterService"
        )
        assert scaffolded["ok"] is True

        transpiled = tools.transpile_tool(
            source_path=scaffolded["path"], project_root=str(project)
        )
        assert transpiled["ok"] is True
        names = {Path(artifact).name for artifact in transpiled["artifacts"]}
        assert names == {
            "greeter_service.py",
            "greeter_service.s0ma.json",
            "greeter_service.s0ma.map",
        }
        for artifact in transpiled["artifacts"]:
            assert Path(artifact).is_file()

    def test_scaffold_respects_explicit_output_dir(self, project: Path) -> None:
        result = tools.scaffold_module_tool(
            project_root=str(project),
            module_name="EdgeAdapter",
            kind="ADAPTER",
            layer="INFRASTRUCTURE",
            output_dir=str(project / "src"),
        )
        assert result["ok"] is True
        assert "kind: ADAPTER" in result["content"]
        assert "INFRASTRUCTURE" in result["content"]

    def test_scaffold_rejects_invalid_kind(self, project: Path) -> None:
        result = tools.scaffold_module_tool(
            project_root=str(project), module_name="Bad", kind="NOT_A_KIND"
        )
        assert result["ok"] is False
        assert "error" in result

    def test_scaffold_refuses_output_outside_project(self, project: Path) -> None:
        result = tools.scaffold_module_tool(
            project_root=str(project),
            module_name="Escapee",
            output_dir=str(project.parent / "elsewhere"),
        )
        assert result["ok"] is False
        assert "outside the given project root" in result["error"]
        assert not (project.parent / "elsewhere").exists()


class TestTranspile:
    def test_transpile_valid_file(self, project: Path) -> None:
        source = project / "src" / "models.s0ma"
        result = tools.transpile_tool(
            source_path=str(source), project_root=str(project)
        )
        assert result["ok"] is True
        assert result["exit_code"] == 0
        assert result["diagnostics"]["summary"]["errors"] == 0
        assert any(a.endswith("models.py") for a in result["artifacts"])
        assert any(a.endswith("models.s0ma.json") for a in result["artifacts"])
        assert any(a.endswith("models.s0ma.map") for a in result["artifacts"])

    def test_transpile_without_project_root_uses_source_dir(
        self, project: Path
    ) -> None:
        source = project / "src" / "models.s0ma"
        result = tools.transpile_tool(source_path=str(source))
        assert result["ok"] is True
        assert result["artifacts"]

    def test_transpile_missing_source_fails_structurally(self) -> None:
        result = tools.transpile_tool(source_path="/nonexistent/nowhere.s0ma")
        assert result["ok"] is False
        assert "does not exist" in result["error"]

    def test_transpile_invalid_source_surfaces_diagnostics(
        self, tmp_path: Path
    ) -> None:
        project = make_project(
            tmp_path / "proj", sources={"broken.s0ma": BROKEN_S0MA}
        )
        result = tools.transpile_tool(
            source_path=str(project / "src" / "broken.s0ma"),
            project_root=str(project),
        )
        assert result["ok"] is False
        assert result["exit_code"] == 1
        errors = result["diagnostics"]["errors"]
        assert errors, "expected structured diagnostics for invalid source"
        for diagnostic in errors:
            assert diagnostic["code"]
            assert diagnostic["severity"] == "error"
            assert diagnostic["remediation"]
            assert diagnostic["file"].endswith("broken.s0ma")

    def test_transpile_refuses_output_dir_outside_project(
        self, project: Path
    ) -> None:
        result = tools.transpile_tool(
            source_path=str(project / "src" / "models.s0ma"),
            project_root=str(project),
            output_dir=str(project.parent / "exfiltrated"),
        )
        assert result["ok"] is False
        assert "NFR-6" in result["error"]
        assert not (project.parent / "exfiltrated").exists()

    def test_transpile_refuses_source_outside_project(
        self, project: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside.s0ma"
        outside.write_text("module outside\n", encoding="utf-8")
        result = tools.transpile_tool(
            source_path=str(outside), project_root=str(project)
        )
        assert result["ok"] is False
        assert "outside the given project root" in result["error"]


class TestCheck:
    def test_check_valid_project(self, project: Path) -> None:
        result = tools.check_tool(project_root=str(project), mode="dev")
        assert result["ok"] is True
        assert result["exit_code"] == 0
        assert result["diagnostics"]["summary"]["errors"] == 0
        assert result["diagnostics"]["summary"]["files_processed"] == 3

    def test_check_gate_mode_is_caller_pinned_and_score_remains_cli_only(
        self, project: Path,
    ) -> None:
        result = tools.check_tool(
            project_root=str(project), mode="dev", gate_mode="release",
        )
        assert result["gate_mode"] == "release"
        assert result["score"]["schema"] == "s0ma-score@2"
        assert result["score"]["mode"] == "dev"
        assert result["gate"]["mode"] == "release"
        assert result["gate"]["floor"] == 90.0

    def test_check_accepts_only_caller_pinned_adoption_policy(
        self, project: Path,
    ) -> None:
        from s0ma_dsl.adoption_policy import (
            AdoptionException,
            policy_sha256,
        )

        vendor = project / "src" / "vendor" / "acme"
        vendor.mkdir(parents=True)
        (vendor / "legacy.py").write_text("VALUE = 1\n", encoding="utf-8")
        exception = AdoptionException(
            path_glob="src/vendor/acme/**",
            category="vendored",
            reason="upstream-owned source",
        )
        policy_path = project / "adoption-policy.json"
        policy_path.write_text(json.dumps({
            "schema": "s0ma-adoption-policy@1",
            "exceptions": [exception.to_dict()],
        }), encoding="utf-8")
        expected = policy_sha256((exception,))
        result = tools.check_tool(
            project_root=str(project),
            mode="dev",
            gate_mode="strict",
            adoption_policy=str(policy_path),
            expected_adoption_policy_hash=expected,
        )
        evidence = result["score"]["faculties"]["proprioception"][
            "metrics"
        ]["registration"]["adoption_policy"]
        assert evidence["sha256"] == expected
        assert evidence["matched_paths"][0]["path"] == (
            "src/vendor/acme/legacy.py"
        )
        assert result["gate"]["floor"] == 75.0

    def test_check_refuses_contract_kill_switch_only_when_gating(
        self, project: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("S0MA_VERIFY_CONTRACTS", "0")
        report_only = tools.check_tool(project_root=str(project), mode="dev")
        assert report_only["ok"] is True

        gated = tools.check_tool(
            project_root=str(project), mode="dev", gate_mode="strict",
        )
        assert gated["ok"] is False
        assert "S0MA_VERIFY_CONTRACTS=0" in gated["error"]

    def test_check_single_file(self, project: Path) -> None:
        result = tools.check_tool(
            path=str(project / "src" / "models.s0ma"),
            project_root=str(project),
            mode="strict",
        )
        assert result["ok"] is True

    def test_check_invalid_file_reports_structured_diagnostics(
        self, tmp_path: Path
    ) -> None:
        project = make_project(
            tmp_path / "proj", sources={"broken.s0ma": BROKEN_S0MA}
        )
        result = tools.check_tool(project_root=str(project), mode="strict")
        assert result["ok"] is False
        assert result["exit_code"] == 1
        errors = result["diagnostics"]["errors"]
        codes = {diagnostic["code"] for diagnostic in errors}
        assert codes, "expected at least one structured error code"
        for diagnostic in errors:
            assert set(diagnostic) >= {
                "code",
                "message",
                "file",
                "line",
                "column",
                "severity",
                "remediation",
            }

    def test_check_surfaces_declaration_suggestion(self, tmp_path: Path) -> None:
        """M1 (0.13.0): a self-healing contract diagnostic's corrected
        declaration block rides the DSL ``--format json`` diagnostics into
        the MCP ``check`` result verbatim — zero MCP-side code, the 0.12.0
        M2 pass-through pattern. Here a self-inflicted ``requires:`` mistake
        (an unresolvable package) surfaces ``MISSING_PACKAGE`` carrying a
        ready-to-paste ``suggested_declaration``.
        """
        def _module(name: str, requires: str) -> str:
            return (
                f"module {name}\n"
                "    layer: APPLICATION\n"
                "    version: 0.1.0\n"
                '    intent: "a demo module"\n'
                f"    requires: [{requires}]\n"
                f"    exports: [{name}_noop]\n"
                "    uses: none\n"
                "    soft_requires: none\n"
                "    runtime_only_requires: none\n"
                "    deferred_requires: none\n"
                "    exports_helpers: none\n"
                "    ---\n"
                "\n"
                f"nerve {name}_noop :: APPLICATION\n"
                "    kind: FUNCTION\n"
                "    visibility: PUBLIC\n"
                '    intent: "noop"\n'
                '    expects: "none"\n'
                '    guarantees: "none"\n'
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
                f"    def {name}_noop():\n"
                "        return 1\n"
            )

        # Two modules so the cross-module resolver (which runs the
        # importability pass) fires — matching real projects; the `needy`
        # module carries the self-inflicted requires mistake.
        project = make_project(
            tmp_path / "proj",
            sources={
                "needy.s0ma": _module(
                    "needy", "os, zzzz_definitely_not_a_real_package_xyz"
                ),
                "clean.s0ma": _module("clean", "json"),
            },
        )
        result = tools.check_tool(project_root=str(project), mode="strict")
        assert result["ok"] is False
        errors = result["diagnostics"]["errors"]
        missing = [e for e in errors if e["code"] == "MISSING_PACKAGE"]
        assert missing, "expected MISSING_PACKAGE for the unresolvable package"
        # The corrected block arrives as an additive per-diagnostic key,
        # dropping the unresolvable entry.
        assert missing[0]["suggested_declaration"] == "requires: [os]"

    def test_check_requires_some_target(self) -> None:
        result = tools.check_tool()
        assert result["ok"] is False
        assert "requires" in result["error"]

    def test_check_missing_path(self, project: Path) -> None:
        result = tools.check_tool(
            path=str(project / "src" / "ghost.s0ma"),
            project_root=str(project),
        )
        assert result["ok"] is False
        assert "does not exist" in result["error"]


class TestBuildProject:
    def test_build_emits_manifest_summary(self, project: Path) -> None:
        result = tools.build_project_tool(project_root=str(project), mode="dev")
        assert result["ok"] is True
        manifest = result["manifest"]
        assert manifest["modules"] == ["models", "processing", "routing"]
        assert manifest["topological_import_order"] == [
            "models",
            "processing",
            "routing",
        ]
        assert manifest["transpiler_version"]
        assert (project / "build" / "build.s0ma.json").is_file()
        assert (project / "build" / "models.py").is_file()

    def test_build_invalid_project_returns_diagnostics(
        self, tmp_path: Path
    ) -> None:
        project = make_project(
            tmp_path / "proj", sources={"broken.s0ma": BROKEN_S0MA}
        )
        result = tools.build_project_tool(project_root=str(project))
        assert result["ok"] is False
        assert result["exit_code"] == 1
        assert result["diagnostics"]["errors"]

    def test_build_missing_root_fails_structurally(self) -> None:
        result = tools.build_project_tool(project_root="/nonexistent/project")
        assert result["ok"] is False
        assert "not a directory" in result["error"]


# A SERVICE factory whose body defines every provides: name (so no hard
# MISSING_PROVIDED_FUNCTION) — only the terminal return dict's literal
# keys vary, so PROVIDES_KEY_MISMATCH (a dev warning, a strict/check
# error) is the sole finding: the check-red / build-green class the M2
# build gate binds.
_GATE_HEAD = """\
module gate_demo
    layer: APPLICATION
    version: 0.1.0
    intent: "A service module exercising the M2 build gate over MCP."
    exports: [assembler]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve assembler :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "Return a dict of ops for the M2 build-gate MCP test."
    expects: "no arguments"
    guarantees: "returns a dict of ops"
    forbids: none
    provides: [assemble, validate]
    evaluates_at: FUNCTION_BOUNDARY
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def assembler():
        def assemble():
            return 1
        def validate():
            return 1
"""
_GATE_GREEN = _GATE_HEAD + "        return {'assemble': assemble, 'validate': validate}\n"
_GATE_BROKEN = _GATE_HEAD + "        return {'assemble': assemble, 'validat': validate}\n"


class TestBuildProjectNewErrorGate:
    """M2 (0.13.0, batch-01c): build_project refuses NEW check errors and
    the allow_new_errors escape hatch builds + stamps the manifest."""

    def _project(self, tmp_path: Path) -> Path:
        return make_project(
            tmp_path / "proj", sources={"gate_demo.s0ma": _GATE_GREEN}
        )

    def test_new_error_refuses_over_mcp(self, tmp_path: Path) -> None:
        project = self._project(tmp_path)
        # green build -> green baseline
        assert tools.build_project_tool(
            project_root=str(project), mode="dev"
        )["ok"] is True
        # edit introduces a NEW check error
        (project / "src" / "gate_demo.s0ma").write_text(
            _GATE_BROKEN, encoding="utf-8"
        )
        result = tools.build_project_tool(project_root=str(project), mode="dev")
        assert result["ok"] is False
        assert result["diagnostics"]["build_refused"]["reason"] == (
            "NEW_CHECK_ERRORS"
        )
        # the refusal carries the labelled NEW error + M1's suggestion
        err = result["diagnostics"]["errors"][0]
        assert err["code"] == "PROVIDES_KEY_MISMATCH"
        assert err["delta_label"] == "NEW"
        assert err["suggested_declaration"].startswith("provides: [")

    def test_allow_new_errors_builds_over_mcp(self, tmp_path: Path) -> None:
        project = self._project(tmp_path)
        assert tools.build_project_tool(
            project_root=str(project), mode="dev"
        )["ok"] is True
        (project / "src" / "gate_demo.s0ma").write_text(
            _GATE_BROKEN, encoding="utf-8"
        )
        result = tools.build_project_tool(
            project_root=str(project), mode="dev", allow_new_errors=True
        )
        assert result["ok"] is True
        override = result["diagnostics"]["build_override"]
        assert override["allow_new_errors"] is True
        assert override["new_error_count"] == 1
        assert (project / "build" / "build.s0ma.json").is_file()


class TestBuildHealthEcho:
    """M4 (0.13.0, batch-01c): a green build points at the way to verify it.

    Ship-without-running was the common thread of the batch's worst
    outcomes (CM6 shipped with zero runtime probes; an ops run left a
    service down) — so the green ``build_project`` result gains ONE
    trailing ``health_echo`` line: the declared verify command, or the
    not-a-fault nudge to declare one. Refusal and legacy results are
    untouched.
    """

    def _project(self, tmp_path: Path, *, extra_toml: str = "") -> Path:
        project = make_project(
            tmp_path / "proj", sources={"gate_demo.s0ma": _GATE_GREEN}
        )
        if extra_toml:
            pyproject = project / "pyproject.toml"
            pyproject.write_text(
                pyproject.read_text(encoding="utf-8") + extra_toml,
                encoding="utf-8",
            )
        return project

    def test_green_build_echoes_declared_health_command(
        self, tmp_path: Path
    ) -> None:
        project = self._project(
            tmp_path,
            extra_toml='health_command = "curl -fsS localhost:8080/health"\n',
        )
        result = tools.build_project_tool(project_root=str(project))
        assert result["ok"] is True
        assert result["health_echo"] == (
            "verify: curl -fsS localhost:8080/health"
        )

    def test_green_build_falls_back_to_run_command(
        self, tmp_path: Path
    ) -> None:
        project = self._project(
            tmp_path, extra_toml='run_command = "python -m gate_demo"\n'
        )
        result = tools.build_project_tool(project_root=str(project))
        assert result["ok"] is True
        assert result["health_echo"] == "verify: python -m gate_demo"

    def test_health_command_wins_over_run_command(
        self, tmp_path: Path
    ) -> None:
        project = self._project(
            tmp_path,
            extra_toml=(
                'run_command = "python -m gate_demo"\n'
                'health_command = "curl -fsS localhost:8080/health"\n'
            ),
        )
        result = tools.build_project_tool(project_root=str(project))
        assert result["ok"] is True
        assert result["health_echo"] == (
            "verify: curl -fsS localhost:8080/health"
        )

    def test_green_build_without_declaration_nudges_not_faults(
        self, tmp_path: Path
    ) -> None:
        project = self._project(tmp_path)
        result = tools.build_project_tool(project_root=str(project))
        assert result["ok"] is True
        # the 0.12.0 M1 not-a-fault wording: absence never reads as an
        # error, it names the declaration and where it goes
        assert result["health_echo"] == (
            "no health_command declared — declare one in [tool.s0ma] "
            "so builds can point at it"
        )

    def test_refusal_result_carries_no_echo(self, tmp_path: Path) -> None:
        project = self._project(
            tmp_path, extra_toml='health_command = "true"\n'
        )
        assert tools.build_project_tool(
            project_root=str(project)
        )["ok"] is True
        (project / "src" / "gate_demo.s0ma").write_text(
            _GATE_BROKEN, encoding="utf-8"
        )
        result = tools.build_project_tool(project_root=str(project))
        assert result["ok"] is False
        assert result["diagnostics"]["build_refused"]["reason"] == (
            "NEW_CHECK_ERRORS"
        )
        # M2's refusal result stays exactly as shipped — no echo rides it
        assert "health_echo" not in result

    def test_legacy_build_carries_no_echo(self, tmp_path: Path) -> None:
        scaffolded = tools.scaffold_module_tool(
            project_root=str(tmp_path), module_name="Ghost"
        )
        assert scaffolded["ok"] is True
        built = tools.build_project_tool(project_root=str(tmp_path))
        assert built["ok"] is True
        # legacy mode already carries its own init_project warning — the
        # right nudge there is init_project, not health_command
        assert "health_echo" not in built


class TestFreshAgentWalkthrough:
    """M4 spec (c): the wave's teaching surfaces read coherently in one
    cold-session arc — init → status (rules) → green build (baseline +
    echo) → in-place mismatch edit → check (M1 suggestion, NEW label) →
    build refusal re-handing the block (M2) → paste the suggested block
    verbatim → green build with the health echo again. One integration
    test over the real MCP tool layer, end to end."""

    def test_cold_session_walkthrough(self, tmp_path: Path) -> None:
        root = tmp_path / "cold"
        root.mkdir()

        # 1. init — the bootstrap result already carries the rules (D1).
        created = tools.init_project_tool(project_root=str(root))
        assert created["changed"] is True
        assert created["rules"]

        # Declare the verify command the health echo should point at
        # ([tool.s0ma] is the trailing table in the generated file).
        pyproject = root / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8")
            + 'health_command = "python -m gate_demo --health"\n',
            encoding="utf-8",
        )

        # 2. orientation — project_status carries the SAME rules object
        #    (one canonical _SURVIVAL_RULES, no forked wording).
        status = tools.project_status_tool(project_root=str(root))
        assert status["ok"] is True and status["is_project"] is True
        assert status["rules"] == created["rules"]

        # 3. author a green module; the first build is green, records
        #    the check baseline, and already carries the echo.
        src = root / "src"
        src.mkdir(exist_ok=True)
        module = src / "gate_demo.s0ma"
        module.write_text(_GATE_GREEN, encoding="utf-8")
        first_build = tools.build_project_tool(project_root=str(root))
        assert first_build["ok"] is True
        assert first_build["health_echo"] == (
            "verify: python -m gate_demo --health"
        )

        # 4. an in-place edit mis-declares provides: (the measured
        #    mismatch class) — check labels it NEW and hands over the
        #    corrected declaration block (M1).
        module.write_text(_GATE_BROKEN, encoding="utf-8")
        checked = tools.check_tool(project_root=str(root), mode="strict")
        assert checked["ok"] is False
        finding = next(
            err
            for err in checked["diagnostics"]["errors"]
            if err["code"] == "PROVIDES_KEY_MISMATCH"
        )
        assert finding["delta_label"] == "NEW"
        suggestion = finding["suggested_declaration"]
        assert suggestion.startswith("provides: [")

        # 5. the build REFUSES the NEW error (M2) and re-hands the block
        #    — and no echo rides a refusal.
        refused = tools.build_project_tool(project_root=str(root))
        assert refused["ok"] is False
        assert refused["diagnostics"]["build_refused"]["reason"] == (
            "NEW_CHECK_ERRORS"
        )
        refused_finding = refused["diagnostics"]["errors"][0]
        assert refused_finding["suggested_declaration"] == suggestion
        assert "health_echo" not in refused

        # 6. paste the suggested block verbatim over the declaration —
        #    correct by construction for ITS class (M1 spec (d)): the
        #    mismatch is gone on re-check. This fixture's body returns
        #    def validate under the key 'validat', so the re-check
        #    honestly surfaces the SUCCESSOR finding (the def/key
        #    inconsistency the declaration paste cannot decide for the
        #    author) — the loop hands the next step, it never dead-ends.
        broken_text = module.read_text(encoding="utf-8")
        fixed_text = re.sub(
            r"provides: \[[^\]]*\]", suggestion, broken_text, count=1
        )
        assert fixed_text != broken_text
        module.write_text(fixed_text, encoding="utf-8")
        rechecked = tools.check_tool(project_root=str(root), mode="strict")
        recheck_codes = {
            err["code"] for err in rechecked["diagnostics"].get("errors", [])
        }
        assert "PROVIDES_KEY_MISMATCH" not in recheck_codes
        assert recheck_codes == {"MISSING_PROVIDED_FUNCTION"}

        # 7. the successor diagnostic names the body-side rename; apply
        #    it and the arc ends green.
        module.write_text(
            module.read_text(encoding="utf-8").replace(
                "def validate()", "def validat()", 1
            ).replace("'validat': validate", "'validat': validat", 1),
            encoding="utf-8",
        )
        rechecked = tools.check_tool(project_root=str(root), mode="strict")
        assert rechecked["ok"] is True

        # 8. the green build closes the loop with the echo (M4).
        final_build = tools.build_project_tool(project_root=str(root))
        assert final_build["ok"] is True
        assert final_build["health_echo"] == (
            "verify: python -m gate_demo --health"
        )


class TestAdoptFile:
    """adopt_file (0.11.0, batch-01a D2): tool → record → verify sees it."""

    def test_adopt_file_round_trip(self, project: Path) -> None:
        """The full round-trip: adopt, record on disk, verify + status see it.

        The stray file mirrors the bench hollow-model shape (P2_P_r02):
        a real ``_impl.py`` beside generated code, invisible to the
        model until adopted.
        """
        assert tools.build_project_tool(project_root=str(project))["ok"] is True
        impl = project / "build" / "legacy_impl.py"
        impl.write_text(
            "def helper(x: int) -> int:\n    return x + 1\n",
            encoding="utf-8",
        )

        # Relative paths resolve against the EXPLICIT project root.
        result = tools.adopt_file_tool(
            project_root=str(project),
            path="build/legacy_impl.py",
            description="bench-shaped stray impl",
        )
        assert result["ok"] is True
        assert result["schema"] == "s0ma-tool-result@1"
        assert result["status"] == "interim"
        assert result["path"] == "build/legacy_impl.py"
        assert result["content_hash"].startswith("sha256:")
        assert result["re_adopted"] is False
        assert result["next_actions"][0]["tool"] == "scaffold_module"
        assert result["next_actions"][0]["arguments"]["module_name"] == (
            "legacy_impl"
        )
        assert result["counts"]["roster_adopted"] == 1

        # The durable record exists at the project root.
        record_path = project / "adopted.s0ma.json"
        assert record_path.is_file()
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        assert payload["schema"] == "s0ma-adopted-files@1"
        entry = payload["files"]["build/legacy_impl.py"]
        assert entry["content_hash"] == result["content_hash"]
        assert entry["description"] == "bench-shaped stray impl"

        # verify (the CLI the tools wrap, run in-process) classifies the
        # file ADOPTED — not UNKNOWN — on the strength of the record.
        import contextlib
        import io

        from s0ma_dsl.cli.main import S0maCLI

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = S0maCLI().run([
                "--project-root", str(project),
                "verify", str(project / "build"),
                "--format", "json",
            ])
        assert rc == 0
        rows = json.loads(out.getvalue())
        statuses = {row["file"]: row["status"] for row in rows}
        adopted_rows = [
            f for f, s in statuses.items() if s == "ADOPTED"
        ]
        assert len(adopted_rows) == 1
        assert adopted_rows[0].endswith("legacy_impl.py")
        assert "UNKNOWN" not in statuses.values()

        # project_status lists the adoption with its recorded hash.
        status = tools.project_status_tool(project_root=str(project))
        assert status["ok"] is True
        assert status["adopted_files"] == [{
            "path": "build/legacy_impl.py",
            "content_hash": result["content_hash"],
            "description": "bench-shaped stray impl",
            "re_adopt_count": 0,
        }]

    def test_adopt_file_reports_cli_refusals_structurally(
        self, project: Path
    ) -> None:
        """CLI refusals come back as structured {ok: false, error} dicts."""
        result = tools.adopt_file_tool(
            project_root=str(project), path="build/nonexistent.py",
            description="Missing file contract test.",
        )
        assert result["ok"] is False
        assert result["exit_code"] == 2
        assert "not an existing regular file" in result["error"]

    def test_adopt_file_missing_root_fails_structurally(self) -> None:
        result = tools.adopt_file_tool(
            project_root="/nonexistent/project", path="x.py",
            description="Missing-root contract test.",
        )
        assert result["ok"] is False
        assert "not a directory" in result["error"]

    def test_project_status_has_empty_adopted_list_by_default(
        self, project: Path
    ) -> None:
        status = tools.project_status_tool(project_root=str(project))
        assert status["ok"] is True
        assert status["adopted_files"] == []
        assert "adopted_files_error" not in status


class TestInspectModule:
    def test_inspect_single_module_returns_ir(self, project: Path) -> None:
        assert tools.build_project_tool(project_root=str(project))["ok"] is True
        result = tools.inspect_module_tool(
            project_root=str(project), module="models"
        )
        assert result["ok"] is True
        ir = result["ir"]
        # DSL-M1 (0.8.0): IR schema 2.0.0 -> 2.1.0 (additive
        # metadata/serves_as fields, ADR-011 §(g)).
        assert ir["schema_version"] == "3.0.0"
        assert ir["module"]["name"] == "models"
        component_ids = {c["canonical_id"] for c in ir["components"]}
        assert {"models::UserModel", "models::UserRole"} <= component_ids

    def test_inspect_all_returns_project_survey(self, project: Path) -> None:
        assert tools.build_project_tool(project_root=str(project))["ok"] is True
        result = tools.inspect_module_tool(project_root=str(project))
        assert result["ok"] is True
        assert isinstance(result["modules"], list)
        assert len(result["modules"]) == 3

    def test_inspect_unknown_module_fails_structurally(
        self, project: Path
    ) -> None:
        assert tools.build_project_tool(project_root=str(project))["ok"] is True
        result = tools.inspect_module_tool(
            project_root=str(project), module="phantom"
        )
        assert result["ok"] is False
        assert result["error"]


class TestRunExample:
    def test_runs_all_examples(self, greetings_project: Path) -> None:
        result = tools.run_example_tool(project_root=str(greetings_project))
        assert result["ok"] is True
        assert len(result["results"]) == 1
        outcome = result["results"][0]
        assert outcome["name"] == "greet_example"
        assert outcome["passed"] is True
        assert "Hello, Ada!" in outcome["stdout"]
        assert outcome["returncode"] == 0
        assert outcome["timed_out"] is False

    def test_runs_named_example(self, greetings_project: Path) -> None:
        result = tools.run_example_tool(
            project_root=str(greetings_project), example_name="greet_example"
        )
        assert result["ok"] is True
        assert [r["name"] for r in result["results"]] == ["greet_example"]

    def test_unknown_example_name_lists_discovered(
        self, greetings_project: Path
    ) -> None:
        result = tools.run_example_tool(
            project_root=str(greetings_project), example_name="ghost"
        )
        assert result["ok"] is False
        assert "discovered: greet_example" in result["error"]

    def test_no_examples_is_ok_noop(self, project: Path) -> None:
        result = tools.run_example_tool(project_root=str(project))
        assert result["ok"] is True
        assert result["results"] == []
        assert "no example declarations" in result["summary"]

    def test_failing_example_reported_not_raised(self, tmp_path: Path) -> None:
        failing = (
            "module failing\n"
            "    layer: DOMAIN\n"
            "    version: 1.0.0\n"
            '    intent: "Module hosting a deliberately failing example."\n'
            "    exports: []\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "\n"
            "example boom_example\n"
            '    intent: "Demonstrates a failing example body for testing."\n'
            "    demonstrates: [nerve::greet]\n"
            "    runs_in: standalone\n"
            "    ---\n"
            "    raise SystemExit(2)\n"
        )
        project = make_project(
            tmp_path / "proj", sources={"failing.s0ma": failing}
        )
        result = tools.run_example_tool(project_root=str(project))
        assert result["ok"] is False
        assert result["results"][0]["passed"] is False
        assert "boom_example" in result["error"]


class TestMigrateExt:
    @staticmethod
    def _legacy_project(root: Path) -> Path:
        """A pre-consolidation project with legacy-extension artifacts."""
        (root / "src").mkdir(parents=True)
        legacy_source = root / "src" / "app.soma"  # legacy-spelling: intentional
        legacy_source.write_text("module app\n", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[project]\nname = "legacy_app"\nversion = "0.1.0"\n\n'
            '[tool.soma]\nsource_roots = ["src"]\n',  # legacy-spelling: intentional
            encoding="utf-8",
        )
        return root

    def test_dry_run_is_the_default_and_changes_nothing(
        self, tmp_path: Path
    ) -> None:
        project = self._legacy_project(tmp_path / "legacy")
        result = tools.migrate_ext_tool(project_root=str(project))
        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["actions"], "expected a non-empty migration plan"
        assert "dry-run" in result["summary"]
        # Nothing changed on disk:
        assert (project / "src" / "app.soma").is_file()  # legacy-spelling: intentional
        assert not (project / "src" / "app.s0ma").exists()
        assert "[tool.soma]" in (  # legacy-spelling: intentional
            project / "pyproject.toml"
        ).read_text(encoding="utf-8")

    def test_apply_renames_and_rewrites(self, tmp_path: Path) -> None:
        project = self._legacy_project(tmp_path / "legacy")
        result = tools.migrate_ext_tool(project_root=str(project), dry_run=False)
        assert result["ok"] is True
        assert result["dry_run"] is False
        assert (project / "src" / "app.s0ma").is_file()
        legacy_name = "app.soma"  # legacy-spelling: intentional
        assert not (project / "src" / legacy_name).exists()
        assert "[tool.s0ma]" in (project / "pyproject.toml").read_text(
            encoding="utf-8"
        )

    def test_apply_is_idempotent(self, tmp_path: Path) -> None:
        project = self._legacy_project(tmp_path / "legacy")
        assert tools.migrate_ext_tool(project_root=str(project), dry_run=False)["ok"]
        again = tools.migrate_ext_tool(project_root=str(project), dry_run=False)
        assert again["ok"] is True
        assert "nothing to migrate" in again["summary"]


class TestBoundarySafety:
    """FR-MCP-2: structured failures, never raw tracebacks."""

    def test_tools_never_raise_on_garbage_input(self) -> None:
        results = [
            tools.transpile_tool(source_path="\0bad"),
            tools.build_project_tool(project_root="\0bad"),
            tools.check_tool(path="\0bad"),
            tools.inspect_module_tool(project_root="\0bad"),
            tools.run_example_tool(project_root="\0bad"),
            tools.migrate_ext_tool(project_root="\0bad"),
            tools.scaffold_module_tool(project_root="\0bad", module_name="X"),
            tools.init_project_tool(project_root="\0bad"),
        ]
        for result in results:
            assert result["ok"] is False
            assert isinstance(result["error"], str)

    def test_results_are_json_serializable(self, project: Path) -> None:
        for result in (
            tools.check_tool(project_root=str(project), mode="dev"),
            tools.build_project_tool(project_root=str(project)),
            tools.inspect_module_tool(project_root=str(project), module="models"),
            tools.migrate_ext_tool(project_root=str(project)),
        ):
            json.dumps(result)  # raises TypeError on non-JSON content


class TestInitProject:
    """Pilot-01 P0-1: the bootstrap step no other tool performed.

    The pilot reproduced a loop with no exit: ``scaffold_module`` ok →
    ``build_project`` ok (silent legacy mode) → ``project_status`` still
    ``is_project: false`` with the same suggestion, because no MCP tool
    created the ``[tool.s0ma]`` table. ``init_project`` is that tool;
    these tests pin the whole loop now closing.
    """

    def test_init_on_empty_dir_creates_pyproject_and_project(
        self, tmp_path: Path
    ) -> None:
        result = tools.init_project_tool(project_root=str(tmp_path))
        assert result["ok"] is True
        assert result["is_project"] is True
        assert result["changed"] is True
        assert result["created_pyproject"] is True
        pyproject = tmp_path / "pyproject.toml"
        assert pyproject.is_file()
        text = pyproject.read_text(encoding="utf-8")
        assert "[tool.s0ma]" in text
        assert 'source_roots = ["src"]' in text
        assert 'authoring = "on"' in text
        assert "scaffold_module" in result["suggested_next_action"]
        assert "s0ma://guide/survival-card" in result["suggested_next_action"]

    def test_init_appends_to_existing_pyproject_byte_preserving(
        self, tmp_path: Path
    ) -> None:
        original = '[project]\nname = "plain"\nversion = "0.1.0"\n'
        (tmp_path / "pyproject.toml").write_text(original, encoding="utf-8")
        result = tools.init_project_tool(project_root=str(tmp_path))
        assert result["ok"] is True
        assert result["changed"] is True
        assert result["created_pyproject"] is False
        text = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
        assert text.startswith(original)  # existing content untouched
        assert "[tool.s0ma]" in text

    def test_init_is_idempotent(self, tmp_path: Path) -> None:
        first = tools.init_project_tool(project_root=str(tmp_path))
        assert first["changed"] is True
        pyproject_after_first = (tmp_path / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        second = tools.init_project_tool(project_root=str(tmp_path))
        assert second["ok"] is True
        assert second["is_project"] is True
        assert second["changed"] is False
        assert (tmp_path / "pyproject.toml").read_text(
            encoding="utf-8"
        ) == pyproject_after_first

    def test_init_rejects_unknown_mode(self, tmp_path: Path) -> None:
        result = tools.init_project_tool(
            project_root=str(tmp_path), mode="yolo"
        )
        assert result["ok"] is False
        assert "unknown mode" in result["error"]
        assert not (tmp_path / "pyproject.toml").exists()

    @pytest.mark.parametrize(
        "poisoned",
        [
            '[tool]\ns0ma = "off"\n',
            "[[tool.s0ma]]\nkey = 1\n",
        ],
        ids=["scalar-s0ma", "array-of-tables"],
    )
    def test_init_refuses_non_table_s0ma_without_touching_file(
        self, tmp_path: Path, poisoned: str
    ) -> None:
        """Adversarial-review regression: a non-table ``tool.s0ma``
        value used to fall through the idempotency check, appending a
        conflicting table and leaving INVALID TOML on disk. The tool
        must refuse structurally and leave the file byte-identical
        (destructiveHint=false is a contract)."""
        pyproject = tmp_path / "pyproject.toml"
        # write_bytes, not write_text: the assertion below is byte
        # equality, and a text-mode write translates LF to CRLF on
        # Windows — the file would differ from `poisoned` before the
        # tool was ever called.
        pyproject.write_bytes(poisoned.encode("utf-8"))
        result = tools.init_project_tool(project_root=str(tmp_path))
        assert result["ok"] is False
        assert "fix it before initializing" in result["error"]
        assert pyproject.read_bytes() == poisoned.encode("utf-8")
        # The file still parses as TOML (the old behavior appended a
        # conflicting table, leaving invalid TOML on disk), and
        # project_status still answers structurally, never raises.
        import tomllib as tomllib_mod

        tomllib_mod.loads(pyproject.read_text(encoding="utf-8"))
        status = tools.project_status_tool(project_root=str(tmp_path))
        assert isinstance(status.get("ok"), bool)

    def test_init_non_ascii_dir_name_writes_valid_project_name(
        self, tmp_path: Path
    ) -> None:
        """Adversarial-review regression: str.isalnum is Unicode-aware,
        so a non-ASCII directory name leaked into [project].name. The
        fallback must stay PEP 508-shaped."""
        import re as re_mod
        import tomllib as tomllib_mod

        target = tmp_path / "café-プロジェクト"
        target.mkdir()
        result = tools.init_project_tool(project_root=str(target))
        assert result["ok"] is True
        data = tomllib_mod.loads(
            (target / "pyproject.toml").read_text(encoding="utf-8")
        )
        name = data["project"]["name"]
        assert re_mod.fullmatch(
            r"[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?", name
        ), name

    def test_init_declares_the_requested_mode(self, tmp_path: Path) -> None:
        result = tools.init_project_tool(
            project_root=str(tmp_path), mode="strict"
        )
        assert result["ok"] is True
        assert 'mode = "strict"' in result["table"]
        status = tools.project_status_tool(project_root=str(tmp_path))
        assert status["mode"] == "strict"

    def test_full_bootstrap_loop_reaches_is_project_true(
        self, tmp_path: Path
    ) -> None:
        """The pilot's exact failure scenario, end to end, now exits the
        loop: init_project → scaffold_module → build_project →
        project_status reports is_project true WITH a manifest."""
        before = tools.project_status_tool(project_root=str(tmp_path))
        assert before["is_project"] is False
        assert "init_project" in before["suggested_next_action"]

        init = tools.init_project_tool(project_root=str(tmp_path))
        assert init["ok"] is True

        scaffolded = tools.scaffold_module_tool(
            project_root=str(tmp_path), module_name="Pipeline"
        )
        assert scaffolded["ok"] is True
        # Now a real project: no legacy-mode hint on the scaffold result.
        assert "hint" not in scaffolded

        built = tools.build_project_tool(project_root=str(tmp_path))
        assert built["ok"] is True
        assert "manifest" in built  # NOT a silent legacy build
        assert "warnings" not in built

        after = tools.project_status_tool(project_root=str(tmp_path))
        assert after["is_project"] is True
        assert after["build"]["built"] is True


class TestBootstrapHonesty:
    """Pilot-01 P0-1/P2-8: non-project work says so instead of
    succeeding silently."""

    def test_scaffold_on_non_project_forwards_warning_and_hint(
        self, tmp_path: Path
    ) -> None:
        result = tools.scaffold_module_tool(
            project_root=str(tmp_path), module_name="Loner"
        )
        assert result["ok"] is True
        assert result["project"] is False
        assert "init_project" in result["hint"]
        # The CLI's onboarding warning is forwarded on SUCCESS now
        # (pilot-01: it surfaced only in error payloads).
        assert any(
            "[tool.s0ma]" in warning for warning in result.get("warnings", [])
        )

    def test_scaffold_on_real_project_has_no_hint(self, project: Path) -> None:
        result = tools.scaffold_module_tool(
            project_root=str(project), module_name="Insider"
        )
        assert result["ok"] is True
        assert "hint" not in result
        assert "project" not in result

    def test_scaffold_duplicate_error_leads_with_cause_not_warning(
        self, tmp_path: Path
    ) -> None:
        tools.scaffold_module_tool(project_root=str(tmp_path), module_name="Dup")
        result = tools.scaffold_module_tool(
            project_root=str(tmp_path), module_name="Dup"
        )
        assert result["ok"] is False
        first_line = result["error"].splitlines()[0].lower()
        assert not first_line.startswith("warning")
        assert "already exists" in result["error"]

    def test_legacy_build_without_table_warns(self, tmp_path: Path) -> None:
        scaffolded = tools.scaffold_module_tool(
            project_root=str(tmp_path), module_name="Ghost"
        )
        assert scaffolded["ok"] is True
        built = tools.build_project_tool(project_root=str(tmp_path))
        assert built["ok"] is True
        assert "manifest" not in built
        assert any(
            "legacy-mode" in warning and "init_project" in warning
            for warning in built["warnings"]
        )

    def test_check_failure_cites_error_catalog_uri(self, tmp_path: Path) -> None:
        """Pilot-01 P1-5: ~40 failing check/build events, zero guide
        reads — no tool response referenced any s0ma:// URI. Now every
        failing diagnostics result cites the catalog for its codes."""
        project = make_project(tmp_path / "proj", sources={})
        (project / "src").mkdir(exist_ok=True)
        (project / "src" / "broken.s0ma").write_text(
            BROKEN_S0MA, encoding="utf-8"
        )
        result = tools.check_tool(project_root=str(project), mode="strict")
        assert result["ok"] is False
        assert "s0ma://guide/errors" in result["error_help"]
        assert "s0ma://guide/survival-card" in result["error_help"]
        # The specific codes are named so the agent can search the doc.
        codes_blob = result["error_help"]
        diagnostics = result["diagnostics"]
        for finding in diagnostics.get("errors", []):
            assert finding["code"] in codes_blob


class TestDeferredImportResilience:
    """DSL-M2 (F-M3-1 restored): the dsl/core machinery imports are
    ``deferred_requires:`` entries, so the built tools module emits them
    INSIDE each consuming def body — the server starts even when
    ``s0ma_dsl.cli`` is broken, and each tool call surfaces the import
    failure as a structured ``{ok: False}`` result through the ``_safe``
    boundary instead of an import-time crash (the original tools.py
    lazy-import design, lost at SH-M3, restored as an authored field).
    """

    def test_built_module_top_carries_no_dsl_or_core_machinery_imports(
        self,
    ) -> None:
        """Static proof on the committed build: every header-authored
        ``s0ma_dsl.*`` / ``s0ma.examples`` / ``s0ma.registry`` import is
        in-body, none at module top. The emitter-written FRAMEWORK
        imports stay at module top by design (``s0ma.decorators`` /
        ``s0ma.models`` / ``s0ma.types`` / the
        ``s0ma_dsl.runtime_bridge.registration`` bridge) — they are the
        registration machinery, not the module header's toolchain
        dependencies."""
        import ast as ast_mod

        source = Path(tools.__file__).read_text(encoding="utf-8")
        tree = ast_mod.parse(source)
        module_top_froms = {
            node.module
            for node in tree.body
            if isinstance(node, ast_mod.ImportFrom) and node.module
        }
        assert not {
            mod
            for mod in module_top_froms
            if (
                mod.startswith("s0ma_dsl")
                and not mod.startswith("s0ma_dsl.runtime_bridge")
            )
            or mod in ("s0ma.examples", "s0ma.registry")
        }, module_top_froms
        in_body_froms = {
            node.module
            for node in ast_mod.walk(tree)
            if isinstance(node, ast_mod.ImportFrom) and node.module
        } - module_top_froms
        assert "s0ma_dsl.cli.main" in in_body_froms

    def test_server_starts_degraded_with_broken_dsl_cli(self) -> None:
        """Arm one (import-time success at the server boundary): with
        ``s0ma_dsl.cli.main`` poisoned, importing the package AND
        constructing the server still succeed — in a fresh subprocess so
        no pre-imported module masks the breakage."""
        import subprocess
        import sys as sys_mod

        code = (
            "import sys\n"
            "sys.modules['s0ma_dsl.cli.main'] = None\n"
            "import s0ma_mcp\n"
            "server = s0ma_mcp.create_server()\n"
            "print('SERVER_STARTED_DEGRADED')\n"
        )
        proc = subprocess.run(
            [sys_mod.executable, "-c", code],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert "SERVER_STARTED_DEGRADED" in proc.stdout

    def test_broken_dsl_cli_fails_per_call_with_structured_result(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Arm two (per-call failure at the tool boundary): each CALL of
        a consuming tool surfaces the deferred-import failure as the
        ``_safe``-shaped structured result — ``{ok: False, error: ...}``
        naming the import error, never a traceback across MCP — and a
        second call fails identically (per-call, not one-shot)."""
        import sys as sys_mod

        monkeypatch.setitem(sys_mod.modules, "s0ma_dsl.cli.main", None)
        for attempt in range(2):
            result = tools.check_tool(project_root=str(project), mode="dev")
            assert result["ok"] is False, attempt
            assert "s0ma_dsl.cli.main" in result["error"]
            assert "Error" in result["error"]  # ImportError/ModuleNotFoundError
            json.dumps(result)


# batch-01a M2 fixtures: a producer whose operations are stuffed into a
# returned dict + a consumer that subscripts the imported MODULE OBJECT
# (the factory-dict trap → MODULE_SUBSCRIPT, M1 B1).
_MODULE_SUBSCRIPT_REGISTRY = """\
module registry
    layer: DOMAIN
    version: 0.1.0
    intent: "Operation registry factory."
    exports: [make_registry]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve make_registry :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    intent: "Build the operation registry dict."
    expects: "nothing"
    guarantees: "a dict of operations"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def make_registry():
        return {"get_op": lambda name: name}
"""

_MODULE_SUBSCRIPT_CLI = """\
module cli
    layer: PRESENTATION
    version: 0.1.0
    intent: "CLI entry that misuses the registry module object."
    uses: [registry]
    exports: [run]
    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve run :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Run an operation via the registry."
    expects: "an op name"
    guarantees: "the op result"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def run(name):
        return registry["get_op"](name)
"""

# batch-01c M2: a minimal strict-green module and its broken twin (a bare
# body import — a reliable BARE_IMPORT) for the check-attribution test.
_BASELINE_VALID = """\
module alpha
    layer: DOMAIN
    version: 1.0.0
    intent: "A minimal module exercising MCP check-baseline attribution."
    exports: [a]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve a :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Return a constant used by the MCP check-baseline test."
    expects: "no arguments"
    guarantees: "returns a constant integer"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def a():
        return 1
"""

_BASELINE_BROKEN = """\
module alpha
    layer: DOMAIN
    version: 1.0.0
    intent: "A minimal module exercising MCP check-baseline attribution."
    exports: [a]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve a :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Return a constant used by the MCP check-baseline test."
    expects: "no arguments"
    guarantees: "returns a constant integer"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def a():
        import os
        return len(str(os.getpid())) and 1
"""


class TestInBandTeaching:
    """batch-01a M2 (D1/D3/P2): the survival rules and pattern teaching
    travel in the result payloads and served text, not only behind the
    s0ma://guide/survival-card URI (read in 2/6 pilot runs)."""

    def _assert_survival_rules(self, rules: object) -> None:
        assert isinstance(rules, list) and rules, rules
        blob = "\n".join(rules)
        # rule 1 — cites the enforced M1 build guard
        assert "GENERATED_FILE_DRIFT" in blob
        # rule 2 — one def, imports declared in requires:
        assert "ONE def" in blob and "requires:" in blob
        # rule 3 — check then build_project
        assert "check" in blob and "build_project" in blob
        # rule 4 — the O2 ops rule (rides M2 per the plan's sequencing)
        assert "Live state is the deliverable" in blob
        # rule 5 — the diagnose-from-observations rule (batch-01c M1): a
        # missing runbook/doc/config declaration is never the root cause
        assert "never the root cause of a fault" in blob
        # rule 6 — the check-attribution rule (batch-01c M2): a NEW
        # failure is yours; "pre-existing" only when the output says so
        assert "NEW check failure after your edit is yours" in blob
        assert "only claimable when the output says" in blob
        # rule 7 — the durable-state-migration rule (batch-01c M4): a
        # shape change needs a migration for existing data; a
        # creation-path-only edit doesn't reach live deployments
        assert "durable-state shape" in blob
        assert "CREATE TABLE IF NOT EXISTS" in blob
        assert "yesterday's version" in blob

    # --- D1: the inline survival rules in result payloads --------------

    def test_init_project_result_carries_inline_rules(
        self, tmp_path: Path
    ) -> None:
        created = tools.init_project_tool(project_root=str(tmp_path))
        assert created["changed"] is True
        self._assert_survival_rules(created["rules"])
        # the survival-card pointer stays alongside the inline rules
        assert "survival-card" in created["suggested_next_action"]
        # the idempotent (already-a-project) answer carries them too
        again = tools.init_project_tool(project_root=str(tmp_path))
        assert again["changed"] is False
        self._assert_survival_rules(again["rules"])

    def test_scaffold_result_carries_inline_rules(self, project: Path) -> None:
        result = tools.scaffold_module_tool(
            project_root=str(project), module_name="Rulesy"
        )
        assert result["ok"] is True
        self._assert_survival_rules(result["rules"])

    def test_project_status_carries_inline_rules(
        self, project: Path, tmp_path: Path
    ) -> None:
        """M4 (0.13.0, batch-01c): project_status lands 36/36 sessions
        while s0ma://guide lands 0/36 — the rules ride the loaded
        channel, both branches, from the ONE canonical source."""
        status = tools.project_status_tool(project_root=str(project))
        assert status["ok"] is True and status["is_project"] is True
        self._assert_survival_rules(status["rules"])

        # the not-yet-a-project branch is the bootstrap moment that most
        # needs them — they ride there too
        outside = tmp_path / "not_a_project"
        outside.mkdir()
        bare = tools.project_status_tool(project_root=str(outside))
        assert bare["ok"] is True and bare["is_project"] is False
        self._assert_survival_rules(bare["rules"])

        # ONE canonical _SURVIVAL_RULES — identical to init's payload
        fresh = tmp_path / "fresh_proj"
        fresh.mkdir()
        created = tools.init_project_tool(project_root=str(fresh))
        assert created["rules"] == status["rules"] == bare["rules"]

    # --- D1: per-code deep anchors into the error catalog --------------

    def test_check_error_help_emits_per_code_anchors(
        self, tmp_path: Path
    ) -> None:
        proj = make_project(
            tmp_path / "proj",
            sources={
                "registry.s0ma": _MODULE_SUBSCRIPT_REGISTRY,
                "cli.s0ma": _MODULE_SUBSCRIPT_CLI,
            },
        )
        result = tools.check_tool(project_root=str(proj), mode="strict")
        assert result["ok"] is False
        codes = {f["code"] for f in result["diagnostics"]["errors"]}
        assert "MODULE_SUBSCRIPT" in codes
        # every returned code gets its own deep anchor into the catalog
        for code in codes:
            assert f"s0ma://guide/errors#{code}" in result["error_help"]
        assert "s0ma://guide/survival-card" in result["error_help"]

    # --- M2: check_tool carries NEW / PRE-EXISTING attribution ----------

    def test_check_result_labels_new_failures_after_green(
        self, tmp_path: Path
    ) -> None:
        """batch-01c M2 (spec (e)): the delta labels ride the wrapped result.

        A project checks green (recording the baseline), an edit
        introduces a failure, and the very next ``check_tool`` result
        labels it NEW — the exact evidence the CM6 r03 agent lacked,
        reaching the agent through the DSL result the tool wraps with no
        MCP-side change.
        """
        proj = make_project(
            tmp_path / "proj", sources={"alpha.s0ma": _BASELINE_VALID}
        )
        green = tools.check_tool(project_root=str(proj), mode="strict")
        assert green["ok"] is True
        # a green run carries no delta block — rendered exactly as before
        assert "delta" not in green["diagnostics"]

        (proj / "src" / "alpha.s0ma").write_text(
            _BASELINE_BROKEN, encoding="utf-8"
        )
        failed = tools.check_tool(project_root=str(proj), mode="strict")
        assert failed["ok"] is False
        delta = failed["diagnostics"]["delta"]
        assert delta["baseline_exists"] is True
        assert {k["code"] for k in delta["new"]}  # a non-empty NEW set
        assert delta["pre_existing"] == []
        assert "NEW since your last green build" in delta["summary"]
        # and the label rides on the diagnostic itself
        assert failed["diagnostics"]["errors"][0]["delta_label"] == "NEW"

    # --- D3: scaffold_module emits the multi-function skeleton ----------

    def test_scaffold_service_emits_provides_skeleton(
        self, project: Path
    ) -> None:
        # default kind is SERVICE → the multi-function factory skeleton
        result = tools.scaffold_module_tool(
            project_root=str(project), module_name="OpRegistry"
        )
        assert result["ok"] is True
        assert result["check"]["ok"] is True  # check-clean in strict mode
        content = result["content"]
        assert "kind: SERVICE" in content
        assert "provides:" in content
        assert "return {" in content  # a factory returning a dict
        assert "MODULE_SUBSCRIPT" in content  # teaches the trap inline
        # a non-SERVICE kind stays the minimal single-def template
        adapter = tools.scaffold_module_tool(
            project_root=str(project), module_name="EdgeThing", kind="ADAPTER"
        )
        assert "provides: none" in adapter["content"]

    # --- P2: describe_server leads with the rules ----------------------

    def test_describe_server_leads_with_rules(self) -> None:
        described = tools.describe_server_tool()
        assert described["ok"] is True
        keys = list(described)
        assert keys[1] == "rules"  # right after ok, before the inventory
        assert keys.index("rules") < keys.index("self_model")
        self._assert_survival_rules(described["rules"])

    # --- P2: every tool that surfaces raw CLI output leads with cause --

    def test_lead_with_cause_puts_advisory_last(self) -> None:
        text = (
            "warning: Operating without project discovery. "
            "Add [tool.s0ma].\n"
            "File already exists: foo.s0ma\n"
        )
        led = tools._lead_with_cause(text)
        lines = led.splitlines()
        assert lines[0] == "File already exists: foo.s0ma"
        assert lines[-1].lower().startswith("warning")
