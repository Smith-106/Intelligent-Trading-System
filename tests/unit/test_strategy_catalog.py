from __future__ import annotations

import yaml

from quantflow.strategy.base import StrategyBase
from quantflow.strategy.catalog import (
    _DEFAULT_DESCRIPTIONS,
    _STRATEGY_CONFIG_DIR,
    catalog_hygiene,
    get_strategy_definition,
    get_strategy_definitions,
    get_strategy_factories,
    get_strategy_specs,
    list_disabled_strategies,
    list_enabled_strategies,
    list_strategy_summaries,
)


def test_strategy_catalog_contains_expected_surface() -> None:
    definitions = get_strategy_definitions()
    assert "trend_following" in definitions
    assert "ml_ensemble" in definitions
    # T018: YAML+factory for research prototypes
    assert "ai_factor" in definitions
    assert "spot_perp_arb" in definitions
    assert len(definitions) >= 9


def test_t018_no_orphan_yaml_and_disabled_explicit() -> None:
    hygiene = catalog_hygiene()
    assert hygiene["ok"] is True
    assert hygiene["orphan_yaml"] == []
    disabled = list_disabled_strategies()
    assert "ai_factor" in disabled
    assert "spot_perp_arb" in disabled
    enabled = list_enabled_strategies()
    assert "trend_following" in enabled
    assert "ai_factor" not in enabled
    # Disabled still listed in full catalog
    defs = get_strategy_definitions(include_disabled=True)
    assert defs["ai_factor"].enabled is False
    assert defs["spot_perp_arb"].enabled is False
    # Active-only filter drops them
    active = get_strategy_definitions(include_disabled=False)
    assert "ai_factor" not in active


def test_summarize_exposes_enabled_flag() -> None:
    summaries = {s["strategy_id"]: s for s in list_strategy_summaries()}
    assert summaries["trend_following"]["enabled"] is True
    assert summaries["ai_factor"]["enabled"] is False


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
        assert isinstance(strategy, StrategyBase), (
            f"{strategy_id} factory returned {type(strategy)}"
        )
        assert strategy.name == strategy_id or strategy.name.replace(
            "_", ""
        ) == strategy_id.replace("_", "")


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


# ---------------------------------------------------------------------------
# ISS-010: YAML-driven catalog guard tests
# ---------------------------------------------------------------------------


class TestCatalogYAMLLoading:
    """ISS-010: Verify catalog loads metadata from YAML, not hardcoded Python."""

    def test_all_strategies_have_yaml_metadata(self) -> None:
        """Every strategy YAML must have metadata.title and metadata.description."""
        yaml_files = list(_STRATEGY_CONFIG_DIR.glob("*.yaml"))
        assert len(yaml_files) >= 7, f"Expected >=7 YAML files, found {len(yaml_files)}"
        for yaml_path in yaml_files:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            meta = raw.get("metadata", {})
            assert "title" in meta, f"{yaml_path.name} missing metadata.title"
            assert "description" in meta, f"{yaml_path.name} missing metadata.description"

    def test_all_strategies_have_param_space(self) -> None:
        """Every strategy YAML must have a param_space block."""
        for yaml_path in _STRATEGY_CONFIG_DIR.glob("*.yaml"):
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            assert "param_space" in raw, f"{yaml_path.name} missing param_space"
            assert isinstance(raw["param_space"], dict), (
                f"{yaml_path.name} param_space is not a dict"
            )

    def test_get_strategy_definitions_loads_from_yaml(self) -> None:
        """get_strategy_definitions returns titles matching YAML metadata."""
        defs = get_strategy_definitions()
        assert len(defs) >= 7
        for sid, defn in defs.items():
            assert defn.title, f"{sid} has empty title"
            assert defn.description, f"{sid} has empty description"

    def test_param_space_yaml_matches_original(self) -> None:
        """Guard: YAML param_space values match original hardcoded values."""
        expected_param_spaces = {
            "trend_following": {
                "fast_ma_period": (3, 15),
                "slow_ma_period": (30, 120),
                "rsi_oversold": (20, 40),
                "rsi_overbought": (60, 85),
                "atr_multiplier": (1.2, 3.0),
                "volume_threshold": (0.8, 2.0),
            },
            "mean_reversion": {
                "rsi_oversold": (20, 40),
                "rsi_overbought": (60, 85),
                "bb_std": (1.5, 3.0),
                "exit_rsi_overbought": (50, 75),
                "exit_rsi_oversold": (25, 50),
            },
            "elliott_wave": {
                "zigzag_threshold": (0.02, 0.08),
                "fib_tolerance": (0.10, 0.25),
                "atr_stop_mult": (1.0, 3.0),
            },
            "volatility_breakout": {
                "atr_threshold": (1.2, 2.0),
                "atr_shrink_exit": (0.5, 0.9),
                "volume_threshold": (1.2, 2.0),
            },
            "funding_rate": {
                "entry_threshold": (0.0005, 0.002),
                "exit_threshold": (0.0001, 0.0005),
                "oi_change_threshold": (0.02, 0.1),
            },
            "momentum_rotation": {
                "lookback": (10, 40),
                "top_n": (1, 5),
                "stop_loss_pct": (0.01, 0.05),
            },
            "ml_ensemble": {
                "entry_threshold": (0.5, 0.8),
                "exit_threshold": (0.2, 0.5),
            },
        }
        defs = get_strategy_definitions()
        for sid, expected_ps in expected_param_spaces.items():
            assert sid in defs, f"Strategy {sid} not found in definitions"
            actual_ps = defs[sid].param_space
            for param, expected_range in expected_ps.items():
                assert param in actual_ps, f"{sid} missing param_space key '{param}'"
                actual_range = actual_ps[param]
                assert tuple(actual_range) == expected_range, (
                    f"{sid}.{param} mismatch: got {actual_range}, expected {expected_range}"
                )

    def test_descriptions_match_fallback(self) -> None:
        """YAML descriptions should match _DEFAULT_DESCRIPTIONS."""
        defs = get_strategy_definitions()
        for sid, fallback_desc in _DEFAULT_DESCRIPTIONS.items():
            if sid in defs:
                assert defs[sid].description == fallback_desc, (
                    f"{sid} YAML description '{defs[sid].description}' "
                    f"differs from fallback '{fallback_desc}'"
                )
