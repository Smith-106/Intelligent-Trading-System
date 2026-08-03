"""Unit tests for quantflow.execution.exchange_health (T-s1-04).

Scenarios (plan test_plan):
- sustained API failures -> circuit trips (fail-closed)
- 6 failures / 4 successes within 60s window -> circuit_open()=True
- consecutive 50011 rate-limit streak -> trip
- hysteresis recovery: cooldown + 3 consecutive successes -> closed
- failure during half-open re-anchors cooldown
- trip publishes EVENT_RISK emergency + critical alert
- snapshot() redaction-safe status
"""

from __future__ import annotations

import pytest

from quantflow.common.event_bus import EVENT_RISK
from quantflow.execution.exchange_health import (
    RECOVERY_SUCCESS_STREAK,
    ExchangeHealthMonitor,
)


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakeBus:
    def __init__(self) -> None:
        self.events: list = []

    def publish(self, event) -> None:
        self.events.append(event)


class FakeSink:
    def __init__(self) -> None:
        self.risk_events: list[tuple[str, str]] = []
        self.alerts: list[tuple[str, str]] = []

    def record_risk_event(self, event_type: str, severity: str) -> None:
        self.risk_events.append((event_type, severity))

    async def send_alert(self, message, level="warning", extra=None):
        self.alerts.append((message, level))
        return {}


def _make(clock=None, bus=None, sink=None, **kwargs) -> ExchangeHealthMonitor:
    return ExchangeHealthMonitor(
        window_seconds=kwargs.get("window_seconds", 60.0),
        error_rate_threshold=kwargs.get("error_rate_threshold", 0.5),
        rate_limit_streak_threshold=kwargs.get("rate_limit_streak_threshold", 3),
        cooldown_seconds=kwargs.get("cooldown_seconds", 300.0),
        monitoring_sink=sink,
        event_bus=bus,
        clock=clock,
    )


class TestTripConditions:
    def test_six_failures_four_successes_opens_circuit(self):
        """Acceptance: 60s window, 6 failures / 4 successes -> open."""
        clock = FakeClock()
        mon = _make(clock=clock)
        for i in range(6):
            mon.record_api_error(code="test")
            clock.advance(1)
            if i < 4:
                mon.record_success()
                clock.advance(1)
        assert mon.circuit_open() is True

    def test_sliding_window_error_rate_trips(self):
        clock = FakeClock()
        mon = _make(clock=clock)
        # 3 successes then 4 failures -> 4/7 = 0.57 > 0.5 -> trip
        for _ in range(3):
            mon.record_success()
            clock.advance(1)
        for _ in range(4):
            mon.record_api_error()
            clock.advance(1)
        assert mon.circuit_open() is True

    def test_below_threshold_stays_closed(self):
        clock = FakeClock()
        mon = _make(clock=clock)
        # 8 successes, 2 failures interleaved -> rate never > 0.5 at a
        # failure point with these interleavings: S S S F S S S F S S
        seq = ["S", "S", "S", "F", "S", "S", "S", "F", "S", "S"]
        for op in seq:
            if op == "S":
                mon.record_success()
            else:
                mon.record_api_error()
            clock.advance(1)
        assert mon.circuit_open() is False

    def test_rate_limit_streak_trips_regardless_of_error_rate(self):
        clock = FakeClock()
        mon = _make(clock=clock, rate_limit_streak_threshold=3)
        # Many successes dilute the error rate, but 3 straight 50011s trip.
        for _ in range(10):
            mon.record_success()
            clock.advance(1)
        for _ in range(3):
            mon.record_rate_limited()
            clock.advance(1)
        assert mon.circuit_open() is True

    def test_rate_limit_streak_resets_on_success(self):
        clock = FakeClock()
        mon = _make(clock=clock, rate_limit_streak_threshold=3)
        # Alternating success/rate-limit keeps the window error rate at
        # exactly 0.5 (never > threshold) AND breaks the streak each time —
        # so neither trip condition fires.
        for _ in range(4):
            mon.record_success()
            clock.advance(1)
            mon.record_rate_limited()
            clock.advance(1)
        assert mon.circuit_open() is False

    def test_window_expiry_dilutes_old_failures(self):
        clock = FakeClock()
        mon = _make(clock=clock, window_seconds=60.0, error_rate_threshold=0.5)
        # Success-heavy traffic with two failures (rate stays <= 0.5 at each
        # failure point), then the window slides past all of it.
        mon.record_success()
        mon.record_api_error()
        mon.record_success()
        mon.record_api_error()
        clock.advance(61)
        for _ in range(4):
            mon.record_success()
            clock.advance(1)
        assert mon.circuit_open() is False
        snap = mon.snapshot()
        assert snap["window_errors"] == 0


