"""Whole-project migration into the explicit semantic-state grammar.

``s0ma migrate grammar`` is dry-run by default.  It parses every authored
source before planning a write, emits a deterministic manifest, and applies
the complete plan with per-file atomic replacement plus whole-plan rollback.

When the target is the root of the project the command resolved, only that
project's source and test roots are read; any other target is read whole.
Whatever git ignores is left out, and a directory that cannot be read is
skipped with a warning on stderr.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma_dsl.errors import S0maError
from s0ma_dsl.parser.s0ma_parser import _RawDeclaration, _split_declarations, parse_s0ma
from s0ma_dsl.semantic_state import semantic_fields, semantic_source_field

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

EXIT_SUCCESS = 0
EXIT_VALIDATION_ERROR = 1
EXIT_USAGE_ERROR = 2

_PRUNE = frozenset({
    ".git", ".hg", ".svn", ".claude", ".venv", "venv", "node_modules",
    "__pycache__", ".s0ma.cache", "__s0ma_cache__", "build", "dist",
})
_HEADER_OR_BODY_FIELDS = frozenset({
    "name", "layer", "source", "target", "body", "prose_body",
    "python_body", "module_location",
})


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class GrammarMigrationChange:
    """One deterministic source rewrite in a migration plan."""

    path: str
    before_sha256: str
    after_sha256: str
    inserted_fields: tuple[str, ...]
    before: bytes
    after: bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "inserted_fields": list(self.inserted_fields),
        }


@dataclass(frozen=True)
class GrammarMigrationPlan:
    """Complete immutable project plan used for dry-run and apply."""

    root: Path
    changes: tuple[GrammarMigrationChange, ...]
    warnings: tuple[str, ...] = ()
    """One line per directory the walk skipped; never part of the manifest."""

    def manifest(self, *, applied: bool) -> dict[str, Any]:
        return {
            "schema": "s0ma-grammar-migration@1",
            "command": "s0ma migrate grammar",
            "applied": applied,
            "change_count": len(self.changes),
            "changes": [change.to_dict() for change in self.changes],
        }


class GrammarMigrationError(ValueError):
    """Named, single-diagnostic failure for grammar migration preflight."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


_WARNING_PREFIX = "warning: s0ma migrate grammar:"


def _relative_label(path: Path, root: Path) -> str:
    """POSIX path of *path* relative to *root*, ``.`` for *root* itself."""

    return path.relative_to(root).as_posix() or "."


def _run_git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str] | None:
    """Run one fixed git command in *root*; ``None`` when it cannot run at all.

    Output is always captured, so nothing git prints reaches the terminal.
    """

    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell, repo-local
            ["git", "-C", str(root), *arguments],  # noqa: S607
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            check=False,
        )
    except (OSError, ValueError):
        return None


