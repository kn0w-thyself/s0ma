"""``s0ma new project --step N``: lay down a sample one step at a time.

A template declared as steps (:class:`s0ma_dsl.cli.templates.ArchetypeStep`)
can be laid down to any step from 0 to its last. No state file records the
step a project is on: it is worked out from the project's files each time
(:func:`current_step`).

- Step 0 is the bare project: everything the scaffolder writes that is not
  a step's file, with no module and no build.
- On a folder that is not a s0ma project yet, ``--step N`` lays down steps
  1 to N at once, through the same scaffolder as the whole sample.
- On a project at an earlier step, it adds what the later steps add,
  replaces what they replace, and builds. A file it would replace that was
  edited since the template wrote it stops the call before anything is
  written. Files no later step touches are kept, and the summary names the
  ones that are not the template's.
- On a project already at step N it writes nothing. On a project past
  step N it refuses.

No network I/O anywhere (PRD P-6 / INV-9).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from s0ma_dsl.cli.migrate_grammar import current_grammar_source
from s0ma_dsl.cli.new_project import (
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    EXIT_VALIDATION_ERROR,
    FEEDBACK_SKILL_RELPATH,
    LAUNCH_CONFIG_RELPATH,
    _archetype_refusal_reasons,
    _first_build,
    _print_archetype_summary,
    _print_refusal,
    write_bare_project,
)
from s0ma_dsl.cli.templates import Archetype, ArchetypeFile, get_archetype

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

#: Files at the project root that the bare project writes and no step
#: touches. They are the person's after step 0, so they are not listed as
#: kept.
_BARE_ROOT_FILES = frozenset({"pyproject.toml", "AGENTS.md", "CLAUDE.md"})


def template_bytes(file: ArchetypeFile) -> bytes:
    """The bytes the scaffolder writes for *file* (``.s0ma`` in the current grammar)."""
    content = file.content
    if file.relpath.endswith(".s0ma"):
        content = current_grammar_source(content, file.relpath)
    return content.encode("utf-8")


def _on_disk(target: Path, relpath: str) -> bytes | None:
    """The file at *relpath* with CRLF read as LF, or ``None`` when absent."""
    path = target.joinpath(*relpath.split("/"))
    if not path.is_file():
        return None
    return path.read_bytes().replace(b"\r\n", b"\n")


def current_step(target: Path, archetype: Archetype) -> int:
    """The step the project at *target* is on, worked out from its files.

    Step K is reached when every file of steps 1 to K is there and the
    files step K adds show it was laid down: at least one of the paths new
    at step K is as the template wrote it (for a step that only replaces
    files, all of its files are). The answer is the highest step reached,
    or 0 when none is. So an edit to a file that is already there does not
    move a project back a step, and a file the person wrote at a later
    step's path does not move it forward.
    """
    seen: set[str] = set()
    signs: list[tuple[ArchetypeFile, ...]] = []
    for step in archetype.steps:
        new = tuple(f for f in step.files if f.relpath not in seen)
        signs.append(new)
        seen.update(f.relpath for f in step.files)

    for number in range(len(archetype.steps), 0, -1):
        if any(
            _on_disk(target, f.relpath) is None
            for f in archetype.files_through(number)
        ):
            continue
        new = signs[number - 1]
        if new:
            reached = any(
                _on_disk(target, f.relpath) == template_bytes(f) for f in new
            )
        else:
            reached = all(
                _on_disk(target, f.relpath) == template_bytes(f)
                for f in archetype.steps[number - 1].files
            )
        if reached:
            return number
    return 0


def kept_files(target: Path, files: tuple[ArchetypeFile, ...]) -> list[str]:
    """Files in the project that are not the template's *files* as written.

    That is every file the person added, and every template file they
    edited. The build folder, folders whose name starts with a dot, Python
    caches, and the bare project's own root files are left out.
    """
    expected = {f.relpath: template_bytes(f) for f in files}
    kept: list[str] = []
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(target).parts
        if parts[0] == "build" or any(
            part.startswith(".") or part == "__pycache__" for part in parts
        ):
            continue
        relpath = "/".join(parts)
        if relpath in _BARE_ROOT_FILES:
            continue
        if relpath in expected and _on_disk(target, relpath) == expected[relpath]:
            continue
        kept.append(relpath)
    return kept


def step_line(archetype: Archetype, number: int, target: Path) -> str:
    """The first line a ``--step`` call prints, from the step's own words."""
    total = len(archetype.steps)
    if number == 0:
        return (
            f"Step 0 of {total}: the project is ready at {target}, "
            f"and nothing is built yet."
        )
    step = archetype.steps[number - 1]
    return f"Step {number} of {total}: {step.name}. {step.intent}"


