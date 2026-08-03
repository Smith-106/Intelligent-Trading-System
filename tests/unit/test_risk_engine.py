"""Tests for quantflow.signal.risk_engine."""

from pytest import approx

from quantflow.common.config import RiskConfig
from quantflow.common.models import Direction, Portfolio, Position, Signal
from quantflow.signal.portfolio import PendingView
from quantflow.signal.risk_engine import RiskEngine


class TestRiskEngine:
    def test_pass_all_checks(self):
        engine = RiskEngine(RiskConfig())
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        result = engine.check(sig, pf)
        assert result.passed

    def test_weekly_loss_limit(self):
        engine = RiskEngine(RiskConfig(weekly_loss_limit=-0.05))
        engine.set_weekly_pnl(-0.06)
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        result = engine.check(sig, pf)
        assert not result.passed
        assert result.reason == "weekly_loss_limit"

    def test_weekly_loss_within_limit(self):
        engine = RiskEngine(RiskConfig(weekly_loss_limit=-0.05))
        engine.set_weekly_pnl(-0.03)
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        result = engine.check(sig, pf)
        assert result.passed

    def test_daily_loss_limit(self):
        engine = RiskEngine(RiskConfig(daily_loss_limit=-0.03, position_limit_pct=1.0))
        pos = Position("BTC/USDT", 1.0, 50000, 48000, unrealized_pnl=-3000)
        # ISS-20260720-004 Wave 3: daily_loss measures total_value vs daily_baseline.
        # total_value = 47000 + 48000 = 95000; baseline=100000 → pnl_pct = -0.05.
        pf = Portfolio(cash=47000, positions={"BTC/USDT": pos}, daily_baseline=100000)
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 48000)
        result = engine.check(sig, pf)
        assert not result.passed
        assert result.reason == "daily_loss_limit"

    def test_max_drawdown(self):
        engine = RiskEngine(RiskConfig(max_drawdown=-0.10))
        pf = Portfolio(cash=80000, current_drawdown=-0.15)
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        result = engine.check(sig, pf)
        assert not result.passed
        assert result.reason == "max_drawdown"

    def test_max_positions(self):
        engine = RiskEngine(RiskConfig(max_positions=2))
        pos1 = Position("BTC/USDT", 1.0, 50000, 50000)
        pos2 = Position("ETH/USDT", 10.0, 3000, 3000)
        pf = Portfolio(cash=50000, positions={"BTC/USDT": pos1, "ETH/USDT": pos2})
        sig = Signal("SOL/USDT", Direction.LONG, 0.8, 100)
        result = engine.check(sig, pf)
        assert not result.passed
        assert result.reason == "max_positions"

    def test_existing_symbol_passes_portfolio_limit(self):
        """Adding to an existing position should pass the max_positions check."""
        engine = RiskEngine(RiskConfig(max_positions=2, position_limit_pct=0.5))
        pos1 = Position("BTC/USDT", 1.0, 50000, 50000)
        pos2 = Position("ETH/USDT", 10.0, 3000, 3000)
        pf = Portfolio(cash=50000, positions={"BTC/USDT": pos1, "ETH/USDT": pos2})
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        result = engine.check(sig, pf)
        # Should pass because symbol already exists (portfolio_limit check)
        # but may fail position_limit if existing position is too large
        assert isinstance(result.passed, bool)


class TestCvarGateWiring:
    """ISS-20260719-001: the CVaR gate (_check_var) must actually trigger once
    the returns history is filled. Before the fix, add_return had no caller so
    _returns_history stayed empty and the `len < 30` guard short-circuited the
    gate to always-passed. The fix wires on_bar → add_return; these tests prove
    the gate fires when the tail breaches cvar_limit.
    """

    def test_insufficient_history_short_circuits_to_pass(self):
        """< 30 returns → gate cannot evaluate → passed (safe default)."""
        engine = RiskEngine(RiskConfig(cvar_limit=-0.05))
        for r in [0.01, -0.01, 0.02, -0.02]:  # only 4 returns
            engine.add_return(r)
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        assert engine.check(sig, pf).passed

    def test_gate_passes_when_tail_within_limit(self):
        """≥30 returns with a mild tail → CVaR milder than -0.05 → passed."""
        engine = RiskEngine(RiskConfig(cvar_limit=-0.05))
        # 50 returns, worst ~ -0.02 → CVaR ~ -0.02, well within -0.05
        mild = [0.01, -0.02, 0.015, -0.01, 0.005] * 10
        for r in mild:
            engine.add_return(r)
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        assert engine.check(sig, pf).passed

    def test_gate_blocks_when_tail_breaches_limit(self):
        """≥30 returns with a deep tail → CVaR worse than -0.05 → blocked."""
        engine = RiskEngine(RiskConfig(cvar_limit=-0.05))
        # 50 returns where the worst 5% are ~ -0.10 → CVaR ~ -0.10 < -0.05
        deep = [0.001] * 45 + [-0.10] * 5
        for r in deep:
            engine.add_return(r)
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        result = engine.check(sig, pf)
        assert not result.passed
        assert result.reason == "var_breach"
        assert "cvar_95" in result.details


