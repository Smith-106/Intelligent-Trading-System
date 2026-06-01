"""Unit tests for event bus."""

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
