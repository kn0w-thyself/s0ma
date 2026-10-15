"""``s0ma adopt`` subcommand handlers (0.11.0, batch-01a D2).

The adoption *primitive*: ``s0ma adopt file <path>`` registers a real,
non-generated file into the project self-model — recorded by
project-root-relative path + content hash in the committed
``adopted.s0ma.json`` sidecar (see :mod:`s0ma_dsl.adoption` for the
persistence design decision). ``s0ma verify`` then classifies the file
``ADOPTED`` (content-hash verified; drift is an actionable failure) and
``s0ma score`` counts it as registered — closing the hollow-model gap
where real ``_impl.py`` files accumulated beside generated code with
verify green throughout (bench P2_P_r02).

The *ladder* starts at ``s0ma adopt scan`` (beta-prep-1-retrofit B4): the
rung-0 read that says what is in a plain-Python tree and in what order to
convert it. It writes nothing anywhere and never imports the code it is
looking at (retrofit rules R-1 and R-2). ``s0ma adopt init`` (C1) is rung
1: it writes the perimeter that scan printed — a ``[tool.s0ma]`` table
and one ``AGENTS.md`` block, and nothing else anywhere — so the tree
becomes a s0ma project without a line of application code changing.
``s0ma adopt draft`` (D4) opens rung 3: it turns one Python module into
a ``.s0ma`` draft whose structure is derived and whose meaning is left
as work for a person, and it never touches the Python file it read.
``s0ma adopt baseline`` and ``s0ma adopt verify-parity`` (E2) are the
promise that makes rung 3 safe: the first records what a module's Python
offered its callers *before* anything is deleted, the second compares
that record with the module the build emitted and names every
difference. ``s0ma adopt status`` (E3) completes the family: it reads
the whole ladder and answers, for somebody coming back to a half-done
retrofit, where they are, what is done, what is left and the one command
to run now — writing nothing, like the scan. The mechanisms live in
:mod:`s0ma_dsl.adopt` and this module is only the commands around them.
The family is complete: adding a seventh sub-command means a milestone
that carries its documentation rulings with it.
"""

from __future__ import annotations

import json
import os
import re
import sys
import textwrap
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma.models import AdoptedFile

from s0ma_dsl.adoption import (
    ADOPTED_FILENAME,
    AdoptedRecordError,
    compute_adopted_hash,
    load_adopted_files,
    save_adopted_files,
)
from s0ma_dsl.discovery import iter_visible_files

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from s0ma_dsl.adopt.model import ScanReport, SourceFile
    from s0ma_dsl.adopt.status import AliasPlan
    from s0ma_dsl.project import S0maProject

__all__ = [
    "cmd_adopt_baseline",
    "cmd_adopt_draft",
    "cmd_adopt_file",
    "cmd_adopt_init",
    "cmd_adopt_scan",
    "cmd_adopt_status",
    "cmd_adopt_verify_parity",
]

# Exit codes mirror cli/main.py's PRD §2.8.2 contract.
_EXIT_SUCCESS = 0
_EXIT_VALIDATION_ERROR = 1
_EXIT_USAGE_ERROR = 2

#: The column the retrofit family's prose folds at — the width
#: ``adopt scan`` reports at and ``adopt init`` closes at, so somebody
#: walking the ladder reads one thing rather than three.
_WRAP = 88

#: How many near-misses a "no module called that" refusal offers. Three
#: is enough to recognise the one you meant and short enough to read in
#: the sentence that names them.
_SUGGESTION_LIMIT = 3

#: Roles :func:`~s0ma_dsl.adopt.discovery.discover_sources` gives a file
#: that a draft can be taken from: application code, and a script that
#: carries a ``__main__`` guard outside any package. The other two roles
#: are refused by name, each with its own reason.
_DRAFTABLE_ROLES = frozenset({"app", "script"})

#: The transpiler's per-file hash headers. A file carrying both is a
#: transpiled s0ma artifact — already registered through its ``.s0ma``
#: source — so adopting it would double-count; the command refuses.
_SOURCE_HASH_RE = re.compile(
    r"^# s0ma-source-hash:\s*sha256:(\w+)$", re.MULTILINE,
)
_OUTPUT_HASH_RE = re.compile(
    r"^# s0ma-output-hash:\s*sha256:(\w+)$", re.MULTILINE,
)


def _fail(
    message: str, *, output_format: str, code: int, command: str = "adopt file"
) -> int:
    """Print *message* as an error in the requested format; return *code*.

    *command* names the sub-command in the text form, so a refusal says
    which one refused. It defaults to ``adopt file`` because that is the
    only caller that predates the family.
    """
    if output_format == "json":
        print(json.dumps({"ok": False, "error": message}, indent=2))
    else:
        print(f"s0ma {command}: {message}", file=sys.stderr)
    return code


def cmd_adopt_file(args: argparse.Namespace) -> int:
    """Handler for ``s0ma adopt file <path>``.

    Records the file (project-root-relative POSIX path + current
    content hash + mandatory intent description) in ``adopted.s0ma.json`` at
    the project root. Re-adopting refreshes the hash and increments an
    advisory history counter; componentization is the preferred drift
    remediation because roster adoption remains interim debt. Refusals
    (all exit 2, nothing written): no resolved ``[tool.s0ma]`` project;
    path missing, not a regular file, or outside the project root
    (NFR-6); file already a transpiled s0ma artifact (carries the
    transpiler hash headers); file already declared under
    ``[tool.s0ma].bootstrap_files`` or ``package_markers`` (one
    classification per file, the CONFLICTING_PACKAGE_DECLARATION rule).
    """
    output_format: str = getattr(args, "output_format", "text")
    project: S0maProject | None = getattr(args, "s0ma_project", None)
    if project is None or project.synthetic:
        return _fail(
            "no [tool.s0ma] project resolved. Adoption records are "
            "project state (written to adopted.s0ma.json at the project "
            "root), so a [tool.s0ma] table is required — add one to "
            "pyproject.toml (`s0ma new project`, or the init_project "
            "MCP tool), then re-run.",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
        )

    target = Path(args.path)
    if not target.is_absolute():
        target = Path.cwd() / target
    try:
        resolved = target.resolve()
    except OSError:
        resolved = target
    if not resolved.is_file():
        return _fail(
            f"{args.path} is not an existing regular file — adoption "
            f"registers real files by content hash, so the file must "
            f"exist on disk.",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
        )

    try:
        root_resolved = project.root.resolve()
    except OSError:
        root_resolved = project.root
    try:
        rel = resolved.relative_to(root_resolved)
    except ValueError:
        return _fail(
            f"{resolved} is outside the project root ({root_resolved}). "
            f"Adoption records are project state; only files inside the "
            f"project tree can be adopted (NFR-6).",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
        )
    rel_posix = rel.as_posix()

    # One classification per file — mirror the loud
    # CONFLICTING_PACKAGE_DECLARATION stance instead of letting two
    # surfaces claim the same file.
    declared_bootstrap = {p.resolve() for p in project.bootstrap_files if p.exists()}
    declared_markers = {p.resolve() for p in project.package_markers if p.exists()}
    if resolved in declared_bootstrap:
        return _fail(
            f"{rel_posix} is declared under [tool.s0ma].bootstrap_files. "
            f"A file has exactly one classification — remove it from "
            f"bootstrap_files first if you want to adopt it instead.",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
        )
    if resolved in declared_markers:
        return _fail(
            f"{rel_posix} is declared under [tool.s0ma].package_markers. "
            f"A file has exactly one classification — remove it from "
            f"package_markers first if you want to adopt it instead.",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
        )

    try:
        content = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        return _fail(
            f"cannot read {rel_posix}: {exc}",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
        )
    except UnicodeDecodeError:
        return _fail(
            f"{rel_posix} is not UTF-8 text. Adoption hashes UTF-8 text "
            f"content (the same convention as the build manifest), so "
            f"binary files cannot be adopted.",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
        )

    if _SOURCE_HASH_RE.search(content) and _OUTPUT_HASH_RE.search(content):
        return _fail(
            f"{rel_posix} is a transpiled s0ma artifact (it carries the "
            f"transpiler's s0ma-source-hash/s0ma-output-hash headers) — "
            f"it is already registered through its .s0ma source, so "
            f"adopting it would double-count. Adoption is for plain "
            f"files the model does not already own.",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
        )

    try:
        records = load_adopted_files(project.root)
    except AdoptedRecordError as exc:
        return _fail(str(exc), output_format=output_format, code=_EXIT_VALIDATION_ERROR)

    re_adopted = rel_posix in records
    content_hash = compute_adopted_hash(resolved)
    description = str(getattr(args, "description", "") or "").strip()
    if not description:
        return _fail(
            "--description is required and must be a non-empty one-line "
            "intent. adopt file is migration intake, and semantic intent "
            "cannot be inferred from the path.",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
        )
    if "\n" in description or "\r" in description:
        return _fail(
            "--description must be one non-empty line of authored intent.",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
        )
    re_adopt_count = (
        records[rel_posix].re_adopt_count + 1 if re_adopted else 0
    )
    record = AdoptedFile(
        path=rel_posix,
        description=description,
        content_hash=content_hash,
        re_adopt_count=re_adopt_count,
    )
    records[rel_posix] = record
    record_path = save_adopted_files(project.root, records)

    if output_format == "json":
        componentized_count, roster_count = _registration_counts(project)
        next_actions: list[dict[str, object]] = [{
            "tool": "author_module",
            "arguments": {
                "project_root": str(project.root),
                "module_name": Path(rel_posix).stem,
            },
            "reason": (
                "Componentize this migration intake: roster-adopted files "
                "cannot answer semantic self-model queries."
            ),
        }]
        warnings = _churn_warnings(rel_posix, re_adopt_count, next_actions[0])
        print(json.dumps({
            "schema": "s0ma-tool-result@1",
            "ok": True,
            "status": "interim",
            "path": rel_posix,
            "content_hash": content_hash,
            "description": record.description,
            "record": str(record_path),
            "re_adopted": re_adopted,
            "re_adopt_count": re_adopt_count,
            "counts": {
                "componentized": componentized_count,
                "roster_adopted": roster_count,
            },
            "next_actions": next_actions,
            "warnings": warnings,
        }, indent=2))
        return _EXIT_SUCCESS

    verb = "Re-adopted" if re_adopted else "Adopted"
    print(f"{verb} {rel_posix} ({content_hash})")
    print(f"Recorded in {ADOPTED_FILENAME} — commit it with the file.")
    componentized_count, roster_count = _registration_counts(project)
    print("Status: interim migration intake; this is not componentization.")
    print(
        f"Current surface: {componentized_count} componentized, "
        f"{roster_count} roster-adopted."
    )
    print(
        f"Next: call author_module for {rel_posix}; adopted files cannot "
        f"answer semantic queries. After an intentional edit, componentize "
        f"first; re-adoption only refreshes migration telemetry."
    )
    if re_adopt_count >= 3:
        print(
            f"WARNING ADOPTED_CHURN: {rel_posix} has been re-adopted "
            f"{re_adopt_count} times; componentize it with author_module."
        )
    return _EXIT_SUCCESS


