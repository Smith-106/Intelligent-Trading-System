"""Backtest report generation."""

from __future__ import annotations

from quantflow.strategy.research.backtest import BacktestResult


def generate_report(result: BacktestResult, format: str = "text") -> str:
    """Generate a backtest report."""
    if format == "text":
        return _text_report(result)
    elif format == "markdown":
        return _markdown_report(result)
    return result.summary()


def _text_report(r: BacktestResult) -> str:
    return r.summary()


def _markdown_report(r: BacktestResult) -> str:
    return (
        f"## Backtest: {r.strategy_id} / {r.symbol}\n\n"
        f"| Metric | Value |\n|--------|-------|\n"
        f"| Period | {r.start_date} → {r.end_date} |\n"
        f"| Capital | {r.initial_capital:,.0f} → {r.final_capital:,.0f} |\n"
        f"| Total Return | {r.total_return:.2%} |\n"
        f"| Annual Return | {r.annual_return:.2%} |\n"
        f"| Sharpe | {r.sharpe_ratio:.3f} |\n"
        f"| Sortino | {r.sortino_ratio:.3f} |\n"
        f"| Calmar | {r.calmar_ratio:.3f} |\n"
        f"| Max Drawdown | {r.max_drawdown:.2%} |\n"
        f"| Win Rate | {r.win_rate:.2%} |\n"
        f"| Profit Factor | {r.profit_factor:.3f} |\n"
        f"| Trades | {r.num_trades} |\n"
    )
