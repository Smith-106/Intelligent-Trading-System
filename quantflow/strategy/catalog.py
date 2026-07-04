"""Shared strategy catalog for QuantFlow surfaces."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, TypeAlias

import yaml

from quantflow.strategy.base import StrategyBase

StrategyFactory: TypeAlias = Callable[[dict[str, Any] | None], StrategyBase]
ParamSpace: TypeAlias = dict[str, tuple[Any, ...]]


def _trend_following_factory(params: dict[str, Any] | None = None) -> StrategyBase:
    from quantflow.strategy.templates.trend_following import TrendFollowingStrategy

    return TrendFollowingStrategy(params)


def _mean_reversion_factory(params: dict[str, Any] | None = None) -> StrategyBase:
    from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy

    return MeanReversionStrategy(params)


def _elliott_wave_factory(params: dict[str, Any] | None = None) -> StrategyBase:
    from quantflow.strategy.templates.elliott_wave import ElliottWaveStrategy

    return ElliottWaveStrategy(params)


def _volatility_breakout_factory(params: dict[str, Any] | None = None) -> StrategyBase:
    from quantflow.strategy.templates.volatility_breakout import VolatilityBreakoutStrategy

    return VolatilityBreakoutStrategy(params)


def _funding_rate_factory(params: dict[str, Any] | None = None) -> StrategyBase:
    from quantflow.strategy.templates.funding_rate import FundingRateStrategy

    return FundingRateStrategy(params)


def _momentum_rotation_factory(params: dict[str, Any] | None = None) -> StrategyBase:
    from quantflow.strategy.templates.momentum_rotation import MomentumRotationStrategy

    return MomentumRotationStrategy(params)


def _ml_ensemble_factory(params: dict[str, Any] | None = None) -> StrategyBase:
    from quantflow.strategy.templates.ml_ensemble import MLEnsembleStrategy

    return MLEnsembleStrategy(params)


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    title: str
    description: str
    config_path: Path
    factory: StrategyFactory
    param_space: ParamSpace


_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_STRATEGY_CONFIG_DIR = _PACKAGE_ROOT / "config" / "strategies"
_DEFAULT_DESCRIPTIONS = {
    "trend_following": "MA crossover, MACD, RSI, ATR, volume multi-filter trend strategy",
    "mean_reversion": "RSI plus Bollinger Band mean reversion with volume confirmation",
    "elliott_wave": "Wave-structure strategy with ZigZag consensus and Fibonacci rules",
    "volatility_breakout": "ATR and channel breakout strategy tuned for crypto volatility",
    "funding_rate": "Funding-rate extreme reversal strategy with open-interest filter",
    "momentum_rotation": "Cross-asset momentum ranking and periodic rotation strategy",
    "ml_ensemble": "Model-driven ensemble signals with configurable thresholds",
}


def get_strategy_definitions() -> dict[str, StrategyDefinition]:
    """Return all supported strategy definitions."""
    return {
        "trend_following": StrategyDefinition(
            strategy_id="trend_following",
            title="Trend Following",
            description=_DEFAULT_DESCRIPTIONS["trend_following"],
            config_path=_STRATEGY_CONFIG_DIR / "trend_following.yaml",
            factory=_trend_following_factory,
            param_space={
                "fast_ma_period": (3, 15),
                "slow_ma_period": (30, 120),
                "rsi_oversold": (20, 40),
                "rsi_overbought": (60, 85),
                "atr_multiplier": (1.2, 3.0),
                "volume_threshold": (0.8, 2.0),
            },
        ),
        "mean_reversion": StrategyDefinition(
            strategy_id="mean_reversion",
            title="Mean Reversion",
            description=_DEFAULT_DESCRIPTIONS["mean_reversion"],
            config_path=_STRATEGY_CONFIG_DIR / "mean_reversion.yaml",
            factory=_mean_reversion_factory,
            param_space={
                "rsi_oversold": (20, 40),
                "rsi_overbought": (60, 85),
                "bb_std": (1.5, 3.0),
                "exit_rsi_overbought": (50, 75),
                "exit_rsi_oversold": (25, 50),
            },
        ),
        "elliott_wave": StrategyDefinition(
            strategy_id="elliott_wave",
            title="Elliott Wave",
            description=_DEFAULT_DESCRIPTIONS["elliott_wave"],
            config_path=_STRATEGY_CONFIG_DIR / "elliott_wave.yaml",
            factory=_elliott_wave_factory,
            param_space={
                "zigzag_threshold": (0.02, 0.08),
                "fib_tolerance": (0.10, 0.25),
                "atr_stop_mult": (1.0, 3.0),
            },
        ),
        "volatility_breakout": StrategyDefinition(
            strategy_id="volatility_breakout",
            title="Volatility Breakout",
            description=_DEFAULT_DESCRIPTIONS["volatility_breakout"],
            config_path=_STRATEGY_CONFIG_DIR / "volatility_breakout.yaml",
            factory=_volatility_breakout_factory,
            param_space={
                "atr_threshold": (1.2, 2.0),
                "atr_shrink_exit": (0.5, 0.9),
                "volume_threshold": (1.2, 2.0),
            },
        ),
        "funding_rate": StrategyDefinition(
            strategy_id="funding_rate",
            title="Funding Rate",
            description=_DEFAULT_DESCRIPTIONS["funding_rate"],
            config_path=_STRATEGY_CONFIG_DIR / "funding_rate.yaml",
            factory=_funding_rate_factory,
            param_space={
                "entry_threshold": (0.0005, 0.002),
                "exit_threshold": (0.0001, 0.0005),
                "oi_change_threshold": (0.02, 0.1),
            },
        ),
        "momentum_rotation": StrategyDefinition(
            strategy_id="momentum_rotation",
            title="Momentum Rotation",
            description=_DEFAULT_DESCRIPTIONS["momentum_rotation"],
            config_path=_STRATEGY_CONFIG_DIR / "momentum_rotation.yaml",
            factory=_momentum_rotation_factory,
            param_space={
                "lookback": (10, 40),
                "top_n": (1, 5),
                "stop_loss_pct": (0.01, 0.05),
            },
        ),
        "ml_ensemble": StrategyDefinition(
            strategy_id="ml_ensemble",
            title="ML Ensemble",
            description=_DEFAULT_DESCRIPTIONS["ml_ensemble"],
            config_path=_STRATEGY_CONFIG_DIR / "ml_ensemble.yaml",
            factory=_ml_ensemble_factory,
            param_space={
                "entry_threshold": (0.5, 0.8),
                "exit_threshold": (0.2, 0.5),
            },
        ),
    }


def get_strategy_definition(strategy_id: str) -> StrategyDefinition:
    """Return a single strategy definition or raise KeyError."""
    return get_strategy_definitions()[strategy_id]


def get_strategy_factories() -> dict[str, StrategyFactory]:
    """Return strategy factories keyed by strategy id."""
    return {key: definition.factory for key, definition in get_strategy_definitions().items()}


def get_strategy_specs() -> dict[str, tuple[StrategyFactory, ParamSpace]]:
    """Return factory plus parameter space map for optimization and validation."""
    return {
        key: (definition.factory, definition.param_space)
        for key, definition in get_strategy_definitions().items()
    }


@cache
def load_strategy_config(strategy_id: str) -> dict[str, Any]:
    """Load the YAML configuration for a strategy."""
    config_path = get_strategy_definition(strategy_id).config_path
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def summarize_strategy(strategy_id: str) -> dict[str, Any]:
    """Return a UI-friendly strategy summary."""
    definition = get_strategy_definition(strategy_id)
    raw = load_strategy_config(strategy_id)
    strategy_block = raw.get("strategy", {})
    params = raw.get("params") or strategy_block.get("params") or {}
    exit_config = raw.get("exit") or strategy_block.get("exit") or {}
    risk_config = raw.get("risk") or {}
    timeframe = raw.get("timeframe") or strategy_block.get("timeframe")
    default_symbol = raw.get("symbol") or strategy_block.get("symbol")
    symbols = raw.get("symbols") or ([default_symbol] if default_symbol else [])
    description = raw.get("description") or strategy_block.get("description") or definition.description
    return {
        "strategy_id": strategy_id,
        "title": definition.title,
        "description": description,
        "timeframe": timeframe,
        "default_symbol": default_symbol,
        "symbols": symbols,
        "param_space": definition.param_space,
        "params": params,
        "exit": exit_config,
        "risk": risk_config,
        "config_path": str(definition.config_path),
    }


def list_strategy_summaries() -> list[dict[str, Any]]:
    """List UI-ready strategy summaries ordered by strategy id."""
    return [summarize_strategy(strategy_id) for strategy_id in get_strategy_definitions()]
