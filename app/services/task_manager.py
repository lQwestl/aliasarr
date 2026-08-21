"""Менеджер фоновых задач и операций.
Отслеживает активные и недавние процессы (поиск релизов, импорт файлов, проверка индексаторов, бэкапы)
и передаёт их статус в интерактивный виджет интерфейса.
"""

from __future__ import annotations

import collections
from contextlib import asynccontextmanager, contextmanager
import datetime as dt
import logging
import uuid
from typing import Any

logger = logging.getLogger("aliasarr.tasks")


class Task:
    def __init__(
        self,
        task_id: str,
        name: str,
        title: str,
        message: str = "",
        progress: float | None = None,
        show_id: int | None = None,
        total_items: int | None = None,
        current_item: int | None = None,
    ) -> None:
        self.id = task_id
        self.name = name
        self.title = title
        self.message = message
        self.progress = progress
        self.show_id = show_id
        self.total_items = total_items
        self.current_item = current_item
        self.status = "running"
        self.started_at = dt.datetime.utcnow()
        self.ended_at: dt.datetime | None = None
        self.error: str | None = None

    def update(
        self,
        message: str | None = None,
        progress: float | None = None,
        current_item: int | None = None,
        total_items: int | None = None,
        show_id: int | None = None,
    ) -> None:
        if message is not None:
            self.message = message
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))
        if current_item is not None:
            self.current_item = current_item
        if total_items is not None:
            self.total_items = total_items
        if show_id is not None:
            self.show_id = show_id

    def complete(self, message: str | None = None) -> None:
        self.status = "completed"
        self.ended_at = dt.datetime.utcnow()
        if message is not None:
            self.message = message
        self.progress = 1.0

    def fail(self, error: str | None = None, message: str | None = None) -> None:
        self.status = "failed"
        self.ended_at = dt.datetime.utcnow()
        if error is not None:
            self.error = str(error)
        if message is not None:
            self.message = message
        elif error is not None:
            self.message = f"Ошибка: {error}"

    def to_dict(self) -> dict[str, Any]:
        now = self.ended_at or dt.datetime.utcnow()
        duration = (now - self.started_at).total_seconds()
        pct = round(self.progress * 100, 1) if self.progress is not None else None
        return {
            "id": self.id,
            "name": self.name,
            "title": self.title,
            "message": self.message,
            "progress": self.progress,
            "percentage": pct,
            "show_id": self.show_id,
            "total_items": self.total_items,
            "current_item": self.current_item,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": round(max(0.1, duration), 1),
            "error": self.error,
        }


class TaskManager:
    def __init__(self, history_limit: int = 30) -> None:
        self._running: dict[str, Task] = {}
        self._history: collections.deque[Task] = collections.deque(maxlen=history_limit)

    def start_task(
        self,
        name: str,
        title: str,
        message: str = "",
        progress: float | None = None,
        show_id: int | None = None,
        total_items: int | None = None,
        current_item: int | None = None,
    ) -> Task:
        task_id = str(uuid.uuid4())[:8]
        task = Task(
            task_id=task_id,
            name=name,
            title=title,
            message=message,
            progress=progress,
            show_id=show_id,
            total_items=total_items,
            current_item=current_item,
        )
        self._running[task_id] = task
        logger.info("Запущена задача [%s] %s: %s", task.id, task.title, task.message)
        return task

    def update_task(
        self,
        task_id: str,
        message: str | None = None,
        progress: float | None = None,
        current_item: int | None = None,
        total_items: int | None = None,
        show_id: int | None = None,
    ) -> None:
        task = self._running.get(task_id)
        if task:
            task.update(
                message=message,
                progress=progress,
                current_item=current_item,
                total_items=total_items,
                show_id=show_id,
            )

    def finish_task(self, task_id: str, message: str | None = None) -> None:
        task = self._running.pop(task_id, None)
        if task:
            task.complete(message=message)
            self._history.appendleft(task)
            logger.info("Завершена задача [%s] %s: %s", task.id, task.title, task.message)

    def fail_task(self, task_id: str, error: str | None = None, message: str | None = None) -> None:
        task = self._running.pop(task_id, None)
        if task:
            task.fail(error=error, message=message)
            self._history.appendleft(task)
            logger.warning("Ошибка в задаче [%s] %s: %s", task.id, task.title, task.message)

    @asynccontextmanager
    async def track(
        self,
        name: str,
        title: str,
        message: str = "",
        progress: float | None = None,
        show_id: int | None = None,
        total_items: int | None = None,
        current_item: int | None = None,
    ):
        task = self.start_task(
            name=name,
            title=title,
            message=message,
            progress=progress,
            show_id=show_id,
            total_items=total_items,
            current_item=current_item,
        )
        try:
            yield task
            if task.id in self._running:
                self.finish_task(task.id)
        except Exception as exc:
            if task.id in self._running:
                self.fail_task(task.id, error=str(exc))
            raise exc

    @contextmanager
    def track_sync(
        self,
        name: str,
        title: str,
        message: str = "",
        progress: float | None = None,
        show_id: int | None = None,
        total_items: int | None = None,
        current_item: int | None = None,
    ):
        task = self.start_task(
            name=name,
            title=title,
            message=message,
            progress=progress,
            show_id=show_id,
            total_items=total_items,
            current_item=current_item,
        )
        try:
            yield task
            if task.id in self._running:
                self.finish_task(task.id)
        except Exception as exc:
            if task.id in self._running:
                self.fail_task(task.id, error=str(exc))
            raise exc

    def get_status(self) -> dict[str, Any]:
        running_list = [t.to_dict() for t in self._running.values()]
        recent_list = [t.to_dict() for t in list(self._history)[:15]]
        return {
            "running": running_list,
            "recent": recent_list,
            "running_count": len(running_list),
        }

    def clear_history(self) -> None:
        self._history.clear()


# Глобальный синглтон менеджера задач
task_manager = TaskManager()