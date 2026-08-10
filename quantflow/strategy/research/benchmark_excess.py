"""Benchmark excess vs a buy-and-hold reference (default: BTC).

Product bar (2026-08-10): absolute return without ``strategy - HODL`` is incomplete.
High-flyer-style production needs explicit beta/excess reporting, not only GO gates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

BARS_PER_YEAR_1H = 8760.0


@dataclass(frozen=True)
class ExcessReport:
    """Strategy vs benchmark on an aligned equity sample."""

    label: str
    benchmark_label: str
    n_bars: int
    strategy_return_pct: float
    benchmark_return_pct: float
    excess_return_pct: float
    strategy_max_dd_pct: float
    benchmark_max_dd_pct: float
    strategy_sharpe: float
    benchmark_sharpe: float
    information_ratio: float
    beats_benchmark: bool
    cost_drag_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_float_series(equity: pd.Series | np.ndarray | list[float]) -> pd.Series:
    if isinstance(equity, pd.Series):
        s = equity.astype(float)
    else:
        s = pd.Series(np.asarray(equity, dtype=float))
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    return s


def equity_stats(
    equity: pd.Series | np.ndarray | list[float],
    *,
    bars_per_year: float = BARS_PER_YEAR_1H,
) -> dict[str, float]:
    """Return total return %, max drawdown % (positive), annualized Sharpe."""
    eq = _as_float_series(equity)
    if len(eq) < 2 or float(eq.iloc[0]) <= 0:
        return {
            "return_pct": 0.0,
            "max_dd_pct": 0.0,
            "sharpe": 0.0,
            "n_bars": float(len(eq)),
        }
    ret = float(eq.iloc[-1] / eq.iloc[0] - 1.0) * 100.0
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    max_dd = abs(float(dd.min() * 100.0))
    r = eq.pct_change().dropna()
    if len(r) < 2 or float(r.std(ddof=1)) <= 0:
        sh = 0.0
    else:
        sh = float(r.mean() / r.std(ddof=1) * np.sqrt(bars_per_year))
    return {
        "return_pct": round(ret, 6),
        "max_dd_pct": round(max_dd, 6),
        "sharpe": round(sh, 6),
        "n_bars": float(len(eq)),
    }


def buy_hold_equity_from_close(close: pd.Series | np.ndarray) -> pd.Series:
    """Unit-capital buy-and-hold equity from a close series."""
    c = _as_float_series(close)
    if c.empty or float(c.iloc[0]) <= 0:
        return pd.Series(dtype=float)
    return (c / float(c.iloc[0])).astype(float)


def excess_vs_benchmark(
    strategy_equity: pd.Series | np.ndarray | list[float],
    benchmark_equity: pd.Series | np.ndarray | list[float],
    *,
    label: str = "strategy",
    benchmark_label: str = "BTC_HODL",
    bars_per_year: float = BARS_PER_YEAR_1H,
    cost_drag_note: str = "",
) -> ExcessReport:
    """Compare two equity curves (same length preferred; truncated to min length)."""
    s = _as_float_series(strategy_equity)
    b = _as_float_series(benchmark_equity)
    n = int(min(len(s), len(b)))
    if n < 2:
        return ExcessReport(
            label=label,
            benchmark_label=benchmark_label,
            n_bars=n,
            strategy_return_pct=0.0,
            benchmark_return_pct=0.0,
            excess_return_pct=0.0,
            strategy_max_dd_pct=0.0,
            benchmark_max_dd_pct=0.0,
            strategy_sharpe=0.0,
            benchmark_sharpe=0.0,
            information_ratio=0.0,
            beats_benchmark=False,
            cost_drag_note=cost_drag_note,
        )
    s = s.iloc[:n].reset_index(drop=True)
    b = b.iloc[:n].reset_index(drop=True)
    # re-base both to 1.0
    s = s / float(s.iloc[0])
    b = b / float(b.iloc[0])
    ss = equity_stats(s, bars_per_year=bars_per_year)
    bs = equity_stats(b, bars_per_year=bars_per_year)
    excess = float(ss["return_pct"] - bs["return_pct"])
    # active returns for IR
    rs = s.pct_change().dropna()
    rb = b.pct_change().dropna()
    m = int(min(len(rs), len(rb)))
    if m < 2:
        ir = 0.0
    else:
        active = rs.iloc[:m].to_numpy() - rb.iloc[:m].to_numpy()
        std = float(np.std(active, ddof=1))
        ir = float(np.mean(active) / std * np.sqrt(bars_per_year)) if std > 0 else 0.0
    return ExcessReport(
        label=label,
        benchmark_label=benchmark_label,
        n_bars=n,
        strategy_return_pct=float(ss["return_pct"]),
        benchmark_return_pct=float(bs["return_pct"]),
        excess_return_pct=round(excess, 6),
        strategy_max_dd_pct=float(ss["max_dd_pct"]),
        benchmark_max_dd_pct=float(bs["max_dd_pct"]),
        strategy_sharpe=float(ss["sharpe"]),
        benchmark_sharpe=float(bs["sharpe"]),
        information_ratio=round(ir, 6),
        beats_benchmark=excess > 0.0,
        cost_drag_note=cost_drag_note,
    )


def gate_beats_benchmark(
    report: ExcessReport,
    *,
    require_positive_excess: bool = True,
    max_dd_not_worse_than_benchmark: bool = False,
) -> dict[str, Any]:
    """Product-style gate: must beat benchmark on total return (default)."""
    checks = {
        "excess_return_gt_0": report.excess_return_pct > 0.0,
    }
    if max_dd_not_worse_than_benchmark:
        checks["max_dd_le_benchmark"] = (
            report.strategy_max_dd_pct <= report.benchmark_max_dd_pct + 1e-9
        )
    ok = (
        all(checks.values()) if require_positive_excess else checks.get("max_dd_le_benchmark", True)
    )
    if require_positive_excess and max_dd_not_worse_than_benchmark:
        ok = all(checks.values())
    elif require_positive_excess:
        ok = bool(checks["excess_return_gt_0"])
    return {
        "decision": "PASS" if ok else "FAIL",
        "checks": checks,
        "report": report.to_dict(),
    }
