"""QuantFlow strategy validation — anti-overfitting verification pipeline."""

from quantflow.strategy.validation.cpcv import cpcv_backtest, split_cpcv
from quantflow.strategy.validation.dsr import deflated_sharpe_ratio
from quantflow.strategy.validation.gate import validation_gate
from quantflow.strategy.validation.lookahead import (
    LookaheadFinding,
    LookaheadReport,
    scan_strategies,
    scan_strategy,
)
from quantflow.strategy.validation.monte_carlo import (
    MonteCarloResult,
    monte_carlo_stress,
    returns_bootstrap_stress,
    trade_shuffle_stress,
)
from quantflow.strategy.validation.pbo import probability_of_overfitting
from quantflow.strategy.validation.wfo import walk_forward_optimization

__all__ = [
    "LookaheadFinding",
    "LookaheadReport",
    "MonteCarloResult",
    "cpcv_backtest",
    "deflated_sharpe_ratio",
    "monte_carlo_stress",
    "probability_of_overfitting",
    "returns_bootstrap_stress",
    "scan_strategies",
    "scan_strategy",
    "split_cpcv",
    "trade_shuffle_stress",
    "validation_gate",
    "walk_forward_optimization",
]