def cmd_adopt_scan(args: argparse.Namespace) -> int:
    """Handler for ``s0ma adopt scan [PATH]`` — rung 0 of the retrofit ladder.

    Reads a tree of plain Python and says what is in it, what perimeter it
    would declare, in what order to convert it, what is worth knowing
    first, and the one command to run next. **It writes nothing anywhere**
    (retrofit rule R-2) and never imports or executes the code it is
    reading (R-1), so it is safe to point at a codebase nobody has decided
    anything about yet.

    ``PATH`` defaults to the project root the CLI resolved
    (``--project-root``, else the current directory). ``--source-root``
    may be given more than once and overrides what the tree would
    otherwise be read as. ``--detail MODULE`` prints one module in full
    instead of the summary; ``--format json`` prints the whole report as
    ``s0ma-adopt-scan@1`` and nothing else on stdout.

    A file that will not parse is a fact in the report, not a failure: the
    scan still exits 0. The only refusals (exit 2, nothing written) are
    about the request itself — a path that is not a directory, a tree with
    no Python in it, and a ``--detail`` naming a module the scan did not
    find.
    """
    from s0ma_dsl.adopt.model import dump_json
    from s0ma_dsl.adopt.report import (
        read_scan,
        render_detail_text,
        render_scan_text,
    )

    output_format: str = getattr(args, "output_format", "text")
    given: str | None = getattr(args, "path", None)
    root, shown = _scan_root(args, given)

    if not root.is_dir():
        return _fail(
            f"{shown} is not a directory that can be scanned. Point the scan "
            f"at the top of the codebase you want to convert — the directory "
            f"holding its pyproject.toml, or its source folder.",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
            command="adopt scan",
        )

    declared = tuple(getattr(args, "source_root", None) or ())
    reading = read_scan(root, declared or None)
    report = reading.report

    if not report.modules:
        outside = reading.scope.outside_files
        elsewhere = (
            f" {outside} Python "
            f"{'file is' if outside == 1 else 'files are'} here but outside "
            f"{_join_words([f'`{entry}`' for entry in reading.scope.source_roots])}."
            if outside
            else ""
        )
        return _fail(
            f"no Python files were found under {shown}, so there is nothing to "
            f"scan.{elsewhere} Check that this is the right directory; if the "
            f"code lives in a sub-folder, either point the scan at it or name "
            f"it with --source-root.",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
            command="adopt scan",
        )

    detail: str | None = getattr(args, "detail", None)
    if detail is not None and not any(
        census.source.module == detail for census in report.modules
    ):
        return _fail(
            f"no module called {detail} was found in this scan. Run the scan "
            f"without --detail to see the modules it found, and use the dotted "
            f"name exactly as it is printed there.",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
            command="adopt scan",
        )

    if output_format == "json":
        # The JSON report already carries every censused module in full, so
        # --detail narrows nothing here; it is validated above so a typo is
        # still caught, and the whole reading is printed. What is *outside*
        # the source roots is in `scope`, counted by directory rather than
        # detailed file by file — nobody is converting it.
        print(dump_json(reading.to_dict()), end="")
        return _EXIT_SUCCESS

    if detail is not None:
        print(render_detail_text(report, detail), end="")
        return _EXIT_SUCCESS

    print(render_scan_text(reading), end="")
    return _EXIT_SUCCESS


def cmd_adopt_status(args: argparse.Namespace) -> int:
    """Handler for ``s0ma adopt status [PATH]`` — where am I on the ladder?

    The command for coming back. It reads the tree and answers four
    questions in one screen — where am I, what is done, what is left, and
    what is the one command to run now — for somebody who has not read the
    guide and may not have touched this project for a fortnight.

    **It writes nothing anywhere** (retrofit rule R-2) and never imports or
    executes the code it is reading (R-1), exactly like ``s0ma adopt
    scan``: the drafts are read as text, the built modules are parsed, and
    the classification comes from the reader ``s0ma verify`` already uses.

    ``PATH`` defaults to the project root the CLI resolved
    (``--project-root``, else the current directory) and works the way the
    scan's does, because rung 0 — a tree with no ``[tool.s0ma]`` table at
    all — is a real answer here and not a refusal. ``--format json`` prints
    an ``s0ma-adopt-status@1`` document for an agent.

    Exit 0 whenever the status could be read, whatever it says: a status is
    a reading, never a verdict, and a project halfway up the ladder is not
    a failure. Exit 2 only when ``PATH`` is not a directory or cannot be
    read at all.
    """
    from s0ma_dsl.adopt.model import dump_json
    from s0ma_dsl.adopt.status import read_ladder, render_status_text

    output_format: str = getattr(args, "output_format", "text")
    given: str | None = getattr(args, "path", None)
    root, shown = _scan_root(args, given)

    if not root.is_dir():
        return _fail(
            f"{shown} is not a directory, so there is no project there to "
            f"report on. Point this at the top of the codebase you are "
            f"retrofitting — the directory holding its pyproject.toml.",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
            command="adopt status",
        )

    try:
        reading = read_ladder(root)
    except OSError as unreadable:
        return _fail(
            f"{shown} could not be read ({unreadable}). Check that the "
            f"directory is readable, then run this again.",
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
            command="adopt status",
        )

    if output_format == "json":
        print(dump_json(reading.to_dict()), end="")
    else:
        print(render_status_text(reading), end="")
    return _EXIT_SUCCESS


