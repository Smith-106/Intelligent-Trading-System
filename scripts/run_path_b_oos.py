#!/usr/bin/env python3
"""Path B multi-window OOS + honest n_trials (research; no live promote)."""

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
from quantflow.strategy.research.dual_path_profiles import path_b_profile  # noqa: E402
from quantflow.strategy.research.path_b_oos import run_path_b_multi_window_oos  # noqa: E402

DEFAULT_OUT = ROOT / "data" / "paper_replay" / "dual_path" / "path_b_oos.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2026-08-04")
    ap.add_argument("--n-windows", type=int, default=4)
    ap.add_argument("--oos-ratio", type=float, default=0.3)
    ap.add_argument("--mode", choices=["rolling", "anchored"], default="rolling")
    ap.add_argument("--fixed-params", action="store_true")
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

    rep = run_path_b_multi_window_oos(
        df,
        profile=path_b_profile(),
        n_windows=args.n_windows,
        oos_ratio=args.oos_ratio,
        mode=args.mode,
        fixed_params=args.fixed_params,
    )
    assert rep.get("promotion_eligible") is False
    assert "combined_score" not in rep

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    s = rep["summary"]
    print("=== Path B multi-window OOS ===")
    print(f"research_go={rep['research_go']} go_discussion_allowed={rep['go_discussion_allowed']}")
    print(f"n_trials_accounted={rep['n_trials_accounted']} underreported={rep['underreported']}")
    print(
        f"windows={s['n_windows_eval']} frac_beat_btc={s['frac_beat_btc']:.2f} "
        f"median_excess={s['median_oos_excess_pct']:.4f} median_dd={s['median_oos_max_dd_pct']:.4f}"
    )
    print(f"promotion_eligible={rep['promotion_eligible']} hard_bind_entry={rep['hard_bind_entry']}")
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
