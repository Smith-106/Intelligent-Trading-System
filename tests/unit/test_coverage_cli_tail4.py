"""CLI tail4: final cli/main.py branch gaps."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from typer.testing import CliRunner

from quantflow.cli import main as cli_main
from quantflow.cli.main import app

runner = CliRunner()


def _df(n: int = 100) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "datetime": idx,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000.0,
        }
    )


def _df_no_datetime(n: int = 100) -> pd.DataFrame:
    df = _df(n)
    return df.drop(columns=["datetime"])


# ------------------------------------------------------------------ console
class TestMakeConsoleTail:
    def test_make_console_no_reconfigure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """L81: stream without reconfigure → skip."""

        class NoReconfig:
            pass

        monkeypatch.setattr(sys, "stdout", NoReconfig())
        monkeypatch.setattr(sys, "stderr", NoReconfig())
        console = cli_main._make_console()
        assert console is not None


# ------------------------------------------------------------------ download
class TestDownloadTail4:
    def test_download_no_date_range(self) -> None:
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock()
        fake_fetcher.fetch_ohlcv = AsyncMock(return_value=_df())
        fake_fetcher.disconnect = AsyncMock()
        fake_store = MagicMock()
        fake_store.save = MagicMock()
        fake_store.get_date_range = MagicMock(return_value=None)
        fake_store.close = MagicMock()
        with (
            patch("quantflow.data.fetcher.DataFetcher", return_value=fake_fetcher),
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.data.cleaner.clean_ohlcv", side_effect=lambda df: df),
        ):
            result = runner.invoke(app, ["download", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "Saved" in result.output


class TestDownloadFundingTail4:
    def test_funding_no_last_ts(self) -> None:
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock()
        fake_fetcher.fetch_funding_rate_history = AsyncMock(return_value=_df())
        fake_fetcher.disconnect = AsyncMock()
        fake_store = MagicMock()
        fake_store.save_funding_rates = MagicMock()
        fake_store.get_last_meta_timestamp = MagicMock(return_value=None)
        fake_store.close = MagicMock()
        with (
            patch(
                "quantflow.data.market_meta_fetcher.MarketMetaFetcher", return_value=fake_fetcher
            ),
            patch("quantflow.data.store.DataStore", return_value=fake_store),
        ):
            result = runner.invoke(app, ["download-funding", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "funding rows" in result.output


class TestDownloadOiTail4:
    def test_oi_no_last_ts(self) -> None:
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock()
        fake_fetcher.fetch_open_interest_history = AsyncMock(return_value=_df())
        fake_fetcher.disconnect = AsyncMock()
        fake_store = MagicMock()
        fake_store.save_open_interest = MagicMock()
        fake_store.get_last_meta_timestamp = MagicMock(return_value=None)
        fake_store.close = MagicMock()
        with (
            patch(
                "quantflow.data.market_meta_fetcher.MarketMetaFetcher", return_value=fake_fetcher
            ),
            patch("quantflow.data.store.DataStore", return_value=fake_store),
        ):
            result = runner.invoke(app, ["download-oi", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "OI rows" in result.output


# ------------------------------------------------- research/optimize/validate
class TestNoDatetimeTail:
    def test_research_no_datetime(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df_no_datetime())
        fake_store.close = MagicMock()
        fake_engine = MagicMock()
        fake_engine.run_backtest = MagicMock(return_value=SimpleNamespace())
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.research.backtest.BacktestEngine", return_value=fake_engine),
            patch("quantflow.strategy.research.report.generate_report", return_value="# R"),
        ):
            result = runner.invoke(app, ["research", "--strategy", "trend_following"])
        assert result.exit_code == 0

    def test_optimize_no_datetime(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df_no_datetime())
        fake_store.close = MagicMock()
        fake_opt = MagicMock()
        fake_opt.optimize = MagicMock(
            return_value={
                "method": "bayesian",
                "objective": "sharpe",
                "best_value": 1.0,
                "n_trials": 1,
                "best_params": {},
            }
        )
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.research.optimizer.StrategyOptimizer", return_value=fake_opt),
        ):
            result = runner.invoke(app, ["optimize", "--strategy", "trend_following"])
        assert result.exit_code == 0

    def test_validate_no_datetime(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df_no_datetime())
        fake_store.close = MagicMock()
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch(
                "quantflow.strategy.validation.cpcv.cpcv_backtest",
                return_value={
                    "n_paths": 4,
                    "pbo": 0.1,
                    "oos_efficiency": 0.6,
                    "oos_sharpe_mean": 0.6,
                    "oos_sharpe_std": 0.1,
                    "oos_sharpe_min": 0.5,
                    "passed": True,
                },
            ),
        ):
            result = runner.invoke(app, ["validate", "--method", "cpcv"])
        assert result.exit_code == 0

    def test_validate_unknown_method(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        with patch("quantflow.data.store.DataStore", return_value=fake_store):
            result = runner.invoke(app, ["validate", "--method", "bogus"])
        assert result.exit_code == 0


# ------------------------------------------------------------ display helpers
class TestDisplayHelpersTail4:
    def test_display_gate_no_reason(self) -> None:
        cli_main._display_gate({"decision": "GO", "checks": {}})

    def test_display_causal_preflight_no_lookahead(self) -> None:
        fake = MagicMock()
        fake.passed = True
        fake.summary = MagicMock(return_value="s")
        fake.severity_counts = {}
        fake.lookahead = None
        fake.negative_shifts = []
        fake.notes = []
        cli_main._display_causal_preflight(fake)

    def test_display_causal_preflight_fail_no_shifts(self) -> None:
        fake = MagicMock()
        fake.passed = False
        fake.summary = MagicMock(return_value="s")
        fake.severity_counts = {}
        fake.lookahead = None
        fake.negative_shifts = []
        fake.notes = []
        cli_main._display_causal_preflight(fake)


# ------------------------------------------------------------------ ai train
class TestAiTrainTail4:
    def test_ai_train_no_datetime_no_fj(self) -> None:
        """L1287-1290 / L1294-1297 / L1299-1320: no datetime col, no latest.json."""
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df_no_datetime())
        fake_store.close = MagicMock()
        fake_pipe = MagicMock()
        fake_report = SimpleNamespace(
            features_hash="abc",
            decision="GO",
            reason="ok",
            n_samples=5,
            model_cls="X",
            feature_importance={},
            to_dict=lambda: {"features_hash": "abc", "decision": "GO"},
        )
        fake_pipe.train = MagicMock(return_value=fake_report)
        fake_fs = MagicMock()
        fake_fs.compute_features = MagicMock(
            return_value=_df().set_index("datetime")[["close"]].rename(columns={"close": "f1"})
        )
        raw_no_dt = _df_no_datetime()
        raw_no_dt["timestamp"] = [1700000000000 + i * 86400000 for i in range(len(raw_no_dt))]
        fake_store.query = MagicMock(return_value=raw_no_dt)
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.ai_training.AITrainingPipeline", return_value=fake_pipe),
            patch("quantflow.indicators.engine.IndicatorEngine", return_value=MagicMock()),
            patch("quantflow.data.feature_store.FeatureStore", return_value=fake_fs),
            patch("pathlib.Path.mkdir"),
        ):
            result = runner.invoke(app, ["ai", "train", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "IndicatorEngine features" in result.output

    def test_ai_train_go_with_fee_slip_grid(self, tmp_path: pytest.TempPathFactory) -> None:
        """L1369: GO + fee_slip_grid present → skip warning branch."""
        fj = tmp_path / "factors.json"
        fj.write_text(json.dumps({"factors": [{"name": "f1", "formula": "x"}]}), encoding="utf-8")
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        fake_pipe = MagicMock()
        fake_report = SimpleNamespace(
            features_hash="abc",
            decision="GO",
            reason="ok",
            n_samples=5,
            model_cls="X",
            feature_importance={},
            to_dict=lambda: {
                "features_hash": "abc",
                "decision": "GO",
                "fee_slip_grid": {"zero_cost": 1.0},
            },
        )
        fake_pipe.train = MagicMock(return_value=fake_report)
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.ai_training.AITrainingPipeline", return_value=fake_pipe),
            patch(
                "quantflow.strategy.rd_agent.load_discovered_factors",
                return_value=[SimpleNamespace(name="f1", formula="x")],
            ),
            patch(
                "quantflow.strategy.rd_agent.materialize_factor_frame",
                return_value=_df().set_index("datetime")[["close"]].rename(columns={"close": "f1"}),
            ),
            patch("pathlib.Path.mkdir"),
        ):
            result = runner.invoke(
                app,
                [
                    "ai",
                    "train",
                    "--symbol",
                    "BTC/USDT",
                    "--factors-json",
                    str(fj),
                ],
            )
        assert result.exit_code == 0


# ------------------------------------------------------------ ai bypass + kol
class TestAiBypassTail4:
    def test_ai_bypass_no_datetime(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df_no_datetime())
        fake_store.close = MagicMock()
        fake_result = SimpleNamespace(
            decision="GO",
            model_id="m1",
            reason="ok",
            n_selected=1,
            n_factors=2,
            report_path="r.json",
            registered_status="paper",
            ai_lane="bypass",
            ai_live_blocked=True,
            notes=[],
        )
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch(
                "quantflow.strategy.ai_validation_bypass.run_ai_validation_bypass",
                return_value=fake_result,
            ),
        ):
            result = runner.invoke(app, ["ai", "bypass", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "Validation gate" in result.output


class TestKolIngestTail4:
    def test_kol_poll_no_channel(self) -> None:
        with patch("scripts.kol_discord_ingest.main", return_value=0):
            result = runner.invoke(app, ["kol-ingest", "poll"])
        assert result.exit_code == 0
        assert "kol-ingest poll done" in result.output
