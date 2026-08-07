#!/usr/bin/env python3
"""Multi-strategy climate-adaptive WFO (option 2).

For each strategy (trend_following / volatility_breakout) and each sliding
window:
  1. Optimize params on the training window (Optuna, nested direction gate).
  2. Replay the optimized params on the FOLLOWING out-of-sample window.
  3. Keep only OOS-positive segments as climate-adaptive parameter library.

Then evaluate two portfolio constructions:
  A. Equal-weight average of OOS-positive segments' returns (vote by climate).
  B. Per-segment best-strategy pick (winner-take-all each forward window).

    python scripts/wfo_multi_climate.py [--trials 12] [--train-months 24]
"""

from __future__ import annotations

import argparse
import asyncio
import json
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

# Strategy-specific parameter spaces (production-path on_bar).
PARAM_SPACES: dict[str, dict[str, tuple[int, int] | tuple[float, float]]] = {
    "trend_following": {
        "fast_ma_period": (5, 40),
        "slow_ma_period": (20, 120),
        "atr_period": (7, 28),
        "atr_multiplier": (1.0, 4.0),
        "trailing_stop_atr_mult": (1.0, 6.0),
        "stop_loss_pct": (0.0, 0.05),
    },
    "volatility_breakout": {
        "atr_period": (7, 28),
        "atr_threshold": (1.0, 3.0),
        "bb_period": (10, 40),
        "bb_std": (1.5, 3.0),
        "volume_threshold": (1.0, 2.5),
        "trailing_stop_atr_mult": (1.0, 5.0),
        "stop_loss_pct": (0.0, 0.05),
        "max_holding_bars": (5, 40),
    },
}

# Gates that survived multi-window screening (nested best on large samples).
DEFAULT_GATE = "nested"


