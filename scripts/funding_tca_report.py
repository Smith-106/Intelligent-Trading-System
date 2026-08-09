#!/usr/bin/env python3
"""Build funding/TCA cost block for Baseline contracts (T014).

Uses measured meta_funding_rate when available (local OKX swap series may be
short); always emits an assumption baseline so GO reports can cite funding
alongside fee×slip even without full-history funding.

    python scripts/funding_tca_report.py
    python scripts/funding_tca_report.py --symbol BTC-USDT-SWAP --out data/paper_replay/baseline0/funding_tca.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quantflow.strategy.validation.cost_fidelity import (  # noqa: E402
    DEFAULT_ASSUMED_ABS_FUNDING_PER_EVENT,
    DEFAULT_FUNDING_EVENTS_PER_DAY,
    DEFAULT_SLIPPAGE,
    DEFAULT_TAKER_FEE,
    build_funding_tca,
    summarize_measured_funding,
)


def _load_measured(symbol: str, start_ms: int | None, end_ms: int | None) -> dict[str, Any] | None:
    from quantflow.data.store import DataStore

    store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
    try:
        df = store.query_funding_rates(symbol, start=start_ms, end=end_ms)
    finally:
        store.close()
    if df is None or df.empty or "funding_rate" not in df.columns:
        return None
    rates = [float(x) for x in df["funding_rate"].tolist() if x == x]
    if not rates:
        return None
    ts = df["timestamp"].astype("int64") if "timestamp" in df.columns else None
    return summarize_measured_funding(
        rates,
        symbol=symbol,
        start_ms=int(ts.min()) if ts is not None and len(ts) else None,
        end_ms=int(ts.max()) if ts is not None and len(ts) else None,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol", default="BTC-USDT-SWAP", help="meta_funding_rate symbol key")
    ap.add_argument("--start-ms", type=int, default=None)
    ap.add_argument("--end-ms", type=int, default=None)
    ap.add_argument(
        "--taker-share",
        type=float,
        default=1.0,
        help="Fraction of notional assumed to pay funding (perp long≈1, spot≈0)",
    )
    ap.add_argument(
        "--assumed-abs",
        type=float,
        default=DEFAULT_ASSUMED_ABS_FUNDING_PER_EVENT,
        help="Fallback abs funding per 8h event",
    )
    ap.add_argument(
        "--out",
        default="data/paper_replay/baseline0/funding_tca.json",
    )
    args = ap.parse_args()

    measured = _load_measured(args.symbol, args.start_ms, args.end_ms)
    mode = "hybrid" if measured else "assumption"
    block = build_funding_tca(
        mode=mode,
        assumed_abs_funding_per_event=args.assumed_abs,
        events_per_day=DEFAULT_FUNDING_EVENTS_PER_DAY,
        measured=measured,
        taker_share=args.taker_share,
        notes=(
            "Measured series may cover only a short recent window; hybrid uses "
            "measured abs mean when present, else assumption. Quote beside "
            f"fee={DEFAULT_TAKER_FEE}/slip={DEFAULT_SLIPPAGE}."
        ),
    )
    payload = {
        "task": "T014",
        "ran_at": datetime.now(UTC).isoformat(),
        "symbol_meta": args.symbol,
        "funding_tca": block,
        "alongside_fee_slip": {
            "taker_fee": DEFAULT_TAKER_FEE,
            "slippage": DEFAULT_SLIPPAGE,
        },
        "display": {
            "funding_annual_drag_pct": block.get("estimated_annual_drag_pct"),
            "fee_slip_production": f"{DEFAULT_TAKER_FEE}/{DEFAULT_SLIPPAGE}",
        },
    }
    out = Path(args.out)
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"[funding_tca] mode={block['mode']} source={block['source']} "
        f"annual_drag≈{block['estimated_annual_drag_pct']:.3f}% "
        f"measured_n={(measured or {}).get('n_events')} → {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
