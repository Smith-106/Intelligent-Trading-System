"""Tests for Monte Carlo path-level stress testing (deep-research F5 / P1)."""

from __future__ import annotations

import numpy as np
import pytest

from quantflow.strategy.validation.monte_carlo import (
    MonteCarloResult,
    monte_carlo_stress,
    returns_bootstrap_stress,
    trade_shuffle_stress,
)

# A deterministic trade-return stream: a few winners, a few losers, in an
# order where the losers cluster late (so the observed path's max drawdown
# is mild — shuffling can surface a worse ordering).
_TRADE_RETURNS = [0.05, 0.04, 0.03, -0.02, -0.06, 0.02, 0.05, -0.03, 0.04, 0.01]


def test_trade_shuffle_terminal_return_is_invariant() -> None:
    """Permutation preserves the multiset, so terminal return is fixed."""
    res = trade_shuffle_stress(_TRADE_RETURNS, n_paths=50, seed=42)
    assert res.method == "trade_shuffle"
    expected_terminal = float(np.prod([1 + r for r in _TRADE_RETURNS]) - 1.0)
    assert abs(res.observed_terminal_return - expected_terminal) < 1e-9
    # Every shuffled path shares the same terminal return (multiplication
    # commutes). The CLI reads only percentiles; assert the median == expected.
    assert abs(res.p95_terminal_return - expected_terminal) < 1e-9
    assert abs(res.p5_terminal_return - expected_terminal) < 1e-9


def test_trade_shuffle_reproducible_with_seed() -> None:
    a = trade_shuffle_stress(_TRADE_RETURNS, n_paths=20, seed=7)
    b = trade_shuffle_stress(_TRADE_RETURNS, n_paths=20, seed=7)
    assert a.p5_max_drawdown == b.p5_max_drawdown
    assert a.p50_max_drawdown == b.p50_max_drawdown
    assert a.prob_worse_drawdown == b.prob_worse_drawdown


def test_trade_shuffle_different_seeds_differ() -> None:
    a = trade_shuffle_stress(_TRADE_RETURNS, n_paths=200, seed=1)
    b = trade_shuffle_stress(_TRADE_RETURNS, n_paths=200, seed=2)
    # Different RNG seeds produce different drawdown distributions (not a
    # strict inequality on every percentile, but the P5 should differ).
    assert a.p5_max_drawdown != b.p5_max_drawdown


def test_trade_shuffle_worst_case_dd_at_least_observed() -> None:
    """The 5th-percentile drawdown must be at least as deep as the median."""
    res = trade_shuffle_stress(_TRADE_RETURNS, n_paths=200, seed=11)
    # worst-case (P5) is more negative than median (P50)
    assert res.p5_max_drawdown <= res.p50_max_drawdown
    # observed drawdown is one realization, must sit within the band
    assert res.p5_max_drawdown <= res.observed_max_drawdown + 1e-9


def test_returns_bootstrap_terminal_return_varies() -> None:
    """Bootstrap resamples WITH replacement, so terminal return varies."""
    res = returns_bootstrap_stress(_TRADE_RETURNS, n_paths=50, seed=3)
    assert res.method == "returns_bootstrap"
    # P5 < P95 because the multiset differs across paths
    assert res.p5_terminal_return < res.p95_terminal_return


def test_returns_bootstrap_reproducible() -> None:
    a = returns_bootstrap_stress(_TRADE_RETURNS, n_paths=30, seed=5)
    b = returns_bootstrap_stress(_TRADE_RETURNS, n_paths=30, seed=5)
    assert a.p5_max_drawdown == b.p5_max_drawdown
    assert a.n_paths == 30


def test_prob_worse_drawdown_in_unit_interval() -> None:
    res = trade_shuffle_stress(_TRADE_RETURNS, n_paths=100, seed=9)
    assert 0.0 <= res.prob_worse_drawdown <= 1.0


def test_keep_paths_returns_equity_arrays() -> None:
    res = trade_shuffle_stress(_TRADE_RETURNS, n_paths=10, seed=1, keep_paths=True)
    assert len(res.paths) == 10
    assert all(len(p) == len(_TRADE_RETURNS) + 1 for p in res.paths)


def test_keep_paths_default_empty() -> None:
    res = trade_shuffle_stress(_TRADE_RETURNS, n_paths=10, seed=1)
    assert res.paths == []


def test_monte_carlo_stress_runs_both_when_both_given() -> None:
    results = monte_carlo_stress(
        trade_returns=_TRADE_RETURNS,
        bar_returns=_TRADE_RETURNS,
        n_paths=20,
        seed=1,
    )
    assert len(results) == 2
    methods = {r.method for r in results}
    assert methods == {"trade_shuffle", "returns_bootstrap"}


def test_monte_carlo_stress_skips_missing_input() -> None:
    only_trade = monte_carlo_stress(trade_returns=_TRADE_RETURNS, n_paths=10, seed=1)
    assert len(only_trade) == 1
    assert only_trade[0].method == "trade_shuffle"

    only_bar = monte_carlo_stress(bar_returns=_TRADE_RETURNS, n_paths=10, seed=1)
    assert len(only_bar) == 1
    assert only_bar[0].method == "returns_bootstrap"

    empty = monte_carlo_stress(n_paths=10, seed=1)
    assert empty == []


def test_insufficient_returns_skipped() -> None:
    """A single return cannot seed either resampler — both are skipped."""
    results = monte_carlo_stress(trade_returns=[0.05], bar_returns=[0.05], n_paths=5, seed=1)
    assert results == []


def test_summary_contains_band_info() -> None:
    res = trade_shuffle_stress(_TRADE_RETURNS, n_paths=20, seed=1)
    s = res.summary()
    assert "MC stress" in s
    assert "P5 dd" in s
    assert "P(path worse than observed dd)" in s


def test_nan_returns_filtered() -> None:
    """NaN entries must not break the resamplers."""
    with_nan = [0.05, float("nan"), -0.02, 0.04, float("nan"), 0.03]
    res = trade_shuffle_stress(with_nan, n_paths=10, seed=1)
    assert isinstance(res, MonteCarloResult)
    assert res.n_paths == 10


@pytest.mark.slow
def test_large_n_paths_runs_and_bounds_hold() -> None:
    res = trade_shuffle_stress(_TRADE_RETURNS, n_paths=2000, seed=1)
    assert res.n_paths == 2000
    # With many paths the worst-case band is statistically stable and must
    # bracket the observed single-path drawdown.
    assert res.p5_max_drawdown <= res.observed_max_drawdown + 1e-9
