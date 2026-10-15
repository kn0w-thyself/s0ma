"""The handlers the counter screen calls."""

from __future__ import annotations

from datetime import date

from bookshelf import BookNotFoundError, api

PRATCHETT = "978-0-00-000001-1"


def test_list_titles_says_how_many_copies_are_free(catalog):
    assert [row["available"] for row in api.list_titles(catalog)] == [1, 2, 0]


def test_borrowing_through_the_handler_returns_the_due_date(catalog, register):
    record = api.borrow_title(register, PRATCHETT, "C-1001", date(2024, 3, 1))
    assert record["due"] == "2024-03-22"


def test_an_expected_failure_is_described_plainly():
    described = api.describe_failure(BookNotFoundError("978-0-00-000999-9"))
    assert described["error"] == "BookNotFoundError"
    assert "978-0-00-000999-9" in described["message"]


def test_an_unexpected_failure_keeps_its_detail_to_itself():
    described = api.describe_failure(ValueError("connection string: hunter2"))
    assert "hunter2" not in described["message"]
