"""Explicit host-interpreter verification for built s0ma projects.

This module owns the deliberately dangerous half of release acceptance.
Static commands never import project code; :func:`verify_host` does so only
after a caller explicitly selects this surface and a host interpreter.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma_dsl.codegen.build_manifest import ManifestSchemaError, load_manifest
from s0ma_dsl.errors import S0maError

if TYPE_CHECKING:
    from s0ma_dsl.project import S0maProject

HOST_VERIFICATION_SCHEMA = "s0ma-host-verification@1"
DEFAULT_MODULE_TIMEOUT_SECONDS = 10.0
DEFAULT_RUN_TIMEOUT_SECONDS = 60.0
OUTPUT_TAIL_BYTES = 4096
_GATE_MODES = frozenset({"migration", "dev", "strict", "release"})
_DIST_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_IMPORT_TO_DIST = {
    "s0ma": "s0ma-core",
    "s0ma_dsl": "s0ma-dsl",
    "s0ma_mcp": "s0ma-mcp",
}


class HostVerificationUsageError(ValueError):
    """The host probe cannot begin safely with the supplied configuration."""


@dataclass(frozen=True)
class HostDependencyInputs:
    """Static dependency facts gathered without importing project code."""

    declared: tuple[str, ...]
    runtime_imports: tuple[str, ...]
    project_distribution: str


def _canonical_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _dependency_name(spec: str) -> str | None:
    match = _DIST_NAME.match(spec)
    return _canonical_distribution(match.group(1)) if match else None


def _python_in_venv(venv: Path, *, windows: bool) -> Path:
    if venv.is_file():
        return venv
    return venv / ("Scripts/python.exe" if windows else "bin/python")


def resolve_host_interpreter(
    project: S0maProject,
    explicit_python: str | None,
    *,
    windows: bool | None = None,
) -> Path:
    """Resolve the host Python with the frozen precedence and no fallback."""
    is_windows = os.name == "nt" if windows is None else windows
    source: str
    if explicit_python:
        explicit = Path(explicit_python).expanduser()
        if explicit.parent == Path("."):
            found = shutil.which(explicit_python)
            candidate = Path(found) if found else explicit
        else:
            candidate = explicit
        source = "explicit --python"
    elif project.venv_path:
        configured = Path(project.venv_path)
        if configured.is_absolute():
            raise HostVerificationUsageError(
                "[tool.s0ma].venv_path must be project-relative; absolute "
                f"path {project.venv_path!r} is refused. Pass --python for an "
                "explicit external interpreter."
            )
        venv = (project.root / configured).resolve()
        try:
            venv.relative_to(project.root.resolve())
        except ValueError as exc:
            raise HostVerificationUsageError(
                "[tool.s0ma].venv_path escapes the project root; configure a "
                "project-relative virtual environment or pass --python explicitly."
            ) from exc
        candidate = _python_in_venv(venv, windows=is_windows)
        source = "[tool.s0ma].venv_path"
    else:
        candidate = _python_in_venv(
            project.root / ".venv", windows=is_windows
        )
        source = "project .venv auto-detection"

    # Preserve the virtual-environment launcher path. Following the final
    # ``python`` symlink to its base interpreter would silently discard the
    # venv's site-packages — precisely the host mismatch this resolver exists
    # to prevent. Containment above follows the configured *venv directory*;
    # the executable identity below is absolute but does not dereference it.
    resolved = candidate.absolute()
    if not resolved.exists():
        raise HostVerificationUsageError(
            f"Host interpreter from {source} does not exist: {candidate}. "
            "Create the project virtual environment, configure "
            "[tool.s0ma].venv_path, or pass --python PATH. s0ma will not "
            "fall back to its own interpreter."
        )
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise HostVerificationUsageError(
            f"Host interpreter from {source} is not an executable file: "
            f"{resolved}. Pass an executable Python path."
        )
    return resolved


def _project_dependencies(root: Path) -> tuple[str, ...]:
    with (root / "pyproject.toml").open("rb") as stream:
        document = tomllib.load(stream)
    raw = document.get("project", {}).get("dependencies", [])
    if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
        raise HostVerificationUsageError(
            "[project].dependencies must be an array of PEP 508 strings "
            "before host verification can compare declared and installed state."
        )
    names = {_dependency_name(value) for value in raw}
    return tuple(sorted(name for name in names if name is not None))


def _runtime_imports(project: S0maProject) -> tuple[str, ...]:
    try:
        manifest = load_manifest(project.build_dir)
    except ManifestSchemaError as exc:
        raise HostVerificationUsageError(str(exc)) from exc
    project_modules = {entry.name.split(".", 1)[0] for entry in manifest.modules}
    imports: set[str] = set()
    for entry in manifest.modules:
        if entry.role != "source":
            continue
        output = project.build_dir / entry.output
        try:
            tree = ast.parse(output.read_text(encoding="utf-8"), filename=str(output))
        except (OSError, SyntaxError) as exc:
            raise HostVerificationUsageError(
                f"Cannot inspect built module {entry.name!r} at {output}: {exc}. "
                "Run `s0ma build` before `s0ma verify-host`."
            ) from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
    return tuple(sorted(imports - project_modules - sys.stdlib_module_names))


def _tail(value: str, limit: int = OUTPUT_TAIL_BYTES) -> str:
    raw = value.encode("utf-8", errors="replace")
    if len(raw) <= limit:
        return value
    return raw[-limit:].decode("utf-8", errors="replace")


def _controlled_environment() -> dict[str, str]:
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    if os.name != "nt":
        env.update({"LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"})
    return env


_HOST_INFO_SCRIPT = r"""
import importlib.metadata as md
import json
import platform
import sys

