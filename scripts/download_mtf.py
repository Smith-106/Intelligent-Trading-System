#!/usr/bin/env python3
"""Download multi-timeframe OHLCV for a symbol into the local Parquet store.

Coarse TFs (1h+) default to full history from --start-coarse; fine TFs
(sub-1h) default to --start-fine to control storage and WFO cost.

    python scripts/download_mtf.py --symbol BTC/USDT
    python scripts/download_mtf.py --tfs 4h,1d --end 2026-08-04
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quantflow.common.config import load_config  # noqa: E402
from quantflow.data.cleaner import clean_ohlcv  # noqa: E402
from quantflow.data.fetcher import TIMEFRAMES, DataFetcher  # noqa: E402
from quantflow.data.store import DataStore  # noqa: E402

DEFAULT_TFS = ["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]
FINE_TFS = {"1m", "3m", "5m", "15m", "30m"}


async def _download_one(
    fetcher: DataFetcher,
    store: DataStore,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
) -> dict[str, object]:
    print(f"[dl] {symbol} {timeframe} {start}→{end} ...", flush=True)
    df = await fetcher.fetch_ohlcv(symbol, timeframe, start, end)
    if df.empty:
        return {"timeframe": timeframe, "bars": 0, "status": "empty"}
    df = clean_ohlcv(df)
    store.save(df, symbol)
    # Re-query to report stored coverage for this TF only.
    covered = store.query(symbol, timeframe=timeframe)
    return {
        "timeframe": timeframe,
        "bars": len(covered),
        "raw_fetched": len(df),
        "status": "ok",
        "min_ts": int(covered["timestamp"].min()) if not covered.empty else None,
        "max_ts": int(covered["timestamp"].max()) if not covered.empty else None,
    }


async def _run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    tfs = [t.strip() for t in args.tfs.split(",") if t.strip()]
    for tf in tfs:
        if tf not in TIMEFRAMES:
            raise SystemExit(f"Invalid timeframe {tf!r}. Allowed: {TIMEFRAMES}")

    fetcher = DataFetcher(cfg.data)
    store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)
    results: list[dict[str, object]] = []
    try:
        await fetcher.connect()
        for tf in tfs:
            start = args.start_fine if tf in FINE_TFS else args.start_coarse
            try:
                res = await _download_one(fetcher, store, args.symbol, tf, start, args.end)
            except Exception as exc:
                print(f"[dl] FAIL {tf}: {exc}", flush=True)
                results.append({"timeframe": tf, "bars": 0, "status": f"error:{exc}"})
                continue
            results.append(res)
            print(f"[dl] {tf}: {res['status']} bars={res['bars']}", flush=True)
    finally:
        await fetcher.disconnect()
        store.close()

    print("\n[dl] coverage summary")
    for r in results:
        print(f"  {r['timeframe']:>4}  bars={r['bars']:<8}  {r['status']}")
    ok = sum(
        1
        for r in results
        if r["status"] == "ok" and isinstance(r["bars"], int) and r["bars"] > 0
    )
    print(f"[dl] ok={ok}/{len(results)}")
    return 0 if ok > 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--tfs", default=",".join(DEFAULT_TFS))
    ap.add_argument("--start-coarse", default="2019-01-01")
    ap.add_argument("--start-fine", default="2021-01-01")
    ap.add_argument("--end", default="2026-08-04")
    ap.add_argument("--config", default="quantflow/config/default.yaml")
    return asyncio.run(_run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
