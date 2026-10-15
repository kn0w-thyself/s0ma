"""``s0ma doctor`` — environment and project health report (FR-DSL-5 v1.1).

Answers "is my environment healthy and what should I do next" in five
sections, machine-first (PRD P-5: the text rendering is derived from
the same structured report ``--format json`` emits):

``versions``
    The s0ma distributions via ``importlib.metadata`` (a missing
    ``s0ma-mcp`` or ``s0ma-studi0`` is tolerated — both are optional
    add-ons and core+dsl-only installs are supported, INV-6), the
    Python version, and the ``mcp`` SDK version if present.
``project``
    Project resolution exactly the way every other subcommand resolves
    it (``S0maProject.discover``), plus per-module build freshness
    judged by the build manifest's own recorded hashes — the same
    recipe as the MCP server's ``project_status`` tool, composed from
    the dsl's own APIs (s0ma-dsl never imports s0ma-mcp, INV-6).
    Status vocabulary: ``fresh`` / ``stale`` / ``unbuilt`` /
    ``orphaned`` per module; ``fresh`` / ``stale`` / ``unbuilt`` for
    the build. Also reports the ``[tool.s0ma].authoring`` posture
    (``on`` / ``off``, default ``on`` — STD-M4). A malformed
    ``[tool.s0ma]`` table is rendered as a finding, never a crash.
``mcp``
    Whether the ``s0ma-mcp`` server executable is on ``PATH``
    (``shutil.which``) and the registration hint.
``license``
    Placeholder, clearly labeled: licensing ships with FR-COM (PRD
    §7.5), after the 20-user testing round.
``update_check``
    Placeholder, clearly labeled: the update notification arrives with
    the FR-COM-4 entitlement ping. **No network I/O happens here or
    anywhere in this command** (PRD P-6 / INV-9).

Doctor diagnoses, it does not gate: findings (missing tools, stale
builds, malformed config) exit 0. A non-zero exit means the
environment itself is broken — e.g. s0ma-dsl cannot import s0ma-core.
"""

from __future__ import annotations

import importlib
import json
import platform
import shutil
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import argparse

    from s0ma_dsl.project import S0maProject

EXIT_SUCCESS = 0
EXIT_INTERNAL_ERROR = 3

#: The MCP registration hint (kept identical to ``s0ma new project``).
MCP_HINT = "claude mcp add s0ma -- s0ma-mcp"

#: The viewer hint (kept identical to the ``s0ma studi0`` not-installed
#: block in ``cli/main.py`` — one wording for one door).
STUDI0_HINT = "s0ma studi0 <project_root>"

#: FR-COM placeholders (PRD §7.5) — offline, clearly labeled (D-2).
LICENSE_PLACEHOLDER = "not required in this version"
UPDATE_CHECK_PLACEHOLDER = "offline in this version — see PRD §7.5 (FR-COM-4)"

#: Where a person standing in front of a health report goes to learn what
#: any of it means (architecture §9.3 entry point 4). Doctor is often the
#: first command somebody runs and it is the one that already answers "what
#: is installed and what state is this in" — so it is the natural place to
#: say that the same toolchain will also explain itself. One line, naming
#: the bare command and one journey id, both of which F9's discovery
#: contract resolves against the composed snapshot rather than trusting.
LEARN_JOURNEY = "journey:first-project"
LEARN_HINT = f"s0ma docs  ·  s0ma docs show {LEARN_JOURNEY}"


def _dist_version(distribution: str) -> str | None:
    """Installed version of *distribution*, or ``None`` when absent."""
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _finding(
    severity: str, section: str, message: str, remediation: str | None = None
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "severity": severity,
        "section": section,
        "message": message,
    }
    if remediation is not None:
        item["remediation"] = remediation
    return item


