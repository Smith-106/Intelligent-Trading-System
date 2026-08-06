"""Integration tests for meta backfill CLI (T-s2-03).

Scenarios (plan test_plan):
- download-funding --days 90 persists rows; get_last_meta_timestamp != None
- download-funding --days 180 -> WARNING (3-month window) truncated to 90d
- download-oi --days 180 -> single windowed call (begin+end pair, 8de8b22
  contract — OKX caps coverage by period instead of paginating), deduped save
- download-funding --help exits 0
"""

from __future__ import annotations

import time as time_mod

import pytest
from typer.testing import CliRunner

from quantflow.cli.main import app
from quantflow.common.config import AppConfig
from quantflow.data.store import DataStore

runner = CliRunner()

HOUR_MS = 3_600_000
BASE_TS = 1_700_000_000_000


class FakeOkxExchange:
    """Records call times; serves scripted funding/OI history pages."""

    instances: list[FakeOkxExchange] = []
    #: class-level script consumed by each new instance (tests set this).
    oi_pages_script: list[list[dict]] = []

    def __init__(self, opts: dict | None = None) -> None:
        self.opts = opts
        self.funding_calls: list[int] = []  # since args
        self.oi_call_times: list[float] = []  # monotonic stamps
        self.oi_calls: list[int] = []  # since args
        self.oi_pages: list[list[dict]] = list(FakeOkxExchange.oi_pages_script)
        # Rows must live inside the 90d backfill window or the since filter
        # drops them; anchor to now like a real exchange response.
        now_ms = int(time_mod.time() * 1000)
        start = now_ms - 89 * 86_400_000
        self.funding_rows = [
            {
                "timestamp": start + i * 8 * HOUR_MS,
                "fundingRate": 0.0001,
                "info": {"realizedRate": 0.0001, "fundingTime": start + i * 8 * HOUR_MS},
            }
            for i in range(267)
        ]
        FakeOkxExchange.instances.append(self)

    def set_sandbox_mode(self, flag: bool) -> None:
        pass

    async def load_markets(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def fetchFundingRateHistory(self, symbol, since, limit, params):  # noqa: N802 — ccxt API mirror
        """Mirror the fixed fetcher call: (symbol, since, limit, params).

        The limit is a positional int (8de8b22 fix — the old dict-in-limit
        spelling was rejected with OKX 51000).
        """
        self.funding_calls.append(int(since))
        rows = [r for r in self.funding_rows if r["timestamp"] >= int(since)]
        return rows

    async def fetchOpenInterestHistory(self, symbol, period, since, limit, params):  # noqa: N802 — ccxt API mirror
        self.oi_call_times.append(time_mod.monotonic())
        self.oi_calls.append(int(since))
        idx = len(self.oi_call_times) - 1
        if idx < len(self.oi_pages):
            return self.oi_pages[idx]
        return []


class FakeCcxt:
    okx = FakeOkxExchange

    # market_meta_fetcher._is_retryable references these ccxt module-level
    # exception classes (8de8b22); the double must mirror the real ccxt API.
    class RateLimitExceeded(Exception):  # noqa: N818 — ccxt exception mirror
        pass

    class DDoSProtection(Exception):  # noqa: N818 — ccxt exception mirror
        pass

    class NetworkError(Exception):
        pass


@pytest.fixture(autouse=True)
def _reset_instances():
    FakeOkxExchange.instances = []
    FakeOkxExchange.oi_pages_script = []
    yield
    FakeOkxExchange.instances = []
    FakeOkxExchange.oi_pages_script = []


@pytest.fixture
def patched(tmp_path, monkeypatch):
    cfg = AppConfig()
    cfg.data.parquet_dir = str(tmp_path / "parquet")
    cfg.data.duckdb_path = str(tmp_path / "meta.duckdb")
    cfg.data.sandbox = False
    monkeypatch.setattr("quantflow.cli.main._load", lambda path: cfg)
    monkeypatch.setattr("quantflow.data.market_meta_fetcher.ccxt", FakeCcxt)
    return cfg


def _open_store(cfg: AppConfig) -> DataStore:
    return DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)


class TestDownloadFunding:
    def test_days_90_saves_rows(self, patched):
        result = runner.invoke(app, ["download-funding", "--symbol", "BTC/USDT", "--days", "90"])
        assert result.exit_code == 0, result.output
        assert "WARNING" not in result.output

        store = _open_store(patched)
        try:
            df = store.query_funding_rates("BTC/USDT")
            assert len(df) > 0
            assert store.get_last_meta_timestamp("BTC/USDT", "funding_rate") is not None
        finally:
            store.close()

    def test_days_180_truncates_with_warning(self, patched):
        """DEV-1: OKX serves a 3-month window; --days 180 must WARN + truncate."""
        result = runner.invoke(app, ["download-funding", "--symbol", "BTC/USDT", "--days", "180"])
        assert result.exit_code == 0, result.output
        assert "WARNING" in result.output
        assert "3-month" in result.output

        ex = FakeOkxExchange.instances[-1]
        assert ex.funding_calls, "fetcher never called"
        since = ex.funding_calls[0]
        now_ms = int(time_mod.time() * 1000)
        delta_ms = now_ms - since
        # truncated to 90 days: since == now - 90d (small runtime drift allowed)
        assert 89 * 86_400_000 <= delta_ms <= 90 * 86_400_000 + 60_000

    def test_help_exits_zero(self):
        result = runner.invoke(app, ["download-funding", "--help"])
        assert result.exit_code == 0


class TestDownloadOi:
    def test_days_180_single_windowed_call_saves_rows(self, patched):
        """8de8b22 contract: one windowed call (begin+end pair), not a page
        loop — OKX caps OI coverage by period (1H ~= 30d) and rejects
        begin-only requests with 50030. Rows saved + deduped."""
        page = [
            {
                "timestamp": BASE_TS + i * HOUR_MS,
                # ccxt-normalized rubik contracts fields (info is a raw list).
                "openInterestAmount": 1000.0 + i,
                "openInterestValue": 40_000_000.0 + i,
            }
            for i in range(100)
        ]

        FakeOkxExchange.oi_pages_script = [page]
        result = runner.invoke(
            app,
            ["download-oi", "--symbol", "BTC/USDT", "--days", "180", "--period", "1H"],
        )

        assert result.exit_code == 0, result.output
        ex = FakeOkxExchange.instances[-1]
        assert len(ex.oi_call_times) == 1, "windowed fetch must be a single call"
        since = ex.oi_calls[0]
        now_ms = int(time_mod.time() * 1000)
        delta_ms = now_ms - since
        # since anchored at the requested window start (now - 180d).
        assert 179 * 86_400_000 <= delta_ms <= 180 * 86_400_000 + 60_000

        store = _open_store(patched)
        try:
            df = store.query_open_interest("BTC/USDT")
            assert len(df) == 100
            assert df["timestamp"].is_unique
            assert store.get_last_meta_timestamp("BTC/USDT", "open_interest") is not None
        finally:
            store.close()

    def test_invalid_period_rejected(self, patched):
        result = runner.invoke(
            app, ["download-oi", "--symbol", "BTC/USDT", "--days", "10", "--period", "5m"]
        )
        assert result.exit_code != 0
