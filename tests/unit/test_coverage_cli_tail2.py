"""CLI tail2: remaining cli/main.py + __init__ + benchmark branches."""

from __future__ import annotations

import json
from pathlib import Path
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


# -------------------------------------------------------------------- optimize
class TestOptimizeTail2:
    def test_optimize_signal_fn_invoked(self) -> None:
        """L419-422: _signal_fn body executes via optimize side_effect."""
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        fake_opt = MagicMock()

        def _fake_optimize(close, signal_fn, param_space, **kw):
            signal_fn(close)
            return {
                "method": "bayesian",
                "objective": "sharpe",
                "best_value": 1.0,
                "n_trials": 1,
                "best_params": {},
            }

        fake_opt.optimize = MagicMock(side_effect=_fake_optimize)
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.research.optimizer.StrategyOptimizer", return_value=fake_opt),
        ):
            result = runner.invoke(app, ["optimize", "--strategy", "trend_following"])
        assert result.exit_code == 0
        assert "Optimization Results" in result.output


# ----------------------------------------------------------------- benchmark
class TestBenchmarkTail2:
    def test_benchmark_failures_non_json(self) -> None:
        """L1115: failures printed in table mode + exit 1."""
        result = runner.invoke(
            app,
            [
                "benchmark",
                "--bars",
                "80",
                "--trials",
                "1",
                "--wfo-windows",
                "1",
                "--skip-subprocess",
                "--min-bars-per-sec",
                "1000000000",
            ],
        )
        assert result.exit_code == 1
        assert "Benchmark threshold failed" in result.output


# ------------------------------------------------------------------ __init__
class TestCliInit:
    def test_getattr_app(self) -> None:
        import quantflow.cli as cli_pkg

        assert cli_pkg.app is app

    def test_getattr_unknown_raises(self) -> None:
        import quantflow.cli as cli_pkg

        with pytest.raises(AttributeError, match="has no attribute"):
            _ = cli_pkg.nope


# ------------------------------------------------------------------ download_oi
class TestDownloadOiTail2:
    def test_oi_exception(self) -> None:
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
            result = runner.invoke(app, ["download-oi", "--symbol", "BTC/USDT"])
        assert result.exit_code == 1


# -------------------------------------------------------------------- validate
class TestValidateTail2:
    def test_validate_stress_empty_results(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        fake_bt = SimpleNamespace(
            trade_returns=pd.Series([0.01]),
            equity_curve=pd.Series([100.0, 101.0]),
        )
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.research.backtest.BacktestEngine") as bt_cls,
            patch("quantflow.strategy.validation.monte_carlo.monte_carlo_stress", return_value=[]),
        ):
            bt_cls.return_value.run_backtest = MagicMock(return_value=fake_bt)
            result = runner.invoke(app, ["validate", "--method", "stress"])
        assert result.exit_code == 0
        assert "Insufficient" in result.output


# ------------------------------------------------------------------------- run
class TestRunTail2:
    def test_run_keyboard_interrupt(self) -> None:
        fake_session = MagicMock()
        fake_session.start = AsyncMock()
        fake_session.run_data_loop = AsyncMock(side_effect=KeyboardInterrupt())
        fake_session.stop = AsyncMock()
        with (
            patch("quantflow.strategy.engine.TradingSession", return_value=fake_session),
            patch("quantflow.monitoring.sink.create_default_sink", return_value=MagicMock()),
        ):
            result = runner.invoke(app, ["run", "--mode", "paper", "--strategy", "trend_following"])
        assert result.exit_code == 0
        assert "Stopping session" in result.output


