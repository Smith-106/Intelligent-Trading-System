"""Elliott Wave walk-forward **smoke** (W20c) — research only, not a GO path.

Runs rolling causal windows of :class:`LiuYudongWaveStrategy` on OHLCV
(synthetic or real Parquet via DataStore). Produces per-window trade counts
and crude returns. **Does not** write promotion reports and **must not** be
used as ``execution_path`` for register/GO (W14).

Usage::

    from quantflow.strategy.research.elliott_wave_wfo_smoke import run_elliott_wfo_smoke
    report = run_elliott_wfo_smoke(n_bars=800, n_windows=3)  # synthetic
    # or
    report = run_elliott_wfo_smoke(df=real_ohlcv, n_windows=3)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quantflow.strategy.elliott_wave_strategy import LiuYudongWaveStrategy
from quantflow.strategy.research.elliott_wave_backtest import (
    generate_synthetic_wave_data,
    run_backtest,
)


@dataclass
class WindowSmokeResult:
    window_id: int
    train_bars: int
    oos_bars: int
    oos_start: int
    oos_end: int
    total_trades: int
    win_rate: float
    total_return_pct: float
    sharpe_ratio: float


@dataclass
class ElliottWfoSmokeReport:
    """Smoke report — explicitly not a promotion artifact."""

    is_smoke: bool = True
    promotion_eligible: bool = False
    execution_path: str = "vectorized_smoke"  # W14: not paper_replay
    n_windows: int = 0
    n_bars: int = 0
    symbol: str = ""
    data_source: str = "synthetic"
    windows: list[WindowSmokeResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _load_parquet_ohlcv(
    symbol: str,
    parquet_dir: str | Path,
    start: int | None = None,
    end: int | None = None,
) -> pd.DataFrame:
    """Best-effort load from Hive parquet via DataStore (real-data path)."""
    from quantflow.data.store import DataStore

    store = DataStore(str(parquet_dir), ":memory:")
    df = store.query(symbol, start=start, end=end)
    if df is None or df.empty:
        raise FileNotFoundError(f"No OHLCV for {symbol} under {parquet_dir}")
    # Ensure required columns
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            raise ValueError(f"OHLCV missing column {col}")
    return df.reset_index(drop=True)


def run_elliott_wfo_smoke(
    *,
    df: pd.DataFrame | None = None,
    symbol: str = "BTC/USDT",
    n_bars: int = 800,
    n_windows: int = 3,
    oos_ratio: float = 0.3,
    config: dict[str, Any] | None = None,
    parquet_dir: str | Path | None = None,
    start: int | None = None,
    end: int | None = None,
) -> ElliottWfoSmokeReport:
    """Rolling WFO-style smoke for Elliott wave strategy.

    For each window, the strategy runs ``generate_signals`` on the prefix
    ``df.iloc[:oos_end]`` (causal CORR-019 path inside the strategy) and
    metrics are taken from a simple backtest on the **OOS slice only**
    (signals outside OOS are zeroed for PnL attribution).

    Args:
        df: OHLCV frame; if None and parquet_dir set, load real data;
            else synthetic.
        n_windows: number of rolling folds (minimum 2).
        oos_ratio: fraction of each fold reserved for OOS.
        parquet_dir: optional DataStore root for real bars.
    """
    notes: list[str] = [
        "W20c smoke only — not for promote_to_live / register GO",
        "execution_path=vectorized_smoke is rejected by W14 promotion_path",
    ]
    data_source = "synthetic"
    if df is None and parquet_dir is not None:
        df = _load_parquet_ohlcv(symbol, parquet_dir, start=start, end=end)
        data_source = f"parquet:{parquet_dir}"
        notes.append(f"loaded real OHLCV for {symbol}")
    if df is None:
        df = generate_synthetic_wave_data(n_bars=n_bars)
        data_source = "synthetic"

    n = len(df)
    n_windows = max(2, int(n_windows))
    oos_ratio = min(0.5, max(0.1, float(oos_ratio)))
    fold = n // n_windows
    if fold < 40:
        notes.append(f"short series n={n}; results unstable")

    cfg = dict(config or {})
    # Smoke defaults: allow degraded so synthetic low-vol folds still run
    cfg.setdefault("allow_degraded_consensus", True)
    cfg.setdefault("require_confirmed_pivots", True)

    windows: list[WindowSmokeResult] = []
    for w in range(n_windows):
        fold_end = min(n, (w + 1) * fold) if w < n_windows - 1 else n
        fold_start = w * fold
        fold_len = fold_end - fold_start
        oos_len = max(10, int(fold_len * oos_ratio))
        oos_start = max(fold_start, fold_end - oos_len)
        oos_end = fold_end
        train_bars = oos_start - fold_start

        # Causal prefix through OOS end
        prefix = df.iloc[:oos_end].copy()
        strategy = LiuYudongWaveStrategy(cfg)
        entries, exits = strategy.generate_signals(prefix)

        # Attribute PnL only on OOS bars: zero signals before oos_start
        e = entries.copy()
        x = exits.copy()
        e.iloc[:oos_start] = False
        x.iloc[:oos_start] = False
        # Build a frame with only OOS prices but full signal alignment
        oos_df = prefix.copy()
        # run_backtest expects to call generate_signals itself — use internal
        # path: inject precomputed by temporarily patching is heavy; instead
        # re-run simple loop here for OOS-only attribution.
        metrics = _oos_metrics(oos_df, e, x)
        windows.append(
            WindowSmokeResult(
                window_id=w,
                train_bars=train_bars,
                oos_bars=oos_end - oos_start,
                oos_start=oos_start,
                oos_end=oos_end,
                total_trades=metrics["total_trades"],
                win_rate=metrics["win_rate"],
                total_return_pct=metrics["total_return_pct"],
                sharpe_ratio=metrics["sharpe_ratio"],
            )
        )

    return ElliottWfoSmokeReport(
        n_windows=n_windows,
        n_bars=n,
        symbol=symbol,
        data_source=data_source,
        windows=windows,
        notes=notes,
    )


def _oos_metrics(
    df: pd.DataFrame,
    entries: pd.Series,
    exits: pd.Series,
    commission: float = 0.001,
    initial_capital: float = 100_000.0,
) -> dict[str, float | int]:
    capital = initial_capital
    position = 0.0
    entry_price = 0.0
    trades: list[float] = []
    equity = [capital]
    for i in range(len(df)):
        price = float(df["close"].iloc[i])
        if bool(entries.iloc[i]) and position == 0:
            position = (capital * 0.95) / price
            entry_price = price
            capital -= position * price * (1 + commission)
        elif bool(exits.iloc[i]) and position > 0:
            capital += position * price * (1 - commission)
            trades.append((price - entry_price) / entry_price * 100)
            position = 0.0
            entry_price = 0.0
        equity.append(capital + position * price)
    if position > 0 and entry_price > 0:
        price = float(df["close"].iloc[-1])
        capital += position * price * (1 - commission)
        trades.append((price - entry_price) / entry_price * 100)
    wins = [t for t in trades if t > 0]
    eq = np.array(equity, dtype=float)
    rets = np.diff(eq) / np.maximum(eq[:-1], 1e-12)
    sharpe = 0.0
    if len(rets) > 1 and float(np.std(rets)) > 0:
        sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(2190))
    return {
        "total_trades": len(trades),
        "win_rate": (len(wins) / len(trades)) if trades else 0.0,
        "total_return_pct": (capital - initial_capital) / initial_capital * 100,
        "sharpe_ratio": sharpe,
    }


def run_full_series_smoke(df: pd.DataFrame | None = None, **kwargs: Any) -> dict[str, Any]:
    """Convenience: single-shot ``run_backtest`` + WFO smoke summary."""
    bt = run_backtest(
        df=df,
        **{
            k: v
            for k, v in kwargs.items()
            if k in ("symbol", "n_bars", "initial_capital", "commission", "config")
        },
    )
    smoke = run_elliott_wfo_smoke(df=df, **kwargs)
    return {
        "full_series": {
            "total_trades": bt.total_trades,
            "win_rate": bt.win_rate,
            "sharpe_ratio": bt.sharpe_ratio,
            "meets_targets": bt.meets_targets,
        },
        "wfo_smoke": smoke.to_dict(),
    }
