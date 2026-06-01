"""Elliott Wave strategy backtest script.

Runs the ElliottWaveStrategy on historical data and computes
performance metrics. Supports both synthetic and real data.

Usage:
    from quantflow.strategy.research.elliott_wave_backtest import run_backtest
    results = run_backtest(symbol="BTC/USDT", n_bars=2000)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quantflow.strategy.elliott_wave_strategy import LiuYudongWaveStrategy


@dataclass
class BacktestResult:
    """Backtest performance metrics."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    total_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    trades: list[dict[str, Any]] | None = None

    @property
    def meets_targets(self) -> dict[str, bool]:
        """Check against minimum performance targets."""
        return {
            "win_rate": self.win_rate >= 0.55,
            "profit_factor": self.profit_factor >= 2.0,
            "max_drawdown": self.max_drawdown_pct <= 15.0,
            "sharpe": self.sharpe_ratio >= 1.5,
        }


def generate_synthetic_wave_data(
    n_bars: int = 2000,
    base_price: float = 100000.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic OHLCV data with clear Elliott Wave patterns.

    Creates multiple impulse-corrective cycles suitable for testing.
    """
    np.random.seed(seed)
    prices = np.zeros(n_bars)
    prices[0] = base_price

    # Generate price series with embedded wave patterns
    cycle_length = 400
    for cycle_start in range(0, n_bars, cycle_length):
        cycle_end = min(cycle_start + cycle_length, n_bars)
        cycle_len = cycle_end - cycle_start

        # 5-wave impulse + 3-wave correction pattern
        w1_len = cycle_len // 8
        w2_len = cycle_len // 8
        w3_len = cycle_len // 4
        w4_len = cycle_len // 8
        w5_len = cycle_len // 8
        abc_len = cycle_len - w1_len - w2_len - w3_len - w4_len - w5_len

        base = prices[cycle_start] if cycle_start > 0 else base_price
        idx = cycle_start

        # W1: rise 10%
        for i in range(w1_len):
            if idx >= n_bars:
                break
            progress = (i + 1) / w1_len
            prices[idx] = base * (1 + 0.10 * progress) + np.random.randn() * base * 0.002
            idx += 1

        # W2: pullback to ~0.5 retracement
        w1_top = prices[idx - 1]
        for i in range(w2_len):
            if idx >= n_bars:
                break
            progress = (i + 1) / w2_len
            prices[idx] = w1_top - (w1_top - base) * 0.5 * progress + np.random.randn() * base * 0.002
            idx += 1

        # W3: strong rise 25%
        w2_low = prices[idx - 1]
        for i in range(w3_len):
            if idx >= n_bars:
                break
            progress = (i + 1) / w3_len
            prices[idx] = w2_low + w2_low * 0.25 * progress + np.random.randn() * base * 0.003
            idx += 1

        # W4: pullback to ~0.382 of W3
        w3_top = prices[idx - 1]
        w3_amp = w3_top - w2_low
        for i in range(w4_len):
            if idx >= n_bars:
                break
            progress = (i + 1) / w4_len
            prices[idx] = w3_top - w3_amp * 0.382 * progress + np.random.randn() * base * 0.002
            idx += 1

        # W5: modest rise 8%
        w4_low = prices[idx - 1]
        for i in range(w5_len):
            if idx >= n_bars:
                break
            progress = (i + 1) / w5_len
            prices[idx] = w4_low + w4_low * 0.08 * progress + np.random.randn() * base * 0.002
            idx += 1

        # A-B-C correction: drop ~15%
        w5_top = prices[idx - 1]
        for i in range(abc_len):
            if idx >= n_bars:
                break
            progress = (i + 1) / abc_len
            prices[idx] = w5_top - w5_top * 0.15 * progress + np.random.randn() * base * 0.003
            idx += 1

    # Ensure no negative prices
    prices = np.maximum(prices, base_price * 0.1)

    # Build OHLCV
    noise_h = np.abs(np.random.randn(n_bars)) * base_price * 0.003
    noise_l = np.abs(np.random.randn(n_bars)) * base_price * 0.003

    df = pd.DataFrame({
        "open": prices + np.random.randn(n_bars) * base_price * 0.001,
        "high": prices + noise_h,
        "low": prices - noise_l,
        "close": prices,
        "volume": np.random.randint(100, 5000, n_bars).astype(float),
    })

    # Add technical indicators required by strategy
    df["macd_histogram"] = _compute_macd_histogram(df["close"])
    df["rsi_14"] = _compute_rsi(df["close"], 14)

    return df


def run_backtest(
    symbol: str = "BTC/USDT",
    n_bars: int = 2000,
    initial_capital: float = 100000.0,
    commission: float = 0.001,
    config: dict[str, Any] | None = None,
    df: pd.DataFrame | None = None,
) -> BacktestResult:
    """Run Elliott Wave strategy backtest.

    Args:
        symbol: Trading pair (used for logging).
        n_bars: Number of bars for synthetic data generation.
        initial_capital: Starting capital.
        commission: Commission rate per trade.
        config: Strategy configuration override.
        df: Pre-loaded DataFrame (if None, generates synthetic data).

    Returns:
        BacktestResult with performance metrics.
    """
    if df is None:
        df = generate_synthetic_wave_data(n_bars=n_bars)

    strategy = LiuYudongWaveStrategy(config)

    # Generate signals
    entries, exits = strategy.generate_signals(df)

    # Simple backtest: enter on entry signals, exit on exit signals
    capital = initial_capital
    position = 0.0
    entry_price = 0.0
    trades: list[dict[str, Any]] = []
    equity_curve: list[float] = [capital]
    peak_equity = capital

    for i in range(len(df)):
        price = float(df["close"].iloc[i])

        if entries.iloc[i] and position == 0:
            # Enter position
            position = (capital * 0.95) / price  # 95% of capital
            entry_price = price
            capital -= position * price * commission

        elif exits.iloc[i] and position > 0:
            # Exit position
            exit_value = position * price
            capital += exit_value * (1 - commission)
            pnl_pct = (price - entry_price) / entry_price * 100
            trades.append({
                "entry_idx": i,
                "entry_price": entry_price,
                "exit_price": price,
                "pnl_pct": pnl_pct,
            })
            position = 0.0
            entry_price = 0.0

        # Track equity
        current_equity = capital + position * price
        equity_curve.append(current_equity)
        peak_equity = max(peak_equity, current_equity)

    # Close any remaining position
    if position > 0 and entry_price > 0:
        price = float(df["close"].iloc[-1])
        capital += position * price * (1 - commission)
        pnl_pct = (price - entry_price) / entry_price * 100
        trades.append({
            "entry_idx": len(df) - 1,
            "entry_price": entry_price,
            "exit_price": price,
            "pnl_pct": pnl_pct,
        })

    # Compute metrics
    total_trades = len(trades)
    winning = [t for t in trades if t["pnl_pct"] > 0]
    losing = [t for t in trades if t["pnl_pct"] <= 0]

    win_rate = len(winning) / total_trades if total_trades > 0 else 0.0
    avg_win = np.mean([t["pnl_pct"] for t in winning]) if winning else 0.0
    avg_loss = abs(np.mean([t["pnl_pct"] for t in losing])) if losing else 0.0

    gross_profit = sum(t["pnl_pct"] for t in winning)
    gross_loss = abs(sum(t["pnl_pct"] for t in losing))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    equity_arr = np.array(equity_curve)
    drawdowns = (equity_arr - np.maximum.accumulate(equity_arr)) / np.maximum.accumulate(equity_arr) * 100
    max_drawdown = abs(min(drawdowns)) if len(drawdowns) > 0 else 0.0

    total_return = (capital - initial_capital) / initial_capital * 100

    # Sharpe ratio (annualized, assuming 4H bars → 6 bars/day → 2190 bars/year)
    daily_returns = np.diff(equity_arr) / equity_arr[:-1]
    if len(daily_returns) > 1 and np.std(daily_returns) > 0:
        sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(2190)
    else:
        sharpe = 0.0

    return BacktestResult(
        total_trades=total_trades,
        winning_trades=len(winning),
        losing_trades=len(losing),
        win_rate=win_rate,
        avg_win_pct=avg_win,
        avg_loss_pct=avg_loss,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown,
        total_return_pct=total_return,
        sharpe_ratio=sharpe,
        trades=trades,
    )


def _compute_macd_histogram(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    """Compute MACD histogram. Delegates to strategy's static method."""
    return LiuYudongWaveStrategy._compute_macd_histogram(close, fast, slow, signal)


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI. Delegates to strategy's static method."""
    return LiuYudongWaveStrategy._compute_rsi(close, period)
