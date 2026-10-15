"""Every error the lending service raises on purpose, in one hierarchy.

Catch :class:`BookshelfError` for anything; catch a narrower class to
handle one failure on its own.
"""

from __future__ import annotations


class BookshelfError(Exception):
    """Base class for every error the lending service raises."""


class CatalogError(BookshelfError):
    """Something is wrong with the catalogue or with a record in it."""


class BookNotFoundError(CatalogError):
    """No title in the catalogue carries the requested ISBN."""

    def __init__(self, isbn: str) -> None:
        super().__init__(f"no title with ISBN {isbn} is in the catalogue")
        self.isbn = isbn


class DuplicateBookError(CatalogError):
    """A title with this ISBN is already in the catalogue."""

    def __init__(self, isbn: str) -> None:
        super().__init__(f"ISBN {isbn} is already in the catalogue")
        self.isbn = isbn


class StorageCorruptError(BookshelfError):
    """A stored table could not be read back as a list of records."""

    def __init__(self, table: str, reason: str) -> None:
        super().__init__(f"the {table} table could not be read: {reason}")
        self.table = table
        self.reason = reason


class LendingError(BookshelfError):
    """A loan could not be made, renewed or returned."""


class BookUnavailableError(LendingError):
    """Every copy of this title is already out on loan."""

    def __init__(self, isbn: str) -> None:
        super().__init__(f"every copy of ISBN {isbn} is out on loan")
        self.isbn = isbn


class LoanNotFoundError(LendingError):
    """This member does not have this title out on loan."""

    def __init__(self, isbn: str, card_number: str) -> None:
        super().__init__(f"card {card_number} does not have ISBN {isbn} on loan")
        self.isbn = isbn
        self.card_number = card_number


class LoanLimitReachedError(LendingError):
    """This member is already holding as many books as the rules allow."""

    def __init__(self, card_number: str, limit: int) -> None:
        super().__init__(f"card {card_number} already holds the limit of {limit} books")
        self.card_number = card_number
        self.limit = limit


class RenewalRefusedError(LendingError):
    """This loan has been renewed as often as the rules allow."""

    def __init__(self, isbn: str, limit: int) -> None:
        super().__init__(f"ISBN {isbn} has already been renewed {limit} times")
        self.isbn = isbn
        self.limit = limit
