#!/usr/bin/env python3
"""IAF prune → CPCV research pipeline (never hard-bind entry)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quantflow.data.store import DataStore  # noqa: E402
from quantflow.strategy.research.contract_pin import parse_window_ms  # noqa: E402
from quantflow.strategy.research.iaf_prune_cpcv import run_iaf_prune_cpcv  # noqa: E402

DEFAULT_OUT = ROOT / "data" / "paper_replay" / "dual_path" / "iaf_prune_cpcv.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2026-08-04")
    ap.add_argument("--threshold", type=float, default=0.7)
    ap.add_argument("--cpcv-groups", type=int, default=6)
    ap.add_argument("--cpcv-test-groups", type=int, default=2)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    start_ms, end_ms = parse_window_ms(args.start, args.end)
    store = DataStore("data/parquet", ":memory:")
    try:
        df = store.query("BTC/USDT", start=start_ms, end=end_ms, timeframe="1h")
    finally:
        store.close()
    if df is None or df.empty:
        print("no data", file=sys.stderr)
        return 2
    df = df.sort_values("timestamp").reset_index(drop=True)

    rep = run_iaf_prune_cpcv(
        df,
        threshold=args.threshold,
        cpcv_groups=args.cpcv_groups,
        cpcv_test_groups=args.cpcv_test_groups,
    )
    assert rep.get("hard_bind_entry") is False
    assert rep.get("promotion_eligible") is False

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("=== IAF prune → CPCV (research only) ===")
    print(f"kept={rep['prune']['kept']}")
    print(f"dropped={rep['prune']['dropped']}")
    print(
        f"cpcv={rep['cpcv']['decision']} pbo={rep['cpcv']['pbo']} "
        f"research_go={rep['research_go']}"
    )
    print(f"hard_bind_entry={rep['hard_bind_entry']} promotion_eligible={rep['promotion_eligible']}")
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
