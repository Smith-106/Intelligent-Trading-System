"""Monte Carlo path-level stress testing (deep-research F5 / P1).

Two resampling strategies probe path-fragility beyond the single observed
backtest path:

1. **Trade-shuffle** — randomly permute the ORDER of closed-trade returns and
   rebuild the equity path. The aggregate return is invariant, but the
   *path* (and thus drawdown) varies. This stress-tests sequencing risk:
   "what if the losers had clustered early?" Worst-case drawdown under
   shuffled ordering bounds how badly the strategy can be mauled by an
   unfavourable trade sequence — independent of any return distribution
   assumption.

2. **Returns-bootstrap** — resample the bar-level (or trade-level) returns
   WITH replacement to construct synthetic paths of the same length, then
   read off the drawdown / terminal-return distribution. This estimates the
   sampling distribution of the performance statistics themselves.

Both are DIAGNOSTIC, not gates: they report a worst-case percentile band so
the operator can sanity-check that the live-deployable edge is not a single
lucky path. They never alter the GO/NO-GO decision of validation_gate
(historical CVaR remains the risk gate; see risk_engine).

CLI: ``quantflow validate --strategy <name> --method stress``
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Stable, reproducible RNG. Callers pass an explicit seed; the module never
# touches the global numpy RNG state (which would pollute the backtest).
_DEFAULT_SEED = 0


@dataclass(frozen=True)
class MonteCarloResult:
    """Outcome of a Monte Carlo stress run.

    All percentile fields are fractions (e.g. 0.35 = 35%). max_drawdown and
    terminal_return are signed; the rest are non-negative fractions.
    """

    n_paths: int
    # Observed (single-path) statistics for reference.
    observed_max_drawdown: float
    observed_terminal_return: float
    # Worst-case (5th-percentile) drawdown across resampled paths: the
    # deepest hole the strategy can fall into under an unlucky ordering.
    p5_max_drawdown: float
    # Median drawdown across resampled paths.
    p50_max_drawdown: float
    # 5th-percentile terminal return: only 5% of paths ended worse than this.
    p5_terminal_return: float
    # 95th-percentile terminal return: only 5% of paths ended better.
    p95_terminal_return: float
    # Fraction of resampled paths whose max drawdown is WORSE (deeper) than
    # the observed path. A high value (e.g. >0.5) means the observed path was
    # unusually lucky — a path-fragility red flag.
    prob_worse_drawdown: float
    method: str  # "trade_shuffle" | "returns_bootstrap"
    paths: list[np.ndarray] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"MC stress ({self.method}, n={self.n_paths}):\n"
            f"  observed max_dd={self.observed_max_drawdown:.4f}, "
            f"terminal={self.observed_terminal_return:.4f}\n"
            f"  path band: P5 dd={self.p5_max_drawdown:.4f}, "
            f"P50 dd={self.p50_max_drawdown:.4f}\n"
            f"  terminal band: P5={self.p5_terminal_return:.4f}, "
            f"P95={self.p95_terminal_return:.4f}\n"
            f"  P(path worse than observed dd)={self.prob_worse_drawdown:.3f}"
        )


def _equity_from_returns(returns: np.ndarray, initial_capital: float) -> np.ndarray:
    """Cumulate a return series into an equity path."""
    equity = np.empty(len(returns) + 1, dtype=float)
    equity[0] = initial_capital
    for i, r in enumerate(returns):
        equity[i + 1] = equity[i] * (1.0 + r)
    return equity


def _max_drawdown(equity: np.ndarray) -> float:
    """Most negative peak-to-trough drop of an equity path (signed < 0)."""
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    return float(dd.min())


def _percentile(arr: np.ndarray, q: float) -> float:
    if len(arr) == 0:
        return 0.0
    return float(np.percentile(arr, q))


def _summarize(
    observed_equity: np.ndarray,
    path_max_dds: np.ndarray,
    path_terminals: np.ndarray,
    method: str,
    paths: list[np.ndarray],
) -> MonteCarloResult:
    observed_dd = _max_drawdown(observed_equity)
    observed_term = float(
        (observed_equity[-1] / observed_equity[0] - 1.0) if len(observed_equity) > 1 else 0.0
    )
    # "worse drawdown" = more negative than observed
    worse = float(np.mean(path_max_dds < observed_dd))
    return MonteCarloResult(
        n_paths=len(path_max_dds),
        observed_max_drawdown=observed_dd,
        observed_terminal_return=observed_term,
        p5_max_drawdown=_percentile(path_max_dds, 5),
        p50_max_drawdown=_percentile(path_max_dds, 50),
        p5_terminal_return=_percentile(path_terminals, 5),
        p95_terminal_return=_percentile(path_terminals, 95),
        prob_worse_drawdown=worse,
        method=method,
        paths=paths,
    )


def trade_shuffle_stress(
    trade_returns: pd.Series | np.ndarray | list[float],
    n_paths: int = 1000,
    initial_capital: float = 10000.0,
    seed: int = _DEFAULT_SEED,
    keep_paths: bool = False,
) -> MonteCarloResult:
    """Resample by permuting closed-trade return ORDER.

    Permutation (not bootstrap): the multiset of trade returns is preserved,
    so the terminal return is invariant across paths. Only the path — and
    hence the drawdown — varies. This isolates sequencing risk from edge
    magnitude.

    Args:
        trade_returns: per-trade realized returns (fractions). Must be the
            returns of CLOSED trades, in chronological order.
        n_paths: number of permuted paths to simulate.
        initial_capital: starting equity for each path.
        seed: deterministic RNG seed (module never touches global state).
        keep_paths: if True, store every simulated equity path in the result
            (memory-heavy for large n_paths; default False).
    """
    r = np.asarray(trade_returns, dtype=float)
    r = r[~np.isnan(r)]
    observed_equity = _equity_from_returns(r, initial_capital)

    rng = np.random.default_rng(seed)
    path_max_dds = np.empty(n_paths, dtype=float)
    path_terminals = np.empty(n_paths, dtype=float)
    paths: list[np.ndarray] = []
    for i in range(n_paths):
        perm = rng.permutation(r)
        eq = _equity_from_returns(perm, initial_capital)
        path_max_dds[i] = _max_drawdown(eq)
        path_terminals[i] = eq[-1] / eq[0] - 1.0
        if keep_paths:
            paths.append(eq)
    return _summarize(observed_equity, path_max_dds, path_terminals, "trade_shuffle", paths)


def returns_bootstrap_stress(
    returns: pd.Series | np.ndarray | list[float],
    n_paths: int = 1000,
    initial_capital: float = 10000.0,
    seed: int = _DEFAULT_SEED,
    keep_paths: bool = False,
) -> MonteCarloResult:
    """Resample bar/trade returns WITH replacement (nonparametric bootstrap).

    Unlike trade_shuffle, the terminal return VARIES across paths because
    the resampled multiset differs. This estimates the sampling distribution
    of the performance statistics (drawdown + terminal return) under an
    i.i.d. assumption on the return stream.

    Args:
        returns: bar-level or trade-level returns (fractions), chronological.
        n_paths: number of bootstrap paths.
        initial_capital: starting equity for each path.
        seed: deterministic RNG seed.
        keep_paths: store every path (memory-heavy; default False).
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    observed_equity = _equity_from_returns(r, initial_capital)

    rng = np.random.default_rng(seed)
    n = len(r)
    path_max_dds = np.empty(n_paths, dtype=float)
    path_terminals = np.empty(n_paths, dtype=float)
    paths: list[np.ndarray] = []
    for i in range(n_paths):
        idx = rng.integers(0, n, size=n)  # with replacement
        sample = r[idx]
        eq = _equity_from_returns(sample, initial_capital)
        path_max_dds[i] = _max_drawdown(eq)
        path_terminals[i] = eq[-1] / eq[0] - 1.0
        if keep_paths:
            paths.append(eq)
    return _summarize(observed_equity, path_max_dds, path_terminals, "returns_bootstrap", paths)