def cmd_adopt_init(args: argparse.Namespace) -> int:
    """Handler for ``s0ma adopt init [PATH]`` — rung 1 of the retrofit ladder.

    Makes an existing tree of plain Python a s0ma project **without
    touching a line of application code**. Exactly two files may change:
    the ``[tool.s0ma]`` table appended to ``pyproject.toml`` (created
    minimal when the tree has none), and one marked block appended to
    ``AGENTS.md``. No starter module, no test directory, no adoption
    record, no build — rung 1 sets the perimeter and stops (retrofit rule
    R-4), because the ``UNKNOWN`` backlog ``s0ma verify`` then reports is
    the honest list of what is left to convert.

    The perimeter written is the one ``s0ma adopt scan`` printed, read
    from the same scan; ``--source-root`` (repeatable) overrides which
    directories hold the code. ``--dry-run`` prints exactly what would be
    written and writes nothing.

    Refusals, all exit 2 with nothing written: a path that is not a
    directory; a tree that is already a s0ma project; a tree with no
    Python in it; a ``pyproject.toml`` that is not valid TOML; and a
    perimeter the project loader will not take, in which case
    ``pyproject.toml`` is restored to its exact previous bytes first.
    """
    from s0ma_dsl.adopt.perimeter import (
        PerimeterRefusedError,
        apply_perimeter,
        refuse_if_already_a_project,
        render_dry_run_text,
        render_init_text,
    )
    from s0ma_dsl.adopt.report import read_scan

    given: str | None = getattr(args, "path", None)
    root, shown = _scan_root(args, given)

    if not root.is_dir():
        return _fail(
            f"{shown} is not a directory that can be made a s0ma project. "
            f"Point this at the top of the codebase you want to convert — "
            f"the directory holding its pyproject.toml, or its source folder.",
            output_format="text",
            code=_EXIT_USAGE_ERROR,
            command="adopt init",
        )

    try:
        refuse_if_already_a_project(root)
    except PerimeterRefusedError as refusal:
        return _fail(
            str(refusal),
            output_format="text",
            code=_EXIT_USAGE_ERROR,
            command="adopt init",
        )

    declared = tuple(getattr(args, "source_root", None) or ())
    reading = read_scan(root, declared or None)
    report = reading.report
    if not report.modules:
        return _fail(
            f"no Python files were found under {shown}, so there is nothing "
            f"to set a perimeter around. Check that this is the right "
            f"directory; if the code lives in a sub-folder, either point this "
            f"at it or name it with --source-root.",
            output_format="text",
            code=_EXIT_USAGE_ERROR,
            command="adopt init",
        )

    dry_run = bool(getattr(args, "dry_run", False))
    try:
        # The scan already knows where this tree's tests live, inside the
        # perimeter and outside it; naming them is what keeps a test suite
        # off the unconverted list for ever.
        result = apply_perimeter(
            root,
            report.perimeter,
            dry_run=dry_run,
            test_directories=reading.scope.test_directories,
        )
    except PerimeterRefusedError as refusal:
        return _fail(
            str(refusal),
            output_format="text",
            code=_EXIT_USAGE_ERROR,
            command="adopt init",
        )
    except OSError as exc:
        return _fail(
            f"the perimeter could not be written ({exc}). Check that you can "
            f"write to this directory, then run this again.",
            output_format="text",
            code=_EXIT_USAGE_ERROR,
            command="adopt init",
        )

    print(
        render_dry_run_text(result) if dry_run else render_init_text(result),
        end="",
    )
    if not dry_run:
        # G1's H-13: the first thing a careful person asks after a
        # command writes into their repository is what belongs in git.
        # Nothing said, so the trial's agent wrote a .gitignore and
        # reasoned each line out. This says it once, in the place they
        # are looking — and writes nothing: a .gitignore is the user's
        # file and rung 1 touches no file it was not asked to.
        print(_render_version_control_text(result.build_dir), end="")
    return _EXIT_SUCCESS


def _render_version_control_text(build_dir: str) -> str:
    """Which of s0ma's own files belong in version control, and the ignore lines.

    Three answers and the reasons behind them: the records are the
    project's memory and are committed; the build directory is committed
    when the application imports it, because then it is part of what
    ships; the caches are not, because they are derived and per-machine.

    Every one of those files is in the future tense, and the text says
    so. This is printed four commands before anything has been built, so
    a reader who looks for the build directory will not find it — G3c's
    trial agent stopped to check the line was not a typo.
    """
    from s0ma_dsl.adopt.model import BASELINE_FILENAME
    from s0ma_dsl.adopt.perimeter import AGENTS_FILENAME
    from s0ma_dsl.adoption import ADOPTED_FILENAME

    return "\n".join([
        "",
        *_wrap(
            f"What to keep in version control: pyproject.toml and "
            f"{AGENTS_FILENAME} as always, and — when they appear — the "
            f"records {BASELINE_FILENAME} and {ADOPTED_FILENAME}, which are "
            f"what your Python promised before it changed and cannot be taken "
            f"again. There is no {build_dir}/ yet: once you have built "
            f"something, commit that too, because by then it is part of what "
            f"ships. These two are derived and belong in .gitignore — the "
            f"first of them appears with that build:"
        ),
        "",
        f"  {build_dir}/.s0ma.cache/",
        "  __pycache__/",
    ]) + "\n"


def cmd_adopt_draft(args: argparse.Namespace) -> int:
    """Handler for ``s0ma adopt draft MODULE_OR_FILE`` — rung 3 begins here.

    Turns one Python module into a ``.s0ma`` draft. Structure is derived
    — each top-level function becomes a nerve or a helper, each class and
    each upper-case constant becomes a cell, bodies are carried across
    byte for byte, imports are sorted into the header's lists — and
    meaning is not: every field that says what something is *for* arrives
    as a ``FIXME(adopt):`` placeholder that ``s0ma check`` refuses in
    every mode, so a half-written conversion cannot build green (ruling
    R-5).

    **The Python file is never modified, moved or deleted.** It is read
    and parsed with :mod:`ast`, never imported and never executed (rule
    R-1), and it stays the code that runs until a person deletes it.

    ``MODULE_OR_FILE`` is the dotted name the scan prints
    (``bookshelf.errors``) or a path to the file
    (``src/bookshelf/errors.py``). Both are resolved through the same
    reading ``s0ma adopt scan`` uses, so the two commands can never
    disagree about what a module is called. ``--layer`` names the
    module's single layer; without it the layer comes from the scan's
    proposal when that proposal is confident, and otherwise the draft
    asks for one. ``--out`` writes the draft into another directory,
    ``--force`` allows an overwrite, and ``--dry-run`` prints the draft
    to stdout and writes nothing at all.

    Refusals, all exit 2 with nothing written: no ``[tool.s0ma]``
    project; a name nothing matches (the nearest names are offered) or
    that more than one file answers to; a test file, a package marker, a
    generated artifact, or a file outside the project; an unknown
    ``--layer``; a draft already in the way; and a module that has been
    converted already.
    """
    from s0ma_dsl.adopt.draft_emit import emit_draft
    from s0ma_dsl.adopt.harvest import HarvestError, harvest_module
    from s0ma_dsl.adopt.model import DRAFT_INTENT_MARKER
    from s0ma_dsl.adopt.report import build_scan_report

    def refuse(message: str) -> int:
        return _fail(
            message,
            output_format="text",
            code=_EXIT_USAGE_ERROR,
            command="adopt draft",
        )

    project: S0maProject | None = getattr(args, "s0ma_project", None)
    if project is None or project.synthetic:
        return refuse(
            "this is not a s0ma project yet, so there is nowhere to put a "
            "draft. Run `s0ma adopt init` here first: it writes the "
            "[tool.s0ma] table that says where your code lives, and touches "
            "no application file."
        )
    try:
        root = project.root.resolve()
    except OSError:  # pragma: no cover - resolve only fails on a broken tree
        root = project.root

    requested = str(getattr(args, "module", "") or "")
    layer, layer_refusal = _requested_layer(getattr(args, "layer", None))
    if layer_refusal is not None:
        return refuse(layer_refusal)

    source_roots = _project_source_roots(project)
    if not source_roots:
        return refuse(
            "this project declares no source roots, so there is nowhere a "
            "draft belongs. Add the directory your code lives in to "
            "[tool.s0ma].source_roots in pyproject.toml, then run this again."
        )

    # Unscoped on purpose: this command resolves ONE named file, and it
    # has to be able to see a file outside the source roots in order to
    # say something useful about it rather than "no such module".
    report = build_scan_report(root, scoped=False)
    sources = tuple(census.source for census in report.modules)
    source, resolve_refusal = _resolve_draft_target(root, requested, sources)
    if source is None:
        return refuse(resolve_refusal or "")

    destination, out_refusal = _draft_destination(
        root, source, source_roots, getattr(args, "out", None)
    )
    if destination is None:
        return refuse(out_refusal or "")

    shown = _relative_posix(destination, root)
    force = bool(getattr(args, "force", False))
    dry_run = bool(getattr(args, "dry_run", False))
    converted = _converted_sources(source_roots)
    if not force and not dry_run:
        clash = _clash_refusal(destination, shown, source, converted, root)
        if clash is not None:
            return refuse(clash)

    if layer is None:
        layer, candidates = _proposed_layer(report, source.module)
    else:
        candidates = ()

    first_party = frozenset(one.module for one in sources)
    converted_stems = {path.stem for path in converted}
    s0ma_modules = frozenset(
        one.module for one in sources if Path(one.path).stem in converted_stems
    )
    try:
        draft = harvest_module(
            root,
            source,
            layer=layer,
            s0ma_modules=s0ma_modules,
            first_party=first_party,
        )
    except HarvestError as unreadable:
        where = (
            source.path if unreadable.line is None
            else f"{source.path} line {unreadable.line}"
        )
        return refuse(
            f"{where} cannot be drafted: {unreadable.message} Put that right "
            f"and run this again."
        )

    text = emit_draft(draft, layer_candidates=candidates)
    if dry_run:
        print(text, end="")
        return _EXIT_SUCCESS

    try:
        _write_draft(destination, text)
    except OSError as exc:
        return refuse(
            f"the draft could not be written to {shown} ({exc}). Check that "
            f"you can write to that directory, then run this again."
        )

    print(
        _render_draft_text(
            written=shown,
            source_path=source.path,
            module=source.module,
            placeholders=text.count(DRAFT_INTENT_MARKER),
            unplaced_lines=sum(
                block.end_line - block.start_line + 1 for block in draft.unplaced
            ),
            has_baseline=_has_baseline(root, source.module),
        ),
        end="",
    )
    return _EXIT_SUCCESS


