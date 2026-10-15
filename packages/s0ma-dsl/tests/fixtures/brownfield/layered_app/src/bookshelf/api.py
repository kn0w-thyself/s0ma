"""The handlers behind the counter screen.

Each handler takes plain values and gives plain records back, so the same
functions serve the command line and anything else put in front of them.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from .catalog import Catalog
from .errors import BookshelfError
from .lending import LoanRegister, overdue_loans
from .models import Book
from .storage import JsonStore

__all__ = [
    "add_title", "borrow_title", "build_services", "list_titles",
    "overdue_report", "return_title", "title_detail",
]


def build_services(data_dir: str | Path) -> tuple[Catalog, LoanRegister]:
    """The catalogue and the loan register, both over one data directory."""
    store = JsonStore(Path(data_dir))
    return Catalog(store), LoanRegister(store)


def list_titles(catalog: Catalog) -> list[dict[str, Any]]:
    """Every title the library owns, as records fit for a screen."""
    return [_title_summary(catalog, book) for book in catalog.books()]


def title_detail(catalog: Catalog, isbn: str) -> dict[str, Any]:
    """One title, with how many copies are free right now."""
    return _title_summary(catalog, catalog.find(isbn))


def add_title(catalog: Catalog, isbn: str, title: str, author: str, copies: int) -> dict[str, Any]:
    """Put a new title in the catalogue and return how it now reads."""
    catalog.add(Book(isbn=isbn, title=title, author=author, copies=copies))
    return title_detail(catalog, isbn)


def borrow_title(
    register: LoanRegister, isbn: str, card_number: str, today: date | None = None
) -> dict[str, Any]:
    """Lend one copy to one member and return the loan as a record."""
    loan = register.borrow(isbn, card_number, today or date.today())
    return {
        "isbn": loan.isbn, "card_number": loan.card_number,
        "due": loan.window.due.isoformat(), "renewals": loan.renewals,
    }


def return_title(register: LoanRegister, isbn: str, card_number: str) -> dict[str, Any]:
    """Take one copy back from one member."""
    register.give_back(isbn, card_number)
    return {"isbn": isbn, "card_number": card_number, "returned": True}


def overdue_report(register: LoanRegister, today: date | None = None) -> list[dict[str, Any]]:
    """The list of late loans that is read out at the counter each morning."""
    judged = today or date.today()
    return [
        {"isbn": loan.isbn, "card_number": loan.card_number, "days_late": -loan.days_left(judged)}
        for loan in overdue_loans(register, judged)
    ]


def describe_failure(error: Exception) -> dict[str, str]:
    """Turn a failure into something that can be put in front of a person.

    Errors raised on purpose carry a message worth showing; anything else
    gets a flat apology rather than an internal detail.
    """
    expected = isinstance(error, BookshelfError)
    return {
        "error": type(error).__name__,
        "message": str(error) if expected else "something went wrong at our end",
    }


def _title_summary(catalog: Catalog, book: Book) -> dict[str, Any]:
    return {
        "isbn": book.isbn, "label": book.label, "copies": book.copies,
        "available": catalog.copies_available(book.isbn),
        "availability": catalog.availability(book.isbn).value,
    }
