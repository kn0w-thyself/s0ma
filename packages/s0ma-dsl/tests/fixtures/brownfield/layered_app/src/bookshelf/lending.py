"""Making, renewing and returning loans."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .catalog import Catalog
from .config import DATA_DIR, MAX_LOANS_PER_MEMBER, RENEWAL_LIMIT, loan_length_days
from .errors import (
    BookUnavailableError,
    LoanLimitReachedError,
    LoanNotFoundError,
    RenewalRefusedError,
)
from .models import Loan, LoanWindow
from .storage import JsonStore

LOANS_TABLE = "loans"


class LoanRegister:
    """Every loan the library currently has out."""

    def __init__(self, store: JsonStore | None = None) -> None:
        self._store = store if store is not None else JsonStore(Path(DATA_DIR))

    def loans(self) -> list[Loan]:
        """Every loan on the register, in the order it was written."""
        return [_loan_from_record(record) for record in self._store.read(LOANS_TABLE)]

    def count_for(self, isbn: str) -> int:
        """How many copies of this title are out on loan."""
        return sum(1 for loan in self.loans() if loan.isbn == isbn)

    def loans_for(self, card_number: str) -> list[Loan]:
        """Every loan held by one member."""
        return [loan for loan in self.loans() if loan.card_number == card_number]

    def borrow(self, isbn: str, card_number: str, today: date) -> Loan:
        """Lend a copy of ``isbn`` to ``card_number`` and return the new loan."""
        if len(self.loans_for(card_number)) >= MAX_LOANS_PER_MEMBER:
            raise LoanLimitReachedError(card_number, MAX_LOANS_PER_MEMBER)
        if Catalog(self._store).copies_available(isbn) <= 0:
            raise BookUnavailableError(isbn)
        loan = Loan(
            isbn=isbn, card_number=card_number,
            window=LoanWindow(today, today + timedelta(days=loan_length_days(0))),
        )
        self._save([*self.loans(), loan])
        return loan

    def renew(self, isbn: str, card_number: str, today: date) -> Loan:
        """Extend one loan, for as long as the renewal limit allows."""
        loans = self.loans()
        for position, loan in enumerate(loans):
            if loan.isbn != isbn or loan.card_number != card_number:
                continue
            if loan.renewals >= RENEWAL_LIMIT:
                raise RenewalRefusedError(isbn, RENEWAL_LIMIT)
            renewals = loan.renewals + 1
            days = loan_length_days(renewals)
            loans[position] = Loan(
                isbn=isbn, card_number=card_number, renewals=renewals,
                window=LoanWindow(today, today + timedelta(days=days)),
            )
            self._save(loans)
            return loans[position]
        raise LoanNotFoundError(isbn, card_number)

    def give_back(self, isbn: str, card_number: str) -> None:
        """Take a title back from a member."""
        loans = self.loans()
        kept = [one for one in loans if one.isbn != isbn or one.card_number != card_number]
        if len(kept) == len(loans):
            raise LoanNotFoundError(isbn, card_number)
        self._save(kept)

    def _save(self, loans: list[Loan]) -> None:
        self._store.write(LOANS_TABLE, [_loan_record(loan) for loan in loans])


# The overdue list is read out at the counter every morning, so the day is an
# argument rather than something this function reads off the clock: the same
# register and the same date always give the same list.
def overdue_loans(register: LoanRegister, today: date) -> list[Loan]:
    """Every loan on ``register`` whose due date has gone by."""
    return sorted(
        (loan for loan in register.loans() if loan.is_overdue(today)),
        key=lambda loan: (loan.window.due, loan.isbn),
    )


def _loan_from_record(record: dict[str, Any]) -> Loan:
    """Rebuild a loan from the record shape kept in the store."""
    start = date.fromisoformat(str(record["start"]))
    due = date.fromisoformat(str(record["due"]))
    return Loan(
        isbn=str(record["isbn"]), card_number=str(record["card_number"]),
        window=LoanWindow(start, due), renewals=int(record["renewals"]),
    )


def _loan_record(loan: Loan) -> dict[str, Any]:
    """Flatten a loan into the record shape kept in the store."""
    return {
        "isbn": loan.isbn, "card_number": loan.card_number,
        "start": loan.window.start.isoformat(),
        "due": loan.window.due.isoformat(), "renewals": loan.renewals,
    }