def cmd_adopt_baseline(args: argparse.Namespace) -> int:
    """Handler for ``s0ma adopt baseline (MODULE_OR_FILE... | --all)``.

    Records what a module's Python offers its callers today — every
    public name, how each one is called, what it says about itself —
    into one committed file at the project root,
    ``adopt-baseline.s0ma.json``. That record is what ``s0ma adopt
    verify-parity`` judges the conversion against, and it is the one
    thing in the whole ladder that cannot be recovered: once the
    original ``.py`` is deleted, nothing else says what it promised. So
    the command's whole job is to be run **before** anything is deleted.

    Each argument is the dotted name ``s0ma adopt scan`` prints or a path
    to the file, resolved exactly the way ``s0ma adopt draft`` resolves
    its own, so the three commands cannot disagree about what a module
    is called. ``--all`` takes every module the scan reports as
    convertible — application code and scripts, never tests, package
    markers or files s0ma generated.

    The Python file is read and parsed, never imported and never run
    (rule R-1), and never modified. Capturing a module whose reading has
    not changed rewrites the same bytes, so a re-run diffs empty.

    Refusals, all exit 2 with nothing written: no ``[tool.s0ma]``
    project; nothing named and no ``--all``; both at once; a name
    nothing matches; a module whose Python file is already gone (which
    is the one mistake this command exists to prevent).
    """
    from s0ma_dsl.adopt.parity import (
        BaselineRecordError,
        baseline_record_path,
        capture_baseline,
        load_baselines,
        save_baselines,
    )
    from s0ma_dsl.adopt.report import build_scan_report

    def refuse(message: str) -> int:
        return _fail(
            message,
            output_format="text",
            code=_EXIT_USAGE_ERROR,
            command="adopt baseline",
        )

    project: S0maProject | None = getattr(args, "s0ma_project", None)
    if project is None or project.synthetic:
        return refuse(
            "this is not a s0ma project yet, so there is nowhere to keep a "
            "baseline. Run `s0ma adopt init` here first: it writes the "
            "[tool.s0ma] table that says where your code lives, and touches no "
            "application file."
        )
    try:
        root = project.root.resolve()
    except OSError:  # pragma: no cover - resolve only fails on a broken tree
        root = project.root

    requested = tuple(getattr(args, "modules", None) or ())
    take_all = bool(getattr(args, "all_modules", False))
    selection_refusal = _selection_refusal(
        requested,
        take_all=take_all,
        command="baseline",
        example="s0ma adopt baseline bookshelf.errors",
    )
    if selection_refusal is not None:
        return refuse(selection_refusal)

    try:
        records = load_baselines(root)
    except BaselineRecordError as unreadable:
        return refuse(str(unreadable))

    # Unscoped on purpose: this command resolves ONE named file, and it
    # has to be able to see a file outside the source roots in order to
    # say something useful about it rather than "no such module".
    report = build_scan_report(root, scoped=False)
    sources = tuple(census.source for census in report.modules)

    # Each target is (dotted module, project-relative Python file). Both
    # come from discovery when the file is there; when it is not but a
    # record is, the record's own ``source_path`` is used, so the store
    # raises the sentence written for that moment rather than this
    # command guessing at one.
    targets: list[tuple[str, str]] = []
    if take_all:
        targets = sorted(
            (source.module, source.path)
            for source in sources
            if source.role in _DRAFTABLE_ROLES
        )
        if not targets:
            return refuse(
                "there is no application code here to take a baseline of. Run "
                "`s0ma adopt scan` to see what this project reads as source; if "
                "your code lives somewhere it is not looking, name that directory "
                "in [tool.s0ma].source_roots."
            )
    else:
        seen: set[str] = set()
        for name in requested:
            source, resolve_refusal = _resolve_draft_target(
                root, name, sources, verb="record", past="recorded"
            )
            if source is not None:
                target = (source.module, source.path)
            else:
                recorded = records.get(name)
                if recorded is None:
                    return refuse(
                        _missing_baseline_target(root, name, project)
                        or resolve_refusal
                        or ""
                    )
                target = (name, recorded.source_path)
            if target[0] in seen:
                continue
            seen.add(target[0])
            targets.append(target)

    captured: list[tuple[str, str]] = []
    replaced: list[str] = []
    for module, path in targets:
        try:
            entry = capture_baseline(root, module, path)
        except BaselineRecordError as unreadable:
            return refuse(str(unreadable))
        previous = records.get(module)
        if previous is not None and previous.source_hash != entry.source_hash:
            replaced.append(module)
        records[module] = entry
        captured.append((module, path))

    try:
        save_baselines(root, records)
    except BaselineRecordError as unwritable:
        return refuse(str(unwritable))

    print(
        _render_baseline_text(
            captured=sorted(captured),
            replaced=sorted(replaced),
            record=_relative_posix(baseline_record_path(root), root),
            converted={path.stem for path in _converted_sources(_project_source_roots(project))},
        ),
        end="",
    )
    return _EXIT_SUCCESS


def cmd_adopt_verify_parity(args: argparse.Namespace) -> int:
    """Handler for ``s0ma adopt verify-parity (MODULE... | --all) [--format text|json]``.

    Reads the module the build emitted, compares its public surface with
    the baseline captured from the Python it replaced, and names every
    difference: a name that is gone or new, a signature, a declared
    type, a docstring, a base class, a decorator or a constant's value
    that moved. It knows what the build adds around an authored body —
    registration, the generated header, the import block, the order of
    ``__all__`` — and ignores that, and only that.

    Exit 0 when every module compared has the surface it had, 1 when
    anything differs, 2 when the comparison could not be made at all.
    ``--format json`` prints the same verdict as an
    ``s0ma-adopt-parity@1`` document for an agent to read.

    **It writes nothing anywhere** (rule R-2) and the built module is
    parsed, never imported (rule R-1) — which matters more here than
    anywhere else on the ladder, because importing a module to check it
    would run the code the check is supposed to be judging.

    Refusals, all exit 2: no ``[tool.s0ma]`` project; nothing named and
    no ``--all``; both at once; nothing built yet; a module with no
    baseline — and if its Python file has been deleted already, the
    plain news that the comparison can no longer be made, with the ways
    out; a module the build does not contain.
    """
    from s0ma.bootstrap import ManifestSchemaError

    from s0ma_dsl.adopt.model import dump_json
    from s0ma_dsl.adopt.parity import (
        BaselineRecordError,
        compare_surfaces,
        load_baselines,
        parity_document,
        render_parity_text,
    )
    from s0ma_dsl.adopt.status import before_you_delete
    from s0ma_dsl.adopt.surface import SurfaceReadError, static_surface
    from s0ma_dsl.codegen.build_manifest import load_manifest

    output_format: str = getattr(args, "output_format", "text")

    def refuse(message: str) -> int:
        return _fail(
            message,
            output_format=output_format,
            code=_EXIT_USAGE_ERROR,
            command="adopt verify-parity",
        )

    project: S0maProject | None = getattr(args, "s0ma_project", None)
    if project is None or project.synthetic:
        return refuse(
            "this is not a s0ma project yet, so there is nothing built to "
            "compare and nowhere a baseline could be. Run `s0ma adopt init` "
            "here first."
        )
    try:
        root = project.root.resolve()
    except OSError:  # pragma: no cover - resolve only fails on a broken tree
        root = project.root

    requested = tuple(getattr(args, "modules", None) or ())
    take_all = bool(getattr(args, "all_modules", False))
    selection_refusal = _selection_refusal(
        requested,
        take_all=take_all,
        command="verify-parity",
        example="s0ma adopt verify-parity bookshelf.errors",
    )
    if selection_refusal is not None:
        return refuse(selection_refusal)

    try:
        records = load_baselines(root)
    except BaselineRecordError as unreadable:
        return refuse(str(unreadable))

    try:
        manifest = load_manifest(project.build_dir)
    except ManifestSchemaError:
        # `s0ma build` runs bare now (G3b, friction F-E2-2), so the
        # refusal can print the plain sentence the milestone that wrote
        # it wanted: a command with no argument to work out.
        return refuse(
            "nothing has been built here yet, so there is no converted module "
            "to compare against — parity reads the .py the build writes, not "
            "the .s0ma source it came from. Convert a module and check it, "
            "then run `s0ma build` first."
        )
    built = _built_modules(manifest, project.build_dir, root)

    waiting: tuple[str, ...] = ()
    if take_all:
        if not records:
            return refuse(
                "no baselines have been captured yet, so there is nothing to "
                "compare. `s0ma adopt baseline --all` records what your Python "
                "offers today; take it before you delete anything."
            )
        # --all compares everything that *can* be compared and names what
        # cannot. A project halfway up the ladder has baselines for
        # modules nobody has converted yet, and refusing the whole run
        # because of them would make --all useless for exactly the
        # project it is for.
        targets = tuple(name for name in sorted(records) if name in built)
        waiting = tuple(name for name in sorted(records) if name not in built)
        if not targets:
            return refuse(
                f"none of the {len(waiting)} modules with a baseline has been "
                f"built, so there is nothing to compare yet. Convert one (`s0ma "
                f"adopt draft <module>`), write its placeholders, build, and run "
                f"this again."
            )
    else:
        targets = requested
        for name in targets:
            if name not in records:
                return refuse(_no_baseline_refusal(name, built, records))
            if name not in built:
                return refuse(_not_built_refusal(name, built))

    results = []
    for name in targets:
        entry = records[name]
        emitted = built[name]
        try:
            surface = static_surface(emitted.path, module=name)
        except SurfaceReadError as unreadable:
            return refuse(
                f"{emitted.shown} could not be read, so {name} cannot be "
                f"compared. {unreadable}"
            )
        results.append(
            compare_surfaces(entry.surface, surface, built_path=emitted.shown)
        )

    # The last step of the ladder, for the modules that have reached it:
    # clean, and their Python still on disk. It is composed here rather
    # than inside `parity_document` / `render_parity_text` because the
    # facts are about the project's layout — where the package's
    # __init__.py sits, how far the build directory is above it — and a
    # comparison of two surfaces has no project to read them from.
    finished = tuple(
        result.module
        for result in results
        if result.clean and built[result.module].original is not None
    )
    plan = _alias_for_verdict(root, project, finished, built)

    if output_format == "json":
        document = parity_document(results, waiting=waiting)
        if finished:
            # Additive under `s0ma-adopt-parity@1`, and the same shape
            # `s0ma adopt status` prints, so an agent reads one document
            # family rather than two.
            document["before_you_delete"] = before_you_delete(
                plan, modules=list(finished)
            )
        print(dump_json(document), end="")
    else:
        print(render_parity_text(results, waiting=waiting), end="")
        if finished:
            print(
                _render_before_you_delete(
                    plan, modules=finished, build_dir=_relative_posix(
                        project.build_dir, root
                    )
                ),
                end="",
            )
    return (
        _EXIT_SUCCESS
        if all(result.clean for result in results)
        else _EXIT_VALIDATION_ERROR
    )


