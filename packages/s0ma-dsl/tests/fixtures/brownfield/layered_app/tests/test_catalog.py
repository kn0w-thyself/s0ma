"""The catalogue: what the library owns, and how much of it is free."""

from __future__ import annotations

import pytest
from bookshelf import Availability, Book, BookNotFoundError, DuplicateBookError

CLARKE = "978-0-00-000002-8"
MANTEL = "978-0-00-000003-5"


def test_books_come_back_sorted_by_title(catalog):
    assert [book.title for book in catalog.books()] == ["Piranesi", "Small Gods", "Wolf Hall"]


def test_find_refuses_an_isbn_the_library_does_not_hold(catalog):
    with pytest.raises(BookNotFoundError):
        catalog.find("978-0-00-000999-9")


def test_the_same_title_cannot_be_added_twice(catalog):
    with pytest.raises(DuplicateBookError):
        catalog.add(Book(isbn=CLARKE, title="Piranesi", author="Susanna Clarke"))


def test_a_title_with_no_copies_reads_as_withdrawn(catalog):
    assert catalog.availability(MANTEL) is Availability.WITHDRAWN
