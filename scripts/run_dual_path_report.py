#!/usr/bin/env python3
"""Build dual-path research report (Path A overlay + Path B TPSL).

Never emits combined_score. Research only — promotion_eligible always false.
"""

from __future__ import annotations

import argparse
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
from quantflow.strategy.research.dual_path_profiles import (  # noqa: E402
    path_a_profile,
    path_b_profile,
)
from quantflow.strategy.research.dual_path_report import (  # noqa: E402
    build_dual_path_report,
    from_overlay_eval,
    from_tpsl_eval,
    write_report,
)
from quantflow.strategy.research.tpsl import (  # noqa: E402
    TPSLConfig,
    dual_ma_entries,
    simulate_long_flat_tpsl,
)
from scripts.run_btc_beta_overlay_eval import _simulate_beta_overlay  # noqa: E402

DEFAULT_START = "2021-01-01"
DEFAULT_END = "2026-08-04"
DEFAULT_OUT = ROOT / "data" / "paper_replay" / "dual_path" / "report.json"


def _load_btc(start: str, end: str):
    start_ms, end_ms = parse_window_ms(start, end)
    store = DataStore("data/parquet", ":memory:")
    try:
        df = store.query("BTC/USDT", start=start_ms, end=end_ms, timeframe="1h")
    finally:
        store.close()
    if df is None or df.empty:
        raise SystemExit("no BTC data — run quantflow download first (fail-closed)")
    return df.sort_values("timestamp").reset_index(drop=True)


def _run_path_a(close, profile: dict[str, Any]) -> dict[str, Any]:
    eq, meta = _simulate_beta_overlay(
        close,
        overlay_weight=float(profile["overlay_weight"]),
        fee=float(profile["fee"]),
        slip=float(profile["slip"]),
        fast=int(profile["fast"]),
        slow=int(profile["slow"]),
        mode=str(profile["mode"]),
    )
    btc_eq = buy_hold_equity_from_close(close)
    vs = excess_vs_benchmark(eq, btc_eq, label="PATH_A", benchmark_label="BTC_HODL")
    gate = gate_beats_benchmark(vs)
    return {
        "primary_overlay_reduce_off": {
            "meta": meta,
            "return_pct": vs.strategy_return_pct,
            "excess_return_pct": vs.excess_return_pct,
            "max_dd_pct": vs.strategy_max_dd_pct,
            "gate": gate.get("decision"),
            "beats_btc": vs.beats_benchmark,
        },
        "btc_hodl": equity_stats(btc_eq),
    }


def _run_path_b(df, profile: dict[str, Any]) -> dict[str, Any]:
    close = df["close"].astype(float)
    high = df["high"].astype(float) if "high" in df.columns else close
    low = df["low"].astype(float) if "low" in df.columns else close
    entries, sig_on = dual_ma_entries(close, int(profile["fast"]), int(profile["slow"]))
    cfg = TPSLConfig(
        stop_loss_pct=float(profile["stop_loss_pct"]),
        take_profit_pct=float(profile["take_profit_pct"]),
        min_rr=float(profile["min_rr"]),
        max_holding_bars=int(profile.get("max_holding_bars") or 0),
        fee=float(profile["fee"]),
        slip=float(profile["slip"]),
    )
    eq, _trades, stats, meta = simulate_long_flat_tpsl(
        close, entries, high=high, low=low, signal_on=sig_on, cfg=cfg
    )
    btc_eq = buy_hold_equity_from_close(close)
    vs = excess_vs_benchmark(eq, btc_eq, label="PATH_B", benchmark_label="BTC_HODL")
    gate = gate_beats_benchmark(vs)
    st = equity_stats(eq)
    return {
        "tpsl_default": {
            "config": meta.get("config", {}),
            "return_pct": vs.strategy_return_pct,
            "excess_return_pct": vs.excess_return_pct,
            "max_dd_pct": vs.strategy_max_dd_pct,
            "sharpe": st.get("sharpe"),
            "gate": gate.get("decision"),
            "beats_btc": vs.beats_benchmark,
            "trade_stats": stats.to_dict(),
            "n_trades": stats.n_trades,
        }
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--md", type=Path, default=None, help="optional markdown path")
    args = ap.parse_args()

    pa = path_a_profile()
    pb = path_b_profile()
    df = _load_btc(args.start, args.end)
    close = df["close"].astype(float)

    overlay_block = _run_path_a(close, pa)
    tpsl_block = _run_path_b(df, pb)

    report = build_dual_path_report(
        path_a=from_overlay_eval(overlay_block, profile=pa),
        path_b=from_tpsl_eval(tpsl_block, profile=pb),
        run_meta={
            "window": {"start": args.start, "end": args.end, "bars": len(df)},
            "btc_hodl": overlay_block.get("btc_hodl"),
        },
        attachments={
            "cost": {"fee": pa["fee"], "slip": pa["slip"], "note": "taker both paths"},
        },
    )

    md_path = args.md
    if md_path is None:
        md_path = args.out.with_suffix(".md")
    jp, mp = write_report(report, args.out, out_md=md_path)

    am = report.paths["path_a"]["metrics"]
    bm = report.paths["path_b"]["metrics"]
    print("=== Dual-Path Research Report ===")
    print(f"window {args.start}→{args.end} bars={len(df)}")
    print(
        f"PATH_A excess={am.get('excess_return_pct')} maxDD={am.get('max_dd_pct')} "
        f"gate={am.get('gate_vs_btc')}"
    )
    print(
        f"PATH_B excess={bm.get('excess_return_pct')} maxDD={bm.get('max_dd_pct')} "
        f"wr={bm.get('winrate')} payoff={bm.get('payoff_ratio')} gate={bm.get('gate_vs_btc')}"
    )
    print("NO combined_score — paths reported side-by-side only")
    print(f"written {jp}" + (f" + {mp}" if mp else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