def _selection_refusal(
    requested: Sequence[str], *, take_all: bool, command: str, example: str
) -> str | None:
    """Refuse a request that names nothing, or names things twice over.

    The two halves of ``(MODULE... | --all)`` are alternatives, not a
    pair: quietly letting one win would leave somebody who typed both
    believing a different set of modules had been read.
    """
    if requested and take_all:
        return (
            f"both module names and --all were given, and they are two ways of "
            f"saying which modules to work on rather than two things to do. "
            f"Either name the ones you mean (`{example}`) or pass --all on its "
            f"own."
        )
    if not requested and not take_all:
        return (
            f"no module was named. Name the ones you mean, by the dotted name "
            f"`s0ma adopt scan` prints — for example `{example}` — or pass --all "
            f"to take in every module of this project at once."
        )
    return None


def _missing_baseline_target(
    root: Path, name: str, project: S0maProject
) -> str | None:
    """The refusal for a baseline target that discovery cannot find, or ``None``.

    One case is worth saying in its own words, because it is the
    expensive mistake this whole command exists to prevent: the module
    has been converted, the Python file is gone, and no record of what
    it promised was ever taken. An ordinary typo is left to the
    resolver, which already offers the nearest names; a module that
    *does* have a record is handled by the caller, which re-reads the
    file the record names so the store can say its own piece.
    """
    converted = {
        path.stem: path for path in _converted_sources(_project_source_roots(project))
    }
    stem = name.rsplit(".", 1)[-1]
    if stem in converted:
        where = _relative_posix(converted[stem], root)
        return (
            f"{name} has been converted already — {where} is the s0ma module it "
            f"became — and the Python file it came from is not here any more, so "
            f"there is nothing left to read a baseline from. A baseline records "
            f"what the original Python promised, which is why it is taken before "
            f"the file is deleted. Bring that file back from version control and "
            f"run this again if you want the comparison; otherwise the project's "
            f"own tests are what tells you the conversion held."
        )
    return None


@dataclass(frozen=True, slots=True)
class _BuiltModule:
    """One module the build emitted, as ``verify-parity`` needs it.

    * ``path`` — the emitted ``.py`` on disk, to parse.
    * ``shown`` — that path project-relative and forward-slashed, for
      anything printed (NFR-7).
    * ``original`` — where the Python this module replaced would sit, if
      it is still there: project-relative, or ``None`` when it is gone.
      The manifest is what knows this, so nothing has to guess.
    """

    path: Path
    shown: str
    original: str | None


def _built_modules(
    manifest: object, build_dir: Path, root: Path
) -> dict[str, _BuiltModule]:
    """Dotted module name → what the build emitted for it.

    s0ma module names are flat — a module drafted from
    ``src/bookshelf/errors.py`` declares ``module errors`` — while a
    baseline is filed under the dotted name the Python had. The manifest
    is what joins them: ``logical_path`` records where the ``.s0ma``
    source sits inside its source root, which is the Python module's own
    path with another suffix. Older manifests, and builds with no
    project to be relative to, record neither; those fall back to the
    flat name, so a single-package project still resolves.
    """
    from s0ma_dsl.adopt.discovery import package_prefix

    found: dict[str, _BuiltModule] = {}
    for entry in getattr(manifest, "modules", ()):
        path = build_dir / entry.output
        shown = _relative_posix(path, root)
        logical = str(getattr(entry, "logical_path", "") or "")
        source_root = str(getattr(entry, "source_root", "") or "")
        original: str | None = None
        if logical:
            candidate = Path(source_root) / logical if source_root else Path(logical)
            python = root / candidate.with_suffix(".py")
            original = _relative_posix(python, root) if python.is_file() else None
            # A source root that is itself a package contributes its own
            # name, exactly as `adopt scan` and `adopt status` read it
            # (friction F-G3a-1): with `metrics` as a source root the
            # Python was `metrics.counters`, so that is what its baseline
            # is filed under and what this has to answer to. Without
            # this, rung 3 stopped at verify-parity on every repository
            # whose packages sit at the top — the pilot's own shape.
            prefix = package_prefix(root / source_root) if source_root else ""
            found.setdefault(
                prefix + logical.removesuffix(".s0ma").replace("/", "."),
                _BuiltModule(path=path, shown=shown, original=original),
            )
        found.setdefault(
            entry.name, _BuiltModule(path=path, shown=shown, original=original)
        )
    return found


def _alias_for_verdict(
    root: Path,
    project: S0maProject,
    finished: Sequence[str],
    built: Mapping[str, _BuiltModule],
) -> AliasPlan | None:
    """The alias lines to print, or ``None`` when there is no one answer.

    The block is per package, so it is offered only when exactly one
    module was compared: a run over five modules in three packages would
    need five blocks, and five blocks is a page rather than a verdict.
    The other two facts hold whatever the count, and are said either way.
    """
    from s0ma_dsl.adopt.status import alias_plan

    if len(finished) != 1:
        return None
    name = finished[0]
    emitted = built[name]
    if emitted.original is None:  # pragma: no cover - `finished` filtered on it
        return None
    return alias_plan(
        root,
        module=name,
        python_path=emitted.original,
        build_dir=_relative_posix(project.build_dir, root),
        built_module=emitted.path.stem,
    )


