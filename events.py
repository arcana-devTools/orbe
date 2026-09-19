"""Barramento de eventos simples: tudo que acontece vira log e vai pro painel via WebSocket."""
from __future__ import annotations

import asyncio
import collections
from typing import Awaitable, Callable

from models import LogEvent

Listener = Callable[[LogEvent], Awaitable[None]]


class EventBus:
    def __init__(self, maxlen: int = 500) -> None:
        self.history: collections.deque[LogEvent] = collections.deque(maxlen=maxlen)
        self._listeners: set[Listener] = set()

    def subscribe(self, fn: Listener) -> None:
        self._listeners.add(fn)

    def unsubscribe(self, fn: Listener) -> None:
        self._listeners.discard(fn)

    async def emit(self, level: str, message: str, source: str = "system", task_id: str = "") -> LogEvent:
        ev = LogEvent(level=level, message=message, source=source, task_id=task_id)
        self.history.append(ev)
        for fn in list(self._listeners):
            try:
                await fn(ev)
            except Exception:
                pass
        return ev

    # atalhos
    async def info(self, message: str, source: str = "system", task_id: str = "") -> None:
        await self.emit("info", message, source, task_id)

    async def step(self, message: str, source: str = "system", task_id: str = "") -> None:
        await self.emit("step", message, source, task_id)

    async def ok(self, message: str, source: str = "system", task_id: str = "") -> None:
        await self.emit("ok", message, source, task_id)

    async def warn(self, message: str, source: str = "system", task_id: str = "") -> None:
        await self.emit("warn", message, source, task_id)

    async def error(self, message: str, source: str = "system", task_id: str = "") -> None:
        await self.emit("error", message, source, task_id)


BUS = EventBus()
