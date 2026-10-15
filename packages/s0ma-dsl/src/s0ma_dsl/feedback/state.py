"""Local, user-scoped state for the feedback function (contract §8).

Everything the feedback function remembers between runs lives under
``~/.s0ma/`` — never inside a project tree, never committed. This module
owns the directory itself and the ``installation_id`` pseudonym; FB-M6
adds the token file, the draft directory, and the receipts log on top of
the same permission discipline (:func:`write_private_text`).

Permissions are **best effort by design**. POSIX gets ``0700`` on the
directory and ``0600`` on every file; elsewhere :func:`_chmod_best_effort`
is a documented no-op, because Windows ACLs are not expressible as a POSIX
mode and a failed ``chmod`` must never stop a user from sending feedback.
No function here raises because a mode could not be applied.

Determinism note (contract §1.4): INV-5 governs *emitted artifacts*. The
installation pseudonym is runtime state and is deliberately random —
:func:`secrets.token_hex`, not a hash of anything about the machine. It is
never a hardware fingerprint (contract §5), and rotating it is a delete.
"""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

__all__ = [
    "INSTALLATION_ID_BYTES",
    "INSTALLATION_ID_FILENAME",
    "STATE_DIR_MODE",
    "STATE_DIR_NAME",
    "STATE_FILE_MODE",
    "ensure_state_dir",
    "installation_id",
    "read_installation_id",
    "rotate_installation_id",
    "state_dir",
    "write_private_text",
]

#: Directory name under the user's home (``%USERPROFILE%`` on Windows).
STATE_DIR_NAME = ".s0ma"

#: File holding the installation pseudonym (contract §8).
INSTALLATION_ID_FILENAME = "installation_id"

#: Owner-only directory mode, applied on POSIX only.
STATE_DIR_MODE = 0o700

#: Owner-only file mode, applied on POSIX only.
STATE_FILE_MODE = 0o600

#: Pseudonym entropy — 16 random bytes rendered as 32 hex characters.
INSTALLATION_ID_BYTES = 16

# A stored pseudonym that does not match this shape is treated as corrupt
# and replaced. That also guarantees the field can never carry hand-written
# content (a name, an email) into an envelope.
_INSTALLATION_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")


def state_dir(home: Path | None = None) -> Path:
    """Return ``<home>/.s0ma`` without creating anything.

    *home* defaults to :meth:`pathlib.Path.home`, which reads ``HOME`` on
    POSIX and ``%USERPROFILE%`` on Windows. Tests either monkeypatch those
    environment variables or pass *home* explicitly.
    """
    base = Path(home) if home is not None else Path.home()
    return base / STATE_DIR_NAME


def _chmod_best_effort(path: Path, mode: int) -> bool:
    """Apply *mode* to *path*, returning whether it was actually applied.

    A no-op returning ``False`` off POSIX, and ``False`` (never an
    exception) when the platform refuses the change.
    """
    if os.name != "posix":
        return False
    try:
        os.chmod(path, mode)
    except OSError:
        return False
    return True


def ensure_state_dir(home: Path | None = None) -> Path:
    """Create ``~/.s0ma`` if needed and return it.

    Raises :class:`OSError` only when the directory itself cannot be
    created; a refused ``chmod`` is swallowed by design.
    """
    directory = state_dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(directory, STATE_DIR_MODE)
    return directory


def write_private_text(path: Path, text: str) -> None:
    """Write *text* to *path* as owner-only UTF-8 with LF line endings.

    The file is created with :data:`STATE_FILE_MODE` from the outset (so it
    is never briefly world-readable) and re-``chmod``-ed afterwards for the
    case where it already existed. The parent directory is created with
    :data:`STATE_DIR_MODE`.
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(parent, STATE_DIR_MODE)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, STATE_FILE_MODE)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    _chmod_best_effort(path, STATE_FILE_MODE)


def read_installation_id(home: Path | None = None) -> str | None:
    """Return the stored pseudonym, or ``None`` when absent or unreadable.

    Never creates anything. A file whose contents are not 32 lowercase hex
    characters reads as ``None`` (corrupt), so callers regenerate rather
    than transmit whatever the file happened to hold.
    """
    path = state_dir(home) / INSTALLATION_ID_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    value = raw.strip()
    return value if _INSTALLATION_ID_RE.match(value) else None


def _mint_installation_id(home: Path | None = None) -> str:
    """Generate, store, and return a fresh pseudonym."""
    directory = ensure_state_dir(home)
    path = directory / INSTALLATION_ID_FILENAME
    value = secrets.token_hex(INSTALLATION_ID_BYTES)
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, STATE_FILE_MODE
        )
    except FileExistsError:
        # Either a concurrent process won the race — keep its id, so both
        # processes agree — or the existing file is corrupt and is replaced.
        concurrent = read_installation_id(home)
        if concurrent is not None:
            return concurrent
        write_private_text(path, f"{value}\n")
        return value
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{value}\n")
    _chmod_best_effort(path, STATE_FILE_MODE)
    return value


def installation_id(home: Path | None = None) -> str:
    """Return this installation's pseudonym, creating it on first use.

    Stable across runs until the user deletes ``~/.s0ma/installation_id``
    or calls :func:`rotate_installation_id`. Raises :class:`OSError` when
    the state directory cannot be written — callers that merely want
    context should treat that as "no pseudonym" rather than a failure.
    """
    existing = read_installation_id(home)
    if existing is not None:
        return existing
    return _mint_installation_id(home)


def rotate_installation_id(home: Path | None = None) -> str:
    """Delete the stored pseudonym and return a freshly generated one.

    Rotation is exactly the user-facing gesture the contract documents —
    deleting the file — performed for them.
    """
    path = state_dir(home) / INSTALLATION_ID_FILENAME
    path.unlink(missing_ok=True)
    return _mint_installation_id(home)