def _versions_section(
    findings: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """The ``versions`` section; second element flags a broken env."""
    broken = False
    try:
        importlib.import_module("s0ma")
    except Exception as exc:  # noqa: BLE001 - any import failure is the finding
        broken = True
        findings.append(
            _finding(
                "error",
                "versions",
                f"s0ma-dsl cannot import s0ma-core: {exc}",
                "Reinstall the toolchain: `pip install s0ma-core s0ma-dsl` "
                "(or `uv sync` in a uv-managed project).",
            )
        )

    versions = {
        "python": platform.python_version(),
        "s0ma_core": _dist_version("s0ma-core"),
        "s0ma_dsl": _dist_version("s0ma-dsl"),
        "s0ma_mcp": _dist_version("s0ma-mcp"),
        "s0ma_studi0": _dist_version("s0ma-studi0"),
        "mcp_sdk": _dist_version("mcp"),
    }
    for dist_key, dist_name in (("s0ma_core", "s0ma-core"), ("s0ma_dsl", "s0ma-dsl")):
        if versions[dist_key] is None:
            findings.append(
                _finding(
                    "warning",
                    "versions",
                    f"distribution metadata for {dist_name} was not found "
                    f"(the import machinery may still work)",
                    f"Reinstall {dist_name} so `importlib.metadata` can "
                    f"resolve it.",
                )
            )
    if versions["s0ma_mcp"] is None:
        findings.append(
            _finding(
                "info",
                "versions",
                "s0ma-mcp is not installed — optional; core+dsl-only "
                "installs are supported (INV-6)",
                "Install s0ma-mcp to author over MCP, then register it: "
                f"`{MCP_HINT}`.",
            )
        )
    # studi0 is optional in exactly the same sense as s0ma-mcp (the
    # transpiler never imports it — `s0ma studi0` defers the import to
    # its handler), so its absence is an info finding, never an error.
    if versions["s0ma_studi0"] is None:
        findings.append(
            _finding(
                "info",
                "versions",
                "s0ma-studi0 is not installed — optional; the local "
                "viewer is an install-time opt-in (INV-6)",
                "Install s0ma-studi0 to view a built project's component "
                f"graph, then run `{STUDI0_HINT}`.",
            )
        )
    return versions, broken


def _module_statuses(project: Any) -> tuple[list[dict[str, Any]], Any]:
    """Per-module build freshness for *project* (the project_status recipe).

    Returns ``(modules, manifest_or_None)``. Staleness compares the
    manifest's recorded ``source_hash`` against the **text** of the
    current source hashed with the manifest's own helper — the build
    hashes source text, not bytes.
    """
    from s0ma_dsl.cache import extract_module_name
    from s0ma_dsl.cli.main import _discover_s0ma_files
    from s0ma_dsl.codegen.build_manifest import (
        BuildManifest,
        ManifestSchemaError,
        compute_file_hash,
        load_manifest,
    )

    sources: list[Path] = []
    for discovery_root in (*project.source_roots, *project.test_roots):
        sources.extend(_discover_s0ma_files(str(discovery_root)))

    manifest: Any = None
    try:
        manifest = load_manifest(Path(project.build_dir))
    except ManifestSchemaError:
        manifest = None  # missing or unreadable — either way: not built

    entries_by_source: dict[Path, Any] = {}
    if manifest is not None:
        for entry in manifest.modules:
            # SH-M1 (INV-5): manifests written against a resolved
            # [tool.s0ma] project record ``source`` as a project-root-
            # relative POSIX path, resolved against the project root —
            # NOT the CWD. DSL-M3 (F-M1-1): the recipe now lives in the
            # one shared dsl helper ``BuildManifest.resolve_source`` (was
            # hand-copied here and in the two s0ma_mcp tools bodies).
            entries_by_source[
                BuildManifest.resolve_source(entry, project.root)
            ] = entry

    modules: list[dict[str, Any]] = []
    matched: set[Path] = set()
    for source in sources:
        resolved = source.resolve()
        entry = entries_by_source.get(resolved)
        if entry is None:
            modules.append(
                {
                    "name": str(extract_module_name(source)),
                    "source": str(source),
                    "status": "unbuilt",
                }
            )
            continue
        matched.add(resolved)
        current_hash = compute_file_hash(source.read_text(encoding="utf-8"))
        modules.append(
            {
                "name": str(entry.name),
                "source": str(source),
                "status": (
                    "fresh" if current_hash == entry.source_hash else "stale"
                ),
            }
        )
    for recorded in sorted(set(entries_by_source) - matched):
        entry = entries_by_source[recorded]
        modules.append(
            {
                "name": str(entry.name),
                "source": str(entry.source),
                "status": "orphaned",
            }
        )
    return modules, manifest


def _build_target(project: S0maProject) -> str | None:
    """The first source root that is really there, project-relative.

    ``s0ma doctor`` used to write ``src`` into its advice whatever the
    project looked like, which on the pilot's four flat packages named a
    directory that did not exist (G2-13). A directory nobody has is worse
    than no directory at all, so an absent root is left unsaid.
    """
    for source_root in project.source_roots:
        if source_root.is_dir():
            try:
                return source_root.relative_to(project.root).as_posix()
            except ValueError:  # pragma: no cover - roots resolve inside the root
                return source_root.name
    return None


def _mid_retrofit(project: S0maProject, mode: str) -> bool:
    """Is this project part way through converting existing Python?

    Two signals, either of which is enough, and neither of which reads a
    file's contents:

    * one of the retrofit's own records is on disk — a parity baseline
      (``s0ma adopt baseline``) or an adoption roster (``s0ma adopt
      file``). Both exist only because somebody started;
    * the project is in ``migration`` mode and there is plain Python
      inside the perimeter: a ``.py`` under a source root with no
      ``.s0ma`` beside it that the perimeter has not declared as a
      deliberate exception.

    Stops at the first plain file it finds, so a large tree costs a walk
    rather than a read.
    """
    from s0ma_dsl.adopt.model import BASELINE_FILENAME
    from s0ma_dsl.adoption import ADOPTED_FILENAME

    root = Path(project.root)
    if (root / BASELINE_FILENAME).is_file() or (root / ADOPTED_FILENAME).is_file():
        return True
    if mode != "migration":
        return False

    from s0ma_dsl.discovery import iter_visible_files

    declared: set[Path] = set()
    for path in (*project.bootstrap_files, *project.package_markers):
        try:
            declared.add(Path(path).resolve())
        except OSError:  # pragma: no cover - a declared path may not exist yet
            declared.add(Path(path))
    for source_root in project.source_roots:
        for candidate in iter_visible_files(source_root, "*.py"):
            try:
                resolved = candidate.resolve()
            except OSError:  # pragma: no cover - resolve fails on a broken tree
                resolved = candidate
            if resolved in declared or candidate.with_suffix(".s0ma").is_file():
                continue
            return True
    return False


def _project_section(
    start: Path, findings: list[dict[str, Any]]
) -> dict[str, Any]:
    """The ``project`` section: resolution + build freshness."""
    from s0ma_dsl.errors import S0maProjectNotFound
    from s0ma_dsl.project import S0maProject

    try:
        project = S0maProject.discover(start)
    except S0maProjectNotFound:
        findings.append(
            _finding(
                "info",
                "project",
                f"no s0ma project found walking up from {start}",
                "Run `s0ma new project <dir>` to initialize one, or add "
                "a [tool.s0ma] table to pyproject.toml.",
            )
        )
        return {"is_project": False, "searched_from": str(start)}
    except ValueError as exc:
        # Malformed [tool.s0ma] (unsupported test_runner, overlapping
        # roots, …) is a finding to render, never a crash (FR-DSL-5).
        findings.append(
            _finding(
                "error",
                "project",
                f"[tool.s0ma] is malformed: {exc}",
                "Fix the [tool.s0ma] table in pyproject.toml and re-run "
                "`s0ma doctor`.",
            )
        )
        return {"is_project": False, "config_error": str(exc)}

    import tomllib

    # `S0maProject` does not model [tool.s0ma].mode — read the one key
    # from the pyproject discovery just resolved, defaulting "dev" (the
    # same composition as the MCP server's project_status).
    mode = "dev"
    try:
        with (Path(project.root) / "pyproject.toml").open("rb") as fh:
            declared = tomllib.load(fh).get("tool", {}).get("s0ma", {})
        if isinstance(declared.get("mode"), str) and declared["mode"]:
            mode = declared["mode"]
    except (OSError, tomllib.TOMLDecodeError):  # pragma: no cover - resolved above
        pass

    modules, manifest = _module_statuses(project)
    built = manifest is not None
    not_fresh = sorted(
        str(m["name"]) for m in modules if m["status"] != "fresh"
    )
    if not built:
        build_status = "unbuilt"
    elif not_fresh:
        build_status = "stale"
    else:
        build_status = "fresh"

    # G3b (G1's H-2, pilot G2-13): a project in the middle of a retrofit
    # is not a greenfield project with no modules yet, and telling one to
    # create its first module — into a `src` directory it may not even
    # have — sends the reader away from the ladder they are on. The one
    # command that knows where they are answers instead, and doctor says
    # so rather than guessing at a rung.
    where = _build_target(project)
    if _mid_retrofit(project, mode):
        suggested = "mid-retrofit — `s0ma adopt status` has the next command"
    elif not modules:
        suggested = (
            f"run `s0ma new module <Name> -o {where}` to create the first module"
            if where
            else "run `s0ma new module <Name>` to create the first module"
        )
    elif not built:
        suggested = "run `s0ma build` — project not built yet"
    elif build_status == "stale":
        count = len(not_fresh)
        plural = "s" if count != 1 else ""
        suggested = f"run `s0ma build` — {count} module{plural} stale"
    else:
        suggested = "run `s0ma check`"

    if build_status != "fresh":
        findings.append(
            _finding(
                "warning",
                "project",
                f"build is {build_status}",
                suggested,
            )
        )

    return {
        "is_project": True,
        "root": str(project.root),
        "mode": mode,
        # STD-M4 (usability plan): the project's authoring posture, read
        # straight off the resolved S0maProject (default "on" when the
        # key is absent). s0ma-dsl never imports s0ma-mcp (INV-6/D-7) —
        # this is the dsl's own model field, the same value the MCP
        # server's project_status surfaces.
        "authoring": project.authoring,
        "module_count": len(modules),
        "modules": modules,
        "build": {
            "built": built,
            "status": build_status,
            "stale_modules": not_fresh if built else [],
            "transpiler_version": (
                str(manifest.transpiler_version) if built else None
            ),
        },
        "suggested_next_action": suggested,
    }


def _mcp_section(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """The ``mcp`` section: server executable on PATH + the hint."""
    executable = shutil.which("s0ma-mcp")
    if executable is None:
        findings.append(
            _finding(
                "info",
                "mcp",
                "the s0ma-mcp server executable is not on PATH",
                f"Install s0ma-mcp, then register it: `{MCP_HINT}`.",
            )
        )
    return {
        "found": executable is not None,
        "server_executable": executable,
        "registration_hint": MCP_HINT,
    }


def _render_text(report: dict[str, Any]) -> str:
    """Human rendering, derived from the structured report (P-5)."""
    lines: list[str] = ["s0ma doctor", ""]

    versions = report["versions"]
    lines.append("versions")
    for key, label in (
        ("python", "python"),
        ("s0ma_core", "s0ma-core"),
        ("s0ma_dsl", "s0ma-dsl"),
        ("s0ma_mcp", "s0ma-mcp"),
        ("s0ma_studi0", "s0ma-studi0"),
        ("mcp_sdk", "mcp SDK"),
    ):
        lines.append(f"  {label:<12}{versions[key] or 'not installed'}")

    project = report["project"]
    lines.append("")
    lines.append("project")
    if not project["is_project"]:
        if "config_error" in project:
            lines.append("  root        (malformed [tool.s0ma] — see findings)")
        else:
            lines.append(
                f"  root        not a s0ma project "
                f"(searched from {project['searched_from']})"
            )
    else:
        by_status: dict[str, int] = {}
        for module in project["modules"]:
            by_status[module["status"]] = by_status.get(module["status"], 0) + 1
        status_summary = ", ".join(
            f"{count} {status}" for status, count in sorted(by_status.items())
        )
        lines.append(f"  root        {project['root']}")
        lines.append(f"  mode        {project['mode']}")
        lines.append(f"  authoring   {project['authoring']}")
        lines.append(
            f"  modules     {project['module_count']}"
            + (f" ({status_summary})" if status_summary else "")
        )
        lines.append(f"  build       {project['build']['status']}")
        lines.append(f"  next        {project['suggested_next_action']}")

    mcp = report["mcp"]
    lines.append("")
    lines.append("mcp")
    lines.append(
        "  s0ma-mcp    "
        + (
            f"found at {mcp['server_executable']}"
            if mcp["found"]
            else "not found on PATH"
        )
    )
    lines.append(f"  register    {mcp['registration_hint']}")

    lines.append("")
    lines.append(f"license       {report['license']}")
    lines.append(f"update check  {report['update_check']}")
    lines.append(f"learn         {report['learn']}")

    findings = report["findings"]
    lines.append("")
    if findings:
        lines.append("findings")
        for item in findings:
            lines.append(
                f"  [{item['severity']}] {item['section']}: {item['message']}"
            )
            if "remediation" in item:
                lines.append(f"      -> {item['remediation']}")
    status = "ok" if report["ok"] else "BROKEN ENVIRONMENT"
    lines.append(f"{status} — {len(findings)} finding(s).")
    return "\n".join(lines)


def run_doctor(args: argparse.Namespace) -> int:
    """Execute ``s0ma doctor`` (see module docstring for semantics)."""
    json_mode: bool = getattr(args, "output_format", "text") == "json"
    start = (
        Path(args.project_root).resolve()
        if getattr(args, "project_root", None)
        else Path.cwd()
    )

    findings: list[dict[str, Any]] = []
    versions, broken = _versions_section(findings)
    project = _project_section(start, findings)
    mcp = _mcp_section(findings)

    report: dict[str, Any] = {
        "ok": not broken,
        "versions": versions,
        "project": project,
        "mcp": mcp,
        "license": LICENSE_PLACEHOLDER,
        "update_check": UPDATE_CHECK_PLACEHOLDER,
        "learn": LEARN_HINT,
        "findings": findings,
    }

    if json_mode:
        print(json.dumps(report, indent=2))
    else:
        print(_render_text(report))

    # Doctor diagnoses, it does not gate: findings exit 0; only a broken
    # environment (core unimportable) is non-zero.
    return EXIT_SUCCESS if not broken else EXIT_INTERNAL_ERROR
