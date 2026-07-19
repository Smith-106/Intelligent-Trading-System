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
from quantflow.strategy.validation.pbo import probability_of_overfitting
from quantflow.strategy.validation.wfo import walk_forward_optimization

__all__ = [
    "LookaheadFinding",
    "LookaheadReport",
    "cpcv_backtest",
    "deflated_sharpe_ratio",
    "probability_of_overfitting",
    "scan_strategies",
    "scan_strategy",
    "split_cpcv",
    "validation_gate",
    "walk_forward_optimization",
]
