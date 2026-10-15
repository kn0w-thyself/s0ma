"""Task service — orchestrates task lifecycle operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from s0ma.decorators import component, internal
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from tests.sample_project.mini_app.models.task import Task


@component(
    name="TaskService",
    kind=ComponentKind.SERVICE,
    layer=Layer.APPLICATION,
    intent="Manages task lifecycle including creation, assignment, and completion",
    dependencies=["Task", "StorageAdapter"],
)
class TaskService:
    """Orchestrates task management operations."""

    def __init__(self) -> None:
        self._tasks: list[Task] = []

    def create_task(self, title: str) -> Task:
        from tests.sample_project.mini_app.models.task import Task

        task = Task(title=title)
        self._tasks.append(task)
        return task

    def get_all_tasks(self) -> list[Task]:
        return list(self._tasks)

    def get_pending_count(self) -> int:
        return _count_by_status(self._tasks, "pending")


@internal(reason="Private helper for filtering tasks by status")
def _count_by_status(tasks: list[Task], status: str) -> int:
    """Count tasks with a given status — internal helper."""
    return sum(1 for t in tasks if t.status == status)
