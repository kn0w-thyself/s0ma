"""Adopted-file records — the per-file primitive of the ``s0ma adopt`` family.

Adoption (0.11.0, batch-01a D2 — owner-decided: adopt, not warning-only)
makes real, non-generated files first-class in the project self-model:
registered by path, verified by content hash, and counted in the score's
registration ratio. The bench failure this closes is the hollow-model
case (P2_P_r02 grew 1→6 unregistered ``_impl.py`` files with verify
green throughout).

Persistence — the design decision, spelled out
----------------------------------------------

The durable record is a **committed JSON sidecar at the project root**:
``adopted.s0ma.json``, schema ``s0ma-adopted-files@1``. Rationale (the
alternatives surveyed and rejected):

* ``.s0ma/registry.db`` (core SQLite persistence) — gitignored ("s0ma
  persistence"), binary, per-machine runtime state; the static CLI
  surfaces (``verify``/``score``/``inspect``) never open it, and the
  record must be a reviewable, diffable artifact.
* ``[tool.s0ma]`` keys in ``pyproject.toml`` — the right home for
  hand-authored path lists (``bootstrap_files``/``package_markers``),
  but adoption records carry machine-computed content hashes rewritten
  on every re-adopt; the toolchain has no TOML round-trip writer (only
  stdlib ``tomllib`` reads; ``init_project`` does a one-time
  byte-preserving *append*), so tool-driven updates would mean text
  surgery on user-owned config.
* a build-dir artifact beside ``build.s0ma.json`` — the build dir is
  derived output (regenerated, ``--clean``-able); adoption records are
  authored state and must survive a clean rebuild.

The chosen shape follows the established ``<name>.s0ma.json``
schema-versioned JSON family (``build.s0ma.json``) and the brownfield
adoption plan's emerging idiom (its M3 ``adopt baseline`` captures land
in committed JSON). Output is deterministic (sorted keys, stable
indentation, trailing newline) so records diff cleanly (INV-5
discipline). Paths are stored project-root-relative in POSIX form so
records stay portable across checkouts and platforms.

Hashing convention: ``sha256:<hex>`` over the file's UTF-8 text
(:func:`s0ma_dsl.codegen.build_manifest.compute_file_hash` over
``read_text``), matching how ``project_status`` compares manifest
source hashes — text-mode reading normalizes newlines, so a CRLF
checkout does not produce false drift.

Interlock: the brownfield plan (``s0ma-new-brownfield-adoption-1``)
owns the full conversion ladder and reserves the ``s0ma adopt
scan/draft/baseline/verify-parity`` sub-commands; this module is only
the per-file record store those mechanisms build on.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from s0ma.models import AdoptedFile

from s0ma_dsl.codegen.build_manifest import compute_file_hash

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADOPTED_SCHEMA = "s0ma-adopted-files@1"
"""Canonical schema string for the adopted-files record. Additive fields
ride the same string; ``@2`` is reserved for a breaking change — the
``build.s0ma.json`` versioning policy."""

ADOPTED_FILENAME = "adopted.s0ma.json"
"""On-disk filename for the adopted-files record, at the project root
(beside ``pyproject.toml``) so it is committed and diffable."""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AdoptedRecordError(Exception):
    """Raised when ``adopted.s0ma.json`` is malformed or schema-mismatched.

    A *missing* record file is not an error — it means nothing has been
    adopted (:func:`load_adopted_files` returns an empty mapping).
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def adopted_record_path(root: Path) -> Path:
    """The adopted-files record path for a project rooted at *root*."""
    return root / ADOPTED_FILENAME


def compute_adopted_hash(path: Path) -> str:
    """Return ``sha256:<hex>`` over *path*'s UTF-8 text content.

    Text-mode reading (universal newlines) keeps the hash stable across
    LF/CRLF checkouts, mirroring the manifest source-hash convention.
    Raises ``OSError`` when unreadable and ``UnicodeDecodeError`` when
    the file is not UTF-8 text — callers surface both as friendly
    refusals.
    """
    return compute_file_hash(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


def load_adopted_files(root: Path) -> dict[str, AdoptedFile]:
    """Read the project's adopted-file records, keyed by recorded path.

    Returns an empty dict when no ``adopted.s0ma.json`` exists (nothing
    adopted yet — the common case). Raises :class:`AdoptedRecordError`
    when the file exists but is malformed or carries an unknown schema,
    with the remediation named explicitly.
    """
    record_path = adopted_record_path(root)
    if not record_path.is_file():
        return {}

    try:
        raw = json.loads(record_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AdoptedRecordError(
            f"Adopted-files record at {record_path} is not readable JSON: "
            f"{exc}. Fix or delete the file, then re-run "
            f"`s0ma adopt file <path>` for each adopted file."
        ) from exc

    if not isinstance(raw, dict):
        raise AdoptedRecordError(
            f"Adopted-files record at {record_path} is not a JSON object. "
            f"Fix or delete the file, then re-run `s0ma adopt file <path>` "
            f"for each adopted file."
        )

    schema = raw.get("schema")
    if schema != ADOPTED_SCHEMA:
        raise AdoptedRecordError(
            f"Adopted-files record at {record_path} has schema {schema!r}, "
            f"expected {ADOPTED_SCHEMA!r}. Regenerate it with "
            f"`s0ma adopt file <path>` using this toolchain version."
        )

    files_raw = raw.get("files", {})
    if not isinstance(files_raw, dict):
        raise AdoptedRecordError(
            f"Adopted-files record at {record_path} has a non-object "
            f"'files' entry. Fix or delete the file, then re-run "
            f"`s0ma adopt file <path>` for each adopted file."
        )

    records: dict[str, AdoptedFile] = {}
    for key, payload in files_raw.items():
        if not isinstance(payload, dict) or "path" not in payload:
            raise AdoptedRecordError(
                f"Adopted-files record at {record_path} has a malformed "
                f"entry for {key!r} (expected an object with a 'path' "
                f"key). Fix or delete the file, then re-run "
                f"`s0ma adopt file <path>` for each adopted file."
            )
        description = payload.get("description")
        if not isinstance(description, str) or not description.strip():
            raise AdoptedRecordError(
                f"Adopted-files record at {record_path} is legacy or malformed: "
                f"files.{key}.description is required and must be a non-empty "
                f"authored intent. Add the intent to that entry (or recreate "
                f"the record with `s0ma adopt file {key} --description "
                f"<intent>`) before re-running; s0ma will not silently invent "
                f"or discard semantic intent."
            )
        try:
            records[str(key)] = AdoptedFile.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise AdoptedRecordError(
                f"Adopted-files record at {record_path} has an invalid entry "
                f"for {key!r}: {exc}"
            ) from exc
    return records


def save_adopted_files(
    root: Path, records: Mapping[str, AdoptedFile],
) -> Path:
    """Write *records* to the project's ``adopted.s0ma.json``; return its path.

    Deterministic output (sorted keys, indent 2, trailing newline, LF
    endings on every platform) so the committed record diffs cleanly.
    ``newline="\\n"`` is what makes that true on Windows, where text
    mode would otherwise translate each newline to CRLF and the same
    record would diff whole every time it crossed platforms. An empty
    mapping still writes a valid record file — "everything un-adopted"
    is a reviewable state, and deleting the file is the author's call,
    not the tool's.
    """
    record_path = adopted_record_path(root)
    payload = {
        "schema": ADOPTED_SCHEMA,
        "files": {
            key: records[key].to_dict() for key in sorted(records)
        },
    }
    record_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return record_path
