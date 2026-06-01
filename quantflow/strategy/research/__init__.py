"""QuantFlow strategy research — backtesting and optimization."""

from quantflow.strategy.research.backtest import BacktestEngine, BacktestResult
from quantflow.strategy.research.optimizer import StrategyOptimizer

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "StrategyOptimizer",
]
