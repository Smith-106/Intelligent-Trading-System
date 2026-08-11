"""Shared strategy catalog for QuantFlow surfaces."""

from __future__ import annotations

import logging
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, TypeAlias

import yaml

from quantflow.strategy.base import StrategyBase

logger = logging.getLogger(__name__)

StrategyFactory: TypeAlias = Callable[[dict[str, Any] | None], StrategyBase]
ParamSpace: TypeAlias = dict[str, tuple[Any, ...]]


def _trend_following_factory(params: dict[str, Any] | None = None) -> StrategyBase:
    from quantflow.strategy.templates.trend_following import TrendFollowingStrategy

    return TrendFollowingStrategy(params)


def _simple_factory(params: dict[str, Any] | None = None) -> StrategyBase:
    from quantflow.strategy.templates.simple import SimpleStrategy

    return SimpleStrategy(params)


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


def _ai_factor_factory(params: dict[str, Any] | None = None) -> StrategyBase:
    from quantflow.strategy.templates.ai_factor_strategy import AIFactorStrategy

    return AIFactorStrategy(params)


def _spot_perp_arb_factory(params: dict[str, Any] | None = None) -> StrategyBase:
    from quantflow.strategy.templates.spot_perp_arb import SpotPerpArbStrategy

    return SpotPerpArbStrategy(params)


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    title: str
    description: str
    config_path: Path
    factory: StrategyFactory
    param_space: ParamSpace
    enabled: bool = True


_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_STRATEGY_CONFIG_DIR = _PACKAGE_ROOT / "config" / "strategies"

_FACTORY_REGISTRY: dict[str, StrategyFactory] = {
    "trend_following": _trend_following_factory,
    "simple": _simple_factory,
    "mean_reversion": _mean_reversion_factory,
    "elliott_wave": _elliott_wave_factory,
    "volatility_breakout": _volatility_breakout_factory,
    "funding_rate": _funding_rate_factory,
    "momentum_rotation": _momentum_rotation_factory,
    "ml_ensemble": _ml_ensemble_factory,
    # T018: YAML existed without factories → "No factory registered" spam.
    "ai_factor": _ai_factor_factory,
    "spot_perp_arb": _spot_perp_arb_factory,
}


def _get_factory_registry() -> dict[str, StrategyFactory]:
    """Return the strategy_id -> factory mapping."""
    return dict(_FACTORY_REGISTRY)


_DEFAULT_DESCRIPTIONS = {
    "trend_following": "MA crossover, MACD, RSI, ATR, volume multi-filter trend strategy",
    "simple": (
        "Jesse-style thin template — override should_long/should_short/should_exit_*; "
        "default long-only SMA (W16 DX; research→paper shared hooks)"
    ),
    "mean_reversion": "RSI plus Bollinger Band mean reversion with volume confirmation",
    "elliott_wave": "Wave-structure strategy with ZigZag consensus and Fibonacci rules",
    "volatility_breakout": "ATR and channel breakout strategy tuned for crypto volatility",
    "funding_rate": "Funding-rate extreme reversal strategy with open-interest filter",
    "momentum_rotation": "Cross-asset momentum ranking and periodic rotation strategy",
    "ml_ensemble": "Model-driven ensemble signals with configurable thresholds",
    "ai_factor": (
        "Registry-driven AI factor strategy — model P(up) gates momentum signals (s4 T-s4-03)"
    ),
    "spot_perp_arb": (
        "Funding-rate extreme symmetric spot-perp prototype — synthetic-data "
        "validated only (s4 T-s4-04)"
    ),
}


