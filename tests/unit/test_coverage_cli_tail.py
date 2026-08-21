"""CLI tail coverage: cli/main.py commands + display helpers to 100/100."""

from __future__ import annotations

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


def _close_df(n: int = 100) -> pd.DataFrame:
    df = _df(n)
    return df.set_index("datetime")


# ------------------------------------------------------------------ download
class TestDownloadTail:
    def test_download_happy(self) -> None:
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock()
        fake_fetcher.fetch_ohlcv = AsyncMock(return_value=_df())
        fake_fetcher.disconnect = AsyncMock()
        fake_store = MagicMock()
        fake_store.save = MagicMock()
        fake_store.get_date_range = MagicMock(return_value=(1704067200000, 1717718400000))
        fake_store.close = MagicMock()
        with (
            patch("quantflow.data.fetcher.DataFetcher", return_value=fake_fetcher),
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.data.cleaner.clean_ohlcv", side_effect=lambda df: df),
        ):
            result = runner.invoke(app, ["download", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "Saved" in result.output

    def test_download_empty(self) -> None:
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock()
        fake_fetcher.fetch_ohlcv = AsyncMock(return_value=pd.DataFrame())
        fake_fetcher.disconnect = AsyncMock()
        fake_store = MagicMock()
        fake_store.close = MagicMock()
        with (
            patch("quantflow.data.fetcher.DataFetcher", return_value=fake_fetcher),
            patch("quantflow.data.store.DataStore", return_value=fake_store),
        ):
            result = runner.invoke(app, ["download", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "No data fetched" in result.output

    def test_download_exception(self) -> None:
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock(side_effect=RuntimeError("boom"))
        fake_fetcher.disconnect = AsyncMock()
        fake_store = MagicMock()
        fake_store.close = MagicMock()
        with (
            patch("quantflow.data.fetcher.DataFetcher", return_value=fake_fetcher),
            patch("quantflow.data.store.DataStore", return_value=fake_store),
        ):
            result = runner.invoke(app, ["download", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "ERR" in result.output


# ------------------------------------------------------------ download_funding
class TestDownloadFundingTail:
    def test_funding_happy(self) -> None:
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock()
        fake_fetcher.fetch_funding_rate_history = AsyncMock(return_value=_df())
        fake_fetcher.disconnect = AsyncMock()
        fake_store = MagicMock()
        fake_store.save_funding_rates = MagicMock()
        fake_store.get_last_meta_timestamp = MagicMock(return_value=1704067200000)
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

    def test_funding_days_truncated_and_empty(self) -> None:
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock()
        fake_fetcher.fetch_funding_rate_history = AsyncMock(return_value=pd.DataFrame())
        fake_fetcher.disconnect = AsyncMock()
        fake_store = MagicMock()
        fake_store.close = MagicMock()
        with (
            patch(
                "quantflow.data.market_meta_fetcher.MarketMetaFetcher", return_value=fake_fetcher
            ),
            patch("quantflow.data.store.DataStore", return_value=fake_store),
        ):
            result = runner.invoke(
                app, ["download-funding", "--symbol", "BTC/USDT", "--days", "200"]
            )
        assert result.exit_code == 0
        assert "truncating" in result.output
        assert "No funding data" in result.output

    def test_funding_exception(self) -> None:
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock(side_effect=RuntimeError("boom"))
        fake_fetcher.disconnect = AsyncMock()
        fake_store = MagicMock()
        fake_store.close = MagicMock()
        with (
            patch(
                "quantflow.data.market_meta_fetcher.MarketMetaFetcher", return_value=fake_fetcher
            ),
            patch("quantflow.data.store.DataStore", return_value=fake_store),
        ):
            result = runner.invoke(app, ["download-funding", "--symbol", "BTC/USDT"])
        assert result.exit_code == 1


# ------------------------------------------------------------------ download_oi
class TestDownloadOiTail:
    def test_oi_happy(self) -> None:
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock()
        fake_fetcher.fetch_open_interest_history = AsyncMock(return_value=_df())
        fake_fetcher.disconnect = AsyncMock()
        fake_store = MagicMock()
        fake_store.save_open_interest = MagicMock()
        fake_store.get_last_meta_timestamp = MagicMock(return_value=1704067200000)
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

    def test_oi_bad_period(self) -> None:
        result = runner.invoke(app, ["download-oi", "--period", "2H"])
        assert result.exit_code != 0

    def test_oi_empty(self) -> None:
        fake_fetcher = MagicMock()
        fake_fetcher.connect = AsyncMock()
        fake_fetcher.fetch_open_interest_history = AsyncMock(return_value=pd.DataFrame())
        fake_fetcher.disconnect = AsyncMock()
        fake_store = MagicMock()
        fake_store.close = MagicMock()
        with (
            patch(
                "quantflow.data.market_meta_fetcher.MarketMetaFetcher", return_value=fake_fetcher
            ),
            patch("quantflow.data.store.DataStore", return_value=fake_store),
        ):
            result = runner.invoke(app, ["download-oi", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "No OI data" in result.output


# -------------------------------------------------------------------- research
class TestResearchTail:
    def test_research_happy(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        fake_engine = MagicMock()
        fake_engine.run_backtest = MagicMock(return_value=SimpleNamespace())
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.research.backtest.BacktestEngine", return_value=fake_engine),
            patch("quantflow.strategy.research.report.generate_report", return_value="# Report"),
        ):
            result = runner.invoke(app, ["research", "--strategy", "trend_following"])
        assert result.exit_code == 0
        assert "Report" in result.output

    def test_research_empty(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=pd.DataFrame())
        fake_store.close = MagicMock()
        with patch("quantflow.data.store.DataStore", return_value=fake_store):
            result = runner.invoke(app, ["research", "--strategy", "trend_following"])
        assert result.exit_code == 0
        assert "No data" in result.output

    def test_research_unknown_strategy(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        with patch("quantflow.data.store.DataStore", return_value=fake_store):
            result = runner.invoke(app, ["research", "--strategy", "nope"])
        assert result.exit_code == 0
        assert "Unknown strategy" in result.output


# -------------------------------------------------------------------- optimize
class TestOptimizeTail:
    def test_optimize_happy(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        fake_opt = MagicMock()
        fake_opt.optimize = MagicMock(
            return_value={
                "method": "bayesian",
                "objective": "sharpe",
                "best_value": 1.5,
                "n_trials": 5,
                "best_params": {"fast": 10},
            }
        )
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.research.optimizer.StrategyOptimizer", return_value=fake_opt),
        ):
            result = runner.invoke(app, ["optimize", "--strategy", "trend_following"])
        assert result.exit_code == 0
        assert "Optimization Results" in result.output

    def test_optimize_empty(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=pd.DataFrame())
        fake_store.close = MagicMock()
        with patch("quantflow.data.store.DataStore", return_value=fake_store):
            result = runner.invoke(app, ["optimize", "--strategy", "trend_following"])
        assert result.exit_code == 0
        assert "No data" in result.output

    def test_optimize_unknown_strategy(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        with patch("quantflow.data.store.DataStore", return_value=fake_store):
            result = runner.invoke(app, ["optimize", "--strategy", "nope"])
        assert result.exit_code == 0
        assert "Unknown strategy" in result.output

    def test_optimize_exception(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        fake_opt = MagicMock()
        fake_opt.optimize = MagicMock(side_effect=RuntimeError("boom"))
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.research.optimizer.StrategyOptimizer", return_value=fake_opt),
        ):
            result = runner.invoke(app, ["optimize", "--strategy", "trend_following"])
        assert result.exit_code == 0
        assert "优化失败" in result.output


# -------------------------------------------------------------------- validate
class TestValidateTail:
    def _store(self) -> MagicMock:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        return fake_store

    def test_validate_unknown_strategy(self) -> None:
        result = runner.invoke(app, ["validate", "--strategy", "nope"])
        assert result.exit_code == 0
        assert "Unknown strategy" in result.output

    def test_validate_causal_preflight(self) -> None:
        fake_report = MagicMock()
        fake_report.summary = MagicMock(return_value="preflight summary")
        fake_report.findings = []
        fake_report.notes = []
        with patch(
            "quantflow.strategy.validation.causal_preflight.run_causal_preflight",
            return_value=fake_report,
        ):
            result = runner.invoke(app, ["validate", "--method", "causal_preflight"])
        assert result.exit_code == 0

    def test_validate_lookahead(self) -> None:
        fake_report = MagicMock()
        fake_report.strategy = "s"
        fake_report.scanned_methods = ["generate_signals"]
        fake_report.source_path = None
        fake_report.findings = []
        with patch(
            "quantflow.strategy.validation.lookahead.scan_strategy", return_value=fake_report
        ):
            result = runner.invoke(app, ["validate", "--method", "lookahead"])
        assert result.exit_code == 0

    def test_validate_recursive(self) -> None:
        fake_report = MagicMock()
        fake_report.strategy = "s"
        fake_report.source_path = None
        fake_report.indicator_deps = {}
        fake_report.cycles = []
        with patch(
            "quantflow.strategy.validation.recursive.scan_recursive", return_value=fake_report
        ):
            result = runner.invoke(app, ["validate", "--method", "recursive"])
        assert result.exit_code == 0

    def test_validate_empty_data(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=pd.DataFrame())
        fake_store.close = MagicMock()
        with patch("quantflow.data.store.DataStore", return_value=fake_store):
            result = runner.invoke(app, ["validate", "--method", "cpcv"])
        assert result.exit_code == 0
        assert "No data" in result.output

    def test_validate_cpcv(self) -> None:
        fake_store = self._store()
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
        assert "CPCV" in result.output

    def test_validate_dsr(self) -> None:
        fake_store = self._store()
        fake_bt = SimpleNamespace(sharpe_ratio=1.2)
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.research.backtest.BacktestEngine") as bt_cls,
            patch(
                "quantflow.strategy.validation.dsr.deflated_sharpe_ratio",
                return_value={
                    "dsr": 0.99,
                    "observed_sharpe": 1.2,
                    "expected_max_sharpe": 1.5,
                    "n_trials": 100,
                    "passed": True,
                },
            ),
        ):
            bt_cls.return_value.run_backtest = MagicMock(return_value=fake_bt)
            result = runner.invoke(app, ["validate", "--method", "dsr"])
        assert result.exit_code == 0
        assert "DSR" in result.output

    def test_validate_wfo(self) -> None:
        fake_store = self._store()
        fake_res = {
            "is_sharpe_mean": 1.0,
            "oos_sharpe_mean": 0.5,
            "oos_efficiency": 0.6,
            "passed": True,
        }
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch(
                "quantflow.strategy.validation.wfo.walk_forward_optimization",
                return_value=fake_res,
            ),
        ):
            result = runner.invoke(app, ["validate", "--method", "wfo"])
        assert result.exit_code == 0
        assert "Walk-Forward" in result.output

    def test_validate_pbo(self) -> None:
        fake_store = self._store()
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch(
                "quantflow.strategy.validation.pbo.probability_of_overfitting",
                return_value={
                    "pbo": 0.2,
                    "overfit_paths": 1,
                    "total_paths": 8,
                    "is_return_mean": 0.1,
                    "oos_return_mean": 0.05,
                    "rank_correlation": 0.8,
                    "passed": True,
                },
            ),
        ):
            result = runner.invoke(app, ["validate", "--method", "pbo"])
        assert result.exit_code == 0
        assert "PBO" in result.output

    def test_validate_gate(self) -> None:
        fake_store = self._store()
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch(
                "quantflow.strategy.validation.gate.validation_gate",
                return_value={
                    "decision": "GO",
                    "reason": "",
                    "checks": {
                        "cpcv": {
                            "passed": True,
                            "signal_quality": {"avg_win_rate": 0.5},
                        }
                    },
                },
            ),
        ):
            result = runner.invoke(app, ["validate", "--method", "gate"])
        assert result.exit_code == 0
        assert "VALIDATION GATE" in result.output

    def test_validate_stress(self) -> None:
        fake_store = self._store()
        fake_bt = SimpleNamespace(
            trade_returns=pd.Series([0.01, -0.02, 0.03]),
            equity_curve=pd.Series([100.0, 101.0, 99.0]),
        )
        fake_mc = SimpleNamespace(
            method="trade",
            n_paths=1000,
            observed_max_drawdown=0.1,
            p5_max_drawdown=0.2,
            p50_max_drawdown=0.12,
            observed_terminal_return=0.05,
            p5_terminal_return=-0.1,
            p95_terminal_return=0.2,
            prob_worse_drawdown=0.3,
        )
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.research.backtest.BacktestEngine") as bt_cls,
            patch(
                "quantflow.strategy.validation.monte_carlo.monte_carlo_stress",
                return_value=[fake_mc],
            ),
        ):
            bt_cls.return_value.run_backtest = MagicMock(return_value=fake_bt)
            result = runner.invoke(app, ["validate", "--method", "stress"])
        assert result.exit_code == 0

    def test_validate_exception(self) -> None:
        fake_store = self._store()
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch(
                "quantflow.strategy.validation.cpcv.cpcv_backtest", side_effect=RuntimeError("boom")
            ),
        ):
            result = runner.invoke(app, ["validate", "--method", "cpcv"])
        assert result.exit_code == 0
        assert "验证失败" in result.output


# ------------------------------------------------------------------------- run
class TestRunTail:
    def test_run_happy(self) -> None:
        fake_session = MagicMock()
        fake_session.start = AsyncMock()
        fake_session.run_data_loop = AsyncMock()
        fake_session.stop = AsyncMock()
        with (
            patch("quantflow.strategy.engine.TradingSession", return_value=fake_session),
            patch("quantflow.monitoring.sink.create_default_sink", return_value=MagicMock()),
        ):
            result = runner.invoke(app, ["run", "--mode", "paper", "--strategy", "trend_following"])
        assert result.exit_code == 0
        assert "Session started" in result.output

    def test_run_unknown_strategy(self) -> None:
        result = runner.invoke(app, ["run", "--strategy", "nope"])
        assert result.exit_code == 0
        assert "Unknown strategy" in result.output

    def test_run_exception(self) -> None:
        fake_session = MagicMock()
        fake_session.start = AsyncMock(side_effect=RuntimeError("boom"))
        fake_session.stop = AsyncMock()
        with (
            patch("quantflow.strategy.engine.TradingSession", return_value=fake_session),
            patch("quantflow.monitoring.sink.create_default_sink", return_value=MagicMock()),
        ):
            result = runner.invoke(app, ["run", "--mode", "paper", "--strategy", "trend_following"])
        assert result.exit_code == 0
        assert "运行失败" in result.output


# --------------------------------------------------------------------- station
class TestStationTail:
    def test_station_launches(self) -> None:
        with patch("quantflow.web.app.run_station") as mock_run:
            result = runner.invoke(app, ["station", "--port", "8090"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with(host="127.0.0.1", port=8090)


# -------------------------------------------------------------------------- ai
class TestAiTail:
    def test_ai_rdagent(self) -> None:
        with patch("quantflow.cli.main._ai_factor_mining") as mock_mining:
            result = runner.invoke(app, ["ai", "rdagent", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        mock_mining.assert_called_once()

    def test_ai_train(self) -> None:
        with patch("quantflow.cli.main._ai_train") as mock_train:
            result = runner.invoke(app, ["ai", "train", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        mock_train.assert_called_once()

    def test_ai_register(self) -> None:
        with patch("quantflow.cli.main._ai_register") as mock_register:
            result = runner.invoke(app, ["ai", "register", "--model-id", "m1"])
        assert result.exit_code == 0
        mock_register.assert_called_once()

    def test_ai_bypass(self) -> None:
        with patch("quantflow.cli.main._ai_validation_bypass") as mock_bypass:
            result = runner.invoke(app, ["ai", "bypass", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        mock_bypass.assert_called_once()

    def test_ai_unknown_action(self) -> None:
        result = runner.invoke(app, ["ai", "bogus"])
        assert result.exit_code == 0
        assert "Unknown AI action" in result.output


# ------------------------------------------------------------ display helpers
class TestDisplayHelpersTail:
    def test_display_cpcv(self) -> None:
        cli_main._display_cpcv(
            {
                "n_paths": 4,
                "pbo": 0.1,
                "oos_efficiency": 0.6,
                "oos_sharpe_mean": 0.6,
                "oos_sharpe_std": 0.1,
                "oos_sharpe_min": 0.5,
                "passed": True,
            }
        )

    def test_display_dsr(self) -> None:
        cli_main._display_dsr(
            {
                "dsr": 0.99,
                "observed_sharpe": 1.2,
                "expected_max_sharpe": 1.5,
                "n_trials": 100,
                "passed": True,
            }
        )

    def test_display_wfo(self) -> None:
        cli_main._display_wfo(
            {"is_sharpe_mean": 1.0, "oos_sharpe_mean": 0.5, "oos_efficiency": 0.6, "passed": True},
            {"is_sharpe_mean": 0.8, "oos_sharpe_mean": 0.3, "oos_efficiency": 0.4, "passed": False},
        )

    def test_display_pbo(self) -> None:
        cli_main._display_pbo(
            {
                "pbo": 0.2,
                "overfit_paths": 1,
                "total_paths": 8,
                "is_return_mean": 0.1,
                "oos_return_mean": 0.05,
                "rank_correlation": 0.8,
                "passed": True,
            }
        )

    def test_display_gate(self) -> None:
        cli_main._display_gate(
            {
                "decision": "GO",
                "reason": "",
                "checks": {
                    "cpcv": {
                        "passed": True,
                        "signal_quality": {"avg_win_rate": 0.5},
                    }
                },
            }
        )

    def test_display_causal_preflight(self) -> None:
        fake = MagicMock()
        fake.summary = MagicMock(return_value="summary")
        fake.findings = []
        fake.notes = []
        cli_main._display_causal_preflight(fake)

    def test_display_lookahead(self) -> None:
        fake = MagicMock()
        fake.strategy = "s"
        fake.scanned_methods = ["generate_signals"]
        fake.source_path = None
        fake.findings = []
        cli_main._display_lookahead(fake)

    def test_display_recursive(self) -> None:
        fake = MagicMock()
        fake.strategy = "s"
        fake.source_path = None
        fake.indicator_deps = {}
        fake.cycles = []
        cli_main._display_recursive(fake)

    def test_display_monte_carlo(self) -> None:
        cli_main._display_monte_carlo(
            SimpleNamespace(
                method="trade",
                n_paths=1000,
                observed_max_drawdown=0.1,
                p5_max_drawdown=0.2,
                p50_max_drawdown=0.12,
                observed_terminal_return=0.05,
                p5_terminal_return=-0.1,
                p95_terminal_return=0.2,
                prob_worse_drawdown=0.3,
            )
        )

    def test_signal_quality_helpers(self) -> None:
        from rich.table import Table

        q = {
            "precision": 0.5,
            "recall": 0.4,
            "hit_rate": 0.6,
            "brier_score": 0.2,
            "oos_sharpe": 0.7,
        }
        assert cli_main._signal_quality_summary({"signal_quality": q})
        table = Table()
        cli_main._add_signal_quality_rows(table, q)
        assert cli_main._format_signal_quality(q, "precision")


# ------------------------------------------------------------- misc functions
class TestMiscTail:
    def test_load_gateway_config_paper(self) -> None:
        cfg = cli_main._load_gateway_config_from_env("paper", sandbox=False)
        assert cfg == {"sandbox": False}

    def test_load_gateway_config_missing_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OKX_API_KEY", raising=False)
        monkeypatch.delenv("OKX_SECRET", raising=False)
        monkeypatch.delenv("OKX_PASSPHRASE", raising=False)
        with pytest.raises(Exception, match="Missing required environment variables"):
            cli_main._load_gateway_config_from_env("live", sandbox=False)

    def test_load_gateway_config_live(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OKX_API_KEY", "k")
        monkeypatch.setenv("OKX_SECRET", "s")
        monkeypatch.setenv("OKX_PASSPHRASE", "p")
        cfg = cli_main._load_gateway_config_from_env("live", sandbox=True)
        assert cfg["api_key"] == "k"
        assert cfg["sandbox"] is True

    def test_date_to_ms(self) -> None:
        assert cli_main._date_to_ms("2024-01-01") > 0

    def test_get_strategy_factories_and_specs(self) -> None:
        assert "trend_following" in cli_main._get_strategy_factories()
        assert "trend_following" in cli_main._get_strategy_specs()
