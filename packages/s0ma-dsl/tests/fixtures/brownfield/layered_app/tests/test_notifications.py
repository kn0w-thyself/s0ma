"""Reminders sent to members about books that are nearly due."""

from __future__ import annotations

import asyncio
from datetime import date

from bookshelf import Member, RecordingNotifier
from bookshelf.notifications import remind_member

PRATCHETT = "978-0-00-000001-1"
MEMBER = Member(card_number="C-1001", name="Ada Okonjo", email="ada@example.invalid")


def test_a_reminder_goes_out_when_a_loan_is_nearly_due(catalog, register):
    register.borrow(PRATCHETT, "C-1001", date(2024, 3, 1))
    notifier = RecordingNotifier()
    sent = asyncio.run(remind_member(notifier, MEMBER, register.loans(), date(2024, 3, 20)))
    assert sent == 1
    assert "due back in 2 days" in notifier.sent[0].subject


def test_nothing_goes_out_while_a_loan_still_has_weeks_to_run(catalog, register):
    register.borrow(PRATCHETT, "C-1001", date(2024, 3, 1))
    notifier = RecordingNotifier()
    sent = asyncio.run(remind_member(notifier, MEMBER, register.loans(), date(2024, 3, 2)))
    assert sent == 0
    assert notifier.sent == []
