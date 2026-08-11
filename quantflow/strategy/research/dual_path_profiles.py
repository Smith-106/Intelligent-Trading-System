"""Load dual-path research profiles (Path A overlay + Path B TPSL).

Research-only. Does not change live/paper strategy defaults or freeze contracts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import yaml

from quantflow.strategy.research.btc_overlay_profiles import PRIMARY, get_profile

_DEFAULT_YAML: Final[Path] = (
    Path(__file__).resolve().parents[2] / "config" / "research" / "dual_path_profiles.yaml"
)

CONTRACT_ID: Final[str] = "DUAL-PATH-RESEARCH-OS-20260811"

# Locked Path B research defaults (aligned with TPSL recommended sweep)
PATH_B_TPSL: Final[dict[str, Any]] = {
    "kind": "discrete_tpsl",
    "name": "tpsl_sl4_tp10_rr25",
    "entry": "dual_ma_lag1",
    "fast": 96,
    "slow": 400,
    "stop_loss_pct": 0.04,
    "take_profit_pct": 0.10,
    "min_rr": 2.5,
    "max_holding_bars": 0,
    "fee": 0.001,
    "slip": 0.001,
}


def default_yaml_path() -> Path:
    return _DEFAULT_YAML


def load_dual_path_profiles(path: Path | str | None = None) -> dict[str, Any]:
    """Load dual-path YAML; fail-closed if missing or malformed."""
    p = Path(path) if path is not None else _DEFAULT_YAML
    if not p.is_file():
        raise FileNotFoundError(f"dual_path profiles not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"dual_path profiles root must be mapping: {p}")
    for key in ("path_a", "path_b", "gates"):
        if key not in raw:
            raise ValueError(f"dual_path profiles missing required key {key!r}")
    if not isinstance(raw["path_a"], dict) or not isinstance(raw["path_b"], dict):
        raise ValueError("path_a and path_b must be mappings")
    return raw


def path_a_profile(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Path A continuous overlay profile (copy)."""
    data = cfg if cfg is not None else load_dual_path_profiles()
    a = dict(data["path_a"])
    # Align with named overlay registry when name matches
    name = str(a.get("name", "primary_w30"))
    try:
        registered = get_profile(name)
        for k in ("mode", "overlay_weight", "fast", "slow", "fee", "slip"):
            if k in registered:
                a[k] = registered[k]
    except KeyError:
        pass
    a["kind"] = "continuous_overlay"
    return a


def path_b_profile(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Path B discrete TPSL profile (copy)."""
    data = cfg if cfg is not None else load_dual_path_profiles()
    b = dict(PATH_B_TPSL)
    b.update(data["path_b"])
    b["kind"] = "discrete_tpsl"
    return b


def assert_aligned_with_primary(path_a: dict[str, Any] | None = None) -> None:
    """Ensure Path A numeric keys match PRIMARY primary_w30."""
    a = path_a if path_a is not None else path_a_profile()
    checks = {
        "overlay_weight": float(PRIMARY["overlay_weight"]),
        "fast": int(PRIMARY["fast"]),
        "slow": int(PRIMARY["slow"]),
        "mode": str(PRIMARY["mode"]),
        "fee": float(PRIMARY["fee"]),
        "slip": float(PRIMARY["slip"]),
    }
    for k, expected in checks.items():
        got = a.get(k)
        if k in ("overlay_weight", "fee", "slip"):
            if abs(float(got) - float(expected)) > 1e-12:
                raise AssertionError(f"path_a.{k}={got!r} != PRIMARY {expected!r}")
        else:
            if got != expected and str(got) != str(expected):
                raise AssertionError(f"path_a.{k}={got!r} != PRIMARY {expected!r}")


def forbid_combined_score_enabled(cfg: dict[str, Any] | None = None) -> bool:
    data = cfg if cfg is not None else load_dual_path_profiles()
    gates = data.get("gates") or {}
    return bool(gates.get("forbid_combined_score", True))
