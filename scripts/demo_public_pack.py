#!/usr/bin/env python3
"""Build / verify the public-reproducible demo pack (P2 T009).

No secrets. Writes under docs/demo/:
  - README.md (how to reproduce without API keys)
  - sample_gate.json (synthetic GO/NO-GO structure for docs only)
  - sample_fee_slip_grid.json
  - POSITIONING.md (product positioning + non-goals)

    python scripts/demo_public_pack.py
    python scripts/demo_public_pack.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = REPO_ROOT / "docs" / "demo"

SAMPLE_GATE = {
    "_meta": {
        "kind": "sample_gate",
        "note": "SYNTHETIC example for documentation — not a live research claim",
    },
    "decision": "NO-GO",
    "reason": "Sample: DSR below threshold (illustrative)",
    "checks": {
        "cpcv": {"passed": True, "pbo": 0.32},
        "dsr": {"passed": False, "dsr": 0.81},
        "wfo_rolling": {"passed": True, "oos_efficiency": 0.62},
        "wfo_anchored": {"passed": True, "oos_efficiency": 0.58},
        "cost_fidelity": {
            "passed": False,
            "note": "GO narratives require fee_slip_grid with zero + 0.1%/0.1% cells",
        },
    },
    "fee_slip_grid": [
        {"taker_fee": 0.0, "slippage": 0.0, "sharpe": 1.05, "return_pct": 38.0},
        {"taker_fee": 0.001, "slippage": 0.001, "sharpe": 0.52, "return_pct": 17.0},
    ],
}

SAMPLE_GRID = {
    "_meta": {
        "kind": "sample_fee_slip_grid",
        "note": "Illustrative cost drag; run scripts/reframe_sensitivity_1h.py for real numbers",
    },
    "baseline_fee_slip": {"taker_fee": 0.001, "slippage": 0.001},
    "cells": SAMPLE_GATE["fee_slip_grid"],
    "summary": {
        "cost_drag_pp_approx": 21.0,
        "rule": "Zero-cost Sharpe alone must not drive paper promotion",
    },
}

POSITIONING = """# QuantFlow product positioning (public brief)

## One-liner

**Personal / small-team Crypto mid-frequency research OS** — paper-first,
validation-gate driven (OKX). Not an institutional OEMS, not a SaaS copy-trading
bot, not a Freqtrade drop-in.

## Primary battlefield

Anti-overfit research → **GO/NO-GO gate** → paper day-session → (optional) live.

## Non-goals

- HFT / FPGA / Rust execution core rewrite
- Institutional multi-venue OEMS
- SaaS hosting, mobile, social copy-trading
- Competing on GitHub stars or exchange-connector count
- Claiming backtest byte-parity with paper/live (parity is paper↔live path only)

## Path A vs Path B (do not mix)

| Path | Command | Nested direction gate? | Use |
|------|---------|------------------------|-----|
| **A** Daily paper | `quantflow run --mode paper …` | No | Day-session ops |
| **B** Research / GO | `python scripts/run_baseline0.py` | Yes | Compare to gate.json |

## Reproduce without API keys

```bash
# 1) install
pip install -e ".[dev]"

# 2) optional: use existing local parquet under data/parquet (no OKX keys)
python scripts/preflight_baseline0_paper.py

# 3) day-session (preflight + summary only)
python scripts/paper_day_session.py

# 4) universe SLA dry-run
python scripts/universe_expand_pipeline.py --dry-run-only

# 5) inspect sample gate structure
cat docs/demo/sample_gate.json
```

Paper mode does **not** need `OKX_API_KEY`. Live is out of scope for this demo pack.

## Open-source decision

This pack is **preparation for a possible open release**. Publishing the private
repository remains a separate product decision.
"""

README = """# QuantFlow demo pack (no secrets)

Synthetic + scripted artifacts so a third party can understand **how** QuantFlow
gates research without any exchange credentials.

| File | Purpose |
|------|---------|
| `POSITIONING.md` | Product positioning and non-goals |
| `sample_gate.json` | Shape of a GO/NO-GO report (+ cost fidelity fields) |
| `sample_fee_slip_grid.json` | Cost-grid narrative requirements |
| `../research/baseline0-paper-run-checklist.md` | Full paper day checklist |

## Quick commands

```bash
python scripts/demo_public_pack.py --check
python scripts/preflight_baseline0_paper.py
python scripts/paper_day_session.py
python scripts/universe_expand_pipeline.py --symbols BTC/USDT,ETH/USDT,SOL/USDT --dry-run-only
```

## Hard rules reflected here

1. No GO without fee×slip grid (zero + production cells).
2. Zero-cost-only alpha is rejected at register.
3. Path A paper PnL ≠ Path B nested `gate.json`.
4. Default `portfolio_optimization.enabled=false` in `default.yaml`.
"""


def write_pack() -> list[Path]:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    files = {
        "sample_gate.json": json.dumps(SAMPLE_GATE, indent=2, ensure_ascii=False) + "\n",
        "sample_fee_slip_grid.json": json.dumps(SAMPLE_GRID, indent=2, ensure_ascii=False)
        + "\n",
        "POSITIONING.md": POSITIONING,
        "README.md": README,
    }
    for name, content in files.items():
        path = DEMO_DIR / name
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def check_pack() -> int:
    required = [
        "README.md",
        "POSITIONING.md",
        "sample_gate.json",
        "sample_fee_slip_grid.json",
    ]
    missing = [n for n in required if not (DEMO_DIR / n).is_file()]
    if missing:
        print(f"MISSING: {missing}", file=sys.stderr)
        return 1
    gate = json.loads((DEMO_DIR / "sample_gate.json").read_text(encoding="utf-8"))
    assert "fee_slip_grid" in gate
    assert "decision" in gate
    pos = (DEMO_DIR / "POSITIONING.md").read_text(encoding="utf-8")
    for needle in ("Non-goals", "Path A", "paper-first", "OKX_API_KEY"):
        if needle not in pos:
            print(f"POSITIONING missing {needle!r}", file=sys.stderr)
            return 1
    # Secret scan: no live key patterns in demo dir
    for path in DEMO_DIR.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".json", ".txt", ".yml", ".yaml"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            for bad in ("OKX_SECRET=", "BEGIN RSA", "sk-live", "api_key:"):
                if bad in text:
                    print(f"possible secret material in {path}: {bad}", file=sys.stderr)
                    return 1
    print("demo pack OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="Verify pack only")
    args = ap.parse_args()
    if not args.check:
        for p in write_pack():
            print(f"wrote {p.relative_to(REPO_ROOT)}")
    return check_pack()


if __name__ == "__main__":
    raise SystemExit(main())