def _render_before_you_delete(
    plan: AliasPlan | None, *, modules: Sequence[str], build_dir: str
) -> str:
    """The three things a conversion is not finished without, as a block.

    Printed under a clean verdict, where the person is standing at the
    one step of the ladder no command takes for them. It is short on
    purpose — one numbered line each, and the alias lines themselves only
    when there is a single module to write them for — and it teaches the
    order that makes the step safe: bind the name first, run the tests
    with the original still there, delete last.

    Nothing here is a citation. The lines are this project's lines
    (:func:`~s0ma_dsl.adopt.status.alias_plan`), which matters because
    the one value a reader cannot work out is how far the package sits
    below the project root.
    """
    from s0ma_dsl.adopt.status import ALIAS_PLACEMENT, RUNTIME_DISTRIBUTIONS

    runtime = " and ".join(RUNTIME_DISTRIBUTIONS)
    lines = [""]
    if plan is not None:
        lines.append(f"Before you delete {plan.python_path}:")
        if plan.lines:
            lines.extend(
                _wrap_numbered(
                    f"1. Point {plan.module} at the built module: put these lines "
                    f"in {plan.package_init}, {ALIAS_PLACEMENT}. "
                    f"The build directory is flat, so without them every "
                    f"`from .{plan.attribute} import ...` in the package stops "
                    f"resolving the moment the file goes."
                )
            )
            lines.append("")
            lines.extend(f"      {line}" if line else "" for line in plan.lines)
            lines.append("")
        else:
            lines.extend(
                _wrap_numbered(
                    f"1. Nothing to alias: {plan.module} is not inside a package, "
                    f"so nothing imports it by a dotted name. Whatever imports it "
                    f"has to find {plan.build_dir} instead."
                )
            )
    else:
        joined = ", ".join(modules)
        lines.append(f"Before you delete the Python of {joined}:")
        lines.extend(
            _wrap_numbered(
                "1. Point each old name at its built module, in the package's own "
                "__init__.py. `s0ma adopt verify-parity <module>` prints the exact "
                "lines for one module — the build directory is flat, so without "
                "them the package stops importing itself."
            )
        )
    lines.extend(
        _wrap_numbered(
            f"2. Declare the s0ma runtime: the built module imports {runtime} "
            f"when it loads, so name both in [project].dependencies and install "
            f"them in the environment that runs this application."
        )
    )
    lines.extend(
        _wrap_numbered(
            f"3. Ship {build_dir} with the application. It is imported at run "
            f"time now, so it has to stay importable and be listed among the "
            f"packages your wheel installs."
        )
    )
    lines.append("")
    lines.extend(
        _wrap(
            "Then run this project's tests with the Python file still there and "
            "check which file the module came from; delete it only once the "
            "built one is what gets imported."
        )
    )
    return "\n".join(lines) + "\n"


def _wrap_numbered(text: str) -> list[str]:
    """One numbered item, folded so its continuations line up under its words."""
    return textwrap.wrap(
        text,
        width=_WRAP,
        initial_indent="  ",
        subsequent_indent="     ",
        break_long_words=False,
        break_on_hyphens=False,
    ) or [f"  {text}"]


def _offered_module_names(built: Mapping[str, _BuiltModule]) -> tuple[str, ...]:
    """The built names worth saying back to somebody, sorted.

    Every module is filed twice — under the dotted name its Python had
    and under the flat name the ``.s0ma`` source declares — because
    either is a reasonable thing to type. Offering both back would read
    as two modules where there is one, so the flat spelling is dropped
    wherever a dotted one reaches the same file.
    """
    dotted = {module.path for name, module in built.items() if "." in name}
    return tuple(
        sorted(
            name
            for name, module in built.items()
            if "." in name or module.path not in dotted
        )
    )


def _no_baseline_refusal(
    name: str, built: Mapping[str, _BuiltModule], records: Mapping[str, object]
) -> str:
    """Why a module cannot be compared when nothing was recorded for it."""
    if name in built:
        original = built[name].original
        if original is None:
            return (
                f"there is no baseline for {name}, and there is no Python file "
                f"left to take one from: the module has been converted and the "
                f"original is gone. That comparison cannot be made any more — a "
                f"baseline has to be captured before the file is deleted. Either "
                f"restore the file from version control, take the baseline there "
                f"and run this again, or accept the conversion on the strength of "
                f"the project's own tests, which are the check parity was only "
                f"ever standing in for."
            )
        return (
            f"there is no baseline for {name}, so there is nothing to compare "
            f"the built module with. {original} is still there, so run `s0ma "
            f"adopt baseline {name}` and then this again. The record will "
            f"describe that file as it stands, which is what you want as long "
            f"as you have not edited it since the conversion began."
        )
    known = sorted(records)
    offered = (
        f" Baselines have been captured for {_join_words(tuple(known[:_SUGGESTION_LIMIT]))}."
        if known
        else ""
    )
    return (
        f"there is no baseline for {name}, and nothing of that name has been "
        f"built either.{offered} Run `s0ma adopt baseline {name}` while its "
        f"Python file is still there, convert it, build, and then compare."
    )


def _not_built_refusal(name: str, built: Mapping[str, _BuiltModule]) -> str:
    """Why a module with a baseline still cannot be compared."""
    known = _offered_module_names(built)
    offered = (
        f" The build holds {_join_words(known[:_SUGGESTION_LIMIT])}."
        if known
        else ""
    )
    return (
        f"{name} has a baseline but the build does not contain it, so there is "
        f"nothing to compare the record against.{offered} Draft the module (`s0ma "
        f"adopt draft {name}`), write its placeholders, then build and run this "
        f"again."
    )


def _render_baseline_text(
    *,
    captured: Sequence[tuple[str, str]],
    replaced: Sequence[str],
    record: str,
    converted: set[str],
) -> str:
    """What was recorded, where it went, and why it has to be committed."""
    count = len(captured)
    heading = f"Captured {count} {_plural(count, 'baseline', 'baselines')}:"
    width = max(len(module) for module, _ in captured)
    lines = [heading]
    lines.extend(f"  {module:<{width}}   {path}" for module, path in captured)
    lines.append("")
    if replaced:
        lines.extend(
            _wrap(
                f"{_join_words(tuple(replaced))} had a baseline already and the "
                f"Python has changed since it was taken, so the old record has "
                f"been replaced by what the file says today."
            )
        )
        lines.append("")
    lines.extend(
        _wrap(
            f"Recorded in {record}. Commit it with your code: it is what the "
            f"conversion will be judged against, and it cannot be taken again "
            f"once the Python file is gone."
        )
    )
    lines.append("")
    pending = [module for module, _ in captured if module.rsplit(".", 1)[-1] not in converted]
    if len(pending) == 1:
        lines.append("Run this next:")
        lines.append(f"  s0ma adopt draft {pending[0]}   turn it into a .s0ma draft")
    else:
        lines.extend(
            _wrap(
                "Convert one module at a time from here, leaves first: `s0ma adopt "
                "draft <module>`, write its placeholders, `s0ma check`, `s0ma "
                "build`, then `s0ma adopt verify-parity <module>`."
            )
        )
    return "\n".join(lines) + "\n"


def _requested_layer(given: object) -> tuple[str | None, str | None]:
    """Validate ``--layer`` against the language's own layer names.

    Returns the layer to use and no refusal, or no layer and the sentence
    that says why. The vocabulary is read off
    :class:`~s0ma_dsl.ast_nodes.enums.Layer` rather than restated here,
    so a language that grows a layer grows this command's answer with it.
    Case is not held against anybody: ``--layer domain`` means ``DOMAIN``.
    """
    from s0ma_dsl.ast_nodes.enums import Layer

    if given is None:
        return None, None
    wanted = str(given).strip().upper()
    known = tuple(layer.value for layer in Layer)
    if wanted in known:
        return wanted, None
    return None, (
        f"{given} is not one of this language's layers. A module sits at "
        f"exactly one of {_join_words(known)} — pass one of those to "
        f"--layer, or leave --layer off and the draft will ask you to choose "
        f"once you can see what is in the module."
    )


def _project_source_roots(project: S0maProject) -> tuple[Path, ...]:
    """The project's configured source roots, as absolute directories."""
    return tuple(
        root if root.is_absolute() else (project.root / root)
        for root in project.source_roots
    )


def _resolve_draft_target(
    root: Path,
    requested: str,
    sources: Sequence[SourceFile],
    *,
    verb: str = "draft",
    past: str = "drafted",
) -> tuple[SourceFile | None, str | None]:
    """Turn what somebody typed into one discovered file, or refuse.

    The candidates are exactly what ``s0ma adopt scan`` read, so the
    commands that use this cannot disagree about which files exist or
    what they are called. A path and a dotted name reach the same
    answer; anything that reaches no answer, or more than one, is a
    refusal that says what to type instead. *verb* and *past* are the
    words the caller's own refusals use, so ``adopt baseline`` says
    "record" where ``adopt draft`` says "draft".
    """
    if not requested:
        return None, (
            "no module was named. Pass the dotted name `s0ma adopt scan` "
            "printed (for example `bookshelf.errors`) or the path to the "
            "file (`src/bookshelf/errors.py`)."
        )
    if _looks_like_a_path(requested, root):
        source, refusal = _source_from_path(root, requested, sources)
    else:
        source, refusal = _source_from_module(requested, sources)
    if source is None:
        return None, refusal
    return _draftable(source, verb=verb, past=past)


