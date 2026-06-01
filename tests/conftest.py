"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import pytest

from quantflow.common.config import AppConfig
from quantflow.common.models import Bar


@pytest.fixture
def config() -> AppConfig:
    return AppConfig()


@pytest.fixture
def sample_bar() -> Bar:
    return Bar(
        symbol="BTC/USDT",
        timestamp=1700000000000,
        open=42000.0,
        high=42500.0,
        low=41800.0,
        close=42300.0,
        volume=1000.0,
    )