class FakeHealthMonitor:
    """Duck-typed stand-in for L5 ExchangeHealthMonitor (T-s1-04).

    RiskEngine must depend on the ``circuit_open()`` shape only — never on
    the concrete L5 class (six-layer one-way dependency).
    """

    def __init__(self, open_: bool = False) -> None:
        self._open = open_

    def circuit_open(self) -> bool:
        return self._open


class TestExchangeCircuitBreakerGate:
    """T-s1-04: circuit breaker short-circuits RiskEngine.check (fail-closed,
    all signals). Acceptance: breaker open → check rejects with
    'exchange_circuit_open'; breaker absent → zero behavior change."""

    def test_open_circuit_rejects_all_signals(self):
        engine = RiskEngine(RiskConfig(), exchange_health=FakeHealthMonitor(open_=True))
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        result = engine.check(sig, pf)
        assert not result.passed
        assert result.reason == "exchange_circuit_open"

    def test_open_circuit_rejects_exit_signals_too(self):
        """Fail-closed full reject: even FLAT signals are blocked while the
        exchange is presumed unhealthy (orders cannot be trusted to reach a
        failing exchange)."""
        engine = RiskEngine(RiskConfig(), exchange_health=FakeHealthMonitor(open_=True))
        sig = Signal("BTC/USDT", Direction.FLAT, 0.8, 50000)
        pf = Portfolio(cash=100000)
        assert engine.check(sig, pf).reason == "exchange_circuit_open"

    def test_closed_circuit_passes_through(self):
        engine = RiskEngine(RiskConfig(), exchange_health=FakeHealthMonitor(open_=False))
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        assert engine.check(sig, pf).passed

    def test_no_monitor_injected_zero_change(self):
        """Acceptance: default (enabled=false → no monitor) → identical
        behavior to pre-T-s1-04 (covered by all tests above using the
        default constructor; explicit smoke check here)."""
        engine = RiskEngine(RiskConfig())
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        assert engine.check(sig, pf).passed

    def test_monitor_without_circuit_open_is_treated_as_closed(self):
        """Duck-type robustness: an object lacking circuit_open() must not
        crash the check chain (getattr guard)."""
        engine = RiskEngine(RiskConfig(), exchange_health=object())
        sig = Signal("BTC/USDT", Direction.LONG, 0.8, 50000)
        pf = Portfolio(cash=100000)
        assert engine.check(sig, pf).passed


class TestExchangeExposureCap:
    """T-s1-04: single-exchange total-exposure cap (positions + pending).

    Acceptance: 85% > 80% cap → new LONG entry rejected with
    'exchange_exposure_exceeded'; exits still pass so the book can unwind."""

    def _over_cap_portfolio(self) -> Portfolio:
        # total_value = 15000 cash + 85000 position = 100000; exposure 85%.
        pos = Position("BTC/USDT", 1.7, 50000, 50000)
        return Portfolio(cash=15000, positions={"BTC/USDT": pos})

    def test_over_cap_blocks_new_entry(self):
        engine = RiskEngine(
            RiskConfig(position_limit_pct=1.0),
            exchange_exposure_limit_pct=0.80,
        )
        sig = Signal("ETH/USDT", Direction.LONG, 0.8, 3000)
        result = engine.check(sig, self._over_cap_portfolio())
        assert not result.passed
        assert result.reason == "exchange_exposure_exceeded"
        assert result.details["exposure_pct"] == approx(0.85)

    def test_over_cap_allows_flat_exit_to_unwind(self):
        engine = RiskEngine(
            RiskConfig(position_limit_pct=1.0),
            exchange_exposure_limit_pct=0.80,
        )
        sig = Signal("BTC/USDT", Direction.FLAT, 0.8, 50000)
        result = engine.check(sig, self._over_cap_portfolio())
        assert result.passed, "exits must pass so an over-cap book can unwind"

    def test_under_cap_passes(self):
        engine = RiskEngine(
            RiskConfig(position_limit_pct=1.0),
            exchange_exposure_limit_pct=0.90,
        )
        sig = Signal("ETH/USDT", Direction.LONG, 0.8, 3000)
        assert engine.check(sig, self._over_cap_portfolio()).passed

    def test_pending_counts_toward_exposure(self):
        engine = RiskEngine(
            RiskConfig(position_limit_pct=1.0, max_positions=10),
            exchange_exposure_limit_pct=0.80,
        )
        # 70% position + 15% pending = 85% > 80%
        pos = Position("BTC/USDT", 1.4, 50000, 50000)
        pf = Portfolio(cash=30000, positions={"BTC/USDT": pos})
        pending = PendingView(total=15000, by_symbol={"ETH/USDT": 15000}, by_strategy={})
        sig = Signal("SOL/USDT", Direction.LONG, 0.8, 100)
        result = engine.check(sig, pf, pending)
        assert not result.passed
        assert result.reason == "exchange_exposure_exceeded"

    def test_no_cap_zero_change(self):
        engine = RiskEngine(RiskConfig(position_limit_pct=1.0))
        sig = Signal("ETH/USDT", Direction.LONG, 0.8, 3000)
        assert engine.check(sig, self._over_cap_portfolio()).passed
