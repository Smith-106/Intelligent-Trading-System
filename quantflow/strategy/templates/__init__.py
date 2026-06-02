"""策略模板 - 趋势跟踪、均值回归、波动率突破、资金费率、动量轮动、ML集成。"""

from quantflow.strategy.templates.funding_rate import FundingRateStrategy
from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy
from quantflow.strategy.templates.ml_ensemble import MLEnsembleStrategy
from quantflow.strategy.templates.momentum_rotation import MomentumRotationStrategy
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy
from quantflow.strategy.templates.volatility_breakout import VolatilityBreakoutStrategy

__all__ = [
    "FundingRateStrategy",
    "MLEnsembleStrategy",
    "MeanReversionStrategy",
    "MomentumRotationStrategy",
    "TrendFollowingStrategy",
    "VolatilityBreakoutStrategy",
]
