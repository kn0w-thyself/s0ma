"""Everything the library knows about the titles it owns."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .errors import BookNotFoundError, DuplicateBookError
from .models import Availability, Book
from .storage import JsonStore

CATALOG_TABLE = "catalog"


class Catalog:
    """The library's holdings, backed by one table in the store."""

    def __init__(self, store: JsonStore | None = None) -> None:
        self._store = store if store is not None else JsonStore(Path(DATA_DIR))

    def books(self) -> list[Book]:
        """Every title the library owns, sorted by title and then author."""
        records = self._store.read(CATALOG_TABLE)
        books = [Book.from_record(_as_record(record)) for record in records]
        return sorted(books, key=lambda book: (book.title, book.author))

    def find(self, isbn: str) -> Book:
        """The title carrying this ISBN, or :class:`BookNotFoundError`."""
        for book in self.books():
            if book.isbn == isbn:
                return book
        raise BookNotFoundError(isbn)

    def add(self, book: Book) -> None:
        """Add a title the library does not already hold."""
        held = self.books()
        if any(other.isbn == book.isbn for other in held):
            raise DuplicateBookError(book.isbn)
        self._store.write(CATALOG_TABLE, [other.as_record() for other in [*held, book]])

    def copies_available(self, isbn: str) -> int:
        """How many copies of this title are on the shelf right now.

        The loan register reads the catalogue in turn, so this module and
        :mod:`bookshelf.lending` refer to each other. Importing the register
        inside the one method that needs it keeps both importable.
        """
        from .lending import LoanRegister

        book = self.find(isbn)
        return book.copies - LoanRegister(self._store).count_for(isbn)

    def availability(self, isbn: str) -> Availability:
        """Whether a copy of this title can be borrowed right now."""
        book = self.find(isbn)
        if book.copies == 0:
            return Availability.WITHDRAWN
        if self.copies_available(isbn) > 0:
            return Availability.ON_SHELF
        return Availability.ON_LOAN


@lru_cache(maxsize=1)
def shelf_sections() -> tuple[str, ...]:
    """The shelf sections titles are filed under; fixed while we are running."""
    return ("children", "fiction", "local history", "reference")


def _as_record(record: dict[str, Any]) -> dict[str, Any]:
    """Narrow a stored record to the four fields a title is made of."""
    return {
        "isbn": record["isbn"], "title": record["title"],
        "author": record["author"], "copies": record["copies"],
    }
