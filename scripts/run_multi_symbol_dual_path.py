#!/usr/bin/env python3
"""Multi-symbol dual-path research report (IMP-04; no promote)."""

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
from quantflow.strategy.research.multi_symbol_dual_path import (  # noqa: E402
    build_multi_symbol_dual_path_report,
)

DEFAULT_OUT = ROOT / "data" / "paper_replay" / "dual_path" / "multi_symbol_dual_path.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default="BTC/USDT,ETH/USDT")
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2026-08-04")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if len(symbols) < 2:
        print("need >=2 symbols", file=sys.stderr)
        return 2

    start_ms, end_ms = parse_window_ms(args.start, args.end)
    store = DataStore("data/parquet", ":memory:")
    frames = {}
    try:
        for sym in symbols:
            df = store.query(sym, start=start_ms, end=end_ms, timeframe="1h")
            if df is None or df.empty:
                print(f"no data for {sym}", file=sys.stderr)
                return 2
            frames[sym] = df.sort_values("timestamp").reset_index(drop=True)
    finally:
        store.close()

    rep = build_multi_symbol_dual_path_report(
        frames,
        run_meta={"window": {"start": args.start, "end": args.end}},
    )
    assert rep.get("promotion_eligible") is False
    assert "combined_score" not in rep

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("=== Multi-symbol dual-path ===")
    print(f"symbols={rep.get('symbols')} book={rep.get('book')}")
    print(f"execution_path={rep.get('run_meta', {}).get('execution_path')}")
    print(f"promotion_eligible={rep.get('promotion_eligible')}")
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