class TestHysteresisRecovery:
    def _tripped(self, clock: FakeClock, cooldown: float = 300.0):
        mon = _make(clock=clock, cooldown_seconds=cooldown)
        for _ in range(4):
            mon.record_api_error()
            clock.advance(1)
        assert mon.circuit_open() is True
        return mon

    def test_cooldown_not_elapsed_stays_open_despite_successes(self):
        clock = FakeClock()
        mon = self._tripped(clock)
        for _ in range(5):
            mon.record_success()
            clock.advance(1)
        assert mon.circuit_open() is True

    def test_cooldown_plus_three_successes_closes(self):
        """Acceptance: cooldown + 3 consecutive successes -> closed."""
        clock = FakeClock()
        mon = self._tripped(clock)
        clock.advance(301)  # past cooldown
        for i in range(RECOVERY_SUCCESS_STREAK - 1):
            mon.record_success()
            assert mon.circuit_open() is True, f"closed early at success {i + 1}"
        mon.record_success()
        assert mon.circuit_open() is False

    def test_failure_during_half_open_reanchors_cooldown(self):
        clock = FakeClock()
        mon = self._tripped(clock)
        clock.advance(301)
        mon.record_success()
        mon.record_success()
        mon.record_api_error()  # resets recovery + cooldown
        clock.advance(200)  # still within the re-anchored cooldown
        mon.record_success()
        mon.record_success()
        mon.record_success()
        assert mon.circuit_open() is True
        clock.advance(301)
        for _ in range(RECOVERY_SUCCESS_STREAK):
            mon.record_success()
        assert mon.circuit_open() is False

    def test_ws_disconnect_feeds_breaker_like_api_error(self):
        clock = FakeClock()
        mon = _make(clock=clock)
        for _ in range(4):
            mon.record_ws_disconnect()
            clock.advance(1)
        assert mon.circuit_open() is True


class TestTripSideEffects:
    @pytest.mark.asyncio
    async def test_trip_publishes_emergency_risk_event(self):
        clock = FakeClock()
        bus = FakeBus()
        sink = FakeSink()
        mon = _make(clock=clock, bus=bus, sink=sink)
        for _ in range(4):
            mon.record_api_error()
        assert mon.circuit_open() is True
        assert len(bus.events) == 1
        ev = bus.events[0]
        assert ev.type == EVENT_RISK
        assert ev.data["severity"] == "emergency"
        assert ev.data["type"] == "exchange_circuit_open"
        assert ("exchange_circuit_open", "emergency") in sink.risk_events

    def test_trip_without_bus_or_sink_is_safe(self):
        clock = FakeClock()
        mon = _make(clock=clock)
        for _ in range(4):
            mon.record_api_error()
        assert mon.circuit_open() is True

    def test_no_duplicate_trip_events(self):
        clock = FakeClock()
        bus = FakeBus()
        mon = _make(clock=clock, bus=bus)
        for _ in range(6):
            mon.record_api_error()
            clock.advance(1)
        assert len(bus.events) == 1  # one transition, not one per failure


class TestSnapshot:
    def test_snapshot_fields(self):
        clock = FakeClock()
        mon = _make(clock=clock)
        mon.record_success()
        mon.record_api_error()
        clock.advance(1)
        snap = mon.snapshot()
        assert snap["circuit_open"] is False
        assert snap["window_samples"] == 2
        assert snap["window_errors"] == 1
        assert snap["error_rate"] == pytest.approx(0.5)
        assert snap["rate_limit_streak"] == 0
        assert snap["cooldown_remaining"] == 0.0

    def test_snapshot_while_open_reports_cooldown_remaining(self):
        clock = FakeClock()
        mon = _make(clock=clock, cooldown_seconds=300.0)
        for _ in range(4):
            mon.record_api_error()
        clock.advance(100)
        snap = mon.snapshot()
        assert snap["circuit_open"] is True
        assert snap["cooldown_remaining"] == pytest.approx(200.0)
