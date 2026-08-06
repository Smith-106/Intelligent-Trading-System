"""Unit tests for SpotPerpPairSimulator (ISS-20260804-003 real-data pair sim).

Covers: symmetric direction P&L, funding income accrual only at settlement
bars while in position, both-leg fees at entry/exit, zero-signal degradation
(flat equity), and spread-drift contribution. Funding series use step
(asof) semantics — the value holds between settlements, mirroring the real
OKX 8h funding cadence — so the strategy's exit band only fires on an
actual funding reset.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.research.spot_perp_sim import SpotPerpPairSimulator


def _pair_df(
    n: int = 60,
    *,
    spot: np.ndarray | None = None,
    perp: np.ndarray | None = None,
    funding_steps: dict[int, float] | None = None,
    oi_drop_at: int | None = None,
) -> pd.DataFrame:
    """Hourly feature frame with step-function (asof) funding.

    ``funding_steps`` maps the FIRST index of each funding value; the value
    holds until the next step. Every step start is a settlement bar.
    OI gate: drop OI at ``oi_drop_at`` so the 3-bar OI change at
    ``oi_drop_at + 3`` exceeds the 5% confirmation threshold.
    """
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    base = 100.0 + np.linspace(0, 0.1, n)
    spot_v = spot if spot is not None else base
    perp_v = perp if perp is not None else base
    f = np.zeros(n, dtype=float)
    settle = set()
    for start, value in sorted((funding_steps or {}).items()):
        end = n if start >= n else start
        # Find the next step boundary.
        nexts = sorted(s for s in (funding_steps or {}) if s > start)
        end = nexts[0] if nexts else n
        f[start:end] = value
        settle.add(start)
    df = pd.DataFrame(
        {
            "spot_open": spot_v,
            "spot_close": spot_v,
            "perp_open": perp_v,
            "perp_close": perp_v,
            "funding_rate": f,
            "funding_settle": np.array([1 if i in settle else 0 for i in range(n)], dtype=int),
            "open_interest": 1000.0 + np.arange(n) * 10.0,
        },
        index=idx,
    )
    if oi_drop_at is not None:
        df.loc[df.index[oi_drop_at], "open_interest"] *= 0.90
    return df


def _entry_oi_drop() -> dict:
    """OI confirmation for an entry at bar 30 (drop 3 bars earlier)."""
    return {"oi_drop_at": 27}


class TestPairPnl:
    def test_funding_income_accrues_only_at_settlement_while_in_position(self) -> None:
        """Long perp (d=+1) with positive funding -> negative income."""
        df = _pair_df(
            funding_steps={0: 0.0, 30: -0.002, 34: 0.0008, 42: 0.0010, 45: 0.0},
            **_entry_oi_drop(),
        )
        res = SpotPerpPairSimulator(fee_per_leg=0.0).run(df)
        assert res.num_trades == 1
        # Position from bar 31; settlements at 34 and 42 accrue -d*f.
        assert res.funding_income == pytest.approx(-(0.0008 + 0.0010))

    def test_short_perp_receives_positive_funding(self) -> None:
        """Short perp (d=-1) with positive funding -> the harvest (income > 0)."""
        df = _pair_df(
            funding_steps={0: 0.0, 30: 0.002, 34: 0.0008, 42: 0.0010, 45: 0.0},
            **_entry_oi_drop(),
        )
        res = SpotPerpPairSimulator(fee_per_leg=0.0).run(df)
        assert res.num_trades == 1
        assert res.funding_income == pytest.approx(0.0008 + 0.0010)

    def test_no_funding_outside_position(self) -> None:
        """Settlements before entry accrue nothing."""
        df = _pair_df(
            funding_steps={0: 0.0009, 10: 0.0005, 30: -0.002, 34: 0.0008, 40: 0.0},
            **_entry_oi_drop(),
        )
        res = SpotPerpPairSimulator(fee_per_leg=0.0).run(df)
        # Only the bar-34 settlement (inside the position) accrues.
        assert res.funding_income == pytest.approx(-0.0008)

    def test_fees_applied_to_both_legs_at_entry_and_exit(self) -> None:
        """Flat prices -> realized trade return is exactly the round-trip fees."""
        df = _pair_df(
            funding_steps={0: 0.0, 30: -0.002, 40: 0.0},
            **_entry_oi_drop(),
        )
        res = SpotPerpPairSimulator(fee_per_leg=0.0005).run(df)
        assert res.num_trades == 1
        assert res.trade_returns == [pytest.approx(-0.002)]  # 2 legs x 2 sides x 5bp
        assert res.total_return == pytest.approx(-0.002, abs=1e-5)  # compounding

    def test_spread_drift_contributes_in_position(self) -> None:
        """Perp outperforms spot while long perp -> positive spread P&L."""
        spot = 100.0 + np.linspace(0, 0.5, 60)
        perp = 100.0 + np.linspace(0, 0.5, 60)
        perp[31:46] += 0.2
        df = _pair_df(
            spot=spot, perp=perp, funding_steps={0: 0.0, 30: -0.002, 45: 0.0}, **_entry_oi_drop()
        )
        res = SpotPerpPairSimulator(fee_per_leg=0.0).run(df)
        assert res.spread_pnl > 0

    def test_zero_signals_flat_equity(self) -> None:
        """No funding extreme / no OI confirmation -> no trades, flat equity."""
        df = _pair_df(funding_steps={0: 0.0})
        res = SpotPerpPairSimulator(fee_per_leg=0.0005).run(df)
        assert res.num_trades == 0
        assert res.total_return == pytest.approx(0.0)
        assert res.funding_income == pytest.approx(0.0)
        assert res.equity_curve.iloc[-1] == pytest.approx(res.initial_capital)

    def test_direction_symmetry_of_pair(self) -> None:
        """Flipping the entry direction flips the P&L sign (mirror symmetry)."""
        # df1: long perp with positive funding -> pays (income < 0).
        df1 = _pair_df(funding_steps={0: 0.0, 30: -0.002, 34: 0.0008, 45: 0.0}, **_entry_oi_drop())
        # df2: short perp with the SAME positive funding -> receives (income > 0).
        df2 = _pair_df(funding_steps={0: 0.0, 30: 0.002, 34: 0.0008, 45: 0.0}, **_entry_oi_drop())
        r1 = SpotPerpPairSimulator(fee_per_leg=0.0).run(df1)
        r2 = SpotPerpPairSimulator(fee_per_leg=0.0).run(df2)
        assert r1.funding_income == pytest.approx(-r2.funding_income)
        assert r1.total_return == pytest.approx(-r2.total_return)
