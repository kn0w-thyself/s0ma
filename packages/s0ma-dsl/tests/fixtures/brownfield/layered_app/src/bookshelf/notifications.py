"""How the library tells members about the books they are holding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from .config import LIBRARY_NAME

if TYPE_CHECKING:
    from datetime import date

    from .models import Loan, Member

REMINDER_WINDOW_DAYS = 3


class Notifier(Protocol):
    """Anything that can put one message in front of one member."""

    def send(self, member: Member, subject: str, body: str) -> None:
        """Deliver the message, however this channel delivers messages."""


@dataclass
class _RecordedMessage:
    """One message a :class:`RecordingNotifier` was asked to send."""

    card_number: str
    subject: str
    body: str


class RecordingNotifier:
    """A notifier that keeps messages in memory instead of sending them.

    What the service runs on until a real channel is configured.
    """

    def __init__(self) -> None:
        self._sent: list[_RecordedMessage] = []

    @property
    def sent(self) -> list[_RecordedMessage]:
        """Every message this notifier has been handed, oldest first."""
        return list(self._sent)

    def send(self, member: Member, subject: str, body: str) -> None:
        """Record the message instead of delivering it anywhere."""
        self._sent.append(_RecordedMessage(member.card_number, subject, body))

    def clear(self) -> None:
        """Forget everything recorded so far."""
        self._sent.clear()


def due_soon_message(loan: Loan, days_left: int) -> tuple[str, str]:
    """The subject and body of the reminder sent before a loan falls due."""
    subject = f"{LIBRARY_NAME}: a book is due back in {days_left} days"
    body = (
        f"ISBN {loan.isbn} is due back on {loan.window.due.isoformat()}. "
        "You can renew it at the counter or on the library's website."
    )
    return subject, body


async def remind_member(
    notifier: Notifier, member: Member, loans: list[Loan], today: date
) -> int:
    """Send one reminder per loan that is nearly due, and count what was sent.

    This is a coroutine because a real channel would wait on the network.
    The in-memory notifier finishes without waiting for anything.
    """
    sent = 0
    for loan in loans:
        days_left = loan.days_left(today)
        if 0 <= days_left <= REMINDER_WINDOW_DAYS:
            subject, body = due_soon_message(loan, days_left)
            notifier.send(member, subject, body)
            sent += 1
    return sent