def _git_ignored(root: Path) -> tuple[frozenset[str], frozenset[str]]:
    """Return the (directories, files) under *root* that git ignores.

    Both sets hold POSIX paths relative to *root*. They are empty, which
    means nothing is filtered, when git is not on PATH, *root* is not in a
    work tree, an enclosing repository ignores *root* itself, or any git
    command fails.
    """

    nothing: tuple[frozenset[str], frozenset[str]] = (frozenset(), frozenset())
    if shutil.which("git") is None:
        return nothing
    inside = _run_git(root, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
        return nothing
    # Exit 0 means an enclosing repository ignores the root itself; 1 means
    # it does not; anything else is a failure. Only 1 lets filtering proceed.
    root_ignored = _run_git(root, "check-ignore", "-q", ".")
    if root_ignored is None or root_ignored.returncode != 1:
        return nothing
    listed = _run_git(
        root, "ls-files", "--others", "--ignored", "--exclude-standard",
        "--directory", "-z",
    )
    if listed is None or listed.returncode != 0:
        return nothing
    directories: set[str] = set()
    files: set[str] = set()
    for item in listed.stdout.split("\0"):
        if not item:
            continue
        if item.endswith("/"):
            directories.add(item.rstrip("/"))
        else:
            files.add(item)
    return frozenset(directories), frozenset(files)


def _discover_sources(
    root: Path,
    *,
    start_directories: Sequence[Path] | None = None,
) -> tuple[list[Path], list[str]]:
    """Return the ``.s0ma`` files to plan under *root* and one warning per skip.

    *start_directories* are walked in order, each directory once; ``None``
    walks *root* itself. Every start directory must lie inside *root*. A
    directory whose listing, or the classification of whose entries, raises
    ``OSError`` is skipped whole and named in one warning. Directories and
    files git ignores are left out without being read.
    """

    ignored_directories, ignored_files = _git_ignored(root)
    sources: list[Path] = []
    warnings: list[str] = []
    visited: set[Path] = set()

    def ignored_directory(relative: str) -> bool:
        if relative == ".":
            return False
        parts = relative.split("/")
        return any(
            "/".join(parts[:end]) in ignored_directories
            for end in range(1, len(parts) + 1)
        )

    def walk(directory: Path) -> None:
        visited.add(directory)
        # Classify every entry before acting on any, so an unreadable
        # directory contributes nothing rather than a partial listing.
        # ``lstat`` raises on every supported Python, whereas the pathlib
        # query methods may answer ``False`` and hide the error.
        classified: list[tuple[Path, bool]] = []
        try:
            for entry in sorted(directory.iterdir(), key=lambda item: item.name):
                try:
                    mode = entry.lstat().st_mode
                except FileNotFoundError:
                    continue
                if not stat.S_ISLNK(mode):
                    classified.append((entry, stat.S_ISDIR(mode)))
        except OSError as exc:
            warnings.append(
                f"{_WARNING_PREFIX} cannot read directory "
                f"{_relative_label(directory, root)} "
                f"({exc.strerror or exc}); it was skipped, so no .s0ma file "
                "under it is in this plan."
            )
            return
        for entry, is_directory in classified:
            relative = entry.relative_to(root).as_posix()
            if is_directory:
                if (
                    entry.name not in _PRUNE
                    and relative not in ignored_directories
                    and entry not in visited
                ):
                    walk(entry)
            elif entry.name.endswith(".s0ma") and relative not in ignored_files:
                sources.append(entry)

    for start in start_directories if start_directories is not None else (root,):
        if start in visited:
            continue
        if ignored_directory(_relative_label(start, root)):
            continue
        walk(start)
    return sources, warnings


def _start_directories(
    root: Path, configured_roots: Sequence[Path],
) -> tuple[list[Path] | None, list[str]]:
    """Pick the configured roots to walk; ``None`` means walk all of *root*.

    Keeps declared order and drops duplicates. A root outside *root* is not
    walked and gets one warning. When no configured root is a directory on
    disk the whole of *root* is walked instead.
    """

    starts: list[Path] = []
    warnings: list[str] = []
    any_directory = False
    for configured in configured_roots:
        candidate = configured.resolve()
        # ``stat`` rather than ``is_dir`` so a root that exists but cannot be
        # inspected is told apart from one that is missing.
        try:
            is_directory = stat.S_ISDIR(candidate.stat().st_mode)
        except (FileNotFoundError, NotADirectoryError):
            is_directory = False
        except OSError:
            # Present but not inspectable: walking it records the warning.
            is_directory = True
        if not is_directory:
            continue
        any_directory = True
        if not candidate.is_relative_to(root):
            warnings.append(
                f"{_WARNING_PREFIX} configured root {candidate.as_posix()} "
                f"is outside {root.as_posix()}; it was not walked."
            )
            continue
        if candidate not in starts:
            starts.append(candidate)
    if not any_directory:
        return None, warnings
    return starts, warnings


def _missing_explicit_fields(raw: _RawDeclaration) -> tuple[str, ...]:
    """Return legacy omissions the M3A reader currently projects to ``none``."""

    missing: list[str] = []
    for field, classification in semantic_fields(raw.decl_type).items():
        if field in _HEADER_OR_BODY_FIELDS:
            continue
        if classification.field_class != "semantic-required-state":
            continue
        if not classification.allow_none:
            continue
        source_field = semantic_source_field(raw.decl_type, field)
        if field == "depends_on":
            authored = source_field in raw.fields or bool(raw.depends_on_lines)
        else:
            authored = source_field in raw.fields
        if not authored:
            missing.append(field)
    return tuple(missing)


def _rewrite_source(source: str, filename: str) -> tuple[str, tuple[str, ...]]:
    """Materialise legacy semantic omissions as explicit ``field: none`` lines."""

    raw_decls = _split_declarations(source, filename)
    lines = source.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in source else "\n"
    insertions: list[tuple[int, tuple[str, ...]]] = []
    field_inventory: list[str] = []

    for index, raw in enumerate(raw_decls):
        missing = _missing_explicit_fields(raw)
        if not missing:
            continue
        next_start = (
            raw_decls[index + 1].start_line - 1
            if index + 1 < len(raw_decls) else len(lines)
        )
        insert_at = next_start
        for line_index in range(raw.start_line, next_start):
            if lines[line_index].strip() == "---":
                insert_at = line_index
                break
        rendered = tuple(
            f"    {semantic_source_field(raw.decl_type, field)}: none{newline}"
            for field in missing
        )
        insertions.append((insert_at, rendered))
        field_inventory.extend(
            f"{raw.decl_type}:{raw.header_names[0]}.{field}" for field in missing
        )

    for insert_at, rendered in reversed(insertions):
        lines[insert_at:insert_at] = rendered
    return "".join(lines), tuple(field_inventory)


def current_grammar_source(source: str, filename: str = "<generated>") -> str:
    """Materialise explicit required semantic states in generated source.

    Scaffolds are authored as compact templates but must never emit legacy
    omission syntax after the M3B requiredness flip. Keeping this pure helper
    beside the migrator gives file migration and new-source generation one
    deterministic rewrite contract.
    """

    rewritten, _inserted = _rewrite_source(source, filename)
    return rewritten


def _parse_in_place(
    source: str,
    path: Path,
    relative: str,
    *,
    _allow_legacy_semantic_omissions: bool = False,
) -> None:
    """Parse *source* as the file at *path*, reporting it as *relative*.

    The parser resolves a relative ``@file(...)`` against the directory of
    the filename it is given, so it gets the absolute path: the embed is
    then found whatever the working directory. A diagnostic still names
    the file by its path relative to the migration root, as the plan does.
    """

    try:
        parse_s0ma(
            source,
            filename=str(path),
            _allow_legacy_semantic_omissions=_allow_legacy_semantic_omissions,
        )
    except S0maError as exc:
        if exc.file != str(path):
            raise
        raise dataclasses.replace(exc, file=relative) from exc


def plan_grammar_migration(
    root: Path,
    *,
    configured_roots: Sequence[Path] | None = None,
) -> GrammarMigrationPlan:
    """Parse the whole project, then return a deterministic immutable plan.

    With *configured_roots* (a project's source roots, then its test roots)
    only those that are directories inside *root* are walked; when none is
    a directory on disk, or without them, all of *root* is walked. Paths in
    the plan stay relative to *root* either way.
    """

    resolved = root.resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    starts: list[Path] | None = None
    warnings: list[str] = []
    if configured_roots is not None:
        starts, warnings = _start_directories(resolved, configured_roots)
    sources, walk_warnings = _discover_sources(resolved, start_directories=starts)
    warnings.extend(walk_warnings)
    changes: list[GrammarMigrationChange] = []
    for path in sources:
        relative = path.relative_to(resolved).as_posix()
        try:
            before = path.read_bytes()
            source = before.decode("utf-8")
            # Whole-project preflight: any failure aborts before a plan can apply.
            _parse_in_place(
                source, path, relative, _allow_legacy_semantic_omissions=True,
            )
        except (OSError, UnicodeDecodeError, S0maError) as exc:
            raise GrammarMigrationError(
                "GRAMMAR_MIGRATION_PARSE_ERROR",
                f"{relative}: {exc}; nothing was "
                "changed. Fix this source, then rerun `s0ma migrate grammar`."
            ) from exc
        after_text, inserted = _rewrite_source(source, relative)
        after = after_text.encode("utf-8")
        if after == before:
            continue
        # Prove the proposed new grammar parses before it can reach the plan.
        try:
            _parse_in_place(after_text, path, relative)
        except S0maError as exc:  # pragma: no cover - defensive invariant
            raise GrammarMigrationError(
                "GRAMMAR_MIGRATION_OUTPUT_INVALID",
                f"{relative}: {exc}; "
                "nothing was changed."
            ) from exc
        changes.append(GrammarMigrationChange(
            path=relative,
            before_sha256=_sha256(before),
            after_sha256=_sha256(after),
            inserted_fields=inserted,
            before=before,
            after=after,
        ))
    return GrammarMigrationPlan(
        root=resolved, changes=tuple(changes), warnings=tuple(warnings),
    )


def _stage_bytes(path: Path, data: bytes) -> Path:
    """Write and fsync a same-directory temporary ready for ``os.replace``."""

    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".m3a", dir=path.parent
    )
    temp_path = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path


