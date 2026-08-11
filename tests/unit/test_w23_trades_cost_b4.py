"""W23 tests: trades ingest, Elliott cost-grid package, B4 contract artifacts."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd
import pytest

from quantflow.common.config import ExecutionConfig
from quantflow.data.trades_ingest import TradesIngestLoop
from quantflow.data.trades_store import TradesStore
from quantflow.strategy.research.elliott_cost_grid_contract import (
    ElliottCostGridPackage,
    build_elliott_cost_grid_package,
)
from quantflow.strategy.validation.cost_fidelity import require_cost_grid, require_funding_tca
from quantflow.strategy.validation.promotion_path import check_promotion_path


class TestW23aTradesIngest:
    def test_config_defaults_off(self) -> None:
        cfg = ExecutionConfig()
        assert cfg.trades_poll_enabled is False
        assert cfg.trades_poll_interval_s == 30.0

    @pytest.mark.asyncio
    async def test_poll_once_writes_store(self, tmp_path: Path) -> None:
        store = TradesStore(tmp_path / "trades")
        calls = {"n": 0}

        async def fake_fetch(symbol: str, limit: int = 100) -> pd.DataFrame:
            calls["n"] += 1
            return pd.DataFrame(
                {
                    "timestamp": [1_700_000_000_000 + calls["n"]],
                    "price": [100.0],
                    "amount": [1.0],
                    "side": ["buy"],
                }
            )

        loop = TradesIngestLoop(
            store,
            fetch_trades=fake_fetch,
            symbols=["BTC/USDT"],
            interval_s=60.0,
            limit=10,
        )
        n = await loop.poll_once()
        assert n >= 1
        loaded = store.load_trades("BTC/USDT")
        assert len(loaded) >= 1
        assert loop.batches_written >= 1

    @pytest.mark.asyncio
    async def test_push_trades_ws_style(self, tmp_path: Path) -> None:
        store = TradesStore(tmp_path / "trades")

        async def never_fetch(symbol: str, limit: int = 100) -> pd.DataFrame:
            raise AssertionError("fetch should not run for push")

        loop = TradesIngestLoop(
            store,
            fetch_trades=never_fetch,
            symbols=["ETH/USDT"],
            interval_s=60.0,
        )
        df = pd.DataFrame(
            {
                "timestamp": [1_700_000_000_100],
                "price": [50.0],
                "amount": [2.0],
                "side": ["sell"],
            }
        )
        n = await loop.push_trades("ETH/USDT", df)
        assert n >= 1
        assert len(store.load_trades("ETH/USDT")) == 1

    @pytest.mark.asyncio
    async def test_start_stop_loop(self, tmp_path: Path) -> None:
        store = TradesStore(tmp_path / "trades")

        async def fake_fetch(symbol: str, limit: int = 100) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "timestamp": [1_700_000_000_200],
                    "price": [1.0],
                    "amount": [1.0],
                    "side": ["buy"],
                }
            )

        loop = TradesIngestLoop(
            store,
            fetch_trades=fake_fetch,
            symbols=["BTC/USDT"],
            interval_s=0.05,
        )
        loop.start()
        await asyncio.sleep(0.12)
        await loop.stop()
        assert not loop.is_running
        assert loop.batches_written >= 1


class TestW23bElliottCostGrid:
    @pytest.mark.asyncio
    async def test_cost_grid_structure_passes(self, tmp_path: Path) -> None:
        pkg = await build_elliott_cost_grid_package(
            n_bars=100,
            output_dir=tmp_path / "elliott_cost",
        )
        assert isinstance(pkg, ElliottCostGridPackage)
        assert pkg.promotion_eligible is False
        assert pkg.path_check.get("passed") is True
        assert pkg.cost_check.get("passed") is True
        require_cost_grid(pkg.report)
        require_funding_tca(pkg.report)
        assert pkg.report.get("decision") == "NO_GO"
        assert (tmp_path / "elliott_cost" / "cost_report.json").exists()
        # full path + fingerprint still ok
        assert check_promotion_path(pkg.report, require_fingerprint=True)["passed"]

    @pytest.mark.asyncio
    async def test_grid_has_zero_and_production_cells(self) -> None:
        pkg = await build_elliott_cost_grid_package(n_bars=80)
        fees = {(r["taker_fee"], r["slippage"]) for r in pkg.fee_slip_grid}
        assert (0.0, 0.0) in fees
        assert (0.001, 0.001) in fees


class TestW23cB4Contract:
    def test_b4_doc_and_overlay_exist(self) -> None:
        root = Path(__file__).resolve().parents[2]
        doc = root / "docs" / "research" / "Candidate-Baseline-4.md"
        overlay = (
            root
            / "quantflow"
            / "config"
            / "research"
            / "overlays"
            / "funding_rate_b4_overlay.yaml"
        )
        assert doc.is_file()
        assert overlay.is_file()
        text = doc.read_text(encoding="utf-8")
        assert "0.0004" in text
        assert "DOES NOT" in text or "not" in text.lower()
        assert "B3" in text
        ov = overlay.read_text(encoding="utf-8")
        assert "0.0004" in ov
        assert "B3" in ov or "frozen" in ov.lower()

    def test_b3_yaml_threshold_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[2]
        b3 = (root / "quantflow" / "config" / "strategies" / "funding_rate.yaml").read_text(
            encoding="utf-8"
        )
        assert "entry_threshold: 0.001" in b3
