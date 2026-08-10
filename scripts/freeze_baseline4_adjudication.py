#!/usr/bin/env python3
"""Materialize B4 adjudication freeze from a baseline4 run package (W26a).

Copies the template, fills fields from run_meta/adjudication when present,
writes ``adjudication_frozen.json`` under the run dir. Never upgrades to GO.
Never writes baseline3/.

    python scripts/freeze_baseline4_adjudication.py --run-dir data/paper_replay/baseline4/smoke
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "docs" / "research" / "baseline4-adjudication-freeze-template.json"
FORBIDDEN = REPO_ROOT / "data" / "paper_replay" / "baseline3"


def _refuse_b3(path: Path) -> None:
    r = path.resolve()
    if "baseline3" in r.parts:
        raise SystemExit(f"[b4-freeze] REFUSED baseline3 path: {r}")


def freeze(run_dir: Path) -> Path:
    _refuse_b3(run_dir)
    if not run_dir.is_dir():
        raise SystemExit(f"[b4-freeze] missing run dir: {run_dir}")
    tmpl: dict[str, Any] = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    meta_path = run_dir / "run_meta.json"
    adj_path = run_dir / "adjudication.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    adj = json.loads(adj_path.read_text(encoding="utf-8")) if adj_path.is_file() else {}

    out = dict(tmpl)
    out["status"] = "FROZEN"
    out["frozen_at"] = datetime.now(UTC).isoformat()
    out["source_run"] = str(run_dir).replace("\\", "/")
    out["verdict"] = adj.get("promotion") or adj.get("verdict") or "KEEP_BASELINE_0"
    out["upgrade"] = False
    out["keep_baseline0"] = True
    out["data_status"] = adj.get("status") or meta.get("mode") or "UNKNOWN"
    results = meta.get("results") or {}
    ch = results.get("funding_rate_b4") or {}
    cl = results.get("classic") or {}
    out["challenger"] = {
        "label": "funding_rate_b4",
        "full_orders": ch.get("n_fills"),
        "full_return_pct": ch.get("total_return_pct"),
        "full_sharpe": ch.get("sharpe_annualized"),
        "notes": adj.get("notes") or meta.get("notes") or [],
    }
    out["classic_control"] = {
        "full_return_pct": cl.get("total_return_pct"),
        "full_sharpe": cl.get("sharpe_annualized"),
        "full_orders": cl.get("n_fills"),
    }
    if meta.get("params"):
        out["b4_params"] = meta["params"]
    dest = run_dir / "adjudication_frozen.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-dir", required=True, help="baseline4/<run_id> directory")
    args = ap.parse_args(argv)
    run_dir = Path(args.run_dir)
    if not run_dir.is_absolute():
        run_dir = REPO_ROOT / run_dir
    try:
        dest = freeze(run_dir)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "frozen": str(dest).replace("\\", "/")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
