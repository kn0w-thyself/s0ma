"""Borrowing, renewing and giving books back."""

from __future__ import annotations

from datetime import date

import pytest
from bookshelf import (
    BookUnavailableError,
    LoanNotFoundError,
    RenewalRefusedError,
    overdue_loans,
)

PRATCHETT = "978-0-00-000001-1"
CLARKE = "978-0-00-000002-8"
BORROWED_ON = date(2024, 3, 1)


def test_borrowing_takes_a_copy_off_the_shelf(catalog, register):
    register.borrow(CLARKE, "C-1001", BORROWED_ON)
    assert catalog.copies_available(CLARKE) == 0


def test_the_last_copy_cannot_be_lent_twice(catalog, register):
    register.borrow(CLARKE, "C-1001", BORROWED_ON)
    with pytest.raises(BookUnavailableError):
        register.borrow(CLARKE, "C-1002", BORROWED_ON)


def test_a_loan_can_be_renewed_up_to_the_limit(catalog, register):
    register.borrow(PRATCHETT, "C-1001", BORROWED_ON)
    register.renew(PRATCHETT, "C-1001", BORROWED_ON)
    register.renew(PRATCHETT, "C-1001", BORROWED_ON)
    with pytest.raises(RenewalRefusedError):
        register.renew(PRATCHETT, "C-1001", BORROWED_ON)


def test_giving_back_a_book_nobody_borrowed_is_refused(register):
    with pytest.raises(LoanNotFoundError):
        register.give_back(PRATCHETT, "C-1001")


def test_overdue_loans_are_listed_once_the_due_date_has_passed(catalog, register):
    register.borrow(PRATCHETT, "C-1001", BORROWED_ON)
    assert [loan.isbn for loan in overdue_loans(register, date(2024, 5, 1))] == [PRATCHETT]
