"""Tests for backtest report generation."""

from __future__ import annotations

import pandas as pd

from quantflow.strategy.research.backtest import BacktestResult
from quantflow.strategy.research.report import generate_report


def _make_result() -> BacktestResult:
    index = pd.date_range("2024-01-01", periods=3, freq="D")
    equity = pd.Series([10000.0, 10200.0, 10400.0], index=index)
    drawdown = pd.Series([0.0, -0.01, -0.005], index=index)
    return BacktestResult(
        strategy_id="trend_following",
        symbol="BTC/USDT",
        start_date="2024-01-01",
        end_date="2024-01-03",
        initial_capital=10000.0,
        final_capital=10400.0,
        total_return=0.04,
        annual_return=0.5,
        sharpe_ratio=1.2,
        sortino_ratio=1.5,
        calmar_ratio=1.1,
        max_drawdown=-0.08,
        win_rate=0.6,
        profit_factor=1.8,
        num_trades=5,
        equity_curve=equity,
        drawdown_curve=drawdown,
    )


def test_generate_report_text_format_uses_summary() -> None:
    result = _make_result()

    report = generate_report(result, format="text")

    assert report == result.summary()
    assert "Backtest: trend_following / BTC/USDT" in report


def test_generate_report_markdown_format() -> None:
    report = generate_report(_make_result(), format="markdown")

    assert report.startswith("## Backtest: trend_following / BTC/USDT")
    assert "| Metric | Value |" in report
    assert "| Total Return | 4.00% |" in report
    assert "| Trades | 5 |" in report


def test_generate_report_unknown_format_falls_back_to_summary() -> None:
    result = _make_result()

    report = generate_report(result, format="html")

    assert report == result.summary()
