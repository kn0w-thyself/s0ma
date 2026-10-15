from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .errors import StorageCorruptError

logger = logging.getLogger(__name__)
# A library has no business configuring logging for the program that imports
# it; the null handler keeps "no handlers could be found" off a quiet console.
logger.addHandler(logging.NullHandler())


class JsonStore:
    """Keeps the service's tables as one JSON file per table.

    A table is a list of records; nothing here knows what a record means.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def read(self, table: str) -> list[dict[str, Any]]:
        """Every record in ``table``; one that was never written reads empty."""
        path = self.path_for(table)
        if not path.exists():
            return []
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StorageCorruptError(table, str(exc)) from exc
        if not isinstance(records, list):
            raise StorageCorruptError(table, "the stored value is not a list of records")
        return records

    def write(self, table: str, records: list[dict[str, Any]]) -> None:
        """Replace every record in ``table``.

        The new file is written beside the old one and renamed over it, so a
        reader never sees a half-written table.
        """
        # Only the write path needs this, and writing is the rare case.
        import os

        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(table)
        scratch = path.with_name(path.name + ".new")
        scratch.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(scratch, path)
        logger.debug("wrote %d records to %s", len(records), path.name)

    def path_for(self, table: str) -> Path:
        """Where ``table`` is kept on disk."""
        return self.root / f"{table}.json"