# ------------------------------------------------------------ display helpers
class TestDisplayHelpersTail2:
    def test_display_causal_preflight_findings(self) -> None:
        fake = MagicMock()
        fake.passed = False
        fake.summary = MagicMock(return_value="summary")
        fake.findings = [{"source": "negative_shift", "detail": {"line": 1}, "severity": "high"}]
        fake.negative_shifts = [{"where": "m", "line": 1, "snippet": "s"}]
        fake.notes = ["note1"]
        cli_main._display_causal_preflight(fake)

    def test_display_lookahead_findings(self) -> None:
        fake = MagicMock()
        fake.passed = False
        fake.strategy = "s"
        fake.scanned_methods = ["generate_signals"]
        fake.source_path = "src.py"
        fake.findings = [SimpleNamespace(severity="high", line=1, pattern="p", snippet="sn")]
        cli_main._display_lookahead(fake)

    def test_display_recursive_cycles(self) -> None:
        fake = MagicMock()
        fake.passed = False
        fake.strategy = "s"
        fake.source_path = "src.py"
        fake.indicator_deps = {"m": ["a"]}
        fake.cycles = [["a", "b"]]
        cli_main._display_recursive(fake)


# ------------------------------------------------------------------ ai actions
class TestAiActionsTail:
    def test_ai_factor_mining_happy(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        fake_runner = MagicMock()
        fake_runner.check_available = MagicMock(return_value=(True, "ok"))
        fake_runner.config = SimpleNamespace(ic_threshold=0.03, min_selected=1)
        fake_runner.discover_factors = MagicMock(
            return_value=[
                SimpleNamespace(name="f1", ic=0.1, rank_ic=0.05, selected=True),
                SimpleNamespace(name="f2", ic=0.01, rank_ic=0.0, selected=False),
            ]
        )
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.rd_agent.RDAgentRunner", return_value=fake_runner),
            patch(
                "quantflow.strategy.rd_agent.save_discovered_factors",
                return_value=Path("data/ai_factors/BTC_USDT/latest.json"),
            ),
        ):
            result = runner.invoke(app, ["ai", "rdagent", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "factors passed" in result.output

    def test_ai_factor_mining_no_qlib(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
        fake_store.close = MagicMock()
        fake_runner = MagicMock()
        fake_runner.check_available = MagicMock(return_value=(False, "qlib missing"))
        fake_runner.config = SimpleNamespace(ic_threshold=0.03, min_selected=1)
        fake_runner.discover_factors = MagicMock(return_value=[])
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.rd_agent.RDAgentRunner", return_value=fake_runner),
            patch(
                "quantflow.strategy.rd_agent.save_discovered_factors",
                return_value=Path("data/ai_factors/BTC_USDT/latest.json"),
            ),
        ):
            result = runner.invoke(app, ["ai", "rdagent", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "Qlib not installed" in result.output

    def test_ai_factor_mining_empty(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=pd.DataFrame())
        fake_store.close = MagicMock()
        fake_runner = MagicMock()
        fake_runner.check_available = MagicMock(return_value=(False, ""))
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.rd_agent.RDAgentRunner", return_value=fake_runner),
        ):
            result = runner.invoke(app, ["ai", "rdagent", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "No data" in result.output

    def test_ai_train_from_csv(self, tmp_path: pytest.TempPathFactory) -> None:
        feat = tmp_path / "feat.csv"
        close = tmp_path / "close.csv"
        pd.DataFrame({"f1": [1.0, 2.0, 3.0, 4.0, 5.0]}).to_csv(feat, index=False)
        pd.DataFrame({"close": [10.0, 11.0, 12.0, 13.0, 14.0]}).to_csv(close, index=False)
        fake_pipe = MagicMock()
        fake_report = SimpleNamespace(
            features_hash="abc",
            decision="GO",
            reason="ok",
            n_samples=5,
            model_cls="X",
            feature_importance={"f1": 0.5},
            to_dict=lambda: {"features_hash": "abc", "decision": "GO"},
        )
        fake_pipe.train = MagicMock(return_value=fake_report)
        with (
            patch("quantflow.strategy.ai_training.AITrainingPipeline", return_value=fake_pipe),
            patch("pathlib.Path.mkdir"),
        ):
            result = runner.invoke(
                app,
                [
                    "ai",
                    "train",
                    "--symbol",
                    "BTC/USDT",
                    "--features-csv",
                    str(feat),
                    "--close-csv",
                    str(close),
                ],
            )
        assert result.exit_code == 0
        assert "Validation gate" in result.output

    def test_ai_train_from_factors_json(self, tmp_path: pytest.TempPathFactory) -> None:
        """L1277-1321: factors_json materialization path."""
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
            to_dict=lambda: {"features_hash": "abc", "decision": "GO"},
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
        assert "Training from discovered factors" in result.output

    def test_ai_train_factors_not_materializable(self, tmp_path: pytest.TempPathFactory) -> None:
        """L1305-1321: factors not materializable → FeatureStore fallback."""
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
            to_dict=lambda: {"features_hash": "abc", "decision": "GO"},
        )
        fake_pipe.train = MagicMock(return_value=fake_report)
        fake_fs = MagicMock()
        fake_fs.compute_features = MagicMock(
            return_value=_df().set_index("datetime")[["close"]].rename(columns={"close": "f1"})
        )
        raw_with_ts = _df()
        raw_with_ts["timestamp"] = [1700000000000 + i * 86400000 for i in range(len(raw_with_ts))]
        fake_store.query = MagicMock(return_value=raw_with_ts)
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch("quantflow.strategy.ai_training.AITrainingPipeline", return_value=fake_pipe),
            patch(
                "quantflow.strategy.rd_agent.load_discovered_factors",
                return_value=[SimpleNamespace(name="f1", formula="x")],
            ),
            patch(
                "quantflow.strategy.rd_agent.materialize_factor_frame",
                return_value=pd.DataFrame(),
            ),
            patch("quantflow.indicators.engine.IndicatorEngine", return_value=MagicMock()),
            patch("quantflow.data.feature_store.FeatureStore", return_value=fake_fs),
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
        assert "falling back to IndicatorEngine" in result.output

    def test_ai_register_no_model_id(self) -> None:
        result = runner.invoke(app, ["ai", "register"])
        assert result.exit_code == 0
        assert "--model-id is required" in result.output

    def test_ai_register_no_report(self, tmp_path: pytest.TempPathFactory) -> None:
        with patch("pathlib.Path.exists", return_value=False):
            result = runner.invoke(app, ["ai", "register", "--model-id", "m1"])
        assert result.exit_code == 0
        assert "No training report" in result.output

    def test_ai_register_happy(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        report_dir = tmp_path / "data" / "ai_reports"
        report_dir.mkdir(parents=True)
        (report_dir / "model-abc.json").write_text(
            json.dumps(
                {
                    "model_id": "model-abc",
                    "model_cls": "X",
                    "features_hash": "abc",
                    "decision": "GO",
                    "validation": {"decision": "GO"},
                }
            ),
            encoding="utf-8",
        )
        fake_reg = MagicMock()
        fake_reg.register = MagicMock(return_value={"status": "paper", "reason": "ok"})
        monkeypatch.chdir(tmp_path)
        with patch("quantflow.strategy.model_registry.ModelRegistry", return_value=fake_reg):
            result = runner.invoke(app, ["ai", "register", "--model-id", "model-abc"])
        assert result.exit_code == 0
        assert "status=paper" in result.output

    def test_ai_validation_bypass_happy(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=_df())
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
            notes=["n1"],
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

    def test_ai_validation_bypass_empty(self) -> None:
        fake_store = MagicMock()
        fake_store.query = MagicMock(return_value=pd.DataFrame())
        fake_store.close = MagicMock()
        with (
            patch("quantflow.data.store.DataStore", return_value=fake_store),
            patch(
                "quantflow.strategy.ai_validation_bypass.run_ai_validation_bypass",
                return_value=SimpleNamespace(),
            ),
        ):
            result = runner.invoke(app, ["ai", "bypass", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "No data" in result.output
