"""W24 tests: B4 runner, Elliott reseat cost grid, watch_trades scaffold."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from quantflow.strategy.research.elliott_cost_grid_contract import (
    build_elliott_cost_grid_package,
)
from quantflow.strategy.validation.cost_fidelity import require_cost_grid, require_funding_tca


class TestW24aB4Runner:
    def test_dry_run_writes_baseline4_not_baseline3(self, tmp_path: Path) -> None:
        import scripts.run_baseline4_challenger as b4

        out = tmp_path / "paper_replay" / "baseline4" / "dry"
        rc = b4.main(["--dry-run", "--out-dir", str(out)])
        assert rc == 0
        assert (out / "run_meta.json").is_file()
        assert (out / "adjudication.json").is_file()
        meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
        assert meta["contract_id"] == "B4"
        assert meta["params"]["entry_threshold"] == 0.0004
        assert meta["promotion_eligible"] is False
        adj = json.loads((out / "adjudication.json").read_text(encoding="utf-8"))
        assert adj["b3_frozen_entry_threshold"] == 0.001
        assert adj["promotion"] == "KEEP_BASELINE_0"

    def test_refuses_baseline3_out_dir(self, tmp_path: Path) -> None:
        import scripts.run_baseline4_challenger as b4

        bad = tmp_path / "paper_replay" / "baseline3" / "oops"
        rc = b4.main(["--dry-run", "--out-dir", str(bad)])
        assert rc == 2
        assert not (bad / "run_meta.json").exists()

    def test_synthetic_smoke(self, tmp_path: Path) -> None:
        import scripts.run_baseline4_challenger as b4

        out = tmp_path / "baseline4" / "syn"
        rc = b4.main(["--synthetic", "--n-bars", "60", "--out-dir", str(out)])
        assert rc == 0
        meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
        assert meta["mode"] == "synthetic"
        assert "results" in meta


class TestW24bReseatGrid:
    @pytest.mark.asyncio
    async def test_reseat_methods_on_grid(self) -> None:
        pkg = await build_elliott_cost_grid_package(n_bars=80, reseat=True)
        assert pkg.cost_check.get("passed") is True
        require_cost_grid(pkg.report)
        require_funding_tca(pkg.report)
        methods = {r["method"] for r in pkg.fee_slip_grid}
        assert methods == {"paper_replay_reseat"}
        assert pkg.report["run_meta"]["cost_grid_method"] == "paper_replay_reseat"
        assert pkg.promotion_eligible is False
        assert pkg.report.get("decision") == "NO_GO"

    @pytest.mark.asyncio
    async def test_proxy_still_available(self) -> None:
        pkg = await build_elliott_cost_grid_package(n_bars=60, reseat=False)
        methods = {r["method"] for r in pkg.fee_slip_grid}
        assert methods == {"proxy_from_fills"}


class TestW24cWatchTrades:
    @pytest.mark.asyncio
    async def test_watch_trades_poll_fallback(self) -> None:
        from quantflow.data.fetcher import DataFetcher

        fetcher = DataFetcher.__new__(DataFetcher)
        fetcher._exchange = MagicMock()
        # no watch_trades attr → poll path
        del fetcher._exchange.watch_trades
        fetcher._exchange.fetch_trades = AsyncMock(
            return_value=[
                {"timestamp": 1, "price": 10.0, "amount": 1.0, "side": "buy"},
            ]
        )
        fetcher._ws_running = False
        fetcher._ws_task = None
        batches: list[pd.DataFrame] = []

        def stop_soon() -> None:
            fetcher._ws_running = False

        async def cb(df: pd.DataFrame) -> None:
            batches.append(df)
            stop_soon()

        # drive loop directly (avoid ensure_future race)
        fetcher._ws_running = True
        task = asyncio.create_task(
            fetcher._watch_trades_loop(
                "BTC/USDT",
                cb,
                limit=10,
                poll_fallback_interval_s=0.01,
            )
        )
        await asyncio.wait_for(task, timeout=2.0)
        assert len(batches) >= 1
        assert list(batches[0].columns) == ["timestamp", "price", "amount", "side"]

    @pytest.mark.asyncio
    async def test_attach_watch_trades_pushes_store(self, tmp_path: Path) -> None:
        from quantflow.data.trades_ingest import TradesIngestLoop, attach_watch_trades
        from quantflow.data.trades_store import TradesStore

        store = TradesStore(tmp_path / "trades")

        async def never_fetch(symbol: str, limit: int = 100) -> pd.DataFrame:
            return pd.DataFrame(columns=["timestamp", "price", "amount", "side"])

        loop = TradesIngestLoop(
            store,
            fetch_trades=never_fetch,
            symbols=["BTC/USDT"],
            interval_s=60.0,
        )

        class FakeFetcher:
            def __init__(self) -> None:
                self.stopped = False

            async def watch_trades(
                self,
                symbol: str,
                callback: Any = None,
                *,
                limit: int = 50,
                poll_fallback_interval_s: float = 5.0,
            ) -> None:
                df = pd.DataFrame(
                    {
                        "timestamp": [1_700_000_000_000],
                        "price": [100.0],
                        "amount": [1.0],
                        "side": ["buy"],
                    }
                )
                if callback is not None:
                    await callback(df)

            def stop_stream(self) -> None:
                self.stopped = True

        fake = FakeFetcher()
        await attach_watch_trades(loop, fake, "BTC/USDT")
        loaded = store.load_trades("BTC/USDT")
        assert len(loaded) == 1
