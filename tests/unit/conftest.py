"""Shared DataStore test doubles for the QuantFlow test-suite.

History: the suite monkeypatches ``quantflow.data.store.DataStore`` at 13
sites with ad-hoc stubs that each reimplemented a *fragment* of the public
interface. Every time the real store gained a method (REV-024 added
``resolve_symbol``) a subset of those stubs broke at runtime with an
``AttributeError`` / ``TypeError`` instead of failing at collection time.

``FakeDataStore`` is the single shared stand-in covering the full public
interface of :class:`quantflow.data.store.DataStore` with configurable
behaviour (return frames / empty frames / raised exceptions). New stub sites
should subclass or instantiate this instead of hand-rolling a partial store.
The ``DataStoreProtocol`` (see ``test_fakedatastore_contract.py``) pins the
contract so a stub that forgets a method fails at collection time.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from quantflow.common.exceptions import DataError
from quantflow.data.store import META_DATA_TYPES, META_REQUIRED_COLUMNS
from quantflow.data.store import DataStore as _RealDataStore

#: Sentinel meaning "query was not configured" -> an empty frame (mirrors the
#: real store's "no data" return), without conflating with an explicit ``None``
#: result that some callers treat as a distinct "missing" signal.
_EMPTY = object()


class FakeDataStore:
    """Configurable in-memory stand-in for :class:`quantflow.data.store.DataStore`.

    Implements the full public interface of the real store (query / save /
    resolve_symbol / close plus the meta-data surface and per-symbol
    helpers), so any stub derived from it automatically satisfies
    ``DataStoreProtocol`` and survives future store extensions that have been
    added to that protocol.

    Behaviour is configurable via constructor kwargs:

      * ``query_result`` -- a ``pd.DataFrame`` (or a callable returning one)
        served by :meth:`query`. Defaults to an empty frame.
      * ``query_raise`` -- an ``Exception`` subtype raised by every
        :meth:`query` call (exercises the storage-error path).
      * ``resolve_map`` -- ``dict[str, str]`` mapping logical symbol -> stored
        symbol used by :meth:`resolve_symbol`; entries beyond the map fall
        back to the bare symbol (matching the real store's fallback.
      * ``meta`` -- ``dict[(meta_type, symbol), pd.DataFrame]`` served by the
        meta queries; missing keys return the empty per-type schema frame.
      * ``callbacks`` -- a dict of optional ``Callable`` hooks invoked from
        the book-keeping methods (``save``, ``close``, ...). Used by tests that
        asserted on side-effects (e.g. ``calls.append({"closed": True})``).

    Every public data method records ``("method", symbol, kwargs)`` into
    :attr:`calls` so tests can assert on the store usage pattern.
    """

    def __init__(
        self,
        parquet_dir: str | Path = ".",
        duckdb_path: str = ":memory:",
        *,
        query: pd.DataFrame | Callable[..., pd.DataFrame] | object = _EMPTY,
        query_raise: type[Exception] | None = None,
        resolve_map: dict[str, str] | None = None,
        meta_frames: dict[tuple[str, str], pd.DataFrame] | None = None,
        close_cb: Callable[[], None] | None = None,
        save_cb: Callable[[pd.DataFrame, str], None] | None = None,
    ) -> None:
        self.parquet_dir = Path(parquet_dir)
        self.duckdb_path = duckdb_path
        self._query_service = query
        self._query_raise = query_raise
        self._resolve_map = resolve_map or {}
        self._meta_frames = meta_frames or {}
        self._close_cb = close_cb
        self._save_cb = save_cb

        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.closed = False
        self.saved: list[pd.DataFrame] = []

    # ------------------------------------------------------------------
    # Book-keeping
    # ------------------------------------------------------------------

    def _record(self, method: str, symbol: str, **kwargs: Any) -> None:
        self.calls.append((method, symbol, kwargs))

    # ------------------------------------------------------------------
    # Query layer
    # ------------------------------------------------------------------

    def query(
        self,
        symbol: str,
        start: int | None = None,
        end: int | None = None,
        timeframe: str | None = None,
        columns: list[str] | tuple[str, ...] | None = None,
    ) -> pd.DataFrame:
        """Return configured / empty / raised frame; mirrors real store."""
        self._record("query", symbol, start=start, end=end, timeframe=timeframe, columns=columns)
        if self._query_raise is not None:
            raise self._query_raise(f"Query failed for {symbol!r}")
        service = self._query_service
        if service is _EMPTY:
            return pd.DataFrame(columns=columns or None)
        df = service() if callable(service) else service
        # Legacy stub semantics: return the configured frame as-is.  Only
        # honour the explicit column projection when the caller asks for a
        # subset -- time/timeframe filters are left to the real store so unit
        # tests keep full control over what `query` returns.
        if columns is not None:
            return df[[c for c in columns if c in df.columns]].reset_index(drop=True)
        return df.reset_index(drop=True)

    # ------------------------------------------------------------------
    # Meta-data queries (funding rate / open interest)
    # ------------------------------------------------------------------

    def query_funding_rates(
        self,
        symbol: str,
        start: int | None = None,
        end: int | None = None,
    ) -> pd.DataFrame:
        return self._query_meta("funding_rate", symbol, start, end)

    def query_open_interest(
        self,
        symbol: str,
        start: int | None = None,
        end: int | None = None,
    ) -> pd.DataFrame:
        return self._query_meta("open_interest", symbol, start, end)

    def _query_meta(
        self,
        data_type: str,
        symbol: str,
        start: int | None,
        end: int | None,
    ) -> pd.DataFrame:
        if data_type not in META_DATA_TYPES:
            raise ValueError(f"Invalid meta data_type: {data_type!r}")
        self._record(f"query_{data_type}", symbol, start=start, end=end)
        key = (data_type, symbol)
        if key not in self._meta_frames:
            return pd.DataFrame(columns=list(META_REQUIRED_COLUMNS[data_type]))
        frame = self._meta_frames[key]
        if start is not None and "timestamp" in frame.columns:
            frame = frame[frame["timestamp"] >= int(start)]
        if end is not None and "timestamp" in frame.columns:
            frame = frame[frame["timestamp"] <= int(end)]
        return frame.reset_index(drop=True)

    def get_last_meta_timestamp(self, symbol: str, data_type: str) -> int | None:
        if data_type not in META_DATA_TYPES:
            raise ValueError(f"Invalid meta data_type: {data_type!r}")
        self._record("get_last_meta_timestamp", symbol, data_type=data_type)
        key = (data_type, symbol)
        frame = self._meta_frames.get(key)
        if frame is None or frame.empty or "timestamp" not in frame.columns:
            return None
        return int(frame["timestamp"].max())

    # ------------------------------------------------------------------
    # Save layer
    # ------------------------------------------------------------------

    def save(self, df: pd.DataFrame, symbol: str) -> None:
        self._record("save", symbol)
        if df.empty:
            return
        self.saved.append(df.copy())
        if self._save_cb is not None:
            self._save_cb(df, symbol)

    def save_funding_rates(self, df: pd.DataFrame, symbol: str) -> None:
        self._save_meta(df, symbol, "funding_rate")

    def save_open_interest(self, df: pd.DataFrame, symbol: str) -> None:
        self._save_meta(df, symbol, "open_interest")

    def _save_meta(self, df: pd.DataFrame, symbol: str, data_type: str) -> None:
        if data_type not in META_DATA_TYPES:
            raise ValueError(
                f"Invalid meta data_type: {data_type!r}. Allowed: {sorted(META_DATA_TYPES)}"
            )
        if df.empty:
            return
        required = META_REQUIRED_COLUMNS[data_type]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise DataError(f"{data_type} frame missing required columns: {missing}")
        self._record(f"save_{data_type}", symbol)
        self.saved.append(df.copy())
        if self._save_cb is not None:
            self._save_cb(df, symbol)

    # ------------------------------------------------------------------
    # Symbol resolution + per-symbol helpers
    # ------------------------------------------------------------------

    def resolve_symbol(
        self,
        symbol: str,
        *,
        priority: tuple[str, ...] = _RealDataStore.DEFAULT_SUFFIX_PRIORITY,
    ) -> str:
        """Mirror the real resolver: mapped entry wins, else bare symbol."""
        self._record("resolve_symbol", symbol, priority=priority)
        return self._resolve_map.get(symbol, symbol)

    def list_symbols(self) -> list[str]:
        self._record("list_symbols", "")
        return sorted({s for _, s in self.calls if s})

    def symbol_summary(self, symbol: str) -> dict[str, Any] | None:
        self._record("symbol_summary", symbol)
        return None

    def get_date_range(self, symbol: str) -> tuple[int, int] | None:
        self._record("get_date_range", symbol)
        return None

    def get_last_timestamp(self, symbol: str, timeframe: str) -> int | None:
        self._record("get_last_timestamp", symbol, timeframe=timeframe)
        return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def group_cols(df: pd.DataFrame) -> list[str]:
        """Mirror the real store's partition-column projection."""
        return [c for c in df.columns if c not in {"year", "month"}]

    def close(self) -> None:
        self.closed = True
        self._record("close", "")
        if self._close_cb is not None:
            self._close_cb()
