"""Dual-path research profile freeze tests."""

from __future__ import annotations

import pytest

from quantflow.strategy.research.btc_overlay_profiles import PRIMARY, get_profile
from quantflow.strategy.research.dual_path_profiles import (
    CONTRACT_ID,
    PATH_B_TPSL,
    assert_aligned_with_primary,
    forbid_combined_score_enabled,
    load_dual_path_profiles,
    path_a_profile,
    path_b_profile,
)


def test_load_dual_path_profiles_has_required_keys() -> None:
    cfg = load_dual_path_profiles()
    assert cfg.get("contract") == CONTRACT_ID or "DUAL-PATH" in str(cfg.get("contract", ""))
    assert "path_a" in cfg and "path_b" in cfg and "gates" in cfg
    assert cfg["gates"].get("forbid_combined_score") is True


def test_path_a_matches_primary_w30() -> None:
    a = path_a_profile()
    assert a["name"] == "primary_w30"
    assert a["kind"] == "continuous_overlay"
    assert float(a["overlay_weight"]) == pytest.approx(0.30)
    assert int(a["fast"]) == 96
    assert int(a["slow"]) == 400
    assert a["mode"] == "reduce_off"
    assert float(a["fee"]) == pytest.approx(0.001)
    assert float(a["slip"]) == pytest.approx(0.001)
    reg = get_profile("primary_w30")
    assert float(a["overlay_weight"]) == pytest.approx(float(reg["overlay_weight"]))
    assert_aligned_with_primary(a)
    # PRIMARY registry unchanged
    assert float(PRIMARY["overlay_weight"]) == pytest.approx(0.30)


def test_path_b_tpsl_defaults() -> None:
    b = path_b_profile()
    assert b["kind"] == "discrete_tpsl"
    assert b["entry"] == "dual_ma_lag1"
    assert float(b["stop_loss_pct"]) == pytest.approx(0.04)
    assert float(b["take_profit_pct"]) == pytest.approx(0.10)
    assert float(b["min_rr"]) == pytest.approx(2.5)
    assert int(b["fast"]) == 96
    assert int(b["slow"]) == 400
    assert float(PATH_B_TPSL["stop_loss_pct"]) == pytest.approx(0.04)


def test_forbid_combined_score_gate() -> None:
    assert forbid_combined_score_enabled() is True
