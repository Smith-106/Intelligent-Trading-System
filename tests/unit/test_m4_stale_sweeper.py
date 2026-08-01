"""Phase 6 integration tests — M4 stale pending sweeper.

Covers PortfolioManager.sweep_stale_pending age-based release, the CRITICAL
log emission, and the reserved_at_ms preservation guarantee of
partial_confirm. All helpers are defined locally in this file (no cross-test
imports). White-box entry injection is used to avoid wall-clock flakiness.
"""

from __future__ import annotations

import logging
import time

import pytest

from quantflow.signal.portfolio import PendingEntry, PortfolioManager

_LOGGER_NAME = "quantflow.signal.portfolio"


def _now_ms() -> int:
    """Wall-clock milliseconds, matching the production reserve timestamp source."""
    return int(time.time() * 1000)


def _fresh_pm() -> PortfolioManager:
    """Create a PortfolioManager with the default initial capital."""
    return PortfolioManager(initial_capital=100000.0)


def _inject(
    pm: PortfolioManager,
    order_id: str,
    *,
    symbol: str,
    notional: float,
    strategy_id: str,
    age_ms: int,
) -> int:
    """Inject a crafted PendingEntry with a controlled reserved_at_ms.

    White-box: the production ``_pending`` dict is a plain dict, so frozen
    PendingEntry instances can be placed directly to avoid real-time waits.
    Returns the reserved_at_ms that was set, for timestamp assertions.
    """
    reserved = _now_ms() - age_ms
    pm._pending[order_id] = PendingEntry(
        symbol=symbol,
        notional=notional,
        strategy_id=strategy_id,
        reserved_at_ms=reserved,
    )
    return reserved


def test_fresh_entry_not_swept_default() -> None:
    # Case 1: a just-reserved entry is well within the 120s default window.
    pm = _fresh_pm()
    pm.reserve("fresh", "BTC/USDT", 100.0, strategy_id="s1")
    released = pm.sweep_stale_pending()  # default max_age_ms=120_000
    assert released == []
    assert "fresh" in pm._pending
    assert pm.total_pending_exposure == pytest.approx(100.0)


def test_old_entry_swept() -> None:
    # Case 2: an entry reserved 200s ago is swept by the 120s threshold.
    pm = _fresh_pm()
    _inject(pm, "old", symbol="BTC/USDT", notional=100.0, strategy_id="s1", age_ms=200_000)
    released = pm.sweep_stale_pending(120_000)
    assert released == ["old"]
    assert "old" not in pm._pending
    assert pm.total_pending_exposure == pytest.approx(0.0)


def test_sweep_max_age_zero_sweeps_past_entry() -> None:
    # Case 3: max_age_ms=0 sweeps any entry whose age is > 0. We inject a small
    # past offset (5ms) so (now - reserved) is deterministically > 0, avoiding
    # same-millisecond boundary flakiness.
    pm = _fresh_pm()
    _inject(pm, "ord1", symbol="BTC/USDT", notional=100.0, strategy_id="s1", age_ms=5)
    released = pm.sweep_stale_pending(max_age_ms=0)
    assert released == ["ord1"]
    assert pm.total_pending_exposure == pytest.approx(0.0)


def test_mixed_old_and_fresh() -> None:
    # Case 4: only the old entry is swept; the fresh one survives.
    pm = _fresh_pm()
    _inject(pm, "old", symbol="BTC/USDT", notional=100.0, strategy_id="s1", age_ms=200_000)
    pm.reserve("fresh", "ETH/USDT", 200.0, strategy_id="s2")
    released = pm.sweep_stale_pending(120_000)
    assert released == ["old"]
    assert "fresh" in pm._pending
    assert pm.pending_for_symbol("ETH/USDT") == pytest.approx(200.0)
    assert pm.total_pending_exposure == pytest.approx(200.0)


def test_returns_correct_released_ids() -> None:
    # Case 5: the returned list contains exactly the stale order_ids.
    pm = _fresh_pm()
    _inject(pm, "a", symbol="BTC/USDT", notional=100.0, strategy_id="s1", age_ms=300_000)
    _inject(pm, "b", symbol="ETH/USDT", notional=200.0, strategy_id="s2", age_ms=250_000)
    _inject(pm, "c", symbol="SOL/USDT", notional=300.0, strategy_id="s3", age_ms=10)
    released = pm.sweep_stale_pending(120_000)
    assert set(released) == {"a", "b"}
    assert "c" in pm._pending
    assert pm.total_pending_exposure == pytest.approx(300.0)


def test_critical_log_emitted_for_swept_entries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Case 6: sweeping a stale entry emits a CRITICAL record naming the oid.
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    pm = _fresh_pm()
    _inject(pm, "old", symbol="BTC/USDT", notional=100.0, strategy_id="s1", age_ms=200_000)
    pm.sweep_stale_pending(120_000)
    critical = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert critical, "expected a CRITICAL log record for the swept entry"
    assert any("oid=old" in r.getMessage() for r in critical)


def test_partial_confirm_preserves_reserved_at_ms_then_swept_by_original_age(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Case 7: partial_confirm must keep the ORIGINAL reserved_at_ms, so a later
    # sweep judges staleness by the original (old) timestamp — proving the
    # timestamp was not reset to "now".
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    pm = _fresh_pm()
    original_ts = _inject(
        pm,
        "o1",
        symbol="BTC/USDT",
        notional=100.0,
        strategy_id="s1",
        age_ms=200_000,
    )
    # Reduce notional via partial confirm; timestamp must be preserved.
    pm.partial_confirm("o1", 40.0)
    remaining = pm._pending.get("o1")
    assert remaining is not None
    assert remaining.reserved_at_ms == original_ts
    assert remaining.notional == pytest.approx(60.0)
    # The original age (~200s) exceeds the 120s threshold. If the timestamp had
    # been reset to now (~0s) this sweep would return [] — the non-empty result
    # proves the original (old) timestamp was retained.
    released = pm.sweep_stale_pending(120_000)
    assert released == ["o1"]
    assert pm.total_pending_exposure == pytest.approx(0.0)
    # Sanity: a CRITICAL record was emitted for this stale sweep.
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)
