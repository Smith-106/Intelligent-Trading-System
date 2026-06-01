"""Tests for CLI commands."""

import pytest
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