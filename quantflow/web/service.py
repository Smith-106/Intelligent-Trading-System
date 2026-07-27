"""Application service layer for QuantFlow Station."""

from __future__ import annotations

import json
import logging
import math
import socket
import subprocess
import time
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, field_validator

from quantflow import __version__

# resolve_config_path is re-exported here only so existing test patches
# (`patch("quantflow.web.service.resolve_config_path")`) keep working; the web
# layer resolves request-supplied paths via resolve_config_path_safe only
# (ISS-019). Do not add new call sites of the unsafe variant in this module.
from quantflow.common.config import (  # noqa: F401
    load_config,
    resolve_config_path,
    resolve_config_path_safe,
)
from quantflow.common.exceptions import DataError
from quantflow.common.numeric import safe_number
from quantflow.common.validators import validate_symbol
from quantflow.data.store import DataStore
from quantflow.monitoring.metrics import metrics_registry_snapshot, metrics_server_status
from quantflow.strategy.catalog import (
    get_strategy_definition,
    list_strategy_summaries,
)
from quantflow.strategy.research.backtest import BacktestEngine, BacktestResult
from quantflow.strategy.research.report import generate_report
from quantflow.web.history import StationHistoryStore

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "quantflow/config/default.yaml"
MAX_CHART_POINTS = 720
DEFAULT_VISIBLE_BARS = 180
_MAX_WORKBENCH_STATE_BYTES = 64 * 1024

# ISS-001 (SEC-007): bound the user-supplied strategy ``params`` dict so a
# deeply-nested or huge payload cannot be used as a memory-amplification /
# DoS vector. Strategy params are flat (a few scalar hyperparameters); a depth
# > 4 or > 32 keys is never legitimate.
_MAX_PARAMS_DEPTH = 4
_MAX_PARAMS_KEYS = 32


