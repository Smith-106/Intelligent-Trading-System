"""Tests for CLI commands."""

from __future__ import annotations

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

    def test_run_command_starts_session_and_enters_data_loop(self, monkeypatch) -> None:
        events: list[tuple[object, ...]] = []

        class FakeSession:
            def __init__(self, config, strategies) -> None:
                self._running = True
                events.append(("init", len(strategies)))

            async def start(self, mode: str = "paper", gateway_config=None) -> None:
                events.append(("start", mode, gateway_config))

            async def run_data_loop(
                self,
                symbol: str,
                timeframe: str = "1h",
                interval_seconds: int = 60,
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
            def __init__(self, config, strategies) -> None:
                self._running = True
                events.append(("init", len(strategies)))

            async def start(self, mode: str = "paper", gateway_config=None) -> None:
                events.append(("start", mode, gateway_config))

            async def run_data_loop(
                self,
                symbol: str,
                timeframe: str = "1h",
                interval_seconds: int = 60,
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
