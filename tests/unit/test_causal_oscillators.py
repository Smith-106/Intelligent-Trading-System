"""Causal guards + IAF oscillator pack tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.indicators import oscillators
from quantflow.indicators.causal import (
    assert_frame_causal,
    assert_series_causal,
    scan_source_for_negative_shift,
    shift_for_trade,
)
from quantflow.indicators.engine import CLASSICAL_EXTENDED_NAMES, IndicatorEngine
from quantflow.strategy.base import StrategyBase
from quantflow.strategy.validation.lookahead import scan_strategy


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    np.random.seed(7)
    n = 300
    close = 40000 * np.exp(np.cumsum(np.random.normal(0.0002, 0.015, n)))
    high = close * (1 + np.random.uniform(0.001, 0.01, n))
    low = close * (1 - np.random.uniform(0.001, 0.01, n))
    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.random.uniform(100, 1000, n),
        }
    )


class TestShiftForTrade:
    def test_rejects_negative(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0])
        with pytest.raises(ValueError):
            shift_for_trade(s, bars=-1)

    def test_lag_one(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0, 4.0])
        out = shift_for_trade(s, 1)
        assert np.isnan(out.iloc[0])
        assert out.iloc[1] == 1.0
        assert out.iloc[-1] == 3.0


class TestNegativeShiftScan:
    def test_flags_shift_minus_one(self) -> None:
        src = "def f(s):\n    return s.shift(-1)\n"
        hits = scan_source_for_negative_shift(src, where="f")
        assert hits
        assert "future" in hits[0].detail

    def test_clean_positive_shift(self) -> None:
        src = "def f(s):\n    return s.shift(1)\n"
        assert scan_source_for_negative_shift(src) == []

    def test_lookahead_scan_flags_strategy_negative_shift(self) -> None:
        class Leaky(StrategyBase):
            name = "leaky"

            def generate_signals(self, df: pd.DataFrame):  # type: ignore[no-untyped-def]
                # intentional future function for scanner test
                sig = (df["close"].shift(-1) > df["close"]).astype(bool)
                return sig, ~sig

        report = scan_strategy(Leaky())
        assert not report.passed
        assert any("shift" in f.pattern.lower() or "future" in f.pattern.lower() for f in report.findings)


class TestOscillatorsCausal:
    def test_cci_causal(self, ohlcv_df: pd.DataFrame) -> None:
        assert_series_causal(
            lambda d: oscillators.cci(d["high"], d["low"], d["close"], 20),
            ohlcv_df,
            name="cci_20",
        )

    def test_roc_causal(self, ohlcv_df: pd.DataFrame) -> None:
        assert_series_causal(lambda d: oscillators.roc(d["close"], 12), ohlcv_df, name="roc_12")

    def test_cmf_causal(self, ohlcv_df: pd.DataFrame) -> None:
        assert_series_causal(
            lambda d: oscillators.cmf(d["high"], d["low"], d["close"], d["volume"], 20),
            ohlcv_df,
            name="cmf_20",
        )

    def test_aroon_causal(self, ohlcv_df: pd.DataFrame) -> None:
        assert_frame_causal(
            lambda d: oscillators.aroon(d["high"], d["low"], 25),
            ohlcv_df,
            ["aroon_up", "aroon_down", "aroon_osc"],
        )

    def test_realized_vol_causal(self, ohlcv_df: pd.DataFrame) -> None:
        assert_series_causal(
            lambda d: oscillators.realized_vol(d["close"], 20),
            ohlcv_df,
            name="realized_vol_20",
        )

    def test_trix_tsi_causal(self, ohlcv_df: pd.DataFrame) -> None:
        assert_series_causal(lambda d: oscillators.trix(d["close"], 15), ohlcv_df, name="trix")
        assert_series_causal(lambda d: oscillators.tsi(d["close"]), ohlcv_df, name="tsi")


class TestEngineIAF:
    def test_batch_has_new_columns(self, ohlcv_df: pd.DataFrame) -> None:
        eng = IndicatorEngine()
        out = eng.batch_calculate(ohlcv_df)
        for name in (
            "cci_20",
            "roc_12",
            "mom_10",
            "aroon_up",
            "aroon_down",
            "aroon_osc",
            "cmf_20",
            "realized_vol_20",
            "bb_width_20",
            "percent_b_20",
            "trix_15",
            "tsi",
        ):
            assert name in CLASSICAL_EXTENDED_NAMES
            assert name in out.columns, name
            assert name in eng.list_available()

    def test_compute_all_subset(self, ohlcv_df: pd.DataFrame) -> None:
        eng = IndicatorEngine()
        out = eng.compute_all(ohlcv_df, ["cci_20", "tsi", "aroon_osc"])
        assert "cci_20" in out.columns
        assert "tsi" in out.columns
        assert "aroon_osc" in out.columns
        # not requested classical core may be absent
        assert "rsi_14" not in out.columns

    def test_core_indicators_still_causal(self, ohlcv_df: pd.DataFrame) -> None:
        eng = IndicatorEngine()

        def rsi_col(d: pd.DataFrame) -> pd.Series:
            return eng.batch_calculate(d)["rsi_14"]

        assert_series_causal(rsi_col, ohlcv_df, name="rsi_14", min_prefix=60)