def get_strategy_definitions(
    *,
    include_disabled: bool = True,
) -> dict[str, StrategyDefinition]:
    """Return strategy definitions loaded from YAML config.

    T018: YAML ``strategy.enabled: false`` is first-class (still listed when
    ``include_disabled=True``) instead of being dropped or spamming
    "No factory registered" for known research prototypes.

    Unknown strategy_id without a factory is recorded once at DEBUG (not
    WARNING) so asset hygiene can surface orphans without log noise.
    """
    definitions: dict[str, StrategyDefinition] = {}

    factories = _get_factory_registry()

    for yaml_path in sorted(_STRATEGY_CONFIG_DIR.glob("*.yaml")):
        try:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            logger.warning("Failed to load strategy config %s: %s", yaml_path.name, exc)
            continue

        if not isinstance(raw, dict):
            logger.warning("Strategy config %s is not a mapping, skipping", yaml_path.name)
            continue

        strategy_config = raw.get("strategy", {})
        if not isinstance(strategy_config, dict):
            strategy_config = {}
        strategy_id = strategy_config.get("name", yaml_path.stem)

        # Metadata from YAML, fallback to _DEFAULT_DESCRIPTIONS
        meta = raw.get("metadata", {})
        if not isinstance(meta, dict):
            meta = {}
        title = meta.get("title", strategy_id.replace("_", " ").title())
        description = meta.get("description", _DEFAULT_DESCRIPTIONS.get(strategy_id, ""))

        # param_space from YAML (list -> tuple conversion)
        raw_param_space = raw.get("param_space", {})
        if not isinstance(raw_param_space, dict):
            raw_param_space = {}
        param_space = {
            k: tuple(v) if isinstance(v, list) else v for k, v in raw_param_space.items()
        }

        # Default enabled=True when key omitted (legacy YAMLs).
        enabled = bool(strategy_config.get("enabled", True))

        factory = factories.get(strategy_id)
        if factory is None:
            # T018: do not WARNING-spam; orphans are listed by catalog_hygiene().
            logger.debug(
                "No factory registered for strategy %r (yaml=%s); orphan asset",
                strategy_id,
                yaml_path.name,
            )
            continue

        if not enabled and not include_disabled:
            continue

        definitions[strategy_id] = StrategyDefinition(
            strategy_id=strategy_id,
            title=title,
            description=description,
            config_path=yaml_path,
            factory=factory,
            param_space=param_space,
            enabled=enabled,
        )

    return definitions


def list_disabled_strategies() -> list[str]:
    """Strategy ids with YAML ``enabled: false`` (T018 explicit disable list)."""
    return sorted(
        sid
        for sid, definition in get_strategy_definitions(include_disabled=True).items()
        if not definition.enabled
    )


def list_enabled_strategies() -> list[str]:
    """Strategy ids with enabled=true (or omitted)."""
    return sorted(
        sid
        for sid, definition in get_strategy_definitions(include_disabled=True).items()
        if definition.enabled
    )


def catalog_hygiene() -> dict[str, Any]:
    """Asset hygiene report: factories vs YAML vs disabled (T018).

    Returns a machine-readable dict suitable for day-session / CI checks.
    ``orphan_yaml`` = YAML strategy.name with no factory (should be empty).
    ``orphan_factory`` = factory keys with no YAML (informational).
    """
    factories = set(_get_factory_registry())
    yaml_ids: set[str] = set()
    disabled: list[str] = []
    enabled: list[str] = []
    for yaml_path in sorted(_STRATEGY_CONFIG_DIR.glob("*.yaml")):
        try:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(raw, dict):
            continue
        strategy_config = raw.get("strategy", {})
        if not isinstance(strategy_config, dict):
            strategy_config = {}
        sid = str(strategy_config.get("name", yaml_path.stem))
        yaml_ids.add(sid)
        is_enabled = bool(strategy_config.get("enabled", True))
        if is_enabled:
            enabled.append(sid)
        else:
            disabled.append(sid)

    orphan_yaml = sorted(yaml_ids - factories)
    orphan_factory = sorted(factories - yaml_ids)
    registered = sorted(yaml_ids & factories)

    return {
        "kind": "catalog_hygiene",
        "task": "T018",
        "yaml_count": len(yaml_ids),
        "factory_count": len(factories),
        "registered": registered,
        "enabled": sorted(enabled),
        "disabled": sorted(disabled),
        "orphan_yaml": orphan_yaml,
        "orphan_factory": orphan_factory,
        "ok": len(orphan_yaml) == 0,
        "note": (
            "disabled strategies remain in catalog with enabled=false; "
            "orphan_yaml must stay empty (no silent skip of YAML assets)"
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
def _load_strategy_config_raw(strategy_id: str) -> dict[str, Any]:
    """Load and cache the YAML configuration for a strategy (internal).

    The cached object is shared across all callers; never return it directly.
    Use ``load_strategy_config`` for a per-call deep copy.
    """
    config_path = get_strategy_definition(strategy_id).config_path
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_strategy_config(strategy_id: str) -> dict[str, Any]:
    """Load the YAML configuration for a strategy.

    Returns a fresh deep copy on every call so callers can mutate the result
    without poisoning the shared ``@cache`` entry (the previous version cached
    and returned the same dict, aliasing nested params/exit/risk into every
    consumer).
    """
    return deepcopy(_load_strategy_config_raw(strategy_id))


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
    description = (
        raw.get("description") or strategy_block.get("description") or definition.description
    )
    return {
        "strategy_id": strategy_id,
        "title": definition.title,
        "description": description,
        "enabled": definition.enabled,
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