def step_report(
    archetype: Archetype,
    number: int,
    target: Path,
    *,
    written: list[str],
    kept: list[str],
    unchanged: bool = False,
) -> dict[str, Any]:
    """The facts a ``--step`` call adds to the summary, text and JSON alike."""
    total = len(archetype.steps)
    step = archetype.steps[number - 1] if number else None
    return {
        "step": {
            "number": number,
            "of": total,
            "name": step.name if step else None,
            "intent": step.intent if step else None,
        },
        "line": step_line(archetype, number, target),
        "finished": number == total,
        "unchanged": unchanged,
        "files_written": written,
        "files_kept": kept,
    }


def _read_pyproject(pyproject: Path) -> tuple[dict[str, Any] | None, bool]:
    """``(data, parsed)`` for *pyproject*; ``(None, True)`` when it is absent."""
    import tomllib

    if not pyproject.is_file():
        return None, True
    try:
        with pyproject.open("rb") as fh:
            return tomllib.load(fh), True
    except tomllib.TOMLDecodeError:
        return None, False


def _is_this_sample(table: dict[str, Any], archetype: Archetype) -> bool:
    """Whether a ``[tool.s0ma]`` table is the one this template writes."""
    return list(table.get("bootstrap_files", [])) == list(
        archetype.bootstrap_files
    ) and table.get("health_command", "") == archetype.health_command