def _looks_like_a_path(requested: str, root: Path) -> bool:
    """Whether to read *requested* as a path rather than a dotted name."""
    if requested.endswith(".py") or "/" in requested or "\\" in requested:
        return True
    candidate = Path(requested)
    if candidate.is_absolute():
        return True
    return any((base / candidate).exists() for base in _path_bases(root))


def _path_bases(root: Path) -> tuple[Path, ...]:
    """What a relative path is read from, in order of preference.

    The directory somebody is standing in comes first — but only when
    they are standing inside the project, which is where this command is
    meant to be run. Otherwise the project root is the only base, so a
    relative name that happens to match a file in some unrelated working
    directory is not quietly picked up from there and then refused for
    being outside the project.
    """
    cwd = Path.cwd()
    if cwd == root or root in cwd.parents:
        return (cwd, root)
    return (root,)


def _source_from_path(
    root: Path, requested: str, sources: Sequence[SourceFile]
) -> tuple[SourceFile | None, str | None]:
    """One discovered file named by its path, or the reason there is none."""
    from s0ma_dsl.adopt.discovery import is_transpiled_artifact

    candidate = Path(requested)
    if not candidate.is_absolute():
        tried = tuple(base / candidate for base in _path_bases(root))
        candidate = next((one for one in tried if one.exists()), tried[0])
    try:
        resolved = candidate.resolve()
    except OSError:  # pragma: no cover - resolve only fails on a broken tree
        resolved = candidate
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return None, (
            f"{Path(requested).as_posix()} is outside this project, and a "
            f"draft is written into the project it came from. Copy the file "
            f"into this tree first, or run this command from the project the "
            f"file belongs to."
        )

    wanted = relative.as_posix()
    for source in sources:
        if source.path == wanted:
            return source, None

    if not resolved.exists():
        return None, (
            f"there is no file at {wanted}. Run `s0ma adopt scan` to see the "
            f"files this project has and the order to convert them in, then "
            f"pass one of the paths or dotted names it prints."
        )
    if resolved.suffix != ".py":
        return None, (
            f"{wanted} is not a Python file, and a draft is made from Python. "
            f"Pass a .py file, or the dotted module name `s0ma adopt scan` "
            f"prints for it."
        )
    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    if text and is_transpiled_artifact(text):
        return None, (
            f"{wanted} was generated by s0ma from a .s0ma source, so it has "
            f"been converted already. Edit that .s0ma source instead; "
            f"everything under the build directory is written from your "
            f"sources and overwritten on every build."
        )
    return None, (
        f"{wanted} sits in a directory this project does not read as source: "
        f"a packaging or virtual-environment directory, something hidden, or "
        f"the build directory, whose contents are written from your sources "
        f"and overwritten on every build. Run `s0ma adopt scan` to see the "
        f"files it does read, and draft one of those."
    )


def _source_from_module(
    requested: str, sources: Sequence[SourceFile]
) -> tuple[SourceFile | None, str | None]:
    """One discovered file named by its dotted module, or the reason there is none."""
    matched = [source for source in sources if source.module == requested]
    if len(matched) == 1:
        return matched[0], None
    if len(matched) > 1:
        paths = sorted(source.path for source in matched)
        return None, (
            f"more than one file in this project is called {requested} "
            f"({_join_words(tuple(paths))}), so the name does not say which "
            f"one you mean. Pass the path of the one you want instead."
        )
    return None, (
        f"no module called {requested} was found in this project."
        f"{_suggestion_sentence(requested, sources)} Run `s0ma adopt scan` to "
        f"see every module it found and the order to convert them in."
    )


def _suggestion_sentence(requested: str, sources: Sequence[SourceFile]) -> str:
    """The "did you mean" for a name nothing matched, or nothing at all.

    Suffix matches first — somebody who typed ``errors`` for
    ``bookshelf.errors`` gets the answer rather than a guess — then the
    closest spellings. Both are computed over a sorted list, so the same
    typo always draws the same offer on every machine.
    """
    names = sorted({source.module for source in sources})
    suffix = f".{requested}"
    offered = [name for name in names if name.endswith(suffix)]
    for name in get_close_matches(requested, names, n=_SUGGESTION_LIMIT, cutoff=0.6):
        if name not in offered:
            offered.append(name)
    if not offered:
        return ""
    return f" Did you mean {_join_words(tuple(offered[:_SUGGESTION_LIMIT]))}?"


def _draftable(
    source: SourceFile, *, verb: str = "draft", past: str = "drafted"
) -> tuple[SourceFile | None, str | None]:
    """Refuse the two roles a draft is never taken from, by name.

    Shared with ``adopt baseline``, which takes the same files for the
    same reasons and needs the sentence to end in its own verb —
    "record it" rather than "draft it" — since a refusal that names the
    wrong action is a refusal somebody has to translate.
    """
    if source.role == "test":
        return None, (
            f"{source.path} is a test, and tests stay as they are through a "
            f"retrofit. A converted module keeps the tests it already has — "
            f"name them in the module's `covered_by:` field. {verb.capitalize()} "
            f"the module under test instead."
        )
    if source.role == "package_marker":
        return None, (
            f"{source.path} only marks a package: it holds a docstring, "
            f"imports and __all__ and no code of its own, so there is nothing "
            f"to {verb}. `s0ma adopt init` already listed it under "
            f"[tool.s0ma].package_markers, which is how it stays out of the "
            f"backlog. An __init__.py that does carry real code is {past} "
            f"like any other module."
        )
    if source.role not in _DRAFTABLE_ROLES:  # pragma: no cover - roles are closed
        return None, (
            f"{source.path} is not application code this command can {verb}. "
            f"Run `s0ma adopt scan` to see what it can."
        )
    return source, None


def _draft_destination(
    root: Path,
    source: SourceFile,
    source_roots: Sequence[Path],
    out: object,
) -> tuple[Path | None, str | None]:
    """Where this draft goes: beside the module, or under ``--out``.

    The draft lands in the module's **own** source root, mirroring the
    Python module's path inside that root, with the ``.s0ma`` suffix —
    which for every ordinary project is the file next door to the Python
    it came from, and which is where the converted module will live.

    With one source root there is nothing to choose and this is the
    retrofit plan's §5.5 convention exactly. With several there is: the
    pilot's ``adopt draft telemetry.mining`` wrote ``analysis/mining.s0ma``
    — the first root in alphabetical order — and nothing said the draft
    had left its package (defect G2-3, and F-G3a-4 where the same module
    then arrived under two names and was counted twice). A file found
    outside every configured root (a script at the project root, which
    ``adopt draft`` deliberately supports) has no own root to go back to,
    so it keeps the first configured one.
    """
    stem = Path(source.path).stem
    if out is not None:
        given = Path(str(out))
        # A relative --out is read the same way a relative module path
        # is (:func:`_path_bases`), so the two arguments of one command
        # cannot mean different things by the same spelling. The
        # directory need not exist yet; only where it would land matters.
        tried = (
            (given,)
            if given.is_absolute()
            else tuple(base / given for base in _path_bases(root))
        )
        for candidate in tried:
            try:
                resolved = candidate.resolve()
            except OSError:  # pragma: no cover - resolve fails on a broken tree
                resolved = candidate
            if resolved == root or root in resolved.parents:
                return resolved / f"{stem}.s0ma", None
        return None, (
            f"--out {given.as_posix()} is outside this project, and a draft "
            f"belongs to the project it came from. Name a directory inside "
            f"this tree."
        )

    inside = Path(source.path)
    if source.source_root != ".":
        inside = Path(source.path[len(source.source_root) + 1 :])
    own = _own_source_root(root, source, source_roots)
    return own / inside.with_suffix(".s0ma"), None


def _own_source_root(
    root: Path, source: SourceFile, source_roots: Sequence[Path]
) -> Path:
    """The configured source root *source* was found under, else the first.

    The scan attributes every file to a root of its own reading, which is
    the project's configured root whenever the file sits under one. A
    file that sits under none — the project root itself, or a directory
    the perimeter does not name — is attributed to ``"."`` or to a
    directory that is not in the table, and there is no own root to
    honour; the first configured root is then the answer, as it always
    was.
    """
    for candidate in source_roots:
        if _relative_posix(candidate, root) == source.source_root:
            return candidate
    return source_roots[0]


def _converted_sources(source_roots: Sequence[Path]) -> tuple[Path, ...]:
    """Every ``.s0ma`` source the project already holds, sorted."""
    found: list[Path] = []
    for directory in source_roots:
        found.extend(iter_visible_files(directory, "*.s0ma"))
    return tuple(sorted(set(found)))


