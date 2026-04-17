from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from uuid import UUID


class TaskEventBus:
    def __init__(self) -> None:
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, task_id: UUID | str, event: str, data: dict[str, Any]) -> None:
        task_key = str(task_id)
        message = {"event": event, "task_id": task_key, "data": data}
        async with self._lock:
            self._history.setdefault(task_key, []).append(message)
            subscribers = list(self._subscribers.get(task_key, []))
        for queue in subscribers:
            await queue.put(message)

    async def get_history(self, task_id: UUID | str) -> list[dict[str, Any]]:
        async with self._lock:
            return list(self._history.get(str(task_id), []))

    @asynccontextmanager
    async def subscribe(self, task_id: UUID | str) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        task_key = str(task_id)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        async with self._lock:
            self._subscribers.setdefault(task_key, []).append(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                subscribers = self._subscribers.get(task_key, [])
                if queue in subscribers:
                    subscribers.remove(queue)
                if not subscribers and task_key in self._subscribers:
                    self._subscribers.pop(task_key, None)


_task_event_bus: TaskEventBus | None = None


def get_task_event_bus() -> TaskEventBus:
    global _task_event_bus
    if _task_event_bus is None:
        _task_event_bus = TaskEventBus()
    return _task_event_bus
