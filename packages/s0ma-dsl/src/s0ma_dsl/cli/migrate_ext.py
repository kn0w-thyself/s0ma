"""``s0ma migrate-ext`` — migrate a project from the legacy extension family.

The s0ma consolidation (IR schema 2.0.0) renamed the on-disk artifact
family from the letter-o spelling to the ``s0ma`` spelling:

==========================  ==========================
Legacy (pre-2.0.0)          Current
==========================  ==========================
``*.soma``                  ``*.s0ma``  # legacy-spelling: intentional
``*.soma.json``             ``*.s0ma.json``  # legacy-spelling: intentional
``*.soma.map``              ``*.s0ma.map``  # legacy-spelling: intentional
``build.soma.json``         ``build.s0ma.json``  # legacy-spelling: intentional
``[tool.soma]``             ``[tool.s0ma]``  # legacy-spelling: intentional
``.soma.cache/``            ``.s0ma.cache/``  # legacy-spelling: intentional
``__soma_cache__/``         ``__s0ma_cache__/``  # legacy-spelling: intentional
==========================  ==========================

This module is the ONLY place in the codebase (other than its tests)
where the legacy spelling may appear; every such literal is marked
``# legacy-spelling: intentional`` for the CI spelling guard.

Behavior
--------
- Walks the project tree and renames every file carrying a legacy
  extension to its current-spelling equivalent. The match is anchored at
  the END of the filename (longest suffix first), so only the extension
  is rewritten — never an interior occurrence.
- Rewrites legacy ``[tool.*]`` table headers in the project root's
  ``pyproject.toml`` to the current spelling, byte-preserving every
  other line.
- Removes legacy cache directories (the pre-consolidation incremental
  build cache and the legacy import-hook cache). Caches are regenerable;
  their internal entries are keyed by legacy artifact names and would
  never be hits again, so removal — not rename — is the correct
  migration. The next ``s0ma build`` (or import) repopulates them under
  the current names.
- Collision-safe: the command first plans the full migration; if ANY
  rename target already exists, it reports every collision and exits
  without touching the tree (error, never clobber).
- Idempotent: a second run finds nothing to migrate and exits 0.
- ``--dry-run`` prints the full plan without applying it. Without
  ``--dry-run`` every rename/removal/rewrite is printed as it happens,
  so a real run is never surprising. ``--quiet`` suppresses the
  per-item lines and keeps the one-line summary.

Note: transpiled ``.py`` outputs produced by a pre-2.0.0 transpiler
embed legacy hash-comment markers; ``migrate-ext`` does not rewrite
``.py`` file contents. Run ``s0ma build`` after migrating — it re-emits
the Python outputs with current markers and a ``build.s0ma.json``
manifest.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

EXIT_SUCCESS = 0
EXIT_VALIDATION_ERROR = 1
EXIT_USAGE_ERROR = 2

#: Legacy extension suffixes mapped to their current spellings, ordered
#: longest-first so suffix matching is unambiguous — x.soma.json  # legacy-spelling: intentional
#: must match the IR suffix, not the bare source suffix.
LEGACY_SUFFIX_MAP: tuple[tuple[str, str], ...] = (
    (".soma.json", ".s0ma.json"),  # legacy-spelling: intentional
    (".soma.map", ".s0ma.map"),  # legacy-spelling: intentional
    (".soma", ".s0ma"),  # legacy-spelling: intentional
)

#: Legacy cache directory names removed by the migration.
LEGACY_CACHE_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".soma.cache",  # legacy-spelling: intentional
        "__soma_cache__",  # legacy-spelling: intentional
    }
)

#: Legacy pyproject config table prefix — [tool.soma] and its  # legacy-spelling: intentional
#: [tool.soma.<sub>] subtable headers.  # legacy-spelling: intentional
_LEGACY_TABLE_PREFIX = "tool.soma"  # legacy-spelling: intentional
_CURRENT_TABLE_PREFIX = "tool.s0ma"

#: Directories never walked into (VCS internals, environments, live
#: current-spelling caches — regenerable, nothing to migrate inside).
_PRUNE_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".s0ma.cache",
        "__s0ma_cache__",
    }
)


def _plan_file_renames(root: Path) -> tuple[list[tuple[Path, Path]], list[Path]]:
    """Walk *root*; return (planned renames, legacy cache dirs).

    Renames are (source, target) pairs for every file whose name ends
    with a legacy suffix. Legacy cache directories are collected for
    removal and never descended into.
    """
    renames: list[tuple[Path, Path]] = []
    cache_dirs: list[Path] = []

    def _walk(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for entry in entries:
            if entry.is_symlink():
                # Never follow or rewrite through symlinks; the link
                # target may live outside the tree being migrated.
                continue
            if entry.is_dir():
                if entry.name in LEGACY_CACHE_DIR_NAMES:
                    cache_dirs.append(entry)
                elif entry.name not in _PRUNE_DIR_NAMES:
                    _walk(entry)
                continue
            for legacy, current in LEGACY_SUFFIX_MAP:
                if entry.name.endswith(legacy):
                    new_name = entry.name[: -len(legacy)] + current
                    renames.append((entry, entry.with_name(new_name)))
                    break

    _walk(root)
    return renames, cache_dirs


def _plan_pyproject_rewrite(pyproject: Path) -> list[tuple[int, str, str]] | None:
    """Return planned (lineno, old, new) header rewrites, or None.

    Only TOML table-header lines naming the legacy table
    (``[tool.soma]`` or a ``[tool.soma.<sub>]`` subtable, see  # legacy-spelling: intentional
    ``_LEGACY_TABLE_PREFIX``) are rewritten; every other byte of the
    file is preserved.
    """
    if not pyproject.is_file():
        return None
    try:
        text = pyproject.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    changes: list[tuple[int, str, str]] = []
    for idx, line in enumerate(text.splitlines()):
        stripped = line.lstrip()
        if not stripped.startswith("["):
            continue
        head = stripped.lstrip("[")
        if head.startswith(_LEGACY_TABLE_PREFIX) and (
            head[len(_LEGACY_TABLE_PREFIX) :].startswith("]")
            or head[len(_LEGACY_TABLE_PREFIX) :].startswith(".")
        ):
            changes.append(
                (
                    idx,
                    line,
                    line.replace(_LEGACY_TABLE_PREFIX, _CURRENT_TABLE_PREFIX, 1),
                )
            )
    return changes or None


def run_migrate_ext(args: argparse.Namespace) -> int:
    """Execute ``s0ma migrate-ext`` (see module docstring for semantics)."""
    dry_run: bool = getattr(args, "dry_run", False)
    quiet: bool = getattr(args, "quiet", False)

    s0ma_project = getattr(args, "s0ma_project", None)
    if getattr(args, "project_dir", None) is not None:
        root = Path(args.project_dir).resolve()
    elif s0ma_project is not None and not s0ma_project.synthetic:
        root = s0ma_project.root
    else:
        root = Path.cwd()

    if not root.is_dir():
        print(f"s0ma migrate-ext: not a directory: {root}")
        return EXIT_USAGE_ERROR

    renames, cache_dirs = _plan_file_renames(root)
    pyproject = root / "pyproject.toml"
    table_changes = _plan_pyproject_rewrite(pyproject)

    if not renames and not cache_dirs and table_changes is None:
        print(f"s0ma migrate-ext: nothing to migrate under {root}.")
        return EXIT_SUCCESS

    # Collision check across the WHOLE plan before touching anything.
    collisions = [(src, dst) for src, dst in renames if dst.exists()]
    if collisions:
        print(
            f"s0ma migrate-ext: refusing to migrate — {len(collisions)} "
            f"rename target(s) already exist (nothing was changed):"
        )
        for src, dst in collisions:
            # W-2: relative paths in diagnostics render POSIX (`/`) on every OS.
            print(
                f"  {src.relative_to(root).as_posix()} -> "
                f"{dst.relative_to(root).as_posix()} (target exists)"
            )
        print(
            "Remove or rename the conflicting target file(s), then re-run "
            "`s0ma migrate-ext`."
        )
        return EXIT_VALIDATION_ERROR

    verb_rename = "would rename" if dry_run else "renamed"
    verb_remove = "would remove" if dry_run else "removed"
    verb_rewrite = "would rewrite" if dry_run else "rewrote"

    for src, dst in renames:
        if not dry_run:
            src.rename(dst)
        if not quiet:
            # W-2: relative paths in diagnostics render POSIX (`/`) on every OS.
            print(
                f"  {verb_rename}: {src.relative_to(root).as_posix()} -> "
                f"{dst.relative_to(root).as_posix()}"
            )

    for cache_dir in cache_dirs:
        if not dry_run:
            shutil.rmtree(cache_dir)
        if not quiet:
            # W-2: relative paths in diagnostics render POSIX (`/`) on every OS.
            print(
                f"  {verb_remove}: {cache_dir.relative_to(root).as_posix()}/ "
                f"(legacy cache; regenerated by the next build)"
            )

    if table_changes is not None:
        if not dry_run:
            # Bytes-mode rewrite (W-3): only the matched header lines
            # change; every other byte — including each line's own
            # ending — is preserved on every OS. Text-mode read/write
            # would translate the file's newlines wholesale (universal
            # newlines on read, os.linesep on write), which both
            # destroys the byte-preservation contract and (on read)
            # makes the per-line ending detection below unreachable.
            lines = pyproject.read_bytes().decode("utf-8").splitlines(keepends=True)
            for idx, _old, new in table_changes:
                newline = ""
                if lines[idx].endswith("\r\n"):
                    newline = "\r\n"
                elif lines[idx].endswith("\n"):
                    newline = "\n"
                lines[idx] = new + newline
            pyproject.write_bytes("".join(lines).encode("utf-8"))
        if not quiet:
            for _idx, old, new in table_changes:
                print(f"  {verb_rewrite}: pyproject.toml: {old.strip()} -> {new.strip()}")

    n_tables = len(table_changes) if table_changes is not None else 0
    summary = (
        f"s0ma migrate-ext: {len(renames)} file(s) renamed, "
        f"{len(cache_dirs)} legacy cache dir(s) removed, "
        f"{n_tables} pyproject table header(s) rewritten under {root}."
    )
    if dry_run:
        summary += " (dry-run: nothing was changed)"
    else:
        summary += " Run `s0ma build` to re-emit Python outputs and the manifest."
    print(summary)
    return EXIT_SUCCESS
