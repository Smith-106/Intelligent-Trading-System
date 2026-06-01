from __future__ import annotations

import copy
"""Configuration management for QuantFlow.

Priority: CLI args > Environment variables > YAML defaults.
"""


import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class DataConfig(BaseModel):
    parquet_dir: str = "./data/parquet"
    duckdb_path: str = "./data/quantflow.duckdb"
    redis_url: str = "redis://localhost:6379"
    exchange: str = "okx"
    sandbox: bool = False
    rate_limit: int = 10


class IndicatorConfig(BaseModel):
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_period: int = 14
    bollinger_period: int = 20
    bollinger_std: float = 2.0


class ValidationConfig(BaseModel):
    cpcv_groups: int = 8
    cpcv_test_groups: int = 2
    embargo_periods: int = 5
    dsr_threshold: float = 0.95
    pbo_threshold: float = 0.5
    wfo_oos_efficiency: float = 0.5


class StrategyConfig(BaseModel):
    research_engine: str = "vectorbt"
    validation: ValidationConfig = Field(default_factory=ValidationConfig)


class RiskConfig(BaseModel):
    position_limit_pct: float = 0.20
    max_positions: int = 5
    daily_loss_limit: float = -0.03
    weekly_loss_limit: float = -0.05
    max_drawdown: float = -0.10
    kill_switch_enabled: bool = True


class ExecutionConfig(BaseModel):
    mode: str = "paper"
    order_timeout: int = 30
    reconnect_interval: int = 5
    reconnect_attempts: int = 5
    slippage: float = 0.001
    maker_fee: float = 0.0008
    taker_fee: float = 0.001


class AlertChannelConfig(BaseModel):
    type: str = "telegram"
    chat_id: str = ""
    token: str = ""


class MonitoringConfig(BaseModel):
    prometheus_port: int = 9090
    grafana_port: int = 3000
    alert_channels: list[AlertChannelConfig] = Field(default_factory=list)


class AppConfig(BaseModel):
    data: DataConfig = Field(default_factory=DataConfig)
    indicators: IndicatorConfig = Field(default_factory=IndicatorConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)


def load_config(config_path: str | Path, cli_overrides: dict[str, Any] | None = None) -> AppConfig:
    """Load config with priority: CLI args > env vars > YAML defaults.

    Args:
        config_path: Path to YAML config file.
        cli_overrides: Dict of CLI argument overrides (highest priority).
    """
    path = Path(config_path)
    raw: dict[str, Any] = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    # Layer 2: environment variable overrides (QUANTFLOW_ prefix)
    env_overrides = _load_env_overrides()
    raw = _deep_merge(raw, env_overrides)

    # Layer 3: CLI overrides (highest priority)
    if cli_overrides:
        raw = _deep_merge(raw, cli_overrides)

    return AppConfig(**raw)


def _load_env_overrides() -> dict[str, Any]:
    """Load config overrides from environment variables with QUANTFLOW_ prefix.

    Examples:
        QUANTFLOW_RISK__MAX_DRAWDOWN=-0.15 → risk.max_drawdown: -0.15
        QUANTFLOW_DATA__SANDBOX=true → data.sandbox: true
        QUANTFLOW_EXECUTION__MODE=live → execution.mode: live
    """
    result: dict[str, Any] = {}
    prefix = "QUANTFLOW_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        path_parts = key[len(prefix):].lower().split("__")
        # Try to cast to appropriate type
        parsed = _parse_env_value(value)
        _set_nested(result, path_parts, parsed)
    return result


def _parse_env_value(value: str) -> Any:
    """Parse env var string to appropriate Python type."""
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _set_nested(d: dict[str, Any], keys: list[str], value: Any) -> None:
    """Set a value in a nested dict using a list of keys."""
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base. Override wins on conflicts."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


SENSITIVE_FIELDS = {"token", "secret", "api_key", "passphrase", "password"}


def _sanitize_config(data: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive fields from config dict before serialization."""
    result = {}
    for key, value in data.items():
        if key in SENSITIVE_FIELDS:
            result[key] = "***REDACTED***"
        elif isinstance(value, dict):
            result[key] = _sanitize_config(value)
        elif isinstance(value, list):
            result[key] = [
                _sanitize_config(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def save_config(config: AppConfig, config_path: str | Path, sanitize: bool = True) -> None:
    """Save config to YAML file. Sensitive fields are redacted by default."""
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump()
    if sanitize:
        data = _sanitize_config(data)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False)
