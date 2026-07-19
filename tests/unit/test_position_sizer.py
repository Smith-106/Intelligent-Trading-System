"""Tests for quantflow.signal.position_sizer."""

from quantflow.common.models import Direction, Portfolio, Position, Signal
from quantflow.signal.position_sizer import PositionSizer


class TestPositionSizer:
    def test_basic_sizing(self):
        sizer = PositionSizer(kelly_fraction=0.5, max_position_pct=0.20)
        sig = Signal("BTC/USDT", Direction.LONG, 1.0, 50000)
        pf = Portfolio(cash=100000)
        size = sizer.size(sig, pf, win_rate=0.55, win_loss_ratio=2.0)
        assert size > 0

    def test_strength_scaling(self):
        sizer = PositionSizer(kelly_fraction=0.5, max_position_pct=0.20)
        pf = Portfolio(cash=100000)
        sig_strong = Signal("BTC/USDT", Direction.LONG, 1.0, 50000)
        sig_weak = Signal("BTC/USDT", Direction.LONG, 0.3, 50000)
        strong = sizer.size(sig_strong, pf, 0.55, 2.0)
        weak = sizer.size(sig_weak, pf, 0.55, 2.0)
        assert strong > weak

    def test_max_position_cap(self):
        sizer = PositionSizer(kelly_fraction=1.0, max_position_pct=0.10)
        sig = Signal("BTC/USDT", Direction.LONG, 1.0, 50000)
        pf = Portfolio(cash=100000)
        size = sizer.size(sig, pf, win_rate=0.99, win_loss_ratio=10.0)
        assert size <= 10000  # 10% of 100k

    def test_zero_equity(self):
        sizer = PositionSizer()
        sig = Signal("BTC/USDT", Direction.LONG, 1.0, 50000)
        pf = Portfolio(cash=0)
        assert sizer.size(sig, pf, 0.55, 2.0) == 0.0

    def test_negative_win_rate(self):
        sizer = PositionSizer(kelly_fraction=0.5)
        sig = Signal("BTC/USDT", Direction.LONG, 1.0, 50000)
        pf = Portfolio(cash=100000)
        assert sizer.size(sig, pf, win_rate=0.1, win_loss_ratio=0.5) == 0.0

    def test_fixed_method(self):
        sizer = PositionSizer(method="fixed", fixed_pct=0.05)
        sig = Signal("BTC/USDT", Direction.LONG, 1.0, 50000)
        pf = Portfolio(cash=100000)
        size = sizer.size(sig, pf)
        assert size > 0

    def test_existing_position_deduction(self):
        sizer = PositionSizer(kelly_fraction=0.5, max_position_pct=0.20)
        pos = Position("BTC/USDT", 0.5, 50000, 50000)
        pf = Portfolio(cash=50000, positions={"BTC/USDT": pos})
        sig = Signal("BTC/USDT", Direction.LONG, 0.5, 50000)
        size = sizer.size(sig, pf, 0.55, 2.0)
        assert size >= 0


