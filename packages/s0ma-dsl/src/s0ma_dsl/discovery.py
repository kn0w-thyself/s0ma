"""Hidden-subtree-aware filesystem walking for s0ma discovery.

Every walker that answers "which files does this project own?" has to
agree on one question: what is *not* project source. The answer is
structural — a path is skipped when any directory component **below the
search root** is hidden (dot-prefixed) or is a well-known machine-owned
directory (:data:`EXCLUDED_DIR_NAMES`).

The rule was previously spelled out one call site at a time. Discovery
in ``cli/main.py`` filtered ``rglob`` results to real files so a ``.s0ma``
*directory* (the gitignored working-state dir holding the check baseline
and ``registry.db``) could not be handed to the parser, and
``adoption_policy`` carried its own ``excluded_dirs`` name set. Neither
excluded ``.claude/``, so a project root containing Claude Code session
worktrees (``.claude/worktrees/<name>/`` — full checkouts of the same
project) discovered every module twice and ``s0ma build <project_root>``
died with ``MODULE_NAME_COLLISION``, once per module per worktree. The
same shape applies to any tool that checks a working copy out inside the
tree it is checking out.

**Relative to the search root, always.** The hidden check runs on the
path *below* the anchor, never on the absolute path. A project may
legitimately live inside a hidden directory — a Claude Code worktree at
``.claude/worktrees/<name>/`` is itself a working project root — and
testing absolute components would make discovery return nothing at all
for exactly the checkouts this module exists to disambiguate.

Pruning, not filtering: :func:`iter_visible_files` never descends into an
excluded directory, so a repository-root walk no longer pays for ``.git``
or ``.venv``. Call sites whose glob may be path-shaped (a user-declared
``[tool.s0ma].fixtures_format`` key) keep ``rglob`` and filter its results
with :func:`is_in_hidden_subtree` instead, preserving glob semantics
exactly.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

__all__ = [
    "EXCLUDED_DIR_NAMES",
    "is_excluded_dir_name",
    "is_in_hidden_subtree",
    "iter_visible_files",
    "iter_visible_dirs",
]


# Machine-owned directories that are not dot-prefixed and so are not
# caught by the hidden rule. ``__pycache__`` is the only one today; it
# was already excluded by ``adoption_policy``'s local name set, which
# this module subsumes (``.git`` / ``.s0ma`` / ``.venv`` / ``.s0ma.cache``
# from that set are all hidden and need no name entry).
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset({"__pycache__"})


def is_excluded_dir_name(name: str) -> bool:
    """Return ``True`` when a *single* directory name is never walked.

    Hidden (dot-prefixed) directories are excluded structurally rather
    than by enumeration, so a machine-owned directory nobody has thought
    of yet — a new agent harness, a new tool cache — is skipped the day
    it appears instead of the day someone adds it to a list.
    """
    return name.startswith(".") or name in EXCLUDED_DIR_NAMES


def is_in_hidden_subtree(path: Path, root: Path) -> bool:
    """Return ``True`` when *path* sits inside an excluded dir below *root*.

    Only the directory components strictly between *root* and *path* are
    tested; *path*'s own basename is not, so a dot-prefixed **file**
    (``.env``) is not excluded by this predicate while any file under a
    dot-prefixed **directory** (``.claude/worktrees/x/src/mod.s0ma``) is.

    A *path* that is not relative to *root* — which a symlink escaping
    the tree can produce — is reported as excluded: discovery cannot
    reason about ownership outside the anchor it was given.
    """
    try:
        relative = path.relative_to(root)
    except ValueError:
        try:
            relative = path.resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            return True
    return any(is_excluded_dir_name(part) for part in relative.parts[:-1])


def iter_visible_files(root: Path, pattern: str = "*") -> list[Path]:
    """Return sorted files under *root* matching *pattern*, hidden dirs pruned.

    A drop-in replacement for ``sorted(root.rglob(pattern))`` when
    *pattern* matches a **basename** (``*.s0ma``, ``*.py``,
    ``*.s0ma.json``) — the walk never descends into an excluded
    directory, and only regular files are returned, so a directory whose
    name matches the pattern (the ``.s0ma`` working-state dir under
    ``*.s0ma``) can never reach a caller that expects a file.

    Matching uses :func:`fnmatch.fnmatch`, which case-normalises per
    platform exactly as ``rglob`` does, so a Windows run stays
    case-insensitive and a POSIX run stays case-sensitive.

    Returns an empty list when *root* is not a directory.
    """
    if not root.is_dir():
        return []
    matched: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not is_excluded_dir_name(d)]
        here = Path(dirpath)
        for filename in filenames:
            if not fnmatch.fnmatch(filename, pattern):
                continue
            candidate = here / filename
            if candidate.is_file():
                matched.append(candidate)
    return sorted(matched)


def iter_visible_dirs(root: Path, name: str) -> list[Path]:
    """Return sorted directories named *name* under *root*, hidden dirs pruned.

    The directory counterpart of :func:`iter_visible_files`, for the
    cleanup paths that hunt legacy artifact directories by exact name.
    A match is itself returned but not descended into — nothing nested
    inside a directory the caller is about to delete is worth reporting
    separately.

    Excluded directories are pruned before matching, so ``s0ma clean`` at
    a repository root cannot reach into a sibling checkout under
    ``.claude/worktrees/`` and delete another session's artifacts.
    """
    if not root.is_dir():
        return []
    matched: list[Path] = []
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not is_excluded_dir_name(d)]
        here = Path(dirpath)
        hits = [d for d in dirnames if d == name]
        for hit in hits:
            matched.append(here / hit)
        # Do not descend into a directory already reported as a match.
        dirnames[:] = [d for d in dirnames if d != name]
    return sorted(matched)
