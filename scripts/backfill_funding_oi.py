#!/usr/bin/env python3
"""Wave B1: optional funding/OI history backfill into DataStore (network).

Uses MarketMetaFetcher + DataStore.save_*. Does **not** edit B3-B5 freezes.
OKX typically serves ~3 months of funding history — denser multi-year pin is
not guaranteed; open **B6-META** contracts rather than lowering entry thr.

Usage (requires network / exchange credentials as configured for public REST):
  set PYTHONUTF8=1
  python scripts/backfill_funding_oi.py --symbols BTC/USDT --dry-run
  python scripts/backfill_funding_oi.py --symbols BTC/USDT,ETH/USDT --since-days 90

Default is **dry-run** (probe only). Pass ``--execute`` to write parquet.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


async def _backfill_one(
    *,
    symbol: str,
    since_ms: int,
    execute: bool,
    parquet_dir: Path,
) -> dict[str, Any]:
    from quantflow.common.config import load_config
    from quantflow.data.market_meta_fetcher import MarketMetaFetcher
    from quantflow.data.store import DataStore

    cfg = load_config(REPO_ROOT / "quantflow" / "config" / "default.yaml")
    store = DataStore(str(parquet_dir), ":memory:")
    fetcher = MarketMetaFetcher(cfg.data)
    result: dict[str, Any] = {
        "symbol": symbol,
        "since_ms": since_ms,
        "execute": execute,
        "funding_rows": 0,
        "oi_rows": 0,
        "status": "ok",
    }
    try:
        await fetcher.connect()
        funding = await fetcher.fetch_funding_rate_history(symbol, since_ms=since_ms)
        result["funding_rows"] = 0 if funding is None else len(funding)
        # OI history may be thinner / endpoint-dependent
        oi = None
        if hasattr(fetcher, "fetch_open_interest_history"):
            try:
                oi = await fetcher.fetch_open_interest_history(symbol, since_ms=since_ms)
            except Exception as exc:
                result["oi_history_error"] = f"{type(exc).__name__}: {exc}"
        if oi is not None and not getattr(oi, "empty", True):
            result["oi_rows"] = len(oi)
        else:
            # snapshot only as soft fallback note
            try:
                snap = await fetcher.fetch_open_interest(symbol)
                result["oi_snapshot"] = {
                    "open_interest": getattr(snap, "open_interest", None),
                    "timestamp": getattr(snap, "timestamp", None),
                }
            except Exception as exc:
                result["oi_snapshot_error"] = f"{type(exc).__name__}: {exc}"

        if execute and funding is not None and not funding.empty:
            store.save_funding_rates(funding, symbol.replace("/", "_"))
            result["funding_saved_as"] = symbol.replace("/", "_")
        if execute and oi is not None and not getattr(oi, "empty", True):
            store.save_open_interest(oi, symbol.replace("/", "_"))
            result["oi_saved_as"] = symbol.replace("/", "_")
        if not execute:
            result["status"] = "dry_run"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        with contextlib.suppress(Exception):
            await fetcher.disconnect()
        store.close()
    return result


async def _amain(args: argparse.Namespace) -> int:
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    since = datetime.now(UTC) - timedelta(days=int(args.since_days))
    since_ms = int(since.timestamp() * 1000)
    parquet_dir = Path(args.parquet_dir)
    if not parquet_dir.is_absolute():
        parquet_dir = REPO_ROOT / parquet_dir

    print(
        f"[backfill] symbols={symbols} since_days={args.since_days} "
        f"execute={args.execute} parquet={parquet_dir}",
        flush=True,
    )
    print(
        "[backfill] honesty: does not edit B3-B5 freezes; "
        "OKX history ~3 months typical; use B6-META for new contracts",
        flush=True,
    )
    t0 = time.time()
    rows = []
    for sym in symbols:
        row = await _backfill_one(
            symbol=sym,
            since_ms=since_ms,
            execute=bool(args.execute),
            parquet_dir=parquet_dir,
        )
        rows.append(row)
        print(
            f"  {sym}: status={row['status']} funding_rows={row['funding_rows']} "
            f"oi_rows={row['oi_rows']}",
            flush=True,
        )
    print(f"[backfill] done in {time.time() - t0:.1f}s", flush=True)
    if args.out:
        import json

        out = Path(args.out)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "kind": "funding_oi_backfill",
            "wave": "B1",
            "as_of": datetime.now(UTC).isoformat(),
            "execute": bool(args.execute),
            "since_days": int(args.since_days),
            "results": rows,
            "honesty": {
                "does_not_edit_b3_b5_freezes": True,
                "default_dry_run": not bool(args.execute),
            },
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"written {out}", flush=True)
    # dry-run always 0; execute errors → 1
    if any(r.get("status") == "error" for r in rows) and args.execute:
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbols", default="BTC/USDT", help="Comma-separated symbols")
    ap.add_argument("--since-days", type=int, default=90)
    ap.add_argument(
        "--parquet-dir",
        default="data/parquet",
        help="Parquet root relative to repo",
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        help="Actually write meta parquet (default: dry-run)",
    )
    ap.add_argument("--out", default="", help="Optional JSON receipt path")
    args = ap.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
