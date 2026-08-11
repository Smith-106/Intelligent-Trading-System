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


class ExchangeHealthConfig(BaseModel):
    """T-s1-04: exchange health monitor + circuit breaker (risk.exchange_health).

    enabled defaults to false — zero behavior change for existing runs.
    YAML-driven via default.yaml risk.exchange_health (no hardcoding).
    """

    enabled: bool = False
    # 滑动窗口错误率阈值（> 阈值触发熔断）
    error_rate_threshold: float = 0.5
    # 滑动窗口长度（秒）
    window_seconds: float = 60.0
    # 连续 50011（限频）次数阈值（≥ 阈值直接触发，不看错误率）
    rate_limit_streak: int = 3
    # 熔断冷却时间（秒）；冷却后需连续 3 次 success 观察窗才恢复（滞回）
    cooldown_seconds: float = 300.0


class DynamicBudgetConfig(BaseModel):
    """s4 (T-s4-01): volatility-scaled per-strategy budget (default OFF).

    When ``enabled`` is false (default) the engine keeps the static
    ``strategy_risk_budgets`` behavior byte-for-byte. When enabled, each
    budgeted strategy's budget fraction is scaled down by
    ``max(1, realized_vol / target_vol)`` (EWMA of recent returns), clamped
    to ``[min_scale, max_scale]``. Rising volatility shrinks the budget
    (fail-closed); an empty/insufficient return history falls back to the
    static budget (fail-safe).
    """

    enabled: bool = False
    #: EWMA span for realized-volatility estimation (bars).
    vol_ewma_span: int = 30
    #: Annualized target volatility fraction (e.g. 0.15 = 15% annual).
    target_vol_pct: float = 0.15
    #: Annualization factor (crypto trades 24/7/365).
    vol_annualization: int = 365
    #: Minimum/maximum scaling factors applied to the static budget.
    min_scale: float = 0.5
    max_scale: float = 1.5
    #: Minimum return samples before volatility scaling is applied.
    min_samples: int = 30
    # s5 (T-s5-02): additionally scale budgets by portfolio CVaR — when the
    # historical CVaR is worse than cvar_limit, budgets shrink by
    # max(1, |CVaR| / |cvar_limit|). Default OFF (zero behavior change);
    # opt-in via risk.dynamic_budget.var_scaling in YAML.
    var_scaling: bool = False


class PortfolioOptimizationConfig(BaseModel):
    """s5 (T-s5-02): portfolio-level optimization (default OFF).

    When ``enabled`` is false (default) the engine keeps the static
    per-strategy allocation behavior byte-for-byte. When enabled, the
    engine tracks per-strategy returns and, every ``rebalance_every_n_bars``
    bars, recomputes risk-parity weights via ``RiskParityOptimizer`` and
    pushes them into ``PortfolioManager.set_allocation`` so sizing follows
    the balanced-risk weights. Any optimization failure degrades to equal
    weights (fail-closed, never raises).
    """

    enabled: bool = False
    #: Allocation method: risk_parity (default) | mean_variance (min-var).
    method: str = "risk_parity"
    #: Rolling window (bars) for per-strategy realized-volatility estimation.
    vol_window: int = 30
    #: Minimum samples per strategy before its volatility is trusted.
    min_samples: int = 30
    #: Rebalance cadence in bars (48 = every ~2 days on 1h bars).
    rebalance_every_n_bars: int = 48
    #: Fallback allocation when optimization cannot run (equal or static).
    fallback: str = "equal"
    #: Optimization grain: ``strategy`` (default, s5) or ``symbol`` (shared-book
    #: multi-asset risk parity with periodic rebalance). ``symbol`` tracks
    #: per-symbol returns and writes ``PortfolioManager`` symbol weights so
    #: sizing becomes ``strategy_weight * symbol_weight``.
    level: str = "strategy"


class PaperReadinessConfig(BaseModel):
    """T016: minimum paper session sample before paper→live promotion."""

    enabled: bool = True
    min_paper_days: float = 7.0
    min_fills: int = 20
    min_orders: int = 0
    require_evidence: bool = True


