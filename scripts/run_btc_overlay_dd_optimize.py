#!/usr/bin/env python3
"""Deep optimize BTC beta+overlay: raise excess, cut max drawdown (taker costs).

Design levers (on top of dual-MA long/flat overlay):
  - mode: reduce_off | add_on
  - MA pair (fast, slow)
  - overlay weight
  - DD throttle: scale exposure toward cash/beta when live equity DD exceeds threshold
  - vol target: scale overlay by rolling vol vs target
  - hysteresis: enter/exit MA bands to cut churn

Product gate: excess vs BTC HODL after fee+slip on overlay rebalances.
Honesty: in-sample / cost-aware selection on pin window — not pure OOS alpha.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quantflow.data.store import DataStore  # noqa: E402
from quantflow.strategy.research.benchmark_excess import (  # noqa: E402
    buy_hold_equity_from_close,
    equity_stats,
    excess_vs_benchmark,
    gate_beats_benchmark,
)
from quantflow.strategy.research.contract_pin import parse_window_ms  # noqa: E402

DEFAULT_START = "2021-01-01"
DEFAULT_END = "2026-08-04"
DEFAULT_OUT = ROOT / "data" / "paper_replay" / "beta_overlay" / "dd_optimize.json"
BASELINE = {
    "mode": "reduce_off",
    "overlay_weight": 0.25,
    "fast": 96,
    "slow": 400,
    "dd_throttle": 0.0,
    "dd_floor_scale": 0.0,
    "vol_target": 0.0,
    "vol_window": 168,
    "hysteresis": 0.0,
}


@dataclass(frozen=True)
class Cfg:
    mode: str = "reduce_off"
    overlay_weight: float = 0.25
    fast: int = 96
    slow: int = 400
    fee: float = 0.001
    slip: float = 0.001
    # When peak-to-trough DD of *strategy equity so far* exceeds dd_throttle,
    # multiply active exposure by lerp toward dd_floor_scale (0=flat, 1=no cut).
    dd_throttle: float = 0.0  # e.g. 0.25 = start cutting after 25% DD
    dd_floor_scale: float = 0.35  # residual scale at deep DD
    vol_target: float = 0.0  # annualized vol target for overlay sleeve; 0=off
    vol_window: int = 168  # 1h bars (~1w)
    hysteresis: float = 0.0  # require |fast-slow|/slow > h to flip

    def key(self) -> tuple[Any, ...]:
        return (
            self.mode,
            self.overlay_weight,
            self.fast,
            self.slow,
            self.dd_throttle,
            self.dd_floor_scale,
            self.vol_target,
            self.vol_window,
            self.hysteresis,
            self.fee,
            self.slip,
        )


def _load_btc_1h(start: str, end: str) -> pd.DataFrame:
    start_ms, end_ms = parse_window_ms(start, end)
    store = DataStore("data/parquet", ":memory:")
    try:
        df = store.query("BTC/USDT", start=start_ms, end=end_ms, timeframe="1h")
    finally:
        store.close()
    if df is None or df.empty:
        raise SystemExit("no BTC/USDT 1h bars")
    return df.sort_values("timestamp").reset_index(drop=True)


def _ma_signal(close: pd.Series, fast: int, slow: int, hysteresis: float) -> np.ndarray:
    c = close.astype(float)
    f = c.rolling(fast, min_periods=fast).mean()
    s = c.rolling(slow, min_periods=slow).mean()
    raw = (f > s).astype(float).to_numpy()
    if hysteresis <= 0:
        return pd.Series(raw).shift(1).fillna(0.0).to_numpy()
    # band: only flip when relative gap exceeds hysteresis
    gap = ((f - s) / s.replace(0, np.nan)).to_numpy()
    n = len(c)
    sig = np.zeros(n, dtype=float)
    state = 0.0
    for i in range(n):
        g = gap[i]
        if not np.isfinite(g):
            sig[i] = state
            continue
        if state < 0.5 and g > hysteresis:
            state = 1.0
        elif state >= 0.5 and g < -hysteresis:
            state = 0.0
        sig[i] = state
    # trade next bar
    out = np.zeros(n, dtype=float)
    out[1:] = sig[:-1]
    return out


def _rolling_vol_ann(close: pd.Series, window: int) -> np.ndarray:
    r = close.astype(float).pct_change()
    v = r.rolling(window, min_periods=max(24, window // 4)).std() * np.sqrt(8760.0)
    return v.bfill().fillna(0.5).to_numpy()


def simulate(close: pd.Series, cfg: Cfg) -> tuple[pd.Series, dict[str, Any]]:
    c = close.astype(float).to_numpy()
    n = len(c)
    if n < cfg.slow + 5:
        raise SystemExit(f"need more bars than slow={cfg.slow}, got {n}")
    sig = _ma_signal(close.astype(float), cfg.fast, cfg.slow, cfg.hysteresis)
    if cfg.vol_target > 0:
        vol = _rolling_vol_ann(close.astype(float), cfg.vol_window)
        # scale overlay sleeve toward target; clip
        vol_scale = np.clip(cfg.vol_target / np.maximum(vol, 1e-6), 0.25, 1.5)
    else:
        vol_scale = np.ones(n, dtype=float)

    eq = np.ones(n, dtype=float)
    peak = 1.0
    overlay_pos = 0.0
    cost_rate = cfg.fee + cfg.slip
    turnover = 0.0
    w = cfg.overlay_weight

    for i in range(1, n):
        r = c[i] / c[i - 1] - 1.0
        # live DD of equity so far
        peak = max(peak, eq[i - 1])
        dd = 1.0 - eq[i - 1] / peak if peak > 0 else 0.0
        if cfg.dd_throttle > 0 and dd > cfg.dd_throttle:
            # linear cut from 1.0 at threshold toward floor at 2x threshold
            span = max(cfg.dd_throttle, 1e-6)
            t = min(1.0, (dd - cfg.dd_throttle) / span)
            risk_scale = (1.0 - t) + t * cfg.dd_floor_scale
        else:
            risk_scale = 1.0

        target = float(sig[i]) * float(vol_scale[i]) * risk_scale
        target = float(np.clip(target, 0.0, 1.0))
        if abs(target - overlay_pos) > 1e-12:
            delta = abs(target - overlay_pos)
            eq[i - 1] *= 1.0 - delta * w * cost_rate
            turnover += delta * w
            overlay_pos = target

        exposure = 1.0 + w * overlay_pos if cfg.mode == "add_on" else (1.0 - w) + w * overlay_pos
        # when dd throttle fires in reduce_off, also pull beta sleeve slightly
        if cfg.mode == "reduce_off" and risk_scale < 1.0:
            exposure = exposure * (0.55 + 0.45 * risk_scale)
        eq[i] = eq[i - 1] * (1.0 + exposure * r)

    equity = pd.Series(eq)
    meta = {
        **asdict(cfg),
        "overlay_turnover_units": round(float(turnover), 6),
        "final_overlay_pos": overlay_pos,
        "mean_equity": round(float(eq.mean()), 6),
    }
    return equity, meta


def score_row(r: dict[str, Any], btc_dd: float) -> float:
    """Primary: excess; secondary: DD improvement vs HODL; tertiary: sharpe."""
    excess = float(r["excess_return_pct"])
    dd = float(r["max_dd_pct"])
    sh = float(r.get("sharpe", 0.0))
    # Prefer beaters; penalize high DD
    if excess <= 0:
        return excess - dd * 0.1
    dd_improve = max(0.0, btc_dd - dd)
    return excess + 0.35 * dd_improve + 5.0 * sh


def grid_configs(fee: float, slip: float, quick: bool) -> list[Cfg]:
    modes = ("reduce_off", "add_on")
    weights = (0.15, 0.20, 0.25, 0.30, 0.35) if not quick else (0.20, 0.25, 0.30)
    ma_pairs = (
        (48, 200),
        (72, 288),
        (96, 400),
        (120, 480),
        (144, 600),
        (168, 720),
        (96, 336),
        (64, 320),
    )
    if quick:
        ma_pairs = ((96, 400), (120, 480), (72, 288), (48, 200))
    dd_throttles = (0.0, 0.20, 0.28, 0.35) if not quick else (0.0, 0.25, 0.35)
    dd_floors = (0.25, 0.40, 0.55) if not quick else (0.35, 0.50)
    vol_targets = (0.0, 0.45, 0.60) if not quick else (0.0, 0.50)
    hyst = (0.0, 0.002, 0.005) if not quick else (0.0, 0.003)

    out: list[Cfg] = []
    # Always include baseline + known best coarse
    out.append(Cfg(fee=fee, slip=slip, **{k: BASELINE[k] for k in BASELINE if k != "fee"}))  # type: ignore[arg-type]
    out.append(
        Cfg(
            mode="reduce_off",
            overlay_weight=0.30,
            fast=96,
            slow=400,
            fee=fee,
            slip=slip,
        )
    )
    for mode in modes:
        for w in weights:
            for fast, slow in ma_pairs:
                if fast >= slow:
                    continue
                for dd_t in dd_throttles:
                    floors = (1.0,) if dd_t == 0.0 else dd_floors
                    for dd_f in floors:
                        for vt in vol_targets:
                            for h in hyst:
                                out.append(
                                    Cfg(
                                        mode=mode,
                                        overlay_weight=w,
                                        fast=fast,
                                        slow=slow,
                                        fee=fee,
                                        slip=slip,
                                        dd_throttle=dd_t,
                                        dd_floor_scale=dd_f if dd_t > 0 else 1.0,
                                        vol_target=vt,
                                        hysteresis=h,
                                    )
                                )
    # de-dupe
    seen: set[tuple[Any, ...]] = set()
    uniq: list[Cfg] = []
    for c in out:
        k = c.key()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)
    return uniq


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--slip", type=float, default=0.001)
    ap.add_argument("--quick", action="store_true", help="smaller grid")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--json-stdout", action="store_true")
    args = ap.parse_args()

    df = _load_btc_1h(args.start, args.end)
    close = df["close"].astype(float)
    btc_eq = buy_hold_equity_from_close(close)
    btc_stats = equity_stats(btc_eq)
    btc_dd = float(btc_stats["max_dd_pct"])

    configs = grid_configs(args.fee, args.slip, args.quick)
    rows: list[dict[str, Any]] = []
    for cfg in configs:
        try:
            eq, meta = simulate(close, cfg)
        except SystemExit:
            continue
        vs = excess_vs_benchmark(eq, btc_eq, label="cfg", benchmark_label="BTC_HODL")
        st = equity_stats(eq)
        row = {
            **{k: meta[k] for k in asdict(cfg)},
            "return_pct": vs.strategy_return_pct,
            "excess_return_pct": vs.excess_return_pct,
            "max_dd_pct": vs.strategy_max_dd_pct,
            "btc_max_dd_pct": vs.benchmark_max_dd_pct,
            "dd_improve_vs_btc_pp": round(btc_dd - vs.strategy_max_dd_pct, 6),
            "sharpe": st["sharpe"],
            "beats_benchmark": vs.beats_benchmark,
            "turnover": meta["overlay_turnover_units"],
            "score": 0.0,
        }
        row["score"] = round(score_row(row, btc_dd), 6)
        rows.append(row)

    rows.sort(key=lambda r: r["score"], reverse=True)
    best = rows[0] if rows else None

    # Pareto: among beaters, minimize DD then maximize excess
    beaters = [r for r in rows if r["beats_benchmark"]]
    pareto_dd = sorted(beaters, key=lambda r: (r["max_dd_pct"], -r["excess_return_pct"]))
    best_dd = pareto_dd[0] if pareto_dd else None
    best_excess = sorted(beaters, key=lambda r: -r["excess_return_pct"])[0] if beaters else None

    # Baseline compare (legacy w=0.25 fixed defaults)
    base_cfg = Cfg(
        mode=str(BASELINE["mode"]),
        overlay_weight=float(BASELINE["overlay_weight"]),
        fast=int(BASELINE["fast"]),
        slow=int(BASELINE["slow"]),
        fee=args.fee,
        slip=args.slip,
        dd_throttle=float(BASELINE["dd_throttle"]),
        dd_floor_scale=float(BASELINE["dd_floor_scale"]),
        vol_target=float(BASELINE["vol_target"]),
        vol_window=int(BASELINE["vol_window"]),
        hysteresis=float(BASELINE["hysteresis"]),
    )
    b_eq, _ = simulate(close, base_cfg)
    b_vs = excess_vs_benchmark(b_eq, btc_eq, label="BASELINE", benchmark_label="BTC_HODL")
    b_st = equity_stats(b_eq)

    def _pick_cfg(r: dict[str, Any] | None) -> dict[str, Any] | None:
        if not r:
            return None
        keys = (
            "mode",
            "overlay_weight",
            "fast",
            "slow",
            "dd_throttle",
            "dd_floor_scale",
            "vol_target",
            "vol_window",
            "hysteresis",
            "fee",
            "slip",
        )
        return {k: r[k] for k in keys}

    # Cost matrix for best score cfg
    cost_matrix: list[dict[str, Any]] = []
    if best:
        c_best = Cfg(**{k: best[k] for k in asdict(base_cfg)})  # type: ignore[arg-type]
        for fee, slip, tag in (
            (0.0, 0.0, "zero"),
            (0.0002, 0.0002, "maker_like"),
            (0.001, 0.001, "taker"),
        ):
            c = Cfg(
                mode=c_best.mode,
                overlay_weight=c_best.overlay_weight,
                fast=c_best.fast,
                slow=c_best.slow,
                fee=fee,
                slip=slip,
                dd_throttle=c_best.dd_throttle,
                dd_floor_scale=c_best.dd_floor_scale,
                vol_target=c_best.vol_target,
                vol_window=c_best.vol_window,
                hysteresis=c_best.hysteresis,
            )
            eq_c, _ = simulate(close, c)
            vs_c = excess_vs_benchmark(eq_c, btc_eq, label=tag, benchmark_label="BTC_HODL")
            st_c = equity_stats(eq_c)
            cost_matrix.append(
                {
                    "tag": tag,
                    "fee": fee,
                    "slip": slip,
                    "return_pct": vs_c.strategy_return_pct,
                    "excess_return_pct": vs_c.excess_return_pct,
                    "max_dd_pct": vs_c.strategy_max_dd_pct,
                    "sharpe": st_c["sharpe"],
                    "gate": gate_beats_benchmark(vs_c)["decision"],
                }
            )

    report = {
        "contract": "HF-BTC-DD-OPT-20260811",
        "window": {"start": args.start, "end": args.end, "bars": len(df)},
        "n_configs": len(rows),
        "btc_hodl": btc_stats,
        "baseline": {
            "cfg": asdict(base_cfg),
            "return_pct": b_vs.strategy_return_pct,
            "excess_return_pct": b_vs.excess_return_pct,
            "max_dd_pct": b_vs.strategy_max_dd_pct,
            "sharpe": b_st["sharpe"],
            "gate": gate_beats_benchmark(b_vs)["decision"],
        },
        "best_score": best,
        "best_score_cfg": _pick_cfg(best),
        "best_dd_among_beaters": best_dd,
        "best_excess_among_beaters": best_excess,
        "cost_matrix_best_score": cost_matrix,
        "top": rows[: args.top],
        "delta_vs_baseline": None
        if not best
        else {
            "excess_pp": round(best["excess_return_pct"] - b_vs.excess_return_pct, 6),
            "return_pp": round(best["return_pct"] - b_vs.strategy_return_pct, 6),
            "max_dd_pp": round(best["max_dd_pct"] - b_vs.strategy_max_dd_pct, 6),
            "sharpe_delta": round(best["sharpe"] - b_st["sharpe"], 6),
        },
        "honesty": (
            "Grid search on pin window with taker costs; cost-aware design selection, "
            "not pure walk-forward OOS. Prefer paper T023/T024 before live."
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("=== BTC overlay DD optimize ===")
    print(f"window {args.start}→{args.end} bars={len(df)} configs={len(rows)}")
    print(
        f"BTC_HODL  ret={btc_stats['return_pct']:+.2f}% maxDD={btc_stats['max_dd_pct']:.2f}% "
        f"sh={btc_stats['sharpe']:.3f}"
    )
    print(
        f"BASELINE  ret={b_vs.strategy_return_pct:+.2f}% excess={b_vs.excess_return_pct:+.2f}pp "
        f"maxDD={b_vs.strategy_max_dd_pct:.2f}% sh={b_st['sharpe']:.3f}"
    )
    if best:
        print(
            f"BEST_SCR  ret={best['return_pct']:+.2f}% excess={best['excess_return_pct']:+.2f}pp "
            f"maxDD={best['max_dd_pct']:.2f}% sh={best['sharpe']:.3f} "
            f"cfg={report['best_score_cfg']}"
        )
        print(
            f"DELTA     excess={report['delta_vs_baseline']['excess_pp']:+.2f}pp "
            f"maxDD={report['delta_vs_baseline']['max_dd_pp']:+.2f}pp "
            f"sharpe={report['delta_vs_baseline']['sharpe_delta']:+.3f}"
        )
    if best_dd:
        print(
            f"BEST_DD   ret={best_dd['return_pct']:+.2f}% excess={best_dd['excess_return_pct']:+.2f}pp "
            f"maxDD={best_dd['max_dd_pct']:.2f}%"
        )
    for cm in cost_matrix:
        print(
            f"  cost {cm['tag']:11s} excess={cm['excess_return_pct']:+.2f}pp "
            f"maxDD={cm['max_dd_pct']:.2f}% gate={cm['gate']}"
        )
    print(f"written {args.out}")
    if args.json_stdout:
        print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
