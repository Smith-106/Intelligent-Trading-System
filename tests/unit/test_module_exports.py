"""Tests for package re-export modules."""

from __future__ import annotations

import quantflow.config as config_module
import quantflow.trading as trading_module
from quantflow.common.config import AppConfig, load_config, save_config
from quantflow.strategy.engine import TradingSession


def test_config_module_reexports_public_api() -> None:
    assert "AppConfig" in config_module.__all__
    assert "load_config" in config_module.__all__
    assert "save_config" in config_module.__all__
    assert config_module.AppConfig is AppConfig
    assert config_module.load_config is load_config
    assert config_module.save_config is save_config


def test_trading_module_reexports_trading_session() -> None:
    assert trading_module.__all__ == ["TradingSession"]
    assert trading_module.TradingSession is TradingSession