def run_step(
    *,
    template: str,
    number: int,
    target: Path,
    project_name: str,
    mode: str,
    authoring: str,
    json_mode: bool,
    quiet: bool,
    fail: Callable[[dict[str, Any], str, int], int],
) -> int:
    """Bring the project at *target* to step *number* of *template*."""
    from s0ma_dsl.cli.new_project import _scaffold_archetype

    archetype = get_archetype(template)
    total = len(archetype.steps)
    if not total:
        return fail(
            {"error": f"--template {template} has no steps"},
            f"s0ma new project: --template {template} has no steps, so "
            f"--step does not apply to it.",
            EXIT_USAGE_ERROR,
        )
    if not 0 <= number <= total:
        return fail(
            {"error": f"--step must be between 0 and {total}, not {number}"},
            f"s0ma new project: --step must be between 0 and {total} for "
            f"--template {template}, not {number}.",
            EXIT_USAGE_ERROR,
        )

    pyproject = target / "pyproject.toml"
    agents_path = target / "AGENTS.md"
    claude_path = target / "CLAUDE.md"
    data, parsed = _read_pyproject(pyproject)
    table = (data or {}).get("tool", {}).get("s0ma") if parsed else None

    if parsed and table is None:
        # Not a s0ma project yet: lay down steps 1 to N at once.
        if number:
            return _scaffold_archetype(
                template=template,
                target=target,
                project_name=project_name,
                mode=mode,
                authoring=authoring,
                json_mode=json_mode,
                quiet=quiet,
                fail=fail,
                count=number,
            )
        return _lay_down_bare(
            archetype=archetype,
            target=target,
            project_name=project_name,
            mode=mode,
            authoring=authoring,
            json_mode=json_mode,
            quiet=quiet,
        )

    if table is None or not _is_this_sample(table, archetype):
        # Unreadable, or a s0ma project from something else: the same
        # refusal as today.
        planned = [
            (target / f.relpath, f.content)
            for f in archetype.files_through(max(number, 1))
        ]
        reasons = _archetype_refusal_reasons(
            target, pyproject, planned, agents_path, claude_path
        )
        return _print_refusal(target, reasons, json_mode)

    project_mode = str(table.get("mode", mode))
    project_authoring = str(table.get("authoring", authoring))
    name = str((data or {}).get("project", {}).get("name", project_name))
    at = current_step(target, archetype)
    if at > number:
        return fail(
            {
                "project_root": str(target),
                "error": f"the project is at step {at}, past step {number}",
                "at_step": at,
                "of": total,
            },
            f"s0ma new project: {target} is at step {at} of {total}, and "
            f"--step does not go back to step {number}.",
            EXIT_VALIDATION_ERROR,
        )

    files = archetype.files_through(number) if number else ()
    written: list[str] = []
    if at < number:
        was = {
            f.relpath: template_bytes(f)
            for f in (archetype.files_through(at) if at else ())
        }
        conflicts: list[str] = []
        for file in files:
            disk = _on_disk(target, file.relpath)
            new = template_bytes(file)
            if disk == new or was.get(file.relpath) == new:
                # Already as the step writes it, or a file no later step
                # touches: left as it is.
                continue
            if disk is not None and disk != was.get(file.relpath):
                by = next(
                    n
                    for n in range(at + 1, number + 1)
                    if file in archetype.steps[n - 1].files
                )
                conflicts.append(
                    f"{file.relpath} has changes of yours, and step {by} "
                    f"would replace it"
                )
                continue
            written.append(file.relpath)
        if conflicts:
            if json_mode:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "project_root": str(target),
                            "at_step": at,
                            "refusals": conflicts,
                        },
                        indent=2,
                    )
                )
            else:
                print(
                    f"s0ma new project: refusing to bring {target} to step "
                    f"{number} (nothing was changed):"
                )
                for reason in conflicts:
                    print(f"  - {reason}")
            return EXIT_VALIDATION_ERROR

        by_path = {f.relpath: f for f in files}
        for relpath in written:
            path = target.joinpath(*relpath.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(template_bytes(by_path[relpath]))

        build_rc, build_output = _first_build(target, project_mode)
        if build_rc != EXIT_SUCCESS:
            return fail(
                {
                    "project_root": str(target),
                    "error": f"the build failed (exit code {build_rc})",
                    "build_output": build_output.strip(),
                },
                f"s0ma new project: the files of step {number} were written "
                f"to {target}, but the build failed (exit code {build_rc}):"
                f"\n{build_output.strip()}",
                build_rc,
            )

    build_dir = target / "build"
    return _print_archetype_summary(
        archetype=archetype,
        files=files,
        target=target,
        project_name=name,
        mode=project_mode,
        authoring=project_authoring,
        pyproject=pyproject,
        pyproject_action="kept",
        agents_path=agents_path,
        claude_path=claude_path,
        skill_path=target.joinpath(*FEEDBACK_SKILL_RELPATH.split("/")),
        skill_created=False,
        launch_path=target.joinpath(*LAUNCH_CONFIG_RELPATH.split("/")),
        launch_created=False,
        build_dir=build_dir if number and build_dir.is_dir() else None,
        json_mode=json_mode,
        quiet=quiet,
        step=step_report(
            archetype,
            number,
            target,
            written=written,
            kept=kept_files(target, files),
            unchanged=at == number,
        ),
        verb="updated",
    )


def _lay_down_bare(
    *,
    archetype: Archetype,
    target: Path,
    project_name: str,
    mode: str,
    authoring: str,
    json_mode: bool,
    quiet: bool,
) -> int:
    """Step 0 on a folder that is not a s0ma project: the bare project only."""
    pyproject = target / "pyproject.toml"
    agents_path = target / "AGENTS.md"
    claude_path = target / "CLAUDE.md"
    reasons = _archetype_refusal_reasons(
        target, pyproject, [], agents_path, claude_path
    )
    if reasons:
        return _print_refusal(target, reasons, json_mode)
    bare = write_bare_project(target, archetype, project_name, mode, authoring)
    return _print_archetype_summary(
        archetype=archetype,
        files=(),
        target=target,
        project_name=project_name,
        mode=mode,
        authoring=authoring,
        pyproject=pyproject,
        pyproject_action=bare.pyproject_action,
        agents_path=agents_path,
        claude_path=claude_path,
        skill_path=bare.skill_path,
        skill_created=bare.skill_created,
        launch_path=bare.launch_path,
        launch_created=bare.launch_created,
        build_dir=None,
        json_mode=json_mode,
        quiet=quiet,
        step=step_report(
            archetype,
            0,
            target,
            written=bare.written,
            kept=kept_files(target, ()),
        ),
    )
