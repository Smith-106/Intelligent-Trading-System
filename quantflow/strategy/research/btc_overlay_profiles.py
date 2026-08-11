"""Named BTC beta+overlay research profiles (product bar vs HODL).

Selected 2026-08-11 on pin window with taker costs (fee+slip=10bp each) and
checked on 2025 OOS / 2022 bear slices. Not a pure walk-forward claim.
"""

from __future__ import annotations

from typing import Any, Final

# Prior fixed default (goal-highflyer evidence 2026-08-10)
LEGACY_W25: Final[dict[str, Any]] = {
    "name": "legacy_w25",
    "mode": "reduce_off",
    "overlay_weight": 0.25,
    "fast": 96,
    "slow": 400,
    "fee": 0.001,
    "slip": 0.001,
    "dd_throttle": 0.0,
    "dd_floor_scale": 1.0,
    "vol_target": 0.0,
    "hysteresis": 0.0,
}

# Primary: higher excess + slightly lower maxDD vs legacy on full pin + OOS 2025
PRIMARY: Final[dict[str, Any]] = {
    "name": "primary_w30",
    "mode": "reduce_off",
    "overlay_weight": 0.30,
    "fast": 96,
    "slow": 400,
    "fee": 0.001,
    "slip": 0.001,
    "dd_throttle": 0.0,
    "dd_floor_scale": 1.0,
    "vol_target": 0.0,
    "hysteresis": 0.0,
    "notes": (
        "Full pin excess +47.09pp maxDD 69.47% vs HODL 77.19%; "
        "OOS 2025 excess +9.14pp; bear 2022 excess +8.60pp."
    ),
}

# Defensive: DD throttle after 35% equity DD (accepts lower full-window excess)
DEFENSIVE: Final[dict[str, Any]] = {
    "name": "defensive_dd35",
    "mode": "reduce_off",
    "overlay_weight": 0.30,
    "fast": 96,
    "slow": 400,
    "fee": 0.001,
    "slip": 0.001,
    "dd_throttle": 0.35,
    "dd_floor_scale": 0.50,
    "vol_target": 0.0,
    "hysteresis": 0.0,
    "notes": (
        "Full pin maxDD ~66.5% excess ~+24pp; may fail IS excess in strong bulls "
        "when throttle cuts beta early — use only when DD priority > excess."
    ),
}

PROFILES: Final[dict[str, dict[str, Any]]] = {
    LEGACY_W25["name"]: LEGACY_W25,
    PRIMARY["name"]: PRIMARY,
    DEFENSIVE["name"]: DEFENSIVE,
}


def get_profile(name: str = "primary_w30") -> dict[str, Any]:
    """Return a copy of a named profile or raise KeyError."""
    if name not in PROFILES:
        raise KeyError(f"unknown profile {name!r}; choose from {sorted(PROFILES)}")
    return dict(PROFILES[name])


def primary_eval_kwargs() -> dict[str, Any]:
    """Kwargs for run_btc_beta_overlay_eval / CLI defaults."""
    p = PRIMARY
    return {
        "mode": p["mode"],
        "overlay_weight": float(p["overlay_weight"]),
        "fast": int(p["fast"]),
        "slow": int(p["slow"]),
        "fee": float(p["fee"]),
        "slip": float(p["slip"]),
    }
