"""Coverage completion for quantflow/strategy/research/paper_replay.py.

Targets the remaining uncovered lines/branches: bars_per_year fallback,
RecordingSink.send_alert, build_multi_symbol_session validation/bypass paths,
replay_multi (gate wrapping, error guards, shared-book loop), replay custom
gates + bar_hook, _DirectionGateWrapper closed gate / delegation,
_max_drawdown zero-peak, _sharpe degenerate curves, aggregate risk reasons.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pandas as pd
import pytest

from quantflow.common.config import AppConfig
from quantflow.common.models import Bar
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.research.paper_replay import (
    GATE_BUILDERS,
    RecordingSink,
    _DirectionGateWrapper,
    _max_drawdown,
    _sharpe,
    aggregate,
    bars_per_year,
    build_multi_symbol_session,
    build_session,
    nested_htf_for,
    replay,
    replay_multi,
)

SYMBOL = "BTC/USDT"
BASE_TS = 1_780_000_000_000


def _synthetic_bars(n: int = 400, start_price: float = 60_000.0) -> pd.DataFrame:
    """High-volatility sawtooth that reliably triggers mean_reversion."""
    rows = []
    price = start_price
    for i in range(n):
        phase = (i // 12) % 2
        if phase == 0:
            price *= 0.985
        else:
            price *= 1.02
        volume = 100.0 * (3.0 if i % 12 < 2 else 1.0)
        rows.append(
            {
                "timestamp": BASE_TS + i * 3_600_000,
                "open": price,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": price,
                "volume": volume,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# trivial helpers / sink
# ---------------------------------------------------------------------------


def test_bars_per_year_unknown_timeframe_falls_back() -> None:
    assert bars_per_year("3h") == float(24 * 365)  # not in _TF_MINUTES
    assert bars_per_year("1m") == float(365 * 24 * 60)


def test_nested_htf_lookup() -> None:
    assert nested_htf_for("5m") == "1h"
    assert nested_htf_for("bogus") == "4h"


@pytest.mark.asyncio
async def test_recording_sink_send_alert_records() -> None:
    sink = RecordingSink()
    out = await sink.send_alert("hello", level="info", extra={"k": 1})
    assert out == {}
    assert sink.alerts == [{"message": "hello", "level": "info", "extra": {"k": 1}}]
    # extra=None default path
    await sink.send_alert("bare")
    assert sink.alerts[-1]["extra"] == {}


# ---------------------------------------------------------------------------
# build_multi_symbol_session guards
# ---------------------------------------------------------------------------


def test_build_multi_symbol_session_empty_symbols_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        build_multi_symbol_session("mean_reversion", [])


def test_build_multi_symbol_session_no_bypass_with_overrides() -> None:
    session = build_multi_symbol_session(
        "mean_reversion",
        ["BTC/USDT", "ETH/USDT"],
        research_risk_bypass=False,
        max_position_pct=0.1,
        max_positions=3,
    )
    assert len(session._instances) == 2
    assert session._portfolio is not None
    assert session._symbols == ["BTC/USDT", "ETH/USDT"]


def test_build_multi_symbol_session_symbol_level_rp() -> None:
    """Cover the shared-book symbol-level RP seeding block."""
    cfg = AppConfig()
    cfg.risk.portfolio_optimization.enabled = True
    cfg.risk.portfolio_optimization.level = "symbol"
    session = build_multi_symbol_session(
        "mean_reversion",
        ["BTC/USDT", "ETH/USDT"],
        config=cfg,
    )
    assert session._instances


# ---------------------------------------------------------------------------
# replay_multi
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_multi_produces_curve_and_fills() -> None:
    session = build_multi_symbol_session("mean_reversion", ["BTC/USDT", "ETH/USDT"])
    bars = {
        "BTC/USDT": _synthetic_bars(400),
        "ETH/USDT": _synthetic_bars(400, start_price=3000.0),
    }
    fills: list[dict] = []
    risk_events: list[dict] = []
    curve = await replay_multi(session, bars, fills, risk_events)
    assert len(curve) == 400
    assert curve[0]["equity"] > 0
    assert fills, "multi-symbol replay produced no fills"


@pytest.mark.asyncio
async def test_replay_multi_default_event_lists() -> None:
    session = build_multi_symbol_session("mean_reversion", ["BTC/USDT", "ETH/USDT"])
    bars = {
        "BTC/USDT": _synthetic_bars(60),
        "ETH/USDT": _synthetic_bars(60, start_price=3000.0),
    }
    curve = await replay_multi(session, bars)  # fills/risk_events default None
    assert len(curve) == 60


@pytest.mark.asyncio
async def test_replay_multi_empty_bars_raises() -> None:
    session = build_multi_symbol_session("mean_reversion", ["BTC/USDT"])
    with pytest.raises(ValueError, match="empty"):
        await replay_multi(session, {})


@pytest.mark.asyncio
async def test_replay_multi_unknown_gate_raises() -> None:
    session = build_multi_symbol_session("mean_reversion", ["BTC/USDT", "ETH/USDT"])
    bars = {"BTC/USDT": _synthetic_bars(60), "ETH/USDT": _synthetic_bars(60)}
    with pytest.raises(ValueError, match="Unknown gate"):
        await replay_multi(session, bars, direction_gate="bogus")


@pytest.mark.asyncio
async def test_replay_multi_direction_gate_str_and_bool() -> None:
    session = build_multi_symbol_session("mean_reversion", ["BTC/USDT", "ETH/USDT"])
    bars = {"BTC/USDT": _synthetic_bars(120), "ETH/USDT": _synthetic_bars(120)}
    curve = await replay_multi(session, bars, direction_gate="ema", entry_tf="1h")
    assert len(curve) == 120
    # bool gate -> sma
    session2 = build_multi_symbol_session("mean_reversion", ["BTC/USDT", "ETH/USDT"])
    curve2 = await replay_multi(session2, bars, direction_gate=True)
    assert len(curve2) == 120


# ---------------------------------------------------------------------------
# replay single-symbol custom paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_direction_gate_custom_sma_period() -> None:
    session = build_session("mean_reversion")
    curve = await replay(
        session, _synthetic_bars(300), SYMBOL, direction_gate=True, gate_sma_period=50
    )
    assert len(curve) == 300


@pytest.mark.asyncio
async def test_replay_direction_gate_named_builder() -> None:
    session = build_session("mean_reversion")
    curve = await replay(session, _synthetic_bars(120), SYMBOL, direction_gate="nested")
    assert len(curve) == 120
    assert set(GATE_BUILDERS) == {"sma", "ema", "slope", "dual", "nested"}


@pytest.mark.asyncio
async def test_replay_unknown_gate_raises() -> None:
    session = build_session("mean_reversion")
    with pytest.raises(ValueError, match="Unknown gate"):
        await replay(session, _synthetic_bars(60), SYMBOL, direction_gate="zzz")


@pytest.mark.asyncio
async def test_replay_bar_hook_called_per_bar() -> None:
    session = build_session("mean_reversion")
    seen: list[tuple] = []
    curve = await replay(
        session,
        _synthetic_bars(50),
        SYMBOL,
        bar_hook=lambda s, row: seen.append((s, row)),
    )
    assert len(curve) == 50
    assert len(seen) == 50


# ---------------------------------------------------------------------------
# _DirectionGateWrapper
# ---------------------------------------------------------------------------


def test_direction_gate_wrapper_closed_gate_suppresses() -> None:
    inner = MagicMock()
    inner.name = "mock"
    inner.required_regime = "any"
    allow = pd.Series([False, True, False])
    wrapper = _DirectionGateWrapper(inner, allow)
    ctx = StrategyContext()
    bar = Bar(
        symbol=SYMBOL, timestamp=1, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0
    )
    wrapper.on_init(ctx)
    wrapper.on_bar(ctx, bar)  # gate closed -> suppressed
    assert inner.on_bar.call_count == 0
    wrapper.on_bar(ctx, bar)  # gate open -> delegated
    assert inner.on_bar.call_count == 1
    wrapper.on_bar(ctx, bar)  # gate closed again (allow[2] is False)
    assert inner.on_bar.call_count == 1
    # past the end of allow -> open (default True)
    wrapper.on_bar(ctx, bar)
    assert inner.on_bar.call_count == 2


def test_direction_gate_wrapper_generate_signals_delegates() -> None:
    inner = MagicMock()
    inner.name = "mock"
    inner.required_regime = "any"
    wrapper = _DirectionGateWrapper(inner, pd.Series([True]))
    df = pd.DataFrame({"close": [1.0, 2.0]})
    wrapper.generate_signals(df)
    inner.generate_signals.assert_called_once_with(df)


# ---------------------------------------------------------------------------
# stats / aggregate
# ---------------------------------------------------------------------------


def test_max_drawdown_zero_peak_iteration() -> None:
    # first point <= 0 keeps peak == 0 -> `if peak > 0` False branch
    curve = [{"equity": -1.0}, {"equity": 2.0}, {"equity": 1.0}]
    assert _max_drawdown(curve) == 0.5


def test_sharpe_degenerate_short_curve() -> None:
    assert math.isnan(_sharpe([{"equity": 1.0}]))
    # constant equity -> std == 0 -> nan
    flat = [{"equity": 1.0}, {"equity": 1.0}, {"equity": 1.0}]
    assert math.isnan(_sharpe(flat))


def test_aggregate_risk_reason_folding() -> None:
    curve = [{"equity": 1000.0}, {"equity": 1010.0}]
    fills = [{"order_id": "o1"}, {"order_id": "o1"}]
    risk_events = [{"reason": "max_dd"}, {"type": "kill_switch"}]
    out = aggregate(curve, fills, risk_events, alerts=[{"a": 1}], capital=1000.0)
    assert out["orders"] == 1
    assert out["risk_events"] == {"max_dd": 1, "kill_switch": 1}
    assert out["fills"] == 2
    assert out["bars"] == 2
    assert out["return_pct"] == pytest.approx(1.0)


def test_aggregate_empty_curve_uses_capital() -> None:
    out = aggregate([], [], [], [], capital=5000.0)
    assert out["final_equity"] == 5000.0
    assert out["equity_curve"] == []


# ---------------------------------------------------------------------------
# remaining guards
# ---------------------------------------------------------------------------


def test_resolve_strategy_class_research_wave() -> None:
    """Cover the research-only liu_yudong_wave branch of _resolve_strategy_class."""
    from quantflow.strategy.research.paper_replay import _resolve_strategy_class

    cls = _resolve_strategy_class("liu_yudong_wave")
    assert cls.__name__ == "LiuYudongWaveStrategy"
    cls2 = _resolve_strategy_class("elliott_wave_liu")
    assert cls2 is cls


@pytest.mark.asyncio
async def test_replay_multi_skips_existing_prototype_context() -> None:
    """Cover the (strategy.name, "") already-present skip in replay_multi."""
    session = build_multi_symbol_session("mean_reversion", ["BTC/USDT"])
    # pre-seed the prototype context so the loop takes the skip branch
    proto_ctx = StrategyContext()
    session._contexts[(session._strategies[0].name, "")] = proto_ctx
    bars = {"BTC/USDT": _synthetic_bars(40)}
    curve = await replay_multi(session, bars)
    assert len(curve) == 40