request = json.loads(sys.argv[1])
package_mapping = md.packages_distributions()
module_distributions = {}
distribution_names = set(request["distributions"])
for module in request["modules"]:
    candidates = package_mapping.get(module, [])
    module_distributions[module] = candidates
    fixed = request["fixed_distributions"].get(module)
    if fixed:
        distribution_names.add(fixed)
    distribution_names.update(candidates)
versions = {}
for name in sorted(distribution_names):
    try:
        versions[name] = md.version(name)
    except md.PackageNotFoundError:
        versions[name] = None
print(json.dumps({
    "python_version": platform.python_version(),
    "implementation": platform.python_implementation(),
    "platform": platform.platform(),
    "versions": versions,
    "module_distributions": module_distributions,
}, sort_keys=True))
"""


def _host_info(
    python: Path,
    declared: tuple[str, ...],
    runtime_imports: tuple[str, ...],
) -> dict[str, Any]:
    requested_distributions = sorted(
        set(declared) | {"s0ma-core", "s0ma-dsl", "s0ma-mcp"}
    )
    request = json.dumps(
        {
            "distributions": requested_distributions,
            "modules": runtime_imports,
            "fixed_distributions": _IMPORT_TO_DIST,
        },
        sort_keys=True,
    )
    try:
        completed = subprocess.run(
            [str(python), "-I", "-c", _HOST_INFO_SCRIPT, request],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_controlled_environment(),
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HostVerificationUsageError(
            f"Could not query host interpreter {python}: {exc}."
        ) from exc
    if completed.returncode != 0:
        raise HostVerificationUsageError(
            f"Host interpreter fingerprint failed for {python}: "
            f"{_tail(completed.stderr or completed.stdout)}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise HostVerificationUsageError(
            f"Host interpreter {python} returned an invalid fingerprint."
        ) from exc
    if not isinstance(payload, dict):
        raise HostVerificationUsageError(
            f"Host interpreter {python} returned an invalid fingerprint shape."
        )
    return payload


def _dependency_inputs(project: S0maProject) -> HostDependencyInputs:
    return HostDependencyInputs(
        declared=_project_dependencies(project.root),
        runtime_imports=_runtime_imports(project),
        project_distribution=_canonical_distribution(project.project_name),
    )


def _dependencies_and_diagnostics(
    inputs: HostDependencyInputs,
    host_info: dict[str, Any],
    interpreter: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_versions = host_info.get("versions", {})
    versions = (
        {
            _canonical_distribution(str(name)): value
            for name, value in raw_versions.items()
        }
        if isinstance(raw_versions, dict)
        else {}
    )
    raw_map = host_info.get("module_distributions", {})
    module_map = raw_map if isinstance(raw_map, dict) else {}
    runtime_by_dist: dict[str, set[str]] = {}
    for module in inputs.runtime_imports:
        fixed = _IMPORT_TO_DIST.get(module)
        candidates = module_map.get(module, [])
        distribution = fixed
        if distribution is None and isinstance(candidates, list) and candidates:
            distribution = str(candidates[0])
        if distribution is None:
            distribution = module.replace("_", "-")
        canonical = _canonical_distribution(distribution)
        if canonical == inputs.project_distribution:
            # A distribution never declares itself as a dependency. Its own
            # package imports are satisfied by installing the host project.
            continue
        runtime_by_dist.setdefault(canonical, set()).add(module)

    names = sorted(set(inputs.declared) | set(runtime_by_dist))
    records: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for name in names:
        installed_version = versions.get(name)
        # Metadata keys preserve our requested canonical spelling.
        installed = isinstance(installed_version, str)
        declared = name in inputs.declared
        runtime_modules = sorted(runtime_by_dist.get(name, set()))
        if declared and not installed:
            status = "declared_not_installed"
            diagnostics.append({
                "code": "DECLARED_DEP_NOT_INSTALLED",
                "dependency": name,
                "message": (
                    f"Host project declares {name!r}, but it is not installed "
                    "in the selected interpreter."
                ),
                "interpreter": interpreter["resolved_path"],
                "python_version": interpreter["python_version"],
                "remediation": (
                    "Install/sync the host project's declared dependencies in "
                    "this exact interpreter, then rerun verify-host."
                ),
            })
        elif declared:
            status = "declared_installed"
        else:
            status = "runtime_imported_undeclared"
            diagnostics.append({
                "code": "HOST_RUNTIME_UNDECLARED",
                "dependency": name,
                "modules": runtime_modules,
                "message": (
                    f"Built code imports {', '.join(runtime_modules)}, mapped "
                    f"to distribution {name!r}, but [project].dependencies "
                    "does not declare it."
                ),
                "interpreter": interpreter["resolved_path"],
                "python_version": interpreter["python_version"],
                "remediation": (
                    f"Add {name!r} to [project].dependencies, sync the host "
                    "environment, rebuild, and rerun verify-host."
                ),
            })
        records.append({
            "name": name,
            "declared": declared,
            "installed": installed,
            "installed_version": installed_version,
            "runtime_imported": bool(runtime_modules),
            "import_modules": runtime_modules,
            "status": status,
        })
    return records, diagnostics


_IMPORT_SCRIPT = r"""
import importlib
import sys

