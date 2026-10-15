"""Fixtures shared by the lending service's tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from bookshelf import Book, Catalog, JsonStore, LoanRegister

PRATCHETT = "978-0-00-000001-1"
CLARKE = "978-0-00-000002-8"
MANTEL = "978-0-00-000003-5"


@pytest.fixture()
def store(tmp_path: Path) -> JsonStore:
    """A store over an empty directory, one per test."""
    return JsonStore(Path(tmp_path, "data"))


@pytest.fixture()
def catalog(store: JsonStore) -> Catalog:
    """A catalogue holding three titles, one of them withdrawn."""
    shelf = Catalog(store)
    shelf.add(Book(isbn=PRATCHETT, title="Small Gods", author="Terry Pratchett", copies=2))
    shelf.add(Book(isbn=CLARKE, title="Piranesi", author="Susanna Clarke", copies=1))
    shelf.add(Book(isbn=MANTEL, title="Wolf Hall", author="Hilary Mantel", copies=0))
    return shelf


@pytest.fixture()
def register(store: JsonStore) -> LoanRegister:
    """A loan register over the same store as the catalogue fixture."""
    return LoanRegister(store)