class BookRiskBudgetConfig(BaseModel):
    """Highflyer-style hierarchical book budget (default OFF).

    When enabled, RiskEngine runs BookRiskBudget after exchange checks:
    book gross/net caps, optional strategy caps, factor sleeves (beta/overlay),
    and drawdown kill for risk-increasing entries.
    """

    enabled: bool = False
    book_gross_limit: float = 1.2
    book_net_limit: float = 1.2
    kill_drawdown: float = 0.15
    beta_sleeve: float = 1.0
    overlay_sleeve: float = 0.20


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
    # W21a/W22c: funding as risk gate (not alpha; not B3 signal threshold).
    # B3 entry_threshold=0.001 is a frozen signal contract (KEEP_B0) — do not
    # "fix" B3 by flipping these risk knobs. See docs/research/w22-*.md.
    # When enabled, |funding_rate| above max_funding_rate_abs blocks new
    # entries and adds pause reason "funding_risk_gate". Optional hard path
    # activates KillSwitch.
    funding_risk_gate_enabled: bool = False
    max_funding_rate_abs: float = 0.001  # e.g. 0.1% per settlement
    funding_risk_gate_kill: bool = False  # True → KillSwitch.activate (hard)
    # T-s1-04: 单所总敞口上限（持仓名义 + pending）占 net value 的比例。
    # pydantic 默认 None（不设限）保既有单测/回测零变化；default.yaml 写 0.8。
    exchange_exposure_limit_pct: float | None = None
    # T-s1-04: 交易所健康度监控/熔断（默认关闭）。
    exchange_health: ExchangeHealthConfig = Field(default_factory=ExchangeHealthConfig)
    # s4 (T-s4-01): volatility-scaled dynamic strategy budget (default OFF).
    dynamic_budget: DynamicBudgetConfig = Field(default_factory=DynamicBudgetConfig)
    # s5 (T-s5-02): portfolio-level risk-parity allocation (default OFF).
    portfolio_optimization: PortfolioOptimizationConfig = Field(
        default_factory=PortfolioOptimizationConfig
    )
    # T016: paper→live minimum sample / duration (default ON).
    paper_readiness: PaperReadinessConfig = Field(default_factory=PaperReadinessConfig)
    # Highflyer-style book budget (default OFF — zero behavior change).
    book_risk_budget: BookRiskBudgetConfig = Field(default_factory=BookRiskBudgetConfig)


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
    # T-s2-04: funding/OI 喂数接线开关（默认 false 零行为变化）。YAML 写权在
    # config/strategies/funding_rate.yaml（避免 default.yaml wave3 冲突）。
    funding_feed_enabled: bool = False
    # W20a: optional ticker BBO poll → push_ticker_bbo (default false = bar_proxy only).
    # Does not enable orderbook_fill; only refreshes BBO cache when poll is on.
    bbo_poll_enabled: bool = False
    bbo_poll_interval_s: float = 5.0
    # W23a: optional public-trades poll → TradesStore (default false).
    # Not a full WS tape; REST fetch_trades on an interval for CVD research.
    trades_poll_enabled: bool = False
    trades_poll_interval_s: float = 30.0
    trades_store_dir: str = "data/trades"
    trades_poll_limit: int = 100
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


class ReconciliationConfig(BaseModel):
    """L7 reconciliation loop settings (T-s1-01; wired in TradingSession w2).

    ``enabled`` defaults to False so existing runs keep byte-for-byte behavior;
    the wave2 TradingSession wiring reads these values when assembling the
    ReconciliationEngine.
    """

    enabled: bool = False
    interval_minutes: float = 5.0
    drift_threshold_bps: float = 100.0
    order_staleness_seconds: float = 300.0


class StateConfig(BaseModel):
    """Session checkpoint/restore settings (T-s1-03; default OFF).

    Declared here in wave1 (alongside ReconciliationConfig) so the YAML
    sections land with a matching pydantic model; wave2 owns the YAML writes.
    """

    enabled: bool = False
    checkpoint_dir: str = "./data/checkpoints"
    checkpoint_interval_minutes: float = 5.0


class RDAgentConfigModel(BaseModel):
    """RD-Agent factor-mining settings (s3-ai-research-pipeline; default OFF).

    ``enabled`` defaults to False so existing runs keep byte-for-byte
    behavior. When enabled, ``discover_factors`` prefers a real RD-Agent CLI
    invocation (LLM-driven factor search) and falls back to the built-in
    Alpha158-style baseline when the CLI or an LLM key is unavailable.
    """

    enabled: bool = False
    llm_backend: str = "litellm"
    chat_model: str = ""
    llm_api_base: str = ""
    llm_timeout_seconds: float = 300.0
    cli_timeout_seconds: float = 600.0


class AutoLoopConfigModel(BaseModel):
    """s4 (T-s4-02): auto research loop — train → validate → register/reject.

    ``enabled`` defaults to False (zero behavior change). When enabled,
    ``AutoResearchLoop`` orchestrates one iteration per call: candidate model
    trained via ``AITrainingPipeline``, validated by ``validation_gate``, then
    registered (GO → paper) or rejected (NO-GO) in the model registry with an
    append-only JSONL decision log.
    """

    enabled: bool = False
    log_path: str = "./data/ai_loop/decisions.jsonl"
    validation_kwargs: dict[str, Any] = Field(default_factory=dict)
    training_kwargs: dict[str, Any] = Field(default_factory=dict)


class AIConfig(BaseModel):
    """AI-layer settings (s3): RD-Agent wiring + model registry (default OFF)."""

    rdagent: RDAgentConfigModel = Field(default_factory=RDAgentConfigModel)
    model_registry_enabled: bool = False
    registry_dir: str = "./data/models"
    # s4 (T-s4-02): auto research loop (default OFF).
    auto_loop: AutoLoopConfigModel = Field(default_factory=AutoLoopConfigModel)


class KolReferenceConfig(BaseModel):
    """KOL Discord consensus as size reference only (default OFF).

    Never opens/closes/reverses from KOL alone. When enabled, multiplies
    PositionSizer notional if consensus aligns/opposes the system signal.
    """

    enabled: bool = False
    max_boost: float = 0.15
    max_cut: float = 0.25
    min_abs_score: float = 0.35
    require_actionable: bool = True
    max_age_hours: float = 6.0
    consensus_path: str = "data/kol_signals/latest_consensus.json"


class AppConfig(BaseModel):
    data: DataConfig = Field(default_factory=DataConfig)
    indicators: IndicatorConfig = Field(default_factory=IndicatorConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    reconciliation: ReconciliationConfig = Field(default_factory=ReconciliationConfig)
    state: StateConfig = Field(default_factory=StateConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    # KOL market assessment / live-call reference weight (advisory).
    kol_reference: KolReferenceConfig = Field(default_factory=KolReferenceConfig)


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
