"""Named BTC overlay profiles and primary defaults."""

from __future__ import annotations

from quantflow.common.config import BookRiskBudgetConfig, load_config
from quantflow.strategy.research.btc_overlay_profiles import (
    PRIMARY,
    PROFILES,
    get_profile,
    primary_eval_kwargs,
)


def test_primary_profile_weight_and_ma() -> None:
    p = get_profile("primary_w30")
    assert p["mode"] == "reduce_off"
    assert p["overlay_weight"] == 0.30
    assert p["fast"] == 96
    assert p["slow"] == 400
    assert primary_eval_kwargs()["overlay_weight"] == 0.30


def test_profiles_registry() -> None:
    assert "legacy_w25" in PROFILES
    assert "defensive_dd35" in PROFILES
    assert PRIMARY["name"] == "primary_w30"


def test_book_risk_budget_default_overlay_sleeve() -> None:
    cfg = BookRiskBudgetConfig()
    assert cfg.overlay_sleeve == 0.30
    assert cfg.enabled is False


def test_default_yaml_overlay_sleeve() -> None:
    app = load_config("quantflow/config/default.yaml")
    assert app.risk.book_risk_budget.overlay_sleeve == 0.30
