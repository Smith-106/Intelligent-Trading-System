#!/usr/bin/env python3
"""Diagnose mean_reversion F5 trade-shuffle red flag (ISS-20260720-003).

P1-verify reported prob_worse_drawdown=0.775 for mean_reversion via the
returns-bootstrap method (>0.7 NO-GO flag). That measures bar-level resampling.
This script runs the complementary TRADE-SHUFFLE method on per-trade returns
to isolate sequencing risk: "if the losers had clustered early, how deep would
the drawdown get?" — independent of any return-distribution assumption.

It also prints the trade-return distribution (count, win rate, largest loss,
loss-clustering index) so the root cause of the order-sensitivity is visible:
a high prob_worse_drawdown means the observed sequence was lucky (losses
spread out / late); the fix direction is position sizing or stop logic, not
the signal.

Trade returns come from BacktestEngine.run_backtest on mean_reversion's
generate_signals. Note: generate_signals does NOT apply the regime gate
(ISS-20260720-001 two-layer design), so this trades a superset of live/paper
— appropriate for diagnosing the strategy's trade-shape, not for live parity.

Usage:
    python scripts/diagnose_mean_reversion_f5.py --symbol BTC/USDT
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from quantflow.strategy.research.backtest import BacktestEngine  # noqa: E402
from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy  # noqa: E402
from quantflow.strategy.validation.monte_carlo import (  # noqa: E402
    trade_shuffle_stress,
)
from scripts.replay_paper_f4f5 import load_bars  # noqa: E402

CAPITAL = 100_000.0


def diagnose(trade_returns: list[float]) -> dict:
    r = np.array(trade_returns, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)
    wins = r[r > 0]
    losses = r[r < 0]
    win_rate = len(wins) / n if n else 0.0
    largest_loss = float(losses.min()) if len(losses) else 0.0
    largest_win = float(wins.max()) if len(wins) else 0.0
    # Loss-clustering: fraction of losses in the first half of the sequence.
    # Low → losses spread late (observed path lucky); high → losses early (unlucky).
    half = n // 2
    losses_first_half = int(np.sum(r[:half] < 0)) if half > 0 else 0
    losses_total = int(np.sum(r < 0))
    loss_first_half_frac = (losses_first_half / losses_total) if losses_total else 0.0

    mc = trade_shuffle_stress(r, n_paths=1000, initial_capital=CAPITAL, seed=0)
    return {
        "n_trades": n,
        "win_rate": win_rate,
        "largest_loss": largest_loss,
        "largest_win": largest_win,
        "losses_total": losses_total,
        "loss_first_half_frac": loss_first_half_frac,
        "observed_max_dd": mc.observed_max_drawdown,
        "p5_max_dd": mc.p5_max_drawdown,
        "p50_max_dd": mc.p50_max_drawdown,
        "prob_worse_dd": mc.prob_worse_drawdown,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--max-bars", type=int, default=None)
    ap.add_argument("--parquet-dir", default="./data/parquet")
    args = ap.parse_args()

    bars_df = load_bars(args.parquet_dir, args.symbol, args.timeframe, args.max_bars)
    strat = MeanReversionStrategy()
    entries, exits = strat.generate_signals(bars_df)

    # Direction series: mean_reversion emits both LONG and SHORT. Derive per-bar
    # direction from which entry condition fired (long_count vs short_count) by
    # re-running the vectorized conditions is complex; use the strategy's own
    # signal by checking entry sign from close vs bb. Simpler: run backtest as
    # LONG-only and SHORT-only and union — but that double-counts. Instead, use
    # the generate_signals entries with a per-bar direction inferred from the
    # BB position at the entry bar (below lower band → LONG, above upper → SHORT).
    import pandas as pd

    close = bars_df["close"]
    bb_mid = close.rolling(strat._bb_period).mean()
    bb_std = close.rolling(strat._bb_period).std()
    bb_upper = bb_mid + strat._bb_std * bb_std
    bb_lower = bb_mid - strat._bb_std * bb_std
    direction = pd.Series(1, index=close.index, dtype=int)
    direction[(entries) & (close > bb_upper)] = -1  # SHORT entries
    direction[(entries) & (close < bb_lower)] = 1  # LONG entries

    bt = BacktestEngine()
    result = bt.run_backtest(
        close=close,
        entries=entries,
        exits=exits,
        initial_capital=CAPITAL,
        fee=0.001,
        strategy_id="mean_reversion",
        symbol=args.symbol,
        direction=direction,
    )
    trade_returns = result.trade_returns

    print("\n=== mean_reversion F5 trade-shuffle root-cause (ISS-20260720-003) ===")
    print(f"symbol / timeframe   : {args.symbol} / {args.timeframe}")
    print(f"bars                 : {len(bars_df)}")
    if len(trade_returns) < 2:
        print(f"[!] only {len(trade_returns)} closed trades — insufficient for trade-shuffle")
        print("    (checklist requires >=20 for statistical significance)")
        return 2

    d = diagnose(trade_returns)
    print("\n--- trade-return distribution ---")
    print(f"  closed trades       : {d['n_trades']}")
    print(f"  win rate            : {d['win_rate']:.3f}")
    print(f"  largest win / loss  : {d['largest_win']:.5f} / {d['largest_loss']:.5f}")
    print(f"  losses total        : {d['losses_total']}")
    print(
        f"  loss-in-first-half  : {d['loss_first_half_frac']:.3f}  "
        "(low = losses spread late → observed path lucky)"
    )

    print("\n--- trade-shuffle stress (1000 permuted paths) ---")
    print(f"  observed max_dd     : {d['observed_max_dd']:.5f}")
    print(f"  P5 max_dd (worst)   : {d['p5_max_dd']:.5f}")
    print(f"  P50 max_dd (median) : {d['p50_max_dd']:.5f}")
    print(
        f"  prob_worse_dd       : {d['prob_worse_dd']:.3f}  "
        "(>0.7 NO-GO: observed path unusually lucky)"
    )

    print("\n--- root-cause reading ---")
    if d["prob_worse_dd"] > 0.7:
        print("  ⚠️ NO-GO flag confirmed: observed drawdown is shallower than 70%+ of")
        print("     shuffled orderings → the live sequence was lucky (losses did NOT cluster")
        print("     early). An adverse ordering would draw down materially deeper.")
        if d["loss_first_half_frac"] < 0.4 and d["losses_total"] > 0:
            print(
                f"  → loss-in-first-half={d['loss_first_half_frac']:.3f} confirms losses clustered"
            )
            print("     LATE in the observed path (luck). Root cause = trade-shape, not signal.")
        print("  Fix direction: reduce position size (vol-target / Kelly fraction) or add a")
        print("     stop-loss so a clustered-loss sequence cannot deepen drawdown unbounded.")
    elif d["prob_worse_dd"] <= 0.5:
        print("  ✅ healthy: observed drawdown is at or deeper than the median shuffled path")
        print("     (sequence not unusually lucky).")
    else:
        print(f"  ⚠️ yellow: prob_worse_dd={d['prob_worse_dd']:.3f} (0.5..0.7) — mild sequencing")
        print("     sensitivity; monitor.")

    if d["n_trades"] < 20:
        print(f"\n  [note] only {d['n_trades']} trades < 20 — statistical significance limited")
        print("     (checklist P1.2-V1 requires >=20). Re-verify after more data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
