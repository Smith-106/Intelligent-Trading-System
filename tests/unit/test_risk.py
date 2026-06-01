"""Unit tests for risk engine and position sizer."""


from quantflow.common.config import RiskConfig
from quantflow.common.models import Direction, Portfolio, Position, Signal
from quantflow.signal.position_sizer import PositionSizer
from quantflow.signal.risk_engine import RiskEngine


class TestRiskEngine:
    def test_passes_normal_signal(self):
        cfg = RiskConfig()
        engine = RiskEngine(cfg)
        portfolio = Portfolio(cash=100000)
        signal = Signal(strategy_id="t", symbol="BTC/USDT", direction=Direction.LONG,
                        strength=0.8, price=42000, timestamp=0)
        result = engine.check(signal, portfolio)
        assert result.passed

    def test_blocks_max_positions(self):
        cfg = RiskConfig(max_positions=2)
        engine = RiskEngine(cfg)
        portfolio = Portfolio(cash=100000, positions={
            "BTC/USDT": Position(symbol="BTC/USDT", quantity=1, entry_price=40000, current_price=42000),
            "ETH/USDT": Position(symbol="ETH/USDT", quantity=10, entry_price=2000, current_price=2200),
        })
        signal = Signal(strategy_id="t", symbol="SOL/USDT", direction=Direction.LONG,
                        strength=0.8, price=100, timestamp=0)
        result = engine.check(signal, portfolio)
        assert not result.passed
        assert result.reason == "max_positions"

    def test_blocks_drawdown_breach(self):
        cfg = RiskConfig(max_drawdown=-0.10)
        engine = RiskEngine(cfg)
        portfolio = Portfolio(cash=100000)
        portfolio.current_drawdown = -0.15
        signal = Signal(strategy_id="t", symbol="BTC/USDT", direction=Direction.LONG,
                        strength=0.8, price=42000, timestamp=0)
        result = engine.check(signal, portfolio)
        assert not result.passed
        assert result.reason == "max_drawdown"


class TestPositionSizer:
    def test_kelly_size(self):
        sizer = PositionSizer(method="kelly", kelly_fraction=0.5)
        portfolio = Portfolio(cash=100000)
        signal = Signal(strategy_id="t", symbol="BTC/USDT", direction=Direction.LONG,
                        strength=0.8, price=42000, timestamp=0)
        size = sizer.size(signal, portfolio, win_rate=0.55, win_loss_ratio=2.0)
        assert size > 0
        assert size < portfolio.total_value

    def test_kelly_zero_when_negative(self):
        sizer = PositionSizer(method="kelly", kelly_fraction=0.5)
        portfolio = Portfolio(cash=100000)
        signal = Signal(strategy_id="t", symbol="BTC/USDT", direction=Direction.LONG,
                        strength=0.8, price=42000, timestamp=0)
        size = sizer.size(signal, portfolio, win_rate=0.2, win_loss_ratio=0.5)
        assert size == 0.0

    def test_zero_equity(self):
        sizer = PositionSizer()
        portfolio = Portfolio(cash=0)
        signal = Signal(strategy_id="t", symbol="BTC/USDT", direction=Direction.LONG,
                        strength=0.8, price=42000, timestamp=0)
        assert sizer.size(signal, portfolio) == 0.0

    def test_strength_scaling(self):
        sizer = PositionSizer(method="kelly", kelly_fraction=0.5)
        portfolio = Portfolio(cash=100000)
        sig_strong = Signal(strategy_id="t", symbol="BTC/USDT", direction=Direction.LONG,
                            strength=1.0, price=42000, timestamp=0)
        sig_weak = Signal(strategy_id="t", symbol="ETH/USDT", direction=Direction.LONG,
                          strength=0.3, price=3000, timestamp=0)
        size_strong = sizer.size(sig_strong, portfolio, win_rate=0.55, win_loss_ratio=2.0)
        size_weak = sizer.size(sig_weak, portfolio, win_rate=0.55, win_loss_ratio=2.0)
        assert size_strong > size_weak
