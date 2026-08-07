#!/usr/bin/env python3
"""M4-6.4 acceptance — real OKX 30-symbol rotation, zero HTTP 429.

Uses a single shared CCXT instance (enableRateLimit=True → one global
throttler) rotating over 30 real OKX symbols. Fails if any request returns
429/rate-limit or raises an unexpected transport error.

    python scripts/verify_okx_throttler.py [--symbols 30] [--rounds 3]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbols", type=int, default=30)
    ap.add_argument("--rounds", type=int, default=3, help="rotation sweeps")
    args = ap.parse_args()

    import ccxt.async_support as ccxt

    exchange = ccxt.okx(
        {"enableRateLimit": True, "timeout": 15000, "options": {"defaultType": "spot"}}
    )
    try:
        markets = None
        for attempt in range(3):
            try:
                markets = await exchange.load_markets()
                break
            except ccxt.RequestTimeout:
                if attempt == 2:
                    raise
                await asyncio.sleep(3.0)
        assert markets is not None
        spot = [s for s in markets if s.endswith("/USDT")][: args.symbols]
        print(f"[throttler] OKX markets loaded; using {len(spot)} spot symbols")

        total_err = 0
        total_429 = 0
        t0 = time.perf_counter()
        for _rnd in range(args.rounds):
            for sym in spot:
                for attempt in range(3):
                    try:
                        bars = await exchange.fetch_ohlcv(sym, "1m", limit=2)
                        if not bars:
                            total_err += 1
                            print(f"  WARN {sym}: empty response")
                        break
                    except ccxt.RateLimitExceeded as e:
                        total_429 += 1
                        print(f"  429 {sym}: {e}")
                        break
                    except ccxt.RequestTimeout as e:
                        if attempt == 2:
                            total_err += 1
                            print(f"  ERR {sym}: RequestTimeout after 3 attempts: {str(e)[:80]}")
                        else:
                            await asyncio.sleep(2.0 * (attempt + 1))
                    except Exception as e:
                        total_err += 1
                        print(f"  ERR {sym}: {type(e).__name__}: {str(e)[:90]}")
                        break
        elapsed = time.perf_counter() - t0

        reqs = args.symbols * args.rounds
        rate = reqs / elapsed if elapsed > 0 else float("inf")
        print(f"[throttler] {reqs} requests in {elapsed:.1f}s ({rate:.1f} req/s)")
        print(f"[throttler] HTTP 429: {total_429} | errors: {total_err}")
        ok = total_429 == 0 and total_err == 0
        print(f"[throttler] {'PASS (zero 429/errors)' if ok else 'FAIL'}")
        return 0 if ok else 1
    finally:
        await exchange.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
