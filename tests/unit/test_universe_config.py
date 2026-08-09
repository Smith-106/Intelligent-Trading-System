"""T019: universe YAML + admitted pool."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from quantflow.strategy.research.universe_config import (
    admitted_symbols,
    baseline_default_symbols,
    candidate_symbols,
    load_universe_config,
    write_admitted,
)


def test_load_repo_universe_yaml():
    cfg = load_universe_config()
    assert cfg.get("_missing") is False
    assert "BTC/USDT" in baseline_default_symbols(cfg)
    cands = candidate_symbols(cfg)
    assert "BTC/USDT" in cands


def test_admitted_filters_sla_fail(tmp_path: Path, monkeypatch):
    # Use tmp as repo root with universe.yaml + admitted.json
    cfg_dir = tmp_path / "quantflow" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "universe.yaml").write_text(
        yaml.safe_dump(
            {
                "baseline_default": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
                "candidates": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"],
            }
        ),
        encoding="utf-8",
    )
    adm = {
        "symbols": ["BTC/USDT", "ETH/USDT", "XRP/USDT"],
        "sla": [
            {"symbol": "BTC/USDT", "sla_pass": True},
            {"symbol": "ETH/USDT", "sla_pass": True},
            {"symbol": "XRP/USDT", "sla_pass": False},
        ],
    }
    write_admitted(adm, repo_root=tmp_path)

    # baseline book = admitted ∩ baseline_default ∩ sla_pass
    book = admitted_symbols(repo_root=tmp_path, intersect_baseline_default=True)
    assert "BTC/USDT" in book
    assert "ETH/USDT" in book
    assert "XRP/USDT" not in book
    assert "SOL/USDT" not in book  # not in admitted pass list

    # expansion book (no intersect)
    expand = admitted_symbols(repo_root=tmp_path, intersect_baseline_default=False)
    assert "XRP/USDT" not in expand  # sla fail stripped
    assert set(expand) >= {"BTC/USDT", "ETH/USDT"}


def test_cold_start_without_admitted_uses_baseline(tmp_path: Path):
    cfg_dir = tmp_path / "quantflow" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "universe.yaml").write_text(
        yaml.safe_dump(
            {
                "baseline_default": ["BTC/USDT", "ETH/USDT"],
                "candidates": ["BTC/USDT", "ETH/USDT", "DOGE/USDT"],
            }
        ),
        encoding="utf-8",
    )
    book = admitted_symbols(repo_root=tmp_path)
    assert book == ["BTC/USDT", "ETH/USDT"]


def test_require_sla_file_fail_closed(tmp_path: Path):
    cfg_dir = tmp_path / "quantflow" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "universe.yaml").write_text(
        yaml.safe_dump({"baseline_default": ["BTC/USDT"], "candidates": ["BTC/USDT"]}),
        encoding="utf-8",
    )
    assert admitted_symbols(repo_root=tmp_path, require_sla_file=True) == []
