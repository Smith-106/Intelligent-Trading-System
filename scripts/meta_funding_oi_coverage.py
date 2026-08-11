#!/usr/bin/env python3
"""Wave B1: offline funding/OI density probe vs OHLCV pin (no freeze edits).

Reports coverage for symbols under data/parquet meta_* partitions and
compares timestamp spans to OHLCV (when present). Does **not** call live API
and does **not** modify B3-B5 strategy freezes.

Usage:
  set PYTHONUTF8=1
  python scripts/meta_funding_oi_coverage.py
  python scripts/meta_funding_oi_coverage.py --out data/paper_replay/meta_coverage.json
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

DEFAULT_SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
# Meta partitions historically used underscore / swap aliases.
META_ALIASES: dict[str, tuple[str, ...]] = {
    "BTC/USDT": ("BTC/USDT", "BTC_USDT", "BTC-USDT-SWAP"),
    "ETH/USDT": ("ETH/USDT", "ETH_USDT", "ETH-USDT-SWAP"),
    "SOL/USDT": ("SOL/USDT", "SOL_USDT", "SOL-USDT-SWAP"),
}


def _ms_to_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat()


def _frame_span(df: Any) -> dict[str, Any]:
    if df is None or getattr(df, "empty", True):
        return {"n": 0, "min_ms": None, "max_ms": None, "min_iso": None, "max_iso": None}
    ts = df["timestamp"] if "timestamp" in df.columns else None
    if ts is None:
        return {"n": len(df), "min_ms": None, "max_ms": None, "min_iso": None, "max_iso": None}
    mn, mx = int(ts.min()), int(ts.max())
    return {
        "n": len(df),
        "min_ms": mn,
        "max_ms": mx,
        "min_iso": _ms_to_iso(mn),
        "max_iso": _ms_to_iso(mx),
    }


def probe_symbol(store: Any, symbol: str) -> dict[str, Any]:
    ohlcv_range = store.get_date_range(symbol)
    ohlcv: dict[str, Any]
    if ohlcv_range is None:
        ohlcv = {
            "min_ms": None,
            "max_ms": None,
            "min_iso": None,
            "max_iso": None,
            "span_days": None,
        }
    else:
        mn, mx = int(ohlcv_range[0]), int(ohlcv_range[1])
        ohlcv = {
            "min_ms": mn,
            "max_ms": mx,
            "min_iso": _ms_to_iso(mn),
            "max_iso": _ms_to_iso(mx),
            "span_days": round((mx - mn) / 86_400_000, 1),
        }

    aliases = META_ALIASES.get(symbol, (symbol, symbol.replace("/", "_")))
    funding_best: dict[str, Any] | None = None
    oi_best: dict[str, Any] | None = None
    per_alias: list[dict[str, Any]] = []
    for alias in aliases:
        f = store.query_funding_rates(alias)
        oi = store.query_open_interest(alias)
        f_span = _frame_span(f)
        oi_span = _frame_span(oi)
        per_alias.append({"alias": alias, "funding": f_span, "open_interest": oi_span})
        if funding_best is None or f_span["n"] > funding_best["n"]:
            funding_best = {**f_span, "alias": alias}
        if oi_best is None or oi_span["n"] > oi_best["n"]:
            oi_best = {**oi_span, "alias": alias}

    assert funding_best is not None and oi_best is not None

    # Coverage vs OHLCV pin: fraction of OHLCV span that meta max-min covers (coarse).
    def coverage_ratio(meta: dict[str, Any]) -> float | None:
        if not ohlcv["min_ms"] or not ohlcv["max_ms"] or not meta["min_ms"] or not meta["max_ms"]:
            return None
        ohlcv_span = max(1, ohlcv["max_ms"] - ohlcv["min_ms"])
        overlap_lo = max(ohlcv["min_ms"], meta["min_ms"])
        overlap_hi = min(ohlcv["max_ms"], meta["max_ms"])
        if overlap_hi <= overlap_lo:
            return 0.0
        return round((overlap_hi - overlap_lo) / ohlcv_span, 4)

    return {
        "symbol": symbol,
        "ohlcv": ohlcv,
        "funding_best": funding_best,
        "open_interest_best": oi_best,
        "funding_coverage_vs_ohlcv": coverage_ratio(funding_best),
        "oi_coverage_vs_ohlcv": coverage_ratio(oi_best),
        "aliases": per_alias,
        "notes": (
            "Sparse funding/OI relative to OHLCV is expected for pre-2026 history; "
            "B3-B5 freezes must not be edited — open B6-META for denser contracts."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--parquet-dir",
        default=str(REPO_ROOT / "data" / "parquet"),
        help="Parquet root (default: data/parquet)",
    )
    ap.add_argument(
        "--symbols",
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated spot symbols",
    )
    ap.add_argument(
        "--out",
        default="",
        help="Optional JSON output path",
    )
    args = ap.parse_args()

    from quantflow.data.store import DataStore

    store = DataStore(str(Path(args.parquet_dir)), ":memory:")
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    rows = [probe_symbol(store, sym) for sym in symbols]
    report: dict[str, Any] = {
        "kind": "meta_funding_oi_coverage",
        "wave": "B1",
        "as_of": datetime.now(UTC).isoformat(),
        "parquet_dir": str(Path(args.parquet_dir).resolve()),
        "symbols": rows,
        "honesty": {
            "does_not_edit_b3_b5_freezes": True,
            "does_not_live_promote": True,
            "okx_history_note": "OKX funding history often ~3 months; full OHLCV pin is multi-year",
        },
    }

    # Human table
    print("=== meta funding/OI coverage (offline) ===")
    print(f"{'symbol':12} {'f_n':>8} {'oi_n':>8} {'f_cov':>8} {'oi_cov':>8} funding_span")
    for r in rows:
        fb, ob = r["funding_best"], r["open_interest_best"]
        print(
            f"{r['symbol']:12} {fb['n']:8d} {ob['n']:8d} "
            f"{r['funding_coverage_vs_ohlcv']!s:>8} {r['oi_coverage_vs_ohlcv']!s:>8} "
            f"{fb.get('min_iso')} → {fb.get('max_iso')}"
        )

    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"written {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