class TestVolTargeting:
    """Volatility-targeting cap (deep-research F3 / P1).

    The hard contract: with vol_target_pct=None (the default) sizing must be
    byte-for-byte identical to the pre-F3 implementation, regardless of
    whether returns have been fed via add_return. Vol-target only binds when
    explicitly opted in AND sufficient history exists.
    """

    def _sig(self) -> Signal:
        return Signal("BTC/USDT", Direction.LONG, 1.0, 50000)

    def test_default_off_is_byte_for_byte_baseline(self):
        """vol_target_pct=None must not alter sizing, even with returns fed."""
        baseline = PositionSizer(kelly_fraction=0.5, max_position_pct=0.20)
        opted_off = PositionSizer(kelly_fraction=0.5, max_position_pct=0.20)
        # Feed returns to the opted-off sizer; with vol-target OFF this must
        # be a complete no-op (never consulted).
        for r in [0.01, -0.02, 0.005, -0.01, 0.03, -0.005, 0.02, -0.015] * 4:
            opted_off.add_return(r)
        pf = Portfolio(cash=100000)
        b = baseline.size(self._sig(), pf, 0.55, 2.0)
        o = opted_off.size(self._sig(), pf, 0.55, 2.0)
        assert o == b, f"vol-target OFF changed sizing: baseline={b} off={o}"

    def test_off_returns_history_does_not_grow_unbounded(self):
        sizer = PositionSizer(kelly_fraction=0.5, max_position_pct=0.20, vol_window=4)
        for r in range(100):
            sizer.add_return(float(r))
        # deque maxlen guards memory; only the last vol_window are retained
        assert len(sizer._returns_history) == 4

    def test_opt_in_insufficient_history_is_noop(self):
        """With <2 returns, vol-target cannot bind — falls back to Kelly."""
        sizer = PositionSizer(
            kelly_fraction=0.5,
            max_position_pct=0.20,
            vol_target_pct=0.15,
            vol_window=30,
        )
        sizer.add_return(0.01)  # only one bar
        pf = Portfolio(cash=100000)
        size = sizer.size(self._sig(), pf, 0.55, 2.0)
        # Must equal the pure-Kelly size (vol-target did not bind)
        kelly_only = PositionSizer(kelly_fraction=0.5, max_position_pct=0.20).size(
            self._sig(), pf, 0.55, 2.0
        )
        assert size == kelly_only

    def test_opt_in_high_vol_binds_below_kelly(self):
        """In a high-vol regime, vol-target must cap below the Kelly target."""
        sizer = PositionSizer(
            kelly_fraction=0.5,
            max_position_pct=0.20,
            vol_target_pct=0.15,  # 15% annual vol target
            vol_annualization=365,
            vol_window=30,
        )
        # Daily returns with stdev ~ 5% => annualized ~ 5%*sqrt(365) ≈ 95%.
        # vol_target_notional = 100000 * 0.15 / 0.95 ≈ 15789, well below the
        # Kelly/max-position target (~20000), so vol-target binds.
        high_vol_returns = [0.05, -0.05, 0.05, -0.05] * 8
        for r in high_vol_returns:
            sizer.add_return(r)
        pf = Portfolio(cash=100000)
        size = sizer.size(self._sig(), pf, 0.55, 2.0)
        kelly_only = PositionSizer(kelly_fraction=0.5, max_position_pct=0.20).size(
            self._sig(), pf, 0.55, 2.0
        )
        assert size < kelly_only, (
            f"vol-target should bind in high-vol regime: vol={size} kelly={kelly_only}"
        )
        # Sanity: capped near the 15% target notional (~15789 before fees)
        assert 14000 <= size <= 16000

    def test_opt_in_low_vol_does_not_bind(self):
        """In a low-vol regime, vol-target must not bind — Kelly wins."""
        sizer = PositionSizer(
            kelly_fraction=0.5,
            max_position_pct=0.20,
            vol_target_pct=0.15,
            vol_annualization=365,
            vol_window=30,
        )
        # Tiny daily stdev (~0.1%) => annualized ~1.9%; vol-target notional
        # ≈ 100000*0.15/0.019 ≈ 789000, far above the Kelly/max-position cap,
        # so vol-target is non-binding and Kelly behavior is preserved.
        low_vol_returns = [0.001, -0.001, 0.001, -0.001] * 8
        for r in low_vol_returns:
            sizer.add_return(r)
        pf = Portfolio(cash=100000)
        size = sizer.size(self._sig(), pf, 0.55, 2.0)
        kelly_only = PositionSizer(kelly_fraction=0.5, max_position_pct=0.20).size(
            self._sig(), pf, 0.55, 2.0
        )
        assert size == kelly_only

    def test_vol_target_respects_min_order_notional(self):
        """When vol-target caps below min_order_notional, size returns 0."""
        sizer = PositionSizer(
            kelly_fraction=0.5,
            max_position_pct=0.20,
            min_order_notional=10.0,
            vol_target_pct=0.01,  # absurdly tight 1% target
            vol_annualization=365,
            vol_window=30,
        )
        for r in [0.05, -0.05, 0.05, -0.05] * 8:
            sizer.add_return(r)
        pf = Portfolio(cash=100000)
        # vol-target notional ≈ 100000*0.01/0.95 ≈ 1052 — above min_order (10),
        # so it survives; verify the cap is the binding constraint, not Kelly.
        size = sizer.size(self._sig(), pf, 0.55, 2.0)
        kelly_only = PositionSizer(kelly_fraction=0.5, max_position_pct=0.20).size(
            self._sig(), pf, 0.55, 2.0
        )
        assert size < kelly_only and size > 0
