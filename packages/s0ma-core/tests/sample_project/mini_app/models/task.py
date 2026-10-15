"""Task model — a registered data model component."""

from __future__ import annotations

from dataclasses import dataclass

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer


@component(
    name="Task",
    kind=ComponentKind.MODEL,
    layer=Layer.DOMAIN,
    intent="Represents a task entity with title, status, and assignment tracking",
)
@dataclass
class Task:
    """A task in the mini task management application."""

    title: str
    status: str = "pending"
    assignee: str | None = None

    def complete(self) -> None:
        self.status = "completed"

    def assign(self, user: str) -> None:
        self.assignee = user
        self.status = "assigned"
