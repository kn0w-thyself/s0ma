"""Whole-project migration into the explicit semantic-state grammar.

``s0ma migrate grammar`` is dry-run by default.  It parses every authored
source before planning a write, emits a deterministic manifest, and applies
the complete plan with per-file atomic replacement plus whole-plan rollback.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.parser.s0ma_parser import _RawDeclaration, _split_declarations, parse_s0ma
from s0ma_dsl.semantic_state import semantic_fields, semantic_source_field

if TYPE_CHECKING:
    import argparse

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


def _discover_sources(root: Path) -> list[Path]:
    sources: list[Path] = []

    def walk(directory: Path) -> None:
        for entry in sorted(directory.iterdir(), key=lambda item: item.name):
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in _PRUNE:
                    walk(entry)
            elif entry.name.endswith(".s0ma"):
                sources.append(entry)

    walk(root)
    return sources


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


def plan_grammar_migration(root: Path) -> GrammarMigrationPlan:
    """Parse the whole project, then return a deterministic immutable plan."""

    resolved = root.resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    changes: list[GrammarMigrationChange] = []
    for path in _discover_sources(resolved):
        relative = path.relative_to(resolved).as_posix()
        try:
            before = path.read_bytes()
            source = before.decode("utf-8")
            # Whole-project preflight: any failure aborts before a plan can apply.
            parse_s0ma(
                source,
                filename=relative,
                _allow_legacy_semantic_omissions=True,
            )
        except (OSError, UnicodeDecodeError, S0maParseError) as exc:
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
            parse_s0ma(after_text, filename=relative)
        except S0maParseError as exc:  # pragma: no cover - defensive invariant
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
    return GrammarMigrationPlan(root=resolved, changes=tuple(changes))


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
    try:
        plan = plan_grammar_migration(root)
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
