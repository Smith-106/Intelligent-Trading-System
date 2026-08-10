"""W22 tests: trades store + CVD features, Elliott contract package, funding/B3 tracks."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantflow.data.feature_store import FeatureStore
from quantflow.data.trades_store import (
    TradesStore,
    build_cvd_feature_frame,
    save_cvd_features,
)
from quantflow.signal.funding_risk_gate import evaluate_funding_risk
from quantflow.strategy.research.elliott_paper_replay_contract import (
    ElliottPaperReplayPackage,
    build_elliott_paper_replay_package,
)
from quantflow.strategy.validation.promotion_path import check_promotion_path


def _ohlcv(n: int = 40, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    ts0 = 1_700_000_000_000
    return pd.DataFrame(
        {
            "timestamp": ts0 + np.arange(n) * 3_600_000,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": rng.uniform(10, 30, n),
        }
    )


class TestW22aTradesAndCvd:
    def test_trades_store_roundtrip(self, tmp_path: Path) -> None:
        store = TradesStore(tmp_path / "trades")
        ts = 1_700_000_100_000
        trades = pd.DataFrame(
            {
                "timestamp": [ts, ts + 1, ts + 2],
                "price": [100.0, 101.0, 100.5],
                "amount": [1.0, 2.0, 1.5],
                "side": ["buy", "sell", "buy"],
            }
        )
        n = store.save_trades("BTC/USDT", trades)
        assert n == 3
        loaded = store.load_trades("BTC/USDT")
        assert len(loaded) == 3
        assert list(loaded["side"]) == ["buy", "sell", "buy"]

    def test_cvd_prefers_trades_then_proxy(self) -> None:
        ohlcv = _ohlcv(5)
        # trades only on first two bars
        t0 = int(ohlcv["timestamp"].iloc[0])
        trades = pd.DataFrame(
            {
                "timestamp": [t0, t0 + 10, t0 + 20],
                "price": [100.0, 101.0, 102.0],
                "amount": [1.0, 1.0, 1.0],
                "side": ["buy", "buy", "sell"],
            }
        )
        with_trades = build_cvd_feature_frame(ohlcv, trades, prefer_trades=True)
        assert with_trades["cvd_source"].iloc[0] == "trades"
        proxy = build_cvd_feature_frame(ohlcv, None, prefer_trades=True)
        assert proxy["cvd_source"].iloc[0] == "proxy"
        assert "cvd" in proxy.columns

    def test_save_cvd_features_to_feature_store(self, tmp_path: Path) -> None:
        fs = FeatureStore(str(tmp_path / "features"))
        ohlcv = _ohlcv(12)
        frame = save_cvd_features(fs, "ETH/USDT", ohlcv, trades=None)
        assert frame["cvd_source"].iloc[0] == "proxy"
        loaded = fs.load_features("ETH/USDT")
        assert not loaded.empty
        assert "cvd" in loaded.columns


class TestW22bElliottContractPackage:
    @pytest.mark.asyncio
    async def test_package_has_fingerprint_and_path_pass(self, tmp_path: Path) -> None:
        pkg = await build_elliott_paper_replay_package(
            n_bars=100,
            output_dir=tmp_path / "elliott_pkg",
        )
        assert isinstance(pkg, ElliottPaperReplayPackage)
        assert pkg.execution_path == "paper_replay"
        assert pkg.promotion_eligible is False
        assert pkg.data_fingerprint.get("aggregate")
        assert pkg.path_check.get("passed") is True
        assert (tmp_path / "elliott_pkg" / "run_meta.json").exists()
        meta = json.loads((tmp_path / "elliott_pkg" / "run_meta.json").read_text(encoding="utf-8"))
        assert meta["execution_path"] == "paper_replay"
        assert "data_fingerprint" in meta
        # W14 check on the package dict
        chk = check_promotion_path(pkg.to_dict(), require_fingerprint=True)
        assert chk["passed"] is True

    @pytest.mark.asyncio
    async def test_smoke_path_without_fingerprint_fails_path_check(self) -> None:
        # Ensure we still refuse incomplete reports
        bad = {"execution_path": "paper_replay"}
        assert check_promotion_path(bad, require_fingerprint=True)["passed"] is False


class TestW22cFundingTracks:
    def test_risk_gate_is_independent_toggle(self) -> None:
        # Gate off: extreme rate does not block (B3 threshold is separate story)
        d_off = evaluate_funding_risk(0.05, enabled=False, max_abs=0.001)
        assert d_off.blocked is False
        d_on = evaluate_funding_risk(0.05, enabled=True, max_abs=0.001)
        assert d_on.blocked is True

    def test_module_doc_mentions_b3_separation(self) -> None:
        import quantflow.signal.funding_risk_gate as mod

        doc = mod.__doc__ or ""
        assert "B3" in doc
        assert "risk" in doc.lower()