def _clash_refusal(
    destination: Path,
    shown: str,
    source: SourceFile,
    converted: Sequence[Path],
    root: Path,
) -> str | None:
    """The sentence that stops a draft from writing over work, or ``None``.

    Two different clashes, and they need different answers. A file
    already at the destination is usually a draft somebody is part way
    through authoring, and losing that is losing the only thing a draft
    cannot rebuild. A ``.s0ma`` source of the same name somewhere else
    means this module has been converted already, and re-drafting it
    would produce a second module with the same name — which the language
    refuses in any case, because module names are flat and unique.
    """
    stem = Path(source.path).stem
    if destination.exists():
        return (
            f"{shown} is already there, and a draft would write over it. If "
            f"it is a draft you have been authoring, that work is not "
            f"recoverable from the Python file. Pass --force to replace it "
            f"anyway, or --out to write this draft somewhere else."
        )
    for existing in converted:
        if existing.stem == stem:
            where = _relative_posix(existing, root)
            return (
                f"{source.path} has already been converted: {where} is the "
                f"s0ma module it became. Module names are flat and unique, so "
                f"a second draft of it could not be built alongside the "
                f"first. Edit {where}, or pass --force if you meant to start "
                f"this module's draft again."
            )
    return None


def _proposed_layer(report: ScanReport, module: str) -> tuple[str | None, tuple[str, ...]]:
    """The layer to write, and the candidates to name when there is none.

    The scan's proposal is taken as the answer only when it is
    ``high`` — the one case where the module's own name and what its
    imports do agree. Anything less is a suggestion, so the draft writes
    its fallback layer and asks for a decision, naming what the scan
    thought plausible so the reader has a shortlist rather than the whole
    vocabulary. Nothing here invents an architecture (rung 0's rule).

    One case is deliberately left unnamed: a suggestion that *is* the
    fallback layer. "The draft wrote DOMAIN … and the candidates are
    DOMAIN" tells a reader being asked to choose nothing they cannot see
    on the line above, and it reads like an answer when the draft is
    asking a question. Saying nothing gets them the whole vocabulary
    instead, which is what somebody choosing actually needs.
    """
    from s0ma_dsl.adopt.draft_emit import FALLBACK_LAYER

    for proposal in report.proposals:
        if proposal.module != module:
            continue
        if proposal.layer is None:
            return None, ()
        if proposal.confidence == "high":
            return proposal.layer, ()
        if proposal.layer == FALLBACK_LAYER:
            return None, ()
        return None, (proposal.layer,)
    return None, ()


def _write_draft(destination: Path, text: str) -> None:
    """Write *text* to *destination* atomically, as UTF-8 with LF endings.

    Through a temporary file in the same directory and then
    :func:`os.replace`, so an interrupted run leaves either the old file
    or the new one and never half of either. ``newline="\\n"`` is not
    optional: a draft is compared byte for byte by the baseline it will
    be checked against, and a Windows default would make those bytes
    platform-dependent.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp.{os.getpid()}")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _has_baseline(root: Path, module: str) -> bool:
    """Whether a parity baseline for *module* has been captured already.

    A record that cannot be read counts as no baseline: the closing
    message then says to take one, which is the safe way round — taking a
    baseline twice costs nothing, and deleting a Python file without one
    cannot be undone.
    """
    from s0ma_dsl.adopt.parity import BaselineRecordError, load_baselines

    try:
        return module in load_baselines(root)
    except BaselineRecordError:
        return False


def _render_draft_text(
    *,
    written: str,
    source_path: str,
    module: str,
    placeholders: int,
    unplaced_lines: int,
    has_baseline: bool,
) -> str:
    """What was written, what is left to write, and the next two commands."""
    lines = [f"Wrote {written}", ""]
    lines.extend(_wrap(_debt_sentence(placeholders, unplaced_lines)))
    lines.extend(
        _wrap(
            f"{source_path} has not been touched. It is still the code that "
            f"runs, and it stays that way until you have checked the draft, "
            f"built it and compared it — then you delete it."
        )
    )
    lines.append("")
    commands: list[tuple[str, str]] = []
    if not has_baseline:
        commands.append((
            f"s0ma adopt baseline {module}",
            "record what this module offers today",
        ))
    commands.append(("s0ma check", "read back every line still to write"))
    width = max(len(command) for command, _ in commands)
    heading = "Run these two next:" if len(commands) == 2 else "Run this next:"
    lines.append(heading)
    lines.extend(f"  {command:<{width}}   {gloss}" for command, gloss in commands)
    if not has_baseline:
        lines.append("")
        lines.extend(
            _wrap(
                "Baseline before you delete anything: the baseline is taken "
                "from the Python file, so once that file is gone there is "
                "nothing left to compare the conversion against."
            )
        )
    return "\n".join(lines) + "\n"


def _debt_sentence(placeholders: int, unplaced_lines: int) -> str:
    """How much of this draft is still somebody's to write.

    Both numbers come from what was emitted rather than from a second
    reading of it: the placeholders are the ``FIXME(adopt):`` markers the
    emitter wrote, which is the same count ``s0ma check`` will report,
    and the quarantined lines are the line ranges the harvester recorded
    for the source it could not place.
    """
    parts: list[str] = []
    if placeholders:
        parts.append(
            f"It carries {placeholders} "
            f"{_plural(placeholders, 'placeholder', 'placeholders')} — "
            f"{_plural(placeholders, 'one field', 'that many fields')} whose "
            f"meaning only a person can write, each marked FIXME(adopt): and "
            f"each saying what belongs there."
        )
    else:
        parts.append(
            "Every field it could not derive was already written in your "
            "Python, so it carries no placeholders."
        )
    if unplaced_lines:
        parts.append(
            f"It also holds {unplaced_lines} "
            f"{_plural(unplaced_lines, 'line', 'lines')} of code no "
            f"declaration could take, quarantined as text so that nothing is "
            f"lost and nothing runs by accident."
        )
    if placeholders or unplaced_lines:
        parts.append(
            "`s0ma check` refuses the draft until that work is done, in every "
            "mode — which is what stops a half-finished conversion from "
            "building green."
        )
    return " ".join(parts)


def _relative_posix(path: Path, root: Path) -> str:
    """*path* as a project-relative, forward-slashed string (NFR-7).

    A path that somehow sits outside the project is printed by name
    alone rather than as a machine path: no output of this family ever
    carries one.
    """
    try:
        return path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - refusals keep paths inside the root
        return path.name


def _plural(count: int, singular: str, plural: str) -> str:
    """*singular* when there is one of something, *plural* otherwise."""
    return singular if count == 1 else plural


def _join_words(items: Sequence[str]) -> str:
    """``a``, ``a and b``, ``a, b and c`` — an English list, not a dump."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _wrap(text: str) -> list[str]:
    """One sentence folded to :data:`_WRAP` columns, continuations indented."""
    return textwrap.wrap(
        text,
        width=_WRAP,
        subsequent_indent="  ",
        break_long_words=False,
        break_on_hyphens=False,
    ) or [text]


def _scan_root(args: argparse.Namespace, given: str | None) -> tuple[Path, str]:
    """The directory to scan, and how to name it in a refusal.

    The name is what the person typed, or the words "the current project
    directory" when they typed nothing. A resolved absolute path is never
    printed: house rule NFR-7 keeps machine paths out of output, and a
    refusal that echoes the argument is the one a reader can act on.
    """
    if given:
        root = Path(given)
        if not root.is_absolute():
            root = Path.cwd() / root
        shown = Path(given).as_posix()
    else:
        project: S0maProject | None = getattr(args, "s0ma_project", None)
        if project is not None:
            root = Path(project.root)
        else:
            # `scan` and `init` self-manage project resolution (they are
            # pointed at trees that are not s0ma projects yet), so there
            # is no resolved project to read the root from and
            # `--project-root` has to be honoured here instead.
            given_root = getattr(args, "project_root", None)
            root = Path(given_root) if given_root else Path.cwd()
        shown = "the current project directory"
    try:
        return root.resolve(), shown
    except OSError:
        return root, shown


def _registration_counts(project: S0maProject) -> tuple[int, int]:
    """Return current componentized/roster counts for adoption guidance."""
    componentized = 0
    for root in (*project.source_roots, project.build_dir):
        for path in iter_visible_files(root, "*.py"):
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if _SOURCE_HASH_RE.search(content) and _OUTPUT_HASH_RE.search(content):
                componentized += 1
    try:
        roster = len(load_adopted_files(project.root))
    except AdoptedRecordError:
        roster = 0
    return componentized, roster


def _churn_warnings(
    path: str,
    re_adopt_count: int,
    action: dict[str, object],
) -> list[dict[str, object]]:
    """Render advisory churn telemetry; deliberately never gate evidence."""
    if re_adopt_count < 3:
        return []
    return [{
        "code": "ADOPTED_CHURN",
        "severity": "warning",
        "path": path,
        "re_adopt_count": re_adopt_count,
        "message": (
            f"{path} has been re-adopted {re_adopt_count} times after "
            "initial intake; stop refreshing the roster hash and componentize."
        ),
        "next_action": action,
        "gate_relevant": False,
    }]
