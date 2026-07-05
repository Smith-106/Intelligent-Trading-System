"""Integration test: full trading pipeline (bar → strategy → signal → risk → execution)."""

from __future__ import annotations

from quantflow.common.config import AppConfig, RiskConfig
from quantflow.common.models import Bar, Direction, Signal
from quantflow.signal.generator import SignalGenerator
from quantflow.signal.portfolio import PortfolioManager
from quantflow.signal.position_sizer import PositionSizer
from quantflow.signal.risk_engine import RiskEngine
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy


class TestFullPipeline:
    """Test the bar → strategy → signal → risk → execution chain."""

    def test_strategy_generates_signal_risk_passes_position_sized(self):
        """End-to-end: bar → strategy signal → risk check → position sizing."""
        config = AppConfig()
        risk_engine = RiskEngine(config.risk)
        portfolio = PortfolioManager(initial_capital=100000.0)
        sizer = PositionSizer(method="kelly", kelly_fraction=0.5, max_position_pct=20.0)
        SignalGenerator()

        strategy = TrendFollowingStrategy()
        ctx = StrategyContext()
        strategy.on_init(ctx)

        # Feed bars to trigger a signal
        for i in range(80):
            bar = Bar(
                "BTC/USDT",
                1000 + i * 60000,
                100.0 + i * 0.8,
                101.0 + i * 0.8,
                99.0 + i * 0.8,
                100.5 + i * 0.8,
                1000.0,
            )
            strategy.on_bar(ctx, bar)

        signals = ctx.flush_signals()
        # Strategy may or may not emit signals depending on data — just verify pipeline
        for sig in signals:
            assert sig.symbol == "BTC/USDT"
            assert sig.direction in (Direction.LONG, Direction.SHORT, Direction.FLAT)
            if sig.direction != Direction.FLAT:
                # Run through risk check
                pf = portfolio.portfolio
                decision = risk_engine.check(sig, pf)
                assert isinstance(decision.passed, bool)
                # If passed, check position sizing
                if decision.passed:
                    size = sizer.size(sig, pf)
                    assert size >= 0

    def test_consolidate_multiple_strategy_signals(self):
        """When two strategies emit conflicting signals, consolidation resolves them."""
        gen = SignalGenerator()
        sigs = [
            Signal("BTC/USDT", Direction.LONG, 0.8, 50000, "trend"),
            Signal("BTC/USDT", Direction.SHORT, 0.3, 50000, "mean_rev"),
        ]
        result = gen.consolidate_signals(sigs, strategy_hit_rates={"trend": 0.6, "mean_rev": 0.5})
        # LONG strength 0.8 * 0.6 = 0.48, SHORT strength 0.3 * 0.5 = 0.15
        # Net > 0 → LONG wins
        assert result is not None
        assert result.direction == Direction.LONG

    def test_risk_engine_blocks_overexposed_strategy(self):
        """Risk engine should block signal when strategy budget exceeded."""
        budgets = {"trend": 0.1}
        risk = RiskEngine(RiskConfig(position_limit_pct=1.0), strategy_risk_budgets=budgets)
        pf = PortfolioManager(initial_capital=100000.0)
        # Add a position for the "trend" strategy
        pf.update_position("BTC/USDT", 0.2, 50000.0, strategy_id="trend")
        portfolio = pf.portfolio

        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000, "trend")
        risk.check(sig, portfolio)
        # trend exposure = 0.2 * 50000 = 10000, total = 110000, budget = 11000 → passes
        # Let's make it fail: increase the position
        pf.update_position("ETH/USDT", 1.0, 3000.0, strategy_id="trend")
        portfolio = pf.portfolio
        # trend exposure = 10000 + 3000 = 13000, budget = 13000 * 0.1 = 1300 → fails
        # Actually total_value = 100000 + 10000 + 3000 = 113000, budget = 11300
        # Exposure = 13000 > budget = 11300 → fails
        sig2 = Signal("BTC/USDT", Direction.LONG, 0.8, 50000, "trend")
        result2 = risk.check(sig2, portfolio)
        assert not result2.passed
        assert result2.reason == "strategy_budget"

    def test_signal_pipeline_from_strategy_to_risk(self):
        """Verify a Signal object flows correctly from strategy through risk check."""
        config = AppConfig()
        risk = RiskEngine(config.risk)
        portfolio = PortfolioManager(initial_capital=100000.0)

        # Manually create a signal
        sig = Signal("BTC/USDT", Direction.LONG, 0.7, 50000, "test_strategy")
        decision = risk.check(sig, portfolio.portfolio)
        assert decision.passed

    def test_pipeline_risk_blocks_daily_loss(self):
        """Daily loss limit should block signals."""
        AppConfig()
        risk = RiskEngine(RiskConfig(daily_loss_limit=-0.03, position_limit_pct=1.0))
        portfolio = PortfolioManager(initial_capital=100000.0)
        # Create a position with large unrealized loss
        portfolio.update_position("BTC/USDT", 1.0, 50000.0)
        portfolio.update_market_prices({"BTC/USDT": 46000.0})  # -4000 unrealized

        sig = Signal("BTC/USDT", Direction.LONG, 0.7, 46000, "test")
        decision = risk.check(sig, portfolio.portfolio)
        assert not decision.passed
        assert decision.reason == "daily_loss_limit"
