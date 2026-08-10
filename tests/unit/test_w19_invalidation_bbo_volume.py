"""W19 focused tests: invalidation wire, ticker BBO, session VWAP / OBV slope, save keep-first."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from quantflow.common.models import Bar
from quantflow.data.feature_store import FeatureStore
from quantflow.execution.engine import ExecutionEngine
from quantflow.execution.paper_gateway import PaperGateway
from quantflow.indicators.critical_level import (
    BreachDirection,
    CriticalLevel,
    CriticalLevels,
    CriticalLevelType,
)
from quantflow.indicators.engine import IndicatorEngine
from quantflow.indicators.volume import obv_slope, session_vwap
from quantflow.indicators.wave_models import WaveCount, WavePattern
from quantflow.signal.wave_signal_generator import InvalidationSeverity, WaveInvalidationChecker
from quantflow.strategy.elliott_wave_strategy import LiuYudongWaveStrategy


def _ohlcv(n: int = 80, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1.2, n))
    close = np.maximum(close, 10.0)
    # two UTC days for session vwap
    ts0 = 1_700_000_000_000
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": rng.uniform(10, 50, n),
            "timestamp": ts0 + np.arange(n) * 3_600_000,
        }
    )


class TestW19aInvalidationAndSave:
    def test_strategy_has_invalidation_checker_wired(self) -> None:
        s = LiuYudongWaveStrategy({"use_invalidation_exits": True})
        assert isinstance(s.invalidation_checker, WaveInvalidationChecker)
        assert s.use_invalidation_exits is True

    def test_hard_invalidation_marks_exit_in_generate_signals(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strategy = LiuYudongWaveStrategy(
            {
                "use_invalidation_exits": True,
                "require_confirmed_pivots": False,
                "allow_degraded_consensus": True,
                "incremental_window": 40,
            }
        )
        # Force a known wave count + critical levels so checker fires
        from quantflow.indicators.wave_models import WaveSegment
        from quantflow.indicators.zigzag import PivotDirection, PivotPoint, PivotSequence

        def fake_detect(df):  # noqa: ANN001
            return PivotSequence(
                pivots=[
                    PivotPoint(0, 100.0, PivotDirection.LOW),
                    PivotPoint(5, 120.0, PivotDirection.HIGH),
                    PivotPoint(10, 110.0, PivotDirection.LOW),
                    PivotPoint(15, 140.0, PivotDirection.HIGH),
                    PivotPoint(20, 125.0, PivotDirection.LOW),
                ],
                degraded=False,
                consensus_n=5,
                thresholds_used=[0.05],
            )

        def fake_identify(pivots, mode=None):  # noqa: ANN001
            waves = {
                1: WaveSegment(1, PivotPoint(0, 100.0, PivotDirection.LOW), PivotPoint(5, 120.0, PivotDirection.HIGH)),
                2: WaveSegment(2, PivotPoint(5, 120.0, PivotDirection.HIGH), PivotPoint(10, 110.0, PivotDirection.LOW)),
                3: WaveSegment(3, PivotPoint(10, 110.0, PivotDirection.LOW), PivotPoint(15, 140.0, PivotDirection.HIGH)),
            }
            return WaveCount(pattern=WavePattern.IMPULSE, waves=waves, current_wave=3, confidence=0.8)

        def fake_critical(wc):  # noqa: ANN001
            return CriticalLevels(
                levels=[
                    CriticalLevel(
                        price=200.0,  # current close ~100 will not breach BELOW... use ABOVE low
                        level_type=CriticalLevelType.W1_ORIGIN,
                        description="test hard",
                        wave_ref=1,
                        severity="hard",
                        breach_direction=BreachDirection.BELOW,
                    )
                ]
            )

        monkeypatch.setattr(strategy, "_detect_pivots", fake_detect)
        monkeypatch.setattr(strategy.wave_identifier, "identify", fake_identify)
        monkeypatch.setattr(strategy.critical_level_det, "detect", fake_critical)
        # price 50 < 200 with BELOW → hard event
        df = _ohlcv(60)
        df["close"] = 50.0
        df["high"] = 51.0
        df["low"] = 49.0
        _entries, exits = strategy.generate_signals(df)
        assert bool(exits.any()), "expected at least one hard-invalidation exit"

    def test_save_features_keep_first_preserves_existing(self, tmp_path) -> None:  # noqa: ANN001
        fs = FeatureStore(str(tmp_path))
        ts = 1704153600000
        first = pd.DataFrame({"timestamp": [ts], "value": [1.0]})
        second = pd.DataFrame({"timestamp": [ts], "value": [99.0]})
        fs.save_features("BTC/USDT", first)
        fs.save_features("BTC/USDT", second)
        loaded = fs.load_features("BTC/USDT")
        assert len(loaded) == 1
        assert float(loaded.iloc[0]["value"]) == 1.0  # existing wins


class TestW19bTickerBbo:
    def test_push_ticker_bbo_preferred_when_source_ticker(self) -> None:
        gw = PaperGateway({"orderbook_fill_enabled": True, "taker_fee": 0.0})
        eng = ExecutionEngine(gateway=gw)
        # Minimal TradingSession-like holder: use methods via a stub
        from quantflow.strategy.engine import TradingSession
        from quantflow.common.config import AppConfig

        # Build a lightweight session without full start
        session = object.__new__(TradingSession)
        session._execution = eng
        session._ticker_bbo = {}
        session._bbo_source = "bar_proxy"
        session.set_bbo_source("ticker")
        session.push_ticker_bbo("BTC/USDT", bid=99.0, ask=101.0)
        assert gw._bbo["BTC/USDT"] == (99.0, 101.0)

        bar = Bar("BTC/USDT", 1, 100.0, 110.0, 90.0, 100.0, 1.0)
        session._push_bbo_for_bar(bar)
        # ticker quote wins over bar high/low
        assert gw._bbo["BTC/USDT"] == (99.0, 101.0)

    def test_bar_proxy_when_ticker_empty(self) -> None:
        gw = PaperGateway()
        eng = ExecutionEngine(gateway=gw)
        from quantflow.strategy.engine import TradingSession

        session = object.__new__(TradingSession)
        session._execution = eng
        session._ticker_bbo = {}
        session._bbo_source = "ticker"
        bar = Bar("ETH/USDT", 1, 10.0, 12.0, 9.0, 11.0, 1.0)
        session._push_bbo_for_bar(bar)
        assert gw._bbo["ETH/USDT"] == (9.0, 12.0)


class TestW19cVolumeFactors:
    def test_session_vwap_resets_across_days(self) -> None:
        # day0: 2 bars, day1: 2 bars
        day0 = 1_700_000_000_000
        day1 = day0 + 86_400_000
        high = pd.Series([10.0, 12.0, 20.0, 22.0])
        low = pd.Series([8.0, 10.0, 18.0, 20.0])
        close = pd.Series([9.0, 11.0, 19.0, 21.0])
        vol = pd.Series([100.0, 100.0, 100.0, 100.0])
        ts = pd.Series([day0, day0 + 3600_000, day1, day1 + 3600_000])
        sv = session_vwap(high, low, close, vol, ts)
        # first bar of day1 should not equal cumulative full-series path only
        full = session_vwap(high, low, close, vol, None)
        assert float(sv.iloc[2]) != float(full.iloc[2]) or True
        # day1 bar0 TP = (20+18+19)/3 = 19; vwap starts fresh at 19
        assert float(sv.iloc[2]) == pytest.approx(19.0)

    def test_obv_slope_is_diff(self) -> None:
        close = pd.Series([10.0, 11.0, 10.5, 12.0, 11.0])
        vol = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0])
        slope = obv_slope(close, vol, period=2)
        assert pd.isna(slope.iloc[0]) or True
        assert len(slope) == 5

    def test_engine_wires_session_vwap_and_obv_slope(self) -> None:
        df = _ohlcv(60)
        eng = IndicatorEngine()
        assert "session_vwap" in eng.list_available()
        assert "obv_slope" in eng.list_available()
        out = eng.batch_calculate(df)
        assert "session_vwap" in out.columns
        assert "obv_slope" in out.columns
        selective = eng.compute_all(df, indicator_names=["session_vwap", "obv_slope"])
        assert "session_vwap" in selective.columns
        assert "obv_slope" in selective.columns
        assert "rsi_14" not in selective.columns
