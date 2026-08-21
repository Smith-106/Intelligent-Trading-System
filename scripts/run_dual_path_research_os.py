#!/usr/bin/env python3
"""Dual-path research OS orchestrator (paper-first, no promotion).

Order (locked):
  causal_preflight → (optional IAF prune) → Path A/B metrics
  → (optional TPSL validation) → cost/vs-BTC attach → dual_path_report

Never emits combined_score. promotion_eligible always false.
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
from quantflow.strategy.research.contract_pin import parse_window_ms  # noqa: E402
from quantflow.strategy.research.dual_path_profiles import (  # noqa: E402
    path_a_profile,
    path_b_profile,
)
from quantflow.strategy.research.dual_path_report import (  # noqa: E402
    assert_no_combined_score,
    build_dual_path_report,
    from_overlay_eval,
    from_tpsl_eval,
    write_report,
)
from quantflow.strategy.templates.trend_following import (  # noqa: E402
    TrendFollowingStrategy,
)
from quantflow.strategy.validation.causal_preflight import (  # noqa: E402
    run_causal_preflight,
)

DEFAULT_START = "2021-01-01"
DEFAULT_END = "2026-08-04"
DEFAULT_OUT = ROOT / "data" / "paper_replay" / "dual_path" / "research_os.json"


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--md", type=Path, default=None)
    ap.add_argument("--skip-prune", action="store_true")
    ap.add_argument("--skip-validation", action="store_true")
    ap.add_argument(
        "--force-continue",
        action="store_true",
        help="Continue after causal preflight FAIL (research only; marks causal_failed)",
    )
    ap.add_argument(
        "--strategy",
        default="trend_following",
        help="Strategy for causal preflight static scan",
    )
    args = ap.parse_args()

    # --- 1) Causal preflight (static; no data) ---
    preflight = run_causal_preflight(TrendFollowingStrategy)
    causal_failed = not preflight.passed
    if causal_failed and not args.force_continue:
        print(preflight.summary())
        print("abort: causal preflight failed (use --force-continue to continue research-only)")
        return 2
    if causal_failed:
        print(preflight.summary() + " — continuing due to --force-continue")

    # --- 2) Load data ---
    df = _load_btc(args.start, args.end)

    # Reuse path metrics builders from dual-path report script
    from scripts.run_dual_path_report import _run_path_a, _run_path_b

    pa = path_a_profile()
    pb = path_b_profile()
    close = df["close"].astype(float)
    overlay_block = _run_path_a(close, pa)
    tpsl_block = _run_path_b(df, pb)

    attachments: dict[str, Any] = {
        "causal_preflight": preflight.to_dict(),
        "cost": {
            "fee": pa["fee"],
            "slip": pa["slip"],
            "note": "taker both paths",
        },
    }
    if causal_failed:
        attachments["causal_failed"] = True

    # --- 3) Optional IAF prune ---
    if not args.skip_prune:
        try:
            from quantflow.indicators.engine import IndicatorEngine
            from quantflow.strategy.research.iaf_prune import (
                IAF_FACTOR_NAMES,
                prune_correlated_factors,
            )

            eng = IndicatorEngine()
            factors = eng.batch_calculate(df)
            cols = [c for c in IAF_FACTOR_NAMES if c in factors.columns]
            if cols:
                prune = prune_correlated_factors(factors, columns=cols)
                attachments["iaf_prune"] = prune.to_dict()
            else:
                attachments["iaf_prune"] = {
                    "skipped": True,
                    "reason": "no IAF columns in batch_calculate",
                }
        except Exception as exc:  # pragma: no cover - defensive
            attachments["iaf_prune"] = {"skipped": True, "reason": str(exc)}

    # --- 4) Optional TPSL validation (small default budget) ---
    if not args.skip_validation:
        try:
            from quantflow.strategy.research.tpsl_validation_report import (
                build_tpsl_validation_report,
            )

            # Short synthetic-friendly budget for research OS default
            val = build_tpsl_validation_report(
                df,
                fast=int(pb["fast"]),
                slow=int(pb["slow"]),
                optimize_trials=3,
                cpcv_groups=4,
                cpcv_test_groups=1,
                wfo_windows=2,
                fee=float(pb["fee"]),
                run_gate=True,
            )
            attachments["tpsl_validation"] = val
        except Exception as exc:
            attachments["tpsl_validation"] = {
                "skipped": True,
                "reason": str(exc),
                "promotion_eligible": False,
            }

    path_b = from_tpsl_eval(tpsl_block, profile=pb)
    if isinstance(attachments.get("tpsl_validation"), dict):
        path_b["validation"] = {
            "decision": attachments["tpsl_validation"].get("decision"),
            "n_trials_accounted": attachments["tpsl_validation"].get("n_trials_accounted"),
            "n_trials_breakdown": attachments["tpsl_validation"].get("n_trials_breakdown"),
            "underreported": attachments["tpsl_validation"].get("underreported"),
            "pbo_source": attachments["tpsl_validation"].get("pbo_source"),
            "promotion_eligible": False,
        }
        path_b["n_trials_accounted"] = attachments["tpsl_validation"].get("n_trials_accounted")
        path_b["n_trials_breakdown"] = attachments["tpsl_validation"].get("n_trials_breakdown")
        path_b["execution_models"] = attachments["tpsl_validation"].get(
            "execution_models", {"tpsl_simulator": True}
        )

    # IMP-01: pin OHLCV fingerprint (research path remains vectorized)
    from quantflow.strategy.research.contract_pin import fingerprint_ohlcv

    data_fp = {
        "aggregate": fingerprint_ohlcv(df),
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "start": args.start,
        "end": args.end,
        "bars": len(df),
    }
    # IMP-02-style cost structure on dual-path OS cost attachment
    attachments["cost"] = {
        **dict(attachments.get("cost") or {}),
        "fee_slip_grid": [
            {"taker_fee": 0.0, "slippage": 0.0, "label": "zero"},
            {
                "taker_fee": float(pa["fee"]),
                "slippage": float(pa["slip"]),
                "label": "profile",
            },
        ],
        "funding_tca": {
            "mode": "assumption",
            "note": "research OS attachment; not register-ready alone",
        },
    }

    report = build_dual_path_report(
        path_a=from_overlay_eval(overlay_block, profile=pa),
        path_b=path_b,
        run_meta={
            "window": {"start": args.start, "end": args.end, "bars": len(df)},
            "pipeline": [
                "causal_preflight",
                "iaf_prune" if not args.skip_prune else "iaf_prune:skipped",
                "path_metrics",
                "tpsl_validation" if not args.skip_validation else "tpsl_validation:skipped",
                "cost",
                "dual_path_report",
            ],
            "btc_hodl": overlay_block.get("btc_hodl"),
            "causal_failed": causal_failed,
        },
        attachments=attachments,
        complete=not causal_failed,
        data_fingerprint=data_fp,
        execution_path="vectorized",
    )
    assert_no_combined_score(report.to_dict())
    assert report.run_meta.get("data_fingerprint") is not None
    assert report.attachments.get("promotion_path", {}).get("promotion_eligible") is False

    md_path = args.md if args.md is not None else args.out.with_suffix(".md")
    jp, mp = write_report(report, args.out, out_md=md_path)

    am = report.paths["path_a"]["metrics"]
    bm = report.paths["path_b"]["metrics"]
    print("=== Dual-Path Research OS ===")
    print(f"causal: {'FAIL' if causal_failed else 'PASS'}")
    print(f"window {args.start}→{args.end} bars={len(df)}")
    print(
        f"PATH_A excess={am.get('excess_return_pct')} maxDD={am.get('max_dd_pct')} "
        f"gate={am.get('gate_vs_btc')}"
    )
    print(
        f"PATH_B excess={bm.get('excess_return_pct')} maxDD={bm.get('max_dd_pct')} "
        f"wr={bm.get('winrate')} payoff={bm.get('payoff_ratio')} gate={bm.get('gate_vs_btc')}"
    )
    if path_b.get("validation"):
        print(
            f"PATH_B validation decision={path_b['validation'].get('decision')} "
            f"n_trials={path_b.get('n_trials_accounted')}"
        )
    print("NO combined_score — paths side-by-side only; promotion_eligible=false")
    print(f"written {jp}" + (f" + {mp}" if mp else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
