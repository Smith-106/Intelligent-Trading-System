"""Phase 6 integration tests — M4 pending exposure ledger lifecycle.

Covers PortfolioManager.reserve / confirm / partial_confirm / release /
release_all and the read-only snapshots (pending_for_symbol,
total_pending_exposure, pending_view, portfolio). All helpers are defined
locally in this file (no cross-test imports).
"""

from __future__ import annotations

import pytest

from quantflow.common.models import Portfolio
from quantflow.signal.portfolio import PortfolioManager

_NOTIONAL = 100.0


def _fresh_pm() -> PortfolioManager:
    """Create a PortfolioManager with the default initial capital."""
    return PortfolioManager(initial_capital=100000.0)


def test_reserve_populates_view_and_exposure() -> None:
    # Case 1: reserve freezes notional across all read paths.
    pm = _fresh_pm()
    pm.reserve("o1", "BTC/USDT", _NOTIONAL, strategy_id="trend")
    view = pm.pending_view()
    assert view.total == pytest.approx(_NOTIONAL)
    assert view.by_symbol["BTC/USDT"] == pytest.approx(_NOTIONAL)
    assert view.by_strategy["trend"] == pytest.approx(_NOTIONAL)
    assert pm.total_pending_exposure == pytest.approx(_NOTIONAL)
    assert pm.portfolio.pending_exposure == pytest.approx(_NOTIONAL)


def test_confirm_removes_entry() -> None:
    # Case 2: confirm pops the shadow on full fill.
    pm = _fresh_pm()
    pm.reserve("o1", "BTC/USDT", _NOTIONAL, strategy_id="trend")
    pm.confirm("o1")
    assert pm.total_pending_exposure == pytest.approx(0.0)
    assert pm.pending_view().total == pytest.approx(0.0)


def test_partial_confirm_cumulative_semantics() -> None:
    # Case 3: cumulative notional semantics + overflow clamp.
    pm = _fresh_pm()
    pm.reserve("o1", "BTC/USDT", 100.0, strategy_id="trend")
    pm.partial_confirm("o1", 40.0)
    assert pm.pending_for_symbol("BTC/USDT") == pytest.approx(60.0)
    assert pm.total_pending_exposure == pytest.approx(60.0)
    # Cumulative reaches full notional -> removed.
    pm.partial_confirm("o1", 100.0)
    assert pm.total_pending_exposure == pytest.approx(0.0)

    # Cumulative exceeds notional -> removed (no negative remaining).
    pm.reserve("o2", "BTC/USDT", 100.0, strategy_id="trend")
    pm.partial_confirm("o2", 150.0)
    assert pm.total_pending_exposure == pytest.approx(0.0)


def test_partial_confirm_intermediate_reaches_full() -> None:
    # Case 4: two cumulative steps summing to full -> removed.
    pm = _fresh_pm()
    pm.reserve("o1", "BTC/USDT", 100.0, strategy_id="trend")
    pm.partial_confirm("o1", 40.0)
    pm.partial_confirm("o1", 60.0)  # cumulative reaches full -> removed
    assert pm.total_pending_exposure == pytest.approx(0.0)
    assert pm.pending_for_symbol("BTC/USDT") == pytest.approx(0.0)


def test_release_and_absent_release_safe() -> None:
    # Case 5: release frees notional; absent id is a no-op.
    pm = _fresh_pm()
    pm.reserve("o1", "BTC/USDT", _NOTIONAL, strategy_id="trend")
    pm.release("o1")
    assert pm.total_pending_exposure == pytest.approx(0.0)
    # Release on absent id must not raise and leaves total unchanged.
    pm.release("does-not-exist")
    assert pm.total_pending_exposure == pytest.approx(0.0)


def test_reserve_overwrites_same_order_id() -> None:
    # Case 6: re-reserve same order_id overwrites (idempotent retry path).
    pm = _fresh_pm()
    pm.reserve("o1", "BTC/USDT", 100.0, strategy_id="trend")
    pm.reserve("o1", "BTC/USDT", 200.0, strategy_id="trend")
    assert len(pm._pending) == 1
    assert pm.pending_for_symbol("BTC/USDT") == pytest.approx(200.0)
    assert pm.total_pending_exposure == pytest.approx(200.0)


def test_release_all_returns_count_and_clears() -> None:
    # Case 7: release_all clears everything and returns the count.
    pm = _fresh_pm()
    pm.reserve("o1", "BTC/USDT", 100.0, strategy_id="trend")
    pm.reserve("o2", "ETH/USDT", 200.0, strategy_id="mean")
    pm.reserve("o3", "SOL/USDT", 300.0, strategy_id="trend")
    assert pm.release_all() == 3
    assert pm.total_pending_exposure == pytest.approx(0.0)
    # On an empty ledger release_all returns 0.
    assert pm.release_all() == 0


def test_pending_for_symbol_sums_across_orders() -> None:
    # Case 8: per-symbol aggregation across multiple order_ids; symbols independent.
    pm = _fresh_pm()
    pm.reserve("o1", "BTC/USDT", 100.0, strategy_id="trend")
    pm.reserve("o2", "BTC/USDT", 50.0, strategy_id="mean")
    pm.reserve("o3", "ETH/USDT", 200.0, strategy_id="trend")
    assert pm.pending_for_symbol("BTC/USDT") == pytest.approx(150.0)
    assert pm.pending_for_symbol("ETH/USDT") == pytest.approx(200.0)
    assert pm.pending_for_symbol("SOL/USDT") == pytest.approx(0.0)


def test_pending_view_by_strategy_aggregates() -> None:
    # Case 9: by_strategy aggregates across order_ids sharing a strategy_id.
    pm = _fresh_pm()
    pm.reserve("o1", "BTC/USDT", 100.0, strategy_id="trend")
    pm.reserve("o2", "ETH/USDT", 200.0, strategy_id="trend")
    pm.reserve("o3", "SOL/USDT", 300.0, strategy_id="mean")
    view = pm.pending_view()
    assert view.by_strategy["trend"] == pytest.approx(300.0)
    assert view.by_strategy["mean"] == pytest.approx(300.0)
    assert view.total == pytest.approx(600.0)
    assert view.by_symbol["BTC/USDT"] == pytest.approx(100.0)
    assert view.by_symbol["ETH/USDT"] == pytest.approx(200.0)
    assert view.by_symbol["SOL/USDT"] == pytest.approx(300.0)


def test_portfolio_property_fresh_snapshot_each_call() -> None:
    # Case 10: portfolio rebuilds each call; earlier snapshot unaffected by later
    # ledger mutations.
    pm = _fresh_pm()
    pm.reserve("o1", "BTC/USDT", 100.0, strategy_id="trend")
    snap1 = pm.portfolio
    assert isinstance(snap1, Portfolio)
    assert snap1.pending_exposure == pytest.approx(100.0)
    # Mutate the ledger and re-fetch — the new snapshot reflects the change.
    pm.reserve("o2", "ETH/USDT", 250.0, strategy_id="mean")
    snap2 = pm.portfolio
    assert snap2.pending_exposure == pytest.approx(350.0)
    # The earlier snapshot is a distinct object and stays unchanged.
    assert snap1.pending_exposure == pytest.approx(100.0)
