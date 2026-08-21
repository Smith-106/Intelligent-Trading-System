"""W20 focused tests: BBO poll loop, cvd_proxy, Elliott WFO smoke."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from quantflow.common.config import AppConfig, ExecutionConfig
from quantflow.indicators.engine import IndicatorEngine
from quantflow.indicators.volume import cvd_proxy
from quantflow.strategy.research.elliott_wave_wfo_smoke import (
    ElliottWfoSmokeReport,
    run_elliott_wfo_smoke,
)


class TestW20aBboPoll:
    def test_config_defaults_off(self) -> None:
        cfg = ExecutionConfig()
        assert cfg.bbo_poll_enabled is False
        assert cfg.bbo_poll_interval_s == 5.0

    @pytest.mark.asyncio
    async def test_bbo_poll_loop_pushes_ticker(self) -> None:
        from quantflow.execution.engine import ExecutionEngine
        from quantflow.execution.paper_gateway import PaperGateway
        from quantflow.strategy.engine import TradingSession

        gw = PaperGateway()
        eng = ExecutionEngine(gateway=gw)
        session = object.__new__(TradingSession)
        session._running = True
        session._execution = eng
        session._ticker_bbo = {}
        session._bbo_source = "ticker"
        session._symbols = ["BTC/USDT"]
        session._bbo_fetcher = None
        session._config = AppConfig(
            execution=ExecutionConfig(
                bbo_poll_enabled=True,
                bbo_poll_interval_s=0.05,
                symbols=["BTC/USDT"],
            )
        )

        class FakeFetcher:
            def __init__(self) -> None:
                self.n = 0

            async def connect(self) -> None:
                return None

            async def disconnect(self) -> None:
                return None

            async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
                self.n += 1
                if self.n >= 2:
                    session._running = False
                return {"bid": 100.0 + self.n, "ask": 101.0 + self.n}

        session._bbo_fetcher = FakeFetcher()
        # bind real methods
        session.push_ticker_bbo = TradingSession.push_ticker_bbo.__get__(session, TradingSession)
        session.set_bbo_source = TradingSession.set_bbo_source.__get__(session, TradingSession)
        session._bbo_poll_loop = TradingSession._bbo_poll_loop.__get__(session, TradingSession)

        await session._bbo_poll_loop()
        assert "BTC/USDT" in session._ticker_bbo
        bid, ask = session._ticker_bbo["BTC/USDT"]
        assert bid > 0 and ask > bid


class TestW20bCvdProxy:
    def test_cvd_proxy_up_down(self) -> None:
        close = pd.Series([10.0, 11.0, 10.0, 12.0])
        vol = pd.Series([100.0, 100.0, 100.0, 100.0])
        cvd = cvd_proxy(close, vol)
        # bar1 +100, bar2 -100 → 0, bar3 +100 → 100
        assert float(cvd.iloc[0]) == 0.0
        assert float(cvd.iloc[1]) == 100.0
        assert float(cvd.iloc[2]) == 0.0
        assert float(cvd.iloc[3]) == 100.0

    def test_engine_wires_cvd_proxy(self) -> None:
        rng = np.random.default_rng(0)
        n = 50
        close = 100 + np.cumsum(rng.normal(0, 1, n))
        df = pd.DataFrame(
            {
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": rng.uniform(10, 20, n),
            }
        )
        eng = IndicatorEngine()
        assert "cvd_proxy" in eng.list_available()
        out = eng.batch_calculate(df)
        assert "cvd_proxy" in out.columns
        sel = eng.compute_all(df, indicator_names=["cvd_proxy"])
        assert "cvd_proxy" in sel.columns
        assert "rsi_14" not in sel.columns


class TestW20cElliottWfoSmoke:
    def test_synthetic_wfo_smoke_report_shape(self) -> None:
        report = run_elliott_wfo_smoke(n_bars=400, n_windows=3, oos_ratio=0.3)
        assert isinstance(report, ElliottWfoSmokeReport)
        assert report.is_smoke is True
        assert report.promotion_eligible is False
        assert report.execution_path == "vectorized_smoke"
        assert report.n_windows == 3
        assert len(report.windows) == 3
        d = report.to_dict()
        assert d["promotion_eligible"] is False
        assert "W20c" in d["notes"][0] or "smoke" in d["notes"][0].lower()

    def test_smoke_with_prebuilt_df(self) -> None:
        from quantflow.strategy.research.elliott_wave_backtest import generate_synthetic_wave_data

        df = generate_synthetic_wave_data(n_bars=300, seed=1)
        report = run_elliott_wfo_smoke(df=df, n_windows=2)
        assert report.n_bars == 300
        assert report.data_source == "synthetic"
