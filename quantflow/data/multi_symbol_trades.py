"""Multi-symbol trades ingest helpers (W25c).

Thin coordinator on top of :class:`TradesIngestLoop` — one loop already
round-robins symbols; this module adds:

- explicit multi-symbol factory
- per-symbol last-batch stats
- optional symbol set mutation

Default posture remains **opt-in** (caller starts the loop).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from quantflow.data.trades_ingest import FetchTradesFn, TradesIngestLoop
from quantflow.data.trades_store import TradesStore

logger = logging.getLogger(__name__)


@dataclass
class MultiSymbolTradesCoordinator:
    """Track per-symbol ingest stats while reusing a single poll loop."""

    loop: TradesIngestLoop
    symbols: list[str]
    per_symbol_batches: dict[str, int] = field(default_factory=dict)
    per_symbol_rows: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for s in self.symbols:
            self.per_symbol_batches.setdefault(s, 0)
            self.per_symbol_rows.setdefault(s, 0)

    def _on_batch(self, symbol: str, df: pd.DataFrame) -> None:
        self.per_symbol_batches[symbol] = self.per_symbol_batches.get(symbol, 0) + 1
        n = 0 if df is None else int(len(df))
        self.per_symbol_rows[symbol] = self.per_symbol_rows.get(symbol, 0) + n

    def add_symbol(self, symbol: str) -> None:
        if symbol not in self.symbols:
            self.symbols.append(symbol)
            self.loop._symbols = list(self.symbols)
            self.per_symbol_batches.setdefault(symbol, 0)
            self.per_symbol_rows.setdefault(symbol, 0)

    def remove_symbol(self, symbol: str) -> None:
        if symbol in self.symbols:
            self.symbols = [s for s in self.symbols if s != symbol]
            self.loop._symbols = list(self.symbols)

    async def poll_once(self) -> int:
        return await self.loop.poll_once()

    def start(self) -> Any:
        return self.loop.start()

    async def stop(self) -> None:
        await self.loop.stop()

    def stats(self) -> dict[str, Any]:
        return {
            "symbols": list(self.symbols),
            "batches_written": self.loop.batches_written,
            "rows_written": self.loop.rows_written,
            "per_symbol_batches": dict(self.per_symbol_batches),
            "per_symbol_rows": dict(self.per_symbol_rows),
            "last_error": self.loop.last_error,
        }


def build_multi_symbol_trades_ingest(
    store: TradesStore | str,
    *,
    fetch_trades: FetchTradesFn,
    symbols: Sequence[str],
    interval_s: float = 30.0,
    limit: int = 100,
) -> MultiSymbolTradesCoordinator:
    """Factory: multi-symbol coordinator with stats callback."""
    ts = store if isinstance(store, TradesStore) else TradesStore(store)
    syms = list(symbols)
    if not syms:
        raise ValueError("symbols must be non-empty for multi-symbol trades ingest")

    coord_holder: dict[str, MultiSymbolTradesCoordinator] = {}

    def _cb(symbol: str, df: pd.DataFrame) -> None:
        c = coord_holder.get("c")
        if c is not None:
            c._on_batch(symbol, df)

    loop = TradesIngestLoop(
        ts,
        fetch_trades=fetch_trades,
        symbols=syms,
        interval_s=interval_s,
        limit=limit,
        on_batch=_cb,
    )
    coord = MultiSymbolTradesCoordinator(loop=loop, symbols=syms)
    coord_holder["c"] = coord
    logger.info("MultiSymbolTradesCoordinator ready: %s", syms)
    return coord
