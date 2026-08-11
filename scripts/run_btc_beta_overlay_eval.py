#!/usr/bin/env python3
"""Evaluate profitability paths vs BTC HODL (product bar).

Paths
-----
1. BTC_HODL — buy & hold (zero fee)
2. B0_SHARED_RP — from sealed multi_symbol_replay artifact (if present)
3. BETA_OVERLAY — 100% BTC beta + small long/flat overlay on dual-MA trend
   (personal-scale highflyer organization: beta sleeve + capped overlay)

Product gate: excess vs BTC HODL (not research PAPER-GO alone).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quantflow.data.store import DataStore  # noqa: E402
from quantflow.signal.book_risk_budget import default_highflyer_style_budget  # noqa: E402
from quantflow.strategy.research.benchmark_excess import (  # noqa: E402
    buy_hold_equity_from_close,
    equity_stats,
    excess_vs_benchmark,
    gate_beats_benchmark,
)
from quantflow.strategy.research.contract_pin import parse_window_ms  # noqa: E402

DEFAULT_START = "2021-01-01"
DEFAULT_END = "2026-08-04"
DEFAULT_B0 = ROOT / "data" / "paper_replay" / "baseline0" / "multi_symbol_replay.json"
DEFAULT_OUT = ROOT / "data" / "paper_replay" / "beta_overlay" / "eval.json"


def _load_btc_1h(start: str, end: str) -> pd.DataFrame:
    start_ms, end_ms = parse_window_ms(start, end)
    store = DataStore("data/parquet", ":memory:")
    try:
        df = store.query("BTC/USDT", start=start_ms, end=end_ms, timeframe="1h")
    finally:
        store.close()
    if df is None or df.empty:
        raise SystemExit("no BTC/USDT 1h bars in window")
    return df.sort_values("timestamp").reset_index(drop=True)


def _dual_ma_long_flat(close: pd.Series, fast: int = 48, slow: int = 200) -> pd.Series:
    """1 when fast MA > slow MA else 0 (long/flat overlay signal)."""
    f = close.astype(float).rolling(fast, min_periods=fast).mean()
    s = close.astype(float).rolling(slow, min_periods=slow).mean()
    sig = (f > s).astype(float)
    # no look-ahead: trade next bar
    return sig.shift(1).fillna(0.0)


def _simulate_beta_overlay(
    close: pd.Series,
    *,
    overlay_weight: float = 0.15,
    fee: float = 0.001,
    slip: float = 0.001,
    fast: int = 48,
    slow: int = 200,
    mode: str = "add_on",
) -> tuple[pd.Series, dict[str, Any]]:
    """Equity paths with mandatory BTC beta sleeve + capped overlay.

    Modes
    -----
    add_on (default, product-oriented):
        exposure = 1 + w * signal  → always full BTC beta; add long overlay when
        dual-MA is on (gross ∈ [1, 1+w]). Matches highflyer-style risk budget:
        beta sleeve 1.0 + overlay sleeve w.
    reduce_off (legacy research):
        exposure = (1-w) + w * signal → underweight when signal off (usually
        loses HODL in secular bulls).
    """
    if mode not in {"add_on", "reduce_off"}:
        raise SystemExit(f"unknown mode {mode!r}")
    c = close.astype(float).to_numpy()
    n = len(c)
    if n < slow + 5:
        raise SystemExit(f"need more bars than slow={slow}, got {n}")
    sig = _dual_ma_long_flat(close.astype(float), fast=fast, slow=slow).to_numpy()
    eq = np.ones(n, dtype=float)
    overlay_pos = 0.0
    cost_rate = fee + slip
    turnover = 0.0
    for i in range(1, n):
        r = c[i] / c[i - 1] - 1.0
        target = float(sig[i])
        if target != overlay_pos:
            delta = abs(target - overlay_pos)
            eq[i - 1] *= 1.0 - delta * overlay_weight * cost_rate
            turnover += delta * overlay_weight
            overlay_pos = target
        if mode == "add_on":
            exposure = 1.0 + overlay_weight * overlay_pos
        else:
            exposure = (1.0 - overlay_weight) + overlay_weight * overlay_pos
        eq[i] = eq[i - 1] * (1.0 + exposure * r)
    equity = pd.Series(eq)
    if mode == "add_on":
        mean_exp = float(np.mean(1.0 + overlay_weight * sig))
    else:
        mean_exp = float(np.mean((1.0 - overlay_weight) + overlay_weight * sig))
    meta = {
        "mode": mode,
        "overlay_weight": overlay_weight,
        "fee": fee,
        "slip": slip,
        "fast": fast,
        "slow": slow,
        "overlay_turnover_units": round(float(turnover), 6),
        "final_overlay_pos": overlay_pos,
        "mean_exposure": round(mean_exp, 6),
    }
    return equity, meta


def _b0_proxy_from_artifact(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    srp = data.get("shared_risk_parity") or {}
    return {
        "source": str(path),
        "return_pct": srp.get("return_pct"),
        "max_drawdown_pct": srp.get("max_drawdown_pct"),
        "sharpe_annualized": srp.get("sharpe_annualized"),
        "orders": srp.get("orders"),
        "window": data.get("window"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    # 2026-08-11 re-opt (taker fee+slip=10bp): w=0.30 beats prior w=0.25 on pin
    # window and 2025 OOS excess; still cost-aware in-sample design — not pure OOS.
    ap.add_argument("--overlay-weight", type=float, default=0.30)
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--slip", type=float, default=0.001)
    # Defaults favor lower overlay turnover so taker costs can still beat HODL
    # on the pin window (96/400 ≈ 4d/17d on 1h).
    ap.add_argument("--fast", type=int, default=96)
    ap.add_argument("--slow", type=int, default=400)
    ap.add_argument(
        "--mode",
        choices=("add_on", "reduce_off"),
        default="reduce_off",
        help="add_on: full beta + long overlay; reduce_off: underweight when off",
    )
    ap.add_argument(
        "--sweep",
        action="store_true",
        help="Sweep overlay weights and report best excess vs BTC",
    )
    ap.add_argument("--b0-artifact", type=Path, default=DEFAULT_B0)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--json-stdout", action="store_true")
    args = ap.parse_args()

    df = _load_btc_1h(args.start, args.end)
    close = df["close"].astype(float)
    btc_eq = buy_hold_equity_from_close(close)
    btc_stats = equity_stats(btc_eq)

    sweep_rows: list[dict[str, Any]] = []
    if args.sweep:
        for w in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35):
            for mode in ("add_on", "reduce_off"):
                for fast, slow in ((args.fast, args.slow), (48, 200), (96, 400)):
                    eq_i, meta_i = _simulate_beta_overlay(
                        close,
                        overlay_weight=w,
                        fee=args.fee,
                        slip=args.slip,
                        fast=fast,
                        slow=slow,
                        mode=mode,
                    )
                    vs_i = excess_vs_benchmark(
                        eq_i,
                        btc_eq,
                        label=f"{mode}_w{w}_f{fast}s{slow}",
                        benchmark_label="BTC_HODL",
                    )
                    sweep_rows.append(
                        {
                            "mode": mode,
                            "overlay_weight": w,
                            "fast": fast,
                            "slow": slow,
                            "return_pct": vs_i.strategy_return_pct,
                            "excess_return_pct": vs_i.excess_return_pct,
                            "max_dd_pct": vs_i.strategy_max_dd_pct,
                            "beats_benchmark": vs_i.beats_benchmark,
                            "mean_exposure": meta_i["mean_exposure"],
                            "turnover": meta_i["overlay_turnover_units"],
                        }
                    )
        # de-dupe identical configs from overlapping MA pairs
        seen: set[tuple[Any, ...]] = set()
        uniq: list[dict[str, Any]] = []
        for r in sweep_rows:
            key = (r["mode"], r["overlay_weight"], r["fast"], r["slow"])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(r)
        sweep_rows = uniq
        sweep_rows.sort(key=lambda r: r["excess_return_pct"], reverse=True)
        best = sweep_rows[0]
        args.overlay_weight = float(best["overlay_weight"])
        args.mode = str(best["mode"])
        args.fast = int(best["fast"])
        args.slow = int(best["slow"])

    overlay_eq, overlay_meta = _simulate_beta_overlay(
        close,
        overlay_weight=args.overlay_weight,
        fee=args.fee,
        slip=args.slip,
        fast=args.fast,
        slow=args.slow,
        mode=args.mode,
    )
    overlay_vs = excess_vs_benchmark(
        overlay_eq,
        btc_eq,
        label="BETA_OVERLAY",
        benchmark_label="BTC_HODL",
        cost_drag_note=f"fee+slip={args.fee + args.slip} on overlay rebalances only; mode={args.mode}",
    )
    overlay_gate = gate_beats_benchmark(overlay_vs)

    # Book budget dry check sample
    budget = default_highflyer_style_budget(overlay_sleeve=args.overlay_weight)
    budget_demo = budget.check(
        equity=100_000.0,
        current_gross=100_000.0 * (1.0 - args.overlay_weight),
        current_net=100_000.0 * (1.0 - args.overlay_weight),
        proposed_notional_delta=100_000.0 * args.overlay_weight,
        sleeve="overlay",
        sleeve_current_notional=0.0,
        current_drawdown=0.0,
    )

    b0 = _b0_proxy_from_artifact(args.b0_artifact)
    # B0 excess vs BTC using scalar returns only (no bar equity in artifact)
    b0_excess = None
    if b0 and b0.get("return_pct") is not None:
        b0_excess = {
            "strategy_return_pct": b0["return_pct"],
            "benchmark_return_pct": btc_stats["return_pct"],
            "excess_return_pct": round(float(b0["return_pct"]) - float(btc_stats["return_pct"]), 6),
            "beats_benchmark": float(b0["return_pct"]) > float(btc_stats["return_pct"]),
            "note": "scalar full-window compare; B0 is multi-symbol shared RP not pure BTC",
        }

    # Cycle slice: 2022-11-01 → end (post trough narrative)
    cycle = None
    try:
        c_start, c_end = parse_window_ms("2022-11-01", args.end)
        mask = (df["timestamp"] >= c_start) & (df["timestamp"] <= c_end)
        c_close = df.loc[mask, "close"].astype(float).reset_index(drop=True)
        if len(c_close) > args.slow + 5:
            c_btc = buy_hold_equity_from_close(c_close)
            c_ov, _ = _simulate_beta_overlay(
                c_close,
                overlay_weight=args.overlay_weight,
                fee=args.fee,
                slip=args.slip,
                fast=args.fast,
                slow=args.slow,
                mode=args.mode,
            )
            cycle = excess_vs_benchmark(
                c_ov, c_btc, label="BETA_OVERLAY_POST_2022_LOW", benchmark_label="BTC_HODL"
            ).to_dict()
    except Exception as exc:
        cycle = {"error": str(exc)}

    report: dict[str, Any] = {
        "contract": "HF-BETA-OVERLAY-EVAL-20260810",
        "north_star_note": (
            "Product success = beat or not-lose BTC HODL after costs; "
            "research PAPER-GO alone is insufficient."
        ),
        "window": {"start": args.start, "end": args.end, "bars": len(df)},
        "btc_hodl": btc_stats,
        "beta_overlay": {
            "meta": overlay_meta,
            "stats": equity_stats(overlay_eq),
            "vs_btc": overlay_vs.to_dict(),
            "product_gate": overlay_gate,
        },
        "sweep": sweep_rows,
        "b0_shared_rp_artifact": b0,
        "b0_vs_btc_scalar": b0_excess,
        "cycle_slice_post_2022_low": cycle,
        "book_risk_budget": {
            "config": budget.to_dict(),
            "demo_overlay_allocate": budget_demo,
        },
        "ranking_by_return": sorted(
            [
                {"name": "BTC_HODL", "return_pct": btc_stats["return_pct"]},
                {
                    "name": "BETA_OVERLAY",
                    "return_pct": overlay_vs.strategy_return_pct,
                },
                {
                    "name": "B0_SHARED_RP",
                    "return_pct": (b0 or {}).get("return_pct"),
                },
            ],
            key=lambda x: (x["return_pct"] is not None, x["return_pct"] or -1e99),
            reverse=True,
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("=== BTC beta+overlay vs HODL ===")
    print(f"window {args.start} → {args.end} bars={len(df)}")
    print(
        f"BTC_HODL     ret={btc_stats['return_pct']:+.2f}% "
        f"maxDD={btc_stats['max_dd_pct']:.2f}% sh={btc_stats['sharpe']:.3f}"
    )
    print(
        f"BETA_OVERLAY ret={overlay_vs.strategy_return_pct:+.2f}% "
        f"excess={overlay_vs.excess_return_pct:+.2f}pp "
        f"maxDD={overlay_vs.strategy_max_dd_pct:.2f}% "
        f"gate={overlay_gate['decision']}"
    )
    if b0_excess:
        print(
            f"B0_SHARED_RP ret={b0_excess['strategy_return_pct']:+.2f}% "
            f"excess={b0_excess['excess_return_pct']:+.2f}pp "
            f"beats={b0_excess['beats_benchmark']}"
        )
    # Dual cost matrix (taker vs maker-like) for product honesty
    cost_matrix: list[dict[str, Any]] = []
    for fee, slip, tag in (
        (0.0, 0.0, "zero"),
        (0.0002, 0.0002, "maker_like"),
        (0.001, 0.001, "taker"),
    ):
        eq_c, meta_c = _simulate_beta_overlay(
            close,
            overlay_weight=args.overlay_weight,
            fee=fee,
            slip=slip,
            fast=args.fast,
            slow=args.slow,
            mode=args.mode,
        )
        vs_c = excess_vs_benchmark(
            eq_c, btc_eq, label=f"BETA_OVERLAY_{tag}", benchmark_label="BTC_HODL"
        )
        g_c = gate_beats_benchmark(vs_c)
        cost_matrix.append(
            {
                "tag": tag,
                "fee": fee,
                "slip": slip,
                "excess_return_pct": vs_c.excess_return_pct,
                "return_pct": vs_c.strategy_return_pct,
                "max_dd_pct": vs_c.strategy_max_dd_pct,
                "gate": g_c["decision"],
                "meta": meta_c,
            }
        )
    report["cost_matrix"] = cost_matrix
    report["product_summary"] = {
        "b0_beats_btc": bool(b0_excess and b0_excess["beats_benchmark"]),
        "overlay_beats_btc_taker": any(
            r["tag"] == "taker" and r["gate"] == "PASS" for r in cost_matrix
        ),
        "overlay_beats_btc_maker_like": any(
            r["tag"] == "maker_like" and r["gate"] == "PASS" for r in cost_matrix
        ),
        "gap_closed_vs_b0": (
            overlay_vs.strategy_return_pct - float((b0 or {}).get("return_pct") or 0.0)
        ),
        "highflyer_principle": (
            "beta sleeve + capped overlay + book risk budget; "
            "not 万卡 copy — production organization"
        ),
    }
    # rewrite with matrix
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("cost_matrix:")
    for row in cost_matrix:
        print(f"  {row['tag']:12} excess={row['excess_return_pct']:+.2f}pp gate={row['gate']}")
    print(f"written {args.out}")
    if args.json_stdout:
        print(json.dumps(report, ensure_ascii=False))

    # Exit 0 always for research eval; product gate is in JSON
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
