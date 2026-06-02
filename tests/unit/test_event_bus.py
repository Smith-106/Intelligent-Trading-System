"""Unit tests for event bus."""

import asyncio

import pytest

from quantflow.common.event_bus import EVENT_BAR, Event, EventBus


class TestEventBus:
    def test_subscribe_and_publish(self):
        bus = EventBus()
        received = []
        bus.subscribe(EVENT_BAR, lambda e: received.append(e.data))
        bus.publish(Event(EVENT_BAR, {"symbol": "BTC/USDT"}))
        assert len(received) == 1
        assert received[0]["symbol"] == "BTC/USDT"

    def test_unsubscribe(self):
        bus = EventBus()
        received = []

        def handler(e):
            return received.append(1)

        bus.subscribe(EVENT_BAR, handler)
        bus.unsubscribe(EVENT_BAR, handler)
        bus.publish(Event(EVENT_BAR))
        assert len(received) == 0

    def test_multiple_handlers(self):
        bus = EventBus()
        count = [0, 0]
        bus.subscribe(EVENT_BAR, lambda e: count.__setitem__(0, count[0] + 1))
        bus.subscribe(EVENT_BAR, lambda e: count.__setitem__(1, count[1] + 1))
        bus.publish(Event(EVENT_BAR))
        assert count == [1, 1]

    def test_handler_error_does_not_block(self):
        bus = EventBus()
        received = []
        bus.subscribe(EVENT_BAR, lambda e: 1 / 0)  # will raise
        bus.subscribe(EVENT_BAR, lambda e: received.append(1))
        bus.publish(Event(EVENT_BAR))
        assert len(received) == 1  # second handler still runs

    def test_clear(self):
        bus = EventBus()
        bus.subscribe(EVENT_BAR, lambda e: None)
        bus.clear()
        bus.publish(Event(EVENT_BAR))  # no error

    def test_event_repr_and_handler_count(self):
        bus = EventBus()
        event = Event(EVENT_BAR, {"x": 1})
        bus.subscribe(EVENT_BAR, lambda e: None)

        assert repr(event) == "Event('bar')"
        assert bus.handler_count(EVENT_BAR) == 1
        assert bus.handler_count("missing") == 0

    def test_unsubscribe_missing_handler_is_noop(self):
        bus = EventBus()

        def handler(event):
            return None

        bus.unsubscribe(EVENT_BAR, handler)
        assert bus.handler_count(EVENT_BAR) == 0

    @pytest.mark.asyncio
    async def test_publish_async_awaits_sync_and_async_handlers(self):
        bus = EventBus()
        received = []

        async def async_handler(event):
            await asyncio.sleep(0)
            received.append(("async", event.data))

        def sync_handler(event):
            received.append(("sync", event.data))

        bus.subscribe(EVENT_BAR, async_handler)
        bus.subscribe(EVENT_BAR, sync_handler)

        await bus.publish_async(Event(EVENT_BAR, 7))

        assert received == [("async", 7), ("sync", 7)]

    @pytest.mark.asyncio
    async def test_publish_async_logs_errors_and_continues(self):
        bus = EventBus()
        received = []

        async def broken_handler(event):
            raise RuntimeError("boom")

        def sync_handler(event):
            received.append(event.type)

        bus.subscribe(EVENT_BAR, broken_handler)
        bus.subscribe(EVENT_BAR, sync_handler)

        await bus.publish_async(Event(EVENT_BAR))

        assert received == [EVENT_BAR]

    @pytest.mark.asyncio
    async def test_publish_schedules_async_handlers_in_background(self):
        bus = EventBus()
        received = []
        done = asyncio.Event()

        async def async_handler(event):
            await asyncio.sleep(0)
            received.append(event.data)
            done.set()

        bus.subscribe(EVENT_BAR, async_handler)
        bus.publish(Event(EVENT_BAR, "payload"))
        await asyncio.wait_for(done.wait(), timeout=1)

        assert received == ["payload"]
        assert bus.handler_count(EVENT_BAR) == 1
