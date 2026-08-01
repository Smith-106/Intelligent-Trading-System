"""Configuration management for QuantFlow.

Priority: CLI args > Environment variables > YAML defaults.
"""

from __future__ import annotations

import copy
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
    research_engine: str = "eventdriven"  # drift-realign DFT-2c8d4f1e: vectorbt 已移除, default 改 eventdriven (BacktestEngine)。注: 字段当前零消费方 (schema-drift)。
    validation: ValidationConfig = Field(default_factory=ValidationConfig)


class RiskConfig(BaseModel):
    position_limit_pct: float = 0.20
    max_positions: int = 5
    daily_loss_limit: float = -0.03
    weekly_loss_limit: float = -0.05
    max_drawdown: float = -0.10
    kill_switch_enabled: bool = True
    # CVaR (Expected Shortfall) threshold at 95% confidence. If the historical
    # CVaR of recent returns is worse (more negative) than this, new signals
    # are blocked. Negative because it represents a loss fraction.
    cvar_limit: float = -0.05
    # Fraction of the full-Kelly bet to use (0.5 = half-Kelly). Loaded from
    # risk.kelly_fraction in default.yaml; previously hardcoded in TradingSession
    # so the YAML value was silently dropped.
    kelly_fraction: float = 0.5
    # Confidence level for VaR/CVaR (historical). Loaded from risk.var_confidence
    # in default.yaml; previously hardcoded as 0.95 in risk_engine, so the YAML
    # value was silently dropped.
    var_confidence: float = 0.95
    # Volatility-targeting cap (opt-in, default None = OFF). When set, position
    # size is additionally bounded by min(half-Kelly, vol-target, single-name
    # cap). vol_target_pct is the target annualized volatility fraction (e.g.
    # 0.15 = 15% annual); position notional is scaled so the strategy's
    # contribution to portfolio volatility does not exceed this target.
    # Default OFF preserves the byte-for-byte backtest baseline (deep-research
    # F3 / P1); enable explicitly via risk.vol_target_pct in YAML.
    vol_target_pct: float | None = None
    # Annualization factor for volatility (crypto trades 24/7/365).
    vol_annualization: int = 365
    # Rolling window (in bars) for realized-volatility estimation when
    # vol-targeting is enabled.
    vol_window: int = 30
    # PositionSizer fixed-method 仓位比例（原 position_sizer.py 硬编码 0.10，
    # ISS-20260721-012 config-source）。默认值对齐硬编码以保 backtest baseline。
    fixed_pct: float = 0.10
    # PositionSizer 最小下单名义价值阈值（原 position_sizer.py 硬编码 10.0，
    # ISS-20260721-012 config-source）。低于此值的订单被跳过。
    min_order_notional: float = 10.0


class ExecutionConfig(BaseModel):
    mode: str = "paper"
    order_timeout: int = 30
    reconnect_interval: int = 5
    reconnect_attempts: int = 5
    slippage: float = 0.001
    maker_fee: float = 0.0008
    taker_fee: float = 0.001
    # ISS-20260723-005: OKX account/market scope. "spot" (default) trades spot
    # pairs and derives holdings from fetch_balance; "swap" trades derivatives
    # and reads the contracts schema from fetch_positions. Drives OKXGateway
    # defaultType + query_positions branch.
    market_type: str = "spot"
    # M4-2.4: multi-symbol support. When non-empty, TradingSession creates
    # per-(strategy, symbol) instances and the data loop rotates over all
    # symbols. Empty list = legacy single-symbol mode (symbol supplied by
    # CLI --symbol or data loop argument). Backward compatible.
    symbols: list[str] = Field(default_factory=list)


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


_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE_DEFAULT_CONFIG = _PACKAGE_ROOT / "config" / "default.yaml"
_DEFAULT_CONFIG_ALIASES = {
    "config/default.yaml",
    "quantflow/config/default.yaml",
    "default.yaml",
}


def resolve_config_path(config_path: str | Path | None = None) -> Path:
    """Resolve config path for source tree and installed package execution."""
    if config_path is None:
        return _PACKAGE_DEFAULT_CONFIG

    path = Path(config_path)
    if path.exists():
        return path

    normalized = path.as_posix()
    if normalized in _DEFAULT_CONFIG_ALIASES:
        return _PACKAGE_DEFAULT_CONFIG

    if not path.is_absolute():
        package_relative = _PACKAGE_ROOT / path
        if package_relative.exists():
            return package_relative

    return path


def resolve_config_path_safe(config_path: str | Path | None) -> Path:
    """Confine an untrusted ``config_path`` to the packaged config tree.

    Used by web request handlers that forward request-supplied ``config_path``
    values. Rejects absolute paths and ``..`` traversal that would escape the
    package root, preventing arbitrary YAML reads/writes via path traversal.
    CLI/internal callers should use :func:`resolve_config_path` instead.
    """
    if config_path is None:
        return _PACKAGE_DEFAULT_CONFIG

    path = Path(config_path)
    if path.is_absolute():
        raise ValueError(f"Absolute config paths are not allowed: {config_path!r}")
    if any(part == ".." for part in path.parts):
        raise ValueError(
            f"Parent-traversal segments are not allowed in config path: {config_path!r}"
        )

    normalized = path.as_posix()
    if normalized in _DEFAULT_CONFIG_ALIASES:
        return _PACKAGE_DEFAULT_CONFIG

    package_relative = _PACKAGE_ROOT / path
    try:
        resolved = package_relative.resolve(strict=False)
        resolved.relative_to(_PACKAGE_ROOT)
    except ValueError as exc:
        raise ValueError(f"Config path escapes the package config tree: {config_path!r}") from exc
    return resolved


def load_config(config_path: str | Path, cli_overrides: dict[str, Any] | None = None) -> AppConfig:
    """Load config with priority: CLI args > env vars > YAML defaults.

    Args:
        config_path: Path to YAML config file.
        cli_overrides: Dict of CLI argument overrides (highest priority).
    """
    path = resolve_config_path(config_path)
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
        path_parts = key[len(prefix) :].lower().split("__")
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
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key in SENSITIVE_FIELDS:
            result[key] = "***REDACTED***"
        elif isinstance(value, dict):
            result[key] = _sanitize_config(value)
        elif isinstance(value, list):
            result[key] = [
                _sanitize_config(item) if isinstance(item, dict) else item for item in value
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
