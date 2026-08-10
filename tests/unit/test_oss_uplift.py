"""OSS-learned control patterns: pause set, BBO age, ghost positions."""

from __future__ import annotations

import time

import pytest

from quantflow.common.models import Order, OrderSide, OrderStatus, Position
from quantflow.common.pause_reasons import PauseReasonSet
from quantflow.execution.paper_gateway import PaperGateway
from quantflow.reconciliation.ghost_positions import find_ghost_positions


def test_pause_reason_set_multi_source() -> None:
    p = PauseReasonSet()
    assert not p.is_paused
    p.add("data_stale")
    p.add("kill_switch")
    assert p.is_paused
    p.remove("data_stale")
    assert p.is_paused
    assert "kill_switch" in p.reasons
    p.remove("kill_switch")
    assert not p.is_paused
    p.set_manual_stop(True)
    assert p.is_paused
    assert "manual_stop" in p.reasons
    p.set_manual_stop(False)
    assert not p.is_paused


def test_ghost_positions_detect_untracked() -> None:
    tracked = ["BTC/USDT"]
    exchange = [
        Position(symbol="BTC/USDT", quantity=1.0, entry_price=100.0, current_price=100.0),
        Position(symbol="ETH/USDT", quantity=2.0, entry_price=50.0, current_price=50.0),
        Position(symbol="DUST/USDT", quantity=1e-12, entry_price=1.0, current_price=1.0),
    ]
    rep = find_ghost_positions(tracked_symbols=tracked, exchange_positions=exchange)
    assert rep.has_ghosts
    assert any(g["symbol"] == "ETH/USDT" for g in rep.ghosts)
    assert "BTC/USDT" in rep.tracked_with_position
    assert "DUST/USDT" in rep.dust_ignored


def test_ghost_missing_on_exchange() -> None:
    rep = find_ghost_positions(
        tracked_symbols=["BTC/USDT", "SOL/USDT"],
        exchange_positions=[
            Position(symbol="BTC/USDT", quantity=0.5, entry_price=1.0, current_price=1.0),
        ],
    )
    assert "SOL/USDT" in rep.missing_on_exchange
    assert not rep.has_ghosts


@pytest.mark.asyncio
async def test_stale_bbo_rejects_when_age_gate_on() -> None:
    pg = PaperGateway(
        {
            "orderbook_fill_enabled": True,
            "orderbook_fill": {"extra_slippage": 0.0, "bbo_max_age_sec": 0.05},
            "taker_fee": 0.0,
            "slippage": 0.0,
        }
    )
    await pg.connect()
    pg.update_orderbook("BTC/USDT", bid=100.0, ask=100.5)
    time.sleep(0.08)
    order = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="market",
        quantity=1.0,
        price=100.0,
    )
    await pg.send_order(order)
    assert order.status == OrderStatus.REJECTED
    await pg.disconnect()


@pytest.mark.asyncio
async def test_fresh_bbo_fills_with_age_gate() -> None:
    pg = PaperGateway(
        {
            "orderbook_fill_enabled": True,
            "orderbook_fill": {"extra_slippage": 0.0, "bbo_max_age_sec": 5.0},
            "taker_fee": 0.0,
        }
    )
    await pg.connect()
    pg.update_orderbook("BTC/USDT", bid=100.0, ask=100.5)
    order = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="market",
        quantity=1.0,
        price=100.0,
    )
    await pg.send_order(order)
    assert order.status == OrderStatus.FILLED
    assert order.filled_price == pytest.approx(100.5)
    await pg.disconnect()


@pytest.mark.asyncio
async def test_age_gate_off_by_default_even_if_bbo_old() -> None:
    """Default bbo_max_age_sec=0 → no stale reject (W16 baseline)."""
    pg = PaperGateway(
        {
            "orderbook_fill_enabled": True,
            "orderbook_fill": {"extra_slippage": 0.0},
            "taker_fee": 0.0,
        }
    )
    await pg.connect()
    pg.update_orderbook("BTC/USDT", bid=99.0, ask=101.0)
    # even if we sleep, age gate is off
    time.sleep(0.02)
    order = Order(
        order_id="",
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type="market",
        quantity=1.0,
        price=100.0,
    )
    await pg.send_order(order)
    assert order.status == OrderStatus.FILLED
    await pg.disconnect()
