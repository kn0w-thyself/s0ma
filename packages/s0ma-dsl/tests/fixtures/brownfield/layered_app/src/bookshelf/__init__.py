"""The Fennel Street Library lending service.

Import what you need from here; how the modules underneath are arranged is
an implementation detail that has changed before and will change again.
"""

from __future__ import annotations

from .catalog import Catalog
from .errors import (
    BookNotFoundError,
    BookshelfError,
    BookUnavailableError,
    CatalogError,
    DuplicateBookError,
    LendingError,
    LoanLimitReachedError,
    LoanNotFoundError,
    RenewalRefusedError,
    StorageCorruptError,
)
from .lending import LoanRegister, overdue_loans
from .models import Availability, Book, Loan, LoanWindow, Member
from .notifications import Notifier, RecordingNotifier
from .storage import JsonStore

__all__ = [
    "Availability", "Book", "BookNotFoundError", "BookUnavailableError",
    "BookshelfError", "Catalog", "CatalogError", "DuplicateBookError",
    "JsonStore", "LendingError", "Loan", "LoanLimitReachedError",
    "LoanNotFoundError", "LoanRegister", "LoanWindow", "Member",
    "Notifier", "RecordingNotifier", "RenewalRefusedError",
    "StorageCorruptError", "overdue_loans",
]
