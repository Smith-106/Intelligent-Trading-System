"""Unit tests for configuration management."""

import tempfile
from pathlib import Path

from quantflow.common.config import AppConfig, DataConfig, RiskConfig, load_config, save_config


class TestAppConfig:
    def test_defaults(self):
        cfg = AppConfig()
        assert cfg.data.exchange == "okx"
        assert cfg.data.sandbox is False
        assert cfg.indicators.rsi_period == 14
        assert cfg.risk.position_limit_pct == 0.20
        assert cfg.risk.kill_switch_enabled is True
        assert cfg.execution.mode == "paper"

    def test_custom_values(self):
        cfg = AppConfig(data=DataConfig(sandbox=True), risk=RiskConfig(max_drawdown=-0.15))
        assert cfg.data.sandbox is True
        assert cfg.risk.max_drawdown == -0.15


class TestConfigIO:
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test_config.yaml"
            cfg = AppConfig()
            save_config(cfg, str(path))
            loaded = load_config(str(path))
            assert loaded.data.exchange == cfg.data.exchange
            assert loaded.risk.position_limit_pct == cfg.risk.position_limit_pct

    def test_load_missing_file(self):
        cfg = load_config("/nonexistent/path.yaml")
        assert isinstance(cfg, AppConfig)
        assert cfg.data.exchange == "okx"
