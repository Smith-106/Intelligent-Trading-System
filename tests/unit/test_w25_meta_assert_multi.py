"""W25 tests: B4 meta-window, Elliott assert script, multi-symbol trades."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest


class TestW25aMetaWindow:
    def test_meta_window_writes_run_id_under_baseline4(self, tmp_path: Path) -> None:
        import scripts.run_baseline4_challenger as b4

        base = tmp_path / "paper_replay" / "baseline4"
        rc = b4.main(
            [
                "--meta-window",
                "--run-id",
                "w25_test",
                "--out-dir",
                str(base),
                "--start",
                "2024-01-01",
                "--end",
                "2024-01-02",
            ]
        )
        # BLOCKED or META_SMOKE both ok structurally (no ERROR)
        assert rc in (0, 1)
        out = base / "w25_test"
        assert (out / "run_meta.json").is_file()
        meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
        assert meta["contract_id"] == "B4"
        assert meta["mode"] == "meta_window"
        assert "baseline3" not in str(out).replace("\\", "/")

    def test_meta_refuses_baseline3(self, tmp_path: Path) -> None:
        import scripts.run_baseline4_challenger as b4

        bad = tmp_path / "baseline3"
        rc = b4.main(["--meta-window", "--run-id", "x", "--out-dir", str(bad)])
        assert rc == 2


class TestW25bAssertScript:
    def test_assert_build_passes(self, tmp_path: Path) -> None:
        import scripts.assert_elliott_cost_package as assert_mod

        out = tmp_path / "elliott_assert"
        rc = assert_mod.main(["--build", "--dir", str(out), "--n-bars", "60", "--no-reseat"])
        assert rc == 0
        assert (out / "cost_report.json").is_file()

    def test_assert_fails_on_empty_report(self, tmp_path: Path) -> None:
        import scripts.assert_elliott_cost_package as assert_mod

        d = tmp_path / "empty"
        d.mkdir()
        (d / "run_meta.json").write_text("{}", encoding="utf-8")
        rc = assert_mod.main(["--dir", str(d)])
        assert rc == 1


class TestW25cMultiSymbolTrades:
    @pytest.mark.asyncio
    async def test_multi_symbol_poll_stats(self, tmp_path: Path) -> None:
        from quantflow.data.multi_symbol_trades import build_multi_symbol_trades_ingest
        from quantflow.data.trades_store import TradesStore

        store = TradesStore(tmp_path / "trades")
        seen: list[str] = []

        async def fetch(symbol: str, limit: int = 100) -> pd.DataFrame:
            seen.append(symbol)
            return pd.DataFrame(
                {
                    "timestamp": [1_700_000_000_000 + len(seen)],
                    "price": [1.0],
                    "amount": [1.0],
                    "side": ["buy"],
                }
            )

        coord = build_multi_symbol_trades_ingest(
            store,
            fetch_trades=fetch,
            symbols=["BTC/USDT", "ETH/USDT"],
            interval_s=60.0,
        )
        n = await coord.poll_once()
        assert n >= 2
        assert set(seen) == {"BTC/USDT", "ETH/USDT"}
        st = coord.stats()
        assert st["per_symbol_batches"]["BTC/USDT"] >= 1
        assert st["per_symbol_batches"]["ETH/USDT"] >= 1
        coord.add_symbol("SOL/USDT")
        assert "SOL/USDT" in coord.symbols
