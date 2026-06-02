"""Event bus — publish-subscribe event system for decoupling modules."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from quantflow.common.models import (
    EVENT_BAR,
    EVENT_FILL,
    EVENT_ORDER,
    EVENT_RISK,
    EVENT_SIGNAL,
    EVENT_TICK,
)

logger = logging.getLogger(__name__)

__all__ = [
    "EVENT_BAR",
    "EVENT_FILL",
    "EVENT_ORDER",
    "EVENT_RISK",
    "EVENT_SIGNAL",
    "EVENT_TICK",
    "Event",
    "EventBus",
]


class Event:
    """Immutable event object passed through the bus."""

    __slots__ = ("data", "type")

    def __init__(self, type: str, data: Any = None) -> None:
        self.type = type
        self.data = data

    def __repr__(self) -> str:
        return f"Event({self.type!r})"


class EventBus:
    """Publish-subscribe event bus with sync and async handler support.

    Handlers can be sync or async functions. Async handlers are awaited
    when publish_async() is called. Sync handlers work with publish().
    Exceptions in handlers are caught and logged to prevent cascade failures.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[Event], Any]]] = defaultdict(list)
        self._background_tasks: set[asyncio.Task[Any]] = set()

    def subscribe(self, event_type: str, handler: Callable[[Event], Any]) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable[[Event], Any]) -> None:
        """Remove a handler for an event type."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def publish(self, event: Event) -> None:
        """Publish an event to all registered handlers (sync).

        Async handlers are scheduled as tasks but not awaited.
        For awaiting async handlers, use publish_async().
        """
        handlers = self._handlers.get(event.type, [])
        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    task = asyncio.create_task(handler(event))
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)
                else:
                    handler(event)
            except Exception as e:
                logger.error("Event handler error [%s]: %s", event.type, e)

    async def publish_async(self, event: Event) -> None:
        """Publish an event, awaiting both sync and async handlers."""
        handlers = self._handlers.get(event.type, [])
        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error("Event handler error [%s]: %s", event.type, e)

    def clear(self) -> None:
        """Remove all handlers."""
        self._handlers.clear()

    def handler_count(self, event_type: str) -> int:
        """Return number of handlers for an event type."""
        return len(self._handlers.get(event_type, []))
