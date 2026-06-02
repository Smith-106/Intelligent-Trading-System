"""Extra coverage for Elliott Wave backtest helpers."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from quantflow.strategy.research import elliott_wave_backtest as ew_backtest


def _ohlcv(close_values: list[float]) -> pd.DataFrame:
    close = pd.Series(close_values, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": pd.Series([1000.0] * len(close_values), dtype=float),
        }
    )


class _StubStrategy:
    def __init__(self, config=None) -> None:
        self.config = config

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        entries = pd.Series(False, index=df.index)
        exits = pd.Series(False, index=df.index)
        entries.iloc[0] = True
        exits.iloc[1] = True
        return entries, exits

    @staticmethod
    def _compute_macd_histogram(
        close: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> pd.Series:
        del fast, slow, signal
        return pd.Series(0.0, index=close.index)

    @staticmethod
    def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        del period
        return pd.Series(50.0, index=close.index)


class _HoldingStrategy(_StubStrategy):
    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        entries = pd.Series(False, index=df.index)
        exits = pd.Series(False, index=df.index)
        entries.iloc[0] = True
        return entries, exits


class TestElliottWaveBacktestExtra:
    def test_generate_synthetic_wave_data_produces_positive_indicator_frame(self) -> None:
        df = ew_backtest.generate_synthetic_wave_data(n_bars=64, base_price=1000.0, seed=7)

        assert list(df.columns) == [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "macd_histogram",
            "rsi_14",
        ]
        assert len(df) == 64
        assert (df["close"] > 0).all()
        assert df["volume"].dtype == float

    def test_run_backtest_uses_generated_data_and_records_closed_trade(self) -> None:
        df = _ohlcv([100.0, 110.0, 120.0])

        with (
            patch.object(ew_backtest, "generate_synthetic_wave_data", return_value=df),
            patch.object(ew_backtest, "LiuYudongWaveStrategy", _StubStrategy),
        ):
            result = ew_backtest.run_backtest(
                symbol="BTC/USDT",
                n_bars=3,
                initial_capital=1000.0,
                commission=0.0,
                config={"mode": "test"},
                df=None,
            )

        assert result.total_trades == 1
        assert result.winning_trades == 1
        assert result.losing_trades == 0
        assert result.win_rate == 1.0
        assert result.avg_win_pct == 10.0
        assert result.avg_loss_pct == 0.0
        assert result.total_return_pct > 0
        assert result.sharpe_ratio > 0
        assert result.trades is not None
        assert result.trades[0]["exit_price"] == 110.0

    def test_run_backtest_closes_open_position_at_final_bar(self) -> None:
        df = _ohlcv([100.0, 95.0, 105.0])

        with patch.object(ew_backtest, "LiuYudongWaveStrategy", _HoldingStrategy):
            result = ew_backtest.run_backtest(
                initial_capital=1000.0,
                commission=0.0,
                df=df,
            )

        assert result.total_trades == 1
        assert result.winning_trades == 1
        assert result.trades is not None
        assert result.trades[0]["entry_idx"] == len(df) - 1
        assert result.trades[0]["exit_price"] == 105.0
        assert result.profit_factor == float("inf")

    def test_run_backtest_handles_flat_equity_without_sharpe(self) -> None:
        df = _ohlcv([100.0, 100.0, 100.0])

        with patch.object(ew_backtest, "LiuYudongWaveStrategy", _HoldingStrategy):
            result = ew_backtest.run_backtest(
                initial_capital=1000.0,
                commission=0.0,
                df=df,
            )

        assert result.total_trades == 1
        assert result.avg_win_pct == 0.0
        assert result.sharpe_ratio == 0.0
        assert result.max_drawdown_pct == 0.0

    def test_helper_indicators_delegate_to_strategy_statics(self) -> None:
        close = pd.Series([100.0, 101.0, 102.0], dtype=float)

        with patch.object(ew_backtest, "LiuYudongWaveStrategy", _StubStrategy):
            macd = ew_backtest._compute_macd_histogram(close, fast=3, slow=5, signal=2)
            rsi = ew_backtest._compute_rsi(close, period=2)

        assert macd.eq(0.0).all()
        assert rsi.eq(50.0).all()
