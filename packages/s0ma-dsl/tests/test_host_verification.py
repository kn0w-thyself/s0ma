"""0.14 M2 trajectories for explicit host-reality verification."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.host_verification import (
    HostVerificationUsageError,
    resolve_host_interpreter,
    static_runtime_dependency_warning,
    verify_host,
)
from s0ma_dsl.project import S0maProject

_BUILDABLE = """\
module quiet
    layer: DOMAIN
    version: 1.0.0
    intent: "Owns a deterministic internal value for host-warning tests."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell QUIET_VALUE :: DOMAIN
    kind: CONSTANT
    visibility: INTERNAL
    intent: "Stores a deterministic integer."
    schema: "int"
    invariants: none
    covered_by: none
    ---
    QUIET_VALUE = 1
"""


def _write_project(
    root: Path,
    modules: dict[str, str],
    *,
    dependencies: tuple[str, ...] = (),
    order: tuple[str, ...] | None = None,
    venv_path: str | None = None,
) -> S0maProject:
    build = root / "build"
    src = root / "src"
    build.mkdir(parents=True)
    src.mkdir()
    deps = ", ".join(json.dumps(value) for value in dependencies)
    venv = f"venv_path = {json.dumps(venv_path)}\n" if venv_path else ""
    (root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "host_fixture"\n'
        'version = "0.1.0"\n'
        f"dependencies = [{deps}]\n\n"
        "[tool.s0ma]\n"
        'source_roots = ["src"]\n'
        'build_dir = "build"\n'
        f"{venv}",
        encoding="utf-8",
    )
    entries: list[dict[str, str]] = []
    for name, source in modules.items():
        (build / f"{name}.py").write_text(source, encoding="utf-8")
        (src / f"{name}.s0ma").write_text(
            f'module {name}\n    intent: "host fixture"\n', encoding="utf-8"
        )
        entries.append({
            "name": name,
            "source": f"src/{name}.s0ma",
            "output": f"{name}.py",
            "ir": f"{name}.s0ma.json",
            "source_map": f"{name}.s0ma.map",
            "source_hash": "sha256:fixture",
            "output_hash": "sha256:fixture",
            "role": "source",
        })
    (build / "build.s0ma.json").write_text(
        json.dumps({
            "schema": "s0ma-build-manifest@1",
            "project": "host_fixture",
            "build_dir": "build",
            "transpiler_version": "0.13.0",
            "modules": entries,
            "topological_import_order": list(order or modules),
        }, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return S0maProject.discover(root)


def test_declared_and_installed_runtime_passes_with_fingerprint(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        {"app": "import s0ma\nimport s0ma_dsl\nVALUE = 1\n"},
        dependencies=("s0ma-core", "s0ma-dsl"),
    )
    report = verify_host(
        project, explicit_python=sys.executable, gate_mode="release"
    )
    assert report["schema"] == "s0ma-host-verification@1"
    assert report["ok"] is True, report
    assert report["gate"] == {"mode": "release", "passes": True, "reasons": []}
    assert report["interpreter"]["resolved_path"] == str(Path(sys.executable).absolute())
    assert report["interpreter"]["python_version"]
    assert report["interpreter"]["implementation"]
    assert report["interpreter"]["platform"]
    assert report["interpreter"]["s0ma_distributions"]["s0ma-core"]
    assert [row["status"] for row in report["dependencies"]] == [
        "declared_installed",
        "declared_installed",
    ]


def test_declared_but_not_installed_fails(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        {"app": "VALUE = 1\n"},
        dependencies=("definitely-not-installed-s0ma-host-fixture",),
    )
    report = verify_host(project, explicit_python=sys.executable)
    assert report["ok"] is False
    assert report["gate"]["passes"] is None
    assert {d["code"] for d in report["diagnostics"]} == {
        "DECLARED_DEP_NOT_INSTALLED"
    }


def test_runtime_import_without_host_declaration_fails(tmp_path: Path) -> None:
    project = _write_project(tmp_path, {"app": "import s0ma\nVALUE = 1\n"})
    report = verify_host(project, explicit_python=sys.executable, gate_mode="strict")
    undeclared = [
        d for d in report["diagnostics"]
        if d["code"] == "HOST_RUNTIME_UNDECLARED"
    ]
    assert len(undeclared) == 1
    assert undeclared[0]["dependency"] == "s0ma-core"
    assert undeclared[0]["modules"] == ["s0ma"]
    assert report["gate"]["passes"] is False


def test_import_timeout_is_bounded_and_fails(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path, {"slow": "import time\ntime.sleep(2)\n"}
    )
    report = verify_host(
        project,
        explicit_python=sys.executable,
        module_timeout_seconds=0.05,
        run_timeout_seconds=1,
    )
    assert report["modules"][0]["outcome"] == "timeout"
    assert report["modules"][0]["duration_ms"] < 1000
    assert "HOST_IMPORT_FAILED" in {d["code"] for d in report["diagnostics"]}


def test_failure_does_not_hide_later_modules(tmp_path: Path) -> None:
    marker = tmp_path / "later-imported.txt"
    project = _write_project(
        tmp_path,
        {
            "broken": 'raise RuntimeError("first module fails")\n',
            "later": (
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n"
            ),
        },
        order=("broken", "later"),
    )
    report = verify_host(project, explicit_python=sys.executable)
    assert [row["outcome"] for row in report["modules"]] == ["failed", "passed"]
    assert marker.read_text(encoding="utf-8") == "ran"


def test_side_effect_fixture_proves_execution_trust_boundary(tmp_path: Path) -> None:
    marker = tmp_path / "import-side-effect.txt"
    project = _write_project(
        tmp_path,
        {"side_effect": (
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
        )},
    )
    assert not marker.exists()
    report = verify_host(project, explicit_python=sys.executable)
    assert report["ok"] is True
    assert marker.read_text(encoding="utf-8") == "executed"


def test_output_tails_are_bounded(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        {"noisy": "print('x' * 10000)\nraise RuntimeError('y' * 10000)\n"},
    )
    report = verify_host(project, explicit_python=sys.executable)
    module = report["modules"][0]
    assert len(module["stdout_tail"].encode("utf-8")) <= 4096
    assert len(module["stderr_tail"].encode("utf-8")) <= 4096


def test_windows_venv_interpreter_detection(tmp_path: Path) -> None:
    project = _write_project(tmp_path, {"app": "VALUE = 1\n"})
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("fixture", encoding="utf-8")
    python.chmod(0o755)
    assert resolve_host_interpreter(project, None, windows=True) == python.resolve()


def test_configured_venv_path_escape_is_refused(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path / "project",
        {"app": "VALUE = 1\n"},
        venv_path="../outside",
    )
    with pytest.raises(HostVerificationUsageError, match="escapes the project root"):
        resolve_host_interpreter(project, None)


def test_missing_venv_refuses_without_current_interpreter_fallback(
    tmp_path: Path,
) -> None:
    project = _write_project(tmp_path, {"app": "VALUE = 1\n"})
    with pytest.raises(HostVerificationUsageError, match="will not fall back"):
        resolve_host_interpreter(project, None)


def test_static_emission_warning_names_missing_s0ma_runtime(tmp_path: Path) -> None:
    project = _write_project(tmp_path, {"app": "VALUE = 1\n"})
    warning = static_runtime_dependency_warning(project)
    assert warning is not None
    assert warning.code == "HOST_RUNTIME_UNDECLARED"
    assert warning.severity == "warning"
    assert warning.context["missing_dependencies"] == ["s0ma-core", "s0ma-dsl"]


def test_the_static_warning_says_what_clears_it_and_what_it_cannot_see(
    tmp_path: Path,
) -> None:
    """G1's H-11: declaring is the whole fix; installing is somewhere else.

    The trial's agent read "declare, sync the host environment, rebuild,
    then run explicit verify-host" as four required steps and did all
    four, when declaring alone cleared the warning. The remediation now
    separates what clears the finding from the fact about the
    environment that runs the application — which nothing in this
    repository can see, and which `s0ma verify-host` exists to prove.
    """
    project = _write_project(tmp_path, {"app": "VALUE = 1\n"})
    warning = static_runtime_dependency_warning(project)

    assert warning is not None
    assert warning.remediation is not None
    said = " ".join(warning.remediation.split())
    assert "[project].dependencies — that alone clears this warning" in said
    assert "the environment that runs the application has to have both installed" in said
    assert "`s0ma verify-host` is how you prove it does" in said


def test_static_warning_clears_when_runtime_is_declared(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        {"app": "VALUE = 1\n"},
        dependencies=("s0ma-core", "s0ma-dsl"),
    )
    assert static_runtime_dependency_warning(project) is None


@pytest.mark.parametrize("command", ["build", "transpile"])
def test_emitting_cli_surfaces_static_runtime_warning(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    root = tmp_path / command
    _write_project(root, {})
    source = root / "src" / "quiet.s0ma"
    source.write_text(_BUILDABLE, encoding="utf-8")
    argv = ["--project-root", str(root), command]
    if command == "build":
        argv.append(str(root / "src"))
    else:
        argv.extend([str(source), "--output-dir", str(root / "build")])
    argv += ["--mode", "migration", "--format", "json"]
    assert S0maCLI().run(argv) == EXIT_SUCCESS
    captured = capsys.readouterr()
    assert not captured.err
    document = json.loads(captured.out)
    assert [warning["code"] for warning in document["warnings"]] == [
        "HOST_RUNTIME_UNDECLARED"
    ]


def test_ordinary_verify_does_not_execute_built_module(tmp_path: Path) -> None:
    marker = tmp_path / "ordinary-verify-side-effect.txt"
    project = _write_project(
        tmp_path,
        {"side_effect": (
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
        )},
    )
    assert not marker.exists()
    S0maCLI().run(["--project-root", str(project.root), "verify", str(project.build_dir)])
    assert not marker.exists()
