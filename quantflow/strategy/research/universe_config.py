"""Universe list YAML loader (T019).

Canonical file: ``quantflow/config/universe.yaml``.
Runtime admitted pool: ``data/paper_replay/universe/admitted.json`` (written by
``universe_expand_pipeline --write-admitted`` after SLA pass).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIVERSE_YAML = _PACKAGE_ROOT / "config" / "universe.yaml"
DEFAULT_ADMITTED_JSON = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "paper_replay"
    / "universe"
    / "admitted.json"
)
# Fallback when package layout differs (editable install vs repo root).
_REPO_ADMITTED = Path(__file__).resolve().parents[3] / "data" / "paper_replay" / "universe" / "admitted.json"

FALLBACK_BASELINE = ("BTC/USDT", "ETH/USDT", "SOL/USDT")


def _repo_root() -> Path:
    # quantflow/strategy/research → repo root is parents[3]
    return Path(__file__).resolve().parents[3]


def default_universe_path(repo_root: Path | None = None) -> Path:
    root = repo_root or _repo_root()
    return root / "quantflow" / "config" / "universe.yaml"


def default_admitted_path(repo_root: Path | None = None) -> Path:
    root = repo_root or _repo_root()
    return root / "data" / "paper_replay" / "universe" / "admitted.json"


def load_universe_config(
    path: Path | str | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Load universe.yaml; returns empty-structure dict if missing."""
    p = Path(path) if path else default_universe_path(repo_root)
    if not p.is_file():
        return {
            "version": 0,
            "baseline_default": list(FALLBACK_BASELINE),
            "candidates": list(FALLBACK_BASELINE),
            "watchlist": [],
            "sla": {
                "min_bars": 500,
                "max_bar_age_hours": 48.0,
                "min_quality": 0.7,
                "timeframe": "1h",
            },
            "_missing": True,
            "_path": str(p),
        }
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"universe config is not a mapping: {p}")
    raw["_path"] = str(p)
    raw["_missing"] = False
    return raw


def _as_symbol_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict) and item.get("symbol"):
                out.append(str(item["symbol"]).strip())
        return out
    return []


def candidate_symbols(
    config: dict[str, Any] | None = None,
    *,
    include_watchlist: bool = False,
    repo_root: Path | None = None,
) -> list[str]:
    cfg = config if config is not None else load_universe_config(repo_root=repo_root)
    symbols = _as_symbol_list(cfg.get("candidates"))
    if include_watchlist:
        symbols = symbols + _as_symbol_list(cfg.get("watchlist"))
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out or list(FALLBACK_BASELINE)


def baseline_default_symbols(
    config: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> list[str]:
    cfg = config if config is not None else load_universe_config(repo_root=repo_root)
    symbols = _as_symbol_list(cfg.get("baseline_default"))
    return symbols or list(FALLBACK_BASELINE)


def load_admitted(
    path: Path | str | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any] | None:
    p = Path(path) if path else default_admitted_path(repo_root)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def admitted_symbols(
    *,
    repo_root: Path | None = None,
    require_sla_file: bool = False,
    intersect_baseline_default: bool = True,
) -> list[str]:
    """Symbols allowed in default multi-symbol Baseline book.

    Prefer runtime ``admitted.json`` (SLA-pass only). If missing:
      - ``require_sla_file=True`` → empty list (fail-closed for expand ops)
      - else → ``baseline_default`` from YAML (cold start).

    When ``intersect_baseline_default`` is True (default for Baseline-0 runners),
    admitted symbols outside YAML baseline_default are kept only if present in
    admitted **and** we are not restricting — actually T019 rule:

      *Default baseline book* = admitted ∩ baseline_default
        (if admitted file exists)
      *Expansion book* = full admitted list (use ``intersect_baseline_default=False``)
    """
    cfg = load_universe_config(repo_root=repo_root)
    baseline = baseline_default_symbols(cfg, repo_root=repo_root)
    adm = load_admitted(repo_root=repo_root)
    if adm is None:
        if require_sla_file:
            return []
        return baseline

    symbols = _as_symbol_list(adm.get("symbols") or adm.get("admitted"))
    # Only keep sla_pass entries if detailed rows present
    rows = adm.get("sla")
    if isinstance(rows, list) and rows:
        passed = {
            str(r.get("symbol"))
            for r in rows
            if isinstance(r, dict) and r.get("sla_pass") and r.get("symbol")
        }
        if passed:
            symbols = [s for s in symbols if s in passed] or [s for s in baseline if s in passed]

    if not symbols:
        return [] if require_sla_file else baseline

    if intersect_baseline_default:
        base_set = set(baseline)
        filtered = [s for s in symbols if s in base_set]
        # If intersection empty but admitted exists, fail soft to baseline only
        # when those baseline symbols themselves passed — else baseline fallback.
        return filtered or baseline
    return symbols


def write_admitted(
    payload: dict[str, Any],
    *,
    repo_root: Path | None = None,
    path: Path | str | None = None,
) -> Path:
    """Persist admitted pool (SLA-pass symbols only)."""
    out = Path(path) if path else default_admitted_path(repo_root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def baseline_symbols_csv(
    *,
    repo_root: Path | None = None,
    intersect_baseline_default: bool = True,
) -> str:
    """Comma-separated book for CLI/scripts (T019 consumers)."""
    return ",".join(
        admitted_symbols(
            repo_root=repo_root,
            intersect_baseline_default=intersect_baseline_default,
        )
    )
