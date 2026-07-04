from __future__ import annotations

from quantflow.strategy.base import StrategyBase
from quantflow.strategy.catalog import (
    get_strategy_definition,
    get_strategy_definitions,
    get_strategy_factories,
    get_strategy_specs,
    list_strategy_summaries,
)


def test_strategy_catalog_contains_expected_surface() -> None:
    definitions = get_strategy_definitions()
    assert "trend_following" in definitions
    assert "ml_ensemble" in definitions
    assert len(definitions) >= 7


def test_strategy_summary_exposes_business_metadata() -> None:
    summary = next(
        item for item in list_strategy_summaries() if item["strategy_id"] == "trend_following"
    )
    assert summary["default_symbol"] == "BTC/USDT"
    assert summary["timeframe"] == "1d"
    assert "params" in summary
    assert "exit" in summary


def test_strategy_specs_match_definition_factory() -> None:
    definition = get_strategy_definition("mean_reversion")
    factory, param_space = get_strategy_specs()["mean_reversion"]
    assert factory is definition.factory
    assert "bb_std" in param_space


def test_all_factories_produce_strategy_base_instances() -> None:
    """Each factory in the catalog should produce a valid StrategyBase instance."""
    factories = get_strategy_factories()
    for strategy_id, factory in factories.items():
        strategy = factory()
        assert isinstance(strategy, StrategyBase), f"{strategy_id} factory returned {type(strategy)}"
        assert strategy.name == strategy_id or strategy.name.replace("_", "") == strategy_id.replace("_", "")


def test_factory_with_custom_params() -> None:
    """Factory should accept custom parameters."""
    factory = get_strategy_factories()["trend_following"]
    strategy = factory({"fast_ma_period": 5})
    assert isinstance(strategy, StrategyBase)


def test_strategy_factories_exposes_all_ids() -> None:
    """get_strategy_factories should cover all strategy IDs."""
    factories = get_strategy_factories()
    definitions = get_strategy_definitions()
    assert set(factories.keys()) == set(definitions.keys())
