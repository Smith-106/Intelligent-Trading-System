"""T026: Baseline-3 funding_rate challenger plumbing."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]


def _load():
    path = REPO / "scripts" / "run_baseline3_challenger.py"
    spec = importlib.util.spec_from_file_location("run_baseline3_challenger", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_funding_rate_registered_in_paper_replay():
    from quantflow.strategy.research.paper_replay import STRATEGIES

    assert "funding_rate" in STRATEGIES


def test_align_meta_to_bars_forward_fill():
    mod = _load()
    bars = pd.DataFrame(
        {
            "timestamp": [1000, 2000, 3000, 4000],
            "open": [1, 1, 1, 1],
            "high": [1, 1, 1, 1],
            "low": [1, 1, 1, 1],
            "close": [1, 2, 3, 4],
            "volume": [1, 1, 1, 1],
        }
    )
    funding = pd.DataFrame(
        {"timestamp": [2000, 4000], "funding_rate": [0.002, -0.003]}
    )
    oi = pd.DataFrame({"timestamp": [1000, 3000], "open_interest": [10.0, 12.0]})
    out = mod.align_meta_to_bars(bars, funding, oi)
    assert "funding_rate" in out.columns
    assert "open_interest" in out.columns
    # before first funding → 0 then ffill
    assert float(out.loc[0, "funding_rate"]) == 0.0
    assert float(out.loc[1, "funding_rate"]) == 0.002
    assert float(out.loc[2, "funding_rate"]) == 0.002
    assert float(out.loc[3, "funding_rate"]) == -0.003


def test_make_funding_hook_calls_strategy():
    mod = _load()
    from quantflow.strategy.templates.funding_rate import FundingRateStrategy

    df = pd.DataFrame(
        {
            "timestamp": [1, 2],
            "open": [1, 1],
            "high": [1, 1],
            "low": [1, 1],
            "close": [1, 1],
            "volume": [1, 1],
            "funding_rate": [0.01, -0.01],
            "open_interest": [100.0, 110.0],
        }
    )
    hook = mod.make_funding_hook(df)
    strat = FundingRateStrategy()

    class Sess:
        _strategies = [strat]

    class Row:
        pass

    hook(Sess(), Row())
    assert len(strat._funding_rates) == 1
    assert strat._funding_rates[0] == 0.01