def apply_grammar_migration(plan: GrammarMigrationPlan) -> None:
    """Apply *plan* atomically or restore every already-replaced source."""

    staged: dict[Path, Path] = {}
    replaced: list[GrammarMigrationChange] = []
    try:
        # Conflict/refusal preflight occurs for the complete set before staging.
        for change in plan.changes:
            target = plan.root / change.path
            if target.is_symlink() or not target.is_file():
                raise GrammarMigrationError(
                    "GRAMMAR_MIGRATION_CONFLICT",
                    f"{change.path} is no longer a "
                    "regular file; nothing was changed."
                )
            current = target.read_bytes()
            if _sha256(current) != change.before_sha256:
                raise GrammarMigrationError(
                    "GRAMMAR_MIGRATION_CONFLICT",
                    f"{change.path} changed after the "
                    "plan was created; nothing was changed. Rerun the dry-run."
                )
        for change in plan.changes:
            target = plan.root / change.path
            staged[target] = _stage_bytes(target, change.after)
        for change in plan.changes:
            target = plan.root / change.path
            os.replace(staged.pop(target), target)
            replaced.append(change)
    except BaseException as exc:
        rollback_errors: list[str] = []
        for change in reversed(replaced):
            target = plan.root / change.path
            try:
                rollback = _stage_bytes(target, change.before)
                os.replace(rollback, target)
            except BaseException as rollback_exc:  # pragma: no cover - disk failure
                rollback_errors.append(f"{change.path}: {rollback_exc}")
        for temp_path in staged.values():
            temp_path.unlink(missing_ok=True)
        if rollback_errors:
            raise GrammarMigrationError(
                "GRAMMAR_MIGRATION_ROLLBACK_FAILED", "; ".join(rollback_errors)
            ) from exc
        if isinstance(exc, GrammarMigrationError):
            raise
        raise GrammarMigrationError(
            "GRAMMAR_MIGRATION_APPLY_FAILED",
            f"{exc}; every replaced file was restored.",
        ) from exc
    finally:
        for temp_path in staged.values():
            temp_path.unlink(missing_ok=True)


