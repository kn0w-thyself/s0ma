"""The nouns of the lending service: titles, members and loans.

Nothing here reaches for the catalogue or the loan register; the classes
know only what can be worked out from the values they carry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, NamedTuple, TypedDict

if TYPE_CHECKING:
    from datetime import date


class Availability(Enum):
    """Whether a copy of a title can be borrowed right now."""

    ON_SHELF = "on_shelf"
    ON_LOAN = "on_loan"
    WITHDRAWN = "withdrawn"


class BookRecord(TypedDict):
    """The shape one title takes when it is stored on disk."""

    isbn: str
    title: str
    author: str
    copies: int


class LoanWindow(NamedTuple):
    """The two dates that bound a loan."""

    start: date
    due: date


@dataclass(frozen=True)
class Book:
    """A title the library owns, and how many copies it holds."""

    isbn: str
    title: str
    author: str
    copies: int = 1

    @property
    def label(self) -> str:
        """A one-line description fit for a shelf edge or a screen."""
        return f"{self.title} by {self.author}"

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> Book:
        """Build a title from the dictionary shape used on disk."""
        return cls(
            isbn=str(record["isbn"]), title=str(record["title"]),
            author=str(record["author"]), copies=int(record["copies"]),
        )

    def as_record(self) -> BookRecord:
        """Return the dictionary shape used on disk."""
        return {
            "isbn": self.isbn, "title": self.title,
            "author": self.author, "copies": self.copies,
        }


@dataclass(frozen=True)
class Member:
    """Someone the library has issued a card to."""

    card_number: str
    name: str
    email: str


@dataclass(frozen=True)
class Loan:
    """One member's hold on one title, for a window of dates."""

    isbn: str
    card_number: str
    window: LoanWindow
    renewals: int = 0

    def is_overdue(self, today: date) -> bool:
        """True when ``today`` has passed the loan's due date."""
        return today > self.window.due

    def days_left(self, today: date) -> int:
        """Days left before the loan falls due; negative once it is late."""
        return (self.window.due - today).days
