#!/usr/bin/env python3
"""Optuna parameter optimization on the PRODUCTION paper-replay path.

Unlike ``quantflow optimize`` (vectorized generate_signals, no regime gate,
no direction gate), this optimizer evaluates every trial through
TradingSession.on_bar in paper mode — with optional direction gate — so the
optimized parameters reflect exactly what production would trade.

    python scripts/optimize_tf_gate.py --gate nested --trials 60
    python scripts/optimize_tf_gate.py --gate none --days 1461 --trials 40
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

# trend_following parameter space (templates/trend_following.py).
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


async def _evaluate(
    params: dict[str, Any], bars_df: pd.DataFrame, symbol: str, gate: str | None
) -> float:
    sink = RecordingSink()
    session = build_session("trend_following", 100_000.0, sink, params=params)
    fills: list[dict[str, object]] = []
    risk: list[dict[str, object]] = []
    curve = await replay(
        session,
        bars_df,
        symbol,
        fills,
        risk,
        direction_gate=gate or False,
    )
    report = aggregate(curve, fills, risk, sink.alerts, 100_000.0)
    sharpe = report["sharpe_annualized"]
    assert isinstance(sharpe, float)
    return sharpe if sharpe == sharpe else -10.0  # NaN-safe


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--gate", default="nested", choices=["none", "sma", "ema", "slope", "dual", "nested"]
    )
    ap.add_argument("--trials", type=int, default=60)
    ap.add_argument("--days", type=int, default=2770, help="full-history window")
    ap.add_argument("--end", default=None, help="window end YYYY-MM-DD")
    args = ap.parse_args()

    import optuna

    from quantflow.data.store import DataStore

    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    end_ms = (
        int(pd.Timestamp(args.end).timestamp() * 1000)
        if args.end
        else int(pd.Timestamp.now().timestamp() * 1000)
    )
    df = store.query("BTC/USDT", start=end_ms - args.days * 86_400_000, end=end_ms)
    if df.empty or "close" not in df.columns:
        raise SystemExit("No BTC/USDT data in window; run download first")
    bars_df = df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    print(f"[optimize] {len(bars_df)} bars | gate={args.gate} | trials={args.trials}")

    gate_arg: str | None = None if args.gate == "none" else args.gate

    def objective(trial: Any) -> float:
        params = {name: _suggest(trial, name) for name in PARAM_SPACE}
        sharpe = asyncio.run(_evaluate(params, bars_df, "BTC/USDT", gate_arg))
        return float(sharpe) if sharpe == sharpe else -10.0

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=args.trials, show_progress_bar=False)

    best = study.best_params
    print(f"[optimize] best sharpe={study.best_value:.4f}")
    for k, v in best.items():
        print(f"  {k} = {v}")
    # Final verification replay with the best params.
    sharpe = asyncio.run(_evaluate(best, bars_df, "BTC/USDT", gate_arg))
    print(f"[optimize] best-params replayed sharpe={sharpe:.4f} (gate={args.gate})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
