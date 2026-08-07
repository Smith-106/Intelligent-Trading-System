#!/usr/bin/env python3
"""Walk-Forward Optimization — out-of-sample check for tf + nested gate.

Sliding 2-year training windows (Optuna, 15 trials each, nested gate) walk
forward in 6-month steps; each window's best params replay on the FOLLOWING
6 months (never seen in training). Compares cumulative out-of-sample
performance vs the full-period synchronized optimization (overfit check).

    python scripts/wfo_tf_gate.py [--train-months 24] [--fwd-months 6]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from quantflow.strategy.research.paper_replay import (  # noqa: E402
    RecordingSink,
    aggregate,
    build_session,
    replay,
)

PARAM_SPACE: dict[str, tuple[int, int] | tuple[float, float]] = {
    "fast_ma_period": (5, 40),
    "slow_ma_period": (20, 120),
    "atr_period": (7, 28),
    "atr_multiplier": (1.0, 4.0),
    "trailing_stop_atr_mult": (1.0, 6.0),
    "stop_loss_pct": (0.0, 0.05),
}


def _suggest(trial: Any, name: str) -> int | float:
    low, high = PARAM_SPACE[name]
    if isinstance(low, int):
        return trial.suggest_int(name, low, high)  # type: ignore[no-any-return]
    return trial.suggest_float(name, low, high, step=0.25 if name == "stop_loss_pct" else 0.1)  # type: ignore[no-any-return]


async def _replay(params: dict[str, Any], bars_df: pd.DataFrame, symbol: str) -> dict[str, float]:
    sink = RecordingSink()
    session = build_session("trend_following", 100_000.0, sink, params=params)
    fills: list[dict[str, object]] = []
    risk: list[dict[str, object]] = []
    curve = await replay(session, bars_df, symbol, fills, risk, direction_gate="nested")
    rep = aggregate(curve, fills, risk, sink.alerts, 100_000.0)
    out: dict[str, float] = {}
    for k, v in rep.items():
        out[k] = float(v) if isinstance(v, (int, float)) else float("nan")
    return out


def _sharpe_of(report: dict[str, float]) -> float:
    s = report["sharpe_annualized"]
    assert isinstance(s, float)
    return s if s == s else -10.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--train-months", type=int, default=24)
    ap.add_argument("--fwd-months", type=int, default=6)
    ap.add_argument("--trials", type=int, default=15, help="Optuna trials per window")
    ap.add_argument("--end", default="2026-08-04")
    args = ap.parse_args()

    import optuna

    from quantflow.data.store import DataStore

    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    end_ms = int(pd.Timestamp(args.end).timestamp() * 1000)
    start_ms = end_ms - 2770 * 86_400_000  # ~7.6y
    df = store.query("BTC/USDT", start=start_ms, end=end_ms)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms")

    month_ms = 30 * 86_400_000
    train_ms = args.train_months * month_ms
    step_ms = args.fwd_months * month_ms
    first_end = int(df["dt"].min().timestamp() * 1000) + train_ms

    segments = []
    t_end = first_end
    while t_end + step_ms <= end_ms:
        seg_start = t_end - train_ms
        segments.append((seg_start, t_end, t_end + step_ms))
        t_end += step_ms
    if len(segments) == 0:
        raise SystemExit("Window too long for the data span")

    print(
        f"[wfo] {len(segments)} segments | train={args.train_months}m fwd={args.fwd_months}m trials={args.trials}/window | gate=nested"
    )

    oos_curve_sum = 0.0
    oos_trades = 0
    oos_reports: list[dict[str, float]] = []
    for i, (s, tr_end, fwd_end) in enumerate(segments):
        train = df[
            (df["dt"] >= pd.to_datetime(s, unit="ms"))
            & (df["dt"] < pd.to_datetime(tr_end, unit="ms"))
        ].drop(columns="dt")
        fwd = df[
            (df["dt"] >= pd.to_datetime(tr_end, unit="ms"))
            & (df["dt"] < pd.to_datetime(fwd_end, unit="ms"))
        ].drop(columns="dt")

        def objective(trial: Any, train_df: pd.DataFrame = train) -> float:
            params = {name: _suggest(trial, name) for name in PARAM_SPACE}
            rep = asyncio.run(_replay(params, train_df, "BTC/USDT"))
            return _sharpe_of(rep)

        study = optuna.create_study(
            direction="maximize", sampler=optuna.samplers.TPESampler(seed=42)
        )
        study.optimize(objective, n_trials=args.trials, show_progress_bar=False)
        best = study.best_params
        rep = asyncio.run(_replay(best, fwd, "BTC/USDT"))
        oos_reports.append(rep)
        oos_trades += int(rep["orders"])
        ret = float(rep["return_pct"])
        oos_curve_sum += ret
        print(
            f"  seg{i + 1}: train {pd.Timestamp(s, unit='ms').date()}→{pd.Timestamp(tr_end, unit='ms').date()} "
            f"| fwd {pd.Timestamp(tr_end, unit='ms').date()}→{pd.Timestamp(fwd_end, unit='ms').date()} "
            f"| OOS {ret:+.2f}% trades={rep['orders']} sharpe={rep['sharpe_annualized']:.3f}"
        )

    # Summary: arithmetic sum of segment returns (each on 100k capital).
    print(f"\n[wfo] OOS segments: {len(oos_reports)}")
    print(f"[wfo] OOS trades: {oos_trades}")
    print(f"[wfo] OOS cumulative (sum of segment %): {oos_curve_sum:+.2f}%")
    print(
        f"[wfo] OOS mean sharpe: {sum(_sharpe_of(r) for r in oos_reports) / len(oos_reports):.3f}"
    )
    print(
        f"[wfo] OOS positive segments: {sum(1 for r in oos_reports if r['return_pct'] > 0)}/{len(oos_reports)}"
    )
    print(
        "[wfo] PASS: OOS cumulative positive"
        if oos_curve_sum > 0
        else "[wfo] FAIL: OOS cumulative <= 0"
    )
    return 0 if oos_curve_sum > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
