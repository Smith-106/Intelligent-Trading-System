"""策略模板 - 趋势跟踪与均值回归。"""

from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy

__all__ = [
    "MeanReversionStrategy",
    "TrendFollowingStrategy",
]
