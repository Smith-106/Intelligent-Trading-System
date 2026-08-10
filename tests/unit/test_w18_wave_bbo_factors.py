"""W18a/b/c focused tests: wave fidelity, BBO feed path, dormant factors."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from quantflow.common.models import Bar, Order, OrderSide, OrderStatus
from quantflow.execution.engine import ExecutionEngine
from quantflow.execution.paper_gateway import PaperGateway
from quantflow.indicators.engine import (
    CLASSICAL_CORE_NAMES,
    CLASSICAL_EXTENDED_NAMES,
    FACTOR_NAMES,
    WAVE_FACTOR_NAMES,
    IndicatorEngine,
)
from quantflow.indicators.zigzag import PivotDirection, PivotSequence, ZigZagIndicator
from quantflow.strategy.elliott_wave_strategy import LiuYudongWaveStrategy


def _ohlcv(n: int = 80, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1.5, n))
    close = np.maximum(close, 10.0)
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.uniform(100, 1000, n),
            "timestamp": np.arange(n, dtype=int) * 3_600_000,
        }
    )


# ---------------------------------------------------------------------------
# W18a — wave pivot fidelity
# ---------------------------------------------------------------------------


class TestW18aWaveFidelity:
    def test_pivot_sequence_degraded_flag_on_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        indicator = ZigZagIndicator()
        high = pd.Series([100.0] * 20, dtype=float)
        low = pd.Series([99.0] * 20, dtype=float)
        timestamps = pd.Series(list(range(20)), dtype=int)

        monkeypatch.setattr(
            "quantflow.indicators.zigzag._merge_pivot_runs",
            lambda *args, **kwargs: pd.DataFrame(
                columns=["pivot_idx", "pivot_price", "pivot_type", "overlap_count"]
            ),
        )
        fake = pd.DataFrame([{"pivot_idx": 5, "pivot_price": 99.5, "pivot_type": -1}])

        def _fake(h, lo, threshold):  # noqa: ANN001
            if abs(threshold - 0.08) < 1e-9:
                return fake.copy()
            return pd.DataFrame(columns=["pivot_idx", "pivot_price", "pivot_type"])

        monkeypatch.setattr("quantflow.indicators.zigzag._zigzag_single", _fake)
        seq = indicator.compute_pivot_sequence(
            high, low, timestamps, thresholds=[0.03, 0.05, 0.08, 0.12, 0.15]
        )
        assert seq.degraded is True
        assert len(seq.pivots) == 1
        assert seq.pivots[0].price == 99.5

    def test_confirmed_pivots_drops_trailing(self) -> None:
        from quantflow.indicators.zigzag import PivotPoint

        seq = PivotSequence(
            pivots=[
                PivotPoint(0, 100.0, PivotDirection.LOW),
                PivotPoint(5, 110.0, PivotDirection.HIGH),
                PivotPoint(9, 105.0, PivotDirection.LOW),
            ],
            overlap_ratio=0.8,
            thresholds_used=[0.05],
            degraded=False,
            consensus_n=3,
        )
        confirmed = seq.with_confirmed_only()
        assert len(confirmed.pivots) == 2
        assert confirmed.pivots[-1].index == 5
        assert confirmed.degraded is False

    def test_detect_pivots_uses_high_low_not_close_only(self) -> None:
        """True high/low path: high pivot price should not equal close when high>close."""
        strategy = LiuYudongWaveStrategy(
            {
                "require_confirmed_pivots": False,
                "allow_degraded_consensus": True,
                "zigzag_thresholds": [0.05],
                "min_overlap_ratio": 1.0,
            }
        )
        # Strong swing so single-threshold finds pivots on high/low extremes
        df = pd.DataFrame(
            {
                "open": [100, 105, 120, 115, 90, 95, 110],
                "high": [102, 108, 130, 118, 100, 100, 115],
                "low": [98, 100, 110, 100, 80, 90, 100],
                "close": [101, 106, 118, 105, 92, 98, 112],
                "volume": [1.0] * 7,
                "timestamp": list(range(7)),
            }
        )
        seq = strategy._detect_pivots(df)
        assert seq is not None
        assert len(seq.pivots) >= 1
        # At least one pivot price should match high or low extreme, not only close
        closes = set(float(x) for x in df["close"])
        highs = set(float(x) for x in df["high"])
        lows = set(float(x) for x in df["low"])
        prices = {p.price for p in seq.pivots}
        # Real extremes live in high/low; if all prices were closes, fidelity failed
        assert prices & (highs | lows) or not prices.issubset(closes)

    def test_extract_pivots_prefers_high_low(self) -> None:
        strategy = LiuYudongWaveStrategy()
        markers = pd.Series([0, 1, -1, 0], dtype=int)
        df = pd.DataFrame(
            {
                "close": [100.0, 110.0, 105.0, 111.0],
                "high": [101.0, 115.0, 106.0, 112.0],
                "low": [99.0, 109.0, 100.0, 110.0],
            }
        )
        result = strategy._extract_pivots(markers, df)
        assert result.pivots[0].price == 115.0  # high, not close 110
        assert result.pivots[1].price == 100.0  # low, not close 105

    def test_degraded_skipped_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        strategy = LiuYudongWaveStrategy({"allow_degraded_consensus": False})

        def _deg(*_a, **_k):  # noqa: ANN001
            from quantflow.indicators.zigzag import PivotPoint

            return PivotSequence(
                pivots=[PivotPoint(1, 100.0, PivotDirection.HIGH)],
                degraded=True,
                consensus_n=1,
                thresholds_used=[0.05],
            )

        monkeypatch.setattr(strategy.zigzag, "compute_pivot_sequence", _deg)
        df = _ohlcv(30)
        assert strategy._detect_pivots(df) is None

    def test_require_confirmed_default_true(self) -> None:
        s = LiuYudongWaveStrategy()
        assert s.require_confirmed_pivots is True
        assert s.allow_degraded_consensus is False


# ---------------------------------------------------------------------------
# W18b — BBO feed path
# ---------------------------------------------------------------------------


class TestW18bBboFeed:
    def test_execution_engine_forwards_orderbook(self) -> None:
        gw = PaperGateway({"orderbook_fill_enabled": True, "taker_fee": 0.0, "slippage": 0.0})
        eng = ExecutionEngine(gateway=gw)
        eng.update_orderbook("BTC/USDT", bid=99.0, ask=101.0, mid_to_last=False)
        assert gw._bbo["BTC/USDT"] == (99.0, 101.0)
        # mid_to_last=False → last price not forced to mid
        assert "BTC/USDT" not in gw._prices or gw._prices.get("BTC/USDT") != 100.0

    @pytest.mark.asyncio
    async def test_bar_proxy_path_enables_bbo_fill_when_opt_in(self) -> None:
        """Simulate strategy engine bar hook: low/high → update_orderbook → fill@ask."""
        gw = PaperGateway(
            {
                "orderbook_fill_enabled": True,
                "orderbook_fill": {"extra_slippage": 0.0},
                "taker_fee": 0.0,
                "slippage": 0.05,
            }
        )
        await gw.connect()
        eng = ExecutionEngine(gateway=gw)
        bar = Bar(
            symbol="BTC/USDT",
            timestamp=1,
            open=100.0,
            high=102.0,
            low=98.0,
            close=100.5,
            volume=1.0,
        )
        eng.update_market_price(bar.symbol, bar.close)
        eng.update_orderbook(bar.symbol, bid=float(bar.low), ask=float(bar.high), mid_to_last=False)
        order = Order(
            order_id="",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=1.0,
            price=100.0,
        )
        await gw.send_order(order)
        assert order.status == OrderStatus.FILLED
        assert order.filled_price == pytest.approx(102.0)  # ask = bar.high
        await gw.disconnect()

    def test_gateway_base_has_update_orderbook_noop(self) -> None:
        from quantflow.execution.gateway_base import GatewayBase

        class _G(GatewayBase):
            async def connect(self, config=None):  # noqa: ANN001
                return None

            async def send_order(self, order):  # noqa: ANN001
                return "x"

            async def cancel_order(self, order_id, symbol):  # noqa: ANN001
                return True

            async def query_positions(self):  # noqa: ANN001
                return []

            async def query_order(self, order_id, symbol):  # noqa: ANN001
                return None

            async def query_open_orders(self, symbol=None):  # noqa: ANN001
                return []

        g = _G()
        g.update_orderbook("X", 1.0, 2.0)  # no-op, must not raise


# ---------------------------------------------------------------------------
# W18c — dormant factors exposed
# ---------------------------------------------------------------------------


class TestW18cDormantFactors:
    def test_list_available_includes_extended(self) -> None:
        names = IndicatorEngine().list_available()
        for n in (
            "dema_20",
            "supertrend",
            "supertrend_direction",
            "stochrsi_k",
            "stochrsi_d",
            "kc_upper",
            "dc_upper",
        ):
            assert n in names
        for n in WAVE_FACTOR_NAMES:
            assert n in names
        assert len(CLASSICAL_CORE_NAMES) == 21
        assert len(WAVE_FACTOR_NAMES) == 6
        assert len(FACTOR_NAMES) == len(CLASSICAL_CORE_NAMES) + len(CLASSICAL_EXTENDED_NAMES) + 6

    def test_batch_calculate_writes_extended_columns(self) -> None:
        df = _ohlcv(80)
        out = IndicatorEngine().batch_calculate(df)
        for col in (
            "dema_20",
            "supertrend",
            "supertrend_direction",
            "stochrsi_k",
            "stochrsi_d",
            "kc_upper",
            "kc_middle",
            "kc_lower",
            "dc_upper",
            "dc_middle",
            "dc_lower",
            "rsi_14",
        ):
            assert col in out.columns

    def test_compute_all_selective_extended(self) -> None:
        df = _ohlcv(80)
        out = IndicatorEngine().compute_all(
            df,
            indicator_names=["dema_20", "supertrend", "stochrsi_k", "kc_upper", "dc_lower"],
        )
        assert "dema_20" in out.columns
        assert "supertrend" in out.columns
        assert "stochrsi_k" in out.columns
        assert "kc_upper" in out.columns
        assert "dc_lower" in out.columns
        # not requested classical stays out
        assert "rsi_14" not in out.columns
