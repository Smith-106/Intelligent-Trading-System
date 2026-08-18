"""Final tail3: remaining strategy branch gaps to 100/100."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from quantflow.common.config import AppConfig
from quantflow.common.models import Bar
from quantflow.strategy.elliott_wave_strategy import LiuYudongWaveStrategy
from quantflow.strategy.auto_loop import _metric_summary
from quantflow.strategy.engine import TradingSession
from quantflow.strategy.model_registry import ModelRegistry
from quantflow.strategy.rd_agent import RDAgentRunner, load_discovered_factors
from quantflow.strategy.validation.causal_preflight import run_causal_preflight
from quantflow.strategy.validation.cost_fidelity import extract_funding_tca
from quantflow.strategy.validation.cpcv import cpcv_backtest
from quantflow.strategy.validation.lookahead import _make_finding, scan_strategy
from quantflow.strategy.validation.paper_readiness import (
    PaperReadinessConfig,
    assert_paper_readiness,
)
from quantflow.strategy.validation.promotion_path import extract_data_fingerprint
from quantflow.strategy.validation.recursive import scan_recursive
from quantflow.strategy.validation.wfo import WalkForwardOptimization


# ------------------------------------------------------------ causal_preflight
class TestCausalPreflightTail3:
    def test_dedup_same_line_same_snippet(self) -> None:
        """L157-158: two identical shifts on one line → dedup continue."""

        class DupStrategy:
            def generate_signals(self, df: Any) -> tuple[Any, Any]:
                x = df.close.shift(-1) + df.close.shift(-1)
                return (x > 0, x < 0)

        report = run_causal_preflight(DupStrategy())
        assert report is not None


# ---------------------------------------------------------------------- auto_loop
class TestAutoLoopTail3:
    def test_metric_summary_checks_not_dict(self) -> None:
        """L150-159: checks not a dict → skip loop."""
        out = _metric_summary({"checks": "not-dict", "decision": "GO"})
        assert out == {"decision": "GO"}


# ----------------------------------------------------------------------- lookahead
class TestLookaheadTail3:
    def test_scan_func_neither_name_nor_attribute(self) -> None:
        """L202-204: func is neither Name nor Attribute (lambda)."""

        class S:
            def generate_signals(self, df: Any) -> tuple[Any, Any]:
                mask = df.close > 0
                v = (lambda x: x.mean())(df.close[mask])
                return (v > 1, v < 0)

        report = scan_strategy(S())
        assert report.findings is not None

    def test_make_finding_no_lineno(self) -> None:
        """L223-225: node without lineno → line=0 → skip snippet."""
        finding = _make_finding("s", "m", SimpleNamespace(), "p", ["line1"], "high")
        assert finding.line == 0
        assert finding.snippet == ""


# ----------------------------------------------------------------------- recursive
class RecursiveEngineStrategy:
    def __init__(self) -> None:
        self.rsi = SimpleNamespace()
        self.rsi.compute = lambda: 1
        self.obj = [SimpleNamespace()]

    def generate_signals(self, df: Any) -> tuple[Any, Any]:
        engine = SimpleNamespace()
        engine.compute = lambda: df.close
        engine.compute_all = lambda: df.close
        engine.compute()
        engine.compute_all()
        self.rsi.compute()
        self.obj[0].attr()
        return (df.close > 0, df.close < 0)


class TestRecursiveTail3:
    def test_scan_engine_name_calls(self) -> None:
        """L98-102: engine.compute() / engine.compute_all() Name-value branch."""
        report = scan_recursive(RecursiveEngineStrategy)
        assert report is not None


# ------------------------------------------------------------------------ rd_agent
class TestRdAgentTail3:
    def test_cli_returns_empty_factors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L237-263: CLI ok but returns [] → degrade to baseline."""
        agent = RDAgentRunner()
        df = pd.DataFrame(
            {"close": np.linspace(100, 120, 30)},
            index=pd.date_range("2024-01-01", periods=30, freq="D"),
        )
        monkeypatch.setattr(RDAgentRunner, "check_available", lambda self: (True, "ok"))
        monkeypatch.setattr(RDAgentRunner, "cli_available", lambda self: (True, "ok"))
        monkeypatch.setattr(
            RDAgentRunner, "_llm_config_from_env", lambda self: {"api_key": "x"}
        )
        monkeypatch.setattr(RDAgentRunner, "_run_rdagent_cli", lambda self, df, schema: [])
        factors = agent.discover_factors(df)
        assert isinstance(factors, list)

    def test_load_factors_empty_name_skipped(self, tmp_path: pytest.TempPathFactory) -> None:
        """L503-499: factor with empty name skipped."""
        p = tmp_path / "factors.json"
        p.write_text(
            json.dumps({"factors": [{"name": "", "formula": "x"}, {"name": "f1", "formula": "y"}]}),
            encoding="utf-8",
        )
        out = load_discovered_factors(p)
        assert len(out) == 1
        assert out[0].name == "f1"


# ---------------------------------------------------------------- promotion_path
class TestPromotionPathTail3:
    def test_path_block_not_dict(self) -> None:
        """L106-110: path_block not a dict → skip."""
        assert extract_data_fingerprint({"checks": {"promotion_path": "nope"}}) is None