def monte_carlo_stress(
    trade_returns: pd.Series | np.ndarray | list[float] | None = None,
    bar_returns: pd.Series | np.ndarray | list[float] | None = None,
    n_paths: int = 1000,
    initial_capital: float = 10000.0,
    seed: int = _DEFAULT_SEED,
    keep_paths: bool = False,
) -> list[MonteCarloResult]:
    """Run both stress strategies and return all available results.

    At least one of ``trade_returns`` (for trade-shuffle) or ``bar_returns``
    (for returns-bootstrap) must be provided. Missing inputs skip the
    corresponding strategy rather than raising, so callers can run whichever
    resampling is meaningful for their data shape.
    """
    results: list[MonteCarloResult] = []
    if trade_returns is not None and len(np.asarray(trade_returns, dtype=float)) >= 2:
        results.append(
            trade_shuffle_stress(
                trade_returns,
                n_paths=n_paths,
                initial_capital=initial_capital,
                seed=seed,
                keep_paths=keep_paths,
            )
        )
    if bar_returns is not None and len(np.asarray(bar_returns, dtype=float)) >= 2:
        results.append(
            returns_bootstrap_stress(
                bar_returns,
                n_paths=n_paths,
                initial_capital=initial_capital,
                seed=seed,
                keep_paths=keep_paths,
            )
        )
    return results
