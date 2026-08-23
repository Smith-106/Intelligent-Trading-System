"""Multi-timeframe analysis service (PERF-REV015).

POST /api/analysis/multi-tf — simultaneous analysis across up to 24 derived
timeframes per symbol. Latency contract (perf_api audit): each symbol reads
its base grid from the store exactly once, then all timeframes are resampled
in memory — never per-TF fetches (that would multiply parquet/network reads
by 24×).
"""

from __future__ import annotations

import asyncio
from typing import Any

from quantflow.common.config import load_config
from quantflow.data.resample import (
    ANALYSIS_TIMEFRAMES,
    base_timeframe_for,
    resample_ohlcv,
)
from quantflow.web.service import StationService, _open_station_store, resolve_config_path_safe

__all__ = ["MAX_MULTI_TF_SYMBOLS", "MultiTfRequest", "multi_tf_analysis"]

MAX_MULTI_TF_SYMBOLS = 50


class MultiTfRequest:
    """Validated request payload for /api/analysis/multi-tf."""

    def __init__(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        symbols = payload.get("symbols")
        if not isinstance(symbols, list) or not symbols:
            raise ValueError("symbols must be a non-empty array.")
        if len(symbols) > MAX_MULTI_TF_SYMBOLS:
            raise ValueError(f"symbols limited to {MAX_MULTI_TF_SYMBOLS}.")
        self.symbols = [str(s) for s in symbols]

        timeframes = payload.get("timeframes") or list(ANALYSIS_TIMEFRAMES)
        if not isinstance(timeframes, list) or len(timeframes) > len(ANALYSIS_TIMEFRAMES):
            raise ValueError(f"timeframes limited to {len(ANALYSIS_TIMEFRAMES)} entries.")
        unknown = [tf for tf in timeframes if tf not in ANALYSIS_TIMEFRAMES]
        if unknown:
            raise ValueError(f"Unsupported timeframes: {unknown}")
        self.timeframes = [str(tf) for tf in timeframes]

        self.start = payload.get("start")
        self.end = payload.get("end")
        fields = payload.get("fields", "meta")
        if fields not in ("full", "meta"):
            raise ValueError("fields must be 'full' or 'meta'.")
        self.fields = fields


def _analyze_symbol(
    service: StationService,
    symbol: str,
    timeframes: list[str],
    start: str | None,
    end: str | None,
    include_candles: bool,
) -> dict[str, Any]:
    """One symbol: a single base-grid read, then in-memory resampling."""
    config = load_config(resolve_config_path_safe(service.config_path))
    store = _open_station_store(config)

    warnings: list[str] = []
    tf_results: list[dict[str, Any]] = []
    base_cache: dict[str, Any] = {}

    for tf in sorted(set(timeframes), key=lambda t: -_order(t)):
        try:
            base_tf = base_timeframe_for(tf)
        except ValueError as e:
            warnings.append(f"{symbol} {tf}: {e}")
            continue
        if base_tf not in base_cache:
            frame = store.query(symbol, timeframe=base_tf, start=start, end=end)
            base_cache[base_tf] = frame
        base = base_cache[base_tf]
        if base.empty:
            tf_results.append(
                {"timeframe": tf, "bars": 0, "insufficient_data": True}
            )
            continue
        derived = resample_ohlcv(base, tf)
        if derived.empty:
            tf_results.append({"timeframe": tf, "bars": 0, "insufficient_data": True})
            continue
        entry: dict[str, Any] = {
            "timeframe": tf,
            "bars": len(derived),
            "insufficient_data": False,
            "last_close": (
                derived["close"].iloc[-1].item()
                if hasattr(derived["close"].iloc[-1], "item")
                else float(derived["close"].iloc[-1])
            ),
            "last_timestamp": int(derived["timestamp"].iloc[-1]),
        }
        if include_candles:
            entry["candles"] = derived[
                ["timestamp", "open", "high", "low", "close", "volume"]
            ].to_dict(orient="records")
        tf_results.append(entry)

    return {"symbol": symbol, "partial": bool(warnings), "warnings": warnings, "timeframes": tf_results}


def _order(tf: str) -> int:
    from quantflow.data.resample import timeframe_to_ms

    return timeframe_to_ms(tf)


async def multi_tf_analysis(service: StationService, request: MultiTfRequest) -> dict[str, Any]:
    """Async entrypoint: fan out per-symbol analysis onto the thread pool."""
    include_candles = request.fields == "full"
    loop = asyncio.get_running_loop()
    results = await asyncio.gather(
        *(
            loop.run_in_executor(
                None,
                _analyze_symbol,
                service,
                sym,
                request.timeframes,
                request.start,
                request.end,
                include_candles,
            )
            for sym in request.symbols
        ),
        return_exceptions=True,
    )

    out: list[dict[str, Any]] = []
    warnings: list[str] = []
    partial = False
    for sym, res in zip(request.symbols, results, strict=True):
        if isinstance(res, BaseException):
            partial = True
            warnings.append(f"{sym}: analysis failed ({res})")
            out.append({"symbol": sym, "partial": True, "warnings": [str(res)], "timeframes": []})
        else:
            partial = partial or bool(res["partial"])
            warnings.extend(res["warnings"])
            out.append(res)

    return {"partial": partial, "warnings": warnings, "results": out}