def _validate_params_depth(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Reject overly-deep or oversized params payloads (ISS-001)."""
    if value is None:
        return None

    def _depth_and_keys(node: Any, depth: int) -> tuple[int, int]:
        if isinstance(node, dict):
            if depth > _MAX_PARAMS_DEPTH:
                raise ValueError(f"params nesting exceeds max depth {_MAX_PARAMS_DEPTH}")
            keys = len(node)
            sub_depth = depth
            sub_keys = keys
            for v in node.values():
                d, k = _depth_and_keys(v, depth + 1)
                sub_depth = max(sub_depth, d)
                sub_keys += k
            return sub_depth, sub_keys
        if isinstance(node, list | tuple):
            sub_depth = depth
            sub_keys = 0
            for v in node:
                d, k = _depth_and_keys(v, depth + 1)
                sub_depth = max(sub_depth, d)
                sub_keys += k
            return sub_depth, sub_keys
        return depth, 0

    _, total_keys = _depth_and_keys(value, 1)
    if total_keys > _MAX_PARAMS_KEYS:
        raise ValueError(f"params payload has too many keys ({total_keys} > {_MAX_PARAMS_KEYS})")
    return value


class ResearchRequest(BaseModel):
    strategy: str = "trend_following"
    symbol: str = "BTC/USDT"
    start: str | None = None
    end: str | None = None
    capital: float = 10000.0
    fee: float = 0.001
    config_path: str = DEFAULT_CONFIG_PATH
    params: dict[str, Any] | None = None

    @field_validator("params")
    @classmethod
    def _bound_params(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return _validate_params_depth(v)

    @field_validator("symbol")
    @classmethod
    def _validate_symbol(cls, v: str) -> str:
        validate_symbol(v)
        return v


class ValidationRequest(BaseModel):
    strategy: str = "trend_following"
    symbol: str = "BTC/USDT"
    method: str = "gate"
    groups: int = 4
    test_groups: int = 1
    n_trials: int = 50
    optimize_trials: int = 10
    optimize_method: str = "random"
    optimize_objective: str = "sharpe"
    wfo_windows: int = 2
    capital: float = 10000.0
    fee: float = 0.001
    config_path: str = DEFAULT_CONFIG_PATH
    params: dict[str, Any] | None = None

    @field_validator("params")
    @classmethod
    def _bound_params(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return _validate_params_depth(v)

    @field_validator("symbol")
    @classmethod
    def _validate_symbol(cls, v: str) -> str:
        validate_symbol(v)
        return v


class DataDownloadRequest(BaseModel):
    symbol: str = "BTC/USDT"
    timeframe: str = "4h"
    start: str = "2025-01-01"
    end: str = "2025-12-31"
    config_path: str = DEFAULT_CONFIG_PATH


class DataSourceTagRequest(BaseModel):
    symbol: str = "BTC/USDT"
    data_source: str = "okx"
    config_path: str = DEFAULT_CONFIG_PATH


def _demo_freq_for_timeframe(timeframe: str) -> str:
    mapping = {
        "1m": "1min",
        "5m": "5min",
        "15m": "15min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1D",
    }
    return mapping.get(timeframe, "4h")


_PROBE_TTL_SECONDS = 3.0
_port_reachable_cache: dict[tuple[str, int], tuple[float, bool]] = {}
_docker_available_cache: tuple[float, bool] | None = None


def _monotonic() -> float:
    return time.monotonic()


def _reset_probe_cache() -> None:
    """Clear cached probe results (primarily for tests)."""
    global _docker_available_cache
    _port_reachable_cache.clear()
    _docker_available_cache = None


def _docker_available() -> bool:
    global _docker_available_cache
    now = _monotonic()
    if (
        _docker_available_cache is not None
        and now - _docker_available_cache[0] < _PROBE_TTL_SECONDS
    ):
        return _docker_available_cache[1]
    try:
        result = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=5)
        available = result.returncode == 0
    except Exception:
        available = False
    _docker_available_cache = (now, available)
    return available


def _port_reachable(host: str, port: int, *, timeout: float = 0.35) -> bool:
    """Probe reachability with a short TTL cache.

    The probe uses a blocking ``socket.create_connection``; caching the result
    for a few seconds means a polling web UI does not stall the event loop on
    every request. (A fully non-blocking variant would use asyncio; tracked
    as a follow-up.)
    """
    key = (host, int(port))
    now = _monotonic()
    cached = _port_reachable_cache.get(key)
    if cached is not None and now - cached[0] < _PROBE_TTL_SECONDS:
        return cached[1]
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            available = True
    except OSError:
        available = False
    _port_reachable_cache[key] = (now, available)
    return available


def _timestamp_to_iso(value: Any) -> str | None:
    try:
        if value is None:
            return None
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _safe_number(value: Any) -> Any:
    """Convert non-finite numeric values to None for JSON-safe payloads.

    Delegates to the single source of truth in ``common.numeric``
    (odyssey-review ARCH+SEC finding: this and ``session_manager._safe_number``
    had diverged — session_manager lacked the numpy branches, letting
    ``np.float64`` NaN reach JSONL persistence).
    """
    return safe_number(value)


def _latency_average(total: Any, count: Any) -> float | None:
    try:
        total_value = float(total)
        count_value = float(count)
    except (TypeError, ValueError):
        return None
    if count_value <= 0 or not math.isfinite(total_value) or not math.isfinite(count_value):
        return None
    return total_value / count_value


def _build_demo_frame(
    symbol: str,
    *,
    start: str | None = None,
    end: str | None = None,
    bars: int = 360,
    timeframe: str = "4h",
) -> pd.DataFrame:
    """Build a deterministic synthetic OHLCV frame for empty workspaces."""
    end_ts = pd.Timestamp(end, tz="UTC") if end else pd.Timestamp.now(tz="UTC").floor("h")
    freq = _demo_freq_for_timeframe(timeframe)
    if start:
        start_ts = pd.Timestamp(start, tz="UTC")
        candidate_index = pd.date_range(start_ts, end_ts, freq=freq)
        if len(candidate_index) == 0:
            index = pd.date_range(start_ts, periods=bars, freq=freq, tz="UTC")
        elif len(candidate_index) > bars:
            positions = np.linspace(0, len(candidate_index) - 1, num=bars, dtype=int)
            index = candidate_index[sorted(set([*positions.tolist(), len(candidate_index) - 1]))]
        else:
            # Keep the requested end anchor, but backfill enough history so
            # demo-backed research / validation / session replay have a real window.
            index = pd.date_range(end=end_ts, periods=bars, freq=freq, tz="UTC")
    else:
        index = pd.date_range(end=end_ts, periods=bars, freq=freq, tz="UTC")

    rng = np.random.default_rng(42)
    trend = np.linspace(0.0, 1800.0, len(index))
    seasonality = np.sin(np.linspace(0.0, 18.0, len(index))) * 500.0
    noise = rng.normal(0.0, 140.0, len(index))
    close = 42000.0 + trend + seasonality + noise
    open_ = close + rng.normal(0.0, 60.0, len(index))
    high = np.maximum(open_, close) + rng.uniform(20.0, 180.0, len(index))
    low = np.minimum(open_, close) - rng.uniform(20.0, 180.0, len(index))
    volume = rng.uniform(120.0, 1600.0, len(index))
    return pd.DataFrame(
        {
            "timestamp": [int(ts.timestamp() * 1000) for ts in index],
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "symbol": symbol,
            "timeframe": timeframe,
        },
        index=index,
    )


def _to_jsonable(value: Any) -> Any:
    """Recursively coerce ``value`` to JSON-safe form (ISS-041).

    Thin wrapper over ``quantflow.common.jsonable.to_jsonable`` so the
    serialization policy (dict / list / Path / numpy / pandas Series /
    pandas Timestamp / non-finite float) has a single owner. Previously
    this 7-branch copy diverged from ``session_manager._jsonable`` (4
    branches), leaking pandas values to JSONL. Kept as an underscored
    module name for back-compat (tests patch ``_series_payload`` etc.).
    """
    from quantflow.common.jsonable import to_jsonable

    return to_jsonable(value)


def _series_payload(series: pd.Series, *, max_points: int = 300) -> dict[str, list[Any]]:
    """Down-sample a pandas Series to a {labels, values} JSON payload.

    Thin wrapper over ``quantflow.common.jsonable.series_payload`` so the
    sampling policy lives in one place. Kept underscored for back-compat.
    """
    from quantflow.common.jsonable import series_payload as _series_payload_impl

    return _series_payload_impl(series, max_points=max_points)


def _label_for_index(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return str(value.isoformat())
    return str(value)


def _numeric_series(frame: pd.DataFrame, column: str, fallback: pd.Series) -> pd.Series:
    if column not in frame.columns:
        return fallback
    series = pd.to_numeric(frame[column], errors="coerce")
    return series.fillna(fallback)


def _chart_positions(length: int, *, max_points: int = MAX_CHART_POINTS) -> list[int]:
    if length <= max_points:
        return list(range(length))

    raw = np.linspace(0, length - 1, num=max_points, dtype=int).tolist()
    positions = sorted(set([*raw, length - 1]))
    return positions


def _line_values(series: pd.Series, positions: list[int]) -> list[float | None]:
    values: list[float | None] = []
    for position in positions:
        number = _safe_number(float(series.iloc[position]))
        values.append(None if number is None else round(float(number), 6))
    return values


def _nearest_chart_index(position: int, positions: list[int]) -> int:
    index = bisect_left(positions, position)
    if index <= 0:
        return 0
    if index >= len(positions):
        return len(positions) - 1
    before = positions[index - 1]
    after = positions[index]
    return index if abs(after - position) < abs(position - before) else index - 1


def _marker_payload(
    signal_series: pd.Series,
    price_series: pd.Series,
    positions: list[int],
    *,
    side: str,
) -> list[dict[str, Any]]:
    signal_positions = np.flatnonzero(signal_series.fillna(False).to_numpy())
    markers: list[dict[str, Any]] = []
    for signal_position in signal_positions:
        # Coerce np.intp → int so _nearest_chart_index + min() stay int-typed
        # (mypy --strict flags the numpy scalar as SupportsDunderLT/GT).
        sp = int(signal_position)
        execution_position = min(sp + 1, len(price_series) - 1)
        chart_index = _nearest_chart_index(execution_position, positions)
        price = _safe_number(float(price_series.iloc[execution_position]))
        markers.append(
            {
                "chart_index": chart_index,
                "label": _label_for_index(price_series.index[execution_position]),
                "price": None if price is None else round(float(price), 6),
                "side": side,
                "signal_index": sp,
                "execution_index": execution_position,
            }
        )
    return markers


def _chart_payload(
    frame: pd.DataFrame,
    entries: pd.Series,
    exits: pd.Series,
    result: BacktestResult,
) -> dict[str, Any]:
    close_series = pd.to_numeric(frame["close"], errors="coerce").ffill().bfill()
    open_series = _numeric_series(frame, "open", close_series)
    high_series = _numeric_series(
        frame, "high", pd.concat([open_series, close_series], axis=1).max(axis=1)
    )
    low_series = _numeric_series(
        frame, "low", pd.concat([open_series, close_series], axis=1).min(axis=1)
    )
    volume_series = _numeric_series(frame, "volume", pd.Series(0.0, index=frame.index))
    positions = _chart_positions(len(frame))

    candles: list[dict[str, Any]] = []
    for chart_index, position in enumerate(positions):
        candles.append(
            {
                "chart_index": chart_index,
                "label": _label_for_index(frame.index[position]),
                "open": round(float(open_series.iloc[position]), 6),
                "high": round(float(high_series.iloc[position]), 6),
                "low": round(float(low_series.iloc[position]), 6),
                "close": round(float(close_series.iloc[position]), 6),
                "volume": round(float(volume_series.iloc[position]), 6),
            }
        )

    timeframe = "unknown"
    if "timeframe" in frame.columns and not frame["timeframe"].dropna().empty:
        timeframe = str(frame["timeframe"].dropna().iloc[-1])

    return {
        "timeframe": timeframe,
        "visible_default": min(DEFAULT_VISIBLE_BARS, len(candles)),
        "sampled": len(positions) != len(frame),
        "candles": candles,
        "volume": _line_values(volume_series, positions),
        "secondary": {
            "equity": _line_values(result.equity_curve, positions),
            "drawdown": _line_values(result.drawdown_curve, positions),
        },
        "markers": {
            "entries": _marker_payload(entries, close_series, positions, side="entry"),
            "exits": _marker_payload(exits, close_series, positions, side="exit"),
        },
        "meta": {
            "bars_total": len(frame),
            "bars_rendered": len(candles),
            "entry_count": int(entries.fillna(False).sum()),
            "exit_count": int(exits.fillna(False).sum()),
        },
    }


def _result_payload(result: BacktestResult) -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        _to_jsonable(
            {
                "strategy_id": result.strategy_id,
                "symbol": result.symbol,
                "start_date": result.start_date,
                "end_date": result.end_date,
                "initial_capital": result.initial_capital,
                "final_capital": result.final_capital,
                "total_return": result.total_return,
                "annual_return": result.annual_return,
                "sharpe_ratio": result.sharpe_ratio,
                "sortino_ratio": result.sortino_ratio,
                "calmar_ratio": result.calmar_ratio,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "profit_factor": result.profit_factor,
                "num_trades": result.num_trades,
                "report_markdown": generate_report(result, format="markdown"),
                "equity_curve": _series_payload(result.equity_curve),
                "drawdown_curve": _series_payload(result.drawdown_curve),
            }
        ),
    )


def _load_store(config_path: str) -> tuple[Any, DataStore]:
    # config_path originates from a web request body — confine it to the
    # packaged config tree to prevent path-traversal reads/writes.
    safe_path = resolve_config_path_safe(config_path)
    config = load_config(safe_path)
    return config, _open_station_store(config)


def _open_station_store(config: Any) -> DataStore:
    """Station reads and parquet maintenance should not lock the workspace DuckDB file."""
    return DataStore(config.data.parquet_dir, ":memory:")


MARKET_DATA_SOURCES = {"okx", "market"}
DEMO_DATA_SOURCES = {"demo"}


def _normalize_data_source(value: Any) -> str:
    if value is None:
        return "unknown"
    if pd.isna(value):
        return "unknown"

    text = str(value).strip().lower()
    if not text or text in {"nan", "none", "null"}:
        return "unknown"
    if text in MARKET_DATA_SOURCES:
        return "okx"
    if text in DEMO_DATA_SOURCES:
        return "demo"
    return text


def _frame_source_breakdown(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty:
        return {}
    if "data_source" not in frame.columns:
        return {"unknown": len(frame)}

    counts = Counter(_normalize_data_source(value) for value in frame["data_source"].tolist())
    return {key: int(value) for key, value in counts.items() if value > 0}


def _resolve_frame_data_source(frame: pd.DataFrame) -> tuple[str, dict[str, int]]:
    breakdown = _frame_source_breakdown(frame)
    categories = [key for key, value in breakdown.items() if value > 0]
    if not categories:
        return "unknown", breakdown
    if len(categories) == 1:
        return categories[0], breakdown
    return "hybrid", breakdown


def _resolve_data_mode(source_counts: dict[str, int], symbol_count: int) -> str:
    if symbol_count <= 0:
        return "demo-ready"

    active_sources = {key for key, value in source_counts.items() if int(value or 0) > 0}
    if not active_sources:
        return "source-unknown"
    if active_sources == {"okx"}:
        return "market"
    if active_sources == {"demo"}:
        return "demo-seeded"
    if active_sources == {"unknown"}:
        return "source-unknown"
    return "hybrid"


def _data_mode_context(mode: str) -> dict[str, str]:
    mapping = {
        "market": {
            "title": "Market data ready",
            "message": "Workspace is backed by tagged OKX market data.",
        },
        "demo-seeded": {
            "title": "Demo data seeded",
            "message": "Workspace currently contains only seeded demo data for front-end walkthroughs.",
        },
        "source-unknown": {
            "title": "Source labels missing",
            "message": "Local parquet data exists, but its persisted data source is not tagged yet.",
        },
        "hybrid": {
            "title": "Mixed data sources",
            "message": "Workspace contains a mix of market, demo, or unclassified parquet data.",
        },
        "demo-ready": {
            "title": "Demo-ready workspace",
            "message": "No local parquet data detected. Research and validation will fall back to synthetic demo data when needed.",
        },
    }
    return mapping.get(
        mode,
        {
            "title": "Unknown data mode",
            "message": "Workspace data mode could not be classified from persisted parquet data.",
        },
    )


def format_data_source_label(source: str) -> str:
    normalized = _normalize_data_source(source)
    if normalized == "okx":
        return "Market"
    if normalized == "demo":
        return "Demo"
    if normalized == "unknown":
        return "Unknown"
    if normalized == "hybrid":
        return "Hybrid"
    return str(source)


def _query_symbol_frame(
    store: DataStore,
    symbol: str,
    start: str | None = None,
    end: str | None = None,
) -> tuple[pd.DataFrame, str]:
    # ISS-20260723-013 (GP1 fail-silent): store.query now raises DataError on
    # storage failures (distinct from "no data" which returns an empty DF).
    # The Station overview must degrade to a demo frame on either — the page
    # must not 500 when a single symbol's parquet is corrupt. The error is
    # logged here so the failure is observable, not silently swallowed.
    try:
        frame = store.query(symbol)
    except DataError as e:
        logger.warning("Station overview query failed for %s: %s — degrading to demo", symbol, e)
        return _build_demo_frame(symbol, start=start, end=end), "demo"
    if frame.empty:
        return _build_demo_frame(symbol, start=start, end=end), "demo"

    data_source, _ = _resolve_frame_data_source(frame)

    if "datetime" in frame.columns:
        if start:
            frame = frame[frame["datetime"] >= pd.Timestamp(start, tz="UTC")]
        if end:
            frame = frame[frame["datetime"] <= pd.Timestamp(end, tz="UTC")]
        frame = frame.set_index("datetime")
    elif "timestamp" in frame.columns:
        frame = frame.copy()
        frame["datetime"] = pd.to_datetime(
            pd.to_numeric(frame["timestamp"], errors="coerce"),
            unit="ms",
            utc=True,
        )
        frame = frame.dropna(subset=["datetime"])
        if start:
            frame = frame[frame["datetime"] >= pd.Timestamp(start, tz="UTC")]
        if end:
            frame = frame[frame["datetime"] <= pd.Timestamp(end, tz="UTC")]
        frame = frame.set_index("datetime")

    if frame.empty:
        return _build_demo_frame(symbol, start=start, end=end), "demo"
    return frame, data_source


VALIDATION_METHOD_LABELS = {
    "gate": "Validation Gate",
    "cpcv": "CPCV",
    "dsr": "Deflated Sharpe Ratio",
    "wfo": "Walk-Forward Optimization",
    "pbo": "Probability of Backtest Overfitting",
}


def _validation_metric(
    label: str,
    value: Any,
    *,
    format_hint: str = "number",
    tone: str | None = None,
) -> dict[str, Any]:
    metric = {
        "label": label,
        "value": _safe_number(value),
        "format": format_hint,
    }
    if tone:
        metric["tone"] = tone
    return metric


def _validation_tone(*, decision: str | None = None, passed: bool | None = None) -> str:
    normalized = str(decision or "").lower()
    if "no-go" in normalized or normalized in {"fail", "failed"}:
        return "danger"
    if "go" in normalized or normalized in {"pass", "passed"}:
        return "accent"
    if passed is True:
        return "accent"
    if passed is False:
        return "danger"
    return "muted"


def _summary_text(value: Any, fallback: str = "N/A") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _validation_summary(payload: dict[str, Any]) -> dict[str, Any]:
    method = str(payload.get("method", "gate"))
    result = payload.get("result", {})
    signals = payload.get("signals", {})
    backtest = payload.get("backtest", {})

    summary: dict[str, Any] = {
        "method": method,
        "method_label": VALIDATION_METHOD_LABELS.get(method, method.upper()),
        "decision": "N/A",
        "outcome_label": "N/A",
        "outcome_tone": "muted",
        "reason": "No validation summary available.",
        "entries": signals.get("entries"),
        "exits": signals.get("exits"),
        "bars": signals.get("bars"),
        "primary_metric_label": "Bars",
        "primary_metric_value": signals.get("bars"),
        "primary_metric_format": "integer",
        "secondary_metrics": [
            _validation_metric("Entries", signals.get("entries"), format_hint="integer"),
            _validation_metric("Exits", signals.get("exits"), format_hint="integer"),
            _validation_metric("Bars", signals.get("bars"), format_hint="integer"),
        ],
        "highlights": [],
    }

    if method == "gate":
        checks = result.get("checks", {})
        cpcv = checks.get("cpcv", {}) if isinstance(checks, dict) else {}
        passed = cpcv.get("passed")
        decision = result.get("decision") or ("GO" if passed else "NO-GO")
        reason = result.get("reason") or (
            "Validation gate cleared all checks."
            if passed
            else "Validation gate detected a release-blocking issue."
        )
        summary.update(
            {
                "decision": decision,
                "outcome_label": decision,
                "outcome_tone": _validation_tone(decision=decision, passed=passed),
                "reason": reason,
                "primary_metric_label": "CPCV PBO",
                "primary_metric_value": cpcv.get("pbo"),
                "primary_metric_format": "number",
                "secondary_metrics": [
                    _validation_metric("Entries", signals.get("entries"), format_hint="integer"),
                    _validation_metric("Exits", signals.get("exits"), format_hint="integer"),
                    _validation_metric("Paths", cpcv.get("n_paths"), format_hint="integer"),
                    _validation_metric(
                        "OOS Efficiency", cpcv.get("oos_efficiency"), format_hint="percent"
                    ),
                ],
                "highlights": [
                    reason,
                    f"CPCV checked {safe_paths} paths."
                    if (safe_paths := cpcv.get("n_paths")) is not None
                    else "CPCV path count unavailable.",
                    f"OOS Sharpe mean {safe_sharpe:.3f}"
                    if (safe_sharpe := _safe_number(cpcv.get("oos_sharpe_mean"))) is not None
                    else "OOS Sharpe mean unavailable.",
                ],
            }
        )
        return summary

    if method == "dsr":
        passed = result.get("passed")
        decision = "PASS" if passed else "FAIL"
        reason = (
            "Observed Sharpe clears the deflated Sharpe hurdle."
            if passed
            else "Observed Sharpe does not clear the deflated Sharpe hurdle."
        )
        summary.update(
            {
                "decision": decision,
                "outcome_label": decision,
                "outcome_tone": _validation_tone(decision=decision, passed=passed),
                "reason": reason,
                "primary_metric_label": "DSR",
                "primary_metric_value": result.get("dsr"),
                "primary_metric_format": "number",
                "secondary_metrics": [
                    _validation_metric("Observed Sharpe", result.get("observed_sharpe")),
                    _validation_metric("Expected Max Sharpe", result.get("expected_max_sharpe")),
                    _validation_metric("Trials", result.get("n_trials"), format_hint="integer"),
                    _validation_metric(
                        "Backtest Return", backtest.get("total_return"), format_hint="percent"
                    ),
                ],
                "highlights": [
                    reason,
                    f"{int(backtest.get('num_trades', 0))} trades sampled in the backing backtest."
                    if backtest.get("num_trades") is not None
                    else "Trade count unavailable.",
                    f"Backtest max drawdown {drawdown:.2%}"
                    if (drawdown := _safe_number(backtest.get("max_drawdown"))) is not None
                    else "Backtest drawdown unavailable.",
                ],
            }
        )
        return summary

    if method == "pbo":
        passed = result.get("passed")
        decision = "PASS" if passed else "FAIL"
        overfit_paths = result.get("overfit_paths")
        total_paths = result.get("total_paths")
        path_share = None
        if total_paths:
            path_share = overfit_paths / total_paths
        reason = result.get("reason") or (
            "Overfitting probability remains inside the acceptable band."
            if passed
            else "Overfitting probability is elevated and needs more robust signal design."
        )
        summary.update(
            {
                "decision": decision,
                "outcome_label": decision,
                "outcome_tone": _validation_tone(decision=decision, passed=passed),
                "reason": reason,
                "primary_metric_label": "PBO",
                "primary_metric_value": result.get("pbo"),
                "primary_metric_format": "number",
                "secondary_metrics": [
                    _validation_metric("Overfit Share", path_share, format_hint="percent"),
                    _validation_metric("Overfit Paths", overfit_paths, format_hint="integer"),
                    _validation_metric("Total Paths", total_paths, format_hint="integer"),
                    _validation_metric("Rank Correlation", result.get("rank_correlation")),
                ],
                "highlights": [
                    reason,
                    f"OOS return mean {oos_return:.2%}"
                    if (oos_return := _safe_number(result.get("oos_return_mean"))) is not None
                    else "OOS return mean unavailable.",
                    f"In-sample return mean {is_return:.2%}"
                    if (is_return := _safe_number(result.get("is_return_mean"))) is not None
                    else "In-sample return mean unavailable.",
                ],
            }
        )
        return summary

    if method == "cpcv":
        passed = result.get("passed")
        decision = "PASS" if passed else "FAIL"
        signal_quality = result.get("signal_quality", {})
        reason = result.get("reason") or (
            "Cross-validated out-of-sample quality is inside the target band."
            if passed
            else "Cross-validated out-of-sample quality is not yet robust enough."
        )
        summary.update(
            {
                "decision": decision,
                "outcome_label": decision,
                "outcome_tone": _validation_tone(decision=decision, passed=passed),
                "reason": reason,
                "primary_metric_label": "OOS Sharpe Mean",
                "primary_metric_value": result.get("oos_sharpe_mean"),
                "primary_metric_format": "number",
                "secondary_metrics": [
                    _validation_metric("PBO", result.get("pbo")),
                    _validation_metric(
                        "OOS Efficiency", result.get("oos_efficiency"), format_hint="percent"
                    ),
                    _validation_metric("Paths", result.get("n_paths"), format_hint="integer"),
                    _validation_metric(
                        "Precision", signal_quality.get("precision"), format_hint="percent"
                    ),
                ],
                "highlights": [
                    reason,
                    f"Signal recall {recall:.2%}"
                    if (recall := _safe_number(signal_quality.get("recall"))) is not None
                    else "Signal recall unavailable.",
                    f"{int(signal_quality.get('n_signals', 0))} OOS signals evaluated."
                    if signal_quality.get("n_signals") is not None
                    else "Signal count unavailable.",
                ],
            }
        )
        return summary

    if method == "wfo":
        rolling = result.get("rolling", {})
        anchored = result.get("anchored", {})
        rolling_passed = rolling.get("passed")
        anchored_passed = anchored.get("passed")
        if rolling_passed == anchored_passed:
            passed = rolling_passed and anchored_passed
            decision = "PASS" if passed else "FAIL"
            tone = _validation_tone(decision=decision, passed=passed)
        else:
            passed = False
            decision = "MIXED"
            tone = "warning"
        reason = (
            "Rolling and anchored windows both clear the OOS threshold."
            if rolling_passed and anchored_passed
            else "Rolling and anchored windows diverge, so the strategy is not release-ready."
            if decision == "MIXED"
            else "Walk-forward windows do not consistently clear the OOS threshold."
        )
        summary.update(
            {
                "decision": decision,
                "outcome_label": decision,
                "outcome_tone": tone,
                "reason": reason,
                "primary_metric_label": "Rolling OOS Sharpe",
                "primary_metric_value": rolling.get("oos_sharpe_mean"),
                "primary_metric_format": "number",
                "secondary_metrics": [
                    _validation_metric(
                        "Rolling Efficiency", rolling.get("oos_efficiency"), format_hint="percent"
                    ),
                    _validation_metric("Anchored OOS Sharpe", anchored.get("oos_sharpe_mean")),
                    _validation_metric(
                        "Anchored Efficiency", anchored.get("oos_efficiency"), format_hint="percent"
                    ),
                    _validation_metric("Windows", rolling.get("n_windows"), format_hint="integer"),
                ],
                "highlights": [
                    reason,
                    f"Rolling decision {_summary_text(rolling.get('decision'))}.",
                    f"Anchored decision {_summary_text(anchored.get('decision'))}.",
                ],
            }
        )
        return summary

    return summary


@dataclass
class StationService:
    """Domain operations backing the business frontend."""

    config_path: str = DEFAULT_CONFIG_PATH
    history_store: StationHistoryStore = field(default_factory=StationHistoryStore)

    def overview(self) -> dict[str, Any]:
        # ISS-019: even though self.config_path is the constructor default (not
        # request-supplied), resolve via the safe confining variant so the web
        # layer has a single config-resolution contract — no resolve_config_path
        # (CLI/unsafe) call site remains in quantflow/web/.
        resolved_config = resolve_config_path_safe(self.config_path)
        config = load_config(resolved_config)
        store = _open_station_store(config)
        data_dir = Path(config.data.parquet_dir)
        source_counts: Counter[str] = Counter()
        try:
            symbols: list[dict[str, Any]] = []
            for symbol_name in store.list_symbols():
                symbol = symbol_name.replace("_", "/")
                # ISS-20260723-013/014 (GP1 fail-silent): store.query/get_date_range
                # now raise DataError on storage failures. A single corrupt
                # symbol must not 500 the whole overview — skip it (logged) so
                # the rest of the dashboard still renders.
                try:
                    frame = store.query(symbol, columns=["timestamp", "data_source"])
                    data_source, source_breakdown = _resolve_frame_data_source(frame)
                    source_counts[data_source] += 1
                    date_range = store.get_date_range(symbol)
                    if date_range is None and not frame.empty and "timestamp" in frame.columns:
                        timestamps = pd.to_numeric(frame["timestamp"], errors="coerce").dropna()
                        if not timestamps.empty:
                            date_range = (int(timestamps.min()), int(timestamps.max()))
                except DataError as e:
                    logger.warning("Station overview skipping symbol %s: %s", symbol, e)
                    continue
                symbols.append(
                    {
                        "symbol": symbol,
                        "files": len(list((data_dir / symbol_name).glob("*/*.parquet"))),
                        "date_range": date_range,
                        "data_source": data_source,
                        "source_breakdown": source_breakdown,
                    }
                )
        finally:
            store.close()

        strategy_items = list_strategy_summaries()
        data_mode = _resolve_data_mode(dict(source_counts), len(symbols))
        source_context = _data_mode_context(data_mode)
        return {
            "version": __version__,
            "phase": "3 (OKX Live + AI Factors)",
            "config_path": str(resolved_config),
            "docker_available": _docker_available(),
            "monitoring": {
                "prometheus_port": config.monitoring.prometheus_port,
                "grafana_port": config.monitoring.grafana_port,
                "grafana_url": f"http://127.0.0.1:{config.monitoring.grafana_port}",
                "prometheus_url": f"http://127.0.0.1:{config.monitoring.prometheus_port}",
            },
            "data": {
                "parquet_dir": config.data.parquet_dir,
                "duckdb_path": config.data.duckdb_path,
                "mode": data_mode,
                "symbol_count": len(symbols),
                "source_counts": {key: int(value) for key, value in source_counts.items()},
                "source_context": source_context,
                "symbols": symbols,
            },
            "risk": {
                "max_drawdown": config.risk.max_drawdown,
                "daily_loss_limit": config.risk.daily_loss_limit,
                "weekly_loss_limit": config.risk.weekly_loss_limit,
                "kill_switch_enabled": config.risk.kill_switch_enabled,
            },
            "execution": {
                "mode": config.execution.mode,
                "slippage": config.execution.slippage,
                "maker_fee": config.execution.maker_fee,
                "taker_fee": config.execution.taker_fee,
            },
            "strategies": {
                "count": len(strategy_items),
                "items": strategy_items,
            },
        }

    def strategies(self) -> list[dict[str, Any]]:
        return list_strategy_summaries()

    def data_snapshot(self) -> dict[str, Any]:
        overview = self.overview()
        data = overview.get("data", {})
        parquet_dir = Path(str(data.get("parquet_dir", "")))
        duckdb_path = Path(str(data.get("duckdb_path", "")))
        symbol_items = data.get("symbols", [])

        symbols: list[dict[str, Any]] = []
        files_total = 0
        earliest_ts: int | None = None
        latest_ts: int | None = None
        latest_symbol: dict[str, Any] | None = None
        widest_symbol: dict[str, Any] | None = None
        source_counts: Counter[str] = Counter()
        now = datetime.now(UTC)

        for raw_item in symbol_items:
            item = dict(raw_item)
            files = int(item.get("files", 0) or 0)
            files_total += files
            date_range = item.get("date_range") or []
            range_start = date_range[0] if len(date_range) == 2 else None
            range_end = date_range[1] if len(date_range) == 2 else None
            raw_breakdown = item.get("source_breakdown") or {}
            source_breakdown: dict[str, int] = {}
            if isinstance(raw_breakdown, dict):
                for key, value in raw_breakdown.items():
                    try:
                        count = int(value or 0)
                    except (TypeError, ValueError):
                        continue
                    if count <= 0:
                        continue
                    normalized_key = _normalize_data_source(key)
                    source_breakdown[normalized_key] = (
                        source_breakdown.get(normalized_key, 0) + count
                    )

            symbol_data_source = _normalize_data_source(item.get("data_source"))
            active_breakdown_sources = [
                key for key, value in source_breakdown.items() if int(value) > 0
            ]
            if active_breakdown_sources:
                symbol_data_source = (
                    active_breakdown_sources[0] if len(active_breakdown_sources) == 1 else "hybrid"
                )
            if symbol_data_source not in {"okx", "demo", "unknown", "hybrid"}:
                symbol_data_source = "unknown"
            source_counts[symbol_data_source] += 1

            if range_start is not None:
                earliest_ts = range_start if earliest_ts is None else min(earliest_ts, range_start)
            if range_end is not None:
                latest_ts = range_end if latest_ts is None else max(latest_ts, range_end)

            coverage_days: int | None = None
            last_bar_age_days: int | None = None
            if range_start is not None and range_end is not None:
                coverage_days = max(1, int((int(range_end) - int(range_start)) / 86_400_000) + 1)
                range_end_dt = datetime.fromtimestamp(int(range_end) / 1000, tz=UTC)
                last_bar_age_days = max(0, int((now - range_end_dt).total_seconds() // 86_400))

            symbol_entry = {
                "symbol": item.get("symbol"),
                "files": files,
                "range_start": _timestamp_to_iso(range_start),
                "range_end": _timestamp_to_iso(range_end),
                "coverage_days": coverage_days,
                "last_bar_age_days": last_bar_age_days,
                "data_source": symbol_data_source,
                "source_breakdown": source_breakdown,
            }
            symbols.append(symbol_entry)

            if latest_symbol is None or (
                range_end is not None
                and (
                    latest_symbol.get("_range_end") is None
                    or int(range_end) > int(latest_symbol["_range_end"])
                )
            ):
                latest_symbol = {**symbol_entry, "_range_end": range_end}

            if widest_symbol is None or files > int(widest_symbol.get("files", 0) or 0):
                widest_symbol = symbol_entry

        mode = str(data.get("mode") or _resolve_data_mode(dict(source_counts), len(symbols)))
        raw_source_context = data.get("source_context")
        source_context = (
            raw_source_context if isinstance(raw_source_context, dict) else _data_mode_context(mode)
        )
        summary_source_counts = {key: int(value) for key, value in source_counts.items()}
        highlights: list[str] = []
        if not symbols:
            highlights.append(
                str(
                    source_context.get("message")
                    or "No local parquet data detected. Research and validation will use synthetic fallback data."
                )
            )
            highlights.append(
                "Prepare historical market data or seed demo data before continuing with the research, validation, and execution workflow."
            )
        else:
            highlights.append(
                str(
                    source_context.get("message")
                    or "Workspace data mode has been classified from persisted parquet data."
                )
            )
            highlights.append(
                f"当前已覆盖 {len(symbols)} 个交易对，共 {files_total} 个月度 parquet 分区文件。"
            )
            if latest_symbol and latest_symbol.get("range_end"):
                range_end = latest_symbol.get("range_end")
                range_end_str = range_end if isinstance(range_end, str) else ""
                highlights.append(
                    f"最新数据来自 {latest_symbol.get('symbol')}，最近 bar 时间为 {range_end_str[:10]}。"
                )
            if mode == "market":
                highlights.append(
                    "当前工作区已具备带来源标注的 market 数据，可直接支撑研究、验证和执行草稿。"
                )
            elif mode == "demo-seeded":
                highlights.append(
                    "当前本地 parquet 仅包含演示数据，适合业务前端 walkthrough，但不应作为真实市场证据。"
                )
            elif mode == "source-unknown":
                highlights.append(
                    "当前存在本地 parquet，但历史数据来源未标注，建议补写 data_source 后再将结果作为发布证据。"
                )
            elif mode == "hybrid":
                highlights.append(
                    "当前工作区混合了 market、demo 或未标注数据源，研究与验证结论需要谨慎解读。"
                )

        return {
            "captured_at": now.isoformat(),
            "mode": mode,
            "source_context": source_context,
            "summary": {
                "symbol_count": len(symbols),
                "files_total": files_total,
                "earliest_bar_at": _timestamp_to_iso(earliest_ts),
                "latest_bar_at": _timestamp_to_iso(latest_ts),
                "parquet_root_exists": parquet_dir.exists(),
                "duckdb_exists": duckdb_path.exists(),
                "source_counts": summary_source_counts,
                "market_symbol_count": int(summary_source_counts.get("okx", 0)),
                "demo_symbol_count": int(summary_source_counts.get("demo", 0)),
                "unknown_symbol_count": int(summary_source_counts.get("unknown", 0)),
                "hybrid_symbol_count": int(summary_source_counts.get("hybrid", 0)),
            },
            "storage": {
                "parquet_dir": str(parquet_dir),
                "duckdb_path": str(duckdb_path),
                "config_path": overview.get("config_path"),
                "execution_mode": overview.get("execution", {}).get("mode", "paper"),
                "source_mix": summary_source_counts,
            },
            "leaders": {
                "latest_symbol": {
                    key: value
                    for key, value in (latest_symbol or {}).items()
                    if not key.startswith("_")
                },
                "widest_symbol": widest_symbol,
            },
            "highlights": highlights[:4],
            "symbols": symbols,
        }

    async def download_data(self, request: DataDownloadRequest) -> dict[str, Any]:
        from quantflow.data.cleaner import clean_ohlcv
        from quantflow.data.fetcher import DataFetcher

        if request.start and request.end and request.start > request.end:
            raise ValueError("start must be earlier than or equal to end")

        config = load_config(resolve_config_path_safe(request.config_path))
        fetcher = DataFetcher(config.data)
        store = _open_station_store(config)

        try:
            await fetcher.connect()
            raw_frame = await fetcher.fetch_ohlcv(
                request.symbol,
                request.timeframe,
                request.start,
                request.end,
            )
            if raw_frame.empty:
                raise ValueError(
                    f"No data fetched for {request.symbol}. Check symbol and date range."
                )

            cleaned_frame = clean_ohlcv(raw_frame)
            if cleaned_frame.empty:
                raise ValueError(
                    f"Fetched data for {request.symbol}, but nothing remained after cleaning."
                )
            cleaned_frame = cleaned_frame.copy()
            cleaned_frame["data_source"] = "okx"
            store.save(cleaned_frame, request.symbol)
            date_range = store.get_date_range(request.symbol)
        finally:
            await fetcher.disconnect()
            store.close()

        return {
            "symbol": request.symbol,
            "timeframe": request.timeframe,
            "start": request.start,
            "end": request.end,
            "rows_saved": len(cleaned_frame),
            "raw_rows": len(raw_frame),
            "data_source": "okx",
            "parquet_dir": config.data.parquet_dir,
            "duckdb_path": config.data.duckdb_path,
            "date_range": {
                "start": _timestamp_to_iso(date_range[0]) if date_range else None,
                "end": _timestamp_to_iso(date_range[1]) if date_range else None,
            },
            "message": f"Saved {len(cleaned_frame)} bars for {request.symbol}.",
        }

    def tag_data_source(self, request: DataSourceTagRequest) -> dict[str, Any]:
        normalized_source = _normalize_data_source(request.data_source)
        if normalized_source not in {"okx", "demo"}:
            raise ValueError("data_source must be one of: okx, market, demo")

        config = load_config(resolve_config_path_safe(request.config_path))
        # SECURITY: validate symbol before turning it into a filesystem path
        # (REV-008 sibling, G4 pattern). The downstream store.query() /
        # store.get_date_range() calls validate too, but this direct Path
        # construction (line below) runs FIRST and would otherwise traverse
        # the parquet dir on a crafted request.symbol.
        symbol_name = validate_symbol(request.symbol)
        symbol_dir = Path(config.data.parquet_dir) / symbol_name
        parquet_files = sorted(symbol_dir.glob("*/*.parquet"))
        if not parquet_files:
            raise ValueError(f"No local parquet files found for {request.symbol}.")

        rows_updated = 0
        files_updated = 0
        for parquet_file in parquet_files:
            frame = pd.read_parquet(parquet_file)
            updated = frame.copy()
            updated["data_source"] = normalized_source
            updated.to_parquet(parquet_file, index=False, compression="zstd")
            rows_updated += len(updated)
            files_updated += 1

        store = _open_station_store(config)
        try:
            date_range = store.get_date_range(request.symbol)
            tagged_frame = store.query(request.symbol, columns=["timestamp", "data_source"])
            resolved_source, source_breakdown = _resolve_frame_data_source(tagged_frame)
        finally:
            store.close()

        return {
            "symbol": request.symbol,
            "data_source": resolved_source,
            "files_updated": files_updated,
            "rows_updated": rows_updated,
            "parquet_dir": config.data.parquet_dir,
            "duckdb_path": config.data.duckdb_path,
            "source_breakdown": source_breakdown,
            "date_range": {
                "start": _timestamp_to_iso(date_range[0]) if date_range else None,
                "end": _timestamp_to_iso(date_range[1]) if date_range else None,
            },
            "message": f"Tagged {request.symbol} parquet data as {format_data_source_label(resolved_source)}.",
        }

    def seed_demo_data(self, request: DataDownloadRequest) -> dict[str, Any]:
        if request.start and request.end and request.start > request.end:
            raise ValueError("start must be earlier than or equal to end")

        config = load_config(resolve_config_path_safe(request.config_path))
        store = _open_station_store(config)
        try:
            demo_frame = _build_demo_frame(
                request.symbol,
                start=request.start,
                end=request.end,
                bars=720,
                timeframe=request.timeframe,
            )
            demo_frame = demo_frame.copy()
            demo_frame["data_source"] = "demo"
            store.save(demo_frame, request.symbol)
            date_range = store.get_date_range(request.symbol)
        finally:
            store.close()

        return {
            "symbol": request.symbol,
            "timeframe": request.timeframe,
            "start": request.start,
            "end": request.end,
            "rows_saved": len(demo_frame),
            "raw_rows": len(demo_frame),
            "data_source": "demo",
            "parquet_dir": config.data.parquet_dir,
            "duckdb_path": config.data.duckdb_path,
            "date_range": {
                "start": _timestamp_to_iso(date_range[0]) if date_range else None,
                "end": _timestamp_to_iso(date_range[1]) if date_range else None,
            },
            "message": f"Seeded {len(demo_frame)} demo bars for {request.symbol}.",
        }

    def research_history(self, limit: int = 12) -> list[dict[str, Any]]:
        return self.history_store.list_research_runs(limit=limit)

    def validation_history(self, limit: int = 12) -> list[dict[str, Any]]:
        items = self.history_store.list_validation_runs(limit=limit)
        normalized: list[dict[str, Any]] = []
        for item in items:
            payload = item.get("payload")
            summary = item.get("summary")
            if isinstance(payload, dict):
                if (
                    not isinstance(summary, dict)
                    or not summary.get("method_label")
                    or not summary.get("outcome_label")
                ):
                    item = dict(item)
                    item["summary"] = _validation_summary(payload)
            normalized.append(item)
        return normalized

    def workbench_state(self) -> dict[str, Any] | None:
        return self.history_store.load_workbench_state()

    def save_workbench_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Workbench state payload must be a JSON object.")
        # Bound payload size to prevent unbounded on-disk growth / abuse.
        try:
            encoded = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Workbench state payload is not JSON-serializable.") from exc
        if len(encoded) > _MAX_WORKBENCH_STATE_BYTES:
            raise ValueError(f"Workbench state payload exceeds {_MAX_WORKBENCH_STATE_BYTES} bytes.")
        return self.history_store.save_workbench_state(payload)

    def monitoring_snapshot(
        self,
        *,
        session_snapshot: dict[str, Any] | None = None,
        session_history: list[dict[str, Any]] | None = None,
        session_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        overview = self.overview()
        research_items = self.research_history(limit=6)
        validation_items = self.validation_history(limit=6)
        session_history = session_history or []
        session_events = session_events or []
        live_session = session_snapshot if isinstance(session_snapshot, dict) else {}
        latest_session = (
            live_session
            if live_session.get("session_id")
            else (session_history[0] if session_history else live_session)
        )

        metrics_registry = metrics_registry_snapshot()
        registry_values = (
            metrics_registry.get("values", {})
            if isinstance(metrics_registry, dict)
            and isinstance(metrics_registry.get("values", {}), dict)
            else {}
        )
        internal_metrics = {
            "available": bool(metrics_registry.get("available")),
            "portfolio_value": registry_values.get("portfolio_value"),
            "portfolio_cash": registry_values.get("portfolio_cash"),
            "portfolio_drawdown": registry_values.get("portfolio_drawdown"),
            "positions_count": registry_values.get("positions_count"),
            "orders_total": registry_values.get("orders_total", 0),
            "orders_filled_total": registry_values.get("orders_filled_total", 0),
            "signals_generated_total": registry_values.get("signals_generated_total", 0),
            "risk_events_total": registry_values.get("risk_events_total", 0),
            "order_latency_count": registry_values.get("order_latency_count", 0),
            "order_latency_avg": _latency_average(
                registry_values.get("order_latency_sum"),
                registry_values.get("order_latency_count"),
            ),
            "bar_latency_count": registry_values.get("bar_latency_count", 0),
            "bar_latency_avg": _latency_average(
                registry_values.get("bar_latency_sum"),
                registry_values.get("bar_latency_count"),
            ),
            "signal_latency_count": registry_values.get("signal_latency_count", 0),
            "signal_latency_avg": _latency_average(
                registry_values.get("signal_latency_sum"),
                registry_values.get("signal_latency_count"),
            ),
        }

        monitoring_cfg = overview.get("monitoring", {})
        services: list[dict[str, Any]] = []
        reachable_total = 0
        for service_id, label, note in (
            ("prometheus", "Prometheus", "Metrics scrape endpoint"),
            ("grafana", "Grafana", "Dashboards and operator panels"),
        ):
            raw_port = monitoring_cfg.get(f"{service_id}_port")
            try:
                port = int(raw_port) if raw_port is not None else None
            except (TypeError, ValueError):
                port = None
            url = monitoring_cfg.get(f"{service_id}_url") or (
                f"http://127.0.0.1:{port}" if port else None
            )
            reachable = port is not None and _port_reachable("127.0.0.1", port)
            if reachable:
                reachable_total += 1
            service_payload = {
                "service_id": service_id,
                "label": label,
                "port": port,
                "url": url,
                "reachable": reachable,
                "status_kind": "reachable" if reachable else "external_unavailable",
                "status_label": "Reachable" if reachable else "Unavailable",
                "tone": "accent" if reachable else "warning",
                "note": note,
                "status_hint": (
                    "Operator endpoint is reachable from this workstation."
                    if reachable
                    else "Configured endpoint is currently unreachable from this workstation."
                ),
            }
            if not port:
                service_payload.update(
                    {
                        "status_kind": "idle",
                        "status_label": "Idle",
                        "tone": "muted",
                        "status_hint": "No operator endpoint has been configured yet.",
                    }
                )

            if service_id == "prometheus":
                server_state = metrics_server_status(port)
                attempted = bool(server_state.get("attempted"))
                started_in_process = bool(server_state.get("started"))
                last_error = server_state.get("last_error")
                registry_available = bool(internal_metrics["available"])

                if reachable:
                    status_kind = "reachable"
                    status_label = "Reachable"
                    tone = "accent"
                    status_hint = "Prometheus exporter is reachable and ready for scrape checks."
                elif attempted and started_in_process:
                    status_kind = "external_unavailable"
                    status_label = "In Process"
                    tone = "warning"
                    status_hint = "Exporter started in this process, but the HTTP endpoint is still unreachable."
                elif attempted and last_error:
                    status_kind = "attempt_failed"
                    status_label = "Attempt Failed"
                    tone = "danger"
                    status_hint = "Exporter startup failed inside the QuantFlow process."
                elif registry_available:
                    status_kind = "registry_only"
                    status_label = "Registry Only"
                    tone = "warning"
                    status_hint = "In-process metrics are available, but no reachable scrape endpoint is exposed."
                else:
                    status_kind = "idle"
                    status_label = "Idle"
                    tone = "muted"
                    status_hint = "No in-process metrics activity has been recorded yet."

                service_payload.update(
                    {
                        "status_kind": status_kind,
                        "status_label": status_label,
                        "tone": tone,
                        "status_hint": status_hint,
                        "attempted": attempted,
                        "started_in_process": started_in_process,
                        "registry_available": registry_available,
                        "last_error": last_error,
                    }
                )

            services.append(service_payload)

        prometheus_service = next(
            (service for service in services if service.get("service_id") == "prometheus"),
            None,
        )

        validation_outcomes: Counter[str] = Counter()
        validation_no_go = 0
        validation_go = 0
        for item in validation_items:
            summary = item.get("summary", {})
            decision = str(summary.get("outcome_label") or summary.get("decision") or "").strip()
            normalized_decision = decision.lower()
            if decision:
                validation_outcomes[decision] += 1
            if "no-go" in normalized_decision or normalized_decision in {"fail", "failed"}:
                validation_no_go += 1
            elif "go" in normalized_decision or normalized_decision in {"pass", "passed"}:
                validation_go += 1

        event_levels = Counter(str(item.get("level", "info")).lower() for item in session_events)
        event_types = Counter(
            str(item.get("event_type", "unknown")).lower() for item in session_events
        )
        warning_events = event_levels.get("warning", 0)
        error_events = event_levels.get("error", 0) + event_levels.get("critical", 0)

        health_tone = "accent"
        health_signals: list[str] = []
        active_session = bool(live_session.get("running"))
        if active_session:
            health_signals.append("Trading session is running.")
        else:
            health_signals.append("No active trading session.")

        data_mode = str(overview.get("data", {}).get("mode", "unknown"))
        raw_data_context = overview.get("data", {}).get("source_context")
        data_context = (
            raw_data_context
            if isinstance(raw_data_context, dict)
            else _data_mode_context(data_mode)
        )
        if data_mode != "market":
            health_tone = "warning"
        health_signals.append(
            str(
                data_context.get("message")
                or "Workspace data mode requires attention before enabling release workflows."
            )
        )

        if validation_no_go:
            if health_tone != "danger":
                health_tone = "warning"
            health_signals.append(f"{validation_no_go} recent validation runs ended in NO-GO.")

        if prometheus_service:
            prometheus_kind = str(prometheus_service.get("status_kind", "idle"))
            if prometheus_kind == "attempt_failed":
                health_tone = "danger"
                health_signals.append(
                    "Prometheus exporter failed to start inside the QuantFlow process."
                )
            elif prometheus_kind == "external_unavailable" and prometheus_service.get(
                "started_in_process"
            ):
                if health_tone == "accent":
                    health_tone = "warning"
                health_signals.append(
                    "Prometheus exporter is running in process, but its endpoint is unreachable."
                )
            elif prometheus_kind == "registry_only":
                if health_tone == "accent":
                    health_tone = "warning"
                health_signals.append(
                    "In-process metrics are available, but the Prometheus scrape endpoint is not active."
                )

        if warning_events:
            if health_tone == "accent":
                health_tone = "warning"
            health_signals.append(f"{warning_events} recent session warnings detected.")

        if error_events:
            health_tone = "danger"
            health_signals.append(f"{error_events} recent session errors detected.")

        if services and reachable_total == 0:
            if health_tone == "accent":
                health_tone = "warning"
            health_signals.append("Monitoring endpoints are not reachable from this workstation.")

        if not overview.get("docker_available", False):
            if health_tone == "accent":
                health_tone = "warning"
            health_signals.append("Docker runtime unavailable on this host.")

        health_label_map = {
            "accent": "Healthy",
            "warning": "Attention",
            "danger": "Incident",
            "muted": "Idle",
        }
        summary_text = {
            "accent": "Core services and recent platform activity look healthy.",
            "warning": "Platform is usable, but several operator checks need attention.",
            "danger": "Active alerts need investigation before enabling live workflows.",
            "muted": "No recent platform activity available yet.",
        }[health_tone]

        latest_research = research_items[0] if research_items else None
        latest_validation = validation_items[0] if validation_items else None

        alerts: list[dict[str, Any]] = []
        for event in session_events:
            level = str(event.get("level", "info")).lower()
            event_type = str(event.get("event_type", "")).lower()
            if level not in {"warning", "error", "critical"} and event_type != "risk":
                continue
            alerts.append(
                {
                    "source": "session",
                    "title": str(event.get("title") or "Session alert"),
                    "message": str(event.get("message") or "Session event requires attention."),
                    "created_at": event.get("created_at"),
                    "tone": "danger" if level in {"error", "critical"} else "warning",
                }
            )

        if latest_validation:
            validation_summary = latest_validation.get("summary", {})
            validation_decision = str(
                validation_summary.get("outcome_label") or validation_summary.get("decision") or ""
            ).lower()
            if "no-go" in validation_decision or validation_decision in {"fail", "failed"}:
                alerts.append(
                    {
                        "source": "validation",
                        "title": str(
                            validation_summary.get("method_label")
                            or validation_summary.get("method")
                            or "Validation"
                        ),
                        "message": str(
                            validation_summary.get("reason")
                            or "Validation gate returned a blocking outcome."
                        ),
                        "created_at": latest_validation.get("created_at"),
                        "tone": "warning",
                    }
                )

        if data_mode != "market":
            alerts.append(
                {
                    "source": "data",
                    "title": str(data_context.get("title") or "Data mode attention"),
                    "message": str(
                        data_context.get("message")
                        or "Workspace data mode requires attention before enabling release workflows."
                    ),
                    "created_at": datetime.now(UTC).isoformat(),
                    "tone": "warning",
                }
            )

        if not overview.get("docker_available", False):
            alerts.append(
                {
                    "source": "platform",
                    "title": "Docker unavailable",
                    "message": "Containerized monitoring and deployment flows are currently unavailable on this host.",
                    "created_at": datetime.now(UTC).isoformat(),
                    "tone": "warning",
                }
            )

        if prometheus_service:
            prometheus_kind = str(prometheus_service.get("status_kind", "idle"))
            if prometheus_kind == "attempt_failed":
                alerts.insert(
                    0,
                    {
                        "source": "monitoring",
                        "title": "Prometheus exporter failed",
                        "message": str(
                            prometheus_service.get("last_error")
                            or "Prometheus exporter startup failed in the QuantFlow process."
                        ),
                        "created_at": datetime.now(UTC).isoformat(),
                        "tone": "danger",
                    },
                )
            elif prometheus_kind in {"registry_only", "external_unavailable"}:
                alerts.insert(
                    0,
                    {
                        "source": "monitoring",
                        "title": "Prometheus exporter attention",
                        "message": str(
                            prometheus_service.get("status_hint")
                            or "Prometheus exporter requires operator attention."
                        ),
                        "created_at": datetime.now(UTC).isoformat(),
                        "tone": "warning",
                    },
                )

        return {
            "captured_at": datetime.now(UTC).isoformat(),
            "health": {
                "overall_label": health_label_map[health_tone],
                "overall_tone": health_tone,
                "summary": summary_text,
                "signals": health_signals[:6],
            },
            "metrics": {
                "services_up": reachable_total,
                "services_total": len(services),
                "validation_no_go": validation_no_go,
                "validation_go": validation_go,
                "warning_events": warning_events,
                "error_events": error_events,
                "research_runs": len(research_items),
                "validation_runs": len(validation_items),
                "session_runs": len(session_history),
                "session_events": len(session_events),
            },
            "platform": {
                "version": overview.get("version"),
                "phase": overview.get("phase"),
                "config_path": overview.get("config_path"),
                "docker_available": overview.get("docker_available", False),
                "data_mode": data_mode,
                "symbol_count": overview.get("data", {}).get("symbol_count", 0),
                "source_counts": overview.get("data", {}).get("source_counts", {}),
                "source_context": data_context,
                "execution_mode": overview.get("execution", {}).get("mode", "paper"),
                "kill_switch_enabled": overview.get("risk", {}).get("kill_switch_enabled", False),
            },
            "runtime": {
                "active_session": active_session,
                "session_id": latest_session.get("session_id") if latest_session else None,
                "open_positions": latest_session.get("health", {}).get("open_positions", 0)
                if latest_session
                else 0,
                "pending_orders": latest_session.get("health", {}).get("pending_orders", 0)
                if latest_session
                else 0,
                "status_label": latest_session.get("dashboard", {}).get("status_label", "Stopped")
                if latest_session
                else "Stopped",
                "status_tone": latest_session.get("dashboard", {}).get("status_tone", "muted")
                if latest_session
                else "muted",
            },
            "services": services,
            "activity": {
                "event_levels": dict(event_levels),
                "event_types": dict(event_types),
                "validation_outcomes": dict(validation_outcomes),
            },
            "internal_metrics": internal_metrics,
            "alerts": alerts[:6],
            "latest": {
                "research": latest_research,
                "validation": latest_validation,
                "session": latest_session,
            },
        }

    def execution_snapshot(
        self,
        *,
        session_snapshot: dict[str, Any] | None = None,
        session_history: list[dict[str, Any]] | None = None,
        session_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        overview = self.overview()
        session_history = session_history or []
        session_events = session_events or []
        live_session = session_snapshot if isinstance(session_snapshot, dict) else {}
        latest_session = (
            live_session
            if live_session.get("session_id")
            else (session_history[0] if session_history else live_session)
        )

        dashboard = latest_session.get("dashboard", {}) if latest_session else {}
        request = latest_session.get("request", {}) if latest_session else {}
        portfolio = latest_session.get("portfolio", {}) if latest_session else {}
        health = latest_session.get("health", {}) if latest_session else {}
        kill_switch = latest_session.get("kill_switch", {}) if latest_session else {}
        telemetry = latest_session.get("telemetry", {}) if latest_session else {}
        positions = latest_session.get("positions", []) if latest_session else []
        open_orders = latest_session.get("open_orders", []) if latest_session else []

        position_count = len(positions)
        order_count = len(open_orders)

        def _finite_sum(items: list[dict[str, Any]], key: str) -> float:
            total = 0.0
            for item in items:
                value = _safe_number(item.get(key, 0.0))
                if value is None:
                    continue
                try:
                    total += float(value)
                except (TypeError, ValueError):
                    continue
            return total if math.isfinite(total) else 0.0

        gross_notional = round(_finite_sum(positions, "market_value"), 2)
        pending_notional = round(_finite_sum(open_orders, "notional"), 2)
        unrealized_pnl = round(_finite_sum(positions, "unrealized_pnl"), 2)

        event_types = Counter(
            str(item.get("event_type", "unknown")).lower() for item in session_events
        )
        event_levels = Counter(str(item.get("level", "info")).lower() for item in session_events)
        execution_events = [
            item
            for item in session_events
            if str(item.get("event_type", "")).lower()
            in {"order", "fill", "risk", "signal", "kill_switch"}
        ]

        status_label = dashboard.get("status_label", "Stopped")
        status_tone = dashboard.get("status_tone", "muted")
        execution_mode = request.get("mode", overview.get("execution", {}).get("mode", "paper"))
        symbol = request.get("symbol", dashboard.get("symbol", "N/A"))
        timeframe = request.get("timeframe", dashboard.get("timeframe", "N/A"))
        strategies = request.get("strategies", []) or []
        strategy_text = ", ".join(strategies)
        telemetry_labels = (
            telemetry.get("labels", []) if isinstance(telemetry.get("labels", []), list) else []
        )

        def _last_value(items: Any, fallback: Any) -> Any:
            if isinstance(items, list) and items:
                return items[-1]
            return fallback

        fallback_label = str(
            latest_session.get("updated_at")
            or latest_session.get("started_at")
            or datetime.now(UTC).isoformat()
        )

        def _telemetry_series(name: str, fallback: Any) -> list[Any]:
            values = telemetry.get(name, [])
            if isinstance(values, list) and values:
                return [_to_jsonable(item) for item in values]
            if telemetry_labels:
                return []
            return [_to_jsonable(fallback)]

        if kill_switch.get("active"):
            health_label = "Kill Switch Active"
            health_tone = "danger"
            health_summary = "执行层已触发熔断，需要人工确认后再恢复。"
        elif live_session.get("running"):
            health_label = "Execution Online"
            health_tone = "accent"
            health_summary = "执行引擎在线，当前订单与持仓状态可由前台直接观察。"
        else:
            health_label = "Execution Idle"
            health_tone = "muted"
            health_summary = "当前没有活跃执行会话，面板展示最近一次执行状态。"

        if latest_session.get("last_error"):
            health_label = "Execution Degraded"
            health_tone = "warning"
            health_summary = str(latest_session.get("last_error"))

        control_note = (
            "熔断已激活，请先确认风险状态。"
            if kill_switch.get("active")
            else (
                "执行回路在线，可直接从终端观察仓位、挂单与事件流。"
                if live_session.get("running")
                else (
                    "最近一次执行快照已加载，可直接配置并启动新会话。"
                    if latest_session.get("session_id")
                    else "当前没有活跃执行会话，可从这里直接拉起终端。"
                )
            )
        )
        control_tone = (
            "danger"
            if kill_switch.get("active")
            else "warning"
            if latest_session.get("last_error")
            else "accent"
            if live_session.get("running")
            else "muted"
        )
        chart_labels = telemetry_labels or [fallback_label]
        equity_series = _telemetry_series(
            "equity",
            portfolio.get("equity", portfolio.get("total_value", 0.0)),
        )
        cash_series = _telemetry_series("cash", portfolio.get("cash", 0.0))
        market_value_series = _telemetry_series(
            "market_value",
            portfolio.get("market_value", gross_notional),
        )
        drawdown_series = _telemetry_series(
            "drawdown",
            portfolio.get("drawdown", 0.0),
        )
        open_positions_series = _telemetry_series(
            "open_positions",
            health.get("open_positions", position_count),
        )
        pending_orders_series = _telemetry_series(
            "pending_orders",
            health.get("pending_orders", order_count),
        )
        point_count = len(chart_labels)
        gross_exposure_value = dashboard.get("gross_exposure_value", gross_notional)
        net_exposure_value = dashboard.get(
            "net_exposure_value",
            portfolio.get("market_value", gross_notional),
        )
        data_payload = (
            overview.get("data", {}) if isinstance(overview.get("data", {}), dict) else {}
        )
        data_mode = str(data_payload.get("mode", "unknown"))
        raw_source_context = data_payload.get("source_context")
        source_context = (
            raw_source_context
            if isinstance(raw_source_context, dict)
            else _data_mode_context(data_mode)
        )
        symbol_snapshot = next(
            (
                item
                for item in data_payload.get("symbols", [])
                if isinstance(item, dict) and str(item.get("symbol") or "") == str(symbol)
            ),
            {},
        )
        symbol_data_source = _normalize_data_source(symbol_snapshot.get("data_source"))
        if symbol_data_source == "unknown":
            if data_mode == "market":
                symbol_data_source = "okx"
            elif data_mode in {"demo-seeded", "demo-ready"}:
                symbol_data_source = "demo"
            elif data_mode == "hybrid":
                symbol_data_source = "hybrid"

        research_items = self.research_history(limit=6)
        validation_items = self.validation_history(limit=6)

        def _artifact_request(item: dict[str, Any]) -> dict[str, Any]:
            request_payload = item.get("request")
            if isinstance(request_payload, dict):
                return request_payload
            payload = item.get("payload")
            if isinstance(payload, dict):
                nested = payload.get("request")
                if isinstance(nested, dict):
                    return nested
            return {}

        def _pick_best_artifact(items: list[dict[str, Any]]) -> dict[str, Any] | None:
            best_item: dict[str, Any] | None = None
            best_score = -1
            for item in items:
                request_payload = _artifact_request(item)
                score = 0
                request_symbol = request_payload.get("symbol")
                if symbol and request_symbol and str(request_symbol) == str(symbol):
                    score += 2
                request_strategy = request_payload.get("strategy")
                if not request_strategy:
                    request_strategies = request_payload.get("strategies")
                    if isinstance(request_strategies, list) and request_strategies:
                        request_strategy = request_strategies[0]
                if request_strategy and request_strategy in strategies:
                    score += 3
                if score > best_score:
                    best_score = score
                    best_item = item
            if best_score > 0:
                return best_item
            return items[0] if items else None

        matched_research = _pick_best_artifact(research_items)
        matched_validation = _pick_best_artifact(validation_items)
        validation_summary = (
            matched_validation.get("summary", {}) if isinstance(matched_validation, dict) else {}
        )
        if not isinstance(validation_summary, dict):
            validation_summary = {}
        validation_label = (
            str(
                validation_summary.get("outcome_label") or validation_summary.get("decision") or ""
            ).strip()
            or None
        )
        validation_tone = str(validation_summary.get("outcome_tone") or "muted")
        validation_reason = str(validation_summary.get("reason") or "").strip() or None
        validation_method = (
            str(
                validation_summary.get("method_label") or validation_summary.get("method") or ""
            ).strip()
            or None
        )
        validation_data_source = None
        if isinstance(matched_validation, dict):
            validation_data_source = matched_validation.get("data_source")
            if validation_data_source is None:
                payload = matched_validation.get("payload")
                if isinstance(payload, dict):
                    validation_data_source = payload.get("data_source")

        execution_context = {
            "source_type": "runtime" if latest_session.get("session_id") else "manual",
            "source_panel": "execution",
            "source_label": ("最近运行配置" if latest_session.get("session_id") else "手动草稿"),
            "data_source": symbol_data_source,
            "data_mode": data_mode,
            "data_context_title": str(source_context.get("title") or ""),
            "data_context_message": str(source_context.get("message") or ""),
            "source_breakdown": symbol_snapshot.get("source_breakdown", {}),
            "validation_label": validation_label,
            "validation_tone": validation_tone,
            "validation_reason": validation_reason,
            "validation_method": validation_method,
            "validation_data_source": validation_data_source,
            "validation_record_id": (
                matched_validation.get("record_id")
                if isinstance(matched_validation, dict)
                else None
            ),
            "research_record_id": (
                matched_research.get("record_id") if isinstance(matched_research, dict) else None
            ),
        }

        return {
            "captured_at": datetime.now(UTC).isoformat(),
            "status": {
                "label": health_label,
                "tone": health_tone,
                "summary": health_summary,
                "session_label": status_label,
                "session_tone": status_tone,
            },
            "summary": {
                "mode": execution_mode,
                "symbol": symbol,
                "timeframe": timeframe,
                "strategy_text": strategy_text or "N/A",
                "position_count": position_count,
                "order_count": order_count,
                "gross_notional": gross_notional,
                "pending_notional": pending_notional,
                "unrealized_pnl": unrealized_pnl,
                "equity": portfolio.get("equity", portfolio.get("total_value", 0.0)),
                "cash": portfolio.get("cash", 0.0),
                "drawdown": portfolio.get("drawdown", 0.0),
                "exposure_pct": dashboard.get("exposure_pct", 0.0),
            },
            "control": {
                "running": bool(live_session.get("running")),
                "session_id": latest_session.get("session_id"),
                "mode": execution_mode,
                "symbol": symbol,
                "timeframe": timeframe,
                "interval_seconds": request.get("interval_seconds", 0),
                "capital": request.get(
                    "capital",
                    portfolio.get("equity", portfolio.get("total_value", 0.0)),
                ),
                "strategies": strategies,
                "config_text": f"{execution_mode} | {symbol} | {timeframe}",
                "strategy_text": strategy_text
                or f"{dashboard.get('strategy_count', 0)} strategies",
                "status_note": control_note,
                "status_tone": control_tone,
                "uptime_label": dashboard.get("uptime_label", "0s"),
                "recent_event_count": dashboard.get("recent_event_count", len(session_events)),
                "open_positions": health.get("open_positions", position_count),
                "pending_orders": health.get("pending_orders", order_count),
                "gross_exposure_value": gross_exposure_value,
                "net_exposure_value": net_exposure_value,
            },
            "telemetry": {
                "point_count": point_count,
                "labels": chart_labels,
                "equity": equity_series,
                "cash": cash_series,
                "market_value": market_value_series,
                "drawdown": drawdown_series,
                "open_positions": open_positions_series,
                "pending_orders": pending_orders_series,
                "equity_last": _last_value(
                    telemetry.get("equity"),
                    portfolio.get("equity", portfolio.get("total_value", 0.0)),
                ),
                "cash_last": _last_value(
                    telemetry.get("cash"),
                    portfolio.get("cash", 0.0),
                ),
                "market_value_last": _last_value(
                    telemetry.get("market_value"),
                    portfolio.get("market_value", gross_notional),
                ),
                "drawdown_last": _last_value(
                    telemetry.get("drawdown"),
                    portfolio.get("drawdown", 0.0),
                ),
            },
            "risk": {
                "kill_switch_active": kill_switch.get("active", False),
                "kill_switch_reason": kill_switch.get("reason"),
                "drawdown_ok": health.get("drawdown_ok", True),
                "warning_events": event_levels.get("warning", 0),
                "error_events": event_levels.get("error", 0) + event_levels.get("critical", 0),
            },
            "positions": positions,
            "orders": open_orders,
            "events": execution_events[:12],
            "event_mix": {
                "by_type": dict(event_types),
                "by_level": dict(event_levels),
            },
            "execution_context": execution_context,
        }

    def research(self, request: ResearchRequest) -> dict[str, Any]:
        definition = get_strategy_definition(request.strategy)
        config, store = _load_store(request.config_path)
        try:
            frame, data_source = _query_symbol_frame(
                store, request.symbol, request.start, request.end
            )
        finally:
            store.close()

        strategy = definition.factory(request.params)
        entries, exits = strategy.generate_signals(frame)
        result = BacktestEngine().run_backtest(
            frame["close"],
            entries,
            exits,
            initial_capital=request.capital,
            fee=request.fee,
            strategy_id=request.strategy,
            symbol=request.symbol,
        )

        payload = cast(
            "dict[str, Any]",
            _to_jsonable(
                {
                    "request": request.model_dump(),
                    "data_source": data_source,
                    "config_summary": {
                        "exchange": config.data.exchange,
                        "parquet_dir": config.data.parquet_dir,
                        "duckdb_path": config.data.duckdb_path,
                    },
                    "result": _result_payload(result),
                    "chart": _chart_payload(frame, entries, exits, result),
                    "signals": {
                        "entries": int(entries.fillna(False).sum()),
                        "exits": int(exits.fillna(False).sum()),
                        "bars": len(frame),
                    },
                }
            ),
        )
        history_record = self.history_store.append_research_run(payload)
        payload["history_record"] = {
            key: value for key, value in history_record.items() if key != "payload"
        }
        return payload

    def validate(self, request: ValidationRequest) -> dict[str, Any]:
        from quantflow.strategy.research.backtest import BacktestEngine
        from quantflow.strategy.validation.cpcv import cpcv_backtest
        from quantflow.strategy.validation.dsr import deflated_sharpe_ratio
        from quantflow.strategy.validation.gate import validation_gate
        from quantflow.strategy.validation.pbo import probability_of_overfitting
        from quantflow.strategy.validation.wfo import walk_forward_optimization

        definition = get_strategy_definition(request.strategy)
        _, store = _load_store(request.config_path)
        try:
            frame, data_source = _query_symbol_frame(store, request.symbol)
        finally:
            store.close()

        strategy = definition.factory(request.params)
        entries, exits = strategy.generate_signals(frame)
        close = frame["close"]

        def signal_fn(data: pd.DataFrame, **params: Any) -> tuple[pd.Series, pd.Series]:
            return definition.factory(params).generate_signals(data)

        payload: dict[str, Any] = {
            "method": request.method,
            "request": request.model_dump(),
            "data_source": data_source,
        }
        if request.method == "cpcv":
            result = cpcv_backtest(
                close,
                entries,
                exits,
                n_groups=request.groups,
                n_test_groups=request.test_groups,
                initial_capital=request.capital,
                fee=request.fee,
                signal_fn=signal_fn,
                param_space=definition.param_space,
                data=frame,
                n_trials=request.optimize_trials,
                method=request.optimize_method,
                objective=request.optimize_objective,
            )
        elif request.method == "dsr":
            backtest = BacktestEngine().run_backtest(
                close,
                entries,
                exits,
                initial_capital=request.capital,
                fee=request.fee,
                strategy_id=request.strategy,
                symbol=request.symbol,
            )
            result = deflated_sharpe_ratio(
                backtest.sharpe_ratio,
                n_trials=request.n_trials,
                sample_length=len(close),
            )
            payload["backtest"] = _result_payload(backtest)
        elif request.method == "wfo":
            result = {
                "rolling": walk_forward_optimization(
                    close,
                    entries,
                    exits,
                    n_windows=request.wfo_windows,
                    mode="rolling",
                    initial_capital=request.capital,
                    fee=request.fee,
                    signal_fn=signal_fn,
                    param_space=definition.param_space,
                    data=frame,
                    n_trials=request.optimize_trials,
                    method=request.optimize_method,
                    objective=request.optimize_objective,
                ),
                "anchored": walk_forward_optimization(
                    close,
                    entries,
                    exits,
                    n_windows=request.wfo_windows,
                    mode="anchored",
                    initial_capital=request.capital,
                    fee=request.fee,
                    signal_fn=signal_fn,
                    param_space=definition.param_space,
                    data=frame,
                    n_trials=request.optimize_trials,
                    method=request.optimize_method,
                    objective=request.optimize_objective,
                ),
            }
        elif request.method == "pbo":
            result = probability_of_overfitting(
                close,
                entries,
                exits,
                n_groups=request.groups,
                n_test_groups=request.test_groups,
                initial_capital=request.capital,
                fee=request.fee,
            )
        else:
            result = validation_gate(
                close,
                entries,
                exits,
                n_trials=request.n_trials,
                cpcv_groups=request.groups,
                cpcv_test_groups=request.test_groups,
                wfo_windows=request.wfo_windows,
                initial_capital=request.capital,
                fee=request.fee,
                signal_fn=signal_fn,
                param_space=definition.param_space,
                data=frame,
                optimize_trials=request.optimize_trials,
                optimize_method=request.optimize_method,
                optimize_objective=request.optimize_objective,
            )

        payload["result"] = _to_jsonable(result)
        payload["signals"] = {
            "entries": int(entries.fillna(False).sum()),
            "exits": int(exits.fillna(False).sum()),
            "bars": len(frame),
        }
        payload["summary"] = _validation_summary(payload)
        history_record = self.history_store.append_validation_run(payload)
        payload["history_record"] = {
            key: value for key, value in history_record.items() if key != "payload"
        }
        return payload
