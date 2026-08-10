"""W21 tests: funding risk gate, Elliott paper_replay smoke, trades CVD scaffold."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from quantflow.common.config import AppConfig, RiskConfig
from quantflow.common.models import Direction, Signal
from quantflow.indicators.volume import cvd_from_trades, cvd_proxy
from quantflow.signal.funding_risk_gate import REASON, evaluate_funding_risk
from quantflow.strategy.research.elliott_paper_replay_smoke import (
    ElliottPaperReplaySmokeReport,
    run_elliott_paper_replay_smoke,
)
from quantflow.strategy.research.paper_replay import _resolve_strategy_class, build_session


class TestW21aFundingRiskGate:
    def test_evaluate_disabled_never_blocks(self) -> None:
        d = evaluate_funding_risk(0.05, enabled=False, max_abs=0.001)
        assert d.blocked is False

    def test_evaluate_blocks_extreme(self) -> None:
        d = evaluate_funding_risk(0.002, enabled=True, max_abs=0.001)
        assert d.blocked is True
        assert REASON in d.reason

    def test_evaluate_missing_rate_fail_closed_when_enabled(self) -> None:
        d = evaluate_funding_risk(None, enabled=True, max_abs=0.001)
        assert d.blocked is True
        assert "missing" in d.reason

    def test_session_note_funding_pauses_new_entries(self) -> None:
        from quantflow.common.pause_reasons import PauseReasonSet
        from quantflow.execution.engine import ExecutionEngine
        from quantflow.execution.paper_gateway import PaperGateway
        from quantflow.strategy.engine import TradingSession
        from quantflow.strategy.templates.trend_following import TrendFollowingStrategy

        cfg = AppConfig(
            risk=RiskConfig(
                funding_risk_gate_enabled=True,
                max_funding_rate_abs=0.001,
                funding_risk_gate_kill=False,
                kill_switch_enabled=False,
            )
        )
        session = TradingSession(cfg, [TrendFollowingStrategy()])
        session._execution = ExecutionEngine(gateway=PaperGateway())
        session._execution.set_portfolio(session._portfolio)
        session._risk_pauses = PauseReasonSet()
        session._last_funding_rate = {}
        session._kill_switch = None
        session._event_bus = session._event_bus  # already set

        session.note_funding_rate("BTC/USDT", 0.005)
        assert session._risk_pauses.is_paused
        assert REASON in session._risk_pauses.reasons

        # under threshold clears soft pause
        session.note_funding_rate("BTC/USDT", 0.0001)
        assert not session._risk_pauses.is_paused


class TestW21bElliottPaperReplay:
    def test_resolve_liu_yudong(self) -> None:
        cls = _resolve_strategy_class("liu_yudong_wave")
        assert cls.name == "liu_yudong_wave" or getattr(cls, "name", "") == "liu_yudong_wave"

    def test_build_session_accepts_liu(self) -> None:
        s = build_session("liu_yudong_wave", capital=50_000.0)
        assert s._strategies[0].name == "liu_yudong_wave"

    @pytest.mark.asyncio
    async def test_paper_replay_smoke_meta(self) -> None:
        report = await run_elliott_paper_replay_smoke(n_bars=120)
        assert isinstance(report, ElliottPaperReplaySmokeReport)
        assert report.execution_path == "paper_replay"
        assert report.promotion_eligible is False
        assert report.is_smoke is True
        assert report.n_bars == 120
        d = report.to_dict()
        assert d["run_meta"]["execution_path"] == "paper_replay"
        assert d["run_meta"]["promotion_eligible"] is False


class TestW21cTradesCvd:
    def test_cvd_from_trades_buy_sell(self) -> None:
        prices = pd.Series([100.0, 101.0, 100.5])
        amounts = pd.Series([1.0, 2.0, 1.0])
        sides = pd.Series(["buy", "sell", "buy"])
        cvd = cvd_from_trades(prices, amounts, sides)
        assert list(cvd) == pytest.approx([1.0, -1.0, 0.0])

    def test_cvd_from_trades_empty(self) -> None:
        cvd = cvd_from_trades(pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=float))
        assert len(cvd) == 0

    def test_proxy_still_available(self) -> None:
        close = pd.Series([1.0, 2.0, 1.5])
        vol = pd.Series([10.0, 10.0, 10.0])
        assert float(cvd_proxy(close, vol).iloc[-1]) == 0.0

    @pytest.mark.asyncio
    async def test_fetch_trades_scaffold(self) -> None:
        from quantflow.data.fetcher import DataFetcher

        fetcher = DataFetcher.__new__(DataFetcher)
        fetcher._exchange = MagicMock()
        fetcher._exchange.fetch_trades = AsyncMock(
            return_value=[
                {"timestamp": 1, "price": 10.0, "amount": 1.0, "side": "buy"},
                {"timestamp": 2, "price": 11.0, "amount": 2.0, "side": "sell"},
            ]
        )
        # CALL_TIMEOUT path uses wait_for — mock is coroutine via AsyncMock
        df = await DataFetcher.fetch_trades(fetcher, "BTC/USDT", limit=10)
        assert len(df) == 2
        assert list(df.columns) == ["timestamp", "price", "amount", "side"]