def _suggest(trial: Any, space: dict[str, tuple[int, int] | tuple[float, float]]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for name, (low, high) in space.items():
        if isinstance(low, int) and isinstance(high, int):
            params[name] = trial.suggest_int(name, low, high)
        else:
            step = 0.25 if name == "stop_loss_pct" else 0.1
            params[name] = trial.suggest_float(name, float(low), float(high), step=step)
    return params


async def _replay(
    strategy: str,
    params: dict[str, Any],
    bars_df: pd.DataFrame,
    symbol: str,
    gate: str | bool = DEFAULT_GATE,
) -> dict[str, float]:
    sink = RecordingSink()
    session = build_session(strategy, 100_000.0, sink, params=params)
    fills: list[dict[str, object]] = []
    risk: list[dict[str, object]] = []
    curve = await replay(session, bars_df, symbol, fills, risk, direction_gate=gate)
    rep = aggregate(curve, fills, risk, sink.alerts, 100_000.0)
    out: dict[str, float] = {}
    for k, v in rep.items():
        out[k] = float(v) if isinstance(v, (int, float)) else float("nan")
    return out


def _sharpe(rep: dict[str, float]) -> float:
    s = rep["sharpe_annualized"]
    return s if s == s else -10.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strategies", default="trend_following,volatility_breakout")
    ap.add_argument("--train-months", type=int, default=24)
    ap.add_argument("--fwd-months", type=int, default=6)
    ap.add_argument("--trials", type=int, default=12)
    ap.add_argument("--gate", default=DEFAULT_GATE)
    ap.add_argument("--end", default="2026-08-04")
    ap.add_argument(
        "--out",
        default="data/paper_replay/wfo_climate_library.json",
        help="climate-adaptive parameter library JSON",
    )
    args = ap.parse_args()

    import optuna

    from quantflow.data.store import DataStore

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    for s in strategies:
        if s not in PARAM_SPACES:
            raise SystemExit(f"Unknown strategy {s!r}. Available: {list(PARAM_SPACES)}")

    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    end_ms = int(pd.Timestamp(args.end).timestamp() * 1000)
    start_ms = end_ms - 2770 * 86_400_000
    df = store.query("BTC/USDT", start=start_ms, end=end_ms)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms")

    month_ms = 30 * 86_400_000
    train_ms = args.train_months * month_ms
    step_ms = args.fwd_months * month_ms
    first_end = int(df["dt"].min().timestamp() * 1000) + train_ms

    segments: list[tuple[int, int, int]] = []
    t_end = first_end
    while t_end + step_ms <= end_ms:
        segments.append((t_end - train_ms, t_end, t_end + step_ms))
        t_end += step_ms
    print(
        f"[climate] {len(segments)} segments x {len(strategies)} strategies | "
        f"train={args.train_months}m fwd={args.fwd_months}m trials={args.trials} | gate={args.gate}"
    )

    library: list[dict[str, Any]] = []
    # per-segment best across strategies for winner-take-all portfolio
    segment_winners: list[dict[str, Any]] = []
    # fair WTA: pick by train sharpe (no look-ahead into OOS)
    fair_winners: list[dict[str, Any]] = []

    for i, (s, tr_end, fwd_end) in enumerate(segments):
        train = df[
            (df["dt"] >= pd.to_datetime(s, unit="ms"))
            & (df["dt"] < pd.to_datetime(tr_end, unit="ms"))
        ].drop(columns="dt")
        fwd = df[
            (df["dt"] >= pd.to_datetime(tr_end, unit="ms"))
            & (df["dt"] < pd.to_datetime(fwd_end, unit="ms"))
        ].drop(columns="dt")

        seg_label = (
            f"{pd.Timestamp(tr_end, unit='ms').date()}→{pd.Timestamp(fwd_end, unit='ms').date()}"
        )
        best_for_seg: dict[str, Any] | None = None

        for strategy in strategies:
            space = PARAM_SPACES[strategy]

            def objective(
                trial: Any,
                train_df: pd.DataFrame = train,
                strat: str = strategy,
                space_: dict[str, tuple[int, int] | tuple[float, float]] = space,
            ) -> float:
                params = _suggest(trial, space_)
                rep = asyncio.run(_replay(strat, params, train_df, "BTC/USDT", args.gate))
                return _sharpe(rep)

            study = optuna.create_study(
                direction="maximize", sampler=optuna.samplers.TPESampler(seed=42)
            )
            study.optimize(objective, n_trials=args.trials, show_progress_bar=False)
            best = study.best_params
            oos = asyncio.run(_replay(strategy, best, fwd, "BTC/USDT", args.gate))
            entry = {
                "segment": i + 1,
                "strategy": strategy,
                "fwd": seg_label,
                "train_start": str(pd.Timestamp(s, unit="ms").date()),
                "train_end": str(pd.Timestamp(tr_end, unit="ms").date()),
                "fwd_start": str(pd.Timestamp(tr_end, unit="ms").date()),
                "fwd_end": str(pd.Timestamp(fwd_end, unit="ms").date()),
                "params": best,
                "train_sharpe": float(study.best_value),
                "oos_return_pct": float(oos["return_pct"]),
                "oos_sharpe": _sharpe(oos),
                "oos_orders": float(oos["orders"]),
                "oos_max_dd_pct": float(oos["max_drawdown_pct"]),
                "positive": float(oos["return_pct"]) > 0,
            }
            library.append(entry)
            print(
                f"  seg{i + 1} {strategy}: train_sh={entry['train_sharpe']:.3f} "
                f"OOS {entry['oos_return_pct']:+.2f}% sharpe={entry['oos_sharpe']:.3f} "
                f"trades={int(entry['oos_orders'])} "
                f"{'KEEP' if entry['positive'] else 'drop'}"
            )
            # Oracle WTA (look-ahead upper bound): pick by OOS return.
            if best_for_seg is None or entry["oos_return_pct"] > best_for_seg["oos_return_pct"]:
                best_for_seg = entry

        if best_for_seg is not None:
            segment_winners.append(best_for_seg)

        # Fair WTA (no look-ahead): pick strategy with highest train sharpe.
        seg_entries = [e for e in library if e["segment"] == i + 1]
        fair = max(seg_entries, key=lambda e: e["train_sharpe"])
        fair_winners.append(fair)
        print(
            f"  → fair-WTA: {fair['strategy']} "
            f"(train_sh={fair['train_sharpe']:.3f}) OOS {fair['oos_return_pct']:+.2f}%"
        )

    # ---- Portfolio constructions ----
    kept = [e for e in library if e["positive"]]
    print(f"\n[climate] library size: {len(kept)}/{len(library)} OOS-positive entries")

    # A: equal-weight average of kept segment returns (by strategy)
    by_strat: dict[str, list[float]] = {}
    for e in kept:
        by_strat.setdefault(e["strategy"], []).append(e["oos_return_pct"])
    print("[climate] A — equal-weight OOS-positive segments by strategy:")
    for strat, rets in by_strat.items():
        print(
            f"  {strat}: n={len(rets)} mean={sum(rets) / len(rets):+.2f}% "
            f"sum={sum(rets):+.2f}% pos_rate={sum(1 for r in rets if r > 0)}/{len(rets)}"
        )

    # B-oracle: winner-take-all by OOS (upper bound; has look-ahead, not deployable)
    wta_rets = [e["oos_return_pct"] for e in segment_winners]
    wta_pos = sum(1 for r in wta_rets if r > 0)
    print(
        f"[climate] B-oracle — WTA by OOS (look-ahead upper bound): n={len(wta_rets)} "
        f"sum={sum(wta_rets):+.2f}% mean={sum(wta_rets) / len(wta_rets):+.2f}% "
        f"pos_rate={wta_pos}/{len(wta_rets)}"
    )
    for e in segment_winners:
        print(
            f"  seg{e['segment']} winner={e['strategy']} "
            f"{e['oos_return_pct']:+.2f}% sharpe={e['oos_sharpe']:.3f}"
        )

    # B-fair: winner-take-all by train sharpe (no look-ahead; deployable rule)
    fair_rets = [e["oos_return_pct"] for e in fair_winners]
    fair_pos = sum(1 for r in fair_rets if r > 0)
    print(
        f"[climate] B-fair — WTA by train sharpe (no look-ahead): n={len(fair_rets)} "
        f"sum={sum(fair_rets):+.2f}% mean={sum(fair_rets) / len(fair_rets):+.2f}% "
        f"pos_rate={fair_pos}/{len(fair_rets)}"
    )
    for e in fair_winners:
        print(
            f"  seg{e['segment']} winner={e['strategy']} "
            f"train_sh={e['train_sharpe']:.3f} OOS {e['oos_return_pct']:+.2f}%"
        )

    # C: pure average of ALL segment OOS (no filtering) — baseline for comparison
    all_by_strat: dict[str, list[float]] = {}
    for e in library:
        all_by_strat.setdefault(e["strategy"], []).append(e["oos_return_pct"])
    print("[climate] C — unfiltered OOS mean (no climate filter):")
    for strat, rets in all_by_strat.items():
        print(f"  {strat}: mean={sum(rets) / len(rets):+.2f}% sum={sum(rets):+.2f}%")

    # Save library
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "gate": args.gate,
        "train_months": args.train_months,
        "fwd_months": args.fwd_months,
        "trials": args.trials,
        "strategies": strategies,
        "library": kept,
        "all_segments": library,
        "winners": segment_winners,
        "fair_winners": fair_winners,
        "summary": {
            "kept": len(kept),
            "total": len(library),
            "wta_sum_pct": sum(wta_rets),
            "wta_mean_pct": sum(wta_rets) / len(wta_rets) if wta_rets else 0.0,
            "wta_pos_rate": f"{wta_pos}/{len(wta_rets)}",
            "fair_wta_sum_pct": sum(fair_rets),
            "fair_wta_mean_pct": sum(fair_rets) / len(fair_rets) if fair_rets else 0.0,
            "fair_wta_pos_rate": f"{fair_pos}/{len(fair_rets)}",
        },
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[climate] library written: {out_path}")

    # Pass gate: fair-WTA cumulative positive AND kept library non-empty.
    # Oracle WTA is reported only as an upper-bound reference.
    ok = sum(fair_rets) > 0 and len(kept) > 0
    print(
        f"[climate] {'PASS' if ok else 'FAIL'}: fair-WTA cumulative "
        f"{'+' if ok else '<='}0 and library non-empty"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
