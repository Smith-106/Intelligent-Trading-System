"""Tests for CLI commands."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
from typer.testing import CliRunner

from quantflow.cli.main import app

runner = CliRunner()


class TestCLIBasics:
    def test_app_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "quantflow" in result.output.lower() or "download" in result.output

    def test_status_command(self):
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "QuantFlow" in result.output

    def test_download_help(self):
        result = runner.invoke(app, ["download", "--help"])
        assert result.exit_code == 0
        assert "symbol" in result.output.lower()

    def test_research_help(self):
        result = runner.invoke(app, ["research", "--help"])
        assert result.exit_code == 0
        assert "strategy" in result.output.lower()

    def test_optimize_help(self):
        result = runner.invoke(app, ["optimize", "--help"])
        assert result.exit_code == 0
        assert "method" in result.output.lower()

    def test_validate_help(self):
        result = runner.invoke(app, ["validate", "--help"])
        assert result.exit_code == 0
        assert "method" in result.output.lower() or "cpcv" in result.output.lower()

    def test_run_help(self):
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "mode" in result.output.lower()

    def test_station_help(self):
        result = runner.invoke(app, ["station", "--help"])
        assert result.exit_code == 0
        assert "port" in result.output.lower()

    def test_benchmark_command_reports_core_performance_paths(self):
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
            ],
        )

        assert result.exit_code == 0
        assert "QuantFlow Performance Baseline" in result.output
        assert "query rows/sec" in result.output
        assert "batch calculate all" in result.output
        assert "save feature partitions" in result.output
        assert "TradingSession.on_bar batch" in result.output
        assert "three strategy bars/sec" in result.output
        assert "paper submit_order batch" in result.output

    def test_benchmark_json_reports_threshold_failures(self):
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
                "--json",
                "--min-bars-per-sec",
                "1000000000",
            ],
        )

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["params"]["bars"] == 80
        metric_names = {item["metric"] for item in payload["metrics"]}
        assert "compute requested subset" in metric_names
        assert "load rows/sec" in metric_names
        assert "three strategy bars/sec" in metric_names
        assert payload["failures"]
        assert payload["failures"][0]["metric"] == "runtime.bars_per_sec"

    def test_run_command_starts_session_and_enters_data_loop(self, monkeypatch) -> None:
        events: list[tuple[object, ...]] = []

        class FakeSession:
            def __init__(self, config, strategies, monitoring_sink=None) -> None:
                self._running = True
                events.append(("init", len(strategies)))

            async def start(self, mode: str = "paper", gateway_config=None, symbols=None) -> None:
                events.append(("start", mode, gateway_config))

            async def run_data_loop(
                self,
                symbol: str = "",
                timeframe: str = "1h",
                interval_seconds: int = 60,
                symbols=None,
            ) -> None:
                events.append(("loop", symbol, timeframe, interval_seconds))
                self._running = False

            async def stop(self) -> None:
                events.append(("stop", None))

        monkeypatch.setattr("quantflow.strategy.engine.TradingSession", FakeSession)

        result = runner.invoke(
            app,
            [
                "run",
                "--mode",
                "paper",
                "--strategy",
                "trend_following",
                "--symbol",
                "ETH/USDT",
                "--timeframe",
                "5m",
                "--interval",
                "3",
            ],
        )

        assert result.exit_code == 0
        assert ("init", 1) in events
        assert any(event[0] == "start" and event[1] == "paper" for event in events)
        assert ("loop", "ETH/USDT", "5m", 3) in events
        assert ("stop", None) in events

    def test_run_command_requires_okx_credentials_for_live_mode(self) -> None:
        result = runner.invoke(
            app,
            [
                "run",
                "--mode",
                "live",
                "--strategy",
                "trend_following",
            ],
        )

        assert result.exit_code != 0
        assert "Missing required environment variables for live mode" in result.output

    def test_run_command_loads_okx_credentials_for_sandbox_mode(self, monkeypatch) -> None:
        events: list[tuple[object, ...]] = []

        class FakeSession:
            def __init__(self, config, strategies, monitoring_sink=None) -> None:
                self._running = True
                events.append(("init", len(strategies)))

            async def start(self, mode: str = "paper", gateway_config=None, symbols=None) -> None:
                events.append(("start", mode, gateway_config))

            async def run_data_loop(
                self,
                symbol: str = "",
                timeframe: str = "1h",
                interval_seconds: int = 60,
                symbols=None,
            ) -> None:
                events.append(("loop", symbol, timeframe, interval_seconds))
                self._running = False

            async def stop(self) -> None:
                events.append(("stop", None))

        monkeypatch.setenv("OKX_API_KEY", "key")
        monkeypatch.setenv("OKX_SECRET", "secret")
        monkeypatch.setenv("OKX_PASSPHRASE", "pass")
        monkeypatch.setattr("quantflow.strategy.engine.TradingSession", FakeSession)

        result = runner.invoke(
            app,
            [
                "run",
                "--mode",
                "sandbox",
                "--strategy",
                "trend_following",
                "--interval",
                "0",
            ],
        )

        assert result.exit_code == 0
        assert any(
            event[0] == "start"
            and event[1] == "sandbox"
            and event[2]
            == {
                "sandbox": True,
                "api_key": "key",
                "secret": "secret",
                "passphrase": "pass",
            }
            for event in events
        )

    def test_validate_gate_passes_strategy_context_for_true_oos_validation(
        self, monkeypatch
    ) -> None:
        dates = pd.date_range("2024-01-01", periods=80, freq="D")
        prices = pd.Series(range(100, 180), index=dates, dtype=float)
        frame = pd.DataFrame(
            {
                "datetime": dates,
                "open": prices.to_numpy(),
                "high": prices.to_numpy() + 1,
                "low": prices.to_numpy() - 1,
                "close": prices.to_numpy(),
                "volume": 1000.0,
            }
        )
        calls: list[dict[str, Any]] = []

        class FakeDataStore:
            def __init__(self, parquet_dir, duckdb_path) -> None:
                self.parquet_dir = parquet_dir
                self.duckdb_path = duckdb_path

            def query(self, symbol, **kwargs):
                assert symbol == "ETH/USDT"
                return frame.copy()

            def close(self) -> None:
                calls.append({"closed": True})

        def fake_validation_gate(close, entries, exits, **kwargs):
            signal_fn = kwargs["signal_fn"]
            data = kwargs["data"]
            regenerated_entries, regenerated_exits = signal_fn(
                data,
                fast_ma_period=3,
                slow_ma_period=5,
                rsi_oversold=30,
                rsi_overbought=70,
                atr_multiplier=2.0,
                volume_threshold=0.5,
            )
            calls.append(
                {
                    "close": close,
                    "entries": entries,
                    "exits": exits,
                    "kwargs": kwargs,
                    "regenerated_entries": regenerated_entries,
                    "regenerated_exits": regenerated_exits,
                }
            )
            return {
                "decision": "GO",
                "reason": "All validation checks passed",
                "checks": {
                    "cpcv": {"passed": True},
                    "wfo_rolling": {"passed": True},
                    "wfo_anchored": {"passed": True},
                },
            }

        monkeypatch.setattr("quantflow.data.store.DataStore", FakeDataStore)
        monkeypatch.setattr(
            "quantflow.strategy.validation.gate.validation_gate", fake_validation_gate
        )

        result = runner.invoke(
            app,
            [
                "validate",
                "--method",
                "gate",
                "--strategy",
                "trend_following",
                "--symbol",
                "ETH/USDT",
                "--groups",
                "4",
                "--test-groups",
                "1",
                "--wfo-windows",
                "3",
                "--optimize-trials",
                "9",
                "--optimize-method",
                "random",
            ],
        )

        assert result.exit_code == 0
        gate_call = next(call for call in calls if "kwargs" in call)
        kwargs = gate_call["kwargs"]
        assert kwargs["data"].index.equals(dates)
        assert kwargs["param_space"]["fast_ma_period"] == (3, 15)
        assert callable(kwargs["signal_fn"])
        assert kwargs["optimize_trials"] == 9
        assert kwargs["optimize_method"] == "random"
        assert kwargs["cpcv_groups"] == 4
        assert kwargs["cpcv_test_groups"] == 1
        assert kwargs["wfo_windows"] == 3
        assert gate_call["regenerated_entries"].index.equals(dates)
        assert gate_call["regenerated_exits"].index.equals(dates)
        assert calls[-1] == {"closed": True}


class TestAICommand:
    def test_ai_help_lists_rdagent_action(self):
        result = runner.invoke(app, ["ai", "--help"])
        assert result.exit_code == 0
        assert "rdagent" in result.output.lower()

    def test_ai_rdagent_prints_install_hint_when_qlib_missing(self, monkeypatch):
        """qlib absent → command prints install hint and exits 0 (not a crash)."""
        from quantflow.strategy.rd_agent import RDAgentRunner

        monkeypatch.setattr(
            RDAgentRunner,
            "check_available",
            staticmethod(lambda: (False, "qlib is not installed. pip install...")),
        )
        result = runner.invoke(app, ["ai", "rdagent", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "not available" in result.output.lower()
        assert "pip install" in result.output.lower()

    def test_ai_rdagent_evalates_factors_when_qlib_available(self, monkeypatch):
        from quantflow.strategy.rd_agent import RDAgentRunner

        monkeypatch.setattr(RDAgentRunner, "check_available", staticmethod(lambda: (True, "")))

        # Non-trivial price series so IC metrics are finite (linear data → NaN IC)
        import numpy as np

        rng = np.random.default_rng(7)
        close = 100.0 * (1.0 + rng.standard_normal(80).cumsum() * 0.01)
        close = np.maximum(close, 1.0)
        fake_df = pd.DataFrame(
            {"close": close},
            index=pd.date_range("2024-01-01", periods=80, freq="D"),
        )

        class FakeStore:
            def __init__(self, *args, **kwargs):
                pass

            def query(self, symbol, **kwargs):
                return fake_df.copy()

            def close(self):
                pass

        monkeypatch.setattr("quantflow.data.store.DataStore", FakeStore)

        # discover_factors runs the real pandas baseline path (no qlib needed)
        real_factors = RDAgentRunner().discover_factors(fake_df)
        monkeypatch.setattr(RDAgentRunner, "discover_factors", lambda self, df: real_factors)

        result = runner.invoke(app, ["ai", "rdagent", "--symbol", "BTC/USDT"])
        assert result.exit_code == 0
        assert "RD-Agent" in result.output
        assert "factors passed" in result.output
        assert "momentum_5" in result.output

    def test_ai_unknown_action_rejected(self):
        result = runner.invoke(app, ["ai", "bogus"])
        assert result.exit_code == 0
        assert "Unknown AI action" in result.output
