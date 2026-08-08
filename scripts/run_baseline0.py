#!/usr/bin/env python3
"""Run Candidate Baseline-0 reproduction (paper shared-book symbol RP).

Locked contract: docs/research/Candidate-Baseline-0.md

Writes:
  data/paper_replay/baseline0/multi_symbol_replay.json
  data/paper_replay/baseline0/wfo_shared_rp.json
  data/paper_replay/baseline0/run_meta.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Locked contract values (must match Candidate-Baseline-0.md)
SYMBOLS = "BTC/USDT,ETH/USDT,SOL/USDT"
START = "2021-01-01"
END = "2026-08-04"
GATE = "nested"
FEE = "0.001"
SLIP = "0.001"
TRAIN_MONTHS = "24"
FWD_MONTHS = "6"
REBALANCE_BARS = "48"
OUT_DIR = REPO_ROOT / "data" / "paper_replay" / "baseline0"


def _run(cmd: list[str]) -> int:
    print("[baseline0]", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    return int(proc.returncode)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-full", action="store_true", help="Skip multi_symbol full-window run")
    ap.add_argument("--skip-wfo", action="store_true", help="Skip WFO OOS run")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    rc = 0

    if not args.skip_full:
        full_out = OUT_DIR / "multi_symbol_replay.json"
        rc = _run(
            [
                py,
                str(REPO_ROOT / "scripts" / "multi_symbol_replay.py"),
                "--symbols",
                SYMBOLS,
                "--start",
                START,
                "--end",
                END,
                "--gate",
                GATE,
                "--fee",
                FEE,
                "--slip",
                SLIP,
                "--out",
                str(full_out.relative_to(REPO_ROOT)).replace("\\", "/"),
            ]
        )
        if rc != 0:
            return rc

    if not args.skip_wfo:
        wfo_out = OUT_DIR / "wfo_shared_rp.json"
        rc = _run(
            [
                py,
                str(REPO_ROOT / "scripts" / "wfo_shared_rp.py"),
                "--symbols",
                SYMBOLS,
                "--start",
                START,
                "--end",
                END,
                "--train-months",
                TRAIN_MONTHS,
                "--fwd-months",
                FWD_MONTHS,
                "--gate",
                GATE,
                "--fee",
                FEE,
                "--slip",
                SLIP,
                "--rebalance-bars",
                REBALANCE_BARS,
                "--out",
                str(wfo_out.relative_to(REPO_ROOT)).replace("\\", "/"),
            ]
        )
        if rc != 0:
            return rc

    meta = {
        "contract": "docs/research/Candidate-Baseline-0.md",
        "ran_at": datetime.now(UTC).isoformat(),
        "symbols": SYMBOLS,
        "start": START,
        "end": END,
        "gate": GATE,
        "fee": float(FEE),
        "slip": float(SLIP),
        "train_months": int(TRAIN_MONTHS),
        "fwd_months": int(FWD_MONTHS),
        "rebalance_bars": int(REBALANCE_BARS),
        "skip_full": args.skip_full,
        "skip_wfo": args.skip_wfo,
        "outputs": {
            "full": "data/paper_replay/baseline0/multi_symbol_replay.json",
            "wfo": "data/paper_replay/baseline0/wfo_shared_rp.json",
        },
    }
    meta_path = OUT_DIR / "run_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[baseline0] meta written {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