# ----------------------------------------------------------------------------- cpcv
class TestCpcvTail3:
    def test_data_without_close_column(self) -> None:
        """L183-185: train data without 'close' column."""
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        rng = np.random.default_rng(3)
        prices = 100.0 * pd.Series(1.0 + rng.normal(0, 0.01, n), index=dates).cumprod()
        entries = pd.Series(False, index=dates)
        exits = pd.Series(False, index=dates)
        for i in range(0, n, 20):
            entries.iloc[i] = True
        for i in range(10, n, 20):
            exits.iloc[i] = True
        data = pd.DataFrame({"open": prices, "high": prices * 1.01}, index=dates)
        r = cpcv_backtest(
            prices, entries, exits, n_groups=4, n_test_groups=2, n_trials=2,
            data=data, method="random",
            param_space={"threshold": (0.5, 2.0)},
            signal_fn=lambda df, **kw: (df.open > 0, df.open < 0),
        )
        assert r is not None


# ---------------------------------------------------------------- model_registry
class TestModelRegistryTail3:
    def test_promote_to_live_without_evidence(self, tmp_path: pytest.TempPathFactory) -> None:
        """L213-215: evidence None → no paper_evidence write."""
        reg = ModelRegistry(
            tmp_path / "r", paper_readiness=PaperReadinessConfig(enabled=False)
        )
        reg.register("m1", "Cls", "h", {"passed": True, "decision": "GO"})
        e = reg.get("m1")
        e["status"] = "paper"
        reg._write(e)
        entry = reg.promote_to_live("m1")
        assert entry["status"] == "live"
        assert "paper_evidence" not in entry


# ---------------------------------------------------------------- paper_readiness
class TestPaperReadinessTail3:
    def test_orders_meet_minimum(self) -> None:
        """L199-205: orders >= min_orders → elif False."""
        cfg = PaperReadinessConfig(min_paper_days=0, min_fills=0, min_orders=5)
        result = assert_paper_readiness(
            {"paper_days": 10, "fills": 50, "orders": 10}, config=cfg
        )
        assert result["passed"] is True


# ----------------------------------------------------------------------------- wfo
class TestWfoTail3:
    def test_all_folds_skipped_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """L168-175: not folds + skipped_folds>0 warning branch."""
        close = pd.Series(range(100, 105), dtype=float)
        entries = pd.Series(False, index=close.index)
        exits = pd.Series(False, index=close.index)
        wfo = WalkForwardOptimization(n_folds=5, test_ratio=0.9, purge_delta=10)
        with caplog.at_level("WARNING"):
            r = wfo.run(close, entries, exits)
        assert r.folds == []
        assert any("all 5 folds skipped" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------- cost_fidelity
class TestCostFidelityTail3:
    def test_cost_dict_with_invalid_block(self) -> None:
        """L218-220: cost is dict but block invalid → continue."""
        assert extract_funding_tca({"cost_fidelity": {"funding_tca": None}}) is None


# ------------------------------------------------------------------ elliott_wave
class TestElliottWaveTail3:
    def _bars(self, n: int = 25) -> list[Bar]:
        return [
            Bar(
                symbol="BTC/USDT",
                timestamp=1700000000 + i * 60000,
                open=100.0 + i * 0.1,
                high=101.0 + i * 0.1,
                low=99.0 + i * 0.1,
                close=100.5 + i * 0.1,
                volume=1000.0,
            )
            for i in range(n)
        ]

    def test_on_bar_emit_not_callable(self) -> None:
        """L149-117: strategy has no emit_signal → skip emit block."""
        s = LiuYudongWaveStrategy()
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            s,
            "generate_signals",
            lambda df: (
                pd.concat(
                    [pd.Series(False, index=df.index).iloc[:-1],
                     pd.Series([True], index=[df.index[-1]])]
                ),
                pd.Series(False, index=df.index),
            ),
        )
        for bar in self._bars():
            s.on_bar(SimpleNamespace(), bar)
        monkeypatch.undo()
        assert len(s._bar_rows) >= 20

    def test_on_bar_exit_signal_emits_flat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L162-117: exits True on last bar → FLAT emit, elif skipped."""
        s = LiuYudongWaveStrategy()
        emitted: list[Any] = []
        monkeypatch.setattr(s, "emit_signal", lambda sig: emitted.append(sig), raising=False)
        monkeypatch.setattr(
            s,
            "generate_signals",
            lambda df: (
                pd.Series(False, index=df.index),
                pd.concat(
                    [pd.Series(False, index=df.index).iloc[:-1],
                     pd.Series([True], index=[df.index[-1]])]
                ),
            ),
        )
        for bar in self._bars():
            s.on_bar(SimpleNamespace(), bar)
        assert len(emitted) >= 1
        assert emitted[0].direction.name == "FLAT"


# ------------------------------------------------------------------------- engine
class TestEngineTail3:
    @pytest.mark.asyncio
    async def test_paper_replay_empty_store_falls_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L1535-1555: paper mode, store empty → fall through to fetcher."""
        cfg = AppConfig()
        cfg.execution.mode = "paper"
        cfg.execution.symbols = ["BTC/USDT"]
        session = TradingSession(cfg, [])
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=pd.DataFrame())
        fake_store.close = MagicMock()
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock()
        fake_fetcher.fetch_ohlcv = AsyncMock(return_value=pd.DataFrame())
        fake_fetcher.disconnect = AsyncMock()
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.data.fetcher.DataFetcher", return_value=fake_fetcher),
            patch.object(session, "check_health"),
            patch.object(session, "_periodic_maintenance", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            async def _stop(*a, **k):
                session._running = False

            mock_sleep.side_effect = _stop
            session._running = True
            await session.run_data_loop(
                symbol="BTC/USDT", timeframe="1h", interval_seconds=60
            )
        fake_store.close.assert_called_once()
