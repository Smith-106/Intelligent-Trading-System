#!/usr/bin/env python3
"""BTC dual-MA long/flat with TP/SL + min R:R vs beta-overlay primary and HODL.

Research only — pin window cost-aware comparison, not pure OOS alpha claim.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

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
from quantflow.strategy.research.tpsl import (  # noqa: E402
    TPSLConfig,
    dual_ma_entries,
    simulate_long_flat_tpsl,
)

# Import overlay sim for baseline compare
from scripts.run_btc_beta_overlay_eval import _simulate_beta_overlay  # noqa: E402

DEFAULT_START = "2021-01-01"
DEFAULT_END = "2026-08-04"
DEFAULT_OUT = ROOT / "data" / "paper_replay" / "tpsl" / "eval.json"


def _load_btc(start: str, end: str):
    start_ms, end_ms = parse_window_ms(start, end)
    store = DataStore("data/parquet", ":memory:")
    try:
        df = store.query("BTC/USDT", start=start_ms, end=end_ms, timeframe="1h")
    finally:
        store.close()
    if df is None or df.empty:
        raise SystemExit("no BTC data")
    return df.sort_values("timestamp").reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--fast", type=int, default=96)
    ap.add_argument("--slow", type=int, default=400)
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--slip", type=float, default=0.001)
    # 2026-08-11 sweep (taker): SL 4% / TP 10% / min_rr 2.5 beats HODL with ~21% maxDD
    ap.add_argument("--sl", type=float, default=0.04, help="stop loss fraction")
    ap.add_argument("--tp", type=float, default=0.10, help="take profit fraction")
    ap.add_argument("--min-rr", type=float, default=2.5)
    ap.add_argument("--max-hold", type=int, default=0)
    ap.add_argument("--atr-sl-mult", type=float, default=0.0)
    ap.add_argument("--overlay-weight", type=float, default=0.30)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args()

    df = _load_btc(args.start, args.end)
    close = df["close"].astype(float)
    high = df["high"].astype(float) if "high" in df.columns else close
    low = df["low"].astype(float) if "low" in df.columns else close

    btc_eq = buy_hold_equity_from_close(close)
    btc_st = equity_stats(btc_eq)

    # primary overlay path (continuous exposure)
    ov_eq, ov_meta = _simulate_beta_overlay(
        close,
        overlay_weight=args.overlay_weight,
        fee=args.fee,
        slip=args.slip,
        fast=args.fast,
        slow=args.slow,
        mode="reduce_off",
    )
    ov_vs = excess_vs_benchmark(ov_eq, btc_eq, label="PRIMARY_OVERLAY", benchmark_label="BTC_HODL")

    entries, sig_on = dual_ma_entries(close, args.fast, args.slow)

    def run_cfg(cfg: TPSLConfig) -> dict[str, Any]:
        eq, trades, stats, meta = simulate_long_flat_tpsl(
            close,
            entries,
            high=high,
            low=low,
            signal_on=sig_on,
            cfg=cfg,
        )
        vs = excess_vs_benchmark(eq, btc_eq, label="TPSL", benchmark_label="BTC_HODL")
        st = equity_stats(eq)
        reasons: dict[str, int] = {}
        for t in trades:
            reasons[t.reason] = reasons.get(t.reason, 0) + 1
        return {
            "config": meta["config"],
            "return_pct": vs.strategy_return_pct,
            "excess_return_pct": vs.excess_return_pct,
            "max_dd_pct": vs.strategy_max_dd_pct,
            "sharpe": st["sharpe"],
            "beats_btc": vs.beats_benchmark,
            "gate": gate_beats_benchmark(vs)["decision"],
            "trade_stats": stats.to_dict(),
            "exit_reasons": reasons,
            "n_trades": stats.n_trades,
        }

    base_cfg = TPSLConfig(
        stop_loss_pct=args.sl,
        take_profit_pct=args.tp,
        min_rr=args.min_rr,
        max_holding_bars=args.max_hold,
        atr_sl_mult=args.atr_sl_mult,
        fee=args.fee,
        slip=args.slip,
    )
    primary_tpsl = run_cfg(base_cfg)

    # no barrier: exit only on signal off (for trade-stat baseline of discrete path)
    no_barrier = run_cfg(
        TPSLConfig(
            stop_loss_pct=0.99,
            take_profit_pct=99.0,
            min_rr=0.0,
            max_holding_bars=0,
            fee=args.fee,
            slip=args.slip,
        )
    )

    sweep_rows: list[dict[str, Any]] = []
    if args.sweep:
        for sl in (0.02, 0.03, 0.04, 0.05):
            for rr in (1.5, 2.0, 2.5, 3.0):
                tp = sl * rr
                for mh in (0, 168, 336):  # 0 / 1w / 2w on 1h
                    cfg = TPSLConfig(
                        stop_loss_pct=sl,
                        take_profit_pct=tp,
                        min_rr=rr,
                        max_holding_bars=mh,
                        fee=args.fee,
                        slip=args.slip,
                    )
                    row = run_cfg(cfg)
                    row["score"] = (
                        row["excess_return_pct"]
                        + 0.25 * max(0.0, btc_st["max_dd_pct"] - row["max_dd_pct"])
                        + 10.0 * row["trade_stats"]["winrate"]
                        + 2.0 * min(row["trade_stats"]["payoff_ratio"], 5.0)
                    )
                    sweep_rows.append(row)
        sweep_rows.sort(key=lambda r: r["score"], reverse=True)

    best = sweep_rows[0] if sweep_rows else primary_tpsl

    # prefer beaters with better DD than overlay if any
    beaters = [r for r in (sweep_rows or [primary_tpsl]) if r["beats_btc"]]
    best_dd = None
    if beaters:
        best_dd = sorted(beaters, key=lambda r: (r["max_dd_pct"], -r["excess_return_pct"]))[0]

    report: dict[str, Any] = {
        "contract": "IAF-TPSL-RR-20260811",
        "window": {"start": args.start, "end": args.end, "bars": len(df)},
        "btc_hodl": btc_st,
        "primary_overlay_reduce_off": {
            "meta": ov_meta,
            "return_pct": ov_vs.strategy_return_pct,
            "excess_return_pct": ov_vs.excess_return_pct,
            "max_dd_pct": ov_vs.strategy_max_dd_pct,
            "gate": gate_beats_benchmark(ov_vs)["decision"],
        },
        "tpsl_default": primary_tpsl,
        "tpsl_signal_exit_only": no_barrier,
        "best_score": best if args.sweep else primary_tpsl,
        "best_dd_among_beaters": best_dd,
        "sweep_top": sweep_rows[:15],
        "delta_tpsl_vs_overlay": {
            "excess_pp": round(primary_tpsl["excess_return_pct"] - ov_vs.excess_return_pct, 6),
            "max_dd_pp": round(primary_tpsl["max_dd_pct"] - ov_vs.strategy_max_dd_pct, 6),
            "return_pp": round(primary_tpsl["return_pct"] - ov_vs.strategy_return_pct, 6),
        },
        "honesty": (
            "Discrete long/flat TPSL is not the same product path as continuous "
            "beta+overlay. Compare carefully. Cost-aware pin-window selection."
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("=== BTC dual-MA TPSL vs HODL / overlay ===")
    print(f"window {args.start}→{args.end} bars={len(df)}")
    print(f"BTC_HODL        ret={btc_st['return_pct']:+.2f}% maxDD={btc_st['max_dd_pct']:.2f}%")
    print(
        f"OVERLAY w={args.overlay_weight} ret={ov_vs.strategy_return_pct:+.2f}% "
        f"ex={ov_vs.excess_return_pct:+.2f}pp maxDD={ov_vs.strategy_max_dd_pct:.2f}%"
    )
    ts = primary_tpsl["trade_stats"]
    print(
        f"TPSL sl={args.sl} tp={args.tp} rr>={args.min_rr} "
        f"ret={primary_tpsl['return_pct']:+.2f}% ex={primary_tpsl['excess_return_pct']:+.2f}pp "
        f"maxDD={primary_tpsl['max_dd_pct']:.2f}% wr={ts['winrate'] * 100:.1f}% "
        f"payoff={ts['payoff_ratio']:.2f} n={ts['n_trades']} gate={primary_tpsl['gate']}"
    )
    if args.sweep and sweep_rows:
        b = sweep_rows[0]
        print(
            f"BEST_SWEEP ret={b['return_pct']:+.2f}% ex={b['excess_return_pct']:+.2f}pp "
            f"maxDD={b['max_dd_pct']:.2f}% wr={b['trade_stats']['winrate'] * 100:.1f}% "
            f"cfg={b['config']}"
        )
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
