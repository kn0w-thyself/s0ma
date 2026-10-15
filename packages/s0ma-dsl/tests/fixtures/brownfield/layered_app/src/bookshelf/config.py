"""Settings for the lending service: no other module reads the environment."""

from __future__ import annotations

import os

DEFAULT_LOAN_DAYS = 21
MAX_LOANS_PER_MEMBER = 5
RENEWAL_LIMIT = 2
LIBRARY_NAME = "Fennel Street Library"

# The data directory is the one setting that really does change between one
# deployment and the next, so it is the one setting read from the environment.
DATA_DIR = os.environ.get("BOOKSHELF_DATA_DIR", "var/bookshelf")


def loan_length_days(renewals: int) -> int:
    """How long a loan runs, given how often it has already been renewed.

    Renewed loans are shorter, so a title in demand comes back sooner.
    """
    if renewals <= 0:
        return DEFAULT_LOAN_DAYS
    return max(7, DEFAULT_LOAN_DAYS - 7 * renewals)