def run_migrate_grammar(args: argparse.Namespace) -> int:
    """CLI entry point for ``s0ma migrate grammar``."""

    explicit = getattr(args, "project_dir", None)
    project = getattr(args, "s0ma_project", None)
    root = (
        Path(explicit) if explicit is not None
        else Path(project.root) if project is not None and not project.synthetic
        else Path.cwd()
    )
    configured_roots: tuple[Path, ...] | None = None
    if (
        project is not None
        and not project.synthetic
        and Path(project.root).resolve() == root.resolve()
    ):
        configured_roots = (*project.source_roots, *project.test_roots)
    try:
        plan = plan_grammar_migration(root, configured_roots=configured_roots)
        for warning in plan.warnings:
            print(warning, file=sys.stderr)
        applied = bool(getattr(args, "apply", False))
        if applied:
            apply_grammar_migration(plan)
        print(json.dumps(plan.manifest(applied=applied), indent=2, sort_keys=True))
        return EXIT_SUCCESS
    except NotADirectoryError:
        print(json.dumps({
            "schema": "s0ma-grammar-migration@1",
            "code": "GRAMMAR_MIGRATION_ROOT_INVALID",
            "ok": False,
            "message": f"not a directory: {root}",
        }, indent=2, sort_keys=True))
        return EXIT_USAGE_ERROR
    except GrammarMigrationError as exc:
        print(json.dumps({
            "schema": "s0ma-grammar-migration@1",
            "code": exc.code,
            "ok": False,
            "message": str(exc),
        }, indent=2, sort_keys=True))
        return EXIT_VALIDATION_ERROR