project_root, build_dir, module_name = sys.argv[1:4]
sys.path.insert(0, project_root)
sys.path.insert(0, build_dir)
importlib.import_module(module_name)
"""


def _module_order(project: S0maProject) -> tuple[str, ...]:
    manifest = load_manifest(project.build_dir)
    source_names = {entry.name for entry in manifest.modules if entry.role == "source"}
    ordered = [
        name for name in manifest.topological_import_order if name in source_names
    ]
    ordered.extend(sorted(source_names - set(ordered)))
    return tuple(ordered)


def _import_modules(
    project: S0maProject,
    python: Path,
    interpreter: dict[str, Any],
    *,
    module_timeout_seconds: float,
    run_timeout_seconds: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    modules: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    deadline = time.monotonic() + run_timeout_seconds
    for name in _module_order(project):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            duration_ms = 0
            modules.append({
                "name": name,
                "owner": name,
                "outcome": "timeout",
                "duration_ms": duration_ms,
                "stdout_tail": "",
                "stderr_tail": "whole-run timeout exhausted before probe",
            })
            diagnostics.append({
                "code": "HOST_IMPORT_FAILED",
                "module": name,
                "owner": name,
                "outcome": "timeout",
                "message": "Whole-run host verification timeout was exhausted.",
                "interpreter": interpreter["resolved_path"],
                "python_version": interpreter["python_version"],
                "remediation": (
                    "Investigate slow import-time work or increase --timeout "
                    "after confirming the side effects are expected."
                ),
            })
            continue
        started = time.monotonic()
        outcome = "passed"
        stdout = ""
        stderr = ""
        returncode: int | None = 0
        try:
            completed = subprocess.run(
                [
                    str(python), "-I", "-c", _IMPORT_SCRIPT,
                    str(project.root), str(project.build_dir), name,
                ],
                cwd=project.root,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_controlled_environment(),
                timeout=min(module_timeout_seconds, max(remaining, 0.001)),
            )
            stdout, stderr, returncode = (
                completed.stdout,
                completed.stderr,
                completed.returncode,
            )
            if completed.returncode != 0:
                outcome = "failed"
        except subprocess.TimeoutExpired as exc:
            outcome = "timeout"
            returncode = None
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            stderr = f"{stderr}\nimport timed out".strip()
        except OSError as exc:
            outcome = "failed"
            returncode = None
            stderr = str(exc)
        duration_ms = int((time.monotonic() - started) * 1000)
        modules.append({
            "name": name,
            "owner": name,
            "outcome": outcome,
            "duration_ms": duration_ms,
            "returncode": returncode,
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
        })
        if outcome != "passed":
            diagnostics.append({
                "code": "HOST_IMPORT_FAILED",
                "module": name,
                "owner": name,
                "outcome": outcome,
                "message": (
                    f"Built production module {name!r} did not import under "
                    f"the selected host interpreter ({outcome})."
                ),
                "interpreter": interpreter["resolved_path"],
                "python_version": interpreter["python_version"],
                "stderr_tail": _tail(stderr),
                "remediation": (
                    "Fix the named module/import dependency under this exact "
                    "host interpreter, rebuild, and rerun verify-host."
                ),
            })
    return modules, diagnostics


def verify_host(
    project: S0maProject,
    *,
    explicit_python: str | None = None,
    gate_mode: str | None = None,
    module_timeout_seconds: float = DEFAULT_MODULE_TIMEOUT_SECONDS,
    run_timeout_seconds: float = DEFAULT_RUN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Execute explicit host verification and return its versioned report."""
    if project.synthetic:
        raise HostVerificationUsageError(
            "verify-host requires a real [tool.s0ma] project and a build manifest."
        )
    if gate_mode is not None and gate_mode not in _GATE_MODES:
        raise HostVerificationUsageError(
            "gate_mode must be one of: migration, dev, strict, release"
        )
    if module_timeout_seconds <= 0 or run_timeout_seconds <= 0:
        raise HostVerificationUsageError("host verification timeouts must be positive")

    started = time.monotonic()
    python = resolve_host_interpreter(project, explicit_python)
    dependency_inputs = _dependency_inputs(project)
    host_info = _host_info(
        python, dependency_inputs.declared, dependency_inputs.runtime_imports
    )
    versions = host_info.get("versions", {})
    interpreter = {
        "resolved_path": str(python),
        "python_version": str(host_info.get("python_version", "unknown")),
        "implementation": str(host_info.get("implementation", "unknown")),
        "platform": str(host_info.get("platform", "unknown")),
        "s0ma_distributions": {
            name: versions.get(name) if isinstance(versions, dict) else None
            for name in ("s0ma-core", "s0ma-dsl", "s0ma-mcp")
        },
    }
    dependencies, dependency_diagnostics = _dependencies_and_diagnostics(
        dependency_inputs, host_info, interpreter
    )
    modules, import_diagnostics = _import_modules(
        project,
        python,
        interpreter,
        module_timeout_seconds=module_timeout_seconds,
        run_timeout_seconds=run_timeout_seconds,
    )
    diagnostics = [*dependency_diagnostics, *import_diagnostics]
    ok = not diagnostics
    gate: dict[str, Any]
    if gate_mode is None:
        gate = {
            "mode": None,
            "passes": None,
            "reasons": ["mode not pinned by caller"],
        }
    else:
        gate = {
            "mode": gate_mode,
            "passes": ok,
            "reasons": [] if ok else sorted({d["code"] for d in diagnostics}),
        }
    return {
        "schema": HOST_VERIFICATION_SCHEMA,
        "ok": ok,
        "gate_mode": gate_mode,
        "interpreter": interpreter,
        "modules": modules,
        "dependencies": dependencies,
        "diagnostics": diagnostics,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "gate": gate,
    }


