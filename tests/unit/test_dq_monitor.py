"""Unit tests for DataQualityMonitor meta-feed validators (T-s2-04).

Covers validate_funding_rate / validate_open_interest freshness gates:
- fresh snapshot -> valid
- stale funding (age > 2 x settlement interval) -> stale_funding violation
- stale OI (age > 600 s) -> stale_oi violation
- missing/invalid fields -> fail-closed invalid
- violations counted via sink (record_risk_event)
"""

from __future__ import annotations

import time

from quantflow.data.dq_monitor import DataQualityMonitor

EIGHT_HOURS_MS = 8 * 3600 * 1000


class FakeSink:
    def __init__(self) -> None:
        self.risk_events: list[tuple[str, str]] = []

    def record_risk_event(self, event_type: str, severity: str) -> None:
        self.risk_events.append((event_type, severity))


def _monitor(sink=None) -> DataQualityMonitor:
    return DataQualityMonitor(enable_prometheus=False, monitoring_sink=sink)


def _now_ms() -> float:
    return time.time() * 1000.0


class TestValidateFundingRate:
    def test_fresh_snapshot_valid(self):
        mon = _monitor()
        result = mon.validate_funding_rate(
            {
                "symbol": "BTC/USDT",
                "fetched_at_ms": _now_ms() - 1000,  # 1 s old
                "settled_interval_ms": EIGHT_HOURS_MS,
            }
        )
        assert result.valid
        assert result.violations == []

    def test_stale_funding_violation(self):
        """Acceptance: age > 2 x settlement interval -> stale_funding."""
        mon = _monitor()
        result = mon.validate_funding_rate(
            {
                "symbol": "BTC/USDT",
                "fetched_at_ms": _now_ms() - 2 * EIGHT_HOURS_MS - 60_000,
                "settled_interval_ms": EIGHT_HOURS_MS,
            }
        )
        assert not result.valid
        assert any(v["type"] == "stale_funding" for v in result.violations)

    def test_boundary_age_within_two_intervals_valid(self):
        mon = _monitor()
        result = mon.validate_funding_rate(
            {
                "symbol": "BTC/USDT",
                "fetched_at_ms": _now_ms() - (2 * EIGHT_HOURS_MS - 60_000),
                "settled_interval_ms": EIGHT_HOURS_MS,
            }
        )
        assert result.valid

    def test_missing_fields_fail_closed(self):
        mon = _monitor()
        result = mon.validate_funding_rate({"symbol": "BTC/USDT"})
        assert not result.valid
        assert result.violations[0]["type"] == "stale_funding"

    def test_invalid_interval_fail_closed(self):
        mon = _monitor()
        result = mon.validate_funding_rate(
            {"symbol": "BTC/USDT", "fetched_at_ms": _now_ms(), "settled_interval_ms": 0}
        )
        assert not result.valid

    def test_runtime_settlement_interval_drives_threshold(self):
        """Settlement period is runtime-derived (D-lock C3): a 4h-interval
        symbol goes stale after 8h, not 16h."""
        mon = _monitor()
        four_hours_ms = 4 * 3600 * 1000
        result = mon.validate_funding_rate(
            {
                "symbol": "BTC/USDT",
                "fetched_at_ms": _now_ms() - 9 * 3600 * 1000,  # 9h old
                "settled_interval_ms": four_hours_ms,  # 2x = 8h threshold
            }
        )
        assert not result.valid


class TestValidateOpenInterest:
    def test_fresh_oi_valid(self):
        mon = _monitor()
        result = mon.validate_open_interest(
            {"symbol": "BTC/USDT", "fetched_at_ms": _now_ms() - 5000}
        )
        assert result.valid

    def test_stale_oi_violation(self):
        """Acceptance: age > 600 s -> stale_oi."""
        mon = _monitor()
        result = mon.validate_open_interest(
            {"symbol": "BTC/USDT", "fetched_at_ms": _now_ms() - 601_000}
        )
        assert not result.valid
        assert any(v["type"] == "stale_oi" for v in result.violations)

    def test_missing_field_fail_closed(self):
        mon = _monitor()
        result = mon.validate_open_interest({"symbol": "BTC/USDT"})
        assert not result.valid


class TestViolationAlerting:
    def test_violation_records_sink_risk_event(self):
        sink = FakeSink()
        mon = _monitor(sink=sink)
        mon.validate_funding_rate({"symbol": "BTC/USDT"})
        assert ("dq_stale_funding", "warning") in sink.risk_events

    def test_valid_snapshot_no_sink_event(self):
        sink = FakeSink()
        mon = _monitor(sink=sink)
        mon.validate_funding_rate(
            {
                "symbol": "BTC/USDT",
                "fetched_at_ms": _now_ms(),
                "settled_interval_ms": EIGHT_HOURS_MS,
            }
        )
        assert sink.risk_events == []
