"""P0 regression guard — ensures backtest outputs remain byte-for-byte stable.

Loads the baseline produced by ``scripts/establish_p0_baseline.py`` from
``.workflow/artifacts/p0-baseline/test-results.json``, re-runs the same 4
strategies with identical parameters, and compares every metric at
``rel=1e-9`` precision.  Signal hashes are compared byte-for-byte.

The test is marked ``@pytest.mark.slow`` and skips gracefully when the
baseline file is absent (CI safety — the baseline artifact is committed
separately).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from quantflow.data.store import DataStore
from quantflow.strategy.catalog import get_strategy_definitions
from quantflow.strategy.research.backtest import BacktestEngine

BASELINE_PATH = Path(".workflow/artifacts/p0-baseline/test-results.json")

INITIAL_CAPITAL = 100_000.0
FEE = 0.001
SYMBOL = "BTC/USDT"


# ---------------------------------------------------------------------------
# Helpers (duplicated from establish_p0_baseline.py to keep the test
# self-contained — no import of scripts/ modules).
# ---------------------------------------------------------------------------


def _hash_series(s: pd.Series) -> str:
    raw = json.dumps(s.tolist(), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _hash_trade_returns(returns: list[float]) -> str:
    raw = json.dumps([f"{r:.15g}" for r in returns])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _load_bars() -> pd.DataFrame:
    store = DataStore("./data/parquet", ":memory:")
    try:
        # Pin to 1h so multi-TF co-resident partitions do not mix intervals.
        df = store.query(SYMBOL, timeframe="1h")
        if df.empty:
            df = store.query(SYMBOL)
    finally:
        store.close()
    return df


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def baseline() -> dict:
    """Load baseline JSON, skip test if missing."""
    if not BASELINE_PATH.exists():
        pytest.skip(f"Baseline file not found: {BASELINE_PATH}")
    with open(BASELINE_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def bars() -> pd.DataFrame:
    """Load BTC/USDT parquet data once per module."""
    df = _load_bars()
    if df.empty:
        pytest.skip("No BTC/USDT parquet data available")
    return df


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

STRATEGIES = [
    "trend_following",
    "volatility_breakout",
    "mean_reversion",
    "momentum_rotation",
]


@pytest.mark.slow
@pytest.mark.parametrize("strategy_name", STRATEGIES)
def test_strategy_regression_guard(baseline: dict, bars: pd.DataFrame, strategy_name: str) -> None:
    """Verify strategy backtest outputs match baseline byte-for-byte."""
    expected = baseline["strategies"][strategy_name]

    # Re-run backtest with identical parameters
    definitions = get_strategy_definitions()
    strategy = definitions[strategy_name].factory()
    entries, exits = strategy.generate_signals(bars)

    engine = BacktestEngine()
    result = engine.run_backtest(
        close=bars["close"],
        entries=entries,
        exits=exits,
        initial_capital=INITIAL_CAPITAL,
        fee=FEE,
        strategy_id=strategy_name,
        symbol=SYMBOL,
    )

    # Float metrics — high precision (rel=1e-9 safe across platforms)
    assert result.total_return == pytest.approx(expected["total_return"], rel=1e-9), (
        f"total_return drifted: {result.total_return} vs {expected['total_return']}"
    )
    assert result.sharpe_ratio == pytest.approx(expected["sharpe_ratio"], rel=1e-9), (
        f"sharpe_ratio drifted: {result.sharpe_ratio} vs {expected['sharpe_ratio']}"
    )
    assert result.max_drawdown == pytest.approx(expected["max_drawdown"], rel=1e-9), (
        f"max_drawdown drifted: {result.max_drawdown} vs {expected['max_drawdown']}"
    )
    assert result.win_rate == pytest.approx(expected["win_rate"], rel=1e-9), (
        f"win_rate drifted: {result.win_rate} vs {expected['win_rate']}"
    )
    assert result.profit_factor == pytest.approx(expected["profit_factor"], rel=1e-9), (
        f"profit_factor drifted: {result.profit_factor} vs {expected['profit_factor']}"
    )
    assert result.annual_return == pytest.approx(expected["annual_return"], rel=1e-9), (
        f"annual_return drifted: {result.annual_return} vs {expected['annual_return']}"
    )
    assert result.sortino_ratio == pytest.approx(expected["sortino_ratio"], rel=1e-9), (
        f"sortino_ratio drifted: {result.sortino_ratio} vs {expected['sortino_ratio']}"
    )
    assert result.final_capital == pytest.approx(expected["final_capital"], rel=1e-9), (
        f"final_capital drifted: {result.final_capital} vs {expected['final_capital']}"
    )

    # Integer metrics — exact comparison
    assert result.num_trades == expected["num_trades"], (
        f"num_trades drifted: {result.num_trades} vs {expected['num_trades']}"
    )
    entry_count = int(entries.sum())
    exit_count = int(exits.sum())
    assert entry_count == expected["entry_count"], (
        f"entry_count drifted: {entry_count} vs {expected['entry_count']}"
    )
    assert exit_count == expected["exit_count"], (
        f"exit_count drifted: {exit_count} vs {expected['exit_count']}"
    )

    # Signal hashes — strict byte-for-byte
    entry_hash = _hash_series(entries.astype(bool))
    exit_hash = _hash_series(exits.astype(bool))
    assert entry_hash == expected["entry_signal_hash"], (
        f"Entry signal sequence changed for {strategy_name}"
    )
    assert exit_hash == expected["exit_signal_hash"], (
        f"Exit signal sequence changed for {strategy_name}"
    )

    # Trade returns hash — strict byte-for-byte
    trade_hash = _hash_trade_returns(result.trade_returns)
    assert trade_hash == expected["trade_returns_hash"], (
        f"Trade returns sequence changed for {strategy_name}"
    )