def static_runtime_dependency_warning(project: S0maProject) -> S0maError | None:
    """Warn when emitted runtime imports are absent from project metadata."""
    if project.synthetic:
        return None
    declared = set(_project_dependencies(project.root))
    required = {"s0ma-core", "s0ma-dsl"}
    missing = sorted(required - declared)
    if not missing:
        return None
    return S0maError(
        code="HOST_RUNTIME_UNDECLARED",
        message=(
            "Generated Python imports the s0ma runtime, but the host project "
            f"does not declare {', '.join(missing)} in [project].dependencies."
        ),
        file=str(project.root / "pyproject.toml"),
        line=1,
        column=0,
        severity="warning",
        remediation=(
            # G1's H-11: the old wording read as a four-step chore —
            # declare, sync, rebuild, verify-host — when declaring is the
            # whole of what clears the warning. What the reader has to
            # know besides is a fact about somewhere else: the
            # environment that runs the application needs both installed,
            # or it will not import.
            "Name s0ma-core and s0ma-dsl in [project].dependencies — that "
            "alone clears this warning. Separately, the environment that runs "
            "the application has to have both installed; `s0ma verify-host` "
            "is how you prove it does."
        ),
        context={"missing_dependencies": missing},
    )


__all__ = [
    "DEFAULT_MODULE_TIMEOUT_SECONDS",
    "DEFAULT_RUN_TIMEOUT_SECONDS",
    "HOST_VERIFICATION_SCHEMA",
    "HostVerificationUsageError",
    "resolve_host_interpreter",
    "static_runtime_dependency_warning",
    "verify_host",
]
