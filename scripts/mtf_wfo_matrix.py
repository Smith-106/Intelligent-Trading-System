#!/usr/bin/env python3
"""Multi-timeframe paper-replay + light WFO matrix.

For each available TF in the local store:
  1. Full-window default-params replay with nested direction gate
  2. Sliding WFO (train/fwd/trials scaled by TF coarseness)
  3. Emit JSON summary for cross-TF comparison

    python scripts/mtf_wfo_matrix.py
    python scripts/mtf_wfo_matrix.py --tfs 1h,4h,1d --trials-coarse 8
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
    bars_per_year,
    build_session,
    nested_htf_for,
    replay,
)

DEFAULT_TFS = ["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]
FINE_TFS = {"5m", "15m", "30m"}

# 1h-native bar counts (legacy default used when --space-mode=fixed).
TF_PARAM_SPACE_1H: dict[str, dict[str, tuple[int, int] | tuple[float, float]]] = {
    "trend_following": {
        "fast_ma_period": (5, 40),
        "slow_ma_period": (20, 120),
        "atr_period": (7, 28),
        "atr_multiplier": (1.0, 4.0),
        "trailing_stop_atr_mult": (1.0, 6.0),
        "stop_loss_pct": (0.0, 0.05),
        "max_holding_bars": (10, 60),
    },
}

# Wall-clock lookback ranges (hours) — scaled to bar counts per entry TF.
# Intent: 4h/6h should search similar *calendar* horizons as 1h, not the same
# bar counts (which would be 4–6× longer in time and over-smooth).
_WALL_HOURS: dict[str, tuple[float, float]] = {
    "fast_ma_period": (6.0, 48.0),  # ~0.25–2 days
    "slow_ma_period": (24.0, 240.0),  # ~1–10 days
    "atr_period": (12.0, 72.0),  # ~0.5–3 days
    "volume_period": (12.0, 72.0),
    "max_holding_bars": (24.0, 240.0),  # hold 1–10 days
}

_TF_HOURS: dict[str, float] = {
    "5m": 5 / 60,
    "15m": 0.25,
    "30m": 0.5,
    "1h": 1.0,
    "2h": 2.0,
    "4h": 4.0,
    "6h": 6.0,
    "12h": 12.0,
    "1d": 24.0,
}


def _clamp_int_range(
    low: float, high: float, min_low: int = 2, max_high: int = 200
) -> tuple[int, int]:
    lo = max(min_low, round(low))
    hi = max(lo + 1, min(max_high, round(high)))
    return int(lo), int(hi)


def param_space_for_tf(
    strategy: str,
    entry_tf: str,
    mode: str = "scaled",
) -> dict[str, tuple[int, int] | tuple[float, float]]:
    """Return Optuna search space for strategy on entry_tf.

    mode:
      - fixed: always the 1h bar-count ranges (legacy; under-fits high TF)
      - scaled: convert wall-clock hour ranges into bar counts for entry_tf
    """
    base = TF_PARAM_SPACE_1H.get(strategy)
    if base is None:
        raise KeyError(f"No param space for strategy {strategy!r}")
    if mode == "fixed" or entry_tf == "1h":
        return dict(base)

    hours = _TF_HOURS.get(entry_tf, 1.0)
    space: dict[str, tuple[int, int] | tuple[float, float]] = {
        "atr_multiplier": (1.0, 4.0),
        "trailing_stop_atr_mult": (1.0, 6.0),
        "stop_loss_pct": (0.0, 0.05),
    }
    for key, (h_lo, h_hi) in _WALL_HOURS.items():
        space[key] = _clamp_int_range(h_lo / hours, h_hi / hours)
    # Enforce slow > fast headroom: slow_min at least fast_min+2
    f_lo, _f_hi = space["fast_ma_period"]
    s_lo, s_hi = space["slow_ma_period"]
    assert isinstance(f_lo, int) and isinstance(s_lo, int) and isinstance(s_hi, int)
    s_lo = max(s_lo, f_lo + 2)
    if s_lo >= s_hi:
        s_hi = s_lo + 5
    space["slow_ma_period"] = (s_lo, s_hi)
    return space


# Back-compat alias
TF_PARAM_SPACE = TF_PARAM_SPACE_1H


def _suggest(trial: Any, space: dict[str, tuple[int, int] | tuple[float, float]]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for name, (low, high) in space.items():
        if isinstance(low, int) and isinstance(high, int):
            params[name] = trial.suggest_int(name, low, high)
        else:
            # stop_loss uses 0.5% steps (was 0.25 which collapsed [0,0.05] badly)
            step = 0.005 if name == "stop_loss_pct" else 0.1
            params[name] = trial.suggest_float(name, float(low), float(high), step=step)
    # Soft constraint: slow > fast when both present
    if "fast_ma_period" in params and "slow_ma_period" in params:
        if params["slow_ma_period"] <= params["fast_ma_period"]:
            params["slow_ma_period"] = int(params["fast_ma_period"]) + 2
    return params


async def _eval(
    strategy: str,
    params: dict[str, Any] | None,
    bars: pd.DataFrame,
    symbol: str,
    entry_tf: str,
    gate: str | bool,
) -> dict[str, float]:
    sink = RecordingSink()
    session = build_session(strategy, 100_000.0, sink, params=params)
    fills: list[dict[str, object]] = []
    risk: list[dict[str, object]] = []
    curve = await replay(session, bars, symbol, fills, risk, direction_gate=gate, entry_tf=entry_tf)
    rep = aggregate(curve, fills, risk, sink.alerts, 100_000.0, entry_tf=entry_tf)
    out: dict[str, float] = {}
    for k, v in rep.items():
        if isinstance(v, (int, float)):
            out[k] = float(v)
        elif v is None and k == "sharpe_annualized":
            out[k] = float("nan")
    return out


def _sharpe(rep: dict[str, float]) -> float:
    s = rep.get("sharpe_annualized", float("nan"))
    return s if s == s else -10.0


def _load_tf(store: Any, symbol: str, tf: str, end_ms: int, start_ms: int | None) -> pd.DataFrame:
    df = store.query(symbol, start=start_ms, end=end_ms, timeframe=tf)
    if df.empty:
        return df
    return df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--tfs", default=",".join(DEFAULT_TFS))
    ap.add_argument("--strategy", default="trend_following")
    ap.add_argument("--gate", default="nested")
    ap.add_argument("--end", default="2026-08-04")
    ap.add_argument("--trials-coarse", type=int, default=8)
    ap.add_argument("--trials-fine", type=int, default=5)
    ap.add_argument("--skip-wfo", action="store_true")
    ap.add_argument(
        "--space-mode",
        choices=["scaled", "fixed"],
        default="scaled",
        help="scaled=wall-clock lookbacks per TF; fixed=1h bar-count ranges",
    )
    ap.add_argument("--out", default="data/paper_replay/mtf_matrix.json")
    args = ap.parse_args()

    import optuna

    from quantflow.data.store import DataStore

    tfs = [t.strip() for t in args.tfs.split(",") if t.strip()]
    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    end_ms = int(pd.Timestamp(args.end).timestamp() * 1000)
    month_ms = 30 * 86_400_000

    rows: list[dict[str, Any]] = []
    for tf in tfs:
        print(f"\n=== TF {tf} (nested HTF={nested_htf_for(tf)}, bpy={bars_per_year(tf):.0f}) ===")
        df = _load_tf(store, args.symbol, tf, end_ms, None)
        if df.empty or len(df) < 500:
            print(f"  SKIP: insufficient bars ({len(df)})")
            rows.append(
                {
                    "timeframe": tf,
                    "status": "skipped_insufficient",
                    "bars": len(df),
                }
            )
            continue

        # Full-window default + nested
        full = asyncio.run(_eval(args.strategy, None, df, args.symbol, tf, args.gate))
        print(
            f"  full default+{args.gate}: ret={full.get('return_pct', float('nan')):+.2f}% "
            f"maxDD={full.get('max_drawdown_pct', float('nan')):.2f}% "
            f"sharpe={full.get('sharpe_annualized', float('nan'))} orders={full.get('orders', 0)}"
        )

        row: dict[str, Any] = {
            "timeframe": tf,
            "status": "ok",
            "bars": len(df),
            "nested_htf": nested_htf_for(tf),
            "space_mode": args.space_mode,
            "bars_per_year": bars_per_year(tf),
            "full_return_pct": full.get("return_pct"),
            "full_max_dd_pct": full.get("max_drawdown_pct"),
            "full_sharpe": full.get("sharpe_annualized"),
            "full_orders": full.get("orders"),
        }

        if args.skip_wfo:
            rows.append(row)
            continue

        # Scale WFO windows by TF
        if tf in FINE_TFS:
            train_m, fwd_m, trials = 12, 3, args.trials_fine
        else:
            train_m, fwd_m, trials = 24, 6, args.trials_coarse

        df = df.copy()
        df["dt"] = pd.to_datetime(df["timestamp"], unit="ms")
        train_ms = train_m * month_ms
        step_ms = fwd_m * month_ms
        first_end = int(df["dt"].min().timestamp() * 1000) + train_ms
        segments: list[tuple[int, int, int]] = []
        t_end = first_end
        data_end = int(df["dt"].max().timestamp() * 1000)
        while t_end + step_ms <= min(end_ms, data_end + 1):
            segments.append((t_end - train_ms, t_end, t_end + step_ms))
            t_end += step_ms
        # Cap segments for fine TF cost control
        if tf in FINE_TFS and len(segments) > 8:
            segments = segments[-8:]

        if len(segments) < 2:
            print(f"  WFO SKIP: only {len(segments)} segments")
            row["wfo_status"] = "skipped_short"
            rows.append(row)
            continue

        oos_rets: list[float] = []
        oos_sharpes: list[float] = []
        space = param_space_for_tf(args.strategy, tf, mode=args.space_mode)
        print(f"  space[{args.space_mode}]: {space}")
        for i, (s, tr_end, fwd_end) in enumerate(segments):
            train = df[
                (df["dt"] >= pd.to_datetime(s, unit="ms"))
                & (df["dt"] < pd.to_datetime(tr_end, unit="ms"))
            ].drop(columns="dt")
            fwd = df[
                (df["dt"] >= pd.to_datetime(tr_end, unit="ms"))
                & (df["dt"] < pd.to_datetime(fwd_end, unit="ms"))
            ].drop(columns="dt")
            if len(train) < 200 or len(fwd) < 50:
                continue

            def objective(
                trial: Any,
                train_df: pd.DataFrame = train,
                etf: str = tf,
                space_: dict[str, tuple[int, int] | tuple[float, float]] = space,
            ) -> float:
                params = _suggest(trial, space_)
                rep = asyncio.run(
                    _eval(args.strategy, params, train_df, args.symbol, etf, args.gate)
                )
                return _sharpe(rep)

            study = optuna.create_study(
                direction="maximize", sampler=optuna.samplers.TPESampler(seed=42)
            )
            study.optimize(objective, n_trials=trials, show_progress_bar=False)
            oos = asyncio.run(
                _eval(args.strategy, study.best_params, fwd, args.symbol, tf, args.gate)
            )
            oos_rets.append(float(oos.get("return_pct", 0.0)))
            oos_sharpes.append(_sharpe(oos))
            print(
                f"  seg{i + 1}/{len(segments)} OOS {oos_rets[-1]:+.2f}% sharpe={oos_sharpes[-1]:.3f}"
            )

        if oos_rets:
            row.update(
                {
                    "wfo_status": "ok",
                    "wfo_segments": len(oos_rets),
                    "wfo_oos_sum_pct": sum(oos_rets),
                    "wfo_oos_mean_pct": sum(oos_rets) / len(oos_rets),
                    "wfo_oos_mean_sharpe": sum(oos_sharpes) / len(oos_sharpes),
                    "wfo_pos_rate": f"{sum(1 for r in oos_rets if r > 0)}/{len(oos_rets)}",
                    "wfo_train_months": train_m,
                    "wfo_fwd_months": fwd_m,
                    "wfo_trials": trials,
                }
            )
            print(
                f"  WFO summary: sum={row['wfo_oos_sum_pct']:+.2f}% "
                f"mean_sh={row['wfo_oos_mean_sharpe']:.3f} pos={row['wfo_pos_rate']}"
            )
        else:
            row["wfo_status"] = "no_segments_eval"
        rows.append(row)

    store.close()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol": args.symbol,
        "strategy": args.strategy,
        "gate": args.gate,
        "end": args.end,
        "space_mode": args.space_mode,
        "rows": rows,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[matrix] written {out_path}")
    print(f"{'TF':>4} {'bars':>8} {'full%':>8} {'fullSh':>7} {'OOSsum':>8} {'OOSsh':>7} {'pos':>6}")
    for r in rows:
        if r.get("status") != "ok":
            print(f"{r['timeframe']:>4} {'—':>8} skip={r.get('status')}")
            continue
        print(
            f"{r['timeframe']:>4} {r['bars']:>8} "
            f"{r.get('full_return_pct', float('nan')):>+8.2f} "
            f"{(r.get('full_sharpe') or float('nan')):>7.3f} "
            f"{r.get('wfo_oos_sum_pct', float('nan')):>+8.2f} "
            f"{r.get('wfo_oos_mean_sharpe', float('nan')):>7.3f} "
            f"{r.get('wfo_pos_rate', '—'):>6}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
